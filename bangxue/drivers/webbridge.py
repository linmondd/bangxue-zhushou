"""Kimi WebBridge 驱动（HTTP 127.0.0.1:10086）。"""
import json, time, urllib.request
from .base import Driver, Tab

class WebBridgeDriver(Driver):
    name = "webbridge"

    def __init__(self, base="http://127.0.0.1:10086/command", session="帮学助手", timeout=20, zoom=100):
        self.base = base
        self.session = session
        self.timeout = timeout
        self.zoom = zoom
        self._current = None

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
        r = self._cmd("navigate", {"url": url, "newTab": new_tab, "group_title": "帮学助手"})
        tab_id = None
        try:
            tab_id = r["data"]["tabId"]
        except Exception:
            pass
        t = Tab(tab_id, url)
        self._current = t
        return t

    def use(self, tab, retries=None):
        """按 tabId 查它现在的真实 URL，再 find_tab 选中；页面跳转后也不会找错。"""
        if retries is None:
            n = len(self.list_tabs() or [])
            retries = min(60, max(10, n * 3))
        for _ in range(retries):
            tabs = self.list_tabs() or []
            cur = next((t for t in tabs if tab.id and t.id == tab.id), None)
            target = cur.url if cur else tab.url
            self._cmd("find_tab", {"url": target})
            time.sleep(0.5)
            if self.current_url() == target:
                self._current = Tab(tab.id, target)
                # 焦点模拟：让后台标签自认为前台，视频流才会加载（关键）
                self.bring_to_front()
                # 可选页面缩放（等效浏览器比例缩小），不影响用户浏览器设置；100 时清除
                try:
                    z = "" if (not self.zoom or self.zoom == 100) else f"{self.zoom/100.0:.2f}"
                    self.eval(f'document.documentElement.style.zoom="{z}"')
                except Exception:
                    pass
                return True
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

    def click(self, x, y):
        if self._current:
            self.use(self._current)
        self._cmd("cdp", {"method": "Input.dispatchMouseEvent", "params": {"type": "mouseMoved", "x": x, "y": y}})
        time.sleep(0.3)
        self._cmd("cdp", {"method": "Input.dispatchMouseEvent", "params": {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1}})
        time.sleep(0.2)
        self._cmd("cdp", {"method": "Input.dispatchMouseEvent", "params": {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1}})

    def hover(self, x, y):
        if self._current:
            self.use(self._current)
        self._cmd("cdp", {"method": "Input.dispatchMouseEvent", "params": {"type": "mouseMoved", "x": x, "y": y}})
        time.sleep(0.2)

    def close(self, tab):
        if not self.use(tab):
            return False
        time.sleep(0.2)
        r = self._cmd("close_tab", {})
        return bool(isinstance(r, dict) and r.get("ok"))

    def bring_to_front(self):
        self._cmd("cdp", {"method": "Page.bringToFront", "params": {}})
        time.sleep(0.3)

    def close_all(self):
        return self._cmd("close_session", {})
