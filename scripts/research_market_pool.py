#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 跨市场扩池验证（美股/港股）

扩池后（美股 61 / 港股 66）复核基准因子：
  1) IC 评估：原始 + 规模中性化（log 成交额代理）
  2) walk-forward 组合回测：低波（direction=-1）与动量（direction=+1）

用法:
    python3 scripts/research_market_pool.py
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
from factors.neutralization import size_proxy  # noqa: E402
from research_run import COSTS, MIN_SYMBOLS, factor_wide  # noqa: E402

FACTORS = ["momentum_20", "momentum_60", "volatility_20", "reversal_5", "volume_anomaly"]
BACKTEST_PLAN = [
    ("美股", "volatility_20", -1, "低波（经典异动复核）"),
    ("美股", "momentum_20", 1, "动量"),
    ("港股", "momentum_20", 1, "动量（前期 ICIR 0.22 复核）"),
    ("港股", "volatility_20", -1, "低波"),
]


def load_ohlcv(store, market, min_bars=300):
    frames = {"open": {}, "high": {}, "low": {}, "close": {}, "volume": {}}
    for _, st in store.all_status().iterrows():
        if st["market"] != market:
            continue
        df = store.load_bars(market, st["symbol"])
        if df is None or len(df) < min_bars:
            continue
        d = df.set_index("date")
        for f in frames:
            frames[f][st["symbol"]] = d[f]
    if not frames["close"]:
        return None
    return {f: pd.DataFrame(d).sort_index() for f, d in frames.items()}


def build_ic(ohlcv, market):
    close, volume = ohlcv["close"], ohlcv["volume"]
    size = size_proxy(close, volume)
    rows = []
    for name in FACTORS:
        f = factor_wide(close, volume, name)
        ev_raw = evaluate(f, close, horizons=(10, 20), min_symbols=MIN_SYMBOLS[market])
        ev_neu = evaluate(size_proxy_neutralize(f, size), close, horizons=(10, 20),
                          min_symbols=MIN_SYMBOLS[market])
        for h in (10, 20):
            rw = ev_raw[ev_raw["horizon"] == h]
            rn = ev_neu[ev_neu["horizon"] == h]
            rows.append({
                "factor": name, "horizon": h,
                "raw_ic": rw.iloc[0]["mean_ic"] if len(rw) else np.nan,
                "raw_icir": rw.iloc[0]["icir"] if len(rw) else np.nan,
                "neu_ic": rn.iloc[0]["mean_ic"] if len(rn) else np.nan,
                "neu_icir": rn.iloc[0]["icir"] if len(rn) else np.nan,
                "neu_rating": rn.iloc[0]["rating"] if len(rn) else "-",
            })
    return pd.DataFrame(rows)


def size_proxy_neutralize(f, size):
    """规模中性化（逐日 log 成交额回归残差，无行业）"""
    out = pd.DataFrame(index=f.index, columns=f.columns, dtype=float)
    for d in f.index:
        fv = f.loc[d].dropna()
        if len(fv) < 10:
            continue
        sz = size.loc[d].reindex(fv.index)
        ok = fv.notna() & sz.notna()
        if ok.sum() < 10:
            continue
        y, x = fv[ok].values, np.log(sz[ok].values)
        x = x - x.mean()
        b = np.dot(x, y) / np.dot(x, x) if np.dot(x, x) > 0 else 0.0
        out.loc[d, fv[ok].index] = y - b * x
    return out


def run_backtest(close, volume, factor, factor_name, direction, market, label):
    f = size_proxy_neutralize(factor, size_proxy(close, volume))
    liq = size_proxy(close, volume)
    wf = walk_forward(close, f, direction=direction, top_pct=0.2, cost_rate=COSTS[market],
                      n_trials=25, train_size=252, test_size=63, rebalance_days=20,
                      liquidity=liq, liquidity_floor_pct=0.1)
    m, o = wf["full_metrics"], wf["oos_metrics"]
    lines = [f"### {market} · {factor_name}（direction={direction} · {label}）", ""]
    lines.append(f"- 全区间：年化 {m['annual_return']:.2%} | 夏普 {m['sharpe']} | HAC t {m['hac_t']} | "
                 f"回撤 {m['max_drawdown']:.2%} | 月胜率 {m['monthly_wr']:.0%} | PF {m['profit_factor']} | DSR {m['dsr']}")
    if o:
        lines.append(f"- **样本外**：年化 {o['annual_return']:.2%} | 夏普 {o['sharpe']} | HAC t {o['hac_t']} | "
                     f"回撤 {o['max_drawdown']:.2%} | DSR {o['dsr']}")
    folds = wf["folds"]
    if not folds.empty:
        lines.append("")
        lines.append("| 折 | IS夏普 | OOS夏普 |")
        lines.append("|----|--------|---------|")
        for _, fl in folds.iterrows():
            lines.append(f"| {fl['train']}~{fl['train_end']} | {fl['is_sharpe']} | {fl['oos_sharpe']} |")
    lines.append("")
    return "\n".join(lines)


def main():
    store = LocalStore(str(ROOT / "data"))
    lines = [
        "# 跨市场扩池验证报告（美股 / 港股）",
        "",
        f"> 生成时间：{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}",
        "> 池：美股 61 只（含大盘股与 ETF）、港股 66 只（恒指权重+中大盘），历史约 4 年",
        "> 方法：MAD(5) 去极值 + 截面 zscore；t+1 执行；Spearman IC；中性化 = log(20日均成交额) 回归残差（规模代理）",
        "> 门控：Sharpe≥1 / 月胜率≥55% / PF≥1 / DSR（已披露试验数 25）；成本：美股 0.1% / 港股 0.2%",
        "",
    ]
    for market in ("美股", "港股"):
        o = load_ohlcv(store, market)
        if o is None:
            lines.append(f"## {market}\n\n数据不足，跳过。\n")
            continue
        tab = build_ic(o, market)
        lines += [f"## {market} · IC 评估（原始 vs 规模中性化）", "",
                  "| 因子 | 前瞻 | 原始IC | 原始ICIR | 中性IC | 中性ICIR | 中性评级 |",
                  "|------|------|--------|----------|--------|----------|----------|"]
        for _, r in tab.iterrows():
            lines.append(f"| {r['factor']} | {r['horizon']} | {r['raw_ic']} | {r['raw_icir']} | "
                         f"{r['neu_ic']} | {r['neu_icir']} | {r['neu_rating']} |")
        lines.append("")
        print(f"{market} IC 完成：{len(tab)} 行")

    lines += ["## walk-forward 组合回测", ""]
    for market, factor_name, direction, label in BACKTEST_PLAN:
        o = load_ohlcv(store, market)
        if o is None:
            continue
        f = factor_wide(o["close"], o["volume"], factor_name)
        lines.append(run_backtest(o["close"], o["volume"], f, factor_name, direction, market, label))

    lines += [
        "## 结论",
        "",
        "- 扩池后美股/港股截面样本充足（60+ 只），此前的“小样本仅参考”标签解除",
        "- 以 walk-forward 样本外为最终门控：若扣费后无显著净边际（HAC t 不显著 / DSR≈0），因子仅作监控信号",
        "",
        "> 本报告基于公开数据与规则化分析生成，仅供研究参考，不构成任何投资建议。",
        "",
    ]
    (ROOT / "docs" / "跨市场扩池验证报告.md").write_text("\n".join(lines), encoding="utf-8")
    print("已输出：docs/跨市场扩池验证报告.md")


if __name__ == "__main__":
    main()
