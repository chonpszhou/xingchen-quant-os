#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 摘要/消息推送（邮件 + IM 机器人）

读取 config/push.yaml 与项目根 .env（凭证），把最新投研摘要发送到
已启用的通道（email / feishu / dingtalk / wecom / serverchan / pushplus）。
未配置凭证时安全跳过并提示。

用法:
    python3 scripts/push_digest.py                    # 推送最新摘要
    python3 scripts/push_digest.py --text "自定义消息"
    python3 scripts/push_digest.py --check            # 仅检查通道配置
"""

import argparse
import os
import re
import smtplib
import sys
from email.header import Header
from email.mime.text import MIMEText
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_env():
    env = {}
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def latest_digest():
    files = sorted(ROOT.glob("docs/投研摘要_*.md"))
    return files[-1] if files else None


def send_email(cfg, env, subject, body):
    host = cfg["smtp_host"].strip("${}") if str(cfg["smtp_host"]).startswith("$") else cfg["smtp_host"]
    user = env.get("SMTP_USER", "")
    pwd = env.get("SMTP_PASS", "")
    frm = env.get("SMTP_FROM", user)
    tos = [x.strip() for x in env.get("MAIL_TO", "").split(",") if x.strip()]
    if not (user and pwd and tos):
        return False, "邮件凭证缺失"
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = frm
    msg["To"] = ",".join(tos)
    with smtplib.SMTP_SSL(host, int(cfg["smtp_port"]), timeout=30) as s:
        s.login(user, pwd)
        s.sendmail(frm, tos, msg.as_string())
    return True, f"邮件已发送至 {len(tos)} 个地址"


def send_webhook(kind, cfg, env, body):
    key = {"feishu": "FEISHU_WEBHOOK", "dingtalk": "DINGTALK_WEBHOOK",
           "wecom": "WECOM_WEBHOOK"}.get(kind)
    url = env.get(key, "")
    if not url:
        return False, f"{kind} 未配置 webhook"
    if kind == "feishu":
        payload = {"msg_type": "text", "content": {"text": body[:4000]}}
    elif kind == "dingtalk":
        payload = {"msgtype": "text", "text": {"content": body[:4000]}}
    elif kind == "wecom":
        payload = {"msgtype": "text", "text": {"content": body[:4000]}}
    r = requests.post(url, json=payload, timeout=15)
    r.raise_for_status()
    return True, f"{kind} 已推送（{r.status_code}）"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--text", default="")
    p.add_argument("--check", action="store_true")
    args = p.parse_args()
    cfg = yaml.safe_load((ROOT / "config" / "push.yaml").read_text(encoding="utf-8"))
    env = load_env()
    channels = cfg["push"]

    if args.check:
        print("=== 推送通道检查 ===")
        email = channels.get("email", {})
        print(f"邮件: {'启用' if email.get('enabled') else '未启用'} "
              f"(SMTP_USER={'已配置' if env.get('SMTP_USER') else '未配置'})")
        for kind, c in channels.get("im", {}).items():
            key = {"feishu": "FEISHU_WEBHOOK", "dingtalk": "DINGTALK_WEBHOOK",
                   "wecom": "WECOM_WEBHOOK", "serverchan": "SERVERCHAN_KEY",
                   "pushplus": "PUSHPLUS_TOKEN"}[kind]
            print(f"{kind}: {'启用' if c.get('enabled') else '未启用'} "
                  f"({'已配置' if env.get(key) else '未配置'})")
        return 0

    digest = latest_digest()
    if not digest:
        print("未找到投研摘要，先运行 python3 scripts/run_all.py digest")
        return 1
    body = args.text or digest.read_text(encoding="utf-8")
    subject = args.text and "星辰投研团 · 通知" or f"星辰投研团 · 投研摘要 {digest.stem.split('_')[-1]}"

    sent = 0
    if channels.get("email", {}).get("enabled"):
        ok, msg = send_email(channels["email"], env, subject, body)
        print(("✓ " if ok else "✗ ") + msg)
        sent += ok
    for kind, c in channels.get("im", {}).items():
        if not c.get("enabled"):
            continue
        if kind in ("serverchan", "pushplus"):
            key = "SERVERCHAN_KEY" if kind == "serverchan" else "PUSHPLUS_TOKEN"
            token = env.get(key, "")
            if not token:
                print(f"✗ {kind} 未配置 token")
                continue
            url = (f"https://sctapi.ftqq.com/{token}.send" if kind == "serverchan"
                   else f"https://www.pushplus.plus/send")
            payload = {"title": subject, "desp": body} if kind == "serverchan" else {"token": token, "title": subject, "content": body}
            r = requests.post(url, data=payload, timeout=15)
            print(f"{'✓' if r.ok else '✗'} {kind} 已推送（{r.status_code}）")
            sent += r.ok
            continue
        ok, msg = send_webhook(kind, c, env, body)
        print(("✓ " if ok else "✗ ") + msg)
        sent += ok
    if sent == 0:
        print("\n未启用任何推送通道。配置方法：复制 .env.example 为 .env，填写凭证，"
              "并把 config/push.yaml 中对应通道 enabled 改为 true。")
    return 0 if sent else 1


if __name__ == "__main__":
    sys.exit(main())
