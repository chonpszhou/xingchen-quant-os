#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 因子流水线命令行

用法:
    python3 scripts/factor_cli.py run --markets A股 港股 美股 虚拟货币

输出:
    data/factors/factor_panel.parquet   因子面板
    data/factors/factor_ic.csv          IC 汇总
    data/factors/factor_quintiles.csv   分位组合（h=10）
    docs/因子流水线报告.md               自动报告
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from factors.definitions import FACTOR_DEFS  # noqa: E402
from factors.pipeline import build_panel, ic_summary, quintiles  # noqa: E402

DEFAULT_MARKETS = ["A股", "港股", "美股", "虚拟货币"]


def flag(mean_ic, tstat, first, second):
    """稳健性速读：|t|>2 且两半同号 → 稳健候选；同号但弱 → 弱候选；否则不稳定"""
    same_sign = (first > 0) == (second > 0) if first and second else False
    if abs(tstat) >= 2 and same_sign:
        return "稳健候选"
    if same_sign:
        return "弱候选"
    return "不稳定"


def write_report(ic: pd.DataFrame, quint: pd.DataFrame, markets, min_symbols):
    lines = [
        "# 星辰投研团 · 因子流水线报告 v0.1",
        "",
        f"> 生成时间：{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}",
        f"> 市场：{' / '.join(markets)}　·　最小截面 {min_symbols} 只　·　数据：本地 parquet（约 2 年）",
        "",
        "## 方法",
        "",
        "- 因子在 t 日收盘后计算（无未来函数）；前瞻收益为 close[t] → close[t+h]",
        "- 日度截面 Spearman IC；ICIR = mean/std；t 值 = mean/std × √n",
        "- 分位组合：每交易日按因子截面排序分 5 组，组内等权未来 10 日收益，再按天平均",
        "- 分半检验：IC 前后两半符号一致性 + |t|≥2 视为稳健候选",
        "",
        "## 因子定义",
        "",
    ]
    for k, v in FACTOR_DEFS.items():
        lines.append(f"- **{k}**：{v}")
    lines += ["", "## IC 汇总（按市场）", ""]
    for market in markets:
        g = ic[ic["market"] == market]
        if g.empty:
            lines.append(f"### {market}\n\n（样本不足）\n")
            continue
        lines.append(f"### {market}")
        lines.append("")
        lines.append("| 因子 | 前瞻期 | 天数 | 均值IC | ICIR | t值 | 正占比 | 前半年IC | 后半年IC | 速读 |")
        lines.append("|------|--------|------|--------|------|------|--------|----------|----------|------|")
        for _, r in g.iterrows():
            lines.append(f"| {r['factor']} | {r['horizon']}日 | {r['n_days']} | {r['mean_ic']} | {r['icir']} | "
                         f"{r['tstat']} | {r['pos_ratio']} | {r['ic_first_half']} | {r['ic_second_half']} | "
                         f"{flag(r['mean_ic'], r['tstat'], r['ic_first_half'], r['ic_second_half'])} |")
        lines.append("")
    lines += [
        "## 分位组合（前瞻 10 日，组1=因子最低，组5=因子最高）",
        "",
        "| 市场 | 因子 | 组1 | 组2 | 组3 | 组4 | 组5 | 多空价差(5-1) |",
        "|------|------|------|------|------|------|------|---------------|",
    ]
    for _, r in quint.iterrows():
        lines.append(f"| {r['market']} | {r['factor']} | {r['g1']} | {r['g2']} | {r['g3']} | {r['g4']} | {r['g5']} | {r['spread']} |")
    lines += [
        "",
        "## 重要边界（务必阅读）",
        "",
        "- **小截面**：A股/港股/美股 13-20 只、加密仅 6 只，IC 噪声大、分位样本少，结果只用于机制学习与监控，不构成 alpha 结论",
        "- **幸存者偏差**：自选清单是当前存续标的，历史收益存在后视镜偏差",
        "- **未中性化**：未做行业/市值/波动率中性，IC 可能混入风格暴露",
        "- **交易假设**：按收盘价 t→t+h 计算，未计佣金/滑点；A股 T+1 未建模",
        "- 因子稳健性判断以「分半同号 + |t|≥2」为标准，未达到的因子不应直接用于实盘",
        "",
    ]
    (ROOT / "docs" / "因子流水线报告.md").write_text("\n".join(lines), encoding="utf-8")
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description="星辰投研团 因子流水线")
    p.add_argument("--markets", nargs="*", default=DEFAULT_MARKETS)
    p.add_argument("--min-symbols", type=int, default=5)
    p.add_argument("--horizons", type=str, default="5,10,20")
    args = p.parse_args()
    horizons = tuple(int(x) for x in args.horizons.split(","))

    print("构建因子面板...")
    panel = build_panel(markets=args.markets, horizons=horizons, data_dir=str(ROOT / "data"))
    if panel.empty:
        print("面板为空，请先运行 datahub_cli.py update")
        return
    out_dir = ROOT / "data" / "factors"
    out_dir.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(out_dir / "factor_panel.parquet", index=False)
    print(f"面板：{len(panel)} 行，{panel['symbol'].nunique()} 只标的")

    ic_frames, quint_frames = [], []
    for market in args.markets:
        ic = ic_summary(panel, market, horizons=horizons, min_symbols=args.min_symbols)
        if not ic.empty:
            ic_frames.append(ic)
            print(f"\n=== {market} ===")
            print(ic.to_string(index=False))
        for factor in FACTOR_DEFS:
            q, spread = quintiles(panel, market, factor, horizon=10, min_symbols=args.min_symbols)
            if not q.empty:
                row = {"market": market, "factor": factor}
                for _, r in q.iterrows():
                    row[f"g{int(r['group'])}"] = r["mean_fwd_ret"]
                row["spread"] = spread
                quint_frames.append(row)
    ic_all = pd.concat(ic_frames, ignore_index=True) if ic_frames else pd.DataFrame()
    quint_all = pd.DataFrame(quint_frames)
    ic_all.to_csv(out_dir / "factor_ic.csv", index=False, encoding="utf-8-sig")
    quint_all.to_csv(out_dir / "factor_quintiles.csv", index=False, encoding="utf-8-sig")

    print("\n" + write_report(ic_all, quint_all, args.markets, args.min_symbols))
    print("\n已输出：data/factors/（panel/ic/quintiles）+ docs/因子流水线报告.md")


if __name__ == "__main__":
    main()
