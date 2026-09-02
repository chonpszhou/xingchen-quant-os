"""横截面因子工具（M-938 横截面因子 / M-937 横截面 ML 因子 / M-042 组合层 共用）

提供：
  - build_panel：从 DataService 取同市场多标的收盘价宽表（按数据可用性过滤）
  - cs_zscore / in_top_quantile：横截面打分与分位筛选
  - walk_forward_ml_scores：无 sklearn 依赖的逐期再训练线性回归（对标 ML-powered
    cross-sectional return prediction），预测每标的下期收益打分，供「截面排序多头」使用

全部为纯 numpy/pandas 实现，无外部 ML 依赖；严格 t→t+1 信号、训练只用历史，无前视。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# 各市场流动性 peer 宇宙（store 格式；运行时按数据可用性过滤，保证面板非空）
PEER_UNIVERSE = {
    "虚拟货币": ["BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "ADA/USDT",
                 "DOGE/USDT", "AVAX/USDT", "DOT/USDT", "LINK/USDT", "LTC/USDT",
                 "ATOM/USDT", "POL/USDT", "SHIB/USDT"],
    "美股": ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AVGO",
             "AMD", "PEP", "KO", "JNJ", "XOM", "JPM", "V"],
    "A股": ["600519", "600036", "000858", "000333", "601318", "300750", "002594",
            "600900", "600276", "000001", "600030", "601888", "600309", "603288",
            "000651", "601012", "000725", "600028", "601398"],
    "港股": ["00700", "09988", "03690", "00939", "00388", "02318", "00941",
             "09618", "09868", "01810"],
}


def build_panel(ds, market: str, symbol: str, min_rows: int = 252) -> pd.DataFrame:
    """取 symbol 所在市场的 peer 面板（收盘价宽表，index=date，columns=peers）。"""
    peers = list(dict.fromkeys([symbol] + PEER_UNIVERSE.get(market, [])))
    panel = ds.closes(market, peers)
    if panel is None or panel.empty:
        return pd.DataFrame()
    keep = [c for c in panel.columns if panel[c].notna().sum() >= min_rows]
    return panel[keep]


def cs_zscore(frame: pd.DataFrame) -> pd.DataFrame:
    """逐行（横截面）z-score。"""
    mu = frame.mean(axis=1)
    sd = frame.std(axis=1).replace(0, np.nan)
    return frame.sub(mu, axis=0).div(sd)


def in_top_quantile(frame: pd.DataFrame, col: str, top_q: float = 0.3) -> pd.Series:
    """每日期末：col 列的值是否处于该行横截面的前 top_q 分位（bool Series）。"""
    thr = frame.quantile(1 - top_q, axis=1)
    return frame[col] >= thr


def walk_forward_ml_scores(panel: pd.DataFrame, refit: int = 63, fwd: int = 21,
                           warmup: int = 504) -> pd.DataFrame:
    """截面 ML 因子打分（无 sklearn）：周期性再训练线性回归预测下期收益。

    特征（每标的每期）：mom1/mom3/mom6/mom12（21/63/126/252 日动量）、
    vol（63 日波动）、rev（5 日短期反转）。标签：未来 fwd 日收益。
    训练只用历史（date <= 当前再训练点 - fwd），预测当前及之后 refit 期的截面打分。
    返回与 panel 同形的打分 DataFrame（行=date，列=peer）。
    """
    rets = panel.pct_change()
    dates = panel.index
    n, p = panel.shape
    feat_names = ["mom1", "mom3", "mom6", "mom12", "vol", "rev"]
    F = np.full((n, p, len(feat_names)), np.nan)
    for k, name in enumerate(feat_names):
        if name == "mom1":
            v = (panel / panel.shift(21) - 1.0).values
        elif name == "mom3":
            v = (panel / panel.shift(63) - 1.0).values
        elif name == "mom6":
            v = (panel / panel.shift(126) - 1.0).values
        elif name == "mom12":
            v = (panel / panel.shift(252) - 1.0).values
        elif name == "vol":
            v = rets.rolling(63).std().values
        else:  # rev
            v = rets.rolling(5).sum().values
        F[:, :, k] = v
    L = (panel.shift(-fwd) / panel - 1.0).values  # 标签：未来 fwd 日收益
    scores = np.full((n, p), np.nan)
    last_beta = None
    t = warmup
    while t < n:
        ti = t - fwd
        if ti > warmup + 50:
            Xtr, ytr = [], []
            for s in range(warmup, ti):
                fv = F[s]
                lv = L[s]
                m = ~np.isnan(fv).any(axis=1) & ~np.isnan(lv)
                if m.sum() >= 5:
                    Xtr.append(fv[m])
                    ytr.append(lv[m])
            if Xtr:
                Xtr = np.vstack(Xtr)
                ytr = np.concatenate(ytr)
                Xa = np.hstack([np.ones((len(Xtr), 1)), Xtr])
                beta, *_ = np.linalg.lstsq(Xa, ytr, rcond=None)
                last_beta = beta
        if last_beta is not None:
            for s in range(t, min(t + refit, n)):
                fv = F[s]
                m = ~np.isnan(fv).any(axis=1)
                if m.sum() >= 1:
                    Xa = np.hstack([np.ones((m.sum(), 1)), fv[m]])
                    scores[s, m] = Xa @ last_beta
        t += refit
    return pd.DataFrame(scores, index=dates, columns=panel.columns)
