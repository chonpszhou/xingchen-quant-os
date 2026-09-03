#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""动态方法库 · 无闸回测（研究层，非实盘晋升）

遍历 config/strategies.json 中已注册的方法，用共享引擎 Backtester 立即回测，
输出 data/method_perf.csv（total_return / sharpe / max_dd / ...）。

设计要点（用户要求：方法动态更新）：
  - 方法**注册即生效、可回测、可对比**，不需要先过五道闸。
  - 五道闸（engine.optimizer.optimize）只用于"晋升到模拟盘/实盘"那一步，
    是下单前的护栏，不是方法进入系统的门槛。
  - 这里只做无闸 NAV 复现，给出方法的真实风险收益画像，供系统持续重测/对比。
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
# 容器里以 `python3 scripts/X.py` 调用时 /app 不在 sys.path[0]，需显式注入仓库根
# （research_sweep.py 同款处理），否则 quantos_engine 等顶层包无法导入。
sys.path.insert(0, str(ROOT))


def _signal_kwargs(template: str) -> set:
    """取信号函数接受的形参名（不含 df），用于参数安全过滤。"""
    from quantos_engine.backtest import _STRATS
    import inspect
    fn = _STRATS.get(template)
    if fn is None:
        return set()
    return {p for p in inspect.signature(fn).parameters if p != "df"}

from quantos_engine.backtest import Backtester
from quantos_engine.strategies import load_registry

# 方法注册表用的市场代码 → data/bars 中文目录名
_MARKET_DIR = {"us": "美股", "a": "A股", "hk": "港股",
               "crypto": "虚拟货币", "future": "期货", "futures": "期货"}


def _sym_file(sym: str, mkt: str) -> str:
    """symbol → bars 文件名（去前缀/补下划线，对齐 data/bars 实际命名）。"""
    if mkt == "crypto":
        return sym.replace("USDT", "_USDT")  # BTCUSDT → BTC_USDT
    return sym


def _bars(mkt: str, sym: str, limit: int = 800):
    """直接读 data/bars/{中文市场}/{SYMBOL}.parquet（与 datahub 布局一致）。"""
    d = _MARKET_DIR.get(mkt, mkt)
    fp = ROOT / "data" / "bars" / d / f"{_sym_file(sym, mkt)}.parquet"
    if not fp.exists():
        print(f"  ⚠️ {sym}({mkt}) 行情文件缺失: {fp}")
        return None
    try:
        df = pd.read_parquet(fp)
    except Exception as e:  # noqa
        print(f"  ⚠️ {sym}({mkt}) 读取失败: {e}")
        return None
    if "close" not in df.columns or "date" not in df.columns or len(df) < 60:
        return None
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    return df.set_index("date")["close"].sort_index().tail(limit).to_frame("close")


def main():
    reg = load_registry(ROOT / "config" / "strategies.json")
    methods = reg.valid_methods()
    print(f"动态方法库：{len(methods)} 条有效方法，开始无闸回测（仅研究，不晋升实盘）")
    rows = []
    for m in methods:
        mid = m["id"]
        tmpl = m["template"]
        params = m.get("params", {}) or {}
        sym = m.get("symbol", "AAPL")
        mkt = m.get("market", "us")
        df = _bars(mkt, sym)
        if df is None:
            rows.append({"id": mid, "template": tmpl, "symbol": sym, "market": mkt,
                         "total_return": None, "sharpe": None, "max_dd": None,
                         "note": "行情不足"})
            print(f"  ⊘ {mid}: 行情不足跳过")
            continue
        # 安全过滤：只把信号函数接受的 kwarg 传进去，多余/改名参数告警跳过
        accepted = _signal_kwargs(tmpl)
        clean = {k: v for k, v in params.items() if k in accepted}
        dropped = [k for k in params if k not in accepted]
        if dropped:
            print(f"  · {mid}: 忽略信号函数不接受参数 {dropped}（接受 {sorted(accepted)}）")
        try:
            res = Backtester(commission=0.002).run(df, strategy=tmpl, **clean)
        except Exception as e:  # noqa
            rows.append({"id": mid, "template": tmpl, "symbol": sym, "market": mkt,
                         "total_return": None, "sharpe": None, "max_dd": None,
                         "note": f"回测异常:{e}"})
            print(f"  ⚠ {mid}: 回测异常 {e}")
            continue
        nav = res["equity"]
        nav.index = df.index
        total = nav.iloc[-1] / nav.iloc[0] - 1
        r = nav.pct_change().dropna()
        sharpe = r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else 0.0
        mdd = (nav / nav.cummax() - 1).min()
        rows.append({"id": mid, "template": tmpl, "symbol": sym, "market": mkt,
                     "total_return": round(total, 4), "sharpe": round(sharpe, 3),
                     "max_dd": round(mdd, 4), "note": "无闸回测(研究层)"})
        print(f"  ➕ {mid} [{tmpl}] {sym}/{mkt}: 收益={total:+.2%} 夏普={sharpe:.2f} 回撤={mdd:+.2%}")

    out = ROOT / "data" / "method_perf.csv"
    if rows:
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"✓ 方法库回测结果已写: {out}")
    else:
        print("（方法库为空，无回测）")


if __name__ == "__main__":
    main()
