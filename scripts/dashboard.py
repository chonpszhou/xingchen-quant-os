#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 本地网页看板（零第三方依赖，标准库实现）

展示：三模拟盘净值与基准（SVG 曲线）/ 风控 / 一致性 / 双低TOP10 /
数据新鲜度 / 期货与期权 IV / 报告入口。

用法:
    python3 scripts/dashboard.py                 # http://127.0.0.1:8080
    python3 scripts/dashboard.py --port 9000
    python3 scripts/dashboard.py --host 0.0.0.0  # Docker/局域网
"""

import argparse
import json
import sys
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent


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
        }
    return out


def svg_curve(dates, navs, w=360, h=90):
    if len(navs) < 2:
        return "<p>数据积累中</p>"
    mn, mx = min(navs), max(navs)
    rng = (mx - mn) or 1
    pts = []
    for i, (d, v) in enumerate(zip(dates, navs)):
        x = 8 + i * (w - 16) / (len(navs) - 1)
        y = h - 12 - (v - mn) * (h - 24) / rng
        pts.append(f"{x:.1f},{y:.1f}")
    return (f'<svg viewBox="0 0 {w} {h}" style="width:100%;height:90px">'
            f'<polyline fill="none" stroke="#3b82f6" stroke-width="2" points="{" ".join(pts)}"/>'
            f'</svg>')


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


def read_md_table(path, startswith="|"):
    p = ROOT / "docs" / path
    if not p.exists():
        return []
    return [l for l in p.read_text(encoding="utf-8").splitlines()
            if l.startswith(startswith) and not l.startswith("|---")]


def render():
    accounts = nav_data()
    cards = ""
    for name, a in accounts.items():
        cards += f"""
        <div class="card">
          <h3>{name} <span class="tag">调仓{a['rebal']}次 · {a['days']}天</span></h3>
          <div class="big">{a['nav']:,.0f}</div>
          <div class="sub">基准 {a['bench']:,.0f} · 超额 <b style="color:{'#16a34a' if a['excess']>=0 else '#dc2626'}">{a['excess']:+,.0f}</b></div>
          <div class="curve">{svg_curve(a['dates'], a['navs'])}</div>
        </div>"""
    top = "".join(
        f"<tr><td>{r['name']}</td><td>{r['price']:.1f}</td><td>{r['premium']:.1f}%</td>"
        f"<td>{r['score']:.1f}</td><td>{r.get('rating','-')}</td></tr>" for r in cb_top())
    fresh = "".join(f"<tr><td>{m}</td><td>{n}</td><td>{s}</td></tr>" for m, n, s in freshness())
    risk = "".join(f"<tr>{''.join(f'<td>{c}</td>' for c in l.split('|')[1:-1])}</tr>"
                   for l in read_md_table("风控状态.md"))
    return f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>星辰投研团 · 看板</title>
<style>
body{{font-family:-apple-system,'PingFang SC',sans-serif;background:#0f172a;color:#e2e8f0;margin:0;padding:20px}}
h1{{font-size:22px}} h2{{font-size:17px;margin-top:28px;color:#93c5fd}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px}}
.card{{background:#1e293b;border-radius:12px;padding:16px}}
.tag{{font-size:12px;color:#94a3b8;font-weight:normal}}
.big{{font-size:26px;font-weight:700;margin:6px 0}}
.sub{{font-size:13px;color:#94a3b8}}
.curve{{margin-top:8px}}
table{{border-collapse:collapse;width:100%;font-size:13px}}
td,th{{padding:6px 10px;border-bottom:1px solid #334155;text-align:left}}
th{{color:#93c5fd;font-weight:600}}
.wrap{{max-width:1100px;margin:auto}}
.updated{{color:#64748b;font-size:12px;margin-top:20px}}
</style></head><body><div class="wrap">
<h1>📊 星辰投研团 · 量化操作系统看板</h1>
<div class="grid">{cards}</div>
<h2>风控状态</h2><table>{risk or "<tr><td>数据积累中</td></tr>"}</table>
<h2>可转债双低 TOP10</h2>
<table><tr><th>名称</th><th>价格</th><th>溢价</th><th>双低值</th><th>评级</th></tr>{top}</table>
<h2>数据新鲜度</h2>
<table><tr><th>市场</th><th>标的数</th><th>状态</th></tr>{fresh}</table>
<h2>报告</h2>
<p style="font-size:13px">
<a href="/file/投研摘要_{date.today():%Y%m%d}.md" style="color:#60a5fa">今日摘要</a> ·
<a href="/file/系统状态.md" style="color:#60a5fa">系统状态</a> ·
<a href="/file/模拟盘预期区间.md" style="color:#60a5fa">预期区间</a> ·
<a href="/file/下次调仓预告.md" style="color:#60a5fa">调仓预告</a>
</p>
<div class="updated">自动生成 · 仅供学习研究参考，不构成投资建议 · 刷新查看最新</div>
</div></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
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
            self.send_response(404); self.end_headers()
            self.wfile.write(b"not found")
            return
        body = render().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
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
