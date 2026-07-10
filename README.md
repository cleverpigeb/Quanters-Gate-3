# Quanters' Gate 3

面向 A 股个股的多因子研究项目。目标是建立一条可解释、可复现的研究流水线：先验证单因子，再做组合、回测和实盘可行性评估。

`main.py` 保留为单股票均线策略练习；正式的多因子研究从 `run_all.py` 进入。

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
  data_fetcher.py          # 行情数据源封装
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

## 快速开始

```powershell
uv sync
uv run python run_all.py --symbols 000001 000002 000063 000333 600000
```

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
