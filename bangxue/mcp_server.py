"""Local MCP stdio server. Browser operations share one owning thread."""
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:
    raise SystemExit("请使用安装程序的 MCP 选项，或在 Python 3.10+ 环境安装 bangxue[mcp,playwright]") from exc

from . import cli, control, flow, monitor, runner, state as stmod
from .drivers import get_driver

DEFAULT_STATE = os.environ.get("BANGXUE_STATE", "bangxue_state.json")
ZOOM = int(os.environ.get("BANGXUE_ZOOM", "100"))
mcp = FastMCP("bangxue")
_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bangxue-browser")
_driver = None
_watch_lock = threading.Lock()
_watches = {}


def _browser():
    global _driver
    if _driver is None:
        _driver = get_driver(os.environ.get("BANGXUE_DRIVER", "auto"), zoom=ZOOM,
                             profile_dir=os.path.expanduser(os.environ.get("BANGXUE_PROFILE", "~/.bangxue/profile")))
    return _driver


def _call(fn, *args):
    def run():
        lines = []
        try:
            result = fn(_browser(), *args, log=lines.append)
        except Exception as exc:
            result, detail = "attention", str(exc)
            lines.append(detail)
        return result, "\n".join(str(line) for line in lines) or str(result or "已执行")
    return _worker.submit(run).result()


def _watch(key, fn, args, interval_min):
    if interval_min < 1:
        raise ValueError("巡检间隔须大于零")
    with _watch_lock:
        if key in _watches:
            return "该任务已在持续巡检"
        event = threading.Event()
        _watches[key] = event

    def loop():
        try:
            while not event.is_set():
                state, report = _call(fn, *args)
                print(report, file=sys.stderr, flush=True)
                if state not in ("running", "busy") or event.wait(interval_min * 60):
                    break
        except Exception as exc:
            print(f"巡检已中止：{exc}", file=sys.stderr, flush=True)
        finally:
            with _watch_lock:
                _watches.pop(key, None)

    threading.Thread(target=loop, name="bangxue-monitor", daemon=True).start()
    return "已启动持续巡检。当前 MCP 服务退出后可用相同状态目录恢复任务"


@mcp.tool()
def bangxue_capture(workshop: str, state: str = DEFAULT_STATE, concurrency: int = 5) -> str:
    """读取专题班完整课表。"""
    import re
    match = re.search(r"[a-fA-F0-9]{8}-(?:[a-fA-F0-9]{4}-){3}[a-fA-F0-9]{12}", workshop)
    if not match or concurrency < 1:
        raise ValueError("请提供正确的专题班链接或 ID，以及正整数并发门数")
    return _call(cli.capture_state, match.group(), state, concurrency)[1]


@mcp.tool()
def bangxue_status(state: str = DEFAULT_STATE, live: bool = False) -> str:
    """读取单班进度，可选核验当前在播课程。"""
    st = stmod.load(state)
    lines = [f"课表共 {len(st['courses'])} 门，已确认 {len(set(st.get('done', [])))} 门，"
             f"在播 {len(st.get('active', []))} 门，未映射 {sum(not c.get('cid') for c in st['courses'])} 门"]
    if st.get("paused_reason") or st.get("attention_reason"):
        lines.append(str(st.get("paused_reason") or st.get("attention_reason")))
    if live:
        def inspect():
            for cid in st.get("active", []):
                info = flow.check(_browser(), cid, st["workshop"])
                yield_text = info.get("prog") or info.get("reason") or info.get("stage") or "待确认"
                lines.append(f"{cid} · {yield_text}")
        _worker.submit(inspect).result()
    return "\n".join(lines)


@mcp.tool()
def bangxue_start(state: str = DEFAULT_STATE, concurrency: int = 5) -> str:
    """按总并发上限逐门确认起播，遇阻即停止补课。"""
    if concurrency < 1:
        raise ValueError("并发门数须大于零")
    return _call(monitor.start_one, state, concurrency)[1]


@mcp.tool()
def bangxue_monitor(state: str = DEFAULT_STATE) -> str:
    """运行一次单班巡检。"""
    return _call(monitor.run_one, state)[1]


@mcp.tool()
def bangxue_run(scope: str = "bangxue_scope.json", state_dir: str = "bangxue_classes",
                concurrency: int = 5, continuous: bool = False, interval_min: int = 1) -> str:
    """按范围巡检一轮。continuous=true 时持续运行到完成、暂停或需要处理。"""
    if concurrency < 1:
        raise ValueError("并发门数须大于零")
    args = (scope, state_dir, concurrency)
    if continuous:
        return _watch(str(Path(state_dir).resolve()), runner.run_cycle, args, interval_min)
    return _call(runner.run_cycle, *args)[1]


@mcp.tool()
def bangxue_monitor_loop(state: str = DEFAULT_STATE, interval_min: int = 1) -> str:
    """持续巡检单班至结束，可通过 bangxue_stop 暂停。"""
    return _watch(str(Path(state).resolve()), monitor.run_one, (state,), interval_min)


@mcp.tool()
def bangxue_stop(scope: str = "", state_dir: str = "bangxue_classes", state: str = "") -> str:
    """暂停指定范围或单班。"""
    if not (scope or state):
        raise ValueError("请选择范围或单班状态文件")
    key = str(Path(state_dir if scope else state).resolve())
    with _watch_lock:
        event = _watches.get(key)
        if event:
            event.set()
    # Signal before queuing a browser operation behind an in-flight cycle.
    marker = os.path.join(state_dir, "_scope_state.json") if scope else state
    stmod.request_pause(marker)
    return _call(control.stop, scope or None, state_dir, state or None)[1]


@mcp.tool()
def bangxue_resume(scope: str = "", state_dir: str = "bangxue_classes", state: str = "") -> str:
    """解除暂停，之后可继续原来的巡检。"""
    if not (scope or state):
        raise ValueError("请选择范围或单班状态文件")
    lines = []
    control.resume(scope or None, state_dir, state or None, log=lines.append)
    return "\n".join(lines)


def main():
    try:
        mcp.run()
    finally:
        with _watch_lock:
            for event in _watches.values():
                event.set()
        def shutdown():
            if _driver and hasattr(_driver, "shutdown"):
                _driver.shutdown()
        _worker.submit(shutdown).result()
        _worker.shutdown()


if __name__ == "__main__":
    main()
