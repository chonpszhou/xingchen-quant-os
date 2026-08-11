#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 双动量 ETF 轮动模拟盘（观察级候选并行验证）

规则（回测口径一致）：
  - 资产池 SPY/GLD/DBC，动量=3/6/12月收益均值，取最高且>0 者满仓
  - 若全部动量≤0，持有 TLT（安全资产）
  - 每 21 交易日调仓，t+1 执行（次日按最新价），成本 0.1%
基准：SPY 买入持有（同初始资金）

状态：data/paper_mom_state.json + data/paper_mom_nav.parquet
用法：
    python3 scripts/paper_trade_momentum.py            # 每日推进
    python3 scripts/paper_trade_momentum.py --reset    # 重置
    python3 scripts/paper_trade_momentum.py --as-of 2026-08-01   # 历史回放（测试用）
"""

import argparse
import os
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from datahub.store import LocalStore  # noqa: E402

ASSETS = ["SPY", "GLD", "DBC"]
SAFE = "TLT"
LOOKBACKS = (63, 126, 252)
REBALANCE_DAYS = 21
COST = 0.001
_STATEDIR = Path(os.environ.get("PAPER_STATE_DIR", str(ROOT / "data")))
STATE_FILE = _STATEDIR / "paper_mom_state.json"
NAV_FILE = _STATEDIR / "paper_mom_nav.parquet"


def latest_prices(store, as_of=None):
    prices, dates = {}, {}
    for sym in ASSETS + [SAFE]:
        df = store.load_bars("美股", sym)
        if df is None or df.empty:
            return None, None
        if as_of is not None:
            d = df[df["date"] <= pd.Timestamp(as_of)]
            if d.empty:
                return None, None
            prices[sym] = float(d["close"].iloc[-1])
            dates[sym] = str(d["date"].iloc[-1].date())
        else:
            prices[sym] = float(df["close"].iloc[-1])
            dates[sym] = str(df["date"].iloc[-1].date())
    return prices, dates


def momentum_scores(store, as_of=None):
    close = {}
    for sym in ASSETS:
        df = store.load_bars("美股", sym)
        if df is not None:
            s = df.set_index("date")["close"]
            if as_of is not None:
                s = s[s.index <= pd.Timestamp(as_of)]
            close[sym] = s
    if len(close) != len(ASSETS):
        return None
    c = pd.DataFrame(close)
    scores = {}
    for a in ASSETS:
        scores[a] = float(np.mean([c[a].iloc[-1] / c[a].iloc[-1 - L] - 1 for L in LOOKBACKS]))
    return scores


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"cash": 1_000_000.0, "holdings": {}, "last_rebalance": None,
            "rebalance_count": 0, "start_date": str(date.today())}


def save_state(st):
    STATE_FILE.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")


def trade_days_since(last, today=None):
    if last is None:
        return 999
    cur = pd.Timestamp(today) if today else pd.Timestamp(date.today())
    return max(1, int((cur - pd.Timestamp(last)).days * 252 / 365))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--reset", action="store_true")
    p.add_argument("--as-of", default="")
    args = p.parse_args()
    if args.reset:
        save_state({"cash": 1_000_000.0, "holdings": {}, "last_rebalance": None,
                    "rebalance_count": 0, "start_date": str(date.today())})
        if NAV_FILE.exists():
            NAV_FILE.unlink()
        print("双动量模拟盘已重置")
        return

    store = LocalStore(str(ROOT / "data"))
    as_of = args.as_of or None
    today = str(date.today()) if not as_of else as_of
    prices, dates = latest_prices(store, as_of)
    if prices is None:
        print("本地缺少 ETF 数据，先运行 python3 scripts/run_all.py update")
        return
    st = load_state()
    due = trade_days_since(st["last_rebalance"], today) >= REBALANCE_DAYS

    # 持仓盯市（策略 + SPY 基准）
    for code, h in st["holdings"].items():
        h["last_price"] = prices.get(code, h["last_price"])
        h["value"] = h["shares"] * h["last_price"]
    nav = st["cash"] + sum(h["value"] for h in st["holdings"].values())
    spy_start = st.get("spy_entry", prices["SPY"])
    st.setdefault("spy_entry", prices["SPY"])
    bench_nav = 1_000_000.0 * prices["SPY"] / st["spy_entry"]

    if due:
        scores = momentum_scores(store, as_of)
        if scores:
            best = max(scores, key=scores.get)
            pick = best if scores[best] > 0 else SAFE
            # 清仓
            for code in list(st["holdings"]):
                h = st["holdings"].pop(code)
                st["cash"] += h["value"] * (1 - COST)
            # 买入选中标的（98% 仓位）
            if pick in prices:
                invest = nav * 0.98
                shares = invest / prices[pick]
                st["holdings"][pick] = {"shares": shares, "last_price": prices[pick],
                                        "value": invest, "entry_date": today}
                st["cash"] -= invest * (1 + COST)
            st["last_rebalance"] = today
            st["rebalance_count"] += 1
            print(f"调仓（第 {st['rebalance_count']} 次）→ {pick}（动量："
                  + " ".join(f"{k}={v:.1%}" for k, v in scores.items()) + "）")
            nav = st["cash"] + sum(h["value"] for h in st["holdings"].values())

    # 记录净值
    row = pd.DataFrame([{"date": pd.Timestamp(today), "nav": nav, "bench_nav": bench_nav,
                         "holding": ",".join(st["holdings"].keys()), "cash": st["cash"]}])
    if NAV_FILE.exists():
        old = pd.read_parquet(NAV_FILE)
        row = pd.concat([old, row], ignore_index=True)
    row = row.drop_duplicates("date", keep="last").sort_values("date")
    row["daily_return"] = row["nav"].pct_change()
    row.to_parquet(NAV_FILE, index=False)
    save_state(st)

    print(f"=== 双动量模拟盘 {today} ===")
    print(f"净值 {nav:,.0f}（SPY基准 {bench_nav:,.0f}）| 持仓 {list(st['holdings'].keys())} | "
          f"调仓 {st['rebalance_count']} 次 | 数据截至 {dates.get(list(st['holdings'])[0] if st['holdings'] else 'SPY', '-')}")
    if not due:
        print(f"距下次调仓约 {REBALANCE_DAYS - trade_days_since(st['last_rebalance'], today)} 交易日")


if __name__ == "__main__":
    main()
