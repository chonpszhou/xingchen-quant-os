#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 推送到微信（clawbot 桥接通道）

复用 微信助手 项目的桥接发送能力（AppleScript 输入框粘贴+回车），
把通知文本发送到你当前打开的微信聊天窗口（如「文件传输助手」）。

要求：微信 Mac 客户端运行、聊天窗口打开、ChatGPT 已授权辅助功能权限。

用法:
    python3 scripts/push_wechat.py --text "消息内容"
"""

import argparse
import os
import re
import sys
from pathlib import Path

WECHAT_DIR = Path(os.environ.get(
    "WECHAT_BRIDGE_DIR", str(Path.home() / "Documents" / "ChatGPT" / "微信助手")))


def clean(text: str, limit: int = 800) -> str:
    """微信纯文本化：去 Markdown 标记、压缩空白、限长"""
    t = re.sub(r"[|#*`>]", "", text)
    t = re.sub(r"\n{2,}", "\n", t)
    t = t.strip()
    return t[:limit]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--text", required=True, help="要发送的消息")
    args = p.parse_args()
    if not WECHAT_DIR.exists():
        print(f"✗ 未找到微信桥接目录 {WECHAT_DIR}")
        return 1
    sys.path.insert(0, str(WECHAT_DIR))
    try:
        from wechat_bridge import load_config, send_text
        cfg = load_config()
        result = send_text(cfg, clean(args.text))
    except Exception as e:  # noqa: BLE001
        print(f"✗ 发送失败：{e}")
        return 1
    if str(result).startswith("ERR"):
        print(f"✗ 微信发送失败：{result}")
        return 1
    print(f"✓ 已发送到微信当前聊天窗口（{result}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
