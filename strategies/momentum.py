"""单标的 时间序列动量（Time-Series Momentum）策略 — 动态优化版

接入新引擎接口，供研究驱动扫描 / 参数寻优逐标的五道闸门验证。
对标 paddy-quant-workbench 的 momentum_signals，并直接采纳学习报告中高频出现的
「Boundaries of Time Series Momentum」结论：朴素动量易被短期反转与过拟合拖累，
应加「12-1 月窗口 + 跳过最近 1 月 + 衰减权重」边界。

信号（单边多头，研究扫描以多头/中性标的为主）：
  - 12-1 动量 = close[t-skip] / close[t-skip-window] - 1（跳过最近 skip 日，避免短期反转）
  - 衰减加权：对窗口内每日对数收益按指数衰减加权（最近月权重最高），sum > 0 持仓
  - 默认 window=252（≈12 月）、skip=21（≈1 月）、decay=0.05（月度衰减 λ）
  - 若需多空，可把 sig 改为 ±1 再映射目标权重
被 engine.optimizer.optimize 用于「研究驱动全宇宙扫描」（每标的独立过五道闸）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from engine.strategy import Strategy, register


@register
class MomentumStrategy(Strategy):
    name = "momentum"
    params = {"symbol": "", "market": "a", "window": 252, "skip": 21, "decay": 0.05}

    def on_init(self):
        self._symbol = self.params.get("symbol") or ""
        self._market = self.params.get("market") or "a"
        self._window = int(self.params.get("window", 252))
        self._skip = int(self.params.get("skip", 21))
        self._decay = float(self.params.get("decay", 0.05))
        self._target = {}
        self._target_series: dict = {}
        if self._symbol and self.ds is not None:
            df = self.ds.bars(self._market, self._symbol)
            if df is not None and "close" in df.columns and len(df) >= self._window + self._skip + 2:
                close = df.set_index("date")["close"].sort_index()
                logret = np.log(close / close.shift(1)).fillna(0.0).to_numpy()
                n = len(logret)
                # 衰减权重：窗口内「越靠近 t-skip」权重越高（最近月权重最大）
                w = np.exp(-self._decay * np.arange(self._window - 1, -1, -1))
                w = w / w.sum()
                # shifted[t] = logret[t - skip]（把收益整体前移 skip，跳过最近 skip 日）
                shifted = np.zeros(n)
                shifted[self._skip:] = logret[: n - self._skip]
                # 卷积得到每时刻的衰减加权累计收益（跳过最近 skip 日、回看 window 日）
                sig_vals = np.convolve(shifted, w[::-1], mode="full")[:n]
                sig = pd.Series(sig_vals, index=close.index)
                self._target_series = {
                    dt: {self._symbol: 1.0} if s > 0 else {}
                    for dt, s in sig.items()
                }

    def on_bar(self, symbol, bar):
        self._target = self._target_series.get(bar.datetime, {})
        return
