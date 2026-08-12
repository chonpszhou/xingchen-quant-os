#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 自动运行安装器（macOS launchd）

安装两个计划任务：
  1. 工作日 16:35  运行 run_all.py all（数据→信号→三模拟盘→IV→期货→摘要）
  2. 每周日 20:00  运行 report_weekly.py（周报）并推送
  3. 每月 28-31 日 17:30 运行 run_all.py monthly（双/三账户月报）
输出日志：~/Library/Logs/星辰投研团/*.log

用法:
    python3 scripts/install_automation.py install     # 安装
    python3 scripts/install_automation.py uninstall   # 卸载
    python3 scripts/install_automation.py status      # 查看状态

说明：launchd 是 macOS 系统级调度（登录后常驻），与 crontab 二选一即可。
"""

import argparse
import plistlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LABEL_PREFIX = "com.xingchen.quant"
LOG_DIR = Path.home() / "Library" / "Logs" / "星辰投研团"
LAUNCH_AGENTS = Path.home() / "Library" / "LaunchAgents"


def plist(label, hour, minute, weekday=None, month_days=None, target=("run_all.py", "all")):
    """构造 launchd plist。weekday: 0-6（周日=0）；month_days: [28,29,30,31]"""
    calendar = {"Hour": hour, "Minute": minute}
    if hour is None:
        calendar = {"Minute": minute}  # 每小时整点触发
    if weekday is not None:
        calendar["Weekday"] = weekday
    if month_days:
        calendar["Day"] = month_days
    return {
        "Label": label,
        "ProgramArguments": [sys.executable, str(ROOT / "scripts" / target[0]), *target[1:]],
        "StartCalendarInterval": calendar,
        "StandardOutPath": str(LOG_DIR / f"{label}.log"),
        "StandardErrorPath": str(LOG_DIR / f"{label}.err.log"),
        "WorkingDirectory": str(ROOT),
        "RunAtLoad": False,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["install", "uninstall", "status"])
    args = p.parse_args()
    LAUNCH_AGENTS.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    if args.action == "install":
        jobs = [
            ("com.xingchen.quant.daily", 16, 35, list(range(1, 6)), None, ("run_all.py", "all")),
            ("com.xingchen.quant.learn", 8, 0, list(range(1, 6)), None, ("learn_daily.py",)),
            ("com.xingchen.quant.learn_hourly", None, 0, None, None, ("learn_hourly.py",)),
            ("com.xingchen.quant.weekly", 20, 0, [0], None, ("report_weekly.py",)),
            ("com.xingchen.quant.monthly", 17, 30, None, [28, 29, 30, 31], ("run_all.py", "monthly")),
        ]
        for label, h, m, wd, md, target in jobs:
            job = plist(label, h, m, wd, md, target)
            pfile = LAUNCH_AGENTS / f"{label}.plist"
            pfile.write_bytes(plistlib.dumps(job))
            subprocess.run(["launchctl", "load", str(pfile)], check=True)
            when = "每小时整点" if label.endswith("learn_hourly") else (
                "工作日 08:00" if label.endswith("learn") else (
                "周日 20:00" if label.endswith("weekly") else ("工作日 16:35" if md is None else "月末 17:30")))
            print(f"✓ 已安装 {label}（{when}）→ {pfile}")
        print("\n安装完成。日志目录：~/Library/Logs/星辰投研团/")
        print("说明：launchd 任务在用户登录后生效；手动立即运行：python3 scripts/run_all.py all")
    elif args.action == "uninstall":
        for pfile in LAUNCH_AGENTS.glob(f"{LABEL_PREFIX}.*.plist"):
            subprocess.run(["launchctl", "unload", str(pfile)], check=False)
            pfile.unlink()
            print(f"✓ 已卸载 {pfile.stem}")
    else:
        print("=== launchd 任务状态 ===")
        found = False
        for pfile in LAUNCH_AGENTS.glob(f"{LABEL_PREFIX}.*.plist"):
            found = True
            r = subprocess.run(["launchctl", "list"], capture_output=True, text=True)
            loaded = pfile.stem in r.stdout
            print(f"{pfile.stem}: {'✓ 已加载' if loaded else '✗ 未加载'} ({pfile})")
        if not found:
            print("未安装任何任务（运行 install 安装）")


if __name__ == "__main__":
    main()
