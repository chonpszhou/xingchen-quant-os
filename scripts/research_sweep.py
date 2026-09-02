#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
研究驱动全宇宙扫描（星辰投研团原生版，吸收 paddy 研究→验证闭环）

等价于 paddy-quant-workbench 的 `quantos.py sweep --research`：
  读 config/research_views.json（研究员/UZI 共识，含量化派生 crypto 观点）
  → long/neutral 入扫、short 研究层否决
  → 逐标的用 engine.optimizer.optimize 跑五道闸门
    （WF+holdout 双闸 + 第四道质量否决 + 第五道 DSR≥0.95 硬卡）
  → 产出 data/experiments/sweep_YYYYMMDD.csv + 控制台摘要

用法:
    python3 scripts/research_sweep.py [--research config/research_views.json] [--limit 800] [--preset balanced]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.data_service import DataService  # noqa: E402
from engine.optimizer import optimize  # noqa: E402
from engine.research_views import from_uzi_json, print_views  # noqa: E402

# 多策略遍历：研究扫描不再只测 sma_cross，而是覆盖已移植进本引擎的「收盘价类」策略。
# 五道闸逻辑不变——每个策略都独立过 WF+holdout 双闸 + 质量否决 + DSR≥0.95，
# 再按 (通过, 样本外夏普) 取每标的的最优策略。这是「用最先进合适方法」的第一步。
# 注意：仅列本引擎 REGISTRY 中真实存在的策略，未移植的（mean_reversal/rsi_reversal/
# ml_reversal 仍在 paddy，未 port）不列入，避免 get_strategy 抛 KeyError 被 try 吞掉、
#  silent 退化成只测 sma_cross。待 port 后在 methodology_proposals.json 标记并加入。
SWEEP_STRATEGIES = ["sma_cross", "momentum", "cs_momentum", "ml_factor", "vol_target_momentum"]
SWEEP_GRIDS = {
    "sma_cross": {"fast": [3, 5, 10], "slow": [20, 30, 60]},
    "momentum": {"window": [20, 60, 120, 250]},
    "cs_momentum": {"lookback": [126, 252], "top_q": [0.3, 0.5]},
    "ml_factor": {},
    "vol_target_momentum": {"window": [126, 252], "target_vol_ann": [0.2, 0.3]},
}
MARKET_MAP = {"a": "A股", "hk": "港股", "us": "美股", "crypto": "虚拟货币"}


def _norm_market(m):
    return MARKET_MAP.get(str(m).lower(), "A股")


def _norm_symbol(mkt: str, sym: str) -> str:
    """本地行情库的代码格式对齐：虚拟货币存为 BTC/USDT，研究文件为 BTCUSDT。"""
    if mkt == "虚拟货币" and "/" not in sym:
        for q in ("USDT", "USD", "USDC"):
            if sym.endswith(q):
                return sym[: -len(q)] + "/" + q
    return sym


def run(research_path: str, limit: int, preset: str, learning_path: str | None = None,
        strategies: list | None = None) -> pd.DataFrame:
    ds = DataService(ROOT / "data")
    views = from_uzi_json(research_path)
    if learning_path:
        try:
            lviews = from_uzi_json(learning_path)
            views = views + lviews
            print(f"\n  🔗 已并入学习派生观点 {len(lviews)} 条（--learning {learning_path}）")
        except Exception as e:
            print(f"\n  ⚠️ 学习观点合并失败，跳过：{e}")
    print("\n" + print_views(views))

    jobs, vetoed = [], []
    for v in views:
        if v.direction == "short":
            vetoed.append(v)
            continue
        mkt = _norm_market(v.market)
        sym = _norm_symbol(mkt, v.symbol)
        bars = ds.bars(mkt, sym)
        if bars is None or "close" not in bars.columns or len(bars) < 60:
            print(f"  ⚠️ 跳过 {v.symbol}({mkt})：行情不足或缺失")
            continue
        # 关键：列名必须是标的代码（引擎按 symbol 给价格成交），不能叫 "close"
        close = bars.set_index("date")["close"].sort_index().tail(limit).rename(sym).to_frame()
        jobs.append((v, mkt, sym, close))
        print(f"  ➕ 研究驱动入扫: {v.symbol}({mkt}) 方向={v.direction} 预设={preset}")

    strts = strategies or SWEEP_STRATEGIES
    rows = []
    for v, mkt, sym, close in jobs:
        best_rec = None
        best_key = (-1, -1e9)          # (PASS_rank, holdout_sharpe)
        tried = []
        for st in strts:
            grid = SWEEP_GRIDS.get(st, {})
            try:
                df = optimize(
                    st, grid, close, ds,
                    cost=0.002, verbose=False,
                    strategy_params={"symbol": sym, "market": mkt},
                )
            except Exception as e:
                print(f"  ⚠️ {sym} 策略 {st} 跳过: {e}")
                continue
            if df is None or len(df) == 0 or "PASS" not in df.columns:
                continue
            r = df.iloc[0]
            tried.append(st)
            hs = r.get("holdout_sharpe", float("nan"))
            hs = float(hs) if pd.notna(hs) else -1e9
            key = (1 if bool(r["PASS"]) else 0, hs)
            if key > best_key:
                best_key = key
                best_rec = (st, r)
        if best_rec is None:
            rows.append({
                "symbol": v.symbol, "market": mkt, "preset": preset,
                "strategy": "(无可用)", "direction": v.direction, "consensus": round(v.consensus, 1),
                "total_return": None, "sharpe": None, "max_dd": None, "wf_oos_sharpe": None,
                "dsr": None, "dsr_gate": None, "quality_veto": None, "PASS": False,
                "verdict": "❌ 暂不采用", "tried": ",".join(tried) or "—",
            })
            print(f"  {v.symbol:<10} {mkt:<8} 无策略通过（试过 {tried}）")
            continue
        st, r = best_rec
        passed = bool(r["PASS"])
        rows.append({
            "symbol": v.symbol, "market": mkt, "preset": preset,
            "strategy": st, "direction": v.direction,
            "consensus": round(v.consensus, 1),
            # 汇报全样本绩效（诚实口径，避免只看最后 30% 保留集虚高）；保留集单独列出对照
            "total_return": round(r["full_ann"], 4) if pd.notna(r.get("full_ann")) else None,
            "sharpe": round(r["full_sharpe"], 3) if pd.notna(r.get("full_sharpe")) else None,
            "max_dd": round(r["full_maxdd"], 4) if pd.notna(r.get("full_maxdd")) else None,
            "holdout_sharpe": round(r["holdout_sharpe"], 3) if pd.notna(r.get("holdout_sharpe")) else None,
            "holdout_ann": round(r["holdout_ann"], 4) if pd.notna(r.get("holdout_ann")) else None,
            "holdout_maxdd": round(r["holdout_maxdd"], 4) if pd.notna(r.get("holdout_maxdd")) else None,
            "wf_oos_sharpe": round(r["wf_oos_sharpe"], 3) if pd.notna(r.get("wf_oos_sharpe")) else None,
            "dsr": round(r["dsr"], 3) if pd.notna(r.get("dsr")) else None,
            "dsr_gate": bool(r["dsr_gate"]) if "dsr_gate" in r else None,
            "quality_veto": bool(r["quality_veto"]) if "quality_veto" in r else None,
            "PASS": passed,
            "verdict": "✅ 通过五道闸" if passed else "❌ 暂不采用",
            "tried": ",".join(tried),
        })
        print(f"  {v.symbol:<10} {mkt:<8} 最优策略={st} PASS={passed} "
              f"dsr={rows[-1]['dsr']} sharpe={rows[-1]['sharpe']} mdd={rows[-1]['max_dd']}")

    out_df = pd.DataFrame(rows)
    out = ROOT / "data" / "experiments" / f"sweep_{pd.Timestamp.now():%Y%m%d}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n  📁 已保存: {out}")

    if vetoed:
        print("  🛡️ 研究层否决（看空，未入扫）:")
        for v in vetoed:
            print(f"     - {v.symbol} {v.name} 共识={v.consensus:.0f} "
                  f"多/中/空={v.bullish}/{v.neutral}/{v.bearish}")

    # M-042 多 alpha 组合层：把通过五道闸的标的按风险平价（1/波动）日频再平衡组合
    _portfolio_layer(views, ds)
    return out_df


def _portfolio_layer(views, ds, limit: int = 800):
    """（M-042）组合层分析：对入扫标的构建风险平价组合，独立于单标的五道闸。
    仅作配置层参考，不替代逐标的否决；组合本身也汇报年度化收益/夏普/回撤。"""
    import numpy as np
    cols = {}
    for v in views:
        if v.direction == "short":
            continue
        mkt = _norm_market(v.market)
        sym = _norm_symbol(mkt, v.symbol)
        bars = ds.bars(mkt, sym)
        if bars is not None and "close" in bars.columns and len(bars) >= 60:
            cols[sym] = bars.set_index("date")["close"].sort_index().tail(limit)
    if not cols:
        return
    panel = pd.DataFrame(cols).sort_index().pct_change().dropna()
    if panel.empty or panel.shape[1] < 2:
        print("\n  🧩 组合层：入扫标的不足 2 个，跳过风险平价组合")
        return
    vol = panel.rolling(21).std() * np.sqrt(252)
    w = (1.0 / vol.replace(0, np.nan))
    w = w.div(w.sum(axis=1), axis=0)
    pret = (panel * w.shift(1).fillna(0.0)).sum(axis=1)
    nav = (1.0 + pret).cumprod()
    ann = nav.iloc[-1] ** (252.0 / len(nav)) - 1.0 if len(nav) > 1 else 0.0
    sharpe = pret.mean() / pret.std() * np.sqrt(252) if pret.std() > 0 else 0.0
    mdd = float((nav / nav.cummax() - 1.0).min())
    print(f"\n  🧩 组合层（M-042 风险平价，{panel.shape[1]} 标的日频再平衡）："
          f"年化={ann:.2%} 夏普={sharpe:.2f} 最大回撤={mdd:.2%}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--research", default=str(ROOT / "config" / "research_views.json"))
    p.add_argument("--learning", default=None,
                   help="学习派生观点文件（learning_to_research.py 产出），并入扫描")
    p.add_argument("--strategies", default=None,
                   help="逗号分隔的策略列表（覆盖默认多策略集）；如 sma_cross,momentum,cs_momentum,ml_factor,vol_target_momentum")
    p.add_argument("--limit", type=int, default=800)
    p.add_argument("--preset", default="balanced")
    a = p.parse_args()
    strs = a.strategies.split(",") if a.strategies else None
    run(a.research, a.limit, a.preset, a.learning, strs)


if __name__ == "__main__":
    main()
