# Equity Research 私人工作台

Phase 2 正式反馈、Phase 3 图表/历史，以及 Phase 4 搜索、审计更正和研究复审表单已实现。后台仅监听 `127.0.0.1:8765`。Tailscale 未完成权限、登录和 HTTPS 配置时，手机访问仍不可用。

## 日常使用

在今日方案看当前有效条件，点股票看 20 日日 K 线。行情是未复权的完成交易日日线，非实时价格。过期计划保留原文用于回看，撤下当前数量和图上的旧委托价。

详情的判断理由、主要反对理由和条件/退出依据优先显示中文「短标签 + 一句话」要点，完整原文分别折叠保留。摘要只用于阅读，不能改变投资建议、数量、账户或邮件。每份摘要同时绑定标的、计划版本、记录哈希及五个原文字段的 SHA-256；任何一项变化后回退为完整原文分点，不沿用旧摘要。

分析师在生产 `10_dashboard` 目录用 `python3 plan_summary.py --template` 生成私人 JSON 模板，填入每区块 1–5 条 `label` / `text` 要点（常规为 3–4 条），再用 `python3 plan_summary.py --input PRIVATE_JSON` 校验，加 `--apply` 保存。英文原文的否定、条件、时间和数量必须保留；摘要不是一份新研究决定。数据在已忽略的 `07_automation/dashboard.local/plan_summaries.json`，旧版本保留用于匹配；当前研究变更后重新整理摘要，无需新增模型 API。

在券商手动操作后填写“正式登记”，先预览股数与现金变化，再确认保存。正常成交默认只填股票、买卖、股数、成交总额（USD）和日期。成交总额是实际扣款 / 到账，费用按所有者确认的本券商零费用处理；后台用总额除以股数计算每股成交价。预览现金和持仓变化后点击「确认新增成交」。不再要求订单类型、金额口径、费用、时间或订单编号。未知订单类型记为 UNSPECIFIED，不推断市价或限价；已关联挂单可保留原有类型。备注、试填及挂单 / 撤单 / 部分成交等收在「其他情况」，实际相关的挂单选择另行显示。部分成交另填剩余股数；后台匹配当前挂单，多笔匹配时用可读选项选择。预览列出关联挂单，独立成交可以明确不关联。挂单不记为成交；撤单前的部分成交须先单独登记。成交台账推算的现金仍标记估算，卖出收入不自动成为已核验的结算资金。

缺项可以保存为待补全反馈，在正式历史补齐。账户应用和重算状态分别显示。应用后的成交不能直接改写；可通过「通过账户核对更正」提交今天的完整账户观察和原因，保留原始成交。「先试填（不更新账户）」用于熟悉表单，可填假设操作；默认仍为「正式登记」。试填只保存在当前浏览器，不跨设备同步，不更新正式账户、不触发研究重算，不能转换为正式记录；实际操作须重新正式登记。

账户核对预填已记录的现金与持仓，须根据券商实际页面核对。全现金账户移除所有持仓行；新标的须填平均成本。完整订单核对可确认当前无挂单，或确认已经逐笔登记的完整列表。未解决的历史订单继续保留。

提交结果未知时用原请求重试，刷新后可恢复同一个请求编号。另一个设备或 writer 改变账户时，停止应用并要求核对新账户。多文件中断在重启时恢复；发现外部修改则暂停，不覆盖新状态。

已完成写入的原请求可直接读取持久回执，不需要等研究锁释放，也不依赖当前账户快照加载成功。内容不同的同一编号仍拒绝；未完成的多文件写入仍需取得锁后恢复。表单保存回执随正式历史更新重算状态，区分「账户已应用」与研究仍在进行、完成或失败。

Trade preview and saving now use a short account lock independently of long
research refreshes. Cash and holdings update immediately; the dashboard shows
these committed facts while superseded research quantities are withheld. The
worker releases account and SQLite transactions for public research, admits only
a matching account-version publication, and carries later fills forward without
reapplying them. The 90-second quiet interval batches research only. Exact
concurrency, bounded recomposition, recovery and email-claim semantics are in
[trade recording during refresh](../00_project_control/feedback_intake.md).

## 权威状态与后台

继续使用 `05_risk_and_positions/current_account_state.local.json`、`current_positions.local.csv` 和 `current_open_orders.local.json`。成交继续写既有 `06_execution_records/manual_executions.local.csv`、`confirmed_execution_report.csv` 与 `reconciliation_report.csv`。

私人 `dashboard_feedback.local/journal.sqlite3` 保存请求、修订、前后字节和后台任务，不替代正式 CSV/JSON。观察凭据在同一忽略目录。`dashboard_feedback_pending.local.json` 是额外绑定哈希的研究输入；缺项或恢复冲突暂停未核对的数量和保护草案。

账户写入使用独立的短时锁；研究任务继续持有 runtime 和 daily 锁。应用事实后运行完整无发送刷新；生产沿用外部公共行情 launcher 的 `--feedback-refresh` 模式及其既有 SEC/Keychain 管理。dashboard 不存凭据，不调用邮件 sender。公共采集失败保留事实并显示失败/缺口，可重试；重算不等于分析师签署新建议。

新标的缺少公开价格时仍可记录人工事实。旧总额仅作参考，页面显示待估值，旧决策不会混入新账户。

Codex 根据用户明确报告的事实登记时，用同一个 `record_feedback.py`。私人 JSON 使用当前 `/api/feedback/snapshot` 的账户版本和唯一 UUID；先 `--preview`，核对变化，把返回的 `preview_hash` 保留在同一个请求内，再 `--apply --refresh`。旧 reconciliation writer 保留兼容用途；新标的、清仓用共同协调器。

## 发布和服务

源代码：`/Users/messssi/Desktop/equity`；生产：`/Users/messssi/LocalRuntime/equity`。通过源码提交、推送和 runtime wrapper 的 `--sync-only` 快进发布。在生产 `10_dashboard` 执行：

```sh
npm ci
npm run build
python3 install_service.py
```

本机可用 Node 在 `/Users/messssi/.nvm/versions/node/v20.20.2/bin`。LaunchAgent `com.steven.equity_research.dashboard` 登录时启动并恢复；日志在 `07_automation/dashboard.local/`。代码发布后重启服务，避免旧 Python 模块继续运行。页面每 30 秒及重新聚焦时比较实际构建资源版本，空闲页自动更新；有未保存输入或结果未确认的请求时保留页面并提供新版入口。引入此机制前打开的旧标签页需手动刷新，先保留未保存内容。Mac 睡眠或停机时网页不可用。

## Tailscale 私人连接

本人在 Mac 的官方应用完成系统扩展/VPN 权限与登录，手机登录同一账号。然后从 `/Users/messssi/LocalRuntime/equity/10_dashboard` 运行：

```sh
python3 connect_private.py
```

若要求 HTTPS 同意页面，由本人完成后重试。私有 `access.json` 仅存 Host 和本人身份名，不存凭据。后台检查 Serve 身份、Host、Origin，拒绝跨站写入。脚本不启用 Funnel，不覆盖其他已有服务。

须用实际手机和 Mac 验证私人 HTTPS、同一状态、填写与回执。手机尺寸的浏览器测试不能替代真实手机连通；未完成时 Phase 3 保持待验收。

## 验证和历史

`npm test` 与 `npm run build` 使用合成账户，覆盖新买入、清仓、全现金输出、部分成交、撤单、待补全、双设备竞争、重复、中断、外部冲突和研究失败保留事实。完整流程还需检查决策与 text/HTML；不在生产写测试成交。

邮件历史从已发送台账筛选，验证原始 `sent_decisions.local/<sha256>.json`；`/?version=<sha256>` 回看历史版本。私人 HTTPS 配置后，新决策捕获私人 Host，邮件文本与 HTML 附带 `/?publication=<id>` 链接，页面按已发送原始归档解析该版本。归档版本可以关联实际操作反馈，但预览始终使用最新账户。已发送邮件不回写；本次未发送测试邮件，实际私人链接和手机打开须在 Tailscale 登录后验收。

## 日常登记与研究复审

从「我的账户」点击「核对当前账户」，先按 Chase 当前显示检查预填的现金和持仓，再确认完整观察。已有持仓可留空成本以保留原记录；新标的需要明确每股成本。新表单使用所有者确认的零费用规则。旧记录的非零费用、总额口径和已知时间原样保留；旧待补全记录的未知费用在用户确认新修订时按零费用处理，不改写原记录。

「记录历史」支持股票、日期、备注、编号搜索，以及操作类型和处理状态筛选，当前展示最近最多 500 条正式记录。详情区分操作发生时间与登记时间；「查看处理轨迹」保留接纳、修订和重算过程。正式记录不删除。需要纠错时点击「通过账户核对更正」，说明原因并填写今天的完整账户观察；原始成交台账保留，更正记录与原记录相互关联。

在「我的账户」或「记录历史」填写「请求研究复审」。标的留空表示整个账户。请求使用同一个编号恢复重试，先显示等待分析师；账户重算通过不会自动显示复审完成。现有分析师任务按 `00_project_control/analyst_followthrough.md` 消费队列，完成须有来源哈希、分析结论和与当前账户一致的最终发布回执。请求分析不会自动追加邮件发送。

未保存内容离开页面前会提示。提交结果未知时表单保留原请求，恢复连接后重试，不新建另一笔。Mac 服务停止或离线时提交不会报告成功。图表支持左右方向键和上一/下一交易日按钮，显示日线 OHLC 与成交量。

CSV 批量导入、分钟线和真实收益率统计留作有明确数据契约的独立扩展；当前日常表单无需这些功能。

录入金额协议使用独立的 `simple_total` 版本；旧 `simple` 请求仍按每股单价解析，旧页面重试和历史记录不会被误乘或误除股数。新版本的未知订单类型只影响成交事实登记，不改变挂单所需的类型 / 价格 / 有效期校验。


## Action-log loading and recovery

The sidebar and full-page action forms read the lightweight
`/api/feedback/snapshot` account context. They remain available when the full
research snapshot is slow or unavailable. Retained plan identities are audit
references only; the account context cannot display a current trading draft.

Each preview/save request has a 15-second deadline, including response parsing.
The separate full research read has a finite 90-second deadline because its
source and publication validation can exceed the intake deadline. This does
not extend account-preview or save deadlines, retry a save, or relax validation.
Use **Stop waiting** to release the form while preserving its input. If a save
result is unknown, use the original request recovery control and inspect formal
history; do not create another entry for the same action. A preview alone does
not update cash, holdings, orders or the execution journal.

A successfully saved pending entry now shows its receipt, financial status and
research status separately. **Review saved record** reopens that record's latest
pending revision; **View saved history** returns to its durable history. These
controls remain available after saving from an existing pending-record editor.
An acknowledged pending receipt is not a network spinner or an unknown save.

An explicitly reported omitted historical fill and a corrected applied-fill date
use the narrow operator-only historical-reconciliation preview/apply path in
`record_feedback.py`. The ordinary form's chronology guard remains in force.
The batch binds the retained owner instruction, current account and execution
fingerprints, the original applied execution and the existing pending revision.
Original history remains available alongside the effective corrected date. This
is a reconciliation of approved local records, not a broker observation or an
order. See [the intake contract](../00_project_control/feedback_intake.md).
