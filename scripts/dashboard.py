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
</style></head><body>
<div class="top"><h1>📊 星辰投研团 · 量化操作系统</h1>
<span id="pill" class="pill">自运转</span><button class="refresh" onclick="toggleRefresh()">自动刷新</button></div>
<div class="tabs" id="tabs">
<button class="tab active" data-t="overview">概览</button>
<button class="tab" data-t="strategies">策略</button>
<button class="tab" data-t="risk">风控</button>
<button class="tab" data-t="ops">操作台</button>
<button class="tab" data-t="data">数据</button>
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
<section id="ops"><h2>操作台</h2><div>{btns}</div>
<p id="runstate" class="muted"></p><pre id="output">就绪。点击按钮触发任务，输出实时显示。</pre></section>
<section id="data"><h2>数据新鲜度</h2>
<table><tr><th>市场</th><th>标的数</th><th>状态</th></tr>{fresh}</table>
<h2>市场摘要</h2><div class="stat"><div>期权 IV<b>{iv_line or '—'}</b></div></div></section>
<section id="reports"><h2>报告（最近 12 份）</h2><div>{reports or '<span class="muted">暂无</span>'}</div></section>
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
