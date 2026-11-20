"""Launch the actual frozen GUI and exercise its local HTTP entry point."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib import request

OUT = Path(__file__).resolve().parents[1] / "build" / "desktop"
if sys.platform == "darwin":
    executable = OUT / "帮学助手.app/Contents/MacOS/帮学助手"
else:
    executable = OUT / "帮学助手/帮学助手.exe"

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    proc = subprocess.Popen([str(executable), "--test-panel", tmp])
    try:
        for _ in range(240):
            if (root / "url.txt").is_file():
                break
            if proc.poll() is not None:
                raise RuntimeError(f"Desktop application exited with {proc.returncode}")
            time.sleep(.25)
        link = (root / "url.txt").read_text(encoding="utf-8")
        url, token = link.split("#", 1)
        with request.urlopen(url, timeout=10) as page:
            assert "帮学助手" in page.read().decode()
        req = request.Request(url.rstrip("/") + "/api/state", headers={"X-Panel-Token": token})
        with request.urlopen(req, timeout=10) as state:
            assert isinstance(json.load(state), dict)
        print("Packaged panel served its UI and authenticated state")
    finally:
        proc.terminate()
        proc.wait(timeout=30)
