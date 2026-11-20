"""范围和单班共用的暂停、恢复及已登记页面清理。"""
import os
from contextlib import ExitStack

from . import flow, state


def _close_records(driver, st, log):
    remaining = []
    for record in st.get("owned_tabs", []):
        try:
            result = flow.close_owned(driver, record) if driver is not None else "unverified"
        except Exception:
            result = "unverified"
        if result not in ("closed", "missing"):
            remaining.append(record)
    st["owned_tabs"] = remaining
    if remaining or st.get("active") or st.get("done_open"):
        log(f"已核对已登记的标签，仍待核实 {len(remaining)} 个。无法证明归属的页面已保留。")


def _change(driver, scope_path, state_dir, state_path, stopping, log):
    if not scope_path and not state_path:
        log("请指定范围或班级状态文件")
        return "attention"
    prog_path = os.path.join(state_dir, "_scope_state.json") if scope_path else None
    chosen = state.selected(scope_path) if scope_path else {}
    explicit = os.path.abspath(state_path) if state_path else None
    if explicit and not os.path.isfile(explicit):
        raise ValueError(f"找不到班级状态文件 {explicit}")
    if prog_path:
        os.makedirs(state_dir, exist_ok=True)
    main_path = prog_path or explicit
    with ExitStack() as locks:
        # 单独串行化控制请求，让进行中的浏览器操作先看到停止信号再交出状态文件。
        controller = state.acquire_lock(main_path + ".control")
        if controller is None:
            log("另一条暂停或恢复指令正在处理")
            return "busy"
        locks.enter_context(controller)
        if stopping:
            state.request_pause(main_path)
        if prog_path:
            locks.enter_context(state.acquire_lock(prog_path, wait=True))
            prog = state.load_progress(prog_path)
            if prog["current"] not in chosen:
                prog["current"] = None
            if stopping:
                prog["paused_reason"] = "user"
                state.save(prog_path, prog)
        paths = {os.path.abspath(os.path.join(state_dir, wid + ".json")): wid for wid in chosen}
        if explicit:
            paths.setdefault(explicit, None)
        retry = set(prog["skipped"]) if prog_path else set()
        for path, wid in paths.items():
            if not os.path.isfile(path):
                continue
            if stopping:
                state.request_pause(path)
            with state.acquire_lock(path, wait=True):
                st = state.load(path)
                if wid and st.get("workshop") != wid:
                    raise ValueError(f"班级状态与范围不符 {wid}")
                if stopping:
                    st["paused_reason"] = "user"
                    state.save(path, st)
                    _close_records(driver, st, log)
                else:
                    st.pop("paused_reason", None)
                    if not prog_path or path == explicit or wid in retry or wid == prog["current"]:
                        st.pop("attention_reason", None)
                        st.pop("failed", None)
                        if wid in retry and any(not c.get("cid") for c in st.get("courses", [])):
                            st["recapture"] = True
                state.save(path, st)
                if not stopping:
                    state.clear_pause(path)
        if prog_path and not stopping:
            prog.pop("paused_reason", None)
            for wid in chosen:
                prog["skipped"].pop(wid, None)
            state.save(prog_path, prog)
            state.clear_pause(prog_path)
    log("已暂停" if stopping else "已解除暂停，可以继续巡检")
    return "paused" if stopping else "running"


def _apply(driver, scope_path, state_dir, state_path, stopping, log):
    try:
        return _change(driver, scope_path, state_dir, state_path, stopping, log)
    except (OSError, ValueError, TypeError) as exc:
        log(f"控制指令未全部完成：{exc}")
        return "attention"


def stop(driver, scope_path, state_dir, state_path=None, log=print):
    return _apply(driver, scope_path, state_dir, state_path, True, log)


def resume(scope_path, state_dir, state_path=None, log=print):
    return _apply(None, scope_path, state_dir, state_path, False, log)
