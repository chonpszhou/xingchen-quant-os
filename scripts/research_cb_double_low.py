#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · A股可转债双低策略回测

规则（经典散户实证版本）：
  - 标的池：可转债全市场（当前清单，含上市后全部历史）
  - 筛选：价格 ≤ 130 且 转股溢价率 ≤ 50%，且上市满 20 个交易日
  - 打分：双低值 = 价格 + 转股溢价率（百分点），升序取前 N 只等权
  - 调仓：每月（20 交易日）t+1 执行；成本 0.1%/边
基准：全债等权（同筛选条件）月度再平衡

注意：清单不含 2026 年前已退市/到期转债，缺失“强赎兑现”样本，结果偏保守。

用法:
    python3 scripts/research_cb_double_low.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from factors.backtest import metrics  # noqa: E402

COST = 0.001
PRICE_CAP = 130.0
PREMIUM_CAP = 50.0
N_HOLD = 20
MIN_LISTED_DAYS = 20
MIN_ELIGIBLE = 30  # 合格标的不足时不开仓（早年样本太少）
REBALANCE = 20
CREDIT_FILTER = True  # 信用过滤：剔除 ST 正股 / C级及以下评级


def load_panel():
    df = pd.read_parquet(ROOT / "data" / "cb_panel.parquet")
    df["date"] = pd.to_datetime(df["date"])
    for c in ("close", "premium_pct", "conv_value"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    # 仅保留标准可转债代码段（排除定向/定转 404/810/820 等异常品种）
    df = df[df["bond"].str.startswith(("110", "111", "113", "118", "123", "127", "128"))]
    return df


def load_meta():
    meta = pd.read_parquet(ROOT / "data" / "cb_meta.parquet")
    meta["code"] = meta["code"].astype(str).str.zfill(6)
    meta["rating"] = meta["rating"].astype(str)
    bad_st = meta["stock_name"].astype(str).str.contains("ST")
    bad_rating = meta["rating"].str.startswith("C") | (meta["rating"] == "nan")
    meta["credit_ok"] = ~(bad_st | bad_rating)
    return meta.set_index("code")["credit_ok"]


def main():
    df = load_panel()
    if df.empty:
        print("缺少 data/cb_panel.parquet，先运行 fetch_cb_panel.py")
        return
    df = df.sort_values(["bond", "date"])
    # cumcount 在该 pandas/numpy 组合下有广播 bug，改用组内排名
    df["listed_days"] = df.groupby("bond")["date"].rank(method="first").astype(int) - 1
    df = df[df["close"].notna()]
    # 数据异常剔除：单日 |收益| > 50% 视为价格错误，整只剔除
    bad = df.sort_values(["bond", "date"]).groupby("bond")["close"].pct_change().abs() > 0.5
    bad_bonds = set(df.loc[bad, "bond"]) if bad.any() else set()
    if bad_bonds:
        print(f"剔除异常价格债券 {len(bad_bonds)} 只（单日收益>50%）", file=sys.stderr)
        df = df[~df["bond"].isin(bad_bonds)]

    # 宽表：numpy 直接索引构建（规避本环境 pandas 大表 pivot 重复索引 bug）
    uniq_dates = pd.DatetimeIndex(sorted(df["date"].unique()))
    uniq_bonds = sorted(df["bond"].unique())
    di_map = {d: i for i, d in enumerate(uniq_dates)}
    ci_map = {b: j for j, b in enumerate(uniq_bonds)}
    di = np.array([di_map[d] for d in df["date"]])
    ci = np.array([ci_map[b] for b in df["bond"]])
    arr = lambda: np.full((len(uniq_dates), len(uniq_bonds)), np.nan)  # noqa: E731
    close_a, prem_a, list_a = arr(), arr(), arr()
    close_a[di, ci] = df["close"].values
    prem_a[di, ci] = df["premium_pct"].values
    list_a[di, ci] = df["listed_days"].values
    close = pd.DataFrame(close_a, index=uniq_dates, columns=uniq_bonds)
    premium = pd.DataFrame(prem_a, index=uniq_dates, columns=uniq_bonds)
    listed = pd.DataFrame(list_a, index=uniq_dates, columns=uniq_bonds)
    score = close + premium

    credit_ok = load_meta() if CREDIT_FILTER else None
    if credit_ok is not None:
        # 元数据缺失（如已退市券）默认保留，只剔除明确为 ST/低评级的
        ok_bonds = credit_ok.reindex(score.columns).fillna(True)
        n_drop = int((~ok_bonds).sum())
        print(f"信用过滤：剔除 {n_drop} 只（ST 正股 / C级及以下 / 无评级）", file=sys.stderr)
        close = close.loc[:, ok_bonds]
        premium = premium.loc[:, ok_bonds]
        listed = listed.loc[:, ok_bonds]
        score = score.loc[:, ok_bonds]

    ret = close.pct_change()
    dates = close.index
    weights = pd.DataFrame(np.nan, index=dates, columns=close.columns)
    bench_w = pd.DataFrame(np.nan, index=dates, columns=close.columns)

    active = False
    for i, d in enumerate(dates):
        if i % REBALANCE != 0:
            continue
        elig = (close.loc[d] <= PRICE_CAP) & (premium.loc[d] <= PREMIUM_CAP) \
            & (listed.loc[d] >= MIN_LISTED_DAYS)
        s = score.loc[d].where(elig).dropna()
        if len(s) < MIN_ELIGIBLE:
            continue
        if not active:
            print(f"开仓起点：{d.date()}（合格 {len(s)} 只）", file=sys.stderr)
            active = True
        if len(s) < N_HOLD:
            continue
        top = s.nsmallest(N_HOLD)
        weights.loc[d] = 0.0  # 先清空旧仓位，避免 ffill 累积
        weights.loc[d, top.index] = 1.0 / N_HOLD
        e = s.index
        bench_w.loc[d] = 0.0
        bench_w.loc[d, e] = 1.0 / len(e)

    def run(w):
        exec_w = w.ffill().shift(1).fillna(0.0)
        gross = (exec_w * ret.fillna(0.0)).sum(axis=1)
        turnover = exec_w.diff().abs().fillna(exec_w.abs()).sum(axis=1)
        net = gross - turnover * COST
        return (1 + net).cumprod()

    # 参数敏感性：持仓数 × 溢价上限
    variants = []
    for n_hold in (15, 20, 30):
        for prem_cap in (30.0, 50.0):
            w_v = pd.DataFrame(np.nan, index=dates, columns=close.columns)
            active_v = False
            for i, d in enumerate(dates):
                if i % REBALANCE != 0:
                    continue
                elig = (close.loc[d] <= PRICE_CAP) & (premium.loc[d] <= prem_cap) \
                    & (listed.loc[d] >= MIN_LISTED_DAYS)
                s = score.loc[d].where(elig).dropna()
                if len(s) < MIN_ELIGIBLE:
                    continue
                if len(s) < n_hold:
                    continue
                top = s.nsmallest(n_hold)
                w_v.loc[d] = 0.0
                w_v.loc[d, top.index] = 1.0 / n_hold
            nav_v = run(w_v)
            nav_v = nav_v[nav_v.index >= w_v.dropna(how="all").index.min()]
            m = metrics(nav_v, 0.0, n_trials=6)
            variants.append((f"N={n_hold}/溢价≤{prem_cap:.0f}", m))

    nav_dl = run(weights)
    nav_bm = run(bench_w)
    # 净值起点对齐到首个开仓日之后
    nav_dl = nav_dl[nav_dl.index >= weights.dropna(how="all").index.min()]
    nav_bm = nav_bm[nav_bm.index >= weights.dropna(how="all").index.min()]
    m_dl = metrics(nav_dl, 0.0, n_trials=6)
    m_bm = metrics(nav_bm, 0.0, n_trials=6)
    mid = len(nav_dl) // 2
    h1, h2 = metrics(nav_dl.iloc[:mid], 0.0)["sharpe"], metrics(nav_dl.iloc[mid:], 0.0)["sharpe"]

    yearly = pd.DataFrame({
        "双低": nav_dl.resample("YE").last().pct_change().fillna(nav_dl.resample("YE").last().iloc[0] - 1),
        "全债等权": nav_bm.resample("YE").last().pct_change().fillna(nav_bm.resample("YE").last().iloc[0] - 1),
    })

    lines = [
        "# A股可转债双低策略回测报告",
        "",
        f"> 生成时间：{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}",
        f"> 池：{close.shape[1]} 只转债 × {len(close)} 交易日（当前清单含历史，缺 2026 前退市样本 → 结果偏保守）",
        f"> 规则：价格≤{PRICE_CAP:.0f} 且溢价≤{PREMIUM_CAP:.0f}%，上市满 {MIN_LISTED_DAYS} 日；双低=价格+溢价百分点，取前 {N_HOLD} 只等权",
        f"> 调仓：每 {REBALANCE} 交易日 t+1 执行；成本 {COST:.1%}/边；基准=全债等权同条件",
        "",
        "## 全区间指标（含成本）",
        "",
        "| 策略 | 年化 | 夏普 | HAC t | 最大回撤 | 月胜率 | PF | DSR |",
        "|------|------|------|-------|----------|--------|-----|-----|",
        f"| 双低前{N_HOLD} | {m_dl['annual_return']:.2%} | {m_dl['sharpe']} | {m_dl['hac_t']} | "
        f"{m_dl['max_drawdown']:.2%} | {m_dl['monthly_wr']:.0%} | {m_dl['profit_factor']} | {m_dl['dsr']} |",
        f"| 全债等权 | {m_bm['annual_return']:.2%} | {m_bm['sharpe']} | {m_bm['hac_t']} | "
        f"{m_bm['max_drawdown']:.2%} | {m_bm['monthly_wr']:.0%} | {m_bm['profit_factor']} | {m_bm['dsr']} |",
        "",
        f"半程稳定性：前半夏普 {h1:.2f} / 后半夏普 {h2:.2f}",
        "",
        "## 参数敏感性（全区间，含成本）",
        "",
        "| 变体 | 年化 | 夏普 | HAC t | 最大回撤 | 月胜率 | PF | DSR |",
        "|------|------|------|-------|----------|--------|-----|-----|",
    ]
    for label, m in variants:
        lines.append(f"| {label} | {m['annual_return']:.2%} | {m['sharpe']} | {m['hac_t']} | "
                     f"{m['max_drawdown']:.2%} | {m['monthly_wr']:.0%} | {m['profit_factor']} | {m['dsr']} |")
    lines += [
        "",
        "## 年度收益",
        "",
        "| 年份 | 双低 | 全债等权 | 超额 |",
        "|------|------|----------|------|",
    ]
    for y, r in yearly.iterrows():
        lines.append(f"| {y.year} | {r['双低']:.2%} | {r['全债等权']:.2%} | {r['双低'] - r['全债等权']:+.2%} |")
    lines += [
        "",
        "## 结论",
        "",
        "- 门控：年化 ≥ 8% / 夏普 ≥ 1 / 回撤 ≥ -15% / 月胜率 ≥ 55% / PF ≥ 1.3 / 前后半程方向一致",
        "- 若通过：双低策略作为系统首个实盘候选（低门槛、T+0、无印花税、散户实证充分）；若不通过：标注限制后降级为观察",
        "",
        "> 本报告基于公开数据与规则化分析生成，仅供研究参考，不构成任何投资建议。",
        "",
    ]
    (ROOT / "docs" / "可转债双低策略回测报告.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:30]))


if __name__ == "__main__":
    main()
