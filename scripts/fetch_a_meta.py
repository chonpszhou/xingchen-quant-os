#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · A股行业/市值元数据（用于因子中性化）

范围：自选股A股 + 沪深300成分（去重），逐只经东财单股接口取
      总市值(f116)/流通市值(f117)/行业(f127)，单请求稳定、可并发。

用法:
    python3 scripts/fetch_a_meta.py

输出:
    data/a_meta.parquet
"""

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


def em_get(path, params, hosts=("push2.eastmoney.com", "82.push2.eastmoney.com"), timeout=12):
    last = None
    for host in hosts:
        try:
            r = requests.get(f"https://{host}{path}", params=params, timeout=timeout, headers=UA)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            last = e
    raise last


def secid(code):
    code = str(code).split(".")[0]
    return ("1." if code.startswith(("6", "5", "9")) else "0.") + code


def fetch_one(code):
    code = str(code).split(".")[0]
    for _ in range(3):
        try:
            d = em_get("/api/qt/stock/get", {
                "secid": secid(code), "fltt": "2", "invt": "2",
                "fields": "f43,f57,f58,f116,f117,f127",
            })
            data = d.get("data") or {}
            if data.get("f43") is None:
                raise RuntimeError("空")
            return {"代码": code, "名称": data.get("f58"), "总市值": data.get("f116"),
                    "流通市值": data.get("f117"), "行业": data.get("f127")}
        except Exception as e:  # noqa: BLE001
            if _ == 2:
                return {"代码": code, "名称": None, "总市值": None, "流通市值": None, "行业": None, "error": str(e)[:60]}
            time.sleep(0.5)


def load_codes():
    codes = set()
    wl = json.loads((ROOT / "config/watchlist.json").read_text(encoding="utf-8"))
    for r in wl["records"]:
        if r["market"] == "A股" or (r["market"] == "期权" and r["symbol"].isdigit()):
            codes.add(r["symbol"])
    try:
        import akshare as ak
        df = ak.index_stock_cons_csindex(symbol="000300")
        codes |= {str(c).split(".")[0] for c in df["成分券代码"]}
    except Exception as e:  # noqa: BLE001
        print("沪深300成分加载失败（仅用自选股）:", str(e)[:80])
    return sorted(codes)


def main():
    codes = load_codes()
    print(f"标的 {len(codes)} 只，开始并发抓取市值/行业...")
    rows = []
    done = 0
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(fetch_one, c): c for c in codes}
        for fut in as_completed(futs):
            done += 1
            rows.append(fut.result())
            if done % 50 == 0:
                print(f"  ...{done}/{len(codes)}", flush=True)
    meta = pd.DataFrame(rows)
    meta.to_parquet(ROOT / "data" / "a_meta.parquet", index=False)
    print(f"已保存 data/a_meta.parquet：{len(meta)} 只，行业覆盖 {meta['行业'].notna().sum()} 只")


if __name__ == "__main__":
    main()
