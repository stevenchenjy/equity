# Equity Research 改动验收入口

适用于修复跨越账户记录、研究、决策、邮件、调度、显示名或生产部署的缺陷。先读当前政策和真实输入，不以旧审计报告代替现状。对每项用户要求，明确可观察的验收结果及其生产者、持久状态、消费方和最终展示/交付位置；逐项检查，不能只依据代码修改或单个测试宣称完成。

源代码位于 `/Users/messssi/Desktop/equity`；运行检出目录位于 `/Users/messssi/LocalRuntime/equity`。两者和 `/Users/messssi/Documents/equity` 的审计资料可能处于不同时间点。检查分支、提交、未提交修改、生成时间和实际产物。只在有相应证据时分别宣称“已编码”“已测试”“已部署”“已重算”“已发送”。保持私人账户、订单、邮件台账与历史审计记录原样；不从计划或假设推断券商成交。

命名变更还须运行：

```sh
python3 09_scripts/equity_research/check_active_display_names.py --runtime-root /Users/messssi/LocalRuntime/equity
```

此检查核对现行受版本控制文档标题、统一显示配置、Graphify 当前节点和社区缓存，以及源码检出目录和生产运行目录中现存邮件/报告的显示标题。源码目录的忽略文件也可能是过期的生成品；不能把它们当作当前生产输出，旧生成品应在保留来源和哈希的前提下移出当前产物路径。历史归档、schema、环境变量、旧 launchd 标识和其他兼容键允许保留原值。`graphify update .` 后先运行 `repair_graph_display_names.py` 的检查模式；若发现缓存漂移，按命名规则修正并重跑上述检查。任何验收未完成时写明具体缺口，不能概括为“已修复”。
