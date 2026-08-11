#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""点对时池行业映射补全（BaoStock 证监会行业），输出 data/a_pit_industry.parquet"""

import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUT = ROOT / "data" / "a_pit_industry.parquet"


def main():
    import baostock as bs
    uni = pd.read_parquet(ROOT / "data" / "a_pit_universe.parquet")
    codes = sorted(uni["code"].unique())
    done = set()
    if OUT.exists():
        done = set(pd.read_parquet(OUT)["code"])
    bs.login()
    rows, fail = [], []
    for i, code in enumerate(codes, 1):
        if code in done:
            continue
        try:
            rs = bs.query_stock_industry(code=("sh." if code.startswith("6") else "sz.") + code)
            while rs.next():
                d = dict(zip(rs.fields, rs.get_row_data()))
                rows.append({"code": code, "industry": d.get("industry"),
                             "classification": d.get("industryClassification")})
        except Exception as e:  # noqa: BLE001
            fail.append(f"{code}: {type(e).__name__} {str(e)[:60]}")
        if i % 200 == 0:
            df = pd.DataFrame(rows)
            if not df.empty:
                df.to_parquet(OUT, index=False)
            print(f"...{i}/{len(codes)} 累计 {len(df)} 行", flush=True)
    bs.logout()
    df = pd.DataFrame(rows)
    if not df.empty:
        df.to_parquet(OUT, index=False)
    print(f"完成：{len(df)} 行；失败 {len(fail)}")
    if fail:
        (ROOT / "data" / "a_pit_industry_errors.csv").write_text("\n".join(fail), encoding="utf-8")


if __name__ == "__main__":
    main()
