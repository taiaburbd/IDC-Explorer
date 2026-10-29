"""Render the SQL an assistant actually ran so a person can rerun it without the assistant."""

from __future__ import annotations

# Columns that exist on the idc-index `index` table and are not a straight copy
# of bigquery-public-data.idc_current.dicom_pivot.
INDEX_ONLY_COLUMNS = {
    "analysis_result_id",
    "license_short_name",
    "series_size_MB",
    "series_aws_url",
    "aws_bucket",
    "crdc_series_uuid",
    "sop_class_name",
    "transfer_syntax_name",
    "series_init_idc_version",
    "series_revised_idc_version",
    "source_DOI",
}

BIGQUERY_TABLE = "`bigquery-public-data.idc_current.dicom_pivot`"


def python_source(sql: str) -> str:
    body = sql.strip()
    return (
        "from idc_index import IDCClient\n\n"
        "client = IDCClient.client()\n"
        f'df = client.sql_query("""\n{body}\n""")\n'
        "df\n"
    )


def bigquery_sql(sql: str) -> str | None:
    """Return a BigQuery version when the statement only uses shared DICOM columns."""
    used = {name for name in INDEX_ONLY_COLUMNS if name in sql}
    if used or "collections_index" in sql or "analysis_results_index" in sql:
        return None
    if "FROM index" not in sql and "from index" not in sql:
        return None
    rewritten = sql.replace("FROM index", f"FROM {BIGQUERY_TABLE}")
    rewritten = rewritten.replace("from index", f"FROM {BIGQUERY_TABLE}")
    return rewritten.strip() + "\n"


def render(sql: str) -> dict:
    bq = bigquery_sql(sql)
    used = sorted(name for name in INDEX_ONLY_COLUMNS if name in sql)
    if bq is None:
        bq_note = (
            "This statement stays in idc-index. "
            + (
                "It uses index columns that are not on dicom_pivot: " + ", ".join(used) + "."
                if used
                else "It reads a table other than the series index."
            )
        )
    else:
        bq_note = f"Same statement against {BIGQUERY_TABLE}."
    return {
        "idc_index_sql": sql.strip() + "\n",
        "python": python_source(sql),
        "bigquery_sql": bq,
        "bigquery_note": bq_note,
    }
