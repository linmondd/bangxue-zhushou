"""Playwright 驱动：支持两种模式
1) connect_over_cdp：连接已开调试端口的 Chrome（需 --remote-debugging-port=9222）
2) persistent：使用专用用户目录启动 Chromium（适合非技术用户，只需登录一次）
"""
import os, time
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

    def _ensure(self):
        if self._context is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except Exception as e:
            raise RuntimeError("未安装 playwright：pip install playwright && python -m playwright install chromium") from e
        self._pw = sync_playwright().start()
        if self.profile_dir:
            self._context = self._pw.chromium.launch_persistent_context(self.profile_dir, headless=self.headless)
        else:
            self._browser = self._pw.chromium.connect_over_cdp(self.cdp_url)
            self._context = self._browser.contexts[0]

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
        pages = list(self._context.pages)
        if not pages:
            pages = [self._context.new_page()]
        return pages

    def list_tabs(self):
        try:
            return [Tab(p.url, p.url) for p in self._pages()]
        except Exception:
            return None

    def open(self, url, new_tab=True):
        self._ensure()
        page = self._context.new_page()
        page.goto(url, wait_until="domcontentloaded")
        self._current_page = page
        return Tab(page.url, page.url)

    def use(self, tab, retries=10):
        for _ in range(retries):
            for p in self._pages():
                if p.url == tab.url:
                    self._current_page = p
                    try:
                        p.bring_to_front()
                    except Exception:
                        pass
                    try:
                        z = "" if (not self.zoom or self.zoom == 100) else f"{self.zoom/100.0:.2f}"
                        p.evaluate(f'document.documentElement.style.zoom="{z}"')
                    except Exception:
                        pass
                    return True
            time.sleep(0.5)
        return False

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
        if not self.use(tab):
            return False
        try:
            self._current_page.close()
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
