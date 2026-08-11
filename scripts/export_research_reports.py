#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""研究报告 → Obsidian 分类导出（含总览 MOC）"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(ROOT, "docs", "obsidian_export", "研究报告")

REPORTS = [
    ("因子中性化与稳健性评估报告.md", "因子评估", ["因子", "中性化", "IC"]),
    ("因子组合回测与WalkForward报告.md", "因子回测", ["因子", "walk-forward", "回测"]),
    ("数据质量报告.md", "数据质量", ["数据", "质量"]),
    ("大佬信号验证报告.md", "大佬信号", ["假突破", "接针", "事件研究"]),
    ("跨市场扩池验证报告.md", "跨市场", ["美股", "港股", "低波", "动量"]),
    ("CTA趋势跟踪验证报告.md", "CTA", ["趋势跟踪", "动量", "波动率目标"]),
    ("基本面因子验证报告.md", "基本面", ["价值", "质量", "ROE", "PE"]),
    ("点对时池验证报告.md", "点对时池", ["幸存者偏差", "沪深300", "中证500"]),
    ("点对时池基本面验证报告.md", "点对时池", ["幸存者偏差", "价值", "质量"]),
    ("期权IV监控快照.md", "期权监控", ["IV", "VIX", "波动率"]),
    ("可转债双低策略回测报告.md", "可转债", ["双低", "可转债", "实盘候选"]),
    ("港股股息率策略验证报告.md", "港股", ["股息率", "分红"]),
    ("加密趋势策略验证报告.md", "加密", ["趋势", "动量", "时间序列"]),
    ("双动量ETF轮动验证报告.md", "ETF轮动", ["双动量", "ETF", "轮动"]),
    ("风险平价配置验证报告.md", "配置", ["风险平价", "资产配置", "底仓"]),
]

MOC = [
    "---",
    "tags:",
    "  - 量化交易",
    "  - 研究报告",
    "  - 分类索引",
    "---",
    "",
    "# 📊 星辰投研团 · 研究报告总览",
    "",
    "> 统一门控：事件研究/IC 为第一层证据，walk-forward 样本外（含成本、HAC t、DSR）为最终门控",
    "> 研究方法论：观点→假设→回测→证伪；不因 IC 好看就放松回测纪律",
    "",
    "## 研究结论速览（截至 2026-08-11）",
    "",
    "| 方向 | 第一层证据 | 最终门控（样本外） | 结论 |",
    "|------|-----------|-------------------|------|",
    "| A股 价格因子（动量/反转/低波/量能） | IC 弱 | DSR≈0 | 无净边际 |",
    "| 大佬信号（假突破/接针，含 v2） | v2 方向正确但弱 | DSR≈0 | 仅作监控信号 |",
    "| CTA 趋势跟踪（14 标的跨资产） | 半程不稳定 | DSR≈0 | 无净边际 |",
    "| 基本面价值/质量（300 只 A股） | 中性化 ICIR≈0.3 | DSR≈0 | 无净边际（池存在幸存者偏差） |",
    "| 点对时池（1111 只动态）价格因子 | 低波 ICIR≈-0.37 最强 | DSR≈0 | 幸存者偏差未改变方向 |",
    "| 点对时池基本面 | 价值 ICIR≈0.4 稳健；质量优势系幸存者偏差 | DSR≈0 | 无净边际 |",
    "| **可转债双低策略** | 6 变体全显著（HAC t 2.0-3.1） | **N=30/溢价≤30：夏普 1.01 / HAC t 3.08 / 回撤 -19.8%** | **首个实盘候选**（保守口径，2023/2026 偏弱） |",
    "| 可转债双低 + 信用过滤 | 2023 转正、2026 回撤减半 | N=30/溢价≤30：HAC t 3.03 / 月胜率 61% | 实盘候选（风控必选）|",
    "| 港股股息率（含分红总回报） | ICIR≈0.31（Moderate） | DSR≈0 | 无净边际 |",
    "| 加密周频趋势（16币/4年） | 修正波动率目标后年化仅 2-3% | 夏普 0.2 / DSR 0 | 无实质边际（早期高收益系失控杠杆假象） |",
    "| 双动量 ETF 轮动（精简池） | 22.7% / 夏普 1.16 / HAC t 2.54 | DSR 0.025（未过门控） | 观察级最强候选，建议模拟盘并行跟踪 |",
    "| 逆波动率风险平价（底仓） | 回撤 -5.8%（SPY 1/3）/ HAC t 2.21 | 夏普 0.71 略低于门槛 | 稳定型观察候选，与双低/双动量互补 |",
    "",
    "## 报告清单",
    "",
]

for src, cat, tags in REPORTS:
    p = os.path.join(ROOT, "docs", src)
    if not os.path.exists(p):
        continue
    os.makedirs(DEST, exist_ok=True)
    name = os.path.splitext(src)[0]
    text = open(p, encoding="utf-8").read()
    lines = text.splitlines()
    title = lines[0].lstrip("# ").strip() if lines and lines[0].startswith("# ") else name
    head = [
        "---",
        "tags:",
        "  - 量化交易",
        "  - 研究报告",
        f"  - {cat}",
    ]
    for t in tags:
        head.append(f"  - {t}")
    head += ["---", "", f"# {title}", "", "[[00_研究报告总览|← 返回总览]]", "", "---", ""]
    # 去掉原 H1（避免重复）
    if lines and lines[0].startswith("# "):
        lines.pop(0)
        while lines and not lines[0].strip():
            lines.pop(0)
    with open(os.path.join(DEST, name + ".md"), "w", encoding="utf-8") as f:
        f.write("\n".join(head + lines).rstrip() + "\n")
    MOC.append(f"- [[{name}|{title}]]")

MOC += ["", "---", "", "> 所有报告基于公开数据与规则化分析生成，仅供研究参考，不构成任何投资建议。", ""]
with open(os.path.join(DEST, "00_研究报告总览.md"), "w", encoding="utf-8") as f:
    f.write("\n".join(MOC))
print(f"已导出 {len(REPORTS)} 篇 → {DEST}")

if __name__ == "__main__":
    pass
