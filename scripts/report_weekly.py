#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 周报生成器（每周日）

内容：三模拟盘周度变化与基准对照 / 双低 TOP10 变化与预警 / IV 快照 / 期货异动

用法:
    python3 scripts/report_weekly.py
输出:
    docs/周报_日期.md
"""

import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent

ACCOUNTS = [
    ("可转债双低", ROOT / "data" / "paper_cb_nav.parquet", "全债等权"),
    ("双动量", ROOT / "data" / "paper_mom_nav.parquet", "SPY持有"),
    ("风险平价", ROOT / "data" / "paper_rp_nav.parquet", "SPY持有"),
]


def weekly_row(name, nav_file, bench_name):
    if not nav_file.exists():
        return None
    df = pd.read_parquet(nav_file)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")
    cur = df.iloc[-1]
    week_ago = df[df["date"] >= cur["date"] - pd.Timedelta(days=7)]
    prev = week_ago.iloc[0] if len(week_ago) > 1 else cur
    chg = cur["nav"] / prev["nav"] - 1
    bench_chg = cur["bench_nav"] / prev["bench_nav"] - 1 if "bench_nav" in df.columns else None
    return {"name": name, "nav": cur["nav"], "week": chg, "bench": bench_chg,
            "excess": (chg - bench_chg) if bench_chg is not None else None}


def main():
    lines = [
        f"# 星辰投研团 · 周报（截至 {date.today()}）",
        "",
    ]
    rows = [r for r in (weekly_row(*a) for a in ACCOUNTS) if r]
    if rows:
        lines += ["## 模拟盘周度变化", "",
                  "| 策略 | 净值 | 周度 | 基准周度 | 超额 |",
                  "|------|------|------|----------|------|"]
        for r in rows:
            b = f"{r['bench']:.2%}" if r["bench"] is not None else "-"
            e = f"{r['excess']:+.2%}" if r["excess"] is not None else "-"
            lines.append(f"| {r['name']} | {r['nav']:,.0f} | {r['week']:.2%} | {b} | {e} |")
        lines.append("")
    else:
        lines.append("模拟盘数据积累中。\n")

    snap = ROOT / "data" / "cb_daily_snapshot.json"
    if snap.exists():
        s = json.loads(snap.read_text(encoding="utf-8"))
        lines += ["## 双低 TOP5 与预警", "",
                  "| 名称 | 价格 | 溢价 | 双低值 | 评级 |",
                  "|------|------|------|--------|------|"]
        for r in s["rank"][:5]:
            lines.append(f"| {r['name']} | {r['price']:.1f} | {r['premium']:.1f}% | {r['score']:.1f} | {r.get('rating','-')} |")
        if s.get("alerts"):
            lines += ["", "### 预警", ""] + [f"- ⚠ {a}" for a in s["alerts"]]
        lines.append("")

    iv = ROOT / "docs" / "期权IV监控快照.md"
    if iv.exists():
        lines += ["## 期权 IV（指数级）", ""]
        for line in iv.read_text(encoding="utf-8").splitlines():
            if line.startswith("| VIX") or line.startswith("| VXN") or line.startswith("| VXD"):
                lines.append(line)
        lines.append("")
    lines += ["---", "> 自动生成，仅供学习研究参考，不构成投资建议。", ""]
    out = ROOT / "docs" / f"周报_{date.today():%Y%m%d}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"已输出：{out}")
    print("\n".join(lines[:12]))


if __name__ == "__main__":
    main()
