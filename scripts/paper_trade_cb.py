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
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import akshare  # noqa: F401,E402

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
_STATEDIR = Path(os.environ.get("PAPER_STATE_DIR", str(ROOT / "data")))
STATE_FILE = _STATEDIR / "paper_cb_state.json"
NAV_FILE = _STATEDIR / "paper_cb_nav.parquet"


def fetch_snapshot():
    import akshare as ak
    df = ak.bond_zh_cov()
    df = df.rename(columns={
        "债券代码": "code", "债券简称": "name", "债现价": "price",
        "转股溢价率": "premium", "正股代码": "stock_code", "正股简称": "stock_name",
        "转股价": "conv_price", "转股价值": "conv_value", "信用评级": "rating",
        "上市时间": "list_date",
    })
    df["code"] = df["code"].astype(str).str.zfill(6)
    df = df[df["code"].str.startswith(("110", "111", "113", "118", "123", "127", "128"))]
    for c in ("price", "premium", "conv_value"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["list_date"] = pd.to_datetime(df["list_date"], errors="coerce")
    # 盯市价映射：取全市场（不做合格性过滤）。避免溢价率/评级缺失的券被过滤后
    # 价格进不了盯市映射、只能沿用旧值造成净值失真（如文科/齐翔/水羊等溢价=nan 的券）
    all_prices = {str(r["code"]).zfill(6): float(r["price"]) for _, r in df.iterrows()
                  if pd.notna(r["price"]) and float(r["price"]) > 0}
    df = df[df["list_date"].notna() & (df["list_date"] <= pd.Timestamp.now() - pd.Timedelta(days=MIN_LISTED_DAYS))]
    # 信用过滤：剔除 ST 正股 / C级及以下 / 无评级
    bad = df["stock_name"].astype(str).str.contains("ST") | df["rating"].astype(str).str.startswith("C") \
        | df["rating"].isna()
    df = df[~bad]
    df = df[(df["price"] <= PRICE_CAP) & (df["premium"] <= PREMIUM_CAP)]
    df["score"] = df["price"] + df["premium"]
    bench = df.sort_values("score")          # 基准：全部合格券等权
    target = bench.head(N_HOLD)
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


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--reset", action="store_true")
    p.add_argument("--as-of", default="")
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
    due = trade_days_since(st["last_rebalance"], today) >= REBALANCE_DAYS

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

    # 异常价保护：转债有涨跌幅限制，若新价相对上次偏离过大、且该券已不在合格样本内，
    # 判为行情异常（如摘牌/停牌后被按面值 100 占位），保留旧价并告警，避免净值失真
    good_codes = set(target["code"]) | set(bench["code"])
    price_warn = []
    for code, h in st["holdings"].items():
        old = float(h.get("last_price") or 0)
        new = float(prices.get(code, old) or 0)
        if old > 0 and new > 0 and code not in good_codes and abs(new / old - 1) > MAX_JUMP:
            price_warn.append({"code": code, "action": "PRICE_JUMP_SUSPECT",
                               "old": round(old, 2), "new": round(new, 2)})
            prices[code] = old

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
    exits = price_warn + enforce_risk_rules(st, prices, today,
                                            quoted=quoted_codes, tradable=good_codes)
    banned = {e["code"] for e in exits if e.get("action") != "SKIP_STALE"}
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
    if st["holdings"]:
        print("\n当前持仓（TOP5）：")
        for code, h in sorted(st["holdings"].items(), key=lambda x: -x[1]["value"])[:5]:
            print(f"  {code}: {h['shares']:.0f} 张 @ {h['last_price']:.2f} = {h['value']:,.0f}")
    if not due:
        print(f"\n距下次调仓约 {REBALANCE_DAYS - trade_days_since(st['last_rebalance'], today)} 交易日")


if __name__ == "__main__":
    main()
