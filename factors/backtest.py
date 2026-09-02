"""兼容垫片：因子组合回测核已迁至 quantos_engine.backtest（单一真源，Phase 1）。

保留本文件以便既有 `from factors.backtest import metrics / portfolio_backtest / walk_forward / factor_signals` 调用零改动。
实际实现见 paddy-quant-workbench/quantos_engine/backtest.py（经 sync_engine.sh 同步进星辰镜像）。

注意：
- walk_forward 在共享包中改名为 factor_walk_forward（避免与 Backtester.walk_forward 混淆），此处仍以 walk_forward 名义 re-export。
- 本垫片不改动 engine.backtest.BacktestEngine（事件驱动，属 app 层，未纳入共享包）。
"""
import sys
from pathlib import Path

# 保证 quantos_engine 包（仓库根 /app）可导入
_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from quantos_engine.backtest import (  # noqa: F401
    newey_west_t,
    portfolio_backtest,
    metrics,
    factor_signals,
    factor_walk_forward as walk_forward,
    Backtester,
)
