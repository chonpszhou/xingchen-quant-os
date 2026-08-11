# 星辰投研团

跨 A股 / 港股 / 美股 / 虚拟货币 / 期权 的多市场投研监控项目骨架。

> GitHub: https://github.com/chonpszhou/xingchen-quant-os · 详见 [docs/系统总览.md](docs/系统总览.md) 与 [docs/用户操作手册.md](docs/用户操作手册.md)

## 目录结构

```
星辰投研团/
├── datahub/                  # 统一数据访问层（A股/港股/美股/加密，多源自动降级）
│   ├── core.py               # DataHub：行情/历史/财务/期权统一接口
│   ├── store.py              # SQLite 元数据 + parquet 日线落库（增量更新）
│   └── calendar.py           # 多市场交易日历
├── factors/                  # 因子流水线 v0.1（动量/波动率/反转/量能）
│   ├── definitions.py        # 因子定义（无未来函数）
│   ├── pipeline.py           # 面板构建 + 日度IC + 分位组合
│   ├── neutralization.py     # 行业(BaoStock)去均值 + log(成交额代理) 中性化
│   ├── evaluate.py           # alpha-evaluate 方法论：标准化/IC/分位多空/单调性/评级
│   └── backtest.py           # 组合回测 + walk-forward + HAC t + DSR
├── config/
│   ├── sources.yaml        # 数据源配置（行情/财务/期权，含主备通道）
│   ├── push.yaml           # 推送通道配置（邮件 + IM 机器人）
│   ├── watchlist.json      # 默认自选股清单（结构化，可直接导入）
│   ├── watchlist.csv       # 同上，CSV 版（Excel 可直接打开）
│   └── tasks.yaml          # 自动化定时分析任务配置建议
├── scripts/
│   ├── check_connections.py # 数据源与推送通道连通性检查
│   ├── datahub_cli.py       # DataHub 命令行（update/quote/status/sample）
│   ├── backfill_a_market.py # A股指数成分/全市场批量回填（并发+断点续传）
│   ├── fetch_a_meta.py      # A股市值/行业元数据（东财单股接口）
│   ├── fetch_a_industry.py  # A股行业映射（BaoStock，中性化用）
│   ├── factor_cli.py        # 因子流水线命令行
│   ├── research_run.py      # 研究方向编排：中性化评估 + walk-forward 回测
│   ├── backfill_us_hk.py    # 美股/港股扩池回填（单线程规避 V8 崩溃）
│   ├── research_market_pool.py  # 跨市场扩池验证（美股/港股）
│   ├── research_master_signals.py # 大佬信号验证（假突破/接针）
│   ├── research_trend_following.py # CTA 趋势跟踪验证
│   ├── fetch_a_fundamentals.py  # A股季度基本面抓取（BaoStock）
│   ├── research_fundamentals.py # 基本面因子验证（价值/质量）
│   ├── build_pit_universe.py    # 点对时池构建（沪深300+中证500 月度成分）
│   ├── backfill_a_pit.py        # 点对时池行情回填（腾讯直连提速）
│   ├── fetch_a_pit_industry.py  # 点对时池行业映射
│   ├── research_pit_validation.py     # 点对时池价格因子验证
│   ├── research_pit_fundamentals.py   # 点对时池基本面验证
│   ├── options_iv_snapshot.py   # 期权 IV 监控快照（CBOE + 期权链）
│   ├── fetch_cb_panel.py        # 可转债历史面板抓取（约 1050 只）
│   ├── research_cb_double_low.py # 可转债双低策略回测（首个实盘候选）
│   ├── run_cb_double_low.py     # 双低每日监控（排名+预警）
│   ├── paper_trade_cb.py        # 双低模拟盘（20日调仓+净值跟踪）
│   ├── paper_trade_momentum.py  # 双动量模拟盘（21日调仓+SPY基准）
│   ├── paper_trade_rp.py        # 风险平价模拟盘（逆波动率配置）
│   ├── validate_paper_engines.py # 模拟盘引擎一致性校验（重放vs回测）
│   ├── research_hk_dividend.py  # 港股股息率策略验证（含分红总回报）
│   ├── research_crypto_trend.py # 加密周频趋势验证
│   ├── run_all.py               # 一键运行入口（更新/双低/IV/摘要）
│   ├── push_digest.py           # 摘要推送（邮件+IM，凭证就绪后启用）
│   ├── report_monthly.py        # 模拟盘月度报告
│   ├── fetch_futures.py         # 期货数据层（商品主力+加密永续费率）
│   ├── system_status.py         # 系统健康看板（一页总览）
│   ├── research_dual_momentum.py # 双动量ETF轮动验证（观察级最强候选）
│   ├── research_risk_parity.py   # 风险平价配置验证（稳定型底仓）
│   ├── broker.py                # 交易执行层抽象（纸面→实盘即插即用）
│   └── export_research_reports.py # 研究报告 → Obsidian
├── docs/
│   ├── 连接检查报告.md       # 带状态标识的连接检查清单（运行脚本自动生成）
│   ├── 连接检查结果.json
│   ├── 量化交易GitHub顶级项目学习笔记.md  # GitHub Top50 量化项目研读
│   ├── 量化交易支撑体系规划.md            # 量化交易软性/硬性支撑体系规划
│   ├── 量化交易GitHub知识库.md            # 全领域知识库（12 大分类，1523 候选）
│   ├── 交易大佬学习笔记.md               # YouTube(投机实验室) + X 大咖学习笔记
│   ├── obsidian_export/交易大佬学习/      # Obsidian 分类导出（7 篇，含总览 MOC）
│   ├── obsidian_export/研究报告/          # 7 篇研究报告 + 总览看板
│   ├── 跨市场扩池验证报告.md              # 美股61/港股66 低波·动量复核
│   ├── CTA趋势跟踪验证报告.md             # 14 标的跨资产趋势跟踪
│   ├── 基本面因子验证报告.md              # A股 300 只 价值/质量
│   ├── 点对时池验证报告.md                # 1111 只动态池 价格因子复核
│   ├── 点对时池基本面验证报告.md          # 动态池 价值/质量复核
│   ├── 期权IV监控快照.md                  # VIX/VXN/VXD + 个股 IV 分位
│   ├── 可转债双低策略回测报告.md           # 双低策略（HAC t 3.08）
│   ├── 港股股息率策略验证报告.md           # 股息率因子（ICIR 0.31）
│   ├── 加密趋势策略验证报告.md             # 加密趋势（观察级）
│   ├── 双动量ETF轮动验证报告.md            # ETF双动量（观察级最强候选）
│   ├── 风险平价配置验证报告.md             # 逆波动率底仓（回撤 -5.8%）
│   ├── 系统总览.md                         # 系统架构/策略/使用/风险 一页通
│   ├── 用户操作手册.md                     # 面向小白的完整操作指南
│   ├── 投研摘要_日期.md                    # 每日一键生成的投研摘要
│   ├── 模拟盘月报_日期.md                  # 月度模拟盘统计与纪律检查
│   └── github_quant_corpus.json           # 量化 GitHub 全领域语料（脚本自动生成）
├── requirements.txt            # Python 依赖清单
├── .env.example                # 凭证模板（复制为 .env 填写）
├── config/broker.yaml          # 实盘券商配置（当前 paper，实盘预留）
└── README.md
```

## 快速开始

1. **检查环境与连通性**

   ```bash
   pip install akshare yfinance ccxt pandas requests
   python3 scripts/check_connections.py
   ```

   运行后自动生成 `docs/连接检查报告.md`，每项带状态标识（✅正常 / ❌异常 / ⚠️未配置）。

2. **配置凭证**

   ```bash
   cp .env.example .env
   # 编辑 .env：邮件 SMTP、飞书/钉钉/企业微信机器人等
   python3 scripts/check_connections.py   # 复检推送通道
   ```

3. **导入自选股**

   `config/watchlist.json` 可直接读取；`watchlist.csv` 为 UTF-8 编码，Excel 双击打开。代码格式说明见 JSON 内 `code_notes`。

4. **部署定时任务**

   参考 `config/tasks.yaml` 中的 cron 表达式与落地方式（系统 crontab / APScheduler / Codex 定时提醒）。

## 数据层（DataHub）

统一收口 akshare / yfinance / 新浪 / 东方财富 / OKX / Gate，把自选股清单变成可落库的历史数据：

```bash
# 增量更新自选股日线到本地（SQLite 元数据 + parquet）
python3 scripts/datahub_cli.py update --lookback 120

# 实时行情快照
python3 scripts/datahub_cli.py quote

# 查看同步状态 / 本地日线
python3 scripts/datahub_cli.py status
python3 scripts/datahub_cli.py sample --market A股 --symbol 600519
```

多源自动降级（实测生效）：东财不稳 → 腾讯/新浪；Yahoo 限流 → 新浪美股；加密直连 OKX/Gate 兜底。本地数据目录 `data/` 已加入 .gitignore。

## 因子流水线

基于本地数据计算日频因子并做 IC / 分位验证（无未来函数，含分半稳健性检验）：

```bash
python3 scripts/factor_cli.py --markets A股 港股 美股 虚拟货币
```

输出 `data/factors/`（因子面板 / IC 汇总 / 分位组合）与 `docs/因子流水线报告.md`。当前因子：20/60 日动量、20 日波动率、5 日反转、量能异动。

## 研究方向（严谨化）

```bash
# A股指数成分批量回填（如沪深300，2 年）
python3 scripts/backfill_a_market.py --index 000300 --lookback 730 --workers 4

# 行业/市值元数据（BaoStock 行业映射 + 东财单股市值）
python3 scripts/fetch_a_industry.py
python3 scripts/fetch_a_meta.py

# 因子中性化评估 + walk-forward 组合回测（含成本/IS-OOS/DSR）
python3 scripts/research_run.py
```

产出：`docs/因子中性化与稳健性评估报告.md`、`docs/因子组合回测与WalkForward报告.md`。

## 数据源速览

| 板块 | 行情 | 财务 | 期权/衍生品 |
|------|------|------|-------------|
| A股 | 东方财富（备用：新浪） | 东方财富F10 | 50ETF/300ETF/科创50ETF 期权、波动率指数 |
| 港股 | 东方财富 | 东方财富 | 窝轮/牛熊证待接入（HKEX） |
| 美股 | Yahoo Finance（备用：东方财富） | Yahoo Finance | 个股/ETF 期权链 |
| 虚拟货币 | ccxt（币安/欧易/Bybit/Gate） | 链上/聚合数据待接入 | Deribit 期权 |

公开接口无需密钥；实盘交易与推送通道需要 `.env` 凭证。
