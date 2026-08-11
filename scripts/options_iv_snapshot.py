#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""星辰投研团 · 期权 IV 监控快照

指数级：CBOE 官方 CSV（VIX/VXN/VXD）→ 2 年分位 + 与本地指数 ETF 实现波动率对比；
个股级：yfinance 期权链 ATM IV（限流时标注待补）。
用途：波动率择时与卖方机会的监控信号（非已验证因子）。
"""

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from datahub.store import LocalStore  # noqa: E402

SYMBOLS = ["SPY", "QQQ", "AAPL", "NVDA", "MSFT", "TSLA", "AMD", "META", "GOOGL", "AMZN"]
LOOKBACK_DAYS = 504  # 2 年实现波动率分布

INDEX_IV = [("VIX", "SPY", "标普500"), ("VXN", "QQQ", "纳指100"), ("VXD", "DIA", "道指")]


def cboe_history(idx):
    url = f"https://cdn.cboe.com/api/global/us_indices/daily_prices/{idx}_History.csv"
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    df = pd.read_csv(pd.io.common.StringIO(r.text))
    df["DATE"] = pd.to_datetime(df["DATE"], format="%m/%d/%Y")
    df = df.rename(columns={"DATE": "date", "CLOSE": "close"}).set_index("date")["close"].dropna()
    return df


def rv_series(store, symbol, window=20):
    df = store.load_bars("美股", symbol)
    if df is None or len(df) < 120:
        return None
    r = df.set_index("date")["close"].pct_change()
    rv = r.rolling(window).std() * np.sqrt(252)
    return rv.dropna()


def main():
    store = LocalStore(str(ROOT / "data"))
    lines = [
        "# 期权 IV 监控快照（美股）",
        "",
        f"> 生成时间：{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}",
        "> 指数级：CBOE 官方波动率指数（VIX/VXN/VXD）2 年分位，与对应 ETF 20 日实现波动率（本地）对比",
        "> 个股级：最近到期日（≥7 天）ATM 期权链 call/put IV 均值；yfinance 限流时标注待补",
        "> 用途：波动率择时与卖方机会监控信号（IV 分位高 → 卖方胜率环境；IV-RV 高 → 溢价厚）",
        "",
    ]

    # ---- 指数级 ----
    lines += ["## 指数级（CBOE）", "",
              "| 指数 | 对应ETF | 最新 | 2年分位 | ETF RV20 | RV分位 | IV/RV | 解读 |",
              "|------|---------|------|---------|----------|--------|-------|------|"]
    for idx, etf, label in INDEX_IV:
        try:
            iv = cboe_history(idx)
            last = float(iv.iloc[-1])
            hist = iv[iv.index >= (iv.index[-1] - pd.Timedelta(days=730))]
            pct = float((hist < last).mean())
            rv = rv_series(store, etf)
            cur_rv = float(rv.iloc[-1]) if rv is not None and len(rv) else np.nan
            rv_pct = float((rv < cur_rv).mean()) if rv is not None and len(rv) else np.nan
            iv_rv = (last / 100.0) / cur_rv if cur_rv and cur_rv > 0 else np.nan
            note = "波动率高企" if pct >= 0.8 else ("波动率低迷" if pct <= 0.2 else "波动率中性")
            if iv_rv >= 1.3:
                note += " · 期权溢价厚"
            lines.append(f"| {idx} | {etf}（{label}） | {last:.1f} | {pct:.0%} | "
                         f"{cur_rv:.1%} | {rv_pct:.0%} | {iv_rv:.2f} | {note} |")
        except Exception as e:  # noqa: BLE001
            lines.append(f"| {idx} | {etf} | 获取失败：{str(e)[:50]} | - | - | - | - | - |")

    # ---- 个股级（尽力而为） ----
    lines += ["", "## 个股级（期权链，尽力而为）", "",
              "| 标的 | 现价 | ATM IV | RV20 | RV分位 | IV/RV | 解读 |",
              "|------|------|--------|------|--------|-------|------|"]
    import yfinance as yf
    rl_streak = 0
    for sym in SYMBOLS:
        if rl_streak >= 3:
            lines.append(f"| {sym} | - | 限流待补 | - | - | - | - |")
            continue
        try:
            time.sleep(2)
            tk = yf.Ticker(sym)
            spot = tk.fast_info.last_price
            exps = [e for e in tk.options if (pd.Timestamp(e) - pd.Timestamp.now()).days >= 7]
            if not exps:
                lines.append(f"| {sym} | - | 无近期期权 | - | - | - | - |")
                continue
            chain = tk.option_chain(exps[0])
            calls, puts = chain.calls, chain.puts
            atm_c = calls.iloc[(calls["strike"] - spot).abs().idxmin()]
            atm_p = puts.iloc[(puts["strike"] - spot).abs().idxmin()]
            iv = (atm_c["impliedVolatility"] + atm_p["impliedVolatility"]) / 2
            rv = rv_series(store, sym)
            if rv is None or len(rv) < 60:
                lines.append(f"| {sym} | {spot:.2f} | {iv:.1%} | - | - | - | 本地历史不足 |")
                continue
            cur_rv = float(rv.iloc[-1])
            rv_pct = float((rv < cur_rv).mean())
            iv_rv = iv / cur_rv if cur_rv > 0 else np.nan
            note = "波动率高企" if rv_pct >= 0.8 else ("波动率低迷" if rv_pct <= 0.2 else "中性")
            if iv_rv >= 1.3:
                note += " · 溢价厚"
            lines.append(f"| {sym} | {spot:.2f} | {iv:.1%} | {cur_rv:.1%} | {rv_pct:.0%} | "
                         f"{iv_rv:.2f} | {note} |")
        except Exception as e:  # noqa: BLE001
            lines.append(f"| {sym} | - | 限流待补（{str(e)[:30]}） | - | - | - | - |")
            rl_streak += 1
            time.sleep(20)

    lines += ["", "> 本快照为监控参考，非投资建议；IV 因子尚未经回测验证。", ""]
    (ROOT / "docs" / "期权IV监控快照.md").write_text("\n".join(lines), encoding="utf-8")
    print("已输出：docs/期权IV监控快照.md")
    print("\n".join(lines[:22]))


if __name__ == "__main__":
    main()
