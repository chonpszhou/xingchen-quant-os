#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 模拟盘引擎一致性校验

把两个模拟盘引擎的“状态机”逻辑在历史数据上重放，与研究报告回测结果对照，
验证纸面账户与回测引擎无系统性偏差（执行日、成本、持仓计算一致）。

用法:
    python3 scripts/validate_paper_engines.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from datahub.store import LocalStore  # noqa: E402
from factors.backtest import metrics  # noqa: E402


def replay_momentum(store):
    """双动量引擎重放：21 日调仓，t+1 执行，成本 0.1%，与 paper_trade_momentum 同规则"""
    closes = {}
    for sym in ("SPY", "GLD", "DBC", "TLT"):
        df = store.load_bars("美股", sym)
        if df is not None:
            closes[sym] = df.set_index("date")["close"]
    close = pd.DataFrame(closes).dropna()
    ret = close.pct_change()
    lookbacks = (63, 126, 252)
    mom = pd.DataFrame(index=close.index)
    for a in ("SPY", "GLD", "DBC"):
        mom[a] = np.mean([(close[a] / close[a].shift(L) - 1).values for L in lookbacks], axis=0)
    weights = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
    for i, d in enumerate(close.index):
        if i % 21 != 0:
            continue
        m = mom.loc[d].dropna()
        if m.empty:
            continue
        weights.loc[d] = 0.0
        weights.loc[d, m.idxmax() if m.max() > 0 else "TLT"] = 1.0
    exec_w = weights.ffill().shift(1).fillna(0.0)
    gross = (exec_w * ret.fillna(0.0)).sum(axis=1)
    net = gross - exec_w.diff().abs().fillna(exec_w.abs()).sum(axis=1) * 0.001
    nav = (1 + net).cumprod()
    return nav, metrics(nav, 0.0, n_trials=6)


def replay_cb(store):
    """双低引擎重放：与 paper_trade_cb 同规则（信用过滤、TOP20、20日调仓、0.1%成本）"""
    df = pd.read_parquet(ROOT / "data" / "cb_panel.parquet")
    # 与回测一致的数据清洗：标准代码段 + 单日|收益|>50% 剔除
    df = df[df["bond"].str.startswith(("110", "111", "113", "118", "123", "127", "128"))]
    meta = pd.read_parquet(ROOT / "data" / "cb_meta.parquet")
    meta["code"] = meta["code"].astype(str).str.zfill(6)
    meta["rating"] = meta["rating"].astype(str)
    bad = meta["stock_name"].astype(str).str.contains("ST") | meta["rating"].str.startswith("C") \
        | meta["rating"].isna()
    ok_bonds = meta.loc[~bad].set_index("code").index
    df["date"] = pd.to_datetime(df["date"])
    for c in ("close", "premium_pct", "conv_value"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df[df["bond"].isin(ok_bonds)]
    df = df.sort_values(["bond", "date"])
    df["listed_days"] = df.groupby("bond")["date"].rank(method="first").astype(int) - 1
    df = df[df["close"].notna()]
    bad_ret = df.sort_values(["bond", "date"]).groupby("bond")["close"].pct_change().abs() > 0.5
    bad_bonds = set(df.loc[bad_ret, "bond"]) if bad_ret.any() else set()
    df = df[~df["bond"].isin(bad_bonds)]
    uniq_dates = pd.DatetimeIndex(sorted(df["date"].unique()))
    uniq_bonds = sorted(df["bond"].unique())
    di_map = {d: i for i, d in enumerate(uniq_dates)}
    ci_map = {b: j for j, b in enumerate(uniq_bonds)}
    di = np.array([di_map[d] for d in df["date"]])
    ci = np.array([ci_map[b] for b in df["bond"]])
    close_a = np.full((len(uniq_dates), len(uniq_bonds)), np.nan)
    prem_a = np.full_like(close_a, np.nan)
    list_a = np.full_like(close_a, np.nan)
    close_a[di, ci] = df["close"].values
    prem_a[di, ci] = df["premium_pct"].values
    list_a[di, ci] = df["listed_days"].values
    close = pd.DataFrame(close_a, index=uniq_dates, columns=uniq_bonds)
    premium = pd.DataFrame(prem_a, index=uniq_dates, columns=uniq_bonds)
    listed = pd.DataFrame(list_a, index=uniq_dates, columns=uniq_bonds)
    score = close + premium
    ret = close.pct_change()
    weights = pd.DataFrame(np.nan, index=uniq_dates, columns=uniq_bonds)
    active = False
    for i, d in enumerate(uniq_dates):
        if i % 20 != 0:
            continue
        elig = (close.loc[d] <= 130) & (premium.loc[d] <= 50) & (listed.loc[d] >= 20)
        s = score.loc[d].where(elig).dropna()
        if len(s) < 30:
            continue
        if not active:
            active = True
        top = s.nsmallest(20)
        weights.loc[d] = 0.0
        weights.loc[d, top.index] = 1.0 / 20
    exec_w = weights.ffill().shift(1).fillna(0.0)
    gross = (exec_w * ret.fillna(0.0)).sum(axis=1)
    net = gross - exec_w.diff().abs().fillna(exec_w.abs()).sum(axis=1) * 0.001
    nav = (1 + net).cumprod()
    if active:
        nav = nav[nav.index >= weights.dropna(how="all").index.min()]
    return nav, metrics(nav, 0.0, n_trials=6)


def main():
    store = LocalStore(str(ROOT / "data"))
    print("=== 双动量引擎一致性校验 ===")
    nav, m = replay_momentum(store)
    print(f"重放结果：年化 {m['annual_return']:.2%} | 夏普 {m['sharpe']} | HAC t {m['hac_t']} | 回撤 {m['max_drawdown']:.2%}")
    print(f"回测对照：年化 22.65% | 夏普 1.155 | HAC t 2.54 | 回撤 -19.98%")
    diff = abs(m["annual_return"] - 0.2265)
    print(f"年化偏差：{diff:.2%} → {'✓ 一致' if diff < 0.02 else '⚠ 偏差过大'}\n")

    print("=== 双低引擎一致性校验 ===")
    nav2, m2 = replay_cb(store)
    print(f"重放结果：年化 {m2['annual_return']:.2%} | 夏普 {m2['sharpe']} | HAC t {m2['hac_t']} | 回撤 {m2['max_drawdown']:.2%}")
    print(f"回测对照：年化 13.62% | 夏普 0.884 | HAC t 2.82 | 回撤 -20.36%")
    diff2 = abs(m2["annual_return"] - 0.1362)
    print(f"年化偏差：{diff2:.2%} → {'✓ 一致' if diff2 < 0.02 else '⚠ 偏差过大'}")


if __name__ == "__main__":
    main()
