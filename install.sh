#!/usr/bin/env bash
set -euo pipefail
dir="$(cd "$(dirname "$0")" && pwd)"
base="${BANGXUE_HOME:-$HOME/.bangxue}"
bin="${BANGXUE_BIN_DIR:-$HOME/.local/bin}"
python="${PYTHON:-python3}"
extra=playwright
case "${1:-}" in
  --mcp) extra=playwright,mcp ;;
  "") ;;
  *) echo "用法：bash install.sh [--mcp]" >&2; exit 2 ;;
esac
if ! command -v "$python" >/dev/null; then
  echo "源码安装需要 Python 3.9+，也可以使用已打包的控制面板。" >&2
  exit 1
fi
mkdir -p "$base" "$bin"
venv="$base/venv"
if [ ! -x "$venv/bin/python" ]; then "$python" -m venv "$venv"; fi
"$venv/bin/python" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else "请使用 Python 3.9 或更高版本")'
if [[ "$extra" == *,mcp ]]; then
  "$venv/bin/python" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else "MCP 需要 Python 3.10+，请使用新版 Python 与新的 BANGXUE_HOME")'
fi
echo "正在安装本版本及浏览器组件…"
# Build from this checkout, so a historical dist wheel cannot override edits.
"$venv/bin/python" -m pip install "$dir[$extra]"
"$venv/bin/python" -m playwright install chromium
"$venv/bin/python" -c 'from bangxue import panel; from bangxue.drivers.playwright_driver import PlaywrightDriver; assert PlaywrightDriver(profile_dir="check").available(), "浏览器组件尚未就绪"'
ln -sf "$venv/bin/bangxue" "$bin/bangxue"
if [[ "$extra" == *,mcp ]]; then
  "$venv/bin/python" -c 'from mcp.server.fastmcp import FastMCP'
  ln -sf "$venv/bin/bangxue-mcp" "$bin/bangxue-mcp"
  echo "MCP 命令入口：$bin/bangxue-mcp"
fi
echo "安装完成。打开控制面板：\"$bin/bangxue\" panel"
