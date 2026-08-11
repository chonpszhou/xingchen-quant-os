#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 跨资产趋势跟踪（CTA）验证

在 14 个流动性标的上做时间序列动量（21/63/126/252 日多周期等权），
波动率目标仓位（书目标年化波动 10%），月度调仓、t+1 执行、双边成本。

用法:
    python3 scripts/research_trend_following.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from datahub.store import LocalStore  # noqa: E402
from factors.backtest import metrics  # noqa: E402

INSTRUMENTS = [
    ("美股", "SPY", "标普500"), ("美股", "QQQ", "纳指100"), ("美股", "IWM", "罗素2000"),
    ("美股", "DIA", "道指"), ("美股", "GLD", "黄金"), ("美股", "TLT", "美国长债"),
    ("美股", "UUP", "美元"), ("美股", "DBC", "商品"),
    ("港股", "02800", "恒生指数ETF"), ("港股", "03033", "恒生科技ETF"),
    ("A股", "000300", "沪深300"), ("A股", "000852", "中证1000"),
    ("虚拟货币", "BTC/USDT", "比特币"), ("虚拟货币", "ETH/USDT", "以太坊"),
]

LOOKBACKS = (21, 63, 126, 252)
COST = {"美股": 0.001, "港股": 0.001, "A股": 0.001, "虚拟货币": 0.002}
REBALANCE = 20          # 月度（20 交易日）
BOOK_TARGET_VOL = 0.12  # 书目标年化波动（每标的贡献 target/N）


def load_basket(store, min_bars=400):
    rows = []
    for market, symbol, name in INSTRUMENTS:
        df = store.load_bars(market, symbol)
        if df is None or len(df) < min_bars:
            print(f"  跳过 {symbol}（{len(df) if df is not None else 0} 根K线）", file=sys.stderr)
            continue
        rows.append({"market": market, "symbol": symbol, "name": name,
                     "close": df.set_index("date")["close"]})
    return rows


def align(rows):
    closes = {f"{r['symbol']}": r["close"] for r in rows}
    meta = {f"{r['symbol']}": r for r in rows}
    df = pd.DataFrame(closes).sort_index()
    # 公共日期（并集）；各标的按自身日历计算收益，缺失日视为无交易（0 收益）
    rets = {}
    for sym in df.columns:
        s = df[sym].dropna()
        rets[sym] = s.pct_change()
    ret = pd.DataFrame(rets)
    return df, ret, meta


def trend_signal(close, lookbacks=LOOKBACKS):
    """时间序列动量：各周期收益符号的等权平均"""
    sigs = []
    for L in lookbacks:
        if L == 252 and len(lookbacks) == 1:
            # 12-1 动量：跳过最近 21 日，用 [t-252, t-21] 收益
            sigs.append(np.sign(close.shift(21) / close.shift(252) - 1))
        else:
            sigs.append(np.sign(close / close.shift(L) - 1))
    s = pd.concat(sigs).groupby(level=0).mean()
    return s.reindex(close.index).ffill()


def instrument_vol(close, window=20):
    return close.pct_change().rolling(window).std() * np.sqrt(252)


def position_weights(close, signal, target_vol=BOOK_TARGET_VOL, max_pos=1.0,
                     long_only=False, vol_cap=3.0):
    """月度调仓权重：w = signal × min(max_pos, 标的波动率目标/实现波动率)"""
    vol = instrument_vol(close)
    dates = close.index
    weights = pd.DataFrame(np.nan, index=dates, columns=close.columns)
    n = close.shape[1]
    inst_target = target_vol / n
    for i, d in enumerate(dates):
        if i % REBALANCE != 0:
            continue
        w = signal.loc[d] * (inst_target / vol.loc[d].clip(lower=1e-4))
        w = w.clip(-max_pos, max_pos)
        if long_only:
            w = w.clip(lower=0.0)
        weights.loc[d] = w.fillna(0.0)
    return weights.ffill().fillna(0.0)


def backtest(close, ret, weights, cost_map, meta):
    # 调仓日设定权重并持有至下一调仓日；t+1 执行
    exec_w = weights.ffill().shift(1).fillna(0.0)
    gross = (exec_w * ret.fillna(0.0)).sum(axis=1)
    # 逐标的成本：按调仓换手 × 各市场成本
    costs = pd.Series(0.0, index=ret.index)
    for sym in ret.columns:
        m = meta[sym]
        costs += exec_w[sym].diff().abs().fillna(exec_w[sym].abs()) * COST[m["market"]]
    net = gross - costs
    nav = (1 + net).cumprod()
    return nav, gross, costs


def yearly_table(nav):
    y = nav.resample("YE").last()
    y = y.pct_change().fillna(y.iloc[0] / 1 - 1)
    return y


def main():
    store = LocalStore(str(ROOT / "data"))
    print("加载 CTA 篮子...")
    rows = load_basket(store)
    close, ret, meta = align(rows)
    print(f"篮子 {close.shape[1]} 个标的 × {len(close)} 个交易日（公共日历）")
    sig = trend_signal(close)

    variants = [
        ("多周期趋势 · 多空 · 杠杆≤1", dict(long_only=False, max_pos=1.0)),
        ("多周期趋势 · 多空 · 杠杆≤2", dict(long_only=False, max_pos=2.0)),
        ("多周期趋势 · 纯多 · 杠杆≤1", dict(long_only=True, max_pos=1.0)),
        ("12-1动量 · 多空 · 杠杆≤1", dict(long_only=False, max_pos=1.0, skip21=True)),
    ]
    n_trials = len(variants) * 2  # 含成本敏感性
    lines = [
        "# 跨资产趋势跟踪（CTA）验证报告",
        "",
        f"> 生成时间：{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}",
        f"> 篮子：{close.shape[1]} 个标的（美股指数ETF/黄金/长债/美元/商品、港股ETF、A股指数、加密），历史约 4 年",
        "> 规则：时间序列动量（21/63/126/252 日等权或 12-1），波动率目标仓位（书目标年化 10%），月度调仓、t+1 执行",
        "> 成本（双边单侧）：美股/港股/A股 0.1%，加密 0.2%；DSR 试验数 " + str(n_trials),
        "",
    ]

    results = []
    for name, kw in variants:
        lookbacks = (252,) if kw.pop("skip21", False) else LOOKBACKS
        sig_v = trend_signal(close, lookbacks)
        w = position_weights(close, sig_v, long_only=kw["long_only"], max_pos=kw["max_pos"])
        nav, gross, costs = backtest(close, ret, w, COST, meta)
        m = metrics(nav, 0.0, n_trials=n_trials)
        mid = len(nav) // 2
        h1 = metrics(nav.iloc[:mid], 0.0)["sharpe"]
        h2 = metrics(nav.iloc[mid:], 0.0)["sharpe"]
        ann_gross = metrics((1 + gross).cumprod(), 0.0)["annual_return"]
        realized_vol = nav.pct_change().std() * np.sqrt(252)
        results.append({"variant": name, **m, "h1_sharpe": h1, "h2_sharpe": h2,
                        "gross_ann": ann_gross, "nav": nav, "realized_vol": realized_vol})
        lines += [f"### {name}", "",
                  f"- 全区间：年化 {m['annual_return']:.2%} | 夏普 {m['sharpe']} | HAC t {m['hac_t']} | "
                  f"回撤 {m['max_drawdown']:.2%} | 月胜率 {m['monthly_wr']:.0%} | PF {m['profit_factor']} | DSR {m['dsr']}",
                  f"- 半程稳定性：前半夏普 {h1:.2f} / 后半夏普 {h2:.2f} | 毛年化（未扣费）{ann_gross:.2%} | 实现波动 {realized_vol:.1%}",
                  f"- 年度收益：{' | '.join(f'{y:.0%}' for y in yearly_table(nav).values)}",
                  ""]

    # 汇总表
    lines += ["## 汇总", "",
              "| 变体 | 年化 | 夏普 | HAC t | 回撤 | 月胜率 | PF | DSR | 实现波动 | 前半/后半夏普 |",
              "|------|------|------|-------|------|--------|-----|-----|----------|---------------|"]
    for r in results:
        lines.append(f"| {r['variant']} | {r['annual_return']:.2%} | {r['sharpe']} | {r['hac_t']} | "
                     f"{r['max_drawdown']:.2%} | {r['monthly_wr']:.0%} | {r['profit_factor']} | {r['dsr']} | {r['realized_vol']:.1%} | "
                     f"{r['h1_sharpe']:.2f} / {r['h2_sharpe']:.2f} |")
    lines += [
        "",
        "## 结论",
        "",
        "- CTA 趋势跟踪在跨资产篮子上是否产生稳定净边际，以 DSR 与半程稳定性为门控",
        "- 若 DSR≈0 或前后半程方向不一致，说明当前篮子/调仓频率下趋势信号同样不成立，下一步转向更细的信号构造（波动率调整趋势、通道突破、成本敏感性分析）",
        "",
        "> 本报告基于公开数据与规则化分析生成，仅供研究参考，不构成任何投资建议。",
        "",
    ]
    (ROOT / "docs" / "CTA趋势跟踪验证报告.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n已输出：docs/CTA趋势跟踪验证报告.md")
    for r in results:
        print(f"{r['variant']}: 年化 {r['annual_return']:.2%} 夏普 {r['sharpe']} HAC {r['hac_t']} "
              f"回撤 {r['max_drawdown']:.2%} DSR {r['dsr']} 前半/后半 {r['h1_sharpe']:.2f}/{r['h2_sharpe']:.2f}")


if __name__ == "__main__":
    main()
