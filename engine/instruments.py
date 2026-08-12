"""多标的规格引擎 —— 统一描述 现货 / 期货 / ETF 的交易属性。

为什么需要它：
- 风控最小集按"名义市值占比"限仓，但期货是保证金交易（同一笔资金撬动更大名义额），
  ETF 有跟踪误差，现货/期货可卖空性不同——这些必须由"标的规格"统一描述，
  否则风控与执行层会算错仓位、算错保证金、漏算穿仓风险。
- 这是把"回测 OS"升级为"交易 OS"的关键一层：策略只说买/卖，执行层依据规格决定
  实际下单手数、保证金占用、费用与是否允许做空。

所有规格可由 config/instruments.yaml 覆盖；缺失时按市场+类型给保守默认值。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

InstrumentType = Literal["spot", "future", "etf"]


@dataclass
class InstrumentSpec:
    symbol: str
    market: str                       # a / hk / us / crypto
    itype: InstrumentType
    multiplier: float = 1.0           # 合约乘数（期货通常 > 1，如股指每点 200 元）
    margin_rate: float = 1.0          # 保证金比例（1.0=全额；期货<1，如 0.10=10% 保证金）
    shortable: bool = True            # 是否可卖空
    fee_rate: float = 0.001           # 单边手续费占成交额比例
    slippage: float = 0.0005          # 滑点占价格比例
    tick_size: float = 0.01           # 最小价格变动
    contract_unit: float = 1.0        # 每手对应标的数量（期货如 100 股/手）
    expiry: str | None = None         # 期货合约到期日 (YYYY-MM-DD)
    underlying: str | None = None     # 期货/ETF 跟踪的标的代码
    notes: str = ""

    # —— 派生量 ——
    @property
    def is_leveraged(self) -> bool:
        """保证金比例 < 1 视为带杠杆（期货）。"""
        return self.margin_rate < 1.0

    def notional(self, qty: float, price: float) -> float:
        """名义市值（风控限仓用）。期货 = qty * price * multiplier * contract_unit。"""
        return qty * price * self.multiplier * self.contract_unit

    def margin_required(self, qty: float, price: float) -> float:
        """开仓占用的保证金（期货只需名义额 × 保证金比例）。"""
        return self.notional(qty, price) * self.margin_rate

    def round_qty(self, qty: float) -> float:
        """按每手取整（期货整手，现货/ETF 通常可碎股则保留）。"""
        if self.contract_unit >= 1 and self.itype == "future":
            import math
            return math.floor(qty / self.contract_unit) * self.contract_unit
        return qty

    def trade_cost(self, qty: float, price: float) -> float:
        """单边费用 + 滑点估算（绝对值，货币单位）。"""
        notional = self.notional(qty, price)
        return notional * (self.fee_rate + self.slippage)

    def validate_order(self, qty: float, side: str) -> tuple[bool, str]:
        if side not in ("buy", "sell") and side not in ("long", "short"):
            return False, f"未知方向 {side}"
        if qty <= 0:
            return False, "数量必须为正"
        if side in ("sell", "short") and not self.shortable:
            return False, f"{self.symbol} 不可卖空"
        if self.expiry:
            return True, "OK（注意期货到期）"
        return True, "OK"


# ---------------------------------------------------------------------------
# 默认规格库（保守默认值；config/instruments.yaml 可覆盖）
# ---------------------------------------------------------------------------
_DEFAULTS: dict[str, dict] = {
    # market -> {itype -> 默认参数}
    "a": {
        "spot": dict(margin_rate=1.0, shortable=False, fee_rate=0.0005, slippage=0.0008,
                     tick_size=0.01, notes="A股现货 T+1，不可裸卖空"),
        "etf":  dict(margin_rate=1.0, shortable=False, fee_rate=0.0005, slippage=0.0005,
                     tick_size=0.001, notes="A股ETF T+1，部分可融券"),
        "future": dict(margin_rate=0.12, shortable=True, fee_rate=0.0003, slippage=0.0005,
                       multiplier=200.0, contract_unit=1.0, tick_size=0.2,
                       notes="如 IF/IC 股指，保证金约 12%，每点 200 元"),
    },
    "hk": {
        "spot": dict(margin_rate=1.0, shortable=True, fee_rate=0.001, slippage=0.001,
                     tick_size=0.01, notes="港股现货可卖空（需沽空名单）"),
        "etf":  dict(margin_rate=1.0, shortable=True, fee_rate=0.001, slippage=0.0008,
                     tick_size=0.01),
        "future": dict(margin_rate=0.10, shortable=True, fee_rate=0.0003, slippage=0.0005,
                       multiplier=50.0, contract_unit=1.0, tick_size=1.0,
                       notes="如恒指期货，每点 50 港元"),
    },
    "us": {
        "spot": dict(margin_rate=1.0, shortable=True, fee_rate=0.0005, slippage=0.0005,
                     tick_size=0.01),
        "etf":  dict(margin_rate=1.0, shortable=True, fee_rate=0.0003, slippage=0.0003,
                     tick_size=0.01, notes="如 SPY/QQQ 可日内卖空与期权"),
        "future": dict(margin_rate=0.10, shortable=True, fee_rate=0.0002, slippage=0.0003,
                       multiplier=20.0, contract_unit=1.0, tick_size=0.25,
                       notes="如 ES 迷你标普，每点 20 美元"),
    },
    "crypto": {
        "spot": dict(margin_rate=1.0, shortable=True, fee_rate=0.001, slippage=0.0005,
                     tick_size=0.01, notes="币安现货，7x24"),
        "etf":  dict(margin_rate=1.0, shortable=True, fee_rate=0.002, slippage=0.001,
                     tick_size=0.001, notes="如现货 ETF 产品"),
        "future": dict(margin_rate=0.05, shortable=True, fee_rate=0.0004, slippage=0.0005,
                       multiplier=1.0, contract_unit=1.0, tick_size=0.1,
                       notes="U 本位合约，默认 5% 维持保证金起"),
    },
}


class InstrumentRegistry:
    """标的规格注册表：按 symbol+market+itype 查规格，支持 config 覆盖与默认值。"""

    def __init__(self, overrides: dict | None = None):
        self._cache: dict[tuple, InstrumentSpec] = {}
        self._overrides = overrides or {}

    def get(self, symbol: str, market: str, itype: InstrumentType = "spot") -> InstrumentSpec:
        key = (symbol, market, itype)
        if key in self._cache:
            return self._cache[key]
        base = _DEFAULTS.get(market, {}).get(itype, {})
        ov = self._overrides.get(market, {}).get(itype, {})
        spec = InstrumentSpec(
            symbol=symbol, market=market, itype=itype,
            **{**base, **ov},
        )
        self._cache[key] = spec
        return spec

    def register(self, spec: InstrumentSpec) -> None:
        self._cache[(spec.symbol, spec.market, spec.itype)] = spec
