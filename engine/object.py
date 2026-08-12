"""统一数据对象（对标 vnpy object.py）"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class BarData:
    symbol: str
    exchange: str = ""
    datetime: datetime | None = None
    open_price: float = 0.0
    high_price: float = 0.0
    low_price: float = 0.0
    close_price: float = 0.0
    volume: float = 0.0


@dataclass
class OrderData:
    symbol: str
    direction: str = "buy"          # buy / sell
    price: float = 0.0
    volume: float = 0.0
    status: str = "submitted"


@dataclass
class TradeData:
    symbol: str
    direction: str = "buy"
    price: float = 0.0
    volume: float = 0.0


@dataclass
class Signal:
    """策略发出的目标持仓信号：{symbol: 目标权重}"""
    weights: dict[str, float] = field(default_factory=dict)
    reason: str = ""
