---
name: bangxue-zhushou
description: 帮学助手——用户需要在已登录的本机学习平台上批量处理课程、核验进度、管理暂停与恢复时使用。桌面版、浏览器组件或 MCP 不可用时也可使用。具体平台由用户本机配置。
---

# 帮学助手

通过可见页面管理用户选定的学习任务。站点地址在本机配置，不写入仓库。只通过平台可见控件和读取页面状态操作，不调用平台内部接口、不修改学习记录、不绕过验证，也不代替用户考试。

## 使用

启动 `bangxue panel` 后，优先使用 `bangxue agent` 或 MCP 的 `bangxue_agent` 操作同一个任务。先准备环境并复用登录态，再按用户给出的栏目或班级授权启动。用户在面板查看结果，仅在平台需要本人的登录、验证或学习操作时介入。不要在代码、提交、日志或公开问题中写入真实站点、班级或账号信息。

桌面版、浏览器组件或 MCP 不可用时，读取 [Agent 浏览器流程](docs/agent-browser-fallback.md)，使用 Agent 已能操作的用户浏览器。按同一授权范围执行，在对话中报告进度和待处理事项。

```sh
bangxue scope --tab <栏目名> --out bangxue_scope.json
bangxue run --scope bangxue_scope.json --state-dir bangxue_classes --concurrency 5
bangxue status --scope bangxue_scope.json --state-dir bangxue_classes
bangxue stop --scope bangxue_scope.json --state-dir bangxue_classes
bangxue resume --scope bangxue_scope.json --state-dir bangxue_classes
bangxue watch --state-dir bangxue_classes --interval 60
```

`run` 默认一分钟一轮，外部定时器使用 `--once`。`--max-seconds` 提供单轮硬超时。MCP 保留单轮接口，持续调用使用 `continuous=true` 和 `interval_min=1`。登录失效、验证码、平台限制要暂停并报告。

## 验收与维护

1. 只关闭本次创建并有完整凭据、页面身份和驱动归属均通过核对的页面。来源不明或用户手动页面一律保留。不能证明目标归属的驱动禁止关闭。
2. 完成以新开、已核对班级身份的完整分页课程表为准。页面播放结束不能代替完成证据。班级完成记录必须带同一班级、完整课程总数及核验时间。扫描或播放卡顿时必须报告，不能静默或标完成。
3. 起播先走详情页的可信点击，确认播放时间实际增长。界面倍速未同步时暂停本次任务、处理已开的自有页面，并提示用户重试。不得显示倍速已设置。
4. 平台“换一换”或分页要逐轮读取并比对，防止拿到默认标签、隐藏列表或重复项。范围发现后列出将处理的班级。用户已授权明确范围时可直接执行，范围有歧义时先确认。未报名页面仅在确认范围内尝试报名。
5. 互动内容或考试标为需人工。课程包可处理其视频课时，但要核对子课进度，不可将整体直接标完成。结尾尚未被平台确认时，保留页面并报告，按受控方式重进或重播。
6. 保留旧版本已有行为，运行中用进程锁、原子写、创建凭据与暂停标记。每轮记录心跳，至少每十分钟在本地日志提供一次摘要。批处理发现的具体站点记录不进公开仓库。

修改后必须更新实现说明与变更记录，并运行 `python -m unittest discover -s tests -v`。每次失败要增加能重现实际问题的回归测试。开发环境测试通过不代表真实平台验收已完成。
