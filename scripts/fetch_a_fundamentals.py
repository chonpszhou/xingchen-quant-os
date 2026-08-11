#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · A股季度基本面抓取（BaoStock 盈利指标）

覆盖 308 只 A股池（沪深300+自选），2022Q4~2026Q1 共 14 个季度，
字段：roeAvg / epsTTM / npMargin / pubDate（披露日，用于无未来函数对齐）。

用法:
    python3 scripts/fetch_a_fundamentals.py
输出:
    data/a_fundamentals.parquet（code, quarter, pubDate, roeAvg, epsTTM, npMargin）
"""

import sys
import signal
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from datahub.store import LocalStore  # noqa: E402

QUARTERS = [(y, q) for y in range(2022, 2027) for q in range(1, 5)
            if (y, q) >= (2022, 4) and (y, q) <= (2026, 1)]
OUT = ROOT / "data" / "a_fundamentals.parquet"
CODE_TIMEOUT = 60  # 单只股票全部季度查询的看门狗超时（秒）


class QueryTimeout(Exception):
    pass


def _timeout_handler(signum, frame):
    raise QueryTimeout()


def bs_code(code: str) -> str:
    return ("sh." if code.startswith(("6", "9")) else "sz.") + code


def save(rows):
    """合并写入（保留历史批次），按 code+quarter 去重"""
    df = pd.DataFrame(rows)
    if OUT.exists():
        old = pd.read_parquet(OUT)
        df = pd.concat([old, df], ignore_index=True)
    df = df.drop_duplicates(subset=["code", "quarter"], keep="last")
    df.to_parquet(OUT, index=False)
    return df


def main():
    import baostock as bs
    # 优先使用点对时池（沪深300+中证500 全历史成分），否则回退到固定池
    pit = ROOT / "data" / "a_pit_universe.parquet"
    if pit.exists():
        uni = pd.read_parquet(pit)
        codes = sorted(uni["code"].astype(str).unique())
    else:
        store = LocalStore(str(ROOT / "data"))
        codes = sorted({
            st["symbol"] for _, st in store.all_status().iterrows()
            if st["market"] == "A股" and st["symbol"].startswith(
                ("600", "601", "603", "605", "688", "000", "001", "002", "003", "300", "301"))
        })

    done = set()
    if OUT.exists():
        old = pd.read_parquet(OUT)
        done = set(old["code"])
        print(f"断点续传：已有 {len(done)} 只", flush=True)

    lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"BaoStock 登录失败: {lg.error_msg}")
    print(f"登录成功，抓取 {len(codes)} 只 × {len(QUARTERS)} 季度", flush=True)

    rows, fail = [], []
    t0 = time.time()
    for i, code in enumerate(codes, 1):
        if code in done:
            continue
        def fetch_one(code_):
            out = []
            for year, quarter in QUARTERS:
                rs = bs.query_profit_data(code=bs_code(code_), year=year, quarter=quarter)
                if rs.error_code != "0":
                    continue
                while rs.next():
                    d = dict(zip(rs.fields, rs.get_row_data()))
                    out.append({
                        "code": code_, "quarter": f"{year}Q{quarter}",
                        "pubDate": d.get("pubDate", ""), "statDate": d.get("statDate", ""),
                        "roeAvg": d.get("roeAvg"), "epsTTM": d.get("epsTTM"),
                        "npMargin": d.get("npMargin"),
                    })
            return out

        signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(CODE_TIMEOUT)
        try:
            rows += fetch_one(code)
        except QueryTimeout:
            fail.append(f"{code}: 查询超时(>{CODE_TIMEOUT}s)，跳过")
        except Exception as e:  # noqa: BLE001
            fail.append(f"{code}: {type(e).__name__} {str(e)[:60]}")
        finally:
            signal.alarm(0)
        if i % 25 == 0 or i == len(codes):
            df = save(rows) if rows else pd.read_parquet(OUT) if OUT.exists() else pd.DataFrame()
            el = time.time() - t0
            print(f"...{i}/{len(codes)} 完成，累计 {len(df)} 行，用时 {el/60:.1f} 分钟，失败 {len(fail)}",
                  flush=True)
    bs.logout()

    df = save(rows) if rows else (pd.read_parquet(OUT) if OUT.exists() else pd.DataFrame())
    print(f"\n===== 完成：{len(df)} 行 → {OUT} =====")
    if fail:
        (ROOT / "data" / "a_fundamentals_errors.csv").write_text("\n".join(fail), encoding="utf-8")
        print(f"失败 {len(fail)} 条 → data/a_fundamentals_errors.csv")


if __name__ == "__main__":
    main()
