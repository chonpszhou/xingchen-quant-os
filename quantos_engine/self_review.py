"""机械级自查闸门 (self_review) · 移植自 UZI-Skill 的 review_stage_output 设计。

为什么要有这一道：
  过往「双闸门 + 质量否决」只管「数值上过没过」，但回测/寻优产物可能被
  - 数据缺口（某窗口 kline 为空）→ 夏普被算成 NaN/0
  - 前视偏差（信号偷看了未来）→ 夏普虚高
  - verdict 与 gate 自相矛盾（gate_ok=True 但评分被封顶）
  - 过拟合比率爆表却仍被放行
  等问题污染，而 agent/脚本可能「做半截」就写进 experiments.jsonl。

本模块提供**机械级**强制自检（参考 UZI-Skill v2.9 的 17 条检查思路，
但字段全部对齐本 OS 的 Backtester / ParameterOptimizer 产物）：
  1. 接收一份回测/寻优结果 dict（形如 OptResult.to_dict() 或 backtest.run() 结果）
  2. 跑一组自动检查，每条产出 Issue(severity, category, issue, evidence, fix)
  3. critical != 0 时 `passed=False` —— 上层应**拒绝**把该结果推进模拟盘/实盘

用法（CLI，无需联网）：
    python -m quantos_engine.self_review --result result.json

设计原则：纯标准库、零依赖、可独立 import；critical 阻断、warning 提示、info 参考。

—— 单一真源：paddy src/utils/self_review.py 与星辰 engine/self_review.py 逐字相同，
   W1-② 迁入 quantos_engine（两仓改 re-export 垫片，且保留 `python -m` 入口）。
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


# —— 对齐本 OS 的阈值（与 optimizer.py 保持一致）——
PASS_SCORE = 70.0
OVERFIT_RATIO = 1.8
SANE_SHARPE_MAX = 10.0          # |夏普| 超过此值高度疑似前视偏差/过拟合（warning）


@dataclass
class Issue:
    severity: str               # critical / warning / info
    category: str               # data / metric / oos / consistency / overfit / param
    issue: str
    evidence: str = ""
    fix: str = ""

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "category": self.category,
            "issue": self.issue,
            "evidence": self.evidence,
            "fix": self.fix,
        }


# ───────────────────────────────────────────────────────────────────────
# 字段提取工具：兼容 backtest.run() 与 OptResult/optimizer 两种产物形态
# ───────────────────────────────────────────────────────────────────────
def _num(d: dict | None, *keys, default=float("nan")):
    if not d:
        return default
    for k in keys:
        if k in d and d[k] is not None:
            try:
                return float(d[k])
            except (TypeError, ValueError):
                continue
    return default


def _extract(res: dict) -> dict:
    """把不同来源的结果归一化出本闸门关心的字段。"""
    in_s = res.get("in_sample") or {}
    out_s = res.get("out_sample") or {}
    # 兼容：指标可能直接挂在顶层（backtest.run）也可能在 in_sample（optimizer）
    sharpe = _num(res, "sharpe") if not _isnan(_num(res, "sharpe")) else _num(in_s, "sharpe")
    total_return = _num(res, "total_return") if not _isnan(_num(res, "total_return")) else _num(in_s, "total_return")
    max_dd = _num(res, "max_drawdown") if not _isnan(_num(res, "max_drawdown")) else _num(in_s, "max_drawdown")
    trades = _num(res, "trades")
    return {
        "sharpe": sharpe,
        "total_return": total_return,
        "max_drawdown": max_dd,
        "trades": trades,
        "in_sample": in_s,
        "out_sample": out_s,
        "score": _num(res, "score"),
        "gate_ok": bool(res.get("gate_ok", False)),
        "overfit_flag": bool(res.get("overfit_flag", False)),
        "verdict": str(res.get("verdict", "")),
        "params": res.get("params") or {},
        "quality": res.get("quality") or {},
        "equity_curve": res.get("equity_curve"),
    }


def _isnan(x) -> bool:
    try:
        return x != x  # NaN
    except Exception:
        return False


# ───────────────────────────────────────────────────────────────────────
# 检查注册表
# ───────────────────────────────────────────────────────────────────────
def check_result_nonempty(ctx: dict) -> list[Issue]:
    issues = []
    if not ctx.get("in_sample") and _isnan(ctx["sharpe"]):
        issues.append(Issue(
            "critical", "data",
            "回测结果为空（无 in_sample 也无顶层指标）",
            evidence="in_sample empty, sharpe=NaN",
            fix="重跑 backtest.run / optimizer.optimize，确认数据非空且策略产出信号",
        ))
    return issues


def check_metrics_finite(ctx: dict) -> list[Issue]:
    issues = []
    for key in ("sharpe", "total_return", "max_drawdown"):
        v = ctx[key]
        if _isnan(v) or not _isfinite(v):
            sev = "critical" if key in ("sharpe", "max_drawdown") else "warning"
            issues.append(Issue(
                sev, "metric",
                f"指标 {key} 非有限值（NaN/Inf）——报告不可用",
                evidence=f"{key}={v}",
                fix="检查数据缺口/除零；确认行情含足够非 NaN 行",
            ))
    return issues


def _isfinite(x) -> bool:
    try:
        return abs(float(x)) < float("inf")
    except Exception:
        return False


def check_drawdown_range(ctx: dict) -> list[Issue]:
    issues = []
    dd = ctx["max_drawdown"]
    if not _isnan(dd) and not (-1.0 < dd <= 0.0):
        issues.append(Issue(
            "critical", "metric",
            f"最大回撤越界（应为 (-1, 0]，实际 {dd:+.3f}）",
            evidence=f"max_drawdown={dd}",
            fix="回撤计算应为负值比例；检查权益曲线是否含前视/重复索引",
        ))
    return issues


def check_sharpe_sane(ctx: dict) -> list[Issue]:
    issues = []
    s = ctx["sharpe"]
    if not _isnan(s) and abs(s) > SANE_SHARPE_MAX:
        issues.append(Issue(
            "warning", "overfit",
            f"夏普绝对值过高（|{s:.2f}| > {SANE_SHARPE_MAX}），高度疑似前视偏差/过拟合",
            evidence=f"sharpe={s:.3f}",
            fix="排查信号函数是否引用了未来列（close 平移/未对齐）；做 walk-forward 复核",
        ))
    return issues


def check_trades_positive(ctx: dict) -> list[Issue]:
    issues = []
    t = ctx["trades"]
    if not _isnan(t) and t <= 0:
        issues.append(Issue(
            "warning", "data",
            "回测成交次数为 0——策略在该样本上从未开仓",
            evidence=f"trades={t}",
            fix="放宽信号阈值或确认数据频率/字段匹配；0 成交的评分无意义",
        ))
    return issues


def check_oos_present(ctx: dict) -> list[Issue]:
    """声明了样本外（out_sample 非空 / gate_ok=True）就必须真有有效窗口。"""
    issues = []
    out = ctx["out_sample"]
    n_valid = _num(out, "n_valid_windows")
    has_oos = bool(out) and not _isnan(n_valid)
    if has_oos and n_valid < 5:
        issues.append(Issue(
            "critical", "oos",
            f"walk-forward 有效窗口不足（{n_valid:.0f} < 5），样本外无统计意义",
            evidence=f"n_valid_windows={n_valid}",
            fix="拉长样本或缩短窗口；<5 窗口的 OOS 夏普不可信",
        ))
    # 声称过闸却无样本外证据 → 自相矛盾
    if ctx["gate_ok"] and (not out or _isnan(n_valid) or n_valid <= 0):
        issues.append(Issue(
            "critical", "oos",
            "gate_ok=True 但 out_sample 无有效窗口——双闸门证据缺失",
            evidence=f"gate_ok={ctx['gate_ok']}, out_sample={out}",
            fix="确认 optimizer 真正跑了 walk-forward；不要手工置 gate_ok",
        ))
    return issues


def check_overfit_ratio(ctx: dict) -> list[Issue]:
    issues = []
    is_s = ctx["sharpe"] if not _isnan(ctx["sharpe"]) else _num(ctx["in_sample"], "sharpe")
    oos_s = _num(ctx["out_sample"], "wf_sharpe", "holdout_sharpe")
    if not _isnan(is_s) and not _isnan(oos_s) and oos_s > 0:
        ratio = is_s / oos_s
        if ratio > OVERFIT_RATIO:
            issues.append(Issue(
                "warning", "overfit",
                f"样本内/样本外夏普比 {ratio:.2f} > {OVERFIT_RATIO}——可能过拟合",
                evidence=f"IS={is_s:.2f}, OOS={oos_s:.2f}",
                fix="降低参数复杂度/缩短回看；以样本外为准，勿被 IS 迷惑",
            ))
    return issues


def check_verdict_consistency(ctx: dict) -> list[Issue]:
    issues = []
    score = ctx["score"]
    gate = ctx["gate_ok"]
    verdict = ctx["verdict"]
    # 过闸却评分被封顶（<PASS_SCORE）→ 不一致
    if gate and not _isnan(score) and score < PASS_SCORE:
        issues.append(Issue(
            "critical", "consistency",
            f"verdict 显示过闸但评分 {score:.1f} < {PASS_SCORE:.0f}——自相矛盾",
            evidence=f"gate_ok={gate}, score={score}, verdict={verdict}",
            fix="统一评分与闸门逻辑；过闸必须 score>=PASS_SCORE",
        ))
    # 评分达标却未过闸 → 至少 warning
    if (not _isnan(score) and score >= PASS_SCORE) and not gate:
        issues.append(Issue(
            "warning", "consistency",
            f"评分 {score:.1f} >= {PASS_SCORE:.0f} 但 gate_ok=False（可能 OOS 不足/过拟合/质量否决）",
            evidence=f"gate_ok={gate}, overfit_flag={ctx['overfit_flag']}",
            fix="检查 OOS 门槛与质量否决原因；达标未过闸须有合理解释",
        ))
    # overfit_flag 与 verdict 文本应一致
    if ctx["overfit_flag"] and "过拟合" not in verdict:
        issues.append(Issue(
            "warning", "consistency",
            "overfit_flag=True 但 verdict 未标注过拟合",
            evidence=f"verdict={verdict}",
            fix="verdict 文本与 overfit_flag 对齐",
        ))
    return issues


def check_quality_consistency(ctx: dict) -> list[Issue]:
    """质量否决（第四道闸门）命中时，gate_ok 必须被关掉。"""
    issues = []
    q = ctx["quality"]
    if isinstance(q, dict) and q.get("veto") and ctx["gate_ok"]:
        issues.append(Issue(
            "critical", "consistency",
            "基本面质量否决已命中，但 gate_ok 仍为 True——第四道闸门未真正拦截",
            evidence=f"quality.veto={q.get('veto')}, gate_ok={ctx['gate_ok']}",
            fix="optimizer 在 quality.veto 时须置 gate_ok=False（见 optimizer.optimize）",
        ))
    return issues


def check_params_present(ctx: dict) -> list[Issue]:
    issues = []
    p = ctx["params"]
    if not isinstance(p, dict) or not p:
        issues.append(Issue(
            "warning", "param",
            "结果不含可部署参数（params 为空）",
            evidence=f"params={p}",
            fix="保留最优参数用于落盘预设；空参数无法复现",
        ))
    return issues


def check_equity_finite(ctx: dict) -> list[Issue]:
    issues = []
    eq = ctx.get("equity_curve")
    if eq is None:
        return issues
    try:
        arr = list(eq)
        for v in arr:
            if v is None or _isnan(v) or not _isfinite(v):
                issues.append(Issue(
                    "critical", "data",
                    "权益曲线含 NaN/Inf——记账或信号在中途断裂",
                    evidence=f"样本数={len(arr)}",
                    fix="排查数据缺行/下单后未 mark 行情；权益曲线必须全程有限",
                ))
                break
    except Exception:
        pass
    return issues


CHECKS = [
    check_result_nonempty,
    check_metrics_finite,
    check_drawdown_range,
    check_sharpe_sane,
    check_trades_positive,
    check_oos_present,
    check_overfit_ratio,
    check_verdict_consistency,
    check_quality_consistency,
    check_params_present,
    check_equity_finite,
]


def review_backtest(result: dict) -> dict:
    """对一份回测/寻优结果跑全部检查。

    返回：
        {
          "reviewed_at": iso-ts,
          "passed": bool,            # critical_count == 0
          "critical_count", "warning_count", "info_count": int,
          "issues": [ {severity, category, issue, evidence, fix}, ... ],
          "checks_run": [fn names],
        }
    """
    ctx = _extract(result)
    all_issues: list[Issue] = []
    for fn in CHECKS:
        try:
            all_issues.extend(fn(ctx) or [])
        except Exception as e:  # 检查自身异常不应阻断主流程
            all_issues.append(Issue(
                "warning", "self-check",
                f"check {fn.__name__} 自身异常: {type(e).__name__}: {str(e)[:120]}",
            ))
    crit = sum(1 for i in all_issues if i.severity == "critical")
    warn = sum(1 for i in all_issues if i.severity == "warning")
    info = sum(1 for i in all_issues if i.severity == "info")
    return {
        "reviewed_at": datetime.now().isoformat(timespec="seconds"),
        "passed": crit == 0,
        "critical_count": crit,
        "warning_count": warn,
        "info_count": info,
        "issues": [i.to_dict() for i in all_issues],
        "checks_run": [c.__name__ for c in CHECKS],
    }


def format_human(report: dict) -> str:
    mark = "✓ 通过" if report["passed"] else "✗ 阻断"
    lines = [f"机械自查 · {mark}",
             f"  critical={report['critical_count']} warning={report['warning_count']} info={report['info_count']}",
             f"  reviewed_at={report['reviewed_at']}"]
    if report["issues"]:
        lines.append("")
        for sev in ("critical", "warning", "info"):
            grp = [i for i in report["issues"] if i["severity"] == sev]
            if not grp:
                continue
            icon = {"critical": "🔴", "warning": "🟡", "info": "🔵"}[sev]
            lines.append(f"  {icon} {sev.upper()} ({len(grp)}):")
            for i in grp:
                lines.append(f"    [{i['category']}] {i['issue']}")
                if i.get("evidence"):
                    lines.append(f"      evidence: {i['evidence'][:120]}")
                if i.get("fix"):
                    lines.append(f"      fix: {i['fix'][:200]}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="回测/寻优结果机械自查")
    ap.add_argument("--result", required=True, help="结果 JSON 文件路径（含 backtest/optimize 产物）")
    args = ap.parse_args()
    p = Path(args.result)
    if not p.exists():
        print(f"结果文件不存在: {p}", file=sys.stderr)
        sys.exit(2)
    res = json.loads(p.read_text(encoding="utf-8"))
    report = review_backtest(res)
    print(format_human(report))
    sys.exit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
