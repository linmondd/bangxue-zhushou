"""Launch the actual frozen GUI and exercise its local HTTP entry point."""
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time
from urllib import request
from zipfile import ZipFile

DELIVERY = Path(__file__).resolve().parents[1] / "delivery"


with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
    root = Path(tmp)
    unpacked = root / "中文 解压目录"
    unpacked.mkdir()
    env = os.environ.copy()
    env["BANGXUE_PANEL_ROOT"] = str(root / "state")
    if sys.platform == "darwin":
        archive = DELIVERY / f"Bangxue-macOS-{platform.machine()}.zip"
        subprocess.run(["ditto", "-x", "-k", str(archive), str(unpacked)], check=True)
        executable = unpacked / "帮学助手.app/Contents/MacOS/帮学助手"
    elif sys.platform == "win32":
        with ZipFile(DELIVERY / "Bangxue-Windows-x64.zip") as archive:
            archive.extractall(unpacked)
        executable = unpacked / "帮学助手/帮学助手.exe"
        env["PLAYWRIGHT_BROWSERS_PATH"] = str(root / "empty-cache")
    else:
        raise SystemExit("当前测试支持 macOS 和 Windows 桌面包")
    proc = subprocess.Popen([str(executable), "--test-panel", tmp], env=env)
    try:
        link_file = root / "url.txt"
        browser_error = root / "browser-error.txt"
        for _ in range(240):
            if browser_error.is_file():
                raise RuntimeError(browser_error.read_text(encoding="utf-8"))
            if link_file.is_file() and "#" in link_file.read_text(encoding="utf-8"):
                break
            if proc.poll() is not None:
                raise RuntimeError(f"Desktop application exited with {proc.returncode}")
            time.sleep(.25)
        else:
            raise RuntimeError("打包版控制面板未在 60 秒内启动")
        link = link_file.read_text(encoding="utf-8")
        url, token = link.split("#", 1)
        with request.urlopen(url, timeout=10) as page:
            assert "帮学助手" in page.read().decode()
        req = request.Request(url.rstrip("/") + "/api/state", headers={"X-Panel-Token": token})
        for _ in range(60):
            with request.urlopen(req, timeout=10) as response:
                state = json.load(response)
            if not state["busy"]:
                break
            time.sleep(.25)
        else:
            raise RuntimeError("打包版环境检查超时")
        if sys.platform == "win32":
            assert state["setup"].get("chromium") is True, state["error"]
            assert state["setup"].get("browser_name") == "Google Chrome", state["setup"]
            assert not (root / "empty-cache").exists()
            print("Installed Google Chrome launched with an empty Playwright browser cache")
        result_path = root / "任务结果.json"
        subprocess.run([str(executable), "agent", "--output", str(result_path), "status"],
                       env=env, check=True, timeout=30)
        result = json.loads(result_path.read_text(encoding="utf-8"))
        assert result["setup"] == state["setup"], result
        print("Packaged Agent command read the same state as the panel")
    finally:
        proc.terminate()
        proc.wait(timeout=30)
