<h1 align="center">YTsaurus Python Client</h1>

<p align="center">
  <b>
A lightweight Python helper library for day-to-day work with YTsaurus - https://ytsaurus.tech YQL CHYT and pandas DataFrames</b>
</p>

<p align="center">
  <a href="https://pypi.org/project/ytsaurus_python_client/">
    <img src="https://img.shields.io/pypi/v/ytsaurus_python_client.svg" alt="PyPI version">
  </a>
  <img src="https://img.shields.io/badge/python-3.9%2B-blue" alt="Python 3.9+">
  <a href="https://github.com/klipbn/ytsaurus_python_client/blob/main/LICENSE">
    <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License">
  </a>
  <img src="https://img.shields.io/badge/status-alpha-orange" alt="Project status">
  <img src="https://img.shields.io/badge/notebook-friendly-purple" alt="Notebook friendly">
</p>

<p align="center">
  <a href="https://pypi.org/project/ytsaurus_python_client/">PyPI</a>
  ·
  <a href="https://github.com/klipbn/ytsaurus_python_client">GitHub</a>
  ·
  <a href="https://github.com/klipbn/ytsaurus_python_client/blob/main/examples/ytsaurus_python_client_example.ipynb">Example notebook</a>
  ·
  <a href="https://github.com/klipbn/ytsaurus_python_client/issues">Issues</a>
</p>

The project wraps common analytics workflows into a small, readable API:

- run YQL queries and return results as `pandas.DataFrame`
- start long-running YQL queries without blocking the notebook
- write YQL results directly into YTsaurus tables
- read large query outputs through temporary YTsaurus tables with progress reporting
- execute CHYT queries through HTTP or the YTsaurus CLI
- upload pandas DataFrames into YTsaurus tables

This repository is designed as a clean portfolio-friendly version of the client: no company-specific hosts, pools, paths, tokens, or internal links are hardcoded

## Installation

```bash
pip install ytsaurus_python_client
```

```bash
pip install -e .
```

For production packaging:

```bash
python -m build
pip install dist/ytsaurus_python_client-*.whl
```

## Requirements

- Python 3.9+
- `pandas`
- `requests`
- `numpy`
- YTsaurus Python client with `yt.wrapper`
- Optional: YTsaurus CLI binary `yt` for CLI-based CHYT helpers

## Configuration

The library is configured through environment variables or explicit constructor arguments.

| Variable | Purpose | Default |
|---|---|---|
| `YT_PROXY` | YTsaurus proxy host | empty |
| `YT_TOKEN` | OAuth/token value used by HTTP CHYT helpers | read from `YT_TOKEN_PATH` |
| `YT_TOKEN_PATH` | Path to a local token file | `~/.yt/token` |
| `YT_DEFAULT_TEMP_DIR` | Temp folder for large YQL result materialization | `//tmp/ytsaurus-python-client` |
| `YT_POOL` | Optional YQL pool pragma | unset |
| `YT_UI_BASE_URL` | Optional web UI base URL used only for printed links | unset |
| `CHYT_HOST` | CHYT HTTP host | `YT_PROXY` |
| `CHYT_PORT` | CHYT HTTP port | `8123` |
| `CHYT_CLIQUE_ALIAS` | Default CHYT clique alias | `ch_public` |
| `YT_BINARY` | YTsaurus CLI binary name/path | `yt` |

Example:

```bash
export YT_PROXY="your-ytsaurus-proxy.example.com"
export YT_TOKEN_PATH="$HOME/.yt/token"
export YT_DEFAULT_TEMP_DIR="//home/your-login/tmp"
export CHYT_CLIQUE_ALIAS="ch_public"
```

## Quick start

### Run a YQL query

```python
from ytsaurus_python_client import YTsaurusHook

hook = YTsaurusHook(
    yt_proxy="your-ytsaurus-proxy.example.com",
    yt_query_result_temp_dir="//home/your-login/tmp",
)

df = hook.yql("""
SELECT
    1 AS id,
    "hello" AS value;
""")

print(df)
```

### Start a long-running query and return the query ID

```python
query_id = hook.yql(
    """
    INSERT INTO `//home/your-login/output_table`
    SELECT *
    FROM `//home/your-login/source_table`;
    """,
    wait=False,
)

print(query_id)
```

### Execute a query and wait without reading the result

```python
query_id = hook.yql_wait("""
CREATE TABLE `//home/your-login/example_table` (
    id Int64,
    value String
);
""")
```

### Control query result access

All YQL methods accept an `access_control_objects` parameter (YT subjects: `everyone-read`, `everyone-use`, `everyone`, `nobody`). A default value can also be set for the whole hook via `query_access_control_objects`:

```python
hook = YTsaurusHook(
    yt_proxy="your-ytsaurus-proxy.example.com",
    query_access_control_objects=["everyone-read"],
)

df = hook.yql(
    "SELECT * FROM `//home/your-login/table`",
    access_control_objects=["everyone-read"],
)
```

### Materialize a large YQL result into a temp table and read it in chunks

```python
df = hook.yql_unlim(
    """
    SELECT *
    FROM `//home/your-login/large_table`;
    """,
    chunksize=500_000,
)
```

### Upload a DataFrame to YTsaurus

```python
import pandas as pd

from ytsaurus_python_client import YTsaurusHook

hook = YTsaurusHook(yt_proxy="your-ytsaurus-proxy.example.com")

df = pd.DataFrame({"id": [1, 2], "name": ["Alice", "Bob"]})
schema = hook.generate_yt_schema(df)

hook.upload_df_to_yt(
    df=df,
    yt_path="//home/your-login/users",
    schema=schema,
    overwrite=True,
)
```

### Run a CHYT query over HTTP

```python
from ytsaurus_python_client import chyt_df

df = chyt_df(
    """
    SELECT 1 AS ok
    """,
    host="your-chyt-host.example.com",
    clique_alias="ch_public",
)
```

### Run a CHYT query through the YTsaurus CLI

```python
from ytsaurus_python_client import chyt_df_cli

df = chyt_df_cli(
    "SELECT 1 AS ok",
    yt_proxy="your-ytsaurus-proxy.example.com",
    clique_alias="ch_public",
)
```

## Public API

```python
from ytsaurus_python_client import (
    YTsaurusHook,
    DOYTHook,          # backward-compatible alias
    chyt_df,
    chyt_raw,
    chyt_to_yt,
    chyt_df_cli,
    chyt_raw_cli,
    chyt_to_yt_cli,
    chyt_check_cli,
)
```

## Design notes

- Defaults are intentionally generic and safe for public repositories
- Secrets are never hardcoded. Use `YT_TOKEN`, `YT_TOKEN_PATH`, or explicit arguments
- Printed YTsaurus UI links are optional and controlled by `YT_UI_BASE_URL`
- YQL pragmas can be provided through `query_pragma_config` or environment variables such as `YT_POOL`
- `DOYTHook` is kept as a backward-compatible alias; new code should prefer `YTsaurusHook`

## Repository hygiene

Before publishing, the project was cleaned from:

- macOS metadata files
- Python cache files
- internal company hosts and UI links
- internal pools and temp paths
- Russian comments and runtime messages
- local tokens or secret values


## License

MIT © 2026 Alexey Voronko