#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 价值 + 低波 组合因子验证（点对时池，无幸存者偏差）

背景：单因子研究中最强的两个信号——
  - 价值 value_pe（PIT 池中性化 ICIR≈0.4，Moderate）
  - 低波 volatility_20（PIT 池中性化 ICIR≈-0.37，方向为低波占优）

组合：逐日截面排名等权（rank(value) + rank(-vol20)）/ 2，NaN 传播；
测试不同调仓频率（20/40/60 日）与成本敏感性，walk-forward 样本外门控。

用法:
    python3 scripts/research_value_lowvol.py
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
from research_run import factor_wide  # noqa: E402


def main():
    store = LocalStore(str(ROOT / "data"))
    fund = pd.read_parquet(ROOT / "data" / "a_fundamentals.parquet")
    print("加载点对时池...")
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
    value, _ = daily_factors(panel, trade_dates)
    value = value.where(mask)
    vol20 = factor_wide(ohlcv["close"], ohlcv["volume"], "volatility_20").where(mask)

    rank_v = value.rank(axis=1, pct=True)
    rank_lv = (-vol20).rank(axis=1, pct=True)
    composite = (rank_v + rank_lv) / 2
    factors = {"value_pe": value, "lowvol": -vol20, "value_lowvol": composite}

    industry = pd.read_parquet(ROOT / "data" / "a_pit_industry.parquet").set_index("code")["industry"]
    industry.index = industry.index.astype(str)
    size = size_proxy(ohlcv["close"], ohlcv["volume"])

    lines = [
        "# 价值 + 低波 组合因子验证报告（点对时池）",
        "",
        f"> 生成时间：{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}",
        "> 池：沪深300+中证500 月度成分（1111 只），成员资格逐日生效，披露日对齐",
        "> 组合：rank(value_pe) + rank(-vol20) 等权；中性化 = 行业 + log(成交额) 残差",
        "> 成本：A股 双边 0.3%；另测 0.15% 敏感性；调仓频率 20/40/60 交易日",
        "",
        "## IC 评估（中性化，前瞻 10/20 日）",
        "",
        "| 因子 | 前瞻 | 原始IC | 原始ICIR | 中性IC | 中性ICIR | 中性评级 |",
        "|------|------|--------|----------|--------|----------|----------|",
    ]
    for name, f in factors.items():
        f_neu = neutralize(f, size, industry)
        raw = evaluate(f, ohlcv["close"], horizons=(10, 20), min_symbols=20)
        neu = evaluate(f_neu, ohlcv["close"], horizons=(10, 20), min_symbols=20)
        for h in (10, 20):
            rw = raw[raw["horizon"] == h]
            rn = neu[neu["horizon"] == h]
            if len(rw) and len(rn):
                lines.append(f"| {name} | {h} | {rw.iloc[0]['mean_ic']} | {rw.iloc[0]['icir']} | "
                             f"{rn.iloc[0]['mean_ic']} | {rn.iloc[0]['icir']} | {rn.iloc[0]['rating']} |")

    lines += ["", "## walk-forward 组合回测（含成本）", ""]
    f_neu = neutralize(factors["value_lowvol"], size, industry)
    for rebal in (20, 40, 60):
        for cost in (0.003, 0.0015):
            wf = walk_forward(ohlcv["close"], f_neu, direction=1, top_pct=0.2, cost_rate=cost,
                              n_trials=25, train_size=252, test_size=63, rebalance_days=rebal,
                              liquidity=size, liquidity_floor_pct=0.1, limit_up_filter=True)
            m, o = wf["full_metrics"], wf["oos_metrics"]
            lines += [f"### 调仓 {rebal} 日 · 成本 {cost:.1%}（direction=1）", "",
                      f"- 全区间：年化 {m['annual_return']:.2%} | 夏普 {m['sharpe']} | HAC t {m['hac_t']} | "
                      f"回撤 {m['max_drawdown']:.2%} | 月胜率 {m['monthly_wr']:.0%} | PF {m['profit_factor']} | DSR {m['dsr']}"]
            if o:
                lines.append(f"- **样本外**：年化 {o['annual_return']:.2%} | 夏普 {o['sharpe']} | HAC t {o['hac_t']} | "
                             f"回撤 {o['max_drawdown']:.2%} | DSR {o['dsr']}")
            lines.append("")

    lines += [
        "## 结论",
        "",
        "- 若组合 ICIR 显著高于单因子且 walk-forward 样本外通过门控（Sharpe≥1/月胜率≥55%/PF≥1/DSR>0.9），"
        "则价值+低波可作为第一个候选实盘策略；否则说明 IC 层面的叠加在成本后仍不成立",
        "",
        "> 本报告基于公开数据与规则化分析生成，仅供研究参考，不构成任何投资建议。",
        "",
    ]
    (ROOT / "docs" / "价值低波组合验证报告.md").write_text("\n".join(lines), encoding="utf-8")
    print("已输出：docs/价值低波组合验证报告.md")


if __name__ == "__main__":
    main()
