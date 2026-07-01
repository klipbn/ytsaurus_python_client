"""Small HTTP helpers for running CHYT queries and moving pandas data to YTsaurus."""

from __future__ import annotations

import os
from io import StringIO
from pathlib import Path
from typing import Optional, List
from urllib.parse import urljoin

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import CHYT_CLIQUE_ALIAS, CHYT_HOST, CHYT_PORT, YT_TOKEN_PATH


def _get_token(token_path: str | Path = YT_TOKEN_PATH) -> str:
    return Path(token_path).expanduser().read_text().strip()


def _session() -> requests.Session:
    session = requests.Session()
    adapter = HTTPAdapter(
        max_retries=Retry(total=3, backoff_factor=1.5, status_forcelist=[502, 503, 504])
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def _endpoints(host: str, port: int) -> list[str]:
    base = f"http://{host}:{port}/"
    return [urljoin(base, "chyt"), urljoin(base, "api/v4/chyt")]


def chyt_df(
    query: str,
    clique_alias: str = CHYT_CLIQUE_ALIAS,
    host: str = CHYT_HOST,
    port: int = CHYT_PORT,
    timeout: int = 1800,
) -> pd.DataFrame:
    """Run a CHYT SELECT query over HTTP and return the result as a DataFrame."""
    sql = query.strip().rstrip(";")
    if not sql.lower().endswith("format tsvwithnames"):
        sql += "\nFORMAT TSVWithNames"

    token = _get_token()
    session = _session()
    last_error: Optional[str] = None

    for url in _endpoints(host, port):
        try:
            response = session.post(
                url,
                params={
                    "chyt.clique_alias": clique_alias,
                    "default_format": "TSVWithNames",
                    "user": clique_alias,
                    "password": token,
                },
                data=sql.encode("utf-8"),
                headers={
                    "Authorization": f"OAuth {token}",
                    "Content-Type": "text/plain",
                    "Accept": "*/*",
                },
                timeout=timeout,
            )
            if response.ok:
                return pd.read_csv(StringIO(response.text), sep="\t")
            last_error = f"{response.status_code} - {response.text}"
        except requests.RequestException as exc:
            last_error = str(exc)

    raise RuntimeError(
        "CHYT query failed: no endpoint responded successfully.\n"
        f"Tried: {', '.join(_endpoints(host, port))}\n"
        f"Check host={host}, port={port}, clique_alias={clique_alias}.\n"
        f"Last error: {last_error}"
    )


def chyt_raw(
    query: str,
    clique_alias: str = CHYT_CLIQUE_ALIAS,
    host: str = CHYT_HOST,
    port: int = CHYT_PORT,
    timeout: int = 1800,
) -> str:
    """Run a CHYT query over HTTP and return the raw response text."""
    token = _get_token()
    session = _session()
    sql = query.strip().rstrip(";")
    last_error: Optional[str] = None

    for url in _endpoints(host, port):
        try:
            response = session.post(
                url,
                params={
                    "chyt.clique_alias": clique_alias,
                    "user": clique_alias,
                    "password": token,
                },
                data=sql.encode("utf-8"),
                headers={
                    "Authorization": f"OAuth {token}",
                    "Content-Type": "text/plain",
                },
                timeout=timeout,
            )
            if response.ok:
                return response.text
            last_error = f"{response.status_code} - {response.text}"
        except requests.RequestException as exc:
            last_error = str(exc)

    raise RuntimeError(
        "CHYT raw query failed: no endpoint responded successfully.\n"
        f"Tried: {', '.join(_endpoints(host, port))}\n"
        f"Last error: {last_error}"
    )


def chyt_to_yt(
    df: pd.DataFrame,
    yt_path: str,
    overwrite: bool = True,
    order_by: Optional[List[str]] = None,
    clique_alias: str = CHYT_CLIQUE_ALIAS,
    host: str = CHYT_HOST,
    port: int = CHYT_PORT,
) -> None:
    """Create a YTsaurus table through CHYT and insert a DataFrame as TSV."""

    def map_dtype(dtype) -> str:
        if pd.api.types.is_integer_dtype(dtype):
            return "Int64"
        if pd.api.types.is_float_dtype(dtype):
            return "Double"
        if pd.api.types.is_bool_dtype(dtype):
            return "UInt8"
        return "String"

    cols = ", ".join(f"`{col}` {map_dtype(dtype)}" for col, dtype in df.dtypes.items())
    order = f" ORDER BY ({', '.join(order_by)})" if order_by else ""
    create_sql = f"CREATE TABLE IF NOT EXISTS `{yt_path}` ({cols}) ENGINE = YtTable(){order}"
    chyt_raw(create_sql, clique_alias=clique_alias, host=host, port=port)

    target = f"<append=%false>{yt_path}" if overwrite else yt_path
    payload = df.to_csv(sep="\t", index=False)
    insert_sql = f"INSERT INTO `{target}` FORMAT TSVWithNames\n{payload}"
    chyt_raw(insert_sql, clique_alias=clique_alias, host=host, port=port)
