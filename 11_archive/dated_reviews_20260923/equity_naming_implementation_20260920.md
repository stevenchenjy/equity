# Equity Research 命名迁移验收

日期：2026-09-20 ET。用户明确要求执行已制定的命名计划。

## 已上线

- 系统及邮件发件人显示名统一为 **Equity Research**。
- 普通邮件使用 `[Equity]`；更正和应请求复核分别使用 `[Equity 更正版]`、`[Equity 应请求复核]`。
- 用户报告采用功能名称；当前每日研究决策、持仓研究、组合配置、行情报告、长期研究、市场状态、结果回顾及运行状态均使用统一品牌。
- 桌面故障提示和未来生成的研究评估报告也使用共享显示配置。既有封存评估和成交证据保留原样。
- 唯一名称来源为 `01_policies/equity_display_names.json`，公共读取与格式函数在 `09_scripts/equity_research/equity_naming.py`。私有邮件配置的旧 `sender_name` 保留兼容校验，实际显示名由新的公共配置覆盖；未打开或修改 SMTP 配置。
- README、当前文档入口、配送政策、允许输入注册表和邮件配置模板已对齐。后续开发使用功能名、日期、进度状态；旧 `phase5r` 路径/schema/调度标识继续兼容。

## 验证

- 完整测试：**406 项通过，0 failures，0 errors**。新增测试覆盖新旧 brief 的邮件身份与消息分类、品牌切换前后研究/通知指纹不变，以及显示配置中的控制字符拒绝。
- 生产当前决策改名前后离线渲染比较：研究 view 和通知判定指纹相同；正文差异仅为品牌。
- 在共享 runtime lock 内部署代码并更新 **13 个当前展示产物**，另重新生成运行状态。原始展示文件保存在本机 `/tmp/equity-naming-presentation-backup-20260920`，历史邮件与归档证据未改写。
- **25 个关键输入/状态文件哈希不变**，包括现金、持仓、人工成交、决策 JSON、调度状态、配送记录、行情、财务数据和策略配置。无需重新运行财务计算或获取行情。
- 新预览通过发送器的只读决策/正文一致性校验；没有调用发送流程，没有发送测试邮件。
- Canonical workflow guard **10 项通过**，dailyrefresh/dailydecision wrapper safe-check 均通过，两个 launchd 任务 loaded/enabled，plist 与模板一致。
- `git diff --check` 通过，`graphify update .` 已执行。

## 部署

代码提交：`20847a96c0bc7cb6e333d6e65a493cef4bcc9687`。部署时间：`2026-09-20T23:59:06.352363+00:00`（即 2026-09-20 19:59:06 ET）。已 normal push 到 GitHub main，并在共享运行锁内 fast-forward 到生产运行副本。验收文档随后单独提交。

旧邮件不会被追溯改名；下一次按既有规则生成和发送的新邮件使用新显示名。此次命名切换不增加发送资格，也不重置任何配送状态。

当前入口：[邮件预览](/Users/messssi/LocalRuntime/equity/07_automation/email_briefs/daily_email_brief.html)、[运行状态](/Users/messssi/LocalRuntime/equity/00_project_control/current_production_status.local.md)、[命名规则](../00_project_control/equity_naming_policy.md)。
