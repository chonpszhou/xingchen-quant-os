#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 平台引擎 CLI（回测 / 纸面信号）

用法:
    python3 scripts/engine_cli.py --strategy dual_momentum --mode backtest
    python3 scripts/engine_cli.py --strategy cb_double_low --mode backtest --tail 500
    python3 scripts/engine_cli.py --strategy risk_parity --mode paper
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.backtest import BacktestEngine  # noqa: E402
from engine.data_service import DataService  # noqa: E402
from engine.database import Database  # noqa: E402
from engine.exits import ExitManager  # noqa: E402
from engine.optimizer import optimize  # noqa: E402
from engine.executor import PaperExecutor  # noqa: E402
from engine.risk import RiskEngine  # noqa: E402
from engine.strategy import get_strategy  # noqa: E402
from factors.backtest import metrics  # noqa: E402

REF = {"dual_momentum": 0.2265, "risk_parity": 0.0579, "cb_double_low": 0.1362}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--strategy", required=True)
    p.add_argument("--mode", choices=["backtest", "paper"], default="backtest")
    p.add_argument("--tail", type=int, default=0, help="仅用最近 N 根 K 线")
    p.add_argument("--sl", type=float, default=0, help="止损百分比覆盖（如 0.08）")
    p.add_argument("--tp", type=float, default=0, help="止盈百分比覆盖")
    p.add_argument("--trail", type=float, default=0, help="移动止损百分比覆盖")
    p.add_argument("--hold", type=int, default=0, help="时间止损天数覆盖")
    p.add_argument("--atr-mult", type=float, default=0, help="ATR 止损倍数覆盖（如 2.0）")
    p.add_argument("--breakeven", type=float, default=0, help="保本移动阈值覆盖（如 0.06）")
    p.add_argument("--optimize", action="store_true", help="参数寻优模式（配 --grid）")
    p.add_argument("--grid", default="", help='参数网格 JSON，如 {"rebalance":[14,21,28]}')
    args = p.parse_args()

    cfg = yaml.safe_load((ROOT / "config" / "strategies.yaml").read_text(encoding="utf-8"))
    params = cfg["strategies"].get(args.strategy, {})
    ds = DataService(ROOT / "data")
    strat = get_strategy(args.strategy, data_service=ds, **params)
    strat.on_init()
    exit_cfg = yaml.safe_load((ROOT / "config" / "exits.yaml").read_text(encoding="utf-8"))
    rules = dict(exit_cfg["exits"].get(args.strategy, {}))
    for k, v in (("stop_loss", args.sl), ("take_profit", args.tp),
                 ("trailing", args.trail), ("max_hold_days", args.hold)):
        if v:
            rules[k] = v
    rules = {k: v for k, v in rules.items() if v}  # 0 值 = 不启用该规则
    if args.atr_mult:
        rules["atr_multiplier"] = args.atr_mult
    if args.breakeven:
        rules["breakeven_at_profit_pct"] = args.breakeven
    exit_mgr = ExitManager(rules)

    if args.mode == "paper":
        last = getattr(strat, "_close", getattr(strat, "_vol", None))
        if last is not None:
            last_bar = last.index[-1]
        else:
            from engine.object import BarData
            import pandas as pd
            last_bar = pd.Timestamp.now()
        from engine.object import BarData
        strat.i = strat.params["rebalance"] * 3 + 1
        strat.on_bar(None, BarData(symbol="", datetime=last_bar))
        print(f"策略 {args.strategy} 当前信号目标持仓：")
        for sym, w in sorted(strat._target.items(), key=lambda x: -x[1]):
            print(f"  {sym}: {w:.0%}")
        print(f"退出规则：{exit_mgr.describe()}")
        return

    # 回测：按策略构建价格面
    if hasattr(strat, "_close"):
        close = strat._close
        start = "2022-09-02"
        atr = build_atr(ds, strat.params["assets"] + [strat.params.get("safe", "")])
    else:
        close = ds.cb_close()
        start = None
        atr = None
    if args.tail:
        close = close.tail(args.tail)
        if atr is not None:
            atr = atr.tail(args.tail)

    if args.optimize:
        if not args.grid:
            print("--optimize 需要 --grid 参数，如 --grid '{\"rebalance\":[14,21,28]}'")
            return
        grid = json.loads(args.grid)
        res = optimize(args.strategy, grid, close, ds, risk=RiskEngine(max_single_weight=1.0, max_positions=30),
                       exits=exit_mgr)
        best = res[res["PASS"]].head(1)
        if len(best):
            print("\n最佳通过参数：")
            print(best.to_string(index=False))
        else:
            print("\n无参数组合通过反过拟合门槛（可放宽 --grid 或调整阈值）")
        return

    db = Database(ROOT / "data" / "engine.sqlite")
    ex = PaperExecutor(db=db, strategy_name=args.strategy)
    risk = RiskEngine(max_single_weight=1.0, max_positions=30)
    engine = BacktestEngine(strat, ex, risk, exit_manager=exit_mgr, atr_frame=atr)
    nav = engine.run(close, start=start)
    m = metrics(nav, 0.0, n_trials=6)
    ref = REF.get(args.strategy)
    diff = f"| 偏差 {abs(m['annual_return'] - ref):.2%}" if ref else ""
    print(f"[{args.strategy}] 回测：年化 {m['annual_return']:.2%} | 夏普 {m['sharpe']} | "
          f"HAC t {m['hac_t']} | 回撤 {m['max_drawdown']:.2%} {diff}")
    print(f"交易流水：{len(db.trades(args.strategy))} 笔 → data/engine.sqlite")
    print(f"退出规则：{exit_mgr.describe()} | 触发退出 {engine.exit_trades} 次")


def build_atr(ds, symbols):
    """14 日 ATR（逐标的真实波幅均值），供 ATR 止损用"""
    import numpy as np
    o = ds.ohlcv("美股", symbols)
    high, low, close = o["high"], o["low"], o["close"]
    pc = close.shift(1)
    tr = pd.DataFrame(index=close.index, columns=close.columns)
    for s in close.columns:
        tr[s] = np.maximum.reduce([
            (high[s] - low[s]).values,
            (high[s] - pc[s]).abs().values,
            (low[s] - pc[s]).abs().values])
    return tr.rolling(14).mean()


if __name__ == "__main__":
    main()
