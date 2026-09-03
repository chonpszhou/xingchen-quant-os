"""quantos_engine — paddy 与星辰投研团共享的量化回测/验证引擎单一真源。

Phase 1 抽取目标：消除三处引擎副本（paddy src/engine、xingchen engine、xingchen factors），
让「同一权重序列 → 两引擎 NAV 一致」「DSR/PSR 数学单点」由单一代码保证。

已纳入（向量化核 + DSR 数学 + 信号库 + 验证闸门）：
- backtest.Backtester（原 paddy src/engine/backtest.py，Phase 0 成本模型已对齐 pos 参数/WF 回看）
- backtest.portfolio_backtest / metrics（原 xingchen factors/backtest.py，DSR 用 per-period 夏普 + 普通峰度）
- backtest 的 8 个信号函数 + _STRATS 注册表（原 paddy）
- features.ml_reversal_signal（原 paddy ML 特征层）
- significance（PSR/DSR/BH 校正，原 paddy src/engine/significance.py）
- quality_filter（第四道闸门，paddy 与 xingchen 逐字相同，W1-② 单一真源）
- self_review（11 项机械自查，paddy src/utils 与 xingchen engine 逐字相同，W1-② 单一真源）
- optimizer.ParameterOptimizer（原 paddy src/engine/optimizer.py，W1-② 单一真源）
- strategies.StrategyRegistry（动态方法库：方法注册即生效、可回测、可版本化，**无五道闸**；
  五道闸仅用于"晋升实盘"路径，见 strategies.py 设计说明）

留在其各自仓 app 层（范式不同，未纳入共享包）：
- xingchen engine/backtest.py 的 BacktestEngine（事件驱动、耦合 executor/risk/exit）
- xingchen engine/optimizer.py 的 optimize()（事件驱动 live 路径，依赖 BacktestEngine；
  其 QualityFilter / metrics(DSR) 已并入本包，故该模块仅靠 re-export 垫片即可零改动运行）
"""
