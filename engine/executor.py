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
                 deploy_ratio: float = 0.98, db=None, strategy_name: str = ""):
        self.cash = initial_cash
        self.positions: dict[str, float] = {}   # symbol -> shares
        self.cost = cost
        self.deploy_ratio = deploy_ratio
        self.history = []                        # (date, nav)
        self.db = db
        self.strategy_name = strategy_name
        self._last: dict[str, float] = {}        # 最后已知价（停牌/退市盯市）
        self._high: dict[str, float] = {}        # 持仓期最高价（移动止损用）
        self._cost: dict[str, float] = {}        # 持仓平均成本
        self._entry: dict[str, str] = {}         # 建仓日期
        self.trade_count = 0

    def _price(self, sym, prices):
        return prices.get(sym, self._last.get(sym, 0.0))

    def _record(self, date, symbol, direction, price, delta):
        self.trade_count += 1
        if self.db:
            self.db.record_trade(self.strategy_name, date, symbol, direction,
                                 price, abs(delta), abs(delta) * self.cost)

    def execute(self, weights, prices, date):
        total = self.nav(prices)
        self._last.update({k: v for k, v in prices.items() if v > 0})
        turnover_cost = 0.0
        for sym, w in weights.items():
            px = self._price(sym, prices)
            if px <= 0:
                continue  # 无价/停牌标的跳过（保持原持仓）
            target_value = total * self.deploy_ratio * w
            cur = self.positions.get(sym, 0.0) * px
            delta = target_value - cur
            if abs(delta) < 100:
                continue
            shares = delta / px
            old_sh, old_cost = self.positions.get(sym, 0.0), self._cost.get(sym, 0.0)
            new_sh = old_sh + shares
            self.positions[sym] = new_sh
            if new_sh > 1e-6:
                self._cost[sym] = (old_sh * old_cost + shares * px) / new_sh
                self._entry.setdefault(sym, str(date)[:10])
            if self.positions[sym] < 1e-6:
                del self.positions[sym]
                self._cost.pop(sym, None)
                self._entry.pop(sym, None)
            self.cash -= delta * (1 + self.cost if delta > 0 else 1 - self.cost)
            turnover_cost += abs(delta) * self.cost
            self._record(date, sym, "buy" if delta > 0 else "sell", px, delta)
        # 移除不再持有的（weights 未包含）
        for sym in list(self.positions):
            if sym not in weights:
                val = self.positions[sym] * self._price(sym, prices)
                self.cash += val * (1 - self.cost)
                turnover_cost += val * self.cost
                del self.positions[sym]
                self._cost.pop(sym, None)
                self._entry.pop(sym, None)
                self._record(date, sym, "sell", self._price(sym, prices), -val)
        self.history.append((date, self.nav(prices)))
        if self.db:
            self.db.save_positions(self.strategy_name, self.positions, prices)
            self.db.record_nav(self.strategy_name, date, self.nav(prices))
        return turnover_cost

    def nav(self, prices):
        mv = sum(sh * self._price(s, prices) for s, sh in self.positions.items())
        return self.cash + mv

    def positions(self):
        return dict(self.positions)

    def positions_with_cost(self, prices=None) -> dict:
        """{symbol: (shares, avg_cost, entry_date, high_since_entry)}"""
        out = {}
        prices = prices or {}
        high = getattr(self, "_high", {})
        for sym, sh in self.positions.items():
            out[sym] = (sh, self._cost.get(sym, 0.0),
                        self._entry.get(sym, ""), high.get(sym, self._price(sym, prices)))
        return out

    def sell_position(self, sym, price, date, reason=""):
        """清仓（止盈止损触发）"""
        sh = self.positions.get(sym, 0.0)
        if sh <= 0 or price <= 0:
            return 0.0
        val = sh * price
        self.cash += val * (1 - self.cost)
        cost_val = val * self.cost
        del self.positions[sym]
        self._cost.pop(sym, None)
        self._entry.pop(sym, None)
        self._record(date, sym, "sell", price, -val)
        self.history.append((date, self.nav({sym: price})))
        return cost_val

    def update_highs(self, prices):
        self._high = {s: max(self._high.get(s, 0.0), px) for s, px in prices.items() if px > 0}
