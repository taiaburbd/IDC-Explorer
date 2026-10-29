# Question library

64 questions people often ask about the Imaging Data Commons, each with a **checked SQL query**
and its answer.

| File | For |
|---|---|
| [`QUESTIONS.md`](QUESTIONS.md) | **Read this.** Questions grouped by topic, each with its answer and its SQL. Copy any SQL into the 🧪 SQL playground. |
| `../../idc_explorer/assistant/questions.jsonl` | The questions and SQL themselves. IDC Explorer suggests them in its chat (**💡 suggested questions**). |
| `answers.jsonl` | The answers recorded for the current data release. |
| `check.py` | Re-runs every question and fails if an answer changed. |

```bash
cd solutions/04-question-library
../../.venv/bin/python check.py           # after updating idc-index or editing a question
../../.venv/bin/python check.py --write   # accept a new IDC data release; rebuilds QUESTIONS.md
```

**To add a question:** add one line to `idc_explorer/assistant/questions.jsonl` with
`id`, `group` (the topic), `question`, `sql` and `check`, then run `check.py --write`.
`check` is one of these:
- `{"op": "scalar", "column": "patients"}` (one row with a value)
- `{"op": "columns", "names": [...]}`
- `{"op": "row_count", "n": 3}`
- `{"op": "min_rows", "n": 1}`
- `{"op": "scalar_equals", "column": "...", "value": ...}`
