"""驱动注册与自动选择。"""
from .base import Driver, Tab
from .webbridge import WebBridgeDriver
from .playwright_driver import PlaywrightDriver, installed_windows_chrome


def get_driver(name=None, **kwargs):
    """name: webbridge | playwright | None(自动)。"""
    if name not in (None, "auto", "webbridge", "playwright"):
        raise ValueError(f"未知驱动: {name}")
    if name != "playwright":
        wb = WebBridgeDriver(**{k: v for k, v in kwargs.items() if k in ("base", "session", "timeout", "zoom")})
        if name == "webbridge" or wb.available():
            return wb
    profile = {k: v for k, v in kwargs.items() if k in ("cdp_url", "profile_dir", "headless", "zoom")}
    if profile.get("profile_dir"):
        profile["executable_path"] = installed_windows_chrome()
    pw = PlaywrightDriver(**profile)
    # Auto falls back to the bridge with its existing connection diagnostic.
    return pw if name == "playwright" or pw.available() else wb
