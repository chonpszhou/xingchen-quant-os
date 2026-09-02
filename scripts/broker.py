#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 交易执行层抽象（纸面 → 实盘即插即用）

统一 Broker 接口：connect / get_nav / get_positions / buy / sell / get_price

实现：
  - PaperBroker   ：可转债双低模拟盘（已运行，天然安全）
  - LiveBroker    ：实盘安全包装层（双闸门 DRY-RUN，移植自 paddy-quant-os）
  - QmtBroker     ：A股 QMT 实盘适配器（预留，凭证就绪后启用）
  - FutuBroker    ：港股/美股 富途 OpenD 适配器（预留）
  - OkxBroker     ：加密 OKX 适配器（预留）

安全原则（比「默认 testnet」更严，因为真金白银不可逆）：
  - 任何真实适配器（qmt/futu/okx）都经由 LiveBroker 双闸门包裹。
  - 默认 DRY-RUN：记录「本应下的单」(data/order_audit.jsonl) 但绝不发单。
  - 仅当「配置 enabled=True」且「dry_run=False」且「confirm=True」三者齐备才 armed。
  - confirm 只能由调用方显式传入，配置本身无法单独把系统置为实盘。

统一审计：PaperBroker（模拟成交）与 LiveBroker（真实适配器 DRY-RUN 拦截 / 实盘成交）
共用同一份 data/order_audit.jsonl 订单留痕，便于全链路回溯。

用法:
    python3 -c "from broker import PaperBroker; b = PaperBroker(); print(b.get_nav())"
    python3 -c "from broker import get_broker; b = get_broker('okx'); print(b.status())"
    python3 -m pytest scripts/test_broker.py -q
"""

import datetime
import json
import sys
from abc import ABC, abstractmethod
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ORDER_AUDIT_LOG = ROOT / "data" / "order_audit.jsonl"   # 统一订单审计留痕


def _audit_order(rec: dict) -> dict:
    """把一条订单记录追加到统一审计日志（持久、可回溯）。失败不影响主流程。"""
    try:
        ORDER_AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with ORDER_AUDIT_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return rec


class Broker(ABC):
    """交易执行统一接口"""

    @abstractmethod
    def connect(self):
        pass

    @abstractmethod
    def get_nav(self):
        pass

    @abstractmethod
    def get_positions(self):
        pass

    @abstractmethod
    def buy(self, symbol, shares):
        pass

    @abstractmethod
    def sell(self, symbol, shares):
        pass

    @abstractmethod
    def get_price(self, symbol):
        pass


class PaperBroker(Broker):
    """纸面券商：读写本地模拟盘状态（data/paper_cb_state.json + nav parquet）

    说明：buy/sell 为**单笔**调仓接口（含记账），供 ad-hoc 交易或经 LiveBroker
    包裹后走统一审计。周期性的完整再平衡由 scripts/paper_trade_cb.py 统一执行
    （它直接改写同一份 state 文件，不经过本接口）。
    """

    def __init__(self, state_file="data/paper_cb_state.json",
                 nav_file="data/paper_cb_nav.parquet"):
        self.state_file = ROOT / state_file
        self.nav_file = ROOT / nav_file

    def connect(self):
        if not self.state_file.exists():
            raise RuntimeError("模拟盘未初始化，先运行 python3 scripts/paper_trade_cb.py")
        return True

    def _state(self):
        return json.loads(self.state_file.read_text(encoding="utf-8"))

    def _write_state(self, st):
        self.state_file.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_nav(self):
        import pandas as pd
        st = self._state()
        nav = None
        if self.nav_file.exists():
            nav = float(pd.read_parquet(self.nav_file)["nav"].iloc[-1])
        return {"nav": nav, "cash": st["cash"],
                "rebalance_count": st["rebalance_count"],
                "last_rebalance": st["last_rebalance"]}

    def get_positions(self):
        st = self._state()
        return [{"symbol": c, "shares": h["shares"], "last_price": h["last_price"],
                 "value": h["value"]} for c, h in st["holdings"].items()]

    def buy(self, symbol, shares, price=None):
        st = self._state()
        price = float(price if price is not None else st["holdings"].get(symbol, {}).get("last_price", 0.0))
        if price <= 0:
            raise ValueError(f"无法买入 {symbol}：价格无效 ({price})")
        shares = float(shares)
        cost = shares * price
        if cost > st["cash"]:
            shares = st["cash"] / price          # 不允许透支：按可用现金上限购买
            cost = shares * price
        h = st["holdings"].get(symbol, {"shares": 0.0, "last_price": price, "value": 0.0})
        h["shares"] = h["shares"] + shares
        h["last_price"] = price
        h["value"] = h["shares"] * price
        st["holdings"][symbol] = h
        st["cash"] = st["cash"] - cost
        self._write_state(st)
        return {"ok": True, "symbol": symbol, "shares": round(shares, 4),
                "price": price, "cost": round(cost, 2), "cash_left": round(st["cash"], 2)}

    def sell(self, symbol, shares, price=None):
        st = self._state()
        if symbol not in st["holdings"] or st["holdings"][symbol]["shares"] <= 0:
            raise ValueError(f"无法卖出 {symbol}：无持仓")
        h = st["holdings"][symbol]
        price = float(price if price is not None else h.get("last_price", 0.0))
        shares = min(float(shares), h["shares"])
        proceeds = shares * price
        h["shares"] = h["shares"] - shares
        h["last_price"] = price
        h["value"] = h["shares"] * price
        if h["shares"] <= 0:
            del st["holdings"][symbol]
        st["cash"] = st["cash"] + proceeds
        self._write_state(st)
        return {"ok": True, "symbol": symbol, "shares": round(shares, 4),
                "price": price, "proceeds": round(proceeds, 2), "cash_left": round(st["cash"], 2)}

    def get_price(self, symbol):
        st = self._state()
        return st["holdings"].get(symbol, {}).get("last_price")


class LiveBroker(Broker):
    """实盘安全包装层（双闸门 DRY-RUN）。

    移植自 paddy-quant-os 的 src/broker/live.py，适配星辰的 Broker 接口
    （buy/sell/get_nav/... 而非 submit_order/mark）。

    双闸门：armed = live_enabled and (not dry_run) and confirm
      - live_enabled 来自 config/broker.yaml 中该券商的 enabled（配置允许）
      - dry_run     构造参数，默认 True（安全默认）
      - confirm     构造参数，默认 False，必须调用方显式传入（显式认知真实风险）
    三者任一不满足 → 不 armed。

    统一审计：所有经本适配器的订单（paper 执行 / 真实适配器 DRY-RUN 拦截 / 实盘成交）
    都写入同一份 data/order_audit.jsonl。
    """

    def __init__(self, backend: Broker, live_enabled: bool = False,
                 dry_run: bool = True, confirm: bool = False):
        self.backend = backend
        self.live_enabled = bool(live_enabled)
        self.dry_run = bool(dry_run)
        self.confirm = bool(confirm)
        self.is_paper = isinstance(backend, PaperBroker)
        # 双闸门：三重校验齐备才真正发单
        self.armed = self.live_enabled and (not self.dry_run) and self.confirm
        if self.is_paper:
            self.mode = "PAPER"
        else:
            self.mode = "LIVE" if self.armed else ("DRY-RUN" if self.dry_run else "DISABLED")

    # —— 安全状态查询 ——
    def status(self) -> str:
        if self.armed:
            return "🔴 LIVE（真实下单，不可逆）"
        if self.is_paper:
            return "🟢 PAPER（模拟成交，已审计）"
        return f"🟢 {self.mode}（未触碰任何券商/交易所）"

    def is_armed(self) -> bool:
        return self.armed

    def _log_dry(self, side, symbol, shares, price=None, note=""):
        return _audit_order({
            "ts": datetime.datetime.now().isoformat(timespec="seconds"),
            "side": side, "symbol": symbol, "shares": shares, "price": price,
            "armed": self.armed, "mode": self.mode, "note": note,
        })

    def _guard(self, side, symbol, shares, price=None):
        if self.armed:
            # 真实下单（仅显式 armed 可达——双闸门已校验）
            self._log_dry(side, symbol, shares, price=price, note="LIVE 实盘成交")
            return getattr(self.backend, side)(symbol, shares, price=price)
        if self.is_paper:
            # 模拟盘：执行记账 + 审计（非拦截）
            self._log_dry(side, symbol, shares, price=price, note="PAPER 模拟成交（经 LiveBroker 审计）")
            return getattr(self.backend, side)(symbol, shares, price=price)
        # 真实适配器 DRY-RUN：留痕，绝不触碰券商
        self._log_dry(side, symbol, shares, price=price, note="DRY-RUN 拦截：未发送真实订单")
        return {"ok": False, "dry_run": True, "side": side,
                "symbol": symbol, "shares": shares, "price": price,
                "msg": "DRY-RUN：未发送真实订单（见 data/order_audit.jsonl）"}

    # —— 接口实现 ——
    def connect(self):
        try:
            return self.backend.connect()
        except NotImplementedError:
            return False  # DRY-RUN 允许底层未实现

    def get_nav(self):
        try:
            return self.backend.get_nav()
        except NotImplementedError:
            return {"nav": None, "cash": None, "mode": self.mode, "armed": self.armed}

    def get_positions(self):
        try:
            return self.backend.get_positions()
        except NotImplementedError:
            return []

    def get_price(self, symbol):
        try:
            return self.backend.get_price(symbol)
        except NotImplementedError:
            return None

    def buy(self, symbol, shares, price=None):
        return self._guard("buy", symbol, shares, price=price)

    def sell(self, symbol, shares, price=None):
        return self._guard("sell", symbol, shares, price=price)

    # —— 沙盘推演：永远只留痕，绝不发单 ——
    def dry_run_replay(self, trades: list) -> dict:
        """trades: [(side, symbol, shares), ...]。

        把一组「拟交易」跑一遍，返回本应下的单清单。与真实盘的 buy/sell
        共用同一道 _guard，切真盘只需把 armed 打开。沙盘推演默认只留痕。
        """
        sent = []
        for t in trades:
            side, symbol, shares = (list(t) + [0, 0])[:3]
            sent.append(self._log_dry(side, symbol, shares, note="replay"))
        return {"mode": self.mode, "armed": self.armed, "n": len(sent), "plan": sent}


class QmtBroker(Broker):
    """A股 QMT（迅投）实盘适配器——需要券商 QMT 账号，见 config/broker.yaml"""

    def __init__(self, cfg):
        self.cfg = cfg

    def connect(self):
        # 计划：from xtquant import xttrader; xttrader.XtQuantTrader(...)
        raise NotImplementedError("QMT 实盘未接入：填写 config/broker.yaml 券商账号后启用")

    def get_nav(self): raise NotImplementedError()
    def get_positions(self): raise NotImplementedError()
    def buy(self, symbol, shares): raise NotImplementedError()
    def sell(self, symbol, shares): raise NotImplementedError()
    def get_price(self, symbol): raise NotImplementedError()


class FutuBroker(Broker):
    """富途 OpenD（港股/美股）适配器——需要 OpenD 运行与账号授权"""

    def __init__(self, cfg):
        self.cfg = cfg

    def connect(self):
        raise NotImplementedError("富途实盘未接入：启动 OpenD 并填写 config/broker.yaml")

    def get_nav(self): raise NotImplementedError()
    def get_positions(self): raise NotImplementedError()
    def buy(self, symbol, shares): raise NotImplementedError()
    def sell(self, symbol, shares): raise NotImplementedError()
    def get_price(self, symbol): raise NotImplementedError()


class OkxBroker(Broker):
    """OKX 加密实盘适配器——需要 API Key/Secret/Passphrase"""

    def __init__(self, cfg):
        self.cfg = cfg

    def connect(self):
        raise NotImplementedError("OKX 实盘未接入：填写 config/broker.yaml 的 API Key 后启用")

    def get_nav(self): raise NotImplementedError()
    def get_positions(self): raise NotImplementedError()
    def buy(self, symbol, shares): raise NotImplementedError()
    def sell(self, symbol, shares): raise NotImplementedError()
    def get_price(self, symbol): raise NotImplementedError()


def get_broker(name="paper", dry_run=True, confirm=False):
    """按配置返回券商实例（真实适配器一律经 LiveBroker 双闸门包裹）。

    - paper      ：用 LiveBroker 包裹 PaperBroker —— 模拟成交走统一审计。
    - qmt/futu/okx：实例化真实适配器，并包裹 LiveBroker。
        live_enabled 取自 config/broker.yaml 中该券商的 enabled；
        dry_run/confirm 默认 False→安全，需调用方显式置位才 armed。
    """
    if name == "paper":
        return LiveBroker(PaperBroker(), live_enabled=False, dry_run=False, confirm=False)
    import yaml
    cfg_path = ROOT / "config" / "broker.yaml"
    if not cfg_path.exists():
        raise RuntimeError(f"缺少 {cfg_path}，无法加载 {name} 实盘配置")
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    real_cls = {"qmt": QmtBroker, "futu": FutuBroker, "okx": OkxBroker}[name]
    real = real_cls(cfg.get(name, {}))
    live_enabled = bool(cfg.get(name, {}).get("enabled", False))
    return LiveBroker(real, live_enabled=live_enabled, dry_run=dry_run, confirm=confirm)


if __name__ == "__main__":
    # 1) 模拟盘（经 LiveBroker 包裹，模拟成交走统一审计）
    b = get_broker("paper")
    b.connect()
    print(json.dumps(b.get_nav(), ensure_ascii=False, indent=2))
    pos = b.get_positions()
    print(f"持仓 {len(pos)} 只，TOP3:")
    for p in sorted(pos, key=lambda x: -x["value"])[:3]:
        print(f"  {p['symbol']}: {p['shares']:.0f} 张 = {p['value']:,.0f}")

    # 2) 真实适配器默认 DRY-RUN（绝不发单）
    print("\n--- 真实适配器双闸门演示（okx，配置 enabled=false）---")
    okx = get_broker("okx")
    print("status:", okx.status(), "| armed:", okx.is_armed())
    print("buy 尝试:", okx.buy("BTC-USDT", 0.01))   # DRY-RUN 拦截留痕
    print("replay:", okx.dry_run_replay([("buy", "ETH-USDT", 0.1), ("sell", "SOL-USDT", 1.0)]))

    # 3) 即便 config enabled=true 且 dry_run=False，缺 confirm 仍不 armed（安全）
    armed_try = LiveBroker(OkxBroker({"enabled": True}), live_enabled=True,
                           dry_run=False, confirm=False)
    print("\n--- 缺 confirm：live_enabled=True & dry_run=False 但 confirm=False ---")
    print("status:", armed_try.status(), "| armed:", armed_try.is_armed())
