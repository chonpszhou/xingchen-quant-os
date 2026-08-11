#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 回测-模拟一致性监控

把模拟盘净值路径与回测分布对照，机器化实盘门槛第②条
（“回测与模拟表现一致，无回测好看实盘打脸”）：
  - 取回测全区间日收益，滚动计算与模拟盘相同持有天数的累计收益分布
  - 模拟盘累计收益在回测分布中的百分位 <5% 或 >95% → 偏离警戒

用法:
    python3 scripts/monitor_backtest_consistency.py
输出:
    docs/一致性监控.md
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from datahub.store import LocalStore  # noqa: E402
from validate_paper_engines import replay_cb, replay_momentum  # noqa: E402


def replay_rp(store):
    """风险平价回测重放（逆波动率，21日调仓，0.1%成本）"""
    closes = {}
    for sym in ("SPY", "GLD", "TLT", "DBC"):
        df = store.load_bars("美股", sym)
        if df is not None:
            closes[sym] = df.set_index("date")["close"]
    close = pd.DataFrame(closes).dropna()
    ret = close.pct_change()
    vol = close.pct_change().rolling(20).std() * np.sqrt(252)
    weights = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
    for i, d in enumerate(close.index):
        if i % 21 != 0:
            continue
        w = 1.0 / vol.loc[d].clip(lower=1e-4)
        w = w / w.sum()
        w = w * min(1.0, 0.08 / (w @ vol.loc[d].values))
        weights.loc[d] = w.fillna(0.0)
    ew = weights.ffill().shift(1).fillna(0.0)
    net = (ew * ret.fillna(0.0)).sum(axis=1) - ew.diff().abs().fillna(ew.abs()).sum(axis=1) * 0.001
    return (1 + net).cumprod()


def percentile_check(bt_nav, paper_nav):
    """模拟盘累计收益在回测同持有期分布中的百分位"""
    n = len(paper_nav)
    if n < 20:
        return None, n
    bt_ret = bt_nav.pct_change().dropna()
    # 回测全区间内所有 N 日窗口的累计收益
    rolling = (bt_nav / bt_nav.shift(n) - 1).dropna()
    if len(rolling) < 30:
        return None, n
    paper_cum = paper_nav.iloc[-1] / paper_nav.iloc[0] - 1
    pct = float((rolling < paper_cum).mean())
    return pct, n


def main():
    store = LocalStore(str(ROOT / "data"))
    refs = {
        "可转债双低": (replay_cb(store)[0], ROOT / "data" / "paper_cb_nav.parquet"),
        "双动量": (replay_momentum(store)[0], ROOT / "data" / "paper_mom_nav.parquet"),
        "风险平价": (replay_rp(store), ROOT / "data" / "paper_rp_nav.parquet"),
    }
    lines = [
        "# 回测-模拟一致性监控",
        "",
        f"> 生成时间：{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}",
        "> 方法：模拟盘累计收益 vs 回测同持有期滚动收益分布；百分位 <5% 或 >95% = 偏离警戒",
        "",
        "| 账户 | 持有天数 | 累计收益 | 回测百分位 | 状态 |",
        "|------|----------|----------|-----------|------|",
    ]
    alerts = []
    for name, (bt, pf) in refs.items():
        if not pf.exists():
            lines.append(f"| {name} | - | - | - | 无模拟盘数据 |")
            continue
        paper = pd.read_parquet(pf)
        paper = paper.set_index("date")["nav"].sort_index()
        res = percentile_check(bt, paper)
        if res[0] is None:
            lines.append(f"| {name} | {res[1]} | - | - | 数据积累中（≥20 交易日生效） |")
            continue
        pct, n = res
        paper_cum = paper.iloc[-1] / paper.iloc[0] - 1
        level = "✅ 正常" if 0.05 <= pct <= 0.95 else "⚠️ 偏离回测分布"
        if pct < 0.05 or pct > 0.95:
            alerts.append(f"{name}: 累计 {paper_cum:.2%} 位于回测分布 {pct:.0%} 分位（偏离）")
        lines.append(f"| {name} | {n} | {paper_cum:.2%} | {pct:.0%} | {level} |")
    lines += ["", "## 预警", ""]
    lines += [f"- ⚠ {a}" for a in alerts] if alerts else ["- 无偏离预警"]
    lines += ["", "> 自动生成，仅供学习研究参考，不构成投资建议。", ""]
    (ROOT / "docs" / "一致性监控.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 1 if alerts else 0


if __name__ == "__main__":
    sys.exit(main())
