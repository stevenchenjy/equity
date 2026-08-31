# Phase 5R open-source adoption decision — 2026-08-31

Phase 5R remains a small, local Python system. No reviewed framework is added as a dependency. The useful patterns are implemented locally so the runtime stays inexpensive, auditable, and broker-free.

| Project | License observed | Decision | Pattern retained |
| --- | --- | --- | --- |
| Microsoft Qlib | MIT | Do not import the full ML/backtest stack for a two-position personal account. | Immutable point-in-time observations and experiment manifests. |
| Microsoft RD-Agent | MIT | Do not add autonomous multi-agent factor research or its model-call cost. | Hypothesis → implementation → measured evaluation → promotion loop. |
| QuantConnect LEAN | Apache-2.0 | Do not add C#/Docker/live-order machinery. | Event/calendar-aware evaluation and corporate-action completeness as a future check. |
| OpenBB | AGPL-3.0 in the current repository | Do not add a large provider platform or its licensing/credential surface. | Small normalized provider-adapter contract. |
| vectorbt | Apache-2.0 with Commons Clause | Do not add Numba/vectorized backtesting for a 29-name daily universe. | Deterministic parameter sensitivity tables where useful. |
| PyPortfolioOpt | MIT | Do not add CVXPY/SciPy optimization for two stocks plus cash. | Covariance and concentration sanity checks; no false optimizer precision. |
| FinRobot | Apache-2.0 | Do not add multi-agent/provider-key requirements. | Separate source facts, derived concepts, thesis, and deterministic valuation arithmetic. |
| TradingAgents | Apache-2.0 | Do not add debate agents or simulated execution. | At most one bounded critic on material disagreement. |
| FinGPT | MIT | Do not fine-tune or add GPU/sentiment infrastructure before a measured need exists. | Reproducible retrieval/evaluation corpus and versioned prompts. |

Primary project pages reviewed: Qlib, RD-Agent, LEAN, OpenBB, vectorbt, PyPortfolioOpt, FinRobot, TradingAgents, and FinGPT on their official GitHub repositories. License and dependency choices must be rechecked before any later import because upstream terms can change.

The active production authority is `00_project_control/phase5r_active_production_config.json`. Earlier model pilots and policy registries are retained only as historical evidence.
