"""参数寻优器（自 paddy-quant-workbench 设计适配本引擎，已对齐五道闸门）

反过拟合原则：
  1) 用 walk-forward 多期样本外指标排序（不用样本内）
  2) 最后 30% 作严格保留集（寻优全程不碰）
  3) 样本内/样本外夏普比 > 1.8 标记过拟合并扣分
  4) 双门槛：walk-forward 均值达标 且 保留集达标，才进入候选
  5) 第四道闸门（质量否决）：若提供 fundamentals，命中基本面红线则否决
  6) 第五道闸门（DSR 硬卡）：保留集指标用 n_trials=参数组合数 做多重检验校正，
     DSR<0.95 直接否决（复用本引擎 factors.backtest.metrics 的 DSR 数学）
"""

from __future__ import annotations

import itertools

import pandas as pd

from engine.backtest import BacktestEngine  # noqa: E402
from engine.executor import PaperExecutor  # noqa: E402
from engine.strategy import get_strategy  # noqa: E402
from engine.quality_filter import Fundamentals, QualityFilter  # noqa: E402  # 第四道闸门(自 paddy 移植)
from factors.backtest import metrics  # noqa: E402

WF_TRAIN, WF_TEST = 126, 21
HOLDOUT_FRAC = 0.30
OVERFIT_RATIO = 1.8
PASS_SCORE = 0.30          # walk-forward 均值夏普底线
HOLDOUT_MIN_SHARPE = 0.3
MIN_TRADES = 5
DSR_MIN = 0.95             # 第五道闸门：紧缩夏普下限(多重检验校正后仍需 ≥95% 置信；自 paddy 移植)


def _run_one(strategy_name, params, ds, close, risk, exits, cost=0.001, strategy_params=None):
    # strategy_params：非网格的固定策略参数（如单资产扫描的 symbol/market），并入实例化
    strat = get_strategy(strategy_name, data_service=ds, **{**params, **(strategy_params or {})})
    strat.on_init()
    ex = PaperExecutor(cost=cost)
    eng = BacktestEngine(strat, ex, risk, exit_manager=exits)
    nav = eng.run(close)
    return nav, ex, eng


def optimize(strategy_name, params_space: dict, close: pd.DataFrame, ds,
             risk=None, exits=None, cost=0.001, verbose=True,
             fundamentals=None, strategy_params=None) -> pd.DataFrame:
    """参数寻优 + 第四/五道闸门（自 paddy-quant-workbench 移植的严格验证纪律）。

    fundamentals: 该标的的基本面快照(dict 或 Fundamentals)。若提供，叠加第四道
        质量否决(quality_filter)——命中红线则 PASS=False。
    DSR：保留集指标用 n_trials=参数组合数 重算（多重检验校正），DSR<DSR_MIN 即
        第五道闸门否决。复用本引擎 factors.backtest.metrics 已有的 DSR 数学。
    """
    keys = list(params_space)
    combos = [dict(zip(keys, v)) for v in itertools.product(*params_space.values())]
    n_trials = max(1, len(combos))
    n = len(close)
    holdout_start = int(n * (1 - HOLDOUT_FRAC))
    train_close = close.iloc[:holdout_start]
    holdout_close = close.iloc[holdout_start:]
    # 第四道闸门：标的基本面一次性评估（与参数无关）
    qrep = QualityFilter().evaluate(fundamentals) if fundamentals is not None else None
    rows = []
    for params in combos:
        oos_sharpes, oos_trades, is_sharpes = [], [], []
        start = WF_TRAIN
        while start + WF_TEST <= len(train_close):
            tr = train_close.iloc[start - WF_TRAIN: start]
            te = train_close.iloc[start: start + WF_TEST]
            nav_is, ex_is, _ = _run_one(strategy_name, params, ds, tr, risk, exits, cost, strategy_params)
            nav_oos, ex_oos, _ = _run_one(strategy_name, params, ds, te, risk, exits, cost, strategy_params)
            is_sharpes.append(metrics(nav_is, 0.0)["sharpe"])
            # 修正存活者偏差：不再因 trade_count<MIN 丢弃空仓折（否则只统计有交易的折，
            # 虚高 WF-OOS）。平仓折(无信号)夏普≈0，纳入均值反而更保守、更真实。
            oos_sr = metrics(nav_oos, 0.0)["sharpe"]
            if pd.notna(oos_sr):
                oos_sharpes.append(oos_sr)
                oos_trades.append(ex_oos.trade_count)
            start += WF_TEST
        # 保留集（寻优全程没碰过的最后 30%）
        nav_h, ex_h, _ = _run_one(strategy_name, params, ds, holdout_close, risk, exits, cost, strategy_params)
        hm = metrics(nav_h, 0.0)
        hm_strict = metrics(nav_h, 0.0, n_trials=n_trials)  # 多重检验校正后的 DSR
        dsr = hm_strict.get("dsr")
        # 全样本绩效（汇报口径，避免只看最后 30% 保留集虚高）
        nav_full, ex_full, _ = _run_one(strategy_name, params, ds, close, risk, exits, cost, strategy_params)
        fm = metrics(nav_full, 0.0)
        wf_score = float(pd.Series(oos_sharpes).mean()) if oos_sharpes else float("nan")
        is_mean = float(pd.Series(is_sharpes).mean()) if is_sharpes else float("nan")
        overfit = (abs(is_mean) > 1e-9 and abs(wf_score / is_mean) < 1 / OVERFIT_RATIO) \
            if pd.notna(is_mean) and pd.notna(wf_score) else False
        valid_windows = len(oos_sharpes)
        # —— 第五道闸门：DSR 硬卡（多重检验校正后仍须 ≥DSR_MIN）——
        dsr_ok = (pd.notna(dsr) and dsr >= DSR_MIN)
        passed = (pd.notna(wf_score) and wf_score >= PASS_SCORE
                  and hm["sharpe"] >= HOLDOUT_MIN_SHARPE
                  and ex_h.trade_count >= MIN_TRADES and not overfit and dsr_ok)
        # —— 第四道闸门：质量否决（命中则关 PASS）——
        quality_veto = False
        if qrep is not None and qrep.veto:
            passed = False
            quality_veto = True
        rows.append({
            **params,
            "wf_oos_sharpe": round(wf_score, 3) if pd.notna(wf_score) else None,
            "valid_windows": valid_windows,
            "holdout_sharpe": round(hm["sharpe"], 3),
            "holdout_ann": round(hm["annual_return"], 4),
            "holdout_maxdd": round(hm["max_drawdown"], 4),
            "holdout_trades": ex_h.trade_count,
            # 全样本绩效（汇报主口径，避免只看最后 30% 保留集虚高）
            "full_sharpe": round(fm["sharpe"], 3) if pd.notna(fm.get("sharpe")) else None,
            "full_ann": round(fm["annual_return"], 4) if pd.notna(fm.get("annual_return")) else None,
            "full_maxdd": round(fm["max_drawdown"], 4) if pd.notna(fm.get("max_drawdown")) else None,
            "overfit": overfit,
            "dsr": round(dsr, 3) if pd.notna(dsr) else None,   # 第五道闸门指标(透明可查)
            "dsr_gate": bool(dsr_ok),
            "quality_veto": bool(quality_veto),                # 第四道闸门
            "PASS": passed,
        })
    df = pd.DataFrame(rows).sort_values(
        ["PASS", "dsr_gate", "wf_oos_sharpe"], ascending=[False, False, False])
    if verbose:
        print(f"寻优完成：{len(combos)} 组参数（walk-forward {WF_TRAIN}/{WF_TEST} + 保留集 "
              f"{len(holdout_close)} 日；第五道 DSR≥{DSR_MIN} 硬卡 + 第四道质量否决已启用）")
        print(df.to_string(index=False))
    return df
