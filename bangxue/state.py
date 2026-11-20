"""状态文件：加载、原子保存、单实例锁。"""
import json, os, tempfile

def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def save(path, st):
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

def acquire_lock(path):
    """返回锁文件句柄；已被占用返回 None。跨平台（Unix: flock，Windows: msvcrt）。"""
    f = open(path + ".lock", "w")
    try:
        if os.name == "nt":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return f
    except Exception:
        f.close()
        return None

def init_state(wid, courses, max_concurrent=5):
    return {"workshop": wid, "courses": courses, "active": [],
            "done": [], "done_open": [], "last_ct": {},
            "max_concurrent": max_concurrent, "initialized": False}
