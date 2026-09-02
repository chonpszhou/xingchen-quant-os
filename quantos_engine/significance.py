"""统计显著性闸门 (Fifth Gate: Statistical Significance) —— PSR / DSR / 多重检验校正。

背景：双闸门（walk-forward + holdout）只是"样本外表现达标"，还不能回答
「这个夏普是运气还是统计显著」。尤其在参数寻优里，我们试了 N 个组合，
挑最好的那个——挑选本身就推高了期望最大夏普（multiple testing）。

本模块实现 Bailey & López de Prado 的两个指标：

1. PSR (Probabilistic Sharpe Ratio, 2012)
   P(真实夏普 > 基准夏普)，考虑收益的偏度/峰度与非正态性：
       PSR = Φ( (SR - SR*) / σ(SR) )
       σ(SR) = sqrt( (1 - γ3·SR + (γ4-1)/4·SR²) / (n-1) )
   其中 SR 为 per-period 夏普，γ3 偏度，γ4 普通峰度（正态=3），n 收益样本数。

2. DSR (Deflated Sharpe Ratio, 2014)
   在 PSR 基础上把基准 SR* 替换为「N 次独立试验下期望最大夏普」：
       SR0 = sqrt(V[SR]) · ( (1-γ)·Φ⁻¹(1-1/N) + γ·Φ⁻¹(1-1/(N·e)) )
   γ ≈ 0.5772 (Euler-Mascheroni)。试得越多（N 越大），SR0 越高，越难过闸。

3. Benjamini-Hochberg FDR 校正：对一组候选的 p 值控制错误发现率，
   多候选同时宣称"显著"时防滥杀。

约定：
- 输入夏普一律用 **per-period**（日频）口径；年化夏普请先 `ann_to_period()`。
- 所有函数纯计算、无状态、不依赖网络；NaN 输入返回 NaN，由调用方兜底。

—— 单一真源：原 paddy src/engine/significance.py，W1-② 迁入 quantos_engine。
"""
from __future__ import annotations

import math
from statistics import NormalDist

_ND = NormalDist()
EULER_GAMMA = 0.5772156649015329
TRADING_DAYS = 252


def ann_to_period(sharpe_annualized: float, periods: int = TRADING_DAYS) -> float:
    """年化夏普 → per-period 夏普（日频除以 √252）。"""
    return float(sharpe_annualized) / math.sqrt(periods)


def norm_cdf(x: float) -> float:
    return _ND.cdf(x)


def norm_ppf(p: float) -> float:
    return _ND.inv_cdf(p)


def sharpe_std(sr: float, n: int, skew: float = 0.0, kurt: float = 3.0) -> float:
    """夏普估计量的标准误 σ(SR)（per-period 口径）。"""
    if n < 2:
        return float("nan")
    var = 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr
    if var <= 0:
        return float("nan")
    return math.sqrt(var / (n - 1))


def psr(sharpe: float, n_returns: int,
        skew: float = 0.0, kurt: float = 3.0,
        benchmark: float = 0.0) -> float:
    """概率夏普：P(真实 per-period 夏普 > benchmark)。返回 [0,1]。

    输入均为 per-period 口径；n_returns 为收益观测数。
    样本不足或方差非法时返回 NaN。
    """
    if n_returns is None or n_returns < 2:
        return float("nan")
    if any(v is None or (isinstance(v, float) and math.isnan(v))
           for v in (sharpe, skew, kurt, benchmark)):
        return float("nan")
    sigma = sharpe_std(float(sharpe), int(n_returns), float(skew), float(kurt))
    if math.isnan(sigma) or sigma <= 0:
        return float("nan")
    return norm_cdf((float(sharpe) - float(benchmark)) / sigma)


def expected_max_sharpe(n_trials: int, var_sharpe: float) -> float:
    """N 次独立试验下的期望最大 per-period 夏普（DSR 的基准）。

    SR0 = sqrt(V[SR]) · ( (1-γ)·Φ⁻¹(1-1/N) + γ·Φ⁻¹(1-1/(N·e)) )
    n_trials<=1 或方差<=0 时返回 0（无多重惩罚）。
    """
    if n_trials is None or n_trials <= 1 or var_sharpe is None or var_sharpe <= 0:
        return 0.0
    z1 = norm_ppf(1.0 - 1.0 / n_trials)
    z2 = norm_ppf(1.0 - 1.0 / (n_trials * math.e))
    return math.sqrt(var_sharpe) * ((1.0 - EULER_GAMMA) * z1 + EULER_GAMMA * z2)


def dsr(sharpe: float, n_returns: int, n_trials: int,
        var_sharpe: float, skew: float = 0.0, kurt: float = 3.0) -> float:
    """紧缩夏普：以「N 次试验期望最大夏普」为基准的 PSR。返回 [0,1]。

    参数寻优场景下应传 n_trials=参数组合数、var_sharpe=各组合样本外夏普的方差。
    """
    if n_returns is None or n_returns < 2:
        return float("nan")
    sr0 = expected_max_sharpe(n_trials, var_sharpe)
    return psr(sharpe, n_returns, skew, kurt, benchmark=sr0)


def psr_pvalue(sharpe: float, n_returns: int,
               skew: float = 0.0, kurt: float = 3.0,
               benchmark: float = 0.0) -> float:
    """PSR 的单侧 p 值：p = 1 - PSR（越小越显著）。供 BH 校正使用。"""
    val = psr(sharpe, n_returns, skew, kurt, benchmark)
    if math.isnan(val):
        return float("nan")
    return 1.0 - val


def benjamini_hochberg(pvalues: list[float], q: float = 0.05) -> list[bool]:
    """Benjamini-Hochberg FDR 校正：返回每个原假设是否被拒绝（=显著）。

    经典两遍法：按 p 升序找满足 p_(k) <= k·q/m 的最大秩 k*，
    前 k* 个（按秩）拒绝。NaN 的 p 视为不显著（False）。
    """
    m = len(pvalues)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: (pvalues[i] if not math.isnan(pvalues[i]) else 1.0))
    k_star = 0
    for rank, idx in enumerate(order, start=1):
        p = pvalues[idx]
        if math.isnan(p):
            continue
        if p <= q * rank / m:
            k_star = rank
    rejected = [False] * m
    for rank, idx in enumerate(order, start=1):
        if rank <= k_star and not math.isnan(pvalues[idx]):
            rejected[idx] = True
    return rejected
