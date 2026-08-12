"""参数寻优器（自 paddy-quant-workbench 设计适配本引擎）

反过拟合原则：
  1) 用 walk-forward 多期样本外指标排序（不用样本内）
  2) 最后 30% 作严格保留集（寻优全程不碰）
  3) 样本内/样本外夏普比 > 1.8 标记过拟合并扣分
  4) 双门槛：walk-forward 均值达标 且 保留集达标，才 PASS
"""

from __future__ import annotations

import itertools

import pandas as pd

from engine.backtest import BacktestEngine  # noqa: E402
from engine.executor import PaperExecutor  # noqa: E402
from engine.strategy import get_strategy  # noqa: E402
from factors.backtest import metrics  # noqa: E402

WF_TRAIN, WF_TEST = 126, 21
HOLDOUT_FRAC = 0.30
OVERFIT_RATIO = 1.8
PASS_SCORE = 0.30          # walk-forward 均值夏普底线
HOLDOUT_MIN_SHARPE = 0.3
MIN_TRADES = 5


def _run_one(strategy_name, params, ds, close, risk, exits, cost=0.001):
    strat = get_strategy(strategy_name, data_service=ds, **params)
    strat.on_init()
    ex = PaperExecutor(cost=cost)
    eng = BacktestEngine(strat, ex, risk, exit_manager=exits)
    nav = eng.run(close)
    return nav, ex, eng


def optimize(strategy_name, params_space: dict, close: pd.DataFrame, ds,
             risk=None, exits=None, cost=0.001, verbose=True) -> pd.DataFrame:
    keys = list(params_space)
    combos = [dict(zip(keys, v)) for v in itertools.product(*params_space.values())]
    n = len(close)
    holdout_start = int(n * (1 - HOLDOUT_FRAC))
    train_close = close.iloc[:holdout_start]
    holdout_close = close.iloc[holdout_start:]
    rows = []
    for params in combos:
        oos_sharpes, oos_trades, is_sharpes = [], [], []
        start = WF_TRAIN
        while start + WF_TEST <= len(train_close):
            tr = train_close.iloc[start - WF_TRAIN: start]
            te = train_close.iloc[start: start + WF_TEST]
            nav_is, ex_is, _ = _run_one(strategy_name, params, ds, tr, risk, exits, cost)
            nav_oos, ex_oos, _ = _run_one(strategy_name, params, ds, te, risk, exits, cost)
            is_sharpes.append(metrics(nav_is, 0.0)["sharpe"])
            if ex_oos.trade_count >= MIN_TRADES:
                oos_sharpes.append(metrics(nav_oos, 0.0)["sharpe"])
                oos_trades.append(ex_oos.trade_count)
            start += WF_TEST
        # 保留集（寻优全程没碰过的最后 30%）
        nav_h, ex_h, _ = _run_one(strategy_name, params, ds, holdout_close, risk, exits, cost)
        hm = metrics(nav_h, 0.0)
        wf_score = float(pd.Series(oos_sharpes).mean()) if oos_sharpes else float("nan")
        is_mean = float(pd.Series(is_sharpes).mean()) if is_sharpes else float("nan")
        overfit = (abs(is_mean) > 1e-9 and abs(wf_score / is_mean) < 1 / OVERFIT_RATIO) \
            if pd.notna(is_mean) and pd.notna(wf_score) else False
        valid_windows = len(oos_sharpes)
        passed = (pd.notna(wf_score) and wf_score >= PASS_SCORE
                  and hm["sharpe"] >= HOLDOUT_MIN_SHARPE
                  and ex_h.trade_count >= MIN_TRADES and not overfit)
        rows.append({
            **params,
            "wf_oos_sharpe": round(wf_score, 3) if pd.notna(wf_score) else None,
            "valid_windows": valid_windows,
            "holdout_sharpe": round(hm["sharpe"], 3),
            "holdout_ann": round(hm["annual_return"], 4),
            "holdout_trades": ex_h.trade_count,
            "overfit": overfit,
            "PASS": passed,
        })
    df = pd.DataFrame(rows).sort_values(
        ["PASS", "wf_oos_sharpe"], ascending=[False, False])
    if verbose:
        print(f"寻优完成：{len(combos)} 组参数（walk-forward {WF_TRAIN}/{WF_TEST} + 保留集 "
              f"{len(holdout_close)} 日）")
        print(df.to_string(index=False))
    return df
