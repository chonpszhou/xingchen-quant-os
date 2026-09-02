"""ML 特征工程层（轻量、可解释、零第三方 ML 依赖）。

设计取舍（与 indevs 研究笔记一致）：
- 本环境隔离、无 sklearn/xgboost/lightgbm（pip 装会污染），故用**纯 numpy/pandas**
  实现「多特征线性打分」作为轻量择时模型——可解释、可复现、可接入现有 optimizer 框架。
- 它不是黑箱 GBM，而是「特征 → 加权打分 → 阈值出信号」的透明原型。
  接 optimizer 做参数寻优前，权重应先在样本外训练（见 ml_reversal_signal 的 weights 参数）。
- 特征覆盖：多周期动量 / 波动率 / RSI / 微观结构（实体+振幅）/ 异常换手。

诚实前提：特征工程只是把信息整理好，能否产生 Alpha 仍须过五道闸门。
（单一真源：原 paddy src/engine/features.py，Phase 1 迁移至 quantos_engine.features）
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / (avg_loss + 1e-12)
    return 100 - 100 / (1 + rs)


def build_features(df: pd.DataFrame, mom_wins: tuple[int, ...] = (5, 10, 20, 60)) -> pd.DataFrame:
    """从 OHLCV 构建多周期特征矩阵。

    返回: 与 df 同索引的 DataFrame，列含多周期动量/波动率/RSI/微观结构/异常换手。
    保证零 NaN（首值 ffill 后补 0），便于直接做线性代数。
    """
    close = df["close"]
    req = {"open", "high", "low"}
    has_ohlc = req.issubset(set(df.columns))
    ret = close.pct_change()

    feats = pd.DataFrame(index=df.index)
    for w in mom_wins:
        feats[f"mom_{w}"] = ret.rolling(w).sum()  # 多周期累计收益（动量）

    feats["vol_20"] = ret.rolling(20).std()
    feats["vol_60"] = ret.rolling(60).std()
    feats["rsi_14"] = _rsi(close, 14)

    if has_ohlc:
        feats["ret_intraday"] = (close - df["open"]) / (df["open"] + 1e-12)
        feats["range_ratio"] = (df["high"] - df["low"]) / (close + 1e-12)
    if "volume" in df.columns:
        vm = df["volume"].rolling(20).mean()
        vs = df["volume"].rolling(20).std()
        feats["vol_z"] = (df["volume"] - vm) / (vs + 1e-9)
    else:
        feats["vol_z"] = 0.0

    # 首值 ffill 后补 0，确保零 NaN（线性打分才可做）
    feats = feats.ffill().fillna(0.0)
    return feats


# 默认权重：均值回归倾向（动量取负、超卖 RSI 取负→超卖做多、异常放量取负→恐慌超卖）
DEFAULT_ML_WEIGHTS: dict[str, float] = {
    "mom_5": -0.3,
    "mom_10": -0.4,
    "mom_20": -0.5,
    "mom_60": -0.3,
    "vol_20": 0.05,
    "vol_60": 0.05,
    "rsi_14": -0.7,
    "ret_intraday": -0.2,
    "range_ratio": 0.1,
    "vol_z": -0.15,
}


def ml_reversal_signal(df: pd.DataFrame, buy_thr: float = 0.5, sell_thr: float = 0.5,
                       cooldown: int = 0, weights: dict[str, float] | None = None) -> pd.Series:
    """轻量 ML 择时信号：特征线性打分 → 阈值出仓。

    参数:
        buy_thr / sell_thr: 打分阈值（>buy_thr 做多，<-sell_thr 做空）
        cooldown: 信号冷却期（K线数），从非零变零后强制空仓 cooldown 根
        weights: 特征权重（样本外训练得到）；默认启发式均值回归权重

    返回: 仓位序列 {-1, 0, 1}，与 df 同索引。
    """
    feats = build_features(df)
    w = weights or DEFAULT_ML_WEIGHTS
    score = pd.Series(0.0, index=df.index)
    for k, v in w.items():
        if k in feats.columns:
            score = score + feats[k].astype(float) * v

    sig = pd.Series(0, index=df.index)
    sig[score > buy_thr] = 1
    sig[score < -sell_thr] = -1

    if cooldown > 0:
        cd = 0
        for i in range(len(sig)):
            if cd > 0:
                sig.iloc[i] = 0
                cd -= 1
            elif i > 0 and sig.iloc[i] == 0 and sig.iloc[i - 1] != 0:
                cd = cooldown
    return sig
