#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 风控监控器

自动执行手册纪律条款：
  1) 回撤阈值：双低 ≤20% / 双动量 ≤25% / 风险平价 ≤10% / 组合 ≤15%
  2) 基准超额：连续 3 个月跑输各自基准 → 警戒（实盘门槛依据）
  3) 阈值分档：>50% 阈值=警戒，>100% 阈值=超标

用法:
    python3 scripts/risk_monitor.py
输出:
    docs/风控状态.md；任一超标时退出码 1（run_all 会记录）
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent

ACCOUNTS = [
    ("可转债双低", ROOT / "data" / "paper_cb_nav.parquet", 0.20),
    ("双动量", ROOT / "data" / "paper_mom_nav.parquet", 0.25),
    ("风险平价", ROOT / "data" / "paper_rp_nav.parquet", 0.10),
]
PORTFOLIO_DD = 0.15


def drawdown(nav):
    return float(((nav - nav.cummax()) / nav.cummax()).min())


def underperform_months(nav, bench):
    """连续跑输基准的月数（含当前未完成月）"""
    m = nav.resample("ME").last().pct_change()
    b = bench.resample("ME").last().pct_change()
    diff = (m - b).dropna()
    streak = 0
    for v in diff.iloc[::-1]:
        if v < 0:
            streak += 1
        else:
            break
    return streak


def main():
    rows = []
    breaches = []
    navs = {}
    for name, nav_file, dd_thr in ACCOUNTS:
        if not nav_file.exists():
            continue
        df = pd.read_parquet(nav_file)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        nav = df["nav"]
        navs[name] = nav
        dd = drawdown(nav)
        ratio = abs(dd) / dd_thr if dd_thr else 0
        level = "正常" if ratio <= 0.5 else ("警戒" if ratio <= 1.0 else "超标")
        streak = 0
        if "bench_nav" in df.columns:
            bench = df["bench_nav"]
            streak = underperform_months(nav, bench)
        rows.append({"name": name, "nav": nav.iloc[-1], "dd": dd, "thr": dd_thr,
                     "ratio": ratio, "level": level, "streak": streak})
        if level == "超标":
            breaches.append(f"{name}: 回撤 {dd:.1%} 超阈值 {dd_thr:.0%}")
        if streak >= 3:
            breaches.append(f"{name}: 连续 {streak} 个月跑输基准（实盘门槛受挫）")

    # 组合回撤
    if len(navs) >= 2:
        raw = pd.concat(navs, axis=1).ffill().dropna()
        port = (raw / raw.iloc[0]).mean(axis=1)
        pdd = drawdown(port)
        pr = abs(pdd) / PORTFOLIO_DD
        plevel = "正常" if pr <= 0.5 else ("警戒" if pr <= 1.0 else "超标")
        rows.append({"name": "组合(等权)", "nav": raw.mean(axis=1).iloc[-1], "dd": pdd, "thr": PORTFOLIO_DD,
                     "ratio": pr, "level": plevel, "streak": 0})
        if plevel == "超标":
            breaches.append(f"组合: 回撤 {pdd:.1%} 超阈值 {PORTFOLIO_DD:.0%}")

    lines = [
        "# 风控状态",
        "",
        f"> 生成时间：{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}",
        "> 规则：回撤 >50% 阈值=警戒；>100% 阈值=超标；连续 3 个月跑输基准=实盘门槛受挫",
        "",
        "| 账户 | 净值 | 当前回撤 | 阈值 | 状态 | 连续跑输月数 |",
        "|------|------|----------|------|------|-------------|",
    ]
    for r in rows:
        icon = {"正常": "✅", "警戒": "⚠️", "超标": "🚨"}[r["level"]]
        lines.append(f"| {r['name']} | {r['nav']:,.0f} | {r['dd']:.2%} | {r['thr']:.0%} | "
                     f"{icon} {r['level']} | {r['streak']} |")
    lines += ["", "## 预警", ""]
    lines += [f"- 🚨 {b}" for b in breaches] if breaches else ["- 无预警，一切正常"]
    lines += ["", "> 自动生成，仅供学习研究参考，不构成投资建议。", ""]
    (ROOT / "docs" / "风控状态.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 1 if breaches else 0


if __name__ == "__main__":
    sys.exit(main())
