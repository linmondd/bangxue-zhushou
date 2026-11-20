"""Kimi WebBridge 驱动（HTTP 127.0.0.1:10086）。"""
import json, time, urllib.request, uuid
from .base import Driver, Tab

class WebBridgeDriver(Driver):
    name = "webbridge"

    def __init__(self, base="http://127.0.0.1:10086/command", session="帮学助手", timeout=20, zoom=100):
        self.base = base
        self.session = session
        self.timeout = timeout
        self.zoom = zoom
        self._current = None
        self._opener_tokens = {}

    def _cmd(self, action, args):
        body = json.dumps({"action": action, "args": args, "session": self.session}).encode("utf-8")
        req = urllib.request.Request(self.base, data=body,
                                     headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            return {"parse_error": str(e)[:300]}

    def available(self):
        try:
            r = self._cmd("list_tabs", {})
            return isinstance(r, dict) and "data" in r
        except Exception:
            return False

    def list_tabs(self):
        r = self._cmd("list_tabs", {})
        if not isinstance(r, dict) or "data" not in r:
            return None
        try:
            return [Tab(t["tabId"], t["url"]) for t in r["data"]["tabs"]]
        except Exception:
            return None

    def open(self, url, new_tab=True):
        before = self.list_tabs() if new_tab else []
        if before is None:
            raise RuntimeError("无法核对打开标签前的浏览器状态")
        r = self._cmd("navigate", {"url": url, "newTab": new_tab, "group_title": "帮学助手"})
        tab_id = None
        try:
            tab_id = r["data"]["tabId"]
        except Exception:
            pass
        if tab_id is None:
            raise RuntimeError("浏览器未返回新页面标识")
        if new_tab and any(t.id == tab_id for t in before):
            raise RuntimeError("浏览器复用了已有标签，已停止操作")
        t = Tab(tab_id, url)
        self._current = t
        return t

    def use(self, tab, retries=None):
        """WebBridge 只能按 URL 选标签，且多标签下常打错——用 current_url 回验重试。"""
        retries = retries if retries is not None else 3
        for _ in range(retries):
            tabs = self.list_tabs() or []
            match = next((t for t in tabs if t.id == tab.id), None)
            if match is None or sum(t.url == match.url for t in tabs) != 1:
                return False
            self._cmd("find_tab", {"url": match.url})
            if self.current_url() == match.url:
                self._current = match
                self.bring_to_front()
                if self.zoom and self.zoom != 100:
                    self.eval(f'document.documentElement.style.zoom="{self.zoom/100:.2f}"')
                return True
            time.sleep(0.3)
        return False

    def mark_opener(self, parent):
        token = uuid.uuid4().hex
        if self.use(parent) and self.eval(f'window.__bangxueOpenerToken = "{token}"') == token:
            self._opener_tokens[parent.id] = token

    def opened_by(self, tab, parent):
        response = self._cmd("list_tabs", {})
        tabs = response.get("data", {}).get("tabs", [])
        if any(t.get("tabId") == tab.id and t.get("openerTabId") == parent.id for t in tabs):
            return True
        token = self._opener_tokens.get(parent.id)
        return bool(token and self.use(tab) and self.eval(
            "(() => {try {return window.opener?.__bangxueOpenerToken} catch {return null}})()"
        ) == token)

    def owned_record(self, tab):
        record = {"id": tab.id, "url": tab.url}
        if self.use(tab) and self.current_url() == tab.url:
            token = uuid.uuid4().hex
            if self.eval(f'window.__bangxuePageToken = "{token}"') == token:
                record["token"] = token
        return record

    def verify_record(self, tab, record):
        return bool(record.get("token") and self.use(tab)
                    and self.eval("window.__bangxuePageToken") == record["token"])

    def current_url(self):
        r = self._cmd("evaluate", {"code": "location.href"})
        if isinstance(r, dict) and "data" in r:
            return r["data"].get("value")
        return None

    def eval(self, js):
        r = self._cmd("evaluate", {"code": js})
        if isinstance(r, dict) and "data" in r:
            return r["data"].get("value", r)
        return r

    def click(self, x, y):
        self._cmd("cdp", {"method": "Input.dispatchMouseEvent", "params": {"type": "mouseMoved", "x": x, "y": y}})
        time.sleep(0.3)
        self._cmd("cdp", {"method": "Input.dispatchMouseEvent", "params": {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1}})
        time.sleep(0.2)
        self._cmd("cdp", {"method": "Input.dispatchMouseEvent", "params": {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1}})

    def hover(self, x, y):
        self._cmd("cdp", {"method": "Input.dispatchMouseEvent", "params": {"type": "mouseMoved", "x": x, "y": y}})
        time.sleep(0.2)

    def close(self, tab):
        if not self.use(tab) or self.current_url() != tab.url:
            return False
        r = self._cmd("close_tab", {})
        return bool(isinstance(r, dict) and r.get("ok"))

    def bring_to_front(self):
        self._cmd("cdp", {"method": "Page.bringToFront", "params": {}})
        time.sleep(0.3)

    def close_all(self):
        return self._cmd("close_session", {})
