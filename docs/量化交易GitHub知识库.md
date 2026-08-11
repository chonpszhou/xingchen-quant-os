# 量化交易 GitHub 知识库

> 版本：v1.0 · 整理时间：2026-08-11  
> 语料范围：GitHub 公开检索，69 组关键词 × 12 大领域，1523 个候选项目，前 250 抓取 README 摘要  
> 原始数据：[github_quant_corpus.json](github_quant_corpus.json) ｜ 配套：量化交易GitHub顶级项目学习笔记.md（Top50 逐项目研读）  
> 用途：作为「星辰投研团 + paddy-quant-workbench」的选型地图与方法论底座

---

## 一、生态全景与三大趋势

GitHub 量化生态按 star 分布高度集中：数据层（yfinance/akshare/ccxt）、回测层（backtrader/vectorbt/Lean）、平台层（vnpy/freqtrade）仍是地基；但 2025-2026 年最显著的变化是 **LLM Agent 化**。

### 趋势 1：LLM 多智能体框架爆发（当前最大增长点）

- **TradingAgents**（★97,322）及中文版 **TradingAgents-CN**（★31,043）：多 Agent 辩论式投研框架（分析师/研究员/交易员角色辩论后决策），是当前 star 第一的量化项目
- **Vibe-Trading**（★30,555）、**QuantDinger**（★10,467）、**daily_stock_analysis**（★61,799）：Agent 一站式「研究→策略→回测→实盘→监控」闭环
- MCP 化：**tradingview-mcp**、**financial-datasets/mcp-server** 把行情/数据集变成 Agent 工具
- 认知：LLM 量化当前更适合「辅助研究/分析/复盘」，实盘决策仍需人审 + 风控兜底（LLM-Trading-Lab 已用真实小资金验证边界）

### 趋势 2：数据与工程化成为主线

- 单点工具极强：**yfinance**（★25,000）、**FinanceDatabase**（30 万+ 标的索引）、**akshare**（A股全家桶）、**ccxt**（100+ 交易所统一接口）
- 本地化/零运维兴起：**free-stockdb**（A股本地量化引擎+增量同步）、**tickflow-stock-panel**（A股选股监控回测工作台）、**a-stock-data**（A股 47 端点零鉴权）
- 认知：生态不缺策略，缺的是「干净、可持续、可复现的数据管线」——这正是本知识库与星辰投研团连接检查的着力点

### 趋势 3：多市场专业化与国产 A股生态繁荣

- 加密：多交易所（passivbot/bybit/okx/gate）、Rust 高性能（barter-rs/hftbacktest）
- A股：vnpy/QUANTAXIS/abu/easytrader/hikyuu/adata 等成熟框架 + AI 分析工具（go-stock、aiagents-stock、TradingAgents-astock）密集涌现
- 衍生品：gs-quant（高盛）、FinancePy、optlib 补齐期权定价与风险口径

---

## 二、分类知识库（C1-C12）

### C1 · 数据与接口

**关键认知**

- 数据是量化第一瓶颈：框架随便选，数据管线必须自己搭（清洗/代码映射/复权/增量/缓存）
- 免费源按市场分工：A股用 akshare/adata/tushare；美股用 yfinance/FinanceDatabase；加密用 ccxt；宏观另类按需接
- 多源互为备份是刚需（本环境已实测：东财 push2 不稳 → 新浪兜底；Yahoo 限流 → 东财兜底；Binance 451 → OKX/Gate 兜底）
- MCP 接口正在把数据源变成 Agent 可调用的标准工具

**代表项目**

- **yfinance**（★25,000）：Yahoo 金融数据事实标准，美股/ETF/期权链，延迟 15 分钟
- **ccxt**（★43,592）：100+ 加密交易所统一 API（行情/交易/账户）
- **akshare**（★21,938）：中国金融数据接口全家桶，免费无鉴权
- **FinanceDatabase**（★8,328）：30 万+ 标的信息索引（权益/ETF/指数/加密）
- **a-stock-data**（★8,577）：A股全栈数据（行情/研报/资金/筹码/公告/期权/舆情），47 端点零鉴权
- **adata**（★5,074）：免费开源 A股量化数据库
- **alpha_vantage**（★4,887）：Alpha Vantage API 封装（日频/宏观）
- **efinance**（★3,928）：基金/股票/债券/期货数据快速获取
- **Ashare**（★3,748）：A股实时行情最简封装
- **free-stockdb**（★1,948）：A股日K/分钟K/ETF 本地量化引擎，增量同步+复权
- **FinMind**（★2,750）：50+ 金融数据开放接口
- **jqdatasdk**（★1,361）：聚宽数据 SDK（需权限）
- **findatapy**（★2,096）：彭博/Quandl/FRED 统一封装

### C2 · 回测与交易框架

**关键认知**

- 两条路线：事件驱动（backtrader/Lean/zipline，贴近实盘）vs 向量化（vectorbt/backtesting.py，快）
- 回测口径必须固定：收益/最大回撤/夏普/胜率/盈亏比 + walk-forward；否则「回测惊艳、实盘翻车」
- A股规则（T+1/涨跌停/停牌）需要专门的 A股引擎（rqalpha/QUANTAXIS/hikyuu）
- 高性能路线：Rust（barter-rs）/ C++（hikyuu/wondertrader），个人研究阶段非必需

**代表项目**

- **backtrader**（★22,806）：社区最大事件驱动回测框架
- **Lean**（★21,155）：QuantConnect 机构级引擎，Python/C#，多资产
- **zipline**（★20,031）：Quantopian 事件驱动回测（已归档，学习用）
- **vectorbt**（★8,632）：向量化回测，千级参数扫描秒级完成
- **backtesting.py**（★8,778）：轻量回测，上手最快
- **rqalpha**（★6,658）：米筐开源，A股规则模拟友好
- **QUANTAXIS**（★10,996）：国产全流程平台（数据/回测/模拟/实盘），Rust 内核加速
- **hikyuu**（★3,426）：C++/Python 超高速量化研究框架（A股）
- **bt**（★2,959）：灵活的回测管线（组合层友好）
- **fastquant**（★1,753）：ML 策略回测优化一体化
- **QSTrader**（★3,430）：QuantStart 事件驱动模拟引擎（学习架构）
- **pybroker**（★3,478）：ML 事件驱动回测框架
- **lumibot**（★1,903）：AI 交易 Agent + 回测一体化
- **barter-rs**（★2,221）：Rust 事件驱动交易框架（高频友好）
- **akquant**（★1,981）：akshare 配套高性能研究框架

### C3 · AI/机器学习量化

**关键认知**

- 按能力分层：因子挖掘（qlib/mlfinlab）→ 预测模型（LSTM/Transformer）→ 决策（RL/FinRL）→ Agent 研究（TradingAgents）
- 最大陷阱是过拟合：预测类项目（Stock-Prediction-Models 等）学习其方法、警惕其结论
- RL 量化门槛高、样本效率低，适合研究不适合个人实盘起步
- LLM Agent 框架的落地价值在「研究自动化」，不在「替代交易员」

**代表项目**

- **TradingAgents**（★97,322）：多 Agent 辩论式金融交易框架（LLM）
- **TradingAgents-CN**（★31,043）：中文增强版，适配 A股数据源（龙虎榜/游资）
- **Vibe-Trading**（★30,555）：个人交易 Agent 一站式接入
- **machine-learning-for-trading**（★20,392）：ML 交易教材全书代码
- **Qbot**（★18,304）：AI 量化机器人（A股/美股/加密，本地部署）
- **mlfinlab**（★4,902）：金融机器学习实验室（Lopez de Prado 方法论）
- **tensortrade**（★6,618）：强化学习交易框架
- **FinRL**（★3,543）：FinRL-X，金融强化学习基础设施
- **TradeMaster**（★2,964）：强化学习量化平台
- **QuantDinger**（★10,466）：AI 交易 OS（研究→策略→实盘闭环）
- **Stock-Prediction-Models**（★9,481）：120+ 预测模型集合（警惕过拟合）
- **pybroker**（★3,478）：ML 回测框架
- **QuantMuse**（★2,833）：AI 综合量化交易系统
- **Vibe-Research**（★1,951）：个人交易研究 Agent
- **surpriver**（★1,871）：机器学习提前发现异动大票

### C4 · 交易平台与机器人

**关键认知**

- 平台选型看三件事：回测与实盘是否共享策略代码、风控是否内建、是否支持多账户/多市场
- 加密机器人成熟度最高（freqtrade/hummingbot），但多数项目「交易能力强、风控弱」，实盘必须自补风控
- 个人 A股实盘路径：easytrader/easyquant（客户端自动化）或 vnpy（机构级）
- 大量老项目已归档（gekko/zenbot/catalyst/pyalgotrade）：学习架构，别用于生产

**代表项目**

- **freqtrade**（★53,159）：加密交易机器人事实标准（dry-run/超参优化/通知）
- **vnpy**（★44,385）：国内机构级 Python 量化框架（C++ 内核）
- **hummingbot**（★19,400）：开源做市/套利机器人
- **jesse**（★8,305）：加密交易框架（多策略/风控/UI）
- **OctoBot**（★6,349）：带 Web UI 的加密机器人（AI/网格/DCA）
- **easytrader**（★10,055）：同花顺/miniqmt/雪球自动化下单
- **easyquant**（★3,662）：A股量化框架（行情+交易）
- **StockSharp**（★10,544）：C# 跨市场平台
- **catalyst**（★2,561）：加密资产算法交易库（归档）
- **blankly**（★2,464）：跨平台回测+实盘一体化
- **passivbot**（★2,050）：Bybit/Bitget/OKX/Gate 多所机器人
- **bbgo**（★1,660）：Go 语言现代加密交易框架
- **opentrader**（★2,814）：开源加密机器人（DCA/网格）
- **gocryptotrader**（★3,454）：Go 多所交易平台
- **Superalgos**（★5,608）：可视化加密机器人平台

### C5 · 策略库

**关键认知**

- 策略库的价值在「信号函数 + 参数 + 回测结果」三件套，而不是代码本身
- 主流风格：趋势跟踪（均线/动量）、均值回归（布林/RSI）、套利（跨所/三角/配对）、事件（财报/公告/舆情）
- 同策略多参数=过拟合温床；策略库应配「参数稳健性」检查而非堆参数

**代表项目**

- **quant-trading**（★10,522）：40+ 策略实现（VIX/期权/统计套利/宏观）
- **fmzquant/strategies**（★5,365）：发明者量化官方策略库（多语言）
- **freqtrade-strategies**（★5,351）：freqtrade 社区策略合集
- **NostalgiaForInfinity**（★3,357）：高频迭代的 freqtrade 策略
- **QuantResearch**（★3,000）：量化分析与策略回测合集
- **Gekko-Strategies**（★1,434）：Gekko 策略+回测结果（学习）
- **smart-money-concepts**（★1,924）：聪明钱概念（流动性/订单块）策略包
- **QuantaAlpha**（★1,391）：量化策略发现工具

### C6 · 金融工程与衍生品

**关键认知**

- 期权/衍生品是知识密度最高的一块：定价（BS/二叉树/蒙特卡洛）、Greeks、IV 曲面、期限结构
- 生产级口径参考 gs-quant（高盛 25 年沉淀）；数值方法学习用 Financial-Models 教程
- 与星辰投研团期权任务对接：IV rank/期限结构/HV 对比的口径直接借鉴 gs-quant

**代表项目**

- **gs-quant**（★11,924）：高盛衍生品定价/风险/交易工具包
- **tf-quant-finance**（★5,469）：TensorFlow 高性能金融计算（蒙特卡洛）
- **Financial-Models-Numerical-Methods**（★7,318）：量化金融数值方法交互教程
- **FinancePy**（★3,101）：Python 金融库（定价/收益率/风险）
- **optlib**（★1,629）：期权定价库（二叉树/解析解）
- **RustQuant**（★1,795）：Rust 量化金融库
- **QuantEcon.py**（★2,387）：量化经济学/金融学习库
- **quant-wiki**（★4,032）：量化知识开源 Wiki
- **quant-mind**（★2,423）：Agent 原生知识提取（LLM 应用）

### C7 · 因子与组合

**关键认知**

- 因子研究标准流水线：数据 → 因子计算 → 分层回测/IC → Alphalens 归因 → 组合优化
- 组合优化不是「预期收益最大化」，而是风险预算/约束下的权衡（PyPortfolioOpt/Riskfolio 提供了完整口径）
- 因子衰减快：需要持续迭代与定期失效检验

**代表项目**

- **alphalens**（★4,408）：因子性能分析事实标准（Quantopian）
- **PyPortfolioOpt**（★5,952）：组合优化（有效前沿/风险模型）
- **Riskfolio-Lib**（★4,437）：组合优化与风险配置
- **cvxportfolio**（★1,246）：斯坦福凸优化组合回测
- **skfolio**（★2,091）：scikit-learn 风格组合优化
- **AutoHedge**（★4,144）：自主对冲基金框架
- **deepdow**（★1,182）：深度学习组合优化
- **QuantMuse**（★2,833）：含因子与组合的 AI 量化系统

### C8 · 技术分析与指标

**关键认知**

- TA 指标是策略的「零件库」而非策略本身；同样指标不同参数结果天差地别
- 缠论（czsc/chan.py）等本土体系已工具化，可作为技术面信号之一
- 指标库选型看性能与可维护性：Python 用 ta/finta，Java 用 ta4j，Go 用 indicator

**代表项目**

- **ta**（★5,140）：Pandas/Numpy 技术指标库
- **ta4j**（★2,480）：Java 技术分析库
- **techan.js**（★2,435）：JavaScript 图表技术分析
- **finta**（★2,264）：常见金融指标实现
- **czsc**（★5,714）：缠论技术分析工具（Rust 内核）
- **chan.py**（★2,006）：开源缠论实现（形态/动力学/区间套）
- **smart-money-concepts**（★1,924）：聪明钱概念指标
- **python-tradingview-ta**（★1,247）：TradingView 技术分析封装
- **indicator**（★1,222）：Go 技术指标库

### C9 · 加密专项

**关键认知**

- 加密特色：7x24、资金费率、合约/期权、链上数据、跨所套利；行情用 ccxt 统一，链上用链上分析工具
- 地区限制真实存在（Binance 451），多所轮询是必选项
- 做市/套利是加密量化最活跃的细分（hummingbot/tribeca/passivbot）

**代表项目**

- **ccxt**（★43,592）：100+ 交易所统一 API
- **python-binance**（★7,197）：币安 Python SDK
- **hummingbot**（★19,400）：做市/套利机器人
- **gocryptotrader**（★3,454）：Go 多所交易平台
- **goex**（★1,991）：Go 交易所 REST SDK
- **solana-trading-bot**（★2,323）：Solana 链上交易机器人
- **cryptocurrency-arbitrage**（★1,278）：跨所套利计算器
- **exchange-api**（★2,570）：200+ 货币汇率免费 API

### C10 · 高频做市

**关键认知**

- HFT/做市的核心是「延迟 + 订单簿重建 + 订单排队模拟」，普通日频框架不适用
- 个人阶段学习为主：hftbacktest 回测、tribeca 做市架构、HFT-Orderbook 订单簿实现
- 高频实盘门槛极高（机房/延迟/成本），建议聚焦于「低频做市/网格」类策略

**代表项目**

- **hftbacktest**（★4,350）：逐笔订单簿重建+排队模拟回测（Rust/Python）
- **tribeca**（★4,115）：加密做市机器人（Go）
- **barter-rs**（★2,221）：Rust 事件驱动框架（高频友好）
- **HFT-Orderbook**（★1,382）：限价订单簿实现（学习）
- **SGX 订单簿策略**（★2,325）：新加坡交易所逐笔数据 HFT 策略
- **High-Frequency-Trading-Model-with-IB**（★2,913）：IB 高频模型（学习）

### C11 · A股专项

**关键认知**

- A股生态是国产量化最强板块：框架（vnpy/QUANTAXIS/hikyuu）、数据（akshare/adata/a-stock-data）、执行（easytrader/openctp）、AI 分析（TradingAgents-astock/go-stock）全覆盖
- A股规则（T+1/涨跌停/停牌/龙虎榜/游资）必须内建到数据与回测层，通用框架需二次开发
- 标的池与事件数据（财报/解禁/龙虎榜）是 A股研究的差异化数据

**代表项目**

- **vnpy**（★44,385）：机构级框架
- **QUANTAXIS**（★10,996）：全流程平台
- **abu**（★18,107）：阿布量化（股票/期权/期货/加密）
- **easytrader**（★10,055）：客户端自动化执行
- **a-stock-data**（★8,577）：A股全栈数据
- **adata**（★5,074）：A股量化数据库
- **czsc**（★5,714）：缠论工具
- **hikyuu**（★3,426）：C++ 高速研究框架
- **efinance**（★3,928）：数据快速获取
- **MyTT**（★2,823）：通达信/同花顺指标公式移植 Python
- **openctp**（★2,892）：CTP/XTP/TORA/OST 柜台统一接口
- **TradingAgents-astock**（★2,796）：A股多 Agent 投研（龙虎榜/游资）
- **go-stock**（★7,207）：AI 选股/资金/财务分析
- **tickflow-stock-panel**（★2,727）：A股选股+监控+回测工作台
- **free-stockdb**（★1,948）：本地量化引擎
- **qstock**（★1,922）：个人量化投研包

### C12 · 学习资源

**关键认知**

- 顶级清单是持续学习的入口：awesome-quant（全球）、thuquant/awesome-quant（中文）、awesome-ai-in-finance（AI 方向）
- 教材代码库比教程更值得读：ML4T、Hands-On ML for Algo Trading、algorithmic-trading-with-python
- 面试/入门向：QuantitativePrimer（量化面试）、learn_backtrader（中文教程）

**代表项目**

- **awesome-quant**（★28,663）：全球量化资源索引
- **awesome-ai-in-finance**（★6,375）：LLM+深度学习策略清单
- **awesome-systematic-trading**（★13,150 / ★4,846）：系统化交易清单（英/中）
- **thuquant/awesome-quant**（★5,554）：中文 Quant 资源索引
- **awesome-crypto-trading-bots**（★2,483）：加密机器人清单
- **QuantEcon.py**（★2,387）：量化经济学教程
- **QuantitativePrimer**（★1,598）：量化金融面试导论
- **learn_backtrader**（★2,264）：Backtrader 中文教程
- **algorithmic-trading-with-python**（★3,418）：Algo Trading 教材代码
- **Hands-On ML for Algo Trading**（★1,906）：实战 ML 量化教材

---

## 三、选型矩阵（按场景）

| 场景 | 首选 | 备选 |
|------|------|------|
| A股数据 | akshare / adata / a-stock-data | tushare / efinance / Ashare |
| 美股数据 | yfinance / FinanceDatabase | alpha_vantage / findatapy |
| 加密数据 | ccxt | python-binance / goex |
| 期权数据与定价 | yfinance（链）+ gs-quant / FinancePy（定价） | optlib / tf-quant-finance |
| 快速验证策略 | backtesting.py | bt / fastquant |
| 参数扫描研究 | vectorbt | backtesting.py |
| A股规则回测 | rqalpha / QUANTAXIS | hikyuu |
| ML 因子研究 | qlib / mlfinlab | pybroker / lumibot |
| 因子归因 | alphalens | QuantMuse |
| 组合优化 | PyPortfolioOpt / Riskfolio-Lib | cvxportfolio / skfolio |
| 加密实盘机器人 | freqtrade | jesse / OctoBot / passivbot |
| 做市/套利 | hummingbot | tribeca / hftbacktest |
| A股实盘执行 | easytrader / openctp | vnpy（机构级） |
| 机构级多资产 | Lean / vnpy | StockSharp / wondertrader |
| LLM 研究 Agent | TradingAgents-CN / Vibe-Trading | QuantDinger / daily_stock_analysis |

---

## 四、反模式与陷阱（生态观察）

1. **数据先于策略**：大量项目死于「策略很棒但数据是 demo 级」。先把数据管线建好（对应星辰投研团连接检查 + DataHub）
2. **预测类项目过拟合严重**：Stock-Prediction-Models、LSTM 教程类代码学习思想，不要直接搬参数
3. **机器人项目风控普遍缺失**：多数 bot 仓库没有仓位/止损/熔断；上实盘前必须自建风控最小集
4. **单一交易所绑定**：Binance 地区限制已是现实，ccxt 多所轮询是底线
5. **归档项目当生产用**：gekko/zipline/pyalgotrade/catalyst 已停更，学习架构可以，生产选活跃项目
6. **回测口径不统一**：没有固定绩效口径 + walk-forward 的「回测结果」没有比较价值

---

## 五、与本项目体系的结合

- **星辰投研团**：数据源连接检查 + 自选股 + 自动化任务（对应 C1/C11 数据层与调度层）
- **paddy-quant-workbench**：行情接入/信号/回测/GEX/研报（对应 C2/C8/C6 执行与信号层）
- **待建层**：数据落库（参考 free-stockdb/tickflow）、因子流水线（C7）、风控执行（C4 教训）
- **学习路线**：先过 C1/C2 数据与回测关 → C3/C5 策略与 ML → C6/C7 衍生品与组合 → 最后接 C4 实盘与风控
