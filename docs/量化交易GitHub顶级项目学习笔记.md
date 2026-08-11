# 星辰投研团 · GitHub 量化交易顶级项目学习笔记（Top 50）

> 采集时间：2026-08-11（时区 Asia/Shanghai）  
> 数据口径：GitHub 公开搜索 API，13 组关键词（quantitative trading / backtesting / trading bot / 量化交易 等），按 star 数降序合并去重  
> 原始数据：[github_top50_dataset.json](github_top50_dataset.json)（139 个候选，含 README 摘要）  
> 说明：star 数为采集时点快照；已剔除明显非量化项目（funNLP、实习信息聚合、x86 汇编教程等）；已补充未进搜索前 60 但属于领域头部项目的 tushare、pythonstock、zvt

---

## 一、Top 50 总览

| # | 项目 | ★ | 语言 | 一句话定位 |
|---|------|-----|------|-----------|
| 1 | [OpenBB-finance/OpenBB](https://github.com/OpenBB-finance/OpenBB) | 71,748 | Python | 分析师/量化/AI 代理统一数据平台，覆盖股票、加密、衍生品、宏观 |
| 2 | [ZhuLinsen/daily_stock_analysis](https://github.com/ZhuLinsen/daily_stock_analysis) | 61,799 | Python | LLM 驱动的多市场股票智能分析系统：多源行情+实时新闻+决策看板+自动推送 |
| 3 | [freqtrade/freqtrade](https://github.com/freqtrade/freqtrade) | 53,158 | Python | 最流行的开源加密交易机器人，回测/优化/实盘一体 |
| 4 | [microsoft/qlib](https://github.com/microsoft/qlib) | 47,270 | Python | 微软 AI 量化平台：数据、因子、模型、回测、组合全流程 |
| 5 | [vnpy/vnpy](https://github.com/vnpy/vnpy) | 44,385 | Python | 国内最主流的 Python 量化交易开发框架（C++ 内核） |
| 6 | [ccxt/ccxt](https://github.com/ccxt/ccxt) | 43,592 | Python | 100+ 加密交易所统一交易 API |
| 7 | [HKUDS/Vibe-Trading](https://github.com/HKUDS/Vibe-Trading) | 30,553 | Python | 个人交易 Agent：一条命令接入行情/回测/实盘能力 |
| 8 | [wilsonfreitas/awesome-quant](https://github.com/wilsonfreitas/awesome-quant) | 28,663 | HTML | 量化金融精选资源大全（库/书/课程/数据） |
| 9 | [mementum/backtrader](https://github.com/mementum/backtrader) | 22,806 | Python | 事件驱动经典回测框架，社区最大 |
| 10 | [akfamily/akshare](https://github.com/akfamily/akshare) | 21,938 | Python | 中国金融数据接口全家桶（A股/港股/美股/期权/期货/宏观） |
| 11 | [QuantConnect/Lean](https://github.com/QuantConnect/Lean) | 21,155 | C# | 机构级多资产回测与实盘引擎（Python/C# 双语言） |
| 12 | [stefan-jansen/machine-learning-for-trading](https://github.com/stefan-jansen/machine-learning-for-trading) | 20,391 | Notebook | 《Machine Learning for Trading》第3版全书代码 |
| 13 | [quantopian/zipline](https://github.com/quantopian/zipline) | 20,032 | Python | Pythonic 事件驱动回测库（Quantopian 原产，已归档） |
| 14 | [hummingbot/hummingbot](https://github.com/hummingbot/hummingbot) | 19,400 | Python | 开源高频做市/套利机器人，可部署到交易所服务器 |
| 15 | [UFund-Me/Qbot](https://github.com/UFund-Me/Qbot) | 18,304 | Notebook | AI 自动量化交易机器人（A股/美股/加密，本地部署） |
| 16 | [bbfamily/abu](https://github.com/bbfamily/abu) | 18,107 | Python | 阿布量化：A股/期权/期货/加密的量化架构与教程 |
| 17 | [waditu/tushare](https://github.com/waditu/tushare) | 15,341 | Python | 老牌 A股/期货数据接口（Pro 版需积分） |
| 18 | [myhhub/stock](https://github.com/myhhub/stock) | 13,750 | Python | 股票数据/指标/筹码分布/形态识别/选股/回测/自动交易全家桶 |
| 19 | [paperswithbacktest/awesome-systematic-trading](https://github.com/paperswithbacktest/awesome-systematic-trading) | 13,148 | Python | 系统化交易精选清单（库/策略/论文/博客） |
| 20 | [goldmansachs/gs-quant](https://github.com/goldmansachs/gs-quant) | 11,924 | Python | 高盛衍生品定价/风险/交易工具包 |
| 21 | [yutiansut/QUANTAXIS](https://github.com/yutiansut/QUANTAXIS) | 10,996 | Python | 国产全流程量化平台：数据/回测/模拟/实盘/可视化，Rust 内核加速 |
| 22 | [StockSharp/StockSharp](https://github.com/StockSharp/StockSharp) | 10,544 | C# | 跨市场 C# 量化交易平台（支持全球交易所与加密） |
| 23 | [je-suis-tm/quant-trading](https://github.com/je-suis-tm/quant-trading) | 10,522 | Python | 40+ 量化策略实现（VIX、期权、统计套利、宏观指标） |
| 24 | [OpenByteInc/QuantDinger](https://github.com/OpenByteInc/QuantDinger) | 10,467 | Python | 开源 AI 交易 OS：策略代码→回测→模拟→实盘→监控 |
| 25 | [askmike/gekko](https://github.com/askmike/gekko) | 10,187 | JavaScript | Node.js 加密交易机器人（已归档，经典学习样本） |
| 26 | [shidenggui/easytrader](https://github.com/shidenggui/easytrader) | 10,054 | Python | 同花顺/miniqmt/雪球客户端自动化下单与模拟交易 |
| 27 | [huseinzol05/Stock-Prediction-Models](https://github.com/huseinzol05/Stock-Prediction-Models) | 9,481 | Notebook | 120+ 股票预测 ML/DL 模型集合（ARIMA→LSTM→强化学习） |
| 28 | [ghostfolio/ghostfolio](https://github.com/ghostfolio/ghostfolio) | 9,104 | TypeScript | 开源财富管理软件：多资产组合跟踪/绩效/报表 |
| 29 | [kernc/backtesting.py](https://github.com/kernc/backtesting.py) | 8,778 | Python | 轻量易用的回测库，代码量小、上手快 |
| 30 | [ccxt/binance-trade-bot](https://github.com/ccxt/binance-trade-bot) | 8,725 | Python | 币安网格自动交易机器人（研究用） |
| 31 | [polakowo/vectorbt](https://github.com/polakowo/vectorbt) | 8,632 | Python | 向量化回测引擎：数万参数组合秒级扫描 |
| 32 | [simonlin1212/a-stock-data](https://github.com/simonlin1212/a-stock-data) | 8,576 | Python | A股全栈数据工具包：10 层架构、47 端点、15 数据源、零鉴权 |
| 33 | [jesse-ai/jesse](https://github.com/jesse-ai/jesse) | 8,305 | Python | 进阶加密交易框架：多策略、风控、UI 一体 |
| 34 | [Rockyzsu/stock](https://github.com/Rockyzsu/stock) | 7,936 | Python | 30 天量化交易入门教程（持续更新） |
| 35 | [pythonstock/stock](https://github.com/pythonstock/stock) | 7,862 | Python | 全栈股票分析系统：akshare+pandas+MySQL+Docker+cron |
| 36 | [LuckyOne7777/LLM-Trading-Lab](https://github.com/LuckyOne7777/LLM-Trading-Lab) | 7,499 | Python | ChatGPT 管理真实小资金账户的实验项目 |
| 37 | [cantaro86/Financial-Models-Numerical-Methods](https://github.com/cantaro86/Financial-Models-Numerical-Methods) | 7,318 | Notebook | 量化金融数值方法交互式笔记本（期权定价/随机过程/计量） |
| 38 | [ricequant/rqalpha](https://github.com/ricequant/rqalpha) | 6,658 | Python | 米筐开源回测/实盘框架，A股友好 |
| 39 | [Drakkar-Software/OctoBot](https://github.com/Drakkar-Software/OctoBot) | 6,346 | Python | 带 Web UI 的加密交易机器人（AI/网格/DCA/跟单） |
| 40 | [wondertrader/wondertrader](https://github.com/wondertrader/wondertrader) | 6,255 | C++ | 全市场 C++ 量化框架：175ns 超低延迟引擎，机构级 |
| 41 | [waditu/czsc](https://github.com/waditu/czsc) | 5,714 | Rust | 缠论技术分析工具（缠论+量化+股票/期货） |
| 42 | [google/tf-quant-finance](https://github.com/google/tf-quant-finance) | 5,469 | Python | TensorFlow 高性能金融计算库（蒙特卡洛/期权定价） |
| 43 | [fmzquant/strategies](https://github.com/fmzquant/strategies) | 5,365 | 多语言 | 发明者量化官方策略库（JS/Python/C++/PineScript） |
| 44 | [freqtrade/freqtrade-strategies](https://github.com/freqtrade/freqtrade-strategies) | 5,351 | Python | freqtrade 社区策略合集 |
| 45 | [1nchaos/adata](https://github.com/1nchaos/adata) | 5,073 | Python | 免费开源 A股量化数据库，专注行情/财务/资金 |
| 46 | [shinnytech/tqsdk-python](https://github.com/shinnytech/tqsdk-python) | 4,937 | Python | 天勤期货量化 SDK：实时行情/历史数据/实盘交易 |
| 47 | [wangzhe3224/awesome-systematic-trading](https://github.com/wangzhe3224/awesome-systematic-trading) | 4,845 | HTML | 中文系统化交易精选清单 |
| 48 | [gbeced/pyalgotrade](https://github.com/gbeced/pyalgotrade) | 4,664 | Python | 老牌 Python 算法交易/回测库 |
| 49 | [nkaz001/hftbacktest](https://github.com/nkaz001/hftbacktest) | 4,350 | Rust | 高频做市回测框架：逐笔订单簿重建+订单排队模拟 |
| 50 | [zvtvz/zvt](https://github.com/zvtvz/zvt) | 4,259 | Python | 模块化量化框架：数据中台+选股+回测+复现交易思想 |

---

## 二、分类研读（50 个项目，7 大类）

### A. 数据源与行情接口（9 个）

**共同范式**：把“数据获取”从策略里彻底解耦；统一封装多数据源、自动降级、缓存与增量更新；接口设计追求“一行代码拿全市场快照”。

- **akshare**（★21,938）：中国金融数据事实标准之一。覆盖 A股/港股/美股/ETF/期权/期货/债券/宏观/资金流，全部免费无鉴权。我们的连接检查脚本就是直接用它做连通性验证（东财+新浪双通道）。**掌握要点**：`stock_zh_a_spot_em`（全市场快照）、`stock_zh_a_hist`（历史K线复权）、`option_current_em`（期权实时）、`index_option_300etf_qvix`（波动率指数）——与本项目 watchlist/tasks 的字段一一对应。
- **tushare**（★15,341）：老牌接口，Pro 版数据质量高（复权因子/财务/龙虎榜/资金流），但需积分/Token。**掌握要点**：适合做 akshare 的“高质量补充层”，对应 sources.yaml 里的 `TUSHARE_TOKEN` 可选增强项。
- **ccxt**（★43,592）：100+ 交易所统一接口。**掌握要点**：统一 `fetch_ticker/fetch_ohlcv/fetch_order_book` 语义；我们的检查已实测 OKX/Gate/Deribit 可达、Binance 地区限制，正好验证了 ccxt 多交易所轮询的必要性。
- **OpenBB**（★71,748）：把股票/加密/衍生品/宏观/新闻统一成可插拔 Provider。**掌握要点**：Provider 抽象层设计（同一种数据格式、多后端），值得借鉴来改造我们的 sources.yaml 为主备 Provider 架构。
- **a-stock-data**（★8,576）：A股“全栈数据”：行情/研报/资金面/筹码/公告/打板/ETF期权/舆情，47 端点、15 数据源、零鉴权。**掌握要点**：10 层架构分层（原始→清洗→指标→事件），覆盖比 akshare 更细的筹码与舆情维度，可直接补强我们的 A股观察池。
- **adata**（★5,073）：免费开源 A股数据库，行情/财务/资金。**掌握要点**：本地缓存+增量更新设计，适合作为每日收盘任务的落库层。
- **zvt**（★4,259）：数据中台思路——统一数据模型、自动爬取、技术面/基本面/资金面齐备。**掌握要点**：`Entity`+`Factor`+`Trader` 三层模型，对我们自选股清单（entity）与自动化任务（factor/trader）的分层有直接参考价值。
- **myhhub/stock**（★13,750）：数据→指标（筹码分布）→形态识别→综合选股→回测→自动交易一条龙。**掌握要点**：筹码分布/形态识别可作为我们“异动预警”的补充信号源。
- **pythonstock/stock**（★7,862）：pandas+akshare+MySQL+Docker+cron 的全栈落地样本。**掌握要点**：每天 18:00 cron 抓取计算、3 天数据缓存、防封策略——正是我们 tasks.yaml 每日收盘任务要落地的工程模式。

### B. 回测引擎与交易框架（10 个）

**共同范式**：事件驱动 vs 向量化两条路线；统一抽象为“数据 feed → 策略信号 → 订单/撮合 → 账户/风控 → 绩效统计”管线。

- **backtrader**（★22,806）：社区最大、文档最全的 Python 回测框架。**掌握要点**：`Cerebro/Strategy/DataFeed/Order` 概念；支持多资产、多周期、滑点/佣金、实盘复用同一策略类。适合做我们 A股/港股策略的基线回测引擎。
- **zipline**（★20,032）：Quantopian 事件驱动回测库，与 Alphalens（因子分析）、Pyfolio（绩效）配套。**掌握要点**：`initialize/handle_data` 的流水线写法；注意项目已归档，新项目建议用维护中的替代品（如 zipline-reloaded）。
- **Lean**（★21,155）：QuantConnect 机构级引擎，多资产（含期权数据）、多时区、云回测。**掌握要点**：算法/数据/执行/风险四个模块分离；`Initialize/OnData` 模型；回测统计口径（Sharpe、Sortino、最大回撤、盈亏比）是我们的周报/月报应该对齐的指标体系。
- **vectorbt**（★8,632）：向量化回测，千级参数组合秒扫。**掌握要点**：以 NumPy 向量运算代替逐 bar 循环；适合参数扫描、敏感性分析与“异动扫描”这类批量任务。
- **backtesting.py**（★8,778）：轻量、代码极少、带交互式图表。**掌握要点**：最适合快速验证单策略想法；性能弱于 vectorbt。
- **pyalgotrade**（★4,664）：老牌事件驱动库。**掌握要点**：Bar/Strategy/Broker 模型清晰，适合读源码学架构。
- **rqalpha**（★6,658）：米筐开源框架，A股模拟撮合贴近国内规则。**掌握要点**：支持日线/分钟、涨跌停/停牌处理、组合报告；A股回测优先考虑。
- **hftbacktest**（★4,350）：逐笔 L2/L3 订单簿重建 + 订单排队位置模拟的高频回测。**掌握要点**：做市/高频策略必须用它，普通日频策略不需要；对我们“期权做市/加密网格”备选场景有用。
- **QUANTAXIS**（★10,996）：数据/回测/模拟/实盘/可视化全流程，Rust 内核（QARS2）加速。**掌握要点**：任务调度+分布式部署的设计，适合团队化使用；QIFI 协议可作为账户/持仓数据交换标准。
- **wondertrader**（★6,255）：C++ 核心、全品种、175ns 低延迟引擎。**掌握要点**：面向机构实盘；个人研究阶段了解其 UFT 引擎与 wtpy 桥接即可，暂不引入。

### C. AI/机器学习量化（9 个）

**共同范式**：把因子/特征工程、模型训练、回测、组合优化串成管线；近年明显向“LLM Agent 驱动研究→交易”演进。

- **qlib**（★47,270）：微软 AI 量化平台。**掌握要点**：数据层（`ExpressionEngine` 高频因子）、模型层（LightGBM/GRU/Transformer 等 50+ 模型）、回测层（`NestedDecisionExecutor` 滚动训练）、组合优化（TopkDropout）。是我们做机器学习因子研究的首选框架。
- **machine-learning-for-trading**（★20,391）：《ML for Trading》3 版全书代码，从数据源到因子、模型、NLP、强化学习。**掌握要点**：按章节系统地学习 Alpha 因子、交叉验证、回测中的偏差陷阱——与我们 backtest-expert 理念一致。
- **Qbot**（★18,304）：AI 量化机器人，本地部署，A股/美股/加密。**掌握要点**：集成回测（backtrader）+实盘（vnpy/easytrader）+LLM 策略生成，是把“研究→实盘”串起来的完整样例。
- **Stock-Prediction-Models**（★9,481）：120+ 预测模型集合。**掌握要点**：适合横向对比传统统计/ML/DL 在涨跌预测上的真实水平，警惕过拟合——学习价值大于实用价值。
- **tf-quant-finance**（★5,469）：Google 的 GPU 金融计算库。**掌握要点**：蒙特卡洛路径模拟、IR 曲线、期权定价；期权波动率/对冲计算可复用其数值方法。
- **Vibe-Trading**（★30,553）：LLM 交易 Agent 一站式接入。**掌握要点**：一条命令装配行情/回测/实盘工具链，反映“Agent 编排”成为量化新范式；适合我们评估 LLM 辅助投研的边界。
- **QuantDinger**（★10,467）：AI Trading OS，研究→策略代码→回测→模拟→实盘→监控闭环，支持 Agent/MCP。**掌握要点**：与我们“自动化任务+推送”架构最接近的样板，MCP/Agent 接口值得借鉴。
- **LLM-Trading-Lab**（★7,499）：真实小资金账户由 LLM 决策的实验。**掌握要点**：LLM 实盘风险控制（仓位上限、人工审批）设计比模型本身更重要。
- **daily_stock_analysis**（★61,799）：LLM 多市场智能分析，多源行情+实时新闻+决策看板+自动推送、零成本定时运行。**掌握要点**：与我们星辰投研团的目标高度重合——建议直接拆解它的“数据采集→LLM 分析→定时推送”链路，作为我们 tasks.yaml 落地时的对标实现。

### D. 交易平台与自动化机器人（10 个）

**共同范式**：策略与执行解耦；统一网关（行情/交易/账户）；支持模拟盘→实盘平滑切换；回测与实盘共享策略代码。

- **vnpy**（★44,385）：国内机构级标准框架。**掌握要点**：`Gateway/Engine/App` 插件化架构，CTA/期权/套利/组合管理 App；C++ 内核保证性能。做 A股/期货/期权实盘时优先考虑。
- **freqtrade**（★53,158）：加密机器人事实标准。**掌握要点**：策略类（`populate_indicators/populate_entry_trend`）、`hyperopt` 参数优化、`dry-run` 模拟盘、Telegram 通知——其“策略+优化+通知”模式可直接映射我们的加密任务与推送配置。
- **hummingbot**（★19,400）：做市/套利机器人，可部署在交易所机房。**掌握要点**：`Connector` 抽象对接各大交易所；适合加密网格/做市策略。
- **jesse**（★8,305）：多策略、多交易所、内置风控与 UI。**掌握要点**：`Strategy` 生命周期清晰（`before/next/after`），路由/组合配置化。
- **OctoBot**（★6,346）：Web UI 可视化配置的加密机器人。**掌握要点**：面向非程序员的可视化策略编排，适合快速验证策略想法。
- **gekko**（★10,187）：经典 Node.js 加密机器人（已归档）。**掌握要点**：读源码学习技术指标计算与回测实现即可，不建议新项目使用。
- **binance-trade-bot**（★8,725）：币安自动化网格交易（研究用）。**掌握要点**：网格参数与止损逻辑可参考，但需注意币安接口策略已变化。
- **easytrader**（★10,054）：同花顺客户端/miniqmt/雪球的 A股自动化下单。**掌握要点**：个人 A股实盘落地最常用通道；对应我们 sources/push 里“实盘执行层”的候选。
- **StockSharp**（★10,544）：C# 跨市场平台，支持全球交易所与加密。**掌握要点**：连接器生态最全，适合 C# 技术栈团队。
- **abu**（★18,107）：阿布量化，A股/期权/期货/加密，自带教程与可视化。**掌握要点**：`AbuFactor/AbuPosition` 因子与仓位模型、环境回测，中文资料全，适合系统学习。

### E. 金融工程与衍生品（3 个）

- **gs-quant**（★11,924）：高盛 25 年衍生品经验沉淀。**掌握要点**：`Greeks/IR/Pricing/Vol` 模块覆盖期权定价、波动率曲面、风险指标——我们 tasks.yaml 里“期权 IV rank/期限结构”可参考其波动率建模口径。
- **Financial-Models-Numerical-Methods**（★7,318）：量化金融数值方法交互笔记本。**掌握要点**：布朗运动、期权定价（BS/二叉树/蒙特卡洛）、计量模型；期权维度的学习入口。
- **tqsdk-python**（★4,937）：天勤期货量化 SDK。**掌握要点**：期货实时行情/历史/实盘一体，未来若要覆盖商品期货可直接接入。

### F. 策略库与学习资源（8 个）

- **awesome-quant**（★28,663）：全球量化资源索引。**掌握要点**：按语言/数据/回测/策略/加密分类，是持续检索新工具的第一入口。
- **awesome-systematic-trading**（★13,148 / ★4,845）：英文与中文两套系统化交易清单。**掌握要点**：覆盖论文、博客、数据集、策略思路。
- **je-suis-tm/quant-trading**（★10,522）：40+ 策略代码（VIX、期权、统计套利、宏观）。**掌握要点**：每个策略带理论讲解，适合当“策略算法词典”翻阅。
- **fmzquant/strategies**（★5,365）：发明者量化官方策略库（多语言）。**掌握要点**：大量可直接改用的 A股/期货/加密策略模板。
- **freqtrade-strategies**（★5,351）：社区加密策略合集。**掌握要点**：与 freqtrade 配套，研究他人策略的结构与参数。
- **Rockyzsu/stock**（★7,936）：30 天量化入门教程。**掌握要点**：适合给团队新人做快速入门教材。
- **czsc**（★5,714）：缠论技术分析工具（Rust）。**掌握要点**：把主观的“缠论”转成可量化信号，作为技术面信号之一可选。

### G. 组合管理与投研应用（1 个）

- **ghostfolio**（★9,104）：开源财富管理软件。**掌握要点**：多资产组合跟踪、绩效归因、税务报表；可参考其“组合视图+报告”设计来做我们自选股组合仪表盘。

---

## 三、对「星辰投研团」的落地借鉴清单

| 我们的模块 | 借鉴项目 | 具体做法 |
|-----------|---------|---------|
| 数据源层（sources.yaml） | akshare、tushare、ccxt、OpenBB、a-stock-data、adata | 把数据源改造成 Provider 抽象：同一查询语义（quote/history/finance/option）对接多后端，自动降级——和我们检查脚本已验证的“东财→新浪、Yahoo→东财、Binance→OKX/Gate”降级链一致 |
| 自选股层（watchlist） | zvt、ghostfolio | 引入 `Entity + Factor + Trader` 分层模型；为每条自选股补充持仓/基准/工具三类属性，输出组合仪表盘 |
| 回测层 | backtrader、vectorbt、backtesting.py、rqalpha、qlib | 日常策略验证用 backtesting.py；参数扫描用 vectorbt；A股规则模拟用 rqalpha；ML 因子研究用 qlib；绩效口径对齐 Lean（Sharpe/回撤/盈亏比） |
| 异动/预警任务（tasks.yaml） | daily_stock_analysis、myhhub/stock、a-stock-data | 增加筹码分布、形态识别、资金流、舆情作为异动信号源；按“数据采集→分析→推送”三步实现，推送沿用现有 IM+邮件分级 |
| 加密任务 | freqtrade、hummingbot、jesse | 加密异动扫描复用 freqtrade 的 dry-run 与通知模式；网格/做市策略参考 hummingbot |
| 期权/衍生品 | gs-quant、tf-quant-finance、tqsdk-python | IV rank/期限结构计算参考 gs-quant 口径；期权定价数值方法用 tf-quant-finance/Financial-Models 教程；后续如需商品期货接 tqsdk |
| AI/LLM 投研 | qlib、Vibe-Trading、QuantDinger、LLM-Trading-Lab | 先上“LLM 辅助分析+人工确认”（日报/周报摘要），实盘决策暂不开放给 LLM；评估 QuantDinger 的 Agent/MCP 编排 |
| 工程化 | pythonstock/stock、QUANTAXIS | 定时抓取+cache 防封、任务调度、分布式部署——作为我们自动化任务的生产化模板 |

## 四、学习路线建议（按阶段）

1. **数据关（1-2 周）**：akshare + tushare + ccxt 三种数据源各跑通一遍，覆盖 A股/港股/美股/加密/期权五类标的（本项目 watchlist 就是练习清单）。
2. **回测关（2-3 周）**：backtesting.py 写第一个均线策略 → backtrader 做多资产回测 → vectorbt 做参数扫描 → rqalpha 验证 A股规则。
3. **策略/因子关（3-4 周）**：跟 je-suis-tm/quant-trading 复现 10 个经典策略；用 qlib 跑通一个 Alpha 因子（LightGBM）管线。
4. **衍生品关（2 周）**：Financial-Models-Numerical-Methods 过期权定价；gs-quant 学希腊字母与 IV 建模；对接我们 tasks.yaml 的期权波动率监控。
5. **实盘/风控关（持续）**：vnpy（A股/期货）、freqtrade（加密）dry-run 各跑一个月，重点练风控：仓位、止损、回撤熔断；绩效口径对齐 Lean。
6. **AI/LLM 关（按需）**：Vibe-Trading / QuantDinger 拆解 Agent 编排；daily_stock_analysis 对标我们的日报推送链路。

---

> 风险提示：榜单中部分项目已归档或停止维护（gekko、zipline、pyalgotrade 等），学习其架构思想即可，生产选型优先维护活跃的项目。所有项目仅作学习参考，不构成投资建议。
