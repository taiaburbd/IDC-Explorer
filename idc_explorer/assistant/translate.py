"""Turn a short English question into idc-index SQL.

The translator only interpolates values it has already mapped to a fixed token
(a modality code, a body-part code, M/F, or a snake_case collection id).
"""

from __future__ import annotations

import re

MODALITIES = {
    "ct": "CT",
    "mr": "MR",
    "mri": "MR",
    "magnetic": "MR",
    "pet": "PT",
    "pt": "PT",
    "cr": "CR",
    "dx": "DX",
    "xray": "DX",
    "x-ray": "DX",
    "seg": "SEG",
    "segmentation": "SEG",
    "segmentations": "SEG",
    "sm": "SM",
    "slide": "SM",
    "slides": "SM",
    "pathology": "SM",
    "rtstruct": "RTSTRUCT",
}

BODY_PARTS = {
    "chest": "CHEST",
    "lung": "CHEST",
    "lungs": "CHEST",
    "thorax": "CHEST",
    "head": "HEAD",
    "brain": "BRAIN",
    "abdomen": "ABDOMEN",
    "pelvis": "PELVIS",
    "breast": "BREAST",
}

SERIES_COLUMNS = """
    collection_id,
    PatientID,
    StudyInstanceUID,
    SeriesInstanceUID,
    Modality,
    BodyPartExamined,
    SeriesDescription,
    ROUND(series_size_MB, 2) AS series_size_MB,
    license_short_name,
    series_aws_url
""".strip()


def _collection_id(text: str) -> str | None:
    match = re.search(r"\b([a-z][a-z0-9]*_[a-z0-9_]+)\b", text)
    return match.group(1) if match else None


def _modality(text: str) -> str | None:
    for word, code in MODALITIES.items():
        if re.search(rf"\b{re.escape(word)}\b", text):
            return code
    return None


def _body_part(text: str) -> tuple[str | None, str | None]:
    for word, code in BODY_PARTS.items():
        if re.search(rf"\b{re.escape(word)}\b", text):
            note = None
            if word in {"lung", "lungs", "thorax"}:
                note = (
                    "Lung and thorax questions use BodyPartExamined = 'CHEST'. "
                    "That is the DICOM value on most of these series."
                )
            return code, note
    return None, None


def _sex(text: str) -> str | None:
    if re.search(r"\b(female|women|woman)\b", text):
        return "F"
    if re.search(r"\b(male|men|man)\b", text):
        return "M"
    return None


def plan_question(question: str) -> dict:
    text = " ".join(question.lower().replace("-", " ").split())
    text = text.replace("x ray", "xray")
    collection = _collection_id(text)
    modality = _modality(text)
    body, body_note = _body_part(text)
    sex = _sex(text)
    original = "analysis result" not in text and "derived" not in text
    wants_licence = "licen" in text
    wants_collections = bool(
        re.search(r"\b(which|list|what)\b", text) and "collection" in text and collection is None
    ) or ("cancer" in text and "collection" in text and collection is None)
    wants_count = text.startswith("how many") or text.startswith("count ")
    wants_sample = any(
        phrase in text
        for phrase in ("show", "smallest", "few", "download", "viewer", "open", "manifest")
    )

    notes = [note for note in (body_note,) if note]
    if original and not wants_collections and not wants_licence:
        notes.append("analysis_result_id IS NULL keeps original series and drops later analysis results.")

    where = []
    if collection:
        where.append(f"collection_id = '{collection}'")
    if modality:
        where.append(f"Modality = '{modality}'")
    if body:
        where.append(f"BodyPartExamined = '{body}'")
    if sex:
        where.append(f"PatientSex = '{sex}'")
    if original and not wants_collections:
        where.append("analysis_result_id IS NULL")

    if wants_collections:
        cancer = None
        for word in ("lung", "breast", "prostate", "colon", "liver", "kidney", "brain"):
            if re.search(rf"\b{word}\b", text):
                cancer = word
                break
        clause = ""
        if cancer:
            clause = (
                "WHERE lower(coalesce(cancer_types, '')) LIKE '%"
                + cancer
                + "%'\n   OR lower(coalesce(tumor_locations, '')) LIKE '%"
                + cancer
                + "%'\n"
            )
        sql = (
            "SELECT collection_id, collection_name, subjects, cancer_types, tumor_locations\n"
            "FROM collections_index\n"
            f"{clause}"
            "ORDER BY subjects DESC\n"
            "LIMIT 20"
        )
        return {
            "understood": True,
            "intent": "collections",
            "summary": "Collections from collections_index.",
            "sql": sql,
            "count_sql": None,
            "notes": notes,
        }

    if not (collection or modality or body or sex) and not wants_count:
        return {
            "understood": False,
            "intent": "unknown",
            "summary": "This question needs a collection, modality, body part, or sex.",
            "sql": None,
            "count_sql": None,
            "notes": [
                "Try: How many patients are in rider_pilot?",
                "Try: Show me a few chest CT series.",
            ],
        }

    where_sql = " AND\n  ".join(where) if where else "TRUE"
    if wants_licence:
        sql = (
            "SELECT license_short_name, COUNT(*) AS series,\n"
            "       COUNT(DISTINCT PatientID) AS patients,\n"
            "       ROUND(SUM(series_size_MB), 1) AS total_size_MB\n"
            "FROM index\n"
            f"WHERE {where_sql}\n"
            "GROUP BY license_short_name\n"
            "ORDER BY series DESC"
        )
        intent = "licence"
        summary = "Licence names on the matching series."
        count_sql = None
    elif wants_count and "patient" in text:
        sql = (
            "SELECT COUNT(DISTINCT PatientID) AS patients,\n"
            "       COUNT(DISTINCT StudyInstanceUID) AS studies,\n"
            "       COUNT(*) AS series,\n"
            "       ROUND(SUM(series_size_MB), 1) AS total_size_MB\n"
            "FROM index\n"
            f"WHERE {where_sql}"
        )
        intent = "count"
        summary = "Patient, study, and series counts for the cohort."
        count_sql = None
    elif wants_count:
        sql = (
            "SELECT COUNT(*) AS series,\n"
            "       COUNT(DISTINCT PatientID) AS patients,\n"
            "       COUNT(DISTINCT StudyInstanceUID) AS studies,\n"
            "       ROUND(SUM(series_size_MB), 1) AS total_size_MB\n"
            "FROM index\n"
            f"WHERE {where_sql}"
        )
        intent = "count"
        summary = "Series count for the cohort."
        count_sql = None
    else:
        limit = 3 if "smallest" in text or "few" in text else 5
        sql = (
            f"SELECT\n    {SERIES_COLUMNS}\n"
            "FROM index\n"
            f"WHERE {where_sql}\n"
            "  AND series_size_MB > 0\n"
            "ORDER BY series_size_MB ASC, SeriesInstanceUID\n"
            f"LIMIT {limit}"
        )
        count_sql = (
            "SELECT COUNT(*) AS series,\n"
            "       COUNT(DISTINCT PatientID) AS patients,\n"
            "       COUNT(DISTINCT StudyInstanceUID) AS studies,\n"
            "       ROUND(SUM(series_size_MB), 1) AS total_size_MB\n"
            "FROM index\n"
            f"WHERE {where_sql}"
        )
        intent = "sample"
        summary = f"Smallest {limit} matching series, plus the full cohort size."
        if not wants_sample and not modality and not body:
            summary = f"Smallest {limit} series in the cohort, plus the full cohort size."

    return {
        "understood": True,
        "intent": intent,
        "summary": summary,
        "sql": sql,
        "count_sql": count_sql,
        "notes": notes,
    }
