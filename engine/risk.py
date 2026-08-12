"""内嵌风控（交易前检查；对标 freqtrade 交易前保护）"""

from __future__ import annotations


class RiskEngine:
    def __init__(self, max_positions: int = 20, max_single_weight: float = 1.0,
                 drawdown_breaker: float = 0.0):
        self.max_positions = max_positions
        self.max_single_weight = max_single_weight
        self.drawdown_breaker = drawdown_breaker   # 0=关闭；0.2=回撤20%熔断
        self.peak_nav = 0.0

    def pre_trade(self, weights: dict, nav: float) -> tuple[bool, str]:
        if nav <= 0:
            return False, "净值异常"
        if len(weights) > self.max_positions:
            return False, f"持仓数 {len(weights)} 超上限 {self.max_positions}"
        if weights and max(weights.values()) > self.max_single_weight + 1e-9:
            return False, f"单标的权重超上限 {self.max_single_weight}"
        self.peak_nav = max(self.peak_nav, nav)
        if self.drawdown_breaker > 0 and nav < self.peak_nav * (1 - self.drawdown_breaker):
            return False, f"回撤 {1 - nav / self.peak_nav:.1%} 触发熔断"
        return True, ""

    def post_trade(self, nav: float):
        self.peak_nav = max(self.peak_nav, nav)
