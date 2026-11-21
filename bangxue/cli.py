"""bangxue 命令行入口。"""
import argparse, json, os, re, sys, time

from . import flow, monitor, runner, state as stmod
from .drivers import get_driver


def _wid(s):
    m = re.search(r"(?:id=)?([a-f0-9]{8}-[a-f0-9-]{27,})", s)
    if not m:
        sys.exit(f"无法从输入解析 workshopId: {s}")
    return m.group(1)


def _watchdog(seconds):
    """整轮硬超时：卡在某个标签时强制退出，释放进程锁，下一轮可接管。"""
    if not seconds or seconds <= 0:
        return

    def _kill():
        time.sleep(seconds)
        print(f"⏱ 本轮超过 {seconds} 秒，强制结束；下轮巡检会接管已开页面", flush=True)
        os._exit(3)

    import threading
    threading.Thread(target=_kill, daemon=True).start()


def _open_state(path):
    try:
        return stmod.load(path)
    except FileNotFoundError:
        sys.exit(f"状态文件不存在: {path}（先运行 bangxue capture）")


def cmd_capture(args):
    d = get_driver(args.driver, zoom=args.zoom, profile_dir=args.profile)
    wid = _wid(args.workshop)
    res = flow.capture(d, wid)
    if res is None:
        sys.exit(1)
    st = stmod.init_state(wid, res["courses"], args.concurrency)
    stmod.save(args.state, st)
    print(f"课表已保存: {args.state}（{len(res['courses'])} 门）")


def cmd_start(args):
    d = get_driver(args.driver, zoom=args.zoom, profile_dir=args.profile)
    st = _open_state(args.state)
    _watchdog(args.max_seconds)
    started, failed = flow.start_pending(d, st, args.concurrency)
    stmod.save(args.state, st)
    print(f"本次确认在播 {len(started)} 门（含已在播，总上限 {args.concurrency}）")


def cmd_login(args):
    from .drivers.playwright_driver import PlaywrightDriver
    d = PlaywrightDriver(profile_dir=args.profile, headless=False)
    if not d.available():
        sys.exit("未安装 playwright：pip install playwright && python -m playwright install chromium")
    d.open("https://learning-platform.local/portal/", new_tab=False)
    print(f"已打开在线学习平台，请在弹出的浏览器里登录。最多等待 {args.timeout} 秒…")
    for _ in range(max(1, args.timeout // 3)):
        time.sleep(3)
        try:
            txt = d.eval("document.body?document.body.innerText:''") or ""
        except Exception:
            txt = ""
        if isinstance(txt, str) and ("退出登录" in txt or "我的专题班" in txt):
            print(f"✅ 登录成功，登录态已保存到 {args.profile}")
            return
    print("⚠ 未检测到登录成功；可重试 bangxue login")


def cmd_doctor(args):
    import bangxue as _pkg
    from .drivers import WebBridgeDriver, PlaywrightDriver
    print(f"帮学助手 {_pkg.__version__}")
    print(f"Python: {sys.version.split()[0]}")
    print(f"登录配置目录: {args.profile} " + ("存在" if os.path.isdir(args.profile) else "不存在（先运行 bangxue login）"))
    print(f"WebBridge 可用: {WebBridgeDriver(session='帮学助手').available()}")
    print(f"Playwright 可用: {PlaywrightDriver(profile_dir=args.profile).available()}")
    print("建议: WebBridge 或 Playwright 至少一个可用；两个都不可用时请重装依赖。")


def _read(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write(path, obj):
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def cmd_stop(args):
    d = get_driver(args.driver, zoom=args.zoom, profile_dir=args.profile)
    if args.scope:
        pp = os.path.join(args.state_dir, "_scope_state.json")
        prog = _read(pp, {"done": [], "skipped": {}, "current": None})
        prog["paused_reason"] = "user"
        _write(pp, prog)
    if args.state:
        st = _read(args.state, None)
        if st:
            st["paused_reason"] = "user"
            _write(args.state, st)
    print("正在关闭所有标签…")
    d.close_all()
    print("✅ 已停止。再次运行前请先执行：bangxue resume ...")


def cmd_resume(args):
    if args.scope:
        pp = os.path.join(args.state_dir, "_scope_state.json")
        prog = _read(pp, None)
        if prog:
            prog.pop("paused_reason", None)
            _write(pp, prog)
            print("范围已解除暂停")
    if args.state:
        st = _read(args.state, None)
        if st:
            st.pop("paused_reason", None)
            _write(args.state, st)
            print("班级已解除暂停")
    print("✅ 已恢复，下次 bangxue run 继续。")


def cmd_scope(args):
    d = get_driver(args.driver, zoom=args.zoom, profile_dir=args.profile)
    classes = flow.read_library_classes(d, args.tab)
    if not classes:
        sys.exit("未读到班级列表（请确认已登录、资源库页面可访问）")
    data = {"name": args.tab or "党的创新理论教育和党性教育资源库",
            "classes": classes, "created_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    _write(args.out, data)
    print(f"✅ 已生成范围文件 {args.out}，共 {len(classes)} 个班")
    for i, c in enumerate(classes, 1):
        print(f"  {i}. {c['title'][:40]}")


def cmd_run(args):
    d = get_driver(args.driver, zoom=args.zoom, profile_dir=args.profile)
    if args.loop:
        runner.run_loop(d, args.scope, args.state_dir, args.concurrency, args.interval)
    else:
        _watchdog(args.max_seconds)
        runner.run_cycle(d, args.scope, args.state_dir, args.concurrency)


def cmd_status(args):
    if args.state_dir:
        prog = _read(os.path.join(args.state_dir, "_scope_state.json"), {})
        titles = {}
        scope = _read(args.scope, {}) if args.scope else {}
        for c in scope.get("classes", []):
            titles[c.get("wid")] = c.get("title", "")
        print(f"范围: {scope.get('name', '-')}")
        cur = prog.get("current")
        print(f"当前班: {titles.get(cur, cur or '-')}")
        manual = prog.get("manual", {})
        print(f"已完成班: {len(prog.get('done', []))}   需人工补完: {len(manual)}   暂停: {prog.get('paused_reason', '无')}")
        print("各班级进度:")
        for fn in sorted(os.listdir(args.state_dir)):
            if not fn.endswith(".json") or fn.startswith("_"):
                continue
            wid = fn[:-5]
            st = _read(os.path.join(args.state_dir, fn), None)
            if not st:
                continue
            done_set = set(st.get("done", []))
            valid = {c["cid"] for c in st.get("courses", []) if c.get("cid")}
            done = len(done_set & valid)
            total = len(valid)
            act = len(st.get("active", []))
            pr = st.get("paused_reason", "")
            tail = f"  ⏸{pr}" if pr else ""
            if wid in manual:
                tail += f"  （剩{manual[wid]}门需人工）"
            print(f"  {titles.get(wid, wid)[:30]:<32} {done}/{total}  在播{act}" + tail)
        return
    st = _open_state(args.state)
    done = len(st.get("done", []))
    active = st.get("active", [])
    total = len([c for c in st["courses"] if c.get("cid")])
    unmapped = len([c for c in st["courses"] if not c.get("cid")])
    print(f"班级: {st['workshop']}")
    print(f"完成: {done}/{total}  在播: {len(active)}  待关: {len(st.get('done_open', []))}  未映射: {unmapped}")
    if args.live and active:
        d = get_driver(args.driver, zoom=args.zoom, profile_dir=args.profile)
        for cid in active:
            s = flow.check(d, cid, st["workshop"])
            info = next((c for c in st["courses"] if c.get("cid") == cid), {})
            print(f"  {info.get('title','?')[:24]} {s.get('prog','?')} {s.get('ct')}/{s.get('dur')} paused={s.get('paused')}")


def cmd_monitor(args):
    d = get_driver(args.driver, zoom=args.zoom, profile_dir=args.profile)
    if args.loop:
        while True:
            monitor.run_one(d, args.state)
            time.sleep(args.interval * 60)
    else:
        _watchdog(args.max_seconds)
        monitor.run_one(d, args.state)


def cmd_watch(args):
    """常驻看门狗：每 N 秒巡检所有有在播页的班，只动工具自己记录的标签。"""
    d = get_driver(args.driver, zoom=args.zoom, profile_dir=args.profile)
    print(f"看门狗启动：每 {args.interval} 秒巡检 {args.state_dir}（只动工具记录的标签）")
    while True:
        for fn in sorted(os.listdir(args.state_dir)):
            if not fn.endswith(".json") or fn.startswith("_"):
                continue
            p = os.path.join(args.state_dir, fn)
            try:
                st = stmod.load(p)
            except Exception:
                continue
            if not st.get("active"):
                continue
            try:
                monitor.run_one(d, p, log=print)
            except Exception as e:
                print(f"看门狗巡检失败 {fn[:8]}：{e}")
        time.sleep(args.interval)


def build_parser():
    p = argparse.ArgumentParser(prog="bangxue", description="帮学助手 CLI")
    p.add_argument("--driver", default="auto", choices=["auto", "webbridge", "playwright"],
                   help="浏览器驱动（默认自动）")
    p.add_argument("--zoom", type=int, default=100,
                   help="页面缩放百分比（100=不缩放；80/66/60 可让控件更紧凑，等效浏览器比例缩小）")
    p.add_argument("--profile", default=os.path.expanduser("~/.bangxue/profile"),
                   help="Playwright 持久化登录目录（默认 ~/.bangxue/profile）")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("capture", help="从专题班提取课表并生成状态文件")
    c.add_argument("--workshop", required=True, help="专题班链接或 workshopId")
    c.add_argument("--state", default="bangxue_state.json")
    c.add_argument("--concurrency", type=int, default=5)
    c.set_defaults(fn=cmd_capture)

    s = sub.add_parser("start", help="起播指定数量课程")
    s.add_argument("--state", default="bangxue_state.json")
    s.add_argument("--concurrency", type=int, default=5)
    s.add_argument("--max-seconds", type=int, default=600, help="单轮硬超时秒数（0=不限）")
    s.set_defaults(fn=cmd_start)

    t = sub.add_parser("status", help="查看进度（单班或按范围汇总）")
    t.add_argument("--state", default="bangxue_state.json")
    t.add_argument("--state-dir", default=None, help="传目录则汇总所有班级进度")
    t.add_argument("--scope", default=None, help="范围文件（用于显示班名）")
    t.add_argument("--live", action="store_true", help="实时读取在播状态")
    t.set_defaults(fn=cmd_status)

    scp = sub.add_parser("scope", help="从资源库自动生成范围文件")
    scp.add_argument("--tab", default="党的创新理论教育和党性教育资源库", help="资源库里的 tab 名")
    scp.add_argument("--out", default="bangxue_scope.json")
    scp.set_defaults(fn=cmd_scope)

    stp = sub.add_parser("stop", help="暂停并关闭所有标签")
    stp.add_argument("--scope", default=None)
    stp.add_argument("--state", default=None)
    stp.add_argument("--state-dir", default="bangxue_classes")
    stp.set_defaults(fn=cmd_stop)

    rsm = sub.add_parser("resume", help="解除暂停")
    rsm.add_argument("--scope", default=None)
    rsm.add_argument("--state", default=None)
    rsm.add_argument("--state-dir", default="bangxue_classes")
    rsm.set_defaults(fn=cmd_resume)

    lg = sub.add_parser("login", help="首次登录：打开浏览器登录在线学习平台并保存登录态")
    lg.add_argument("--timeout", type=int, default=300)
    lg.set_defaults(fn=cmd_login)

    dc = sub.add_parser("doctor", help="环境自检：Python/驱动/登录状态")
    dc.set_defaults(fn=cmd_doctor)

    r = sub.add_parser("run", help="按班级范围自动续班（刷完一个自动找下一个）")
    r.add_argument("--scope", default="bangxue_scope.json", help="范围文件（班级列表）")
    r.add_argument("--state-dir", default="bangxue_classes", help="各班状态文件目录")
    r.add_argument("--concurrency", type=int, default=5)
    r.add_argument("--loop", action="store_true")
    r.add_argument("--interval", type=int, default=15, help="循环间隔分钟")
    r.add_argument("--max-seconds", type=int, default=1200, help="单轮硬超时秒数（0=不限）")
    r.set_defaults(fn=cmd_run)

    m = sub.add_parser("monitor", help="跑一轮巡检（可 --loop）")
    m.add_argument("--state", default="bangxue_state.json")
    m.add_argument("--loop", action="store_true")
    m.add_argument("--interval", type=int, default=15, help="循环间隔分钟")
    m.add_argument("--max-seconds", type=int, default=900, help="单轮硬超时秒数（0=不限）")
    m.set_defaults(fn=cmd_monitor)

    w = sub.add_parser("watch", help="常驻看门狗：每 N 秒巡检所有在播班")
    w.add_argument("--state-dir", default="bangxue_classes")
    w.add_argument("--interval", type=int, default=60, help="巡检间隔秒数")
    w.set_defaults(fn=cmd_watch)
    return p


def main(argv=None):
    p = build_parser()
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
