#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 数据质量对账

用法:
    python3 scripts/datahub_quality.py

输出:
    data/quality_summary.csv   逐标的质量指标
    docs/数据质量报告.md        带问题分级的质量报告
"""

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from datahub.calendar import trading_days  # noqa: E402
from datahub.store import LocalStore  # noqa: E402


def grade(row):
    if row["bars"] == 0 or row["dup_dates"] > 0 or row["nan"] > 0 or row["coverage"] < 70:
        return "问题"
    if row["big_moves_30pct"] > 0 or row["coverage"] < 90 or row["missing_days"] > 30:
        return "关注"
    return "正常"


def main():
    store = LocalStore(str(ROOT / "data"))
    status = store.all_status()
    rows = []
    for _, st in status.iterrows():
        market, symbol = st["market"], st["symbol"]
        df = store.load_bars(market, symbol)
        base = {"market": market, "symbol": symbol, "source": st.get("source", "")}
        if df is None or df.empty:
            rows.append({**base, "bars": 0, "first": "", "last": "", "expected": 0,
                         "coverage": 0.0, "missing_days": 0, "dup_dates": 0,
                         "nan": 0, "zero_px": 0, "big_moves_30pct": 0, "biggest": "", "sample_missing": ""})
            continue
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"]).dt.normalize()
        first, last = df["date"].min(), df["date"].max()
        exp = set(pd.to_datetime(trading_days(market, first.date(), last.date())).normalize())
        act = set(df["date"])
        missing = sorted(exp - act)
        pct = df["close"].pct_change()
        big = pct.abs() > 0.3
        biggest = ""
        if big.any():
            idx = pct.abs().idxmax()
            biggest = f"{df.loc[idx, 'date'].date()} {pct.loc[idx]:+.1%}"
        rows.append({
            **base,
            "bars": len(df), "first": str(first.date()), "last": str(last.date()),
            "expected": len(exp),
            "coverage": round(len(act & exp) / max(len(exp), 1) * 100, 1),
            "missing_days": len(missing),
            "dup_dates": int(df["date"].duplicated().sum()),
            "nan": int(df[["open", "high", "low", "close", "volume"]].isna().sum().sum()),
            "zero_px": int((df[["open", "high", "low", "close"]] == 0).sum().sum()),
            "big_moves_30pct": int(big.sum()),
            "biggest": biggest,
            "sample_missing": " ".join(str(d.date()) for d in missing[:3]),
        })
    out = pd.DataFrame(rows)
    out["grade"] = out.apply(grade, axis=1)
    out.to_csv(ROOT / "data" / "quality_summary.csv", index=False, encoding="utf-8-sig")
    write_report(out)


def write_report(out):
    counts = out["grade"].value_counts().to_dict()
    lines = [
        "# 星辰投研团 · 数据质量报告",
        "",
        f"> 生成时间：{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}",
        f"> 检查范围：{len(out)} 个标的多市场日线（本地 parquet）",
        "",
        "## 汇总",
        "",
        f"- 正常：{counts.get('正常', 0)}",
        f"- 关注：{counts.get('关注', 0)}",
        f"- 问题：{counts.get('问题', 0)}",
        "",
        "质量分级说明：",
        "- **问题**：无数据 / 日期重复 / 含 NaN / 覆盖率 <70%",
        "- **关注**：单日涨跌超 ±30%（疑似复权/数据异常）/ 覆盖率 <90% / 缺失天数较多",
        "- 覆盖率按工作日近似计算，**未扣除法定节假日**（A股春节/国庆、美股感恩节等），故正常标的覆盖率约 95% 属预期",
        "",
        "## 按板块汇总",
        "",
        "| 板块 | 标的数 | 平均K线数 | 平均覆盖率 | 问题数 |",
        "|------|--------|-----------|-----------|--------|",
    ]
    for market, g in out.groupby("market"):
        lines.append(f"| {market} | {len(g)} | {int(g['bars'].mean())} | {g['coverage'].mean():.1f}% | {(g['grade'] == '问题').sum()} |")
    lines += ["", "## 问题清单", ""]
    problems = out[out["grade"] != "正常"]
    if problems.empty:
        lines.append("无")
    else:
        lines.append("| 板块 | 代码 | 评级 | K线数 | 覆盖率 | 重复 | NaN | ±30%异常 | 说明 |")
        lines.append("|------|------|------|-------|--------|------|-----|----------|------|")
        for _, r in problems.iterrows():
            note = r["biggest"] or (f"缺失示例: {r['sample_missing']}" if r["missing_days"] else "")
            lines.append(f"| {r['market']} | {r['symbol']} | {r['grade']} | {r['bars']} | {r['coverage']}% | "
                         f"{r['dup_dates']} | {r['nan']} | {r['big_moves_30pct']} | {note} |")
    lines += [
        "",
        "## 说明",
        "",
        "- 指数类标的（000300 沪深300、000852 中证1000）当前股票日线通道无法获取，待接入指数行情接口",
        "- 加密市场 7x24 交易，覆盖率按自然日计算",
        "- 单日 ±30% 波动多为除权/复权或极端行情，需人工抽查确认",
        "",
    ]
    (ROOT / "docs" / "数据质量报告.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
