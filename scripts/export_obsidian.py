#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 导出到 Obsidian 库

用法:
    OBSIDIAN_VAULT="/path/to/vault" python3 scripts/export_obsidian.py

默认库路径: ~/Documents/Obsidian Vault
目标目录:   <vault>/量化交易/GitHub量化学习/

生成内容:
    - 00_GitHub量化学习总览.md（MOC）
    - 01~07 分类索引（按 7 大类）
    - 项目笔记/ 50 篇项目笔记（frontmatter + 定位 + 掌握要点 + 同类链接）
    - 项目资料/ 星辰投研团概览、连接检查清单、自选股说明、定时任务说明
"""

import json
import os
import re
import shutil
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
CONFIG = os.path.join(ROOT, "config")
VAULT = os.environ.get("OBSIDIAN_VAULT", os.path.expanduser("~/Documents/Obsidian Vault"))
DEST = os.path.join(VAULT, "量化交易", "GitHub量化学习")
NOTE_DIR = os.path.join(DEST, "项目笔记")
REF_DIR = os.path.join(DEST, "项目资料")

NOTE = os.path.join(DOCS, "量化交易GitHub顶级项目学习笔记.md")
DATASET = os.path.join(DOCS, "github_top50_dataset.json")

CATEGORY_META = {
    "01_数据源与行情接口": "数据源",
    "02_回测引擎与框架": "回测框架",
    "03_AI机器学习量化": "AI量化",
    "04_交易平台与机器人": "交易平台",
    "05_金融工程与衍生品": "金融工程",
    "06_策略库与学习资源": "策略库",
    "07_组合管理与投研应用": "组合管理",
}


def parse_note():
    text = open(NOTE, encoding="utf-8").read()
    table = {}
    in_table = False
    for line in text.splitlines():
        if line.startswith("## 一、"):
            in_table = True
            continue
        if line.startswith("## 二、"):
            in_table = False
        if in_table and line.startswith("|"):
            m = re.match(r"^\|\s*\d+\s*\|\s*\[([^\]]+)\]\(([^)]+)\)\s*\|\s*([0-9,]+)\s*\|\s*([^|]+?)\s*\|\s*(.+?)\s*\|$", line)
            if m:
                name, url, stars, lang, desc = m.groups()
                full = url.rstrip("/").split("github.com/")[-1]
                table[full] = {
                    "full": full,
                    "short": full.split("/")[-1],
                    "stars": int(stars.replace(",", "")),
                    "lang": lang,
                    "desc": desc.strip(),
                    "url": url,
                    "category": None,
                    "cat_file": None,
                    "cat_tag": None,
                    "lead": "",
                    "points": "",
                }

    sections = re.split(r"^### ([A-G])\. (.+?)（(\d+) 个）\s*$", text, flags=re.M)
    # sections: [前文, letter, title, count, body, letter, ...]
    cat_files = list(CATEGORY_META)
    for i in range(1, len(sections), 4):
        letter, title, count, body = sections[i], sections[i + 1], int(sections[i + 2]), sections[i + 3]
        cat_file = cat_files[ord(letter) - ord("A")]
        cat_tag = CATEGORY_META[cat_file]
        para = re.search(r"\*\*共同范式\*\*：(.+?)(?:\n\n|\n-)", body, re.S)
        paradigm = para.group(1).strip() if para else ""
        bullets = re.findall(r"^- \*\*(.+?)\*\*（★([^）]+)）：(.+)$", body, re.M)
        for bname, bstars, btext in bullets:
            entries = []
            if " / " in bstars:
                for part in bstars.split(" / "):
                    entries.append((bname, re.sub(r"[★\s]", "", part), btext))
            else:
                entries.append((bname, bstars, btext))
            for ename, estars, etext in entries:
                matched = None
                for full, item in table.items():
                    if item["short"] == ename or item["full"] == ename:
                        if matched is None or item["stars"] == int(estars.replace(",", "")):
                            matched = item
                if matched:
                    matched["category"] = title
                    matched["cat_file"] = cat_file
                    matched["cat_tag"] = cat_tag
                    matched["paradigm"] = paradigm
                    if "**掌握要点**" in etext:
                        lead, _, points = etext.partition("**掌握要点**")
                        matched["lead"] = lead.strip().rstrip("：")
                        matched["points"] = points.strip().lstrip("：").strip()
                    else:
                        matched["lead"] = etext.strip()
                        matched["points"] = ""
    return table


def fmt_stars(n):
    return f"{n:,}"


def project_note(item):
    fname = item["full"].replace("/", "_") + ".md"
    lines = [
        "---",
        "tags:",
        "  - 量化交易",
        "  - GitHub学习",
        f"  - {item['cat_tag']}",
        f"stars: {item['stars']}",
        f"language: {item['lang']}",
        f"repo: {item['url']}",
        f"category: {item['category']}",
        "---",
        "",
        f"# {item['short']}",
        "",
        f"> ★ {fmt_stars(item['stars'])} · {item['lang']} · [GitHub]({item['url']})  ",
        f"> 分类：[[{item['cat_file']}|{item['category']}]]",
        "",
        "## 一句话定位",
        "",
        item["desc"],
        "",
    ]
    if item.get("lead"):
        lines += ["## 定位与背景", "", item["lead"], ""]
    if item.get("points"):
        lines += ["## 掌握要点", "", item["points"], ""]
    lines += ["## 同类项目", ""]
    for other in same_category_items(item):
        if other is not item:
            lines.append(f"- [[{other['full'].replace('/', '_')}|{other['short']}]] ★ {fmt_stars(other['stars'])}")
    lines += [
        "",
        "---",
        "",
        "返回：[[00_GitHub量化学习总览]]",
        "",
    ]
    return fname, "\n".join(lines)


def same_category_items(item):
    return [x for x in table.values() if x["cat_file"] == item["cat_file"]]


def category_moc(cat_file, items):
    title = cat_file.split("_", 1)[1]
    tag = CATEGORY_META[cat_file]
    paradigm = next((i["paradigm"] for i in items if i.get("paradigm")), "")
    lines = [
        "---",
        "tags:",
        "  - 量化交易",
        "  - GitHub学习",
        "  - 分类索引",
        "---",
        "",
        f"# {title}（{len(items)} 个项目）",
        "",
        f"> 标签：`{tag}`",
        "",
    ]
    if paradigm:
        lines += ["## 共同范式", "", paradigm, ""]
    lines += ["## 项目清单", ""]
    for it in sorted(items, key=lambda x: -x["stars"]):
        lines.append(f"- [[{it['full'].replace('/', '_')}|{it['short']}]] ★ {fmt_stars(it['stars'])} — {it['desc']}")
    lines += ["", "---", "", "返回：[[00_GitHub量化学习总览]]", ""]
    return cat_file + ".md", "\n".join(lines)


def root_moc():
    lines = [
        "---",
        "tags:",
        "  - 量化交易",
        "  - GitHub学习",
        "  - 分类索引",
        "---",
        "",
        "# 📚 GitHub 量化学习 · 总览（Top 50）",
        "",
        "> 整理时间：2026-08-11",
        "> 数据口径：GitHub 公开搜索（13 组关键词）按 star 排序；剔除非量化噪声项目",
        "> 原始数据：`星辰投研团/docs/github_top50_dataset.json`（项目仓库内）",
        "",
        "## 分类导航",
        "",
    ]
    for cat_file in CATEGORY_META:
        items = [x for x in table.values() if x["cat_file"] == cat_file]
        title = cat_file.split("_", 1)[1]
        lines.append(f"- [[{cat_file}|{title}]]（{len(items)} 个）")
    lines += [
        "",
        "## 学习路线（六阶段）",
        "",
        "1. **数据关**：akshare + tushare + ccxt 跑通五类标的（A股/港股/美股/加密/期权）",
        "2. **回测关**：backtesting.py → backtrader → vectorbt → rqalpha",
        "3. **策略/因子关**：复现 je-suis-tm 经典策略；qlib 跑通 Alpha 因子管线",
        "4. **衍生品关**：Financial-Models 过期权定价；gs-quant 学 IV 与希腊字母",
        "5. **实盘/风控关**：vnpy、freqtrade dry-run，重点练仓位/止损/回撤熔断",
        "6. **AI/LLM 关**：拆解 Vibe-Trading、QuantDinger、daily_stock_analysis 的 Agent 编排",
        "",
        "## 项目资料",
        "",
        "- [[星辰投研团_项目概览]]",
        "- [[数据源与推送_连接检查清单]]",
        "- [[默认自选股清单_说明]]",
        "- [[自动化定时分析任务_说明]]",
        "",
        "---",
        "",
        "> 风险提示：部分项目已归档（gekko、zipline、pyalgotrade），学习架构思想即可；内容仅供学习参考，不构成投资建议。",
        "",
    ]
    return "00_GitHub量化学习总览.md", "\n".join(lines)


def ref_project_overview():
    readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
    lines = [
        "---",
        "tags: [量化交易, 星辰投研团, 项目资料]",
        "---",
        "",
        "# 星辰投研团 · 项目概览",
        "",
        "> 项目位置：`~/Documents/ChatGPT/量化交易/星辰投研团`",
        "",
    ]
    lines += readme.splitlines()
    return "星辰投研团_项目概览.md", "\n".join(lines)


def ref_connection_check():
    report = open(os.path.join(DOCS, "连接检查报告.md"), encoding="utf-8").read()
    lines = [
        "---",
        "tags: [量化交易, 星辰投研团, 数据源]",
        "---",
        "",
    ]
    lines += report.splitlines()
    return "数据源与推送_连接检查清单.md", "\n".join(lines)


def ref_watchlist():
    wl = json.load(open(os.path.join(CONFIG, "watchlist.json"), encoding="utf-8"))
    recs = wl["records"]
    from collections import Counter
    by_market = Counter(r["market"] for r in recs)
    by_group = Counter(r["group"] for r in recs)
    lines = [
        "---",
        "tags: [量化交易, 星辰投研团, 自选股]",
        "---",
        "",
        "# 默认自选股清单 · 说明",
        "",
        "> 结构化数据文件：`config/watchlist.json`（64 条）与 `config/watchlist.csv`",
        "",
        "## 覆盖范围",
        "",
        "| 板块 | 数量 |",
        "|------|------|",
    ]
    for m in ("A股", "港股", "美股", "虚拟货币", "期货", "期权"):
        lines.append(f"| {m} | {by_market.get(m, 0)} |")
    lines += ["", "## 分组", ""]
    for g in ("核心持仓", "观察池", "行业基准", "期权工具"):
        lines.append(f"- {g}：{by_group.get(g, 0)} 条")
    lines += [
        "",
        "## 代码格式",
        "",
        "- A股：6 位数字（兼容 akshare/东方财富）",
        "- 港股：5 位数字含前导 0（如 00700）",
        "- 美股：Yahoo 代码（如 AAPL）",
        "- 虚拟货币：ccxt 交易对（如 BTC/USDT）",
        "- 期权：标的池（50ETF/300ETF 期权、IO/IM 股指期权、AAPL/NVDA/SPY 期权链、BTC/ETH 加密期权）",
        "",
        "## 与自动化任务的关系",
        "",
        "自选股清单是 `config/tasks.yaml` 全部定时任务的扫描范围，导入配置后即可直接参与异动/收盘/周报分析。",
        "",
    ]
    return "默认自选股清单_说明.md", "\n".join(lines)


def ref_tasks():
    tasks = yaml.safe_load(open(os.path.join(CONFIG, "tasks.yaml"), encoding="utf-8"))["tasks"]
    lines = [
        "---",
        "tags: [量化交易, 星辰投研团, 自动化]",
        "---",
        "",
        "# 自动化定时分析任务 · 说明",
        "",
        "> 完整参数见项目内 `config/tasks.yaml`",
        "",
        "| 任务 | cron | 主要分析维度 | 触发推送条件 |",
        "|------|------|-------------|-------------|",
    ]
    for t in tasks:
        dims = "；".join(t["analysis"]) if isinstance(t["analysis"], list) else "见配置文件"
        dims = dims.replace("|", "／").replace("\n", " ")
        if len(dims) > 90:
            dims = dims[:90] + "…"
        push = "见配置文件"
        if isinstance(t.get("push"), dict) and "rules" in t["push"]:
            push = "；".join(f"「{r.get('condition','')}」" for r in t["push"]["rules"][:3])
        elif isinstance(t.get("push"), dict) and "channel" in t["push"]:
            push = "定时推送 " + "+".join(t["push"]["channel"])
        lines.append(f"| {t['name']} | `{t['cron']}` | {dims} | {push} |")
    lines += [
        "",
        "## 落地方式",
        "",
        "- **cron**：直接使用各任务 cron 表达式",
        "- **APScheduler**：`pip install apscheduler`，由调度器读取 tasks.yaml",
        "- **Codex 定时提醒**：可在 Codex 应用内创建",
        "",
    ]
    return "自动化定时分析任务_说明.md", "\n".join(lines)


def write(path, content):
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def main():
    global table
    table = parse_note()
    complete = [x for x in table.values() if x["category"]]
    if len(complete) != 50:
        print(f"警告: 分类解析 {len(complete)}/50", file=sys.stderr)
        missing = [x["full"] for x in table.values() if not x["category"]]
        if missing:
            print("未分类:", missing, file=sys.stderr)

    os.makedirs(NOTE_DIR, exist_ok=True)
    os.makedirs(REF_DIR, exist_ok=True)
    written = 0

    for item in table.values():
        fname, content = project_note(item)
        write(os.path.join(NOTE_DIR, fname), content)
        written += 1

    for cat_file in CATEGORY_META:
        items = [x for x in table.values() if x["cat_file"] == cat_file]
        fname, content = category_moc(cat_file, items)
        write(os.path.join(DEST, fname), content)
        written += 1

    fname, content = root_moc()
    write(os.path.join(DEST, fname), content)
    written += 1

    for fn in (ref_project_overview, ref_connection_check, ref_watchlist, ref_tasks):
        fname, content = fn()
        write(os.path.join(REF_DIR, fname), content)
        written += 1

    print(f"已写入 {written} 个文件 → {DEST}")


if __name__ == "__main__":
    main()
