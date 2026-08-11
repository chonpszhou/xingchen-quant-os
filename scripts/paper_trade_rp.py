#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 风险平价模拟盘（稳定型底仓候选）

规则（回测口径一致）：
  - 资产池 SPY/GLD/TLT/DBC，权重 = 逆波动率（w ∝ 1/20日年化波动）
  - 波动目标 8%（若自然权重组合波动 >8% 则整体缩放，不加杠杆）
  - 每 21 交易日调仓，t+1 执行（按最新价），成本 0.1%，差额调仓
基准：SPY 买入持有（同初始资金）

状态：data/paper_rp_state.json + data/paper_rp_nav.parquet
用法：
    python3 scripts/paper_trade_rp.py            # 每日推进
    python3 scripts/paper_trade_rp.py --reset    # 重置
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from datahub.store import LocalStore  # noqa: E402

ASSETS = ["SPY", "GLD", "TLT", "DBC"]
REBALANCE_DAYS = 21
COST = 0.001
TARGET_VOL = 0.08
STATE_FILE = ROOT / "data" / "paper_rp_state.json"
NAV_FILE = ROOT / "data" / "paper_rp_nav.parquet"


def latest_prices(store):
    prices, dates = {}, {}
    for sym in ASSETS:
        df = store.load_bars("美股", sym)
        if df is None or df.empty:
            return None, None
        prices[sym] = float(df["close"].iloc[-1])
        dates[sym] = str(df["date"].iloc[-1].date())
    return prices, dates


def target_weights(store, prices):
    vols = {}
    for sym in ASSETS:
        df = store.load_bars("美股", sym)
        if df is None or len(df) < 30:
            return None
        r = df.set_index("date")["close"].pct_change().tail(20)
        vols[sym] = float(r.std() * np.sqrt(252))
    w = pd.Series({s: 1.0 / max(v, 1e-4) for s, v in vols.items()})
    w = w / w.sum()
    port_vol = np.sqrt(w.values @ np.diag([vols[s] ** 2 for s in ASSETS]) @ w.values)
    scale = min(1.0, TARGET_VOL / max(port_vol, 1e-4))
    return (w * scale).to_dict()


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"cash": 1_000_000.0, "holdings": {}, "last_rebalance": None,
            "rebalance_count": 0, "start_date": str(date.today()), "spy_entry": None}


def save_state(st):
    STATE_FILE.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")


def trade_days_since(last):
    if last is None:
        return 999
    return max(1, int((pd.Timestamp(date.today()) - pd.Timestamp(last)).days * 252 / 365))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--reset", action="store_true")
    args = p.parse_args()
    if args.reset:
        save_state({"cash": 1_000_000.0, "holdings": {}, "last_rebalance": None,
                    "rebalance_count": 0, "start_date": str(date.today()), "spy_entry": None})
        if NAV_FILE.exists():
            NAV_FILE.unlink()
        print("风险平价模拟盘已重置")
        return

    store = LocalStore(str(ROOT / "data"))
    prices, dates = latest_prices(store)
    if prices is None:
        print("本地缺少 ETF 数据，先运行 python3 scripts/run_all.py update")
        return
    st = load_state()
    today = str(date.today())
    due = trade_days_since(st["last_rebalance"]) >= REBALANCE_DAYS
    if not st.get("spy_entry"):
        st["spy_entry"] = prices["SPY"]

    # 盯市
    for code, h in st["holdings"].items():
        h["last_price"] = prices.get(code, h["last_price"])
        h["value"] = h["shares"] * h["last_price"]
    nav = st["cash"] + sum(h["value"] for h in st["holdings"].values())
    bench_nav = 1_000_000.0 * prices["SPY"] / st["spy_entry"]

    if due:
        w = target_weights(store, prices)
        if w:
            invest = nav * 0.98
            target_value = {s: w[s] * invest for s in ASSETS}
            # 差额调仓
            for s in ASSETS:
                cur = st["holdings"].get(s, {}).get("value", 0.0)
                delta = target_value[s] - cur
                if abs(delta) < 100:
                    continue
                if delta > 0:  # 买入
                    shares = delta / prices[s]
                    st["holdings"][s] = {"shares": shares, "last_price": prices[s],
                                         "value": delta, "entry_date": today}
                    st["cash"] -= delta * (1 + COST)
                else:  # 卖出
                    sell_val = min(cur, -delta)
                    st["holdings"][s]["shares"] -= sell_val / prices[s]
                    st["holdings"][s]["value"] = st["holdings"][s]["shares"] * prices[s]
                    st["cash"] += sell_val * (1 - COST)
                    if st["holdings"][s]["shares"] < 0.001:
                        del st["holdings"][s]
            st["last_rebalance"] = today
            st["rebalance_count"] += 1
            print(f"调仓（第 {st['rebalance_count']} 次）→ " +
                  " ".join(f"{s}={w[s]:.0%}" for s in ASSETS))
            nav = st["cash"] + sum(h["value"] for h in st["holdings"].values())

    row = pd.DataFrame([{"date": pd.Timestamp(today), "nav": nav, "bench_nav": bench_nav,
                         "holding": ";".join(f"{k}:{v['shares']:.0f}" for k, v in st["holdings"].items()),
                         "cash": st["cash"]}])
    if NAV_FILE.exists():
        old = pd.read_parquet(NAV_FILE)
        row = pd.concat([old, row], ignore_index=True)
    row = row.drop_duplicates("date", keep="last").sort_values("date")
    row["daily_return"] = row["nav"].pct_change()
    row.to_parquet(NAV_FILE, index=False)
    save_state(st)

    print(f"=== 风险平价模拟盘 {today} ===")
    print(f"净值 {nav:,.0f}（SPY基准 {bench_nav:,.0f}）| 调仓 {st['rebalance_count']} 次 | 数据截至 {dates['SPY']}")
    if st["holdings"]:
        print("当前配置（TOP4）：")
        for s, h in sorted(st["holdings"].items(), key=lambda x: -x[1]["value"]):
            print(f"  {s}: {h['value']:,.0f} ({h['value'] / nav:.0%})")
    if not due:
        print(f"距下次调仓约 {REBALANCE_DAYS - trade_days_since(st['last_rebalance'])} 交易日")


if __name__ == "__main__":
    main()
