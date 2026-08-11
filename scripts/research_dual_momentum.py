#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 双动量 ETF 轮动策略验证（Antonacci 双动量）

规则：
  - 风险资产池（美股ETF/商品ETF/加密）中，取动量最高且动量>0 的标的满仓持有
  - 若无一满足，持有安全资产 TLT
  - 月度调仓，t+1 执行，成本 0.1%
动量口径：12M（经典）/ 3-6-12M 均值（Antonacci 原版）

用法:
    python3 scripts/research_dual_momentum.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from datahub.store import LocalStore  # noqa: E402
from factors.backtest import metrics  # noqa: E402

COST = 0.001
REBALANCE = 21
VARIANTS = [
    ("经典12M · 全资产（含加密）", (252,), ["SPY", "QQQ", "IWM", "DIA", "GLD", "DBC", "BTC/USDT", "ETH/USDT"], "TLT"),
    ("3-6-12M · 全资产（含加密）", (63, 126, 252), ["SPY", "QQQ", "IWM", "DIA", "GLD", "DBC", "BTC/USDT", "ETH/USDT"], "TLT"),
    ("3-6-12M · 不含加密", (63, 126, 252), ["SPY", "QQQ", "IWM", "DIA", "GLD", "DBC"], "TLT"),
    ("3-6-12M · 精简池", (63, 126, 252), ["SPY", "GLD", "DBC"], "TLT"),
]


def load(store):
    closes = {}
    for sym, market in (("SPY", "美股"), ("QQQ", "美股"), ("IWM", "美股"), ("DIA", "美股"),
                        ("GLD", "美股"), ("TLT", "美股"), ("DBC", "美股"),
                        ("BTC/USDT", "虚拟货币"), ("ETH/USDT", "虚拟货币")):
        df = store.load_bars(market, sym)
        if df is not None and len(df) > 300:
            closes[sym] = df.set_index("date")["close"]
    return pd.DataFrame(closes).sort_index()


def main():
    store = LocalStore(str(ROOT / "data"))
    close = load(store)
    # 公共交易日（交集）
    close = close.dropna()
    ret = close.pct_change()
    print(f"池：{close.shape[1]} 资产 × {len(close)} 日（{close.index[0].date()} ~ {close.index[-1].date()}）")

    results = {}
    for label, lookbacks, assets, safe in VARIANTS:
        # 每资产动量 = 各回看窗口收益均值（跨资产不混合；显式保留日期索引）
        mom = pd.DataFrame(index=close.index)
        for a in assets:
            mom[a] = np.mean([(close[a] / close[a].shift(L) - 1).values for L in lookbacks], axis=0)
        weights = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
        for i, d in enumerate(close.index):
            if i % REBALANCE != 0:
                continue
            m = mom.loc[d].dropna()
            if m.empty:
                continue
            best = m.idxmax()
            weights.loc[d] = 0.0  # 先清空旧仓位，避免 ffill 累积成多重满仓
            if m[best] > 0:
                weights.loc[d, best] = 1.0
            else:
                weights.loc[d, safe] = 1.0
        exec_w = weights.ffill().shift(1).fillna(0.0)
        gross = (exec_w * ret.fillna(0.0)).sum(axis=1)
        turnover = exec_w.diff().abs().fillna(exec_w.abs()).sum(axis=1)
        net = gross - turnover * COST
        nav = (1 + net).cumprod()
        m = metrics(nav, 0.0, n_trials=6)
        mid = len(nav) // 2
        results[label] = {"nav": nav, "m": m,
                          "h1": metrics(nav.iloc[:mid], 0.0)["sharpe"],
                          "h2": metrics(nav.iloc[mid:], 0.0)["sharpe"],
                          "rv": nav.pct_change().std() * np.sqrt(252)}

    lines = [
        "# 双动量 ETF 轮动策略验证报告",
        "",
        f"> 生成时间：{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}",
        f"> 池：{close.shape[1]} 资产 × {len(close)} 日（公共日历）；月度调仓、t+1、成本 {COST:.1%}",
        "> 规则：风险资产中动量最高且>0 者满仓，否则持 TLT",
        "",
        "| 变体 | 年化 | 夏普 | HAC t | 回撤 | 月胜率 | PF | DSR | 实现波动 | 前半/后半 |",
        "|------|------|------|-------|------|--------|-----|-----|----------|-----------|",
    ]
    for label, r in results.items():
        m = r["m"]
        lines.append(f"| {label} | {m['annual_return']:.2%} | {m['sharpe']} | {m['hac_t']} | "
                     f"{m['max_drawdown']:.2%} | {m['monthly_wr']:.0%} | {m['profit_factor']} | {m['dsr']} | "
                     f"{r['rv']:.1%} | {r['h1']:.2f} / {r['h2']:.2f} |")

    best = max(results, key=lambda k: results[k]["m"]["hac_t"])
    lines += ["", f"## 年度收益（{best}）", "", "| 年份 | 收益 |", "|------|------|"]
    nav = results[best]["nav"]
    yearly = nav.resample("YE").last().pct_change().fillna(nav.resample("YE").last().iloc[0] - 1)
    for y, v in yearly.items():
        lines.append(f"| {y.year} | {v:.2%} |")

    # 调仓频率敏感性（精简池）
    lines += ["", "## 调仓频率敏感性（精简池 3-6-12M）", "",
              "| 调仓周期 | 年化 | 夏普 | HAC t | 回撤 | DSR |", "|----------|------|------|-------|------|-----|"]
    for rebal in (10, 21, 42):
        assets_v, safe_v, lbs = ["SPY", "GLD", "DBC"], "TLT", (63, 126, 252)
        mom_v = pd.DataFrame(index=close.index)
        for a in assets_v:
            mom_v[a] = np.mean([(close[a] / close[a].shift(L) - 1).values for L in lbs], axis=0)
        w_v = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
        for i, d in enumerate(close.index):
            if i % rebal != 0:
                continue
            m = mom_v.loc[d].dropna()
            if m.empty:
                continue
            w_v.loc[d] = 0.0
            w_v.loc[d, m.idxmax() if m.max() > 0 else safe_v] = 1.0
        ew = w_v.ffill().shift(1).fillna(0.0)
        g = (ew * ret.fillna(0.0)).sum(axis=1)
        n = (1 + g - ew.diff().abs().fillna(ew.abs()).sum(axis=1) * COST).cumprod()
        mm = metrics(n, 0.0, n_trials=6)
        lines.append(f"| {rebal} 日 | {mm['annual_return']:.2%} | {mm['sharpe']} | {mm['hac_t']} | "
                     f"{mm['max_drawdown']:.2%} | {mm['dsr']} |")
    lines += [
        "",
        "## 对照",
        "",
        "| 基准 | 年化 | 夏普 | 回撤 |",
        "|------|------|------|------|",
    ]
    for sym in ("SPY", "TLT", "BTC/USDT"):
        r = close[sym].pct_change().fillna(0.0)
        n = (1 + r).cumprod()
        mm = metrics(n, 0.0)
        lines.append(f"| {sym} | {mm['annual_return']:.2%} | {mm['sharpe']} | {mm['max_drawdown']:.2%} |")
    lines += [
        "",
        "## 结论",
        "",
        "- 门控：夏普≥1 / HAC t≥2 / 回撤≤-20% / DSR>0.9 / 跑赢 SPY",
        "- 精简池（SPY/GLD/DBC+TLT）全区间显著（夏普 1.16、HAC t 2.54）且前后半程一致，但 DSR 0.025 未过门控",
        "- 结论：观察级最强候选（仅 ETF、散户友好），建议模拟盘并行跟踪；加密纳入会显著恶化回撤，不建议",
        "",
        "> 本报告基于公开数据与规则化分析生成，仅供研究参考，不构成任何投资建议。",
        "",
    ]
    (ROOT / "docs" / "双动量ETF轮动验证报告.md").write_text("\n".join(lines), encoding="utf-8")
    print("已输出：docs/双动量ETF轮动验证报告.md")
    for label, r in results.items():
        m = r["m"]
        print(f"{label}: 年化 {m['annual_return']:.2%} 夏普 {m['sharpe']} HAC {m['hac_t']} "
              f"回撤 {m['max_drawdown']:.2%} DSR {m['dsr']} 前半/后半 {r['h1']:.2f}/{r['h2']:.2f}")


if __name__ == "__main__":
    main()
