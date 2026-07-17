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
├─ config/
│  └─ default.toml                 # 版本化的研究与回测默认配置
├─ pyproject.toml                  # 项目、依赖、pytest 与 Ruff 配置
├─ uv.lock                         # uv 锁定的完整依赖版本
├─ snapshots/                      # 版本控制内的共享数据快照清单
├─ src/quanters_gate/
│  ├─ cli.py                       # 中文命令行界面与互斥模式校验
│  ├─ workflows.py                 # 数据构建和研究流程编排
│  ├─ settings.py                  # TOML 配置读取和严格校验
│  ├─ paths.py                     # 项目数据路径的唯一来源
│  ├─ validation.py                # 共用输入校验
│  ├─ storage.py                   # 原子文件写入与内容校验
│  ├─ data/                        # 行情来源、缓存、清洗与股票池
│  │  ├─ provider.py               # 行情数据源协议、工厂与顺序下载
│  │  ├─ akshare.py                # AKShare 免费行情适配器
│  │  ├─ lixinger.py               # 理杏仁 HTTP 客户端
│  │  ├─ cache.py                  # 可续跑的逐股票缓存
│  │  ├─ cleaning.py               # 日线清洗和审计摘要
│  │  ├─ dates.py                  # 上海交易日期标准化
│  │  └─ universe.py               # 历史成员资格与股票代码
│  ├─ research/                    # 因子计算、研究收益与统计评估
│  │  ├─ factors.py                # 原始价格量因子
│  │  ├─ preprocessing.py          # MAD 去极值和横截面标准化
│  │  ├─ returns.py                # 研究口径未来收益
│  │  └─ evaluation.py             # Rank IC 和因子分组收益
│  └─ backtest/                    # 组合构建与执行收益
│     ├─ portfolio.py              # 月度 Top N 组合回测
│     └─ execution.py              # 次日开盘执行收益
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

- 修改研究日期、预测周期、股票池、基准指数、调仓频率、评估参数、组合持仓数、成本率、随机种子或默认因子权重时，编辑 `config/default.toml`。
- 新增或调整原始因子时，编辑 `src/quanters_gate/research/factors.py`，并同步检查 `PRICE_FACTOR_COLUMNS`、组合权重和对应测试。
- 修改数据获取、缓存、清洗、收益或回测规则时，编辑职责对应的模块，不要把业务逻辑放入根目录 `main.py`。
- 新增数据源时，实现 `src/quanters_gate/data/provider.py` 中的协议，并只在应用入口选择具体实现；缓存和研究流程不得依赖供应商专用鉴权或 HTTP 细节。
- 修改命令行参数时，编辑 `src/quanters_gate/cli.py`；跨模块执行顺序由 `src/quanters_gate/workflows.py` 管理。
- 每次修改后运行 Ruff 和 pytest；涉及量化计算时，还要检查样本数量、缺失值、日期对齐和是否引入未来信息。

## 项目配置

`config/default.toml` 是版本控制内唯一的研究默认配置，并通过 `schema_version` 明确配置格式版本。程序启动时只读该文件并进行校验，不会重写或格式化它；修改后的值会在下一次运行中实际生效。它记录以下内容：

- `research`：研究区间、未来收益周期、IC 抽样步长、分组数和随机种子。
- `universe`：默认股票列表、基准指数、调仓频率和下载批量。
- `data`：数据来源、研究价格口径和执行价格口径。
- `portfolio`：持仓数量、单边成本率和因子权重。

命令行中的 `--symbols`、`--start`、`--end`、`--horizon` 和两个批量参数仍可临时覆盖对应默认值。每次研究流程成功完成后，程序会将实际生效的参数、运行模式和功能开关原子写入 `data/reports/run_config.toml`，因此命令行覆盖值也能随结果保存。当前流程没有随机步骤，但配置仍显式保存随机种子，防止未来加入随机算法后失去复现依据。

默认数据源为无需 Token 的 AKShare。若在 `config/default.toml` 中改回 `lixinger`，理杏仁 Token 不属于研究配置，只能通过环境变量或未跟踪的 `.env` 文件提供。

## 数据源边界

`data/provider.py` 定义行情下载所需的结构化协议，并提供有界、顺序的多股票下载流程。`AkShareClient` 和 `LixingerClient` 都实现该协议，`cli.py` 根据配置选择具体实现；缓存和研究流程只接收协议或数据源工厂。因此可以在测试中使用内存数据源，也可以新增离线数据集或备用供应商，而不需要修改因子、收益和回测逻辑。

AKShare 个股日线依次尝试东财和新浪：`lxr_fc_rights` 映射为其 `qfq` 前复权选项，`ex_rights` 映射为默认不复权选项。只有返回完整 OHLC、成交量和成交额的来源才能进入研究缓存；腾讯日线接口不返回成交额，因此不会被用于本项目的因子研究。两家供应商的复权数值未必完全一致，缓存元数据会按供应商隔离，不能混用。

AKShare 当前的中证成分接口只返回其实际标注日期的一份当前快照，不能按任意历史日期查询。程序会拒绝把这份快照标记为过去日期，以防止未来信息泄漏。因此：可以使用 AKShare 重新下载已有、经过审计的历史成分股票列表的完整行情；但不能用它重建月度历史成分。重建成分历史需要可靠的历史快照来源，或保留现有审计过的成员文件。

## 数据结构

历史行情面板必须包含每只历史相关股票的完整可用价格，并包含：

```text
eligible_on_signal_date
```

该布尔字段表示股票在该交易日是否可作为新信号的候选。因子回看和未来收益先在完整个股历史上计算，之后才筛选合格信号。

因子回看、未来收益和次日开盘执行都按全市场交易日期序列定位窗口。若某只股票在窗口要求的准确交易日缺少行情，结果必须保持缺失；程序不会把该股票的下一条可用记录错误地当作目标交易日。

逐股票缓存由两个文件组成：

```text
000001.csv
000001.meta.json
```

元数据记录缓存格式版本、数据来源、实际请求区间、实际观测到的首末交易日、价格口径、行数、CSV 内容的 SHA-256 摘要和构建时间。实际观测首日可以晚于请求首日，例如股票尚未上市；该边界会被审计记录，不能被请求区间的元数据掩盖。AKShare 缓存还会在 CSV 和元数据中记录实际使用的 `data_source`（`eastmoney` 或 `sina`）；缺少这些字段的旧版缓存会自动重新获取。CSV 与元数据都通过同目录临时文件原子替换，并最后提交元数据；因此，即使写入中断，也能通过行数、日期范围或内容摘要不一致识别失效缓存，避免误用新旧文件混合的数据。

## 常用命令

构建月末沪深 300 成分历史（仅限支持历史成分快照的数据源；AKShare 不支持）：

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

分批构建财务 point-in-time 面板；重复运行直到提示覆盖全部历史成分股：

```powershell
uv run python main.py --build-fundamental-history --max-fundamental-symbols 12
```

财务面板完整后，`--run-market-history` 会自动附加 ROE、ROA、营收增长和经营现金流质量候选因子，并继续使用同一套 IC、分组与相关性诊断。披露当天的数据不会进入信号；现有组合权重不会被自动改变。

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

改回理杏仁数据源时，真实 Token 只能放在未跟踪的 `.env` 中：

```text
LIXINGER_TOKEN=你的真实令牌
```

## 当前共享数据快照

当前冻结快照为 `000300_ME_20210101_20260630_akshare_v1`。项目继续使用既有且经过审计的 `000300_ME_membership.csv`：文件包含 2021-01-29 至 2026-06-30 的 66 个月末快照、19,800 条成员记录和 459 只历史相关股票。AKShare 仅负责重新获取这些股票的完整行情，不负责生成或回填历史成分。

研究与执行行情分别具有 459 组 CSV 和元数据文件，全部通过缓存格式、请求区间、实际日期范围、股票代码、价格口径、行数、内容摘要和 AKShare 实际来源校验。修正后的前复权研究面板包含 593,334 行，未复权执行面板包含 593,335 行；两者都覆盖 459 只股票和 `688072`，并保留指数纳入前或移除后的价格。研究面板中有 201,096 行明确标记为不可在该日新建仓位，而不是被删除。

该快照中的成分历史、逐股票缓存和合并行情面板仍是有效的冻结输入。后续审计发现，快照所用旧代码会在个股交易日缺口处按“下一行”推进因子和收益窗口；当前代码已改为按全市场准确交易日定位。因而 v1 中的因子、评估和回测文件只能视为提交 `83a0547facb53c42be342fc402dc077868c49063` 对应的历史产物，不能代表当前修正后的计算方法。版本控制内的 `snapshots/000300_ME_20210101_20260630_akshare_v1.toml` 记录其配置、成分历史、缓存集合、主要产物和本地归档文件的 SHA-256 摘要。

完整归档位于 `data/snapshots/000300_ME_20210101_20260630_akshare_v1.zip`，共有 1,855 个条目，SHA-256 为 `92118320e42d9465c96bf6956e302ca1e2af7514b729b11a2afb23442bae5275`。该 ZIP 通过 Git LFS 跟踪，克隆仓库时需要安装 Git LFS；展开后的 `data/` 内容仍被 Git 忽略，避免把同一份数据重复提交。使用前应核对同目录 `.sha256` 文件。冻结版本不得原地覆盖：数据、配置或计算代码发生变化时，应创建新的快照标识和清单。

首次取得共享数据时，在仓库根目录运行：

```powershell
git lfs pull
New-Item -ItemType Directory -Path data -Force | Out-Null
Expand-Archive -LiteralPath data/snapshots/000300_ME_20210101_20260630_akshare_v1.zip -DestinationPath data -Force
```

归档内部直接包含 `market/`、`universe/`、`factors/` 和 `reports/`，因此必须解压到项目的 `data/` 目录。解压不会修改版本控制内的配置文件。完成后可直接运行 `--run-market-history` 研究命令，无需再次执行任何 `--build-*` 数据下载命令。

如需精确复现 v1 的所有派生文件，应先使用其清单记录的 `project_commit`。在当前代码上从同一份成分历史重新计算时，依次运行以下命令，并在代码提交后创建新的快照标识和清单，不能覆盖 v1：

```powershell
uv run python main.py --build-market-history
uv run python main.py --build-execution-history
uv run python main.py --run-market-history --with-evaluation --with-backtest --with-execution-backtest
```

## 当前研究边界

项目目前具备动态成员资格、行情清洗、八个基础价格-成交因子、横截面预处理、非重叠 Rank IC、年度稳定性、分组收益、因子诊断摘要、因子相关性诊断、Top N 组合和初步执行收益。首批因子覆盖短中期趋势、短期反转、波动、成交活跃度、流动性摩擦、成交活跃度变化和极端收益暴露；它们是可复现的研究基线，不应被预设为有效 alpha。财务数据层已具备 AKShare 财务摘要标准化与 point-in-time 合并：报告在其最晚报表更新时间当日之后才进入信号截面，后续批量缓存完成后可接入 ROE、ROA、营收增长和现金流质量因子。`--with-evaluation` 会额外生成 IC t 统计量、年度稳定性、分组单调性和因子两两横截面 Rank 相关性，用于人工判断因子方向、稳定性与重复暴露；这些诊断不会自动改变因子方向或组合权重。它仍未完整处理涨跌停、ST、退市、现金分红、最小委托数量、最低佣金、现金账户和真实成交，因此不能被描述为可直接实盘的系统。

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
