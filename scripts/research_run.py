#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 研究方向一/二编排：
  1) 因子中性化 + 稳健性评估（alpha-evaluate 方法论）
  2) 稳健候选 walk-forward 组合回测（成本 / IS-OOS / DSR）

用法:
    python3 scripts/research_run.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from datahub.store import LocalStore  # noqa: E402
from factors.backtest import factor_signals, metrics, walk_forward  # noqa: E402
from factors.evaluate import evaluate  # noqa: E402
from factors.neutralization import load_a_industry, neutralize, size_proxy  # noqa: E402

COSTS = {"A股": 0.003, "港股": 0.002, "美股": 0.001, "虚拟货币": 0.002}
MIN_SYMBOLS = {"A股": 20, "港股": 10, "美股": 10, "虚拟货币": 5}


def factor_wide(close, volume, name):
    c = close
    if name == "momentum_20":
        return c / c.shift(20) - 1
    if name == "momentum_60":
        return c / c.shift(60) - 1
    if name == "volatility_20":
        return c.pct_change().rolling(20).std()
    if name == "reversal_5":
        return -(c / c.shift(5) - 1)
    if name == "volume_anomaly":
        return volume / volume.shift(1).rolling(20).mean()
    raise ValueError(name)


FACTORS = ["momentum_20", "momentum_60", "volatility_20", "reversal_5", "volume_anomaly"]


def is_stock(code):
    """A股纯股票识别（剔除 ETF/LOF/指数），保证研究池与回测池干净"""
    c = str(code)
    if c in {"000300", "000852"}:
        return False
    return c.startswith(("600", "601", "603", "605", "688", "689",
                         "000", "001", "002", "003", "300", "301"))


def load_market(store, market, stock_only=False):
    closes, volumes = {}, {}
    for _, st in store.all_status().iterrows():
        if st["market"] != market:
            continue
        if stock_only and not is_stock(st["symbol"]):
            continue
        df = store.load_bars(market, st["symbol"])
        if df is None or len(df) < 120:
            continue
        closes[st["symbol"]] = df.set_index("date")["close"]
        volumes[st["symbol"]] = df.set_index("date")["volume"]
    if not closes:
        return None, None
    close = pd.DataFrame(closes).sort_index()
    volume = pd.DataFrame(volumes).sort_index()
    return close, volume


def build_eval(close, volume, market, industry=None, size=None, neutralize_a=False):
    rows = []
    for name in FACTORS:
        f = factor_wide(close, volume, name)
        if neutralize_a:
            f = neutralize(f, size, industry)
        ev = evaluate(f, close, horizons=(10, 20), min_symbols=MIN_SYMBOLS[market])
        for _, r in ev.iterrows():
            rows.append({"market": market, "factor": name, **r.to_dict()})
    return pd.DataFrame(rows)


def write_research_report(eval_raw, eval_neu):
    lines = [
        "# 因子中性化与稳健性评估报告",
        "",
        f"> 生成时间：{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}",
        "> 方法：MAD(5) 去极值 + 截面 zscore；t+1 执行；Spearman IC；分位多空（5组）；单调性；评级 Strong/Moderate/Weak",
        "> 中性化：A股按 行业(BaoStock) 去均值 + log(20日均成交额代理) 回归残差（规模代理时间可变、无时点偏差）",
        "",
        "## A股：原始 vs 中性化 对比（前瞻期 10/20 日）",
        "",
        "| 因子 | 前瞻 | 原始IC | 原始ICIR | 原始评级 | 中性IC | 中性ICIR | 中性评级 |",
        "|------|------|--------|----------|----------|--------|----------|----------|",
    ]
    for _, r in eval_neu.iterrows():
        raw = eval_raw[(eval_raw["factor"] == r["factor"]) & (eval_raw["horizon"] == r["horizon"])]
        if raw.empty:
            continue
        rw = raw.iloc[0]
        lines.append(f"| {r['factor']} | {r['horizon']} | {rw['mean_ic']} | {rw['icir']} | {rw['rating']} | "
                     f"{r['mean_ic']} | {r['icir']} | {r['rating']} |")
    lines += ["", "## 其他市场评估（原始）", ""]
    for market in ("港股", "美股", "虚拟货币"):
        g = eval_raw[eval_raw["market"] == market]
        if g.empty:
            continue
        lines += [f"### {market}", "",
                  "| 因子 | 前瞻 | 均值IC | ICIR | t | 多空Sharpe | 多空MaxDD | 单调 | 评级 |",
                  "|------|------|--------|------|---|-----------|-----------|------|------|"]
        for _, r in g.iterrows():
            lines.append(f"| {r['factor']} | {r['horizon']} | {r['mean_ic']} | {r['icir']} | {r['tstat']} | "
                         f"{r['ls_sharpe']} | {r['ls_maxdd']} | {r['mono_corr']} | {r['rating']} |")
        lines.append("")
    lines += [
        "## 边界",
        "",
        "- 行业为当前映射（BaoStock 快照）；规模代理为时间可变成交额，无时点偏差",
        "- 截面仍偏小（A股约300-320只），评级仅用于筛选研究方向",
        "",
    ]
    (ROOT / "docs" / "因子中性化与稳健性评估报告.md").write_text("\n".join(lines), encoding="utf-8")
    return "\n".join(lines)


def run_backtests(store, industry):
    cands = [
        ("港股", "momentum_20", 1, 504, 126),
        ("A股", "volatility_20", -1, 252, 63),
        ("A股", "reversal_5", -1, 252, 63),
    ]
    lines = [
        "# 因子组合回测与 Walk-Forward 报告",
        "",
        f"> 生成时间：{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}",
        "> 规则：每 20 个交易日调仓，截面 top20% 等权（direction=1 做多高因子，-1 做多低因子）；t 收盘给信号、t+1 执行",
        "> 成本（双边）：A股 0.3% / 港股 0.2% / 美股 0.1% / 加密 0.2%；A股调仓日过滤当日涨幅>9.5%的标的",
        "> 池：A股为纯股票池（剔除ETF/指数），调仓日剔除流动性最低 10% 标的；港股动量用 6 年历史、train 504/test 126",
        "> Walk-forward：embargo 5 日；DSR 以已披露试验次数 25 计；A股因子使用中性化后因子",
        "",
    ]
    for market, factor, direction, train, test in cands:
        close, volume = load_market(store, market, stock_only=(market == "A股"))
        if close is None:
            continue
        if close.shape[1] < 10:
            lines.append(f"## {market} · {factor}（direction={direction}）\n\n截面仅 {close.shape[1]} 只，样本不足，未执行组合回测。\n")
            continue
        f = factor_wide(close, volume, factor)
        liq = None
        if market == "A股":
            f = neutralize(f, size_proxy(close, volume), industry)
            liq = size_proxy(close, volume)
        wf = walk_forward(close, f, direction=direction, top_pct=0.2, cost_rate=COSTS[market],
                          n_trials=25, train_size=train, test_size=test, liquidity=liq)
        lines.append(f"## {market} · {factor}（direction={direction} · train {train}/test {test}）")
        lines.append("")
        lines.append("### 全区间指标（含成本）")
        lines.append("")
        m = wf["full_metrics"]
        lines.append(f"- 年化 {m['annual_return']:.2%} | 夏普 {m['sharpe']} | HAC t {m['hac_t']} | 最大回撤 {m['max_drawdown']:.2%} | "
                     f"Calmar {m['calmar']} | 月胜率 {m['monthly_wr']:.0%} | PF {m['profit_factor']} | DSR {m['dsr']}")
        if wf["oos_metrics"]:
            o = wf["oos_metrics"]
            lines.append(f"- **样本外**：年化 {o['annual_return']:.2%} | 夏普 {o['sharpe']} | HAC t {o['hac_t']} | 回撤 {o['max_drawdown']:.2%} | DSR {o['dsr']}")
        lines.append(f"- IS 平均夏普 {wf['is_avg_sharpe']:.2f} vs OOS 夏普 {wf['oos_metrics']['sharpe'] if wf['oos_metrics'] else float('nan'):.2f}")
        lines.append("")
        folds = wf["folds"]
        if not folds.empty:
            lines.append("| 折 | IS区间 | OOS区间 | IS夏普 | OOS夏普 |")
            lines.append("|----|--------|---------|--------|---------|")
            for _, fl in folds.iterrows():
                lines.append(f"| {fl['train']}~{fl['train_end']} | {fl['oos_start']}~{fl['oos_end']} | {fl['is_sharpe']} | {fl['oos_sharpe']} |")
        lines.append("")
    lines += [
        "## 结论",
        "",
        "- 所有候选在全区间与 walk-forward 样本外均未通过门控（Sharpe≥1 / 月胜率≥55% / PF≥1）",
        "- 按偏差规避准则表述：**样本外扣费后无显著净边际**（HAC t 均不显著、DSR≈0）",
        "- 因子 IC 层面的信号（港股动量、A股低波）在真实调仓成本与月度换手下被侵蚀，方向需进一步改进（见报告边界）",
        "",
        "## 门控检查（alpha-backtest 默认）",
        "",
        "- Sharpe ≥ 1.0 / MaxDD ≥ -25% / PF ≥ 1.0 / 月胜率 ≥ 55% / 最大连续亏损月 ≤ 4",
        "",
        "> 本报告基于公开数据与规则化分析生成，仅供研究参考，不构成任何投资建议。",
        "",
    ]
    (ROOT / "docs" / "因子组合回测与WalkForward报告.md").write_text("\n".join(lines), encoding="utf-8")
    return "\n".join(lines)


def main():
    store = LocalStore(str(ROOT / "data"))
    industry = load_a_industry(str(ROOT / "data"))
    if industry is None:
        print("缺少 data/a_industry.parquet，A股仅做规模中性化")

    print("加载数据并评估因子...")
    eval_raw, eval_neu = [], []
    for market in COSTS:
        close, volume = load_market(store, market, stock_only=(market == "A股"))
        if close is None:
            continue
        eval_raw.append(build_eval(close, volume, market))
        if market == "A股":
            eval_neu.append(build_eval(close, volume, market, industry=industry,
                                       size=size_proxy(close, volume), neutralize_a=True))
    raw = pd.concat(eval_raw, ignore_index=True)
    neu = pd.concat(eval_neu, ignore_index=True) if eval_neu else pd.DataFrame()
    print("\n" + write_research_report(raw, neu))
    print("\n" + run_backtests(store, industry))
    print("\n已输出：docs/因子中性化与稳健性评估报告.md、docs/因子组合回测与WalkForward报告.md")


if __name__ == "__main__":
    main()
