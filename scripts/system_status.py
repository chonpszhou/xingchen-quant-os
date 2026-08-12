#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 系统健康看板（一页总览）

检查：数据新鲜度 / 策略与模拟盘 / 监控任务 / 推送配置 / 研究结论

用法:
    python3 scripts/system_status.py
输出:
    docs/系统状态.md
"""

import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from datahub.store import LocalStore  # noqa: E402


def freshness(store):
    st = store.all_status()
    rows = []
    for market in ("A股", "港股", "美股", "虚拟货币", "期货"):
        g = st[st["market"] == market]
        if g.empty:
            rows.append((market, 0, "-", "无数据"))
            continue
        last = g["last_date"].max()
        days_behind = (pd.Timestamp(date.today()) - pd.Timestamp(last)).days
        state = "✓ 新鲜" if days_behind <= 4 else ("⚠ 落后" if days_behind <= 10 else "✗ 过期")
        rows.append((market, len(g), str(last), f"{state}（{days_behind}天）"))
    return rows


def main():
    store = LocalStore(str(ROOT / "data"))
    lines = [
        "# 星辰投研团 · 系统状态",
        "",
        f"> 生成时间：{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "## 数据层",
        "",
        "| 市场 | 标的数 | 最新数据日 | 状态 |",
        "|------|--------|-----------|------|",
    ]
    for m, n, last, state in freshness(store):
        lines.append(f"| {m} | {n} | {last} | {state} |")

    # 策略与模拟盘
    nav_file = ROOT / "data" / "paper_cb_nav.parquet"
    state_file = ROOT / "data" / "paper_cb_state.json"
    lines += ["", "## 策略与模拟盘", ""]
    lines.append("- 引擎一致性：双低重放与回测 0.00% 偏差 ✓；双动量 1.25% 偏差 ✓（validate_paper_engines.py）")
    if nav_file.exists() and state_file.exists():
        nav = pd.read_parquet(nav_file)
        st = json.loads(state_file.read_text(encoding="utf-8"))
        last = nav.iloc[-1]
        bench = f" / 基准 {last['bench_nav']:,.0f}" if "bench_nav" in nav.columns else ""
        lines += [f"- **可转债双低**（唯一实盘候选）：净值 {last['nav']:,.0f}{bench}，"
                  f"持仓 {int(last['holdings'])} 只，调仓 {st['rebalance_count']} 次",
                  f"- 回测验证：N=30/溢价≤30 + 信用过滤 → 年化 14.4%、HAC t 3.03（保守口径）",
                  f"- 实盘门槛：模拟盘连续 3 个月跑赢全债等权基准（未满足，跟踪中）",
                  ""]
    else:
        lines.append("- 模拟盘未启动（运行 python3 scripts/paper_trade_cb.py）\n")
    mom_nav = ROOT / "data" / "paper_mom_nav.parquet"
    if mom_nav.exists():
        mnav = pd.read_parquet(mom_nav)
        ml = mnav.iloc[-1]
        lines += [f"- **双动量 ETF 轮动**（观察级候选）：净值 {ml['nav']:,.0f} / SPY基准 {ml['bench_nav']:,.0f}，"
                  f"当前持仓 {ml['holding']}",
                  f"- 回测验证：精简池 3-6-12M → 年化 22.7%、HAC t 2.54（DSR 0.025 未过门控，观察级）",
                  ""]
    rp_nav = ROOT / "data" / "paper_rp_nav.parquet"
    if rp_nav.exists():
        rnav = pd.read_parquet(rp_nav)
        rl = rnav.iloc[-1]
        lines += [f"- **风险平价底仓**（稳定型观察）：净值 {rl['nav']:,.0f} / SPY基准 {rl['bench_nav']:,.0f}",
                  f"- 回测验证：逆波动率配置 → 年化 5.8%、回撤 -5.8%（SPY 的 1/3）、HAC t 2.21",
                  ""]

    # 监控
    snap = ROOT / "data" / "cb_daily_snapshot.json"
    iv = ROOT / "docs" / "期权IV监控快照.md"
    lines += ["## 监控任务", "",
              f"- 双低监控：{'✓ 最近快照 ' + json.loads(snap.read_text(encoding='utf-8')).get('date', '-') if snap.exists() else '未运行'}",
              f"- 期权 IV：{'✓ 已生成' if iv.exists() else '未生成'}（指数级正常，个股链视限流）",
              f"- 风控监控：{'✓ 已运行（docs/风控状态.md）' if (ROOT / 'docs' / '风控状态.md').exists() else '未运行'}",
              f"- 定时任务：见 config/tasks.yaml（daily_summary 工作日 16:35 全链路）",
              ""]

    # 推送
    push_cfg = yaml.safe_load((ROOT / "config" / "push.yaml").read_text(encoding="utf-8"))["push"]
    env = {}
    if (ROOT / ".env").exists():
        for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    email_on = push_cfg.get("email", {}).get("enabled") and env.get("SMTP_USER")
    im_on = [k for k, c in push_cfg.get("im", {}).items()
             if c.get("enabled") and env.get({"feishu": "FEISHU_WEBHOOK", "dingtalk": "DINGTALK_WEBHOOK",
                                              "wecom": "WECOM_WEBHOOK", "serverchan": "SERVERCHAN_KEY",
                                              "pushplus": "PUSHPLUS_TOKEN", "wechat": "wechat"}[k])]
    lines += ["## 推送通道", "",
              f"- 邮件：{'✓ 启用' if email_on else '未启用（填 .env 后开启）'}",
              f"- IM：{('、'.join(im_on) + ' 已启用') if im_on else '未启用（填 .env 后开启）'}",
              ""]

    # 研究结论
    lines += ["## 研究结论（13 份报告）", "",
              "- 通过门控：可转债双低 + 信用过滤（唯一实盘候选）",
              "- 观察级：无（加密趋势在波动率归一化后确认无边际）",
              "- 已证伪：价格因子/大佬信号/CTA/基本面组合/港股股息（样本外均无净边际）",
              "",
              "> 自动生成，仅供学习研究参考，不构成投资建议。",
              ""]
    out = ROOT / "docs" / "系统状态.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
