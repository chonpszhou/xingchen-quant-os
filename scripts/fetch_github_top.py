#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · GitHub 量化交易领域 top 项目数据采集

用法:
    python3 scripts/fetch_github_top.py

输出:
    docs/github_top50_dataset.json   候选项目列表（含 star/语言/简介/README 摘要）

说明:
    - 使用 GitHub 公开 REST API，无需令牌（若配置 GITHUB_TOKEN 则自动使用，限额更高）
    - 搜索 13 组关键词 → 合并去重 → 按 star 排序 → 抓取 README 摘要
"""

import json
import os
import re
import time

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
OUT = os.path.join(DOCS, "github_top50_dataset.json")

QUERIES = [
    "quantitative trading",
    "quantitative finance",
    "algorithmic trading",
    "backtesting",
    "backtest framework",
    "trading bot",
    "stock trading",
    "factor investing",
    "option trading",
    "quant",
    "crypto trading bot",
    "量化交易",
    "股票量化",
]

SEARCH_URL = "https://api.github.com/search/repositories"
RAW_URL = "https://raw.githubusercontent.com/{full}/HEAD/{path}"

HEADERS = {"Accept": "application/vnd.github+json"}
TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"

RELEVANCE = re.compile(
    r"quant(?!um)|trad|backtest|financ|stock|market|portfolio|factor|strateg|option|"
    r"crypto|bitcoin|invest|broker|exchange|ohlc|kline|orderbook|algo|"
    r"交易|量化|股票|基金|期权|投资|策略|回测|A股|美股",
    re.I,
)
EXCLUDE = re.compile(r"quantum|kubernetes|typescript-eslint|quantumult", re.I)

README_PATHS = [
    "README.md",
    "README.rst",
    "README.markdown",
    "readme.md",
    "README_CN.md",
    "README.zh-CN.md",
    "docs/README.md",
]


def relevant(item):
    text = " ".join([
        item.get("name", ""),
        item.get("description", "") or "",
        " ".join(item.get("topics", []) or []),
    ])
    return bool(RELEVANCE.search(text)) and not EXCLUDE.search(text)


def search(query):
    r = requests.get(
        SEARCH_URL,
        params={"q": query, "sort": "stars", "order": "desc", "per_page": 15},
        headers=HEADERS,
        timeout=20,
    )
    r.raise_for_status()
    return r.json().get("items", [])


def readme_head(full_name):
    for path in README_PATHS:
        try:
            r = requests.get(RAW_URL.format(full=full_name, path=path), timeout=15)
            if r.status_code == 200:
                return r.text[:1800]
        except Exception:
            continue
    return ""


def main():
    os.makedirs(DOCS, exist_ok=True)
    merged = {}
    print("搜索关键词中...")
    for i, q in enumerate(QUERIES):
        try:
            items = search(q)
            for it in items:
                fn = it["full_name"]
                if fn in merged:
                    merged[fn]["stars"] = max(merged[fn]["stars"], it["stargazers_count"])
                else:
                    merged[fn] = {
                        "full_name": fn,
                        "name": it["name"],
                        "owner": it["owner"]["login"],
                        "stars": it["stargazers_count"],
                        "forks": it["forks_count"],
                        "language": it.get("language"),
                        "description": it.get("description"),
                        "topics": it.get("topics") or [],
                        "url": it["html_url"],
                        "updated_at": it.get("updated_at"),
                        "pushed_at": it.get("pushed_at"),
                    }
            print(f"  [{i+1}/{len(QUERIES)}] {q} -> 命中 {len(items)}")
        except Exception as e:
            print(f"  [{i+1}/{len(QUERIES)}] {q} -> 失败 {type(e).__name__}: {str(e)[:90]}")
        time.sleep(7)  # 未认证搜索限额 10 次/分钟

    candidates = [v for v in merged.values() if relevant(v)]
    candidates.sort(key=lambda v: v["stars"], reverse=True)
    top = candidates[:60]
    print(f"\n候选项目 {len(candidates)} 个，取前 60 抓取 README...")

    for i, item in enumerate(top):
        item["readme_head"] = readme_head(item["full_name"])
        print(f"  [{i+1}/{len(top)}] {item['stars']:>8,} ★ {item['full_name']}")
        time.sleep(0.5)

    payload = {
        "collected_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "queries": QUERIES,
        "total_candidates": len(candidates),
        "top": top,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\n已保存: docs/github_top50_dataset.json")


if __name__ == "__main__":
    main()
