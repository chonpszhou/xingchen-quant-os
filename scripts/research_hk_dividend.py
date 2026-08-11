#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 港股股息率策略验证

数据：东财港股分红历史（stock_hk_dividend_payout_em，含除净日）；
因子：股息率 = 近 12 个月除净日分红合计（折算港币）/ 收盘价；
回测：截面 top20% 高股息等权，20 日调仓，t+1 执行，成本 0.2%。

用法:
    python3 scripts/research_hk_dividend.py
"""

import re
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
from factors.neutralization import size_proxy  # noqa: E402

DIV_FILE = ROOT / "data" / "hk_dividends.parquet"
FX = {"人民币": 1.08, "港币": 1.0, "港元": 1.0, "美元": 7.8, "澳门元": 0.97, "新加坡元": 5.8}


def parse_amount(text):
    """解析分红方案文本 → 每股港币金额"""
    t = str(text)
    m = re.search(r"每10股(?:派|送)([0-9.]+)", t)
    per_share = float(m.group(1)) / 10 if m else None
    if per_share is None:
        m = re.search(r"每股(?:派|派息|派发|派送)(?:港币|港元|人民币|美元|澳门元|新加坡元)?([0-9.]+)", t)
        per_share = float(m.group(1)) if m else None
    if per_share is None:
        m = re.search(r"(?:派|派息|派发)(?:港币|港元|人民币|美元)?([0-9.]+)(?:港元|港币|人民币|元)", t)
        per_share = float(m.group(1)) if m else None
    if per_share is None:
        return np.nan
    fx = 1.0
    for k, v in FX.items():
        if k in t:
            fx = v
            break
    return per_share * fx


def fetch_dividends(store):
    import akshare as ak
    rows = []
    symbols = sorted(st["symbol"] for _, st in store.all_status().iterrows() if st["market"] == "港股")
    for i, sym in enumerate(symbols, 1):
        try:
            df = ak.stock_hk_dividend_payout_em(symbol=sym)
            if df is None or df.empty:
                continue
            df = df.rename(columns={"除净日": "ex_date", "分红方案": "plan"})
            df["code"] = sym
            df["amount_hkd"] = df["plan"].map(parse_amount)
            rows.append(df[["code", "ex_date", "amount_hkd", "plan"]])
        except Exception as e:  # noqa: BLE001
            print(f"  {sym}: {str(e)[:60]}", file=sys.stderr)
        if i % 20 == 0:
            print(f"  ...{i}/{len(symbols)}", flush=True)
    out = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    if not out.empty:
        out["ex_date"] = pd.to_datetime(out["ex_date"])
        out = out.dropna(subset=["amount_hkd"])
        out.to_parquet(DIV_FILE, index=False)
    return out


def build_yield(store, div):
    close = {}
    for _, st in store.all_status().iterrows():
        if st["market"] != "港股":
            continue
        df = store.load_bars("港股", st["symbol"])
        if df is not None and len(df) > 120:
            close[st["symbol"]] = df.set_index("date")["close"]
    close = pd.DataFrame(close).sort_index()
    # 每股近 12 个月分红（按除净日累计）
    ttm = {}
    div_daily = {}
    for sym in close.columns:
        d = div[div["code"] == sym]
        if d.empty:
            continue
        d = d.groupby("ex_date", as_index=False)["amount_hkd"].sum()
        s = d.set_index("ex_date")["amount_hkd"].sort_index()
        ttm[sym] = s.rolling("365D").sum().reindex(close.index, method="ffill").fillna(0.0)
        # 仅在除净日计入分红（不得 ffill，避免收益前视泄漏）
        dd = s.reindex(close.index).fillna(0.0) / close[sym].shift(1)
        div_daily[sym] = dd.fillna(0.0)
    ttm = pd.DataFrame(ttm)
    yield_ = ttm / close
    # 总回报指数（含分红）：价格收益 + 除净日分红/前收
    tr = close.pct_change().fillna(0.0) + pd.DataFrame(div_daily)
    tr_index = (1 + tr).cumprod()
    return close, yield_, tr_index


def main():
    store = LocalStore(str(ROOT / "data"))
    if DIV_FILE.exists():
        div = pd.read_parquet(DIV_FILE)
        print(f"分红数据（缓存）：{len(div)} 行 / {div['code'].nunique()} 只")
    else:
        print("抓取港股分红...")
        div = fetch_dividends(store)
    if div.empty:
        print("无分红数据")
        return
    close, dy, tr_index = build_yield(store, div)
    print(f"股息率面板：{dy.shape[1]} 只 × {len(dy)} 日，覆盖 "
          f"{(dy[dy > 0].notna()).mean().mean():.0%}（日均正股息）")

    size = size_proxy(close, close.notna().astype(float))
    rows = []
    for name, f in (("div_yield_raw", dy),):
        ev = evaluate(f, tr_index, horizons=(10, 20), min_symbols=10)
        for _, r in ev.iterrows():
            rows.append({"factor": name, **r.to_dict()})
    ic = pd.DataFrame(rows)

    lines = [
        "# 港股股息率策略验证报告",
        "",
        f"> 生成时间：{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}",
        f"> 池：港股 {dy.shape[1]} 只 × {len(dy)} 日；股息率 = 近12月除净日分红(折算港币)/收盘价",
        "> 成本 0.2%；20 日调仓；t+1 执行；门控同基准报告",
        "",
        "## IC 评估",
        "",
        "| 因子 | 前瞻 | 均值IC | ICIR | t | 多空Sharpe | 评级 |",
        "|------|------|--------|------|---|-----------|------|",
    ]
    for _, r in ic.iterrows():
        lines.append(f"| {r['factor']} | {r['horizon']} | {r['mean_ic']} | {r['icir']} | {r['tstat']} | "
                     f"{r['ls_sharpe']} | {r['rating']} |")
    lines += ["", "## walk-forward 组合回测（高股息 top20%，含成本）", ""]
    wf = walk_forward(tr_index, dy, direction=1, top_pct=0.2, cost_rate=0.002, n_trials=25,
                      train_size=504, test_size=126, rebalance_days=20, liquidity=None)
    m, o = wf["full_metrics"], wf["oos_metrics"]
    lines += [f"- 全区间：年化 {m['annual_return']:.2%} | 夏普 {m['sharpe']} | HAC t {m['hac_t']} | "
              f"回撤 {m['max_drawdown']:.2%} | 月胜率 {m['monthly_wr']:.0%} | PF {m['profit_factor']} | DSR {m['dsr']}"]
    if o:
        lines.append(f"- **样本外**：年化 {o['annual_return']:.2%} | 夏普 {o['sharpe']} | HAC t {o['hac_t']} | "
                     f"回撤 {o['max_drawdown']:.2%} | DSR {o['dsr']}")
    lines += [
        "",
        "## 结论",
        "",
        "- 股息率因子在港股是否产生可交易边际：以 IC 与 walk-forward 样本外为准",
        "- 限制：分红金额按文本解析（含汇率折算近似）；池仅 66 只；分红再投资未单独建模",
        "",
        "> 本报告基于公开数据与规则化分析生成，仅供研究参考，不构成任何投资建议。",
        "",
    ]
    (ROOT / "docs" / "港股股息率策略验证报告.md").write_text("\n".join(lines), encoding="utf-8")
    print("已输出：docs/港股股息率策略验证报告.md")
    print(ic.to_string(index=False))


if __name__ == "__main__":
    main()
