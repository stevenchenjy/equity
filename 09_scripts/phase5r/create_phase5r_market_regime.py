#!/usr/bin/env python3
"""Build current market context from already validated public snapshots."""
from phase5r_daily_common import ROOT, MARKET_SNAPSHOT_PATH, atomic_write_json, atomic_write_text, iso_now, latest_published_market_session, now_et, read_csv, read_json
from phase5r_market_regime import POLICY_PATH, STATE_PATH, REPORT_PATH, build_regime


def main() -> int:
    report = build_regime(read_csv(MARKET_SNAPSHOT_PATH),
                          read_csv(ROOT / "03_source_data/phase5r/phase5r_universe_seed.csv"),
                          read_json(STATE_PATH, {}), read_json(POLICY_PATH),
                          latest_published_market_session(now_et()).isoformat(), iso_now())
    atomic_write_json(STATE_PATH, report)
    atomic_write_text(REPORT_PATH, "\n".join([
        "# 市场状态与研究节奏", "", f"生成：{report['generated_at']}；收盘日：{report['market_session_date']}。",
        f"状态：{report['status']}；市场环境：{report['regime']}；原始观察：{report['raw_regime']}。",
        f"新增资金方案需要 {report['required_distinct_closes']} 个不同有效收盘确认。",
        f"研究优先级：{report['research_priority']}。", f"指标：{report['metrics']}", "",
        "市场压力连续两个不同收盘确认后延长新增方案复核，连续三个正常收盘才恢复；同一收盘重复运行不累计。",
        "仓位上限、现金储备、长期配置目标不随此模块改变；市场价格状态不构成退出持仓的独立理由。",
        "阈值是透明的研究规则，不是经过收益优化的参数；报价未完成公司行动校验，不能据此声称投资有效。", ""]))
    print(f"market_regime={report['regime']} required_distinct_closes={report['required_distinct_closes']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
