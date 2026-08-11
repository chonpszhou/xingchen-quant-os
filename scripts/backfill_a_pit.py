#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 点对时池行情回填（沪深300+中证500 全历史成分，并发 + 断点续传）

用法:
    python3 scripts/backfill_a_pit.py --lookback 1500 --workers 4
"""

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from datahub.core import _tx_fast, history_a_share  # noqa: E402
from datahub.store import LocalStore  # noqa: E402

# 预加载 akshare：避免嵌入式 V8 在子线程首次初始化崩溃
import akshare  # noqa: F401,E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--lookback", type=int, default=1500)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--force", action="store_true")
    args = p.parse_args()

    uni = __import__("pandas").read_parquet(ROOT / "data" / "a_pit_universe.parquet")
    codes = sorted(uni["code"].unique())
    print(f"点对时池累计标的 {len(codes)} 只", flush=True)

    store = LocalStore(str(ROOT / "data"))
    end = time.strftime("%Y-%m-%d")
    start = time.strftime("%Y-%m-%d", time.localtime(time.time() - args.lookback * 86400))
    stats = {"ok": 0, "skip": 0, "fail": 0, "errors": []}

    def work(code):
        try:
            s = store.incremental_start("A股", code, args.lookback, args.force)
            if s > end:
                return ("skip", code, "")
            # 线程内仅走纯 HTTP 腾讯直连（akshare 在子线程会触发 V8 崩溃）
            df = _tx_fast(code, s, end)
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
            if done % 50 == 0 or done == len(codes):
                print(f"...{done}/{len(codes)} 成功{stats['ok']} 跳过{stats['skip']} 失败{stats['fail']}", flush=True)

    print(f"\n===== 汇总：成功 {stats['ok']} / 跳过 {stats['skip']} / 失败 {stats['fail']} =====")
    if stats["errors"]:
        print(f"失败 {len(stats['errors'])} 只，开始单线程兜底（akshare 通道）...")
        for entry in stats["errors"]:
            code = entry.split(":")[0].strip()
            try:
                s = store.incremental_start("A股", code, args.lookback, args.force)
                if s > end:
                    continue
                df = history_a_share(code, s, end)
                if df is None or df.empty:
                    continue
                store.save_bars("A股", code, df)
                store.set_status("A股", code, df["date"].max().date(),
                                 df["source"].iloc[-1] if "source" in df.columns else "unknown")
                stats["ok"] += 1
            except Exception:  # noqa: BLE001
                pass
        p_out = ROOT / "data" / "backfill_pit_errors.csv"
        p_out.write_text("\n".join(stats["errors"]), encoding="utf-8")
        print(f"兜底完成，剩余失败明细已存 {p_out}")


if __name__ == "__main__":
    main()
