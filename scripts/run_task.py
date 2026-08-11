#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 定时任务调度器（tasks.yaml 落地执行）

按任务 ID 分发到对应脚本，供 crontab / launchd 直接调用：
    python3 scripts/run_task.py daily_summary

任务映射见下方 TASKS（与 config/tasks.yaml 一一对应）。
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable

TASKS = {
    # 盘中异动监控：暂无独立脚本（预留），输出提示
    "intraday_monitor": None,
    "daily_close_digest": ("run_all.py", "digest"),
    "weekly_review": ("report_weekly.py",),
    "earnings_monitor": None,
    "option_vol_daily": ("options_iv_snapshot.py",),
    "crypto_daily": ("datahub_cli.py", "quote", "--markets", "虚拟货币"),
    "cb_double_low_monitor": ("run_cb_double_low.py",),
    "us_vol_index_monitor": ("options_iv_snapshot.py",),
    "daily_summary": ("run_all.py", "all"),
    "paper_monthly_report": ("report_monthly.py",),
}


def main():
    if len(sys.argv) < 2:
        print("用法: python3 scripts/run_task.py <task_id>\n可用任务: " + ", ".join(TASKS))
        return 1
    tid = sys.argv[1]
    if tid not in TASKS:
        print(f"未知任务 {tid}，可用: {', '.join(TASKS)}")
        return 1
    script = TASKS[tid]
    if script is None:
        print(f"[{tid}] 未配置独立脚本（见 config/tasks.yaml 说明），跳过")
        return 0
    cmd = [PY, str(ROOT / "scripts" / script[0]), *script[1:]]
    print(f"[{tid}] 执行: {' '.join(cmd)}")
    return subprocess.call(cmd)


if __name__ == "__main__":
    sys.exit(main())
