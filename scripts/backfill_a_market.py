#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · A股批量回填（指数成分 / 全市场，并发 + 断点续传）

用法:
    python3 scripts/backfill_a_market.py --index 000300 --lookback 730 --workers 4
    python3 scripts/backfill_a_market.py --full --lookback 730 --workers 4
"""

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from datahub.core import history_a_share  # noqa: E402
from datahub.store import LocalStore  # noqa: E402


def normalize(code):
    return str(code).split(".")[0].strip()


def load_universe(index_code=None, full=False):
    import akshare as ak
    if index_code:
        df = ak.index_stock_cons_csindex(symbol=index_code)
        return [normalize(c) for c in df["成分券代码"]]
    if full:
        df = ak.stock_zh_a_spot_em()
        return [normalize(c) for c in df["代码"]]
    raise ValueError("需要 --index 或 --full")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--index", help="指数代码，如 000300")
    p.add_argument("--full", action="store_true", help="全市场")
    p.add_argument("--lookback", type=int, default=730)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--force", action="store_true")
    args = p.parse_args()

    print("加载股票池...")
    codes = load_universe(args.index, args.full)
    print(f"股票池 {len(codes)} 只")
    store = LocalStore(str(ROOT / "data"))
    end = time.strftime("%Y-%m-%d")
    start = (time.strftime("%Y-%m-%d", time.localtime(time.time() - args.lookback * 86400)))
    stats = {"ok": 0, "skip": 0, "fail": 0, "errors": []}

    def work(code):
        try:
            s = store.incremental_start("A股", code, args.lookback, args.force)
            if s > end:
                return ("skip", code, "")
            df = history_a_share(code, s, end)
            if df is None or df.empty:
                return ("skip", code, "")
            store.save_bars("A股", code, df)
            store.set_status("A股", code, df["date"].max().date(),
                             df["source"].iloc[-1] if "source" in df.columns else "unknown")
            return ("ok", code, f"{len(df)}")
        except Exception as e:  # noqa: BLE001
            return ("fail", code, f"{type(e).__name__}: {str(e)[:80]}")

    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(work, c): c for c in codes}
        for fut in as_completed(futs):
            done += 1
            status, code, msg = fut.result()
            stats[status] += 1
            if status == "fail":
                stats["errors"].append(f"{code}: {msg}")
            if done % 25 == 0 or done == len(codes):
                print(f"...{done}/{len(codes)} 成功{stats['ok']} 跳过{stats['skip']} 失败{stats['fail']}", flush=True)

    print(f"\n===== 汇总：成功 {stats['ok']} / 跳过 {stats['skip']} / 失败 {stats['fail']} =====")
    if stats["errors"]:
        (ROOT / "data" / "backfill_errors.csv").write_text("\n".join(stats["errors"]), encoding="utf-8")
        print("失败明细已存 data/backfill_errors.csv")


if __name__ == "__main__":
    main()
