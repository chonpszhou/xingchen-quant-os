"""因子评估（alpha-evaluate 方法论）：标准化、t+1执行、IC/ICIR、分位多空、单调性、评级"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats


def compute_forward_returns(close: pd.DataFrame, periods: int, shift: int = 1):
    """t 收盘知道因子 → t+1 执行，持有 periods 日：close[t+1+periods]/close[t+1]-1"""
    entry = close.shift(-shift)
    exit_ = close.shift(-shift - periods)
    return exit_ / entry - 1


def standardize(df: pd.DataFrame, mad_n: int = 5):
    """MAD 去极值 + 截面 zscore"""
    med = df.median(axis=1)
    mad = df.sub(med, axis=0).abs().median(axis=1)
    up, lo = med + mad_n * 1.4826 * mad, med - mad_n * 1.4826 * mad
    w = df.clip(lo, up, axis=0)
    # 稀疏因子（如接针）MAD=0 时裁剪会整行退化：若原始行本身有离散度，则回退原始值参与排名
    degenerate = (w.std(axis=1) == 0) & (df.std(axis=1) > 0)
    w = w.mask(degenerate, df)
    return w.sub(w.mean(axis=1), axis=0).div(w.std(axis=1), axis=0)


def daily_ic(factor: pd.DataFrame, fwd: pd.DataFrame, min_symbols=8):
    out = {}
    for d in factor.index.intersection(fwd.index):
        f, r = factor.loc[d].dropna(), fwd.loc[d].dropna()
        idx = f.index.intersection(r.index)
        if len(idx) < min_symbols:
            continue
        out[d] = stats.spearmanr(f[idx], r[idx]).statistic
    return pd.Series(out).sort_index()


def group_returns(factor: pd.DataFrame, fwd: pd.DataFrame, groups=5, min_symbols=8):
    res = {}
    for d in factor.index.intersection(fwd.index):
        f, r = factor.loc[d].dropna(), fwd.loc[d].dropna()
        idx = f.index.intersection(r.index)
        if len(idx) < groups:
            continue
        q = pd.qcut(f[idx].rank(method="first"), groups, labels=False)
        res[d] = {g: r[idx][q == g].mean() for g in range(groups)}
    return pd.DataFrame(res).T


def rating(icir, ls_sharpe, mono_corr, mono_p):
    monotonic = abs(mono_corr) > 0.8 and mono_p < 0.1
    if abs(icir) >= 0.5 and monotonic and abs(ls_sharpe) > 1:
        return "Strong"
    if abs(icir) >= 0.3 or abs(ls_sharpe) > 0.5:
        return "Moderate"
    return "Weak"


def evaluate(factor_wide, close_wide, horizons=(5, 10, 20), min_symbols=8, groups=5):
    """返回 DataFrame：每因子×前瞻期的 IC/ICIR/t/分位多空夏普/单调性/评级"""
    rows = []
    fz = standardize(factor_wide)
    for h in horizons:
        fwd = compute_forward_returns(close_wide, h)
        ic = daily_ic(fz, fwd, min_symbols)
        if len(ic) < 40:
            continue
        gr = group_returns(fz, fwd, groups, min_symbols)
        ls = gr[groups - 1] - gr[0]
        ls_sharpe = ls.mean() / ls.std() * np.sqrt(252 / h) if ls.std() > 0 else np.nan
        ls_cum = (1 + ls).cumprod()
        ls_maxdd = ((ls_cum - ls_cum.cummax()) / ls_cum.cummax()).min()
        gmeans = [gr[g].mean() for g in range(groups)]
        mono_corr, mono_p = stats.spearmanr(range(groups), gmeans)
        rows.append({
            "horizon": h, "mean_ic": round(ic.mean(), 4),
            "icir": round(ic.mean() / ic.std(), 3) if ic.std() > 0 else np.nan,
            "tstat": round(ic.mean() / ic.std() * np.sqrt(len(ic)), 2) if ic.std() > 0 else np.nan,
            "pos_ratio": round(float((ic > 0).mean()), 3),
            "ls_sharpe": round(ls_sharpe, 2), "ls_maxdd": round(ls_maxdd, 4),
            "mono_corr": round(mono_corr, 3), "mono_p": round(mono_p, 3),
            "rating": rating(ic.mean() / ic.std() if ic.std() > 0 else 0, ls_sharpe, mono_corr, mono_p),
            "n_days": len(ic),
        })
    return pd.DataFrame(rows)
