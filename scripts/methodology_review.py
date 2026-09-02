#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
方法论动态优化审查器（星辰投研团）

把「每天的学习报告」变成对系统自身方法的持续拷问：
  - 扫描 docs/学习笔记_*.md / 学习日志_*.md，识别方法论升级信号
    （动量/因子/ML/组合/横截面/波动率/成本/回测纪律…）
  - 维护 config/methodology_proposals.json（审查董事会）：
      每条 = {id, component, current, proposed, source, rationale,
              hypothesis, validation, status, adopted_at, evidence_count, last_seen}
  - 幂等：同 (component, proposed) 不重复；仅更新 evidence_count / last_seen
  - 打印审查板，供人工拍板「采纳/驳回」

原则（与五道闸一致，不放松纪律）：
  - 本脚本只「提案 + 记录证据」，不改任何引擎代码；
  - 采纳（adopted）需由人工/我落地代码改动，并经五道闸/样本外验证后才生效；
  - 绝不因为「学习说某方法先进」就降低 DSR/质量否决阈值去强行通过。

用法:
    python3 scripts/methodology_review.py
    python3 scripts/methodology_review.py --adopt M-001   # 标记某条为已采纳（代码改动另做）
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROP = ROOT / "config" / "methodology_proposals.json"

# 主题 → 关键词 + 提案模板。proposed 为「最先进合适」的替代方向（需验证后采纳）。
THEMES = {
    "momentum_bounds": {
        "kw": ["动量", "momentum", "time series momentum"],
        "component": "strategy.momentum",
        "current": "朴素动量（pct_change(window) 单窗口，无跳过月/衰减）",
        "proposed": "时间序列动量加边界：12-1 月窗口 + 1 月跳过 + 衰减权重（对标 Boundaries of TS Momentum）",
        "source": "学习笔记 2026-09-02 #3 Quantpedia《Boundaries of Time Series Momentum》",
        "rationale": "学习语料中动量/TS-momentum 命中 25+ 文档；该文指出朴素动量有过拟合与衰减边界，需校正窗口",
        "hypothesis": "加边界的 TS 动量在样本外更稳，可能通过五道闸而朴素版不能",
        "validation": "同标的同数据对比朴素 vs 边界动量，看 DSR/回撤是否改善且不放松闸门",
    },
    "ml_factor": {
        "kw": ["机器学习", "ML", "machine learning", "factor research", "return prediction"],
        "component": "strategy.ml_factor",
        "current": "仅 ml_reversal（单特征打分）",
        "proposed": "横截面 ML 因子模型：多因子（动量/价值/质量/低波等）XGBoost/线性，做截面排序",
        "source": "学习笔记 2026-09-02 #7 Factor-Research《ML-powered stock return prediction (7 factors)》",
        "rationale": "ML/机器学习 命中 22 文档；单特征 ml_reversal 远弱于多因子 ML",
        "hypothesis": "多因子 ML 截面模型信息比更高，可能产出通过五道闸的 alpha",
        "validation": "需行情+因子数据；walk-forward 截面训练，严禁前视；DSR≥0.95 硬卡",
    },
    "portfolio_layer": {
        "kw": ["组合", "portfolio", "multi-alpha", "multi factor", "ensemble"],
        "component": "layer.portfolio",
        "current": "无组合层：逐标的单策略评分，无跨标的组合/集成",
        "proposed": "多 alpha 组合层：把通过五道闸的策略跨标的按风险平价/波动率目标组合",
        "source": "学习笔记 2026-09-02 #2 ai_for_trading multi_factor_modeling_project",
        "rationale": "组合/portfolio 命中 23 文档；系统缺组合构建，只到单标的",
        "hypothesis": "组合层降低 idiosyncratic 风险，提升整体 Sharpe/回撤",
        "validation": "对通过闸的策略做组合回测，对比单标的分散效果",
    },
    "cross_sectional": {
        "kw": ["横截面", "cross-sectional", "cross section", "截面"],
        "component": "factor.cross_sectional",
        "current": "仅时间序列因子（时序动量/时序均值回归）",
        "proposed": "加横截面因子：截面动量、截面价值、截面低波（行业内 z-score）",
        "source": "学习笔记 cross-sectional 命中 3 文档；因子研究通用做法",
        "rationale": "时序因子易受市场 beta 干扰；截面因子剥离 beta 更干净",
        "hypothesis": "截面因子提供与市场无关的 alpha 来源",
        "validation": "需多标的同日期截面；walk-forward；DSR 硬卡",
    },
    "vol_target_sizing": {
        "kw": ["波动率", "volatility", "风险平价", "risk parity", "仓位"],
        "component": "risk.position_sizing",
        "current": "固定仓位（无波动率目标）",
        "proposed": "波动率目标/风险平价仓位：按标的波动率的倒数定仓，组合层风险平价",
        "source": "系统已有风险平价模拟盘账户；学习 波动率/风险 命中 22 文档",
        "rationale": "固定仓位在高波动标的暴露过大；波动率目标更稳",
        "hypothesis": "波动目标降低回撤、提升风险调整收益",
        "validation": "同策略对比固定 vs 波动目标仓位，看 max_dd/Sharpe",
    },
    "cost_model": {
        "kw": ["成本", "佣金", "滑点", "commission", "slippage", "transaction cost"],
        "component": "cost.model",
        "current": "单一 flat 成本 0.002（不分市场）",
        "proposed": "分市场成本：A股 T+1+印花税、加密 maker 0.1%、美股佣金/§220 规则",
        "source": "回测纪律（学习 回测 命中 25 文档）；Ernie Chan 强调成本敏感性",
        "rationale": "单一成本对高换手策略低估摩擦，可能虚高夏普",
        "hypothesis": "真实分市场成本下部分策略夏普下降，更诚实",
        "validation": "同策略对比 flat vs 分市场成本，看通过率变化（更保守）",
    },
    "backtest_discipline": {
        "kw": ["回测", "backtest", "前视", "look-ahead", "过拟合", "walk forward"],
        "component": "discipline.backtest",
        "current": "已落实：无未来函数(shift1) + walk-forward + holdout + DSR≥0.95",
        "proposed": "维持并定期复检（学习反复强调回测纪律，与现有五道闸一致）",
        "source": "学习 回测/backtest 命中 25 文档",
        "rationale": "学习语料印证现有无前视+WF+DSR 纪律正确，无需改方法，需保持",
        "hypothesis": "—",
        "validation": "—",
    },
}


def _load_props() -> list:
    if PROP.exists():
        try:
            return json.loads(PROP.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _save_props(props: list):
    PROP.parent.mkdir(parents=True, exist_ok=True)
    PROP.write_text(json.dumps(props, ensure_ascii=False, indent=2), encoding="utf-8")


def _scan_learning() -> str:
    chunks = []
    for pat in ("学习笔记_*.md", "学习日志_*.md"):
        for f in sorted((ROOT / "docs").glob(pat), reverse=True):
            try:
                chunks.append(f.read_text(encoding="utf-8").lower())
            except Exception:
                continue
    return "\n".join(chunks)


def _id_of(component: str) -> str:
    h = abs(hash(component)) % 1000
    return f"M-{h:03d}"


def run(adopt: str | None = None):
    props = _load_props()
    by_key = {(p["component"], p["proposed"]): p for p in props}
    text = _scan_learning()
    today = datetime.now().strftime("%Y-%m-%d")

    for theme, t in THEMES.items():
        hits = sum(text.count(k.lower()) for k in t["kw"])
        if hits == 0:
            continue
        key = (t["component"], t["proposed"])
        if key in by_key:
            p = by_key[key]
            p["evidence_count"] = p.get("evidence_count", 0) + 1
            p["last_seen"] = today
        else:
            p = {
                "id": _id_of(t["component"]),
                "component": t["component"],
                "current": t["current"],
                "proposed": t["proposed"],
                "source": t["source"],
                "rationale": t["rationale"],
                "hypothesis": t["hypothesis"],
                "validation": t["validation"],
                "status": "pending",
                "adopted_at": None,
                "evidence_count": 1,
                "last_seen": today,
            }
            props.append(p)
            by_key[key] = p
        if adopt and p["id"] == adopt:
            p["status"] = "adopted"
            p["adopted_at"] = today

    _save_props(props)
    # 打印审查板
    print(f"  方法论审查董事会（基于每日学习报告动态更新）— {today}")
    print(f"  {'ID':<7} {'状态':<9} {'组件':<22} {'当前→建议'}")
    for p in sorted(props, key=lambda x: (x["status"] != "adopted", -x.get("evidence_count", 0))):
        cur = p["current"][:18]
        pro = p["proposed"][:22]
        print(f"  {p['id']:<7} {p['status']:<9} {p['component']:<22} {cur} → {pro}")
    print(f"  （共 {len(props)} 条；pending 待拍板采纳，adopted 已落地代码并过五道闸）")
    return props


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--adopt", default=None, help="标记某提案为已采纳（如 M-001）")
    a = ap.parse_args()
    run(a.adopt)
