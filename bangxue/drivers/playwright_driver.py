"""Playwright 驱动：支持两种模式
1) connect_over_cdp：连接已开调试端口的 Chrome（需 --remote-debugging-port=9222）
2) persistent：使用专用用户目录启动 Chromium（适合非技术用户，只需登录一次）
"""
import os, time
from weakref import WeakKeyDictionary
from .base import Driver, Tab


class PlaywrightDriver(Driver):
    name = "playwright"

    def __init__(self, cdp_url="http://127.0.0.1:9222", profile_dir=None, headless=False, zoom=100):
        self.cdp_url = cdp_url
        self.profile_dir = profile_dir
        self.headless = headless
        self.zoom = zoom
        self._pw = None
        self._browser = None
        self._context = None
        self._current_page = None
        self._target_ids = WeakKeyDictionary()

    def _ensure(self):
        if self._context is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except Exception as e:
            raise RuntimeError("未安装 playwright：pip install playwright && python -m playwright install chromium") from e
        self._pw = sync_playwright().start()
        try:
            if self.profile_dir:
                self._context = self._pw.chromium.launch_persistent_context(self.profile_dir, headless=self.headless)
            else:
                self._browser = self._pw.chromium.connect_over_cdp(self.cdp_url)
                self._context = self._browser.contexts[0]
        except Exception:
            self.shutdown()
            raise

    def _chromium_installed(self):
        try:
            from playwright.sync_api import sync_playwright
            pw = sync_playwright().start()
            exe = pw.chromium.executable_path
            pw.stop()
            return bool(exe and os.path.exists(exe))
        except Exception:
            return False

    def available(self):
        if self._context is not None:
            return True
        if self.profile_dir:
            # 持久模式：只检查 playwright 与 chromium 是否安装，不启动浏览器
            return self._chromium_installed()
        try:
            self._ensure()
            return True
        except Exception:
            return False

    def _pages(self):
        self._ensure()
        return list(self._context.pages)

    def _tab(self, page):
        if page not in self._target_ids:
            session = self._context.new_cdp_session(page)
            try:
                self._target_ids[page] = session.send("Target.getTargetInfo")["targetInfo"]["targetId"]
            finally:
                session.detach()
        return Tab(self._target_ids[page], page.url)

    def _page(self, tab):
        return next((p for p in self._pages() if self._tab(p).id == tab.id), None)

    def list_tabs(self):
        try:
            pages = self._pages()
            if pages:
                # Pump Chromium events before reading the locally cached page collection.
                pages[0].wait_for_timeout(1)
            return [self._tab(p) for p in self._pages()]
        except Exception:
            return None

    def open(self, url, new_tab=True):
        self._ensure()
        page = self._current_page
        created = new_tab or page is None or page.is_closed()
        if created:
            page = self._context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded")
        except Exception:
            if created:
                page.close()
            raise
        self._current_page = page
        return self._tab(page)

    def use(self, tab, retries=None):
        page = self._page(tab)
        if page is None:
            return False
        self._current_page = page
        page.bring_to_front()
        zoom = "" if not self.zoom or self.zoom == 100 else str(self.zoom / 100)
        page.evaluate("(zoom) => document.documentElement.style.zoom = zoom", zoom)
        return True

    def opened_by(self, tab, parent):
        page = self._page(tab)
        opener = page.opener() if page else None
        return opener is not None and self._tab(opener).id == parent.id

    def current_url(self):
        try:
            return self._current_page.url
        except Exception:
            return None

    def eval(self, js):
        try:
            return self._current_page.evaluate(js)
        except Exception as e:
            return {"error": str(e)[:200]}

    def click(self, x, y):
        # Playwright 鼠标事件是可信事件
        self._current_page.mouse.move(x, y)
        time.sleep(0.3)
        self._current_page.mouse.click(x, y)

    def hover(self, x, y):
        try:
            self._current_page.mouse.move(x, y)
        except Exception:
            pass

    def close(self, tab):
        try:
            page = self._page(tab)
            if page is None or page.url != tab.url:
                return False
            page.close()
            if self._current_page is page:
                self._current_page = None
            return True
        except Exception:
            return False

    def bring_to_front(self):
        try:
            self._current_page.bring_to_front()
        except Exception:
            pass

    def close_all(self):
        try:
            for p in self._pages():
                try:
                    p.close()
                except Exception:
                    pass
            return True
        except Exception:
            return False

    def shutdown(self):
        """释放连接，专用配置使用的浏览器随最后一个上下文关闭。"""
        try:
            if self.profile_dir and self._context is not None:
                self._context.close()
        finally:
            if self._pw is not None:
                self._pw.stop()
            self._pw = self._context = self._browser = self._current_page = None
            self._target_ids.clear()
