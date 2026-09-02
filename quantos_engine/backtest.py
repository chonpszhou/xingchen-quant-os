"""quantos_engine.backtest — 共享向量化回测/验证核（单一真源）。

合并来源（Phase 1 抽取，行为与原两处完全一致，由 Phase 0 回归测试守护收敛）：
- paddy src/engine/backtest.py：8 个信号函数 + _STRATS + _apply_stop + Backtester（成本模型已对齐 |Δw|）
- xingchen factors/backtest.py：portfolio_backtest（多资产向量化 NAV）+ metrics（DSR/PSR，per-period 夏普 + 普通峰度）
  + newey_west_t + factor_signals + factor_walk_forward（原 factors.walk_forward，重命名以避开 Backtester.walk_forward）

设计约定：
- 所有 NAV 一律用「(1 + 策略收益 - 换手幅度×成本).cumprod()」，成本按 |Δw| 比例（非二值化）。
- DSR/PSR 一律用 per-period 夏普（非年化）与「普通峰度」(normal=3；pandas .kurt() 为超额需 +3)。
- 信号严格防未来函数：t 日信号 shift(1) 后于 t+1 执行。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from .features import ml_reversal_signal  # 第八策略：轻量 ML 择时（纯 numpy 特征打分）


# —— 指标基元 ——
def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / (avg_loss + 1e-12)
    return 100.0 - 100.0 / (1.0 + rs)


def _atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(window).mean()


# —— 信号函数（统一接收 df，返回与索引等长的 -1/0/1 仓位信号）——
def sma_cross_signals(df: pd.DataFrame, fast: int = 5, slow: int = 20) -> pd.Series:
    close = df["close"]
    ma_f = close.rolling(fast).mean()
    ma_s = close.rolling(slow).mean()
    sig = pd.Series(0, index=close.index)
    sig[ma_f > ma_s] = 1
    sig[ma_f < ma_s] = -1
    return sig


def momentum_signals(df: pd.DataFrame, window: int = 20) -> pd.Series:
    close = df["close"]
    ret = close.pct_change(window)
    sig = pd.Series(0, index=close.index)
    sig[ret > 0] = 1
    sig[ret < 0] = -1
    return sig


def mean_reversion_signals(df: pd.DataFrame, window: int = 20, n_std: float = 2.0) -> pd.Series:
    close = df["close"]
    ma = close.rolling(window).mean()
    sd = close.rolling(window).std()
    z = (close - ma) / (sd + 1e-12)
    sig = pd.Series(0, index=close.index)
    sig[z < -n_std] = 1
    sig[z > n_std] = -1
    return sig


def donchian_signals(df: pd.DataFrame, window: int = 20) -> pd.Series:
    """通道突破（海龟式趋势跟踪）。突破 N 日最高/最低后持仓，直到反向突破。"""
    high, low, close = df["high"], df["low"], df["close"]
    upper = high.rolling(window).max().shift(1)   # 用 t-1 的通道，避免未来函数
    lower = low.rolling(window).min().shift(1)
    sig = pd.Series(0, index=close.index)
    sig[close > upper] = 1
    sig[close < lower] = -1
    # 突破后持仓直到反向突破（ffill 保留上一次方向）；初始未突破则为空仓
    sig = sig.replace(0, np.nan).ffill().fillna(0)
    return sig


def dual_thrust_signals(df: pd.DataFrame, k1: float = 0.5, k2: float = 0.5) -> pd.Series:
    """Dual Thrust 日内突破：以前一日波动区间构造上下触发线。"""
    open_, high, low, close = df["open"], df["high"], df["low"], df["close"]
    hh = high.shift(1)
    ll = low.shift(1)
    lc = close.shift(1)          # HC == LC，区间 = max(HH-LC, LC-LL)
    rng = (hh - lc).abs()
    buy_trigger = open_ + k1 * rng
    sell_trigger = open_ - k2 * rng
    sig = pd.Series(0, index=close.index)
    sig[close > buy_trigger] = 1
    sig[close < sell_trigger] = -1
    return sig


def rsi_reversal_signals(df: pd.DataFrame, period: int = 14,
                         oversold: float = 30.0, overbought: float = 70.0,
                         cooldown: int = 0) -> pd.Series:
    """RSI 逆向均值回归：超卖做多、超买卖空。

    参数:
        cooldown: 信号冷却期（K线数）。当信号从非零变为零后，接下来
                  cooldown 根K线强制空仓（sig=0），抑制反复开平。
                  默认 0 表示不启用冷却。
    """
    close = df["close"]
    r = _rsi(close, period)
    sig = pd.Series(0, index=close.index)
    sig[r < oversold] = 1
    sig[r > overbought] = -1
    if cooldown > 0:
        cd = 0
        for i in range(len(sig)):
            if cd > 0:
                sig.iloc[i] = 0
                cd -= 1
            elif i > 0 and sig.iloc[i] == 0 and sig.iloc[i - 1] != 0:
                cd = cooldown
    return sig


def atr_channel_signals(df: pd.DataFrame, window: int = 20, mult: float = 3.0) -> pd.Series:
    """ATR 通道突破（波动自适应趋势跟踪）：中轨±mult×ATR 构造通道。"""
    close = df["close"]
    center = close.rolling(window).mean()
    atr = _atr(df, window)
    upper = center + mult * atr
    lower = center - mult * atr
    sig = pd.Series(0, index=close.index)
    sig[close > upper] = 1
    sig[close < lower] = -1
    sig = sig.replace(0, np.nan).ffill().fillna(0)
    return sig


def ts_momentum_signals(df: pd.DataFrame, window: int = 252, skip: int = 21,
                        decay: float = 0.05) -> pd.Series:
    """时间序列动量（Time-Series Momentum, 12-1 月窗口 + 跳过 + 衰减加权）。

    对齐星辰投研团 M-105：朴素动量易被短期反转与过拟合拖累，故采用
    「12-1 月窗口 + 跳过最近 skip 日 + 指数衰减加权」边界（Boundaries of TS Momentum）。
    返回连续仓位权重（0/1）：衰减加权累计收益 > 0 时满仓多头，否则空仓。
    Backtester 会对外做 shift(1) 防未来函数，故此处用 close 截至 t 即可。
    """
    close = df["close"]
    logret = np.log(close / close.shift(1)).fillna(0.0).to_numpy()
    n = len(logret)
    w = np.exp(-decay * np.arange(window - 1, -1, -1))
    w = w / w.sum()
    shifted = np.zeros(n)
    shifted[skip:] = logret[: n - skip]
    sig = np.convolve(shifted, w[::-1], mode="full")[:n]
    sig = pd.Series(sig, index=close.index)
    return (sig > 0).astype(float)


def vol_target_momentum_signals(df: pd.DataFrame, window: int = 252, skip: int = 21,
                                decay: float = 0.05, target_vol_ann: float = 0.25) -> pd.Series:
    """波动率目标动量（M-030）：12-1 衰减动量信号叠加波动率目标仓位。

    对齐星辰投研团 vol_target_momentum：固定满仓在高波动标的暴露过大，按实现波动
    倒数定仓（目标年化波动 target_vol_ann），高波动期自动降仓，更稳。
    返回连续仓位权重（0..1）：动量>0 且实现波动>0 时，权重 = min(1, target_vol_ann/实现波动)。
    实现波动 = 日收益滚动 skip 日标准差 × √252（年化）。
    """
    close = df["close"]
    logret = np.log(close / close.shift(1)).fillna(0.0).to_numpy()
    n = len(logret)
    w = np.exp(-decay * np.arange(window - 1, -1, -1))
    w = w / w.sum()
    shifted = np.zeros(n)
    shifted[skip:] = logret[: n - skip]
    sig = pd.Series(np.convolve(shifted, w[::-1], mode="full")[:n], index=close.index)
    vol = close.pct_change().rolling(skip).std() * np.sqrt(252)
    weight = pd.Series(0.0, index=close.index)
    mask = (sig > 0) & vol.notna() & (vol > 0)
    if mask.any():
        weight[mask] = np.minimum(1.0, target_vol_ann / vol[mask].to_numpy())
    return weight


# 需要 OHLC 列的策略（缺列时给出清晰报错）
_OHLC_STRATS = {"donchian", "dual_thrust", "atr_channel"}

_STRATS = {
    "sma_cross": sma_cross_signals,
    "momentum": momentum_signals,
    "ts_momentum": ts_momentum_signals,
    "vol_target_momentum": vol_target_momentum_signals,
    "mean_reversion": mean_reversion_signals,
    "donchian": donchian_signals,
    "dual_thrust": dual_thrust_signals,
    "rsi_reversal": rsi_reversal_signals,
    "atr_channel": atr_channel_signals,
    "ml_reversal": ml_reversal_signal,
}


def _apply_stop(pos: pd.Series, close: pd.Series, stop_pct: float) -> pd.Series:
    """在仓位序列上叠加止损：持仓期间触及止损价即强制平仓，直到信号再次翻转。"""
    eff = pos.copy()
    hold = 0.0
    entry = None
    closes = close.values
    poss = pos.values
    for i in range(len(pos)):
        s = poss[i]
        price = closes[i]
        if hold == 0:
            if s != 0:
                hold = s
                entry = price
                eff.iloc[i] = s
        else:
            breached = (hold > 0 and price <= entry * (1 - stop_pct)) or \
                       (hold < 0 and price >= entry * (1 + stop_pct))
            if breached:
                hold = 0.0
                entry = None
                eff.iloc[i] = 0.0
            elif s == 0:
                hold = 0.0
                entry = None
                eff.iloc[i] = 0.0
            elif s != hold:
                hold = s
                entry = price
                eff.iloc[i] = s
            else:
                eff.iloc[i] = hold
    return eff


class Backtester:
    def __init__(self, initial_capital: float = 100000, commission: float = 0.001):
        self.cap = initial_capital
        self.comm = commission

    def run(self, df: pd.DataFrame, strategy: str = "sma_cross",
            stop_pct: float = 0.0, pos: "pd.Series | None" = None, **params):
        if strategy not in _STRATS:
            raise ValueError(f"未知策略: {strategy}, 可选 {list(_STRATS)}")
        if pos is None and strategy in _OHLC_STRATS:
            missing = [c for c in ("open", "high", "low") if c not in df.columns]
            if missing:
                raise ValueError(f"策略 {strategy} 需要 OHLC 列，缺少: {missing}（请使用含开高低收的行情）")

        if pos is None:
            raw_sig = _STRATS[strategy](df, **params)
            pos = raw_sig.shift(1).fillna(0)  # 防止未来函数
        if stop_pct and stop_pct > 0:     # 止损收紧风控（复用同一权益计算，避免双模拟口径不一致）
            pos = _apply_stop(pos, df["close"], stop_pct)

        ret = df["close"].pct_change().fillna(0)
        strat_ret = pos * ret

        # 真实成本：按换手幅度（|Δw|）比例计费，而非"有变化就扣全额"
        # 原 `trade = pos.diff().abs() > 0` 把换手幅度二值化，任何微调都扣全额佣金，
        # 低估高换手策略、虚增低换手策略净收益（AAPL 等权动量曾因此被低估 ~50%）。
        turnover = pos.diff().abs().fillna(pos.abs())
        strat_ret = strat_ret - turnover * self.comm

        equity = (1 + strat_ret).cumprod() * self.cap

        total_ret = equity.iloc[-1] / self.cap - 1
        n = len(strat_ret)
        ann_ret = (1 + total_ret) ** (252 / n) - 1 if n > 0 else 0.0
        roll_max = equity.cummax()
        dd = (equity - roll_max) / roll_max
        max_dd = float(dd.min())
        sharpe = float(np.sqrt(252) * strat_ret.mean() / (strat_ret.std() + 1e-12))
        nonzero = strat_ret[strat_ret != 0]
        win_rate = float((strat_ret > 0).sum() / (len(nonzero) + 1e-12))
        wins = strat_ret[strat_ret > 0]
        losses = -strat_ret[strat_ret < 0]
        avg_win = float(wins.mean()) if len(wins) else 0.0
        avg_loss = float(losses.mean()) if len(losses) else 0.0
        pl_ratio = float(avg_win / (avg_loss + 1e-12))

        # 高阶矩（供 PSR/DSR 统计显著性闸门使用；样本太少时为 NaN，调用方兜底）
        ret_skew = float(strat_ret.skew()) if n >= 3 else float("nan")
        ret_kurt = float(strat_ret.kurt() + 3.0) if n >= 4 else float("nan")  # 普通峰度(正态=3)

        return {
            "strategy": strategy,
            "equity": equity,
            "total_return": float(total_ret),
            "annual_return": float(ann_ret),
            "max_drawdown": max_dd,
            "sharpe": sharpe,
            "win_rate": win_rate,
            "profit_loss_ratio": pl_ratio,
            "n_trades": int((turnover > 0).sum()),
            "n_returns": int(n),
            "skew": ret_skew,
            "kurtosis": ret_kurt,
        }

    @staticmethod
    def walk_forward(df: pd.DataFrame, strategy: str = "sma_cross",
                     train_size: int = 252, test_size: int = 63,
                     step: int = 63, **params) -> list[dict]:
        """滚动窗口样本外验证（反过拟合核心）。返回每段样本外绩效。

        修正：信号在「训练+测试」完整窗口上计算后再切出测试段，避免低频/长窗口
        策略（如 252 日动量的 vol_target_momentum）在短测试折里因回看不足被 NaN
        吞掉、退化为几乎空仓的伪样本外（WF-OOS 虚高）。
        """
        results = []
        n = len(df)
        i = train_size
        while i + test_size <= n:
            test = df.iloc[i:i + test_size]
            ext = df.iloc[: i + test_size]   # 完整回看窗口
            bt = Backtester()
            try:
                raw = _STRATS[strategy](ext, **params)
                pos_full = raw.shift(1).fillna(0)
                pos_test = pos_full.iloc[i:]          # 与 test.index 对齐（已 t+1）
                r = bt.run(test, strategy=strategy, pos=pos_test, **params)
                r["window_start"] = str(test.index[0].date())
                results.append(r)
            except Exception:
                pass
            i += step
        return results


# ─────────────────────────────────────────────────────────────────────────────
# 以下为原 xingchen factors/backtest.py 的因子组合回测核（多资产向量化 NAV + DSR）
# 现并入共享包，作为「因子/组合」视角的单一真源。
# ─────────────────────────────────────────────────────────────────────────────

def newey_west_t(returns: pd.Series, lags=None):
    n = len(returns)
    if n < 3:
        return np.nan, np.nan
    e = (returns - returns.mean()).values
    if lags is None:
        lags = max(1, int(4 * (n / 100) ** (2 / 9)))
    var = e @ e / n
    for l in range(1, min(lags, n - 1) + 1):
        g = e[l:] @ e[:-l] / n
        var += 2 * (1 - l / (lags + 1)) * g
    se = np.sqrt(max(var, 1e-12) / n)
    return returns.mean() / se, se


def portfolio_backtest(close: pd.DataFrame, signals: dict, cost_rate: float,
                       risk_free=0.02) -> pd.Series:
    """signals: {date: {symbol: weight}}，t 日收盘给信号，t+1 执行；返回净值序列"""
    dates = close.index
    rets = close.pct_change().fillna(0.0)
    weights = pd.DataFrame(0.0, index=dates, columns=close.columns)
    for d, w in signals.items():
        if d in weights.index and w:
            weights.loc[d] = pd.Series(w)
    exec_w = weights.shift(1).fillna(0.0)
    port_ret = (exec_w * rets).sum(axis=1)
    turnover = (exec_w.diff().abs().fillna(exec_w.abs())).sum(axis=1)
    # 按换手幅度 |Δw| 比例计费（与 paddy Backtester 口径一致），无 /2 折半
    nav = (1 + port_ret - turnover * cost_rate).cumprod()
    return nav


def metrics(nav: pd.Series, cost_rate, n_trials=1, periods_per_year=252):
    r = nav.pct_change().dropna()
    total = nav.iloc[-1] / nav.iloc[0] - 1
    # 年化夏普用「per-period 年化」mean/std·√252，禁止对短窗口做几何
    # (1+total)^(1/n_years)-1 放大。与 paddy Backtester 的 sharpe=√252·mean/std 口径一致。
    per_sr = r.mean() / r.std() if (len(r) > 1 and r.std() > 0) else np.nan
    sharpe = per_sr * np.sqrt(periods_per_year) if not np.isnan(per_sr) else np.nan
    ann = (1 + total) ** (1 / (len(r) / periods_per_year)) - 1 if len(r) > 0 else np.nan
    vol = r.std() * np.sqrt(periods_per_year)
    t, _ = newey_west_t(r)
    dd = ((nav - nav.cummax()) / nav.cummax()).min()
    monthly = nav.resample("ME").last().pct_change().dropna()
    pf = (monthly[monthly > 0].sum() / abs(monthly[monthly < 0].sum())
          if (monthly < 0).any() else np.nan)
    # DSR（Bailey & López de Prado）：基准须用 per-period 夏普（非年化），
    # 峰度用「普通峰度」(normal=3；pandas .kurt() 为超额峰度需 +3)，与
    # paddy significance.py 口径一致。n_trials=1 时退化为 PSR（无多重检验惩罚）。
    skew = r.skew() if len(r) > 3 else 0.0
    kurt = (r.kurt() + 3.0) if len(r) > 3 else 3.0   # 普通峰度（非超额）
    sr_std = (np.sqrt((1 - skew * per_sr + (kurt - 1) / 4 * per_sr ** 2) / (len(r) - 1))
              if (not np.isnan(per_sr) and len(r) > 1) else np.nan)
    euler = 0.5772156649
    emax = stats.norm.ppf(1 - 1 / n_trials) * (1 - euler) + euler * stats.norm.ppf(1 - 1 / (n_trials * np.e))
    dsr = float(stats.norm.cdf((per_sr - emax) / sr_std)) if (sr_std and sr_std > 0 and not np.isnan(per_sr)) else np.nan
    return {
        "total_return": round(total, 4), "annual_return": round(ann, 4),
        "sharpe": round(float(sharpe), 3) if not np.isnan(sharpe) else np.nan,
        "hac_t": round(t, 2),
        "max_drawdown": round(dd, 4), "calmar": round(ann / abs(dd), 2) if dd < 0 else np.nan,
        "monthly_wr": round(float((monthly > 0).mean()), 3), "profit_factor": round(pf, 3),
        "dsr": round(dsr, 3) if not np.isnan(dsr) else np.nan, "n_days": len(r),
    }


def factor_signals(close: pd.DataFrame, factor: pd.DataFrame, direction=1,
                   top_pct=0.2, rebalance_days=20, min_obs=8, limit_up_filter=False,
                   liquidity=None, liquidity_floor_pct=0.1):
    """每 rebalance_days 生成 top/bottom 组合等权信号（t 收盘，t+1 执行）"""
    rets = close.pct_change()
    signals = {}
    dates = close.index
    for i, d in enumerate(dates):
        if i % rebalance_days != 0:
            continue
        f = factor.loc[d].dropna()
        if len(f) < min_obs:
            continue
        if liquidity is not None and d in liquidity.index:
            floor = liquidity.loc[d].quantile(liquidity_floor_pct)
            f = f[liquidity.loc[d].reindex(f.index).fillna(0) > floor]
            if len(f) < min_obs:
                continue
        if limit_up_filter and d in rets.index:
            limit_up = rets.loc[d] > 0.095
            f = f[~limit_up]
            if len(f) < min_obs:
                continue
        n = max(1, int(len(f) * top_pct))
        top = f.nlargest(n) if direction == 1 else f.nsmallest(n)
        signals[d] = (top / top.sum()).to_dict()
    return signals


def factor_walk_forward(close, factor, direction, top_pct, cost_rate, rebalance_days=20,
                        train_size=252, test_size=63, embargo=5, n_trials=1,
                        liquidity=None, liquidity_floor_pct=0.1, limit_up_filter=False):
    """滚动 walk-forward：每折在 train 内回测(IS)，在 test 内回测(OOS)，汇总 OOS。

    （原名 factors.walk_forward；因与 Backtester.walk_forward 同名易混，迁入共享包后改名 factor_walk_forward，
     factors/backtest.py 垫片仍以 walk_forward 名义 re-export，调用方零改动。）
    """
    dates = close.index
    folds, oos_parts, is_stats = [], [], []
    start = train_size
    while start + test_size <= len(dates):
        tr = dates[start - train_size: start]
        te = dates[start + embargo: start + test_size]
        if len(te) < 10:
            break
        liq_tr = liquidity.loc[tr] if liquidity is not None else None
        liq_te = liquidity.loc[te] if liquidity is not None else None
        sig_tr = factor_signals(close.loc[tr], factor.loc[tr], direction, top_pct, rebalance_days,
                                liquidity=liq_tr, liquidity_floor_pct=liquidity_floor_pct,
                                limit_up_filter=limit_up_filter)
        sig_te = factor_signals(close.loc[te], factor.loc[te], direction, top_pct, rebalance_days,
                                liquidity=liq_te, liquidity_floor_pct=liquidity_floor_pct,
                                limit_up_filter=limit_up_filter)
        nav_is = portfolio_backtest(close.loc[tr], sig_tr, cost_rate)
        nav_oos = portfolio_backtest(close.loc[te], sig_te, cost_rate)
        is_stats.append(metrics(nav_is, cost_rate))
        oos_parts.append(nav_oos)
        folds.append({"train": str(tr[0].date()), "train_end": str(tr[-1].date()),
                      "oos_start": str(te[0].date()), "oos_end": str(te[-1].date()),
                      "is_sharpe": is_stats[-1]["sharpe"], "oos_sharpe": metrics(nav_oos, cost_rate)["sharpe"]})
        start += test_size
    oos_nav = pd.concat(oos_parts) if oos_parts else None
    oos_nav = oos_nav[~oos_nav.index.duplicated(keep="last")].sort_index()
    full_sig = factor_signals(close, factor, direction, top_pct, rebalance_days,
                              liquidity=liquidity, liquidity_floor_pct=liquidity_floor_pct,
                              limit_up_filter=limit_up_filter)
    full_nav = portfolio_backtest(close, full_sig, cost_rate)
    return {
        "folds": pd.DataFrame(folds),
        "oos_nav": oos_nav, "full_nav": full_nav,
        "full_metrics": metrics(full_nav, cost_rate, n_trials),
        "oos_metrics": metrics(oos_nav, cost_rate, n_trials) if oos_nav is not None and len(oos_nav) > 2 else None,
        "is_avg_sharpe": float(pd.Series([f["is_sharpe"] for f in folds]).mean()) if folds else np.nan,
    }
