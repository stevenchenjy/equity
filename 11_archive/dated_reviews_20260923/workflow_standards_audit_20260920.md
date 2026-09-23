# Workflow 四项标准审计 — 2026-09-20

审计结论：目前尚未完整达到「长期持有、成倍增长潜力、随市场变化调整策略、稳定抓取数据与新闻」四项标准。已具备较好的日级行情/SEC 管线、风险约束和审计基础，但投资研究深度、决策规则一致性、新闻覆盖和策略验证仍有关键缺口。

本次为审计，未修改策略、阈值、账户、生产配置或调度，未触发生产刷新、邮件或交易。唯一新增交付物是本报告。测试中的发送/账户更新输出来自测试夹具，不代表真实操作。

**审计范围和证据口径**

- 原登记路径 `/Users/messssi/Documents/equity` 已不存在；作者工作区是 `/Users/messssi/Desktop/equity`，生产目录是 `/Users/messssi/LocalRuntime/equity`。
- 两个目录代码 HEAD 均为 `75d733a2acef877b363b5bb0ac335ece54ae817e`。实际生产数据使用 runtime，未把作者目录的旧失败报告当作当前故障。
- 当前状态快照生成于 2026-09-20 11:38 ET，行情对应 2026-09-18 收盘。以下价格和财务值是工作区记录，未在本次审计重新抓取逐项核验。
- P1 表示优先修正的判断质量问题或核心目标缺口；P2 表示后续应修正的功能、覆盖或验证缺口。优先级不代表已经发生投资损失。

| 用户标准 | 结论 | 主要依据 |
|---|---|---|
| 长期持有 | 部分达到 | 五年期限、反频繁操作约束存在；但持仓 thesis 未完备，单日价格变化仍可触发退出复核 |
| 成倍增长潜力 | 尚未达到研究验收标准 | 当前主要是短期价格/成交量排序与 TTM 收入倍数比较，没有公司专属多年每股价值模型 |
| 策略随市场变化 | 部分达到 | 新数据改变分数、估值、权重；未找到市场状态驱动的配置/风险预算切换或经验证的规则更新闭环 |
| 数据、新闻抓取稳定 | 行情/SEC 有短期运行证据；新闻覆盖不足 | 保留的 14 个日历日最终刷新全通过且有失败恢复；生产新闻检查基本等同 SEC filing 检查 |

**优先发现 1 — 单日价格因素可以生成全仓退出复核（P1）**

RBRK 不在普通 B2 候选计分路径，持仓缺少 market score 时，baseline 使用 `clamp(5 + 当日涨跌幅 × 0.5)`。技术项占最终研究分数 15%，而动态权重模块将分数低于 5.5 直接映射到 `exit_review`，随后生成全部股数的退出复核方案。ADD 的两日稳定限制不适用于 EXIT。

只读隔离复现：取当前 RBRK 研究行，保持 business=6.5、earnings=8.5、valuation=2、catalyst=5、portfolio fit=8 不变；当前 technical=4.5，综合分为 5.85。假设单日跌幅为 −6%，technical=2，综合分变为 5.47，越过退出阈值。这是条件场景，不是声称历史上实际发生了退出。

下游文字仍要求 thesis 受损及人工确认，没有自动交易；但代码本身未要求新的 thesis-break 证据就生成全仓退出方案，无法充分满足长期持有的决策纪律。

证据：[技术分回退](/Users/messssi/Desktop/equity/09_scripts/equity_research/build_current_research_baseline.py:113)、[计分权重](/Users/messssi/Desktop/equity/09_scripts/equity_research/account_common.py:351)、[退出阈值](/Users/messssi/Desktop/equity/09_scripts/equity_research/calculate_dynamic_weights.py:119)、[全部股数退出方案](/Users/messssi/Desktop/equity/09_scripts/equity_research/create_exact_action_plan.py:179)。

建议：把入场技术评分、长期 thesis 失效、集中度约束分别处理；价格变化可以触发调查，但一般退出方案应具有对应的基本面或既定风险理由。保留明确风险事件的及时复核能力。

**优先发现 2 — 重大披露不分方向地提高研究分数（P1）**

任何新的 material SEC filing 都将 catalyst/news score 从 5 提至 8，经 15% 权重机械增加最终分数 0.45。material 列表包含潜在负面事件的 8-K 项目。代码没有先判断方向再加分，因此发现重大负面披露也可能提高该项评分。

人工复核和估值门槛限制了实际动作，但不能消除评分含义错误。事件重要性与投资利好程度应分开；未判定方向的事件应进入待评估状态。

证据：[事件加分](/Users/messssi/Desktop/equity/09_scripts/equity_research/build_current_research_baseline.py:128)、[material 项目](/Users/messssi/Desktop/equity/09_scripts/equity_research/refresh_daily_evidence.py:105)、[15% 权重](/Users/messssi/Desktop/equity/09_scripts/equity_research/account_common.py:363)。

**优先发现 3 — 研究完备程度不足以支撑强长期结论（P1 目标缺口）**

当前 6 个公司估值记录仅 AVGO 完整；三个个股持仓的估值完整率为 0/3：

| 标的 | 当前阻断 |
|---|---|
| IOT | 同期间债务输入缺失 |
| RBRK | 同期间债务输入缺失 |
| NVDA | 必需期间自由现金流利润率缺失 |

当前日报的三个持仓估值区间均为空，NVDA 持有逻辑和反证规则仍标明待完善；IOT/RBRK 使用通用的「thesis 变弱/新闻变化/周线破坏」描述。这可以支持「维持现状、等待研究」，不能等同已验证的长期持有 thesis。SPY 作为 ETF 不要求公司估值，应另按基金与核心配置口径验收。

SEC 财务覆盖与估值完整率有不同分母：11 家公司财务行中 2 家估值输入完整（AVGO、MU）；实际入选当前完整研究的 6 家公司中只有 1 家估值完整。两者并不矛盾。

证据：[当前日报持仓](/Users/messssi/LocalRuntime/equity/04_research/company_research/daily_decision.md:20)、[估值情景](/Users/messssi/LocalRuntime/equity/04_data/equity_research/valuation_scenarios.local.json)、[财务明细](/Users/messssi/LocalRuntime/equity/03_source_data/equity_research/daily_fundamentals.csv)。

优点是缺失字段没有被填成零，而且缺估值不能绕过新增仓位门槛。需要修复字段取数/口径，并将技术运行健康、证据覆盖、thesis 完整程度和可行动性分别呈现；当前状态的 `blockers=none` 主要描述运行阻断，并不代表研究已完整。

**成倍增长研究：当前模型的实际能力边界（P2 / 核心目标缺口）**

初筛分数中，当日涨跌占 30%、相对成交量占 25%，另有静态主题和规模/风险档位；仅排名前三的非持仓股票进入完整研究。这使长期研究入口受短期交易活跃度影响。安静但有持续经营进步的公司可能长期无法进入研究队列。

估值计算为 `(情景倍数 × 当前 TTM 收入 − 债务 + 现金) / 当前股数`，再按现金流、净现金和稀释调整倍数。源码明确注明期限和概率未估计，属于政策倍数比较器。它没有预测公司未来 3/5 年收入、利润率、每股自由现金流和股本变化，不能据此认定 2×/3× 增长空间。

证据：[初筛计分](/Users/messssi/Desktop/equity/09_scripts/equity_research/score_candidates.py:101)、[top-3 入口](/Users/messssi/Desktop/equity/09_scripts/equity_research/build_current_research_baseline.py:54)、[估值算式](/Users/messssi/Desktop/equity/09_scripts/equity_research/refresh_valuation_scenarios.py:214)、[模型解释](/Users/messssi/Desktop/equity/09_scripts/equity_research/refresh_valuation_scenarios.py:271)。

现有五年 12%–15% 年化目标，数学上对应 1.76×–2.01× 期末价值；五年翻倍需约 14.87% 年化。这是目标换算，不是当前策略已能实现的证据。个股翻倍与整个组合翻倍也应分别衡量。市场风险资产无法保证收益，历史表现也不能预测未来表现：[SEC 投资表现说明](https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-bulletins-47)。

建议增加独立于每日动量排名的长期研究队列；每家公司保留来源明确的经营驱动因素、竞争优势与反证、未来每股价值情景、达到 2×/3× 所需经营条件和估值压缩敏感性。

**市场适应能力：已有响应，但没有完整的策略调整闭环（P2）**

已有响应包括价格更新后的权重计算、集中度复核、估值重算、收入收缩提醒。配置目标仍为 core/active/cash=60/20/20，档位和门槛固定。没有找到利率、波动、市场广度等市场状态进入配置目标/风险预算切换的生产路径。固定规则本身不必然有问题，但不充分满足用户提出的市场适应目标。

`fundamental_weakening` 当前仅检测收入同比负增长。一家公司从 40% 增长降至 16% 仍可标为 strong_growth；利润率恶化、持续稀释或客户指标下降没有独立触发这一标记。研究伴随报告虽提出相关问题，目前并不改变生产决策。

建议保持长期投资原则稳定，把可调整项目限定为事先定义的风险预算、投入节奏和研究优先级；采用明确触发条件与退出条件，记录原因及策略版本，避免随短期涨跌任意改规则。

证据：[配置](/Users/messssi/Desktop/equity/00_project_control/active_production_config.json:14)、[弱化条件](/Users/messssi/Desktop/equity/09_scripts/equity_research/create_daily_decision_and_brief.py:440)、[研究伴随报告边界](/Users/messssi/Desktop/equity/00_project_control/research_working_agreement.md:22)。

**额外功能缺陷：SPY 新增方案的两日确认可能被正常价格变化反复重置（P2）**

SPY 的最高复核价被设为当日价格，而两日稳定 fingerprint 包含该价格。提取并原样执行决策源码的相关 AST 语句，在全部门槛通过、始终复核同一股数的隔离场景下得到：

```text
SPY 1 股，第一日价格上限 760.00：count=1，eligible=0
SPY 1 股，第二日价格上限 759.00：count=1，eligible=0
SPY 1 股，第三日价格上限 759.00：count=2，eligible=1
```

前两日投资方案相同且价格更低，却没有积累为两日稳定。应区分方案逻辑稳定与每日可接受价格刷新。当前 runtime 没有新候选主要是估值、整股资金和目标空间限制；不能把当前无候选归因于这个潜在缺陷。

证据：[SPY 上限价](/Users/messssi/Desktop/equity/09_scripts/equity_research/regenerate_portfolio_outputs.py:365)、[稳定性 hash](/Users/messssi/Desktop/equity/09_scripts/equity_research/create_daily_decision_and_brief.py:487)。

另有低一级配置不一致：6% high-conviction 档要求 confidence=high，但 canonical baseline 只输出 medium_high 或 medium，当前生成路径无法达到该档。见 [档位要求](/Users/messssi/Desktop/equity/00_project_control/active_production_config.json:34) 与 [confidence 生成](/Users/messssi/Desktop/equity/09_scripts/equity_research/build_current_research_baseline.py:159)。

**数据、新闻和运行稳定性**

- 保留状态中，2026-09-07 至 09-20 的 14 个日历日均最终 `refresh_fully_passed=true`。这不是 14 个交易日，也不是每次请求成功率 100%。
- 09-17 发生 Massive 请求失败，旧快照保留，后续时段在 12:39 ET 成功恢复，说明重试/恢复并非只有设计文件。
- 09-20 最新行情 29/29 有效，SEC scan=ok，持仓覆盖完整。EOD 数据使用最新已发布的 09-18 收盘，对周日日级研究口径合理。
- 当天一次完整刷新成功后，后续重试时段被标记完成；未建立独立下午事件扫描。它是日级研究管线，不能声称全天候新闻覆盖。
- 生产 `news_check` 实际只是 SEC material filing 检查。未找到独立公司 IR/RSS、财报电话会或其他新闻/监管事件抓取进入当前生产路径。
- 09-17 邮件出现 `delivery_status_unknown`；09-18 告警清除，不代表能追认前一天已送达。抓取成功和用户收到通知应分开。
- 当前本机告警不能替代在主机掉线时仍能发现故障的外部监测。长期稳定性还需要更长观察期和覆盖/延迟指标。

证据：[14 日状态与失败恢复](/Users/messssi/LocalRuntime/equity/00_project_control/run_logs/daily_scheduler_state.local.json:295)、[实际 B2 运行日志](/Users/messssi/LocalRuntime/equity/00_project_control/run_logs/run_log.csv:723)、[当前状态](/Users/messssi/LocalRuntime/equity/00_project_control/current_production_status.local.md)、[news 字段](/Users/messssi/Desktop/equity/09_scripts/equity_research/build_current_research_baseline.py:153)、[刷新时段完成逻辑](/Users/messssi/Desktop/equity/09_scripts/equity_research/run_daily_refresh_scheduler.py:426)。

现有 SEC 约每秒五次以下串行请求符合其公开每秒十次上限方向；该规则只证明访问纪律，不能证明数据完整：[SEC 自动访问说明](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data)。

**验证证据与局限**

本次主动执行：作者目录全套 active unittest，334 tests / 0 failures / 0 errors（约 7.7 秒）；生产两个 scheduler safe-check 通过；两个 LaunchAgent 均 loaded、enabled，已安装 plist 与模板一致，旧任务未加载。safe-check 不 fetch、不调用 provider、不运行生产 pipeline、不发送邮件。

另进行了上述 RBRK 评分及 filing 加分的纯函数验证，以及 SPY 两日确认的隔离源码复现。它们揭示现有测试没有覆盖的业务目标问题。334 项测试通过不能证明投资有效。

生产表现记录为 302 个快照、15 个不同来源交易日、414 条结果记录，实际成熟期限只有 1/5 个交易日。151 条 primary ticker/origin/horizon 记录也不是独立试验。当前还不能验证五年 CAGR、跨市场环境超额收益、完整组合回撤或净总回报。原始实现明确承认缺少完整现金流、分红、公司行动和成本处理。人工反馈可选，0 条反馈本身不构成系统失败。

证据：[当前验证报告](/Users/messssi/LocalRuntime/equity/08_reviews/current/capital_allocation_validation.local.md:28)、[复盘统计](/Users/messssi/LocalRuntime/equity/08_reviews/current/retrospective.local.md:5)。

**达到用户标准的修复顺序与验收建议**

1. 修正价格单独触发退出和重大披露无差别加分；修正两日稳定 hash；用真实结构的多日场景验证。严重的已确认风险事件仍允许及时人工复核。
2. 为每只个股持仓补齐可审计 thesis、可量化反证、同期间财务输入与估值；日报明确区分「长期逻辑支持」与「证据不足，暂维持现状」。
3. 建立独立长期候选队列与公司专属 3/5 年情景；把 2×/3× 的必要条件、股本稀释、倍数压缩和失败路径列出。所有关键经营假设均保留来源与日期。
4. 扩充官方 IR/业绩披露等事件来源，分别统计抓取成功率、标的覆盖率、关键字段完整率、事件发现延迟和通知状态；故障/空响应不能等同「无新事件」。可先用 30–60 个交易日作为工程观察阶段，此长度不构成投资有效性证明。
5. 增加有边界的市场状态响应，记录策略版本，以独立样本外和情景回放检验；完善组合净总回报记录后再讨论长期表现。

15% 单股硬上限、整股限制及现金储备是已经确定的风险/资金政策，不因本次审计自动放宽。让赢家长期持有与控制集中度存在真实取舍，应明确何时只是价格上涨导致权重漂移、何时是投资逻辑失效。高现金比例也需在未来业绩测量中计入，不能靠放松风控掩盖研究输入不足。
