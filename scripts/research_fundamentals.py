#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · A股基本面因子验证（价值 / 质量）

数据：BaoStock 季度盈利指标（roeAvg / epsTTM / npMargin + pubDate 披露日），
无未来函数对齐：因子仅在披露日（pubDate）之后可用。
因子：
  - value_pe   价值：-log(pe_ttm)，pe_ttm = 收盘价 / epsTTM（仅 eps>0）
  - quality_roe 质量：roeAvg（ROE 平均）
  - composite  价值 + 质量等权 zscore

用法:
    python3 scripts/research_fundamentals.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from datahub.store import LocalStore  # noqa: E402
from factors.backtest import walk_forward  # noqa: E402
from factors.evaluate import evaluate  # noqa: E402
from factors.neutralization import load_a_industry, neutralize, size_proxy  # noqa: E402
from research_run import COSTS, MIN_SYMBOLS, is_stock  # noqa: E402

MIN_BARS = 120


def load_panel(store):
    """返回 {code: (close Series, fundamentals DataFrame)}"""
    fund = pd.read_parquet(ROOT / "data" / "a_fundamentals.parquet")
    fund["pubDate"] = pd.to_datetime(fund["pubDate"])
    fund = fund.sort_values(["code", "pubDate"])
    panel = {}
    for _, st in store.all_status().iterrows():
        if st["market"] != "A股" or not is_stock(st["symbol"]):
            continue
        df = store.load_bars("A股", st["symbol"])
        if df is None or len(df) < MIN_BARS:
            continue
        f = fund[fund["code"] == st["symbol"]]
        panel[st["symbol"]] = (df.set_index("date")["close"], f)
    return panel


def daily_factors(panel, trade_dates):
    """逐日点对时因子：每个交易日取 '披露日 <= 当日' 的最新季度"""
    value, quality = {}, {}
    td = np.array(trade_dates, dtype="datetime64[ns]")
    for code, (close, f) in panel.items():
        if f.empty:
            continue
        v = pd.Series(np.nan, index=trade_dates)
        q = pd.Series(np.nan, index=trade_dates)
        pub = f["pubDate"].values.astype("datetime64[ns]")
        idx = np.searchsorted(pub, td, side="right") - 1
        valid = idx >= 0
        if not valid.any():
            continue
        eps = pd.to_numeric(f["epsTTM"], errors="coerce").values
        roe = pd.to_numeric(f["roeAvg"], errors="coerce").values
        days = trade_dates[valid]
        rows = idx[valid]
        c = close.reindex(days).values
        e = eps[rows]
        good_e = pd.notna(e) & (e > 0)
        pe = c[good_e] / e[good_e]
        good = pe > 0
        vv = -np.log(pe)
        v.loc[days[good_e][good]] = vv[good]
        q.loc[days[pd.notna(roe[rows])]] = roe[rows][pd.notna(roe[rows])]
        value[code] = v
        quality[code] = q
    value = pd.DataFrame(value).sort_index()
    quality = pd.DataFrame(quality).sort_index()
    return value, quality


def main():
    store = LocalStore(str(ROOT / "data"))
    fund_p = ROOT / "data" / "a_fundamentals.parquet"
    if not fund_p.exists():
        print("缺少 data/a_fundamentals.parquet，请先运行 fetch_a_fundamentals.py")
        return

    print("加载基本面面板...")
    panel = load_panel(store)
    all_dates = sorted({d for _, (c, _) in panel.items() for d in c.index})
    trade_dates = pd.DatetimeIndex(all_dates)
    value, quality = daily_factors(panel, trade_dates)
    print(f"面板：{value.shape[1]} 只 × {len(value)} 日；value 覆盖率 "
          f"{(value.notna().mean().mean()):.0%}，quality {quality.notna().mean().mean():.0%}")

    close = value.copy() * np.nan
    for code, (c, _) in panel.items():
        if code in close.columns:
            close[code] = c.reindex(trade_dates)
    industry = load_a_industry(str(ROOT / "data"))

    # 真实规模代理（量×价）
    vols = {}
    for _, st in store.all_status().iterrows():
        if st["market"] == "A股" and st["symbol"] in close.columns:
            df = store.load_bars("A股", st["symbol"])
            if df is not None:
                vols[st["symbol"]] = df.set_index("date")["volume"]
    volume = pd.DataFrame(vols).reindex(trade_dates).sort_index()
    size = size_proxy(close, volume)

    factors = {"value_pe": value, "quality_roe": quality}
    # 复合因子：逐日截面排名（0-1）等权求和，NaN 传播（避免全样本 z 分前视与缺失填0偏差）
    rank_v = value.rank(axis=1, pct=True)
    rank_q = quality.rank(axis=1, pct=True)
    factors["composite"] = rank_v + rank_q

    lines = [
        "# A股基本面因子验证报告（价值 / 质量）",
        "",
        f"> 生成时间：{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}",
        "> 数据：BaoStock 季度盈利指标，披露日（pubDate）对齐，无未来函数；覆盖 "
        f"{value.shape[1]} 只 × {len(value)} 交易日",
        "> 因子：value_pe=-log(pe_ttm)（收盘/epsTTM）、quality_roe=roeAvg、composite=等权zscore",
        "> 中性化：行业去均值 + log(20日均成交额) 回归残差；门控同基准报告",
        "",
    ]

    for name, f in factors.items():
        f_neu = neutralize(f, size, industry)
        raw = evaluate(f, close, horizons=(10, 20), min_symbols=MIN_SYMBOLS["A股"])
        neu = evaluate(f_neu, close, horizons=(10, 20), min_symbols=MIN_SYMBOLS["A股"])
        lines += [f"## {name}", "",
                  "| 前瞻 | 原始IC | 原始ICIR | 原始评级 | 中性IC | 中性ICIR | 中性评级 |",
                  "|------|--------|----------|----------|--------|----------|----------|"]
        for h in (10, 20):
            rw = raw[raw["horizon"] == h]
            rn = neu[neu["horizon"] == h]
            if len(rw) and len(rn):
                lines.append(f"| {h} | {rw.iloc[0]['mean_ic']} | {rw.iloc[0]['icir']} | {rw.iloc[0]['rating']} | "
                             f"{rn.iloc[0]['mean_ic']} | {rn.iloc[0]['icir']} | {rn.iloc[0]['rating']} |")
        lines.append("")

    # walk-forward：composite 与 value_pe（中性化后）
    lines += ["## walk-forward 组合回测（A股，含成本）", ""]
    for name in ("composite", "value_pe"):
        f = neutralize(factors[name], size, industry)
        wf = walk_forward(close, f, direction=1, top_pct=0.2, cost_rate=COSTS["A股"],
                          n_trials=25, train_size=252, test_size=63, rebalance_days=20,
                          liquidity=size, liquidity_floor_pct=0.1, limit_up_filter=True)
        m, o = wf["full_metrics"], wf["oos_metrics"]
        lines += [f"### {name}（direction=1）", "",
                  f"- 全区间：年化 {m['annual_return']:.2%} | 夏普 {m['sharpe']} | HAC t {m['hac_t']} | "
                  f"回撤 {m['max_drawdown']:.2%} | 月胜率 {m['monthly_wr']:.0%} | PF {m['profit_factor']} | DSR {m['dsr']}"]
        if o:
            lines.append(f"- **样本外**：年化 {o['annual_return']:.2%} | 夏普 {o['sharpe']} | HAC t {o['hac_t']} | "
                         f"回撤 {o['max_drawdown']:.2%} | DSR {o['dsr']}")
        lines.append("")

    lines += [
        "## 结论",
        "",
        "- 价值/质量/复合因子的 IC 与样本外表现决定基本面方向是否值得继续",
        "- 若 DSR≈0，则价格类与基本面类单因子在当前池/频率下均无净边际，需转向组合层（多因子+择时）或另选数据（一致预期/分析师修正）",
        "",
        "> 本报告基于公开数据与规则化分析生成，仅供研究参考，不构成任何投资建议。",
        "",
    ]
    (ROOT / "docs" / "基本面因子验证报告.md").write_text("\n".join(lines), encoding="utf-8")
    print("已输出：docs/基本面因子验证报告.md")
    print(lines[lines.index("## composite"):lines.index("## composite") + 8])


if __name__ == "__main__":
    main()
