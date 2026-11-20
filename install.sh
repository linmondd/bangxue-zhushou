#!/usr/bin/env bash
# 帮学助手 一键安装（macOS / Linux）
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
PY="${PYTHON:-python3}"

if ! command -v "$PY" >/dev/null 2>&1; then
  echo "❌ 未找到 python3。请先安装 Python 3.9+（https://www.python.org/downloads/），再重新运行本脚本。"
  exit 1
fi

echo "== 帮学助手 一键安装 =="
BASE="$HOME/.bangxue"
VENV="$BASE/venv"
mkdir -p "$BASE" "$HOME/.local/bin"

if [ ! -x "$VENV/bin/python" ]; then
  echo "1/4 创建运行环境…"
  "$PY" -m venv "$VENV" || { echo "❌ 创建虚拟环境失败"; exit 1; }
fi

echo "2/4 安装帮学助手…"
"$VENV/bin/pip" install -q --upgrade pip
WHEEL=$(ls "$DIR"/dist/bangxue-*.whl 2>/dev/null | head -1 || true)
if [ -n "$WHEEL" ]; then
  "$VENV/bin/pip" install -q "$WHEEL" || { echo "❌ 安装失败"; exit 1; }
else
  "$VENV/bin/pip" install -q "$DIR" || { echo "❌ 安装失败"; exit 1; }
fi

echo "3/4 安装 Playwright 与浏览器组件（用于登录和驱动）…"
"$VENV/bin/pip" install -q playwright || echo "（Playwright 安装失败，可稍后手动安装）"
"$VENV/bin/python" -m playwright install chromium >/dev/null 2>&1 || echo "（浏览器组件下载失败，可稍后重试）"

echo "4/4 创建命令入口…"
cat > "$HOME/.local/bin/bangxue" <<EOF
#!/bin/bash
exec "$VENV/bin/bangxue" "\$@"
EOF
chmod +x "$HOME/.local/bin/bangxue"

echo ""
echo "✅ 安装完成！"
echo ""
echo "下一步："
echo "  1) 登录一次：  $HOME/.local/bin/bangxue login"
echo "  2) 环境自检：  $HOME/.local/bin/bangxue doctor"
echo "  3) 开始学习：  $HOME/.local/bin/bangxue run --scope 范围文件.json --state-dir 班级状态 --concurrency 5"
echo ""
echo "提示：如果提示 command not found，请把 $HOME/.local/bin 加入 PATH，或直接使用上面的完整路径。"
