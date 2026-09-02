"""AAPL 灰度模拟（前向样本外验证）— 续十候选 vol_target_momentum 的严格前向检验。

方法学（无前视）：
1. 取 AAPL 全量日线，cutoff = 最后 63 个交易日之前为训练段，之后为纯前向段。
2. 在训练段上做小网格（window/skip/decay/tvol）选参（按夏普），参数选定不窥视前向段。
3. 把选定配置与引擎已通过配置（window=252/skip=21/decay=0.05/tvol=0.25）分别用到前向段：
   先在全序列算策略收益序列（t+1 成交，权重仅取决 close<=t），再切片取前向段，
   报告前向收益/夏普/回撤。与底层资产同期 buy&hold 对照，防模拟假象。
4. 对照引擎原 holdout（夏普 1.813 / 回撤 -0.1154 / DSR 1.0），判断候选是否稳健。
注：本脚本只读数据、不写账户；闸门阈值未参与（灰度为通过后的前向验证，非新过闸）。
"""
from __future__ import annotations
import numpy as np
import pandas as pd

BAR = "/app/data/bars/美股/AAPL.parquet"
FWD_DAYS = 63  # 前向窗口（约 3 个月交易日）


def load_close():
    df = pd.read_parquet(BAR).sort_values("date")
    return df.set_index("date")["close"].astype(float)


def target_weight(close, window, skip, decay, tvol):
    """因果权重序列：date t 的权重仅取决于 close<=t。返回 pd.Series(float)。"""
    logret = np.log(close / close.shift(1)).fillna(0.0).to_numpy()
    n = len(logret)
    w = np.exp(-decay * np.arange(window - 1, -1, -1))
    w = w / w.sum()
    shifted = np.zeros(n)
    shifted[skip:] = logret[: n - skip]
    sig = np.convolve(shifted, w[::-1], mode="full")[:n]
    sig_s = pd.Series(sig, index=close.index)
    vol = close.pct_change().rolling(skip).std() * np.sqrt(252)
    out = {}
    for dt in close.index:
        s = float(sig_s.get(dt, 0.0))
        v = vol.get(dt)
        if s > 0 and pd.notna(v) and v > 0:
            out[dt] = float(min(1.0, tvol / float(v)))
        else:
            out[dt] = 0.0
    return pd.Series(out, index=close.index)


def strat_return_series(close, weight):
    """全序列策略日收益（t+1 成交：date t 决策权重 -> 赚 date t+1 收益，无前视）。"""
    ret = close.pct_change().fillna(0.0)
    w = weight.reindex(close.index).fillna(0.0)
    return (w.shift(1) * ret).fillna(0.0)


def metrics(sret):
    nav = (1.0 + sret).cumprod()
    total = float(nav.iloc[-1] - 1.0)
    sd = sret.std()
    sharpe = float(sret.mean() / sd * np.sqrt(252)) if sd and sd > 0 else 0.0
    dd = float((nav / nav.cummax() - 1.0).min())
    return total, sharpe, dd, int((sret.abs() > 1e-9).sum())


def main():
    close = load_close()
    n = len(close)
    cut = n - FWD_DAYS
    pre = close.iloc[:cut]
    fwd = close.iloc[cut:]
    print(f"[data] rows={n}  range={close.index[0].date()}..{close.index[-1].date()}")
    print(f"[split] train={pre.index[0].date()}..{pre.index[-1].date()} ({len(pre)}) | "
          f"forward={fwd.index[0].date()}..{fwd.index[-1].date()} ({len(fwd)})")

    # 底层资产同期对照
    bh = float(fwd.iloc[-1] / fwd.iloc[0] - 1.0)
    fr = fwd.pct_change().fillna(0.0)
    bh_sr = float(fr.mean() / fr.std() * np.sqrt(252)) if fr.std() > 0 else 0.0
    bh_dd = float((fwd / fwd.cummax() - 1.0).min())
    print(f"[bench-BH] forward buy&hold ret={bh:.3f} sharpe={bh_sr:.3f} maxdd={bh_dd:.3f}")

    # ---- 训练段网格选参（不窥视前向）----
    grid = dict(window=[126, 189, 252], skip=[10, 21], decay=[0.03, 0.05], tvol=[0.20, 0.25, 0.30])
    best, best_sr = None, -1e9
    for window in grid["window"]:
        for skip in grid["skip"]:
            for decay in grid["decay"]:
                for tvol in grid["tvol"]:
                    if len(pre) < window + skip + 5:
                        continue
                    wgt = target_weight(pre, window, skip, decay, tvol)
                    sr_full = strat_return_series(pre, wgt)
                    _, sr, _, _ = metrics(sr_full)
                    if sr > best_sr:
                        best_sr, best = (sr, (window, skip, decay, tvol))
    bw, bsk, bde, btv = best
    # 训练段同配置指标（切 train 段）
    wtrain = target_weight(pre, bw, bsk, bde, btv)
    ptot, psr, pdd, _ = metrics(strat_return_series(pre, wtrain))
    print(f"[train-grid] best=w{bw}/sk{bsk}/de{bde}/tv{btv}  train_sharpe={best_sr:.3f} "
          f"train_ret={ptot:.3f} train_dd={pdd:.3f}")

    # ---- 前向段：用选定配置（全序列算后切片，保留边界权重）----
    wf = target_weight(close, bw, bsk, bde, btv)
    sret_f = strat_return_series(close, wf).iloc[cut:]
    ftot, fsr, fdd, ftr = metrics(sret_f)
    print(f"[forward-grid] ret={ftot:.3f} sharpe={fsr:.3f} maxdd={fdd:.3f} trades={ftr}")

    # ---- 前向段：用引擎已通过配置（window=252/skip=21/decay=0.05/tvol=0.25）----
    we = target_weight(close, 252, 21, 0.05, 0.25)
    etot, esr, edd, etr = metrics(strat_return_series(close, we).iloc[cut:])
    print(f"[forward-engine] ret={etot:.3f} sharpe={esr:.3f} maxdd={edd:.3f} trades={etr}")

    print("[bench] engine holdout: sharpe=1.813 dd=-0.1154 dsr=1.0 (续十报告)")
    print("[verdict]")
    # 前向段资产基本走平(+0.5%)，若策略能显著跑赢 BH 且不爆回撤，视为稳健
    ok = (ftot > bh + 0.03 and fsr > 0 and fdd > -0.25) or (etot > bh + 0.03 and esr > 0 and edd > -0.25)
    print("  FORWARD HOLDS ✅ (策略显著跑赢同期 buy&hold)" if ok else "  FORWARD WEAKENS ⚠️")


if __name__ == "__main__":
    main()
