#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub CLI 设备授权登录（免交互 TUI）

用法:
    python3 scripts/github_device_login.py

流程:
    1. 从 GitHub 获取设备授权码（打印浏览器地址 + 一次性代码）
    2. 用户浏览器完成授权后自动轮询获取 token
    3. 通过 `gh auth login --with-token` 写入 gh，并验证登录状态
"""

import subprocess
import sys
import time
import urllib.parse

import requests

CLIENT_ID = "178c6fc778ccc68e1d6a"  # GitHub CLI 官方 OAuth 应用 client_id
SCOPES = "repo,read:org,gist,workflow"


def post(url, data):
    r = requests.post(url, data=data, timeout=30)
    r.raise_for_status()
    return {
        urllib.parse.unquote(k): [urllib.parse.unquote(v)]
        for k, v in (p.split("=", 1) for p in r.text.split("&") if "=" in p)
    }


def main():
    print("1/3 正在向 GitHub 申请设备授权码...")
    code = post("https://github.com/login/device/code", {
        "client_id": CLIENT_ID,
        "scope": SCOPES,
    })
    device_code = code["device_code"][0]
    user_code = code["user_code"][0]
    verify_url = code["verification_uri"][0]
    interval = int(code.get("interval", [5])[0])
    expires = int(code["expires_in"][0])

    print("=" * 62)
    print(f"请在浏览器打开: {verify_url}")
    print(f"输入一次性代码: {user_code}")
    print("=" * 62, flush=True)

    print("2/3 等待你在浏览器中确认授权...", flush=True)
    deadline = time.time() + expires
    token = None
    while time.time() < deadline:
        time.sleep(interval)
        try:
            resp = post("https://github.com/login/oauth/access_token", {
                "client_id": CLIENT_ID,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            })
        except Exception as e:
            print("轮询出错:", type(e).__name__, str(e)[:100])
            sys.exit(1)
        if "access_token" in resp:
            token = resp["access_token"][0]
            break
        err = resp.get("error", [""])[0]
        if err == "authorization_pending":
            continue
        if err == "slow_down":
            interval += 5
        elif err in ("expired_token", "access_denied"):
            print("授权失败:", err)
            sys.exit(1)

    if not token:
        print("等待超时，请重新运行本脚本")
        sys.exit(1)

    print("3/3 授权成功，正在写入 gh 配置...")
    p = subprocess.run(
        ["gh", "auth", "login", "--hostname", "github.com",
         "--git-protocol", "https", "--with-token"],
        input=token.encode(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if p.returncode != 0:
        print("gh auth login 失败:", p.stderr.decode()[:300])
        sys.exit(1)
    v = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
    print(v.stdout or v.stderr)
    print("完成：GitHub CLI 已登录")


if __name__ == "__main__":
    main()
