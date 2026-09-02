# AGENTS.md

Guidance for AI assistants and scripts working inside this project.

## Purpose

This repo is for education, research, risk calculation, and journaling only. It supports a small cash-account portfolio currently operating at approximately the $3,000 scale. Current account value must be derived from manually maintained cash and shares at current canonical prices, never from this descriptive scale.

Codex may prepare research, calculate risk, screen a local watchlist, summarize filings, draft memos, and create trade plans for human review. Codex may not execute trades.

## Non-Negotiable Constraints

- No live trading.
- No brokerage API integration.
- No credential storage.
- No bank, debit card, credit card, password, API key, or broker login handling.
- No automatic trade execution.
- No margin.
- No options.
- No short selling.
- OTC penny stocks are out of scope.
- Every real trade requires human approval outside this repo before any action is taken.
- Do not issue buy or sell commands.
- Do not place trades.

## Research Standards

- Prefer SEC filings, company investor relations, exchange filings, FDA pages, official government sources, audited statements, and other primary sources.
- Use reliable financial sources as secondary context only.
- Treat social media, forums, blogs, promotional newsletters, and influencer posts as weak evidence unless confirmed by primary sources.
- Keep facts, estimates, and opinions separate.
- Explain uncertainty clearly.
- Use the labels `reject`, `watchlist`, `paper trade candidate`, or `real-trade candidate`.
- A real-trade candidate label is not approval to trade.

## File Conventions

- Store filing downloads or filing summaries in `02_filings/`.
- Store manually maintained data in `04_data/`.
- Store company memos in `03_research/`.
- Store paper and real trade logs in `06_trading/`.
- Store weekly and monthly reviews in `07_reviews/`.

## Script Safety

- Scripts must remain readable and offline-first where practical.
- Scripts must not place orders or connect to a brokerage.
- Scripts must not store credentials.
- Network use is allowed only for public research sources, such as SEC endpoints, and should be explicit in script arguments or comments.
- Scripts must not add live trading, margin, options, short selling, or broker API functionality.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

When the user types `/graphify`, use the installed graphify skill or instructions before doing anything else.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- Dirty graphify-out/ files are expected after hooks or incremental updates; dirty graph files are not a reason to skip graphify. Only skip graphify if the task is about stale or incorrect graph output, or the user explicitly says not to use it.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
