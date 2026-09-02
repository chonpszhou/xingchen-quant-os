"""研究→验证 闭环适配器（自 paddy-quant-workbench/src/research/uzi_adapter.py 移植）

定位：把研究员/UZI 的个股深度研究共识，接入本引擎的回测/风控闸门，
形成 研究(看多/看空) → 回测(五道闸门) → 风控(质量否决+研究层否决) 闭环。

本模块做三件事：
  1. 把研究共识（panel_consensus 0-100 + 多空分布）解析为 CandidateView
     （方向 long/short/neutral + 置信度 conviction + 风险点）。
  2. 把 CandidateView 作为「研究层覆盖(research overlay)」接到 QualityFilter：
     若研究共识偏空（bearish 占多数 / consensus<35），而量化闸门本要通过，
     则追加一条研究层否决（与第四道闸门「基本面否决」同一哲学：真钱前最后一道护栏）。
  3. 把看多(bullish)标的导出为 watchlist，供 optimizer 优先扫描。

兼容读取的 UZI 输出 schema（缺失字段不报错）：
  ticker / symbol / code : 代码（如 600519 / 00700 / AAPL / BTCUSDT）
  name / company         : 名称
  market                 : a / hk / us / crypto（缺省按代码前缀推断）
  panel_consensus        : 0-100 评委共识分
  signal_distribution    : {bullish, neutral, bearish} 计数
  thesis / risks         : 文本（可选）
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


# 研究层覆盖的默认行为：共识偏空即触发研究层否决
RESEARCH_VETO_BEARISH_SHARE = 0.5     # bearish 占比超过即视为偏空
RESEARCH_VETO_CONSENSUS_FLOOR = 35.0  # consensus 低于此值视为偏空


@dataclass
class CandidateView:
    """研究共识在本引擎内的标准化形态。"""
    symbol: str
    name: str = ""
    market: str = "a"
    direction: str = "neutral"        # long / short / neutral
    conviction: float = 50.0          # 0-100，距 50 的偏离度映射
    consensus: float = 50.0           # 研究员 panel_consensus 原值
    bullish: int = 0
    neutral: int = 0
    bearish: int = 0
    thesis: str = ""
    risks: list[str] = field(default_factory=list)
    source: str = "uzi-skill"
    as_of: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "CandidateView":
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        known.setdefault("symbol", d.get("ticker", d.get("symbol", d.get("code", "?"))))
        return cls(**known)


def _infer_market(symbol: str, market: str | None) -> str:
    if market:
        return market
    s = str(symbol)
    if s.lower().startswith("hk") or (s.isdigit() and len(s) == 5):
        return "hk"
    if s.lower().startswith("us") or (s.isalpha() and s.isupper()):
        return "us"
    if s.isdigit():
        return "a"
    return "a"


def from_uzi_panel(ticker: str, name: str, market: str | None,
                   consensus: float, bullish: int, neutral: int, bearish: int,
                   *, thesis: str = "", risks: list[str] | None = None,
                   as_of: str = "") -> CandidateView:
    """由研究员评委共识构造 CandidateView。"""
    total = max(1, bullish + neutral + bearish)
    bear_share = bearish / total
    bull_share = bullish / total
    consensus = float(consensus)
    if bear_share > RESEARCH_VETO_BEARISH_SHARE:
        direction = "short"
    elif bull_share > RESEARCH_VETO_BEARISH_SHARE:
        direction = "long"
    else:
        direction = "neutral"
    conviction = round(abs(consensus - 50.0) * 2.0, 1)
    return CandidateView(
        symbol=str(ticker), name=name or str(ticker),
        market=_infer_market(ticker, market), direction=direction,
        conviction=conviction, consensus=consensus,
        bullish=int(bullish), neutral=int(neutral), bearish=int(bearish),
        thesis=thesis, risks=list(risks or []),
        source="uzi-skill", as_of=as_of,
    )


def from_uzi_json(path: str | Path) -> list[CandidateView]:
    """解析一份研究产物 JSON → CandidateView 列表（兼容量化派生 crypto 观点）。"""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"研究产物文件不存在: {p}")
    raw = json.loads(p.read_text(encoding="utf-8"))
    items = raw if isinstance(raw, list) else [raw]

    views: list[CandidateView] = []
    for it in items:
        ticker = it.get("ticker") or it.get("symbol") or it.get("code")
        if not ticker:
            continue
        consensus = float(it.get("panel_consensus")
                          or it.get("consensus")
                          or (it.get("consensus_formula") or {}).get("score_mean")
                          or 50.0)
        sd = it.get("signal_distribution") or {}
        bullish = int(sd.get("bullish", it.get("bullish", 0)) or 0)
        neutral = int(sd.get("neutral", it.get("neutral", 0)) or 0)
        bearish = int(sd.get("bearish", it.get("bearish", 0)) or 0)
        name = it.get("name") or it.get("company") or str(ticker)
        market = it.get("market")
        risks = it.get("risks") or []
        if isinstance(risks, str):
            risks = [risks]
        view = from_uzi_panel(
            ticker, name, market, consensus, bullish, neutral, bearish,
            thesis=it.get("thesis", ""), risks=list(risks),
            as_of=it.get("as_of", it.get("date", "")),
        )
        views.append(view)
    return views


def overlay_research(quality: "Any", view: CandidateView,
                     *, enabled: bool = True) -> "Any":
    """把研究层观点作为覆盖接到 QualityFilter 的结果上（返回新 QualityReport）。

    若研究共识偏空（bearish 占多数 或 consensus<floor）而量化层本未否决，
    则追加「研究层看空否决」并把 veto 置 True、评分压低——与第四道闸门同一哲学。
    """
    from engine.quality_filter import QualityReport

    reasons = list(quality.reasons)
    details = dict(quality.details)
    score = float(quality.score)
    veto = bool(quality.veto)

    bear_share = view.bearish / max(1, view.bullish + view.neutral + view.bearish)
    bearish = (bear_share > RESEARCH_VETO_BEARISH_SHARE) or (view.consensus < RESEARCH_VETO_CONSENSUS_FLOOR)

    research_note = (f"研究层共识={view.consensus:.0f} "
                     f"多/中/空={view.bullish}/{view.neutral}/{view.bearish} → {view.direction}")
    details["research_overlay"] = {
        "direction": view.direction, "consensus": view.consensus,
        "bearish_share": round(bear_share, 3), "veto": bearish,
    }

    if enabled and bearish and not veto:
        reasons.append(f"研究层看空否决: {research_note}")
        veto = True
        score = min(score, 0.0)

    return QualityReport(veto=veto, reasons=reasons, score=score, details=details)


def views_to_watchlist(views: list[CandidateView]) -> list[tuple[str, str]]:
    """导出看多(long)标的，供 optimizer 优先扫描。"""
    return [(v.symbol, v.market) for v in views if v.direction == "long"]


def write_views(views: list[CandidateView], path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps([v.to_dict() for v in views],
                            ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def print_views(views: list[CandidateView]) -> str:
    lines = [f"候选观点（共 {len(views)} 个）:"]
    for v in views:
        lines.append(
            f"  {v.symbol:<10} {v.name:<10} [{v.market}] "
            f"方向={v.direction:<7} 共识={v.consensus:5.1f} 置信={v.conviction:5.1f} "
            f"多/中/空={v.bullish}/{v.neutral}/{v.bearish}"
        )
        if v.risks:
            lines.append(f"      风险: {'; '.join(v.risks[:3])}")
    return "\n".join(lines)
