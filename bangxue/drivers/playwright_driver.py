"""Playwright 驱动：支持两种模式
1) connect_over_cdp：连接已开调试端口的 Chrome（需 --remote-debugging-port=9222）
2) persistent：使用专用用户目录启动 Chromium（适合非技术用户，只需登录一次）
"""
import os, subprocess, time, uuid
from pathlib import Path
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
        self._owned_urls = {}
        self._owned_pages = {}
        self._active_url = ""
        self._startup_tab = None
        self._process = None

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
                self._connect_profile()
            else:
                self._browser = self._pw.chromium.connect_over_cdp(self.cdp_url)
                self._context = self._browser.contexts[0]
        except Exception:
            self.shutdown()
            raise

    def _connect_profile(self):
        # Playwright-owned persistent browsers terminate with the driver, including
        # any tabs the user opens in them. Attach to a separate Chromium process.
        profile = Path(self.profile_dir).expanduser().resolve()
        profile.mkdir(parents=True, exist_ok=True)
        port_file = profile / "DevToolsActivePort"

        def connect():
            try:
                port, path = port_file.read_text(encoding="ascii").splitlines()[:2]
                if not port.isdecimal() or not path.startswith("/devtools/browser/"):
                    return False
                endpoint = f"ws://127.0.0.1:{port}{path}"
                self._browser = self._pw.chromium.connect_over_cdp(endpoint, timeout=1500)
                self._context = self._browser.contexts[0]
                return True
            except (OSError, ValueError):
                return False
            except Exception:
                return False

        if connect():
            return
        # Distinguish our startup blank from any pre-existing/restored blank tab.
        blank = "about:blank#bangxue-" + uuid.uuid4().hex
        args = [self._pw.chromium.executable_path, f"--user-data-dir={profile}",
                "--remote-debugging-port=0", "--remote-debugging-address=127.0.0.1",
                "--no-first-run", "--no-default-browser-check"]
        if self.headless:
            args.append("--headless")
        if os.name != "nt" and os.getuid() == 0:
            args.append("--no-sandbox")
        detached = ({"creationflags": subprocess.DETACHED_PROCESS} if os.name == "nt"
                    else {"start_new_session": True})
        self._process = subprocess.Popen([*args, blank], stdin=subprocess.DEVNULL,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **detached)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if connect():
                page = next((p for p in self._context.pages if p.url == blank), None)
                if page is not None:
                    page.goto("about:blank")
                    self._startup_tab = page
                return
            if self._process.poll() is not None:
                break
            time.sleep(.1)
        raise RuntimeError("无法连接专用 Chromium 配置，请核对该配置是否已被其他浏览器占用")

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
            self._active_url = url
        if not created and (not self.owns(self._tab(page)) or not self.current_matches()):
            raise RuntimeError("无法核实当前标签归属")
        try:
            page.goto(url, wait_until="domcontentloaded")
        except Exception:
            if created:
                page.close()
            raise
        self._current_page = page
        tab = self._tab(page)
        self._owned_pages[tab.id] = page
        self._owned_urls[tab.id] = tab.url
        return tab

    def use(self, tab, retries=None):
        page = self._page(tab)
        if page is None:
            return False
        self._current_page = page
        page.bring_to_front()
        self._active_url = page.url
        zoom = "" if not self.zoom or self.zoom == 100 else str(self.zoom / 100)
        page.evaluate("(zoom) => document.documentElement.style.zoom = zoom", zoom)
        return True

    def _select_current(self, url):
        if self._current_page is None or self._current_page.is_closed():
            raise RuntimeError("未能核对当前操作标签")
        if self.current_url() != url or not self.owns(self._tab(self._current_page)):
            raise RuntimeError("未能核对当前操作标签")
        self._active_url = url

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

    def owns(self, tab):
        page = self._owned_pages.get(tab.id)
        return page is not None and not page.is_closed() and self._page(tab) is page

    def claim_popup(self, tab, parent):
        if not super().claim_popup(tab, parent):
            return False
        self._owned_pages[tab.id] = self._page(tab)
        return True

    def owned_record(self, tab):
        record = super().owned_record(tab)
        page = self._owned_pages[tab.id]
        # A reconnected driver must prove that this is the original document.
        record["token"] = page.evaluate(
            "(token) => window.__bangxuePageToken ||= token", uuid.uuid4().hex)
        return record

    def verify_record(self, tab, record):
        if record.get("id") != tab.id or record.get("url") != tab.url:
            return False
        page = self._page(tab)
        if page is None:
            return False
        if not record.get("token"):
            return self.owns(tab)
        if record.get("driver") != self.name or page.evaluate(
                "() => window.__bangxuePageToken") != record["token"]:
            return False
        self._owned_pages[tab.id] = page
        self._owned_urls[tab.id] = tab.url
        return True

    def close(self, tab):
        try:
            page = self._page(tab)
            if not self.owns(tab) or page is None or page.url != tab.url:
                return False
            page.close()
            self._owned_urls.pop(tab.id, None)
            self._owned_pages.pop(tab.id, None)
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

    def shutdown(self):
        """断开 CDP；专用窗口里用户新开的页面可继续使用。"""
        try:
            if self.profile_dir and self._context is not None:
                self.close_all()
                if self._startup_tab is not None:
                    page = self._startup_tab
                    if not page.is_closed() and page.url == "about:blank":
                        page.close()
        finally:
            if self._pw is not None:
                self._pw.stop()
            self._pw = self._context = self._browser = self._current_page = None
            self._target_ids.clear()
            self._owned_urls.clear()
            self._owned_pages.clear()
            self._startup_tab = None
            if self._process is not None:
                self._process.poll()
                self._process = None
