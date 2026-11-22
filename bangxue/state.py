"""状态文件、跨进程锁和可在巡检过程中请求的暂停。"""
import errno
import json
import os
import re
import tempfile
import time


_WINDOWS_FILE_RETRY = os.name == "nt"


def _file_operation(operation, *args, **kwargs):
    # A Windows reader or scanner can briefly block an atomic replacement,
    # and a reader can also meet a file in the middle of that transition.
    for delay in (0.01, 0.02, 0.04, 0.08, 0.16, 0.32, 0):
        try:
            return operation(*args, **kwargs)
        except PermissionError:
            if not _WINDOWS_FILE_RETRY or not delay:
                raise
            time.sleep(delay)


def load(path):
    with _file_operation(open, path, encoding="utf-8") as f:
        return json.load(f)


def load_progress(path):
    try:
        data = load(path)
    except FileNotFoundError:
        data = {}
    if not isinstance(data, dict):
        raise ValueError("范围状态格式有误")
    data.setdefault("done", [])
    data.setdefault("skipped", {})
    data.setdefault("current", None)
    if not isinstance(data["done"], list) or not isinstance(data["skipped"], dict):
        raise ValueError("范围进度格式有误")
    return data


def has_evidence(records, wid):
    item = records.get(wid, {})
    return (item.get("wid") == wid and isinstance(item.get("total"), int)
            and item["total"] > 0 and bool(item.get("checked_at")))


def selected(scope_path):
    scope = load(scope_path)
    if not isinstance(scope, dict) or not isinstance(scope.get("classes"), list):
        raise ValueError("范围文件需要 classes 列表")
    result = {}
    for item in scope["classes"]:
        wid = item.get("wid") if isinstance(item, dict) else None
        if not isinstance(wid, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}", wid):
            raise ValueError("范围中有无效的班级编号")
        result.setdefault(wid, str(item.get("title") or wid))
    if not result:
        raise ValueError("尚未选择班级")
    return result


def validate_concurrency(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 10:
        raise ValueError("并发数须为 1 到 10 的整数")
    return value


def save(path, st):
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=1)
        _file_operation(os.replace, tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def acquire_lock(path, wait=False):
    """进程/线程公用的文件锁。巡检不排队，控制指令可等待当前操作退出。"""
    f = open(os.fspath(path) + ".lock", "a+b")
    try:
        if os.name == "nt":
            import msvcrt
            f.seek(0)
            # A region may extend past EOF. All processes lock byte zero.
            while True:
                try:
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                    return f
                except OSError as exc:
                    if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                        raise
                    if not wait:
                        f.close()
                        return None
                    time.sleep(0.1)
        import fcntl
        flags = fcntl.LOCK_EX if wait else fcntl.LOCK_EX | fcntl.LOCK_NB
        try:
            fcntl.flock(f, flags)
        except BlockingIOError:
            f.close()
            return None
        return f
    except BaseException:
        f.close()
        raise


def pause_requested(path):
    return os.path.exists(os.fspath(path) + ".pause")


def request_pause(path):
    save(os.fspath(path) + ".pause", {"requested": time.time()})


def clear_pause(path):
    try:
        os.unlink(os.fspath(path) + ".pause")
    except FileNotFoundError:
        pass


class PauseRequested(BaseException):
    """用户中断。流程层的普通网络异常重试不可吞掉它。"""


def check_pause(*paths):
    if any(pause_requested(p) for p in paths):
        raise PauseRequested()


class GuardedDriver:
    def __init__(self, driver, paths):
        self.driver = driver
        self.paths = paths
        self.opened = {}

    def open(self, url, new_tab=True):
        check_pause(*self.paths)
        tab = self.driver.open(url, new_tab=new_tab)
        if new_tab and tab is not None and tab.id is not None:
            self.opened[tab.id] = {"id": tab.id, "url": tab.url}
        return tab

    def close(self, tab):
        check_pause(*self.paths)
        closed = self.driver.close(tab)
        if closed:
            self.opened.pop(tab.id, None)
        return closed

    def keep_receipts(self, st):
        records = st.setdefault("owned_tabs", [])
        known = {r["id"] for r in records}
        records.extend(record for key, record in self.opened.items() if key not in known)

    def __getattr__(self, name):
        target = getattr(self.driver, name)
        if not callable(target):
            return target

        def guarded(*args, **kwargs):
            check_pause(*self.paths)
            return target(*args, **kwargs)
        return guarded


def guard_driver(driver, *paths):
    return GuardedDriver(driver, paths)


def init_state(wid, courses, max_concurrent=5):
    return {"workshop": wid, "courses": courses, "active": [],
            "done": [], "done_open": [], "last_ct": {}, "owned_tabs": [],
            "max_concurrent": validate_concurrency(max_concurrent), "initialized": False}
