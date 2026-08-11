#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 一键运行入口（面向普通用户）

用法:
    python3 scripts/run_all.py update     # 增量更新四市场行情/财务数据
    python3 scripts/run_all.py cb         # 可转债双低监控 + 模拟盘推进
    python3 scripts/run_all.py iv         # 期权 IV 快照（CBOE + 个股链）
    python3 scripts/run_all.py digest     # 生成当日投研摘要（markdown）
    python3 scripts/run_all.py push       # 推送摘要到已配置通道
    python3 scripts/run_all.py monthly    # 模拟盘月度报告
    python3 scripts/run_all.py futures    # 期货数据更新（商品+永续费率）
    python3 scripts/run_all.py status     # 系统健康看板
    python3 scripts/run_all.py momentum   # 双动量模拟盘推进
    python3 scripts/run_all.py rp         # 风险平价模拟盘推进
    python3 scripts/run_all.py validate   # 模拟盘引擎一致性校验
    python3 scripts/run_all.py weekly     # 周报生成
    python3 scripts/run_all.py portfolio  # 组合模拟盘视图
    python3 scripts/run_all.py test       # 模拟盘前向状态机测试（隔离）
    python3 scripts/run_all.py risk       # 风控状态（回撤/超额预警）
    python3 scripts/run_all.py consistency # 回测-模拟一致性监控
    python3 scripts/run_all.py expected  # 模拟盘预期区间（回测分布）
    python3 scripts/run_all.py preview   # 下次调仓预告（当前信号）
    python3 scripts/run_all.py all        # 依序执行全部

所有脚本日志追加到 data/logs/run_YYYYMMDD.log。
"""

import subprocess
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "data" / "logs"


def log(msg):
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_DIR / f"run_{date.today():%Y%m%d}.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run(script, args=()):
    cmd = [sys.executable, str(ROOT / "scripts" / script), *args]
    log(f"运行: {' '.join(cmd)}")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.stdout:
        log(r.stdout.strip()[:1500])
    if r.returncode != 0:
        log(f"⚠ {script} 失败: {r.stderr.strip()[:800]}")
    else:
        log(f"✓ {script} 完成")
    return r.returncode


def digest():
    from datetime import date
    import json

    import pandas as pd

    lines = [
        f"# 星辰投研团 · 投研摘要 {date.today()}",
        "",
    ]
    # 模拟盘
    nav_file = ROOT / "data" / "paper_cb_nav.parquet"
    state_file = ROOT / "data" / "paper_cb_state.json"
    if nav_file.exists() and state_file.exists():
        nav = pd.read_parquet(nav_file)
        st = json.loads(state_file.read_text(encoding="utf-8"))
        last = nav.iloc[-1]
        bench_txt = f" | 基准 {last['bench_nav']:,.0f}（超额 {last['nav'] - last['bench_nav']:+,.0f}）" \
            if "bench_nav" in nav.columns else ""
        lines += ["## 可转债双低模拟盘", "",
                  f"- 净值 {last['nav']:,.0f} | 持仓 {int(last['holdings'])} 只 | 现金 {last['cash']:,.0f} | "
                  f"调仓 {st['rebalance_count']} 次{bench_txt}",
                  f"- 记录起始：{st['start_date']}；最近净值日：{last['date'].date()}",
                  ""]
    # 双低快照
    snap_file = ROOT / "data" / "cb_daily_snapshot.json"
    if snap_file.exists():
        snap = json.loads(snap_file.read_text(encoding="utf-8"))
        lines += ["## 双低 TOP10（当日）", "",
                  "| 名称 | 价格 | 溢价 | 双低值 | 评级 |", "|------|------|------|--------|------|"]
        for r in snap["rank"][:10]:
            lines.append(f"| {r['name']} | {r['price']:.1f} | {r['premium']:.1f}% | {r['score']:.1f} | {r.get('rating','-')} |")
        if snap["alerts"]:
            lines += ["", "### 预警", ""]
            lines += [f"- ⚠ {a}" for a in snap["alerts"]]
        lines.append("")
    # IV
    iv_file = ROOT / "docs" / "期权IV监控快照.md"
    if iv_file.exists():
        lines += ["## 期权 IV（指数级）", ""]
        for line in iv_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("| VIX") or line.startswith("| VXN") or line.startswith("| VXD"):
                lines.append(line)
        lines.append("")
    # 期货
    fund_file = ROOT / "data" / "futures_funding.json"
    if fund_file.exists():
        fund = json.loads(fund_file.read_text(encoding="utf-8"))
        lines += ["## 期货（商品主力 + 加密永续费率）", "",
                  "| 合约 | 最新 | 涨跌 | 永续费率 |", "|------|------|------|----------|"]
        store_path = ROOT / "data" / "bars" / "期货"
        for sym in ("RB0", "AU0", "SC0", "CU0", "I0"):
            p = store_path / f"{sym}.parquet"
            if p.exists():
                b = pd.read_parquet(p)
                last = b.iloc[-1]
                prev = b.iloc[-2] if len(b) > 1 else last
                chg = (last["close"] / prev["close"] - 1) * 100 if prev["close"] else 0
                lines.append(f"| {sym} | {last['close']:.0f} | {chg:+.2f}% | - |")
        for inst, info in fund.get("funding", {}).items():
            lines.append(f"| {inst} | - | - | {info['funding_rate']:.4f}% |")
        lines.append("")
    # 双动量模拟盘
    mom_nav = ROOT / "data" / "paper_mom_nav.parquet"
    if mom_nav.exists():
        mnav = pd.read_parquet(mom_nav)
        ml = mnav.iloc[-1]
        mbench = ml["bench_nav"]
        lines += ["## 双动量模拟盘（SPY/GLD/DBC轮动）", "",
                  f"- 净值 {ml['nav']:,.0f} | SPY基准 {mbench:,.0f}（超额 {ml['nav'] - mbench:+,.0f}）| "
                  f"当前持仓 {ml['holding']} | 净值日 {ml['date'].date()}",
                  ""]
    # 风险平价模拟盘
    rp_nav = ROOT / "data" / "paper_rp_nav.parquet"
    if rp_nav.exists():
        rnav = pd.read_parquet(rp_nav)
        rl = rnav.iloc[-1]
        lines += ["## 风险平价模拟盘（SPY/GLD/TLT/DBC 逆波动率）", "",
                  f"- 净值 {rl['nav']:,.0f} | SPY基准 {rl['bench_nav']:,.0f}（超额 {rl['nav'] - rl['bench_nav']:+,.0f}）| "
                  f"净值日 {rl['date'].date()}",
                  ""]
    # 风控状态
    risk_file = ROOT / "docs" / "风控状态.md"
    if risk_file.exists():
        lines += ["## 风控状态", ""]
        for line in risk_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("| ") and not line.startswith("|------") and not line.startswith("| 账户"):
                lines.append(line)
        lines.append("")
    lines += ["---", "> 自动生成，仅供学习参考，不构成投资建议。", ""]
    out = ROOT / "docs" / f"投研摘要_{date.today():%Y%m%d}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    log(f"✓ 摘要已生成: {out}")


def main():
    step = sys.argv[1] if len(sys.argv) > 1 else "all"
    steps = {
        "update": [("datahub_cli.py", ("update", "--markets", "A股", "港股", "美股", "虚拟货币"))],
        "cb": [("run_cb_double_low.py", ()), ("paper_trade_cb.py", ())],
        "iv": [("options_iv_snapshot.py", ())],
        "digest": [],
        "push": [("push_digest.py", ())],
        "monthly": [("report_monthly.py", ())],
        "futures": [("fetch_futures.py", ())],
        "status": [("system_status.py", ())],
        "momentum": [("paper_trade_momentum.py", ())],
        "rp": [("paper_trade_rp.py", ())],
        "validate": [("validate_paper_engines.py", ())],
        "weekly": [("report_weekly.py", ())],
        "portfolio": [("portfolio_view.py", ())],
        "test": [("test_paper_forward.py", ())],
        "risk": [("risk_monitor.py", ())],
        "consistency": [("monitor_backtest_consistency.py", ())],
        "expected": [("expected_path.py", ())],
        "preview": [("preview_next_rebalance.py", ())],
        "all": [("datahub_cli.py", ("update", "--markets", "A股", "港股", "美股", "虚拟货币")),
                ("run_cb_double_low.py", ()), ("paper_trade_cb.py", ()),
                ("paper_trade_momentum.py", ()), ("paper_trade_rp.py", ()),
                ("options_iv_snapshot.py", ()), ("fetch_futures.py", ()),
                ("risk_monitor.py", ()), ("monitor_backtest_consistency.py", ())],
    }
    if step not in steps:
        print("未知步骤，可选: update / cb / iv / digest / push / monthly / futures / status / momentum / rp / validate / weekly / portfolio / test / risk / consistency / expected / preview / all")
        return 1
    for script, args in steps[step]:
        run(script, args)
    if step in ("all", "digest"):
        digest()
        if step == "all":
            run("push_digest.py")  # 摘要生成后再推送
    log("全部完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
