#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 盘中盯市（intraday mark-to-market）

用实时报价重估模拟盘账户权益，让看板在盘中也能看到变动，而不必等到 16:35 日终批处理。

设计原则（务必遵守）
--------------------
1. **不污染日终净值**：结果只写 ``data/intraday_mtm.json``，绝不触碰
   ``paper_*_nav.parquet``。日终净值仍由 16:35 的 ``run_all.py all`` 唯一写入，
   两者语义分离：nav = 已结算事实，intraday = 未结算估计。
2. **只估值、不交易**：不触发任何调仓 / 止损 / 再平衡逻辑。
3. **快**：全量重估须在数十秒内完成（每小时跑一次）。
   因此**不走** ``DataHub.quote()`` —— 其 A股/港股路径走 akshare，单标的 8~12 秒，
   仅可转债账户 20 个标的就会让任务跑 4 分钟。改为腾讯 ``qt.gtimg.cn``
   （实测约 300ms/标的）+ Binance ticker 的快速路径。
4. **诚实**：取不到实时价、或报价时间不是今天（说明该市场当前闭市），
   一律回落到本地最后收盘并标注来源，绝不伪造变动。

用法
----
    python3 scripts/mark_to_market.py             # 重估全部账户并写文件
    python3 scripts/mark_to_market.py --print     # 额外打印摘要（调试用）
"""

import argparse
import json
import math
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from datahub.core import BINANCE_DATA_API  # noqa: E402
from datahub.store import LocalStore  # noqa: E402

DATA_DIR = Path(os.environ.get("PAPER_STATE_DIR", str(ROOT / "data")))
OUT_FILE = DATA_DIR / "intraday_mtm.json"

REQ_TIMEOUT = 5  # 秒；快速路径不做重试，失败即回落本地收盘
UA = {"User-Agent": "Mozilla/5.0"}

# 账户前缀 -> (市场, 显示名)，与 scripts/dashboard.py 的 ACCOUNT_DEFS 保持一致
ACCOUNT_DEFS = [
    ("paper_cb", "A股", "双低·可转债"),
    ("paper_mom", "美股", "双动量·ETF"),
    ("paper_rp", "美股", "风险平价"),
    ("paper_crypto", "虚拟货币", "加密·等权"),
    ("paper_hk", "港股", "港股"),
    ("paper_aapl", "美股", "AAPL·灰度"),
]

# paper_aapl 用 shares 单字段存仓（非 holdings 字典），需单独处理
SINGLE_SHARE_ACCOUNTS = {"paper_aapl": "AAPL"}

TX_QUOTE_URL = "https://qt.gtimg.cn/q="


def _clean(obj):
    """NaN / Inf -> None。历史教训：含 NaN 的 JSON 会让前端 JSON.parse 直接抛错，
    导致看板整块卡在「加载中」。写出前必须清洗。"""
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


def _safe_name(symbol: str) -> str:
    return symbol.replace("/", "_")


def _tx_code(market: str, symbol: str):
    """把内部代码转成腾讯行情代码。

    A股/可转债必须带对交易所前缀，否则返回 v_pv_none_match（实测 sh123188 无数据、
    sz123188 正常）：
      11xxxx（110/111/113/118 沪市转债）→ sh    12xxxx（123/127/128/129 深市转债）→ sz
      6xxxxx（沪市/科创板）→ sh                  0xxxxx / 3xxxxx（深市/创业板）→ sz
      4xxxxx / 8xxxxx（北交所）→ bj
    """
    s = str(symbol).replace("/", "").strip()
    if market == "A股":
        if s.startswith("11"):
            return "sh" + s
        if s.startswith("12"):
            return "sz" + s
        if s.startswith("6"):
            return "sh" + s
        if s[:1] in ("0", "3"):
            return "sz" + s
        if s[:1] in ("4", "8"):
            return "bj" + s
        return "sh" + s
    if market == "港股":
        return "hk" + s.zfill(5)
    if market == "美股":
        return "us" + s
    return None


def _norm_quote_date(raw: str):
    """腾讯三种时间格式 -> YYYY-MM-DD。用于判断报价是否属于今天（市场是否开盘）。"""
    if not raw:
        return None
    m = re.match(r"(\d{4})(\d{2})(\d{2})", raw.replace("/", "").replace("-", ""))
    if not m:
        return None
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"


def _tx_quote(market: str, symbol: str):
    """腾讯实时快照。返回 (price, quote_date, source)；失败返回 (None, None, None)。"""
    code = _tx_code(market, symbol)
    if not code:
        return None, None, None
    try:
        r = requests.get(TX_QUOTE_URL + code, timeout=REQ_TIMEOUT, headers=UA)
        r.encoding = "gbk"
        txt = r.text.strip()
        if '="' not in txt or "~" not in txt:
            return None, None, None
        f = txt.split('="', 1)[1].rstrip('";').split("~")
        if len(f) < 31 or not f[3]:
            return None, None, None
        return float(f[3]), _norm_quote_date(f[30]), "腾讯"
    except Exception as e:  # noqa: BLE001
        print(f"[mark_to_market] 腾讯报价失败 {code}: {type(e).__name__}: {str(e)[:80]}",
              file=sys.stderr)
        return None, None, None


def _binance_quote(symbol: str):
    """Binance 24h ticker。返回 (price, quote_date, source)。

    容器内偶发 SSL/DNS 抖动（如 data-api.binance.vision 握手失败）会让单个标的掉出
    盘中估值，故重试 2 次（间隔 1s），避免一次瞬断就把 BTC 等标的排除在外。
    """
    # 持仓键写作 BTC_USDT（下划线），watchlist 写作 BTC/USDT，统一归一成 BTCUSDT
    pair = "".join(ch for ch in str(symbol).upper() if ch.isalnum())
    last_err = ""
    for attempt in range(2):
        try:
            r = requests.get(f"{BINANCE_DATA_API}/api/v3/ticker/24hr",
                             params={"symbol": pair}, timeout=REQ_TIMEOUT, headers=UA)
            r.raise_for_status()
            t = r.json()
            if not isinstance(t, dict) or not t.get("lastPrice"):
                return None, None, None
            # 加密 7x24 交易，报价时刻即当下
            return float(t["lastPrice"]), datetime.now().strftime("%Y-%m-%d"), "Binance"
        except Exception as e:  # noqa: BLE001
            last_err = f"{type(e).__name__}: {str(e)[:80]}"
            if attempt < 1:
                time.sleep(1)
    print(f"[mark_to_market] Binance 报价失败 {symbol}: {last_err}", file=sys.stderr)
    return None, None, None


def fast_quote(market: str, symbol: str):
    """统一快速报价入口：(price, quote_date, source)。"""
    if market == "虚拟货币":
        return _binance_quote(symbol)
    return _tx_quote(market, symbol)


def _load_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        print(f"[mark_to_market] 读取失败 {path.name}: {type(e).__name__}: {e}", file=sys.stderr)
        return None


def _last_nav_row(prefix: str):
    p = DATA_DIR / f"{prefix}_nav.parquet"
    if not p.exists():
        return None, None
    try:
        df = pd.read_parquet(p)
        if df.empty:
            return None, None
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date")
        last = df.iloc[-1]
        return float(last["nav"]), str(last["date"].date())
    except Exception as e:  # noqa: BLE001
        print(f"[mark_to_market] 净值读取失败 {p.name}: {type(e).__name__}: {e}", file=sys.stderr)
        return None, None


def _basis_price(holding: dict, store, market: str, symbol: str, nav_date: str):
    """取「日终净值所使用的价格」作为盘中涨跌的基准。

    优先用持仓里记录的 ``last_price``：它与 last_nav 同源同刻（日终脚本每次都会
    ``h["last_price"] = prices.get(...)``），能避免跨源比较产生的幻影涨跌。
    典型反例：可转债在 data/bars/A股 下没有行情文件，若回落到 bars 会取不到基准，
    拿腾讯实时价和一个错误基准比，凭空算出 +3.6% 的"盘中涨幅"。
    取不到时才回落到本地 bars 收盘。
    """
    lp = (holding or {}).get("last_price")
    if lp:
        return float(lp), "state"
    try:
        df = store.load_bars(market, _safe_name(symbol))
        if df is not None and not df.empty:
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date")
            if nav_date:
                df = df[df["date"] <= pd.Timestamp(nav_date)]
            if not df.empty:
                return float(df["close"].iloc[-1]), "bars"
    except Exception as e:  # noqa: BLE001
        print(f"[mark_to_market] 基准价读取失败 {symbol}: {type(e).__name__}: {e}", file=sys.stderr)
    return None, None


def _positions_of(prefix: str, state: dict):
    """统一成 {symbol: shares}。"""
    holdings = state.get("holdings") or {}
    if holdings:
        return {k: float(v.get("shares", 0.0)) for k, v in holdings.items() if v.get("shares")}
    sym = SINGLE_SHARE_ACCOUNTS.get(prefix)
    if sym and state.get("shares"):
        return {sym: float(state["shares"])}
    return {}


def evaluate():
    store = LocalStore(str(DATA_DIR))
    today = datetime.now().strftime("%Y-%m-%d")
    result = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "today": today,
        "generated_by": "scripts/mark_to_market.py",
        "note": "盘中盯市估值（未结算估计）；已结算的日终净值以 paper_*_nav.parquet 为准",
        "accounts": {},
    }

    for prefix, market, name in ACCOUNT_DEFS:
        state = _load_json(DATA_DIR / f"{prefix}_state.json")
        last_nav, nav_date = _last_nav_row(prefix)
        if state is None:
            continue

        positions = _positions_of(prefix, state)
        cash = float(state.get("cash") or 0.0)

        items, equity, live_cnt, stale, suspect = [], 0.0, 0, [], []
        holdings = state.get("holdings") or {}
        for sym, shares in positions.items():
            price, qdate, source = fast_quote(market, sym)
            basis, basis_src = _basis_price(holdings.get(sym) or {}, store, market, sym, nav_date)

            reason = None
            if price is None:
                price, reason = basis, "取价失败"
            elif qdate and qdate != today:
                # 报价不是今天 → 该市场当前闭市，报价即上次收盘，不算盘中变动
                price, reason = basis, f"闭市(报价 {qdate})"
            if reason:
                source = f"{basis_src or '本地'}基准"
                stale.append(sym)
            else:
                live_cnt += 1

            value = (price or 0.0) * shares
            equity += value
            chg = (price / basis - 1) if (price is not None and basis) else None
            # 单标的盘中偏离 >10% 通常不是真实行情，而是基准价本身有问题
            # （如 akshare 对部分可转债返回面值 100 的缺失占位）——显式标出，不静默计入
            is_suspect = bool(chg is not None and abs(chg) > 0.10)
            if is_suspect:
                suspect.append(sym)
            items.append({
                "symbol": sym, "shares": round(shares, 6), "price": price,
                "basis": basis, "basis_src": basis_src, "chg_pct": chg,
                "value": round(value, 2), "source": source, "reason": reason,
                "suspect": is_suspect,
            })

        equity += cash
        if live_cnt > 0:
            pnl = (equity - last_nav) if last_nav is not None else None
            pct = (pnl / last_nav) if (pnl is not None and last_nav) else None
        else:
            # 全账户无实时价（该市场当前闭市）：此时 equity 只是"用最后收盘重算的日终值"，
            # 与 last_nav 的差来自收盘价/数据源修正，并非盘中变动 → 不展示假的盘中涨跌。
            pnl, pct = None, None

        result["accounts"][prefix] = {
            "name": name, "market": market,
            "last_nav": last_nav, "last_nav_date": nav_date,
            "equity": round(equity, 2), "cash": round(cash, 2),
            "pnl": pnl, "pct": pct,
            "live": live_cnt > 0,
            "live_symbols": live_cnt,
            "total_symbols": len(items),
            "stale_symbols": stale,
            "suspect_symbols": suspect,
            "positions": items,
        }
    return result


def main():
    ap = argparse.ArgumentParser(description="盘中盯市：重估模拟盘账户权益")
    ap.add_argument("--print", dest="do_print", action="store_true", help="打印摘要")
    args = ap.parse_args()

    t0 = time.time()
    result = evaluate()
    OUT_FILE.write_text(json.dumps(_clean(result), ensure_ascii=False, indent=2), encoding="utf-8")
    cost = time.time() - t0

    print(f"[mark_to_market] 盯市完成 {result['ts']} 用时 {cost:.1f}s -> {OUT_FILE}")
    if args.do_print:
        for prefix, a in result["accounts"].items():
            pct = a["pct"]
            pct_s = f"{pct * 100:+.2f}%" if pct is not None else "n/a"
            nav_s = f"{a['last_nav']:,.0f}" if a["last_nav"] is not None else "n/a"
            eq_s = f"{a['equity']:,.0f}" if a["equity"] is not None else "n/a"
            flag = "实时" if a["live"] else "收盘"
            line = (f"  {a['name']:10s} {flag}  日终({a['last_nav_date']}) {nav_s:>12s}"
                    f"  ->  盘中 {eq_s:>12s}  {pct_s:>8s}"
                    f"   [{a['live_symbols']}/{a['total_symbols']} 实时]")
            if a["stale_symbols"]:
                line += f"  非实时: {a['stale_symbols']}"
            print(line)
            if a.get("suspect_symbols"):
                print(f"      ⚠ 基准价存疑（偏离>10%，疑似源返回占位值）: {a['suspect_symbols']}")


if __name__ == "__main__":
    main()
