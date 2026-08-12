#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 美股期权 Gamma Exposure（GEX）快照

自 paddy-quant-workbench 合并：对 SPY/QQQ/等标的计算 Call Wall / Put Wall /
Zero Gamma，辅助判断期权做市商对冲方向（支撑/阻力位）。

用法:
    python3 scripts/gex_snapshot.py
输出:
    docs/期权GEX快照.md
"""

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.gex import compute_gex  # noqa: E402

SYMBOLS = ["SPY", "QQQ", "AAPL", "NVDA", "TSLA"]


def main():
    rows = []
    for sym in SYMBOLS:
        try:
            g = compute_gex(sym)
            if g is None:
                rows.append((sym, "-", "-", "-", "-"))
                continue
            rows.append((sym, f"{g['underlying']:.1f}", g.get("zero_gamma"),
                         g.get("call_wall"), g.get("put_wall")))
        except Exception as e:  # noqa: BLE001
            rows.append((sym, "失败", str(e)[:30], "-", "-"))
    lines = [
        "# 期权 Gamma Exposure（GEX）快照",
        "",
        f"> 生成时间：{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}",
        "> 口径：最近到期期权链 × Black-Scholes Gamma × 持仓量（估算，非官方数据）",
        "> 解读：Zero Gamma 下方=做市商倾向卖跌（支撑）；Call Wall=最大正 Gamma（阻力上方易加速）",
        "",
        "| 标的 | 现价 | Zero Gamma | Call Wall | Put Wall |",
        "|------|------|-----------|-----------|----------|",
    ]
    for sym, px, zg, cw, pw in rows:
        lines.append(f"| {sym} | {px} | {zg or '-'} | {cw or '-'} | {pw or '-'} |")
    lines += ["", "> 仅供学习研究参考，不构成投资建议。", ""]
    out = ROOT / "docs" / "期权GEX快照.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
