"""
Where a catalogue query runs.

local  — DuckDB already loaded by IDC Explorer
api    — POST https://api.imaging.datacommons.cancer.gov/v3/sql
mcp    — POST https://api.imaging.datacommons.cancer.gov/mcp  tool run_sql

Downloads, the viewer, and citation lookups do not use this switch.
"""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd

API_SQL_URL = "https://api.imaging.datacommons.cancer.gov/v3/sql"
API_VERSION_URL = "https://api.imaging.datacommons.cancer.gov/v3/version"
MCP_URL = "https://api.imaging.datacommons.cancer.gov/mcp"
REMOTE_MAX_ROWS = 10_000
TIMEOUT_S = 90

LABELS = {
    "local": "Local catalogue (this computer)",
    "api": "Remote IDC API",
    "mcp": "Remote IDC MCP",
}


class QueryError(RuntimeError):
    """The chosen source refused the query or could not be reached."""


def label(source: str) -> str:
    return LABELS.get(source, LABELS["local"])


def remote_version() -> str:
    """IDC data release the public API is serving, for example 'v24'."""
    cached = _VERSION.get("label")
    if cached:
        return cached
    payload = _get_json(API_VERSION_URL)
    version = payload.get("idc_version") or "unknown"
    index = payload.get("idc_index_data_version")
    label = f"{version} (index {index})" if index else str(version)
    _VERSION["label"] = label
    return label


def remote_sql(sql: str, source: str, max_rows: int = REMOTE_MAX_ROWS) -> pd.DataFrame:
    """Run one read-only SQL statement on the public IDC API or MCP server."""
    if source not in ("api", "mcp"):
        raise QueryError(f"Unknown remote source: {source}")
    max_rows = max(1, min(int(max_rows), REMOTE_MAX_ROWS))
    key = (source, sql, max_rows)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached.copy()
    payload = _call_api(sql, max_rows) if source == "api" else _call_mcp(sql, max_rows)
    if payload.get("truncated"):
        raise QueryError(
            "The remote catalogue returned only the first "
            f"{int(payload.get('max_rows') or max_rows):,} rows. "
            "Switch to Local for this selection, or narrow the filters."
        )
    rows = payload.get("rows") or []
    columns = payload.get("columns") or (list(rows[0]) if rows else [])
    frame = pd.DataFrame(rows, columns=columns)
    if len(_CACHE) >= 48:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[key] = frame
    return frame.copy()


_CACHE: dict[tuple, pd.DataFrame] = {}
_VERSION: dict[str, str] = {}


def _call_api(sql: str, max_rows: int) -> dict:
    body = _post_json(API_SQL_URL, {"sql": sql, "max_rows": max_rows})
    if "error" in body and "rows" not in body:
        raise QueryError(_error_text(body))
    return body


def _call_mcp(sql: str, max_rows: int) -> dict:
    body = _post_json(
        MCP_URL,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "run_sql", "arguments": {"sql": sql, "max_rows": max_rows}},
        },
        accept="application/json, text/event-stream",
    )
    if body.get("error"):
        raise QueryError(_error_text(body["error"]))
    result = body.get("result") or {}
    if result.get("isError"):
        raise QueryError(_mcp_text(result) or "The IDC MCP server rejected the query.")
    text = _mcp_text(result)
    try:
        payload = json.loads(text) if text else {}
    except json.JSONDecodeError as exc:
        raise QueryError(f"The IDC MCP server returned an unexpected answer: {text[:300]}") from exc
    if isinstance(payload, dict) and payload.get("error") and "rows" not in payload:
        raise QueryError(_error_text(payload))
    return payload if isinstance(payload, dict) else {}


def _mcp_text(result: dict) -> str:
    parts = []
    for block in result.get("content") or []:
        if isinstance(block, dict) and block.get("text"):
            parts.append(block["text"])
    return "\n".join(parts).strip()


def _error_text(body) -> str:
    if isinstance(body, dict):
        err = body.get("error", body)
        if isinstance(err, dict):
            return str(err.get("message") or err.get("code") or err)
        return str(err)
    return str(body)


def _get_json(url: str) -> dict:
    request = Request(url, headers={"accept": "application/json", "user-agent": "idc-explorer"})
    try:
        with urlopen(request, timeout=TIMEOUT_S) as response:
            payload = json.loads(response.read().decode())
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise QueryError(f"Could not reach {url}: {exc}") from exc
    return payload if isinstance(payload, dict) else {}


def _post_json(url: str, payload: dict, accept: str = "application/json") -> dict:
    data = json.dumps(payload).encode()
    request = Request(
        url,
        data=data,
        headers={
            "content-type": "application/json",
            "accept": accept,
            "user-agent": "idc-explorer",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=TIMEOUT_S) as response:
            raw = response.read().decode()
    except HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        try:
            message = _error_text(json.loads(detail))
        except json.JSONDecodeError:
            message = detail.strip() or str(exc)
        raise QueryError(message) from exc
    except (URLError, TimeoutError) as exc:
        raise QueryError(f"Could not reach {url}: {exc}") from exc
    return _parse_body(raw)


def _parse_body(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("{"):
        return json.loads(raw)
    for line in raw.splitlines():
        if line.startswith("data:"):
            return json.loads(line[5:].strip())
    raise QueryError("The remote service returned a response IDC Explorer could not read.")
