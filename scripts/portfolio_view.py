#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 组合模拟盘视图（三策略加权）

把三个模拟盘合并为“推荐组合”，展现系统级风险收益画像：
  - 默认权重：双低 40% / 双动量 30% / 风险平价 30%（可调）
  - 输出组合净值、回撤、月度胜率、与基准（全债/SPY 混合）对照

用法:
    python3 scripts/portfolio_view.py [--w-cb 0.4 --w-mom 0.3 --w-rp 0.3]
输出:
    docs/组合模拟盘视图.md
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from factors.backtest import metrics  # noqa: E402

FILES = {
    "cb": ROOT / "data" / "paper_cb_nav.parquet",
    "mom": ROOT / "data" / "paper_mom_nav.parquet",
    "rp": ROOT / "data" / "paper_rp_nav.parquet",
}


def load_nav(name):
    df = pd.read_parquet(FILES[name])
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").drop_duplicates("date").set_index("date")
    return df["nav"], df["bench_nav"]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--w-cb", type=float, default=0.4)
    p.add_argument("--w-mom", type=float, default=0.3)
    p.add_argument("--w-rp", type=float, default=0.3)
    args = p.parse_args()
    if abs(args.w_cb + args.w_mom + args.w_rp - 1) > 1e-6:
        print("权重之和须为 1")
        return

    navs, benchs = {}, {}
    for name in FILES:
        if not FILES[name].exists():
            print(f"缺少 {name} 模拟盘数据，先运行 run_all.py all")
            return
        navs[name], benchs[name] = load_nav(name)

    weights = {"cb": args.w_cb, "mom": args.w_mom, "rp": args.w_rp}
    all_dates = sorted(set().union(*[set(n.index) for n in navs.values()]))
    idx = pd.DatetimeIndex(all_dates)

    # 组合净值 = Σ w_i × nav_i / nav_i[首日]（以各自起点 100 万归一）
    port = pd.Series(0.0, index=idx)
    bench = pd.Series(0.0, index=idx)
    for name, w in weights.items():
        n = navs[name].reindex(idx).ffill()
        base = n.dropna().iloc[0]
        port = port.add(w * n / base, fill_value=0.0)
        b = benchs[name].reindex(idx).ffill()
        if b.notna().any():
            bbase = b.dropna().iloc[0]
            bench = bench.add(w * b / bbase, fill_value=0.0)
    port = port.replace(0.0, np.nan).ffill().dropna()
    bench = bench.replace(0.0, np.nan).ffill().dropna()
    port = port / port.iloc[0]
    bench = bench / bench.iloc[0]

    m = metrics(port, 0.0, n_trials=3)
    mb = metrics(bench, 0.0, n_trials=3)
    dd = ((port - port.cummax()) / port.cummax()).min()
    yearly = port.resample("YE").last().pct_change().fillna(port.resample("YE").last().iloc[0] - 1)

    lines = [
        "# 组合模拟盘视图（三策略加权）",
        "",
        f"> 生成时间：{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}",
        f"> 权重：双低 {args.w_cb:.0%} / 双动量 {args.w_mom:.0%} / 风险平价 {args.w_rp:.0%}（--w-* 可调）",
        f"> 区间：{port.index[0].date()} ~ {port.index[-1].date()}（{len(port)} 个净值日）",
        "",
        "## 组合指标",
        "",
        f"- 累计收益 {m['total_return']:.2%} | 年化 {m['annual_return']:.2%} | 夏普 {m['sharpe']} | HAC t {m['hac_t']}",
        f"- 最大回撤 {dd:.2%} | 月度胜率 {m['monthly_wr']:.0%} | PF {m['profit_factor']}",
        f"- 混合基准（同权重基准加权）：累计 {mb['total_return']:.2%} | 回撤 {mb['max_drawdown']:.2%} | 超额 {m['total_return'] - mb['total_return']:+.2%}",
        "",
        "## 年度收益",
        "",
        "| 年份 | 组合 |",
        "|------|------|",
    ]
    for d, r in yearly.items():
        lines.append(f"| {d.year} | {r:.2%} |")
    lines += [
        "",
        "## 三策略贡献",
        "",
        "| 策略 | 权重 | 净值 | 累计 |",
        "|------|------|------|------|",
    ]
    for name in ("cb", "mom", "rp"):
        n = navs[name]
        lines.append(f"| {name} | {weights[name]:.0%} | {n.iloc[-1]:,.0f} | {n.iloc[-1] / 1e6 - 1:.2%} |")
    lines += [
        "",
        "## 定位",
        "",
        "- 组合=收益（双低）+ 趋势（双动量）+ 稳定（风险平价）三档叠加，追求“回撤可控前提下的复利”",
        "- 权重是建议起点，风险偏好高可提高双动量比例；保守可提高风险平价比例",
        "- 实盘门槛仍以单个模拟盘连续 3 个月跑赢各自基准为准，组合仅作整体画像",
        "",
        "> 仅供学习研究参考，不构成投资建议。",
        "",
    ]
    out = ROOT / "docs" / "组合模拟盘视图.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"已输出：{out}")
    print(f"组合：累计 {m['total_return']:.2%} | 年化 {m['annual_return']:.2%} | 回撤 {dd:.2%} | 夏普 {m['sharpe']}")


if __name__ == "__main__":
    main()
