# Quanters' Gate 3

面向 A 股个股的多因子研究项目。目标是建立一条可解释、可复现的研究流水线：先验证单因子，再做组合、回测和实盘可行性评估。

`main.py` 保留为单股票均线策略练习；正式的多因子研究从 `run_all.py` 进入。

## 项目目标

最终目标是形成一套可小资金实盘的 A 股个股量化策略，而不是只得到一份历史回测。策略必须能够回答四件事：买什么、何时调仓、因何有效、在真实交易限制下能否执行。

第一版研究范围保持克制：以沪深 300 成分股为初始股票池、月频调仓、20 个交易日预测窗口、少量可解释因子。先完成完整闭环，再逐步扩充股票池、因子数量和策略复杂度。

## 阶段计划

1. 研究底座：动态股票池、行情数据、清洗、复权价格和交易限制。
2. 单因子研究：因子计算、横截面预处理、非重叠 Rank IC、分组收益和稳定性分析。
3. 多因子策略：方向统一、去冗余、等权综合分数、Top N 组合和基准比较。
4. 可交易回测：交易成本、滑点、涨跌停、停牌、调仓延迟、换手和风险暴露。
5. 实盘验证：样本外测试、模拟盘、交易记录和监控，最后才是小资金实盘。

每一阶段完成的标准不是“代码能跑”，而是研究结论、数据口径和限制条件都能被团队成员复现和解释。

## 团队分工

- Quant researcher：提出因子假设、定义研究口径、判断 IC/分组结果、解释失效原因和决定下一步研究。
- Quant developer：维护数据管道、研究模块、回测引擎、执行与监控基础设施。
- Trader：审查调仓规则、可交易性、成本假设、仓位约束和实盘风险。

角色并不排斥互相 review。任何进入策略的假设都需要同时通过研究合理性、工程可复现性和交易可执行性三关。

## 模块职责

`settings.py` 保存默认研究参数，例如初始股票池、日期范围、预测窗口和分组数。`stock_pool.py` 则保存股票池的业务逻辑：代码校验、按日期取成分股、ST/停牌/退市过滤等。第一版可以在 settings 配置沪深 300；后续换成动态成分股时，入口和其他模块不需要重写。

## 研究流程

```text
股票池 -> 行情获取 -> 清洗 -> 原始因子
      -> 截面预处理 -> 非重叠 Rank IC -> 分组收益评估
```

当前第一版只使用价格和成交额因子：20 日动量、5 日反转、20 日波动率和流动性代理。它们只是研究基线，不代表已经发现 alpha。

## 项目结构

```text
config/
  settings.py              # 股票池、日期、预测窗口和研究参数
  paths.py                 # 项目内数据路径的唯一来源
src/
  stock_pool.py            # 股票代码与股票池校验
  data_fetcher.py          # 理杏仁行情与指数成分接口封装
  data_cleaner.py          # 行情清洗
  factor_calculator.py     # 原始因子计算
  factor_preprocessor.py   # MAD 去极值、z-score、覆盖率报告
  ic_analyzer.py           # 未来收益与非重叠 Rank IC
  factor_evaluator.py      # 因子分组收益评估
data/
  market/{raw,processed}/
  factors/{raw,processed}/
  reports/
notebooks/                 # 探索性研究和人工检查，不放正式主流程
run_all.py                 # 正式研究入口
main.py                    # 单股票均线练习示例
```

行情和报告会写入 `data/`，目前默认不提交，以免把本地运行产物和大文件带进协作仓库。

理杏仁 Token 仅保存在本机项目根目录 `.env`，可从 `.env.example` 创建模板；它绝不能进入 Git。

## 快速开始

```powershell
uv sync
uv run python run_all.py --symbols 000001 000002 000063 000333 600000
```

使用某一日期的沪深 300 成分股快照：

```powershell
uv run python run_all.py --universe-date 2024-01-02
```

这只是第一版的点时股票池接口。全历史回测必须使用逐日或逐次调样的历史成分股，不能用某一天的成分股回填整个历史区间。

基础流程会获取、清洗行情并生成原始因子。继续做预处理：

```powershell
uv run python run_all.py --with-preprocess
```

生成非重叠 Rank IC：

```powershell
uv run python run_all.py --with-analysis
```

加上分组收益评估：

```powershell
uv run python run_all.py --with-evaluation
```

`FORWARD_DAYS=20` 且 `IC_SAMPLE_STEP=20` 的默认设计，是为了避免每天计算未来 20 日收益时，样本窗口高度重叠而夸大 IC 的稳定性。

## 个股项目边界

后续正式扩展前，需要先补齐这些个股专属问题：动态股票池、ST/停牌/退市处理、复权价格、财报披露日对齐、行业/市值中性化，以及含交易成本的组合回测。财报数据必须按披露日可得性合并，不能按报告期末直接使用。

## Git 协作

日常工作在 `Hush` 分支进行：

```powershell
git switch Hush
git pull origin Hush
git status
git add <files>
git commit -m "feat: describe the change"
git push origin Hush
```

需要合入主线时，通过 Pull Request 从功能分支合入 `main`。提交前不要加入 `.env`、Token、临时缓存或未经确认的大型数据文件。
