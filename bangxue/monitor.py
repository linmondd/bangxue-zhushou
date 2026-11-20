"""巡检：对账 / 核进度 / 关已完成 / 补新课 / 恢复暂停。"""
import time

from . import flow, state as stmod

ROUND_BUDGET = 600

def run_one(driver, state_path, log=print):
    lock = stmod.acquire_lock(state_path)
    if lock is None:
        log("另一轮巡检正在运行，本轮跳过")
        return
    try:
        _run(driver, state_path, log=log)
    finally:
        lock.close()

def _run(driver, state_path, log=print):
    st = stmod.load(state_path)
    wid = st["workshop"]
    courses = st["courses"]
    active = list(st.get("active", []))
    done = st.setdefault("done", [])
    if len(done) != len(set(done)):
        done[:] = list(dict.fromkeys(done))
    done_open = st.setdefault("done_open", [])
    last_ct = st.setdefault("last_ct", {})
    failed = st.setdefault("failed", {})
    maxc = st.get("max_concurrent", 5)
    report = []
    t0 = time.time()

    if st.get("paused_reason"):
        log(f"⏸ 已暂停（{st['paused_reason']}），本轮不动作。用 bangxue resume 恢复。")
        return

    # 初始对账：建表时已完成的课直接进 done
    if not st.get("initialized"):
        for c in courses:
            if c.get("cid") and (c.get("prog") == "100%" or "回看" in (c.get("act") or "")):
                if c["cid"] not in done:
                    done.append(c["cid"])
        st["initialized"] = True
        report.append("初始对账：已把建表时完成的课计入 done")

    # 课程表核对（缓存：默认 30 分钟一次，避免每轮开表页）
    last_sync = st.get("last_sync", 0)
    need_sync = (time.time() - last_sync > 1800) or (not active)
    if need_sync:
        try:
            live_done = flow.sync_done(driver, wid, courses)
            added = 0
            for cid in live_done:
                if cid not in done:
                    done.append(cid); added += 1
            st["last_sync"] = time.time()
            if added:
                report.append(f"课程表核对：新增已确认完成 {added} 门，跳过不再学")
        except Exception as e:
            report.append(f"课程表核对失败（沿用旧状态）：{str(e)[:80]}")

    # 接管本班仍在的播放标签
    ex = set(flow.list_play_cids(driver, wid))
    adopted = 0
    for c in courses:
        cid = c.get("cid")
        if cid and cid in ex and cid not in done and cid not in active:
            active.append(cid); adopted += 1
    if adopted:
        report.append(f"接管了 {adopted} 个已在播标签")

    still = []
    for cid in active:
        if time.time() - t0 > ROUND_BUDGET:
            still.append(cid); report.append("⏱ 本轮预算用尽，剩余留到下一轮"); continue
        s = flow.check(driver, cid, wid)
        stage = s.get("stage")
        if stage == "blocked":
            reason = s.get("reason", "")
            if reason in ("login", "captcha"):
                st["paused_reason"] = reason
                report.append(f"⛔ {reason}：暂停并报告（不绕过验证）")
                break
            failed[cid] = reason
            report.append(f"⚠ 阻断({reason})，跳过 {cid[:8]}")
            continue
        if stage == "removed":
            failed[cid] = "removed"
            report.append(f"⚠ 课程已下架，跳过 {cid[:8]}")
            continue
        if stage == "notab":
            report.append(f"⚠标签丢失，重新入队 {cid[:8]}")
            continue
        prev = last_ct.get(cid)
        ct_now = s.get("ct", -1)
        stagn = (prev is not None and (ct_now < 0 or abs(ct_now - prev) < 1))
        if s.get("paused") is True or stagn:
            flow.resume(driver, cid, wid)
            time.sleep(2)
            s = flow.check(driver, cid, wid)
            report.append(f"↻ 恢复播放 {cid[:8]} (paused={s.get('paused')})")
        info = next((c for c in courses if c.get("cid") == cid), {})
        prog = str(s.get("prog", ""))
        ct, dur = s.get("ct", -1), s.get("dur", -1)
        if isinstance(ct, (int, float)):
            last_ct[cid] = ct
        hit_end = (prog == "100%") or (dur and dur > 60 and ct >= dur - 5)
        if hit_end:
            v = flow.verify(driver, wid, info.get("title", ""))
            if v.get("confirmed"):
                if cid not in done:
                    done.append(cid)
                report.append(f"✔完成(已回验) {info.get('title', cid)[:22]} 表={v.get('prog')}{v.get('act','')}")
                if not flow.close(driver, cid, wid):
                    done_open.append(cid)
                    report.append(f"  关页失败，记入 done_open: {cid[:8]}")
            else:
                still.append(cid)
                report.append(f"…待确认 {info.get('title', cid)[:22]} 播放页{prog} 表={v.get('prog', v.get('reason','?'))}")
        else:
            still.append(cid)
            report.append(f"播放 {info.get('title', cid)[:22]} {prog} {ct}/{dur}")

    for cid in list(done_open):
        if flow.close(driver, cid, wid):
            done_open.remove(cid)
            report.append(f"  关闭残留页成功 {cid[:8]}")

    # 补新课：逐门起播，确认一门在播后再开下一门；失败即停（不批量开页）
    while len(still) < maxc and time.time() - t0 < ROUND_BUDGET:
        nxt = next((c for c in courses if c.get("cid") and c["cid"] not in done
                    and c["cid"] not in still and c["cid"] not in done_open
                    and c["cid"] not in failed and not c.get("manual")), None)
        if not nxt:
            break
        report.append(f"逐门起播：{nxt['title'][:20]}（确认在播后才开下一门）")
        r = flow.start(driver, nxt["cid"], wid, log=log)
        if r.get("ok"):
            still.append(nxt["cid"])
            report.append(f"▶起播确认 {nxt['title'][:20]} ct={r.get('ct')} growth={r.get('growth')} rate={r.get('rate')}")
        else:
            stg = r.get("stage")
            if stg == "blocked":
                reason = r.get("reason", "")
                if reason in ("login", "captcha"):
                    st["paused_reason"] = reason
                    report.append(f"⛔ {reason}：暂停并报告（不绕过验证）")
                    break
                failed[nxt["cid"]] = reason
            elif stg == "removed":
                failed[nxt["cid"]] = "removed"
            report.append(f"✖起播失败 {nxt['title'][:20]} {stg}")
            courses.append(courses.pop(courses.index(nxt)))
            break

    st["active"] = still
    st["done"] = done
    st["failed"] = failed
    st["done_open"] = done_open
    st["last_ct"] = last_ct
    stmod.save(state_path, st)

    unmapped = [c for c in courses if not c.get("cid")]
    left = len([c for c in courses if c.get("cid") and c["cid"] not in done and c["cid"] not in done_open])
    log(f"=== 巡检 {time.strftime('%H:%M:%S')} 在播{len(still)} 完成{len(done)} 待关{len(done_open)} ===")
    for line in report:
        log(line)
    if unmapped:
        log(f"⚠ 有 {len(unmapped)} 门课未映射 courseId（需重跑建课表）：")
        for c in unmapped[:10]:
            log("   -", c.get("title", "?"))
    manual_left = len([c for c in courses if c.get("manual") and c.get("cid") not in done])
    log(f"剩余未完成：{left}（另 {len(unmapped)} 门未映射，{manual_left} 门需人工）")
