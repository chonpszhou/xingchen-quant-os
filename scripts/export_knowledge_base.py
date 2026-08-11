#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 量化知识库导出到 Obsidian

用法:
    OBSIDIAN_VAULT="/path/to/vault" python3 scripts/export_knowledge_base.py

目标目录: <vault>/量化交易/量化知识库/
生成: 00_总览 + 12 篇分类笔记 + 全文副本
"""

import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
DOC = os.path.join(DOCS, "量化交易GitHub知识库.md")
VAULT = os.environ.get("OBSIDIAN_VAULT", os.path.expanduser("~/Documents/Obsidian Vault"))
DEST = os.path.join(VAULT, "量化交易", "量化知识库")


def parse_doc():
    text = open(DOC, encoding="utf-8").read()
    parts = re.split(r"^### (C\d+) · (.+)$", text, flags=re.M)
    sections = []
    for i in range(1, len(parts), 3):
        cid, title, body = parts[i], parts[i + 1], parts[i + 2]
        points = []
        projects = []
        for line in body.splitlines():
            m = re.match(r"^- (.+)$", line)
            if m:
                p = re.match(r"^\*\*(.+?)\*\*（★([0-9,]+)）：(.+)$", m.group(1))
                if p:
                    projects.append((p.group(1), p.group(2), p.group(3)))
                else:
                    points.append(m.group(1))
        sections.append({"id": cid, "title": title, "points": points, "projects": projects})
    return sections


def category_note(sec):
    safe = sec["title"].replace("/", "_").replace("\\", "_")
    lines = [
        "---",
        "tags:",
        "  - 量化交易",
        "  - 量化知识库",
        "---",
        "",
        f"# {sec['id']} · {sec['title']}",
        "",
        "## 关键认知",
        "",
    ]
    for p in sec["points"]:
        lines.append(f"- {p}")
    lines += ["", "## 代表项目", ""]
    for name, stars, desc in sec["projects"]:
        lines.append(f"- **{name}**（★{stars}）：{desc}")
    lines += ["", "---", "", "返回：[[00_量化知识库总览]]", ""]
    return f"{sec['id']}_{safe}.md", "\n".join(lines)


def moc(sections):
    lines = [
        "---",
        "tags:",
        "  - 量化交易",
        "  - 量化知识库",
        "  - 分类索引",
        "---",
        "",
        "# 🧠 量化交易 GitHub 知识库（12 大分类）",
        "",
        "> 语料：69 组关键词 × 12 领域，1523 个候选项目，前 250 带 README 摘要",
        "> 全文：[[00_量化交易GitHub知识库_全文]]",
        "",
        "## 分类导航",
        "",
    ]
    for sec in sections:
        safe = sec["title"].replace("/", "_").replace("\\", "_")
        lines.append(f"- [[{sec['id']}_{safe}|{sec['id']} · {sec['title']}]]（{len(sec['projects'])} 个代表项目）")
    lines += [
        "",
        "## 三大趋势",
        "",
        "1. **LLM 多智能体爆发**：TradingAgents（97k★）/ Vibe-Trading / QuantDinger，Agent 化研究是当前最大增长点",
        "2. **数据与工程化为主线**：yfinance / FinanceDatabase / free-stockdb，数据管线决定研究下限",
        "3. **多市场专业化 + A股生态繁荣**：加密多所（ccxt/passivbot）、A股全栈（vnpy/QUANTAXIS/adata）",
        "",
        "## 反模式速记",
        "",
        "- 数据先于策略；预测类项目防过拟合；机器人风控普遍缺失；勿用归档项目生产；回测口径必须统一",
        "",
        "## 与本项目结合",
        "",
        "- 星辰投研团 = 数据源检查 + 自选股 + 自动化任务（数据/调度层）",
        "- paddy-quant-workbench = 行情/信号/回测/GEX/研报（信号/执行层）",
        "- 待建：数据落库、因子流水线、风控执行层",
        "",
        "---",
        "",
        "> 学习路线：C1/C2 数据与回测 → C3/C5 策略与 ML → C6/C7 衍生品与组合 → C4 实盘与风控",
        "",
    ]
    return "00_量化知识库总览.md", "\n".join(lines)


def main():
    sections = parse_doc()
    if len(sections) != 12:
        print(f"警告: 解析到 {len(sections)}/12 个分类", file=sys.stderr)
    os.makedirs(DEST, exist_ok=True)
    for sec in sections:
        fname, content = category_note(sec)
        with open(os.path.join(DEST, fname), "w", encoding="utf-8") as f:
            f.write(content)
    fname, content = moc(sections)
    with open(os.path.join(DEST, fname), "w", encoding="utf-8") as f:
        f.write(content)
    shutil.copyfile(DOC, os.path.join(DEST, "00_量化交易GitHub知识库_全文.md"))
    print(f"已写入 {len(sections) + 2} 个文件 → {DEST}")


if __name__ == "__main__":
    main()
