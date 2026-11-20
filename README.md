# 帮学助手（bangxue-zhushou）

建行学习（u.ccb.com）专题班课程自动巡航：在用户圈定的范围内逐门学习、完成后自动关页并补下一门，整班完成后自动切下一班。只驱动本机**已登录**的浏览器，不调用平台内部接口、不篡改学习记录。

## 一键安装（推荐给非技术用户）
**macOS / Linux**
```bash
bash install.sh                                  # 自动建环境、装 CLI/Playwright、生成命令入口
~/.local/bin/bangxue login                        # 只登录一次（登录态保存到 ~/.bangxue/profile）
~/.local/bin/bangxue doctor                       # 环境自检
~/.local/bin/bangxue run --scope bangxue_scope.json --state-dir bangxue_classes --concurrency 5
```
**Windows（PowerShell）**
```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
%USERPROFILE%\.bangxue\bin\bangxue.cmd login
%USERPROFILE%\.bangxue\bin\bangxue.cmd doctor
%USERPROFILE%\.bangxue\bin\bangxue.cmd run --scope bangxue_scope.json --state-dir bangxue_classes --concurrency 5
```
> 完全不懂技术的用户可以看 **[新手使用说明.md](新手使用说明.md)**：里面有一段「直接发给 Workbuddy」的话，Agent 会帮他装。

## 环境要求（手动安装时）
- Python 3.9+
- 本机 Chrome 已登录 u.ccb.com（或使用 `bangxue login` 的持久化浏览器登录一次）
- 一个浏览器驱动（二选一）：
  - **WebBridge**（当前实测）：Kimi WebBridge 扩展 + 守护进程 `127.0.0.1:10086`
  - **Playwright**（通用）：`pip install playwright`，用 `bangxue login` 打开并登录即可（持久化模式，无需调试端口）

## 安装（手动）
```bash
cd bangxue-zhushou
pip install -e .            # 或 pip install dist/bangxue-0.1.1-py3-none-any.whl
```
安装后获得两个命令：`bangxue`（CLI）和 `bangxue-mcp`（MCP 服务）。

## 快速开始
```bash
# 1) 建范围文件：可从资源库自动生成，或按格式手写
bangxue scope --tab "党的创新理论教育和党性教育资源库" --out bangxue_scope.json
# 2) 范围自动续班（推荐）：刷完一个班自动找下一个
bangxue run --scope bangxue_scope.json --state-dir bangxue_classes --concurrency 5

# 单班操作
bangxue capture --workshop "<专题班链接或ID>" --concurrency 5
bangxue start   --state bangxue_state.json --concurrency 5
bangxue status  --state bangxue_state.json --live
bangxue monitor --state bangxue_state.json

# 可选：页面缩放（控件被弹窗挤出视区时用）
bangxue run ... --zoom 80

# 暂停 / 恢复
bangxue stop   --scope bangxue_scope.json --state-dir bangxue_classes
bangxue resume --scope bangxue_scope.json --state-dir bangxue_classes
```

## 范围文件格式（bangxue_scope.json）
```json
{
  "name": "党的创新理论教育和党性教育资源库",
  "classes": [
    {"wid": "<班级ID>", "title": "班级名"},
    {"wid": "<班级ID>", "title": "班级名"}
  ]
}
```
班级ID 从班级链接 `https://u.ccb.com/workshop/#/myworkshop/detail?id=<班级ID>` 取。

## MCP（供 Workbuddy / Codex / Claude Code 等 Agent 调用）
```json
{"mcpServers": {"bangxue": {"command": "python", "args": ["-m", "bangxue.mcp_server"]}}}
```
工具：`bangxue_capture / bangxue_status / bangxue_start / bangxue_monitor / bangxue_run`。
环境变量：`BANGXUE_STATE`（默认状态文件）、`BANGXUE_ZOOM`（默认 100）。

## 文档
- [设计说明](docs/设计说明.md)：架构、状态机、数据文件、驱动契约、扩展点、已知限制
- [隐私与安全](docs/隐私与安全.md)：数据边界、本地存储、删除方式、上传注意
- [新手使用说明](新手使用说明.md)：给完全不懂技术的人

## 核心规则（务必了解）
- **逐门起播**：打开一门 → 点「我要学习」→ 确认播放时间真的增长 → 才开下一门；失败即停，不批量开页。
- **完成判定**：播放页 100% 不算数，必须回查刷新后的课程表「100%/立即回看」。
- **完成即关**：确认完成后先关该课页面，再开下一门，不堆积页面。
- **已完成不重复学**：每轮先同步课程表，已 100% 的班/课自动跳过。
- **范围自动续班**：整班完成后自动切范围内下一个班，直到全部完成。

## 常见问题
| 现象 | 处理 |
|---|---|
| 找不到播放按钮/进度条 | 顶部弹窗顶动布局；工具会自动关弹窗并重读坐标。仍不行加 `--zoom 80`（或 66/60） |
| 起播后时间不动 | 工具会重试并重新定位播放器；持续失败会报告并停止开新页 |
| 4008/缓冲超时 | 记录进度 → 降并发 → 刷新一次 → 仍失败从课程表重进 |
| 登录失效/验证码 | 工具会暂停并报告，不绕过验证 |
| 页面显示 100% 但课程表没更新 | 保留页面，下一轮再核，不会提前关页 |

## 说明
- 本工具用于帮助管理个人已授权的学习任务，请遵守所在单位的平台使用规则。
- WebBridge 驱动为当前实测实现；Playwright 驱动为设计兼容（需自备调试端口 Chrome）。
