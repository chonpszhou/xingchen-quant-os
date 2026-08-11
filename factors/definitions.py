"""因子定义（日频，t 日收盘后可得，无未来函数）"""

import pandas as pd

FACTOR_DEFS = {
    "momentum_20": "20日动量：close_t / close_{t-20} - 1",
    "momentum_60": "60日动量：close_t / close_{t-60} - 1",
    "volatility_20": "20日波动率：日收益率的20日滚动标准差",
    "reversal_5": "5日反转：-(close_t / close_{t-5} - 1)",
    "volume_anomaly": "量能异动：volume_t / 前20日均量(不含当日)",
    # 大佬信号（投机实验室公开方法，见 docs/大佬信号验证报告.md）
    "fake_breakout_20": "假突破后回落：盘中破前20日收盘高点但收盘收回失败位，现价低于失败位越多因子越大",
    "wick_rejection": "接针反转：多头接针(下影>2倍实体且收上半区)为正，空头接针为负",
    "wick_at_support": "支撑位接针：多头接针且当日低点触及前20日低点1.03倍以内",
}


def compute_factors(df: pd.DataFrame, horizons=(5, 10, 20)) -> pd.DataFrame:
    """由单标的日线计算因子与前瞻收益（t 收盘后可得 → t+h 收盘收益）"""
    df = df.sort_values("date").copy()
    close, volume = df["close"], df["volume"]
    out = pd.DataFrame(index=df.index)
    out["date"] = df["date"]
    out["momentum_20"] = close / close.shift(20) - 1
    out["momentum_60"] = close / close.shift(60) - 1
    out["volatility_20"] = close.pct_change().rolling(20).std()
    out["reversal_5"] = -(close / close.shift(5) - 1)
    vol_base = volume.shift(1).rolling(20).mean()
    out["volume_anomaly"] = volume / vol_base
    for h in horizons:
        out[f"fwd_{h}"] = close.shift(-h) / close - 1
    return out
