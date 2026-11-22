"""Double-click launcher for the standalone local control panel."""
import os
from pathlib import Path
import sys


def verify_bundled_browser():
    """Launch from the frozen payload with a temporary browser profile."""
    from playwright.sync_api import sync_playwright

    bundled = Path(sys._MEIPASS) / "browser"
    with sync_playwright() as playwright:
        executable = Path(playwright.chromium.executable_path).resolve()
        if not executable.is_relative_to(bundled.resolve()):
            raise RuntimeError("Windows 测试没有使用安装包内置的浏览器")
        browser = playwright.chromium.launch(executable_path=str(executable), headless=True)
        try:
            page = browser.new_page()
            page.goto("data:text/html,<title>Bundled Chromium</title>")
            if page.title() != "Bundled Chromium":
                raise RuntimeError("内置浏览器未能打开测试页面")
        finally:
            browser.close()


def main():
    # Windows builds ship Chromium. Source runs and other packages use a cache.
    if sys.platform == "darwin":
        cache = Path.home() / "Library" / "Caches"
    elif os.name == "nt":
        cache = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    bundled = Path(sys._MEIPASS) / "browser" if getattr(sys, "frozen", False) else None
    default = bundled if bundled and bundled.is_dir() else cache / "ms-playwright"
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(default))
    # Launch the packaged panel against an isolated data directory in native
    # acceptance tests, including windowed Windows builds without stdout.
    if len(sys.argv) == 3 and sys.argv[1] == "--test-panel":
        from bangxue import panel
        root = Path(sys.argv[2])
        if sys.platform == "win32":
            try:
                verify_bundled_browser()
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
