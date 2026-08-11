#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 点对时池验证（消除幸存者偏差后重测价格因子与大佬信号）

池：沪深300+中证500 月度成分快照（51 个月），成员资格逐日生效；
对比固定池（308 只，当前时点入选）的结论是否改变。

用法:
    python3 scripts/research_pit_validation.py
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
from factors.master_signals import MASTER_DEFS, master_factors  # noqa: E402
from factors.neutralization import neutralize, size_proxy  # noqa: E402
from research_run import COSTS, factor_wide  # noqa: E402

PRICE_FACTORS = ["momentum_20", "momentum_60", "volatility_20", "reversal_5", "volume_anomaly"]
MASTER = ["fake_breakout_20", "wick_rejection", "wick_at_support_v2", "fake_breakout_pullback"]
BACKTEST_PLAN = [
    ("momentum_20", 1), ("reversal_5", -1), ("volatility_20", -1),
    ("fake_breakout_20", 1), ("wick_rejection", 1),
]


def load_pit(store):
    uni = pd.read_parquet(ROOT / "data" / "a_pit_universe.parquet")
    mem = pd.read_parquet(ROOT / "data" / "a_pit_membership.parquet")
    codes = sorted(uni["code"].unique())
    frames = {"open": {}, "high": {}, "low": {}, "close": {}, "volume": {}}
    for code in codes:
        df = store.load_bars("A股", code)
        if df is None or len(df) < 120:
            continue
        d = df.set_index("date")
        for f in frames:
            frames[f][code] = d[f]
    if not frames["close"]:
        return None, None, None
    out = {f: pd.DataFrame(d).sort_index() for f, d in frames.items()}
    # 逐日成员资格掩码（CSI300 ∪ CSI500）
    mem["date"] = pd.to_datetime(mem["date"])
    di = pd.Series(np.arange(len(out["close"].index)), index=out["close"].index)
    ci = pd.Series(np.arange(len(out["close"].columns)), index=out["close"].columns)
    rows = di.reindex(mem["date"]).values
    cols = ci.reindex(mem["code"].astype(str)).values
    valid = pd.notna(rows) & pd.notna(cols)
    m = np.zeros((len(out["close"].index), len(out["close"].columns)), dtype=bool)
    m[rows[valid].astype(int), cols[valid].astype(int)] = True
    mask = pd.DataFrame(m, index=out["close"].index, columns=out["close"].columns)
    return out, mask, codes


def all_factors(ohlcv):
    f = master_factors(ohlcv["high"], ohlcv["low"], ohlcv["close"], ohlcv["open"], ohlcv["volume"])
    for name in PRICE_FACTORS:
        f[name] = factor_wide(ohlcv["close"], ohlcv["volume"], name)
    return f


def main():
    store = LocalStore(str(ROOT / "data"))
    print("加载点对时池行情与成员资格...")
    ohlcv, mask, codes = load_pit(store)
    if ohlcv is None:
        print("数据不足")
        return
    close, volume = ohlcv["close"], ohlcv["volume"]
    print(f"池：{close.shape[1]} 只 × {len(close)} 日，日均成员 {mask.sum(axis=1).mean():.0f} 只")

    industry = pd.read_parquet(ROOT / "data" / "a_pit_industry.parquet").set_index("code")["industry"]
    industry.index = industry.index.astype(str)
    size = size_proxy(close, volume)
    factors = all_factors(ohlcv)

    lines = [
        "# 点对时池验证报告（消除幸存者偏差）",
        "",
        f"> 生成时间：{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}",
        f"> 池：沪深300+中证500 月度成分快照（{mask.sum(axis=1).mean():.0f} 只/日，累计 {close.shape[1]} 只），成员资格逐日生效",
        "> 目的：对比固定池（308 只，当前时点入选）结论——幸存者偏差是否改变方向",
        "> 中性化：证监会行业（BaoStock 快照）+ log(20日均成交额) 代理；门控同基准报告",
        "",
    ]

    all_names = PRICE_FACTORS + MASTER
    ic_rows = []
    for name in all_names:
        f = factors[name].where(mask)
        f_neu = neutralize(f, size, industry)
        raw = evaluate(f, close, horizons=(10, 20), min_symbols=20)
        neu = evaluate(f_neu, close, horizons=(10, 20), min_symbols=20)
        for h in (10, 20):
            rw = raw[raw["horizon"] == h]
            rn = neu[neu["horizon"] == h]
            if len(rw) and len(rn):
                ic_rows.append({
                    "factor": name, "h": h,
                    "raw_ic": rw.iloc[0]["mean_ic"], "raw_icir": rw.iloc[0]["icir"],
                    "neu_ic": rn.iloc[0]["mean_ic"], "neu_icir": rn.iloc[0]["icir"],
                    "rating": rn.iloc[0]["rating"],
                })
    ic = pd.DataFrame(ic_rows)
    lines += ["## IC 评估（成员资格掩码后，原始 vs 中性化）", "",
              "| 因子 | 前瞻 | 原始IC | 原始ICIR | 中性IC | 中性ICIR | 评级 |",
              "|------|------|--------|----------|--------|----------|------|"]
    for _, r in ic.iterrows():
        lines.append(f"| {r['factor']} | {r['h']} | {r['raw_ic']} | {r['raw_icir']} | "
                     f"{r['neu_ic']} | {r['neu_icir']} | {r['rating']} |")

    lines += ["", "## walk-forward 组合回测（含成本）", ""]
    for name, direction in BACKTEST_PLAN:
        f = factors[name].where(mask)
        f = neutralize(f, size, industry)
        wf = walk_forward(close, f, direction=direction, top_pct=0.2, cost_rate=COSTS["A股"],
                          n_trials=25, train_size=252, test_size=63, rebalance_days=20,
                          liquidity=size, liquidity_floor_pct=0.1, limit_up_filter=True)
        m, o = wf["full_metrics"], wf["oos_metrics"]
        lines += [f"### {name}（direction={direction}）", "",
                  f"- 全区间：年化 {m['annual_return']:.2%} | 夏普 {m['sharpe']} | HAC t {m['hac_t']} | "
                  f"回撤 {m['max_drawdown']:.2%} | 月胜率 {m['monthly_wr']:.0%} | PF {m['profit_factor']} | DSR {m['dsr']}"]
        if o:
            lines.append(f"- **样本外**：年化 {o['annual_return']:.2%} | 夏普 {o['sharpe']} | HAC t {o['hac_t']} | "
                         f"回撤 {o['max_drawdown']:.2%} | DSR {o['dsr']}")
        lines.append("")

    lines += [
        "## 结论",
        "",
        "- 与固定池（308 只）对比：若方向与显著性一致，说明此前结论稳健；若显著变差，说明固定池存在幸存者偏差高估",
        "- 以 walk-forward 样本外为最终门控",
        "",
        "> 本报告基于公开数据与规则化分析生成，仅供研究参考，不构成任何投资建议。",
        "",
    ]
    (ROOT / "docs" / "点对时池验证报告.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n已输出：docs/点对时池验证报告.md")
    print(ic.to_string(index=False))


if __name__ == "__main__":
    main()
