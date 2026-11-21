"""在已选班级范围内巡检。完成来自整张课表，跳过和待处理分别计数。"""
import math
import os
import time
from collections import Counter

from . import classes, control, flow, monitor, state


def _inspect_class(driver, path, wid, title, concurrency, log, evidence):
    lock = state.acquire_lock(path)
    if lock is None:
        return "busy", "班级正由其他任务操作"
    with lock:
        st = state.load(path) if os.path.exists(path) else None
        if st is not None and st.get("workshop") != wid:
            return "attention", "班级状态与所选编号不符"
        if state.pause_requested(path) or (st and st.get("paused_reason")):
            return "paused", (st or {}).get("paused_reason") or "user"
        rows = classes.read_class_table(driver, wid)
        if not rows:
            if not classes.ensure_enrolled(driver, wid):
                return "attention", "报名未确认"
            rows = classes.read_class_table(driver, wid)
            if not rows:
                return "attention", "报名后仍无课表"
        if classes.is_complete(rows) and st is not None:
            if st.get("done_open") and not st.get("owned_tabs"):
                st["recapture"] = True
                return "attention", "存在无法核验归属的已完成页面，需重读课程表"
            titles = [flow._norm(c.get("title", "")) for c in st["courses"]]
            titles_mismatch = len(titles) != len(rows) or Counter(titles) != Counter(
                flow._norm(r.get("title", "")) for r in rows)
            if titles_mismatch and not st.get("active") and not st.get("owned_tabs"):
                st["recapture"] = True
                state.save(path, st)
                result = flow.capture(driver, wid, log=log)
                if not result or not result.get("courses"):
                    return "attention", "未能重新读取完整课表"
                st["courses"] = result["courses"]
                st.pop("recapture", None)
                st.pop("verified_table_version", None)
                state.save(path, st)
            elif len(titles) != len(rows):
                return "attention", "本地清单与完整课表数量不同，需要重新读取"
            elif any(count > 1 for count in Counter(titles).values()):
                return "attention", "班级存在同名课程，需要人工核验"
        if classes.is_complete(rows):
            evidence.update(wid=wid, total=len(rows), checked_at=time.time())
            if st is not None:
                control._close_records(driver, st, log)
                if st.get("owned_tabs"):
                    st["attention_reason"] = "课表已完成，仍有任务页无法核实或关闭"
                    state.save(path, st)
                    return "attention", st["attention_reason"]
                st["active"] = []
                st["done_open"] = []
                counts = Counter(flow._norm(r.get("title", "")) for r in rows)
                st["done"] = sorted({c["cid"] for c in st["courses"] if c.get("cid") and
                                     counts[flow._norm(c.get("title", ""))] == 1})
                st.pop("attention_reason", None)
                state.save(path, st)
            return "complete", ""
        if st is None or st.get("recapture"):
            result = flow.capture(driver, wid, log=log)
            if not result or not result.get("courses"):
                return "attention", "未能建立完整课表"
            if st is None:
                st = state.init_state(wid, result["courses"], concurrency)
            else:
                st["courses"] = result["courses"]
                st.pop("recapture", None)
                st.pop("verified_table_version", None)
            state.save(path, st)
            log(f"已建立 {title} 课表，共 {len(st['courses'])} 门")
    result = monitor.run_one(driver, path, log=log, concurrency=concurrency, expected_wid=wid)
    st = state.load(path)
    if result == "complete":
        # 单班本地清单可能比实时课表少行；必须再看整班结果。
        rows = classes.read_class_table(driver, wid)
        if not classes.is_complete(rows):
            with state.acquire_lock(path, wait=True):
                st = state.load(path)
                st["recapture"] = True
                state.save(path, st)
            return "attention", "本地课程均已完成，实时课表仍有未完成课程，需要重新建表"
        evidence.update(wid=wid, total=len(rows), checked_at=time.time())
    return result, st.get("paused_reason") or st.get("attention_reason") or ""


def _class_cycle(driver, path, wid, title, concurrency, log, evidence):
    guard = state.guard_driver(driver, path)
    try:
        return _inspect_class(guard, path, wid, title, concurrency, log, evidence)
    finally:
        if guard.opened:
            with state.acquire_lock(path, wait=True):
                if os.path.exists(path):
                    st = state.load(path)
                else:
                    st = state.init_state(wid, [], concurrency)
                    st["recapture"] = True
                guard.keep_receipts(st)
                state.save(path, st)


def _run_cycle(driver, scope_path, state_dir, prog_path, concurrency, log):
    chosen = state.selected(scope_path)
    prog = state.load_progress(prog_path)
    if prog.get("current") not in chosen:
        prog["current"] = None
    receipts = prog.setdefault("class_evidence", {})
    prog["done"] = [wid for wid in prog["done"] if state.has_evidence(receipts, wid)]
    prog["verified_table_version"] = 2
    state.save(prog_path, prog)
    if prog.get("paused_reason") or state.pause_requested(prog_path):
        log(f"范围已暂停（{prog.get('paused_reason') or 'user'}）")
        return "paused"
    done = set(prog["done"])
    skipped = prog["skipped"]
    cur = prog["current"]
    order = ([cur] if cur else []) + [wid for wid in chosen if wid != cur]
    driver = state.guard_driver(driver, prog_path)
    for wid in order:
        if wid in done:
            continue
        if wid in skipped:
            path = os.path.join(state_dir, wid + ".json")
            if os.path.isfile(path):
                st = state.load(path)
                if st.get("active") or st.get("done_open"):
                    log(f"{chosen[wid]} 仍有在播或待关课程（{skipped[wid]}），请先处理后重试")
                    return "attention"
            continue
        state.check_pause(prog_path)
        prog["current"] = wid
        state.save(prog_path, prog)
        path = os.path.join(state_dir, wid + ".json")
        evidence = {}
        try:
            result, reason = _class_cycle(driver, path, wid, chosen[wid], concurrency, log, evidence)
        except state.PauseRequested:
            result, reason = "paused", "user"
        except Exception as exc:
            reason = getattr(exc, "reason", "") or str(exc) or type(exc).__name__
            result = "paused" if reason in monitor.PAUSE_REASONS else "attention"
        if result == "paused":
            prog["paused_reason"] = reason or "user"
            state.save(prog_path, prog)
            log(f"{chosen[wid]} 已暂停（{prog['paused_reason']}）")
            return result
        if result in ("running", "busy"):
            state.save(prog_path, prog)
            return result
        if result == "complete" and evidence.get("total", 0) > 0:
            receipts[wid] = evidence
            done.add(wid)
            prog["done"] = sorted(done)
            log(f"已核实整班完成：{chosen[wid]}")
        else:
            skipped[wid] = reason or "待人工核查"
            log(f"{chosen[wid]} 待处理（{skipped[wid]}）")
            if os.path.isfile(path):
                st = state.load(path)
                if st.get("active") or st.get("done_open"):
                    state.save(prog_path, prog)
                    return "attention"
        prog["current"] = None
        state.save(prog_path, prog)

    prog["current"] = None
    state.save(prog_path, prog)
    completed = len(done.intersection(chosen))
    pending = len(set(chosen).intersection(skipped) - done)
    log(f"所选班级已完成 {completed}/{len(chosen)}，待处理 {pending}")
    return "complete" if completed == len(chosen) else "attention"


def run_cycle(driver, scope_path, state_dir, concurrency=5, log=print):
    state.validate_concurrency(concurrency)
    os.makedirs(state_dir, exist_ok=True)
    prog_path = os.path.join(state_dir, "_scope_state.json")
    lock = state.acquire_lock(prog_path)
    if lock is None:
        log("另一轮范围巡检正在运行")
        return "busy"
    with lock:
        try:
            pulse_path = os.path.join(state_dir, "_heartbeat.json")
            try:
                pulse = state.load(pulse_path)
            except FileNotFoundError:
                pulse = {}
            started = time.time()
            pulse.update(started=started, status="checking", pid=os.getpid())
            state.save(pulse_path, pulse)
            result = _run_cycle(driver, scope_path, state_dir, prog_path, concurrency, log)
            pulse.update(finished=time.time(), status=result)
            if started - pulse.get("last_summary", 0) >= 600 or result != "running":
                chosen = state.selected(scope_path)
                prog = state.load_progress(prog_path)
                done = set(prog["done"]).intersection(chosen)
                pending = set(prog["skipped"]).intersection(chosen) - done
                current = chosen.get(prog["current"], "无")
                pulse["summary"] = (f"所选班级已完成 {len(done)}/{len(chosen)}，待处理 {len(pending)}，"
                                    f"当前班 {current}，本轮状态 {result}")
                pulse["last_summary"] = started
                log(pulse["summary"])
            state.save(pulse_path, pulse)
            return result
        except state.PauseRequested:
            return "paused"
        except (OSError, ValueError, TypeError) as exc:
            log(f"范围巡检需要处理：{exc}")
            return "attention"


def run_loop(driver, scope_path, state_dir, concurrency=5, interval_min=1, log=print):
    if not math.isfinite(interval_min) or interval_min <= 0:
        raise ValueError("巡检间隔必须为正数")
    path = os.path.join(state_dir, "_scope_state.json")
    while True:
        tick = time.monotonic()
        result = run_cycle(driver, scope_path, state_dir, concurrency, log=log)
        if result != "running":
            return result
        if monitor.wait_interval(path, max(.01, interval_min - (time.monotonic()-tick)/60)) == "paused":
            return "paused"
