#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""补齐 A股行业映射（东财行业板块成分 → 代码），合并进 data/a_meta.parquet"""

import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def fetch_board(name):
    import akshare as ak
    try:
        cons = ak.stock_board_industry_cons_em(symbol=name)
        return {str(c).split(".")[0]: name for c in cons["代码"]}
    except Exception:  # noqa: BLE001
        return {}


def main():
    import akshare as ak
    p = ROOT / "data" / "a_meta.parquet"
    if not p.exists():
        print("请先运行 fetch_a_meta.py")
        return
    meta = pd.read_parquet(p)
    meta["代码"] = meta["代码"].astype(str).str.split(".").str[0]
    boards = ak.stock_board_industry_name_em()["板块名称"].tolist()
    print(f"行业板块 {len(boards)} 个，并发抓取成分...")
    mapping = {}
    done = 0
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(fetch_board, b): b for b in boards}
        for fut in as_completed(futs):
            done += 1
            mapping.update(fut.result())
            if done % 20 == 0:
                print(f"  ...{done}/{len(boards)}", flush=True)
            time.sleep(0.1)
    # 只保留 a_meta 范围内的代码（先到先得）
    meta["行业"] = meta["代码"].map(mapping)
    meta.to_parquet(p, index=False)
    print(f"行业覆盖：{meta['行业'].notna().sum()} / {len(meta)} → data/a_meta.parquet")


if __name__ == "__main__":
    main()
