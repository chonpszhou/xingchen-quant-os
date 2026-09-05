#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 港股等权蓝筹篮子模拟盘（观察级候选并行验证）

规则：
  - 资产池 00700(腾讯)/01810(小米)/00388(港交所)/00939(建行)/00941(中国移动)/01299(友邦)
  - 等权持有 6 只港股蓝筹，每 21 交易日再平衡回等权（成本 0.1%）
  - 个股从建仓价回撤 < -20% 止损（移到现金，记录风控事件）
  - 基准：腾讯(00700)买入持有（同初始资金，作港股代表）
状态：data/paper_hk_state.json + data/paper_hk_nav.parquet
用法：
    python3 scripts/paper_trade_hk.py            # 每日推进
    python3 scripts/paper_trade_hk.py --reset    # 重置
    python3 scripts/paper_trade_hk.py --as-of 2026-08-01   # 历史回放（测试用）
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

ASSETS = ["00700", "01810", "00388", "00939", "00941", "01299"]
BENCH = "00700"
REBALANCE_DAYS = 21
COST = 0.001
STOP_LOSS_PCT = -0.20
_STATEDIR = Path(os.environ.get("PAPER_STATE_DIR", str(ROOT / "data")))
STATE_FILE = _STATEDIR / "paper_hk_state.json"
NAV_FILE = _STATEDIR / "paper_hk_nav.parquet"


def latest_prices(store, as_of=None):
    prices, dates = {}, {}
    for sym in ASSETS + [BENCH]:
        df = store.load_bars("港股", sym)
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


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"cash": 1_000_000.0, "holdings": {}, "last_rebalance": None,
            "rebalance_count": 0, "start_date": str(date.today()),
            "risk_exits": []}


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
    p.add_argument("--force", action="store_true",
                   help="忽略调仓日历，立即按现有等权规则再平衡（用于把释放/追加的闲置现金按需部署）")
    args = p.parse_args()
    if args.reset:
        save_state({"cash": 1_000_000.0, "holdings": {}, "last_rebalance": None,
                    "rebalance_count": 0, "start_date": str(date.today()),
                    "risk_exits": []})
        if NAV_FILE.exists():
            NAV_FILE.unlink()
        print("港股模拟盘已重置")
        return

    store = LocalStore(str(ROOT / "data"))
    as_of = args.as_of or None
    today = str(date.today()) if not as_of else as_of
    prices, dates = latest_prices(store, as_of)
    if prices is None:
        print("本地缺少港股数据，先运行 python3 scripts/run_all.py update")
        return
    st = load_state()
    exits = st.setdefault("risk_exits", [])
    due = trade_days_since(st["last_rebalance"], today) >= REBALANCE_DAYS or args.force

    for code, h in st["holdings"].items():
        h["last_price"] = prices.get(code, h["last_price"])
        h["value"] = h["shares"] * h["last_price"]

    for code in list(st["holdings"]):
        h = st["holdings"][code]
        ep = h.get("entry_price") or h["last_price"]
        if ep and h["last_price"] < ep * (1 + STOP_LOSS_PCT):
            proceeds = h["value"] * (1 - COST)
            st["cash"] += proceeds
            exits.append({"code": code, "action": "SELL_STOP_LOSS",
                          "reason": f"回撤 {(h['last_price']/ep-1)*100:.1f}% < {STOP_LOSS_PCT*100:.0f}%",
                          "date": today})
            st["holdings"].pop(code)
            print(f"止损卖出 {code} @ {h['last_price']:.2f}")

    nav = st["cash"] + sum(h["value"] for h in st["holdings"].values())
    st.setdefault("bench_entry", prices[BENCH])
    bench_nav = 1_000_000.0 * prices[BENCH] / st["bench_entry"]

    if due or not st["holdings"]:
        for code in list(st["holdings"]):
            h = st["holdings"].pop(code)
            st["cash"] += h["value"] * (1 - COST)
        if st["holdings"] or due or nav >= 1_000_000.0:
            invest = st["cash"] * 0.98
            per = invest / len(ASSETS)
            for sym in ASSETS:
                if sym in prices:
                    shares = per / prices[sym]
                    st["holdings"][sym] = {"shares": shares, "last_price": prices[sym],
                                          "value": per, "entry_date": today,
                                          "entry_price": prices[sym]}
                    st["cash"] -= per * (1 + COST)
            st["last_rebalance"] = today
            st["rebalance_count"] += 1
            print(f"建仓/再平衡（第 {st['rebalance_count']} 次）→ 等权 {ASSETS}")
            nav = st["cash"] + sum(h["value"] for h in st["holdings"].values())

    row = pd.DataFrame([{"date": pd.Timestamp(today), "nav": nav, "bench_nav": bench_nav,
                         "holding": ",".join(st["holdings"].keys()), "cash": st["cash"]}])
    if NAV_FILE.exists():
        old = pd.read_parquet(NAV_FILE)
        row = pd.concat([old, row], ignore_index=True)
    row = row.drop_duplicates("date", keep="last").sort_values("date")
    row["daily_return"] = row["nav"].pct_change()
    row.to_parquet(NAV_FILE, index=False)
    save_state(st)

    print(f"=== 港股模拟盘 {today} ===")
    print(f"净值 {nav:,.0f}（腾讯基准 {bench_nav:,.0f}）| 持仓 {list(st['holdings'].keys())} | "
          f"调仓 {st['rebalance_count']} 次 | 数据截至 {dates.get(list(st['holdings'])[0] if st['holdings'] else BENCH, '-')}")
    if not due:
        print(f"距下次调仓约 {REBALANCE_DAYS - trade_days_since(st['last_rebalance'], today)} 交易日")


if __name__ == "__main__":
    main()
