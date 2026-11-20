# 变更记录

## 0.2.0

- 新增桌面控制面板、按班级勾选和可选并发，以及原生应用构建流程。
- 完整读取分页课程表，核对范围、页面归属与完成证据，暂停、续跑及异常汇总复用同一套状态。
- CLI 的 run 默认持续巡检，外部定时调用改用 --once。MCP 保留单轮入口，并提供后台持续模式。

## 0.1.1 — 2026-11-20

- 删除 `scripts/` 旧脚本（与 `bangxue/` 重复且带硬编码），文档只指向唯一实现。
- 新增 `.gitignore`：状态文件、范围文件、登录态、日志一律不入库。
- 补充开源仓库说明与隐私边界；无行为变更。
- 安装包重建并在全新虚拟环境复验。

## 0.1.0 — 2026-11-20

- 首个可用版本：CLI（capture/start/status/scope/stop/resume/login/doctor/run/monitor）、
  MCP 服务、WebBridge / Playwright 双驱动、范围自动续班、进度汇总与暂停恢复。
- 一键安装：`install.sh`（macOS/Linux）、`install.ps1`（Windows）。
