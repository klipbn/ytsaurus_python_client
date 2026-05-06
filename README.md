<h1 align="center">YTsaurus Python Client</h1>

<p align="center">
  <b>
A lightweight Python helper library for day-to-day work with YTsaurus - https://ytsaurus.tech YQL and pandas DataFrames</b>
</p>

The project wraps common analytics workflows into a small, readable API:

- run YQL queries and return results as `pandas.DataFrame`
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

## License

MIT © 2026 Aleksey Voronko
