# Equity Research 命名与归档规则

生效日期：2026-09-23。当前系统名称为 **Equity Research**；仓库名称为 `equity`。

## “5R”的来源与结论

历史 [Phase 0C reframe plan](../11_archive/phase5r_retired_20260831/00_project_control/audit_reports/phase0c/phase0c_reframe_plan.md) 用 Phase 5R 标识一次实时选股流程重整。后续 B2、C9、C9B 等后缀是交付阶段号。现存材料没有给出 `R` 的正式定义，也没有统一的阶段递增规则。它不表示投资表现、风险等级、当前功能或系统成熟度，因此不再用于现行文件名、目录名或用户展示名。原始历史证据保留原名以便追溯。

截图中的 `Phase 5R Equity Bri…` 源于旧本地邮件配置的 `sender_name = Phase 5R Equity Brief`；省略号是界面截断。2026-09-20 已将实际发件人、主题和当前报告显示名统一到 [equity_display_names.json](../01_policies/equity_display_names.json)。旧配置字段仅用于兼容校验，不再决定显示名。

## 文件与目录

| 对象 | 规则 | 示例 |
|---|---|---|
| 现行代码 | `snake_case`，动词 + 对象；共享模块用对象名 | `refresh_official_news.py`、`account_common.py` |
| 现行数据、政策和报告 | 按内容或职责命名，不嵌入阶段号 | `market_data_snapshot.csv`、`daily_delivery_policy.md` |
| 目录 | 用稳定的功能域名 | `09_scripts/equity_research/`、`02_filings/issuer_filings/` |
| 运行日志 | 区分写入者，避免同名覆盖 | `market_data_run_log.csv`、`account_run_log.csv`、`execution_run_log.csv` |
| 日期 | 仅用于不可变的审计、迁移和历史报告 | `naming_migration_manifest_20260923.csv` |
| 协议版本 | 格式兼容性真正需要时才使用 `v1`、`v2` | `news_events_v1` |
| 部署版本 | 使用 Git commit，不创建新 Phase 号 | `git rev-parse HEAD` |

当前入口为 [current_documents.md](current_documents.md)、[active_production_config.json](active_production_config.json)、[allowed_active_inputs.csv](allowed_active_inputs.csv) 和 [09_scripts/equity_research](../09_scripts/equity_research/)。完整旧路径到新路径见 [迁移清单](naming_migration_manifest_20260923.csv)。一次性日期审计报告放在 [dated_reviews_20260923](../11_archive/dated_reviews_20260923/)；先前已归档的实现和证据保持原始名称。

## 兼容边界

文件名可以更改；已写入的 schema 值、状态枚举、邮件去重键、Keychain 服务名以及哈希链中的值不能靠全局字符串替换更改。这些旧字符串不是现行文件名。更改它们需要单独的协议迁移、兼容读写和数据验证。私有账户状态、邮件台账、SEC 接受索引的接受记录及其扩展内容按原始字节保留；派生的 SEC 文件索引仅更新路径字段，原始索引另存归档；文件搬迁不改变投资策略、资金、持仓、通知资格或交易权限。

生产迁移已在共享运行锁下搬迁私有状态，并检查现行文件名、旧/新调度、静态 guard 和测试。验收记录见 [naming_runtime_migration_20260923.md](../11_archive/dated_reviews_20260923/naming_runtime_migration_20260923.md)。历史资料可以含原名，但不能成为当前流程输入。
