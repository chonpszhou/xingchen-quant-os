"""统一数据访问层：A股/港股/美股/虚拟货币/期权，主备降级 + 本地缓存"""

from __future__ import annotations

import datetime as dt
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

from .store import LocalStore

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
EM_QUOTE_HOSTS = ("push2.eastmoney.com", "82.push2.eastmoney.com")


@dataclass
class Quote:
    symbol: str
    name: str
    market: str
    price: Optional[float] = None
    change_pct: Optional[float] = None
    volume: Optional[float] = None
    amount: Optional[float] = None
    ts: str = ""
    source: str = ""

    def to_dict(self):
        return {
            "market": self.market, "symbol": self.symbol, "name": self.name,
            "price": self.price, "change_pct": self.change_pct,
            "volume": self.volume, "amount": self.amount, "ts": self.ts, "source": self.source,
        }


def _retry(fn, attempts=3, delay=2.0):
    last = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            if i < attempts - 1:
                time.sleep(delay)
    raise last


def _em_get(path, params, hosts=EM_QUOTE_HOSTS, timeout=15):
    last = None
    for host in hosts:
        try:
            r = requests.get(f"https://{host}{path}", params=params, timeout=timeout, headers=UA)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            last = e
    raise last


def _a_secid(code):
    return ("1." if str(code).startswith("6") else "0.") + str(code)


def _now():
    return dt.datetime.now().isoformat(timespec="seconds")


def _norm_ohlcv(df, source):
    """统一为 date/open/high/low/close/volume(amount 可选)"""
    df = df.copy()
    rename = {
        "日期": "date", "date": "date", "时间": "date",
        "开盘": "open", "open": "open", "Open": "open",
        "最高": "high", "high": "high", "High": "high",
        "最低": "low", "low": "low", "Low": "low",
        "收盘": "close", "close": "close", "Close": "close",
        "成交量": "volume", "volume": "volume", "Volume": "volume",
        "成交额": "amount", "amount": "amount",
    }
    df = df.rename(columns=rename)
    # 腾讯等通道把成交量放进 amount 字段
    if "volume" not in df.columns and "amount" in df.columns:
        df = df.rename(columns={"amount": "volume"})
    df["date"] = pd.to_datetime(df["date"])
    for c in ("open", "high", "low", "close"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    if "volume" in df.columns:
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    else:
        df["volume"] = 0.0
    if "amount" in df.columns:
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    df["source"] = source
    return df[["date", "open", "high", "low", "close", "volume"] + (["amount"] if "amount" in df.columns else []) + ["source"]]


def _empty_ohlcv(source):
    return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume", "source"]).assign(source=source)


INDEX_SH = {"000300", "000852", "000905", "000016", "000688"}
CRYPTO_INDEX = {"INDEX:TOTAL", "INDEX:BTCD"}


def _a_tx_symbol(code):
    code = str(code)
    if code in INDEX_SH:
        return "sh" + code
    if code.startswith(("5", "6", "9")):
        return "sh" + code
    if code.startswith(("4", "8")):
        return "bj" + code
    return "sz" + code


# ---------- A股 ----------

def quote_a_share(code):
    def _em():
        d = _em_get("/api/qt/stock/get", {
            "secid": _a_secid(code), "fltt": "2", "invt": "2",
            "fields": "f43,f57,f58,f170,f47,f48",
        })
        data = d.get("data") or {}
        if data.get("f43") is None:
            raise RuntimeError(f"东财单股接口返回异常: {str(d)[:120]}")
        return Quote(symbol=str(code), name=data.get("f58") or str(code), market="A股",
                     price=data.get("f43"), change_pct=data.get("f170"),
                     volume=data.get("f47"), amount=data.get("f48"), ts=_now(), source="东方财富")
    try:
        return _retry(_em, attempts=3, delay=1.5)
    except Exception:
        import akshare as ak
        df = ak.stock_zh_a_spot()
        hit = df[df["代码"].astype(str) == str(code)]
        if hit.empty:
            raise RuntimeError(f"新浪快照未找到 {code}")
        r = hit.iloc[0]
        return Quote(symbol=str(code), name=r["名称"], market="A股", price=r["最新价"],
                     change_pct=r["涨跌幅"], volume=r["成交量"], amount=r["成交额"], ts=_now(), source="新浪")


def history_a_share(code, start, end, adjust="qfq"):
    if str(code) in INDEX_SH:
        return history_a_index(code, start, end)

    def _em():
        import akshare as ak
        df = ak.stock_zh_a_hist(symbol=str(code), period="daily", start_date=start, end_date=end, adjust=adjust)
        if df is None or df.empty:
            raise RuntimeError("东财历史为空")
        return _norm_ohlcv(df, "东方财富")
    try:
        return _retry(_em, attempts=2, delay=1.5)
    except Exception:
        return _tx_chunked(code, start, end, adjust)


def history_a_index(code, start, end):
    """指数日线：新浪指数通道（EM 指数接口在本版 akshare 缺失）"""
    import akshare as ak

    def _sina():
        df = ak.stock_zh_index_daily(symbol="sh" + str(code))
        if df is None or df.empty:
            raise RuntimeError("新浪指数为空")
        df = _norm_ohlcv(df, "新浪指数")
        return df[(df["date"] >= pd.to_datetime(start)) & (df["date"] <= pd.to_datetime(end))].reset_index(drop=True)

    return _retry(_sina, attempts=3, delay=2)


def _tx_chunked(code, start, end, adjust):
    """腾讯通道按年分片，规避 akshare 多年区间分页空页 bug"""
    import akshare as ak
    sym = _a_tx_symbol(code)
    start_d = dt.date.fromisoformat(start)
    end_d = dt.date.fromisoformat(end)
    chunks = []
    for y in range(start_d.year, end_d.year + 1):
        s, e = max(start_d, dt.date(y, 1, 1)), min(end_d, dt.date(y, 12, 31))
        if s > e:
            continue
        try:
            df = ak.stock_zh_a_hist_tx(
                symbol=sym, start_date=s.strftime("%Y%m%d"), end_date=e.strftime("%Y%m%d"), adjust=adjust,
            )
            if df is not None and not df.empty:
                chunks.append(df)
        except Exception:  # noqa: BLE001
            continue
    if not chunks:
        try:  # 最后兜底：新浪日线
            df = ak.stock_zh_a_daily(symbol=sym, start_date=start, end_date=end, adjust=adjust)
            if df is not None and not df.empty:
                return _norm_ohlcv(df, "新浪")
        except Exception:  # noqa: BLE001
            pass
        return _empty_ohlcv("腾讯")
    df = pd.concat(chunks, ignore_index=True).drop_duplicates(subset="date")
    return _norm_ohlcv(df, "腾讯")


def _tx_fast(code, start, end, adjust="qfq"):
    """腾讯 K线直连（单接口翻页拉全量，提速用）。
    返回 DataFrame(date/open/high/low/close/volume)，失败抛异常。"""
    import requests as _requests
    sym = _a_tx_symbol(code)
    url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    rows, cur_end = [], end
    for _ in range(8):  # 最多 8 页 ≈ 5120 根
        params = {"param": f"{sym},day,{start},{cur_end},640,{adjust}"}
        r = _requests.get(url, params=params, timeout=15, headers=UA)
        r.raise_for_status()
        data = r.json().get("data") or {}
        if not isinstance(data, dict):
            break
        node = data.get(sym) or {}
        page = node.get(adjust + "day") or node.get("day") or []
        if not page:
            break
        rows.extend(page)
        first = page[0][0]
        if first <= start:
            break
        cur_end = first
    if not rows:
        raise RuntimeError(f"腾讯直连为空 {code}")
    rows = [r[:6] for r in rows]  # 兼容腾讯附加字段（第7列起忽略）
    df = pd.DataFrame(rows, columns=["date", "open", "close", "high", "low", "volume"])
    df = df.drop_duplicates(subset="date")
    df = df[(df["date"] >= start) & (df["date"] <= end)]
    df["date"] = pd.to_datetime(df["date"])
    for c in ("open", "close", "high", "low", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.sort_values("date").reset_index(drop=True)
    return _norm_ohlcv(df, "腾讯直连")


def finance_a_share(code):
    import akshare as ak
    return ak.stock_financial_abstract(symbol=str(code))


# ---------- 港股 ----------

def quote_hk(code):
    def _em():
        d = _em_get("/api/qt/stock/get", {
            "secid": "116." + str(code), "fltt": "2", "invt": "2",
            "fields": "f43,f57,f58,f170,f47,f48",
        })
        data = d.get("data") or {}
        if data.get("f43") is None:
            raise RuntimeError(f"东财港股接口返回异常: {str(d)[:120]}")
        return Quote(symbol=str(code), name=data.get("f58") or str(code), market="港股",
                     price=data.get("f43"), change_pct=data.get("f170"),
                     volume=data.get("f47"), amount=data.get("f48"), ts=_now(), source="东方财富")
    try:
        return _retry(_em, attempts=3, delay=1.5)
    except Exception:
        import akshare as ak
        df = ak.stock_hk_spot()
        hit = df[df["代码"].astype(str) == str(code)]
        if hit.empty:
            raise RuntimeError(f"新浪港股快照未找到 {code}")
        r = hit.iloc[0]
        return Quote(symbol=str(code), name=r["名称"], market="港股", price=r["最新价"],
                     change_pct=r["涨跌幅"], volume=r["成交量"], amount=r["成交额"], ts=_now(), source="新浪")


def history_hk(code, start, end, adjust="qfq"):
    def _em():
        import akshare as ak
        df = ak.stock_hk_hist(symbol=str(code), period="daily", start_date=start, end_date=end, adjust=adjust)
        if df is None or df.empty:
            raise RuntimeError("东财港股历史为空")
        return _norm_ohlcv(df, "东方财富")
    try:
        return _retry(_em, attempts=2, delay=1.5)
    except Exception:
        import akshare as ak
        df = ak.stock_hk_daily(symbol=str(code), adjust=adjust)
        if df is None or df.empty:
            raise RuntimeError(f"新浪港股历史为空 {code}")
        df = _norm_ohlcv(df, "新浪")
        return df[(df["date"] >= pd.to_datetime(start)) & (df["date"] <= pd.to_datetime(end))].reset_index(drop=True)


def finance_hk(code):
    import akshare as ak
    return ak.stock_financial_hk_analysis_indicator_em(symbol=str(code), indicator="年度")


# ---------- 美股 ----------

def quote_us(symbol):
    def _yf():
        import yfinance as yf
        fi = yf.Ticker(symbol).fast_info
        price = getattr(fi, "last_price", None)
        if price is None:
            raise RuntimeError("yfinance 未返回最新价")
        prev = getattr(fi, "previous_close", None)
        pct = None
        if prev:
            pct = round((price / prev - 1) * 100, 2)
        return Quote(symbol=symbol, name=symbol, market="美股", price=price, change_pct=pct,
                     ts=_now(), source="Yahoo Finance")
    try:
        return _retry(_yf, attempts=2, delay=3)
    except Exception:
        def _em(prefix):
            d = _em_get("/api/qt/stock/get", {
                "secid": f"{prefix}.{symbol}", "fltt": "2", "invt": "2",
                "fields": "f43,f57,f58,f170,f47,f48",
            })
            data = d.get("data") or {}
            if data.get("f43") is None:
                raise RuntimeError("东财美股接口为空")
            return Quote(symbol=symbol, name=data.get("f58") or symbol, market="美股",
                         price=data.get("f43"), change_pct=data.get("f170"),
                         volume=data.get("f47"), amount=data.get("f48"), ts=_now(), source="东方财富")
        try:
            return _retry(lambda: _em("105"), attempts=2, delay=1.5)
        except Exception:
            return _em("106")


def history_us(symbol, start, end, adjust=None):
    def _yf():
        import yfinance as yf
        df = yf.Ticker(symbol).history(start=start, end=(dt.date.fromisoformat(end) + dt.timedelta(days=1)).isoformat(),
                                       interval="1d", auto_adjust=True)
        if df is None or df.empty:
            raise RuntimeError("yfinance 历史为空")
        df = df.reset_index().rename(columns={"Date": "date", "Open": "open", "High": "high",
                                              "Low": "low", "Close": "close", "Volume": "volume"})
        return _norm_ohlcv(df, "Yahoo Finance")
    try:
        return _retry(_yf, attempts=2, delay=4)
    except Exception:
        try:
            import akshare as ak
            df = ak.stock_us_daily(symbol=symbol, adjust="qfq")
            if df is None or df.empty:
                return _empty_ohlcv("新浪美股")
            df = _norm_ohlcv(df, "新浪美股")
            return df[(df["date"] >= pd.to_datetime(start)) & (df["date"] <= pd.to_datetime(end))].reset_index(drop=True)
        except Exception:
            pass
        import akshare as ak
        for prefix in ("105", "106"):
            try:
                df = ak.stock_us_hist(symbol=f"{prefix}.{symbol}", period="daily", start_date=start, end_date=end, adjust="qfq")
                if df is not None and not df.empty:
                    return _norm_ohlcv(df, "新浪美股")
            except Exception:
                continue
        raise RuntimeError(f"美股历史获取失败 {symbol}")


def finance_us(symbol):
    def _yf():
        import yfinance as yf
        stmt = yf.Ticker(symbol).income_stmt
        if stmt is None or stmt.shape[1] == 0:
            raise RuntimeError("yfinance 财务为空")
        return stmt
    try:
        return _retry(_yf, attempts=2, delay=3)
    except Exception:
        import akshare as ak
        return ak.stock_financial_us_analysis_indicator_em(symbol=symbol, indicator="年报")


def option_us(symbol):
    import yfinance as yf
    chain = yf.Ticker(symbol).option_chain()
    return {"calls": chain.calls, "puts": chain.puts, "expiry": str(chain.calls.index.name or "")}


# ---------- 虚拟货币（直连 REST，规避 ccxt 多请求在当前网络的抖动） ----------


def _okx_ticker(symbol):
    inst = symbol.replace("/", "-")
    r = requests.get("https://www.okx.com/api/v5/market/ticker", params={"instId": inst}, timeout=12)
    r.raise_for_status()
    data = r.json()
    if data.get("code") != "0" or not data.get("data"):
        raise RuntimeError(f"OKX ticker 异常: {str(data)[:120]}")
    t = data["data"][0]
    last, op = float(t["last"]), float(t["open24h"])
    pct = round((last / op - 1) * 100, 2) if op else None
    return Quote(symbol=symbol, name=symbol, market="虚拟货币", price=last, change_pct=pct,
                 volume=float(t["vol24h"]), amount=float(t["volCcy24h"]), ts=_now(), source="OKX")


def _gate_ticker(symbol):
    pair = symbol.replace("/", "_")
    r = requests.get("https://api.gateio.ws/api/v4/spot/tickers", params={"currency_pair": pair}, timeout=12)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list) or not data:
        raise RuntimeError("Gate ticker 为空")
    t = data[0]
    return Quote(symbol=symbol, name=symbol, market="虚拟货币", price=float(t["last"]),
                 change_pct=float(t["change_percentage"]), volume=float(t["base_volume"]),
                 amount=float(t["quote_volume"]), ts=_now(), source="Gate")


def quote_crypto(symbol):
    if symbol in CRYPTO_INDEX:
        return quote_crypto_index(symbol)
    try:
        return _retry(lambda: _okx_ticker(symbol), attempts=3, delay=2)
    except Exception:
        return _retry(lambda: _gate_ticker(symbol), attempts=3, delay=2)


def quote_crypto_index(symbol):
    r = requests.get("https://api.coingecko.com/api/v3/global", timeout=15)
    r.raise_for_status()
    data = (r.json() or {}).get("data") or {}
    if symbol == "INDEX:TOTAL":
        return Quote(symbol=symbol, name="加密货币总市值", market="虚拟货币",
                     price=data.get("total_market_cap", {}).get("usd"), ts=_now(), source="CoinGecko")
    if symbol == "INDEX:BTCD":
        return Quote(symbol=symbol, name="BTC主导率", market="虚拟货币",
                     price=data.get("market_cap_percentage", {}).get("btc"),
                     change_pct=None, ts=_now(), source="CoinGecko")
    raise ValueError(f"未知加密指数: {symbol}")


def _okx_ohlcv(symbol, start, end):
    inst = symbol.replace("/", "-")
    start_ms = int(pd.Timestamp(start).timestamp() * 1000)
    after = int(pd.Timestamp(end).timestamp() * 1000)
    raw = []
    for _ in range(16):  # OKX 单次最多 100 根，4 年日线需 15+ 页
        r = requests.get("https://www.okx.com/api/v5/market/candles",
                         params={"instId": inst, "bar": "1D", "limit": "100", "after": str(after)}, timeout=15)
        r.raise_for_status()
        data = (r.json() or {}).get("data") or []
        if not data:
            break
        raw.extend(data)
        oldest = int(data[-1][0])
        if oldest <= start_ms:
            break
        after = oldest
        time.sleep(0.25)
    rows = [{"ts": int(x[0]), "open": float(x[1]), "high": float(x[2]),
             "low": float(x[3]), "close": float(x[4]), "volume": float(x[5])} for x in raw]
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["ts"], unit="ms", utc=True).dt.tz_convert("Asia/Shanghai").dt.date
    df = df[(df["date"].astype(str) >= start) & (df["date"].astype(str) <= end)].copy()
    return _norm_ohlcv(df, "OKX")


def _gate_ohlcv(symbol, start, end):
    pair = symbol.replace("/", "_")
    r = requests.get("https://api.gateio.ws/api/v4/spot/candlesticks",
                     params={"currency_pair": pair, "interval": "1d", "limit": "1000"}, timeout=15)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list) or not data:
        raise RuntimeError("Gate candles 为空")
    rows = [{"ts": int(x[0]), "open": float(x[5]), "high": float(x[3]),
             "low": float(x[4]), "close": float(x[2]), "volume": float(x[6])} for x in data]
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_convert("Asia/Shanghai").dt.date
    df = df[(df["date"].astype(str) >= start) & (df["date"].astype(str) <= end)].copy()
    return _norm_ohlcv(df, "Gate")


def history_crypto(symbol, start, end, adjust=None):
    if symbol in CRYPTO_INDEX:
        return _empty_ohlcv("CoinGecko")
    try:
        return _retry(lambda: _okx_ohlcv(symbol, start, end), attempts=2, delay=2)
    except Exception:
        return _retry(lambda: _gate_ohlcv(symbol, start, end), attempts=2, delay=2)


# ---------- 期权 ----------

def option_cn_snapshot():
    import akshare as ak
    return ak.option_current_em()


# ---------- 统一入口 ----------

class DataHub:
    def __init__(self, watchlist: str = "config/watchlist.json", data_dir: str = "data"):
        self.watchlist = self._load_watchlist(watchlist)
        self.store = LocalStore(data_dir)

    @staticmethod
    def _load_watchlist(path):
        p = Path(path)
        if not p.exists():
            return []
        data = json.loads(p.read_text(encoding="utf-8"))
        return data.get("records", [])

    def _resolve(self, item):
        """期权市场条目解析到底层市场（ETF→A股 / ticker→美股 / 交易对→加密）"""
        market = item["market"]
        if market != "期权":
            return market, item["symbol"]
        sym = item["symbol"]
        if "/" in sym:
            return "虚拟货币", sym
        if sym.isdigit():
            return "A股", sym
        return "美股", sym

    def watch_symbols(self, markets=None):
        seen, out = set(), []
        for item in self.watchlist:
            m, s = self._resolve(item)
            if markets and m not in markets:
                continue
            key = (m, s)
            if key in seen:
                continue
            seen.add(key)
            out.append({"market": m, "symbol": s, "name": item["name"], "group": item.get("group", "")})
        return out

    # ---------- 实时行情 ----------

    def quote(self, market: str, symbol: str) -> Quote:
        if market == "A股":
            return quote_a_share(symbol)
        if market == "港股":
            return quote_hk(symbol)
        if market == "美股":
            return quote_us(symbol)
        if market == "虚拟货币":
            return quote_crypto(symbol)
        raise ValueError(f"不支持的板块: {market}")

    def quotes(self, markets=None, symbols=None):
        result = []
        for item in self.watch_symbols(markets):
            if symbols and item["symbol"] not in symbols:
                continue
            try:
                q = self.quote(item["market"], item["symbol"])
                q.name = item["name"]
                result.append(q)
            except Exception as e:  # noqa: BLE001
                result.append(Quote(symbol=item["symbol"], name=item["name"], market=item["market"],
                                    ts=_now(), source="ERROR", price=None))
                result[-1]._error = str(e)[:120]  # type: ignore[attr-defined]
        return result

    # ---------- 历史数据 ----------

    def history(self, market: str, symbol: str, start=None, end=None, adjust="qfq"):
        end = end or dt.date.today().isoformat()
        start = start or (dt.date.today() - dt.timedelta(days=120)).isoformat()
        if market == "A股":
            return history_a_share(symbol, start, end, adjust)
        if market == "港股":
            return history_hk(symbol, start, end, adjust)
        if market == "美股":
            return history_us(symbol, start, end, adjust)
        if market == "虚拟货币":
            return history_crypto(symbol, start, end, adjust)
        raise ValueError(f"不支持的板块: {market}")

    def update(self, markets=None, symbols=None, lookback_days=120, adjust="qfq", force=False):
        stats = {"ok": 0, "skip": 0, "failed": 0, "errors": []}
        items = self.watch_symbols(markets)
        if symbols:
            items = [i for i in items if i["symbol"] in symbols]
        for i, item in enumerate(items, 1):
            m, s = item["market"], item["symbol"]
            print(f"[{i}/{len(items)}] {m} {s} {item['name']}", flush=True)
            try:
                start = self.store.incremental_start(m, s, lookback_days, force)
                if start > dt.date.today().isoformat():
                    stats["skip"] += 1
                    continue
                df = self.history(m, s, start=start, end=dt.date.today().isoformat(), adjust=adjust)
                if df is None or df.empty:
                    stats["skip"] += 1
                    print("    无新数据", flush=True)
                    continue
                self.store.save_bars(m, s, df)
                source = df["source"].iloc[-1] if "source" in df.columns else "unknown"
                self.store.set_status(m, s, df["date"].max().date(), source)
                stats["ok"] += 1
                print(f"    ✅ {len(df)} 根K线（{df['date'].min().date()} ~ {df['date'].max().date()}，{source}）", flush=True)
            except Exception as e:  # noqa: BLE001
                stats["failed"] += 1
                msg = f"{m} {s}: {type(e).__name__}: {str(e)[:150]}"
                stats["errors"].append(msg)
                print(f"    ❌ {msg}", flush=True)
        return stats

    def status(self):
        return self.store.all_status()

    def bars(self, market: str, symbol: str, limit: int = 30):
        df = self.store.load_bars(market, symbol)
        if df is None:
            return None
        return df.tail(limit).reset_index(drop=True)

    def finance(self, market: str, symbol: str):
        if market == "A股":
            return finance_a_share(symbol)
        if market == "港股":
            return finance_hk(symbol)
        if market == "美股":
            return finance_us(symbol)
        raise ValueError(f"板块 {market} 暂无财务接口")

    def option_chain(self, market: str, symbol: str):
        if market == "美股":
            return option_us(symbol)
        if market == "A股":
            return option_cn_snapshot()
        raise ValueError(f"板块 {market} 暂无期权链接口")
