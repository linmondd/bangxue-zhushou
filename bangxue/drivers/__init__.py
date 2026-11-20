"""驱动注册与自动选择。"""
from .base import Driver, Tab
from .webbridge import WebBridgeDriver
from .playwright_driver import PlaywrightDriver


def get_driver(name=None, **kwargs):
    """name: webbridge | playwright | None(自动)。"""
    if name in (None, "auto"):
        wb = WebBridgeDriver(**{k: v for k, v in kwargs.items() if k in ("base", "session", "timeout", "zoom")})
        if wb.available():
            return wb
        pw = PlaywrightDriver(**{k: v for k, v in kwargs.items() if k in ("cdp_url", "profile_dir", "headless", "zoom")})
        if pw.available():
            return pw
        return wb  # 都不可用时返回 webbridge（报错信息更明确）
    if name == "webbridge":
        return WebBridgeDriver(**{k: v for k, v in kwargs.items() if k in ("base", "session", "timeout", "zoom")})
    if name == "playwright":
        return PlaywrightDriver(**{k: v for k, v in kwargs.items() if k in ("cdp_url", "profile_dir", "headless", "zoom")})
    raise ValueError(f"未知驱动: {name}")
