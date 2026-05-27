<h1 align="center">YTsaurus Python Client</h1>

<p align="center">
  <b>
A lightweight Python helper library for day-to-day work with YTsaurus - https://ytsaurus.tech YQL and pandas DataFrames</b>
</p>

The project wraps common analytics workflows into a small, readable API:

- run YQL queries and return results as `pandas.DataFrame`
- read large query outputs through temporary YTsaurus tables
- write YQL results directly into YTsaurus tables
- upload pandas DataFrames into YTsaurus tables

This repository is designed as a clean portfolio-friendly version of the client: no company-specific hosts, pools, paths, tokens, or internal links are hardcoded

## Installation

```bash
pip install ytsaurus_python_client
```

```bash
pip install -e .
```

## Requirements

- Python 3.9+
- `pandas`
- `numpy`
- YTsaurus Python client with `yt.wrapper`

## Configuration

The library is configured through environment variables or explicit constructor arguments.

| Variable | Purpose | Default |
|---|---|---|
| `YT_PROXY` | YTsaurus proxy host | empty |
| `YT_TOKEN_PATH` | Path to a local token file | `~/.yt/token` |
| `YT_DEFAULT_TEMP_DIR` | Temp folder for large YQL result materialization | `//tmp/ytsaurus-python-client` |
| `YT_POOL` | Optional YQL pool pragma | unset |
| `YT_UI_BASE_URL` | Optional web UI base URL used only for printed links | unset |

Example:

```bash
export YT_PROXY="your-ytsaurus-proxy.example.com"
export YT_TOKEN_PATH="$HOME/.yt/token"
export YT_DEFAULT_TEMP_DIR="//home/your-login/tmp"
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

## Public API

```python
from ytsaurus_python_client import (
    YTsaurusHook,
    DOYTHook,          # backward-compatible alias
)
```

## Design notes

- Defaults are intentionally generic and safe for public repositories
- Secrets are never hardcoded. Use `YT_TOKEN`, `YT_TOKEN_PATH`, or explicit arguments
- Printed YTsaurus UI links are optional and controlled by `YT_UI_BASE_URL`
- YQL pragmas can be provided through `query_pragma_config` or environment variables such as `YT_POOL`
- `DOYTHook` is kept as a backward-compatible alias; new code should prefer `YTsaurusHook`

## License

MIT © 2026 Aleksey Voronko
