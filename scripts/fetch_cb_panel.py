#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · A股可转债历史面板抓取（双低策略数据）

来源：akshare bond_zh_cov_value_analysis（东财，含已退市转债历史）
清单：bond_zh_cov（1047）∪ bond_zh_cov_info_ths（954）——注意：
当前清单不含 2026 年前已退市/到期转债，回测会系统性缺失“强赎兑现”
的样本，方向偏保守，结论解读需标注此限制。

用法:
    python3 scripts/fetch_cb_panel.py
输出:
    data/cb_panel.parquet（bond, date, close, premium_pct, conv_value）
"""

import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 预加载 akshare（避免嵌入式 V8 在子线程首次初始化崩溃）
import akshare  # noqa: F401,E402

OUT = ROOT / "data" / "cb_panel.parquet"


def save(out):
    """合并写入（保留历史批次），按 bond+date 去重"""
    if OUT.exists():
        old = pd.read_parquet(OUT)
        out = pd.concat([old, out], ignore_index=True)
    out = out.drop_duplicates(subset=["bond", "date"], keep="last")
    out.to_parquet(OUT, index=False)
    return out


def universe():
    import akshare as ak
    codes = set()
    for fn in ("bond_zh_cov", "bond_zh_cov_info_ths"):
        try:
            df = getattr(ak, fn)()
            codes |= set(df["债券代码"].astype(str).str.zfill(6))
        except Exception as e:  # noqa: BLE001
            print(f"清单 {fn} 失败: {str(e)[:80]}", file=sys.stderr)
    return sorted(codes)


def main():
    import akshare as ak
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--smoke", type=int, default=0, help="仅抓取前 N 只（通道冒烟测试）")
    args = p.parse_args()
    codes = universe()
    print(f"转债清单 {len(codes)} 只", flush=True)
    if args.smoke:
        codes = codes[: args.smoke]
    done = set()
    if OUT.exists():
        done = set(pd.read_parquet(OUT, columns=["bond"])["bond"])
        print(f"断点续传：已有 {len(done)} 只", flush=True)

    lock = threading.Lock()
    rows, fail = [], []
    t0 = time.time()

    def work(code):
        try:
            df = ak.bond_zh_cov_value_analysis(symbol=code)
            if df is None or df.empty:
                return ("empty", code, None)
            df = df.rename(columns={"日期": "date", "收盘价": "close",
                                    "转股溢价率": "premium_pct", "转股价值": "conv_value"})
            df["bond"] = code
            return ("ok", code, df[["bond", "date", "close", "premium_pct", "conv_value"]])
        except Exception as e:  # noqa: BLE001
            return ("fail", code, f"{type(e).__name__} {str(e)[:60]}")

    pending = [c for c in codes if c not in done]
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(work, c): c for c in pending}
        for i, fut in enumerate(as_completed(futs), 1):
            status, code, data = fut.result()
            with lock:
                if status == "ok":
                    rows.append(data)
                elif status == "fail":
                    fail.append(f"{code}: {data}")
            if i % 50 == 0 or i == len(pending):
                with lock:
                    out = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
                if not out.empty:
                    out = save(out)
                el = time.time() - t0
                print(f"...{i}/{len(pending)} 累计 {len(out)} 行，用时 {el/60:.1f} 分，失败 {len(fail)}", flush=True)
    with lock:
        out = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    if not out.empty:
        out = save(out)
    print(f"\n===== 完成：{len(out)} 行 → {OUT} =====")
    if fail:
        (ROOT / "data" / "cb_fetch_errors.csv").write_text("\n".join(fail), encoding="utf-8")
        print(f"失败 {len(fail)} 条 → data/cb_fetch_errors.csv")


if __name__ == "__main__":
    main()
