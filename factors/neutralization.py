"""因子中性化：行业去均值 + log(规模代理) 回归残差（截面，逐日）

规模代理使用本地数据：20 日均成交额 = 20日均量 × 收盘（时间可变，无时点偏差）。
行业使用 BaoStock 证监会行业映射（免费稳定，替代被限流的东财接口）。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def load_a_industry(data_dir="data"):
    p = Path(data_dir) / "a_industry.parquet"
    if not p.exists():
        return None
    df = pd.read_parquet(p)
    code = df["code"].astype(str).str.split(".").str[-1]
    return df.groupby(code)["industry"].first()


def size_proxy(close: pd.DataFrame, volume: pd.DataFrame, window=20):
    """时间可变规模代理：20日均成交额（量×收盘）"""
    return (volume * close).rolling(window).mean()


def neutralize(factor_wide: pd.DataFrame, size_wide: pd.DataFrame, industry: pd.Series | None,
                min_obs=8) -> pd.DataFrame:
    """逐日：因子先按行业去均值（等价行业哑变量中心化），再对 log(规模代理) 回归取残差"""
    res = pd.DataFrame(index=factor_wide.index, columns=factor_wide.columns, dtype=float)
    for d in factor_wide.index:
        f = factor_wide.loc[d].dropna()
        if len(f) < min_obs:
            continue
        sz = size_wide.loc[d].reindex(f.index) if size_wide is not None else pd.Series(1.0, index=f.index)
        valid = f.notna() & sz.notna()
        if valid.sum() < min_obs:
            continue
        fv, szv = f[valid], sz[valid]
        if industry is not None:
            indv = industry.reindex(fv.index)
            ok = indv.notna()
            if ok.sum() >= min_obs:
                fv, szv, indv = fv[ok], szv[ok], indv[ok]
                y = (fv - indv.map(fv.groupby(indv).mean())).values
            else:
                y = fv.values
        else:
            y = fv.values
        x = np.log(szv).values
        x = x - x.mean()
        b = np.dot(x, y) / np.dot(x, x) if np.dot(x, x) > 0 else 0.0
        res.loc[d, fv.index] = y - b * x
    return res
