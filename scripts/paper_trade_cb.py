#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 可转债双低策略模拟盘（有状态持仓模拟）

每日运行（或定时）：
  1) 拉取全市场可转债快照（akshare bond_zh_cov），计算目标组合
  2) 到调仓日（距上次调仓 ≥20 交易日）执行调仓：卖出不在目标中的持仓，
     买入目标组合缺失的标的，等权分配，成本 0.1%/边
  3) 每日按最新价格对持仓盯市，记录净值序列

状态文件：data/paper_cb_state.json（持仓/现金/上次调仓/调仓次数）
净值序列：data/paper_cb_nav.parquet（date, nav, bench_nav, daily_return, holdings）
基准：全债等权（同筛选条件、同调仓节奏），用于“跑赢基准”纪律判定。

用法:
    python3 scripts/paper_trade_cb.py            # 每日更新（模拟盘推进）
    python3 scripts/paper_trade_cb.py --reset    # 重置模拟盘
    python3 scripts/paper_trade_cb.py --as-of 2026-08-01   # 历史回放（测试用，面板数据）
"""

import argparse
import os
import json
import sys
import time
import requests
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import akshare  # noqa: F401,E402

# 腾讯实时快照（纠正 akshare 对缺失/停牌可转债返回面值 100 占位价的 bug）
TX_QUOTE_URL = "https://qt.gtimg.cn/q="


def _tx_cb_code(code: str) -> str:
    """可转债腾讯行情代码：11xxxx(沪) -> sh；12xxxx(深) -> sz。"""
    s = str(code).zfill(6)
    if s.startswith("11"):
        return "sh" + s
    if s.startswith("12"):
        return "sz" + s
    return "sh" + s


def _tx_cb_price(code: str):
    """腾讯快照取可转债现价；失败返回 None。快速路径(~300ms)，不依赖 akshare。"""
    tc = _tx_cb_code(code)
    try:
        r = requests.get(TX_QUOTE_URL + tc, timeout=5, headers={"User-Agent": "Mozilla/5.0"})
        r.encoding = "gbk"
        txt = r.text.strip()
        if '="' not in txt or "~" not in txt:
            return None
        f = txt.split('="', 1)[1].rstrip('";').split("~")
        if len(f) < 4 or not f[3]:
            return None
        return float(f[3])
    except Exception:
        return None


TX_BATCH = 60          # 腾讯 q= 单次可拼接的代码数（实测 60 个 / 0.3s 稳定）
TX_RETRY = 2


def _tx_eq_code(code: str) -> str:
    """正股腾讯行情代码：6 开头沪市，其余深市（含 0/3 开头）。"""
    s = str(code).zfill(6)
    return ("sh" if s.startswith("6") else "sz") + s


def _tx_batch_quotes(keys) -> dict:
    """批量取腾讯行情。keys 为带交易所前缀的代码列表（sh110043/sz300750）。

    返回 {6位数字代码: {"price": 现价, "vol": 当日成交量(手)}}。
    全市场 ~1000 只约 17 次请求 / 5 秒，远快于逐只请求。

    ⚠️ 必须同时取成交量：腾讯对**已退市/已赎回**的可转债仍会回显最后成交价，
    且时间戳打的是查询时刻（看起来像当日行情）。只有成交量能区分死债——实测
    695 只无转股价的老债成交量 100% 为 0，而在交易的券仅 4.9% 为 0。
    """
    out = {}
    keys = list(dict.fromkeys(keys))  # 去重保序
    for i in range(0, len(keys), TX_BATCH):
        chunk = keys[i:i + TX_BATCH]
        for attempt in range(TX_RETRY):
            try:
                r = requests.get(TX_QUOTE_URL + ",".join(chunk), timeout=8,
                                 headers={"User-Agent": "Mozilla/5.0"})
                r.encoding = "gbk"
                for seg in r.text.split(";"):
                    seg = seg.strip()
                    if '="' not in seg:
                        continue
                    key = seg.split('="', 1)[0].strip()          # v_sh110043
                    f = seg.split('="', 1)[1].rstrip('";').split("~")
                    if len(f) < 7 or not f[3]:
                        continue
                    try:
                        px = float(f[3])
                        vol = float(f[6] or 0)
                    except ValueError:
                        continue
                    if px > 0:
                        out[key[-6:]] = {"price": px, "vol": vol}
                break
            except Exception as e:
                if attempt == TX_RETRY - 1:
                    print(f"[paper_cb] 腾讯批量取价失败（{len(chunk)} 只）: "
                          f"{type(e).__name__}: {str(e)[:80]}", file=sys.stderr)
                else:
                    time.sleep(1)
    return out


def _tx_batch_prices(keys) -> dict:
    """只要现价的便捷封装：{6位代码: 现价}。"""
    return {k: v["price"] for k, v in _tx_batch_quotes(keys).items()}


# —— 自愈元数据缓存 ——
# 背景：akshare bond_zh_cov 的上游（东财）会间歇性只返回部分券的「转股价/转股价值/
# 转股溢价率」。2026-09-03 实测 转股价 仅 319/1051 有值，而 2026-08-11 的本地快照
# 1047 只全有值 —— 属上游退化。若直接用当日数据，premium=nan 的券会被
# `premium <= PREMIUM_CAP` 判 False 而剔除，选样宇宙从 ~1000 只被截断到 ~317 只，
# 双低策略等于只在「数据恰好完整」的子集里选，构成严重选样偏差。
# 对策：转股价/评级/上市日 属慢变字段（仅在下修、除权、评级调整时变动），
# 用「最后已知有效值」逐字段累积到缓存，当日有值则刷新、当日缺失则沿用缓存。
META_CACHE = ROOT / "data" / "cb_meta_cache.parquet"
META_SLOW_FIELDS = ["name", "stock_code", "stock_name", "conv_price", "rating", "list_date"]
CONV_PRICE_STALE_DAYS = 180   # 转股价缓存超过此天数则告警（下修未被捕获的风险窗口）

COST = 0.001
N_HOLD = 20
PRICE_CAP = 130.0
PREMIUM_CAP = 50.0
MIN_LISTED_DAYS = 30  # 自然日
REBALANCE_DAYS = 20   # 交易日
# —— 风控规则（下跌市不再裸奔，与调仓日解耦，每日扫描）——
STOP_LOSS_PCT = -0.08  # 单债相对建仓价最大回撤，低于则清仓
MIN_PRICE = 95.0       # 价格破面下限，触发清仓（信用/下修风险信号）
MAX_WEIGHT = 0.08      # 单只权重上限，超额部分卖出
MAX_JUMP = 0.10        # 单日价格跳变阈值：超出且该券已不在合格样本内，视为行情异常（转债涨跌幅限制内）
DELIST_ZERO_VOL_DAYS = 3   # 连续零成交交易日数，达到即判定停牌/强赎摘牌并按最后成交价清仓
_STATEDIR = Path(os.environ.get("PAPER_STATE_DIR", str(ROOT / "data")))
STATE_FILE = _STATEDIR / "paper_cb_state.json"
NAV_FILE = _STATEDIR / "paper_cb_nav.parquet"


def _merge_meta_cache(live: pd.DataFrame) -> pd.DataFrame:
    """把当日 akshare 慢变字段并入自愈缓存，返回「最后已知有效值」宽表。

    逐字段规则：当日非空 → 采用当日值并把 asof 打到今天；当日为空 → 沿用缓存值。
    这样即便上游某天只返回 1/3 的券，选样宇宙也不会塌缩。
    """
    today = date.today().isoformat()
    live = live.copy()
    live["code"] = live["code"].astype(str).str.zfill(6)
    live = live.drop_duplicates("code", keep="last")

    if META_CACHE.exists():
        cache = pd.read_parquet(META_CACHE)
        cache["code"] = cache["code"].astype(str).str.zfill(6)
    else:
        # 首次运行：用历史 cb_meta.parquet 播种（含 2026-08-11 的全量转股价）
        seed = ROOT / "data" / "cb_meta.parquet"
        if seed.exists():
            s = pd.read_parquet(seed)
            s["code"] = s["code"].astype(str).str.zfill(6)
            keep = ["code"] + [c for c in META_SLOW_FIELDS if c in s.columns]
            cache = s[keep].copy()
            cache["conv_price_asof"] = "2026-08-11"   # 播种快照日期，据实标注
            print(f"[paper_cb] 元数据缓存首次播种：cb_meta.parquet {len(cache)} 只", file=sys.stderr)
        else:
            cache = pd.DataFrame(columns=["code"] + META_SLOW_FIELDS + ["conv_price_asof"])
    for c in META_SLOW_FIELDS + ["conv_price_asof"]:
        if c not in cache.columns:
            cache[c] = np.nan

    out = cache.set_index("code")
    lv = live.set_index("code")
    for code in lv.index.difference(out.index):
        out.loc[code] = np.nan
    for f in META_SLOW_FIELDS:
        if f not in lv.columns:
            continue
        new = lv[f].reindex(out.index)
        out[f] = new.where(new.notna(), out[f])
    fresh = lv["conv_price"].reindex(out.index).notna() if "conv_price" in lv.columns \
        else pd.Series(False, index=out.index)
    out["conv_price_asof"] = np.where(fresh, today, out["conv_price_asof"])
    # 没有转股价的券不该带 asof 时间戳（否则看起来像"有数据且是某天取的"，误导排查）
    out.loc[pd.to_numeric(out["conv_price"], errors="coerce").isna(), "conv_price_asof"] = None

    out = out.reset_index()
    META_CACHE.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(META_CACHE, index=False)
    n_fresh = int(fresh.sum())
    print(f"[paper_cb] 元数据缓存：{len(out)} 只，其中 {n_fresh} 只转股价当日刷新、"
          f"{len(out) - n_fresh} 只沿用缓存", file=sys.stderr)
    return out


def fetch_snapshot():
    """取当日全市场可转债快照。

    取价链路（2026-09-03 重构）：
      · 价格 —— 全部走腾讯批量快照（1021/1021 覆盖、~5s）。不再用 akshare 的
        「债现价」：实测 710/1051 只返回面值 100.0 占位，直接用会低估净值。
      · 转股价值 —— 本地重算 100/转股价 × 正股价（正股价同样走腾讯批量）。
        已对 317 只双源可比样本校验：与 akshare 口径最大偏差 0.00005，公式精确。
      · 转股溢价率 —— 本地重算 (价格/转股价值 − 1)×100。同样已校验（最大偏差
        0.005pp，纯舍入），不再依赖 akshare 当日是否返回该字段。
      · 慢变字段（转股价/评级/上市日）—— 走自愈缓存，抵御上游间歇性缺字段。
      · 活跃性闸门 —— 用成交量剔除已退市老债，见下方注释。

    ⚠️ 关于「转股价只有 ~320/1021 只有值」的结论（2026-09-03 查证，勿再误判）：
    这**不是**上游退化、也**不是**选样宇宙被截断。那 ~695 只无转股价的券实测当日
    成交量 100% 为 0，是已赎回/摘牌的历史债；东财不再维护其转股价是正确行为。
    真实可交易宇宙就是 ~320 只。切勿为了"把宇宙做大"去补这些券的转股价。
    """
    import akshare as ak
    try:
        raw = ak.bond_zh_cov()
        raw = raw.rename(columns={
            "债券代码": "code", "债券简称": "name", "债现价": "ak_price",
            "转股溢价率": "ak_premium", "正股代码": "stock_code", "正股简称": "stock_name",
            "转股价": "conv_price", "转股价值": "ak_conv_value", "信用评级": "rating",
            "上市时间": "list_date",
        })
        raw["code"] = raw["code"].astype(str).str.zfill(6)
        for c in ("ak_price", "ak_premium", "ak_conv_value", "conv_price"):
            raw[c] = pd.to_numeric(raw.get(c), errors="coerce")
        live = raw[["code"] + [c for c in META_SLOW_FIELDS if c in raw.columns]].copy()
    except Exception as e:
        print(f"[paper_cb] akshare bond_zh_cov 失败，全量退回元数据缓存: "
              f"{type(e).__name__}: {str(e)[:100]}", file=sys.stderr)
        raw = pd.DataFrame(columns=["code", "ak_price"])
        live = pd.DataFrame(columns=["code"] + META_SLOW_FIELDS)

    df = _merge_meta_cache(live)
    df = df[df["code"].str.startswith(("110", "111", "113", "118", "123", "127", "128"))].copy()
    df["conv_price"] = pd.to_numeric(df["conv_price"], errors="coerce")
    df["list_date"] = pd.to_datetime(df["list_date"], errors="coerce")

    # —— 腾讯批量取价：转债 + 正股各一轮 ——
    bond_q = _tx_batch_quotes([_tx_cb_code(c) for c in df["code"]])
    df["price"] = df["code"].map({k: v["price"] for k, v in bond_q.items()})
    df["vol"] = df["code"].map({k: v["vol"] for k, v in bond_q.items()}).fillna(0.0)
    sc = df["stock_code"].astype(str).str.zfill(6)
    stock_px = _tx_batch_prices([_tx_eq_code(c) for c in sc.dropna().unique()])
    df["stock_px"] = sc.map(stock_px)
    if "ak_price" in raw.columns:   # 腾讯漏掉的券兜底用 akshare（但排除 100.0 占位）
        ak_px = raw.set_index("code")["ak_price"]
        fb = df["code"].map(ak_px)
        df["price"] = df["price"].where(df["price"].notna(), fb.where(fb != 100.0))
    print(f"[paper_cb] 腾讯批量取价：转债 {len(bond_q)}/{len(df)}、正股 {len(stock_px)} 只",
          file=sys.stderr)

    # —— 本地重算转股价值 / 溢价率（公式已双源校验）——
    df["conv_value"] = np.where(
        (df["conv_price"] > 0) & df["stock_px"].notna(),
        100.0 / df["conv_price"] * df["stock_px"], np.nan)
    df["premium"] = np.where(
        (df["conv_value"] > 0) & df["price"].notna(),
        (df["price"] / df["conv_value"] - 1.0) * 100.0, np.nan)

    # —— 活跃性闸门（退市保护，勿删）——
    # 盯市映射要「尽量宽」以免持仓价滞留旧值（溢价/评级缺失的在交易券必须进映射，
    # 如文科/齐翔/水羊），但**绝不能宽到收进已退市的死债**：腾讯对赎回摘牌的老债仍
    # 回显最后成交价且时间戳是查询时刻，一旦进映射，持仓摘牌后会被当成"有正常行情"，
    # 绕过 enforce_risk_rules 里的 SKIP_STALE 保护，按一个永不变的僵尸价长期计入净值。
    # 判活规则：当日有成交量 > 0，或东财仍在维护其转股价（可算出溢价率）。
    # 盘前/非交易时段全市场成交量都是 0，此时退化为「有溢价率即算活」，避免全盘误判。
    vol_ok = df["vol"] > 0
    if vol_ok.sum() < 20:          # 成交量数据未就绪（盘前/休市）
        alive = df["premium"].notna()
        print("[paper_cb] 成交量未就绪（盘前/休市），活跃性判定退化为「有溢价率」", file=sys.stderr)
    else:
        alive = vol_ok | df["premium"].notna()
    n_dead = int((~alive).sum())
    all_prices = {str(r["code"]).zfill(6): float(r["price"])
                  for _, r in df[alive].iterrows()
                  if pd.notna(r["price"]) and float(r["price"]) > 0}
    print(f"[paper_cb] 活跃性闸门：判活 {int(alive.sum())} 只、剔除疑似退市/零成交 "
          f"{n_dead} 只（不进盯市映射，持仓命中则走 SKIP_STALE 告警）", file=sys.stderr)
    df = df[alive]

    df = df[df["list_date"].notna() & (df["list_date"] <= pd.Timestamp.now() - pd.Timedelta(days=MIN_LISTED_DAYS))]
    # 信用过滤：剔除 ST 正股 / C级及以下 / 无评级
    bad = df["stock_name"].astype(str).str.contains("ST") | df["rating"].astype(str).str.startswith("C") \
        | df["rating"].isna()
    df = df[~bad]
    df = df[df["price"].notna() & df["premium"].notna()]
    df = df[(df["price"] <= PRICE_CAP) & (df["premium"] <= PREMIUM_CAP)]

    # —— 流动性闸门：选样必须当日真有成交（2026-09-03 新增，勿删）——
    # 双低打分 = 价格 + 溢价率，天然偏爱"价格低且溢价低"的券。停牌/待摘牌的券价格被
    # 冻结在停牌前收盘价（腾讯 f[30] 时间戳停在 09:00:00、f[6] 成交量恒为 0），溢价率
    # 也随之冻结，于是它们会持续霸占双低榜前列 —— 这是一个系统性逆向选择陷阱：
    # 买不进去（停牌）、或买进就等着被强赎摘牌。实测当日合格样本 50 只里 6 只零成交，
    # 且有 2 只（齐翔转2 128128、密卫转债 113658）挤进了目标前 20。
    # 因此：盯市（all_prices，上面已算完）保持宽松——停牌券按最后收盘价估值是标准惯例；
    #       选样（bench/target）必须严格要求 vol > 0，杜绝买入僵尸债。
    # 已持仓踩中停牌的券不会被强卖：它不在 bench 里 → 不属于 tradable → 走 WATCH_ONLY。
    n_before = len(df)
    if (df["vol"] > 0).sum() >= 20:            # 成交量已就绪（收盘后/盘中）
        df = df[df["vol"] > 0]
        n_frozen = n_before - len(df)
    else:                                       # 盘前全市场量为 0，不做流动性剔除
        n_frozen = 0
        print("[paper_cb] 成交量未就绪（盘前/休市），本轮跳过流动性闸门", file=sys.stderr)

    df["score"] = df["price"] + df["premium"]
    bench = df.sort_values("score")          # 基准：全部合格券等权
    target = bench.head(N_HOLD)
    print(f"[paper_cb] 合格样本 {len(bench)} 只（流动性闸门剔除停牌/零成交 {n_frozen} 只）",
          file=sys.stderr)
    return target, bench, all_prices


def fetch_snapshot_panel(as_of):
    """从本地面板重建历史快照（--as-of 测试用），与 live 快照同口径"""
    panel = pd.read_parquet(ROOT / "data" / "cb_panel.parquet")
    meta = pd.read_parquet(ROOT / "data" / "cb_meta.parquet")
    meta["code"] = meta["code"].astype(str).str.zfill(6)
    meta["rating"] = meta["rating"].astype(str)
    panel["date"] = pd.to_datetime(panel["date"])
    panel = panel[panel["date"] <= pd.Timestamp(as_of)]
    panel = panel[panel["bond"].str.startswith(("110", "111", "113", "118", "123", "127", "128"))]
    latest = panel.loc[panel.groupby("bond")["date"].idxmax()]  # 绕开 sort_values 的 pandas/numpy bug
    # 与 live 快照同口径：盯市用全市场价（不过滤），避免持仓价滞留
    all_prices = {str(r["bond"]).zfill(6): float(r["close"]) for _, r in latest.iterrows()
                  if pd.notna(r["close"]) and float(r["close"]) > 0}
    meta_s = meta[["code", "stock_name", "rating"]].rename(columns={"code": "meta_code"})
    latest = latest.merge(meta_s, left_on="bond", right_on="meta_code")
    latest = latest.drop(columns=["meta_code"])
    bad = latest["stock_name"].astype(str).str.contains("ST") | latest["rating"].str.startswith("C") \
        | latest["rating"].isna()
    latest = latest[~bad]
    cnt = panel.groupby("bond").size()
    latest = latest[latest["bond"].map(cnt) >= 20]
    latest = latest[(latest["close"] <= PRICE_CAP) & (latest["premium_pct"] <= PREMIUM_CAP)]
    latest["score"] = latest["close"] + latest["premium_pct"]
    bench = latest.sort_values("score")
    target = bench.head(N_HOLD)
    cols = {"bond": "code", "close": "price", "premium_pct": "premium"}
    return target.rename(columns=cols), bench.rename(columns=cols), all_prices


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"cash": 1_000_000.0, "holdings": {}, "last_rebalance": None,
            "rebalance_count": 0, "start_date": str(date.today())}


def save_state(st):
    STATE_FILE.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")


def trade_days_since(last, today=None):
    """用本地交易日历粗算两个日期间交易日数（近 252 日/年近似）"""
    if last is None:
        return 999
    cur = pd.Timestamp(today) if today else pd.Timestamp(date.today())
    return max(1, int((cur - pd.Timestamp(last)).days * 252 / 365))


def enforce_risk_rules(st, prices, today, quoted=None, tradable=None):
    """每日盯市后执行风控：个股止损 / 破面清仓 / 权重上限，返回退出记录列表。
    与调仓日(20交易日)解耦，下跌市中也能逐日拦截风险，避免一次性建仓后裸奔。
    quoted:   本次行情源实际收录的券集合；未收录者价格不可信，只告警不误卖。
    tradable: 允许执行自动卖出的券集合（当日合格样本 target/bench）。
              不在此集合的持仓价格可信度低，一律只告警不交易，
              避免按被污染的价格误砍（如摘牌券被按面值 100 计价触发假止损）。
    """
    exits = []
    quoted = set(prices) if quoted is None else quoted
    tradable = set() if tradable is None else tradable
    for code, h in st["holdings"].items():
        h.setdefault("entry_price", h.get("last_price"))
    for code in list(st["holdings"]):
        h = st["holdings"][code]
        px = prices.get(code, h["last_price"])
        entry = h.get("entry_price", px)
        # 行情源未收录该券 -> 价格不可信（可能摘牌/停牌），不误卖，仅告警
        if code not in quoted:
            exits.append({"code": code, "action": "SKIP_STALE",
                          "reason": "行情源未收录(价格不可信)"})
            continue
        # 非当日合格样本：价格可信度低，只告警、不自动卖出
        if code not in tradable:
            exits.append({"code": code, "action": "WATCH_ONLY",
                          "reason": "非当日合格样本(不自动交易)"})
            continue
        # 破面清仓（信用风险 / 下修风险信号）
        if px < MIN_PRICE:
            st["cash"] += h["value"] * (1 - COST)
            exits.append({"code": code, "action": "SELL_MIN_PRICE", "price": round(px, 2)})
            st["holdings"].pop(code)
            continue
        # 相对建仓价回撤止损
        if entry and px / entry - 1 < STOP_LOSS_PCT:
            st["cash"] += h["value"] * (1 - COST)
            exits.append({"code": code, "action": "SELL_STOP_LOSS",
                          "price": round(px, 2), "entry": round(entry, 2)})
            st["holdings"].pop(code)
            continue
    # 单只权重上限再平衡（同样只在合格样本内执行，避免按可疑价交易）
    mv = sum(h["value"] for h in st["holdings"].values())
    nav2 = st["cash"] + mv
    for code in list(st["holdings"]):
        if code not in tradable:
            continue
        h = st["holdings"][code]
        w = h["value"] / nav2 if nav2 else 0
        if w > MAX_WEIGHT:
            sell_val = h["value"] - MAX_WEIGHT * nav2
            st["cash"] += sell_val * (1 - COST)
            h["shares"] -= sell_val / h["last_price"]
            h["value"] = h["shares"] * h["last_price"]
            exits.append({"code": code, "action": "TRIM_WEIGHT",
                          "weight": round(w, 3)})
    return exits


def enforce_delisting(st, bench, prices, today):
    """停牌/强赎摘牌退出规则（2026-09-03 新增）。

    动机（真实踩坑，勿删）：水羊转债 123188 最后真实成交日为 2026-07-29（收盘 142.81），
    7-30 起成交量恒为 0、价格永久冻结——实为强赎摘牌。但模拟盘把它当"持仓"挂了五周，
    占净值 6.9%，既占着 20 个仓位之一，又让净值挂在一个永不变的僵尸价上。
    原有 SKIP_STALE / WATCH_ONLY 只"告警不动作"，救不了这种永久性摘牌。

    规则：连续 DELIST_ZERO_VOL_DAYS 个**交易日**零成交 → 判定摘牌，按最后有效价清仓入现金。
    经济含义正确：强赎前转股价值远高于面值，理性持有人会在最后交易日卖出/转股离场。

    交易日判定：拿「当日合格样本（已过流动性闸门）」当参照物 —— 盘前/休市时它们成交量
    也全为 0，此时直接跳过计数，避免周末把全部持仓误判成摘牌。
    """
    notes = []
    ref = list(bench["code"].head(30)) if len(bench) else []
    held_all = list(st.get("holdings", {})) + list(st.get("bench_holdings", {}))
    if not held_all:
        return notes
    q = _tx_batch_quotes([_tx_cb_code(c) for c in dict.fromkeys(held_all + ref)])
    if sum(1 for c in ref if q.get(c, {}).get("vol", 0) > 0) == 0:
        notes.append({"action": "DELIST_CHECK_SKIP", "reason": "参照券全零成交(盘前/休市)"})
        return notes
    # 策略组合与基准组合同规则处理，否则基准会一直背着僵尸债、比较失真
    for hkey, ckey, tag in (("holdings", "cash", ""), ("bench_holdings", "bench_cash", "BENCH_")):
        notes += _delist_one(st, q, prices, today, hkey, ckey, tag)
    return notes


def _delist_one(st, q, prices, today, hkey, ckey, tag):
    notes = []
    for code in list(st.get(hkey, {})):
        h = st[hkey][code]
        vol = q.get(code, {}).get("vol", 0.0)
        if vol > 0:
            h["zero_vol_days"] = 0
            h["zero_vol_last"] = None
            continue
        if h.get("zero_vol_last") == today:      # 同一交易日不重复计数
            continue
        h["zero_vol_days"] = int(h.get("zero_vol_days", 0)) + 1
        h["zero_vol_last"] = today
        if h["zero_vol_days"] >= DELIST_ZERO_VOL_DAYS:
            px = float(prices.get(code, h["last_price"]) or h["last_price"])
            proceeds = h["shares"] * px * (1 - COST)
            st[ckey] = st.get(ckey, 0.0) + proceeds
            notes.append({"code": code, "action": tag + "SELL_DELISTED",
                          "price": round(px, 3), "days": h["zero_vol_days"],
                          "proceeds": round(proceeds, 2),
                          "reason": f"连续{h['zero_vol_days']}个交易日零成交，判定停牌/强赎摘牌"})
            st[hkey].pop(code)
        else:
            notes.append({"code": code, "action": tag + "ZERO_VOL_WATCH",
                          "days": h["zero_vol_days"],
                          "reason": f"零成交累计{h['zero_vol_days']}/{DELIST_ZERO_VOL_DAYS}日"})
    return notes


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--reset", action="store_true")
    p.add_argument("--as-of", default="")
    p.add_argument("--force", action="store_true",
                   help="忽略调仓日历，立即按现有双低规则再平衡（用于把释放的闲置现金按需部署）")
    args = p.parse_args()
    if args.reset:
        save_state({"cash": 1_000_000.0, "holdings": {}, "last_rebalance": None,
                    "rebalance_count": 0, "start_date": str(date.today())})
        if NAV_FILE.exists():
            NAV_FILE.unlink()
        print("模拟盘已重置")
        return

    as_of = args.as_of or None
    today = str(date.today()) if not as_of else as_of
    target, bench, all_prices = fetch_snapshot_panel(as_of) if as_of else fetch_snapshot()
    st = load_state()
    st.setdefault("bench_cash", 1_000_000.0)
    st.setdefault("bench_holdings", {})
    due = trade_days_since(st["last_rebalance"], today) >= REBALANCE_DAYS or args.force

    # 盯市价优先用全市场映射（含被合格性过滤的券），避免价格滞留旧值
    prices = dict(all_prices)
    prices.update(target.set_index("code")["price"].to_dict())
    prices.update(bench.set_index("code")["price"].to_dict())
    for code in list(st["holdings"]):
        if code not in prices:
            prices[code] = st["holdings"][code]["last_price"]
    for code in list(st["bench_holdings"]):
        if code not in prices:
            prices[code] = st["bench_holdings"][code]["last_price"]

    # 残留面值 100 占位兜底。live 路径已在 fetch_snapshot 里全量走腾讯，正常不会命中；
    # 主要覆盖 --as-of 历史面板路径（cb_panel.parquet 里仍存着被 akshare 污染的 100.0）
    # 以及持仓沿用旧值的情形。改为批量请求，避免逐只 300ms 累加成分钟级耗时。
    ph = [c for c in prices if prices.get(c) == 100.0]
    if ph:
        real = _tx_batch_prices([_tx_cb_code(c) for c in ph])
        fixed = 0
        for c in ph:
            if real.get(c):
                prices[c] = real[c]
                fixed += 1
        print(f"[paper_cb] 面值100占位兜底：命中 {len(ph)} 只，腾讯修正 {fixed} 只", file=sys.stderr)

    # 异常价保护：仅在「新价本身是面值 100 占位」时回落旧价。
    # 旧逻辑会把偏离>10% 的新价一律回落旧价——但当下旧价可能正是被 akshare 污染的 100.0，
    # 那样会拒绝腾讯真实价、重新锁死净值低估。改为：新价==100.0（占位签名）才视为异常回落，
    # 真实价（如腾讯 142.8）即便相对旧价 100.0 跳涨也采信——这正是要修的净值低估。
    good_codes = set(target["code"]) | set(bench["code"])
    price_warn = []
    for code, h in st["holdings"].items():
        old = float(h.get("last_price") or 0)
        new = float(prices.get(code, old) or 0)
        if old > 0 and new > 0 and code not in good_codes and new == 100.0 and abs(new / old - 1) > MAX_JUMP:
            price_warn.append({"code": code, "action": "PRICE_JUMP_SUSPECT",
                               "old": round(old, 2), "new": round(new, 2)})
            prices[code] = old

    # —— 停牌/摘牌退出（必须在盯市之前：清仓后现金才能计入当日净值）——
    # --as-of 历史面板路径没有成交量数据，跳过，避免用缺失字段做误判。
    delist_notes = [] if as_of else enforce_delisting(st, bench, prices, today)

    # 持仓盯市（策略 + 基准）
    for code, h in st["holdings"].items():
        h["last_price"] = prices.get(code, h["last_price"])
        h["value"] = h["shares"] * h["last_price"]
    mv = sum(h["value"] for h in st["holdings"].values())
    nav = st["cash"] + mv
    for code, h in st["bench_holdings"].items():
        h["last_price"] = prices.get(code, h["last_price"])
        h["value"] = h["shares"] * h["last_price"]
    bench_mv = sum(h["value"] for h in st["bench_holdings"].values())
    bench_nav = st["bench_cash"] + bench_mv

    # —— 每日风控扫描（独立于调仓日）——
    quoted_codes = set(all_prices) | set(target["code"]) | set(bench["code"])
    exits = delist_notes + price_warn + enforce_risk_rules(st, prices, today,
                                                          quoted=quoted_codes, tradable=good_codes)
    banned = {e["code"] for e in exits
              if e.get("code") and e.get("action") not in ("SKIP_STALE", "DELIST_CHECK_SKIP")}
    if banned:
        target = target[~target["code"].isin(banned)]
        bench = bench[~bench["code"].isin(banned)]
    if exits:
        st.setdefault("risk_exits", [])
        st["risk_exits"] = (st["risk_exits"] + exits)[-50:]
        for e in exits:
            print(f"  [风控] {e}")

    if due and len(target) >= N_HOLD:
        # ---- 策略组合调仓 ----
        target_codes = set(target["code"])
        for code in list(st["holdings"]):
            if code not in target_codes:
                h = st["holdings"].pop(code)
                st["cash"] += h["value"] * (1 - COST)
        target_value = nav * 0.98 / N_HOLD
        for _, r in target.iterrows():
            code = r["code"]
            if code in st["holdings"]:
                continue
            shares = target_value / r["price"]
            st["holdings"][code] = {"shares": shares, "last_price": float(r["price"]),
                                    "value": target_value, "entry_date": today,
                                    "entry_price": float(r["price"])}
            st["cash"] -= target_value * (1 + COST)
        # ---- 基准组合调仓（全合格券等权） ----
        bench_codes = set(bench["code"])
        for code in list(st["bench_holdings"]):
            if code not in bench_codes:
                h = st["bench_holdings"].pop(code)
                st["bench_cash"] += h["value"] * (1 - COST)
        if len(bench) > 0:
            bv = bench_nav * 0.98 / len(bench)
            for _, r in bench.iterrows():
                code = r["code"]
                if code in st["bench_holdings"]:
                    continue
                shares = bv / r["price"]
                st["bench_holdings"][code] = {"shares": shares, "last_price": float(r["price"]),
                                              "value": bv, "entry_date": today}
                st["bench_cash"] -= bv * (1 + COST)
        st["last_rebalance"] = today
        st["rebalance_count"] += 1
        print(f"调仓执行（第 {st['rebalance_count']} 次），策略 {len(target)} 只 / 基准 {len(bench)} 只")
        mv = sum(h["value"] for h in st["holdings"].values())
        nav = st["cash"] + mv
        bench_mv = sum(h["value"] for h in st["bench_holdings"].values())
        bench_nav = st["bench_cash"] + bench_mv

    # 记录净值
    nav_row = pd.DataFrame([{"date": pd.Timestamp(today), "nav": nav, "bench_nav": bench_nav,
                             "holdings": len(st["holdings"]), "cash": st["cash"]}])
    if NAV_FILE.exists():
        old = pd.read_parquet(NAV_FILE)
        nav_row = pd.concat([old, nav_row], ignore_index=True)
    nav_row = nav_row.drop_duplicates("date", keep="last").sort_values("date")
    nav_row["daily_return"] = nav_row["nav"].pct_change()
    nav_row.to_parquet(NAV_FILE, index=False)
    save_state(st)

    print(f"=== 模拟盘 {today} ===")
    print(f"净值 {nav:,.0f}（基准 {bench_nav:,.0f}）| 持仓 {len(st['holdings'])} 只 | 现金 {st['cash']:,.0f} | 调仓 {st['rebalance_count']} 次")
    # 摘牌清仓属被动退出，会留下空仓位。按 20 交易日调仓纪律不做临时补仓（避免额外换手
    # 与择时），但现金占比偏高会拖累收益，须显式提示，不能让它静默发生。
    cash_w = st["cash"] / nav if nav else 0
    if cash_w > 0.15 or len(st["holdings"]) < N_HOLD:
        print(f"⚠ 现金占比 {cash_w:.1%}、持仓 {len(st['holdings'])}/{N_HOLD} 只"
              f"（摘牌被动退出留下的空仓位将在下次调仓回补，期间存在现金拖累）")
    if st["holdings"]:
        print("\n当前持仓（TOP5）：")
        for code, h in sorted(st["holdings"].items(), key=lambda x: -x[1]["value"])[:5]:
            print(f"  {code}: {h['shares']:.0f} 张 @ {h['last_price']:.2f} = {h['value']:,.0f}")
    if not due:
        print(f"\n距下次调仓约 {REBALANCE_DAYS - trade_days_since(st['last_rebalance'], today)} 交易日")


if __name__ == "__main__":
    main()
