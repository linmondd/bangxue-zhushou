# 帮学助手

帮学助手是一款本机学习任务管理工具。用户在自己的学习平台手动登录，在面板里选择课程范围并查看进度。账号、验证码和课程数据留在用户自己的电脑上，学习平台地址也仅保存在本机。

## 下载与使用

- [下载 Windows x64 版](https://github.com/linmondd/bangxue-zhushou/releases/latest/download/Bangxue-Windows-x64.zip)
- [下载 macOS Apple 芯片版](https://github.com/linmondd/bangxue-zhushou/releases/latest/download/Bangxue-macOS-arm64.zip)
- [查看发布记录](https://github.com/linmondd/bangxue-zhushou/releases)

完整解压后双击「帮学助手」，浏览器会打开本地控制面板。首次使用按面板提示安装 Chromium，填写自己的学习平台 HTTPS 地址，手动登录后勾选班级。默认同时播放 1 门，可选择 3、5 或 10 门。具体范围由用户确认。运行期间保持助手运行和电脑唤醒。平台要求验证或人工完成的课程会列入待处理。

## 源码与 Agent

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

面板运行期间每分钟自动巡检，日志至少每十分钟写一次汇总。进程被系统终止后，重新打开应用会从已保存的暂停状态恢复，需点击继续。长时间运行时请保持电脑唤醒。

MCP 默认单轮调用，设置 `continuous=true` 持续巡检，参数 `interval_min` 默认为 1。将客户端 stdio command 设置为安装后的 `bangxue-mcp` 绝对路径。浏览器登录和任务范围仍由本人处理。`BANGXUE_SITE_URL` 可指定当前客户端的平台地址。

## 验证

```sh
python -m pip install ".[playwright,mcp]" "pyinstaller>=6,<7"
python -m playwright install chromium
python -m unittest discover -s tests -v
python packaging/build_desktop.py
python packaging/smoke_desktop.py
```

[新手使用说明](新手使用说明.md) · [设计说明](docs/设计说明.md) · [隐私与安全](docs/隐私与安全.md)
