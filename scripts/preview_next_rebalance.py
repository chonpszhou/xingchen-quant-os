#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 下次调仓预告

用当前信号计算三个策略的“下一次调仓目标持仓”：
  - 双动量：当前动量最高且>0 的资产（否则 TLT）
  - 风险平价：当前逆波动率权重
  - 可转债双低：当前快照 TOP20（信用过滤后）

注意：这是当前信号的前瞻展示，不是收益预测；信号在调仓日可能变化。

用法:
    python3 scripts/preview_next_rebalance.py
输出:
    docs/下次调仓预告.md
"""

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from datahub.store import LocalStore  # noqa: E402
from paper_trade_momentum import momentum_scores, latest_prices as mom_prices  # noqa: E402
from paper_trade_rp import latest_prices as rp_prices, target_weights  # noqa: E402


def main():
    store = LocalStore(str(ROOT / "data"))
    today = pd.Timestamp.now().strftime("%Y-%m-%d")
    lines = [
        "# 下次调仓预告",
        "",
        f"> 生成时间：{today} · 依据当前最新信号（非收益预测，调仓日可能变化）",
        "",
    ]

    # 双动量
    scores = momentum_scores(store)
    if scores:
        best = max(scores, key=scores.get)
        pick = best if scores[best] > 0 else "TLT（动量全负，持安全资产）"
        lines += ["## 双动量（下次调仓目标）", "",
                  f"- 预计持仓：**{pick}**",
                  "- 当前动量：" + "、".join(f"{k} {v:.1%}" for k, v in scores.items()),
                  ""]
    else:
        lines += ["## 双动量\n\n数据不足。\n"]

    # 风险平价
    prices, _ = rp_prices(store)
    if prices:
        w = target_weights(store, prices)
        if w:
            lines += ["## 风险平价（下次调仓目标权重）", "",
                      "| 资产 | 目标权重 |", "|------|----------|"]
            for s, v in sorted(w.items(), key=lambda x: -x[1]):
                lines.append(f"| {s} | {v:.0%} |")
            lines.append("")

    # 双低
    snap = ROOT / "data" / "cb_daily_snapshot.json"
    if snap.exists():
        s = json.loads(snap.read_text(encoding="utf-8"))
        lines += ["## 可转债双低（当前 TOP20 = 下次调仓候选）", "",
                  "| 名称 | 价格 | 溢价 | 双低值 | 评级 |",
                  "|------|------|------|--------|------|"]
        for r in s["rank"][:20]:
            lines.append(f"| {r['name']} | {r['price']:.1f} | {r['premium']:.1f}% | "
                         f"{r['score']:.1f} | {r.get('rating', '-')} |")
        lines.append("")

    lines += [
        "## 说明",
        "",
        "- 这是**当前信号**的前瞻：若信号在调仓日未变，将按此执行；变了则按新信号",
        "- 实际调仓由模拟盘脚本在调仓日自动执行（20-21 交易日一次），届时以当日摘要为准",
        "",
        "> 仅供学习研究参考，不构成投资建议。",
        "",
    ]
    out = ROOT / "docs" / "下次调仓预告.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:24]))


if __name__ == "__main__":
    main()
