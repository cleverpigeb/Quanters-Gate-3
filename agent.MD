# Quanters' Gate 3 Agent Handoff

## 1. Project identity

This is a collaborative A-share individual-stock multi-factor research project. The final objective is a strategy suitable for cautious small-capital live trading after research, realistic backtesting, and paper-trading validation.

Do not copy the index-rotation logic from `C:\Users\Hush\quant_learning`. It is a useful engineering reference only. This project must be designed around individual-stock issues: dynamic universe membership, ST/suspension/delisting rules, adjusted prices, financial-report publication dates, industry and market-cap exposures, and trading feasibility.

## 2. Current state

- Working branch: `Hush`, tracking `origin/Hush`.
- Default flow: `run_all.py` -> market fetch -> cleaning -> raw factors -> optional preprocessing -> non-overlapping Rank IC -> optional quantile returns.
- Initial stock universe: point-in-time CSI 300 constituents from Lixinger. This is a snapshot interface, not yet the full historical dynamic universe needed for production backtests.
- Lixinger integration was live-checked with the local token: `cn/index/constituents` uses `stockCodes: ["000300"]`; `cn/company/candlestick` uses `stockCode`, `type: "day"`, `startDate`, and `endDate`.
- Market cleaning validates prices and OHLC ranges, removes duplicate `(date, symbol)` rows by retaining the latest response, and preserves zero-activity bars as `is_tradable=False`.
- The cleaner normalizes provider timestamps to timezone-naive Shanghai trading dates before any cross-source merge.
- Current factors: 20-day momentum, 5-day reversal, 20-day volatility, and a liquidity proxy.
- All 20-day factors require a full 20-trading-day lookback. Do not fill warm-up observations just to enlarge an analysis sample.
- `main.py` is a separate single-stock moving-average exercise. Preserve it unless the user explicitly asks to change it.
- `data/` is ignored for now. Do not commit API tokens, `.env`, caches, or large generated datasets without explicit agreement.

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

Implement historical CSI 300 membership and investability filters before adding many more factors. The first full strategy target is: CSI 300, monthly rebalance, 20-trading-day horizon, a small set of interpretable factors, Top N equal-weight holdings, and a transaction-cost-aware benchmark comparison.
