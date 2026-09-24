# 长期研究、倍增情景与证据边界

生效：2026-09-20。执行参数为 `01_policies/long_horizon_research_policy.json`。

研究候选使用所有已有且质量合格的公司基本面，以收入增长、现金转化和稀释分配研究优先级。前六个基本面候选与原来的前三个市场信号候选合并，并始终保留当前持仓和 SPY。研究优先级不是交易排序，未覆盖和不可用公司在报告中单列；静态研究池仍不等于整个市场。

新重大文件仅触发事件复核。文件存在或重大程度不能证明利好，因此当前确定性生成器的事件得分保持中性 5。只有独立且有来源的方向性分析建立后才应讨论新计分规则，本次没有自动推断事件方向。

公司研究分为三部分：有财务期间和官方可得时间的事实、未获验证的公司商业假设、明确给定的条件敏感性。IOT、RBRK、NVDA 具有独立假设与反证检查。收入同比减速、相对 TTM 的增长落差、利润率下降、负现金流与稀释超线触发研究复核；这些数值信号本身不构成已确认的投资逻辑失效。相邻季度比较要求可比季度证据，年度数字或缺失的前季不能替代。

3/5 年计算将当前 TTM 收入按显式收入 CAGR 推进，乘以显式期末现金流率，再乘股权 P/FCF 倍数；摊薄股数按显式年度稀释推进，不另加现金或减债务。反向情景求解给定这些条件实现 2×/3× 价格所需的收入 CAGR。经营现金流减资本开支是杠杆后现金流代理口径，不等同于可分配股东现金，因此使用股权倍数而不使用企业价值倍数；未计分红、中途分配、未来融资、现金再投资、回购或未来估值分布。因此输出是透明敏感性，不是 DCF、目标价、公司预测、总回报或倍增概率。三个参数组合及其最小/最大范围不是置信区间，不应把“中间组合”理解为最可能结果。

缺失收入、股数、价格、来源、可得时间或对齐期间会阻断相关每股情景；债务和现金缺失仍然是研究与资产负债风险证据缺口，但不作为股权 P/FCF 敏感性的机械加减项。明确披露且有来源的零值可以使用；缺失值不得当作零。历史 FCF 缺失不会被假设填成事实；独立标示的未来现金流率敏感性可以计算，但不能消除历史证据缺口或使研究状态自动完成。

`high` 信心和 6% high-conviction 配置层级目前明确保留，不由确定性生成器输出。完整数据只能支持数据质量较高，不能证明已经独立审阅的公司高确信度；本次不把公司批量升级为 high，也不修改该层级的风险限制。

没有审阅记录的公司继续保持 `pending_research`。2026-09-24 起，独立的维护观点记录可以将商业研究推进到已审阅，而估值仍保持未完成；不能因为有数字或列出了问题就视为投资假设已成立。报告的 `canonical_influence_allowed=false`、`recommendation_authority=false`、`automatic_action_allowed=false` 保持不变。决策展示可以据此解释已记录的商业观点、研究缺口或需要复核的变化，报告不得直接产生增仓、退出或修改风险参数。

产物为 `04_research/company_research/long_horizon_research.local.json` 和 `08_reviews/current/long_horizon_research.local.md`。`create_long_horizon_research.py` 只读本地快照，可指定不同输入/输出根目录进行离线验证，不调用模型、网络、邮箱或券商。

50% 主动股票硬上限、15% 单股硬上限、$500 现金储备和全部人工执行边界维持现行配置。本文件没有新增人工批准步骤或要求用户每天完成研究任务。

## Maintained company research, effective 2026-09-24

The private ledger `04_research/company_research/thesis_dossiers.local.json` stores immutable analyst reviews. It is distinct from `05_risk_and_positions/thesis_reviews.local.json`, the existing narrow capital-protection/thesis-break input. The new company dossier does not automatically populate that input and cannot independently change a position plan or mandate.

Each review contains:

- A stable company thesis identity, monotonically increasing version, prior-version hash, review ID, reviewer, timestamp and reason for change.
- A maintained business conclusion, per-share economics, company valuation readiness, and portfolio role/alternative assessment as separate sections.
- Supporting and contradictory claims. Reported observations are distinguished from analyst inference. Every claim binds exact text offsets to the cached primary filing, raw and normalized SHA-256, accession, financial period, official publication time, retrieval time and review time.
- Explicit unresolved questions, conditions that would require reassessment, and a next review within 31 days. Provisional support is a legitimate conclusion; it is neither high conviction nor trade eligibility.

`update_thesis_review.py --input reviewed-record.json --root PROJECT` validates without appending. Add `--apply` to append the sealed record under a private lock. It checks the complete supersession chain and rejects a stale writer version. The request to improve or conduct research authorizes preparing and recording a review; this workflow adds no daily user-approval dependency. The analyst must actually read and assess the cited material. Software checks provenance and structure; it cannot prove that a narrative inference is true.

The initial source contract uses retained SEC 10-Q/10-K filings (including amendments) with verified DocumentPeriodEndDate. A news URL or an unretained excerpt cannot silently satisfy it. Other primary-source types remain visible research inputs but need an equivalent provenance contract before they can independently complete a dossier claim.

Nonperiodic SEC material filings can now be resolved through optional `reviewed_material_filings` receipts without changing that periodic-claim contract. Each receipt binds the accepted issuer/accession/form, official SEC URL, publication and retrieval times, retained raw/text paths and SHA-256 values, exact text excerpt, analyst assessment, and disposition (`no_change_to_maintained_view` or `reassessment_required`). Admission requires the verified artifact index; later reports and publication rehash the retained documents and check the immutable acceptance chain even after the rolling index stops selecting that old filing. A bare acknowledged accession cannot suppress reassessment. A reviewed filing that still needs reassessment remains unresolved; review never implies favorable news or a new trade instruction.

The daily evaluator reads the ledger without rewriting it. An authored `reviewed` view becomes `monitor` on a later day if unchanged. It becomes `reassess` when its review is due, the latest financial period/accession was not reviewed, earnings incorporation is pending/unknown, or a new material filing needs incorporation. A late-discovered filing is also visible. Invalid or modified evidence makes the effective view `unresolved`; the authored ledger remains available for repair and audit. An invalidated business case requires an explicit sourced review with counterevidence; a price move or a numerical flag alone cannot create one.

Financial incorporation and thesis incorporation are separate checks. Downloading a new filing or selecting current revenue does not mean an analyst reviewed it. Conversely, an analyst may review the latest filing while automated financial selection is pending; that authored view is preserved, but the current report remains `reassess` until both checks are resolved.

Valuation remains independently `unresolved` until there is a retained, hashed company-specific valuation bundle that passes the existing `valuation_input_bundle` validator, complete valuation observations, explicitly reviewed target/downside assumptions sourced as `human_valuation_scenario`, and a company-specific supporting and countercase rationale. Generic deterministic policy assumptions cannot complete this gate. A reviewed scenario is not a forecast or a new trade authorization. The first four held-company dossiers retain unresolved valuations rather than invent missing debt, cash-flow or dilution inputs.

The long-horizon report exposes `companies[TICKER].maintained_view`, including `thesis_id`, `thesis_version`, `review_id`, `review_record_sha256`, effective `status`, `business_case_status`, `valuation_readiness`, conclusion, next review, validation errors and reopening reasons. The current-decision publisher uses this same view. Outcome records can reference the exact thesis version without retroactively editing prior observations. Existing unreviewed companies and the original sensitivity arithmetic remain useful and unchanged.

Issuer news is a separate maintenance check. A fresh substantive official announcement published after a review, or a changed previously acknowledged headline, reopens the effective view while preserving the source-bound filing conclusion. Clearly administrative conference-attendance and earnings-date notices do not automatically reopen a business thesis. Other headlines are conservatively triaged without inferring a positive or negative investment signal. Known earlier unreviewed news remains visible as `pending_prior_news`; retrieval alone cannot mark it reviewed. Missing issuer coverage is explicit even if no pending event is available.

A subsequent immutable dossier version may include optional `reviewed_news_events` receipts: the exact stable event identity, issuer, title, source, URL and publication timestamp; its content hash; the analyst's assessment; and `review_scope=issuer_headline_triage`. Admission requires an exact match to a fresh, validated official event available before the review. This acknowledges headline triage only, not a claim that an unretained full article was researched. A changed headline needs another assessment. Collection timestamps are excluded from semantic history and notification comparisons.

Already-eligible new individual-stock proposals receive a separate `candidate_views` check rather than being added to held-company counts. They remain watch-only with zero proposed shares unless the maintained business review is current and provisionally supported, company-specific valuation scenarios have been reviewed, and issuer news has current coverage with no unreviewed substantive items. Existing broad-ETF gates remain separate. This gate can reduce proposals, never increase their volume. No email schedule or cadence cap changes; genuinely new substantive news may qualify as a meaningful change within the existing delivery policy.
