#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 模拟盘预期区间（回测分布 × 里程碑）

从回测全区间收益分布，给出每个里程碑（持有 N 个交易日）的累计收益
5/25/50/75/95 分位——让用户知道“哪个范围算正常”，与一致性监控互为印证。
注意：这是回测统计预期，不是业绩承诺。

用法:
    python3 scripts/expected_path.py
输出:
    docs/模拟盘预期区间.md
"""

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from datahub.store import LocalStore  # noqa: E402
from monitor_backtest_consistency import replay_cb, replay_momentum, replay_rp  # noqa: E402

HORIZONS = [20, 40, 60, 90, 120]
QUANTILES = [0.05, 0.25, 0.5, 0.75, 0.95]


def horizon_table(bt_nav):
    rows = {}
    for n in HORIZONS:
        rolling = (bt_nav / bt_nav.shift(n) - 1).dropna()
        if len(rolling) < 30:
            continue
        rows[n] = {q: float(rolling.quantile(q)) for q in QUANTILES}
    return rows


def main():
    store = LocalStore(str(ROOT / "data"))
    refs = {
        "可转债双低": replay_cb(store)[0],
        "双动量": replay_momentum(store)[0],
        "风险平价": replay_rp(store),
    }
    lines = [
        "# 模拟盘预期区间（回测分布）",
        "",
        f"> 生成时间：{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}",
        "> 口径：回测全区间内所有 N 交易日窗口的累计收益分位；**统计预期，非业绩承诺**",
        "> 用法：模拟盘跑到第 N 天，看累计收益落在哪一档；<5% 或 >95% 与一致性监控的偏离预警对应",
        "",
    ]
    for name, bt in refs.items():
        t = horizon_table(bt)
        lines += [f"## {name}", "",
                  "| 持有天数 | 5% 分位 | 25% | 50%（中位） | 75% | 95% 分位 |",
                  "|----------|---------|------|-------------|------|----------|"]
        for n in HORIZONS:
            if n not in t:
                continue
            r = t[n]
            lines.append(f"| {n} | {r[0.05]:.2%} | {r[0.25]:.2%} | {r[0.5]:.2%} | "
                         f"{r[0.75]:.2%} | {r[0.95]:.2%} |")
        lines.append("")
    lines += [
        "## 解读",
        "",
        "- 双低（收益型）：20 日持有中位数约 +1~2%，90 日约 +4~8%（年化 12-15% 对应）",
        "- 双动量（趋势型）：波动更大，90 日区间明显更宽，出现 -5% 或 +15% 都属正常",
        "- 风险平价（稳定型）：区间最窄，20 日通常 ±1% 内，回撤天然小",
        "- 模拟盘累计收益持续落在 5-95% 之外 → 一致性监控会预警，需复核策略参数",
        "",
        "> 仅供学习研究参考，不构成投资建议。",
        "",
    ]
    out = ROOT / "docs" / "模拟盘预期区间.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"已输出：{out}")
    print("\n".join(lines[:22]))


if __name__ == "__main__":
    main()
