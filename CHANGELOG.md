# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.4.0] - 2026-07-01

### Added
- **CHYT** support over HTTP:
- `chyt_raw(sql)` — runs raw queries (`CREATE`, `INSERT`, `DROP`)

### Changed
- New functions `hook.yql` and `hook.yql_unlim` replaced the old `hook.run_yql_to_df` and `hook.run_yql_to_df_unlimited` for naming consistency
- New functions `chyt_df`, `chyt_to_yt`, `chyt_raw` replaced the old `query_chyt_to_df`, `upload_df_to_chyt`, `query_chyt_raw`
- Improved network error handling (auto-retry, fallback to `/api/v4/chyt`)

### Fixed
- Fixed the `Sort order violation` error when uploading string keys — sorting is now performed automatically

---

## [0.3.0] - 2026-06-17

### Added
- Progress bar for reading results:
  - A single progress line without console spam: `rows`, `bytes≈`, `%`, `speed`, `elapsed`
  - `yql_unlim` additionally prints expected table metrics (when available): `expected rows≈…`, `expected bytes≈…`
- Helpers:
  - `_get_table_stats(path)` — safe reading of `@row_count`, `@uncompressed_data_size`, `@compressed_data_size`, `@chunk_count` with type coercion
  - `_progress_printer(...)` — unified progress output format
  - `_sanitize_json_line(...)` — a utility for gentle cleanup of "dirty" JSON lines (NaN/Infinity/trailing commas); used inside the streaming parser

### Changed
- `yql`:
  - Simplified reader: reads only `JSON (raw=True)` with incremental LJSON parsing by `\n`
  - No longer **raises exceptions** and no longer **prints tracebacks** — on error it prints a readable message and returns an empty `DataFrame`
  - Clear JSON error messages and `NaN/Infinity` hints on how to rewrite the query
- `yql_unlim`:
  - Wrapping the final `SELECT` into `INSERT INTO <temp_table> WITH (TRUNCATE, EXPIRATION="…")` — as before, but the reader is now only `JSON (raw=True)` with chunking, progress and "quiet" behavior on errors (empty `DataFrame`)
  - The final-select detector became more robust: `^\s*select\b` (matches `SELECT*`, `SELECT\t`, `SELECT\n`, etc.)
  - When no final `SELECT` is present, the function does not crash but prints `[YQL ERROR]` and returns an empty `DataFrame`
- Logs:
  - All service messages unified to a consistent style (`[YT TEMP TABLE]`, `[YT META]`, `[YQL JSON ERROR]`, `[YQL ERROR]`)

### Removed
- Query-result reading fallbacks:
  - Removed the `JSON(raw=True) → JSON(raw=False) → YSON` transitions and the retries through a temp table inside `yql`
  - No more dependency on YSON bindings when reading results (eliminates errors like `YSON bindings required`)
- Traceback printing on export errors — now only short human-readable messages

### Notes / Breaking changes
- `yql` and `yql_unlim` **return an empty `DataFrame`** on errors and print a readable message (no exceptions)
- If the query result contains `NaN/Infinity/-Infinity`, the YTsaurus server does not return valid JSON.
  Such values must be **cleaned** in the YQL itself, for example:
  ```sql
  CASE WHEN denom = 0 OR denom IS NULL THEN NULL ELSE num/denom END AS metric
  -- or
  num / NULLIF(denom, 0) AS metric
  -- or (if available)
  CASE WHEN isnan(metric) THEN NULL ELSE metric END AS metric
  ```
- For `yql_unlim` to work correctly, the final `SELECT` must be present explicitly (detected by `^\s*select\b`)

---

## [0.2.0] - 2026-05-27

### Added
- `yql_unlim` function:
  - Solves the YTsaurus limitation on exporting more than 10k rows
  - Runs a YQL query and stores the result in a temporary table with a configurable name and TTL
  - Loads the result into a Pandas DataFrame without a row limit

### Changed
- Updated documentation on data export methods, added descriptions of temporary table parameters

---

## [0.1.0] - 2026-05-06

### Added
- Project and library initialization
- Support for connecting to YTsaurus through YQL
- Methods:
  - `yql` — run YQL queries and load results into a DataFrame
  - `upload_df_to_yt` — upload a DataFrame to YTsaurus
  - `execute_internal` — low-level query execution
- Support for working with temporary tables
- Configurable connection and pool parameters
