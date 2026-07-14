# Quanters' Gate 3 Agent Handoff

## 1. Project identity

This is a collaborative A-share individual-stock multi-factor research project. The final objective is a strategy suitable for cautious small-capital live trading after research, realistic backtesting, and paper-trading validation.

Do not copy the index-rotation logic from `C:\Users\Hush\quant_learning`. It is a useful engineering reference only. This project must be designed around individual-stock issues: dynamic universe membership, ST/suspension/delisting rules, adjusted prices, financial-report publication dates, industry and market-cap exposures, and trading feasibility.

## 2. Current state

- Working branch: `Hush`, tracking `origin/Hush`.
- Default flow: `run_all.py` -> market fetch -> cleaning -> raw factors -> optional preprocessing -> non-overlapping Rank IC -> optional quantile returns.
- Initial stock universe: point-in-time CSI 300 constituents from Lixinger. This is a snapshot interface, not yet the full historical dynamic universe needed for production backtests.
- Monthly CSI 300 membership history is built from real CSI 300 trading dates, then one Lixinger constituent snapshot per month-end. It must be available before a full-universe historical backtest.
- Universe snapshots are cached one month per CSV under `data/universe/` and built in small resumable batches. Do not replace this with aggressive parallel API requests.
- Market history uses the same bounded, per-symbol cache under `data/market/raw/by_symbol/`. Only after every historical constituent has a complete price file does the pipeline create the membership-filtered panel.
- Cache coverage checks normalize provider timestamps to timezone-naive Shanghai dates before comparing against the configured research range.
- Read cached `symbol` columns with an explicit string dtype; otherwise leading-zero A-share codes fail to match membership history.
- Apply membership by the global latest month-end snapshot for each market date, then exact-match symbols within that snapshot. Never as-of merge membership separately by symbol, because it incorrectly retains stocks after they leave the index.
- The local 2021-01-29 to 2026-06-30 membership build completed with 66 snapshots and 19,800 rows. Every snapshot has 300 symbols; the first and last snapshots differ by 200 codes.
- The completed membership-filtered market panel has 392,238 eligible daily bars across 458 symbols. Most days have 300 names; the minimum is 296 because a small number of member-day observations have no usable quote.
- The first full CSI 300 research run completed with 64 non-overlapping 20-day observations and median cross-section size 300. The four initial raw factors are weak diagnostics only; none is ready to enter a trading strategy without further validation.
- The monthly history contains 459 unique symbols across the full period, and the local per-symbol market cache is complete. The cache remains local because the membership-filtered panel is the smaller reproducible input needed for research.
- Lixinger integration was live-checked with the local token: `cn/index/constituents` uses `stockCodes: ["000300"]`; `cn/company/candlestick` uses `stockCode`, `type: "day"`, `startDate`, and `endDate`.
- Market cleaning validates prices and OHLC ranges, removes duplicate `(date, symbol)` rows by retaining the latest response, and preserves zero-activity bars as `is_tradable=False`.
- The cleaner normalizes provider timestamps to timezone-naive Shanghai trading dates before any cross-source merge.
- Current factors: 20-day momentum, 5-day reversal, 20-day volatility, and a liquidity proxy.
- All 20-day factors require a full 20-trading-day lookback. Do not fill warm-up observations just to enlarge an analysis sample.
- Preprocessing applies MAD winsorization and z-score separately on each trading-date cross-section, while preserving missing factor values.
- IC analysis uses close-to-close forward returns and samples every `IC_SAMPLE_STEP` trading dates to avoid overlapping forward-return windows. Never shift factor values forward to manufacture an IC result.
- Quantile evaluation is equal-weighted and sampled every `IC_SAMPLE_STEP` dates. Its output is a factor diagnostic, not a transaction-cost-aware strategy backtest.
- The minimal portfolio research backtest is implemented in `src/portfolio_backtester.py`. It takes month-end signals, selects an equal-weighted Top N portfolio, and compares its forward return with the equal-weighted eligible universe. Defaults belong in `PORTFOLIO_FACTOR_WEIGHTS` and `PORTFOLIO_TOP_N`.
- Its current return starts at the signal-date close and uses the existing future-N-available-bar return. It intentionally excludes execution delay, costs, price limits, ST/delisting rules, and cap-weighted index benchmarking. Never present its outputs as tradeable or live-strategy performance.
- The first full-panel momentum-only Top 30 research run has 63 monthly observations: 47.79% portfolio total return versus 21.20% equal-weight-universe benchmark, but -53.94% maximum drawdown and 83.97% mean one-way turnover. It is a starting diagnostic, not a validated alpha result.
- The next execution layer has a separate `data/market/execution/` cache and panel, fetched as `ex_rights` through `--build-execution-history`. `src/execution_returns.py` maps factor-date signals to the next available open and the open after the configured holding horizon; both must be tradable.
- `--with-execution-backtest` refuses to use adjusted execution prices and applies the configurable `PORTFOLIO_ONE_WAY_COST_RATE`. It is not yet runnable until the unadjusted execution panel is built, and it still excludes cash dividends, price limits, ST/delisting rules, and real order fills.
- A five-stock end-to-end run for 2021-01-04 to 2026-06-30 completed successfully. Treat it only as a pipeline smoke test; five names are far too few for an alpha conclusion.
- `main.py` is a separate single-stock moving-average exercise. Preserve it unless the user explicitly asks to change it.
- `data/` is ignored by default. The explicit shared-data exception is the versioned CSI 300 snapshot: `data/universe/000300_ME_membership.csv`, `data/market/raw/000300_ME_panel.csv`, and `data/reports/*.csv`. Do not commit API tokens, `.env`, per-symbol caches, or regenerable cleaning/factor intermediates without explicit agreement.

## 3. Engineering rules

1. Keep the project structured and immediately understandable to collaborators.
2. Before every push, update both `README.md` and `agent.MD` when project status, structure, commands, decisions, or handoff information changed. A no-op wording review is enough when neither document needs a factual change.
3. Keep modules concise. Do not add duplicated helpers, dead code, unused compatibility layers, or overlapping modules.
4. Favor extension through configuration and clear interfaces. The project should grow from a small CSI 300 factor set to broader universes, more factors, and more research stages without rewriting the pipeline.
5. Use `config/settings.py` for research parameters and `config/paths.py` as the single source of project paths. Keep core production logic in `src/`; put exploratory work in `notebooks/`.
6. Do not introduce a new top-level directory without a concrete business reason and an explanation in README.
7. Preserve user and teammate changes. Never reset, overwrite, or remove unrelated work.

## 4. Research correctness rules

- Factors must only use information available on the factor date.
- Never backfill a full historical test with one current CSI 300 constituent snapshot; that creates survivorship bias.
- Financial data becomes usable on its publication date, not the accounting period end date.
- Rank IC with an N-day forward return should use non-overlapping or explicitly adjusted samples; otherwise overlapping windows exaggerate stability.
- A positive backtest alone is insufficient. Check costs, slippage, turnover, suspensions, price limits, delistings, and sample-out performance.
- The cleaner must not forward-fill price bars or discard a zero-volume bar merely to make a panel rectangular; tradability is a later business decision.
- A negative IC can still be useful if it is stable and its sign is explicitly reversed before combination.
- Start with simple, explainable equal-weight factor combinations before complex models.

## 4.1 Lixinger implementation notes

- Use a request header of `Accept-Encoding: gzip`; requests without it receive a validation error from the API.
- Read `LIXINGER_TOKEN` from the environment or this project's local `.env`, never from a hard-coded value or another repository path.
- Research bars use Lixinger front-adjusted `lxr_fc_rights`, which includes dividend reinvestment. Execution work must explicitly request unadjusted `ex_rights` prices; never use an adjusted price as a simulated fill price.

## 5. Git workflow

1. Start with `git switch Hush` and `git pull origin Hush`.
2. Inspect `git status` before editing and before committing.
3. Keep each commit scoped and explainable.
4. Before push: run relevant checks, review `git diff --cached --check`, and update README/agent.MD as required above.
5. Do not commit or push merely because code changes are complete. Wait for explicit user authorization to commit and/or push after the user has reviewed the local changes.
6. When explicitly authorized, push to `origin Hush`. Merge to `main` through a Pull Request when the team agrees.

## 6. Suggested next research milestone

Add explicit investability filters and an execution-aware portfolio return model before adding many more factors. The next strategy target is: CSI 300, monthly rebalance, 20-trading-day horizon, a small set of interpretable factors, Top N equal-weight holdings, next-trading-day execution, and a transaction-cost-aware benchmark comparison.
