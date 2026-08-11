"""因子组合回测 + walk-forward 验证（t+1 执行、成本、IS/OOS、HAC t、DSR）"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats


def newey_west_t(returns: pd.Series, lags=None):
    n = len(returns)
    if n < 3:
        return np.nan, np.nan
    e = (returns - returns.mean()).values
    if lags is None:
        lags = max(1, int(4 * (n / 100) ** (2 / 9)))
    var = e @ e / n
    for l in range(1, min(lags, n - 1) + 1):
        g = e[l:] @ e[:-l] / n
        var += 2 * (1 - l / (lags + 1)) * g
    se = np.sqrt(max(var, 1e-12) / n)
    return returns.mean() / se, se


def portfolio_backtest(close: pd.DataFrame, signals: dict, cost_rate: float,
                       risk_free=0.02) -> pd.Series:
    """signals: {date: {symbol: weight}}，t 日收盘给信号，t+1 执行；返回净值序列"""
    dates = close.index
    rets = close.pct_change().fillna(0.0)
    weights = pd.DataFrame(0.0, index=dates, columns=close.columns)
    for d, w in signals.items():
        if d in weights.index and w:
            weights.loc[d] = pd.Series(w)
    exec_w = weights.shift(1).fillna(0.0)
    port_ret = (exec_w * rets).sum(axis=1)
    turnover = (exec_w.diff().abs().fillna(exec_w.abs())).sum(axis=1)
    nav = (1 + port_ret - turnover * cost_rate / 2).cumprod()
    return nav


def metrics(nav: pd.Series, cost_rate, n_trials=1, periods_per_year=252):
    r = nav.pct_change().dropna()
    n_years = len(r) / periods_per_year
    total = nav.iloc[-1] / nav.iloc[0] - 1
    ann = (1 + total) ** (1 / n_years) - 1 if n_years > 0 else np.nan
    vol = r.std() * np.sqrt(periods_per_year)
    risk_free = 0.02
    sharpe = (ann - risk_free) / vol if vol > 0 else np.nan
    t, _ = newey_west_t(r)
    dd = ((nav - nav.cummax()) / nav.cummax()).min()
    monthly = nav.resample("ME").last().pct_change().dropna()
    pf = (monthly[monthly > 0].sum() / abs(monthly[monthly < 0].sum())
          if (monthly < 0).any() else np.nan)
    turnover = r.shape[0] and 0.0  # 简化：turnover 在回测内计算
    # DSR（去通胀夏普，Lopez de Prado 近似）
    skew = r.skew() if len(r) > 3 else 0.0
    kurt = r.kurt() if len(r) > 3 else 3.0
    sr_std = np.sqrt((1 - skew * sharpe + (kurt - 1) / 4 * sharpe ** 2) / (len(r) - 1))
    euler = 0.5772156649
    emax = stats.norm.ppf(1 - 1 / n_trials) * (1 - euler) + euler * stats.norm.ppf(1 - 1 / (n_trials * np.e))
    dsr = float(stats.norm.cdf((sharpe - emax) / sr_std)) if sr_std > 0 else np.nan
    return {
        "total_return": round(total, 4), "annual_return": round(ann, 4),
        "sharpe": round(sharpe, 3), "hac_t": round(t, 2),
        "max_drawdown": round(dd, 4), "calmar": round(ann / abs(dd), 2) if dd < 0 else np.nan,
        "monthly_wr": round(float((monthly > 0).mean()), 3), "profit_factor": round(pf, 3),
        "dsr": round(dsr, 3), "n_days": len(r),
    }


def factor_signals(close: pd.DataFrame, factor: pd.DataFrame, direction=1,
                   top_pct=0.2, rebalance_days=20, min_obs=8, limit_up_filter=False,
                   liquidity=None, liquidity_floor_pct=0.1):
    """每 rebalance_days 生成 top/bottom 组合等权信号（t 收盘，t+1 执行）"""
    rets = close.pct_change()
    signals = {}
    dates = close.index
    for i, d in enumerate(dates):
        if i % rebalance_days != 0:
            continue
        f = factor.loc[d].dropna()
        if len(f) < min_obs:
            continue
        if liquidity is not None and d in liquidity.index:
            floor = liquidity.loc[d].quantile(liquidity_floor_pct)
            f = f[liquidity.loc[d].reindex(f.index).fillna(0) > floor]
            if len(f) < min_obs:
                continue
        if limit_up_filter and d in rets.index:
            limit_up = rets.loc[d] > 0.095
            f = f[~limit_up]
            if len(f) < min_obs:
                continue
        n = max(1, int(len(f) * top_pct))
        top = f.nlargest(n) if direction == 1 else f.nsmallest(n)
        signals[d] = (top / top.sum()).to_dict()
    return signals


def walk_forward(close, factor, direction, top_pct, cost_rate, rebalance_days=20,
                 train_size=252, test_size=63, embargo=5, n_trials=1,
                 liquidity=None, liquidity_floor_pct=0.1, limit_up_filter=False):
    """滚动 walk-forward：每折在 train 内回测(IS)，在 test 内回测(OOS)，汇总 OOS"""
    dates = close.index
    folds, oos_parts, is_stats = [], [], []
    start = train_size
    while start + test_size <= len(dates):
        tr = dates[start - train_size: start]
        te = dates[start + embargo: start + test_size]
        if len(te) < 10:
            break
        liq_tr = liquidity.loc[tr] if liquidity is not None else None
        liq_te = liquidity.loc[te] if liquidity is not None else None
        sig_tr = factor_signals(close.loc[tr], factor.loc[tr], direction, top_pct, rebalance_days,
                                liquidity=liq_tr, liquidity_floor_pct=liquidity_floor_pct,
                                limit_up_filter=limit_up_filter)
        sig_te = factor_signals(close.loc[te], factor.loc[te], direction, top_pct, rebalance_days,
                                liquidity=liq_te, liquidity_floor_pct=liquidity_floor_pct,
                                limit_up_filter=limit_up_filter)
        nav_is = portfolio_backtest(close.loc[tr], sig_tr, cost_rate)
        nav_oos = portfolio_backtest(close.loc[te], sig_te, cost_rate)
        is_stats.append(metrics(nav_is, cost_rate))
        oos_parts.append(nav_oos)
        folds.append({"train": str(tr[0].date()), "train_end": str(tr[-1].date()),
                      "oos_start": str(te[0].date()), "oos_end": str(te[-1].date()),
                      "is_sharpe": is_stats[-1]["sharpe"], "oos_sharpe": metrics(nav_oos, cost_rate)["sharpe"]})
        start += test_size
    oos_nav = pd.concat(oos_parts) if oos_parts else None
    oos_nav = oos_nav[~oos_nav.index.duplicated(keep="last")].sort_index()
    full_sig = factor_signals(close, factor, direction, top_pct, rebalance_days,
                              liquidity=liquidity, liquidity_floor_pct=liquidity_floor_pct,
                              limit_up_filter=limit_up_filter)
    full_nav = portfolio_backtest(close, full_sig, cost_rate)
    return {
        "folds": pd.DataFrame(folds),
        "oos_nav": oos_nav, "full_nav": full_nav,
        "full_metrics": metrics(full_nav, cost_rate, n_trials),
        "oos_metrics": metrics(oos_nav, cost_rate, n_trials) if oos_nav is not None and len(oos_nav) > 2 else None,
        "is_avg_sharpe": float(pd.Series([f["is_sharpe"] for f in folds]).mean()) if folds else np.nan,
    }
