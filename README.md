# Quanters' Gate 3

Quanters' Gate 3 是面向 A 股个股的多因子研究项目。项目以沪深 300 的历史成分股为初始研究范围，通过可复现的数据、因子评估和组合回测流程，判断简单选股信号是否值得继续研究。

本项目目前是研究系统，不是自动交易系统，也不构成收益承诺。任何真实资金使用都必须经过数据口径修正、执行约束建模、样本外验证和模拟盘验证。

## 设计原则

- 因子只能使用信号日当时已经可得的信息。
- 指数成员资格只决定某日能否选入股票，不得删除持仓期或因子回看期需要的价格。
- 研究收益使用前复权价格；执行价格必须使用未复权价格。
- 缺失行情和零成交记录不得通过前向填充伪造。
- 数据获取必须可续跑，缓存必须记录请求区间和价格口径。
- 研究结论必须同时展示收益、风险、换手和已知限制。

## 项目结构

```text
quanters_gate_3/
├─ main.py                         # 唯一项目入口
├─ pyproject.toml                  # 项目、依赖、pytest 与 Ruff 配置
├─ uv.lock                         # uv 锁定的完整依赖版本
├─ src/quanters_gate/
│  ├─ cli.py                       # 中文命令行界面与互斥模式校验
│  ├─ workflows.py                 # 数据构建和研究流程编排
│  ├─ settings.py                  # 研究参数和外部接口常量
│  ├─ paths.py                     # 项目数据路径的唯一来源
│  ├─ dates.py                     # 上海交易日期标准化
│  ├─ validation.py                # 共用输入校验
│  ├─ lixinger.py                  # 理杏仁 HTTP 客户端
│  ├─ cache.py                     # 可续跑的逐股票缓存
│  ├─ storage.py                   # 原子文件写入与内容校验
│  ├─ cleaning.py                  # 日线清洗和审计摘要
│  ├─ universe.py                  # 历史成员资格与股票代码
│  ├─ factors.py                   # 原始价格量因子
│  ├─ preprocessing.py             # MAD 去极值和横截面标准化
│  ├─ returns.py                   # 研究收益与执行收益
│  ├─ evaluation.py                # Rank IC 和因子分组收益
│  └─ portfolio.py                 # 月度 Top N 组合回测
├─ tests/                          # pytest 单元测试和回归测试
├─ data/                           # 本地输入、中间结果和报告
└─ AGENTS.md                       # 交接给其他 AI 代理的开发文档
```

## 环境

项目要求 Python 3.14，并完全使用 uv 管理环境、项目安装和锁文件。

```powershell
uv sync
```

运行质量检查：

```powershell
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

## 修改项目

- 修改研究日期、预测周期、组合持仓数、成本率或默认因子权重时，编辑 `src/quanters_gate/settings.py`。
- 新增或调整原始因子时，编辑 `src/quanters_gate/factors.py`，并同步检查 `PRICE_FACTOR_COLUMNS`、组合权重和对应测试。
- 修改数据获取、缓存、清洗、收益或回测规则时，编辑职责对应的模块，不要把业务逻辑放入根目录 `main.py`。
- 修改命令行参数时，编辑 `src/quanters_gate/cli.py`；跨模块执行顺序由 `src/quanters_gate/workflows.py` 管理。
- 每次修改后运行 Ruff 和 pytest；涉及量化计算时，还要检查样本数量、缺失值、日期对齐和是否引入未来信息。

## 数据结构

历史行情面板必须包含每只历史相关股票的完整可用价格，并包含：

```text
eligible_on_signal_date
```

该布尔字段表示股票在该交易日是否可作为新信号的候选。因子回看和未来收益先在完整个股历史上计算，之后才筛选合格信号。

逐股票缓存由两个文件组成：

```text
000001.csv
000001.meta.json
```

元数据记录缓存格式版本、数据来源、实际请求区间、价格口径、行数、CSV 内容的 SHA-256 摘要和构建时间。CSV 与元数据都通过同目录临时文件原子替换，并最后提交元数据；因此，即使写入中断，也能通过行数或内容摘要不一致识别失效缓存，避免误用新旧文件混合的数据。

## 常用命令

构建月末沪深 300 成分历史：

```powershell
uv run python main.py --build-universe-history
```

每次默认补充 12 个月度快照，可调整批量大小：

```powershell
uv run python main.py --build-universe-history --max-universe-snapshots 6
```

构建完整的前复权研究行情：

```powershell
uv run python main.py --build-market-history
```

构建完整的未复权执行行情：

```powershell
uv run python main.py --build-execution-history
```

在历史研究面板上执行因子预处理和 Rank IC：

```powershell
uv run python main.py --run-market-history --with-analysis
```

增加分组收益评估：

```powershell
uv run python main.py --run-market-history --with-evaluation
```

运行月度 Top 30 组合研究回测：

```powershell
uv run python main.py --run-market-history --with-backtest
```

运行次日开盘执行口径回测：

```powershell
uv run python main.py --run-market-history --with-execution-backtest
```

也可以使用临时股票列表运行基础流程：

```powershell
uv run python main.py --symbols 000001 000002 000063 000333 600000
```

真实理杏仁 Token 只能放在未跟踪的 `.env` 中：

```text
LIXINGER_TOKEN=你的真实令牌
```

## 当前共享数据说明

仓库中现有的 `data/market/raw/000300_ME_panel.csv` 来自旧版流程：它在保存前已经按成分资格删除了非成员价格，因此无法恢复股票退出指数后的行情。新代码会在读取它时发出中文警告并保持旧数据可运行，但这不能修复已经丢失的数据。

本次审计还确认：成分历史在最后一个快照中包含 `688072`，但旧行情面板没有该股票的价格，因此当前共享面板覆盖 458 只股票，而成分历史覆盖 459 只。仓库中跟踪的 `portfolio_backtest_20d.csv` 也早于当前报告结构，尚不包含 `gross_portfolio_return` 和 `transaction_cost` 两列。

要得到修正后的研究结果，必须准备理杏仁 Token，重复执行 `--build-market-history` 直至完整缓存构建完成，再重新生成研究报告。仓库中现有报告应视为旧数据口径的历史快照。

## 当前研究边界

项目目前具备动态成员资格、行情清洗、四个基础因子、横截面预处理、非重叠 Rank IC、分组收益、Top N 组合和初步执行收益。它仍未完整处理涨跌停、ST、退市、现金分红、最小委托数量、最低佣金、现金账户和真实成交，因此不能被描述为可直接实盘的系统。

组合模块在每个月末独立观察固定 20 个可用交易日的未来收益。相邻月末之间并不总是恰好相隔 20 个交易日，因此这些观察窗口可能重叠，也可能留有空档。当前摘要中的复利、年化收益和回撤只能作为研究诊断指标，不能解释为严格自融资组合的真实净值。用于模拟盘或实盘前，必须改为按相邻调仓日估值的连续持仓回测。

## Git 协作

新成员首次参与开发时，先克隆仓库并安装锁文件指定的环境：

```powershell
git clone https://github.com/cleverpigeb/Quanters-Gate-3.git
cd Quanters-Gate-3
uv sync
```

开始工作前先切换到 main 并拉取最新代码，随后在新分支中开始工作：

```powershell
git switch main
git pull origin main
git switch -c <分支名>
```

完成一项范围清晰的修改并通过质量检查后，检查变更、按需暂存、提交并推送：

```powershell
uv run ruff check .
uv run ruff format --check .
uv run pytest
git status
git diff
git add <文件路径>
git commit -m "提交说明"
git push origin <分支名>
```

需要合入主线时，通过 Pull Request 将功能分支合入 `main`，不要直接向 `main` 推送未经审查的修改。提交前必须确认没有加入 `.env`、Token、逐股票临时缓存、个人运行产物或未经团队确认的大型数据文件。
