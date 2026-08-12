"""止盈止损退出规则引擎（对标专业交易系统的事件驱动退出管理）

规则（可在 config/exits.yaml 配置，逐策略设置）：
  - stop_loss   固定止损：价格 ≤ 成本 × (1 - pct)
  - take_profit 固定止盈：价格 ≥ 成本 × (1 + pct)
  - trailing    移动止损：价格 ≤ 持仓期最高价 × (1 - pct)
  - max_hold    时间止损：持有超过 N 交易日强制退出
"""

from __future__ import annotations

import datetime as dt


class ExitManager:
    def __init__(self, rules: dict | None = None):
        # rules: {"stop_loss": 0.08, "take_profit": 0.15, "trailing": 0.06, "max_hold_days": 40}
        self.rules = rules or {}

    def check(self, positions: dict, prices: dict, date) -> dict[str, str]:
        """positions: {symbol: (shares, avg_cost, entry_date, high)}；返回触发退出的 {symbol: 原因}"""
        exits = {}
        for sym, (shares, cost, entry_date, high) in positions.items():
            px = prices.get(sym, 0.0)
            if shares <= 0 or px <= 0:
                continue
            if cost <= 0:
                continue
            if "stop_loss" in self.rules and px <= cost * (1 - self.rules["stop_loss"]):
                exits[sym] = f"止损 {self.rules['stop_loss']:.0%}（{px:.2f} ≤ {cost * (1 - self.rules['stop_loss']):.2f}）"
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
        return "、".join(parts)
