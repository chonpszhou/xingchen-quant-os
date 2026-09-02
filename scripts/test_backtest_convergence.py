#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 0 回归测试：同一 vol_target_momentum 权重 → paddy 与星辰回测引擎 NAV 必须一致。

真值锚点：scripts/paper_trade_aapl.py::backfill 对 AAPL 全历史用 t+1 应用权重（无成本）
得到 全期 +70.9% / 年化夏普 0.69 / 最大回撤 -36.5%（对齐工作记录中的「真值」）。

本测试覆盖 Phase 0 三个正确性修复的收敛性：
  1) paddy backtest 成本模型改为按 |Δw| 比例计费（不再二值化扣全额）
  2) xingchen factors.backtest.portfolio_backtest 成本去掉 /2 折半，与 paddy 同口径
  3) xingchen factors.backtest.metrics 夏普用 per-period·√252、DSR 用 per-period+普通峰度
     （与 paddy significance.py 一致）

断言：
  A) 成本-free：两引擎 NAV 逐点 == 真值（容差 1e-9），且真值≈+70.9%/0.69/-36.5%
  B) 有成本(comm=0.001)：两引擎 NAV 逐点一致（容差 1e-9），且都低于成本-free 真值
  C) paddy walk_forward 样本外夏普有限且 <2（不再出现 WF-OOS≈4.59 的几何放大伪值）

用法:
    python3 scripts/test_backtest_convergence.py
退出码非 0 表示回归失败。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 直接按文件路径加载 factors/backtest.py，避免触发 factors/__init__ 拉起
# datahub/requests 等整包依赖（本测试只需该模块内的 portfolio_backtest/metrics）。
import importlib.util as _ilu

_spec = _ilu.spec_from_file_location("xingchen_factors_backtest", ROOT / "factors" / "backtest.py")
_xfb = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_xfb)
portfolio_backtest = _xfb.portfolio_backtest

PADDY = Path("/Users/zhoupeng/WorkBuddy/量化交易/paddy-quant-workbench")
sys.path.insert(0, str(PADDY))
from src.engine.backtest import Backtester as PaddyBacktester  # noqa: E402

SYM, MARKET = "AAPL", "美股"
BAR = ROOT / "data" / "bars" / MARKET / f"{SYM}.parquet"
WINDOW, SKIP, DECAY, TVOL = 252, 21, 0.05, 0.25
COST = 0.001

# 真值锚点（来自对齐工作记录）
TRUTH_TOTAL = 0.709
TRUTH_SHARPE = 0.69
TRUTH_MDD = -0.365


def target_series(close: pd.Series) -> pd.Series:
    """复现 paper_trade_aapl.target_series：因果 12-1 月动量 + 波动目标仓位。"""
    logret = np.log(close / close.shift(1)).fillna(0.0).to_numpy()
    n = len(logret)
    w = np.exp(-DECAY * np.arange(WINDOW - 1, -1, -1))
    w = w / w.sum()
    shifted = np.zeros(n)
    shifted[SKIP:] = logret[: n - SKIP]
    sig = np.convolve(shifted, w[::-1], mode="full")[:n]
    sig_s = pd.Series(sig, index=close.index)
    vol = close.pct_change().rolling(SKIP).std() * np.sqrt(252)
    out = {}
    for dt in close.index:
        s = float(sig_s.get(dt, 0.0))
        v = vol.get(dt)
        out[dt] = float(min(1.0, TVOL / float(v))) if (s > 0 and pd.notna(v) and v > 0) else 0.0
    return pd.Series(out, index=close.index)


def _norm(nav: pd.Series) -> pd.Series:
    return nav / nav.iloc[0]


def main() -> int:
    df = pd.read_parquet(BAR).sort_values("date").set_index("date")["close"].astype(float)
    print(f"[data] AAPL 行情 {df.index[0].date()}..{df.index[-1].date()}  共 {len(df)} 行")

    w = target_series(df)
    ret = df.pct_change().fillna(0.0)

    # —— 真值（成本-free，t+1），与 paper_trade_aapl.backfill 同式 ——
    nav_cf = (1.0 + (w.shift(1).fillna(0.0) * ret)).cumprod()
    total_cf = float(nav_cf.iloc[-1] - 1.0)
    r_cf = nav_cf.pct_change().dropna()
    sharpe_cf = float(r_cf.mean() / r_cf.std() * np.sqrt(252))
    mdd_cf = float((nav_cf / nav_cf.cummax() - 1.0).min())
    print(f"[truth] 成本-free: total={total_cf:+.4f} sharpe={sharpe_cf:.3f} mdd={mdd_cf:+.4f}")

    # —— 星辰 factors.backtest（成本-free）——
    close_x = df.to_frame(SYM)
    sig_x = {dt: {SYM: float(w.get(dt, 0.0))} for dt in df.index}
    nav_x_cf = portfolio_backtest(close_x, sig_x, cost_rate=0.0)
    nav_x_cf.index = df.index

    # —— paddy Backtester（成本-free）——
    pos_p = w.shift(1).fillna(0.0)
    close_p = df.to_frame("close")   # paddy 要求 "close" 列
    res_p_cf = PaddyBacktester(commission=0.0).run(close_p, strategy="sma_cross", pos=pos_p)
    nav_p_cf = res_p_cf["equity"]
    nav_p_cf.index = df.index
    print(f"[paddy] 成本-free: total={nav_p_cf.iloc[-1]/nav_p_cf.iloc[0]-1:+.4f} "
          f"sharpe={res_p_cf['sharpe']:.3f} mdd={res_p_cf['max_drawdown']:+.4f}")
    print(f"[xingchen] 成本-free: total={nav_x_cf.iloc[-1]/nav_x_cf.iloc[0]-1:+.4f}")

    ok = True

    # A) 成本-free 真值锚点
    if abs(total_cf - TRUTH_TOTAL) > 0.015:
        print(f"  ✗ 真值 total {total_cf:+.4f} 偏离锚点 {TRUTH_TOTAL:+.3f}"); ok = False
    if abs(sharpe_cf - TRUTH_SHARPE) > 0.03:
        print(f"  ✗ 真值 sharpe {sharpe_cf:.3f} 偏离锚点 {TRUTH_SHARPE}"); ok = False
    if abs(mdd_cf - TRUTH_MDD) > 0.03:
        print(f"  ✗ 真值 mdd {mdd_cf:+.4f} 偏离锚点 {TRUTH_MDD}"); ok = False

    # A) 两引擎 NAV == 真值（逐点）
    if not np.allclose(_norm(nav_p_cf).values, _norm(nav_cf).values, atol=1e-9):
        print("  ✗ paddy 成本-free NAV 与真值不一致"); ok = False
    if not np.allclose(_norm(nav_x_cf).values, _norm(nav_cf).values, atol=1e-9):
        print("  ✗ xingchen 成本-free NAV 与真值不一致"); ok = False
    # A) 两引擎一致
    if not np.allclose(_norm(nav_p_cf).values, _norm(nav_x_cf).values, atol=1e-9):
        d = float(np.max(np.abs(_norm(nav_p_cf).values - _norm(nav_x_cf).values)))
        print(f"  ✗ 两引擎成本-free NAV 不一致，最大差 {d:.2e}"); ok = False

    # B) 有成本：两引擎 NAV 逐点一致，且都低于成本-free 真值
    nav_p = PaddyBacktester(commission=COST).run(close_p, strategy="sma_cross", pos=pos_p)["equity"]
    nav_p.index = df.index
    nav_x = portfolio_backtest(close_x, sig_x, cost_rate=COST)
    nav_x.index = df.index
    if not np.allclose(_norm(nav_p).values, _norm(nav_x).values, atol=1e-9):
        d = float(np.max(np.abs(_norm(nav_p).values - _norm(nav_x).values)))
        print(f"  ✗ 两引擎有成本 NAV 不一致，最大差 {d:.2e}"); ok = False
    costed_total = float(nav_p.iloc[-1] / nav_p.iloc[0] - 1.0)
    if not (costed_total < total_cf - 1e-9):
        print(f"  ✗ 有成本 total {costed_total:+.4f} 未低于成本-free 真值 {total_cf:+.4f}"
              f"（成本模型未生效）"); ok = False
    print(f"[costed] paddy total={nav_p.iloc[-1]/nav_p.iloc[0]-1:+.4f}  "
          f"xingchen total={nav_x.iloc[-1]/nav_x.iloc[0]-1:+.4f}")

    # C) paddy walk_forward 样本外夏普有限且均值合理（修复 WF 回看饥饿后不再虚高；
    #    单折可能因幸运窗口偏高，故检查「均值」而非单折 max）
    folds = PaddyBacktester.walk_forward(df.to_frame("close"), "momentum",
                                         train_size=252, test_size=63, step=63, window=250)
    wf_sharpes = [f["sharpe"] for f in folds if np.isfinite(f["sharpe"])]
    if wf_sharpes:
        mx = float(np.max(wf_sharpes))
        mean_wf = float(np.mean(wf_sharpes))
        print(f"[wf] {len(folds)} 折，max OOS sharpe={mx:.3f} mean={mean_wf:.3f}")
        if not np.isfinite(mean_wf) or mean_wf >= 2.0:
            print(f"  ✗ WF-OOS 均值异常（mean={mean_wf:.3f}），疑似放大伪值"); ok = False
    else:
        print("  ✗ 无有效 WF 折"); ok = False

    if ok:
        print("\n✅ PASS：两引擎回测 NAV 收敛，真值与锚点一致，WF-OOS 合理。")
        return 0
    print("\n❌ FAIL：见上。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
