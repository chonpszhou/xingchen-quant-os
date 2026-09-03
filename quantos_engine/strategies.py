"""动态策略注册表（量化交易 OS · 方法库层）

设计意图（用户明确：策略/方法都是动态更新的）：
  方法库是**活的**——学到一个方法、或方法被更新，立即注册进引擎，可回测、可对比、
  可版本化，**不需要先过五道闸就能"存在并运行"**。

  五道闸（WF + holdout + 质量否决 + DSR≥0.95 + 灰度）只用在**晋升到真金白银**
  （模拟盘/实盘）的那一步，是"下单前的护栏"，不是"方法进入系统的门槛"。

安全约束：
  - 每条方法必须是 **_STRATS 已注册的模板 + 参数**，绝不执行任意代码（无 codegen 风险）。
  - 模板不在 _STRATS → 跳过并告警（拒绝凭空造策略）。
  - 注册表按 id 幂等：同一 id 再次出现则更新 params/updated_at，不重复。

registry schema (config/strategies.json):
{
  "version": 2,
  "methods": [
    {
      "id": "vol_target_momentum_fast",
      "template": "vol_target_momentum",
      "params": {"window": 126, "skip": 10, "decay": 0.05, "target_vol": 0.25},
      "source": "learning-derived",
      "thesis": "缩短回看窗口以捕捉更快的动量",
      "symbol": "AAPL", "market": "us",        # 可选：该方法默认回测标的
      "created_at": "2026-09-02",
      "updated_at": "2026-09-02",
      "promoted": false                        # 是否通过五道闸晋升实盘
    }
  ]
}
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from .backtest import _STRATS


class StrategyRegistry:
    """版本化、幂等的方法库。"""

    def __init__(self, data: dict | None = None):
        d = data or {}
        self.version: int = int(d.get("version", 2))
        self.methods: list[dict] = list(d.get("methods", []))

    # ---- 查询 ----
    def list_methods(self) -> list[dict]:
        return self.methods

    def get(self, mid: str) -> dict | None:
        for m in self.methods:
            if m.get("id") == mid:
                return m
        return None

    def valid_methods(self) -> list[dict]:
        """模板存在于 _STRATS 的方法（其余会在保存/加载时告警跳过）。"""
        out, bad = [], []
        for m in self.methods:
            if m.get("template") in _STRATS:
                out.append(m)
            else:
                bad.append(m.get("id", "?"))
        if bad:
            print(f"  ⚠️ 注册表跳过未知模板: {bad}（仅允许 {sorted(_STRATS)}）")
        return out

    # ---- 写入（幂等） ----
    def upsert(self, *, mid: str, template: str, params: dict | None = None,
               source: str = "learning-derived", thesis: str = "",
               symbol: str | None = None, market: str | None = None,
               today: str | None = None) -> dict:
        """按 id 幂等写入/更新一条方法。返回最终条目。"""
        today = today or date.today().strftime("%Y-%m-%d")
        params = params or {}
        if template not in _STRATS:
            raise ValueError(f"模板 {template!r} 不在已注册策略 {sorted(_STRATS)}，拒绝注册")
        existing = self.get(mid)
        if existing is None:
            entry = {
                "id": mid, "template": template, "params": params,
                "source": source, "thesis": thesis,
                "created_at": today, "updated_at": today, "promoted": False,
            }
            if symbol:
                entry["symbol"] = symbol
            if market:
                entry["market"] = market
            self.methods.append(entry)
            return entry
        # 更新（保留 created_at / promoted）
        existing["template"] = template
        existing["params"] = params
        existing["source"] = source
        if thesis:
            existing["thesis"] = thesis
        if symbol:
            existing["symbol"] = symbol
        if market:
            existing["market"] = market
        existing["updated_at"] = today
        return existing

    def mark_promoted(self, mid: str, promoted: bool = True) -> None:
        """晋升标记（五道闸通过后调用）。"""
        m = self.get(mid)
        if m:
            m["promoted"] = promoted
            m["promoted_at"] = date.today().strftime("%Y-%m-%d") if promoted else None

    # ---- 持久化 ----
    def to_dict(self) -> dict:
        return {"version": self.version, "methods": self.methods}

    def save(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
                     encoding="utf-8")
        return p


def load_registry(path: str | Path) -> "StrategyRegistry":
    p = Path(path)
    if not p.exists():
        return StrategyRegistry({"version": 2, "methods": []})
    try:
        return StrategyRegistry(json.loads(p.read_text(encoding="utf-8")))
    except Exception as e:
        print(f"  ⚠️ 注册表解析失败，退回空库: {e}")
        return StrategyRegistry({"version": 2, "methods": []})
