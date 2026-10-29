"""Local memory and the prompt sent to the IDC assistant tools."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

MEMORY_PATH = Path.home() / ".idc_explorer" / "memory.json"
MAX_MEMORY = 40

MODALITY_WORDS = {
    "CT": "CT",
    "MR": "MRI",
    "PT": "PET",
    "MG": "mammography",
    "CR": "xray",
    "DX": "xray",
    "US": "ultrasound",
    "SM": "pathology slides",
    "SEG": "segmentation",
    "RTSTRUCT": "rtstruct",
}


LIBRARY_PATH = Path(__file__).resolve().parent / "assistant" / "questions.jsonl"
LIBRARY_TOPICS = {
    "cohort": "Patients, studies and scans",
    "modality": "Imaging types",
    "body": "Body parts",
    "download": "Download size",
    "licence": "Licences",
    "demographics": "Patients' sex",
    "equipment": "Scanners",
    "viewer": "Open in the viewer",
    "collections": "Datasets",
    "analysis": "Analysis results",
    "version": "IDC releases",
    "sop": "File types",
    "gotcha": "Common mistakes",
}


def load_library() -> list[dict]:
    """Checked questions (question + SQL) suggested in the chat. See solutions/04-question-library."""
    if not LIBRARY_PATH.exists():
        return []
    items = []
    for line in LIBRARY_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            item = json.loads(line)
            item["topic"] = LIBRARY_TOPICS.get(item.get("group"), "Other")
            items.append(item)
    return items


def match_library(library: list[dict], question: str) -> dict | None:
    """A typed question that is word-for-word a library question uses its checked SQL."""
    needle = " ".join(question.lower().rstrip("?. ").split())
    for item in library:
        if " ".join(item["question"].lower().rstrip("?. ").split()) == needle:
            return item
    return None


def format_library_answer(item: dict, result: dict) -> str:
    rows = result.get("rows") or []
    parts = ["Answered with a checked query from the question library, on the whole catalogue "
             "(your filters are not applied)."]
    if not rows:
        parts.append("No rows.")
    elif len(rows) == 1 and len(rows[0]) <= 4:
        parts.append(", ".join(f"**{key}** = {value}" for key, value in rows[0].items()))
    else:
        cols = list(rows[0])
        lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
        for row in rows[:15]:
            lines.append("| " + " | ".join(str(row.get(c)).replace("|", "/")[:60] for c in cols) + " |")
        if len(rows) > 15 or result.get("truncated"):
            lines.append(f"\n*Showing 15 of {len(rows)}{'+' if result.get('truncated') else ''} rows. "
                         "Run the SQL in the 🧪 SQL playground to see them all.*")
        parts.append("\n".join(lines))
    parts.append("SQL used:\n\n```sql\n" + item["sql"].strip() + "\n```")
    return "\n\n".join(parts)


def load_memory() -> list[dict]:
    if not MEMORY_PATH.exists():
        return []
    try:
        data = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict) and item.get("question")]


def save_memory(question: str, prompt: str, answer: str) -> list[dict]:
    items = [item for item in load_memory() if item.get("question") != question]
    items.insert(0, {
        "question": question,
        "prompt": prompt,
        "answer": answer,
        "at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    })
    items = items[:MAX_MEMORY]
    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    MEMORY_PATH.write_text(json.dumps(items, indent=2), encoding="utf-8")
    return items


def search_memory(items: list[dict], typed: str, limit: int = 6) -> list[dict]:
    needle = " ".join(typed.lower().split())
    if not needle:
        return items[:limit]
    hits = []
    for item in items:
        hay = f"{item.get('question', '')} {item.get('answer', '')}".lower()
        if needle in hay or all(word in hay for word in needle.split()):
            hits.append(item)
        if len(hits) >= limit:
            break
    return hits


def selection_lines(recipe, summary: dict, human_size) -> list[str]:
    lines = ["Selection on screen"]
    if recipe.cancer_types:
        lines.append("Cancer type: " + ", ".join(recipe.cancer_types))
    if recipe.tumor_locations:
        lines.append("Organ / tumour location: " + ", ".join(recipe.tumor_locations))
    if recipe.collections:
        lines.append("Collections: " + ", ".join(recipe.collections))
    if recipe.modalities:
        lines.append("Imaging type: " + ", ".join(
            f"{MODALITY_WORDS.get(m, m)} ({m})" for m in recipe.modalities))
    if recipe.body_parts:
        lines.append("Body part: " + ", ".join(recipe.body_parts))
    if recipe.manufacturers:
        lines.append("Manufacturer: " + ", ".join(recipe.manufacturers))
    if recipe.sexes:
        lines.append("Sex: " + ", ".join(recipe.sexes))
    if recipe.age_min is not None or recipe.age_max is not None:
        lines.append(f"Age: {recipe.age_min or 0}–{recipe.age_max or 100} years")
    if recipe.commercial_ok_only:
        lines.append("Rights: commercial use allowed only")
    if recipe.with_segmentation_only:
        lines.append("Only scans that have organ or tumour outlines")
    if recipe.uses_ct():
        bits = []
        if recipe.ct_slice_min is not None or recipe.ct_slice_max is not None:
            bits.append(f"slice {recipe.ct_slice_min}–{recipe.ct_slice_max} mm")
        if recipe.ct_kvp:
            bits.append("kV " + ", ".join(str(v) for v in recipe.ct_kvp))
        if recipe.ct_kernels:
            bits.append("kernel " + ", ".join(recipe.ct_kernels))
        if bits:
            lines.append("CT settings: " + "; ".join(bits))
    if recipe.uses_mr():
        bits = []
        if recipe.mr_field_t:
            bits.append("field " + ", ".join(f"{v:g} T" for v in recipe.mr_field_t))
        if recipe.mr_acq_type:
            bits.append("acquisition " + ", ".join(recipe.mr_acq_type))
        if recipe.mr_slice_min is not None or recipe.mr_slice_max is not None:
            bits.append(f"slice {recipe.mr_slice_min}–{recipe.mr_slice_max} mm")
        if bits:
            lines.append("MRI settings: " + "; ".join(bits))
    if recipe.pt_tracers:
        lines.append("PET tracer: " + ", ".join(recipe.pt_tracers))
    lines.append(
        f"Matched {summary['patients']:,} patients, {summary['series']:,} scans, "
        f"{summary['collections']:,} datasets, {human_size(summary['size_GB'])}."
    )
    return lines


def wants_download(question: str) -> bool:
    """Only a question that mentions downloading gets the download plan (and the button)."""
    return bool(re.search(r"\b(download|downloads|downloading|downloaded)\b", question, re.I))


def download_lines(download: dict, human_size) -> list[str]:
    lines = [
        f"Download plan: {download['what']} · {download['scans']:,} scans · "
        f"{human_size(download['size_gb'])}."
    ]
    # A real path such as IDC_downloads looks like a collection id to the
    # assistant (snake_case). Say where the files go without that token.
    lines.append("Save to: the folder chosen on the Download tab")
    lines.append(f"Folder layout: {download['layout']}")
    lines.append(f"Download server: {download['source']}")
    return lines


def full_prompt(question: str, lines: list[str]) -> str:
    question = question.strip() or "How many patients and series are in this selection, and what licence applies?"
    return question + "\n\n" + "\n".join(lines)


def mcp_tools(query):
    """The MCP tools module, with its database calls pointed at the explorer's catalogue."""
    import sys

    root = Path(__file__).resolve().parent / "assistant"
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    import tools

    def query_index(sql: str) -> list[dict]:
        frame = query(sql)
        frame = frame.where(frame.notna(), None)
        return frame.to_dict(orient="records")

    tools.query_index = query_index
    return tools


def ask_mcp(question: str, query) -> dict:
    """Run the same `ask` tool the MCP server exposes, on the explorer's catalogue."""
    return mcp_tools(query).call_tool("ask", {"question": question, "confirm_large": False})


def sql_mcp(sql: str, query, max_rows: int = 5000) -> dict:
    """Run the MCP `query_index` tool (read-only SQL) on the explorer's catalogue."""
    return mcp_tools(query).call_tool("query_index", {"sql": sql, "max_rows": max_rows})


def format_answer(local: str, answer: dict) -> str:
    parts = [local]
    if not answer.get("understood"):
        parts.append(answer.get("summary") or "The assistant could not turn that into a catalogue query.")
        for note in answer.get("notes") or []:
            parts.append(f"- {note}")
        parts.append("The numbers above are still the selection on screen.")
        return "\n\n".join(part for part in parts if part)

    parts.append(answer.get("summary") or "Catalogue answer")
    rows = answer.get("rows") or []
    intent = answer.get("intent")
    if intent == "count" and rows:
        row = rows[0]
        parts.append("Count: " + ", ".join(f"{key} = {row[key]}" for key in row))
    elif intent == "licence" and rows:
        lines = ["Licences:"]
        for row in rows[:8]:
            lines.append(
                f"- {row.get('license_short_name')}: {row.get('series')} scans, "
                f"{row.get('patients')} patients, {row.get('total_size_MB')} MB"
            )
        parts.append("\n".join(lines))
    elif intent == "collections" and rows:
        lines = ["Datasets:"]
        for row in rows[:8]:
            lines.append(f"- {row.get('collection_id')}: {row.get('subjects')} subjects")
        parts.append("\n".join(lines))
    elif rows:
        lines = ["Sample series:"]
        for row in rows[:5]:
            lines.append(
                f"- {row.get('collection_id')} · {row.get('Modality')} · "
                f"{row.get('series_size_MB')} MB · {row.get('license_short_name')}"
            )
        parts.append("\n".join(lines))
    cohort = answer.get("cohort")
    if cohort:
        parts.append(
            f"Full cohort behind that sample: {cohort.get('patients')} patients, "
            f"{cohort.get('series')} scans, {cohort.get('total_size_MB')} MB."
        )
    for note in answer.get("notes") or []:
        parts.append(f"- {note}")
    guard = answer.get("guardrail") or {}
    if guard.get("message"):
        parts.append(guard["message"])
    names = [item.get("name") for item in guard.get("licences") or [] if item.get("name")]
    if names:
        parts.append("Licence names: " + ", ".join(names) + ".")
    links = answer.get("viewer_links") or []
    if links:
        lines = ["Open in the viewer:"]
        for link in links[:3]:
            lines.append(f"- {link.get('collection_id')}: {link.get('url')}")
        parts.append("\n".join(lines))
    work = answer.get("work") or {}
    sql = work.get("idc_index_sql") if isinstance(work, dict) else None
    if sql:
        parts.append("SQL used:\n\n```sql\n" + sql.strip() + "\n```")
    return "\n\n".join(part for part in parts if part)
