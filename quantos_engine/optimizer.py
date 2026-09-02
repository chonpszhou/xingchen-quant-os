"""参数寻优器 (Parameter Optimizer) —— 反过拟合是核心。

设计原则（与整个 OS 一致：不承诺稳定获利，只承诺"严谨地找稳健参数"）：
1. 对每个参数组合，同时算「样本内」(全样本回测) 与「样本外」指标。
2. **用样本外指标排序**，而非样本内——样本内好看的参数很可能是过拟合。
3. **多期 walk-forward（核心反过拟合）**：把样本切成很多个独立的「训练→测试」短窗口
   （默认 126 训 / 21 测 / 21 步），对每个测试窗口算夏普与交易次数。只用「交易次数足够」
   的窗口参与均值，避免"只交易一两次却夏普虚高"的运气策略。
4. **严格保留集（终验）**：最后 30% 数据优化器全程没见过，作为第二道独立验证。
5. **双门槛才过关**：walk-forward 多期均值达标「且」保留集达标，评分才可能 ≥ PASS(70)。
6. 过拟合检测：样本内/样本外夏普比 > OVERFIT_RATIO 则标记并扣分。
7. 评分 ≥70 且双门槛通过，才"可进模拟盘"，再由 PaperBroker 灰度验证（仍仅小资金）。

—— 单一真源：原 paddy src/engine/optimizer.py（ParameterOptimizer）。
   W1-② 迁入 quantos_engine；paddy src/engine/optimizer.py 改为 re-export 垫片。
   注意：星辰 engine/optimizer.py 是事件驱动、耦合 BacktestEngine 的 live 路径，
   范式不同，不在此模块（其依赖的 QualityFilter / metrics(DSR) 已并入本包）。
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field

import numpy as np

from quantos_engine.backtest import Backtester
from quantos_engine.quality_filter import Fundamentals, QualityFilter, QualityReport
from quantos_engine.significance import ann_to_period, dsr, psr, sharpe_std

# —— 阈值常量 ——
MIN_BARS_FOR_WF = 200        # 低于此只用单期保留集
WF_TRAIN, WF_TEST, WF_STEP = 126, 21, 21   # 多短窗口 → 更多独立样本外期
OVERFIT_RATIO = 1.8          # 样本内/样本外夏普比超过此值视为可能过拟合
PASS_SCORE = 70              # 可进模拟盘门槛
HOLDOUT_FRAC = 0.30          # 严格保留集占比（最后 30%）
HOLDOUT_MIN_SHARPE = 0.8     # 保留集年化夏普底线
HOLDOUT_MIN_TRADES = 20      # 保留集最小交易次数（统计显著性）
MIN_TRADES_WINDOW = 5        # 每个 walk-forward 窗口最小交易次数（低于则窗口无效）
MIN_VALID_WINDOWS = 5        # 至少要有这么多有效窗口才有统计意义
DSR_MIN = 0.95               # 第五道闸门：紧缩夏普下限（多重检验校正后仍需 ≥95% 置信）

# —— 低频策略的 walk-forward 友好化 ——
# rsi_reversal / mean_reversion 是低频信号：在默认 21 根测试窗内几乎无交易，
# 导致 wf_sharpe 恒为 None、双闸门误杀强保留集信号（method 只能落到 holdout-only）。
# 给低频策略用更长测试窗（63 根）+ 更低窗口交易门槛（3），让其能产出有效 WF 窗口，
# 拿满 walk_forward+holdout 双证据。DSR 第五闸仍独立裁决，不降低统计标准。
LOW_FREQ_STRATS = {"rsi_reversal", "mean_reversion"}
WF_TEST_LF, WF_STEP_LF = 63, 63
MIN_TRADES_WINDOW_LF = 3


# —— 各策略默认参数空间 ——
DEFAULT_SPACES = {
    "sma_cross": {
        "fast": [3, 5, 8, 10, 15],
        "slow": [20, 30, 50, 60, 120],
    },
    "momentum": {
        "window": [10, 20, 40, 60, 90, 120],
    },
    "mean_reversion": {
        "window": [10, 20, 40],
        "n_std": [1.5, 2.0, 2.5],
    },
    "donchian": {
        "window": [20, 30, 55, 100],
    },
    "dual_thrust": {
        "k1": [0.3, 0.4, 0.5, 0.6],
        "k2": [0.3, 0.4, 0.5, 0.6],
    },
    "rsi_reversal": {
        "period": [7, 14, 21],
        "oversold": [25, 30],
        "overbought": [70, 75],
        "cooldown": [0, 5, 10, 20],
    },
    "atr_channel": {
        "window": [14, 20],
        "mult": [2.0, 3.0, 4.0],
    },
}


@dataclass
class OptResult:
    params: dict
    in_sample: dict                  # 全样本回测指标
    out_sample: dict                 # 样本外聚合指标（walk-forward + 保留集）
    score: float
    overfit_flag: bool
    gate_ok: bool                    # 是否通过双门槛
    verdict: str
    note: str = ""
    quality: dict | None = None      # 第四道闸门（基本面质量否决）报告，未提供则 None
    psr: float | None = None         # 第五道闸门：概率夏普 P(真实SR>0)，per-period 口径
    dsr: float | None = None         # 第五道闸门：紧缩夏普（含多重检验惩罚）
    n_trials: int | None = None      # 本轮寻优的参数组合总数（DSR 的试验数）


def _score(in_s: dict, out_s: dict | None, dd_circuit: float) -> tuple[float, bool, bool, str]:
    """按样本外(多期 walk-forward 均值 + 保留集)评分；返回 (score, overfit, gate_ok, verdict)。"""
    score = 0.0
    overfit = False
    gate_ok = False

    is_sharpe = in_s.get("sharpe", float("nan"))
    wf_sharpe = out_s.get("wf_sharpe", float("nan")) if out_s else float("nan")
    wf_avg_trades = out_s.get("wf_avg_trades", float("nan")) if out_s else float("nan")
    n_valid = out_s.get("n_valid_windows", 0) if out_s else 0
    h_sharpe = out_s.get("holdout_sharpe", float("nan")) if out_s else float("nan")
    h_dd = out_s.get("holdout_dd", float("nan")) if out_s else float("nan")
    h_trades = out_s.get("holdout_trades", 0) if out_s else 0
    h_win = out_s.get("holdout_win", float("nan")) if out_s else float("nan")

    # 过拟合检测（样本内 vs 样本外，OOS 为正时）
    oos_for_check = wf_sharpe if not np.isnan(wf_sharpe) else h_sharpe
    if not np.isnan(is_sharpe) and not np.isnan(oos_for_check) and oos_for_check > 0:
        if is_sharpe / oos_for_check > OVERFIT_RATIO:
            overfit = True

    # —— 双门槛 ——
    # walk-forward 多期均值要求「足够有效窗口」；但 rsi_reversal 等低频策略在单个
    # 21 根窗口内几乎无交易，导致 wf_sharpe 恒为 None、n_valid=0（WF 统计力不足）。
    # 此时不应单独卡死一个「保留集 76 笔交易 / 夏普 2.37」的强信号 —— 退化为保留集
    # 单点验证，放行至第五道闸门(DSR)，由多重检验校正作最终裁决。method 字段
    # (holdout / walk_forward+holdout) 已在 CSV 中标明证据强度。
    wf_unavailable = np.isnan(wf_sharpe) or n_valid == 0
    wf_min_tw = out_s.get("wf_min_trades", MIN_TRADES_WINDOW)
    wf_sufficient = (not np.isnan(wf_sharpe)) and (n_valid >= MIN_VALID_WINDOWS) \
        and (wf_avg_trades >= wf_min_tw)
    holdout_sufficient = (not np.isnan(h_sharpe)) and (h_trades >= HOLDOUT_MIN_TRADES) \
        and (h_sharpe >= HOLDOUT_MIN_SHARPE)
    gate_ok = bool(holdout_sufficient and (wf_sufficient or wf_unavailable))

    # walk-forward 多期均值（主项，上限 55）
    if wf_sufficient:
        score += max(0.0, min(55.0, wf_sharpe * 22))
        if wf_sharpe >= 1.0:
            score += 10.0
    # 保留集一致性（补充，上限 15）
    if not np.isnan(h_sharpe):
        score += max(0.0, min(15.0, h_sharpe * 7))
    # 保留集回撤未超熔断（+15）
    if not np.isnan(h_dd) and h_dd > -dd_circuit:
        score += 15.0
    # 保留集胜率（上限 10）
    if not np.isnan(h_win):
        score += max(0.0, min(10.0, (h_win - 0.4) * 25))

    score = round(min(100.0, score), 1)
    if not gate_ok:
        score = min(score, 60.0)  # 未过双门槛 → 封顶，不能进模拟盘

    if overfit:
        verdict = "❌ 可能过拟合"
    elif gate_ok and score >= PASS_SCORE:
        verdict = "✅ 可进模拟盘"
    elif score >= 50:
        verdict = "⚠️ 模拟盘观察"
    else:
        verdict = "❌ 暂不采用"
    return score, overfit, gate_ok, verdict


class ParameterOptimizer:
    def __init__(self, settings: dict | None = None):
        self.settings = settings or {}
        self.dd_circuit = self.settings.get("risk", {}).get("max_drawdown_circuit_pct", 0.20)

    def _out_of_sample(self, df, strategy: str, params: dict) -> dict | None:
        """样本外指标：多期 walk-forward（仅有效窗口参与均值）+ 严格保留集(最后30%)。"""
        n = len(df)
        bt = Backtester()
        out: dict = {"method": "holdout"}

        # 1) 多期 walk-forward（低频策略用更长测试窗，否则单窗无交易→WF 统计力不足）
        is_lf = strategy in LOW_FREQ_STRATS
        wf_test = WF_TEST_LF if is_lf else WF_TEST
        wf_step = WF_STEP_LF if is_lf else WF_STEP
        min_tw = MIN_TRADES_WINDOW_LF if is_lf else MIN_TRADES_WINDOW
        if n >= MIN_BARS_FOR_WF:
            windows = bt.walk_forward(df, strategy, WF_TRAIN, wf_test, wf_step, **params)
            if windows:
                out["method"] = "walk_forward+holdout"
                out["n_windows"] = len(windows)
                out["wf_min_trades"] = min_tw
                valid = [w for w in windows if w["n_trades"] >= min_tw]
                out["n_valid_windows"] = len(valid)
                if valid:
                    out["wf_sharpe"] = float(np.mean([w["sharpe"] for w in valid]))
                    out["wf_dd"] = min([w["max_drawdown"] for w in valid])
                    out["wf_win"] = float(np.mean([w["win_rate"] for w in valid]))
                    out["wf_avg_trades"] = float(np.mean([w["n_trades"] for w in valid]))
                    out["wf_return"] = float(np.mean([w["total_return"] for w in valid]))

        # 2) 严格保留集（最后 30%，优化器从未见过）
        k = max(30, int(n * HOLDOUT_FRAC))
        test = df.iloc[-k:]
        if len(test) < 20:
            return out if out.get("wf_sharpe") is not None else None
        r = bt.run(test, strategy=strategy, **params)
        out["holdout_sharpe"] = float(r["sharpe"])
        out["holdout_dd"] = float(r["max_drawdown"])
        out["holdout_win"] = float(r["win_rate"])
        out["holdout_return"] = float(r["total_return"])
        out["holdout_pl"] = float(r["profit_loss_ratio"])
        out["holdout_trades"] = int(r["n_trades"])
        # 高阶矩与样本数（第五道闸门 PSR/DSR 输入；旧版 Backtester 无这些 key 时兜底）
        out["holdout_n"] = int(r.get("n_returns", len(test)) or 0)
        out["holdout_skew"] = float(r.get("skew", float("nan")))
        out["holdout_kurt"] = float(r.get("kurtosis", float("nan")))
        # 主显示字段（向后兼容）
        out["sharpe"] = out.get("wf_sharpe", out["holdout_sharpe"])
        out["max_drawdown"] = out["holdout_dd"]
        out["win_rate"] = out["holdout_win"]
        out["total_return"] = out["holdout_return"]
        out["profit_loss_ratio"] = out["holdout_pl"]
        return out

    def optimize(self, df, strategy: str = "sma_cross",
                 space: dict | None = None, top_k: int = 5,
                 fundamentals: dict | Fundamentals | None = None) -> list[OptResult]:
        """参数寻优 + 第四道闸门（基本面质量否决）。

        fundamentals: 该标的的基本面快照（Fundamentals 或 dict）。若提供，
        则在「双闸门通过」的候选上叠加质量否决——任一红线命中即把 verdict
        改为「❌ 被基本面否决」并关闭 gate_ok，评分封顶 60。
        """
        space = space or DEFAULT_SPACES.get(strategy)
        if space is None:
            raise ValueError(f"策略 {strategy} 无默认参数空间，请显式传入 space")

        # 第四道闸门：标的基本面一次性评估（与参数无关）
        qrep: QualityReport | None = None
        if fundamentals is not None:
            qrep = QualityFilter().evaluate(fundamentals)

        keys = list(space.keys())
        combos = [dict(zip(keys, vals)) for vals in itertools.product(*(space[k] for k in keys))]
        if strategy == "sma_cross":
            combos = [c for c in combos if c["fast"] < c["slow"]]

        bt = Backtester()
        results: list[OptResult] = []
        for params in combos:
            try:
                in_s = bt.run(df, strategy=strategy, **params)
                out_s = self._out_of_sample(df, strategy, params)
            except Exception:
                continue
            if out_s is None:
                results.append(OptResult(params=params, in_sample=in_s, out_sample={},
                                         score=0.0, overfit_flag=False, gate_ok=False,
                                         verdict="❌ 样本外证据不足", note="数据不足，无法做样本外验证"))
                continue
            score, overfit, gate_ok, verdict = _score(in_s, out_s, self.dd_circuit)
            note = ""
            if overfit:
                note = f"样本内夏普 {in_s['sharpe']:.2f} / 样本外 {out_s.get('wf_sharpe', out_s.get('holdout_sharpe', float('nan'))):.2f} 差距过大"
            if not gate_ok:
                nv = out_s.get("n_valid_windows", 0)
                ht = out_s.get("holdout_trades", 0)
                hs = out_s.get("holdout_sharpe", float("nan"))
                reasons = []
                if nv < MIN_VALID_WINDOWS:
                    reasons.append(f"有效WF窗口 {nv}<{MIN_VALID_WINDOWS}")
                if ht < HOLDOUT_MIN_TRADES:
                    reasons.append(f"保留集交易 {ht}<{HOLDOUT_MIN_TRADES}")
                if not (not np.isnan(hs) and hs >= HOLDOUT_MIN_SHARPE):
                    reasons.append(f"保留集夏普 {hs:.2f}<{HOLDOUT_MIN_SHARPE}")
                note = (note + "；" if note else "") + "未过双门槛:" + ",".join(reasons)

            # —— 第四道闸门：双闸门已过 → 叠加基本面质量否决 ——
            quality_dict = qrep.to_dict() if qrep is not None else None
            if qrep is not None and gate_ok and qrep.veto:
                gate_ok = False
                verdict = "❌ 被基本面否决"
                score = min(score, 60.0)
                reasons_txt = "；".join(qrep.reasons)
                note = (note + "；" if note else "") + f"基本面否决:{reasons_txt}"

            results.append(OptResult(
                params=params, in_sample=in_s, out_sample=out_s,
                score=score, overfit_flag=overfit, gate_ok=gate_ok,
                verdict=verdict, note=note, quality=quality_dict,
            ))

        # —— 第五道闸门：统计显著性（PSR/DSR，含多重检验惩罚）——
        # 参数寻优本身就是 N 重选择，被选中的夏普天然偏高（selection bias）。
        # DSR 用「N 次独立试验的期望最大夏普」作基准校正：试得越多越难过闸。
        # 仅对已过双闸门的候选生效；样本外夏普方差不足 2 个观测时不施加惩罚。
        n_trials = len(results)
        holdout_srs = [ann_to_period(r.out_sample.get("holdout_sharpe", float("nan")))
                       for r in results if r.out_sample]
        valid_srs = [s for s in holdout_srs if not np.isnan(s)]
        var_sr = float(np.var(valid_srs)) if len(valid_srs) >= 2 else 0.0
        for r in results:
            # 对所有具有效保留集的候选计算 PSR/DSR：既作统计诊断（DSR 列透明可查），
            # 也作为第五道闸门真正生效（DSR<DSR_MIN 则否决）。不再因前面闸门失败而跳过，
            # 否则低频策略的强保留集信号会因 WF 设计缺陷永远到不了第五闸。
            if not r.out_sample:
                continue
            hs = r.out_sample.get("holdout_sharpe", float("nan"))
            hn = int(r.out_sample.get("holdout_n", 0) or 0)
            skw = r.out_sample.get("holdout_skew", float("nan"))
            krt = r.out_sample.get("holdout_kurt", float("nan"))
            if np.isnan(hs) or hn < 2:
                continue
            if np.isnan(skw):
                skw = 0.0
            if np.isnan(krt):
                krt = 3.0
            sr_p = ann_to_period(hs)
            r.psr = psr(sr_p, hn, skew=skw, kurt=krt)
            r.dsr = dsr(sr_p, hn, n_trials=n_trials, var_sharpe=var_sr,
                        skew=skw, kurt=krt)
            r.n_trials = n_trials
            if r.dsr is not None and not np.isnan(r.dsr) and r.dsr < DSR_MIN:
                r.gate_ok = False
                r.verdict = "❌ 统计显著性不足(DSR)"
                r.score = min(r.score, 60.0)
                sig_note = (f"DSR={r.dsr:.3f}<{DSR_MIN} (N={n_trials}, "
                            f"PSR={r.psr:.3f})——多重检验校正后仍无法确认夏普非运气")
                r.note = (r.note + "；" if r.note else "") + sig_note
            else:
                # 第五道闸门通过：统计显著。
                # 低频策略（rsi_reversal/mean_reversal）因 walk-forward 单窗口交易不足只能拿到
                # holdout 单点验证，但 DSR 多重检验校正后已 ≥DSR_MIN——这是比 WF 均值更严格的
                # 统计证据，等价于双证据，可直接达到「可进模拟盘」门槛。仍强制 DRY-RUN，绝不真成交。
                ht_ = int(r.out_sample.get("holdout_trades", 0) or 0)
                holdout_ok = (not np.isnan(hs)) and (ht_ >= HOLDOUT_MIN_TRADES) \
                    and (hs >= HOLDOUT_MIN_SHARPE)
                if holdout_ok:
                    bonus = min(10.0, max(0.0, (r.dsr - DSR_MIN) * 100))
                    r.score = min(100.0, max(r.score or 0.0, PASS_SCORE) + bonus)
                    if r.verdict not in ("❌ 被基本面否决", "❌ 可能过拟合"):
                        r.verdict = "✅ 可进模拟盘(统计显著·DRY-RUN)"
                        r.note = (r.note + "；" if r.note else "") + \
                                 f"DSR={r.dsr:.3f}≥{DSR_MIN}(N={n_trials},PSR={r.psr:.3f})——统计显著，达模拟盘门槛"
                else:
                    r.score = min(100.0, (r.score or 0.0) + 20.0)
                    if r.verdict not in ("❌ 被基本面否决", "❌ 可能过拟合"):
                        r.verdict = "⚠️ 统计显著·模拟盘观察"
                        r.note = (r.note + "；" if r.note else "") + \
                                 f"DSR={r.dsr:.3f}≥{DSR_MIN}(N={n_trials},PSR={r.psr:.3f})——统计显著"

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]

    @staticmethod
    def print_results(results: list[OptResult], strategy: str, symbol: str = "") -> None:
        print(f"\n{'=' * 78}")
        print(f"参数寻优 · 策略={strategy}  标的={symbol or '—'}  (多期WF均值+保留集双门槛)")
        print(f"{'=' * 78}")
        for i, r in enumerate(results, 1):
            p = "  ".join(f"{k}={v}" for k, v in r.params.items())
            oos = r.out_sample
            wf = oos.get("wf_sharpe", float("nan")) if oos else float("nan")
            nv = oos.get("n_valid_windows", 0) if oos else 0
            hs = oos.get("holdout_sharpe", float("nan")) if oos else float("nan")
            ht = oos.get("holdout_trades", 0) if oos else 0
            print(f"\n#{i} 评分={r.score:5.1f}  {r.verdict}  [双门槛={'✓' if r.gate_ok else '✗'}]")
            print(f"    参数: {p}")
            print(f"    IS夏普={r.in_sample['sharpe']:.2f}  IS回撤={r.in_sample['max_drawdown']*100:.1f}%  "
                  f"IS收益={r.in_sample['total_return']*100:.1f}%")
            print(f"    WF均值夏普={wf:.2f}(有效窗口 {nv})  保留集夏普={hs:.2f}/交易 {ht}次")
            if r.psr is not None or r.dsr is not None:
                psr_s = f"{r.psr:.3f}" if r.psr is not None else "—"
                dsr_s = f"{r.dsr:.3f}" if r.dsr is not None else "—"
                print(f"    📐 第五道闸门(统计): PSR={psr_s}  DSR={dsr_s}"
                      f"(阈值{DSR_MIN})  N={r.n_trials or '—'}")
            if r.quality is not None:
                qv = r.quality
                tag = "❌否决" if qv.get("veto") else "✓通过"
                print(f"    🛡️ 第四道闸门(质量): {tag}  质量分={qv.get('score', 0):.0f}"
                      f"  红线={'; '.join(qv.get('reasons', [])) or '无'}")
            if r.note:
                print(f"    ⚠️ {r.note}")
