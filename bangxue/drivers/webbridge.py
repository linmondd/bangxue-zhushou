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
        self._owned_urls = {}
        self._active_url = ""

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
        if not new_tab:
            if not self._current or not self.current_matches() or not self.owns(self._current):
                raise RuntimeError("无法核实当前标签归属")
            response = self._cmd("navigate", {"url": url, "newTab": False})
            if response.get("error") or response.get("parse_error") or self.current_url() != url:
                raise RuntimeError("当前标签未确认完成导航")
            self._owned_urls[self._current.id] = url
            self._active_url = url
            return self._current
        before = self.list_tabs()
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
        self._owned_urls[t.id] = t.url
        self._active_url = url
        self.owned_record(t)
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
                self._active_url = match.url
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
        if not token or not self.owns(parent) or not self.use(tab):
            return False
        try:
            value = self.eval("(() => {try {return window.opener?.__bangxueOpenerToken} catch {return null}})()")
        finally:
            self.use(parent)
        return value == token

    def owned_record(self, tab):
        if not self.owns(tab) or not self.use(tab):
            raise RuntimeError("没有可核实的创建凭据")
        token = uuid.uuid4().hex
        if self.eval(f'window.__bangxuePageToken = "{token}"') != token:
            raise RuntimeError("无法保存页面创建凭据")
        record = super().owned_record(tab)
        record["token"] = token
        return record

    def verify_record(self, tab, record):
        return False

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

    def _candidates(self):
        tabs = self.list_tabs() or []
        match = next((t for t in tabs if self._current and t.id == self._current.id), None)
        if match is None or sum(t.url == match.url for t in tabs) != 1:
            return None
        return match.url

    def _select_current(self, url):
        match = self._candidates()
        if match != url:
            raise RuntimeError("当前标签已改变，已停止操作")
        self._cmd("find_tab", {"url": match})
        if self.current_url() != match:
            raise RuntimeError("未能核对当前操作标签")
        self._active_url = match

    def click(self, x, y):
        url = self._candidates()
        if not url:
            raise RuntimeError("无法核对当前操作标签")
        self._cmd("cdp", {"method": "Input.dispatchMouseEvent", "params": {"type": "mouseMoved", "x": x, "y": y}})
        time.sleep(0.3)
        self._cmd("cdp", {"method": "Input.dispatchMouseEvent", "params": {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1}})
        time.sleep(0.2)
        self._cmd("cdp", {"method": "Input.dispatchMouseEvent", "params": {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1}})
        self._active_url = url

    def hover(self, x, y):
        url = self._candidates()
        if not url:
            raise RuntimeError("无法核对当前操作标签")
        self._cmd("cdp", {"method": "Input.dispatchMouseEvent", "params": {"type": "mouseMoved", "x": x, "y": y}})
        time.sleep(0.2)

    def close(self, tab):
        if not self.owns(tab) or not self.use(tab) or self.current_url() != tab.url:
            return False
        # Close the recorded browser target, independent of the current focus.
        result = self._cmd("cdp", {"method": "Target.closeTarget",
                                   "params": {"targetId": tab.id}})
        data = result.get("data", {}) if isinstance(result, dict) else {}
        if data.get("result") is not True:
            return False
        self._owned_urls.pop(tab.id, None)
        if self._current and self._current.id == tab.id:
            self._current = None
            self._active_url = ""
        return True

    def bring_to_front(self):
        self._cmd("cdp", {"method": "Page.bringToFront", "params": {}})
        time.sleep(0.3)
