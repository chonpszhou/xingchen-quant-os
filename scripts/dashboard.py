#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""星辰投研团 · 本地网页看板（零 JS：CSS 标签 + 表单任务 + meta-refresh 任务页）"""

import argparse
import collections
import json
import subprocess
import sys
import threading
import time
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent

VERSION = "0.4.0"
START_TS = time.time()

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
TAB_IDS = ["overview", "strategies", "risk", "health", "trades", "ops", "data", "scan", "accounts", "learn", "reports"]

# 模拟盘账户定义（显示名, state/nav 文件前缀）——覆盖全部 5 个账户
ACCOUNT_DEFS = [
    ("双低·可转债", "paper_cb"),
    ("双动量·ETF", "paper_mom"),
    ("风险平价", "paper_rp"),
    ("加密·等权", "paper_crypto"),
    ("港股", "paper_hk"),
    ("AAPL·灰度", "paper_aapl"),
]

_queue = collections.deque()
_current = {"name": None, "proc": None}
_running = {"task": None, "started": None, "log": []}


# ---------- 结构化 JSON 日志（进容器 json-file 日志 + 落本地文件）----------
_ACCESS_LOG = ROOT / "data" / "dashboard_access.log"


def log_event(event, **fields):
    """输出一行结构化 JSON 日志：stdout/stderr 由容器 json-file 驱动采集；
    同时追加到 data/dashboard_access.log 供宿主机直接查阅。"""
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "event": event, **fields}
    line = json.dumps(rec, ensure_ascii=False)
    try:
        print(line, flush=True)
    except Exception:
        pass
    try:
        with open(_ACCESS_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _run(name, args):
    cmd = [sys.executable, str(ROOT / "scripts" / args[0]), *args[1:]]
    _running.update({"task": name, "started": time.strftime("%H:%M:%S"), "log": []})
    _current["name"] = name
    try:
        _current["proc"] = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                            text=True, cwd=ROOT)
        for line in _current["proc"].stdout:
            _running["log"].append(line.rstrip())
            if len(_running["log"]) > 400:
                _running["log"] = _running["log"][-400:]
        _current["proc"].wait()
        _running["log"].append(f"[完成] 退出码 {_current['proc'].returncode}")
    except Exception as e:  # noqa: BLE001
        _running["log"].append(f"[错误/已取消] {e}")
    finally:
        _current["proc"] = None
        _running["task"] = None
        _running["started"] = None


def _worker():
    while True:
        if not _queue:
            _current["name"] = None
            return
        name, args = _queue.popleft()
        _run(name, args)


def enqueue(name, args):
    if len(_queue) >= 3 and _current["name"]:
        return "队列已满（最多 3 个排队）"
    started_now = _current["name"] is None and not _queue
    _queue.append((name, args))
    if started_now:
        threading.Thread(target=_worker, daemon=True).start()
    return None if started_now else name


def cancel():
    if _current["proc"]:
        try:
            _current["proc"].terminate()
        except Exception:
            pass
    _queue.clear()


def nav_data():
    out = {}
    for name, f in ACCOUNT_DEFS:
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
        grid += (f'<line x1="{pad_l}" y1="{gy:.1f}" x2="{w-pad_r}" y2="{gy:.1f}" stroke="#1e2a44"/>'
                 f'<text x="{pad_l-6}" y="{gy+3:.1f}" fill="#5b6b85" font-size="10" text-anchor="end">{val:,.0f}</text>')
    return (f'<svg viewBox="0 0 {w} {h}" style="width:100%;height:{h}px">'
            f'{grid}<polygon points="{area}" fill="rgba(91,141,239,0.10)"/>'
            f'<polyline fill="none" stroke="#5b8def" stroke-width="2.2" points="{pts_n}"/>'
            f'<polyline fill="none" stroke="#fbbf24" stroke-width="1.6" stroke-dasharray="5,4" points="{pts_b}"/>'
            f'<text x="{pad_l}" y="{h-5}" fill="#5b6b85" font-size="10">{dates[0]}</text>'
            f'<text x="{w-pad_r}" y="{h-5}" fill="#5b6b85" font-size="10" text-anchor="end">{dates[-1]}</text>'
            f'<rect x="{w-150}" y="4" width="12" height="3" fill="#5b8def"/>'
            f'<text x="{w-134}" y="8" fill="#8b9bb4" font-size="10">净值</text>'
            f'<rect x="{w-92}" y="4" width="12" height="3" fill="#fbbf24"/>'
            f'<text x="{w-76}" y="8" fill="#8b9bb4" font-size="10">基准</text></svg>')


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
    try:
        from engine.database import Database
        df = Database(ROOT / "data" / "engine.sqlite").nav_series(strategy)
        if df.empty:
            return None
        return df.set_index("date")["nav"]
    except Exception:
        return None


def tear_sheet(strategy):
    nav = engine_nav(strategy)
    if nav is None or len(nav) < 5:
        return "<p class='muted'>回测数据积累中</p>"
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
    dds = ((s - s.cummax()) / s.cummax()) * 100
    dd_pts = " ".join(f"{i/(len(dds)-1)*300:.1f},{50 - v*1.2:.1f}" for i, v in enumerate(dds.values))
    rs = r.rolling(60).mean() / r.rolling(60).std() * 252 ** 0.5
    rs = rs.dropna()
    rs_pts = " ".join(f"{i/(len(rs)-1)*300:.1f},{40 - min(max(v,-2),2)*18:.1f}" for i, v in enumerate(rs.values)) if len(rs) > 1 else ""
    cells = ""
    for year, grp in monthly.groupby(monthly.index.year):
        for m in range(1, 13):
            v = grp.get(grp.index.month == m)
            val = float(v.iloc[0]) if len(v) else None
            if val is None:
                cells += "<td style='background:#0f172a'></td>"
            else:
                tone = ("rgba(34,197,94,%.2f)" % min(abs(val) / 0.12, 1)) if val >= 0 else ("rgba(239,68,68,%.2f)" % min(abs(val) / 0.12, 1))
                cells += f"<td style='background:{tone}'>{val:+.1%}</td>"
        cells += "</tr><tr>"
    return f"""
    <div class="stat">
      <div>年化<b>{ann:.2%}</b></div><div>夏普<b>{sharpe:.2f}</b></div>
      <div>最大回撤<b style="color:{'#f87171' if dd < -0.2 else '#e2e8f0'}">{dd:.1%}</b></div>
      <div>月度胜率<b>{wr:.0%}</b></div><div>盈亏比<b>{pf:.2f}</b></div>
    </div>
    <h3>回撤曲线</h3><svg viewBox="0 0 300 50" style="width:100%;height:50px"><polyline fill="none" stroke="#f87171" stroke-width="1.5" points="{dd_pts}"/></svg>
    <h3>滚动夏普（60日）</h3><svg viewBox="0 0 300 45" style="width:100%;height:45px"><polyline fill="none" stroke="#60a5fa" stroke-width="1.5" points="{rs_pts}"/></svg>
    <h3>月度收益热力图</h3>
    <table style="font-size:11px"><tr><th></th>{"".join(f"<th>{m}月</th>" for m in range(1,13))}</tr><tr>{cells}</table>
    """


def trades_view():
    try:
        from engine.database import Database
        t = Database(ROOT / "data" / "engine.sqlite").trades()
        if t.empty:
            return "<p class='muted'>暂无交易流水</p>"
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
    rows = []
    for name, f in ACCOUNT_DEFS:
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


def _fmt_scan_num(col, v):
    """扫描表数值列格式化 + 红绿配色（涨绿跌红，按 A股习惯）"""
    s = str(v)
    if s in ("", "nan", "None", "NaN"):
        return "<td>—</td>"
    pct_cols = {"total_return", "max_dd", "wf_dd", "excess"}
    flt_cols = {"sharpe", "dsr", "consensus", "wf_oos_sharpe", "pl_ratio",
                "score", "wf_sharpe", "win_rate"}
    try:
        f = float(v)
    except (TypeError, ValueError):
        return f"<td>{s}</td>"
    if col in pct_cols:
        cls = "up" if f >= 0 else "down"
        return f"<td class='{cls}'>{f:+.2%}</td>"
    if col in flt_cols:
        cls = "up" if f >= 0 else "down"
        return f"<td class='{cls}'>{f:+.2f}</td>"
    return f"<td>{f:,.2f}</td>"


def scan_view():
    """只读研究扫描面板：读取最新 data/experiments/sweep_YYYYMMDD.csv"""
    import re
    pat = re.compile(r"sweep_(\d{8})\.csv$")
    best = None
    d = ROOT / "data" / "experiments"
    if d.exists():
        for f in d.glob("sweep_*.csv"):
            if pat.search(f.name) and (best is None or f.name > best.name):
                best = f
    if best is None:
        return "<p class='muted'>暂无扫描结果（运行 scripts/research_sweep.py 或每周日自动化后生成）</p>"
    try:
        df = pd.read_csv(best, encoding="utf-8-sig")
    except Exception as e:  # noqa: BLE001
        return f"<p class='muted'>读取扫描失败：{e}</p>"
    if df.empty:
        return "<p class='muted'>扫描结果为空</p>"
    cols = list(df.columns)
    n_total = len(df)
    verdict_col = "verdict" if "verdict" in cols else None
    pass_col = "PASS" if "PASS" in cols else None
    n_ok = int(df[verdict_col].astype(str).str.contains("✅").sum()) if verdict_col else 0
    n_no = int(df[verdict_col].astype(str).str.contains("❌").sum()) if verdict_col else 0
    n_pass = int(df[pass_col].astype(str).str.contains("True").sum()) if pass_col else n_ok

    def cell(col, v):
        s = str(v)
        if col == "verdict":
            # 状态色（通过=绿/未过=红），与价格涨跌语义分离，避免和红涨绿跌混淆
            cls = "pass" if "✅" in s else ("fail" if "❌" in s else "")
            return f"<td><b class='{cls}'>{s}</b></td>"
        if col == "PASS":
            cls = "pass" if s.strip().lower() == "true" else "fail"
            return f"<td class='{cls}'>{s}</td>"
        if col in ("direction", "market", "preset", "strategy", "symbol"):
            return f"<td>{s}</td>"
        return _fmt_scan_num(col, v)

    head = "".join(f"<th>{c}</th>" for c in cols)
    body_rows = "".join("<tr>" + "".join(cell(c, r[c]) for c in cols) + "</tr>"
                        for _, r in df.iterrows())
    summary = (f"<div class='stat'><div>入扫标的<b>{n_total}</b></div>"
               f"<div>通过(✅)<b class='up'>{n_ok or n_pass}</b></div>"
               f"<div>未过(❌)<b class='down'>{n_no}</b></div>"
               f"<div>文件<b>{best.name}</b></div></div>")
    note = ("<p class='muted'>数据源：星辰原生五道闸验证（WF+holdout 双闸门 → 质量否决 → DSR≥0.95 → 自审）。"
            "每周日全自动刷新；权威交付以 paddy 引擎为准，结论一致（当前无实盘候选）。</p>")
    return summary + f"<table><tr>{head}</tr>{body_rows}</table>" + note


def accounts_view():
    """只读模拟盘面板：全部 5 个账户的净值卡片 + 汇总表 + 持仓"""
    accounts = nav_data()
    if not accounts:
        return "<p class='muted'>暂无模拟盘账户数据</p>"
    cards = ""
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
        </div>"""
    agg_rows = ""
    for name, a in accounts.items():
        daily, cum, dd = metrics_of(a["navs"])
        agg_rows += (f"<tr><td>{name}</td><td>{a['nav']:,.0f}</td>"
                     f"<td class=\"{'up' if cum>=0 else 'down'}\">{cum:+.2%}</td>"
                     f"<td class=\"{'up' if a['excess']>=0 else 'down'}\">{a['excess']:+,.0f}</td>"
                     f"<td class=\"{'ok' if dd>=-0.20 else 'warn'}\">{dd:.1%}</td>"
                     f"<td>{a['rebal']}</td><td>{a['date']}</td></tr>")
    agg = (f"<h2>账户汇总</h2><table><tr><th>账户</th><th>最新净值</th><th>累计</th>"
           f"<th>超额基准</th><th>最大回撤</th><th>调仓</th><th>日期</th></tr>{agg_rows}</table>")
    return f"<div class='grid'>{cards}</div>{agg}<h2>持仓明细</h2>{paper_positions_view()}"


def market_view():
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
    notes = sorted((ROOT / "docs").glob("学习笔记_*.md"), reverse=True)
    hourly = ROOT / "docs" / f"学习日志_{date.today():%Y-%m-%d}.md"
    hourly_html = ""
    if hourly.exists():
        lines = hourly.read_text(encoding="utf-8").splitlines()
        entries, cur = [], []
        for l in lines:
            if l.startswith("### "):
                if cur:
                    entries.append(cur)
                cur = [l]
            elif cur:
                cur.append(l)
        if cur:
            entries.append(cur)
        for e in entries[-8:][::-1]:
            title = next((x for x in e if x.startswith("- 标题：")), "")
            core = next((x for x in e if x.startswith("- 核心观点")), "")
            hypo = next((x for x in e if x.startswith("- 可测假设")), "")
            hourly_html += (f"<div class='card' style='margin-bottom:10px'><b>{e[0][4:]}</b><br>"
                            f"<span style='font-size:13px;color:#cbd5e1'>{title[5:][:60]}<br>"
                            f"{core[6:][:90]}<br><span style='color:#60a5fa'>{hypo[6:][:90]}</span></span></div>")
    items_html = ""
    log = ROOT / "data" / "learning_log.parquet"
    n = 0
    if log.exists():
        df = pd.read_parquet(log)
        n = len(df.drop_duplicates("link"))
        if not df.empty:
            df = df.drop_duplicates("link").tail(8).iloc[::-1]
            items_html = "".join(
                f"<tr><td>{r['source']}</td><td><a href='{r['link']}' style='color:#60a5fa'>{r['title'][:60]}</a></td>"
                f"<td>{r['date']}</td></tr>" for _, r in df.iterrows())
    note_link = f"<a class='rep' href='/file/{notes[0].name}'>最新学习笔记（{notes[0].stem.replace('学习笔记_','')}）</a>" if notes else ""
    return (f"<div>{note_link}</div>"
            f"<h2>每小时学习成果（今天）</h2>{hourly_html or '<p class=\"muted\">暂无每小时记录</p>'}"
            f"<h2>最近条目（累计 {n}）</h2>"
            f"<table><tr><th>来源</th><th>标题</th><th>日期</th></tr>{items_html or '<tr><td class=\"muted\">暂无</td></tr>'}</table>")


def task_page(msg=""):
    """零 JS 任务页：meta-refresh 自动刷新显示日志与队列"""
    running = _running["task"]
    queue = [n for n, _ in _queue]
    state = f"运行中：{running}" if running else ("空闲" if not queue else "当前空闲，队列待执行")
    meta = '<meta http-equiv="refresh" content="3">' if (running or queue) else ""
    log = "".join(f"{l}<br>" for l in _running["log"][-80:]) or "（暂无输出）"
    body = f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">{meta}
<title>星辰投研团 · 任务</title><style>
body{{font-family:-apple-system,'PingFang SC',system-ui,sans-serif;background:#0a0e1a;color:#e6edf6;padding:24px;max-width:900px;margin:auto;line-height:1.5}}
pre{{background:#0b1220;border:1px solid #1e2a44;border-radius:12px;padding:14px;font-size:12px;white-space:pre-wrap;font-family:ui-monospace,monospace;color:#cbd5e1}}
.btn{{background:#3b82f6;color:#fff;border:0;border-radius:10px;padding:9px 15px;margin:4px;cursor:pointer;font-size:13px;text-decoration:none;display:inline-block;transition:filter .16s ease}}
.btn:hover{{filter:brightness(1.1)}}
.btn:focus-visible{{outline:2px solid #5b8def;outline-offset:2px}}
.btn.red{{background:#dc2626}}
@media (prefers-reduced-motion:reduce){{*{{transition:none!important}}}}
</style></head><body>
<h2>任务状态：{state}</h2>
<p>队列：{("、".join(queue) if queue else "无")}</p>
<a class="btn" href="/">← 返回看板</a>
<form action="/api/cancel" method="GET" style="display:inline"><button class="btn red" type="submit">取消当前任务</button></form>
{('<p class="muted">页面每 3 秒自动刷新（无需操作）</p>' if (running or queue) else "")}
<h3>输出</h3><pre>{log}</pre>
</body></html>"""
    return body


def render():
    accounts = nav_data()
    cards, port_navs, port_dates = "", [], []
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
    forms = "".join(
        f'<form action="/api/run" method="GET" style="display:inline">'
        f'<input type="hidden" name="key" value="{i}"><button class="btn" type="submit">{name}</button></form>'
        for i, name in enumerate(ACTIONS))
    reports = "".join(
        f'<a class="rep" href="/file/{p.name}">{p.stem}</a>'
        for p in sorted((ROOT / "docs").glob("*.md"), key=lambda x: -x.stat().st_mtime)[:12])
    tear = "".join(f"<h3>{st}</h3>{tear_sheet(st)}" for st in ("dual_momentum", "risk_parity", "cb_double_low"))
    iv_line = ""
    iv = ROOT / "docs" / "期权IV监控快照.md"
    if iv.exists():
        for l in iv.read_text(encoding="utf-8").splitlines():
            if l.startswith("| VIX"):
                c = [x.strip() for x in l.split("|")[1:-1]]
                iv_line = f"VIX {c[2]}（2年分位 {c[3]}）"
                break
    gex_line = ""
    gex = ROOT / "docs" / "期权GEX快照.md"
    if gex.exists():
        for l in gex.read_text(encoding="utf-8").splitlines():
            if l.startswith("| SPY") or l.startswith("| QQQ"):
                c = [x.strip() for x in l.split("|")[1:-1]]
                gex_line += f" | {c[0]} ZG={c[2]} CW={c[3]}"
    trade_txt = "—"
    try:
        from engine.database import Database
        trade_txt = f"{len(Database(ROOT / 'data' / 'engine.sqlite').trades())} 笔"
    except Exception:
        pass
    radios = "".join(
        f'<input type="radio" name="tab" id="t-{tid}" class="tabin" {"checked" if tid=="overview" else ""}>'
        for tid in TAB_IDS)
    labels = "".join(
        f'<label for="t-{tid}" class="tab">{ {"overview":"概览","strategies":"策略","risk":"风控","health":"体检","trades":"交易","ops":"操作台","data":"行情/数据","scan":"研究扫描","accounts":"模拟盘","learn":"学习","reports":"报告"}[tid] }</label>'
        for tid in TAB_IDS)
    pill = "运行中" if _running["task"] else "自运转"
    return f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="60">
<title>星辰投研团 · 量化操作系统</title>
<style>
:root{{
  --bg:#0a0e1a; --surface:#0f1629; --surface-2:#131c30; --border:#1e2a44; --border-soft:#16203a;
  --text:#e6edf6; --muted:#8b9bb4; --faint:#5b6b85;
  --primary:#5b8def; --primary-strong:#3b82f6;
  --up:#f87171; --up-bg:#2a1414;          /* 涨=红（A股习惯） */
  --down:#4ade80; --down-bg:#0e2a1d;      /* 跌=绿 */
  --pass:#4ade80; --fail:#f87171;          /* 状态色：通过=绿 / 未过=红 */
  --warn:#fbbf24; --info:#60a5fa; --purple:#c4b5fd;
  --r-sm:8px; --r:12px; --r-lg:16px;
  --sh-sm:0 1px 2px rgba(0,0,0,.3); --sh:0 6px 18px -6px rgba(0,0,0,.5);
  --tr:160ms ease;
}}
*{{box-sizing:border-box}}
body{{font-family:-apple-system,'PingFang SC','Microsoft YaHei',system-ui,sans-serif;background:var(--bg);color:var(--text);margin:0;line-height:1.5;-webkit-font-smoothing:antialiased}}
a{{color:var(--info);text-decoration:none}}
.top{{background:linear-gradient(135deg,#0d1426,#15203a);border-bottom:1px solid var(--border);padding:14px 24px;display:flex;align-items:center;gap:14px}}
.top h1{{font-size:18px;margin:0;flex:1;letter-spacing:.3px}}
.pill{{font-size:12px;padding:4px 12px;border-radius:20px;background:{'#3b2314' if _running['task'] else '#0e2a1d'};color:{'#fbbf24' if _running['task'] else '#4ade80'};border:1px solid {'#78350f' if _running['task'] else '#14532d'}}}
.dot{{width:8px;height:8px;border-radius:50%;background:var(--pass);flex:none;animation:pulse 2s infinite}}
@keyframes pulse{{0%{{box-shadow:0 0 0 0 rgba(74,222,128,.5)}}70%{{box-shadow:0 0 0 7px rgba(74,222,128,0)}}100%{{box-shadow:0 0 0 0 rgba(74,222,128,0)}}}}
.ver{{font-size:11px;color:var(--faint);border:1px solid var(--border);padding:2px 8px;border-radius:8px}}
.tabs{{display:flex;gap:6px;padding:10px 24px;border-bottom:1px solid var(--border);background:var(--surface);overflow-x:auto;position:sticky;top:0;z-index:20;backdrop-filter:blur(6px)}}
.tab{{background:none;border:0;color:var(--muted);font-size:14px;padding:9px 16px;border-radius:10px;cursor:pointer;white-space:nowrap;transition:background var(--tr),color var(--tr)}}
.tab:hover{{color:var(--text);background:var(--surface-2)}}
.tab:focus-visible{{outline:2px solid var(--primary);outline-offset:2px}}
.tabin{{display:none}}
section{{display:none;padding:22px 24px;max-width:1200px;margin:auto;animation:fade .2s ease}}
@keyframes fade{{from{{opacity:.4}}to{{opacity:1}}}}
#t-overview:checked~section#overview{{display:block}}
#t-strategies:checked~section#strategies{{display:block}}
#t-risk:checked~section#risk{{display:block}}
#t-health:checked~section#health{{display:block}}
#t-trades:checked~section#trades{{display:block}}
#t-ops:checked~section#ops{{display:block}}
#t-data:checked~section#data{{display:block}}
#t-scan:checked~section#scan{{display:block}}
#t-accounts:checked~section#accounts{{display:block}}
#t-learn:checked~section#learn{{display:block}}
#t-reports:checked~section#reports{{display:block}}
#t-overview:checked~.tabs label[for="t-overview"],
#t-strategies:checked~.tabs label[for="t-strategies"],
#t-risk:checked~.tabs label[for="t-risk"],
#t-health:checked~.tabs label[for="t-health"],
#t-trades:checked~.tabs label[for="t-trades"],
#t-ops:checked~.tabs label[for="t-ops"],
#t-data:checked~.tabs label[for="t-data"],
#t-scan:checked~.tabs label[for="t-scan"],
#t-accounts:checked~.tabs label[for="t-accounts"],
#t-learn:checked~.tabs label[for="t-learn"],
#t-reports:checked~.tabs label[for="t-reports"]{{background:var(--surface-2);color:var(--info);font-weight:600;box-shadow:inset 0 -2px 0 var(--primary)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px}}
.card{{background:var(--surface);border:1px solid var(--border);border-radius:var(--r-lg);padding:18px;transition:transform var(--tr),box-shadow var(--tr),border-color var(--tr)}}
.card:hover{{transform:translateY(-3px);box-shadow:var(--sh);border-color:#2b3a5e}}
.hero{{background:radial-gradient(120% 140% at 0% 0%,#16224a 0%,#0f1629 60%);border:1px solid #21336b;border-radius:var(--r-lg);padding:22px;margin-bottom:18px}}
.card-head{{display:flex;justify-content:space-between;align-items:center;gap:10px}}
.card-head h3{{margin:0;font-size:15px;color:var(--text)}}
.badge{{font-size:11px;color:var(--muted);background:var(--surface-2);padding:3px 9px;border-radius:10px;border:1px solid var(--border-soft)}}
.big{{font-size:30px;font-weight:800;margin:10px 0 8px;font-variant-numeric:tabular-nums;letter-spacing:.5px}}
.chips{{display:flex;gap:8px;margin-bottom:8px;flex-wrap:wrap}}
.chip{{font-size:12px;padding:4px 10px;border-radius:9px;background:var(--surface-2);color:var(--muted);border:1px solid var(--border-soft)}}
.chip.up{{color:var(--up);background:var(--up-bg)}}.chip.down{{color:var(--down);background:var(--down-bg)}}
.chip.ok{{color:var(--pass);background:var(--down-bg)}}.chip.warn{{color:var(--warn);background:#2a230e}}
.sub{{font-size:13px;color:var(--muted)}}
.up{{color:var(--up)}}.down{{color:var(--down)}}
.pass{{color:var(--pass);font-weight:600}}.fail{{color:var(--fail);font-weight:600}}
.curve{{margin-top:12px}}
table{{border-collapse:collapse;width:100%;font-size:13px;background:var(--surface);border-radius:12px;overflow:hidden;border:1px solid var(--border)}}
td,th{{padding:9px 13px;border-bottom:1px solid var(--border);text-align:left}}
th{{color:var(--info);font-weight:600;background:var(--surface-2)}}
tr:hover td{{background:var(--surface-2)}}
.rate{{font-weight:600;color:var(--purple)}}
h2{{font-size:16px;margin:24px 0 12px;color:var(--info);display:flex;align-items:center;gap:8px}}
h2::before{{content:"";width:4px;height:16px;background:var(--primary);border-radius:3px;display:inline-block}}
h3{{font-size:14px;color:var(--info);margin:16px 0 8px}}
.btn{{background:linear-gradient(180deg,var(--primary),var(--primary-strong));color:#fff;border:0;border-radius:10px;padding:9px 15px;margin:4px;cursor:pointer;font-size:13px;text-decoration:none;display:inline-block;box-shadow:var(--sh-sm);transition:transform var(--tr),box-shadow var(--tr),filter var(--tr)}}
.btn:hover{{transform:translateY(-1px);box-shadow:var(--sh);filter:brightness(1.07)}}
.btn:active{{transform:translateY(0)}}
.btn:focus-visible{{outline:2px solid var(--primary);outline-offset:2px}}
.rep{{display:inline-block;color:var(--info);background:var(--surface-2);border:1px solid #21336b;padding:7px 13px;border-radius:10px;margin:4px;font-size:13px;transition:border-color var(--tr),background var(--tr)}}
.rep:hover{{border-color:var(--primary);background:#16213c}}
.updated{{color:var(--faint);font-size:12px;margin:24px 0}}
.muted{{color:var(--faint)}}
.stat{{display:flex;gap:26px;flex-wrap:wrap;margin:10px 0}}
.stat div{{font-size:13px;color:var(--muted)}}.stat b{{color:var(--text);font-size:16px;display:block;font-variant-numeric:tabular-nums}}
@media (prefers-reduced-motion:reduce){{*{{animation:none!important;transition:none!important}}}}
@media (max-width:640px){{.top h1{{font-size:15px}}.big{{font-size:24px}}section{{padding:16px}}}}
</style></head><body>
{radios}
<div class="top"><span class="dot" title="系统在线"></span><h1>📊 星辰投研团 · 量化操作系统</h1><span class="ver">v{VERSION}</span><span class="pill">{pill}</span>
<span class="muted" style="font-size:12px">每60秒自动刷新 · 零JS兼容</span></div>
<div class="tabs">{labels}</div>
<section id="overview">
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
<section id="health"><h2>策略体检（引擎回测绩效）</h2>{tear}</section>
<section id="trades"><h2>纸面持仓</h2>{paper_positions_view()}
<h2>交易记录（引擎 SQLite）</h2>{trades_view()}</section>
<section id="ops"><h2>操作台（点击即执行，自动排队）</h2>
<div class="stat"><div>并发<b>串行+排队</b></div><div>排队上限<b>3</b></div></div>
{forms}
<p class="muted">点击任务后跳到任务页，每 3 秒自动刷新显示日志；可随时取消。</p></section>
<section id="data"><h2>自选行情（本地两日涨跌）</h2>{market_view()}
<h2>数据新鲜度</h2>
<table><tr><th>市场</th><th>标的数</th><th>状态</th></tr>{fresh}</table>
<div class="stat"><div>期权 IV<b>{iv_line or '—'}</b></div>
<div>GEX（SPY/QQQ）<b>{gex_line or '数据待补'}</b></div></div></section>
<section id="scan"><h2>研究驱动全宇宙扫描（五道闸验证）</h2>{scan_view()}</section>
<section id="accounts"><h2>模拟盘账户（全部 {len(nav_data())} 个）</h2>{accounts_view()}</section>
<section id="learn"><h2>每日量化学习</h2>{learning_view()}</section>
<section id="reports"><h2>报告（最近 12 份）</h2><div>{reports or '<span class="muted">暂无</span>'}</div></section>
<div style="padding:0 24px"><div class="updated">自动生成 · 仅供学习研究参考，不构成投资建议 · 仅限本机访问 · {pd.Timestamp.now():%H:%M:%S}</div></div>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # —— 健康检查（供 Docker HEALTHCHECK / 监控）——
        if self.path.startswith("/health"):
            self._json({
                "status": "ok",
                "service": "xingchen-quant-dashboard",
                "version": VERSION,
                "uptime_s": round(time.time() - START_TS, 1),
                "now": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            })
            return
        if self.path.startswith("/ready"):
            try:
                ready = bool(nav_data())
            except Exception:
                ready = False
            if ready:
                self._json({
                    "status": "ready",
                    "service": "xingchen-quant-dashboard",
                    "accounts": len(nav_data()),
                })
            else:
                self._json({
                    "status": "not_ready",
                    "service": "xingchen-quant-dashboard",
                    "reason": "no account nav data available",
                }, code=503)
            return
        if self.path.startswith("/api/run"):
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            key = int(q.get("key", ["0"])[0])
            name = list(ACTIONS)[key]
            status = enqueue(name, ACTIONS[name])
            self._html(task_page(f"任务：{name} " + (f"（已排队：{status}）" if isinstance(status, str) else "（已启动）")))
            return
        if self.path.startswith("/api/cancel"):
            cancel()
            self._html(task_page("已取消当前任务并清空队列"))
            return
        if self.path.startswith("/api/task"):
            self._html(task_page())
            return
        if self.path.startswith("/api/log"):
            self._json({"running": _running["task"] is not None,
                        "task": _running["task"], "log": _running["log"],
                        "queue": [n for n, _ in _queue]})
            return
        if self.path.startswith("/file/"):
            name = unquote(self.path.split("/file/", 1)[1])
            target = (ROOT / "docs" / name).resolve()
            docs_root = (ROOT / "docs").resolve()
            # 防目录穿越：仅允许访问 docs 目录内文件
            if not str(target).startswith(str(docs_root) + "/") and target != docs_root:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"bad path")
                return
            if target.is_file():
                body = target.read_bytes()
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
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        self.wfile.write(body)

    def _html(self, html):
        body = html.encode("utf-8")
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

    def log_request(self, code="-", size="-"):
        log_event("http", request=getattr(self, "requestline", "-"),
                  status=str(code), bytes=str(size))

    def log_message(self, *a):
        pass  # 抑制默认纯文本日志，结构化 JSON 由 log_request 统一输出


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8080)
    args = p.parse_args()
    log_event("startup", host=args.host, port=args.port, version=VERSION)
    print(f"看板已启动：http://{args.host}:{args.port}（零 JS 兼容）")
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
