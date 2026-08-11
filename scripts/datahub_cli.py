#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
星辰投研团 · DataHub 命令行

用法:
    python3 scripts/datahub_cli.py update --markets A股 港股 --lookback 120
    python3 scripts/datahub_cli.py quote --symbols 600519 AAPL BTC/USDT
    python3 scripts/datahub_cli.py status
    python3 scripts/datahub_cli.py sample --market A股 --symbol 600519
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from datahub import DataHub  # noqa: E402


def cmd_update(args):
    hub = DataHub(watchlist=str(ROOT / "config/watchlist.json"), data_dir=str(ROOT / "data"))
    stats = hub.update(markets=args.markets or None, symbols=args.symbols or None,
                       lookback_days=args.lookback, force=args.force)
    print("\n===== 更新汇总 =====")
    print(f"成功 {stats['ok']} / 跳过 {stats['skip']} / 失败 {stats['failed']}")
    for e in stats["errors"]:
        print("  !", e)


def cmd_quote(args):
    hub = DataHub(watchlist=str(ROOT / "config/watchlist.json"), data_dir=str(ROOT / "data"))
    quotes = hub.quotes(markets=args.markets or None, symbols=args.symbols or None)
    rows = [q.to_dict() for q in quotes]
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    print(f"{'板块':<6}{'代码':<12}{'名称':<16}{'最新价':>12}{'涨跌幅%':>10}{'来源':<10}")
    for q in quotes:
        err = getattr(q, "_error", "")
        if err:
            print(f"{q.market:<6}{q.symbol:<12}{q.name:<16}{'-':>12}{'-':>10}{'失败':<10} {err}")
        else:
            print(f"{q.market:<6}{q.symbol:<12}{q.name:<16}{str(q.price):>12}{str(q.change_pct):>10}{q.source:<10}")


def cmd_status(args):
    hub = DataHub(watchlist=str(ROOT / "config/watchlist.json"), data_dir=str(ROOT / "data"))
    df = hub.status()
    if df.empty:
        print("暂无同步记录，先运行 update")
        return
    print(df.to_string(index=False))


def cmd_sample(args):
    hub = DataHub(watchlist=str(ROOT / "config/watchlist.json"), data_dir=str(ROOT / "data"))
    df = hub.bars(args.market, args.symbol, limit=args.limit)
    if df is None:
        print(f"{args.market} {args.symbol} 暂无本地数据")
        return
    print(df.to_string(index=False))


def main():
    p = argparse.ArgumentParser(description="星辰投研团 DataHub 命令行")
    sub = p.add_subparsers(dest="cmd", required=True)

    pu = sub.add_parser("update", help="增量更新自选股日线到本地库")
    pu.add_argument("--markets", nargs="*", help="板块过滤（A股/港股/美股/虚拟货币）")
    pu.add_argument("--symbols", nargs="*", help="代码过滤，如 600519 AAPL BTC/USDT")
    pu.add_argument("--lookback", type=int, default=120, help="首次/强制更新回看天数")
    pu.add_argument("--force", action="store_true", help="强制全量刷新")
    pu.set_defaults(func=cmd_update)

    pq = sub.add_parser("quote", help="实时行情快照")
    pq.add_argument("--markets", nargs="*")
    pq.add_argument("--symbols", nargs="*")
    pq.add_argument("--json", action="store_true")
    pq.set_defaults(func=cmd_quote)

    ps = sub.add_parser("status", help="同步状态")
    ps.set_defaults(func=cmd_status)

    psample = sub.add_parser("sample", help="查看本地日线样本")
    psample.add_argument("--market", required=True)
    psample.add_argument("--symbol", required=True)
    psample.add_argument("--limit", type=int, default=30)
    psample.set_defaults(func=cmd_sample)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
