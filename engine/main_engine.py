"""总引擎：组件注册 + 事件路由（对标 vnpy MainEngine）"""

from __future__ import annotations

from .events import EVENT_BAR, EVENT_SIGNAL, Event, EventBus


class MainEngine:
    def __init__(self, data_service=None):
        self.ds = data_service
        self.bus = EventBus()
        self.strategies: dict[str, object] = {}
        self.executor = None
        self.risk = None
        self.bus.subscribe(EVENT_SIGNAL, self._on_signal)

    def add_strategy(self, name: str, strategy):
        strategy.engine = self
        strategy.ds = self.ds
        self.strategies[name] = strategy
        strategy.on_init()

    def set_executor(self, executor):
        self.executor = executor

    def set_risk(self, risk):
        self.risk = risk

    def emit_signal(self, signal):
        self.bus.publish(Event(EVENT_SIGNAL, signal))

    def _on_signal(self, event):
        signal = event.data
        if self.risk and self.executor:
            nav = self.executor.nav(getattr(self, "_prices", {}))
            ok, msg = self.risk.pre_trade(signal.weights, nav)
            if not ok:
                signal.weights = {}

    def on_bar(self, bar):
        self.bus.publish(Event(EVENT_BAR, bar))
        self._prices = {bar.symbol: bar.close_price} if bar else {}
