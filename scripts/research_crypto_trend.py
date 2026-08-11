#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 加密时间序列趋势策略验证（周频）

池：BTC/ETH/SOL/DOGE/BNB/XRP（OKX 本地日线，约 4 年）
信号：时间序列动量（30/90/180 日等权符号）
仓位：波动率目标（单币目标年化 8%，杠杆上限 2），周度调仓，t+1 执行
成本：0.1%/边；门控同基准报告

用法:
    python3 scripts/research_crypto_trend.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from datahub.store import LocalStore  # noqa: E402
from factors.backtest import metrics  # noqa: E402

REBALANCE = 5          # 周频
BOOK_TARGET_VOL = 0.15 # 书目标年化波动（单币 = 书目标/N，避免随币种数放大）
MAX_POS = 2.0
COST = 0.001

VARIANTS = [
    ("多周期(30/90/180)", (30, 90, 180)),
    ("多周期(60/120/240)", (60, 120, 240)),
    ("多周期(30/90/180/360)", (30, 90, 180, 360)),
    ("12-1动量(跳过30日,360日)", (30, 360), True),
]


def main():
    store = LocalStore(str(ROOT / "data"))
    closes = {}
    for _, st in store.all_status().iterrows():
        if st["market"] != "虚拟货币":
            continue
        df = store.load_bars("虚拟货币", st["symbol"])
        if df is not None and len(df) > 300:
            closes[st["symbol"]] = df.set_index("date")["close"]
    close = pd.DataFrame(closes).sort_index()
    print(f"池：{close.shape[1]} 币 × {len(close)} 日（{close.index[0].date()} ~ {close.index[-1].date()}）")
    ret = close.pct_change()

    vol = close.pct_change().rolling(20).std() * np.sqrt(365)

    results = {}
    for variant, lookbacks, *skip21 in VARIANTS:
        sigs = []
        for L in lookbacks:
            if skip21 and L == lookbacks[-1]:
                sigs.append(np.sign(close.shift(30) / close.shift(L) - 1))
            else:
                sigs.append(np.sign(close / close.shift(L) - 1))
        sig = sum(sigs) / len(sigs)
        for label, long_only in ((f"{variant}·多空", False), (f"{variant}·纯多", True)):
            weights = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
            for i, d in enumerate(close.index):
                if i % REBALANCE != 0:
                    continue
                w = sig.loc[d] * (BOOK_TARGET_VOL / close.shape[1] / vol.loc[d].clip(lower=1e-4))
                w = w.clip(-MAX_POS, MAX_POS)
                if long_only:
                    w = w.clip(lower=0.0)
                weights.loc[d] = w.fillna(0.0)
            exec_w = weights.ffill().shift(1).fillna(0.0)
            gross = (exec_w * ret.fillna(0.0)).sum(axis=1)
            turnover = exec_w.diff().abs().fillna(exec_w.abs()).sum(axis=1)
            net = gross - turnover * COST
            nav = (1 + net).cumprod()
            m = metrics(nav, 0.0, n_trials=8)
            mid = len(nav) // 2
            results[label] = {"nav": nav, "m": m,
                              "h1": metrics(nav.iloc[:mid], 0.0)["sharpe"],
                              "h2": metrics(nav.iloc[mid:], 0.0)["sharpe"],
                              "rv": nav.pct_change().std() * np.sqrt(365)}

    lines = [
        "# 加密时间序列趋势策略验证报告（周频）",
        "",
        f"> 生成时间：{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}",
        f"> 池：{close.shape[1]} 币（OKX 日线，约 4 年）；信号：多周期动量等权符号；"
        f"仓位：书目标波动 {BOOK_TARGET_VOL:.0%}（单币={BOOK_TARGET_VOL:.0%}/N）、杠杆≤{MAX_POS:.0f}、周频、t+1 执行、成本 {COST:.1%}",
        "",
        "| 变体 | 年化 | 夏普 | HAC t | 回撤 | 月胜率 | PF | DSR | 实现波动 | 前半/后半夏普 |",
        "|------|------|------|-------|------|--------|-----|-----|----------|---------------|",
    ]
    for label, r in results.items():
        m = r["m"]
        lines.append(f"| {label} | {m['annual_return']:.2%} | {m['sharpe']} | {m['hac_t']} | "
                     f"{m['max_drawdown']:.2%} | {m['monthly_wr']:.0%} | {m['profit_factor']} | {m['dsr']} | "
                     f"{r['rv']:.1%} | {r['h1']:.2f} / {r['h2']:.2f} |")
    best_long = max(((k, v) for k, v in results.items() if "纯多" in k),
                    key=lambda kv: kv[1]["m"]["hac_t"])
    lines += ["", f"## 年度收益（{best_long[0]}）", "", "| 年份 | 收益 |", "|------|------|"]
    nav = best_long[1]["nav"]
    yearly = nav.resample("YE").last().pct_change().fillna(nav.resample("YE").last().iloc[0] - 1)
    for y, v in yearly.items():
        lines.append(f"| {y.year} | {v:.2%} |")
    lines += [
        "",
        "## 结论",
        "",
        "- 加密趋势（多空/纯多）是否产生稳定净边际：以 DSR 与半程稳定性为门控",
        "- 若纯多年化显著为正且回撤可控，可作第二候选（7x24 可交易、门槛低）；否则维持‘仅 A股双低为实盘候选’结论",
        "",
        "> 本报告基于公开数据与规则化分析生成，仅供研究参考，不构成任何投资建议。",
        "",
    ]
    (ROOT / "docs" / "加密趋势策略验证报告.md").write_text("\n".join(lines), encoding="utf-8")
    print("已输出：docs/加密趋势策略验证报告.md")
    for label, r in results.items():
        m = r["m"]
        print(f"{label}: 年化 {m['annual_return']:.2%} 夏普 {m['sharpe']} HAC {m['hac_t']} "
              f"回撤 {m['max_drawdown']:.2%} DSR {m['dsr']} 前半/后半 {r['h1']:.2f}/{r['h2']:.2f}")


if __name__ == "__main__":
    main()
