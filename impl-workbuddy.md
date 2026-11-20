# 刷课 · Workbuddy 适配说明（移植清单）

> 状态：**设计兼容，未实测**。本文档是把 `bangxue` 迁到 Workbuddy 时要做的映射与核对。
> 通用流程、验收标准见 `SKILL.md`，那里不变；本文件只填「契约 → Workbuddy API」。

## 落地顺序（优先用现成能力，不要重写）
1. **首选 CLI**：Workbuddy 只要能执行本机命令，直接调：
   ```
   bangxue run --scope bangxue_scope.json --state-dir bangxue_classes --concurrency 5
   bangxue status --state bangxue_state.json
   ```
   `run` = 范围内自动续班：刷完一个班自动找下一个（未报名先报名），直到范围内全部完成。Agent 只负责“开任务/看报告/处理异常”。
2. **次选 MCP**：Workbuddy 支持 MCP 时，配置 `python -m bangxue.mcp_server`，调用 `bangxue_run(scope, state_dir, concurrency)` / `bangxue_status` / `bangxue_monitor` 工具。
3. **兜底**：Workbuddy 既不能跑命令也不能接 MCP，才按下面的契约实现驱动（工作量最大，最不稳）。

## 0. 先确认 Workbuddy 有没有浏览器能力
Workbuddy 是 Agent 运行时，本 skill 需要它能驱动一个**已登录 learning-platform.local 的浏览器**。逐项确认：
- [ ] 能否打开/列举/切换浏览器标签页？（自有浏览器工具 / 接 Playwright / 接 WebBridge 均可）
- [ ] 能否读取页面 DOM（播放时间、课程表）？
- [ ] 能否对指定标签做「焦点模拟/激活」或等效让后台媒体加载的手段？⚠️最关键，没有就要实测替代方案
- [ ] 能否可靠关闭**指定**标签（不是"当前活动标签"）？
- [ ] 有没有定时调度（等价 cron）？
- 全没有 → 本 skill 在 Workbuddy 上不可跑，如实告知用户，不硬套。

## 0.5 ⚠️ Workbuddy 已知坑：光打开页面不进视频学习（必读）
**症状**：Workbuddy 打开了课程页面，但停在详情页，视频不开始、不进入学习。

**原因**：
1. 平台流程是「课程详情页 → 点『我要学习/继续学习』→ 才跳 `/play/` 播放页 → 视频才开播」。**直开播放地址或只开详情页，平台不建立本次学习会话。**
2. 「我要学习」按钮**只认可信点击**（`event.isTrusted=true`）。JS 合成的 `element.click()` / `dispatchEvent(new MouseEvent(...))` **实测无效**，按钮没反应。

**必须这样做**：
- 打开课程详情页 → **可信点击**「我要学习/继续学习」→ 确认跳到 `/course/#/play/<courseId>`。
- 可信点击的来源（任选其一）：浏览器底层鼠标事件（CDP `Input.dispatchMouseEvent`）、Playwright `page.click()`、系统级鼠标（如 macOS 电脑操作）。
- **禁止**用 `document.querySelector().click()` 代替。
- 按钮可能要先滚动到可视区、必要时悬停一下再点。

**验收（硬标准）**：
1. 地址含 `/course/#/play/<courseId>`；
2. 视频 `currentTime` 隔 ~10 秒读两次，**真的增长**才算进入学习；页面打开≠在学习。


## 1. 契约 → Workbuddy 映射表
| 契约函数 | Workbuddy 实现（填实际 API） | 备注 |
|---|---|---|
| list_play(wid) | 遍历标签，筛 url 含 `/play/` 且 `workshopId=<wid>`，正则取 courseId | |
| open_course(wid,cid) | 新开标签到 `https://learning-platform.local/course/#/play/<cid>?workshopId=<wid>` | |
| focus(tab) | Workbuddy 的焦点/激活调用；**若无，先试不做能否加载，不能则需替代** | 实测事实为准 |
| read_state(tab) | 读 `<video>` / 播放器实例的 当前时间/总时长/暂停/进度% | 只读，不改记录 |
| set_rate/set_quality | 平台控件点击，读回 2.0x / 流畅 确认 | ⚠️若只能屏幕点击，用坐标+截图核验 |
| close(tab) | 关闭指定标签，**关前重新核对 courseId** | 防关错页 |
| read_table(wid) | 打开 `myworkshop/detail?id=<wid>`，循环确认 href 后读课程表行 | |
| schedule | Workbuddy 的定时机制 | |

## 2. 移植步骤
1. 按上表实现 `bangxue/adapters/workbuddy_driver.py`（对上 SKILL.md 的契约函数签名）。
2. 让 `bangxue/drivers/` 认这个新驱动（`base.py` 的契约不变），业务逻辑 `flow.py / monitor.py / runner.py` 一行都不用改。
3. 跑 **三条验收标准**（SKILL.md）：完成有据 / 关页准确 / 断线恢复不重复。
4. 标状态：契约实现过了哪条验收，就标哪条实测；没跑过的标「设计兼容」。

## 3. Workbuddy 侧建议
- 若有稳定 tabId，`list_play`/`focus`/`close` 全走 tabId，比 WebBridge 的 URL 回验稳得多——这是换工具的最大收益点。
- 定时巡检在 Workbuddy 里挂它的调度器，巡检体逻辑沿用 `learning_monitor.py` 的对账→核进度→关完成→补新课。
- 断线恢复契约已内置（启动对账），Workbuddy 重启后直接跑 monitor 即可接管，不用清状态。

## 4. 边界（沿用）
不调平台内部接口、不改学习记录、不绕过验证；只驱动真实界面 + 读页面状态。
