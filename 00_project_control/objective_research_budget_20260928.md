# Objective research work budget

The owner permitted raising the research workload when observed output quality
and operating cost justify it. The configured default is now at most **ten
changed issuers per completed refresh**, replacing the previous three-issuer
default. This changes workload only. Evidence admission, analyst review,
valuation, eligibility, allocation and risk limits are unchanged.

`workflow.objective_research_max_tickers` in `active_production_config.json`
controls the scheduled `create_research_backlog.py` stage. The CLI can override
it with `--max-tickers`; configuration, runner and report validation permit only
integer budgets from 1 through 10. Historical reports with a three-issuer budget
remain valid. An unchanged source set is skipped, so ten is a ceiling rather
than a quota. No extra network request or model call is introduced.

A September 28 read-only rehearsal used identical copied durable histories
and current verified SEC caches. Three slots took about 0.50 seconds; ten took
about 0.82 seconds. The wider pass reached five previously unprocessed issuers:
four produced source-bound numeric attachments and one correctly remained
unverified because its selected financial period needed reconciliation. Neither
budget completed an additional financial field. This supports inexpensive
coverage completion, **not** a claim of better recommendations or returns.

The local Python workload consumes no Codex model calls. The separate analyst
follow-through chat does use Codex inference when it evaluates evidence and
authors a review. Its task count and observed progress must be tracked
separately; raising this cache-processing budget does not allocate more model
usage or automatically scale the analyst workload.

The pipeline audit also removed mutable news collection timestamps from work
deduplication, so unchanged repolls no longer repeatedly consume the ceiling.
Existing evidence, failed attempts, source hashes and history remain retained.
An initial bounded compatibility reassessment can occur for old fingerprints;
the history is never reset merely to report apparent new progress.
