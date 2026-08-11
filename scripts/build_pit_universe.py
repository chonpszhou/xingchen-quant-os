#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 点对时股票池构建（沪深300 + 中证500 月度成分快照）

消除幸存者偏差：股票是否可交易按“当日之前最近一次指数成分快照”判定，
不再使用当前时点的固定池。

输出:
    data/a_pit_universe.parquet   (snapshot_date, index, code)
    data/a_pit_membership.parquet (date, code, index)  逐交易日成员资格
"""

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

START = "2022-06-15"
END = "2026-08-31"


def main():
    import baostock as bs
    lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"BaoStock 登录失败: {lg.error_msg}")

    # 交易日历
    rs = bs.query_trade_dates(start_date=START, end_date=END)
    days = []
    while rs.next():
        d = rs.get_row_data()
        if d[1] == "1":  # is_trading_day
            days.append(d[0])
    days = sorted(days)
    print(f"交易日 {len(days)} 天（{START}~{END}）", flush=True)

    # 每月快照日：当月 15 日之前最后一个交易日
    import datetime as dt
    months = {}
    for d in days:
        y, m = int(d[:4]), int(d[5:7])
        key = (y, m)
        if dt.date(y, m, 15).isoformat() >= d:
            months[key] = d  # 取 ≤15 日的最后一个
    snap_dates = sorted(months.values())
    print(f"月度快照 {len(snap_dates)} 个：{snap_dates[0]} ~ {snap_dates[-1]}", flush=True)

    rows = []
    for sd in snap_dates:
        for idx, fn in (("000300", "query_hs300_stocks"), ("000905", "query_zz500_stocks")):
            rs = getattr(bs, fn)(date=sd)
            if rs.error_code != "0":
                print(f"  快照失败 {sd} {idx}: {rs.error_msg}", flush=True)
                continue
            while rs.next():
                code = rs.get_row_data()[1].split(".")[-1]
                rows.append({"snapshot_date": sd, "index": idx, "code": code})
    bs.logout()

    uni = pd.DataFrame(rows).drop_duplicates(["snapshot_date", "index", "code"])
    uni["snapshot_date"] = pd.to_datetime(uni["snapshot_date"])
    uni.to_parquet(ROOT / "data" / "a_pit_universe.parquet", index=False)
    print(f"快照表：{len(uni)} 行，月度平均 {len(uni)//len(snap_dates)} 只，"
          f"去重后累计标的 {uni['code'].nunique()} 只", flush=True)

    # 逐交易日成员资格：最近一次快照（merge_asof 向量化）
    day_df = pd.DataFrame({"date": pd.to_datetime(days)})
    snap_df = pd.DataFrame({"snapshot_date": pd.to_datetime(sorted(uni["snapshot_date"].unique()))})
    day_df = pd.merge_asof(day_df, snap_df, left_on="date", right_on="snapshot_date")
    mem = day_df.merge(uni, on="snapshot_date")[["date", "code", "index"]]
    mem["date"] = mem["date"].dt.strftime("%Y-%m-%d")
    mem.to_parquet(ROOT / "data" / "a_pit_membership.parquet", index=False)
    print(f"成员资格表：{len(mem)} 行，日均 {len(mem)//len(days)} 只")


if __name__ == "__main__":
    main()
