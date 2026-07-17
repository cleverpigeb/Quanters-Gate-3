# Quanters' Gate 3 AI Agent Handoff

## Purpose

`AGENTS.md` exists solely to hand over project context, engineering constraints, and quantitative-correctness requirements to future AI agents. It is not a user guide, research report, or collaboration-process document. Before changing the project, an AI agent must read this file and `README.md`, then inspect the current code and tests instead of relying only on prior conversation history.

## Project Scope

This project is a cross-sectional equity-factor research pipeline for mainland China A-shares. Its current research scope focuses on historical CSI 300 constituents, monthly signals, 20-trading-day forward returns, and equal-weighted Top N portfolios. The system is intended for testing research hypotheses; it is not a broker integration, automated execution system, or production-grade capital-management platform.

The only entry point is the root-level `main.py`, which calls `quanters_gate.cli.main`. Implementation code lives in `src/quanters_gate/`, and tests live in `tests/`. The environment, project installation, dependencies, and lockfile are managed through uv.

## Module Responsibilities

- `cli.py`: Chinese-language CLI, argument defaults, primary-mode validation, and concrete provider selection.
- `workflows.py`: Application orchestration for constituent history, market data, fundamental history, research, and backtests.
- `settings.py`: Typed loading and strict validation of the versioned TOML configuration.
- `paths.py`: All project data paths.
- `validation.py`: Shared input validation across subpackages.
- `storage.py`: Shared atomic CSV/JSON/text writers and SHA-256 file hashing.
- `data/provider.py`: Provider protocols, the factory type, and bounded sequential multi-security retrieval.
- `data/akshare.py`: AKShare field conversion, price-convention mapping, and source-snapshot validation.
- `data/lixinger.py`: Authentication, HTTP sessions, API response validation, and source-field conversion.
- `data/cache.py`: Per-security caches with auditable metadata and content-identity checks.
- `data/cleaning.py`: Validation of daily fields, numeric values, OHLC relationships, duplicate rows, and tradability.
- `data/fundamentals.py`: Financial-summary normalization and point-in-time attachment after a conservative disclosure-date lag.
- `data/dates.py`: Shanghai trading-date normalization and global-calendar position mapping.
- `data/universe.py`: Security-code normalization, constituent history, and `eligible_on_signal_date`.
- `research/factors.py`: Calendar-aligned 20/60-day momentum, 5-day reversal, 20-day volatility, turnover proxy, Amihud illiquidity, turnover surprise, and maximum daily return.
- `research/preprocessing.py`: Daily cross-sectional MAD winsorization and z-score standardization.
- `research/returns.py`: Calendar-aligned forward close-to-close research returns.
- `research/evaluation.py`: Non-overlapping Rank IC, quantile returns, Top-Bottom spreads, factor diagnostic summaries, and pairwise factor rank correlations.
- `backtest/portfolio.py`: Monthly Top N portfolios, turnover, costs, and backtest summaries.
- `backtest/execution.py`: Calendar-aligned next-open execution returns based on unadjusted prices and tradability.

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
- Do not reintroduce the removed AkShare moving-average exercise or `matplotlib`. `akshare` is retained only as a provider dependency.
- Data downloads must remain bounded, sequential, and resumable. Do not send aggressively concurrent requests to any provider.
- Preserve the three bounded subpackages: `data` for acquisition and eligibility, `research` for factor analysis, and `backtest` for portfolio and execution logic. Cross-cutting infrastructure and application orchestration stay at the package root.
- `data/cache.py` and `workflows.py` must depend on provider protocols, not on `LixingerClient`. The CLI is the composition root that selects the concrete provider implementation.
- Low-level `data` modules must receive price conventions explicitly and must not import `PROJECT_CONFIG`.
- Changes to quantitative logic must include minimal regression tests capable of exposing look-ahead bias, index-removal errors, and missing execution prices.
- Generated report fields and paths are auditable interfaces. Intentional changes require corresponding updates to tests and `README.md`. Factor diagnostics are research evidence only and must not silently invert factor directions or alter portfolio weights.

## Configuration Contract

The `config/default.toml` file is the single version-controlled source of research defaults and includes an explicit `schema_version`. It is opened read-only and validated at process startup; normal execution must never rewrite, normalize, or format this authoritative input. The loader contains no fallback research parameters. It records the research interval, forward-return and evaluation parameters, random seed, default symbols, benchmark index, rebalance frequency, download batch sizes, data provider, price conventions, portfolio size, transaction cost, and factor weights.

Command-line values may temporarily override the supported date, symbol, horizon, and batch-size defaults. After a successful research run, the fully resolved configuration and run-mode flags must be atomically saved as `data/reports/run_config.toml`; this artifact must contain the effective overrides rather than a copy of defaults. Secrets must never be stored in TOML: if the Lixinger provider is selected, its token remains an environment or untracked `.env` value. `settings.py` must reject malformed, incomplete, unsupported, or quantitatively unsafe configuration instead of silently falling back to hidden constants.

## Data Cache Contract

Every per-security CSV must have a matching `.meta.json` file containing:

- `schema_version`
- `provider`
- `requested_start`
- `requested_end`
- `observed_start`
- `observed_end`
- `price_type`
- `row_count`
- `content_sha256`
- `built_at`

When AKShare provides a cache, the CSV and metadata must additionally record its single actual `data_source` (`eastmoney` or `sina`); legacy AKShare caches lacking it must be fetched again. Tencent's daily interface does not provide transaction value and must not be used to fabricate the required `amount` field.

A cache may be reused only when its schema and provider match the current implementation, its metadata covers the requested interval, its recorded observed date range exactly matches the valid dates in the CSV, its price type matches the request, its row count and SHA-256 digest match the CSV, and its non-empty CSV contains only valid trading dates. `observed_start` may be later than `requested_start` for a stock that was not yet listed; this is an audited availability boundary rather than fabricated missing data. Every CSV row must also match the security encoded by the filename and the requested price type. The CSV is replaced atomically before the metadata is committed, so an interrupted update leaves a detectable mismatch instead of a silently reusable mixed pair. Legacy or incomplete caches must be fetched again.

## Current Frozen Data Snapshot

The corrected shared-data snapshot is `000300_ME_20210101_20260630_akshare_v1`. It retains the existing audited `000300_ME_membership.csv`, which contains 66 month-end snapshots, 19,800 membership rows, and 459 unique historical securities from 2021-01-29 through 2026-06-30. AKShare was used only to retrieve complete per-security prices for that historical symbol set; it was not used to infer or backfill historical membership.

Both price conventions have 459 valid CSV/metadata pairs. The forward-adjusted research panel contains 593,334 rows, and the unadjusted execution panel contains 593,335 rows. Both panels cover all 459 historical securities, including `688072`, and retain prices outside membership periods. The research panel has 201,096 rows with `eligible_on_signal_date=False`; these rows remain available for factor lookback and post-removal portfolio valuation.

The membership history, per-security caches, and merged panels remain valid frozen inputs. A later audit found that the code used to build v1 advanced factor and return windows by per-security row position, which could bridge a missing security-level trading date. Current code uses exact positions in the global market calendar and leaves the result missing when the required security bar is absent. Therefore, v1's factor, evaluation, and backtest artifacts are historical outputs of commit `83a0547facb53c42be342fc402dc077868c49063`, not outputs of the current corrected calculation. Exact configuration, membership, cache-set, artifact, and archive identities are recorded in `snapshots/000300_ME_20210101_20260630_akshare_v1.toml`. The matching archive is `data/snapshots/000300_ME_20210101_20260630_akshare_v1.zip`; Git LFS tracks this archive while expanded and generated `data/` contents remain ignored. After cloning, run `git lfs pull` and extract the archive into the project's `data/` directory because the archive root directly contains `market/`, `universe/`, `factors/`, and `reports/`. Never overwrite a frozen snapshot in place. Create a new snapshot identifier and manifest whenever source data, configuration, or calculation code changes.

Financial history is not part of the frozen v1 snapshot. `--build-fundamental-history` fetches AKShare financial abstracts and three statement update dates sequentially into `data/fundamentals/raw/by_symbol/`, with a SHA-256 metadata file per security. It must be rerun until all historical universe symbols are cached. The processed panel uses the latest report whose conservative availability date is strictly before a signal date; it must never treat a report-period end date or same-day disclosure as tradable information. Only after a complete processed panel exists may historical research attach the four financial candidates.

AKShare's constituent interface still provides only a current snapshot and cannot reconstruct monthly historical membership. Exact reproduction of all v1 artifacts requires the manifest's `project_commit`. With current code, starting from the audited membership file, use the following sequence and freeze the regenerated outputs under a new snapshot identifier after the code has been committed:

```powershell
uv run python main.py --build-market-history
uv run python main.py --build-execution-history
uv run python main.py --run-market-history --with-evaluation --with-backtest --with-execution-backtest
```

When using a provider that supports historical constituent snapshots, run `--build-universe-history` first. Each history-build command must be rerun until all per-security caches are complete before generating reports or creating a new frozen snapshot.

## Development Validation

After every code change, run at least:

```powershell
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

For changes to research calculations, also compare output row counts, fields, ordering, numerical differences, and runtime against the complete shared panel. Performance improvements must not reduce the valid sample, alter missing-value rules, or lower calculation precision.
