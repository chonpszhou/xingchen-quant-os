#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""星辰投研团 · 本地网页看板（零第三方依赖；标签页 + 双线净值图 + 操作台）"""

import argparse
import json
import subprocess
import sys
import threading
import time
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent

ACTIONS = {
    "数据更新(四市场)": ["datahub_cli.py", "update", "--markets", "A股", "港股", "美股", "虚拟货币"],
    "全链路(每日任务)": ["run_all.py", "all"],
    "双低监控+模拟盘": ["run_all.py", "cb"],
    "生成摘要": ["run_all.py", "digest"],
    "风控检查": ["run_all.py", "risk"],
    "一致性监控": ["run_all.py", "consistency"],
    "验收测试(10项)": ["run_all.py", "test"],
    "调仓预告": ["run_all.py", "preview"],
    "周报": ["run_all.py", "weekly"],
    "月报": ["run_all.py", "monthly"],
    "期权IV快照": ["run_all.py", "iv"],
    "期货更新": ["run_all.py", "futures"],
}

_lock = threading.Lock()
_running = {"task": None, "started": None, "log": []}


def run_task(name, args):
    cmd = [sys.executable, str(ROOT / "scripts" / args[0]), *args[1:]]
    _running.update({"task": name, "started": time.strftime("%H:%M:%S"), "log": []})
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, cwd=ROOT)
        for line in p.stdout:
            _running["log"].append(line.rstrip())
            if len(_running["log"]) > 400:
                _running["log"] = _running["log"][-400:]
        p.wait()
        _running["log"].append(f"[完成] 退出码 {p.returncode}")
    except Exception as e:  # noqa: BLE001
        _running["log"].append(f"[错误] {e}")
    finally:
        _running["task"] = None
        _running["started"] = None


def nav_data():
    out = {}
    for name, f in (("双低", "paper_cb"), ("双动量", "paper_mom"), ("风险平价", "paper_rp")):
        p = ROOT / "data" / f"{f}_nav.parquet"
        s = ROOT / "data" / f"{f}_state.json"
        if not p.exists():
            continue
        df = pd.read_parquet(p)
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date")
        st = json.loads(s.read_text(encoding="utf-8")) if s.exists() else {}
        last = df.iloc[-1]
        out[name] = {
            "nav": float(last["nav"]), "bench": float(last["bench_nav"]),
            "excess": float(last["nav"] - last["bench_nav"]),
            "days": len(df), "rebal": st.get("rebalance_count", 0),
            "date": str(last["date"].date()),
            "dates": [d.strftime("%m-%d") for d in df["date"].tail(60)],
            "navs": [round(float(v), 0) for v in df["nav"].tail(60)],
            "benchs": [round(float(v), 0) for v in df["bench_nav"].tail(60)],
        }
    return out


def metrics_of(navs):
    s = pd.Series(navs)
    daily = s.iloc[-1] / s.iloc[-2] - 1 if len(s) > 1 else 0.0
    cum = s.iloc[-1] / s.iloc[0] - 1 if len(s) else 0.0
    dd = float(((s - s.cummax()) / s.cummax()).min()) if len(s) > 1 else 0.0
    return daily, cum, dd


def svg_dual(dates, navs, benchs, w=560, h=150):
    if len(navs) < 2:
        return "<p class='muted'>数据积累中</p>"
    mn = min(min(navs), min(benchs))
    mx = max(max(navs), max(benchs))
    rng = (mx - mn) or 1
    pad_l, pad_r, pad_t, pad_b = 46, 10, 12, 22

    def X(i):
        return pad_l + i * (w - pad_l - pad_r) / (len(navs) - 1)

    def Y(v):
        return pad_t + (mx - v) * (h - pad_t - pad_b) / rng

    pts_n = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(navs))
    pts_b = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(benchs))
    area = (f"{X(0):.1f},{Y(navs[0]):.1f} " +
            " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(navs)) +
            f" {X(len(navs)-1):.1f},{h-pad_b:.1f} {X(0):.1f},{h-pad_b:.1f}")
    grid = ""
    for g in range(4):
        gy = pad_t + g * (h - pad_t - pad_b) / 3
        val = mx - g * rng / 3
        grid += (f'<line x1="{pad_l}" y1="{gy:.1f}" x2="{w-pad_r}" y2="{gy:.1f}" stroke="#1e293b"/>'
                 f'<text x="{pad_l-6}" y="{gy+3:.1f}" fill="#64748b" font-size="10" text-anchor="end">{val:,.0f}</text>')
    return (f'<svg viewBox="0 0 {w} {h}" style="width:100%;height:{h}px">'
            f'{grid}<polygon points="{area}" fill="rgba(59,130,246,0.12)"/>'
            f'<polyline fill="none" stroke="#3b82f6" stroke-width="2.2" points="{pts_n}"/>'
            f'<polyline fill="none" stroke="#f59e0b" stroke-width="1.6" stroke-dasharray="5,4" points="{pts_b}"/>'
            f'<text x="{pad_l}" y="{h-5}" fill="#64748b" font-size="10">{dates[0]}</text>'
            f'<text x="{w-pad_r}" y="{h-5}" fill="#64748b" font-size="10" text-anchor="end">{dates[-1]}</text>'
            f'<rect x="{w-150}" y="4" width="12" height="3" fill="#3b82f6"/>'
            f'<text x="{w-134}" y="8" fill="#94a3b8" font-size="10">净值</text>'
            f'<rect x="{w-92}" y="4" width="12" height="3" fill="#f59e0b"/>'
            f'<text x="{w-76}" y="8" fill="#94a3b8" font-size="10">基准</text></svg>')


def cb_top():
    p = ROOT / "data" / "cb_daily_snapshot.json"
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8")).get("rank", [])[:10]


def freshness():
    sys.path.insert(0, str(ROOT))
    from datahub.store import LocalStore
    st = LocalStore(str(ROOT / "data")).all_status()
    rows = []
    for m in ("A股", "港股", "美股", "虚拟货币", "期货"):
        g = st[st["market"] == m]
        if g.empty:
            rows.append((m, 0, "-"))
            continue
        last = g["last_date"].max()
        behind = (pd.Timestamp(date.today()) - pd.Timestamp(last)).days
        state = "✅" if behind <= 4 else ("⚠️" if behind <= 10 else "❌")
        rows.append((m, len(g), f"{state} {last}"))
    return rows


def read_md_table(path):
    p = ROOT / "docs" / path
    if not p.exists():
        return []
    return [l for l in p.read_text(encoding="utf-8").splitlines()
            if l.startswith("| ") and not l.startswith("|---")]


def engine_nav(strategy):
    """从引擎 SQLite 取回测净值（绩效体检数据源）"""
    try:
        from engine.database import Database
        df = Database(ROOT / "data" / "engine.sqlite").nav_series(strategy)
        if df.empty:
            return None
        return df.set_index("date")["nav"]
    except Exception:
        return None


def tear_sheet(strategy):
    """绩效体检（借鉴 jesse metrics / quantstats tear sheet）"""
    nav = engine_nav(strategy)
    if nav is None or len(nav) < 5:
        return "<p class='muted'>回测数据积累中（先跑 engine_cli 回测）</p>"
    s = nav
    r = s.pct_change().dropna()
    years = len(r) / 252
    ann = (s.iloc[-1] / s.iloc[0]) ** (1 / years) - 1 if years > 0 else 0
    vol = r.std() * 252 ** 0.5
    sharpe = (ann - 0.02) / vol if vol > 0 else 0
    dd = float(((s - s.cummax()) / s.cummax()).min())
    monthly = s.resample("ME").last().pct_change().dropna()
    wr = float((monthly > 0).mean())
    pf = float(monthly[monthly > 0].sum() / abs(monthly[monthly < 0].sum())) if (monthly < 0).any() else float("nan")
    # 回撤曲线
    dds = ((s - s.cummax()) / s.cummax()) * 100
    dd_pts = " ".join(f"{i/(len(dds)-1)*300:.1f},{50 - v*1.2:.1f}" for i, v in enumerate(dds.values))
    # 滚动夏普（60 日）
    rs = r.rolling(60).mean() / r.rolling(60).std() * 252 ** 0.5
    rs = rs.dropna()
    rs_pts = " ".join(f"{i/(len(rs)-1)*300:.1f},{40 - min(max(v,-2),2)*18:.1f}" for i, v in enumerate(rs.values)) if len(rs) > 1 else ""
    # 月度热力图
    cells = ""
    for year, grp in monthly.groupby(monthly.index.year):
        for m in range(1, 13):
            v = grp.get(grp.index.month == m)
            val = float(v.iloc[0]) if len(v) else None
            if val is None:
                cells += "<td style='background:#0f172a'></td>"
            else:
                tone = "rgba(34,197,94,%.2f)" % min(abs(val) / 0.12, 1) if val >= 0 else "rgba(239,68,68,%.2f)" % min(abs(val) / 0.12, 1)
                cells += f"<td style='background:{tone}'>{val:+.1%}</td>"
        cells += "</tr><tr>"
    return f"""
    <div class="stat">
      <div>年化<b>{ann:.2%}</b></div><div>夏普<b>{sharpe:.2f}</b></div>
      <div>最大回撤<b style="color:{'#f87171' if dd < -0.2 else '#e2e8f0'}">{dd:.1%}</b></div>
      <div>月度胜率<b>{wr:.0%}</b></div><div>盈亏比<b>{pf:.2f}</b></div>
    </div>
    <h3>回撤曲线</h3>
    <svg viewBox="0 0 300 50" style="width:100%;height:50px"><polyline fill="none" stroke="#f87171" stroke-width="1.5" points="{dd_pts}"/></svg>
    <h3>滚动夏普（60日）</h3>
    <svg viewBox="0 0 300 45" style="width:100%;height:45px"><polyline fill="none" stroke="#60a5fa" stroke-width="1.5" points="{rs_pts}"/></svg>
    <h3>月度收益热力图</h3>
    <table style="font-size:11px"><tr><th></th>{"".join(f"<th>{m}月</th>" for m in range(1,13))}</tr><tr>{cells}</table>
    """


def trades_view():
    """最近交易记录（借鉴 octobot/jesse 交易视图，数据源 engine.sqlite）"""
    try:
        from engine.database import Database
        t = Database(ROOT / "data" / "engine.sqlite").trades()
        if t.empty:
            return "<p class='muted'>暂无交易流水（先跑 engine_cli 回测或纸面）</p>"
        t = t.tail(50).iloc[::-1]
        rows = "".join(
            f"<tr><td>{r['strategy']}</td><td>{str(r['date'])[:10]}</td><td>{r['symbol']}</td>"
            f"<td><span class=\"{'up' if r['direction']=='buy' else 'down'}\">{r['direction']}</span></td>"
            f"<td>{r['price']:.2f}</td><td>{r['value']:,.0f}</td><td>{r['cost']:.0f}</td></tr>"
            for _, r in t.iterrows())
        return (f"<div class='stat'><div>交易笔数<b>{len(t)}（近50）</b></div></div>"
                f"<table><tr><th>策略</th><th>日期</th><th>标的</th><th>方向</th><th>价格</th><th>金额</th><th>成本</th></tr>{rows}</table>")
    except Exception:
        return "<p class='muted'>交易库不可用</p>"


def paper_positions_view():
    """纸面持仓视图（含止盈止损状态提示）"""
    rows = []
    for name, f in (("双低", "paper_cb"), ("双动量", "paper_mom"), ("风险平价", "paper_rp")):
        p = ROOT / "data" / f"{f}_state.json"
        if not p.exists():
            continue
        st = json.loads(p.read_text(encoding="utf-8"))
        for sym, h in st.get("holdings", {}).items():
            rows.append((name, sym, h.get("shares", 0), h.get("last_price", 0), h.get("value", 0)))
    if not rows:
        return "<p class='muted'>暂无纸面持仓</p>"
    body = "".join(
        f"<tr><td>{n}</td><td>{s}</td><td>{sh:,.0f}</td><td>{px:,.2f}</td><td>{val:,.0f}</td></tr>"
        for n, s, sh, px, val in rows[:30])
    return (f"<div class='stat'><div>持仓<b>{len(rows)}</b></div></div>"
            f"<table><tr><th>策略</th><th>标的</th><th>数量</th><th>最新价</th><th>市值</th></tr>{body}</table>")


def market_view():
    """自选行情（本地库最后两日涨跌，借鉴 OpenBB/OctoBot 行情视图）"""
    sys.path.insert(0, str(ROOT))
    from datahub.store import LocalStore
    store = LocalStore(str(ROOT / "data"))
    rows = []
    for market, sym in (("A股", "600519"), ("A股", "300750"), ("A股", "000001"),
                        ("美股", "SPY"), ("美股", "NVDA"), ("美股", "AAPL"),
                        ("虚拟货币", "BTC/USDT"), ("虚拟货币", "ETH/USDT"), ("虚拟货币", "SOL/USDT"),
                        ("港股", "00700"), ("港股", "09988"), ("期货", "AU0")):
        df = store.load_bars(market, sym)
        if df is None or len(df) < 2:
            continue
        px = float(df["close"].iloc[-1])
        chg = px / float(df["close"].iloc[-2]) - 1
        rows.append((f"{market} {sym}", px, chg))
    rows.sort(key=lambda x: -abs(x[2]))
    body = "".join(
        f"<tr><td>{n}</td><td>{p:,.2f}</td><td><b class=\"{'up' if c>=0 else 'down'}\">{c:+.2%}</b></td></tr>"
        for n, p, c in rows)
    return f"<table><tr><th>标的</th><th>最新价</th><th>日涨跌</th></tr>{body}</table>"


def learning_view():
    """每日量化学习：最新笔记 + 最近条目"""
    notes = sorted((ROOT / "docs").glob("学习笔记_*.md"), reverse=True)
    items_html = ""
    log = ROOT / "data" / "learning_log.parquet"
    if log.exists():
        df = pd.read_parquet(log)
        if not df.empty:
            df = df.drop_duplicates("link").tail(8).iloc[::-1]
            items_html = "".join(
                f"<tr><td>{r['source']}</td><td><a href='{r['link']}' target='_blank' style='color:#60a5fa'>{r['title'][:60]}</a></td>"
                f"<td>{r['date']}</td></tr>" for _, r in df.iterrows())
    note_link = f"<a class='rep' href='/file/{notes[0].name}'>最新学习笔记（{notes[0].stem.replace('学习笔记_','')}）</a>" if notes else ""
    return (f"<div>{note_link}</div>"
            f"<h2>最近条目（累计 {len(df) if log.exists() else 0}）</h2>"
            f"<table><tr><th>来源</th><th>标题</th><th>日期</th></tr>{items_html or '<tr><td class=\"muted\">暂无</td></tr>'}</table>")


def render():
    accounts = nav_data()
    cards = ""
    port_navs = []
    port_dates = []
    if accounts:
        port_dates = next(iter(accounts.values()))["dates"]
        base = [a["navs"][0] or 1 for a in accounts.values()]
        port_navs = [sum(v / b for v, b in zip(n, base)) / len(base)
                     for n in zip(*[a["navs"] for a in accounts.values()])]
    for name, a in accounts.items():
        daily, cum, dd = metrics_of(a["navs"])
        cards += f"""
        <div class="card">
          <div class="card-head"><h3>{name}</h3><span class="badge">{a['days']}天 · 调仓{a['rebal']}</span></div>
          <div class="big">{a['nav']:,.0f}</div>
          <div class="chips">
            <span class="chip {'up' if daily>=0 else 'down'}">日 {daily:+.2%}</span>
            <span class="chip">累计 {cum:+.2%}</span>
            <span class="chip {'ok' if dd>=-0.20 else 'warn'}">回撤 {dd:.1%}</span>
          </div>
          <div class="sub">基准 {a['bench']:,.0f} · 超额 <b class="{'up' if a['excess']>=0 else 'down'}">{a['excess']:+,.0f}</b></div>
          <div class="curve">{svg_dual(a['dates'], a['navs'], a['benchs'], w=340, h=110)}</div>
        </div>"""
    hero = svg_dual(port_dates, port_navs, port_navs, w=760, h=170) if accounts else "<p class='muted'>数据积累中</p>"
    top = "".join(
        f"<tr><td>{r['name']}</td><td>{r['price']:.1f}</td><td>{r['premium']:.1f}%</td>"
        f"<td>{r['score']:.1f}</td><td><span class='rate'>{r.get('rating','-')}</span></td></tr>"
        for r in cb_top())
    fresh = "".join(f"<tr><td>{m}</td><td>{n}</td><td>{s}</td></tr>" for m, n, s in freshness())
    risk = "".join(f"<tr>{''.join(f'<td>{c}</td>' for c in l.split('|')[1:-1])}</tr>"
                   for l in read_md_table("风控状态.md"))
    btns = "".join(f'<button class="btn" data-key="{i}" onclick="runTask({i})">{name}</button>'
                   for i, name in enumerate(ACTIONS))
    reports = "".join(
        f'<a class="rep" href="/file/{p.name}">{p.stem}</a>'
        for p in sorted((ROOT / "docs").glob("*.md"), key=lambda x: -x.stat().st_mtime)[:12])
    iv_line = ""
    iv = ROOT / "docs" / "期权IV监控快照.md"
    if iv.exists():
        for l in iv.read_text(encoding="utf-8").splitlines():
            if l.startswith("| VIX"):
                c = [x.strip() for x in l.split("|")[1:-1]]
                iv_line = f"VIX {c[2]}（2年分位 {c[3]}）"
                break
    trade_txt = "—"
    try:
        from engine.database import Database
        trade_txt = f"{len(Database(ROOT / 'data' / 'engine.sqlite').trades())} 笔"
    except Exception:
        pass
    tear_tabs = ""
    tear_panels = ""
    for st in ("dual_momentum", "risk_parity", "cb_double_low"):
        tear_tabs += f"<button class='tab t2 active' onclick=\"document.querySelectorAll('.tp').forEach(x=>x.classList.remove('active'));document.getElementById('tp-{st}').classList.add('active');this.parentNode.querySelectorAll('.t2').forEach(x=>x.classList.remove('active'));this.classList.add('active')\">{st}</button>"
        tear_panels += f"<div id='tp-{st}' class='tp active'>{tear_sheet(st)}</div>"
    return f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>星辰投研团 · 量化操作系统</title>
<style>
body{{font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;background:#0b1120;color:#e2e8f0;margin:0}}
.top{{background:linear-gradient(135deg,#0f172a,#1e293b);border-bottom:1px solid #1e293b;padding:14px 24px;display:flex;align-items:center;gap:14px;position:sticky;top:0;z-index:10}}
.top h1{{font-size:18px;margin:0;flex:1}}
.pill{{font-size:12px;padding:4px 10px;border-radius:20px;background:#0e2a1d;color:#4ade80;border:1px solid #14532d}}
.pill.warn{{background:#3b2314;color:#fbbf24;border-color:#78350f}}
.tabs{{display:flex;gap:4px;padding:10px 24px;border-bottom:1px solid #1e293b;background:#0f172a;overflow-x:auto}}
.tab{{background:none;border:0;color:#94a3b8;font-size:14px;padding:8px 16px;border-radius:8px;cursor:pointer;white-space:nowrap}}
.tab.active{{background:#1e293b;color:#60a5fa;font-weight:600}}
section{{display:none;padding:20px 24px;max-width:1200px;margin:auto}}
section.active{{display:block}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px}}
.card{{background:#0f172a;border:1px solid #1e293b;border-radius:14px;padding:18px}}
.hero{{background:linear-gradient(135deg,#172554,#1e293b);border:1px solid #1e3a8a;border-radius:14px;padding:20px;margin-bottom:16px}}
.card-head{{display:flex;justify-content:space-between;align-items:center}}
.card-head h3{{margin:0;font-size:15px}}
.badge{{font-size:11px;color:#94a3b8;background:#1e293b;padding:3px 8px;border-radius:10px}}
.big{{font-size:30px;font-weight:800;margin:8px 0 6px;font-variant-numeric:tabular-nums}}
.chips{{display:flex;gap:8px;margin-bottom:6px;flex-wrap:wrap}}
.chip{{font-size:12px;padding:3px 9px;border-radius:8px;background:#1e293b;color:#cbd5e1}}
.chip.up{{color:#4ade80;background:#0e2a1d}}
.chip.down{{color:#f87171;background:#2a0e0e}}
.chip.ok{{color:#4ade80}}.chip.warn{{color:#fbbf24}}
.sub{{font-size:13px;color:#94a3b8}}
.up{{color:#4ade80}}.down{{color:#f87171}}
.curve{{margin-top:10px}}
table{{border-collapse:collapse;width:100%;font-size:13px;background:#0f172a;border-radius:10px;overflow:hidden}}
td,th{{padding:8px 12px;border-bottom:1px solid #1e293b;text-align:left}}
th{{color:#93c5fd;font-weight:600;background:#111c2e}}
tr:hover td{{background:#16233a}}
.rate{{font-weight:600;color:#c4b5fd}}
h2{{font-size:16px;margin:22px 0 10px;color:#93c5fd}}
.btn{{background:#2563eb;color:#fff;border:0;border-radius:8px;padding:8px 14px;margin:4px;cursor:pointer;font-size:13px}}
.btn:hover{{background:#3b82f6}}
.btn:disabled{{background:#334155;cursor:not-allowed}}
#output{{background:#0b1220;border:1px solid #1e293b;border-radius:10px;padding:12px;font-size:12px;white-space:pre-wrap;height:240px;overflow:auto;font-family:ui-monospace,monospace}}
.rep{{display:inline-block;color:#60a5fa;background:#111c2e;border:1px solid #1e3a8a;padding:6px 12px;border-radius:8px;margin:4px;text-decoration:none;font-size:13px}}
.rep:hover{{background:#172554}}
.updated{{color:#475569;font-size:12px;margin:24px 0}}
.muted{{color:#64748b}}
.stat{{display:flex;gap:24px;flex-wrap:wrap;margin:8px 0}}
.stat div{{font-size:13px;color:#94a3b8}}
.stat b{{color:#e2e8f0;font-size:16px;display:block}}
.refresh{{font-size:12px;color:#64748b;cursor:pointer;background:none;border:1px solid #334155;border-radius:8px;padding:4px 10px}}
.tp{{display:none}}.tp.active{{display:block}}
.t2{{font-size:12px;padding:5px 12px;margin-right:6px;border:0;border-radius:6px;background:#111c2e;color:#94a3b8;cursor:pointer}}
.t2.active{{background:#1e3a8a;color:#93c5fd}}
</style></head><body>
<div class="top"><h1>📊 星辰投研团 · 量化操作系统</h1>
<span id="pill" class="pill">自运转</span><button class="refresh" onclick="toggleRefresh()">自动刷新</button></div>
<div class="tabs" id="tabs">
<button class="tab active" data-t="overview">概览</button>
<button class="tab" data-t="strategies">策略</button>
<button class="tab" data-t="risk">风控</button>
<button class="tab" data-t="health">体检</button>
<button class="tab" data-t="trades">交易</button>
<button class="tab" data-t="ops">操作台</button>
<button class="tab" data-t="data">行情/数据</button>
<button class="tab" data-t="learn">学习</button>
<button class="tab" data-t="reports">报告</button></div>
<section id="overview" class="active">
<div class="hero"><h2 style="margin-top:0">组合净值（三策略等权）</h2>{hero}</div>
<div class="grid">{cards}</div></section>
<section id="strategies"><h2>策略详情</h2><div class="grid">{cards}</div>
<div class="stat"><div>交易流水<b>{trade_txt}</b></div><div>净值天数<b>{len(port_navs)}</b></div></div>
<h2>可转债双低 TOP10</h2>
<table><tr><th>名称</th><th>价格</th><th>溢价</th><th>双低值</th><th>评级</th></tr>{top}</table></section>
<section id="risk"><h2>风控状态</h2><table>{risk or '<tr><td class="muted">数据积累中</td></tr>'}</table>
<h2>相关监控</h2>
<a class="rep" href="/file/一致性监控.md">回测-模拟一致性</a>
<a class="rep" href="/file/模拟盘预期区间.md">预期区间</a>
<a class="rep" href="/file/下次调仓预告.md">调仓预告</a></section>
<section id="health"><h2>策略体检（引擎回测绩效，借鉴 jesse/quantstats）</h2>
<div>{tear_tabs}</div><div style="margin-top:12px">{tear_panels}</div></section>
<section id="trades"><h2>纸面持仓</h2>{paper_positions_view()}
<h2>交易记录（引擎 SQLite，含止盈止损自动退出）</h2>{trades_view()}</section>
<section id="ops"><h2>操作台</h2><div>{btns}</div>
<p id="runstate" class="muted"></p><pre id="output">就绪。点击按钮触发任务，输出实时显示。</pre></section>
<section id="data"><h2>自选行情（本地两日涨跌）</h2>{market_view()}
<h2>数据新鲜度</h2>
<table><tr><th>市场</th><th>标的数</th><th>状态</th></tr>{fresh}</table>
<h2>市场摘要</h2><div class="stat"><div>期权 IV<b>{iv_line or '—'}</b></div></div></section>
<section id="reports"><h2>报告（最近 12 份）</h2><div>{reports or '<span class="muted">暂无</span>'}</div></section>
<section id="learn"><h2>每日量化学习（GitHub + 精选博客）</h2>{learning_view()}</section>
<div style="padding:0 24px"><div class="updated">自动生成 · 仅供学习研究参考，不构成投资建议 · 操作台仅限本机访问 · {pd.Timestamp.now():%H:%M:%S}</div></div>
<script>
const keys = {json.dumps(list(ACTIONS), ensure_ascii=False)};
let poll=null, timer=null, autoRefresh=false;
document.getElementById('tabs').addEventListener('click',e=>{{const t=e.target.dataset.t;if(!t)return;
document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('active',x===e.target));
document.querySelectorAll('section').forEach(s=>s.classList.toggle('active',s.id===t));}});
function toggleRefresh(){{autoRefresh=!autoRefresh;
if(autoRefresh){{timer=setInterval(()=>{{fetch('/api/log').then(r=>r.json()).then(j=>{{if(!j.running)location.reload();}});}},60000);
document.querySelector('.refresh').textContent='自动刷新开';}}
else{{clearInterval(timer);document.querySelector('.refresh').textContent='自动刷新';}}}}
function runTask(i){{document.querySelectorAll('.btn').forEach(b=>b.disabled=true);
fetch('/api/run?key='+i).then(r=>r.json()).then(j=>{{
document.getElementById('runstate').textContent='正在运行: '+keys[j.key]+'（'+j.started+'）';
document.getElementById('pill').textContent='运行中';document.getElementById('pill').className='pill warn';
poll=setInterval(pollLog,1500);}});}}
function pollLog(){{fetch('/api/log').then(r=>r.json()).then(j=>{{
const o=document.getElementById('output');o.textContent=j.log.join('\\n')||'（无输出）';o.scrollTop=o.scrollHeight;
if(!j.running){{clearInterval(poll);document.getElementById('runstate').textContent='完成：'+j.task;
document.getElementById('pill').textContent='自运转';document.getElementById('pill').className='pill';
document.querySelectorAll('.btn').forEach(b=>b.disabled=false);}}}});}}
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/run"):
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            key = int(q.get("key", ["0"])[0])
            name = list(ACTIONS)[key]
            if not _lock.acquire(blocking=False):
                self._json({"error": "已有任务在运行"}, 409)
                return
            threading.Thread(target=lambda: (run_task(name, ACTIONS[name]), _lock.release()),
                             daemon=True).start()
            self._json({"started": True, "key": key, "task": name, "started": _running["started"]})
            return
        if self.path.startswith("/api/log"):
            self._json({"running": _running["task"] is not None,
                        "task": _running["task"], "log": _running["log"]})
            return
        if self.path.startswith("/file/"):
            name = self.path.split("/file/", 1)[1]
            p = ROOT / "docs" / name
            if p.exists() and p.is_file():
                body = p.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/markdown; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"not found")
            return
        body = render().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8080)
    args = p.parse_args()
    print(f"看板已启动：http://{args.host}:{args.port}")
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
