"""执行层接口 + 纸面执行（对标 freqtrade exchange）"""

from __future__ import annotations

from abc import ABC, abstractmethod


class Executor(ABC):
    @abstractmethod
    def execute(self, weights: dict, prices: dict, date) -> float:
        """按目标权重调仓，返回成交成本"""

    @abstractmethod
    def nav(self, prices: dict) -> float:
        pass

    @abstractmethod
    def positions(self) -> dict:
        pass


class PaperExecutor(Executor):
    """通用纸面执行：现金+持仓，按目标权重调仓，双边成本"""

    def __init__(self, initial_cash: float = 1_000_000.0, cost: float = 0.001,
                 deploy_ratio: float = 0.98):
        self.cash = initial_cash
        self.positions: dict[str, float] = {}   # symbol -> shares
        self.cost = cost
        self.deploy_ratio = deploy_ratio
        self.history = []                        # (date, nav)

    def execute(self, weights, prices, date):
        total = self.nav(prices)
        turnover_cost = 0.0
        for sym, w in weights.items():
            target_value = total * self.deploy_ratio * w
            cur = self.positions.get(sym, 0.0) * prices.get(sym, 0.0)
            delta = target_value - cur
            if abs(delta) < 100:
                continue
            shares = delta / prices[sym]
            self.positions[sym] = self.positions.get(sym, 0.0) + shares
            if self.positions[sym] < 1e-6:
                del self.positions[sym]
            self.cash -= delta * (1 + self.cost if delta > 0 else 1 - self.cost)
            turnover_cost += abs(delta) * self.cost
        # 移除不再持有的（weights 未包含）
        for sym in list(self.positions):
            if sym not in weights:
                val = self.positions[sym] * prices.get(sym, 0.0)
                self.cash += val * (1 - self.cost)
                turnover_cost += val * self.cost
                del self.positions[sym]
        self.history.append((date, self.nav(prices)))
        return turnover_cost

    def nav(self, prices):
        mv = sum(sh * prices.get(s, 0.0) for s, sh in self.positions.items())
        return self.cash + mv

    def positions(self):
        return dict(self.positions)
