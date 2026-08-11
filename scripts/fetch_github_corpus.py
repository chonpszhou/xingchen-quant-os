#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · GitHub 量化交易全领域语料采集

用法:
    python3 scripts/fetch_github_corpus.py

输出:
    docs/github_quant_corpus.json   全量候选项目语料（含 README 摘要）

说明:
    - 优先使用 gh 已登录令牌（自动通过 `gh auth token` 获取），否则走公开限额
    - 覆盖 12 个领域约 50 组关键词，按 star 合并去重
"""

import json
import os
import re
import subprocess
import time

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
OUT = os.path.join(DOCS, "github_quant_corpus.json")

QUERIES = [
    # ---- 数据与接口 ----
    ("数据", "financial data api"),
    ("数据", "stock market data"),
    ("数据", "financial dataset"),
    ("数据", "market data python"),
    ("数据", "crypto market data"),
    ("数据", "期权数据"),
    ("数据", "stock data china"),
    # ---- 回测与框架 ----
    ("回测", "backtesting"),
    ("回测", "backtest framework"),
    ("回测", "trading backtest"),
    ("回测", "backtesting engine python"),
    ("回测", "event driven backtest"),
    ("回测", "A股回测"),
    # ---- 量化金融 ----
    ("金融工程", "quantitative finance"),
    ("金融工程", "quant library python"),
    ("金融工程", "financial engineering"),
    ("金融工程", "derivatives pricing"),
    ("金融工程", "options pricing"),
    ("金融工程", "volatility surface"),
    ("金融工程", "monte carlo finance"),
    # ---- 因子与组合 ----
    ("因子与组合", "factor investing"),
    ("因子与组合", "factor model"),
    ("因子与组合", "portfolio optimization"),
    ("因子与组合", "risk management quant"),
    ("因子与组合", "alphalens"),
    ("因子与组合", "fama french"),
    # ---- AI/ML 量化 ----
    ("AI量化", "machine learning trading"),
    ("AI量化", "deep learning stock prediction"),
    ("AI量化", "stock prediction"),
    ("AI量化", "reinforcement learning trading"),
    ("AI量化", "LLM trading agent"),
    ("AI量化", "AI quantitative trading"),
    ("AI量化", "time series forecasting stock"),
    # ---- 策略 ----
    ("策略", "trading strategies"),
    ("策略", "quant strategies"),
    ("策略", "pairs trading"),
    ("策略", "mean reversion trading"),
    ("策略", "momentum trading"),
    ("策略", "grid trading"),
    ("策略", "arbitrage trading"),
    ("策略", "technical analysis strategies"),
    # ---- 机器人/平台 ----
    ("交易机器人", "trading bot"),
    ("交易机器人", "crypto trading bot"),
    ("交易机器人", "stock trading bot"),
    ("交易机器人", "algorithmic trading"),
    ("交易机器人", "auto trading platform"),
    # ---- 技术分析 ----
    ("技术分析", "technical analysis"),
    ("技术分析", "trading indicators"),
    ("技术分析", "candlestick pattern"),
    ("技术分析", "缠论"),
    # ---- 加密专项 ----
    ("加密专项", "crypto arbitrage"),
    ("加密专项", "crypto signals"),
    ("加密专项", "on-chain analytics"),
    ("加密专项", "defi analytics"),
    ("加密专项", "cryptocurrency exchange api"),
    # ---- HFT/做市 ----
    ("高频做市", "high frequency trading"),
    ("高频做市", "market making"),
    ("高频做市", "order book analysis"),
    ("高频做市", "hft backtest"),
    # ---- 中国市场 ----
    ("A股专项", "股票量化"),
    ("A股专项", "股票数据"),
    ("A股专项", "量化交易"),
    ("A股专项", "龙虎榜"),
    ("A股专项", "股票分析系统"),
    # ---- 学习资源 ----
    ("学习资源", "quantitative trading book"),
    ("学习资源", "quant tutorial"),
    ("学习资源", "algorithmic trading book"),
    ("学习资源", "awesome quant"),
    ("学习资源", "finance python tutorial"),
]

SEARCH_URL = "https://api.github.com/search/repositories"
RAW_URL = "https://raw.githubusercontent.com/{full}/HEAD/{path}"


def get_token():
    if os.environ.get("GITHUB_TOKEN", "").strip():
        return os.environ["GITHUB_TOKEN"].strip()
    try:
        p = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=15)
        if p.returncode == 0 and p.stdout.strip():
            return p.stdout.strip()
    except Exception:
        pass
    return ""


TOKEN = get_token()
HEADERS = {"Accept": "application/vnd.github+json"}
if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"

RELEVANCE = re.compile(
    r"quant(?!um)|trad|backtest|financ|stock|market|portfolio|factor|strateg|option|"
    r"crypto|bitcoin|invest|broker|exchange|ohlc|kline|orderbook|algo|volatility|"
    r"derivative|pricing|monte|technical|indicator|candlestick|bollinger|momentum|"
    r"arbitrage|market.?making|high.?frequency|reinforcement|deep.?learning|machine.?learning|"
    r"neural|forecast|prediction|signal|sentiment|backtest|回测|量化|股票|基金|期权|"
    r"投资|策略|交易|期货|缠论|龙虎榜|行情|筹码|主力|资金",
    re.I,
)
EXCLUDE = re.compile(
    r"quantum|internship|jobs?|resume|hiring|typescript-eslint|bare-metal|"
    r"操作系统|面试|leetcode|算法题",
    re.I,
)

README_PATHS = [
    "README.md", "README.rst", "README.markdown", "readme.md",
    "README_CN.md", "README.zh-CN.md", "docs/README.md",
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
        params={"q": query, "sort": "stars", "order": "desc", "per_page": 30},
        headers=HEADERS,
        timeout=25,
    )
    if r.status_code == 403:
        raise RuntimeError("搜索配额耗尽: " + r.text[:200])
    r.raise_for_status()
    return r.json().get("items", [])


def readme_head(full_name):
    for path in README_PATHS:
        try:
            r = requests.get(RAW_URL.format(full=full_name, path=path), timeout=15)
            if r.status_code == 200:
                return r.text[:1200]
        except Exception:
            continue
    return ""


def main():
    os.makedirs(DOCS, exist_ok=True)
    merged = {}
    print(f"令牌状态: {'已认证(gh)' if TOKEN else '公开限额'} · 共 {len(QUERIES)} 组关键词\n")
    for i, (cat, q) in enumerate(QUERIES, 1):
        try:
            items = search(q)
            for it in items:
                fn = it["full_name"]
                if fn in merged:
                    item = merged[fn]
                    item["stars"] = max(item["stars"], it["stargazers_count"])
                    item["cats"].add(cat)
                else:
                    merged[fn] = {
                        "full_name": fn, "name": it["name"], "owner": it["owner"]["login"],
                        "stars": it["stargazers_count"], "forks": it["forks_count"],
                        "language": it.get("language"), "description": it.get("description"),
                        "topics": it.get("topics") or [], "url": it["html_url"],
                        "created_at": it.get("created_at"), "updated_at": it.get("updated_at"),
                        "cats": {cat},
                    }
            print(f"  [{i}/{len(QUERIES)}] {cat} · {q} -> {len(items)}")
        except Exception as e:
            print(f"  [{i}/{len(QUERIES)}] {cat} · {q} -> 失败 {type(e).__name__}: {str(e)[:90]}")
        time.sleep(2.2)

    candidates = [v for v in merged.values() if relevant(v)]
    candidates.sort(key=lambda v: -v["stars"])
    top = candidates[:250]
    for item in candidates:
        item["cats"] = sorted(item["cats"])
    print(f"\n候选 {len(candidates)} 个，前 250 抓取 README 摘要...")

    for i, item in enumerate(top, 1):
        item["readme_head"] = readme_head(item["full_name"])
        if i % 50 == 0 or i == len(top):
            print(f"  ...{i}/{len(top)}")
        time.sleep(0.3)

    payload = {
        "collected_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "queries": [{"category": c, "query": q} for c, q in QUERIES],
        "auth": bool(TOKEN),
        "total_candidates": len(candidates),
        "top_with_readme": top,
        "all_candidates": candidates,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    print(f"\n已保存: docs/github_quant_corpus.json（含 {len(candidates)} 个候选）")


if __name__ == "__main__":
    main()
