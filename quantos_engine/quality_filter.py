"""第四道闸门：基本面质量否决 (Quality Filter)。

设计位置：在「双闸门（多期 walk-forward + 严格保留集）」之后，
作为把"统计胜者"推向"真金白银"前的最后一道护栏。

为什么要这一道：
  双闸门只管「信号在历史上有没有用」，不管「这家公司是不是雷」。
  经验案例：携程(hk09961) rsi_reversal p=7 通过了双闸门，
  但基本面是价值陷阱（净利同比 −38.8%、51.79亿反垄断罚单、ROE 仅 1.5%），
  若直接进模拟盘就是在给雷浇水。这一道把这类标的在真钱前拦下。

否决规则（任意一条命中即否决）：
  1. 监管/法律红旗（red_flags 非空）→ 直接否决
  2. 盈利塌方：净利同比 ≤ 底线（默认 −20%）→ 否决
  3. 资本毁灭：ROE（年化）≤ 底线（默认 5%）→ 否决
  4. 资产负债表风险：负债率 ≥ 上限（默认 70%）→ 否决
  5. 流动性风险：流动比率 < 下限（默认 1.0，若数据可得）→ 否决
  6. 估值极端：PE ≤ 0 或 PE ≥ 上限（默认 100）→ 否决（泡沫或价值陷阱）

注意：本模块不承诺「通过=好公司」，只承诺「否决=明确不达标」。
阈值均为保守经验值，可按标的/市场调整。

—— 单一真源：paddy src/engine/quality_filter.py 与星辰 engine/quality_filter.py
   逐字相同，W1-② 迁入 quantos_engine（两仓改 re-export 垫片）。
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


# —— 默认阈值（保守经验值，可在 QualityFilter(thresholds=...) 覆盖）——
DEFAULT_THRESHOLDS: dict[str, float] = {
    "net_profit_yoy_min": -20.0,    # 盈利同比下限（%）：低于即视为塌陷
    "roe_annualized_min": 5.0,      # ROE 年化下限（%）：低于即视为资本毁灭
    "debt_ratio_max": 70.0,         # 负债率上限（%）
    "current_ratio_min": 1.0,       # 流动比率下限（数据可得时启用）
    "pe_max": 100.0,                # PE 上限（超过视为泡沫/极端）
}


@dataclass
class Fundamentals:
    """单标的的基本面快照。所有财务字段单位均为百分比(%)或倍数，可有缺失。"""
    symbol: str
    name: str = ""
    market: str = ""
    source: str = ""                 # 数据来源（westock / wind / 手动）
    as_of: str = ""                  # 报告期（如 2026Q1）
    net_profit_yoy: float | None = None   # 净利润同比增长 %
    revenue_yoy: float | None = None      # 营收同比增长 %
    roe: float | None = None              # ROE（按 roe_basis 口径）
    roe_basis: str = "ttm"                # quarter / ttm / annual
    net_margin: float | None = None       # 净利率 %
    gross_margin: float | None = None     # 毛利率 %
    debt_ratio: float | None = None       # 负债率 %
    current_ratio: float | None = None    # 流动比率（倍数）
    pe: float | None = None               # 滚动 PE（倍数）
    pb: float | None = None               # PB（倍数）
    red_flags: list[str] = field(default_factory=list)  # 监管/法律红旗
    notes: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "Fundamentals":
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        known.setdefault("symbol", d.get("code", d.get("symbol", "?")))
        return cls(**known)


@dataclass
class QualityReport:
    veto: bool
    reasons: list[str]              # 命中的否决/警告原因
    score: float                    # 质量分 0-100（过闸候选可视作参考）
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class QualityFilter:
    def __init__(self, thresholds: dict[str, float] | None = None):
        self.th = {**DEFAULT_THRESHOLDS, **(thresholds or {})}

    def _annualized_roe(self, f: Fundamentals) -> float | None:
        if f.roe is None:
            return None
        if f.roe_basis == "quarter":
            return f.roe * 4.0
        return f.roe

    def evaluate(self, f: Fundamentals | dict) -> QualityReport:
        if isinstance(f, dict):
            f = Fundamentals.from_dict(f)

        checks: list[tuple[str, bool, str]] = []   # (label, passed, detail)
        reasons: list[str] = []

        # 0) 监管/法律红旗（最高优先级，直接否决）
        if f.red_flags:
            joined = "；".join(f.red_flags)
            reasons.append(f"监管/法律红旗: {joined}")
            checks.append(("red_flag", False, joined))
        else:
            checks.append(("red_flag", True, "无"))

        # 1) 盈利同比
        if f.net_profit_yoy is not None:
            ok = f.net_profit_yoy >= self.th["net_profit_yoy_min"]
            detail = f"{f.net_profit_yoy:+.1f}% (底线 {self.th['net_profit_yoy_min']:.0f}%)"
            checks.append(("net_profit_yoy", ok, detail))
            if not ok:
                reasons.append(f"盈利同比塌陷 {detail}")
        else:
            checks.append(("net_profit_yoy", True, "N/A"))

        # 2) ROE 年化
        aroe = self._annualized_roe(f)
        if aroe is not None:
            ok = aroe >= self.th["roe_annualized_min"]
            detail = f"{aroe:.1f}% (底线 {self.th['roe_annualized_min']:.0f}%)"
            checks.append(("roe", ok, detail))
            if not ok:
                reasons.append(f"ROE 年化过低 {detail}")
        else:
            checks.append(("roe", True, "N/A"))

        # 3) 负债率
        if f.debt_ratio is not None:
            ok = f.debt_ratio <= self.th["debt_ratio_max"]
            detail = f"{f.debt_ratio:.1f}% (上限 {self.th['debt_ratio_max']:.0f}%)"
            checks.append(("debt_ratio", ok, detail))
            if not ok:
                reasons.append(f"负债率过高 {detail}")
        else:
            checks.append(("debt_ratio", True, "N/A"))

        # 4) 流动比率（数据可得时启用）
        if f.current_ratio is not None:
            ok = f.current_ratio >= self.th["current_ratio_min"]
            detail = f"{f.current_ratio:.2f} (下限 {self.th['current_ratio_min']:.1f})"
            checks.append(("current_ratio", ok, detail))
            if not ok:
                reasons.append(f"流动性偏弱 {detail}")
        else:
            checks.append(("current_ratio", True, "N/A"))

        # 5) 估值（PE 极端）
        if f.pe is not None:
            ok = (f.pe > 0) and (f.pe <= self.th["pe_max"])
            detail = f"PE={f.pe:.1f} (上限 {self.th['pe_max']:.0f})"
            checks.append(("pe", ok, detail))
            if not ok:
                reasons.append(f"估值极端 {detail}")
        else:
            checks.append(("pe", True, "N/A"))

        # 计算质量分：有效检查（非 N/A）的通过比例；N/A 视为通过，避免惩罚缺数据。
        # 红旗一旦存在，质量分直接压到 0。
        scored = [c for c in checks if c[0] != "red_flag"]
        valid = [c for c in scored if c[2] != "N/A"]
        if valid:
            score = round(100.0 * sum(1 for c in valid if c[1]) / len(valid), 1)
        else:
            score = 100.0
        if f.red_flags:
            score = 0.0

        veto = bool(reasons)
        return QualityReport(veto=veto, reasons=reasons, score=score,
                             details={c[0]: {"pass": c[1], "detail": c[2]} for c in checks})
