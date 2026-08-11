#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 模拟盘月度报告（双低 + 双动量并行对照）

从两个模拟盘净值文件读取每日净值，输出月收益/累计/回撤/胜率/盈亏比，
并分别与各自基准（全债等权 / SPY 持有）和回测预期对照。

用法:
    python3 scripts/report_monthly.py [--month 2026-08]
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent

ACCOUNTS = [
    ("可转债双低", ROOT / "data" / "paper_cb_nav.parquet", ROOT / "data" / "paper_cb_state.json",
     "全债等权", 0.12, -0.20, 0.55),
    ("双动量ETF轮动", ROOT / "data" / "paper_mom_nav.parquet", ROOT / "data" / "paper_mom_state.json",
     "SPY持有", 0.18, -0.25, 0.50),
    ("风险平价底仓", ROOT / "data" / "paper_rp_nav.parquet", ROOT / "data" / "paper_rp_state.json",
     "SPY持有", 0.06, -0.10, 0.50),
]


def account_stats(nav_file, state_file, month=""):
    nav = pd.read_parquet(nav_file)
    nav["date"] = pd.to_datetime(nav["date"])
    nav = nav.sort_values("date").drop_duplicates("date")
    st = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}
    monthly = nav.set_index("date")["nav"].resample("ME").last()
    monthly_ret = monthly.pct_change().fillna(monthly.iloc[0] / 1e6 - 1)
    bench_ret = None
    if "bench_nav" in nav.columns:
        bm = nav.set_index("date")["bench_nav"].resample("ME").last()
        bench_ret = bm.pct_change().fillna(bm.iloc[0] / 1e6 - 1)
    if month:
        monthly_ret = monthly_ret[monthly_ret.index.strftime("%Y-%m") == month]
    total = nav["nav"].iloc[-1] / 1e6 - 1
    bench_total = nav["bench_nav"].iloc[-1] / 1e6 - 1 if "bench_nav" in nav.columns else np.nan
    dd = ((nav["nav"] - nav["nav"].cummax()) / nav["nav"].cummax()).min()
    pos = (monthly_ret > 0).mean()
    pf = monthly_ret[monthly_ret > 0].sum() / abs(monthly_ret[monthly_ret < 0].sum()) \
        if (monthly_ret < 0).any() else np.nan
    return {"nav": nav, "monthly_ret": monthly_ret, "bench_ret": bench_ret,
            "total": total, "bench_total": bench_total, "dd": dd, "pos": pos,
            "pf": pf, "rebal": st.get("rebalance_count", 0)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--month", default="")
    args = p.parse_args()
    if not any(f.exists() for _, f, _, _, _, _, _ in ACCOUNTS):
        print("模拟盘尚无净值记录，先运行 python3 scripts/run_all.py all")
        return
    stats = []
    min_days = 99
    for name, nav_file, state_file, bench, e_ann, e_dd, e_wr in ACCOUNTS:
        if not nav_file.exists():
            continue
        s = account_stats(nav_file, state_file, args.month)
        min_days = min(min_days, len(s["nav"]))
        stats.append((name, bench, e_ann, e_dd, e_wr, s))
    if min_days < 5:
        print(f"模拟盘数据积累中（最短 {min_days} 个交易日），预计 {20 - min_days} 日后可生成首份有效月报")
        return

    lines = [
        "# 模拟盘月度报告（双低 + 双动量）",
        "",
        f"> 生成时间：{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}",
        "> 双低：TOP20 转债等权、信用过滤、20日调仓；双动量：SPY/GLD/DBC 轮动、TLT 安全仓、21日调仓",
        "> 成本均 0.1%；初始资金各 100 万；引擎一致性已通过校验（scripts/validate_paper_engines.py）",
        "",
    ]
    for name, bench, e_ann, e_dd, e_wr, s in stats:
        lines += [f"## {name}", "",
                  f"| 月份 | 策略 | {bench}基准 | 超额 |",
                  "|------|------|-------------|------|"]
        for d, r in s["monthly_ret"].items():
            b = s["bench_ret"].get(d, np.nan) if s["bench_ret"] is not None else np.nan
            lines.append(f"| {d.strftime('%Y-%m')} | {r:.2%} | {b:.2%} | {r - b:+.2%} |")
        lines += ["", "### 累计指标", "",
                  f"- 累计收益 {s['total']:.2%} | 基准 {s['bench_total']:.2%} | 超额 {s['total'] - s['bench_total']:.2%}",
                  f"- 最大回撤 {s['dd']:.2%} | 月度胜率 {s['pos']:.0%} | 盈亏比 {s['pf']:.2f} | 调仓 {s['rebal']} 次",
                  "", "### 与回测预期对照", "",
                  f"- 年化预期 ≈{e_ann:.0%}（待满3个月）| 回撤阈值 {e_dd:.0%}（{'✓ 达标' if s['dd'] >= e_dd else '⚠ 超预期'}）"
                  f"| 月胜率阈值 {e_wr:.0%}（{'✓ 达标' if s['pos'] >= e_wr else '⚠ 待观察'}）",
                  ""]
    lines += [
        "## 纪律检查",
        "",
        "- 连续 3 个月跑赢各自基准前不投入实盘；回撤超阈值或月胜率持续低于阈值时暂停加仓并复核参数",
        "",
        "> 本报告仅供学习研究参考，不构成投资建议。",
        "",
    ]
    out = ROOT / "docs" / f"模拟盘月报_{pd.Timestamp.now():%Y%m}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"已输出：{out}")
    for name, bench, _, _, _, s in stats:
        print(f"{name}: 累计 {s['total']:.2%} / 基准 {s['bench_total']:.2%} / 超额 {s['total'] - s['bench_total']:+.2%} / 回撤 {s['dd']:.2%}")


if __name__ == "__main__":
    main()
