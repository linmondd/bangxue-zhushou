"""Build a native zip using the current platform's Python and PyInstaller."""
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build" / "desktop"
DEST = ROOT / "delivery"


def main():
    DEST.mkdir(exist_ok=True)
    name = "帮学助手"
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
            "--name", name, "--windowed", "--onedir", "--paths", str(ROOT),
            "--collect-data", "bangxue", "--collect-all", "playwright",
            "--exclude-module", "mcp", "--osx-bundle-identifier", "com.linmondd.bangxue",
            "--distpath", str(OUT), "--workpath", str(OUT.parent / "pyinstaller"),
            "--specpath", str(OUT.parent)]
    launcher = str(ROOT / "packaging" / "desktop.py")
    if sys.platform == "win32":
        # Ship the browser revision expected by this exact Playwright build.
        with tempfile.TemporaryDirectory(prefix="bangxue-browser-") as tmp:
            browsers = Path(tmp)
            env = {**os.environ, "PLAYWRIGHT_BROWSERS_PATH": str(browsers)}
            subprocess.run([sys.executable, "-m", "playwright", "install", "--no-shell", "chromium"],
                           env=env, check=True)
            if not any(browsers.glob("chromium-*/**/chrome.exe")):
                raise RuntimeError("Windows 构建缺少 Chromium")
            # Do not redistribute Playwright's machine-local cache links.
            for folder in sorted(browsers.iterdir()):
                if folder.is_dir() and not folder.name.startswith("."):
                    args.extend(["--add-data", f"{folder}:browser/{folder.name}"])
            subprocess.run([*args, launcher], cwd=ROOT, check=True)
    else:
        subprocess.run([*args, launcher], cwd=ROOT, check=True)
    if sys.platform == "darwin":
        archive = DEST / f"Bangxue-macOS-{platform.machine()}.zip"
        app = OUT / (name + ".app")
        subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent",
                        str(app), str(archive)], check=True)
    elif sys.platform == "win32":
        shutil.make_archive(str(DEST / "Bangxue-Windows-x64"), "zip", OUT, name)
    else:
        shutil.make_archive(str(DEST / "Bangxue-Linux"), "gztar", OUT, name)


if __name__ == "__main__":
    main()
