#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 一键验收测试

聚合核心健康检查，输出 PASS/FAIL 报告：
  1) 连接检查（26 项，网络类）
  2) 模拟盘引擎一致性（回测对照）
  3) 模拟盘前向状态机（25 日回放）
  4) 风控监控器
  5) 摘要生成
  6) launchd 自动化状态
  7) git 工作区干净度

用法:
    python3 scripts/acceptance_test.py
输出:
    docs/验收报告.md
"""

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable


def run(name, script, args=(), timeout=600):
    try:
        r = subprocess.run([PY, str(ROOT / "scripts" / script), *args],
                           capture_output=True, text=True, timeout=timeout)
        return name, r.returncode == 0, (r.stdout + r.stderr)[-300:]
    except subprocess.TimeoutExpired:
        return name, False, f"超时（>{timeout}s）"
    except Exception as e:  # noqa: BLE001
        return name, False, str(e)[:200]


def main():
    results = []
    print("星辰投研团 · 一键验收测试\n" + "=" * 40)

    # 1. 连接检查
    results.append(run("连接检查（26项）", "check_connections.py", timeout=600))
    # 2. 引擎一致性
    results.append(run("引擎一致性校验", "validate_paper_engines.py", timeout=180))
    # 3. 前向状态机
    results.append(run("前向状态机测试", "test_paper_forward.py", timeout=180))
    # 4. 风控
    results.append(run("风控监控器", "risk_monitor.py", timeout=60))
    # 5. 摘要
    results.append(run("每日摘要生成", "run_all.py", ("digest",), timeout=120))
    # 6. launchd
    agents = list((Path.home() / "Library" / "LaunchAgents").glob("com.xingchen.quant.*.plist"))
    loaded = len(agents) >= 2
    results.append(("launchd 自动化", loaded,
                    f"{len(agents)} 个任务: {[p.stem for p in agents]}" if agents else "未安装"))
    # 7. git
    g = subprocess.run(["git", "status", "--short"], capture_output=True, text=True,
                       cwd=ROOT)
    dirty = bool(g.stdout.strip())
    results.append(("git 工作区", not dirty, g.stdout.strip()[:200] or "干净"))

    # 汇总
    lines = [
        "# 一键验收报告",
        "",
        f"> 生成时间：{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "| 检查项 | 状态 | 说明 |",
        "|--------|------|------|",
    ]
    all_ok = True
    for name, ok, detail in results:
        all_ok &= ok
        icon = "✅ 通过" if ok else "❌ 失败"
        lines.append(f"| {name} | {icon} | {detail.replace('|', '／').replace(chr(10), ' ')[:120]} |")
    lines += ["", f"**结论：{'全部通过' if all_ok else '存在失败项，需处理'}**", ""]
    (ROOT / "docs" / "验收报告.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print("\n结果汇总：", "全部通过 ✓" if all_ok else "存在失败项 ✗")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
