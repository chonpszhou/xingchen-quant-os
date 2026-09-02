#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · AAPL 波动率目标动量灰度模拟盘（续十候选前向跟踪）

续十产出系统首个五道闸候选 AAPL(vol_target_momentum)；灰度模拟报告(gray_sim_aapl_20260902.md)
确认其前向样本外成立(FORWARD HOLDS)。本脚本把它接成**日频观察账户**，持续累积前向样本。

规则（与引擎/灰度验证一致，t+1 成交）：
  - 信号：12-1 月动量窗口 + 跳过最近 21 日 + 指数衰减权重；纯多头。
  - 仓位：波动目标，权重 = min(1, 目标年化波动 0.25 / 实现波动(21日))。
  - 调仓：目标权重相对当前持仓偏离 ≥ 5pp 才交易（降成本），成本 0.1%。
  - 基准：AAPL 买入持有（同初始资金）。
状态：data/paper_aapl_state.json + data/paper_aapl_nav.parquet
用法：
    python3 scripts/paper_trade_aapl.py            # 每日推进（append 今日）
    python3 scripts/paper_trade_aapl.py --backfill # 回放全历史，写完整 NAV
    python3 scripts/paper_trade_aapl.py --reset     # 重置
注意：本账户为**观察级灰度**，不进实盘、不触 broker、不发送任何下单。
"""
import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SYM = "AAPL"
MARKET = "美股"
WINDOW = 252
SKIP = 21
DECAY = 0.05
TVOL = 0.25
COST = 0.001
REBAL_THRESH = 0.05  # 目标权重偏离 ≥ 5pp 才调仓
INIT_CASH = 1_000_000.0
_STATEDIR = Path(os.environ.get("PAPER_STATE_DIR", str(ROOT / "data")))
STATE_FILE = _STATEDIR / "paper_aapl_state.json"
NAV_FILE = _STATEDIR / "paper_aapl_nav.parquet"
BAR = ROOT / "data" / "bars" / MARKET / f"{SYM}.parquet"


def load_close():
    df = pd.read_parquet(BAR).sort_values("date")
    return df.set_index("date")["close"].astype(float)


def target_series(close):
    """全序列因果目标权重（date t 权重仅取决 close<=t）。t+1 成交用 w.shift(1)。"""
    logret = np.log(close / close.shift(1)).fillna(0.0).to_numpy()
    n = len(logret)
    w = np.exp(-DECAY * np.arange(WINDOW - 1, -1, -1))
    w = w / w.sum()
    shifted = np.zeros(n)
    shifted[SKIP:] = logret[: n - SKIP]
    sig = np.convolve(shifted, w[::-1], mode="full")[:n]
    sig_s = pd.Series(sig, index=close.index)
    vol = close.pct_change().rolling(SKIP).std() * np.sqrt(252)
    out = {}
    for dt in close.index:
        s = float(sig_s.get(dt, 0.0))
        v = vol.get(dt)
        if s > 0 and pd.notna(v) and v > 0:
            out[dt] = float(min(1.0, TVOL / float(v)))
        else:
            out[dt] = 0.0
    return pd.Series(out, index=close.index)


def target_at(close, as_of):
    """as_of 当日的因果目标权重（用于每日推进的决策）。"""
    s = close[close.index <= pd.Timestamp(as_of)] if as_of is not None else close
    if len(s) < WINDOW + SKIP + 2:
        return 0.0
    return float(target_series(s).iloc[-1])


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"cash": INIT_CASH, "shares": 0.0, "entry_price": None,
            "target_weight": 0.0, "last_rebalance": None, "rebalance_count": 0,
            "start_date": str(date.today()), "bench_entry": None}


def save_state(st):
    STATE_FILE.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")


def backfill():
    close = load_close()
    w = target_series(close)
    ret = close.pct_change().fillna(0.0)
    sret = (w.shift(1) * ret).fillna(0.0)  # t+1
    nav = (1.0 + sret).cumprod() * INIT_CASH
    bench = INIT_CASH * close / float(close.iloc[0])
    rows = []
    cur_w = 0.0
    reb = 0
    for dt in close.index:
        rows.append({"date": pd.Timestamp(dt), "nav": float(nav.loc[dt]),
                     "bench_nav": float(bench.loc[dt]), "weight": float(w.get(dt, 0.0)),
                     "cash": float(INIT_CASH * (1.0 - float(w.get(dt, 0.0)))),
                     "rebalance_count": reb})
    df = pd.DataFrame(rows).sort_values("date").drop_duplicates("date", keep="last")
    df["daily_return"] = df["nav"].pct_change()
    df.to_parquet(NAV_FILE, index=False)
    last_w = float(w.iloc[-1])
    last_price = float(close.iloc[-1])
    save_state({"cash": INIT_CASH * (1 - last_w), "shares": (INIT_CASH * last_w) / last_price,
                "entry_price": last_price, "target_weight": last_w,
                "last_rebalance": str(close.index[-1].date()), "rebalance_count": int((w > 0).sum()),
                "start_date": str(close.index[0].date()), "bench_entry": float(close.iloc[0])})
    print(f"=== AAPL 灰度模拟盘 回放完成 ===")
    print(f"区间 {close.index[0].date()}..{close.index[-1].date()}  净值 {df['nav'].iloc[-1]:,.0f} "
          f"| 基准 {df['bench_nav'].iloc[-1]:,.0f} | 末权重 {last_w:.2f}")
    print(f"全期收益 {(df['nav'].iloc[-1]/INIT_CASH-1):+.1%}  基准 {(df['bench_nav'].iloc[-1]/INIT_CASH-1):+.1%}")


def daily_step(as_of=None):
    close = load_close()
    today = pd.Timestamp(as_of) if as_of else pd.Timestamp(date.today())
    today = close.index[close.index <= today]
    if len(today) == 0:
        print("无数据")
        return
    today = today[-1]
    price = float(close.loc[today])
    st = load_state()
    # 盯市当前持仓（昨日决策、今日持有）
    pos_value = st["shares"] * price
    nav = st["cash"] + pos_value
    if st["bench_entry"] is None:
        st["bench_entry"] = price
    bench_nav = INIT_CASH * price / float(st["bench_entry"])
    cur_w = st["target_weight"]

    # 记录今日净值（用当前持仓，t+1 口径）
    row = pd.DataFrame([{"date": pd.Timestamp(today), "nav": nav, "bench_nav": bench_nav,
                         "weight": cur_w, "cash": st["cash"],
                         "rebalance_count": st["rebalance_count"]}])
    if NAV_FILE.exists():
        old = pd.read_parquet(NAV_FILE)
        if str(today.date()) in set(pd.to_datetime(old["date"]).dt.strftime("%Y-%m-%d")):
            print(f"今日 {today.date()} 已记录，跳过")
            return
        row = pd.concat([old, row], ignore_index=True)
    row = row.drop_duplicates("date", keep="last").sort_values("date")
    row["daily_return"] = row["nav"].pct_change()
    row.to_parquet(NAV_FILE, index=False)

    # 计算今日决策权重（数据≤今日），偏离≥阈值才调仓（t+1 执行）
    new_w = target_at(close, today)
    if abs(new_w - cur_w) >= REBAL_THRESH or (st["last_rebalance"] is None and new_w > 0):
        # 调到 new_w：卖出旧仓、买入新仓，成本 0.1%
        st["cash"] += pos_value * (1 - COST)  # 先平旧仓
        st["shares"] = 0.0
        invest = nav * new_w
        if invest > 0:
            st["shares"] = invest / price
            st["cash"] -= invest * (1 + COST)
        st["target_weight"] = new_w
        st["entry_price"] = price
        st["last_rebalance"] = str(today.date())
        st["rebalance_count"] += 1
        print(f"调仓（第 {st['rebalance_count']} 次）→ 权重 {new_w:.2f} @ {price:.2f}")
    save_state(st)
    print(f"=== AAPL 灰度模拟盘 {today.date()} ===")
    print(f"净值 {nav:,.0f}（基准 {bench_nav:,.0f}）| 当前权重 {st['target_weight']:.2f} | "
          f"调仓 {st['rebalance_count']} 次")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--reset", action="store_true")
    p.add_argument("--backfill", action="store_true")
    p.add_argument("--as-of", default="")
    args = p.parse_args()
    if args.reset:
        save_state({"cash": INIT_CASH, "shares": 0.0, "entry_price": None,
                    "target_weight": 0.0, "last_rebalance": None, "rebalance_count": 0,
                    "start_date": str(date.today()), "bench_entry": None})
        if NAV_FILE.exists():
            NAV_FILE.unlink()
        print("AAPL 灰度模拟盘已重置")
        return
    if args.backfill:
        backfill()
        return
    daily_step(args.as_of or None)


if __name__ == "__main__":
    main()
