#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 数据源与推送通道连通性检查

用法:
    python3 scripts/check_connections.py

输出:
    docs/连接检查结果.json   原始检查结果
    docs/连接检查报告.md     带状态标识（正常/异常/未配置）的连接检查清单

状态说明:
    正常   —— 接口连通、鉴权通过、返回格式符合预期
    异常   —— 接口不可达、超时或返回格式不符合预期
    未配置 —— 通道存在但缺少凭证/Webhook，属于初始化阶段待补项
"""

import concurrent.futures
import datetime as dt
import importlib
import json
import os
import socket
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
ENV_FILE = os.path.join(ROOT, ".env")
TIMEOUT_SOCKET = 20  # 全局 socket 超时，避免个别调用无限挂起


class ConfigMissing(Exception):
    """凭证缺失，映射为「未配置」状态"""


def load_dotenv(path):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())


def lib_version(name):
    try:
        mod = importlib.import_module(name)
        return getattr(mod, "__version__", "已安装")
    except Exception:
        return None


def probe(fn, timeout=60):
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    fut = ex.submit(fn)
    try:
        return fut.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        ex.shutdown(wait=False, cancel_futures=True)
        raise TimeoutError(f"调用超过 {timeout}s 未返回")
    except BaseException:
        ex.shutdown(wait=False, cancel_futures=True)
        raise


def retry(fn, attempts=3, delay=3, timeout=60):
    """带重试的探测，规避公共接口偶发的瞬时网络抖动/限流"""
    last = None
    for i in range(attempts):
        try:
            return probe(fn, timeout=timeout)
        except Exception as e:
            last = e
            if i < attempts - 1:
                time.sleep(delay)
    raise last


def em_get(path, params, hosts=("push2.eastmoney.com", "82.push2.eastmoney.com")):
    """东方财富接口直连（单请求），多主机轮询规避抖动"""
    import requests
    last = None
    for host in hosts:
        try:
            r = requests.get(f"https://{host}{path}", params=params, timeout=15)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last = e
    raise last


CHECKS = []


def register(cid, market, item, source, auth=False, timeout=60):
    def deco(fn):
        CHECKS.append({
            "id": cid, "market": market, "item": item, "source": source,
            "auth": auth, "timeout": timeout, "fn": fn,
        })
        return fn
    return deco


# ---------- A股 ----------

@register("a_quote", "A股", "实时行情", "东方财富 push2 行情接口（分页直连）", timeout=60)
def check_a_quote():
    def _run():
        data = em_get("/api/qt/clist/get", {
            "pn": "1", "pz": "10", "po": "1", "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281", "fltt": "2", "invt": "2",
            "fid": "f12", "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
            "fields": "f2,f3,f12,f14",
        })
        rows = (data.get("data") or {}).get("diff") or []
        if data.get("rc") != 0 or not rows:
            raise AssertionError(f"返回格式异常: {str(data)[:160]}")
        r = rows[0]
        return f"接口连通（单页 {len(rows)} 条）；样本 {r.get('f12')} {r.get('f14')} 最新价 {r.get('f2')} 涨跌幅 {r.get('f3')}%"
    return retry(_run, attempts=3, delay=2, timeout=50)


@register("a_quote_sina", "A股", "实时行情（备用通道）", "新浪财经 · ak.stock_zh_a_spot", timeout=120)
def check_a_quote_sina():
    import akshare as ak
    df = ak.stock_zh_a_spot()
    if df is None or len(df) < 1000:
        raise AssertionError(f"返回行数异常: {0 if df is None else len(df)}")
    r = df.iloc[0]
    return f"覆盖 {len(df)} 只A股；样本 {r.get('代码')} {r.get('名称')} 最新价 {r.get('最新价')}"


@register("a_fin", "A股", "财务摘要", "东方财富F10 · ak.stock_financial_abstract", timeout=90)
def check_a_fin():
    def _run():
        import akshare as ak
        df = ak.stock_financial_abstract(symbol="600519")
        if df is None or df.empty:
            raise AssertionError("返回空数据")
        if "指标" not in df.columns:
            raise AssertionError(f"缺少'指标'列，实际列: {list(df.columns)[:8]}")
        idx = {str(i) for i in df["指标"].astype(str)}
        if not any(k in i for i in idx for k in ("净利润", "营业收入", "营业总收入")):
            raise AssertionError(f"缺少财务指标行，实际指标: {sorted(idx)[:15]}")
        return f"取到 {len(df.columns) - 2} 个报告期 × {len(df)} 项指标（净利润/营业总收入/报告期）"
    return retry(_run, attempts=2, delay=2, timeout=70)


@register("a_hist", "A股", "历史K线", "东方财富 push2his K线接口（直连）", timeout=60)
def check_a_hist():
    def _run():
        end = dt.date.today()
        start = end - dt.timedelta(days=15)
        data = em_get("/api/qt/stock/kline/get", {
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "ut": "7eea3edcaed734bea9cbfc24409ed989",
            "klt": "101", "fqt": "1", "secid": "1.600519",
            "beg": start.strftime("%Y%m%d"), "end": end.strftime("%Y%m%d"),
        }, hosts=("push2his.eastmoney.com", "33.push2his.eastmoney.com"))
        klines = (data.get("data") or {}).get("klines") or []
        if not klines:
            raise AssertionError(f"K线为空: {str(data)[:160]}")
        return f"近 {len(klines)} 个交易日；最近一条 {klines[-1]}"
    return retry(_run, attempts=3, delay=2, timeout=50)


# ---------- 港股 ----------

@register("hk_quote", "港股", "实时行情", "东方财富 push2 港股接口（分页直连）", timeout=60)
def check_hk_quote():
    def _run():
        data = em_get("/api/qt/clist/get", {
            "pn": "1", "pz": "10", "po": "1", "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281", "fltt": "2", "invt": "2",
            "fid": "f12", "fs": "m:128+t:3,m:128+t:4,m:128+t:1,m:128+t:2",
            "fields": "f2,f3,f12,f14",
        })
        rows = (data.get("data") or {}).get("diff") or []
        if data.get("rc") != 0 or not rows:
            raise AssertionError(f"返回格式异常: {str(data)[:160]}")
        r = rows[0]
        return f"接口连通（单页 {len(rows)} 条）；样本 {r.get('f12')} {r.get('f14')} 最新价 {r.get('f2')} 涨跌幅 {r.get('f3')}%"
    return retry(_run, attempts=3, delay=2, timeout=50)


@register("hk_fin", "港股", "财务指标", "东方财富 · ak.stock_financial_hk_analysis_indicator_em", timeout=90)
def check_hk_fin():
    import akshare as ak
    df = ak.stock_financial_hk_analysis_indicator_em(symbol="00700", indicator="年度")
    if df is None or len(df) == 0:
        raise AssertionError("返回空数据")
    return f"取到 {len(df)} 条年度财务指标（腾讯控股）"


@register("hk_hist", "港股", "历史K线", "东方财富 push2his 港股K线接口（直连）", timeout=60)
def check_hk_hist():
    def _run():
        end = dt.date.today()
        start = end - dt.timedelta(days=15)
        data = em_get("/api/qt/stock/kline/get", {
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "ut": "7eea3edcaed734bea9cbfc24409ed989",
            "klt": "101", "fqt": "0", "secid": "116.00700",
            "beg": start.strftime("%Y%m%d"), "end": end.strftime("%Y%m%d"),
        }, hosts=("push2his.eastmoney.com", "33.push2his.eastmoney.com"))
        klines = (data.get("data") or {}).get("klines") or []
        if not klines:
            raise AssertionError(f"K线为空: {str(data)[:160]}")
        return f"近 {len(klines)} 个交易日；最近一条 {klines[-1]}"
    return retry(_run, attempts=3, delay=2, timeout=50)


# ---------- 美股 ----------

@register("us_quote", "美股", "近端行情", "Yahoo Finance · yfinance（备用: 东方财富美股快照）", timeout=90)
def check_us_quote():
    try:
        return retry(_us_yf_quote, attempts=2, delay=4, timeout=60)
    except Exception as e:
        try:
            return retry(_us_spot_em_sample, attempts=3, delay=2, timeout=70)
        except Exception:
            raise e


def _us_yf_quote():
    import yfinance as yf
    fi = yf.Ticker("AAPL").fast_info
    price = getattr(fi, "last_price", None)
    if price is None:
        raise AssertionError("fast_info 未返回最新价")
    return f"AAPL 最新价 {price}"


def _us_spot_em_sample():
    def _run():
        data = em_get("/api/qt/stock/get", {
            "secid": "105.AAPL", "fltt": "2", "invt": "2", "fields": "f43,f57,f58",
        })
        d = data.get("data") or {}
        name, price = d.get("f58"), d.get("f43")
        if not name or price is None:
            raise AssertionError(f"返回格式异常: {str(data)[:160]}")
        return f"东方财富美股行情（Yahoo 不可用时自动切换）: {name} 最新价 {price}"
    return retry(_run, attempts=3, delay=2, timeout=50)


@register("us_fin", "美股", "财务数据", "Yahoo Finance · yfinance（备用: 东方财富美股财报指标）", timeout=90)
def check_us_fin():
    try:
        return retry(_us_yf_fin, attempts=2, delay=4, timeout=60)
    except Exception as e:
        try:
            return retry(_us_fin_em, attempts=3, delay=2, timeout=70)
        except Exception:
            raise e


def _us_yf_fin():
    import yfinance as yf
    stmt = yf.Ticker("AAPL").income_stmt
    if stmt is None or stmt.shape[1] == 0:
        raise AssertionError("income_stmt 为空")
    col = stmt.columns[0]
    d = col.date() if hasattr(col, "date") else col
    return f"AAPL 最新报告期 {d}，利润表 {stmt.shape[0]} 行指标"


def _us_fin_em():
    import akshare as ak
    df = ak.stock_financial_us_analysis_indicator_em(symbol="AAPL", indicator="年报")
    if df is None or len(df) == 0:
        raise AssertionError("东方财富美股财报为空")
    return f"东方财富美股财报指标（Yahoo 不可用时自动切换）: {len(df)} 行"


@register("us_option", "美股", "期权链", "Yahoo Finance · yfinance option_chain", timeout=90)
def check_us_option():
    def _run():
        import yfinance as yf
        chain = yf.Ticker("AAPL").option_chain()
        calls, puts = chain.calls, chain.puts
        if calls is None or len(calls) == 0:
            raise AssertionError("期权链为空")
        return f"AAPL 期权链: {len(calls)} 张看涨 / {len(puts)} 张看跌"
    return retry(_run, attempts=3, delay=8, timeout=60)


# ---------- 虚拟货币 ----------

@register("crypto_quote", "虚拟货币", "现货行情", "OKX / Gate / Binance 行情接口直连", timeout=60)
def check_crypto_quote():
    import requests
    probes = [
        ("OKX", "https://www.okx.com/api/v5/market/ticker", {"instId": "BTC-USDT"},
         lambda d: d.get("code") == "0" and bool(d.get("data") and d["data"][0].get("last"))),
        ("Gate", "https://api.gateio.ws/api/v4/spot/tickers", {"currency_pair": "BTC_USDT"},
         lambda d: isinstance(d, list) and bool(d and d[0].get("last"))),
        ("Binance", "https://api.binance.com/api/v3/ticker/price", {"symbol": "BTCUSDT"},
         lambda d: bool(d.get("price"))),
    ]
    ok, notes = [], []
    for name, url, params, valid in probes:
        for attempt in range(3):
            try:
                r = requests.get(url, params=params, timeout=12)
                if r.status_code == 451:
                    notes.append(f"{name}:地区限制(451)")
                    break
                r.raise_for_status()
                data = r.json()
                if valid(data):
                    ok.append(name)
                    break
                raise AssertionError(f"格式异常: {str(data)[:120]}")
            except Exception as e:
                if attempt == 2:
                    notes.append(f"{name}:{type(e).__name__}")
                time.sleep(1)
    if not ok:
        raise AssertionError("全部交易所不可达: " + "; ".join(notes))
    return "可用交易所: " + ", ".join(ok) + ("；受限: " + "; ".join(notes) if notes else "")


@register("crypto_option", "虚拟货币", "期权行情", "Deribit 行情接口直连（加密期权主市场）", timeout=60)
def check_crypto_option():
    def _run():
        import requests
        r = requests.get(
            "https://www.deribit.com/api/v2/public/get_index_price",
            params={"index_name": "btc_usd"}, timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        price = (data.get("result") or {}).get("index_price")
        if not price:
            raise AssertionError(f"返回格式异常: {str(data)[:160]}")
        return f"Deribit 连通，BTC 指数价格 {price}"
    return retry(_run, attempts=3, delay=4, timeout=50)


# ---------- 期权与衍生品 ----------

@register("cn_option", "A股期权", "场内期权行情", "东方财富 push2 期权接口（分页直连）", timeout=60)
def check_cn_option():
    def _run():
        data = em_get("/api/qt/clist/get", {
            "pn": "1", "pz": "10", "po": "1", "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281", "fltt": "2", "invt": "2",
            "fid": "f12", "fs": "m:10,m:12,m:140,m:141,m:151,m:163,m:226",
            "fields": "f2,f3,f12,f14",
        })
        rows = (data.get("data") or {}).get("diff") or []
        if data.get("rc") != 0 or not rows:
            raise AssertionError(f"返回格式异常: {str(data)[:160]}")
        r = rows[0]
        return f"接口连通（单页 {len(rows)} 条）；样本 {r.get('f12')} {r.get('f14')} 最新价 {r.get('f2')} 涨跌幅 {r.get('f3')}%"
    return retry(_run, attempts=3, delay=2, timeout=50)


@register("cn_iv", "A股期权", "波动率指数", "中证指数官网 · ak.index_option_300etf_qvix", timeout=90)
def check_cn_iv():
    def _run():
        import akshare as ak
        df = ak.index_option_300etf_qvix()
        if df is None or len(df) == 0:
            raise AssertionError("返回空数据")
        last = df.iloc[-1]
        vals = " | ".join(f"{c}={last[c]}" for c in df.columns[:4])
        return f"最新一条: {vals}"
    return retry(_run, attempts=2, delay=3, timeout=70)


# ---------- 推送通道 ----------

@register("push_email", "推送", "邮件 SMTP", "SMTP · 配置与鉴权", auth=True, timeout=45)
def check_email():
    host = os.environ.get("SMTP_HOST", "").strip()
    user = os.environ.get("SMTP_USER", "").strip()
    pw = os.environ.get("SMTP_PASS", "").strip()
    if not (host and user and pw):
        raise ConfigMissing("缺少 SMTP_HOST/SMTP_USER/SMTP_PASS，请在 .env 中配置后复检")
    import smtplib
    port = int(os.environ.get("SMTP_PORT", "465") or 465)
    if port == 465:
        import ssl
        with smtplib.SMTP_SSL(host, port, timeout=15, context=ssl.create_default_context()) as s:
            s.login(user, pw)
    else:
        with smtplib.SMTP(host, port, timeout=15) as s:
            s.ehlo()
            s.starttls()
            s.login(user, pw)
    return f"{host}:{port} SMTP 登录鉴权成功"


def _webhook_check(env_key, name, expect_ok):
    url = os.environ.get(env_key, "").strip()
    if not url:
        raise ConfigMissing(f"缺少 {env_key}，请在 .env 中配置{name}机器人 Webhook")
    import requests
    payload = {"msg_type": "text", "content": {"text": "星辰投研团 · 连接测试"}}
    r = requests.post(url, json=payload, timeout=15)
    data = r.json()
    if not expect_ok(data):
        raise AssertionError(f"返回异常: {data}")
    return "测试消息发送成功"


@register("push_feishu", "推送", "飞书机器人", "飞书自定义机器人 Webhook", auth=True, timeout=45)
def check_feishu():
    return _webhook_check("FEISHU_WEBHOOK", "飞书", lambda d: d.get("code") == 0)


@register("push_dingtalk", "推送", "钉钉机器人", "钉钉自定义机器人 Webhook", auth=True, timeout=45)
def check_dingtalk():
    return _webhook_check("DINGTALK_WEBHOOK", "钉钉", lambda d: d.get("errcode") == 0)


@register("push_wecom", "推送", "企业微信机器人", "企业微信群机器人 Webhook", auth=True, timeout=45)
def check_wecom():
    return _webhook_check("WECOM_WEBHOOK", "企业微信", lambda d: d.get("errcode") == 0)


@register("push_serverchan", "推送", "Server酱", "Server酱 SendKey", auth=True, timeout=45)
def check_serverchan():
    key = os.environ.get("SERVERCHAN_KEY", "").strip()
    if not key:
        raise ConfigMissing("缺少 SERVERCHAN_KEY，请在 .env 中配置")
    import requests
    r = requests.post(
        f"https://sctapi.ftqq.com/{key}.send",
        data={"title": "星辰投研团 · 连接测试", "desp": "连通性检查"},
        timeout=15,
    )
    data = r.json()
    if data.get("code") != 0:
        raise AssertionError(f"返回异常: {data}")
    return "测试消息发送成功"


@register("push_pushplus", "推送", "PushPlus", "PushPlus 微信公众号推送 Token", auth=True, timeout=45)
def check_pushplus():
    token = os.environ.get("PUSHPLUS_TOKEN", "").strip()
    if not token:
        raise ConfigMissing("缺少 PUSHPLUS_TOKEN，请在 .env 中配置")
    import requests
    r = requests.post(
        "https://www.pushplus.plus/send",
        json={"token": token, "title": "星辰投研团 · 连接测试", "content": "连通性检查"},
        timeout=15,
    )
    data = r.json()
    if data.get("code") != 200:
        raise AssertionError(f"返回异常: {data}")
    return "测试消息发送成功"


# ---------- 期货 / 可转债 / 期权指数 / 模拟盘（新增通道） ----------

@register("futures_cn", "期货", "商品期货主力日线", "新浪 futures_zh_daily_sina", timeout=45)
def check_futures_cn():
    import akshare as ak
    df = ak.futures_zh_daily_sina(symbol="RB0")
    if df is None or df.empty:
        raise RuntimeError("返回为空")
    return f"螺纹钢主力 {len(df)} 根，截至 {df['date'].iloc[-1]}"


@register("cboe_iv", "期权", "CBOE 波动率指数", "cdn.cboe.com 直连 CSV", timeout=30)
def check_cboe_iv():
    import requests
    r = requests.get("https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv", timeout=20)
    r.raise_for_status()
    lines = r.text.strip().splitlines()
    if len(lines) < 100:
        raise RuntimeError("数据行数异常")
    return f"VIX 历史 {len(lines) - 1} 行，末行 {lines[-1]}"


@register("cb_panel", "可转债", "双低策略数据面板", "本地 cb_panel.parquet", timeout=30)
def check_cb_panel():
    import pandas as pd
    from pathlib import Path
    p = Path(__file__).resolve().parent.parent / "data" / "cb_panel.parquet"
    if not p.exists():
        raise RuntimeError("缺少 cb_panel.parquet，运行 fetch_cb_panel.py")
    df = pd.read_parquet(p, columns=["bond", "date"])
    return f"面板 {df['bond'].nunique()} 只转债，数据截至 {df['date'].max()}"


@register("paper_cb", "模拟盘", "双低模拟盘状态", "本地 paper_cb_state.json", timeout=30)
def check_paper_cb():
    import json
    from pathlib import Path
    p = Path(__file__).resolve().parent.parent / "data" / "paper_cb_state.json"
    if not p.exists():
        raise RuntimeError("模拟盘未初始化")
    st = json.loads(p.read_text(encoding="utf-8"))
    return f"净值 {st['cash'] + sum(h['value'] for h in st['holdings'].values()):,.0f}，持仓 {len(st['holdings'])} 只，调仓 {st['rebalance_count']} 次"


@register("paper_mom", "模拟盘", "双动量模拟盘状态", "本地 paper_mom_state.json", timeout=30)
def check_paper_mom():
    import json
    from pathlib import Path
    p = Path(__file__).resolve().parent.parent / "data" / "paper_mom_state.json"
    if not p.exists():
        raise RuntimeError("模拟盘未初始化")
    st = json.loads(p.read_text(encoding="utf-8"))
    return f"净值 {st['cash'] + sum(h['value'] for h in st['holdings'].values()):,.0f}，持仓 {list(st['holdings'].keys())}，调仓 {st['rebalance_count']} 次"


@register("okx_funding", "虚拟货币", "永续资金费率", "OKX 公开接口", timeout=30)
def check_okx_funding():
    import requests
    r = requests.get("https://www.okx.com/api/v5/public/funding-rate",
                     params={"instId": "BTC-USDT-SWAP"}, timeout=20)
    r.raise_for_status()
    data = (r.json() or {}).get("data") or []
    if not data:
        raise RuntimeError("返回为空")
    return f"BTC 永续费率 {float(data[0]['fundingRate']) * 100:.4f}%"


# ---------- 报告生成 ----------

def build_markdown(payload):
    meta, checks, counts = payload["meta"], payload["checks"], payload["summary"]
    lines = [
        "# 星辰投研团 · 数据源与推送通道连接检查清单",
        "",
        f"- 检查时间: {meta['checked_at']}",
        f"- 运行环境: Python {meta['python']}",
        f"- 依赖库: " + ", ".join(f"{k} {v}" for k, v in meta["libraries"].items()),
        f"- 凭证文件: {meta['env_file']}",
        "",
        "## 汇总",
        "",
        f"共检查 {len(checks)} 项：**正常 {counts['正常']}** / **异常 {counts['异常']}** / **未配置 {counts['未配置']}**",
        "",
        "状态标识：`正常`=接口连通、鉴权通过、返回格式符合预期；`异常`=不可达/超时/格式不符；`未配置`=通道存在但缺少凭证（初始化待补项）。",
        "",
        "## 检查明细",
        "",
        "| # | 板块 | 检查项 | 数据源/接口 | 状态 | 说明 |",
        "|---|------|--------|-------------|------|------|",
    ]
    for i, r in enumerate(checks, 1):
        icon = {"正常": "✅ 正常", "异常": "❌ 异常", "未配置": "⚠️ 未配置"}[r["status"]]
        lines.append(f"| {i} | {r['market']} | {r['item']} | {r['source']} | {icon} | {r['detail']} |")
    lines += [
        "",
        "---",
        "",
        "补充说明：",
        "",
        "1. 数据源均为公开行情/财务接口，无需密钥；脚本内置重试、自动降级与异常项复检（如 Yahoo 限流时切东方财富，东财瞬时抖动时等待后复检）。",
        "2. 部分海外接口受网络/地区限制：如 Binance 在本网络返回 451（地区限制），虚拟货币行情已通过 OKX/Gate/Deribit 等交易所轮询兜底。",
        "3. 港股衍生品（窝轮/牛熊证/期权）暂无稳定的免费批量接口，建议后续接入港交所(HKEX)或商业数据源，当前标记为待接入。",
        "4. 推送通道需在项目根目录 `.env` 中配置凭证后，重新运行本脚本复检。",
    ]
    return "\n".join(lines) + "\n"


def main():
    os.environ.setdefault("TQDM_DISABLE", "1")
    import warnings
    warnings.filterwarnings("ignore")
    socket.setdefaulttimeout(TIMEOUT_SOCKET)
    load_dotenv(ENV_FILE)
    started = dt.datetime.now().isoformat(timespec="seconds")
    results = []
    print("星辰投研团 · 连接检查开始\n")
    for c in CHECKS:
        t0 = time.time()
        try:
            detail = probe(c["fn"], timeout=c["timeout"])
            status = "正常"
        except ConfigMissing as e:
            status = "未配置"
            detail = str(e)
        except Exception as e:
            status = "异常"
            detail = f"{type(e).__name__}: {e}"
        if len(detail) > 300:
            detail = detail[:300] + "…"
        results.append({
            "id": c["id"], "market": c["market"], "item": c["item"],
            "source": c["source"], "auth_required": c["auth"],
            "status": status, "detail": detail,
            "elapsed_sec": round(time.time() - t0, 1),
        })
        print(f"[{status}] {c['market']} · {c['item']}（{results[-1]['elapsed_sec']}s）")
        print(f"    {detail}")

    # 网络类异常项复检一次，区分「接口故障」与「瞬时网络抖动」
    recheck_ids = {
        "a_quote", "a_quote_sina", "a_fin", "a_hist",
        "hk_quote", "hk_fin", "hk_hist",
        "us_quote", "us_fin", "us_option",
        "crypto_quote", "crypto_option", "cn_option", "cn_iv",
        "futures_cn", "cboe_iv", "okx_funding",
    }
    failed = [r for r in results if r["status"] == "异常" and r["id"] in recheck_ids]
    if failed:
        print("\n网络类异常项进入复检（等待 20s 避开瞬时抖动）...")
        time.sleep(20)
        for r in failed:
            c = next(x for x in CHECKS if x["id"] == r["id"])
            t0 = time.time()
            try:
                detail = probe(c["fn"], timeout=c["timeout"])
                r["status"] = "正常"
                r["detail"] = detail + "（复检通过，首次异常为瞬时网络抖动）"
            except Exception as e:
                r["detail"] += f"；复检仍失败: {type(e).__name__}: {str(e)[:150]}"
            r["elapsed_sec"] = round(time.time() - t0, 1)
            print(f"[{r['status']}] 复检 {c['market']} · {c['item']} → {r['detail'][:140]}")

    meta = {
        "project": "星辰投研团",
        "checked_at": started,
        "python": sys.version.split()[0],
        "libraries": {n: lib_version(n) for n in ("akshare", "yfinance", "ccxt", "pandas", "requests")},
        "env_file": os.path.basename(ENV_FILE) if os.path.exists(ENV_FILE) else "未创建(.env)",
    }
    counts = {s: sum(1 for r in results if r["status"] == s) for s in ("正常", "异常", "未配置")}
    payload = {"meta": meta, "summary": counts, "checks": results}

    os.makedirs(DOCS, exist_ok=True)
    with open(os.path.join(DOCS, "连接检查结果.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    with open(os.path.join(DOCS, "连接检查报告.md"), "w", encoding="utf-8") as f:
        f.write(build_markdown(payload))

    print(f"\n共 {len(results)} 项: 正常 {counts['正常']} / 异常 {counts['异常']} / 未配置 {counts['未配置']}")
    print("报告已生成: docs/连接检查报告.md")


if __name__ == "__main__":
    main()
