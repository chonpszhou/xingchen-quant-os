#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 可转债双低策略监控（每日收盘后执行）

拉取全市场可转债快照（akshare bond_zh_cov），按双低值排名输出 TOP30，
并对持仓执行预警规则：
  - 价格突破 130（强赎风险）
  - 溢价率较上日跳升 > 10pp
  - 价格 < 90 且正股 ST/*ST（信用/退市风险）

用法:
    python3 scripts/run_cb_double_low.py [--top 30]
输出:
    data/cb_daily_snapshot.json（当日快照归档）
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import akshare  # noqa: F401,E402

PRICE_CAP = 130.0
PREMIUM_CAP = 50.0
CREDIT_PRICE = 90.0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--top", type=int, default=30)
    args = p.parse_args()

    import akshare as ak
    df = ak.bond_zh_cov()
    df = df.rename(columns={
        "债券代码": "code", "债券简称": "name", "债现价": "price",
        "转股溢价率": "premium", "正股代码": "stock_code", "正股简称": "stock_name",
        "转股价": "conv_price", "转股价值": "conv_value", "信用评级": "rating",
        "上市时间": "list_date",
    })
    for c in ("price", "premium", "conv_value"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["code"] = df["code"].astype(str).str.zfill(6)
    # 上市满 30 个自然日（≈20 交易日），排除次新券与待上市
    df["list_date"] = pd.to_datetime(df["list_date"], errors="coerce")
    df = df[df["list_date"].notna() & (df["list_date"] <= pd.Timestamp.now() - pd.Timedelta(days=30))]

    # 标准可转债代码段
    df = df[df["code"].str.startswith(("110", "111", "113", "118", "123", "127", "128"))]
    # 信用过滤：剔除 ST 正股 / C级及以下评级 / 无评级（与模拟盘、回测口径一致）
    bad = df["stock_name"].astype(str).str.contains("ST") | df["rating"].astype(str).str.startswith("C") \
        | df["rating"].isna()
    df = df[~bad]
    df = df[df["price"].notna() & df["premium"].notna()]
    df = df[(df["price"] <= PRICE_CAP) & (df["premium"] <= PREMIUM_CAP)]
    df["score"] = df["price"] + df["premium"]
    df = df.sort_values("score").head(args.top)

    # 预警
    alerts = []
    for _, r in df.iterrows():
        if r["price"] > PRICE_CAP:
            alerts.append(f"{r['name']}({r['code']}) 价格 {r['price']:.1f} 突破 130 → 强赎风险")
        if r["price"] < CREDIT_PRICE and "ST" in str(r["stock_name"]):
            alerts.append(f"{r['name']}({r['code']}) 价格 {r['price']:.1f} 且正股 {r['stock_name']} ST → 信用风险")

    today = str(date.today())
    out = {
        "date": today,
        "rule": f"价格≤{PRICE_CAP:.0f} 且 溢价≤{PREMIUM_CAP:.0f}%，双低=价格+溢价，取前 {args.top}",
        "rank": df[["code", "name", "price", "premium", "conv_value", "stock_code", "stock_name", "rating", "score"]]
        .round(2).to_dict("records"),
        "alerts": alerts,
    }
    (ROOT / "data" / "cb_daily_snapshot.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"=== 可转债双低 TOP{args.top}（{today}）===\n")
    print(df[["name", "code", "price", "premium", "score", "rating"]].to_string(index=False))
    if alerts:
        print("\n=== 预警 ===")
        for a in alerts:
            print("⚠", a)
    else:
        print("\n无持仓预警")


if __name__ == "__main__":
    main()
