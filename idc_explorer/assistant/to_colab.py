"""Turn one assistant answer into a Colab notebook that reruns the same query."""

from __future__ import annotations

import json
from pathlib import Path


def _md(source: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": _lines(source)}


def _code(source: str) -> dict:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": _lines(source),
    }


def _lines(source: str) -> list[str]:
    if not source.endswith("\n"):
        source += "\n"
    lines = source.splitlines(keepends=True)
    return lines or ["\n"]


def build_notebook(answer: dict) -> dict:
    """`answer` is the dict returned by the hosted assistant."""
    question = answer.get("question", "")
    sql = answer.get("work", {}).get("idc_index_sql", "")
    python = answer.get("work", {}).get("python", "")
    bigquery = answer.get("work", {}).get("bigquery_sql")
    bigquery_note = answer.get("work", {}).get("bigquery_note", "")
    guard = answer.get("guardrail", {})
    manifest = answer.get("manifest")
    cells = [
        _md(
            "# IDC cohort\n\n"
            f"**Question.** {question}\n\n"
            "This notebook reruns the SQL from the assistant. "
            "It does not call a model.\n"
        ),
        _code("%pip install -q idc-index\n"),
        _md("## Query\n\nThe next cell is the Python the assistant would rerun.\n"),
        _code(python or "raise RuntimeError('No SQL was recorded for this answer.')\n"),
    ]
    if bigquery:
        cells.append(_md(f"## BigQuery\n\n{bigquery_note}\n"))
        cells.append(_md(f"```sql\n{bigquery.rstrip()}\n```\n"))
    else:
        cells.append(_md(f"## BigQuery\n\n{bigquery_note}\n"))
    cells.append(
        _code(
            "links = []\n"
            "if {'StudyInstanceUID', 'SeriesInstanceUID'} <= set(df.columns):\n"
            "    for _, row in df.head(5).iterrows():\n"
            "        study = row['StudyInstanceUID']\n"
            "        series = row['SeriesInstanceUID']\n"
            "        links.append(\n"
            "            'https://viewer.imaging.datacommons.cancer.gov/v3/viewer/'"
            "f'?StudyInstanceUIDs={study}&initialSeriesInstanceUID={series}'\n"
            "        )\n"
            "links\n"
        )
    )
    warn_mb = guard.get("warn_mb", 1024)
    cells.append(
        _md(
            "## Download\n\n"
            f"The assistant warns at {warn_mb:g} MB. "
            "Set `CONFIRM_LARGE = True` only if you intend to fetch a cohort that large. "
            "This cell writes a manifest and does not start a download on its own.\n"
        )
    )
    manifest_literal = json.dumps(manifest or "")
    cells.append(
        _code(
            "CONFIRM_LARGE = False\n"
            f"WARN_MB = {warn_mb}\n"
            "total_mb = float(df['series_size_MB'].sum()) if 'series_size_MB' in df.columns else 0.0\n"
            "print(f'Rows in this frame: {len(df)}; size: {total_mb:.1f} MB')\n"
            "if total_mb >= WARN_MB and not CONFIRM_LARGE:\n"
            "    print('Manifest withheld. Set CONFIRM_LARGE = True to write it.')\n"
            "    manifest = None\n"
            "else:\n"
            f"    manifest = {manifest_literal}\n"
            "    print(manifest or 'No manifest was attached to this answer.')\n"
        )
    )
    if sql.strip():
        cells.insert(2, _md(f"## SQL\n\n```sql\n{sql.rstrip()}\n```\n"))
    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "colab": {"name": "idc_cohort.ipynb", "provenance": []},
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        },
        "cells": cells,
    }


def write_notebook(answer: dict, path: str | Path) -> Path:
    target = Path(path)
    target.write_text(json.dumps(build_notebook(answer), indent=1), encoding="utf-8")
    return target
