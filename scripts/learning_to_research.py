#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
学习→研究 闭环桥接器（星辰投研团）

把每日/每小时学习产出的「可测假设」真正接回研究驱动扫描，
实现之前只停留在文本/Obsidian 笔记里的「观点→假设→回测→证伪」闭环。

设计原则（不编造）：
  1. 只把【明确提到本系统宇宙标的】且【能识别多空立场】的学习条目，
     转成与研究文件同构的 CandidateView（写入 config/learning_views.json）。
  2. 通用因子/方法类假设（不指名具体标的）→ 记为 unmapped，供人工跟进，
     绝不凭空造一个 ticker 塞进扫描。
  3. 学习派生观点的共识分由立场推导（看多=60 / 看空=40），并显式标注
     source="learning-derived" + risks 提示「未经研究员共识，仅作候选」。
  4. 幂等：每次重跑覆盖写，不产生重复。

产出：
  - config/learning_views.json        （与 research_views.json 同构，供 --learning 合并）
  - 星辰 data/learning_research_bridge.json  （ ingested / unmapped 统计，供看板/排错）
  - 同时镜像一份到 paddy-quant-workbench/config/learning_views.json（权威引擎同源消费）

用法:
    python3 scripts/learning_to_research.py
    python3 scripts/learning_to_research.py --dry   # 只打印不写文件
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# paddy 权威内核（同机兄弟目录），用于镜像同一份 learning_views
PADDY_CFG = Path("/Users/zhoupeng/WorkBuddy/量化交易/paddy-quant-workbench/config/learning_views.json")

# ---- 本系统宇宙标的别名表（学习文本里可能出现的写法 → 标准代码/市场/名称）----
UNIVERSE = [
    ("600519", "a", "贵州茅台", ["600519", "茅台", "贵州茅台"]),
    ("00700", "hk", "腾讯控股", ["00700", "腾讯", "腾讯控股"]),
    ("AAPL", "us", "苹果", ["AAPL", "苹果", "Apple", "苹果公司"]),
    ("BTCUSDT", "crypto", "比特币", ["BTCUSDT", "BTC", "比特币", "Bitcoin"]),
    ("ETHUSDT", "crypto", "以太坊", ["ETHUSDT", "ETH", "以太坊", "Ethereum"]),
    ("BNBUSDT", "crypto", "BNB", ["BNBUSDT", "BNB"]),
    ("SOLUSDT", "crypto", "SOL", ["SOLUSDT", "SOL", "Solana"]),
    ("ADAUSDT", "crypto", "ADA", ["ADAUSDT", "ADA", "Cardano", "艾达币"]),
]

BULL = ["看多", "做多", "long", "bullish", "买入", "看好", "上扬", "突破", "多头", "逢低买"]
BEAR = ["看空", "做空", "short", "bearish", "卖出", "看淡", "下行", "跌破", "空头", "减仓"]


def _detect_direction(text: str):
    low = text.lower()
    b = any(k.lower() in low for k in BULL)
    r = any(k.lower() in low for k in BEAR)
    if b and r:
        return "neutral"  # 多空冲突 → 不编造方向
    if b:
        return "long"
    if r:
        return "short"
    return None


def _match_universe(text: str):
    """返回 (ticker, market, name) 或 None（取首个命中的别名）。

    短别名(≤3字符, 如 ETH/BTC/SOL/ADA)用词边界匹配，避免误中
    together/Alpha 等；长别名(ETHUSDT/Solana/贵州茅台)用子串匹配。
    全局按别名长度降序，确保 ETHUSDT 先于 ETH 命中。
    """
    low = text.lower()
    order = sorted(
        ((al, tk, mk, nm) for tk, mk, nm, als in UNIVERSE for al in als),
        key=lambda x: len(x[0]), reverse=True,
    )
    for al, tk, mk, nm in order:
        if len(al) <= 3:
            if re.search(r"(?<![\w])" + re.escape(al.lower()) + r"(?![\w])", low):
                return tk, mk, nm
        elif al.lower() in low:
            return tk, mk, nm
    return None


def _consensus_of(direction: str) -> float:
    return {"long": 60.0, "short": 40.0, "neutral": 50.0}.get(direction, 50.0)


def _signal_dist(direction: str) -> dict:
    if direction == "long":
        return {"bullish": 3, "neutral": 1, "bearish": 1}
    if direction == "short":
        return {"bullish": 1, "neutral": 1, "bearish": 3}
    return {"bullish": 1, "neutral": 2, "bearish": 1}


def _iter_markdown_docs():
    """学习笔记 / 学习日志 逐篇读取文本"""
    for pat in ("学习笔记_*.md", "学习日志_*.md"):
        for f in sorted((ROOT / "docs").glob(pat), reverse=True):
            try:
                yield f.name, f.read_text(encoding="utf-8")
            except Exception:
                continue


def _iter_parquet():
    """可选：learning_hourly / learning_log 的 parquet（需 pandas）"""
    try:
        import pandas as pd  # noqa
    except Exception:
        return
    for p in ("data/learning_hourly.parquet", "data/learning_log.parquet"):
        fp = ROOT / p
        if not fp.exists():
            continue
        try:
            df = pd.read_parquet(fp)
        except Exception:
            continue
        cols = [c for c in ("title", "link", "core", "hints", "summary", "thesis") if c in df.columns]
        for _, row in df.iterrows():
            txt = " ".join(str(row.get(c, "")) for c in cols if pd.notna(row.get(c)))
            yield fp.name, txt


def build(dry: bool = False):
    ingested, unmapped = [], []
    seen = set()
    sources = list(_iter_markdown_docs()) + list(_iter_parquet())

    for src, text in sources:
        # 按条切分（学习日志以 ### 为条；学习笔记以表格行 | 为条）
        chunks = re.split(r"(?m)^###\s|^[|]\s", text)
        if len(chunks) <= 1:
            chunks = [text]
        for ch in chunks:
            if not ch.strip():
                continue
            u = _match_universe(ch)
            if not u:
                # 含「可测假设」「因子」「回测」等关键词但无标的 → 记 unmapped
                if any(k in ch for k in ("可测假设", "factor", "因子", "backtest", "回测", "momentum", "动量")):
                    snippet = ch.strip().replace("\n", " ")[:80]
                    if snippet and snippet not in unmapped:
                        unmapped.append(snippet)
                continue
            ticker, market, name = u
            if ticker in seen:
                continue
            direction = _detect_direction(ch)
            if direction is None:
                # 提到标的但无立场 → 不编造，记 unmapped
                snippet = ch.strip().replace("\n", " ")[:80]
                if snippet and snippet not in unmapped:
                    unmapped.append(f"[提及{name}但无立场] {snippet}")
                continue
            seen.add(ticker)
            view = {
                "ticker": ticker,
                "market": market,
                "name": name,
                "panel_consensus": _consensus_of(direction),
                "signal_distribution": _signal_dist(direction),
                "thesis": f"（学习派生）{ch.strip().replace(chr(10), ' ')[:60]}",
                "risks": ["学习派生假设，未经研究员共识，仅作候选入扫"],
                "source": "learning-derived",
            }
            ingested.append(view)

    summary = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "ingested_count": len(ingested),
        "unmapped_count": len(unmapped),
        "ingested": [v["ticker"] for v in ingested],
        "note": ("今日学习无可映射到本系统标的的可测假设；闭环已就绪，"
                 "待学习产出提及具体标的并带立场时自动接入扫描。")
                if not ingested else "已把学习派生假设并入候选，经五道闸验证后决定是否入扫。",
    }

    if not dry:
        out = ROOT / "config" / "learning_views.json"
        out.write_text(json.dumps(ingested, ensure_ascii=False, indent=2), encoding="utf-8")
        bridge = ROOT / "data" / "learning_research_bridge.json"
        bridge.write_text(json.dumps({**summary, "unmapped": unmapped},
                                     ensure_ascii=False, indent=2), encoding="utf-8")
        # 镜像到 paddy 权威内核（同源消费）
        try:
            PADDY_CFG.parent.mkdir(parents=True, exist_ok=True)
            PADDY_CFG.write_text(json.dumps(ingested, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"  ⚠️ 镜像 paddy 失败（不影响星辰）: {e}")

    print(f"  学习→研究 桥接：并入 {len(ingested)} 条，待人工跟进 {len(unmapped)} 条")
    for v in ingested:
        print(f"    ➕ {v['ticker']} {v['name']} [{v['market']}] 方向={_dir_of(v)} 共识={v['panel_consensus']:.0f}")
    if not ingested:
        print(f"    · {summary['note']}")
    return ingested, summary


def _dir_of(v: dict) -> str:
    sd = v.get("signal_distribution", {})
    b, n, r = sd.get("bullish", 0), sd.get("neutral", 0), sd.get("bearish", 0)
    if r > b:
        return "short"
    if b > r:
        return "long"
    return "neutral"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="只打印不写文件")
    a = ap.parse_args()
    build(dry=a.dry)
