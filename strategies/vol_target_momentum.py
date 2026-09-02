"""波动率目标动量（M-030）：动量信号（12-1 月窗口+跳过+衰减）叠加波动率目标仓位。

对应学习报告主题「波动率目标/风险平价仓位」：固定满仓在高波动标的暴露过大，
按实现波动倒数定仓（目标年化波动 target_vol_ann），高波动期自动降仓，更稳。
纯多头：信号>0 且实现波动>0 时，权重 = min(1, target_vol_ann / 实现波动)。
逐标的过五道闸（与其他策略同纪律）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from engine.strategy import Strategy, register


@register
class VolTargetMomentumStrategy(Strategy):
    name = "vol_target_momentum"
    params = {"symbol": "", "market": "a", "window": 252, "skip": 21,
              "decay": 0.05, "target_vol_ann": 0.25}

    def on_init(self):
        self._symbol = self.params.get("symbol") or ""
        self._market = self.params.get("market") or "a"
        self._window = int(self.params.get("window", 252))
        self._skip = int(self.params.get("skip", 21))
        self._decay = float(self.params.get("decay", 0.05))
        self._tvol = float(self.params.get("target_vol_ann", 0.25))
        self._target = {}
        self._target_series = {}
        if self._symbol and self.ds is not None:
            df = self.ds.bars(self._market, self._symbol)
            if df is not None and "close" in df.columns and len(df) >= self._window + self._skip + 2:
                close = df.set_index("date")["close"].sort_index()
                logret = np.log(close / close.shift(1)).fillna(0.0).to_numpy()
                n = len(logret)
                w = np.exp(-self._decay * np.arange(self._window - 1, -1, -1))
                w = w / w.sum()
                shifted = np.zeros(n)
                shifted[self._skip:] = logret[: n - self._skip]
                sig = np.convolve(shifted, w[::-1], mode="full")[:n]
                sig_s = pd.Series(sig, index=close.index)
                vol = close.pct_change().rolling(self._skip).std() * np.sqrt(252)
                out = {}
                for dt in close.index:
                    s = sig_s.get(dt, 0.0)
                    v = vol.get(dt)
                    if s > 0 and pd.notna(v) and v > 0:
                        wt = min(1.0, self._tvol / float(v))
                        out[dt] = {self._symbol: round(float(wt), 4)}
                    else:
                        out[dt] = {}
                self._target_series = out

    def on_bar(self, symbol, bar):
        self._target = self._target_series.get(bar.datetime, {})
        return
