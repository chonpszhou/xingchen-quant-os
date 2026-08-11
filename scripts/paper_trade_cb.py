#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 可转债双低策略模拟盘（有状态持仓模拟）

每日运行（或定时）：
  1) 拉取全市场可转债快照（akshare bond_zh_cov），计算目标组合
  2) 到调仓日（距上次调仓 ≥20 交易日）执行调仓：卖出不在目标中的持仓，
     买入目标组合缺失的标的，等权分配，成本 0.1%/边
  3) 每日按最新价格对持仓盯市，记录净值序列

状态文件：data/paper_cb_state.json（持仓/现金/上次调仓/调仓次数）
净值序列：data/paper_cb_nav.parquet（date, nav, bench_nav, daily_return, holdings）
基准：全债等权（同筛选条件、同调仓节奏），用于“跑赢基准”纪律判定。

用法:
    python3 scripts/paper_trade_cb.py            # 每日更新（模拟盘推进）
    python3 scripts/paper_trade_cb.py --reset    # 重置模拟盘
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

import akshare  # noqa: F401,E402

COST = 0.001
N_HOLD = 20
PRICE_CAP = 130.0
PREMIUM_CAP = 50.0
MIN_LISTED_DAYS = 30  # 自然日
REBALANCE_DAYS = 20   # 交易日
STATE_FILE = ROOT / "data" / "paper_cb_state.json"
NAV_FILE = ROOT / "data" / "paper_cb_nav.parquet"


def fetch_snapshot():
    import akshare as ak
    df = ak.bond_zh_cov()
    df = df.rename(columns={
        "债券代码": "code", "债券简称": "name", "债现价": "price",
        "转股溢价率": "premium", "正股代码": "stock_code", "正股简称": "stock_name",
        "转股价": "conv_price", "转股价值": "conv_value", "信用评级": "rating",
        "上市时间": "list_date",
    })
    df["code"] = df["code"].astype(str).str.zfill(6)
    df = df[df["code"].str.startswith(("110", "111", "113", "118", "123", "127", "128"))]
    for c in ("price", "premium", "conv_value"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["list_date"] = pd.to_datetime(df["list_date"], errors="coerce")
    df = df[df["list_date"].notna() & (df["list_date"] <= pd.Timestamp.now() - pd.Timedelta(days=MIN_LISTED_DAYS))]
    # 信用过滤：剔除 ST 正股 / C级及以下 / 无评级
    bad = df["stock_name"].astype(str).str.contains("ST") | df["rating"].astype(str).str.startswith("C") \
        | df["rating"].isna()
    df = df[~bad]
    df = df[(df["price"] <= PRICE_CAP) & (df["premium"] <= PREMIUM_CAP)]
    df["score"] = df["price"] + df["premium"]
    bench = df.sort_values("score")          # 基准：全部合格券等权
    target = bench.head(N_HOLD)
    return target, bench


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"cash": 1_000_000.0, "holdings": {}, "last_rebalance": None,
            "rebalance_count": 0, "start_date": str(date.today())}


def save_state(st):
    STATE_FILE.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")


def trade_days_since(last):
    """用本地交易日历粗算两个日期间交易日数（近 252 日/年近似）"""
    if last is None:
        return 999
    return max(1, int((pd.Timestamp(date.today()) - pd.Timestamp(last)).days * 252 / 365))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--reset", action="store_true")
    args = p.parse_args()
    if args.reset:
        save_state({"cash": 1_000_000.0, "holdings": {}, "last_rebalance": None,
                    "rebalance_count": 0, "start_date": str(date.today())})
        if NAV_FILE.exists():
            NAV_FILE.unlink()
        print("模拟盘已重置")
        return

    target, bench = fetch_snapshot()
    st = load_state()
    st.setdefault("bench_cash", 1_000_000.0)
    st.setdefault("bench_holdings", {})
    today = str(date.today())
    due = trade_days_since(st["last_rebalance"]) >= REBALANCE_DAYS

    prices = target.set_index("code")["price"].to_dict()
    prices.update(bench.set_index("code")["price"].to_dict())
    for code in list(st["holdings"]):
        if code not in prices:
            prices[code] = st["holdings"][code]["last_price"]
    for code in list(st["bench_holdings"]):
        if code not in prices:
            prices[code] = st["bench_holdings"][code]["last_price"]

    # 持仓盯市（策略 + 基准）
    for code, h in st["holdings"].items():
        h["last_price"] = prices.get(code, h["last_price"])
        h["value"] = h["shares"] * h["last_price"]
    mv = sum(h["value"] for h in st["holdings"].values())
    nav = st["cash"] + mv
    for code, h in st["bench_holdings"].items():
        h["last_price"] = prices.get(code, h["last_price"])
        h["value"] = h["shares"] * h["last_price"]
    bench_mv = sum(h["value"] for h in st["bench_holdings"].values())
    bench_nav = st["bench_cash"] + bench_mv

    if due and len(target) >= N_HOLD:
        # ---- 策略组合调仓 ----
        target_codes = set(target["code"])
        for code in list(st["holdings"]):
            if code not in target_codes:
                h = st["holdings"].pop(code)
                st["cash"] += h["value"] * (1 - COST)
        target_value = nav * 0.98 / N_HOLD
        for _, r in target.iterrows():
            code = r["code"]
            if code in st["holdings"]:
                continue
            shares = target_value / r["price"]
            st["holdings"][code] = {"shares": shares, "last_price": float(r["price"]),
                                    "value": target_value, "entry_date": today}
            st["cash"] -= target_value * (1 + COST)
        # ---- 基准组合调仓（全合格券等权） ----
        bench_codes = set(bench["code"])
        for code in list(st["bench_holdings"]):
            if code not in bench_codes:
                h = st["bench_holdings"].pop(code)
                st["bench_cash"] += h["value"] * (1 - COST)
        if len(bench) > 0:
            bv = bench_nav * 0.98 / len(bench)
            for _, r in bench.iterrows():
                code = r["code"]
                if code in st["bench_holdings"]:
                    continue
                shares = bv / r["price"]
                st["bench_holdings"][code] = {"shares": shares, "last_price": float(r["price"]),
                                              "value": bv, "entry_date": today}
                st["bench_cash"] -= bv * (1 + COST)
        st["last_rebalance"] = today
        st["rebalance_count"] += 1
        print(f"调仓执行（第 {st['rebalance_count']} 次），策略 {len(target)} 只 / 基准 {len(bench)} 只")
        mv = sum(h["value"] for h in st["holdings"].values())
        nav = st["cash"] + mv
        bench_mv = sum(h["value"] for h in st["bench_holdings"].values())
        bench_nav = st["bench_cash"] + bench_mv

    # 记录净值
    nav_row = pd.DataFrame([{"date": pd.Timestamp(today), "nav": nav, "bench_nav": bench_nav,
                             "holdings": len(st["holdings"]), "cash": st["cash"]}])
    if NAV_FILE.exists():
        old = pd.read_parquet(NAV_FILE)
        nav_row = pd.concat([old, nav_row], ignore_index=True)
    nav_row = nav_row.drop_duplicates("date", keep="last").sort_values("date")
    nav_row["daily_return"] = nav_row["nav"].pct_change()
    nav_row.to_parquet(NAV_FILE, index=False)
    save_state(st)

    print(f"=== 模拟盘 {today} ===")
    print(f"净值 {nav:,.0f}（基准 {bench_nav:,.0f}）| 持仓 {len(st['holdings'])} 只 | 现金 {st['cash']:,.0f} | 调仓 {st['rebalance_count']} 次")
    if st["holdings"]:
        print("\n当前持仓（TOP5）：")
        for code, h in sorted(st["holdings"].items(), key=lambda x: -x[1]["value"])[:5]:
            print(f"  {code}: {h['shares']:.0f} 张 @ {h['last_price']:.2f} = {h['value']:,.0f}")
    if not due:
        print(f"\n距下次调仓约 {REBALANCE_DAYS - trade_days_since(st['last_rebalance'])} 交易日")


if __name__ == "__main__":
    main()
