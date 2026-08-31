from typing import Optional, Any, Dict, Callable, Union, List
from time import sleep, time
import json
import re
import itertools as _it
import json as _json
import math
import os
import yt.wrapper
import pandas as pd
from yt.wrapper.format import JsonFormat, YsonFormat
from .config import (
    DEFAULT_YQL_QUERY_PRAGMA_CONFIG,
    YT_DEFAULT_PROXY,
    YT_DEFAULT_TEMP_DIR,
    YT_UI_BASE_URL,
)
from .exceptions import retry_on_retryable_exception
from .utils import extract_variables, strip_variables


class YQLQueryResponse:
    def __init__(self, data: Dict):
        self.data = data

    @classmethod
    def from_bytes(cls, res: bytes) -> "YQLQueryResponse":
        import json

        try:
            return cls(json.loads(res))
        except Exception as exc:
            raise Exception(f"Invalid YQL response: {res}. Error: {exc}")

    def get_state(self) -> str:
        try:
            return self.data["state"]
        except Exception:
            raise Exception(f"Missing 'state' in response: {self.data}")


class YtQueryResponse:
    def __init__(self, data: Dict):
        self.data = data

    def enumerate_errors(self, data: Optional[Dict] = None):
        if data is None:
            data = self.data.get("error")
        if not data:
            return
        message = data.get("message")
        if message:
            yield message
        for sub in data.get("inner_errors", []):
            yield from self.enumerate_errors(sub)

    def get_error_message(self) -> Optional[str]:
        import io

        buf = io.StringIO()
        for error in self.enumerate_errors():
            buf.write(error + "\n")
        return buf.getvalue().strip() or None


class YTsaurusHook:
    def __init__(
        self,
        yt_proxy: Optional[str] = None,
        yt_token: Optional[str] = None,
        yt_cluster_name: Optional[str] = None,
        query_engine: str = "yql",
        query_duration_timeout: int = 60000,
        query_output_table: Optional[str] = None,
        query_pragma_config: Optional[Dict[str, Any]] = None,
        client_config: Optional[Dict[str, Any]] = None,
        yt_query_result_temp_dir: str = YT_DEFAULT_TEMP_DIR,
        yt_ui_base_url: Optional[str] = None,
        query_access_control_objects: Optional[List[str]] = None,
        *args,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.yt_proxy = yt_proxy or YT_DEFAULT_PROXY
        self.yt_token = yt_token
        self.yt_query_result_temp_dir = yt_query_result_temp_dir
        self.yt_cluster_name = yt_cluster_name or self._extract_cluster_name(self.yt_proxy)
        self.yt_ui_base_url = yt_ui_base_url if yt_ui_base_url is not None else YT_UI_BASE_URL
        self.query_engine = query_engine
        self.query_duration_timeout = query_duration_timeout
        self.query_output_table = query_output_table
        self.query_pragma_config = query_pragma_config or {}
        self.client_config = client_config or {}
        self.query_access_control_objects = query_access_control_objects or []
        self.client = self.get_client()

    @staticmethod
    def _extract_cluster_name(proxy: str) -> str:
        """
        Extract the YTsaurus cluster name from a proxy host.

        Handles HTTP-proxy hosts like ``42.http-proxy.hahn-yt.example.com``
        where the cluster name is the segment with the ``-yt`` suffix.
        Falls back to the first host segment.
        """
        for segment in proxy.split("."):
            if segment.endswith("-yt"):
                return segment[:-3]
        return proxy.split(".")[0]

    # ===== helpers =====
    def _get_table_stats(self, table_path: str) -> dict:
        """
        @row_count / @uncompressed_data_size / @compressed_data_size / @chunk_count
        """
        import json as _json

        stats: dict[str, int] = {}

        def _to_int(val):
            if val is None:
                return None
            if isinstance(val, (int, bool)):
                return int(val)
            if isinstance(val, float):
                return int(val)
            if isinstance(val, (bytes, bytearray)):
                s = val.decode("utf-8", "ignore").strip()
            elif isinstance(val, str):
                s = val.strip()
            else:
                try:
                    return int(str(val))
                except Exception:
                    return None
            try:
                j = _json.loads(s)
                return (
                    int(j)
                    if isinstance(j, (int, float))
                    or (isinstance(j, str) and j.isdigit())
                    else None
                )
            except Exception:
                pass
            try:
                return int(s)
            except Exception:
                return None

        for attr in (
            "row_count",
            "uncompressed_data_size",
            "compressed_data_size",
            "chunk_count",
        ):
            try:
                raw = self.client.get(f"{table_path}/@{attr}", format="json")
                val = _to_int(raw)
                if val is not None:
                    stats[attr] = val
            except Exception:
                pass
        return stats

    def _progress_printer(
        self,
        *,
        rows_read: int,
        bytes_read: Optional[int],
        total_rows: Optional[int],
        total_bytes: Optional[int],
        t0: float,
    ) -> None:
        """
        Print a compact single-line progress indicator while reading YTsaurus data.
        """
        elapsed = time() - t0
        rate = rows_read / elapsed if elapsed > 0 else 0.0

        head = f"[YT READ] rows={rows_read:,}"
        if total_rows:
            pct = 100.0 * rows_read / max(1, total_rows)
            head += f" ({pct:5.1f}%)"
        if bytes_read is not None:
            head += f"  bytes≈{bytes_read:,}"
            if total_bytes:
                bpct = 100.0 * bytes_read / max(1, total_bytes)
                head += f" ({bpct:5.1f}%)"

        tail = f"  speed≈{rate:,.0f} rows/s  elapsed={elapsed:,.1f}s"
        msg = head + tail

        term_width = os.get_terminal_size().columns if os.isatty(1) else 120
        msg = msg[: term_width - 1]

        print("\r" + msg + " " * max(0, term_width - len(msg) - 1), end="", flush=True)

    def _iter_json_with_progress(
        self,
        it,
        *,
        report_every_rows: int = 200_000,
        report_every_sec: float = 1.5,
        total_rows: Optional[int] = None,
        total_bytes: Optional[int] = None,
        drop_bad_rows: bool = True,
        max_bad_rows: int = 10_000,
    ):
        """
        Yield JSON objects from a raw YTsaurus stream with tolerant parsing and progress output.
        """
        rows_read = 0
        bytes_read = 0
        bad_rows = 0
        t0 = time()
        next_t = t0 + report_every_sec

        try:
            import ujson as _fast_json
        except Exception:
            _fast_json = None
        try:
            import simplejson as _sj
        except Exception:
            _sj = None
        import json as _std_json

        def _try_parse_obj(s: str):
            if _fast_json is not None:
                try:
                    return _fast_json.loads(s)
                except Exception:
                    pass
            try:
                return _std_json.loads(s)
            except Exception:
                pass
            if _sj is not None:
                try:
                    return _sj.loads(s, strict=False, allow_nan=True)
                except Exception:
                    pass
            # sanitize -> simplejson
            s2 = self._sanitize_json_line(s)
            if _sj is not None:
                try:
                    return _sj.loads(s2, strict=False, allow_nan=True)
                except Exception:
                    pass
            # sanitize -> std
            return _std_json.loads(s2)

        buf = ""
        depth = 0
        in_str = False
        esc = False
        obj_start = None

        def _feed(s_chunk: str):
            nonlocal buf, depth, in_str, esc, obj_start, rows_read, bytes_read, next_t, bad_rows
            buf += s_chunk
            i = 0
            n = len(buf)
            while i < n:
                ch = buf[i]
                if in_str:
                    if esc:
                        esc = False
                    else:
                        if ch == "\\":
                            esc = True
                        elif ch == '"':
                            in_str = False
                else:
                    if ch == '"':
                        in_str = True
                    elif ch == "{":
                        if depth == 0:
                            obj_start = i
                        depth += 1
                    elif ch == "}":
                        if depth > 0:
                            depth -= 1
                            if depth == 0 and obj_start is not None:
                                obj_str = buf[obj_start : i + 1]
                                buf = buf[i + 1 :]
                                n = len(buf)
                                i = -1
                                obj_start = None
                                try:
                                    obj = _try_parse_obj(obj_str)
                                except Exception as e:
                                    bad_rows += 1
                                    if bad_rows <= 3:
                                        preview = self._sanitize_json_line(obj_str)[
                                            :180
                                        ].replace("\n", "\\n")
                                        print(
                                            f"\n[YT WARN] bad JSON object #{bad_rows}: {type(e).__name__}: {e}  -> preview: {preview}"
                                        )
                                    if bad_rows > max_bad_rows or not drop_bad_rows:
                                        raise
                                    i += 1
                                    continue
                                rows_read += 1
                                if (
                                    rows_read % report_every_rows == 0
                                    or time() >= next_t
                                ):
                                    self._progress_printer(
                                        rows_read=rows_read,
                                        bytes_read=bytes_read,
                                        total_rows=total_rows,
                                        total_bytes=total_bytes,
                                        t0=t0,
                                    )
                                    next_t = time() + report_every_sec
                                yield obj
                i += 1

        for chunk in it:
            if isinstance(chunk, (bytes, bytearray)):
                bytes_read += len(chunk)
                s = chunk.decode("utf-8", "ignore")
            else:
                s = str(chunk)
                bytes_read += len(s.encode("utf-8", "ignore"))
            yield from _feed(s)

        if depth != 0 and obj_start is not None:
            preview = self._sanitize_json_line(buf[obj_start:])[:180].replace(
                "\n", "\\n"
            )
            print(
                f"\n[YT WARN] truncated JSON tail (incomplete object) -> skipping. preview: {preview}"
            )
            bad_rows += 1

        self._progress_printer(
            rows_read=rows_read,
            bytes_read=bytes_read,
            total_rows=total_rows,
            total_bytes=total_bytes,
            t0=t0,
        )
        if bad_rows:
            print(f"\n[YT NOTICE] skipped malformed JSON objects: {bad_rows}")
        print()

    def _iter_yson_with_progress(
        self,
        it,
        *,
        report_every_rows: int = 200_000,
        report_every_sec: float = 1.5,
        total_rows: Optional[int] = None,
    ):
        """
        Yield objects from a YSON iterator and print read progress.
        """
        rows_read = 0
        t0 = time()
        next_t = t0 + report_every_sec
        for obj in it:
            rows_read += 1
            if rows_read % report_every_rows == 0 or time() >= next_t:
                self._progress_printer(
                    rows_read=rows_read,
                    bytes_read=None,
                    total_rows=total_rows,
                    total_bytes=None,
                    t0=t0,
                )
                next_t = time() + report_every_sec
            yield obj
        self._progress_printer(
            rows_read=rows_read,
            bytes_read=None,
            total_rows=total_rows,
            total_bytes=None,
            t0=t0,
        )

    def _iter_obj_with_progress(
        self,
        it,
        *,
        report_every_rows: int = 200_000,
        report_every_sec: float = 1.5,
        total_rows: Optional[int] = None,
    ):
        """
        Yield already-decoded objects while periodically printing read progress.
        """
        rows_read = 0
        t0 = time()
        next_t = t0 + report_every_sec
        for obj in it:
            rows_read += 1
            if rows_read % report_every_rows == 0 or time() >= next_t:
                self._progress_printer(
                    rows_read=rows_read,
                    bytes_read=None,
                    total_rows=total_rows,
                    total_bytes=None,
                    t0=t0,
                )
                next_t = time() + report_every_sec
            yield obj
        self._progress_printer(
            rows_read=rows_read,
            bytes_read=None,
            total_rows=total_rows,
            total_bytes=None,
            t0=t0,
        )
        print()

    def _sanitize_json_line(self, bline: Union[bytes, str]) -> str:
        """
        Clean a JSON line before tolerant parsing by replacing non-finite values and invalid bytes.
        """
        import re

        if isinstance(bline, (bytes, bytearray)):
            s = bline.decode("utf-8", "ignore")
        else:
            s = bline

        s = re.sub(r"(?i)(?P<key>:\s*)(NaN|Infinity|-Infinity)", r"\g<key>null", s)

        s = re.sub(r",(\s*[}\]])", r"\1", s)

        s = s.replace("\x00", "")

        return s

    def _query_url(self, query_id: str) -> str:
        if not self.yt_ui_base_url:
            return f"query_id={query_id}"
        base = self.yt_ui_base_url.rstrip("/")
        cluster = f"/{self.yt_cluster_name}" if self.yt_cluster_name else ""
        return f"{base}{cluster}/queries/{query_id}"

    def _navigation_url(self, table_path: str) -> str:
        if not self.yt_ui_base_url:
            return table_path
        base = self.yt_ui_base_url.rstrip("/")
        cluster = f"/{self.yt_cluster_name}" if self.yt_cluster_name else ""
        return f"{base}{cluster}/navigation?path={table_path}"

    def get_client(self) -> yt.wrapper.YtClient:
        config = yt.wrapper.default_config.get_config_from_env()
        config["proxy"].update(
            {
                "url": self.yt_proxy,
                "enable_proxy_discovery": False,
                "accept_encoding": "identity",
            }
        )
        if self.yt_token:
            config["token"] = self.yt_token
        config.update(self.client_config)
        return yt.wrapper.YtClient(config=config)

    def ls(self, path: str, **kwargs) -> Any:
        return self.client.list(path, **kwargs)

    def exists(self, path: str, **kwargs) -> bool:
        return self.client.exists(path, **kwargs)

    def create_temp_table(self, **kwargs) -> str:
        expiration_timeout = kwargs.pop("expiration_timeout", 1000 * 60 * 60 * 24)
        return self.client.create_temp_table(
            self.yt_query_result_temp_dir,
            prefix="temp_table_",
            expiration_timeout=expiration_timeout,
        )

    def get_table(self, table: str, **kwargs) -> Any:
        if not self.exists(table):
            raise Exception(f"Table {table} doesn't exist.")
        kwargs.setdefault("format", JsonFormat(encode_utf8=False, enable_ujson=True))
        kwargs.setdefault("raw", True)
        return self.client.read_table(table, **kwargs)

    @retry_on_retryable_exception(retries=8, delay=1, backoff=2)
    def get_query(self, query_id: str, **kwargs):
        kwargs.setdefault("format", JsonFormat(encode_utf8=False, enable_ujson=True))
        return self.client.get_query(query_id, **kwargs)

    def _prepare_query(self, raw_query: str) -> str:
        pragmas = {**DEFAULT_YQL_QUERY_PRAGMA_CONFIG, **self.query_pragma_config}
        pragma_lines = [
            (
                f'PRAGMA {k} = "{v}";'
                if not isinstance(v, bool)
                else f"PRAGMA {'Disable' if not v else ''}{k};"
            )
            for k, v in pragmas.items()
        ]
        return (
            f"USE {self.yt_cluster_name};\n"
            + "\n".join(pragma_lines)
            + "\n"
            + raw_query
        )

    def execute_internal(
        self,
        query: str,
        get_func: Callable[[str], Any],
        query_engine: Optional[str] = None,
        *,
        wait: bool = True,
        access_control_objects: Optional[List[str]] = None,
    ) -> Any:
        query_engine = query_engine or self.query_engine

        query_access_control_objects = (
            access_control_objects
            if access_control_objects is not None
            else self.query_access_control_objects
        )

        print(f"Executing query via {query_engine.upper()}")

        start_query_kwargs = {}
        if query_access_control_objects:
            start_query_kwargs["access_control_objects"] = query_access_control_objects

        query_id = self.client.start_query(query_engine, query, **start_query_kwargs)
        print(
            f"Started query id={query_id} -> {self._query_url(query_id)}"
        )

        if not wait:
            return query_id

        start_time = time()
        while True:
            q_resp = YQLQueryResponse.from_bytes(self.get_query(query_id))
            state = q_resp.get_state()
            if state == "completed":
                break
            elif state in ("aborted", "failed"):
                raise Exception(
                    f"Query failed ({state}): {YtQueryResponse(q_resp.data).get_error_message()}"
                )
            if time() - start_time > self.query_duration_timeout:
                self.client.abort_query(query_id, message="Query timeout")
                raise Exception(f"Query {query_id} exceeded timeout")
            sleep(10)

        print(f"Query {query_id} completed.")
        return get_func(query_id)


    def yql(
        self,
        query: str,
        wait: bool = True,
        read_result: bool = True,
        access_control_objects: Optional[List[str]] = None,
    ) -> Union[pd.DataFrame, str]:
        """
        Run a YQL query and optionally return the result as a pandas DataFrame.

        Use wait=False to start a long-running query and return its query ID immediately.
        Use read_result=False for DDL/DML queries where a DataFrame result is not needed.

        :param access_control_objects: Access control objects for the YTsaurus query.
            Possible values (YT subjects):
            - ``"everyone-read"`` — everyone can read the query result
            - ``"everyone-use"`` — everyone can use the query result
            - ``"everyone"`` — full access for everyone
            - ``"nobody"`` — owner-only access (default)
            Example:
                hook.yql("SELECT ...", access_control_objects=["everyone-read"])
        """

        def get_output(query_id: str) -> Any:
            import json as _json
            from json import JSONDecodeError

            print(f"-> Query ID: {query_id}")
            print(f"-> URL: {self._query_url(query_id)}")

            try:
                it = self.client.read_query_result(query_id, format="json", raw=True)

                buf = b""
                rows = []
                rows_read = 0
                bytes_read = 0
                t0 = time()
                next_t = t0 + 1.5

                for chunk in it:
                    if isinstance(chunk, (bytes, bytearray)):
                        bytes_read += len(chunk)
                        buf += chunk
                        parts = buf.split(b"\n")
                        buf = parts[-1]
                        lines = parts[:-1]
                    else:
                        s = str(chunk)
                        bytes_read += len(s.encode("utf-8", "ignore"))
                        parts = s.split("\n")
                        buf = parts[-1].encode("utf-8", "ignore")
                        lines = [p.encode("utf-8", "ignore") for p in parts[:-1]]

                    for bline in lines:
                        if not bline:
                            continue

                        line = bline.rstrip(b"\r").decode("utf-8", "ignore")

                        try:
                            obj = _json.loads(line)

                        except JSONDecodeError:
                            preview = line[:180].replace("\n", "\\n")

                            if "NaN" in line or "Infinity" in line or "Inf" in line:
                                print(
                                    "[YQL JSON ERROR] The result contains NaN/Infinity, so JSON cannot be returned.\n"
                                    "Rewrite the query to avoid division by zero and non-finite values.\n"
                                    "Examples:\n"
                                    "  CASE WHEN denom = 0 OR denom IS NULL THEN NULL ELSE num / denom END AS metric\n"
                                    "  num / NULLIF(denom, 0) AS metric\n"
                                    "  COALESCE(expr, 0)\n"
                                    f"Problematic row preview: {preview}"
                                )
                            else:
                                print(
                                    "[YQL JSON ERROR] Cannot parse a result row as JSON.\n"
                                    "Check SELECT expressions, quotes, commas, and special characters.\n"
                                    f"Problematic row preview: {preview}"
                                )

                            return pd.DataFrame()

                        rows.append(obj)
                        rows_read += 1

                        if time() >= next_t or rows_read % 200_000 == 0:
                            self._progress_printer(
                                rows_read=rows_read,
                                bytes_read=bytes_read,
                                total_rows=None,
                                total_bytes=None,
                                t0=t0,
                            )
                            next_t = time() + 1.5

                tail = buf.rstrip(b"\r\n")

                if tail:
                    line = tail.decode("utf-8", "ignore")

                    try:
                        obj = _json.loads(line)
                        rows.append(obj)
                        rows_read += 1

                    except JSONDecodeError:
                        preview = line[:180].replace("\n", "\\n")
                        print(
                            "[YQL JSON ERROR] The result tail is truncated or invalid; no complete JSON object was found.\n"
                            "Check the query and SELECT expressions: quotes, commas, NaN/Inf generation, etc.\n"
                            f"Problematic tail preview: {preview}"
                        )
                        return pd.DataFrame()

                self._progress_printer(
                    rows_read=rows_read,
                    bytes_read=bytes_read,
                    total_rows=None,
                    total_bytes=None,
                    t0=t0,
                )
                print()

                return pd.DataFrame.from_records(rows)

            except Exception as e:
                print(f"[YQL ERROR] Failed to read query result: {e}")
                return pd.DataFrame()

        def get_query_id_only(query_id: str) -> str:
            """
            """
            print(f"-> Query ID: {query_id}")
            print(f"-> URL: {self._query_url(query_id)}")
            return query_id

        query_str = self._prepare_query(query) if self.query_engine == "yql" else query

        if not wait:
            return self.execute_internal(
                query_str,
                lambda _: None,
                wait=False,
                access_control_objects=access_control_objects,
            )

        if not read_result:
            return self.execute_internal(
                query_str,
                get_query_id_only,
                wait=True,
                access_control_objects=access_control_objects,
            )

        return self.execute_internal(
            query_str,
            get_output,
            wait=True,
            access_control_objects=access_control_objects,
        )


    def yql_wait(
        self,
        query: str,
        access_control_objects: Optional[List[str]] = None,
    ) -> str:
        """
        Run a YQL query, wait for completion, and return the query ID without reading rows.

        :param access_control_objects: Access control objects for the YTsaurus query.
            Example:
                hook.yql_wait("INSERT INTO ...", access_control_objects=["everyone-read"])
        """

        return self.yql(
            query=query,
            wait=True,
            read_result=False,
            access_control_objects=access_control_objects,
        )


    def generate_yt_schema(
        self, df: pd.DataFrame, custom_type_map: dict = None
    ) -> list[dict]:
        """
        Generate a simple YTsaurus table schema from pandas dtypes.
        
        Pass custom_type_map to override inferred types for selected columns.
        """
        default_type_map = {
            "int64": "int64",
            "float64": "double",
            "bool": "boolean",
            "datetime64[ns]": "string",
            "object": "string",
        }

        schema = []
        for col, dtype in df.dtypes.items():
            dtype_str = str(dtype)
            yt_type = (
                custom_type_map[col]
                if custom_type_map and col in custom_type_map
                else default_type_map.get(dtype_str, "string")
            )
            schema.append({"name": col, "type": yt_type})
        return schema

    def upload_df_to_yt(
        self,
        df: pd.DataFrame,
        yt_path: str,
        schema: list[dict],
        format: str = "json",
        overwrite: bool = False,
        log_result: bool = True,
        **kwargs,
    ):
        """
        Upload a pandas DataFrame into a YTsaurus table using an explicit schema.
        """
        from yt.wrapper.format import JsonFormat, YsonFormat
        import math

        def sanitize_value(value):
            """Helper method."""
            if isinstance(value, float):
                if math.isnan(value) or math.isinf(value):
                    return None
                return value
            elif isinstance(value, (list, tuple)):
                return [sanitize_value(v) for v in value]
            elif isinstance(value, dict):
                return {k: sanitize_value(v) for k, v in value.items()}
            elif pd.isna(value):
                return None
            return value

        yt_format = {"json": JsonFormat(), "yson": YsonFormat()}.get(format)
        if yt_format is None:
            raise ValueError(f"Unsupported format: {format}")

        if overwrite:
            if self.client.exists(yt_path):
                self.client.remove(yt_path, force=True)
            self.client.create("table", yt_path, attributes={"schema": schema})
            print(f"Created table {yt_path} with schema: {schema}")
        else:
            yt_path = f"<append=%true>{yt_path}"

        data = df.to_dict(orient="records")
        data_clean = [sanitize_value(row) for row in data]

        self.client.write_table(yt_path, data_clean, format=yt_format, **kwargs)

        if log_result == True:
            print(
                f"DataFrame successfully written to -> Path: {self._navigation_url(yt_path)}"
            )
        else:
            pass

    def _is_use_or_pragma_line(self, line: str) -> bool:
        s = line.strip().lower()
        return s.startswith("use ") or s.startswith("pragma ")

    def _parse_header_lines(
        self, lines: list[str]
    ) -> tuple[Optional[str], dict[str, str]]:
        """
        Parse USE and PRAGMA lines into a cluster name and a pragma mapping.
        """
        use_cluster = None
        pragmas: dict[str, str] = {}
        for ln in lines:
            s = ln.strip().rstrip(";")
            if not s:
                continue
            low = s.lower()
            if low.startswith("use "):
                use_cluster = s.split(None, 1)[1].strip()
            elif low.startswith("pragma "):
                rest = s[7:].strip()
                key = rest.split("=", 1)[0].split(None, 1)[0].strip().lower()
                pragmas[key] = s + ";"
        return use_cluster, pragmas

    def _extract_use_and_pragmas(
        self, text: str
    ) -> tuple[str, Optional[str], dict[str, str]]:
        """
        Split query text into body SQL plus extracted USE/PRAGMA declarations.
        """
        header_lines, body_lines = [], []
        for ln in text.splitlines():
            if self._is_use_or_pragma_line(ln):
                header_lines.append(ln)
            else:
                body_lines.append(ln)
        use_cluster, pragmas = self._parse_header_lines(header_lines)
        return "\n".join(body_lines).strip(), use_cluster, pragmas

    def _system_pragmas_as_dict(self) -> tuple[str, dict[str, str]]:
        """
        Build default USE/PRAGMA declarations from hook configuration.
        """
        sys_use = self.yt_cluster_name
        merged_cfg = {
            **DEFAULT_YQL_QUERY_PRAGMA_CONFIG,
            **(self.query_pragma_config or {}),
        }
        sys_pragmas: dict[str, str] = {}
        for k, v in merged_cfg.items():
            if isinstance(v, bool):
                sys_pragmas[k.lower()] = f"PRAGMA {'Disable' if not v else ''}{k};"
            else:
                sys_pragmas[k.lower()] = f'PRAGMA {k} = "{v}";'
        return sys_use, sys_pragmas

    def _prepare_yql_header(
        self, user_vars_header: list[str], user_body_header: list[str]
    ) -> str:
        """
        Build a final YQL header with a single USE statement and de-duplicated pragmas.
        """
        sys_use, sys_pragmas = self._system_pragmas_as_dict()

        uvars_use, uvars_pr = self._parse_header_lines(user_vars_header)
        ubody_use, ubody_pr = self._parse_header_lines(user_body_header)

        # USE: user_vars > user_body > system
        final_use = uvars_use or ubody_use or sys_use
        header_lines = [f"USE {final_use};"]

        merged = dict(sys_pragmas)
        merged.update(uvars_pr)
        merged.update(ubody_pr)

        header_lines.extend(merged.values())
        return "\n".join(header_lines)

    def _prepare_yql_insert_wrapped(
        self, raw_query: str, out_table: str, expiration: str, overwrite: bool
    ) -> str:
        """
        Wrap a final SELECT query into INSERT INTO while preserving variables and pragmas.
        """
        import re

        if re.search(r"(?is)\binsert\s+into\b", raw_query):
            return raw_query.strip()

        vars_block = (extract_variables(raw_query) or "").strip()
        body_block = (strip_variables(raw_query) or "").strip()

        vars_clean, vars_use, vars_pragmas = self._extract_use_and_pragmas(vars_block)
        body_clean, body_use, body_pragmas = self._extract_use_and_pragmas(body_block)

        user_vars_header = []
        if vars_use:
            user_vars_header.append(f"USE {vars_use};")
        user_vars_header.extend(vars_pragmas.values())

        user_body_header = []
        if body_use:
            user_body_header.append(f"USE {body_use};")
        user_body_header.extend(body_pragmas.values())

        header = self._prepare_yql_header(user_vars_header, user_body_header)

        flags = []
        if overwrite:
            flags.append("TRUNCATE")
            if expiration:
                flags.append(f'EXPIRATION="{expiration}"')
        else:
            if expiration:
                print(
                    "[YQL NOTICE] EXPIRATION is ignored when overwrite=False because YQL EXPIRATION works only with TRUNCATE."
                )

        if flags:
            insert_line = f'INSERT INTO `{out_table}` WITH ({", ".join(flags)})'
        else:
            insert_line = f"INSERT INTO `{out_table}`"

        body_clean_s = body_clean.strip()
        if body_clean_s.endswith(";"):
            body_clean_s = body_clean_s[:-1].rstrip()

        vars_clean_s = vars_clean.strip()
        if vars_clean_s and not vars_clean_s.endswith(";"):
            vars_clean_s += ";"

        return "\n".join(
            p for p in [header, vars_clean_s, insert_line, body_clean_s] if p.strip()
        )

    def yql_unlim(
        self,
        query: str,
        temp_table_path: str = None,
        temp_table_expiration: str = "1d",
        chunksize: int = 500_000,
        overwrite: bool = True,
        show_progress: bool = True,
        report_every_rows: int = 200_000,
        report_every_sec: float = 1.5,
        access_control_objects: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """
        Run YQL through a temporary table and read a large result in chunks.

        This is useful when direct query-result reading is too memory-intensive or unstable.

        :param access_control_objects: Access control objects for the YTsaurus query.
            Possible values (YT subjects):
            - ``"everyone-read"`` — everyone can read the query result
            - ``"everyone-use"`` — everyone can use the query result
            - ``"everyone"`` — full access for everyone
            - ``"nobody"`` — owner-only access (default)
            Example:
                hook.yql_unlim("SELECT ...", access_control_objects=["everyone-read"])
        """
        import json as _json
        from json import JSONDecodeError

        try:
            if not temp_table_path:
                temp_table_path = self.create_temp_table()
            print(
                f"[YT TEMP TABLE] {self._navigation_url(temp_table_path)}"
            )

            select_matches = list(
                re.finditer(r"(?im)^\s*select\b", query)
            )
            if not select_matches:
                print(
                    "[YQL ERROR] No SELECT statement found in the query using pattern ^\\s*select\\b. "
                    "Check the syntax or add a final SELECT statement."
                )
                return pd.DataFrame()
            final_select_pos = select_matches[-1].start()

            header_part = query[:final_select_pos].rstrip()
            final_select_part = query[final_select_pos:].lstrip()

            insert_wrapped_query = (
                f"{header_part}\n\n"
                f'INSERT INTO `{temp_table_path}` WITH (TRUNCATE, EXPIRATION="{temp_table_expiration}")\n'
                f"{final_select_part}\n"
            )

            self.execute_internal(
                insert_wrapped_query, lambda _: None, query_engine="yql",
                access_control_objects=access_control_objects,
            )

            total_rows = total_bytes = None
            if show_progress:
                stats = self._get_table_stats(temp_table_path)
                total_rows = stats.get("row_count")
                total_bytes = stats.get("uncompressed_data_size") or stats.get(
                    "compressed_data_size"
                )
                if total_rows is not None:
                    print(f"[YT META] expected rows≈{total_rows:,}")
                if total_bytes is not None:
                    print(f"[YT META] expected bytes≈{total_bytes:,}")

            try:
                it = self.get_table(
                    temp_table_path,
                    format=JsonFormat(encode_utf8=False, enable_ujson=True),
                    raw=True,
                )
            except Exception as e_open:
                msg = str(e_open)
                if "Unexpected NaN or infinity" in msg:
                    print(
                        "[YQL JSON ERROR] The table contains NaN/Infinity, so JSON cannot be returned.\n"
                        "Rewrite the query to avoid division by zero and non-finite values.\n"
                        "Examples:\n"
                        "  CASE WHEN denom = 0 OR denom IS NULL THEN NULL ELSE num/denom END AS metric\n"
                        "  num/NULLIF(denom, 0) AS metric\n"
                        "  COALESCE(expr, 0)\n"
                        f"Table path: {temp_table_path}"
                    )
                    return pd.DataFrame()
                print(
                    f"[YQL ERROR] Failed to open table {temp_table_path}: {e_open}"
                )
                return pd.DataFrame()

            def iter_rows_json_ljson(iterator):
                buf = b""
                rows_read = 0
                bytes_read = 0
                t0 = time()
                next_t = t0 + report_every_sec
                for chunk in iterator:
                    if isinstance(chunk, (bytes, bytearray)):
                        bytes_read += len(chunk)
                        buf += chunk
                        parts = buf.split(b"\n")
                        buf = parts[-1]
                        lines = parts[:-1]
                    else:
                        s = str(chunk)
                        bytes_read += len(s.encode("utf-8", "ignore"))
                        parts = s.split("\n")
                        buf = parts[-1].encode("utf-8", "ignore")
                        lines = [p.encode("utf-8", "ignore") for p in parts[:-1]]

                    for bline in lines:
                        if not bline:
                            continue
                        line = bline.rstrip(b"\r").decode("utf-8", "ignore")
                        try:
                            obj = _json.loads(line)
                        except JSONDecodeError:
                            if "NaN" in line or "Infinity" in line or "Inf" in line:
                                preview = line[:180].replace("\n", "\\n")
                                print(
                                    "[YQL JSON ERROR] The result contains NaN/Infinity, so JSON cannot be returned.\n"
                                    "Rewrite the query to avoid division by zero and non-finite values.\n"
                                    f"Problematic row preview: {preview}"
                                )
                            else:
                                preview = line[:180].replace("\n", "\\n")
                                print(
                                    "[YQL JSON ERROR] Cannot parse a result row as JSON.\n"
                                    f"Problematic row preview: {preview}"
                                )
                            return

                        rows_read += 1
                        yield obj

                        if show_progress and (
                            rows_read % report_every_rows == 0 or time() >= next_t
                        ):
                            self._progress_printer(
                                rows_read=rows_read,
                                bytes_read=bytes_read,
                                total_rows=total_rows,
                                total_bytes=total_bytes,
                                t0=t0,
                            )
                            next_t = time() + report_every_sec

                tail = buf.rstrip(b"\r\n")
                if tail:
                    line = tail.decode("utf-8", "ignore")
                    try:
                        yield _json.loads(line)
                    except JSONDecodeError:
                        preview = line[:180].replace("\n", "\\n")
                        print(
                            "[YQL JSON ERROR] The result tail is truncated or invalid; no complete JSON object was found.\n"
                            f"Problematic tail preview: {preview}"
                        )
                        return

            def read_chunks(iterator, size):
                while True:
                    chunk = list(_it.islice(iterator, size))
                    if not chunk:
                        break
                    yield pd.DataFrame.from_records(chunk)

            chunks = list(read_chunks(iter_rows_json_ljson(it), chunksize))
            return pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()

        except Exception as e:
            print(f"[YQL ERROR] Failed to execute or read result: {e}")
            return pd.DataFrame()

    def yql_into_table(
        self, query: str, out_table: str, overwrite: bool = True, expiration: str = "7d",
        access_control_objects: Optional[List[str]] = None,
    ) -> str:
        """
        Run a YQL query and write its result directly into the target YTsaurus table.

        :param access_control_objects: Access control objects for the YTsaurus query.
        """
        if overwrite and self.client.exists(out_table):
            try:
                self.client.remove(out_table, force=True)
            except Exception:
                pass

        insert_query = self._prepare_yql_insert_wrapped(
            raw_query=query,
            out_table=out_table,
            expiration=expiration,
            overwrite=overwrite,
        )

        self.execute_internal(insert_query, lambda _: None, query_engine="yql",
                              access_control_objects=access_control_objects)
        return out_table
    

# Backward-compatible alias for legacy usage.
DOYTHook = YTsaurusHook
