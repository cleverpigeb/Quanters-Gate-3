# Quanters' Gate 3 AI Agent Handoff

## Purpose

This file exists solely to hand over project context, engineering constraints, and quantitative-correctness requirements to future AI agents. It is not a user guide, research report, or collaboration-process document. Before changing the project, an AI agent must read this file and `README.md`, then inspect the current code and tests instead of relying only on prior conversation history.

## Project Scope

This project is a cross-sectional equity-factor research pipeline for mainland China A-shares. Its current research scope focuses on historical CSI 300 constituents, monthly signals, 20-trading-day forward returns, and equal-weighted Top N portfolios. The system is intended for testing research hypotheses; it is not a broker integration, automated execution system, or production-grade capital-management platform.

The only entry point is the root-level `main.py`, which calls `quanters_gate.cli.main`. Implementation code lives in `src/quanters_gate/`, and tests live in `tests/`. The environment, project installation, dependencies, and lockfile are managed through uv.

## Module Responsibilities

- `cli.py`: Chinese-language CLI, argument defaults, and validation of mutually exclusive primary modes.
- `workflows.py`: Orchestration for constituent history, research prices, execution prices, and research workflows.
- `settings.py`: Research parameters and Lixinger API constants.
- `paths.py`: All project data paths.
- `dates.py`: Centralized conversion from external timestamps to Shanghai trading dates.
- `validation.py`: Shared input validation across modules.
- `lixinger.py`: Authentication, HTTP sessions, API response validation, and source-field conversion.
- `cache.py`: Per-security caches with requested-range and price-type metadata.
- `cleaning.py`: Validation of daily fields, numeric values, OHLC relationships, duplicate rows, and tradability.
- `universe.py`: Security-code normalization, constituent history, and `eligible_on_signal_date`.
- `factors.py`: 20-day momentum, 5-day reversal, 20-day volatility, and turnover proxy.
- `preprocessing.py`: Daily cross-sectional MAD winsorization and z-score standardization.
- `returns.py`: Forward close-to-close returns and next-open execution returns.
- `evaluation.py`: Non-overlapping Rank IC, quantile returns, and Top-Bottom spreads.
- `portfolio.py`: Monthly Top N portfolios, turnover, costs, and backtest summaries.

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
- Changes to quantitative logic must include minimal regression tests capable of exposing look-ahead bias, index-removal errors, and missing execution prices.
- Generated report fields and paths are auditable interfaces. Intentional changes require corresponding updates to tests and `README.md`.

## Data Cache Contract

Every per-security CSV must have a matching `.meta.json` file containing:

- `requested_start`
- `requested_end`
- `price_type`

A cache may be reused only when its metadata covers the requested interval, its price type matches the request, and its non-empty CSV contains only valid trading dates. Every CSV row must also match the security encoded by the filename and the requested price type. Legacy caches without metadata must be fetched again.

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
