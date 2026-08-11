#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 点对时池基本面因子验证（价值/质量，无幸存者偏差）

复用 research_fundamentals.py 的披露日对齐逻辑，叠加点对时成员资格掩码；
对比固定池（300 只）结论是否改变。

用法:
    python3 scripts/research_pit_fundamentals.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from datahub.store import LocalStore  # noqa: E402
from factors.backtest import walk_forward  # noqa: E402
from factors.evaluate import evaluate  # noqa: E402
from factors.neutralization import neutralize, size_proxy  # noqa: E402
from research_fundamentals import daily_factors  # noqa: E402
from research_pit_validation import load_pit  # noqa: E402
from research_run import COSTS  # noqa: E402


def main():
    store = LocalStore(str(ROOT / "data"))
    fund_p = ROOT / "data" / "a_fundamentals.parquet"
    if not fund_p.exists():
        print("缺少 a_fundamentals.parquet")
        return
    fund = pd.read_parquet(fund_p)

    print("加载点对时池行情/成员资格/基本面...")
    ohlcv, mask, codes = load_pit(store)
    if ohlcv is None:
        return
    panel = {}
    for code in codes:
        c = ohlcv["close"].get(code)
        f = fund[fund["code"] == code]
        if c is not None and len(f) > 0:
            panel[code] = (c, f)
    trade_dates = ohlcv["close"].index
    value, quality = daily_factors(panel, trade_dates)
    value = value.where(mask)
    quality = quality.where(mask)
    print(f"面板：{value.shape[1]} 只 × {len(value)} 日；value 覆盖率 "
          f"{(value.notna().mean().mean()):.0%}，quality {quality.notna().mean().mean():.0%}")

    industry = pd.read_parquet(ROOT / "data" / "a_pit_industry.parquet").set_index("code")["industry"]
    industry.index = industry.index.astype(str)
    size = size_proxy(ohlcv["close"], ohlcv["volume"])

    rank_v = value.rank(axis=1, pct=True)
    rank_q = quality.rank(axis=1, pct=True)
    factors = {"value_pe": value, "quality_roe": quality, "composite": rank_v + rank_q}

    lines = [
        "# 点对时池基本面因子验证报告（价值 / 质量）",
        "",
        f"> 生成时间：{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}",
        f"> 池：沪深300+中证500 月度成分（{value.shape[1]} 只累计），披露日对齐，成员资格逐日生效",
        "> 对比：固定池（300 只）基本面结论是否受幸存者偏差影响",
        "",
    ]
    for name, f in factors.items():
        f_neu = neutralize(f, size, industry)
        raw = evaluate(f, ohlcv["close"], horizons=(10, 20), min_symbols=20)
        neu = evaluate(f_neu, ohlcv["close"], horizons=(10, 20), min_symbols=20)
        lines += [f"## {name}", "",
                  "| 前瞻 | 原始IC | 原始ICIR | 原始评级 | 中性IC | 中性ICIR | 中性评级 |",
                  "|------|--------|----------|----------|--------|----------|----------|"]
        for h in (10, 20):
            rw = raw[raw["horizon"] == h]
            rn = neu[neu["horizon"] == h]
            if len(rw) and len(rn):
                lines.append(f"| {h} | {rw.iloc[0]['mean_ic']} | {rw.iloc[0]['icir']} | {rw.iloc[0]['rating']} | "
                             f"{rn.iloc[0]['mean_ic']} | {rn.iloc[0]['icir']} | {rn.iloc[0]['rating']} |")
        lines.append("")

    lines += ["## walk-forward 组合回测（A股，含成本）", ""]
    for name in ("composite", "value_pe"):
        f = neutralize(factors[name], size, industry)
        wf = walk_forward(ohlcv["close"], f, direction=1, top_pct=0.2, cost_rate=COSTS["A股"],
                          n_trials=25, train_size=252, test_size=63, rebalance_days=20,
                          liquidity=size, liquidity_floor_pct=0.1, limit_up_filter=True)
        m, o = wf["full_metrics"], wf["oos_metrics"]
        lines += [f"### {name}（direction=1）", "",
                  f"- 全区间：年化 {m['annual_return']:.2%} | 夏普 {m['sharpe']} | HAC t {m['hac_t']} | "
                  f"回撤 {m['max_drawdown']:.2%} | 月胜率 {m['monthly_wr']:.0%} | PF {m['profit_factor']} | DSR {m['dsr']}"]
        if o:
            lines.append(f"- **样本外**：年化 {o['annual_return']:.2%} | 夏普 {o['sharpe']} | HAC t {o['hac_t']} | "
                         f"回撤 {o['max_drawdown']:.2%} | DSR {o['dsr']}")
        lines.append("")
    lines += [
        "## 结论",
        "",
        "- 与固定池对比：IC 强度与回测结论是否一致；若 PIT 池显著变弱，说明固定池基本面结论被幸存者偏差高估",
        "",
        "> 本报告基于公开数据与规则化分析生成，仅供研究参考，不构成任何投资建议。",
        "",
    ]
    (ROOT / "docs" / "点对时池基本面验证报告.md").write_text("\n".join(lines), encoding="utf-8")
    print("已输出：docs/点对时池基本面验证报告.md")


if __name__ == "__main__":
    main()
