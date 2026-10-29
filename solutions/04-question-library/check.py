"""Run every question in idc_explorer/assistant/questions.jsonl and compare with the recorded answers.

    python check.py           # check: fails if any answer changed
    python check.py --write   # accept the current answers (new IDC release) and rebuild QUESTIONS.md
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
# The questions live with the assistant, which suggests them in the IDC Explorer chat.
QUESTIONS = HERE.parents[1] / "idc_explorer" / "assistant" / "questions.jsonl"
ANSWERS = HERE / "answers.jsonl"
LIBRARY = HERE / "QUESTIONS.md"

TOPICS = {
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


def load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def plain(value):
    """Turn numpy / pandas values into JSON values."""
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [plain(v) for v in value]
    if isinstance(value, float) and math.isnan(value):
        return None
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            return plain(value.item())
        except Exception:
            return str(value)
    return value


def run(connection, item: dict) -> dict:
    """The answer: row count and the first five rows. `check` says what must hold."""
    try:
        frame = connection.query(item["sql"]).to_df().head(5)
    except Exception as exc:
        return {"error": str(exc)}
    rows = plain(frame.where(frame.notna(), None).to_dict(orient="records"))
    check = item["check"]
    if check["op"] == "row_count":
        ok = len(connection.query(item["sql"]).to_df()) == check["n"]
    elif check["op"] == "min_rows":
        ok = len(connection.query(item["sql"]).to_df()) >= check["n"]
    elif check["op"] == "columns":
        ok = bool(rows) and all(name in rows[0] for name in check["names"])
    elif check["op"] == "scalar_equals":
        ok = bool(rows) and rows[0].get(check["column"]) == check["value"]
    else:  # "scalar": one row with a value
        ok = len(rows) == 1 and rows[0].get(check["column"]) is not None
    return {"ok": ok, "rows": rows}


def short(answer: dict) -> str:
    if "error" in answer:
        return f"⚠️ {answer['error']}"
    rows = answer["rows"]
    if not rows:
        return "No rows."
    if len(rows) == 1 and len(rows[0]) <= 4:
        return ", ".join(f"**{k}** = {v}" for k, v in rows[0].items())
    cols = list(rows[0])[:5]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for row in rows[:3]:
        lines.append("| " + " | ".join(str(row.get(c))[:40] for c in cols) + " |")
    return "\n".join(lines)


def write_library(questions: list[dict], answers: dict) -> None:
    out = ["# IDC question library",
           "",
           f"{len(questions)} questions people ask about the Imaging Data Commons, with the answer "
           "from the current data release and the SQL behind it.",
           "",
           "**To use one:** copy its SQL into the **🧪 SQL playground** of IDC Explorer (or the "
           "notebook), run it, and change the values to fit your question.",
           ""]
    order = [t for t in TOPICS if any(q["group"] == t for q in questions)]
    out += [f"- [{TOPICS[t]}](#{TOPICS[t].lower().replace(' ', '-').replace(',', '').replace(chr(39), '')})"
            for t in order]
    for topic in order:
        out += ["", f"## {TOPICS[topic]}", ""]
        for q in (q for q in questions if q["group"] == topic):
            out += [f"### {q['question']}", "", short(answers.get(q["id"], {"rows": []})), "",
                    "```sql", q["sql"], "```", ""]
    LIBRARY.write_text("\n".join(out), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="accept the current answers")
    args = parser.parse_args()

    import duckdb
    import idc_index_data

    data_dir = Path(idc_index_data.IDC_INDEX_PARQUET_FILEPATH).parent
    connection = duckdb.connect()
    for table, filename in (("index", "idc_index.parquet"),
                            ("collections_index", "collections_index.parquet"),
                            ("analysis_results_index", "analysis_results_index.parquet")):
        connection.execute(f"CREATE VIEW {table} AS SELECT * FROM read_parquet('{(data_dir / filename).as_posix()}')")

    questions = load(QUESTIONS)
    recorded = {a["id"]: a["answer"] for a in load(ANSWERS)}
    answers, failed = {}, 0
    for q in questions:
        answer = answers[q["id"]] = run(connection, q)
        changed = not args.write and q["id"] in recorded and recorded[q["id"]] != answer
        if not answer.get("ok") or changed:
            failed += 1
            print(f"FAIL {q['id']} {q['question']}")
            if changed:
                print(f"     was {recorded[q['id']]['rows'][:1]}\n     now {answer.get('rows', answer)[:1]}")
        else:
            print(f"ok   {q['id']} {q['question']}")

    if args.write:
        ANSWERS.write_text("".join(json.dumps({"id": q["id"], "answer": answers[q["id"]]}) + "\n"
                                   for q in questions), encoding="utf-8")
        write_library(questions, answers)
        print(f"wrote {ANSWERS.name} and {LIBRARY.name}")
    if failed:
        raise SystemExit(f"{failed} of {len(questions)} questions failed")
    print(f"{len(questions)} questions passed")


if __name__ == "__main__":
    main()
