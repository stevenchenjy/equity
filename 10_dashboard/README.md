# Equity Research 私人工作台

Phase 2 正式反馈与 Phase 3 图表/历史实现。后台仅监听 `127.0.0.1:8765`。Tailscale 未完成权限、登录和 HTTPS 配置时，手机访问仍不可用。

## 日常使用

在今日方案看当前有效条件，点股票看 20 日日 K 线。行情是未复权的完成交易日日线，非实时价格。过期计划保留原文用于回看，撤下当前数量和图上的旧委托价。

在券商手动操作后填写“正式登记”，先预览股数与现金变化，再确认保存。股数是本次新增成交量；连续部分成交逐次登记，并关联已记录的订单。挂单不记为成交；撤单前的部分成交须先单独登记。成交台账推算的现金仍标记估算，卖出收入不自动成为已核验的结算资金。

缺项可以保存为待补全反馈，在正式历史补齐。账户应用和重算状态分别显示。应用后的成交不能直接改写，更正留给带审计的后续工作。“演示模式”保留浏览器隔离试填，旧演示记录不自动转入正式账户。

账户核对预填已记录的现金与持仓，须根据券商实际页面核对。全现金账户移除所有持仓行；新标的须填平均成本。完整订单核对可确认当前无挂单，或确认已经逐笔登记的完整列表。未解决的历史订单继续保留。

提交结果未知时用原请求重试，刷新后可恢复同一个请求编号。另一个设备或 writer 改变账户时，停止应用并要求核对新账户。多文件中断在重启时恢复；发现外部修改则暂停，不覆盖新状态。

## 权威状态与后台

继续使用 `05_risk_and_positions/current_account_state.local.json`、`current_positions.local.csv` 和 `current_open_orders.local.json`。成交继续写既有 `06_execution_records/manual_executions.local.csv`、`confirmed_execution_report.csv` 与 `reconciliation_report.csv`。

私人 `dashboard_feedback.local/journal.sqlite3` 保存请求、修订、前后字节和后台任务，不替代正式 CSV/JSON。观察凭据在同一忽略目录。`dashboard_feedback_pending.local.json` 是额外绑定哈希的研究输入；缺项或恢复冲突暂停未核对的数量和保护草案。

协调器持有既有 runtime 和 daily 锁。应用事实后运行完整无发送刷新；生产沿用外部公共行情 launcher 的 `--feedback-refresh` 模式及其既有 SEC/Keychain 管理。dashboard 不存凭据，不调用邮件 sender。公共采集失败保留事实并显示失败/缺口，可重试；重算不等于分析师签署新建议。

新标的缺少公开价格时仍可记录人工事实。旧总额仅作参考，页面显示待估值，旧决策不会混入新账户。

Codex 根据用户明确报告的事实登记时，用同一个 `record_feedback.py`。私人 JSON 使用当前 `/api/snapshot` 的账户版本和唯一 UUID；先 `--preview`，核对变化，把返回的 `preview_hash` 保留在同一个请求内，再 `--apply --refresh`。旧 reconciliation writer 保留兼容用途；新标的、清仓用共同协调器。

## 发布和服务

源代码：`/Users/messssi/Desktop/equity`；生产：`/Users/messssi/LocalRuntime/equity`。通过源码提交、推送和 runtime wrapper 的 `--sync-only` 快进发布。在生产 `10_dashboard` 执行：

```sh
npm ci
npm run build
python3 install_service.py
```

本机可用 Node 在 `/Users/messssi/.nvm/versions/node/v20.20.2/bin`。LaunchAgent `com.steven.equity_research.dashboard` 登录时启动并恢复；日志在 `07_automation/dashboard.local/`。代码发布后重启服务，避免旧 Python 模块继续运行。Mac 睡眠或停机时网页不可用。

## Tailscale 私人连接

本人在 Mac 的官方应用完成系统扩展/VPN 权限与登录，手机登录同一账号。然后从生产目录运行：

```sh
python3 connect_private.py
```

若要求 HTTPS 同意页面，由本人完成后重试。私有 `access.json` 仅存 Host 和本人身份名，不存凭据。后台检查 Serve 身份、Host、Origin，拒绝跨站写入。脚本不启用 Funnel，不覆盖其他已有服务。

须用实际手机和 Mac 验证私人 HTTPS、同一状态、填写与回执。手机尺寸的浏览器测试不能替代真实手机连通；未完成时 Phase 3 保持待验收。

## 验证和历史

`npm test` 与 `npm run build` 使用合成账户，覆盖新买入、清仓、全现金输出、部分成交、撤单、待补全、双设备竞争、重复、中断、外部冲突和研究失败保留事实。完整流程还需检查决策与 text/HTML；不在生产写测试成交。

邮件历史从已发送台账筛选，验证原始 `sent_decisions.local/<sha256>.json`；`/?version=<sha256>` 回看历史版本。私人 HTTPS 配置后，新决策捕获私人 Host，邮件文本与 HTML 附带 `/?publication=<id>` 链接，页面按已发送原始归档解析该版本。归档版本可以关联实际操作反馈，但预览始终使用最新账户。已发送邮件不回写；本次未发送测试邮件，实际私人链接和手机打开须在 Tailscale 登录后验收。
