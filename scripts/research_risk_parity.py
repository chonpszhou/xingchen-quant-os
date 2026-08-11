#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 风险平价配置策略验证（SPY/GLD/TLT/DBC）

思路：四大资产类别（股票/黄金/债券/商品）按风险贡献等权，目标是把回撤与
波动压到最低——与双低（收益型）、双动量（趋势型）互补的“稳定型”候选。
变体：
  - 逆波动率加权（w ∝ 1/vol，月频再平衡）
  - 协方差风险平价（w ∝ 1/(Σw)，迭代求解，月频）
  - 波动目标：书目标年化 8%（不加杠杆）
基准：等权配置 / SPY 持有

用法:
    python3 scripts/research_risk_parity.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from datahub.store import LocalStore  # noqa: E402
from factors.backtest import metrics  # noqa: E402

ASSETS = ["SPY", "GLD", "TLT", "DBC"]
REBALANCE = 21
COST = 0.001
TARGET_VOL = 0.08


def inverse_vol_weights(vol):
    w = 1.0 / vol.clip(lower=1e-4)
    return w / w.sum()


def risk_parity_weights(cov):
    """协方差风险平价（迭代法，风险贡献相等）"""
    n = cov.shape[0]
    w = np.ones(n) / n
    for _ in range(100):
        port_var = w @ cov @ w
        mrc = cov @ w / np.sqrt(port_var)          # 边际风险贡献
        rc = w * mrc                                # 风险贡献
        target = rc.mean()
        w_new = w * (target / rc)
        w_new = w_new / w_new.sum()
        if np.max(np.abs(w_new - w)) < 1e-6:
            w = w_new
            break
        w = w_new
    return w


def main():
    store = LocalStore(str(ROOT / "data"))
    closes = {}
    for sym in ASSETS:
        df = store.load_bars("美股", sym)
        if df is not None and len(df) > 300:
            closes[sym] = df.set_index("date")["close"]
    close = pd.DataFrame(closes).dropna()
    ret = close.pct_change()
    vol = close.pct_change().rolling(20).std() * np.sqrt(252)
    print(f"池：{close.shape[1]} 资产 × {len(close)} 日（{close.index[0].date()} ~ {close.index[-1].date()}）")

    results = {}
    for label, weight_fn in (("逆波动率", inverse_vol_weights), ("风险平价", risk_parity_weights)):
        weights = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
        for i, d in enumerate(close.index):
            if i % REBALANCE != 0:
                continue
            if label == "逆波动率":
                w = weight_fn(vol.loc[d])
            else:
                hist = ret.loc[:d].tail(126)
                cov = hist.cov() * 252
                w = pd.Series(weight_fn(cov.values), index=close.columns)
            # 波动目标缩放（不加杠杆，≤1）
            w = w * min(1.0, TARGET_VOL / (w @ vol.loc[d].values))
            weights.loc[d] = w.fillna(0.0)
        exec_w = weights.ffill().shift(1).fillna(0.0)
        gross = (exec_w * ret.fillna(0.0)).sum(axis=1)
        net = gross - exec_w.diff().abs().fillna(exec_w.abs()).sum(axis=1) * COST
        nav = (1 + net).cumprod()
        m = metrics(nav, 0.0, n_trials=6)
        mid = len(nav) // 2
        results[label] = {"nav": nav, "m": m,
                          "h1": metrics(nav.iloc[:mid], 0.0)["sharpe"],
                          "h2": metrics(nav.iloc[mid:], 0.0)["sharpe"],
                          "rv": nav.pct_change().std() * np.sqrt(252)}

    # 基准
    benches = {}
    for sym in ("SPY",):
        r = close[sym].pct_change().fillna(0.0)
        n = (1 + r).cumprod()
        benches[sym] = metrics(n, 0.0)
    eq = pd.DataFrame(np.full((len(close), len(ASSETS)), 0.25), index=close.index, columns=close.columns)
    ew = (1 + ((eq.shift(1) * ret.fillna(0.0)).sum(axis=1) - 0)).cumprod()
    benches["等权"] = metrics(ew, 0.0)

    lines = [
        "# 风险平价配置策略验证报告",
        "",
        f"> 生成时间：{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}",
        f"> 池：{close.shape[1]} 资产 × {len(close)} 日；月频再平衡、t+1、成本 {COST:.1%}、波动目标 {TARGET_VOL:.0%}",
        "",
        "| 变体 | 年化 | 夏普 | HAC t | 回撤 | 月胜率 | PF | DSR | 实现波动 | 前半/后半 |",
        "|------|------|------|-------|------|--------|-----|-----|----------|-----------|",
    ]
    for label, r in results.items():
        m = r["m"]
        lines.append(f"| {label} | {m['annual_return']:.2%} | {m['sharpe']} | {m['hac_t']} | "
                     f"{m['max_drawdown']:.2%} | {m['monthly_wr']:.0%} | {m['profit_factor']} | {m['dsr']} | "
                     f"{r['rv']:.1%} | {r['h1']:.2f} / {r['h2']:.2f} |")
    lines += ["", "| 基准 | 年化 | 夏普 | 回撤 |", "|------|------|------|------|"]
    for name, m in benches.items():
        lines.append(f"| {name} | {m['annual_return']:.2%} | {m['sharpe']} | {m['max_drawdown']:.2%} |")
    lines += [
        "",
        "## 结论",
        "",
        "- 定位：稳定型配置（低回撤），非收益型；门控侧重：回撤显著低于 SPY、夏普不差、HAC t 为正",
        "- 若回撤 <10% 且夏普 ≥0.8：作为第三候选（与双低/双动量互补，作为“底仓”）；否则诚实归档",
        "",
        "> 本报告基于公开数据与规则化分析生成，仅供研究参考，不构成任何投资建议。",
        "",
    ]
    (ROOT / "docs" / "风险平价配置验证报告.md").write_text("\n".join(lines), encoding="utf-8")
    print("已输出：docs/风险平价配置验证报告.md")
    for label, r in results.items():
        m = r["m"]
        print(f"{label}: 年化 {m['annual_return']:.2%} 夏普 {m['sharpe']} HAC {m['hac_t']} "
              f"回撤 {m['max_drawdown']:.2%} DSR {m['dsr']} 前半/后半 {r['h1']:.2f}/{r['h2']:.2f}")


if __name__ == "__main__":
    main()
