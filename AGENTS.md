# Quanters' Gate 3 AI Agent Handoff

## Purpose

`AGENTS.md` exists solely to hand over project context, engineering constraints, and quantitative-correctness requirements to future AI agents. It is not a user guide, research report, or collaboration-process document. Before changing the project, an AI agent must read this file and `README.md`, then inspect the current code and tests instead of relying only on prior conversation history.

## Project Scope

This project is a cross-sectional equity-factor research pipeline for mainland China A-shares. Its current research scope focuses on historical CSI 300 constituents, monthly signals, 20-trading-day forward returns, and equal-weighted Top N portfolios. The system is intended for testing research hypotheses; it is not a broker integration, automated execution system, or production-grade capital-management platform.

The only entry point is the root-level `main.py`, which calls `quanters_gate.cli.main`. Implementation code lives in `src/quanters_gate/`, and tests live in `tests/`. The environment, project installation, dependencies, and lockfile are managed through uv.

## Module Responsibilities

- `cli.py`: Chinese-language CLI, argument defaults, primary-mode validation, and concrete provider selection.
- `workflows.py`: Application orchestration for constituent history, market data, research, and backtests.
- `settings.py`: Typed loading and strict validation of the versioned TOML configuration.
- `paths.py`: All project data paths.
- `validation.py`: Shared input validation across subpackages.
- `storage.py`: Shared atomic CSV/JSON/text writers and SHA-256 file hashing.
- `data/provider.py`: Provider protocols and the factory type used by data workflows.
- `data/lixinger.py`: Authentication, HTTP sessions, API response validation, and source-field conversion.
- `data/cache.py`: Per-security caches with auditable metadata and content-identity checks.
- `data/cleaning.py`: Validation of daily fields, numeric values, OHLC relationships, duplicate rows, and tradability.
- `data/dates.py`: Centralized conversion from external timestamps to Shanghai trading dates.
- `data/universe.py`: Security-code normalization, constituent history, and `eligible_on_signal_date`.
- `research/factors.py`: 20-day momentum, 5-day reversal, 20-day volatility, and turnover proxy.
- `research/preprocessing.py`: Daily cross-sectional MAD winsorization and z-score standardization.
- `research/returns.py`: Forward close-to-close research returns.
- `research/evaluation.py`: Non-overlapping Rank IC, quantile returns, and Top-Bottom spreads.
- `backtest/portfolio.py`: Monthly Top N portfolios, turnover, costs, and backtest summaries.
- `backtest/execution.py`: Next-open execution returns based on unadjusted prices and tradability.

## Quantitative Constraints That Must Not Be Violated

1. Factors may use only information available on or before the signal date.
2. Historical index membership determines only whether a security may be newly selected on a signal date.
3. Complete security-level price histories must be retained for factor lookback before index inclusion and portfolio valuation after index removal.
4. Factors and forward returns must be calculated on each security's complete history before filtering signals by `eligible_on_signal_date=True`.
5. Current constituents must never be used to backfill the historical universe.
6. Research returns use `lxr_fc_rights` forward-adjusted prices; execution returns accept only `ex_rights` unadjusted prices.
7. Missing market data must not be forward-filled, and zero-turnover records must not be removed to fabricate continuous trading.
8. IC and quantile evaluation for N-day forward returns must use non-overlapping samples or an explicitly justified statistical correction.
9. A factor must remain missing when its complete lookback window is unavailable.
10. Positive returns alone do not establish strategy validity; drawdown, turnover, costs, and out-of-sample stability must also be reviewed.
11. Monthly fixed-horizon return windows may overlap or leave gaps because adjacent month ends are not always exactly 20 trading days apart. Current compounded backtest summaries are research diagnostics, not a strict self-financing NAV, and must not be presented as realizable performance.

## Engineering Constraints

- All code comments, docstrings, exception messages, CLI help text, and ordinary runtime messages must use Simplified Chinese.
- Python identifiers, CSV field names, command-line options, and external API fields must retain stable English names.
- Shared logic should be placed in the existing module with the appropriate responsibility. Do not duplicate date normalization, column validation, or file-writing logic.
- Do not restore the former `src.*` or `config.*` compatibility wrappers.
- Do not reintroduce the removed AkShare moving-average exercise or the `akshare` and `matplotlib` dependencies.
- Data downloads must remain bounded, sequential, and resumable. Do not send aggressively concurrent requests to the Lixinger API.
- Preserve the three bounded subpackages: `data` for acquisition and eligibility, `research` for factor analysis, and `backtest` for portfolio and execution logic. Cross-cutting infrastructure and application orchestration stay at the package root.
- `data/cache.py` and `workflows.py` must depend on provider protocols, not on `LixingerClient`. The CLI is the composition root that selects the concrete provider implementation.
- Changes to quantitative logic must include minimal regression tests capable of exposing look-ahead bias, index-removal errors, and missing execution prices.
- Generated report fields and paths are auditable interfaces. Intentional changes require corresponding updates to tests and `README.md`.

## Configuration Contract

The `config/default.toml` file is the single version-controlled source of research defaults and includes an explicit `schema_version`. It is opened read-only and validated at process startup; normal execution must never rewrite, normalize, or format this authoritative input. The loader contains no fallback research parameters. It records the research interval, forward-return and evaluation parameters, random seed, default symbols, benchmark index, rebalance frequency, download batch sizes, data provider, price conventions, portfolio size, transaction cost, and factor weights.

Command-line values may temporarily override the supported date, symbol, horizon, and batch-size defaults. After a successful research run, the fully resolved configuration and run-mode flags must be atomically saved as `data/reports/run_config.toml`; this artifact must contain the effective overrides rather than a copy of defaults. Secrets must never be stored in TOML: the Lixinger token remains an environment or untracked `.env` value. `settings.py` must reject malformed, incomplete, unsupported, or quantitatively unsafe configuration instead of silently falling back to hidden constants.

## Data Cache Contract

Every per-security CSV must have a matching `.meta.json` file containing:

- `schema_version`
- `provider`
- `requested_start`
- `requested_end`
- `price_type`
- `row_count`
- `content_sha256`
- `built_at`

A cache may be reused only when its schema and provider match the current implementation, its metadata covers the requested interval, its price type matches the request, its row count and SHA-256 digest match the CSV, and its non-empty CSV contains only valid trading dates. Every CSV row must also match the security encoded by the filename and the requested price type. The CSV is replaced atomically before the metadata is committed, so an interrupted update leaves a detectable mismatch instead of a silently reusable mixed pair. Legacy or incomplete caches must be fetched again.

## Current Data-Migration State

The tracked `data/market/raw/000300_ME_panel.csv` is a legacy constituent-filtered panel. It lacks complete prices before index inclusion and after index removal, and it does not contain a native eligibility column. For compatibility, the current code temporarily adds an eligibility column when reading this file and emits a warning, but it cannot recover prices that were already discarded.

The audited membership history contains 459 unique securities, while the legacy market panel contains 458. Security `688072` appears in the final membership snapshot but has no row in the shared market panel. The tracked `portfolio_backtest_20d.csv` also predates the current report schema and lacks the `gross_portfolio_return` and `transaction_cost` columns.

Corrected shared data and reports can be rebuilt only when a Lixinger token is available, using this sequence:

```powershell
uv run python main.py --build-universe-history
uv run python main.py --build-market-history
uv run python main.py --run-market-history --with-evaluation --with-backtest
```

The market-history build command must be rerun until all per-security caches are complete. Existing reports use the legacy data convention and must not be represented as reflecting the corrected index-removal treatment.

## Development Validation

After every code change, run at least:

```powershell
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

For changes to research calculations, also compare output row counts, fields, ordering, numerical differences, and runtime against the complete shared panel. Performance improvements must not reduce the valid sample, alter missing-value rules, or lower calculation precision.
