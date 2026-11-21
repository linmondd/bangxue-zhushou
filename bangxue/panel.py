"""本地学习控制面板，浏览器操作由一个专属线程顺序执行。"""

import copy
import os
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import re
import secrets
import subprocess
import sys
import threading
import time
import webbrowser
from collections import deque
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from . import flow, runner, state, site_config
from .drivers.playwright_driver import PlaywrightDriver


def read(path, default):
    try:
        return state.load(path)
    except FileNotFoundError:
        return default


class BrowserBackend:
    def __init__(self, profile_dir):
        self.profile = str(profile_dir)
        self.driver = None

    def browser(self):
        if self.driver is None:
            self.driver = PlaywrightDriver(profile_dir=self.profile, headless=False)
        return self.driver

    def setup(self):
        installed = importlib.util.find_spec("playwright") is not None
        # A dependency probe creates a temporary Playwright runtime. Keep it
        # separate from the live sync runtime held by the browser worker.
        with ThreadPoolExecutor(max_workers=1) as pool:
            chromium = installed and pool.submit(PlaywrightDriver(profile_dir=self.profile).available).result()
        return {"python": sys.version.split()[0], "playwright": installed, "chromium": chromium}

    def repair(self):
        from .environment import install_browser
        if importlib.util.find_spec("playwright") is None:
            if getattr(sys, "frozen", False):
                raise RuntimeError("安装包缺少 Playwright，请重新运行帮学助手安装程序。")
            subprocess.run([sys.executable, "-m", "pip", "install", "playwright>=1.40"],
                           check=True, timeout=600)
        install_browser()

    def close(self):
        if self.driver is not None:
            self.driver.shutdown()
            self.driver = None

    def login(self):
        try:
            self.browser().open(site_config.site_url("/portal/"), new_tab=True)
        except Exception:
            # A user may close the last window between visits. A healthy
            # browser with surviving pages must be left alone on a network error.
            if self.driver and self.driver.list_tabs():
                raise
            self.close()
            self.browser().open(site_config.site_url("/portal/"), new_tab=True)

    def verify(self):
        from .environment import check_session, login_status
        current = login_status(self.browser())
        return current if current == "authenticated" else check_session(self.browser())

    def tabs(self):
        return flow.read_library_tabs(self.browser())

    def classes(self, tab):
        return flow.read_library_classes(self.browser(), tab)

    def cycle(self, scope, directory, log, concurrency):
        return runner.run_cycle(self.browser(), str(scope), str(directory), concurrency, log=log)

    def pause(self, scope, directory, log):
        from .control import stop
        result = stop(self.browser(), str(scope), str(directory), log=log)
        if result != "paused":
            raise RuntimeError("未能完全暂停，请查看运行记录。")

    def resume(self, scope, directory, log):
        from .control import resume
        result = resume(str(scope), str(directory), log=log)
        if result != "running":
            raise RuntimeError("未能恢复任务，请查看运行记录。")


def class_rows(scope, directory):
    progress = read(directory / "_scope_state.json", {})
    done = {wid for wid in progress.get("done", []) if state.has_evidence(progress.get("class_evidence", {}), wid)}
    skipped = progress.get("skipped", {})
    rows = []
    for item in scope.get("classes", []):
        wid = item["wid"]
        data = read(directory / (wid + ".json"), {})
        courses = data.get("courses", [])
        completed = set(data.get("done", [])) if wid in done else set()
        reason = skipped.get(wid) or data.get("attention_reason") or data.get("paused_reason", "")
        status = ("done" if wid in done else "attention" if reason
                  else "current" if wid == progress.get("current") else "waiting")
        details = []
        for course in courses:
            cid = course.get("cid")
            if status == "done" or (cid and cid in completed):
                label = "已完成"
            elif cid and cid in data.get("failed", {}):
                label = "待处理"
            elif course.get("manual"):
                label = "需人工学习"
            elif not cid:
                label = "未识别课程"
            elif cid in data.get("active", []):
                label = "在播"
            else:
                label = "待学习"
            playback = data.get("playback", {}).get(cid, {})
            detail = " · ".join(str(v) for v in (
                playback.get("resume_status"), playback.get("reason"),
                (f"页面倍速 {playback['label']}" if playback.get("label") else None),
                playback.get("lesson")) if v)
            details.append({"title": course.get("title") or "未命名课程", "label": label, "detail": detail})
        rows.append({"wid": wid, "title": item["title"], "status": status, "reason": reason,
                     "courses": details, "active": len(data.get("active", []))})
    return rows, progress.get("paused_reason", "")


class ActionError(ValueError):
    pass


class PanelAlreadyRunning(RuntimeError):
    pass


class Panel:
    """管理当前范围、历史任务和浏览器工作线程。提交操作与状态切换共用一把锁。"""

    def __init__(self, root, backend=None, profile_dir=None, interval=60):
        self.root = Path(root)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.lockfile = state.acquire_lock(str(self.root / "panel"))
        if self.lockfile is None:
            raise PanelAlreadyRunning("控制面板已在运行")
        self.backend = backend or BrowserBackend(profile_dir or Path.home() / ".bangxue/profile")
        self.interval = interval
        self.cv = threading.Condition()
        self.queue = deque([("setup", {})])
        self.closing = False
        self.busy = "setup"
        self.deadline = None
        self.pause_requested = False
        self.error = ""
        self.setup = {}
        self.login = "unknown"
        self.tabs = []
        self.tab = ""
        self.catalog = []
        try:
            self.index = read(self.root / "tasks.json", {"current": None, "history": []})
            self.task = self._load_task(self.index["current"]) if self.index["current"] else None
            if self.task and self.task.get("site") != site_config.configured():
                self.task["phase"] = "attention"
                self.task["note"] = "请先切换到该任务使用的学习平台地址"
            if self.task and self.task["phase"] == "running":
                self._phase("paused", "上次运行已中断，可继续上次的范围。")
            self.worker = threading.Thread(target=self._worker, name="学习浏览器", daemon=True)
            self.worker.start()
        except BaseException:
            self.lockfile.close()
            raise

    def _dir(self, key):
        if not re.fullmatch(r"[0-9a-f]{32}", key):
            raise ValueError("本地任务编号无效")
        return self.root / key

    def _load_task(self, key):
        task = state.load(self._dir(key) / "task.json")
        if site_config.configured():
            task.setdefault("site", site_config.configured())
        return task

    def _save_task(self):
        state.save(self._dir(self.task["id"]) / "task.json", self.task)

    def _phase(self, phase, note):
        self.task.update(phase=phase, note=note)
        self._save_task()

    def _paths(self):
        folder = self._dir(self.task["id"])
        return folder / "scope.json", folder / "progress"

    def snapshot(self):
        with self.cv:
            result = {"site": site_config.configured(), "setup": self.setup, "login": self.login, "tabs": self.tabs,
                      "tab": self.tab, "catalog": self.catalog, "error": self.error,
                      "busy": self.busy, "pausing": self.pause_requested,
                      "history": self.index["history"], "task": None}
            if self.task:
                scope_path, directory = self._paths()
                rows, reason = class_rows(state.load(scope_path), directory)
                result["task"] = {**self.task, "rows": rows, "reason": reason}
            return copy.deepcopy(result)

    def _confirm(self, payload):
        selected = payload.get("ids")
        if not isinstance(selected, list) or not selected or not all(isinstance(x, str) for x in selected):
            raise ActionError("请至少选择一个班级。")
        if payload.get("tab") != self.tab or not set(selected) <= {x["wid"] for x in self.catalog}:
            raise ActionError("列表已更新，请重新核对班级。")
        concurrency = payload.get("concurrency", 1)
        if type(concurrency) is not int or concurrency not in (1, 3, 5, 10):
            raise ActionError("请选择 1、3、5 或 10 门。")
        ids = set(selected)
        classes = [item for item in self.catalog if item["wid"] in ids]
        key = uuid4().hex
        folder = self._dir(key)
        (folder / "progress").mkdir(parents=True)
        created = time.strftime("%Y-%m-%d %H:%M")
        state.save(folder / "scope.json", {"name": self.tab, "classes": classes, "created_at": created})
        task = {"id": key, "site": site_config.configured(), "concurrency": concurrency, "name": self.tab, "created": created, "phase": "ready",
                "note": "范围已保存，可核对班级后开始。", "logs": []}
        state.save(folder / "task.json", task)
        index = {"current": key, "history": [{"id": key, "name": self.tab, "created": created,
                                              "count": len(classes)}, *self.index["history"]]}
        state.save(self.root / "tasks.json", index)
        self.index, self.task = index, task
        if self.task.get("site") != site_config.configured():
            self.task["phase"], self.task["note"] = "attention", "请先切换到该任务使用的学习平台地址"
        self.catalog = []

    def submit(self, action, payload):
        with self.cv:
            phase = self.task["phase"] if self.task else None
            if self.closing:
                raise ActionError("面板正在关闭。")
            if action in {"start", "pause", "resume", "retry"} and (not self.task or payload.get("id") != self.task["id"]):
                raise ActionError("当前任务已切换，请核对后再操作。")
            if action == "pause" and phase == "running":
                if not self.pause_requested:
                    state.request_pause(self._paths()[1] / "_scope_state.json")
                    self.pause_requested = True
                    self.deadline = None
                    self.queue.append(("pause", {}))
                    self.cv.notify()
                return
            if self.busy or phase == "running" or phase == "attention" and action not in {"retry", "quit"}:
                raise ActionError("请等待当前操作完成，运行中的任务可先暂停。")
            if action == "quit":
                self.closing = True
                self.cv.notify_all()
                return
            if action in {"start", "resume", "retry"}:
                required = {"start": "ready", "resume": "paused", "retry": "attention"}
                if phase != required[action]:
                    raise ActionError("任务状态已更新，请刷新。")
                if not self.setup.get("chromium"):
                    raise ActionError("请先安装浏览器组件。")
                if self.login != "authenticated":
                    raise ActionError("请先点击「检查登录」，如有需要，在学习窗口完成登录。")
                if self.task.get("site") and self.task["site"] != site_config.configured():
                    raise ActionError("当前平台与此任务的学习平台不同")
                self._phase("running", "正在核对已选班级。")
            elif action == "site":
                if self.task and self.task["phase"] in {"running", "ready", "paused", "attention"}:
                    raise ActionError("请先完成当前任务后再更换站点")
                site_config.save(payload.get("url"))
                self.login, self.catalog, self.tabs, self.tab = "unknown", [], [], ""
                self.error = ""
                return
            elif action == "confirm":
                self._confirm(payload)
                self.error = ""
                return
            elif action == "history":
                key = payload.get("id")
                if key not in {v["id"] for v in self.index["history"]}:
                    raise ActionError("找不到此任务。")
                task = self._load_task(key)
                if task.get("site") != site_config.configured():
                    raise ActionError("请先切换到该任务使用的学习平台地址")
                state.save(self.root / "tasks.json", {**self.index, "current": key})
                self.index["current"], self.task = key, task
                self.error = ""
                return
            elif action == "classes":
                tab = payload.get("tab")
                if not isinstance(tab, str) or not tab.strip() or len(tab) > 200:
                    raise ActionError("请选择或填写资源栏目名称。")
                self.catalog, self.tab = [], ""
            elif action == "login":
                self.login = "unknown"
                self.catalog, self.tabs, self.tab = [], [], ""
            elif action not in {"setup", "repair", "verify", "tabs"}:
                raise ActionError("操作无效。")
            if action in {"login", "verify", "tabs", "classes"} and not self.setup.get("chromium"):
                raise ActionError("请先安装浏览器组件。")
            self.busy, self.error = action, ""
            self.queue.append((action, payload))
            self.cv.notify()

    def _log(self, message):
        with self.cv:
            self.task["logs"] = [*self.task["logs"][-49:], time.strftime("%H:%M:%S  ") + str(message)[:500]]
            self._save_task()

    def _cycle(self):
        tick = time.monotonic()
        result = self.backend.cycle(*self._paths(), self._log, self.task.get("concurrency", 5))
        notes = {"complete": "已选班级均已由课程表确认完成。", "running": "等待下一轮核对。",
                 "busy": "另一轮正在核对，稍后将自动重试。", "attention": "请查看班级结果，在学习窗口处理后重试。",
                 "paused": "任务已暂停，请查看原因后继续。"}
        if result not in notes:
            raise RuntimeError("本轮未返回有效结果，请查看学习窗口后重试。")
        with self.cv:
            phase = "running" if result == "busy" else result
            pulse = read(self._paths()[1] / "_heartbeat.json", {})
            last = pulse.get("finished")
            note = notes[result]
            if last:
                note += " 最近巡检 " + time.strftime("%H:%M:%S", time.localtime(last))
            self._phase(phase, note)
            if phase == "running" and not self.pause_requested:
                self.deadline = max(time.monotonic() + 1, tick + self.interval)

    def _execute(self, action, payload):
        if action in {"setup", "repair"}:
            if action == "repair":
                self.backend.close()
                self.backend.repair()
            setup = self.backend.setup()
            with self.cv:
                self.setup = setup
        elif action == "login":
            self.backend.login()
            with self.cv:
                self.login = "opened"
        elif action == "verify":
            status = self.backend.verify()
            with self.cv:
                self.login = status
                if status != "authenticated":
                    self.error = "尚未在学习窗口确认登录。请完成登录及验证，再点击检查。"
        elif action == "tabs":
            tabs = self.backend.tabs()
            with self.cv:
                self.tabs = tabs
                if not tabs:
                    self.error = "未读到资源栏目。请检查学习窗口的登录状态，或填写网站上显示的栏目全名。"
        elif action == "classes":
            tab = payload["tab"].strip()
            classes = self.backend.classes(tab)
            unique = {}
            for item in classes:
                wid = item.get("wid")
                if not isinstance(wid, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", wid):
                    raise ValueError("班级标识无法识别，请重新读取栏目。")
                unique[wid] = {"wid": wid, "title": str(item.get("title") or wid)}
            with self.cv:
                self.tab, self.catalog = tab, list(unique.values())
                if not self.catalog:
                    self.error = "此栏目未读到班级。请核对栏目名称和登录状态，再次读取。"
        elif action == "pause":
            if self.task["phase"] != "complete":
                self.backend.pause(*self._paths(), self._log)
                with self.cv:
                    self._phase("paused", "已暂停，可以从本机记录继续。")
        else:
            if action in {"resume", "retry"}:
                self.backend.resume(*self._paths(), self._log)
            with self.cv:
                if self.pause_requested:
                    return
            self._cycle()

    def _worker(self):
        try:
            while True:
                with self.cv:
                    while not self.queue and not self.closing:
                        delay = None if self.deadline is None else self.deadline - time.monotonic()
                        if delay is not None and delay <= 0:
                            self.queue.append(("cycle", {}))
                            self.deadline = None
                            break
                        self.cv.wait(delay)
                    if self.closing:
                        break
                    action, payload = self.queue.popleft()
                    self.busy = action
                try:
                    self._execute(action, payload)
                except Exception as exc:
                    with self.cv:
                        self.error = (str(exc).split("Call log:")[0].strip() or type(exc).__name__)[:500]
                        if action in {"cycle", "start", "pause", "resume", "retry"}:
                            self._phase("attention", self.error)
                finally:
                    with self.cv:
                        if action == "pause":
                            self.pause_requested = False
                        self.busy = self.queue[0][0] if self.queue else ""
                        self.cv.notify_all()
        finally:
            self.backend.close()

    def close(self):
        with self.cv:
            if self.lockfile.closed:
                return
            if self.task and self.task["phase"] == "running":
                state.request_pause(self._paths()[1] / "_scope_state.json")
            self.closing = True
            self.cv.notify_all()
        self.worker.join()
        self.lockfile.close()


ASSETS = Path(__file__).parent / "panel_assets"


def serve(panel):
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, code, body=b"", content_type="text/plain; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(body)

        def local(self):
            return self.headers.get("Host") == self.server.address

        def authorized(self):
            return secrets.compare_digest(self.headers.get("X-Panel-Token", "").encode(), token.encode())

        def do_GET(self):
            if not self.local():
                return self.reply(403)
            if self.path == "/api/state":
                if not self.authorized():
                    return self.reply(403)
                return self.reply(200, json.dumps(panel.snapshot(), ensure_ascii=False).encode(),
                                  "application/json; charset=utf-8")
            assets = {"/": ("index.html", "text/html"), "/panel.css": ("panel.css", "text/css"),
                      "/panel.js": ("panel.js", "application/javascript")}
            if self.path not in assets:
                return self.reply(404)
            name, mime = assets[self.path]
            self.reply(200, (ASSETS / name).read_bytes(), mime + "; charset=utf-8")

        def do_POST(self):
            if not self.local() or self.headers.get("Origin") != self.server.origin or not self.authorized():
                return self.reply(403)
            if self.path != "/api/action":
                return self.reply(404)
            if self.headers.get_content_type() != "application/json":
                return self.reply(415)
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 100000:
                    return self.reply(413)
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict) or not isinstance(data.get("action"), str):
                    return self.reply(400)
                panel.submit(data["action"], data)
            except (ValueError, UnicodeError) as exc:
                return self.reply(409, str(exc).encode())
            self.reply(200, b"{}", "application/json")
            if data["action"] == "quit":
                self.server.shutdown()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.address = "127.0.0.1:%s" % server.server_port
    server.origin = "http://" + server.address
    server.url = server.origin + "/#" + token
    return server


def _existing_url(root):
    # During a second double-click the first process may still be binding
    # its port, or a dead process may have left an old address behind.
    for _ in range(25):
        url = read(root / "window.json", {}).get("url", "")
        if re.fullmatch(r"http://127[.]0[.]0[.]1:[0-9]+/#[A-Za-z0-9_-]+", url):
            target = urlsplit(url)
            conn = HTTPConnection(target.hostname, target.port, timeout=.4)
            try:
                conn.request("GET", "/api/state", headers={"X-Panel-Token": target.fragment})
                if conn.getresponse().status == 200:
                    return url
            except OSError:
                pass
            finally:
                conn.close()
        time.sleep(.1)
    raise RuntimeError("已有面板正在启动或退出，请稍后重新打开。")


def main(profile_dir=None, *, open_browser=True, ready=None, root=None):
    def show(url):
        if ready:
            ready(url)
        if sys.stdout is not None:
            print("帮学助手已启动，面板地址 " + url, flush=True)
        if open_browser:
            webbrowser.open(url)

    root = Path(root) if root is not None else Path.home() / ".bangxue" / "panel"
    try:
        panel = Panel(root, profile_dir=profile_dir)
    except PanelAlreadyRunning:
        show(_existing_url(root))
        return
    try:
        with serve(panel) as server:
            state.save(root / "window.json", {"url": server.url})
            show(server.url)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                (root / "window.json").unlink(missing_ok=True)
    finally:
        panel.close()
