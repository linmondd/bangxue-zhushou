"""bangxue MCP 服务：把刷课能力暴露给支持 MCP 的 Agent（Workbuddy / Codex / Claude Code 等）。

启动：
  python -m bangxue.mcp_server
或（安装后）：
  bangxue-mcp

客户端配置示例（stdio）：
  {"mcpServers": {"bangxue": {"command": "python", "args": ["-m", "bangxue.mcp_server"]}}}
"""
import os
import threading

try:
    from mcp.server.fastmcp import FastMCP
except Exception as e:  # 未安装 mcp
    raise SystemExit("未安装 mcp：pip install mcp") from e

from . import flow, monitor, state as stmod
from .drivers import get_driver

DEFAULT_STATE = os.environ.get("BANGXUE_STATE", "bangxue_state.json")

ZOOM = int(os.environ.get("BANGXUE_ZOOM", "100"))

mcp = FastMCP("bangxue")


@mcp.tool()
def bangxue_capture(workshop: str, state: str = DEFAULT_STATE, concurrency: int = 5) -> str:
    """提取专题班课程表并生成状态文件。workshop 传专题班链接或 workshopId。"""
    d = get_driver("auto", zoom=ZOOM)
    wid = workshop
    import re
    m = re.search(r"([a-f0-9]{8}-[a-f0-9-]{27,})", workshop)
    if m:
        wid = m.group(1)
    res = flow.capture(d, wid)
    if res is None:
        return "失败：未进入专题班课程表页"
    st = stmod.init_state(wid, res["courses"], concurrency)
    stmod.save(state, st)
    return f"课表已保存 {state}（{len(res['courses'])} 门）"


@mcp.tool()
def bangxue_status(state: str = DEFAULT_STATE, live: bool = False) -> str:
    """查看进度：完成/在播/待关/未映射。live=true 时实时读取在播状态。"""
    st = stmod.load(state)
    done = len(st.get("done", []))
    active = st.get("active", [])
    total = len([c for c in st["courses"] if c.get("cid")])
    unmapped = len([c for c in st["courses"] if not c.get("cid")])
    lines = [f"完成 {done}/{total}，在播 {len(active)}，待关 {len(st.get('done_open', []))}，未映射 {unmapped}"]
    if live and active:
        d = get_driver("auto", zoom=ZOOM)
        for cid in active:
            s = flow.check(d, cid, st["workshop"])
            info = next((c for c in st["courses"] if c.get("cid") == cid), {})
            lines.append(f"{info.get('title','?')[:24]} {s.get('prog','?')} {s.get('ct')}/{s.get('dur')} paused={s.get('paused')}")
    return "\n".join(lines)


@mcp.tool()
def bangxue_start(state: str = DEFAULT_STATE, concurrency: int = 5) -> str:
    """从队列起播最多 concurrency 门课（需已运行 capture 生成状态文件）。"""
    d = get_driver("auto", zoom=ZOOM)
    st = stmod.load(state)
    done = set(st.get("done", []))
    active = set(st.get("active", []))
    pending = [c for c in st["courses"] if c.get("cid") and c["cid"] not in done and c["cid"] not in active]
    started = []
    for c in pending[:concurrency]:
        r = flow.start(d, c["cid"], st["workshop"])
        if r.get("ok"):
            started.append(c["cid"])
        import time
        time.sleep(2)
    st["active"] = list(active | set(started))
    stmod.save(state, st)
    return f"本次起播 {len(started)} 门"


@mcp.tool()
def bangxue_monitor(state: str = DEFAULT_STATE) -> str:
    """跑一轮巡检：核进度、关已完成、补新课、恢复暂停。"""
    d = get_driver("auto", zoom=ZOOM)
    buf = []
    monitor.run_one(d, state, log=buf.append)
    return "\n".join(buf) if buf else "本轮无输出"


@mcp.tool()
def bangxue_run(scope: str = "bangxue_scope.json", state_dir: str = "bangxue_classes", concurrency: int = 5) -> str:
    """按班级范围自动续班：刷完一个班自动找下一个（未报名先报名），直到范围内全部完成。"""
    from . import runner
    d = get_driver("auto", zoom=ZOOM)
    buf = []
    runner.run_cycle(d, scope, state_dir, concurrency, log=buf.append)
    return "\n".join(buf) if buf else "本轮无输出"


@mcp.tool()
def bangxue_monitor_loop(state: str = DEFAULT_STATE, interval_min: int = 15) -> str:
    """后台常驻巡检（每 interval_min 分钟一轮）。调用后立即返回，适合交给常驻进程。"""
    def _loop():
        d = get_driver("auto", zoom=ZOOM)
        while True:
            monitor.run_one(d, state)
            import time
            time.sleep(interval_min * 60)
    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    return f"已在后台启动巡检，每 {interval_min} 分钟一轮"


def main():
    mcp.run()


if __name__ == "__main__":
    main()
