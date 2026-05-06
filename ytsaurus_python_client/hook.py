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
        *args,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.yt_proxy = yt_proxy or YT_DEFAULT_PROXY
        self.yt_token = yt_token
        self.yt_query_result_temp_dir = yt_query_result_temp_dir
        self.yt_cluster_name = yt_cluster_name or (self.yt_proxy.split(".")[0] if self.yt_proxy else "")
        self.yt_ui_base_url = yt_ui_base_url if yt_ui_base_url is not None else YT_UI_BASE_URL
        self.query_engine = query_engine
        self.query_duration_timeout = query_duration_timeout
        self.query_output_table = query_output_table
        self.query_pragma_config = query_pragma_config or {}
        self.client_config = client_config or {}
        self.client = self.get_client()

    # ===== helpers =====

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
    ) -> Any:
        query_engine = query_engine or self.query_engine
        print(f"Executing query via {query_engine.upper()}")
        query_id = self.client.start_query(query_engine, query)
        print(
            f"Started query id={query_id} -> {self._query_url(query_id)}"
        )

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
    ) -> Union[pd.DataFrame, str]:
        """
        Run a YQL query and return the result as a pandas DataFrame.
        """

        def get_output(query_id: str) -> Any:
            import json as _json

            print(f"-> Query ID: {query_id}")
            print(f"-> URL: {self._query_url(query_id)}")

            it = self.client.read_query_result(query_id, format="json", raw=True)

            buf = b""
            rows = []
            for chunk in it:
                if isinstance(chunk, (bytes, bytearray)):
                    buf += chunk
                else:
                    buf += str(chunk).encode("utf-8", "ignore")

            for bline in buf.split(b"\n"):
                if not bline:
                    continue
                line = bline.rstrip(b"\r").decode("utf-8", "ignore")
                rows.append(_json.loads(line))

            return pd.DataFrame.from_records(rows)

        query_str = self._prepare_query(query) if self.query_engine == "yql" else query

        return self.execute_internal(
            query_str,
            get_output,
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


# Backward-compatible alias for legacy usage.
DOYTHook = YTsaurusHook
