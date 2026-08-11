"""因子流水线：面板构建 + 日度 IC + 分位组合"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from datahub.store import LocalStore  # noqa: E402
from factors.definitions import FACTOR_DEFS, compute_factors  # noqa: E402


def build_panel(markets=None, symbols=None, horizons=(5, 10, 20), data_dir="data"):
    """把多市场标的的因子 + 前瞻收益拼成长表（date/market/symbol/...）"""
    store = LocalStore(data_dir)
    status = store.all_status()
    frames = []
    for _, st in status.iterrows():
        m, s = st["market"], st["symbol"]
        if markets and m not in markets:
            continue
        if symbols and s not in symbols:
            continue
        df = store.load_bars(m, s)
        if df is None or len(df) < 80:
            continue
        f = compute_factors(df, horizons)
        f["market"] = m
        f["symbol"] = s
        frames.append(f)
    return pd.concat(frames, ignore_index=True)


def _pivot(panel, col):
    return panel.pivot_table(index="date", columns="symbol", values=col)


def daily_ic(panel, factor, horizon, min_symbols=5):
    """逐日截面 Spearman IC：因子值 vs 未来 h 日收益"""
    f = _pivot(panel, factor)
    r = _pivot(panel, f"fwd_{horizon}")
    common = f.index.intersection(r.index)
    out = {}
    for d in common:
        x, y = f.loc[d].dropna(), r.loc[d].dropna()
        idx = x.index.intersection(y.index)
        if len(idx) < min_symbols:
            continue
        out[d] = stats.spearmanr(x[idx], y[idx]).statistic
    return pd.Series(out).sort_index()


def ic_summary(panel, market, horizons=(5, 10, 20), min_symbols=5, min_days=60):
    """每个因子 × 每个前瞻期的 IC 汇总（含分半稳健性）"""
    sub = panel[panel["market"] == market]
    rows = []
    for factor in FACTOR_DEFS:
        for h in horizons:
            ic = daily_ic(sub, factor, h, min_symbols)
            if len(ic) < min_days:
                continue
            n = len(ic)
            mean, std = ic.mean(), ic.std()
            half = n // 2
            rows.append({
                "market": market, "factor": factor, "horizon": h, "n_days": n,
                "mean_ic": round(mean, 4),
                "icir": round(mean / std, 3) if std > 0 else np.nan,
                "tstat": round(mean / std * np.sqrt(n), 2) if std > 0 else np.nan,
                "pos_ratio": round(float((ic > 0).mean()), 3),
                "ic_first_half": round(float(ic[:half].mean()), 4),
                "ic_second_half": round(float(ic[half:].mean()), 4),
                "ic_std": round(float(std), 4),
            })
    return pd.DataFrame(rows)


def quintiles(panel, market, factor, horizon=10, min_symbols=5, groups=5):
    """按因子截面排序分 5 组，统计各组未来 h 日平均收益（多空价差）"""
    sub = panel[panel["market"] == market]
    f, r = _pivot(sub, factor), _pivot(sub, f"fwd_{horizon}")
    common = f.index.intersection(r.index)
    bins = {g: [] for g in range(groups)}
    for d in common:
        x, y = f.loc[d].dropna(), r.loc[d].dropna()
        idx = x.index.intersection(y.index)
        if len(idx) < min_symbols:
            continue
        ranks = (x[idx].rank(pct=True) * groups).clip(0, groups - 1).astype(int)
        for g in range(groups):
            sel = y[idx][ranks == g]
            if len(sel):
                bins[g].append(sel.mean())
    res = []
    for g in range(groups):
        arr = pd.Series(bins[g]).dropna()
        res.append({"group": g + 1, "n_days": len(arr),
                    "mean_fwd_ret": round(float(arr.mean()), 4) if len(arr) else np.nan,
                    "std": round(float(arr.std()), 4) if len(arr) else np.nan})
    spread = np.nan
    if len(res) >= 2 and res[0]["n_days"] and res[-1]["n_days"]:
        spread = round(res[-1]["mean_fwd_ret"] - res[0]["mean_fwd_ret"], 4)
    return pd.DataFrame(res), spread
