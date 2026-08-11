"""大佬信号因子（来自投机实验室等公开交易方法，日频，t 收盘后可得，无未来函数）

实现两条可回测规则：
1) fake_breakout_20  假突破后回落：价格盘中突破前 20 日收盘高点但收盘收回失败位
                      之后持续处于失败位下方 → 均值回归候选（direction=+1）
2) wick_rejection    接针反转：长下影且收在上半区（多头接针）为 +，反之长上影为 -
                      传统 Pin Bar 规则：影线 > 2 倍实体
3) wick_at_support   支撑位接针：多头接针同时触及前 20 日低点附近（供需区承接）
"""

from __future__ import annotations

import numpy as np
import pandas as pd

MASTER_DEFS = {
    "fake_breakout_20": ("假突破后回落：盘中破前20日收盘高点但收盘收回失败位，"
                         "现价低于失败位越多因子越大（5日内事件窗口）"),
    "wick_rejection": ("接针反转：多头接针(下影>2倍实体且收上半区)为正，"
                       "空头接针(上影>2倍实体且收下半区)为负"),
    "wick_at_support": ("支撑位接针：多头接针且当日低点触及前20日低点1.03倍以内"
                        "（供需区承接，非全样本接针）"),
    "wick_at_support_v2": ("支撑位接针·量能确认：多头接针 + 触及前20日低点1.03倍以内 + "
                           "收盘守住支撑 + 当日量能>20日均量1.2倍（供需区+吸筹确认）"),
    "fake_breakout_pullback": ("假突破后回踩支撑：近5日内假突破事件 + 现价回踩至前20日低点上方"
                               "1.06倍以内且未破位（假突破后的延续再入场）"),
}


def master_factors(high: pd.DataFrame, low: pd.DataFrame,
                   close: pd.DataFrame, open_: pd.DataFrame,
                   volume: pd.DataFrame | None = None) -> dict[str, pd.DataFrame]:
    """输入为宽表（index=date, columns=symbol），返回各因子宽表"""
    high, low, close, open_ = (x.sort_index(axis=0) for x in (high, low, close, open_))

    # ---- 1. 假突破后回落 ----
    hh_prev = close.shift(1).rolling(20).max()          # t-1 收盘视角的前20日高点
    breakout_fail = ((high > hh_prev) & (close <= hh_prev)).astype(float)
    any_fail = breakout_fail.rolling(5, min_periods=1).max()          # 近5日内发生假突破
    level = hh_prev.rolling(5, min_periods=1).max()                   # 事件窗口内的失败位
    fake_breakout_20 = (level - close) / level
    fake_breakout_20 = fake_breakout_20.where(any_fail > 0, 0.0)

    # ---- 2. 接针反转 ----
    body = (close - open_).abs()
    rng = (high - low).replace(0, np.nan)
    lower_wick = np.minimum(open_, close) - low
    upper_wick = high - np.maximum(open_, close)
    bull_pin = ((lower_wick > 2 * body) & (close >= 0.5 * (high + low)))
    bear_pin = ((upper_wick > 2 * body) & (close <= 0.5 * (high + low)))
    wick_rejection = (lower_wick / rng).where(bull_pin, 0.0) - (upper_wick / rng).where(bear_pin, 0.0)

    # ---- 3. 支撑位接针（供需区承接） ----
    ll_prev = low.shift(1).rolling(20).min()
    at_support = low <= ll_prev * 1.03
    wick_at_support = (lower_wick / rng).where(bull_pin & at_support, 0.0)
    # v2：+ 收盘守住支撑 + 量能确认（吸筹）
    wick_at_support_v2 = wick_at_support.copy()
    if volume is not None:
        vol_confirm = volume / volume.shift(1).rolling(20).mean()
        holds = close >= ll_prev
        wick_at_support_v2 = (lower_wick / rng).where(
            bull_pin & at_support & holds & (vol_confirm > 1.2), 0.0)

    # ---- 4. 假突破后回踩支撑（延续再入场） ----
    near_support = (close >= ll_prev) & (close <= ll_prev * 1.06)
    fake_breakout_pullback = ((close - ll_prev) / ll_prev).where(
        (any_fail > 0) & near_support, 0.0)

    return {
        "fake_breakout_20": fake_breakout_20,
        "wick_rejection": wick_rejection,
        "wick_at_support": wick_at_support,
        "wick_at_support_v2": wick_at_support_v2,
        "fake_breakout_pullback": fake_breakout_pullback,
    }
