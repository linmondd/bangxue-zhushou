"""The learning platform address belongs to the user's local configuration."""
import os
from pathlib import Path
from urllib.parse import urlsplit

from . import state


def _path():
    return Path(os.environ.get("BANGXUE_SITE_CONFIG", Path.home() / ".bangxue" / "site.json"))


def origin(value):
    value = str(value or "").strip()
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or any(ch.isspace() for ch in value) or parsed.query or parsed.fragment:
        raise ValueError("请填写有效的 HTTPS 平台地址")
    return "https://" + parsed.netloc.lower()


def configured():
    value = os.environ.get("BANGXUE_SITE_URL")
    if value is None:
        try:
            value = state.load(_path())["origin"]
        except FileNotFoundError:
            return ""
    return origin(value)


def save(value):
    address = origin(value)
    override = os.environ.get("BANGXUE_SITE_URL")
    if override and origin(override) != address:
        raise ValueError("站点已由启动环境指定，请先修改该配置")
    state.save(_path(), {"origin": address})
    return address


def site_url(path):
    base = configured()
    if not base or not path.startswith("/") or path.startswith("//"):
        raise ValueError("请先在面板保存学习平台地址，或运行 bangxue site --url <HTTPS地址>")
    return base + path


def is_site_url(value):
    try:
        parsed = urlsplit(str(value or ""))
        expected = urlsplit(configured())
        return (parsed.scheme == "https" and parsed.hostname
                and not parsed.username and not parsed.password
                and parsed.netloc.lower() == expected.netloc)
    except ValueError:
        return False
