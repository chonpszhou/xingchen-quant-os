#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 每日账面对比（今日实时权益 vs 昨日收盘）

生成:
    data/equity_report.json
    data/equity_report.md

--push:
    通过 scripts/push_digest.py 把 markdown 推送到已配置通道（邮件/IM）。
    条件推送：仅当「6 账户总权益单日变动 %」≥ 环境变量 DAILY_REPORT_PUSH_MIN_PCT
    （默认 0.5）或触发回撤告警时才发；平稳日静默（报告仍生成）。设该变量为 0 即恢复每日必发。

口径说明
--------
- "今日实时" = data/intraday_mtm.json 当前快照（盘中盯市每 15min 刷新，权益=现金+持仓市值）。
- "昨日收盘" = data/paper_*_nav.parquet 中日期 = (今日-1) 的行；若该账户当日尚未落 nav 行，
  则取最近一个 < 今日的收盘行（美股账户常因盘中未收盘而沿用上一收盘，报告中标注 ⚠ 沿用旧收）。
- 日期列在不同 parquet 中可能是 int(20260902) / str(2026-09-02) / datetime，统一归一化为 YYYYMMDD。

仅依赖 pandas（镜像内已装，read_parquet 走 pyarrow）。
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
INIT = 1_000_000.0
OBS_ACCOUNTS = ["paper_aapl"]  # 观察级账户，单独列示、不计入"真实盘"合计
ORDER = ["paper_cb", "paper_mom", "paper_rp", "paper_crypto", "paper_hk", "paper_aapl"]
NAMES = {
    "paper_cb": "可转债双低",
    "paper_mom": "双动量ETF",
    "paper_rp": "风险平价",
    "paper_crypto": "加密等权",
    "paper_hk": "港股等权",
    "paper_aapl": "AAPL灰度(观察)",
}


def _nav_date_norm(df):
    """把 nav 的 date 列归一化为 YYYYMMDD 字符串（兼容 int/str/datetime）。"""
    s = (
        df["date"]
        .astype(str)
        .str.replace("-", "", regex=False)
        .str.replace(" ", "", regex=False)
        .str.replace(":", "", regex=False)
    )
    return s.str.slice(0, 8)


def load_intraday():
    p = DATA / "intraday_mtm.json"
    if not p.exists():
        return None, {}
    try:
        m = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None, {}
    return m.get("today"), m.get("accounts", {})


def load_yesterday(today):
    """返回 {account: {"nav": float, "cash": float}}，取日期=today-1 的行，缺失则取最近 < today 的收盘行。"""
    y = today - timedelta(days=1)
    YN = y.strftime("%Y%m%d")
    TN = today.strftime("%Y%m%d")
    out = {}
    for f in sorted(DATA.glob("paper_*_nav.parquet")):
        a = f.stem.replace("_nav", "")
        try:
            df = pd.read_parquet(f)
        except Exception:
            continue
        if "date" not in df.columns or "nav" not in df.columns:
            continue
        d = _nav_date_norm(df)
        row = df[d == YN]
        if len(row) == 0:
            row = df[d < TN]
            row = row.tail(1) if len(row) else df.tail(1)
        if len(row) == 0:
            continue
        r = row.iloc[0]
        out[a] = {
            "nav": float(r["nav"]),
            "cash": float(r["cash"]) if "cash" in df.columns else 19020.0,
        }
    return out


def _has_drawdown_breach():
    """回撤告警是否触发（任一真实账户当前权益较历史峰值回撤超阈值）。触发则无论变动大小都推送。"""
    p = DATA / "drawdown_alert.json"
    if not p.exists():
        return False
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return False
    return any(a.get("breach") for a in d.get("accounts", {}).values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--push", action="store_true", help="生成后通过 push_digest.py 推送")
    args = ap.parse_args()

    today_str, intraday = load_intraday()
    try:
        today = datetime.strptime(today_str, "%Y-%m-%d").date() if today_str else date.today()
    except Exception:
        today = date.today()
    yest_map = load_yesterday(today)

    rows = []
    for a in ORDER:
        v = intraday.get(a, {})
        tv = float(v.get("equity")) if (v and v.get("equity") is not None) else None
        live = bool(v.get("live", False)) if v else False
        yv = yest_map.get(a, {}).get("nav")
        cv = float(v.get("cash", 0.0)) if (v and v.get("cash") is not None) else yest_map.get(a, {}).get("cash", 19020.0)
        yc = yest_map.get(a, {}).get("cash", 19020.0)
        dy = (tv - yv) if (tv is not None and yv is not None) else None
        dcy = cv - yc
        if tv is not None and abs(tv - cv) < 1:
            status = "全现金"
        elif live:
            status = "实时"
        else:
            status = "⚠沿用旧收"
        rows.append(
            {
                "account": a,
                "name": NAMES.get(a, a),
                "yesterday": yv,
                "today": tv,
                "delta": dy,
                "cash_today": cv,
                "cash_yest": yc,
                "cash_delta": dcy,
                "live": live,
                "status": status,
            }
        )

    ty = sum((r["yesterday"] for r in rows if r["yesterday"] is not None), 0.0)
    tt = sum((r["today"] for r in rows if r["today"] is not None), 0.0)
    tc = sum((r["cash_today"] for r in rows), 0.0)
    yc_all = sum((r["cash_yest"] for r in rows), 0.0)
    ty5 = sum((r["yesterday"] for r in rows if r["account"] not in OBS_ACCOUNTS and r["yesterday"] is not None), 0.0)
    tt5 = sum((r["today"] for r in rows if r["account"] not in OBS_ACCOUNTS and r["today"] is not None), 0.0)

    # 快照时点提示（动态）：标明实时/沿用旧收账户，避免误读单日 Δ
    live_accounts = [r["name"] for r in rows if r["status"] == "实时"]
    stale_accounts = [r["name"] for r in rows if r["status"] == "⚠沿用旧收"]
    allcash_accounts = [r["name"] for r in rows if r["status"] == "全现金"]
    if stale_accounts:
        live_txt = "、".join(live_accounts) if live_accounts else "无（均未取到实时价）"
        stale_txt = "、".join(stale_accounts)
        allcash_txt = f"；全现金（已清仓）：{('、'.join(allcash_accounts))}" if allcash_accounts else ""
        snapshot_note = (
            "⚠ **快照时点提示**：本对比为「今日实时快照 vs 昨日收盘」的混合时点——"
            f"实时账户：{live_txt}；沿用上一收盘（⚠）：{stale_txt}{allcash_txt}。"
            "各市场开闭市不同，快照天然混合实时价与昨收价；表中单日权益Δ主要反映实时账户的变动，"
            "并非四市场统一时点的完整当日盈亏。做归因时请以「状态」列（实时/沿用旧收/全现金）为准。"
        )
    else:
        snapshot_note = "✓ 本对比所有账户均为实时价（四市场统一收盘后快照）。"

    report = {
        "date": today.isoformat(),
        "yesterday": (today - timedelta(days=1)).isoformat(),
        "accounts": rows,
        "total_all": {
            "yesterday": ty,
            "today": tt,
            "delta": tt - ty,
            "cash_today": tc,
            "cash_yest": yc_all,
            "cash_delta": tc - yc_all,
        },
        "total_real": {"yesterday": ty5, "today": tt5, "delta": tt5 - ty5},
        "initial": INIT * 6,
        "cum_vs_initial": tt - INIT * 6,
        "cum_vs_initial_pct": (tt - INIT * 6) / (INIT * 6) * 100,
        "snapshot_note": snapshot_note,
    }
    (DATA / "equity_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    yd = (today - timedelta(days=1)).isoformat()
    L = []
    L.append(f"# 星辰投研团 · 每日账面对比（{today.isoformat()} vs {yd}）")
    L.append("")
    L.append("> 口径：今日=盘中盯市实时快照；昨日=上一交易日收盘权益。标注 ⚠ 表示今日尚未刷新实时价（沿用上一收盘）。")
    L.append("")
    L.append(snapshot_note)
    L.append("")
    L.append("| 账户 | 昨日收盘 | 今日实时 | 权益Δ | 今日现金 | 现金Δ | 状态 |")
    L.append("|------|------:|------:|------:|------:|------:|------|")
    for r in rows:
        yv = f"{r['yesterday']:,.2f}" if r["yesterday"] is not None else "-"
        tv = f"{r['today']:,.2f}" if r["today"] is not None else "-"
        dy = f"{r['delta']:+,.2f}" if r["delta"] is not None else "-"
        dcy = f"{r['cash_delta']:+,.2f}"
        st = r.get("status", "实时") or ("实时" if r["live"] else "⚠沿用旧收")
        L.append(f"| {r['name']} | {yv} | {tv} | {dy} | {r['cash_today']:,.2f} | {dcy} | {st} |")
    L.append(
        f"| **合计(6账户)** | **{ty:,.2f}** | **{tt:,.2f}** | **{tt - ty:+,.2f}** | **{tc:,.2f}** | **{tc - yc_all:+,.2f}** | |"
    )
    L.append(f"| 合计(5真实盘) | {ty5:,.2f} | {tt5:,.2f} | {tt5 - ty5:+,.2f} | - | - | |")
    L.append("")
    L.append(
        f"- 初始总投入：{INIT * 6:,.0f} ｜ 今日总权益：**{tt:,.2f}** ｜ 累计 vs 初始：**{tt - INIT * 6:+,.2f}（{(tt - INIT * 6) / (INIT * 6) * 100:+.2f}%）**"
    )
    L.append(f"- 可用现金：{yc_all:,.2f} → {tc:,.2f}（Δ {tc - yc_all:+,.2f}）")
    L.append("")
    L.append("> 自动生成，仅供学习参考，不构成投资建议。")
    md = "\n".join(L)
    (DATA / "equity_report.md").write_text(md, encoding="utf-8")
    print(md)
    print(f"\n✓ 已写入 data/equity_report.json / data/equity_report.md")

    if args.push:
        min_pct = float(os.environ.get("DAILY_REPORT_PUSH_MIN_PCT", "0.5"))
        total_delta = report["total_all"]["delta"]
        total_yest = report["total_all"]["yesterday"] or 1.0
        delta_pct = total_delta / total_yest * 100
        breach = _has_drawdown_breach()
        if abs(delta_pct) >= min_pct or breach:
            reason = (
                "回撤告警触发" if breach and abs(delta_pct) < min_pct
                else f"权益变动 {delta_pct:+.2f}% ≥ 阈值 {min_pct:.2f}%"
            )
            print(f"→ 推送每日账面对比（{reason}）…")
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "push_digest.py"),
                    "--file",
                    str(DATA / "equity_report.md"),
                    "--subject",
                    f"星辰投研团 · 每日账面对比 {today.isoformat()}",
                ],
                check=False,
            )
        else:
            print(
                f"· 权益变动 {delta_pct:+.2f}% < 阈值 {min_pct:.2f}%，且无回撤告警 "
                f"→ 跳过推送（报告已生成于 data/equity_report.md）"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
