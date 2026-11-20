# 帮学助手

帮学助手在本机打开建行学习，帮你选择专题班、查看课表、按范围巡检并核对平台进度。账号、验证码和课程记录留在自己的电脑上。需要本人操作的内容会列入待处理。

## 第一次使用

向分发人索取与电脑匹配的压缩包。Mac 解压后打开“帮学助手.app”，Windows 解压整个文件夹后双击“帮学助手.exe”。应用在默认浏览器打开本机控制面板，首次使用根据提示下载专用 Chromium。桌面版自带 Python 运行环境。内部测试构建未做开发者签名和公证，请按单位的软件安装要求使用。

1. 打开控制面板，检查浏览器组件。在弹出的学习窗口手动登录。
2. 读取资源库，勾选需要的班级，选择最多同时播放的门数（面板默认 1 门），再确认开始。运行期间保持电脑唤醒和助手运行。
3. 查看课表核验结果。出现登录、验证码或人工课程时，按提示处理，再继续原任务。

更多操作见[新手使用说明](新手使用说明.md)。维护者可以从本仓库 Actions 的 **Desktop acceptance** 成功运行中下载对应平台的构建产物。私有仓库外的用户可由分发人转交其中的应用压缩包。

## 从源代码安装

Python 3.9+ 支持 CLI 与控制面板。安装 MCP 时需使用 Python 3.10+。安装脚本会检查 Python、依赖和浏览器。已有旧版虚拟环境时会升级其中的程序，保留个人数据。

**macOS / Linux**

```sh
bash install.sh
~/.local/bin/bangxue panel
```

**Windows PowerShell**

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
& "$env:USERPROFILE\.bangxue\bin\bangxue.cmd" panel
```

## CLI 与 Workbuddy

控制面板使用 Playwright 专用浏览器。CLI 的自动模式优先连接已有 WebBridge；要使用与面板相同的登录资料，请在子命令前指定 `--driver playwright`，并先退出占用同一资料目录的面板。凭据到期时需重新登录。

```sh
bangxue login
bangxue --driver playwright doctor
bangxue --driver playwright scope --tab "党的创新理论教育和党性教育资源库" --out bangxue_scope.json
# 在确认生成的班级清单后启动；run 默认持续巡检
bangxue --driver playwright run --scope bangxue_scope.json --state-dir bangxue_classes
bangxue status --scope bangxue_scope.json --state-dir bangxue_classes
bangxue stop --scope bangxue_scope.json --state-dir bangxue_classes
bangxue resume --scope bangxue_scope.json --state-dir bangxue_classes
```

从不同进程停止持久化 Playwright 任务时，优先在原控制面板操作。程序会保留无法确认归属的标签并报告。恢复命令解除暂停，之后用同一个范围和状态目录再次运行。外部定时器使用 `run --once`。已有单班命令 `capture/start/status/monitor` 可继续使用。

## MCP

用 `bash install.sh --mcp` 或 `.\install.ps1 -Mcp` 安装。将客户端的 stdio **command** 配置为安装后的绝对路径，例如 macOS 的 `~/.local/bin/bangxue-mcp`（配置时展开用户目录）或 Windows 的 `%USERPROFILE%\.bangxue\venv\Scripts\bangxue-mcp.exe`（填入实际路径）。`BANGXUE_DRIVER=playwright` 选择专用浏览器，`BANGXUE_PROFILE` 可指定专用资料目录。使用独立的 MCP 配置目录，或先退出占用同一目录的控制面板。

`bangxue_run` 默认一轮，适合外部调度。设置 `continuous=true` 后在该 MCP 服务中持续运行；通过 `bangxue_stop` 暂停，`bangxue_resume` 解除暂停。单班启动与巡检复用 CLI 的规则。

## 验证与打包

```sh
python -m pip install ".[playwright,mcp]" "pyinstaller>=6,<7"
python -m playwright install chromium
python -m unittest discover -s tests -v
python packaging/build_desktop.py
python packaging/smoke_desktop.py
```

在目标操作系统上构建桌面应用。压缩包位于 `delivery/`。离线夹具模拟多页课表、失败及恢复路径，真实学时以平台返回的完整课表为准。[设计说明](docs/设计说明.md) · [隐私与安全](docs/隐私与安全.md)
