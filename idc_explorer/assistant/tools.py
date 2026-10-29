"""Operations shared by the portal page and the MCP-style tool calls."""

from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

VIEWER = (
    "https://viewer.imaging.datacommons.cancer.gov/v3/viewer/"
    "?StudyInstanceUIDs={study}&initialSeriesInstanceUID={series}"
)

import guardrails  # noqa: E402
import show_work  # noqa: E402
import to_colab  # noqa: E402
from translate import plan_question  # noqa: E402


def _client():
    from idc_index import IDCClient

    if not hasattr(_client, "instance"):
        _client.instance = IDCClient.client()
    return _client.instance


def query_index(sql: str) -> list[dict]:
    client = _client()
    for name in client.indices_overview:
        if getattr(client, name, None) is None and re.search(rf"\b{name}\b", sql):
            client.fetch_index(name)
    frame = client.sql_query(sql)
    frame = frame.where(frame.notna(), None)
    return frame.to_dict(orient="records")


def viewer_links(rows: list[dict], limit: int = 5) -> list[dict]:
    links = []
    seen = set()
    for row in rows:
        study = row.get("StudyInstanceUID")
        series = row.get("SeriesInstanceUID")
        if not study or not series or study in seen:
            continue
        seen.add(study)
        links.append(
            {
                "collection_id": row.get("collection_id"),
                "PatientID": row.get("PatientID"),
                "StudyInstanceUID": study,
                "SeriesInstanceUID": series,
                "url": VIEWER.format(study=study, series=series),
            }
        )
        if len(links) >= limit:
            break
    return links


def manifest_text(rows: list[dict]) -> str:
    lines = ["# idc-index s5cmd manifest", "# generated for the series listed in this answer"]
    for row in rows:
        url = row.get("series_aws_url")
        if not url:
            continue
        source = url.rstrip("/")
        if not source.endswith("*"):
            source += "/*"
        folder = "/".join(
            str(row.get(key) or "unknown")
            for key in ("collection_id", "PatientID", "Modality", "SeriesInstanceUID")
        )
        lines.append(f"cp '{source}' '{folder}/'")
    return "\n".join(lines) + "\n"


def ask(question: str, confirm_large: bool = False) -> dict:
    plan = plan_question(question)
    if not plan["understood"]:
        return {
            "question": question,
            "understood": False,
            "summary": plan["summary"],
            "notes": plan["notes"],
            "rows": [],
            "cohort": None,
            "viewer_links": [],
            "manifest": None,
            "work": None,
            "guardrail": None,
        }

    rows = query_index(plan["sql"])
    cohort = None
    if plan["count_sql"]:
        counted = query_index(plan["count_sql"])
        cohort = counted[0] if counted else None

    licences = []
    for row in rows:
        name = row.get("license_short_name")
        if name and name not in licences:
            licences.append(name)
    sample_mb = None
    if any(row.get("series_size_MB") is not None for row in rows):
        sample_mb = sum(float(row["series_size_MB"]) for row in rows if row.get("series_size_MB") is not None)
    cohort_mb = None
    if cohort and cohort.get("total_size_MB") is not None:
        cohort_mb = float(cohort["total_size_MB"])
    guard = guardrails.assess_download(sample_mb if sample_mb is not None else cohort_mb, licences)
    if (
        cohort_mb is not None
        and sample_mb is not None
        and cohort_mb >= guardrails.DEFAULT_WARN_MB
        and cohort_mb > sample_mb
    ):
        plan["notes"].append(
            f"The full cohort is about {cohort_mb:,.0f} MB. "
            "The manifest is only the small sample in the table, not the whole cohort."
        )
    manifest = None
    if any(row.get("series_aws_url") for row in rows) and guardrails.allow_manifest(guard, confirm_large):
        manifest = manifest_text(rows)

    answer = {
        "question": question,
        "understood": True,
        "summary": plan["summary"],
        "notes": plan["notes"],
        "intent": plan["intent"],
        "rows": rows,
        "cohort": cohort,
        "viewer_links": viewer_links(rows),
        "manifest": manifest,
        "work": show_work.render(plan["sql"]),
        "guardrail": guard,
    }
    return answer


def notebook_bytes(answer: dict) -> bytes:
    import json

    return json.dumps(to_colab.build_notebook(answer), indent=1).encode("utf-8")


TOOLS = [
    {
        "name": "ask",
        "description": "Answer a plain-English IDC question with a cohort, viewer links, SQL, and a manifest.",
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "confirm_large": {"type": "boolean"},
            },
            "required": ["question"],
        },
    },
    {
        "name": "query_index",
        "description": "Run one read-only idc-index SQL query (SELECT or WITH) and return up to max_rows rows.",
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string"},
                "max_rows": {"type": "integer"},
            },
            "required": ["sql"],
        },
    },
]


MAX_ROWS = 5000


def read_only_sql(sql: str) -> str:
    """One SELECT/WITH query, without a trailing semicolon. Anything else is refused."""
    sql = sql.strip().rstrip(";").strip()
    if not re.match(r"(?is)^(select|with)\b", sql):
        raise ValueError("Only SELECT (or WITH … SELECT) queries are allowed.")
    if ";" in sql:
        raise ValueError("Run one query at a time (no ';' inside the query).")
    return sql


def call_tool(name: str, arguments: dict) -> dict:
    if name == "ask":
        return ask(arguments["question"], bool(arguments.get("confirm_large", False)))
    if name == "query_index":
        sql = read_only_sql(arguments["sql"])
        max_rows = max(1, min(int(arguments.get("max_rows") or MAX_ROWS), MAX_ROWS))
        # Wrapping makes DuckDB reject anything that is not a single query, and caps the rows.
        rows = query_index(f"SELECT * FROM (\n{sql}\n) AS q LIMIT {max_rows + 1}")
        return {
            "rows": rows[:max_rows],
            "truncated": len(rows) > max_rows,
            "work": show_work.render(sql),
        }
    raise KeyError(name)
