"""Warn before a large download and attach licence names to a result."""

from __future__ import annotations

DEFAULT_WARN_MB = 1024.0

LICENCE_NOTE = (
    "The short name comes from license_short_name in the IDC index. "
    "Read that licence and the collection source DOI before you reuse the files."
)


def assess(rows: list[dict], warn_mb: float = DEFAULT_WARN_MB) -> dict:
    """Summarise size and licence for the rows the assistant is about to hand back.

    `rows` are the series the user would download, not a one-row count.
    A cohort count belongs in `cohort_size_mb`, passed separately via `assess_download`.
    """
    total = 0.0
    has_size = False
    licences: list[str] = []
    for row in rows:
        if row.get("series_size_MB") is not None:
            has_size = True
            total += float(row["series_size_MB"])
        name = row.get("license_short_name")
        if name and name not in licences:
            licences.append(name)
    return _package(total if has_size else None, licences, warn_mb)


def assess_download(
    total_size_mb: float | None,
    licences: list[str],
    warn_mb: float = DEFAULT_WARN_MB,
) -> dict:
    return _package(total_size_mb, licences, warn_mb)


def _package(total_size_mb: float | None, licences: list[str], warn_mb: float) -> dict:
    warn = total_size_mb is not None and total_size_mb >= warn_mb
    message = None
    if warn:
        message = (
            f"This download is about {total_size_mb:,.0f} MB, "
            f"above the {warn_mb:,.0f} MB warning line. "
            "The manifest stays hidden until you confirm."
        )
    return {
        "total_size_mb": None if total_size_mb is None else round(total_size_mb, 2),
        "warn_mb": warn_mb,
        "warn": warn,
        "message": message,
        "licences": [{"name": name, "note": LICENCE_NOTE} for name in licences],
    }


def allow_manifest(assessment: dict, confirm_large: bool) -> bool:
    return (not assessment["warn"]) or confirm_large
