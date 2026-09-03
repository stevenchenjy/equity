# Phase 5R 决策分析结构摘要（供判断是否加入 LLM）

整理日期：`2026-09-02`

用途：让独立评审者判断 Phase 5R 是否存在值得由 LLM 解决的问题，以及 LLM 应处于什么边界。本文描述架构，不构成交易建议，也不授权恢复任何历史模型代码。

## 一句话概括

Phase 5R 目前是一条以公开市场收盘数据、SEC 官方证据和本地账户状态为输入的确定性、失败即关闭、人工执行流水线。它擅长数据门控、计算、仓位限制和可审计性；主要薄弱点是对财报正文、指引、风险变化、矛盾证据和投资逻辑变化的语义理解较浅。

## 当前生产链路

```text
固定研究池 + 持仓
        |
        v
Massive Basic EOD 市场数据 ---- SEC submissions / Company Facts / 文件原文
        |                                      |
        +--------------+-----------------------+
                       v
          新鲜度、完整性、来源和时点门控
                       |
                       v
          B2 市场筛选与当前研究 baseline
                       |
                       v
        来源绑定的 bear/base/bull 确定性估值
                       |
                       v
   C9 账户重估、组合适配、仓位上限和整股可行性
                       |
                       v
     动作门控与稳定性检查 -> 每日决定性结论
                       |
           +-----------+------------+
           v                        v
   重大变化/周报邮件             结果跟踪
                                      |
                           1/5/20/60 个交易日
                           相对 SPY / QQQ 评估

任何组合变化 -> 人工复核 -> 仓库外人工交易 -> 人工记录和对账
```

生产刷新还会生成一个去敏、封存、可校验的 evidence packet，但当前没有模型消费它；它只是审计产物。

## 各层的实际职责

| 层 | 当前方法 | 应否交给 LLM |
| --- | --- | --- |
| 数据事实 | 27 个固定研究标的，加持仓价格监控；Massive 提供完整日线；SEC 提供 submissions、Company Facts 和文件原文；账户现金和股数由本地人工维护 | 否。LLM 不能成为价格、账户或财务数字的事实来源 |
| 数据门控 | 校验交易日、完整收盘、质量标签、SEC coverage、acceptance time、来源 URL、hash、时点和账户一致性；缺失时 fail closed | 否。继续使用确定性代码 |
| B2 市场筛选 | `0.30×趋势 + 0.25×成交量 + 0.20×主题催化 + 0.15×流动性质量 - 0.10×波动风险`；选出前三个非持仓候选，另保留 SPY 和持仓 | 通常否。这里是透明的粗筛，不需要语言模型 |
| 研究 baseline | business、收入趋势、估值、催化、技术、组合适配六类分数；当前 business/earnings/catalyst 的生成规则较粗 | 这是最可能需要 LLM 的位置，但只适合做有引用的语义证据分析 |
| 估值 | 公司使用 EV/TTM revenue；按收入增长区间选 bear/base/bull 倍数，再根据 FCF margin、净现金/收入、稀释调整；Python 计算每股场景、预期上涨空间和 reward/risk | 数学和最终场景必须保持确定性。LLM 最多提出需审查的假设或指出模型不适用情形 |
| C9 组合构建 | 动态账户总值=`现金+股数×当前合格收盘价`；组合评分=`25% business + 20% earnings + 15% valuation + 15% catalyst + 15% technical + 10% portfolio fit`；再套用仓位、现金储备、主题集中和整股约束 | 否。不能让 LLM 计算仓位、越过门槛或改写上限 |
| 新个股准入 | starter/normal/high conviction 分别要求最低总分、置信度、上涨空间、reward/risk、entry score、portfolio fit，并检查现金与组合上限 | 否。所有准入门槛保持确定性 |
| 核心仓位 | SPY 与个股分开；只允许每次最多一整股的分批人工复核，并检查价格区间、现金、core gap 和 maintenance 状态 | 否。LLM 不应控制资产配置或金额 |
| 最终决策 | 优先级为：账户冲突 > 数据失败 > 长期基本面转弱 > 合格动作变化 > HOLD；新增或 ADD 要在两个不同有效收盘日保持相同；TRIM/EXIT 可立即升级人工复核 | 决策权不交给 LLM。LLM 可提供非权威的支持/反对证据 |
| 通知 | 只在重大变化时发送，外加周五收盘后的周报；普通无变化邮件被抑制 | 可选用 LLM 改善表述，但不应决定是否发送 |
| 执行 | HOLD/WATCH 无需确认；任何增减仓方案必须人工确认；不连接券商、不生成订单、不自动交易 | 绝不交给 LLM |

## 当前系统的强项

- 可复现：同一输入和政策得到同一结果。
- 可审计：来源、时间、hash、计算、门槛和动作原因都有结构化记录。
- 失败安全：市场、SEC、账户或估值证据不完整时，不会猜测或自动升级动作。
- 组合纪律明确：单股默认上限 `6%`、硬上限 `8%`，active sleeve 目标 `20%`、硬上限 `30%`，战略现金储备 `$500`；实际金额始终按运行时账户动态计算。
- 行动惯性：每日分析不等于每日交易；新增方案需要两个不同有效收盘确认。
- 人机边界清楚：模型、脚本、邮件和研究标签都不是交易批准。
- 已有点时结果跟踪，可以与确定性 baseline 和 SPY/QQQ 比较。

## 当前系统的薄弱点

这些问题里只有一部分适合由 LLM 解决。

1. `business_quality_score` 主要由收入增速和净利率正负生成，无法充分表达单位经济、经营杠杆、收入质量、竞争优势、资本配置或管理层执行。
2. `earnings_revenue_trend_score` 主要是收入同比的分档规则，对 segment mix、指引变化、一次性项目、会计口径变化和可持续性理解不足。
3. `catalyst_news_quality_score` 基本是“本次是否出现按表格/Item 规则判定的重大官方文件”，并未深读文件内容或判断影响方向、持续期和可信度。
4. 估值依赖统一的 EV/revenue 增长分档。它透明但可能过度简化，不同商业模式、利润结构、周期位置和资本强度可能不适合同一倍数框架。
5. 固定研究池和简单市场排序限制了发现能力；不过扩大数据源或研究池是数据工程问题，不天然需要 LLM。
6. 分数很精确，但部分底层规则较粗，可能形成“精确数字包装粗假设”的错觉。
7. 当前规则难以系统比较“新证据 vs 旧投资逻辑”，也不擅长发现文件正文与结构化数字之间的矛盾。

LLM 不能修复数据缺失、错误 period/unit、过期市场数据、账户不同步或估值输入不足；这些仍应导致 abstain/HOLD。

## 如果加入 LLM，最合理的候选职责

唯一明显具有任务匹配度的位置，是放在生产链路之外的只读语义分析 sidecar：

```text
去敏且封存的 evidence packet
             |
             v
LLM evidence analyst：提取有 source_id 的事实、变化和矛盾
             |
             v
独立 critic：挑战证据支持度、过度推断和遗漏的反证
             |
             v
本地确定性 validator：schema、引用、ticker、period、unit、算术、政策
             |
             v
非权威 shadow 报告；最初不能改变决定、邮件或组合方案
```

可能适合的具体任务：

- 比较最新 10-Q/10-K/8-K/6-K 与上一期文件或既有 thesis，列出 strengthened / weakened / unchanged。
- 提取管理层指引、风险因素、会计政策、竞争变化、稀释、客户集中和资本配置变化，并逐条绑定 packet 内 `source_id`。
- 建立 bull/base/bear 的定性假设和明确反证，但不自行计算价格或回报。
- 对确定性动作建议做 red-team，指出未支持的推断、冲突证据或应当 abstain 的原因。
- 生成更易读的解释草稿，但发送资格仍由确定性代码决定。

不应由 LLM 承担的任务：市场和账户事实、财务算术、估值计算、分数和仓位计算、准入门槛、整股数量、现金储备、动作稳定性、邮件资格、交易批准或执行。

## 已有 LLM 试验事实

- `2026-08-31` 的当前运营决定是：从 active production 移除 AI，归档实现；当前模型调用许可为 `false`，月度硬上限为 `$0`。
- 生产路径没有真实 shadow 观测：`0/10`，所以无法证明 AI 对真实决策有边际收益。
- 历史试验与“当前生产 0 次调用”是两件事。归档的 v1–v5 试验合计启动 `18` 次调用、得到 `13` 个完成 receipt，但每个版本最终都因结构化合同错误而不完整；累计收费或预留约 `$0.654002`，无法形成合规的完整评估集。
- 归档的 v10 离线 AI 辅助复核检查了 `48` 条 claim：`39` 条支持、`9` 条部分支持，并发现 `4` 个实质性夸大或证据绑定缺陷。
- v10 critic 对部分案例有中到高的增量价值，尤其能挑战过度宽泛的结论；该复核未发现 critic false positive，但样本很小、不是独立双人评审，也没有完成可用于生产推广的盲测。
- 最终 authority review 仍保留很高的门槛：至少 `250` 个点时 replay packet、覆盖至少 `20` 家发行人和 `50` 个重大变化案例，再完成 `30–60` 个 live shadow 语义事件，并要求政策违规为零。该门槛用于未来权限评审，不用于阻止前期小规模价值验证，也不能在没有新证据时跳过。
- 因此历史证据既不能证明“LLM 没用”，也不能证明“值得加入”；它证明的是旧试验的合同可靠性和评估设计尚未达到推广标准。

## 当前运行基线

从 Mac mini runtime 在 `2026-09-02 11:59 ET` 生成的状态看：

- 确定性 refresh 已通过；市场数据 `29/29`，对应最新完成交易日 `2026-09-01`。
- SEC evidence 正常，持仓 coverage 完整。
- 估值记录 `4/5` 完整；不完整估值会被门控，不会被猜测补齐。
- 已积累 `72` 个点时 recommendation snapshots 和 `66` 条已评估 horizon 记录。
- 当时没有运行 blocker；模型仍不在生产路径。

这说明现在有一个可运行的确定性 baseline，可以用于比较 LLM 的真实增量，而不是只做主观演示。

## 希望独立评审回答的核心问题

不要先问“LLM 能不能做”，而应问：

1. 当前最重要的错误来源是语义理解不足，还是数据/估值模型/研究池/运行可靠性？
2. LLM 是否能在不改变安全边界的情况下，显著减少遗漏、过度推断或 thesis 更新错误？
3. 增量价值能否通过点时 replay、盲评和 live shadow 与当前确定性 baseline 比较？
4. 对一个小额现金账户，模型成本、维护复杂度、版本漂移、隐私和错误面是否值得？
5. 如果只需要更好的文字摘要，是否应选择低风险 narrative-only，而不是让 LLM 影响研究分类？
6. 如果建议加入，最低可行范围是什么，什么证据会触发继续、推广或永久停止？

## 可直接交给 GPT 的评审提示词

```text
你是一个独立的投资研究系统架构评审者。请基于下面这份 Phase 5R 决策分析结构摘要，判断是否应该加入 LLM。不要因为“LLM 能做某件事”就推荐加入；只有当它相对确定性代码有独特、可测量且风险可控的边际价值时才推荐。

请从以下四个结论中选择一个：
A. NO_LLM：目前不加 LLM，优先改善数据、估值或规则。
B. NARRATIVE_ONLY：只允许 LLM 改善解释或摘要，不影响研究分类。
C. SHADOW_LLM：增加异步、只读、非权威的 evidence analyst、条件 critic 和独立盲评 judge，用于自动评估，不影响生产决定或邮件。
D. LIMITED_ADVISORY：在严格验证和推广门槛后，允许 LLM 对研究分类提供有限影响，但永远不能越过确定性门控或参与交易执行。

你的回答必须包含：
1. 明确结论和置信度。
2. 你认为当前系统最重要的三个决策质量瓶颈，并区分哪些适合 LLM、哪些不适合。
3. 如果加 LLM：精确列出它的输入、输出、允许动作、禁止动作，以及仍必须由确定性代码负责的部分。
4. 一个最小但有效的 point-in-time replay + live shadow 试验，包括样本范围、baseline、盲评方法、成功指标、成本上限、推广门槛和 kill criteria。
5. 如果不加 LLM：给出更优先的三项非 LLM 改进及其预期收益。
6. 专门讨论 hallucination、引用错误、period/unit 错误、prompt injection、模型版本漂移、相关性错误、建议不稳定、隐私和运维复杂度。
7. 说明已有历史试验为什么不足以支持推广，以及哪些新证据会改变你的结论。

不可改变的边界：
- SEC 和合格市场数据是事实来源；LLM 不是事实源。
- 数学、估值、分数、仓位、现金、门槛、稳定性和通知资格必须由确定性代码完成。
- 数据不足时必须 fail closed / abstain，LLM 不得补数字。
- LLM 初始阶段只能读去敏、封存、带 source_id 的 evidence packet。
- 不连接券商，不读取券商账户，不生成或发送订单，不自动交易。
- 任何真实组合变化始终由人类在仓库外独立决定和执行。

最后请给出一个简洁的决策表：方案、预期收益、主要风险、实施复杂度、是否现在推荐。
```

## 主要依据文件

- `00_project_control/phase5r_active_production_config.json`
- `00_project_control/phase5r_ai_operating_decision.md`
- `00_project_control/phase5r_daily_research_policy.md`
- `00_project_control/phase5r_daily_decision_policy.md`
- `00_project_control/phase5r_c9_action_threshold_policy.md`
- `00_project_control/phase5r_c9_dynamic_weight_policy.md`
- `00_project_control/phase5r_c9_core_allocation_policy.md`
- `01_policies/phase5r_valuation_scenario_policy.json`
- `09_scripts/phase5r/run_phase5r_daily_refresh.py`
- `09_scripts/phase5r/build_phase5r_current_research_baseline.py`
- `09_scripts/phase5r/refresh_phase5r_valuation_scenarios.py`
- `09_scripts/phase5r/phase5r_portfolio_construction.py`
- `09_scripts/phase5r/create_phase5r_daily_decision_and_brief.py`
- `11_archive/phase5r_retired_20260831/04_research/realtime_stock_picker_phase5r/phase5r_llm_decision_architecture_research.md`
- `11_archive/phase5r_retired_20260831/08_reviews/phase5r_model_pilot/phase5r_model_pilot_terminal_no_go_report.md`
- `11_archive/phase5r_retired_20260831/08_reviews/phase5r_model_pilot/ai_assisted_v10_review/phase5r_model_pilot_v10_ai_assisted_review_report.md`
