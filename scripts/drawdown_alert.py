#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""星辰投研团 · 模拟盘权益回撤告警（item ⑤）。

含义：每个模拟盘账户的「当前权益」相对其「历史峰值权益」的回撤；
      当回撤 ≤ -ALERT_PCT（默认 5%，环境变量 DRAWDOWN_ALERT_PCT 可覆盖）时触发告警。

与 risk_monitor 的区别：
  - risk_monitor 看的是「整个历史区间的最大峰谷回撤」对比账户硬阈值（20/25/10/15%）；
  - 本脚本看的是「此刻权益 vs 历史峰值」的实时回撤，更敏感、更直接反映
    「账户正在从高点往下掉」，适合做盘中/日终的及时告警。

当前权益取值优先级：
  1) 盘中盯市 data/intraday_mtm.json（若 ts 为今天且 ≤2h 前，取该账户 equity）
  2) 否则回落到日终 paper_*_nav.parquet 最新一行 nav
历史峰值：paper_*_nav.parquet 中 nav 的累计最大值（cummax）。

输出：
  - 标准输出打印 Markdown 告警（供 push_digest.py --file 推送）
  - data/drawdown_alert.json 落盘（机器可读，供看板/调度分支）
  - data/drawdown_alert.md 落盘（人类可读，供 push_digest.py --file 读取）
退出码：0=无告警；2=触发告警（供调度器分支立即推送）
"""
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
ALERT_PCT = float(os.environ.get("DRAWDOWN_ALERT_PCT", "0.05"))

# (显示名, NAV parquet 前缀, intraday 账户 key)
# 仅覆盖 5 个真实注资模拟盘；AAPL·灰度 为观察级(续十候选前向跟踪)，其 nav 为子日频、
# 非真实资金账户，易产生 -40% 这类噪声回撤，故与 risk_monitor 一致排除。
ACCOUNTS = [
    ("双低·可转债", "paper_cb", "paper_cb"),
    ("双动量·ETF", "paper_mom", "paper_mom"),
    ("风险平价", "paper_rp", "paper_rp"),
    ("加密·等权", "paper_crypto", "paper_crypto"),
    ("港股", "paper_hk", "paper_hk"),
]


def load_intraday():
    p = DATA / "intraday_mtm.json"
    if not p.exists():
        return None, None
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
        return obj, obj.get("ts", "")
    except Exception:
        return None, None


def intraday_current(obj, key):
    """返回 (equity, fresh_bool)。fresh = ts 为今天且 ≤2h 前。"""
    acct = (obj.get("accounts") or {}).get(key)
    if not acct:
        return None, False
    eq = acct.get("equity")
    ts = obj.get("ts", "")
    fresh = False
    try:
        dt = datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S") if ts else None
        now = datetime.now()
        if dt and dt.date() == now.date() and (now - dt) <= timedelta(hours=2):
            fresh = True
    except Exception:
        fresh = False
    return eq, fresh


def main():
    import pandas as pd

    intraday, intraday_ts = load_intraday()
    rows = []
    breaches = []
    out = {
        "alert_pct": ALERT_PCT,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "intraday_ts": intraday_ts,
        "accounts": {},
    }
    for name, nav_pre, mtm_key in ACCOUNTS:
        nav_file = DATA / f"{nav_pre}_nav.parquet"
        if not nav_file.exists():
            continue
        df = pd.read_parquet(nav_file)
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date")
        nav = df["nav"].astype(float)
        peak = float(nav.cummax().iloc[-1])
        last_nav = float(nav.iloc[-1])
        ieq, fresh = intraday_current(intraday, mtm_key) if intraday else (None, False)
        current = ieq if (ieq is not None and fresh) else last_nav
        src = "盘中盯市" if (ieq is not None and fresh) else "日终净值"
        dd_now = current / peak - 1 if peak > 0 else 0.0
        breach = dd_now <= -ALERT_PCT
        rows.append({"name": name, "current": current, "peak": peak,
                     "dd": dd_now, "src": src, "breach": breach})
        out["accounts"][nav_pre] = {
            "name": name, "current": round(current, 2), "peak": round(peak, 2),
            "dd": round(dd_now, 6), "src": src, "breach": breach,
        }
        if breach:
            breaches.append(
                f"{name}：当前权益 {current:,.0f} 较峰值 {peak:,.0f} 回撤 {dd_now:.2%}"
                f"（≤ -{ALERT_PCT:.0%}）")

    lines = ["# 模拟盘权益回撤告警", "",
             f"> 触发阈值：回撤 ≤ -{ALERT_PCT:.0%}（当前权益 vs 历史峰值）",
             f"> 数据时刻：{intraday_ts or '—'}", "",
             "| 账户 | 当前权益 | 历史峰值 | 回撤 | 数据源 |",
             "|------|----------|----------|------|--------|"]
    for r in rows:
        icon = "🚨" if r["breach"] else "✅"
        lines.append(f"| {r['name']} | {r['current']:,.0f} | {r['peak']:,.0f} | "
                     f"{r['dd']:.2%} | {r['src']} {icon} |")
    lines += ["", "## 告警", ""]
    lines += [f"- 🚨 {b}" for b in breaches] if breaches else ["- 无回撤告警，全部账户在阈值内"]
    lines += ["", "> 自动生成，仅供学习研究参考，不构成投资建议。", ""]
    md = "\n".join(lines)

    (DATA / "drawdown_alert.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    (DATA / "drawdown_alert.md").write_text(md, encoding="utf-8")
    print(md)
    return 2 if breaches else 0


if __name__ == "__main__":
    sys.exit(main())
