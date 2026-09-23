# 2026-09-23 命名迁移验收

工作区从历史 `phase5r` 文件名切换为按功能命名。Git 迁移见提交 `9e085c9`、`99c6883` 和 `00_project_control/naming_migration_manifest_20260923.csv`。不可变 SEC 接受索引、版本扩展和原始 filing 字节仅移动路径，内容未改。六份一次性审计报告归入本目录，旧历史归档保持原名。

生产副本 `/Users/messssi/LocalRuntime/equity` 从 `b97ff7b` 快进到 `99c6883`。在旧调度卸载后，受同一运行锁保护，移动 1,374 个私有文件及缓存；逐文件搬迁前后 SHA-256 一致。账户状态、持仓、手工执行记录、邮件配置和配送台账的 SHA-256 未变。派生 SEC artifact index 只更新相对路径，并逐件验证原始及规范化文本哈希；本地估值输入仅更新来源路径、核对摘录哈希并重新封存，原始副本保存在本地归档。私有逐文件清单和前后备份位于生产副本忽略的 `11_archive/runtime_naming_migration_20260923.local/`。

作者与生产两端各有 469 项测试通过；生产两个 scheduler 的 `--safe-check`、静态 guard、运行 guard 和 `verify_daily_upgrade.py --operational` 均通过。旧 `com.steven.phase5r.*` LaunchAgent 已卸载并转入系统归档，新 `com.steven.equity_research.dailyrefresh`、`.dailydecision`、`.shadoweval` 已加载，plist 与模板一致。验证未调用发送器或外部研究管线。未改动投资策略、账户真值、交易权限或通知去重语义。
