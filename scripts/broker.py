#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 交易执行层抽象（纸面 → 实盘即插即用）

统一 Broker 接口：connect / get_nav / get_positions / buy / sell / get_price
当前实现：PaperBroker（可转债双低模拟盘，已运行）
预留适配器（凭证就绪后启用，见 config/broker.yaml）：
  - QmtBroker   （A股，QMT/迅投，需券商账号）
  - FutuBroker  （港股/美股，富途 OpenD，需账号与 OpenD 地址）
  - OkxBroker   （加密，OKX API Key）

用法（示例）:
    python3 -c "from broker import PaperBroker; b = PaperBroker(); print(b.get_nav())"
"""

import json
import sys
from abc import ABC, abstractmethod
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


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
    """纸面券商：读写本地模拟盘状态（data/paper_cb_state.json + nav parquet）"""

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

    def buy(self, symbol, shares):
        raise NotImplementedError("PaperBroker 调仓由 paper_trade_cb.py 统一执行，勿单独调用")

    def sell(self, symbol, shares):
        raise NotImplementedError("同上")

    def get_price(self, symbol):
        raise NotImplementedError("价格由每日快照统一获取")


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


def get_broker(name="paper"):
    """按配置返回券商实例（当前仅 paper 可用）"""
    if name == "paper":
        return PaperBroker()
    import yaml
    cfg = yaml.safe_load((ROOT / "config" / "broker.yaml").read_text(encoding="utf-8"))
    cls = {"qmt": QmtBroker, "futu": FutuBroker, "okx": OkxBroker}[name]
    return cls(cfg.get(name, {}))


if __name__ == "__main__":
    b = get_broker("paper")
    b.connect()
    print(json.dumps(b.get_nav(), ensure_ascii=False, indent=2))
    pos = b.get_positions()
    print(f"持仓 {len(pos)} 只，TOP3:")
    for p in sorted(pos, key=lambda x: -x["value"])[:3]:
        print(f"  {p['symbol']}: {p['shares']:.0f} 张 = {p['value']:,.0f}")
