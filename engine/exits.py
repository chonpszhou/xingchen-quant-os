"""止盈止损退出规则引擎（含 paddy-quant-workbench 合并的 ATR/保本移动）

规则（config/exits.yaml 逐策略配置）：
  - stop_loss     固定止损：价格 ≤ 成本 × (1 - pct)
  - take_profit   固定止盈：价格 ≥ 成本 × (1 + pct)
  - trailing      移动止损：价格 ≤ 持仓期最高价 × (1 - pct)
  - max_hold_days 时间止损：持有超过 N 交易日强制退出
  - atr_multiplier ATR 止损：价格 ≤ 成本 - atr × N（与固定止损取更严格者；需传入 atr）
  - breakeven_at_profit_pct 保本移动：浮盈 ≥ N% → 止损上移至成本
"""

from __future__ import annotations

import datetime as dt


class ExitManager:
    def __init__(self, rules: dict | None = None):
        # rules: {"stop_loss": 0.08, "take_profit": 0.15, "trailing": 0.06, "max_hold_days": 40}
        self.rules = rules or {}

    def check(self, positions: dict, prices: dict, date, atr: dict | None = None) -> dict[str, str]:
        """positions: {symbol: (shares, avg_cost, entry_date, high)}；atr: {symbol: 当前ATR}"""
        exits = {}
        atr = atr or {}
        for sym, (shares, cost, entry_date, high) in positions.items():
            px = prices.get(sym, 0.0)
            if shares <= 0 or px <= 0:
                continue
            if cost <= 0:
                continue
            if "stop_loss" in self.rules and px <= cost * (1 - self.rules["stop_loss"]):
                exits[sym] = f"止损 {self.rules['stop_loss']:.0%}（{px:.2f} ≤ {cost * (1 - self.rules['stop_loss']):.2f}）"
                continue
            if "atr_multiplier" in self.rules and atr.get(sym, 0) > 0:
                atr_stop = cost - atr[sym] * self.rules["atr_multiplier"]
                fixed_stop = cost * (1 - self.rules.get("stop_loss", 0.0))
                stop = min(atr_stop, fixed_stop)
                if "breakeven_at_profit_pct" in self.rules and high >= cost * (1 + self.rules["breakeven_at_profit_pct"]):
                    stop = max(stop, cost)  # 保本移动
                if px <= stop:
                    exits[sym] = f"ATR止损 {self.rules['atr_multiplier']:.1f}×ATR（{px:.2f} ≤ {stop:.2f}）"
                    continue
            elif "breakeven_at_profit_pct" in self.rules and high >= cost * (1 + self.rules["breakeven_at_profit_pct"]):
                if px <= cost:
                    exits[sym] = f"保本移动（浮盈达标后回落至成本 {cost:.2f}）"
                    continue
            if "take_profit" in self.rules and px >= cost * (1 + self.rules["take_profit"]):
                exits[sym] = f"止盈 {self.rules['take_profit']:.0%}（{px:.2f} ≥ {cost * (1 + self.rules['take_profit']):.2f}）"
                continue
            if "trailing" in self.rules and high > cost:
                stop = high * (1 - self.rules["trailing"])
                if px <= stop:
                    exits[sym] = f"移动止损 {self.rules['trailing']:.0%}（高点 {high:.2f} → {stop:.2f}）"
                    continue
            if "max_hold_days" in self.rules and entry_date:
                held = (dt.date.fromisoformat(str(date)[:10]) - dt.date.fromisoformat(str(entry_date)[:10])).days
                if held >= self.rules["max_hold_days"]:
                    exits[sym] = f"时间止损（持有 {held} 天 ≥ {self.rules['max_hold_days']}）"
        return exits

    def describe(self) -> str:
        if not self.rules:
            return "无退出规则（仅按调仓执行）"
        parts = []
        if "stop_loss" in self.rules:
            parts.append(f"止损 {self.rules['stop_loss']:.0%}")
        if "take_profit" in self.rules:
            parts.append(f"止盈 {self.rules['take_profit']:.0%}")
        if "trailing" in self.rules:
            parts.append(f"移动止损 {self.rules['trailing']:.0%}")
        if "max_hold_days" in self.rules:
            parts.append(f"时间止损 {self.rules['max_hold_days']} 天")
        if "atr_multiplier" in self.rules:
            parts.append(f"ATR止损 {self.rules['atr_multiplier']:.1f}×")
        if "breakeven_at_profit_pct" in self.rules:
            parts.append(f"保本移动 +{self.rules['breakeven_at_profit_pct']:.0%}")
        return "、".join(parts)
