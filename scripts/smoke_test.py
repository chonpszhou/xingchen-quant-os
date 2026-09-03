#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""星辰投研团 · 系统防回归冒烟测试（item ④）。

设计目标：在每次部署/每日批处理后，用一组低成本断言快速发现「系统悄悄坏掉」的
回归，而不是等到用户打开看板才发现金额不动 / 面板空白 / JSON 非法 / NAV 被截断。

校验项（防回归）：
  1. 看板 HTTP：
       - /health  → 200 且 JSON 中 status=="ok"
       - /ready   → 200 且包含 "ready"（说明 nav_data 至少能产出 1 个账户）
       - /        → 200 且渲染的账户面板含关键标记（双低·可转债 / 风险平价 / 盘中盯市快照）
  2. 盘中盯市 JSON：data/intraday_mtm.json 可解析，且递归检查无 NaN / Infinity
                    （mark_to_market 重写后已保证不产生非法浮点，这里做回归护栏）。
  3. 模拟盘 NAV 行数不降：每个 paper_*_nav.parquet 行数 >= 上次基线；最新 nav 有限且 > 0。
                    基线存于 data/smoke_baseline.json，首次运行建立基线，之后负责「不降」断言。
  4. market_status() 合理性：四市场键齐全、取值均为 bool、加密恒为 True。

运行：
  - 容器内（有 pandas）：python3 scripts/smoke_test.py  → 跑全量 4 组校验。
  - 宿主（无 pandas）：仅跑 HTTP + JSON 两组（数据层校验自动跳过并提示）。
  - 看板地址可用环境变量 DASHBOARD_URL 覆盖（默认 http://localhost:8080）。

退出码：全部通过 0；任一失败 1（供 cron / CI 判红）。
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
BASELINE = DATA / "smoke_baseline.json"

# 看板地址候选：显式环境变量优先；否则按运行位置自动探测
#   - 宿主 / web 容器自身：localhost:8080
#   - cron 容器（独立网络命名空间）：需经 compose 服务名 xingchen-quant-web:8080
_DASHBOARD_CANDIDATES = [
    os.environ.get("DASHBOARD_URL", "").rstrip("/"),
    "http://localhost:8080",
    "http://127.0.0.1:8080",
    "http://xingchen-quant-web:8080",
    "http://web:8080",
]
_DASHBOARD_CANDIDATES = [u for u in _DASHBOARD_CANDIDATES if u]


def discover_dashboard_url():
    for url in _DASHBOARD_CANDIDATES:
        try:
            with urllib.request.urlopen(url + "/health", timeout=3) as r:
                if r.status == 200:
                    return url
        except Exception:
            continue
    return _DASHBOARD_CANDIDATES[0] if _DASHBOARD_CANDIDATES else "http://localhost:8080"


DASHBOARD_URL = discover_dashboard_url()

# 账户面板必然出现的标记（render 的 accounts_view 渲染内容）
ACCOUNT_PANEL_MARKERS = ["双低·可转债", "风险平价", "盘中盯市快照"]

results = []   # 真实断言 (name, ok, detail)
skipped = []   # 因环境缺失而跳过的项 (name, detail)


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))


def skip(name, detail=""):
    skipped.append((name, detail))
    print(f"[SKIP] {name}" + (f" — {detail}" if detail else ""))


def http_get(path, timeout=5):
    with urllib.request.urlopen(DASHBOARD_URL + path, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "replace")


def probe_dashboard():
    """探测看板可达地址；不可达时返回 None。"""
    try:
        with urllib.request.urlopen(DASHBOARD_URL + "/health", timeout=5) as r:
            return r.status
    except Exception:
        return None


def no_nan(obj, path="$"):
    """递归检查 JSON 对象是否含 NaN/Infinity（json.loads 会将其解析成 float）。"""
    bad = []
    if isinstance(obj, float):
        if obj != obj or obj in (float("inf"), float("-inf")):
            bad.append(path)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            bad += no_nan(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            bad += no_nan(v, f"{path}[{i}]")
    return bad


def main():
    # ---------- 1. 看板 HTTP ----------
    print(f"看板探测地址：{DASHBOARD_URL}")
    try:
        st, body = http_get("/health")
        ok = st == 200 and '"status":"ok"' in body.replace(" ", "")
        check("看板 /health 200+status=ok", ok, f"http={st}")
    except Exception as e:
        check("看板 /health 200+status=ok", False, f"{type(e).__name__}: {e}")

    try:
        st, body = http_get("/ready")
        ok = st == 200 and "ready" in body
        check("看板 /ready 200+ready", ok, f"http={st}")
    except Exception as e:
        check("看板 /ready 200+ready", False, f"{type(e).__name__}: {e}")

    try:
        st, body = http_get("/")
        miss = [m for m in ACCOUNT_PANEL_MARKERS if m not in body]
        ok = st == 200 and not miss
        check("看板 / 200+账户面板", ok, f"http={st}" + (f" 缺失:{miss}" if miss else ""))
    except Exception as e:
        check("看板 / 200+账户面板", False, f"{type(e).__name__}: {e}")

    # ---------- 2. 盘中盯市 JSON 无 NaN ----------
    mtm = DATA / "intraday_mtm.json"
    if mtm.exists():
        try:
            obj = json.loads(mtm.read_text(encoding="utf-8"))
            bad = no_nan(obj)
            check("盘中盯市 JSON 无 NaN/Inf", len(bad) == 0,
                  "全部有限" if not bad else f"非法点位: {bad[:5]}")
        except Exception as e:
            check("盘中盯市 JSON 可解析", False, f"{type(e).__name__}: {e}")
    else:
        check("盘中盯市 JSON 存在", False, "intraday_mtm.json 缺失")

    # ---------- 3 + 4. 数据层（需要 pandas + dashboard 模块）----------
    try:
        import pandas as pd  # noqa: F401
        sys.path.insert(0, str(ROOT / "scripts"))
        import dashboard  # noqa: F401
        HAVE = True
    except Exception as e:
        skip("数据层校验(NAV/状态)",
             f"无 pandas 或 dashboard 模块不可用（{type(e).__name__}: {e}）；"
             f"请在容器内运行以获得全量校验。仅 HTTP+JSON 已验。")
        HAVE = False

    if HAVE:
        import pandas as pd
        sys.path.insert(0, str(ROOT / "scripts"))
        import dashboard

        # ---------- 4. market_status 合理性 ----------
        try:
            ms = dashboard.market_status()
            ok = (set(ms.keys()) == {"A股", "港股", "美股", "加密"}
                  and all(isinstance(v, bool) for v in ms.values())
                  and ms["加密"] is True)
            check("market_status 合理性", ok, str(ms))
        except Exception as e:
            check("market_status 合理性", False, f"{type(e).__name__}: {e}")

        # ---------- 3. NAV 行数不降 + 最新 nav 有限 ----------
        baseline = {}
        if BASELINE.exists():
            try:
                baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
            except Exception:
                baseline = {}
        cur = {}
        all_ok = True
        for name, f in dashboard.ACCOUNT_DEFS:
            p = DATA / f"{f}_nav.parquet"
            if not p.exists():
                continue
            try:
                df = pd.read_parquet(p)
                n = len(df)
                cur[f] = n
                last_nav = float(df.iloc[-1]["nav"])
                finite_ok = last_nav == last_nav and abs(last_nav) < float("inf") and last_nav > 0
                base_n = baseline.get(f)
                if base_n is not None and n < base_n:
                    all_ok = False
                    check(f"NAV 行数不降[{name}]", False, f"{n} < 基线 {base_n}")
                else:
                    check(f"NAV 行数[{name}]", True,
                          f"{n} 行, 最新 nav={last_nav:,.0f}" + ("" if finite_ok else " ⚠nav非有限"))
                    if not finite_ok:
                        all_ok = False
            except Exception as e:
                all_ok = False
                check(f"NAV 读取[{name}]", False, f"{type(e).__name__}: {e}")
        try:
            BASELINE.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
        check("NAV 行数不降(汇总)", all_ok, "首次运行已建基线" if not baseline else "基线已更新")

    # ---------- 汇总 ----------
    failed = [r for r in results if not r[1]]
    print()
    if skipped:
        print(f"（跳过 {len(skipped)} 项：{', '.join(n for n, _ in skipped)}）")
    if failed:
        print(f"❌ 冒烟测试失败 {len(failed)}/{len(results)} 项：")
        for n, _, d in failed:
            print(f"   - {n}：{d}")
        return 1
    print(f"✅ 冒烟测试全部通过 {len(results)}/{len(results)} 项"
          + (f"（另跳过 {len(skipped)} 项）" if skipped else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
