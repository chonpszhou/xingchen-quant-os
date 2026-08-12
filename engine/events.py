"""事件总线（对标 vnpy EventEngine，轻量实现）"""

from __future__ import annotations

from collections import defaultdict

EVENT_BAR = "bar"
EVENT_SIGNAL = "signal"
EVENT_TRADE = "trade"
EVENT_RISK = "risk"


class Event:
    def __init__(self, type_: str, data=None):
        self.type = type_
        self.data = data


class EventBus:
    def __init__(self):
        self._handlers: dict[str, list] = defaultdict(list)

    def subscribe(self, type_: str, handler):
        self._handlers[type_].append(handler)
        return self

    def publish(self, event: Event):
        for h in list(self._handlers.get(event.type, [])):
            h(event)
