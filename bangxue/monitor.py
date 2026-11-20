"""单班巡检。每项操作更新同一份状态，暂停时保留尚未巡检的课程。"""
import math
import time

from . import flow, state

ROUND_BUDGET = 600
PAUSE_REASONS = {"login", "captcha", "restriction", "restricted", "limit", "platform_limit"}


def _add(items, item):
    if item not in items:
        items.append(item)


def _terminal(st):
    if st.get("paused_reason"):
        return "paused"
    if st.get("attention_reason"):
        return "attention"
    if st["active"]:
        return "running"
    if st["done_open"]:
        st["attention_reason"] = "已完成课程仍有待核实的页面"
        return "attention"
    done = set(st["done"])
    pending = [c for c in st["courses"] if not c.get("cid") or c["cid"] not in done]
    if any(c.get("cid") and not c.get("manual") and c["cid"] not in st["failed"] for c in pending):
        return "running"
    if not pending and st["courses"]:
        return "complete"
    manual = sum(bool(c.get("manual")) for c in pending)
    unmapped = sum(not c.get("cid") for c in pending)
    st["attention_reason"] = f"待人工 {manual} 门，未映射 {unmapped} 门，失败 {len(st['failed'])} 门"
    return "attention"


def _operate(driver, state_path, log, operation, *, expected_wid=None):
    lock = state.acquire_lock(state_path)
    if lock is None:
        log("另一轮班级操作正在运行")
        return "busy"
    with lock:
        st = state.load(state_path)
        if expected_wid and st.get("workshop") != expected_wid:
            raise ValueError(f"班级状态与当前范围不符 {expected_wid}")
        if not isinstance(st.get("courses"), list) or not st.get("workshop"):
            raise ValueError("班级状态缺少课表或班级编号")
        if state.pause_requested(state_path) or st.get("paused_reason"):
            log(f"班级已暂停（{st.get('paused_reason') or 'user'}）")
            return "paused"
        if st.get("attention_reason"):
            log(st["attention_reason"])
            return "attention"
        for key in ("active", "done", "done_open", "owned_tabs"):
            st.setdefault(key, [])
        for key in ("failed", "last_ct"):
            st.setdefault(key, {})
        guard = state.guard_driver(driver, state_path)
        try:
            operation(guard, st)
        except state.PauseRequested:
            st["paused_reason"] = "user"
        except Exception as exc:
            reason = getattr(exc, "reason", "")
            if reason in PAUSE_REASONS:
                st["paused_reason"] = reason
            else:
                st["attention_reason"] = str(exc) or type(exc).__name__
                if isinstance(exc, flow.CourseListChanged):
                    st["recapture"] = True
        guard.keep_receipts(st)
        result = _terminal(st)
        state.save(state_path, st)
        reason = st.get("paused_reason") or st.get("attention_reason")
        log(f"在播 {len(st['active'])}，已完成 {len(st['done'])}，待关 {len(st['done_open'])}"
            + (f"（{reason}）" if reason else ""))
        return result


def start_one(driver, state_path, concurrency=5, log=print):
    state.validate_concurrency(concurrency)

    def start(guard, st):
        st["max_concurrent"] = concurrency
        _, failed = flow.start_pending(guard, st, concurrency, log=log)
        if failed and not st.get("paused_reason"):
            st.setdefault("attention_reason", "课程起播失败，需要检查")
    return _operate(driver, state_path, log, start)


def _close_completed(driver, st, cid, log):
    # 已接管的手动标签没有创建记录，继续保留。
    matches = [r for r in st["owned_tabs"] if any(
        flow._course(r.get("url"), st["workshop"], route) == cid for route in ("play", "detail"))]
    if not matches:
        log(f"课程 {cid} 没有可核实的任务标签，已保留可能打开的页面")
    for record in matches:
        result = flow.close_owned(driver, record)
        if result not in ("closed", "missing"):
            return False
        st["owned_tabs"].remove(record)
    return True


def _outcome(st, cid, s):
    reason = s.get("reason") or s.get("stage") or "播放状态不可读"
    if reason in PAUSE_REASONS:
        st["paused_reason"] = reason
    elif s.get("stage") in ("removed", "blocked"):
        st["failed"][cid] = reason
        st["active"].remove(cid)
    elif s.get("stage") == "notab":
        st["active"].remove(cid)
    elif s.get("ok") is False:
        st["attention_reason"] = reason
    else:
        return False
    return True


def _monitor(driver, st, log, concurrency):
    wid = st["workshop"]
    if concurrency is not None:
        st["max_concurrent"] = concurrency
    maxc = state.validate_concurrency(st.get("max_concurrent", 5))
    by_id = {c["cid"]: c for c in st["courses"] if c.get("cid")}
    active = st["active"]
    deadline = time.monotonic() + ROUND_BUDGET
    if (not st.get("verified_table_version") or not active
            or time.time() - st.get("last_sync", 0) > 1800):
        confirmed = flow.sync_done(driver, wid, st["courses"])
        # 旧版本只看课表第一页，并可能以截断标题误计完成。
        st["done"] = sorted(set(confirmed) & by_id.keys())
        st["verified_table_version"] = 1
        st["initialized"] = True
        st["last_sync"] = time.time()

    for cid in flow.list_play_cids(driver, wid):
        if cid in by_id and not by_id[cid].get("manual") and cid not in st["failed"] and cid not in st["done"]:
            _add(active, cid)

    for cid in active.copy():
        if time.monotonic() >= deadline:
            return
        if cid in st["done"]:
            active.remove(cid)
            _add(st["done_open"], cid)
            continue
        if cid not in by_id:
            st["attention_reason"] = f"正在播放的课程不在课表中 {cid}"
            return
        s = flow.check(driver, cid, wid)
        if not _outcome(st, cid, s):
            ct = s.get("ct", -1)
            prev = st["last_ct"].get(cid)
            if s.get("paused") is True or (prev is not None and (ct < 0 or abs(ct - prev) < 1)):
                resumed = flow.resume(driver, cid, wid)
                if isinstance(resumed, dict) and _outcome(st, cid, resumed):
                    if st.get("paused_reason") or st.get("attention_reason"):
                        return
                    continue
                time.sleep(2)
                s = flow.check(driver, cid, wid)
                if _outcome(st, cid, s):
                    if st.get("paused_reason") or st.get("attention_reason"):
                        return
                    continue
            ct, dur = s.get("ct", -1), s.get("dur", -1)
            if isinstance(ct, (float, int)):
                st["last_ct"][cid] = ct
            if s.get("prog") == "100%" or (dur > 60 and ct >= dur - 5):
                result = flow.verify(driver, wid, by_id[cid].get("title", ""))
                if result.get("reason") in PAUSE_REASONS:
                    st["paused_reason"] = result["reason"]
                    return
                if result.get("confirmed"):
                    _add(st["done"], cid)
                    active.remove(cid)
                    _add(st["done_open"], cid)
                elif result.get("reason"):
                    st["attention_reason"] = result["reason"]
                    return
        if st.get("paused_reason") or st.get("attention_reason"):
            return

    for cid in st["done_open"].copy():
        if not _close_completed(driver, st, cid, log):
            st["attention_reason"] = f"无法核实或关闭已完成课程页面 {cid}"
            return
        st["done_open"].remove(cid)

    for cid, course in by_id.items():
        if len(active) >= maxc or time.monotonic() >= deadline:
            return
        if cid in active or cid in st["done"] or cid in st["failed"] or course.get("manual"):
            continue
        result = flow.start(driver, cid, wid, log=log)
        for record in result.get("owned_tabs", []):
            _add(st["owned_tabs"], record)
        if result.get("ok"):
            active.append(cid)
            log(f"已确认起播 {course.get('title') or cid}")
        else:
            reason = result.get("reason") or result.get("stage") or "未确认起播"
            if reason in PAUSE_REASONS:
                st["paused_reason"] = reason
            else:
                st["failed"][cid] = reason
                log(f"课程 {course.get('title') or cid} 起播失败（{reason}），本轮停止开页")
            return


def run_one(driver, state_path, log=print, *, concurrency=None, expected_wid=None):
    return _operate(driver, state_path, log, lambda d, st: _monitor(d, st, log, concurrency),
                    expected_wid=expected_wid)


def wait_interval(path, interval_min):
    if not math.isfinite(interval_min) or interval_min <= 0:
        raise ValueError("巡检间隔必须为正数")
    end = time.monotonic() + interval_min * 60
    while True:
        if state.pause_requested(path):
            return "paused"
        remaining = end - time.monotonic()
        if remaining <= 0:
            return "running"
        time.sleep(min(0.5, remaining))


def run_loop(driver, state_path, interval_min=15, log=print):
    if not math.isfinite(interval_min) or interval_min <= 0:
        raise ValueError("巡检间隔必须为正数")
    while True:
        result = run_one(driver, state_path, log=log)
        if result != "running":
            return result
        if wait_interval(state_path, interval_min) == "paused":
            return "paused"
