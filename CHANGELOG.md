# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

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
