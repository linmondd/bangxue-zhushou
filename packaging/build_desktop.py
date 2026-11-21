"""Build a native zip using the current platform's Python and PyInstaller."""
from pathlib import Path
import platform
import shutil
import subprocess
import sys

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
    subprocess.run([*args, str(ROOT / "packaging" / "desktop.py")], cwd=ROOT, check=True)
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
