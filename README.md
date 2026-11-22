# 帮学助手

帮学助手是一款本机学习任务管理工具。Agent 准备环境、查找班级并运行选定的学习任务，用户在面板查看进度和待处理事项。账号、验证码和课程数据留在用户自己的电脑上，学习平台地址也仅保存在本机。

## 下载与使用

- [下载 Windows x64 版](https://github.com/linmondd/bangxue-zhushou/releases/latest/download/Bangxue-Windows-x64.zip)
- [下载 macOS Apple 芯片版](https://github.com/linmondd/bangxue-zhushou/releases/latest/download/Bangxue-macOS-arm64.zip)
- [查看发布记录](https://github.com/linmondd/bangxue-zhushou/releases)

完整解压后双击「帮学助手」，浏览器会打开学习工作台。将平台地址和希望学习的栏目或班级告诉同一台电脑上的 Agent。Windows 版优先使用已安装的 Google Chrome。平台需要首次登录、验证码或人工完成课程时，请按工作台提示处理。工作台可直接暂停任务，也可展开「手动设置」独立使用。运行期间保持助手运行和电脑唤醒。

## Agent 操作

将这句话发给能在你电脑上运行程序的 Agent。

> 请从 https://github.com/linmondd/bangxue-zhushou 安装并启动帮学助手。按我提供的平台和班级范围，用 Agent 命令准备环境、查找班级并运行任务。需要我登录或验证时提醒我，其余进度和结果放到学习工作台。

可通过 `bangxue panel --background` 在后台启动，或者双击桌面版打开结果页。Agent 使用以下命令查询和操作同一任务。

```sh
bangxue agent prepare --url "https://learning.example.test"
bangxue agent discover
bangxue agent discover --tab "栏目名称"
bangxue agent start --tab "栏目名称" --id "从列表取得的班级编号"
bangxue agent status
bangxue agent pause
bangxue agent resume
bangxue agent retry
```

用户明确授权整个栏目时，可用 `start --tab "栏目名称" --all`。若 `login` 为 `opened`，等待本人完成登录后重跑 `prepare`，再继续原指令。若返回 `busy`，用 `status` 跟进。任务运行由本机助手维持。

桌面安装包内的可执行程序也接收同样的参数。调用 Windows 的 `帮学助手.exe` 时，在子命令前提供 `agent --output "本机结果.json" status`，即可从本机文件读取 JSON。使用 MCP 的客户端可调用 `bangxue_agent` 执行同一组操作。

## 源码与独立命令

Python 3.9+ 支持 CLI 与控制面板，MCP 需 Python 3.10+。macOS/Linux 运行 `bash install.sh`，Windows PowerShell 运行 `.\install.ps1`，随后执行 `bangxue panel`。MCP 安装选项为 `bash install.sh --mcp` 或 `.\install.ps1 -Mcp`。

其他电脑或 Agent 使用同一份公开源码安装。真实平台地址在首次使用时由用户自行配置，不包含在仓库或安装命令中。没有 Python 的用户使用对应系统的桌面压缩包。

配置本机平台可运行 `bangxue site --url "你的学习平台 HTTPS 地址"`。已有 WebBridge 环境的 CLI 可复用已登录浏览器，未配置时使用 Playwright 专用资料目录。

```sh
bangxue scope --tab "平台上的栏目名称" --out bangxue_scope.json
bangxue run --scope bangxue_scope.json --state-dir bangxue_classes
bangxue status --scope bangxue_scope.json --state-dir bangxue_classes
bangxue stop --scope bangxue_scope.json --state-dir bangxue_classes
bangxue resume --scope bangxue_scope.json --state-dir bangxue_classes
```

`run` 默认一分钟一轮，按所选范围逐班巡检，整班完成需保存完整课表凭据。运行时间和完成摘要保存在本地状态目录。外部调度可用 `run --once`。`watch` 兼容现有在播班巡检，`capture/start/status/monitor` 可继续使用。不同进程尽量使用同一驱动，避免重复接管。

已有任务可以运行 `bangxue audit --scope <范围文件>`，重新打开每班完整课程表进行独立复核。报告写入本地 `audit.json`，不会改写原任务的完成记录。

页面操作依赖平台的具体结构。当前公开版本适合与现有实现兼容的课程页面，其他平台需要完成相应适配和验证。

面板运行期间每分钟自动巡检，日志至少每十分钟写一次汇总。退出后再次打开应用时，Agent 可以从已保存的任务继续。

旧版独立 MCP 工具默认单轮调用，设置 `continuous=true` 持续巡检，参数 `interval_min` 默认为 1。将客户端 stdio command 设置为安装后的 `bangxue-mcp` 绝对路径。`BANGXUE_SITE_URL` 可指定当前客户端的平台地址。

## 验证

```sh
python -m pip install ".[playwright,mcp]" "pyinstaller>=6,<7"
python -m playwright install chromium
python -m unittest discover -s tests -v
python packaging/build_desktop.py
python packaging/smoke_desktop.py
```

[新手使用说明](新手使用说明.md) · [设计说明](docs/设计说明.md) · [隐私与安全](docs/隐私与安全.md)
