"""Installation and sign-in checks shared by the CLI and the local panel."""
import os
from pathlib import Path
import subprocess
from .site_config import is_site_url, site_url


def login_status(driver):
    if not is_site_url(driver.current_url()):
        return "unknown"
    body = driver.eval("document.body ? document.body.innerText : ''")
    if not isinstance(body, str):
        return "unknown"
    if any(label in body for label in ("密码登录", "短信登录", "获取验证码", "验证码")):
        return "login"
    if any(label in body for label in ("退出登录", "我的专题班")):
        return "authenticated"
    return "unknown"


def install_browser():
    # Use the same Node executable and CLI as Playwright's python -m entry
    # point. A frozen desktop application has no standalone Python binary.
    from playwright._impl._driver import compute_driver_executable, get_driver_env
    node, cli = compute_driver_executable()
    log = Path.home() / ".bangxue" / "browser-install.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        with log.open("wb") as output:
            subprocess.run([node, cli, "install", "chromium"], env=get_driver_env(),
                           stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                           creationflags=flags, check=True, timeout=1200)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"浏览器组件安装失败。请查看本机日志 {log}") from exc


def check_session(driver, timeout=10):
    """Check the portal in our temporary tab; release just that handle."""
    import time
    tab = driver.open(site_url("/portal/"), new_tab=True)
    try:
        until = time.monotonic() + timeout
        while True:
            result = login_status(driver)
            if result != "unknown" or time.monotonic() >= until:
                return result
            time.sleep(0.5)
    finally:
        driver.close(tab)
