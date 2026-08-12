#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 每日量化学习流水线

每日抓取：GitHub 新量化项目（搜索 API）+ 精选博客 RSS（QuantStart/Quantocracy/
Alpha Architect/Ernie Chan/Quantpedia/AQR 等）→ 关键词打分筛选 → 生成学习笔记
（含一句话摘要与“可借鉴到本系统”提示）→ 同步 Obsidian → 入库跟踪。

用法:
    python3 scripts/learn_daily.py [--top 8]
输出:
    docs/学习笔记_日期.md + data/learning_log.parquet + data/learning_cache/文章全文
"""

import argparse
import html
import re
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
CFG = yaml.safe_load((ROOT / "config" / "learning_sources.yaml").read_text(encoding="utf-8"))
KEYWORDS = [k.strip() for k in CFG["keywords"][0].split(",") if k.strip()]
CACHE = ROOT / "data" / "learning_cache"
LOG = ROOT / "data" / "learning_log.parquet"
UA = {"User-Agent": "xingchen-learn/1.0"}


def score(text: str) -> int:
    t = text.lower()
    return sum(1 for k in KEYWORDS if k.lower() in t)


def parse_rss(url, timeout=15):
    """解析 RSS/Atom，返回 [(title, link, summary)]"""
    try:
        r = requests.get(url, headers=UA, timeout=timeout)
        r.raise_for_status()
        import xml.etree.ElementTree as ET
        root = ET.fromstring(r.content)
        items = []
        for it in root.iter():
            if it.tag.endswith("item") or it.tag.endswith("entry"):
                t = l = s = ""
                for child in it:
                    if child.tag.endswith("title"):
                        t = (child.text or "").strip()
                    elif child.tag.endswith("link") and l == "":
                        l = child.text or child.get("href", "")
                    elif child.tag.endswith(("description", "summary", "content")):
                        s = re.sub(r"<[^>]+>", " ", child.text or "")[:300]
                if t:
                    items.append((t, l, html.unescape(s)))
        return items
    except Exception:
        return []


def github_items(query, timeout=15):
    try:
        r = requests.get("https://api.github.com/search/repositories",
                         params={"q": query, "sort": "stars", "per_page": 5},
                         headers=UA, timeout=timeout)
        if r.status_code != 200:
            return []
        out = []
        for it in r.json().get("items", []):
            out.append((it["full_name"], it["html_url"],
                        (it.get("description") or "")[:200]))
        return out
    except Exception:
        return []


def fetch_article(url, timeout=15) -> str:
    try:
        r = requests.get(url, headers=UA, timeout=timeout)
        if r.status_code != 200:
            return ""
        text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", r.text, flags=re.S)
        text = re.sub(r"<[^>]+>", " ", text)
        text = html.unescape(re.sub(r"\s+", " ", text))
        return text[:3000]
    except Exception:
        return ""


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--top", type=int, default=8)
    args = p.parse_args()
    today = date.today().isoformat()
    items = []

    # RSS
    for src in CFG["rss"]:
        for t, l, s in parse_rss(src["url"]):
            items.append({"kind": "rss", "source": src["name"], "title": t,
                          "link": l, "summary": s, "score": score(f"{t} {s}")})
    # GitHub
    for q in CFG["github_queries"]:
        for name, link, desc in github_items(q):
            items.append({"kind": "github", "source": "GitHub", "title": name,
                          "link": link, "summary": desc, "score": score(f"{name} {desc}")})

    df = pd.DataFrame(items)
    if df.empty:
        print("今日无抓取结果（数据源可能超时）")
        return
    df = df[df["score"] > 0].sort_values("score", ascending=False).drop_duplicates("link")
    top = df.head(args.top).copy()

    # 缓存 top3 文章全文（离线精读用）
    CACHE.mkdir(parents=True, exist_ok=True)
    cached = []
    for _, r in top.head(3).iterrows():
        if r["kind"] != "rss":
            continue
        text = fetch_article(r["link"])
        if text:
            f = CACHE / f"{today}_{re.sub(r'[^\w\u4e00-\u9fff]+', '_', r['title'])[:40]}.txt"
            f.write_text(text, encoding="utf-8")
            cached.append(str(f))

    # 学习笔记
    lines = [
        f"# 每日量化学习 · {today}",
        "",
        f"> 来源：RSS 精选 + GitHub 新量化项目；共抓取 {len(df)} 条，筛选 {len(top)} 条",
        "> 筛选关键词：动量/价值/因子/回测/期权/波动率/风险/量化/加密/可转债/机器学习等",
        "",
        "## 今日要点",
        "",
        "| # | 标题 | 来源 | 一句话 | 可借鉴到本系统 |",
        "|---|------|------|--------|----------------|",
    ]
    for i, (_, r) in enumerate(top.iterrows(), 1):
        hint = "策略/因子/回测" if any(k in r["summary"].lower() for k in ("factor", "backtest", "momentum", "alpha")) \
            else "风控/组合" if any(k in r["summary"].lower() for k in ("risk", "portfolio", "volatility")) \
            else "研究参考"
        lines.append(f"| {i} | [{r['title']}]({r['link']}) | {r['source']} | {r['summary'][:80]} | {hint} |")
    if cached:
        lines += ["", "## 全文缓存（离线精读）", ""] + [f"- {c}" for c in cached]
    lines += [
        "",
        "## 学习建议",
        "",
        "- 每天挑 1-2 条与本系统策略相关的精读（看缓存全文）",
        "- 能写成可测假设的，进因子流水线验证（观点→假设→回测→证伪）",
        "- 与本系统无关的（喊单/荐股类）直接忽略",
        "",
        "> 自动抓取生成，仅作学习参考，不构成投资建议。",
        "",
    ]
    note = ROOT / "docs" / f"学习笔记_{today}.md"
    note.write_text("\n".join(lines), encoding="utf-8")

    # 同步 Obsidian（可选，Docker 内可通过 OBSIDIAN_VAULT 指定）
    vault = Path(__import__("os").environ.get("OBSIDIAN_VAULT",
        str(Path.home() / "Documents" / "Obsidian Vault")))
    dest_dir = vault / "量化交易" / "学习笔记"
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        (dest_dir / f"每日学习_{today}.md").write_text("\n".join(lines), encoding="utf-8")
    except Exception:
        pass

    # 入库
    top["date"] = today
    if LOG.exists():
        old = pd.read_parquet(LOG)
        top = pd.concat([old, top], ignore_index=True).drop_duplicates("link")
    top.to_parquet(LOG, index=False)

    print(f"已生成：{note}（{len(top)} 条，库累计 {len(top)} 条）")
    for _, r in top.head(5).iterrows():
        print(f"  [{r['source']}] {r['title'][:60]}")


if __name__ == "__main__":
    main()
