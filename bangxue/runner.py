"""班级队列：在给定范围内，刷完一个班自动找下一个（未报名先报名），直到范围内全部完成。"""
import json, os, re, time

from . import classes, flow, monitor, state as stmod


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save(path, obj):
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    import tempfile
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def run_cycle(driver, scope_path, state_dir, concurrency=5, log=print):
    os.makedirs(state_dir, exist_ok=True)
    prog_path = os.path.join(state_dir, "_scope_state.json")
    lock = stmod.acquire_lock(prog_path)
    if lock is None:
        log("另一轮范围巡检正在运行，本轮跳过")
        return
    try:
        _run_cycle(driver, scope_path, state_dir, concurrency, log=log)
    finally:
        lock.close()


def _run_cycle(driver, scope_path, state_dir, concurrency=5, log=print):
    scope = _load(scope_path, {})
    classes_list = scope.get("classes", [])
    if not classes_list:
        log(f"范围文件为空或不存在：{scope_path}")
        return
    os.makedirs(state_dir, exist_ok=True)
    prog_path = os.path.join(state_dir, "_scope_state.json")
    prog = _load(prog_path, {"done": [], "skipped": {}, "current": None})
    if prog.get("paused_reason"):
        log(f"⏸ 范围已暂停（{prog['paused_reason']}），用 bangxue resume 恢复。")
        return
    done = set(prog.get("done", []))
    skipped = prog.get("skipped", {})
    manual_classes = prog.setdefault("manual", {})
    cur = prog.get("current")
    # 清理本会话残留标签：只保留当前班仍在播的视频，防止标签越堆越多拖垮定位
    try:
        keep = set()
        if cur:
            sp0 = os.path.join(state_dir, f"{cur}.json")
            if os.path.exists(sp0):
                keep = set(stmod.load(sp0).get("active", []))
        tabs = driver.list_tabs() or []
        stale = []
        for t in tabs:
            m = re.search(r"/course/#/play/([a-f0-9-]+)", t.url)
            if m and m.group(1) in keep:
                continue
            stale.append(t)
        if stale:
            if not keep and len(stale) > 3:
                driver.close_all()
            else:
                for t in stale[:80]:
                    driver.close(t)
            log(f"清理会话残留标签 {len(stale)} 个（保留在播 {len(keep)} 门）")
    except Exception as e:
        log(f"清理标签失败（忽略）：{e}")
    title_of = {c["wid"]: c.get("title", "") for c in classes_list}

    # 1) 当前班：巡检 → 判断整班是否完成
    if cur and cur not in done:
        sp = os.path.join(state_dir, f"{cur}.json")
        if os.path.exists(sp):
            monitor.run_one(driver, sp, log=log)
            try:
                cst = stmod.load(sp)
                if cst.get("paused_reason"):
                    prog["paused_reason"] = cst["paused_reason"]
                    _save(prog_path, prog)
                    log(f"⏸ 班级暂停（{cst['paused_reason']}），已停止本轮")
                    return
            except Exception:
                pass
        rows = classes.read_class_table(driver, cur)
        if classes.is_complete(rows):
            done.add(cur)
            try:
                cst = stmod.load(sp)
                cst["done"] = [c["cid"] for c in cst.get("courses", []) if c.get("cid")]
                cst["active"] = []
                stmod.save(sp, cst)
            except Exception:
                pass
            prog["current"] = None
            prog["done"] = sorted(done)
            _save(prog_path, prog)
            log(f"✅ 班级完成：{title_of.get(cur, '')[:26]}")
        else:
            # 视频全学完、只剩 scorm/课程包/考试：记「需人工」，继续下一个班，避免整夜卡死
            try:
                cst = stmod.load(sp)
                valid = [c for c in cst.get("courses", []) if c.get("cid")]
                done_set = set(cst.get("done", []))
                video_left = [c for c in valid if not c.get("manual") and c["cid"] not in done_set and c.get("prog") != "100%"]
                manual_left = [c for c in valid if c.get("manual") and c["cid"] not in done_set and c.get("prog") != "100%"]
                unmapped = [c for c in cst.get("courses", []) if not c.get("cid")]
            except Exception:
                video_left, manual_left, unmapped = [1], [], []
            if not video_left and manual_left and not unmapped:
                manual_classes[cur] = len(manual_left)
                prog["current"] = None
                prog["manual"] = manual_classes
                _save(prog_path, prog)
                log(f"⏭ 视频已学完，剩 {len(manual_left)} 门需人工（scorm/课程包/考试）：{title_of.get(cur, '')[:26]}")
            else:
                d, t = classes.progress(rows) if rows else (0, 0)
                log(f"当前班级：{title_of.get(cur, '')[:26]} 完成 {d}/{t}，下轮继续")
                prog["done"] = sorted(done)
                _save(prog_path, prog)
                return

    # 2) 找下一个班：已完成的跳过；未报名的先报名；然后建课表并起播
    try:
        scan = driver.open("https://learning-platform.local/portal/", new_tab=True)
        if not driver.use(scan):
            log("⚠ 扫描标签定位失败，仍尝试继续")
    except Exception:
        pass
    for c in classes_list:
        wid = c["wid"]
        title = c.get("title", "")
        if wid in done or wid in skipped or wid in manual_classes:
            continue
        log(f"检查：{title[:26]}")
        rows = classes.read_class_table(driver, wid, reuse=True)
        if classes.is_complete(rows):
            done.add(wid)
            log(f"✅ 已完成，跳过：{title[:26]}")
            continue
        if not rows:
            if not classes.ensure_enrolled(driver, wid, reuse=True):
                skipped[wid] = "enroll_failed"
                log(f"⚠ 报名失败，跳过：{title[:26]}")
                continue
            rows = classes.read_class_table(driver, wid, reuse=True)
            if not rows:
                skipped[wid] = "no_table"
                log(f"⚠ 无课程表，跳过：{title[:26]}")
                continue
        res = flow.capture(driver, wid)
        if not res or not res.get("courses"):
            skipped[wid] = "capture_failed"
            log(f"⚠ 建课表失败，跳过：{title[:26]}")
            continue
        sp = os.path.join(state_dir, f"{wid}.json")
        st = stmod.init_state(wid, res["courses"], concurrency)
        stmod.save(sp, st)
        prog["current"] = wid
        prog["done"] = sorted(done)
        prog["skipped"] = skipped
        _save(prog_path, prog)
        log(f"▶ 开始新班：{title[:26]}（{len(res['courses'])} 门）")
        flow.start_pending(driver, st, concurrency, log=log)
        stmod.save(sp, st)
        if st.get("paused_reason"):
            prog["paused_reason"] = st["paused_reason"]
            _save(prog_path, prog)
            log(f"⏸ 班级暂停（{st['paused_reason']}），已停止本轮")
        return

    prog["done"] = sorted(done)
    prog["manual"] = manual_classes
    prog["skipped"] = skipped
    prog["current"] = None
    _save(prog_path, prog)
    if skipped:
        log(f"⚠ 本轮结束：{len(skipped)} 个班报名/建表失败被跳过，尚未完成；详见状态文件")
    elif manual_classes:
        log(f"✅ 可自动学习的班已全部完成；另有 {len(manual_classes)} 个班需人工补完")
    else:
        log("🎉 范围内所有班级已全部完成")


def run_loop(driver, scope_path, state_dir, concurrency=5, interval_min=15, log=print):
    while True:
        run_cycle(driver, scope_path, state_dir, concurrency, log=log)
        time.sleep(interval_min * 60)
