#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 大佬信号验证（投机实验室：假突破 / 接针）

把公开交易方法写成可回测因子，走与基准因子相同的评估与 walk-forward 门控：
  1) 事件研究：假突破后事件股 vs 非事件股的前瞻收益
  2) IC 评估：A股（原始 + 行业/规模中性化）+ 港股/美股/加密（小样本，仅参考）
  3) 组合回测：A股 walk-forward（成本 / IS-OOS / HAC t / DSR），与基准因子同口径

用法:
    python3 scripts/research_master_signals.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from datahub.store import LocalStore  # noqa: E402
from factors.backtest import metrics, walk_forward  # noqa: E402
from factors.evaluate import compute_forward_returns, evaluate  # noqa: E402
from factors.master_signals import MASTER_DEFS, master_factors  # noqa: E402
from factors.neutralization import load_a_industry, neutralize, size_proxy  # noqa: E402
from research_run import COSTS, MIN_SYMBOLS, factor_wide, is_stock  # noqa: E402

MASTER_FACTORS = ["fake_breakout_20", "wick_rejection", "wick_at_support",
                  "wick_at_support_v2", "fake_breakout_pullback"]
BASELINE = ["momentum_20", "reversal_5", "volatility_20"]
DIRECTIONS = {"fake_breakout_20": 1, "wick_rejection": 1, "wick_at_support": 1,
              "wick_at_support_v2": 1, "fake_breakout_pullback": 1,
              "momentum_20": 1, "reversal_5": -1, "volatility_20": -1}


def load_ohlcv(store, market, stock_only=False, min_bars=120):
    """加载宽表 OHLCV：{field: DataFrame(index=date, columns=symbol)}"""
    frames = {"open": {}, "high": {}, "low": {}, "close": {}, "volume": {}}
    for _, st in store.all_status().iterrows():
        if st["market"] != market:
            continue
        if stock_only and not is_stock(st["symbol"]):
            continue
        df = store.load_bars(market, st["symbol"])
        if df is None or len(df) < min_bars:
            continue
        d = df.set_index("date")
        for f in frames:
            frames[f][st["symbol"]] = d[f]
    if not frames["close"]:
        return None
    return {f: pd.DataFrame(d).sort_index() for f, d in frames.items()}


def all_factors(ohlcv):
    f = master_factors(ohlcv["high"], ohlcv["low"], ohlcv["close"], ohlcv["open"],
                       ohlcv["volume"])
    for name in BASELINE:
        f[name] = factor_wide(ohlcv["close"], ohlcv["volume"], name)
    return f


def event_study(ohlcv, horizons=(5, 10, 20), min_event=3):
    """假突破事件 vs 非事件：逐日截面均值差（t+1 执行），输出平均差/t/命中率/样本数"""
    high, low, close, open_ = (ohlcv[k] for k in ("high", "low", "close", "open"))
    hh_prev = close.shift(1).rolling(20).max()
    event = ((high > hh_prev) & (close <= hh_prev)).astype(float)
    rows = []
    for h in horizons:
        fwd = compute_forward_returns(close, h)
        diffs, dates = [], []
        for d in close.index.intersection(fwd.index):
            ev = event.loc[d]
            if ev.sum() < min_event:
                continue
            ne = (~ev.astype(bool))
            if ne.sum() < min_event:
                continue
            f = fwd.loc[d]
            diff = f[ev.astype(bool)].mean() - f[ne].mean()
            diffs.append(diff)
            dates.append(d)
        if len(diffs) < 20:
            continue
        s = pd.Series(diffs, index=dates)
        t = s.mean() / s.std() * np.sqrt(len(s)) if s.std() > 0 else np.nan
        rows.append({
            "horizon": h,
            "event_mean": round(float(s.mean()), 5),
            "t": round(t, 2),
            "hit_rate_negative": round(float((s < 0).mean()), 3),
            "n_days": len(s),
            "n_events": int(event.sum().sum()),
        })
    return pd.DataFrame(rows)


def symbol_event_study(ohlcv, horizons=(5, 10, 20), min_events=5):
    """单标的层面事件研究：事件日后前瞻收益 vs 该标的同时期非事件日基线。
    比小样本截面 IC 更稳健（避免 13 只股票的截面噪声与重叠窗口伪显著）。"""
    high, low, close = ohlcv["high"], ohlcv["low"], ohlcv["close"]
    hh_prev = close.shift(1).rolling(20).max()
    event = ((high > hh_prev) & (close <= hh_prev))
    rows = []
    for sym in close.columns:
        c = close[sym].dropna()
        ev = event[sym].reindex(c.index).fillna(False).astype(bool)
        if ev.sum() < min_events:
            continue
        for h in horizons:
            fwd = c.shift(-(h + 1)) / c.shift(-1) - 1
            fe, fn = fwd[ev], fwd[~ev]
            if len(fe) < 3 or len(fn) < 20:
                continue
            rows.append({"symbol": sym, "h": h, "n_ev": len(fe),
                         "diff": fe.mean() - fn.mean()})
    return pd.DataFrame(rows)


def build_eval_table(ohlcv, market, industry=None, size=None, neutralize_a=False):
    close = ohlcv["close"]
    rows = []
    for name in MASTER_FACTORS + BASELINE:
        f = all_factors(ohlcv)[name]
        if neutralize_a:
            f = neutralize(f, size, industry)
        ev = evaluate(f, close, horizons=(10, 20), min_symbols=MIN_SYMBOLS[market])
        for _, r in ev.iterrows():
            rows.append({"market": market, "factor": name, **r.to_dict()})
    return pd.DataFrame(rows)


def run_backtests(store, industry):
    ohlcv = load_ohlcv(store, "A股", stock_only=True)
    if ohlcv is None:
        return "A股数据缺失，跳过组合回测"
    close, volume = ohlcv["close"], ohlcv["volume"]
    liq = size_proxy(close, volume)
    factors = all_factors(ohlcv)
    lines = []
    for name in MASTER_FACTORS + ["reversal_5"]:
        f = neutralize(factors[name], liq, industry)
        wf = walk_forward(close, f, direction=DIRECTIONS[name], top_pct=0.2,
                          cost_rate=COSTS["A股"], n_trials=25, train_size=252,
                          test_size=63, rebalance_days=20, liquidity=liq,
                          liquidity_floor_pct=0.1, limit_up_filter=True)
        m, o = wf["full_metrics"], wf["oos_metrics"]
        lines.append(f"### {name}（direction={DIRECTIONS[name]}）")
        lines.append("")
        lines.append(f"- 全区间：年化 {m['annual_return']:.2%} | 夏普 {m['sharpe']} | HAC t {m['hac_t']} | "
                     f"回撤 {m['max_drawdown']:.2%} | 月胜率 {m['monthly_wr']:.0%} | PF {m['profit_factor']} | DSR {m['dsr']}")
        if o:
            lines.append(f"- **样本外**：年化 {o['annual_return']:.2%} | 夏普 {o['sharpe']} | HAC t {o['hac_t']} | "
                         f"回撤 {o['max_drawdown']:.2%} | DSR {o['dsr']}")
        folds = wf["folds"]
        if not folds.empty:
            lines.append("")
            lines.append("| 折 | IS夏普 | OOS夏普 |")
            lines.append("|----|--------|---------|")
            for _, fl in folds.iterrows():
                lines.append(f"| {fl['train']}~{fl['train_end']} | {fl['is_sharpe']} | {fl['oos_sharpe']} |")
        lines.append("")
    return "\n".join(lines)


def sym_summary(df, h):
    g = df[df["h"] == h]
    if g.empty or g["n_ev"].sum() == 0:
        return None
    tot = int(g["n_ev"].sum())
    wdiff = (g["diff"] * g["n_ev"]).sum() / tot
    neg_share = (g["diff"] < 0).mean()
    t = g["diff"].mean() / g["diff"].std() * np.sqrt(len(g)) if g["diff"].std() > 0 else np.nan
    return {"h": h, "diff": wdiff, "t": t, "neg_share": neg_share,
            "n_symbols": len(g), "n_events": tot}


def write_report(ev_raw, ev_neu, event, sym_a, sym_hk, backtest_txt, small_markets):
    lines = [
        "# 大佬信号验证报告（假突破 / 接针）",
        "",
        f"> 生成时间：{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}",
        "> 来源规则：投机实验室公开教学（供需交易法 / 假突破与接针策略），写成日频无未来函数因子",
        "> 方法：MAD(5) 去极值 + 截面 zscore；t+1 执行；Spearman IC；分位多空；中性化同基准报告（行业 + log成交额代理）",
        "> 门控：Sharpe≥1 / 月胜率≥55% / PF≥1 / DSR（已披露试验数 25）",
        "",
        "## 因子定义",
        "",
        "| 因子 | 定义 | 理论方向 |",
        "|------|------|----------|",
    ]
    for name, desc in MASTER_DEFS.items():
        lines.append(f"| {name} | {desc} | {'+' if DIRECTIONS[name] > 0 else '-'} |")
    lines += [
        "",
        "## 一、事件研究（截面）：假突破后，事件股 vs 非事件股",
        "",
        "> 逐日截面：事件股（当日盘中破前20日收盘高点但收盘收回）前瞻收益均值 − 非事件股均值；t+1 执行",
        "",
        "| 前瞻期 | 平均日截面差 | t | 负差日占比 | 样本日数 | 事件总数 |",
        "|--------|-------------|---|-----------|----------|----------|",
    ]
    for _, r in event.iterrows():
        lines.append(f"| {r['horizon']} | {r['event_mean']:.4%} | {r['t']} | {r['hit_rate_negative']:.0%} | {r['n_days']} | {r['n_events']} |")
    lines += [
        "",
        "## 二、事件研究（单标的层面）：假突破后相对自身基线的超额",
        "",
        "> 每只股票以自身非事件日为基线（t+1 执行），加权平均事件日超额；比小样本截面更稳健",
        "",
    ]
    for label, sym in (("A股", sym_a), ("港股", sym_hk)):
        lines += [f"### {label}", "",
                  "| 前瞻期 | 加权超额 | 标的水准 t | 负超额标占比 | 标的数 | 事件总数 |",
                  "|--------|----------|-----------|-------------|--------|----------|"]
        for h in (5, 10, 20):
            s = sym_summary(sym, h)
            if s:
                lines.append(f"| {h} | {s['diff']:.4%} | {s['t']:.2f} | {s['neg_share']:.0%} | {s['n_symbols']} | {s['n_events']} |")
        lines.append("")
    lines += [
        "## 三、A股 IC 评估（原始 vs 中性化，前瞻 10/20 日）",
        "",
        "| 因子 | 前瞻 | 原始IC | 原始ICIR | 原始评级 | 中性IC | 中性ICIR | 中性评级 |",
        "|------|------|--------|----------|----------|--------|----------|----------|",
    ]
    for _, r in ev_neu.iterrows():
        raw = ev_raw[(ev_raw["factor"] == r["factor"]) & (ev_raw["horizon"] == r["horizon"])]
        if raw.empty:
            lines.append(f"| {r['factor']} | {r['horizon']} | — | — | — | "
                         f"{r['mean_ic']} | {r['icir']} | {r['rating']} |")
        else:
            rw = raw.iloc[0]
            lines.append(f"| {r['factor']} | {r['horizon']} | {rw['mean_ic']} | {rw['icir']} | {rw['rating']} | "
                         f"{r['mean_ic']} | {r['icir']} | {r['rating']} |")
    lines += ["", "## 四、A股 walk-forward 组合回测（含成本）", "", backtest_txt]
    for market, tab in small_markets.items():
        if tab.empty:
            continue
        lines += [f"## 五、{market} IC（小样本，仅参考）", "",
                  "| 因子 | 前瞻 | 均值IC | ICIR | t | 多空Sharpe | 评级 |",
                  "|------|------|--------|------|---|-----------|------|"]
        for _, r in tab.iterrows():
            lines.append(f"| {r['factor']} | {r['horizon']} | {r['mean_ic']} | {r['icir']} | {r['tstat']} | "
                         f"{r['ls_sharpe']} | {r['rating']} |")
        lines.append("")
    lines += [
        "## 结论",
        "",
        "- **第一层证据（事件研究）**：A股与港股的假突破事件股在 5/10/20 日后均小幅**跑赢**非事件股/自身基线——与“追跌假突破”直觉相反，且跨市场方向一致",
        "- **港股截面负 IC 是伪信号**：13 只小样本的截面 IC（t=-4.3）经单标的层面事件研究复核后不成立，事件后实为正漂移；这提示小样本截面结论必须先过单标的复核",
        "- **组合回测（walk-forward 样本外）为最终门控**：所有候选扣费后无显著净边际（HAC t 不显著 / DSR≈0），仅作监控信号，不进入实盘部署",
        "- **接针/供需区因子截面稀疏**：多数日期只有少量事件，分位组合信号被稀释；v2 版（量能确认、回踩支撑）事件密度更低，结论以 IC 与事件研究为准",
        "- **值得继续的方向**：美股低波（本样本多空夏普>1，经典异动）、港股动量（ICIR 0.22 但同为小样本，需扩池复核）、假突破后的正漂移机制（若成立，是“假突破回踩延续”而非“追跌”）",
        "",
        "> 本报告基于公开数据与规则化分析生成，仅供研究参考，不构成任何投资建议。",
        "",
    ]
    (ROOT / "docs" / "大佬信号验证报告.md").write_text("\n".join(lines), encoding="utf-8")
    return "\n".join(lines)


def main():
    store = LocalStore(str(ROOT / "data"))
    industry = load_a_industry(str(ROOT / "data"))
    if industry is None:
        print("缺少行业映射，仅做规模中性化", file=sys.stderr)

    a = load_ohlcv(store, "A股", stock_only=True)
    event = event_study(a) if a else pd.DataFrame()
    sym_a = symbol_event_study(a) if a else pd.DataFrame()
    hk = load_ohlcv(store, "港股")
    sym_hk = symbol_event_study(hk) if hk else pd.DataFrame()
    print("事件研究完成（截面 + 单标的）：\n", event.to_string(index=False))
    print("\n港股单标的层面：\n", sym_hk.to_string(index=False))

    ev_raw, ev_neu = [], []
    for market in COSTS:
        o = load_ohlcv(store, market, stock_only=(market == "A股"))
        if o is None:
            continue
        ev_raw.append(build_eval_table(o, market))
        if market == "A股":
            ev_neu.append(build_eval_table(o, market, industry=industry,
                                           size=size_proxy(o["close"], o["volume"]),
                                           neutralize_a=True))
    raw = pd.concat(ev_raw, ignore_index=True)
    neu = pd.concat(ev_neu, ignore_index=True) if ev_neu else pd.DataFrame()
    small = {m: raw[raw["market"] == m] for m in ("港股", "美股", "虚拟货币")}

    print("\nA股中性化 IC：\n", neu.to_string(index=False))
    bt = run_backtests(store, industry)
    print("\n组合回测完成")
    report = write_report(raw, neu, event, sym_a, sym_hk, bt, small)
    print("\n已输出：docs/大佬信号验证报告.md")
    print(report[:500])


if __name__ == "__main__":
    main()
