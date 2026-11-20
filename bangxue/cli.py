"""bangxue 命令行入口。"""
import argparse, os, re, sys, time
from pathlib import Path

from . import environment, flow, monitor, runner, state as stmod
from .drivers import get_driver


def _wid(s):
    m = re.search(r"(?:id=)?([a-f0-9]{8}-[a-f0-9-]{27,})", s)
    if not m:
        sys.exit(f"无法从输入解析 workshopId: {s}")
    return m.group(1)


def _open_state(path):
    try:
        return stmod.load(path)
    except FileNotFoundError:
        sys.exit(f"状态文件不存在: {path}（先运行 bangxue capture）")


def cmd_capture(args):
    d = get_driver(args.driver, zoom=args.zoom, profile_dir=args.profile)
    wid = _wid(args.workshop)
    capture_state(d, wid, args.state, args.concurrency)


def capture_state(driver, wid, path, concurrency, log=print):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    lock = stmod.acquire_lock(str(path))
    if lock is None:
        raise RuntimeError("状态文件正在使用，请稍后重试")
    try:
        if os.path.exists(path):
            old = stmod.load(path)
            if old.get("active") or old.get("owned_tabs") or old.get("paused_reason"):
                raise RuntimeError("已有任务仍在使用这个状态文件。请继续原任务或选择新的状态文件")
        res = flow.capture(driver, wid, log=log)
        if not res or not res.get("courses"):
            raise RuntimeError("没有读到可核对的课程表")
        st = stmod.init_state(wid, res["courses"], concurrency)
        stmod.save(path, st)
        log(f"课表已保存到 {path}，共 {len(res['courses'])} 门")
    finally:
        lock.close()


def cmd_start(args):
    d = get_driver(args.driver, zoom=args.zoom, profile_dir=args.profile)
    return monitor.start_one(d, args.state, args.concurrency)


def cmd_login(args):
    from .drivers.playwright_driver import PlaywrightDriver
    d = PlaywrightDriver(profile_dir=args.profile, headless=False)
    if not d.available():
        sys.exit("浏览器组件尚未就绪，请打开控制面板修复或重新运行安装程序")
    try:
        d.open("https://u.ccb.com/portal/", new_tab=True)
        print(f"请在专用浏览器中登录，最多等待 {args.timeout} 秒。")
        until = time.monotonic() + args.timeout
        while time.monotonic() < until:
            if environment.login_status(d) == "authenticated":
                print("已在平台页面确认登录")
                return
            time.sleep(1)
        sys.exit("未能从平台页面确认登录。请重新登录或在面板里查看状态")
    finally:
        d.shutdown()


def cmd_doctor(args):
    from . import __version__
    d = get_driver(args.driver, zoom=args.zoom, profile_dir=args.profile)
    print(f"帮学助手 {__version__} · Python {sys.version.split()[0]} · 驱动 {d.name}")
    if not d.available():
        sys.exit("驱动未就绪。请打开控制面板安装浏览器组件，或检查所选的驱动")
    try:
        result = environment.check_session(d)
        if result == "authenticated":
            print("已从平台页面确认当前会话可用")
        elif result == "login":
            sys.exit("平台要求登录，请运行 bangxue login")
        else:
            sys.exit("驱动可用，暂未确认登录。请在学习窗口检查平台页面")
    finally:
        if hasattr(d, "shutdown"):
            d.shutdown()


def _read(path, default):
    try:
        return stmod.load(path)
    except FileNotFoundError:
        return default


def cmd_stop(args):
    from . import control
    d = get_driver(args.driver, zoom=args.zoom, profile_dir=args.profile)
    return control.stop(d, args.scope, args.state_dir, args.state)


def cmd_resume(args):
    from . import control
    return control.resume(args.scope, args.state_dir, args.state)


def cmd_panel(args):
    from . import panel
    panel.main(profile_dir=args.profile)


def cmd_scope(args):
    d = get_driver(args.driver, zoom=args.zoom, profile_dir=args.profile)
    classes = flow.read_library_classes(d, args.tab)
    if not classes:
        sys.exit("未读到班级列表（请确认已登录、资源库页面可访问）")
    data = {"name": args.tab or "党的创新理论教育和党性教育资源库",
            "classes": classes, "created_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    stmod.save(args.out, data)
    print(f"✅ 已生成范围文件 {args.out}，共 {len(classes)} 个班")
    for i, c in enumerate(classes, 1):
        print(f"  {i}. {c['title'][:40]}")


def cmd_run(args):
    d = get_driver(args.driver, zoom=args.zoom, profile_dir=args.profile)
    if args.loop:
        return runner.run_loop(d, args.scope, args.state_dir, args.concurrency, args.interval)
    else:
        return runner.run_cycle(d, args.scope, args.state_dir, args.concurrency)


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
        selected = set(titles) if args.scope else None
        completed = set(prog.get("done", []))
        skipped = set(prog.get("skipped", {}))
        if selected is not None:
            completed &= selected
            skipped &= selected
        print(f"已完成班: {len(completed)}   待处理班: {len(skipped)}   暂停: {prog.get('paused_reason', '无')}")
        print("各班级进度:")
        for fn in sorted(os.listdir(args.state_dir) if os.path.isdir(args.state_dir) else []):
            if not fn.endswith(".json") or fn.startswith("_"):
                continue
            wid = fn[:-5]
            if selected is not None and wid not in selected:
                continue
            st = _read(os.path.join(args.state_dir, fn), None)
            if not st:
                continue
            done = len(set(st.get("done", [])))
            total = len(st.get("courses", []))
            act = len(st.get("active", []))
            pr = st.get("paused_reason", "")
            print(f"  {titles.get(wid, wid)[:30]:<32} {done}/{total}  在播{act}" + (f"  ⏸{pr}" if pr else ""))
        return
    st = _open_state(args.state)
    done = len(set(st.get("done", [])))
    active = st.get("active", [])
    total = len(st["courses"])
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
        return monitor.run_loop(d, args.state, args.interval)
    return monitor.run_one(d, args.state)


def positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("请输入大于零的整数")
    return number


def build_parser():
    p = argparse.ArgumentParser(prog="bangxue", description="帮学助手 CLI")
    p.add_argument("--driver", default="auto", choices=["auto", "webbridge", "playwright"],
                   help="浏览器驱动（默认自动）")
    p.add_argument("--zoom", type=positive_int, default=100,
                   help="页面缩放百分比（100=不缩放；80/66/60 可让控件更紧凑，等效浏览器比例缩小）")
    p.add_argument("--profile", default=os.path.expanduser("~/.bangxue/profile"),
                   help="Playwright 持久化登录目录（默认 ~/.bangxue/profile）")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("panel", help="打开本机图形控制面板").set_defaults(fn=cmd_panel)

    c = sub.add_parser("capture", help="从专题班提取课表并生成状态文件")
    c.add_argument("--workshop", required=True, help="专题班链接或 workshopId")
    c.add_argument("--state", default="bangxue_state.json")
    c.add_argument("--concurrency", type=positive_int, default=5)
    c.set_defaults(fn=cmd_capture)

    s = sub.add_parser("start", help="起播指定数量课程")
    s.add_argument("--state", default="bangxue_state.json")
    s.add_argument("--concurrency", type=positive_int, default=5)
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

    stp = sub.add_parser("stop", help="暂停任务并核对可关闭的任务页面")
    stp.add_argument("--scope", default=None)
    stp.add_argument("--state", default=None)
    stp.add_argument("--state-dir", default="bangxue_classes")
    stp.set_defaults(fn=cmd_stop)

    rsm = sub.add_parser("resume", help="解除暂停")
    rsm.add_argument("--scope", default=None)
    rsm.add_argument("--state", default=None)
    rsm.add_argument("--state-dir", default="bangxue_classes")
    rsm.set_defaults(fn=cmd_resume)

    lg = sub.add_parser("login", help="首次登录：打开浏览器登录建行学习并保存登录态")
    lg.add_argument("--timeout", type=positive_int, default=300)
    lg.set_defaults(fn=cmd_login)

    dc = sub.add_parser("doctor", help="环境自检：Python/驱动/登录状态")
    dc.set_defaults(fn=cmd_doctor)

    r = sub.add_parser("run", help="按班级范围自动续班（刷完一个自动找下一个）")
    r.add_argument("--scope", default="bangxue_scope.json", help="范围文件（班级列表）")
    r.add_argument("--state-dir", default="bangxue_classes", help="各班状态文件目录")
    r.add_argument("--concurrency", type=positive_int, default=5)
    mode = r.add_mutually_exclusive_group()
    mode.add_argument("--loop", dest="loop", action="store_true", help="持续巡检（默认）")
    mode.add_argument("--once", dest="loop", action="store_false", help="只运行一轮，供外部调度")
    r.set_defaults(loop=True)
    r.add_argument("--interval", type=positive_int, default=15, help="循环间隔分钟")
    r.set_defaults(fn=cmd_run)

    m = sub.add_parser("monitor", help="跑一轮巡检（可 --loop）")
    m.add_argument("--state", default="bangxue_state.json")
    m.add_argument("--loop", action="store_true")
    m.add_argument("--interval", type=positive_int, default=15, help="循环间隔分钟")
    m.set_defaults(fn=cmd_monitor)
    return p


def main(argv=None):
    # Redirected output in Windows PowerShell may default to a legacy code
    # page. Agent clients and log collectors need a predictable encoding.
    if os.name == "nt":
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure") and not stream.isatty():
                stream.reconfigure(encoding="utf-8")
    p = build_parser()
    args = p.parse_args(argv)
    if args.cmd in ("stop", "resume") and not (args.scope or args.state):
        p.error("请指定 --scope 或 --state 以选定任务")
    try:
        result = args.fn(args)
    except (OSError, RuntimeError, ValueError) as exc:
        p.exit(1, f"操作未完成：{exc}\n")
    if result in ("attention", "busy"):
        p.exit(1)



if __name__ == "__main__":
    main()
