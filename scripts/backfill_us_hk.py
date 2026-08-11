#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 美股/港股扩池回填（并发 + 断点续传）

用法:
    python3 scripts/backfill_us_hk.py --market US --lookback 1100 --workers 6
    python3 scripts/backfill_us_hk.py --market HK --lookback 1100 --workers 6

股票池为静态清单（跨行业大中盘，见 US_UNIVERSE / HK_UNIVERSE），
历史约 3 年（1100 自然日），够 walk-forward 复核低波/动量因子。
"""

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from datahub.core import history_hk, history_us  # noqa: E402
from datahub.store import LocalStore  # noqa: E402

# 预加载 akshare：其依赖的嵌入式 V8（py_mini_racer）不能在子线程首次初始化，
# 必须在主线程导入一次，子线程仅复用模块（否则 macOS 上直接崩溃）
import akshare  # noqa: F401,E402

US_UNIVERSE = [
    # 科技/半导体/通信
    "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "AMD", "NFLX", "TSLA",
    "AVGO", "ORCL", "CRM", "ADBE", "INTC", "CSCO", "QCOM", "MU", "IBM", "TSM", "ARM",
    # 金融
    "JPM", "BAC", "GS", "MS", "V", "MA", "WFC", "C", "BLK", "AXP",
    # 医疗
    "JNJ", "PFE", "UNH", "MRK", "ABBV", "LLY", "TMO", "AMGN",
    # 能源/工业
    "XOM", "CVX", "CAT", "BA", "GE", "HON", "UPS", "MMM",
    # 消费
    "WMT", "PG", "KO", "MCD", "DIS", "NKE", "HD", "COST", "SBUX", "PEP",
    # 跨资产 CTA 篮子（商品/债券/美元）
    "GLD", "TLT", "UUP", "DBC",
]

HK_UNIVERSE = [
    "00001", "00002", "00003", "00005", "00011", "00016", "00017", "00027",
    "00066", "00175", "00267", "00288", "00316", "00322", "00386", "00388",
    "00688", "00700", "00762", "00823", "00857", "00868", "00883", "00914",
    "00939", "00941", "00981", "00992", "01024", "01038", "01088", "01093",
    "01113", "01177", "01211", "01299", "01810", "01876", "01928", "01929",
    "02015", "02020", "02269", "02318", "02331", "02382", "02601", "02628",
    "02800", "02822", "02888", "03033", "03328", "03690", "03968", "03988",
    "06060", "06618", "06862", "09618", "09633", "09888", "09901", "09961",
    "09988", "09999",
]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--market", required=True, choices=["US", "HK"])
    p.add_argument("--lookback", type=int, default=1100)
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--force", action="store_true")
    args = p.parse_args()

    market = "美股" if args.market == "US" else "港股"
    universe = US_UNIVERSE if args.market == "US" else HK_UNIVERSE
    fetch = history_us if args.market == "US" else history_hk
    print(f"股票池 {len(universe)} 只（{market}）")

    store = LocalStore(str(ROOT / "data"))
    end = time.strftime("%Y-%m-%d")
    start = time.strftime("%Y-%m-%d", time.localtime(time.time() - args.lookback * 86400))
    stats = {"ok": 0, "skip": 0, "fail": 0, "errors": []}

    def work(code):
        try:
            s = store.incremental_start(market, code, args.lookback, args.force)
            if s > end:
                return ("skip", code, "")
            df = fetch(code, s, end)
            if df is None or df.empty:
                return ("skip", code, "")
            store.save_bars(market, code, df)
            store.set_status(market, code, df["date"].max().date(),
                             df["source"].iloc[-1] if "source" in df.columns else "unknown")
            return ("ok", code, f"{len(df)}")
        except Exception as e:  # noqa: BLE001
            return ("fail", code, f"{type(e).__name__}: {str(e)[:100]}")

    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(work, c): c for c in universe}
        for fut in as_completed(futs):
            done += 1
            status, code, msg = fut.result()
            stats[status] += 1
            if status == "fail":
                stats["errors"].append(f"{code}: {msg}")
            if done % 10 == 0 or done == len(universe):
                print(f"...{done}/{len(universe)} 成功{stats['ok']} 跳过{stats['skip']} 失败{stats['fail']}", flush=True)

    print(f"\n===== 汇总：成功 {stats['ok']} / 跳过 {stats['skip']} / 失败 {stats['fail']} =====")
    if stats["errors"]:
        p = ROOT / "data" / f"backfill_{args.market}_errors.csv"
        p.write_text("\n".join(stats["errors"]), encoding="utf-8")
        print(f"失败明细已存 {p}")


if __name__ == "__main__":
    main()
