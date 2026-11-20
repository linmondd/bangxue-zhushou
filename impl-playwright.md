# 刷课 · Playwright 驱动说明（通用移植首选）

> 状态：**已实现，未在真实刷课中实测**（连接/点击/关闭的代码路径已编译通过）。
> 用途：给没装 Kimi WebBridge 的人/环境使用。Playwright 的 `page.click()` 是**可信点击**，能点动「我要学习」。

## 原理
连接用户**已登录的 Chrome**（不是另开无痕浏览器），复用其登录态：
- Chrome 需以 `--remote-debugging-port=9222` 启动（或使用 Playwright 的持久化用户目录）
- 驱动 `PlaywrightDriver` 通过 `connect_over_cdp("http://127.0.0.1:9222")` 接入

## 启动已登录的 Chrome（macOS 示例）
```bash
# 先完全退出 Chrome，再以调试端口启动（会沿用你的用户资料，保持登录）
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/.chrome-bangxue"
```
> 首次用新的 user-data-dir 需要重新登录 u.ccb.com；也可以指向你日常使用的 profile（不同版本路径不同）。

## 安装与使用
```bash
pip install playwright        # 仅连接已开 Chrome，不需要 playwright install
cd <本 skill 目录>
python -m bangxue --driver playwright status --state bangxue_state.json
python -m bangxue --driver playwright monitor --state bangxue_state.json
```
或安装后：`pip install -e .` → `bangxue --driver playwright ...`

## 与 WebBridge 的差异（为什么更稳）
| 能力 | WebBridge | Playwright |
|---|---|---|
| 标签定位 | 只能按 URL，多标签易错（靠回验重试） | `page` 对象稳定，按 URL 精确找 |
| 可信点击 | 需 CDP `Input.dispatchMouseEvent` | `page.mouse.click` 原生可信 |
| 关闭指定标签 | 只能关“当前标签”（关前回验） | `page.close()` 精确关闭 |
| 焦点模拟 | `Page.bringToFront` | `page.bring_to_front()` |
| 依赖 | Kimi WebBridge 扩展+守护进程 | `pip install playwright` |

## 注意
- `connect_over_cdp` 需要 Chrome 以调试端口启动；普通打开的 Chrome 连不上。
- 若目标机器不允许开调试端口，可改用 Playwright 持久化上下文（会另开一个浏览器实例，需要重新登录）。
- 该驱动与 WebBridge 实现同一契约（见 SKILL.md「工具适配契约」），流程层无需改动。
