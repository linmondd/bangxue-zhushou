# 变更记录

## 0.1.2 — 2026-11-20

- 修复 `start` 命令把「同时播放上限」误当成「本次最多新开几门」：已在播 5 门时再执行
  `--concurrency 10` 会多开 10 门。现在按「总上限 − 已在播」计算补位数量。
- 该问题只影响手动 `start`；巡检补位原本就是按总量控制，夜间自动续班不受影响。

## 0.1.1 — 2026-11-20

- 删除 `scripts/` 旧脚本（与 `bangxue/` 重复且带硬编码），文档只指向唯一实现。
- 新增 `.gitignore`：状态文件、范围文件、登录态、日志一律不入库。
- 补充开源仓库说明与隐私边界；无行为变更。
- 安装包重建并在全新虚拟环境复验。

## 0.1.0 — 2026-11-20

- 首个可用版本：CLI（capture/start/status/scope/stop/resume/login/doctor/run/monitor）、
  MCP 服务、WebBridge / Playwright 双驱动、范围自动续班、进度汇总与暂停恢复。
- 一键安装：`install.sh`（macOS/Linux）、`install.ps1`（Windows）。
