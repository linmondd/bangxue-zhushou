"""Installation and sign-in checks shared by the CLI and the local panel."""
import subprocess
from urllib.parse import urlsplit


def login_status(driver):
    url = urlsplit(driver.current_url() or "")
    if url.scheme != "https" or url.hostname != "u.ccb.com":
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
    subprocess.run([node, cli, "install", "chromium"], env=get_driver_env(),
                   check=True, timeout=1200)


def check_session(driver, timeout=10):
    """Check the portal in our temporary tab; release just that handle."""
    import time
    tab = driver.open("https://u.ccb.com/portal/", new_tab=True)
    try:
        until = time.monotonic() + timeout
        while True:
            result = login_status(driver)
            if result != "unknown" or time.monotonic() >= until:
                return result
            time.sleep(0.5)
    finally:
        driver.close(tab)
