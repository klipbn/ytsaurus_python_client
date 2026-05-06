"""Configuration defaults for the YTsaurus Python client."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return int(value)


YT_DEFAULT_PROXY = os.getenv("YT_PROXY", "")
YT_ALTERNATIVE_PROXY = os.getenv("YT_ALTERNATIVE_PROXY", "")
YT_DEFAULT_TEMP_DIR = os.getenv("YT_DEFAULT_TEMP_DIR", "//tmp/ytsaurus-python-client")
YT_TOKEN_PATH = Path(os.getenv("YT_TOKEN_PATH", "~/.yt/token")).expanduser()
YT_UI_BASE_URL = os.getenv("YT_UI_BASE_URL", "")

CHYT_HOST = os.getenv("CHYT_HOST", YT_DEFAULT_PROXY)
CHYT_PORT = _env_int("CHYT_PORT", 8123)
CHYT_URL = os.getenv("CHYT_URL", f"http://{CHYT_HOST}/chyt" if CHYT_HOST else "")
CHYT_CLIQUE_ALIAS = os.getenv("CHYT_CLIQUE_ALIAS", "ch_public")

DEFAULT_YQL_QUERY_PRAGMA_CONFIG: dict[str, Any] = {
    "AutoCommit": True,
}

if os.getenv("YT_POOL"):
    DEFAULT_YQL_QUERY_PRAGMA_CONFIG["yt.Pool"] = os.environ["YT_POOL"]
