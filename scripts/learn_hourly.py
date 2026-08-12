#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 每小时轻学习

从每日学习池（learning_log.parquet）取一篇未读条目，提炼「学习成果卡片」：
核心观点 / 可借鉴点 / 可测假设（初稿，精读由 Agent/人工跟进）。
结果实时追加到：
  - docs/学习日志_日期.md（看板「学习」页展示）
  - Obsidian 量化交易/学习日志/
  - data/learning_hourly.parquet（入库）
  - 可选：推送（配置推送通道后每小时推送）

用法:
    python3 scripts/learn_hourly.py
"""

import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
CFG = yaml.safe_load((ROOT / "config" / "learning_sources.yaml").read_text(encoding="utf-8"))
KEYWORDS = [k.strip() for k in CFG["keywords"][0].split(",") if k.strip()]
LOG = ROOT / "data" / "learning_log.parquet"
HOURLY = ROOT / "data" / "learning_hourly.parquet"
PROC = ROOT / "data" / "learning_processed.json"
UA = {"User-Agent": "xingchen-learn/1.0"}


def load_processed() -> set:
    if PROC.exists():
        return set(json.loads(PROC.read_text(encoding="utf-8")))
    return set()


def save_processed(s):
    PROC.write_text(json.dumps(sorted(s), ensure_ascii=False), encoding="utf-8")


def light_fetch():
    """池耗尽时轻量补充：取第一个 RSS 源最新条目"""
    import xml.etree.ElementTree as ET
    try:
        r = requests.get(CFG["rss"][0]["url"], headers=UA, timeout=12)
        root = ET.fromstring(r.content)
        out = []
        for it in root.iter():
            if it.tag.endswith("item") or it.tag.endswith("entry"):
                t = l = ""
                for c in it:
                    if c.tag.endswith("title"):
                        t = (c.text or "").strip()
                    elif c.tag.endswith("link") and not l:
                        l = c.text or c.get("href", "")
                if t:
                    out.append({"kind": "rss", "source": CFG["rss"][0]["name"],
                                "title": t, "link": l, "summary": "", "score": 1})
                if len(out) >= 3:
                    break
        return out
    except Exception:
        return []


def distill(item):
    """提炼成果卡片：核心观点/可借鉴/可测假设（初稿）"""
    text = f"{item.get('title', '')} {item.get('summary', '')}"
    low = text.lower()
    core = (item.get("summary") or "").strip()[:120] or "（无摘要，待精读）"
    tags = [k for k in KEYWORDS if k.lower() in low]
    hints = []
    if "momentum" in low or "动量" in low:
        hints.append("动量因子在 X 市场 20/60 日窗口 IC 对比（走本系统门控）")
    if "backtest" in low or "回测" in low:
        hints.append("检验其回测方法是否含前视偏差（对照本系统 walk-forward 门控）")
    if "factor" in low or "因子" in low:
        hints.append("把论文因子写成无未来函数定义，走 IC/分位门控")
    if "options" in low or "期权" in low or "volatility" in low:
        hints.append("期权 IV 分位/偏斜与本系统 CBOE 快照联动监控")
    if "risk" in low or "portfolio" in low or "组合" in low:
        hints.append("其组合/风控方法与三策略组合（收益/趋势/稳定）对照")
    if not hints:
        hints.append("先精读全文，再定可测假设")
    return {
        "core": core,
        "tags": tags[:5],
        "hints": list(dict.fromkeys(hints[:4])),
    }


def main():
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    hour = now.strftime("%H:00")
    if not LOG.exists():
        print("学习池为空，先运行 learn_daily.py")
        return
    pool = pd.read_parquet(LOG).drop_duplicates("link")
    processed = load_processed()
    unread = pool[~pool["link"].isin(processed)]
    if unread.empty:
        fresh = light_fetch()
        if fresh:
            fresh_df = pd.DataFrame(fresh)
            pool = pd.concat([pool, fresh_df], ignore_index=True).drop_duplicates("link")
            pool.to_parquet(LOG, index=False)
            unread = pool[~pool["link"].isin(processed)]
    if unread.empty:
        print("暂无未读内容（池已读完）")
        return
    item = unread.iloc[0].to_dict()
    processed.add(item["link"])
    save_processed(processed)
    d = distill(item)

    entry = [
        f"### {hour} · {item['source']}",
        f"- 标题：[{item['title']}]({item['link']})",
        f"- 核心观点（初稿）：{d['core']}",
        f"- 标签：{'、'.join(d['tags']) or '—'}",
        f"- 可测假设：{'；'.join(d['hints'])}",
        "",
    ]
    log_file = ROOT / "docs" / f"学习日志_{today}.md"
    header = [f"# 每小时学习日志 · {today}", "", ""]
    if not log_file.exists():
        log_file.write_text("\n".join(header), encoding="utf-8")
    with open(log_file, "a", encoding="utf-8") as f:
        f.write("\n".join(entry))

    # Obsidian 追加
    vault = Path(__import__("os").environ.get("OBSIDIAN_VAULT",
        str(Path.home() / "Documents" / "Obsidian Vault")))
    try:
        dest_dir = vault / "量化交易" / "学习日志"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"学习日志_{today}.md"
        if not dest.exists():
            dest.write_text("\n".join(header), encoding="utf-8")
        with open(dest, "a", encoding="utf-8") as f:
            f.write("\n".join(entry))
    except Exception:
        pass

    # 入库
    row = pd.DataFrame([{"date": today, "hour": hour, "source": item["source"],
                         "title": item["title"], "link": item["link"],
                         "core": d["core"], "tags": "、".join(d["tags"]),
                         "hints": "；".join(d["hints"])}])
    if HOURLY.exists():
        row = pd.concat([pd.read_parquet(HOURLY), row], ignore_index=True)
    row.to_parquet(HOURLY, index=False)

    # 可选推送（已配置通道时）
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        from push_digest import load_env
        env = load_env()
        if any(env.get(k) for k in ("PUSHPLUS_TOKEN", "SERVERCHAN_KEY", "FEISHU_WEBHOOK", "MAIL_TO")):
            import subprocess
            msg = f"[{hour}] 学习成果：{item['title']}\n{d['core']}\n可测假设：{'；'.join(d['hints'])}"
            subprocess.Popen([sys.executable, str(ROOT / "scripts" / "push_digest.py"),
                              "--text", msg], cwd=ROOT)
    except Exception:
        pass

    print(f"[{hour}] 学习成果已记录：{item['title'][:50]}")
    print(f"  核心：{d['core'][:80]}")
    print(f"  可测假设：{'；'.join(d['hints'])}")


if __name__ == "__main__":
    main()
