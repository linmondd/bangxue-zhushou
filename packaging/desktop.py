"""Double-click launcher for the standalone local control panel."""
import os
from pathlib import Path
import sys


def verify_installed_chrome(root):
    """Exercise the desktop browser driver with an isolated test profile."""
    from bangxue.panel import BrowserBackend
    from playwright.sync_api import Error

    with_chrome = BrowserBackend(root / "chrome-profile")
    driver = with_chrome.browser()
    if driver.executable_path is None:
        raise RuntimeError("Windows 测试未检测到系统 Google Chrome")
    driver.headless = True
    try:
        driver.open("data:text/html,<title>Installed Chrome</title>")
        if driver.eval("document.title") != "Installed Chrome":
            raise RuntimeError("系统 Google Chrome 未能打开测试页面")
    finally:
        if driver._browser is not None and driver._process is not None:
            try:
                driver._browser.new_browser_cdp_session().send("Browser.close")
            except Error:
                pass
        with_chrome.close()


def main():
    # Use a writable cache when the desktop app needs to install Chromium.
    if sys.platform == "darwin":
        cache = Path.home() / "Library" / "Caches"
    elif os.name == "nt":
        cache = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(cache / "ms-playwright"))
    # Launch the packaged panel against an isolated data directory in native
    # acceptance tests, including windowed Windows builds without stdout.
    if len(sys.argv) == 3 and sys.argv[1] == "--test-panel":
        from bangxue import panel
        root = Path(sys.argv[2])
        if sys.platform == "win32":
            try:
                verify_installed_chrome(root)
            except Exception:
                import traceback
                (root / "browser-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
                return
        panel.main(profile_dir=str(root / "profile"), root=root / "state",
                   open_browser=False,
                   ready=lambda url: (root / "url.txt").write_text(url, encoding="utf-8"))
        return
    from bangxue.cli import main as cli
    cli(sys.argv[1:] or ["panel"])


if __name__ == "__main__":
    main()
