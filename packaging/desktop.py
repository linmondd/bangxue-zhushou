"""Double-click launcher for the standalone local control panel."""
import os
from pathlib import Path
import sys


def main():
    # Frozen Playwright otherwise looks for a writable browser inside the app.
    if sys.platform == "darwin":
        cache = Path.home() / "Library" / "Caches"
    elif os.name == "nt":
        cache = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(cache / "ms-playwright"))
    # Optional local site-config command keeps the desktop app self-contained.
    # Launch the packaged panel against an isolated data directory in native
    # acceptance tests, including windowed Windows builds without stdout.
    if len(sys.argv) == 3 and sys.argv[1] == "--test-panel":
        from bangxue import panel
        root = Path(sys.argv[2])
        panel.main(profile_dir=str(root / "profile"), root=root / "state",
                   open_browser=False,
                   ready=lambda url: (root / "url.txt").write_text(url, encoding="utf-8"))
        return
    from bangxue.cli import main as cli
    cli(sys.argv[1:] or ["panel"])


if __name__ == "__main__":
    main()
