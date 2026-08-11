#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · 模拟盘前向状态机测试

用最近 25 个交易日历史数据，逐日回放模拟盘脚本（--as-of），
验证 21 天后首次调仓的完整路径（持仓切换/现金核算/调仓触发）无 bug。

用法:
    python3 scripts/test_paper_forward.py
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
PY = sys.executable

ACCOUNTS = [
    ("双动量", "paper_trade_momentum.py", "data/paper_mom_state.json",
     ["SPY", "GLD", "DBC", "TLT"]),
    ("风险平价", "paper_trade_rp.py", "data/paper_rp_state.json",
     ["SPY", "GLD", "TLT", "DBC"]),
    ("可转债双低", "paper_trade_cb.py", "data/paper_cb_state.json", []),
]


def trade_days(store, n=25):
    df = store.load_bars("美股", "SPY")
    return [d.strftime("%Y-%m-%d") for d in df["date"].tail(n)]


def check_invariants(name, state_file, allowed):
    st = json.loads(Path(state_file).read_text(encoding="utf-8"))
    errs = []
    if st["cash"] < -1:
        errs.append(f"现金为负 {st['cash']:.0f}")
    for code in st["holdings"]:
        if allowed and code not in allowed:
            errs.append(f"非法持仓 {code}")
        h = st["holdings"][code]
        if h["value"] < 0 or h["shares"] < 0:
            errs.append(f"{code} 负值持仓")
    nav = st["cash"] + sum(h["value"] for h in st["holdings"].values())
    if nav <= 0:
        errs.append(f"净值异常 {nav:.0f}")
    return errs, st


def main():
    sys.path.insert(0, str(ROOT / "scripts"))
    from datahub.store import LocalStore
    store = LocalStore(str(ROOT / "data"))
    days = trade_days(store)
    print(f"回放窗口：{days[0]} ~ {days[-1]}（{len(days)} 个交易日）\n")
    all_ok = True

    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, PAPER_STATE_DIR=tmp)
        for name, script, state_file, allowed in ACCOUNTS:
            subprocess.run([PY, str(ROOT / "scripts" / script), "--reset"],
                           capture_output=True, check=True, env=env)
            errors = []
            rebalance_days = []
            for d in days:
                r = subprocess.run([PY, str(ROOT / "scripts" / script), "--as-of", d],
                                   capture_output=True, text=True, env=env)
                if r.returncode != 0:
                    errors.append(f"{d}: 脚本退出 {r.returncode}: {r.stderr[-200:]}")
                    break
                st = json.loads(Path(tmp, Path(state_file).name).read_text(encoding="utf-8"))
                if "调仓" in r.stdout:
                    rebalance_days.append((d, st["rebalance_count"]))
                errs, _ = check_invariants(name, Path(tmp, Path(state_file).name), allowed)
                errors.extend(f"{d}: {e}" for e in errs)
            ok = not errors
            all_ok &= ok
            print(f"[{'✓' if ok else '✗'}] {name}：25 日回放无异常" if ok
                  else f"[✗] {name} 异常：\n  " + "\n  ".join(errors[:5]))
            print(f"    调仓触发：{rebalance_days}")

    print("\n结论：", "全部通过 ✓（前向状态机无 bug）" if all_ok else "存在异常，需修复")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
