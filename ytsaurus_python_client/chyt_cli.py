from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from io import StringIO
from typing import Optional, List, Dict

import numpy as np
import pandas as pd

from .config import CHYT_CLIQUE_ALIAS, YT_DEFAULT_PROXY

CHYT_CLIQUE = CHYT_CLIQUE_ALIAS
YT_PROXY = YT_DEFAULT_PROXY
YT_BINARY = os.getenv("YT_BINARY", "yt")


class CHYTError(RuntimeError):
    """Raised when a CHYT or YTsaurus CLI command fails."""


def _normalize_alias(alias: str) -> str:
    alias = alias.strip()
    return alias if alias.startswith("*") else f"*{alias}"


def _build_env(yt_proxy: str = YT_PROXY, extra_env: Optional[Dict[str, str]] = None) -> dict:
    env = os.environ.copy()
    if yt_proxy:
        env["YT_PROXY"] = yt_proxy
    if extra_env:
        env.update(extra_env)
    return env


def _strip_trailing_format_clause(sql: str) -> str:
    return re.sub(
        r"\s+FORMAT\s+[A-Za-z0-9_]+(?:\s*)$",
        "",
        sql.strip().rstrip(";"),
        flags=re.IGNORECASE,
    )


def _cmd_to_str(cmd: List[str]) -> str:
    return " ".join(shlex.quote(part) for part in cmd)


def _run_chyt_cli(
    query: str,
    clique_alias: str = CHYT_CLIQUE,
    yt_proxy: str = YT_PROXY,
    timeout: int = 1800,
    input_text: Optional[str] = None,
    data_format: Optional[str] = None,
) -> str:
    sql = query.strip().rstrip(";")
    alias = _normalize_alias(clique_alias)

    cmd = [YT_BINARY, "clickhouse", "execute", sql, "--alias", alias]
    if data_format:
        cmd.extend(["--format", data_format])

    try:
        proc = subprocess.run(
            cmd,
            input=input_text,
            text=True,
            capture_output=True,
            timeout=timeout,
            env=_build_env(yt_proxy),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise CHYTError(
            f"CHYT CLI timeout after {timeout} sec\n\n"
            f"Command:\n{_cmd_to_str(cmd)}\n\n"
            f"Query:\n{sql[:4000]}"
        ) from exc
    except FileNotFoundError as exc:
        raise CHYTError(
            "The `yt` binary was not found. Install the YTsaurus CLI and make sure "
            "it is available in PATH."
        ) from exc

    if proc.returncode != 0:
        raise CHYTError(
            "CHYT CLI query failed\n\n"
            f"Command:\n{_cmd_to_str(cmd)}\n\n"
            f"STDERR:\n{proc.stderr}\n\n"
            f"STDOUT:\n{proc.stdout}\n\n"
            f"Query:\n{sql[:4000]}"
        )

    return proc.stdout


def chyt_raw_cli(
    query: str,
    clique_alias: str = CHYT_CLIQUE,
    yt_proxy: str = YT_PROXY,
    timeout: int = 1800,
    data_format: Optional[str] = None,
) -> str:
    """Run a CHYT query through the YTsaurus CLI and return raw stdout."""
    return _run_chyt_cli(
        query=query.strip().rstrip(";"),
        clique_alias=clique_alias,
        yt_proxy=yt_proxy,
        timeout=timeout,
        data_format=data_format,
    )


def chyt_df_cli(
    query: str,
    clique_alias: str = CHYT_CLIQUE,
    yt_proxy: str = YT_PROXY,
    timeout: int = 1800,
) -> pd.DataFrame:
    """Run a CHYT SELECT query through the CLI and return a DataFrame."""
    sql = _strip_trailing_format_clause(query)
    raw = _run_chyt_cli(
        query=sql,
        clique_alias=clique_alias,
        yt_proxy=yt_proxy,
        timeout=timeout,
        data_format="TSVWithNames",
    )
    if not raw.strip():
        return pd.DataFrame()
    return pd.read_csv(StringIO(raw), sep="\t")


def _quote_identifier(name: str) -> str:
    return f"`{str(name).replace('`', '``')}`"


def _base_ch_type_from_dtype(dtype) -> str:
    if pd.api.types.is_integer_dtype(dtype):
        return "Int64"
    if pd.api.types.is_float_dtype(dtype):
        return "Double"
    if pd.api.types.is_bool_dtype(dtype):
        return "UInt8"
    if pd.api.types.is_datetime64_any_dtype(dtype):
        return "DateTime"
    return "String"


def _map_series_to_ch_type(series: pd.Series) -> str:
    base_type = _base_ch_type_from_dtype(series.dtype)
    if series.isna().any():
        return f"Nullable({base_type})"
    return base_type


def _escape_tsv_value(value) -> str:
    try:
        if pd.isna(value):
            return "\\N"
    except Exception:
        pass
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("\t", "\\t")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )


def _df_to_tsv_with_names(df: pd.DataFrame) -> str:
    header = "\t".join(str(col) for col in df.columns)
    rows = ["\t".join(_escape_tsv_value(value) for value in row) for row in df.itertuples(index=False, name=None)]
    return header + "\n" + "\n".join(rows) + "\n"


def _run_yt_cli(
    cmd: List[str],
    yt_proxy: str = YT_PROXY,
    timeout: int = 1800,
    input_text: Optional[str] = None,
) -> str:
    try:
        proc = subprocess.run(
            cmd,
            input=input_text,
            text=True,
            capture_output=True,
            timeout=timeout,
            env=_build_env(yt_proxy),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise CHYTError(
            f"YT CLI timeout after {timeout} sec\n\n"
            f"Command:\n{_cmd_to_str(cmd)}"
        ) from exc
    except FileNotFoundError as exc:
        raise CHYTError(
            "The `yt` binary was not found. Install the YTsaurus CLI and make sure "
            "it is available in PATH."
        ) from exc

    if proc.returncode != 0:
        raise CHYTError(
            "YT CLI command failed\n\n"
            f"Command:\n{_cmd_to_str(cmd)}\n\n"
            f"STDERR:\n{proc.stderr}\n\n"
            f"STDOUT:\n{proc.stdout}"
        )
    return proc.stdout


def _json_safe_value(value):
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, np.datetime64):
        return pd.Timestamp(value).strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def _df_to_json_lines(df: pd.DataFrame) -> str:
    lines = []
    for row in df.to_dict(orient="records"):
        safe_row = {str(col): _json_safe_value(value) for col, value in row.items()}
        lines.append(json.dumps(safe_row, ensure_ascii=False, separators=(",", ":")))
    return "\n".join(lines) + "\n"


def _yt_remove_if_exists(yt_path: str, yt_proxy: str = YT_PROXY, timeout: int = 1800) -> None:
    _run_yt_cli(
        cmd=[YT_BINARY, "remove", yt_path, "--force"],
        yt_proxy=yt_proxy,
        timeout=timeout,
    )


def chyt_to_yt_cli(
    df: pd.DataFrame,
    yt_path: str,
    overwrite: bool = True,
    order_by: Optional[List[str]] = None,
    clique_alias: str = CHYT_CLIQUE,
    yt_proxy: str = YT_PROXY,
    timeout: int = 1800,
    schema: Optional[Dict[str, str]] = None,
) -> None:
    """Create or append to a YTsaurus table and upload a DataFrame through the CLI."""
    if df.empty:
        raise ValueError("DataFrame is empty; there is nothing to upload.")

    if schema is None:
        schema = {col: _map_series_to_ch_type(df[col]) for col in df.columns}

    missing_cols = [col for col in df.columns if col not in schema]
    if missing_cols:
        raise ValueError("Schema is missing DataFrame columns: " + ", ".join(missing_cols))

    cols_sql = ",\n    ".join(f"{_quote_identifier(col)} {col_type}" for col, col_type in schema.items())

    order_sql = ""
    if order_by:
        order_cols = ", ".join(_quote_identifier(col) for col in order_by)
        order_sql = f"\nORDER BY ({order_cols})"

    if overwrite:
        _yt_remove_if_exists(yt_path=yt_path, yt_proxy=yt_proxy, timeout=timeout)

    create_sql = f"""
        CREATE TABLE IF NOT EXISTS {_quote_identifier(yt_path)}
        (
            {cols_sql}
        )
        ENGINE = YtTable()
        {order_sql}
        """.strip()

    chyt_raw_cli(create_sql, clique_alias=clique_alias, yt_proxy=yt_proxy, timeout=timeout)

    target_path = f"<append=%false>{yt_path}" if overwrite else yt_path
    payload = _df_to_json_lines(df)
    cmd = [YT_BINARY, "write-table", target_path, "--format", "<encode_utf8=%false>json"]
    _run_yt_cli(cmd=cmd, yt_proxy=yt_proxy, timeout=timeout, input_text=payload)


def chyt_check_cli(clique_alias: str = CHYT_CLIQUE, yt_proxy: str = YT_PROXY) -> pd.DataFrame:
    """Run a lightweight CHYT health check query."""
    return chyt_df_cli(
        """
        SELECT
            1 AS ok,
            version() AS ch_version,
            hostName() AS host
        """,
        clique_alias=clique_alias,
        yt_proxy=yt_proxy,
        timeout=60,
    )
