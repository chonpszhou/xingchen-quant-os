#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""星辰投研团 · 交易执行层单元测试（stdlib unittest，无外部依赖）

覆盖：双闸门、DRY-RUN 拦截、replay 留痕、统一审计、PaperBroker 记账、get_broker 分发。
运行：python3 scripts/test_broker.py   （或 python3 -m unittest scripts/test_broker -v）

注意：所有测试均使用临时 state / audit 文件，不触碰真实 data/paper_cb_state.json
与 data/order_audit.jsonl。
"""
import json
import os
import sys
import tempfile
import unittest

# 让 `import broker` 在脚本模式与 `python3 -m unittest scripts.test_broker` 包模式下都能解析
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import broker
from broker import LiveBroker, PaperBroker, QmtBroker, FutuBroker, OkxBroker, get_broker


class TestDoubleGate(unittest.TestCase):
    """双闸门：armed 需 enabled + (not dry_run) + confirm 三者齐备。"""

    def test_armed_only_when_all_three(self):
        b = LiveBroker(OkxBroker({}), live_enabled=True, dry_run=False, confirm=True)
        self.assertTrue(b.is_armed())
        self.assertIn("LIVE", b.status())

    def test_missing_confirm_not_armed(self):
        # 即便 enabled + dry_run=False，缺 confirm 仍不 armed（安全最关键一闸）
        b = LiveBroker(OkxBroker({}), live_enabled=True, dry_run=False, confirm=False)
        self.assertFalse(b.is_armed())
        self.assertIn("DISABLED", b.status())

    def test_missing_enabled_not_armed(self):
        b = LiveBroker(OkxBroker({}), live_enabled=False, dry_run=False, confirm=True)
        self.assertFalse(b.is_armed())

    def test_default_is_dry_run(self):
        b = LiveBroker(OkxBroker({}), live_enabled=True)   # dry_run 默认 True
        self.assertFalse(b.is_armed())
        self.assertIn("DRY-RUN", b.status())


class TestDryRunIntercept(unittest.TestCase):
    """真实适配器 DRY-RUN：buy/sell 被拦截，绝不发单，留痕审计。"""

    def setUp(self):
        self.tmp_audit = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
        self.tmp_audit.close()
        self._orig = broker.ORDER_AUDIT_LOG
        broker.ORDER_AUDIT_LOG = broker.Path(self.tmp_audit.name)

    def tearDown(self):
        broker.ORDER_AUDIT_LOG = self._orig
        os.unlink(self.tmp_audit.name)

    def test_buy_intercepted_and_audited(self):
        b = LiveBroker(OkxBroker({}), live_enabled=True)   # DRY-RUN
        res = b.buy("BTC-USDT", 0.01)
        self.assertFalse(res["ok"])
        self.assertTrue(res["dry_run"])
        # 审计文件应有一条 BTC-USDT 记录
        lines = [json.loads(l) for l in open(self.tmp_audit.name, encoding="utf-8")]
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["symbol"], "BTC-USDT")
        self.assertIn("DRY-RUN 拦截", lines[0]["note"])

    def test_replay_only_logs(self):
        b = LiveBroker(OkxBroker({}), live_enabled=True)
        out = b.dry_run_replay([("buy", "ETH-USDT", 0.1), ("sell", "SOL-USDT", 1.0)])
        self.assertEqual(out["n"], 2)
        self.assertFalse(out["armed"])
        lines = [json.loads(l) for l in open(self.tmp_audit.name, encoding="utf-8")]
        self.assertEqual(len(lines), 2)
        self.assertEqual({x["symbol"] for x in lines}, {"ETH-USDT", "SOL-USDT"})


class TestPaperBookkeeping(unittest.TestCase):
    """PaperBroker 经 LiveBroker 包裹：模拟成交执行记账 + 统一审计。"""

    def setUp(self):
        self.tmp_state = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump({"cash": 1000000.0, "rebalance_count": 0, "last_rebalance": "",
                   "holdings": {}}, self.tmp_state)
        self.tmp_state.close()
        self.tmp_nav = tempfile.NamedTemporaryFile("w", suffix=".parquet", delete=False)
        self.tmp_nav.close()
        self.tmp_audit = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
        self.tmp_audit.close()
        self._orig = broker.ORDER_AUDIT_LOG
        broker.ORDER_AUDIT_LOG = broker.Path(self.tmp_audit.name)
        self.b = LiveBroker(PaperBroker(state_file=self.tmp_state.name,
                                         nav_file=self.tmp_nav.name),
                            live_enabled=False, dry_run=False, confirm=False)

    def tearDown(self):
        broker.ORDER_AUDIT_LOG = self._orig
        for f in (self.tmp_state, self.tmp_nav, self.tmp_audit):
            os.unlink(f.name)

    def test_paper_executes_and_audits(self):
        self.assertTrue(self.b.is_paper)
        res = self.b.buy("TEST", 10, price=100.0)
        self.assertTrue(res["ok"])
        st = json.loads(open(self.tmp_state.name, encoding="utf-8").read())
        self.assertAlmostEqual(st["cash"], 999000.0, places=2)
        self.assertEqual(st["holdings"]["TEST"]["shares"], 10)
        lines = [json.loads(l) for l in open(self.tmp_audit.name, encoding="utf-8")]
        self.assertEqual(len(lines), 1)
        self.assertIn("PAPER", lines[0]["note"])
        # 卖出后现金回笼、持仓清零
        res2 = self.b.sell("TEST", 10, price=110.0)
        self.assertTrue(res2["ok"])
        st2 = json.loads(open(self.tmp_state.name, encoding="utf-8").read())
        self.assertAlmostEqual(st2["cash"], 999000.0 + 1100.0, places=2)
        self.assertNotIn("TEST", st2["holdings"])


class TestGetBrokerDispatch(unittest.TestCase):
    """get_broker 分发：paper 包裹 LiveBroker；真实适配器默认 DRY-RUN。"""

    def test_paper_returns_livebroker_wrapping_paper(self):
        b = get_broker("paper")
        self.assertIsInstance(b, LiveBroker)
        self.assertTrue(b.is_paper)

    def test_okx_default_dry_run_not_armed(self):
        b = get_broker("okx")
        self.assertIsInstance(b, LiveBroker)
        self.assertFalse(b.is_armed())
        self.assertIn("DRY-RUN", b.status())

    def test_okx_armed_requires_confirm(self):
        # 配置 enabled=false → 即便代码传 dry_run=False/confirm=True 也不 armed
        b = get_broker("okx", dry_run=False, confirm=True)
        self.assertFalse(b.is_armed())


if __name__ == "__main__":
    unittest.main(verbosity=2)
