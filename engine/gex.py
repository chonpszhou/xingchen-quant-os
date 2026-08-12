"""美股期权 Gamma Exposure (GEX) 估算。

基于 yfinance 期权链 + Black-Scholes gamma 近似计算每个行权价的 GEX,
推导 Call Wall / Put Wall / Zero Gamma。

注意: 这是估算值, 非交易所官方数据, 仅作辅助参考。
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import yfinance as yf


def _bs_gamma(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black-Scholes gamma。"""
    if T <= 0 or sigma <= 0 or S <= 0:
        return 0.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    return math.exp(-0.5 * d1**2) / (S * sigma * math.sqrt(T) * math.sqrt(2 * math.pi))


def compute_gex(symbol: str, r: float = 0.05) -> dict | None:
    """计算某美股的 GEX 结构。

    Returns:
        dict: { underlying, expiry, call_wall, put_wall, zero_gamma, gex_by_strike }
        失败返回 None
    """
    tk = yf.Ticker(symbol)
    try:
        expirations = tk.options
        if not expirations:
            return None
        chain = tk.option_chain(expirations[0])
    except Exception:
        return None

    calls = chain.calls
    puts = chain.puts

    try:
        hist = tk.history(period="5d", interval="1d", auto_adjust=True)
        if hist is None or hist.empty:
            return None
        S = float(hist["Close"].iloc[-1])
    except Exception:
        return None

    T = 1 / 12  # 近似: 取最近到期 (~1 个月)

    def gex_rows(df: pd.DataFrame, is_call: bool):
        rows = []
        for _, row in df.iterrows():
            K = row["strike"]
            oi = row.get("openInterest", 0) or 0
            iv = row.get("impliedVolatility", 0) or 0
            if oi <= 0:
                continue
            sigma = iv if iv > 0 else 0.3
            g = _bs_gamma(S, K, T, r, sigma)
            contrib = g * oi * 100 * S * (1 if is_call else -1)
            rows.append((K, contrib, oi))
        return rows

    all_rows = gex_rows(calls, True) + gex_rows(puts, False)
    if not all_rows:
        return None

    gex_df = pd.DataFrame(all_rows, columns=["strike", "gex", "oi"])
    gex_df = gex_df.groupby("strike", as_index=False).sum().sort_values("strike")

    # 从高 strike 向低 strike 累计 GEX
    rev = gex_df["gex"].iloc[::-1].cumsum().iloc[::-1]
    gex_df["cum_gex"] = rev.values

    zero_gamma = None
    prev = None
    for _, row in gex_df.iterrows():
        if prev is not None and prev >= 0 and row["cum_gex"] < 0:
            zero_gamma = float(row["strike"])
            break
        prev = row["cum_gex"]

    call_wall = None
    put_wall = None
    if not calls.empty and calls["openInterest"].notna().any():
        call_wall = float(calls.loc[calls["openInterest"].idxmax(), "strike"])
    if not puts.empty and puts["openInterest"].notna().any():
        put_wall = float(puts.loc[puts["openInterest"].idxmax(), "strike"])

    return {
        "underlying": S,
        "expiry": expirations[0],
        "call_wall": call_wall,
        "put_wall": put_wall,
        "zero_gamma": zero_gamma,
        "gex_by_strike": gex_df,
    }
