#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 交易大佬学习笔记 → Obsidian 分类导出

用法:
    python3 scripts/export_trading_masters.py [目标目录]

默认目标: <项目>/docs/obsidian_export/交易大佬学习/
把 docs/交易大佬学习笔记.md 按主题拆成 6 篇 Obsidian 笔记（含 frontmatter 与互链）。
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "docs", "交易大佬学习笔记.md")
REPORT = os.path.join(ROOT, "docs", "大佬信号验证报告.md")
DEFAULT_DEST = os.path.join(ROOT, "docs", "obsidian_export", "交易大佬学习")

TAG = "交易大佬学习"


def split_sections(text):
    """按 ## / ### 标题切分，返回 [(level, title, body_lines)]"""
    sections = []
    cur = None
    for line in text.splitlines():
        m = re.match(r"^(#{2,3}) (.*)$", line)
        if m:
            if cur:
                sections.append(cur)
            cur = [len(m.group(1)), m.group(2).strip(), []]
        elif cur is not None:
            cur[2].append(line)
    if cur:
        sections.append(cur)
    return sections


def pick(sections, predicate):
    return [s for s in sections if predicate(s[1])]


def render(fname, title, tags, body, links=None):
    head = [
        "---",
        "tags:",
        "  - 量化交易",
        f"  - {TAG}",
    ]
    for t in tags:
        head.append(f"  - {t}")
    head += ["---", "", f"# {title}", ""]
    if links:
        head += ["## 相关笔记", ""]
        head += links
        head += [""]
    return fname, "\n".join(head + body).rstrip() + "\n"


def fmt_section(s):
    level, title, body = s
    lines = [f"{'#' * level} {title}", ""]
    # 去掉源文档中与当前文件重复的标题行
    lines += body
    return lines


def header_lines(header):
    """去掉源文档 H1 主标题与其后的空行，只保留引言块"""
    out = []
    started = False
    for line in header:
        if line.startswith("# "):
            continue
        if not started and not line.strip():
            continue
        started = True
        out.append(line)
    return out


def main():
    dest = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DEST
    text = open(SRC, encoding="utf-8").read()
    sections = split_sections(text)

    header = []
    for line in text.splitlines():
        if line.startswith("## "):
            break
        header.append(line)
    quote = header_lines(header)

    you = pick(sections, lambda t: t.startswith("一、"))
    x_a = pick(sections, lambda t: t.startswith("A."))
    x_b = pick(sections, lambda t: t.startswith("B."))
    x_c = pick(sections, lambda t: t.startswith("C."))
    x_d = pick(sections, lambda t: t.startswith("D."))
    x_e = pick(sections, lambda t: t.startswith("E."))
    x_f = pick(sections, lambda t: t.startswith("F."))
    method = pick(sections, lambda t: t.startswith("三、"))

    def body_of(secs):
        out = []
        for s in secs:
            out += fmt_section(s)
            out.append("")
        return out

    notes = []

    # 01 YouTube
    notes.append(render(
        "01_YouTube_投机实验室.md",
        "YouTube · 投机实验室（Speculation Lab）",
        ["YouTube", "投机实验室", "供需交易", "威科夫"],
        quote + [""] + body_of(you),
        ["- [[00_交易大佬学习总览|← 返回总览]]"],
    ))

    # 02 X 美股交易大咖
    notes.append(render(
        "02_X_美股交易大咖清单.md",
        "X · 美股交易大咖清单",
        ["X", "美股", "大咖清单"],
        quote + [""] + body_of(x_a + x_b + x_c),
        ["- [[00_交易大佬学习总览|← 返回总览]]"],
    ))

    # 03 全球量化与加密导师
    notes.append(render(
        "03_全球量化与加密导师.md",
        "全球量化导师 · 加密方向 · 宏观周期",
        ["X", "量化导师", "加密", "宏观"],
        quote + [""] + body_of(x_d + x_e),
        ["- [[00_交易大佬学习总览|← 返回总览]]"],
    ))

    # 04 高风险样本
    notes.append(render(
        "04_高风险样本与防噪纪律.md",
        "高风险样本 · 幸存者偏差 · 防噪纪律",
        ["风险样本", "幸存者偏差", "纪律"],
        quote + [""] + body_of(x_f),
        ["- [[00_交易大佬学习总览|← 返回总览]]"],
    ))

    # 05 方法论
    notes.append(render(
        "05_观点转可验证假设.md",
        "方法 · 把大佬观点变成可验证假设",
        ["方法论", "因子验证", "学习闭环"],
        quote + [""] + body_of(method) + [
            "## 两轮落地情况（2026-08-11）",
            "",
            "假突破/接针规则（含量能确认 v2）已写成因子并完成两轮 A股 walk-forward 验证：扣费后均无显著净边际；",
            "量能确认版接针是唯一方向正确的信号但强度不足，美股低波异动复现，详见 [[06_大佬信号验证报告|信号验证报告]]。",
            "",
        ],
        ["- [[00_交易大佬学习总览|← 返回总览]]"],
    ))

    # 06 验证报告（完整内容 + frontmatter）
    report_body = open(REPORT, encoding="utf-8").read()
    report_note = [
        "---",
        "tags:",
        "  - 量化交易",
        "  - 交易大佬学习",
        "  - 信号验证",
        "---",
        "",
        "# 大佬信号验证报告（假突破 / 接针）",
        "",
        "> 第一轮验证：A股 308 只（2023-05 ~ 2026-08），事件研究 + IC + walk-forward",
        "> 结论速览：A股 扣费后无显著净边际；港股假突破方向与理论一致；美股低波复现",
        "",
        "## 相关笔记",
        "",
        "- [[00_交易大佬学习总览|← 返回总览]]",
        "- [[05_观点转可验证假设|方法 · 观点→可验证假设]]",
        "",
        "---",
        "",
    ]
    # 报告正文去掉首个 H1 标题（与上面的标题重复），保留其余
    rl = report_body.splitlines()
    if rl and rl[0].startswith("# ") and not rl[0].startswith("## "):
        rl.pop(0)
        while rl and not rl[0].strip():
            rl.pop(0)
    notes.append(("06_大佬信号验证报告.md", "\n".join(report_note + rl).rstrip() + "\n"))

    # 00 总览 MOC
    toc = [
        "---",
        "tags:",
        "  - 量化交易",
        "  - 交易大佬学习",
        "  - 分类索引",
        "---",
        "",
        "# 📚 交易大佬学习 · 总览",
        "",
        "> 整理时间：2026-08-11",
        "> 目的：系统学习成熟交易员/投资人的公开内容，把“观点”转化为“可验证的假设”，再交给 DataHub + 因子流水线去证伪",
        "> 声明：账号清单反映特定时间窗口的内容相关度与信息价值，不构成任何背书或投资建议",
        "",
        "## 分类导航",
        "",
        "- [[01_YouTube_投机实验室|YouTube · 投机实验室]] —— 供需/威科夫/假突破/账户复盘",
        "- [[02_X_美股交易大咖清单|X · 美股交易大咖]] —— 31 核心美股 + 18 科技AI半导体 + 宏观周期",
        "- [[03_全球量化与加密导师|全球量化导师 · 加密方向]] —— Ernie Chan / Damodaran / 链上周期等",
        "- [[04_高风险样本与防噪纪律|高风险样本 · 防噪纪律]] —— Serenity / Leto Bao 幸存者偏差标注",
        "- [[05_观点转可验证假设|方法 · 观点→可验证假设]] —— 精读→假设→回测→归档闭环",
        "- [[06_大佬信号验证报告|信号验证报告]] —— 第一轮：假突破/接针 A股 回测结论",
        "",
        "## 一句话记忆",
        "",
        "1. **投机实验室**：华人系统化交易教学 + 真实账户复盘，供需/威科夫/假突破可直接信号化",
        "2. **X 大咖**：美股财报/估值/期权（Sober、GURGAVIN、Kobeissi）+ 科技AI半导体硬核数据（Dylan Patel）",
        "3. **量化底座**：Ernie Chan 三分类（均值回归/动量/波动率）是因子库理论底座；Damodaran 供估值锚",
        "4. **防噪**：不追喊单、不追粉丝量；Serenity 类高收益叙事默认怀疑",
        "5. **落地**：每周精读 1-2 个账号，观点写成 If-Then 规则进因子流水线证伪",
        "",
        "## 相关库",
        "",
        "- [[00_量化知识库总览|量化知识库]]（GitHub 全领域 12 大分类）",
        "- [[00_GitHub量化学习总览|GitHub 量化学习 · Top50]]",
        "",
        "---",
        "",
        "> 本库内容基于公开内容整理，仅供学习参考，不构成任何投资建议。",
        "",
    ]
    notes.append(("00_交易大佬学习总览.md", "\n".join(toc)))

    os.makedirs(dest, exist_ok=True)
    for fname, content in notes:
        with open(os.path.join(dest, fname), "w", encoding="utf-8") as f:
            f.write(content)
    print(f"已写入 {len(notes)} 篇 → {dest}")


if __name__ == "__main__":
    main()
