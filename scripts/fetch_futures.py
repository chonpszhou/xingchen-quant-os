#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 期货数据层

1) 国内商品期货主力合约日线（新浪，futures_zh_daily_sina）
2) 加密永续合约资金费率快照（OKX 公开接口）

用法:
    python3 scripts/fetch_futures.py
输出:
    data/bars/期货/*.parquet + data/futures_funding.json
"""

import json
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from datahub.core import _norm_ohlcv  # noqa: E402
from datahub.store import LocalStore  # noqa: E402

CN_FUTURES = [  # 主力连续合约（新浪代码）
    ("RB0", "螺纹钢"), ("AU0", "沪金"), ("AG0", "沪银"), ("CU0", "沪铜"),
    ("SC0", "原油"), ("M0", "豆粕"), ("CF0", "棉花"), ("TA0", "PTA"),
    ("I0", "铁矿石"), ("JM0", "焦煤"),
]
PERPS = ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"]


def main():
    import akshare as ak
    store = LocalStore(str(ROOT / "data"))

    # ---- 国内商品期货日线 ----
    for sym, name in CN_FUTURES:
        try:
            df = ak.futures_zh_daily_sina(symbol=sym)
            if df is None or df.empty:
                print(f"  {sym} 无数据", file=sys.stderr)
                continue
            df = df.rename(columns={"settle": "amount"})
            df = _norm_ohlcv(df, "新浪期货")
            store.save_bars("期货", sym, df)
            store.set_status("期货", sym, df["date"].max().date(), "新浪期货")
            print(f"✓ {sym} {name}：{len(df)} 根")
        except Exception as e:  # noqa: BLE001
            print(f"✗ {sym}: {str(e)[:80]}", file=sys.stderr)
        time.sleep(0.3)

    # ---- 加密永续资金费率快照 ----
    funding = {}
    for inst in PERPS:
        try:
            r = requests.get("https://www.okx.com/api/v5/public/funding-rate",
                             params={"instId": inst}, timeout=15)
            r.raise_for_status()
            data = (r.json() or {}).get("data") or []
            if data:
                d = data[0]
                funding[inst] = {
                    "funding_rate": float(d.get("fundingRate", 0)) * 100,
                    "next_time": d.get("nextFundingTime", ""),
                }
        except Exception as e:  # noqa: BLE001
            print(f"✗ {inst}: {str(e)[:80]}", file=sys.stderr)
        time.sleep(0.2)
    (ROOT / "data" / "futures_funding.json").write_text(
        json.dumps({"date": str(date.today()), "funding": funding}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(f"资金费率快照：{len(funding)}/{len(PERPS)} 个合约")


if __name__ == "__main__":
    main()
