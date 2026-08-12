#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 小白配置向导

一条命令完成首次配置：
  1) .env 凭证（邮件/IM 推送，可跳过）
  2) 实盘券商选择（默认 paper，可跳过）
  3) 自动运行安装（launchd，可跳过）
  4) 连接检查复检

用法:
    python3 scripts/setup_wizard.py              # 交互式
    python3 scripts/setup_wizard.py --auto       # 非交互（跳过凭证，仅装自动化+复检）
    python3 scripts/setup_wizard.py --pushplus TOKEN      # 一键：微信推送（PushPlus）
    python3 scripts/setup_wizard.py --serverchan KEY     # 一键：微信推送（Server酱）
    python3 scripts/setup_wizard.py --feishu URL         # 一键：飞书群机器人
    python3 scripts/setup_wizard.py --dingtalk URL       # 一键：钉钉群机器人
    python3 scripts/setup_wizard.py --wecom URL          # 一键：企业微信群机器人
"""

import argparse
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
PUSH_YAML = ROOT / "config" / "push.yaml"
ENV_FILE = ROOT / ".env"

CHANNEL_ENV = {
    "pushplus": "PUSHPLUS_TOKEN",
    "serverchan": "SERVERCHAN_KEY",
    "feishu": "FEISHU_WEBHOOK",
    "dingtalk": "DINGTALK_WEBHOOK",
    "wecom": "WECOM_WEBHOOK",
}


def write_env(key, value):
    """写 .env（追加或更新）"""
    lines = []
    if ENV_FILE.exists():
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    found = False
    for i, l in enumerate(lines):
        if l.startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            found = True
            break
    if not found:
        lines.append(f"{key}={value}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"✓ .env 已写入 {key}")


def enable_channel(channel):
    """把 config/push.yaml 中对应通道 enabled 改为 true"""
    text = PUSH_YAML.read_text(encoding="utf-8")
    if channel == "email":
        # 仅启用 email 段（第一个顶层 enabled: false 属于 email）
        text = text.replace("enabled: false", "enabled: true", 1)
    else:
        # 定位通道块内第一个 enabled: false → true
        lines = text.splitlines(keepends=True)
        inside = False
        for i, l in enumerate(lines):
            if l.strip().startswith(f"{channel}:"):
                inside = True
                continue
            if inside and l.strip() == "enabled: false":
                lines[i] = l.replace("false", "true")
                break
            if inside and l and not l[0].isspace():
                inside = False
        text = "".join(lines)
    PUSH_YAML.write_text(text, encoding="utf-8")
    print(f"✓ config/push.yaml 已启用 {channel}")


def quick_configure(channel, value):
    write_env(CHANNEL_ENV[channel], value)
    enable_channel(channel)
    print(f"\n推送已配置（{channel}）。验证：python3 scripts/push_digest.py --check")
    print("立即测试：python3 scripts/push_digest.py --text '星辰投研团 · 推送测试'")


def ask(prompt, default=""):
    if default:
        r = input(f"{prompt}（默认 {default}）: ").strip()
        return r or default
    return input(f"{prompt}: ").strip()


def setup_env(auto=False):
    if ENV_FILE.exists():
        print("✓ .env 已存在（如需修改请直接编辑）")
        return
    if auto:
        print("跳过凭证配置（--auto）；系统可无推送运行")
        return
    print("\n=== 第 1 步：推送凭证（可跳过） ===")
    print("填任意一个通道即可启用每日摘要推送：邮件 SMTP 或 IM webhook（飞书/钉钉/企微）")
    if ask("现在配置吗？(y/n)", "n").lower() != "y":
        print("跳过凭证配置（系统仍可正常跑，只是不推送）")
        return
    smtp_user = ask("SMTP 用户名（发件邮箱，可留空跳过）")
    if smtp_user:
        smtp_pass = ask("SMTP 密码/授权码")
        smtp_host = ask("SMTP 服务器", "smtp.qq.com")
        mail_to = ask("收件邮箱（逗号分隔多个）")
        lines = [
            f"SMTP_HOST={smtp_host}", "SMTP_PORT=465", f"SMTP_USER={smtp_user}",
            f"SMTP_PASS={smtp_pass}", f"SMTP_FROM={smtp_user}", f"MAIL_TO={mail_to}",
        ]
        ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("✓ 邮件凭证已写入 .env（还需在 config/push.yaml 把 email.enabled 改为 true）")
        return
    webhook = ask("IM webhook 地址（飞书/钉钉/企微任选，可留空跳过）")
    if webhook:
        ENV_FILE.write_text(f"FEISHU_WEBHOOK={webhook}\n", encoding="utf-8")
        print("✓ webhook 已写入 .env（还需在 config/push.yaml 把对应通道 enabled 改为 true）")


def setup_broker(auto=False):
    if auto:
        print("跳过券商配置（--auto）；当前使用 paper 模拟盘")
        return
    print("\n=== 第 2 步：实盘券商（可跳过，当前为模拟盘） ===")
    choice = ask("选择实盘券商 qmt(可转债A股)/futu(港股美股)/okx(加密)，或留空跳过", "")
    if choice not in ("qmt", "futu", "okx"):
        print("保持 paper 模拟盘（实盘资格需模拟盘先连续 3 个月跑赢基准）")
        return
    print(f"请按 config/broker.yaml 中 {choice} 段填写凭证后运行 python3 scripts/broker.py 验证连接")


def setup_automation(auto=False):
    print("\n=== 第 3 步：每日自动运行（推荐安装） ===")
    if auto or ask("安装 launchd 自动任务（工作日 16:35 全链路 + 月末月报）？(y/n)", "y").lower() == "y":
        subprocess.call([PY, str(ROOT / "scripts" / "install_automation.py"), "install"])
    else:
        print("跳过自动安装；可随时运行 python3 scripts/install_automation.py install")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--auto", action="store_true")
    for ch in CHANNEL_ENV:
        p.add_argument(f"--{ch}", default="", help=f"一键配置 {ch}（见用法）")
    args = p.parse_args()
    print("星辰投研团 · 配置向导\n" + "=" * 40)
    for ch, val in vars(args).items():
        if ch != "auto" and val:
            quick_configure(ch, val)
            setup_automation(args.auto)
            print("\n=== 连接检查复检 ===")
            subprocess.call([PY, str(ROOT / "scripts" / "check_connections.py")])
            print("\n配置完成！")
            return
    setup_env(args.auto)
    setup_broker(args.auto)
    setup_automation(args.auto)
    print("\n=== 第 4 步：连接检查复检 ===")
    subprocess.call([PY, str(ROOT / "scripts" / "check_connections.py")])
    print("\n配置完成！接下来只需：")
    print("  python3 scripts/run_all.py all     # 立即跑一次全链路")
    print("  python3 scripts/system_status.py   # 查看系统状态")


if __name__ == "__main__":
    main()
