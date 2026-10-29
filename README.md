# IDC Explorer

A point-and-click app for the NCI **Imaging Data Commons**: find public cancer imaging
(CT, MRI, PET, mammography, pathology, and more), preview it in the browser, check the
licence, ask a question, or download DICOM files. No account.

The catalogue is the local `idc-index` metadata (IDC release shown in the app header,
about 100 TB and 86,000 patients in release v25). Image files stay on public Amazon S3
and Google Cloud Storage until you download them.

---

## Start

From the repository root, with the project virtualenv (Python 3.12):

```bash
cd idc_explorer
../.venv/bin/python -m streamlit run app.py
```

The app opens at http://127.0.0.1:8501. Leave that terminal open. The first start
loads the catalogue into memory (about a minute). Later starts reuse the files already
cached by `idc-index`.

Needs about 8 GB of RAM, an internet connection for the first catalogue load and for
downloads, and enough free disk for the files you save.

---

## What you do

1. **Filters** (left panel), or a **Quick start** search: Brain MRI, Lung CT, Breast MRI, Prostate MRI, PET, Pathology.
2. **Overview, Browse, Download, Licences, Help** appear once a search matches scans.
   **Browse** opens a scan in the public IDC viewer. Nothing is downloaded.
3. **Download** saves DICOM on this computer. Tick the licence box, then **Start download**.
   The bar follows bytes written on disk. If a transfer stops, start it again: files
   already saved are skipped.
4. **Chat** is the box pinned to the **bottom of every page**, including the empty page
   before you pick a filter. Type a question, or pick a suggestion. **Enter** sends your
   own words. A dialog shows the exact prompt and asks **Are you sure?** before anything
   is sent.
5. **SQL playground** is the expander at the top of the page. Pick an example or write
   one `SELECT` / `WITH` query, then **Run query**.

**Save this search** writes `idc_search.json`. **Open a saved search** loads it back.

---

## Workflow

```mermaid
flowchart TD
  click[You click in IDC Explorer]

  click --> source{Query source setting}
  click --> open[Open a scan]
  click --> download[Start download]
  click --> cite[Generate citations]
  click --> missing[First load of a missing table]

  source -->|Local| duck[(DuckDB on this computer)]
  source -->|Remote IDC API| api[POST /v3/sql]
  source -->|Remote IDC MCP| mcp[POST /mcp tool run_sql]

  open --> viewer[viewer.imaging.datacommons.cancer.gov]
  download --> buckets[s3.amazonaws.com or storage.googleapis.com]
  cite --> doi[dx.doi.org]
  missing --> github[github.com/ImagingDataCommons/idc-index-data]
```

The same request flow is drawn as a Claude artifact: https://claude.ai/artifact/6mDVNyCmeT1Hk1o3YFJ1CC

The **Query source** control at the top of the left panel decides where catalogue SQL runs. The default is **Local**: filters, overview, browse, licences, chat, and the SQL playground all read DuckDB on this computer, and nothing is sent to `api.imaging.datacommons.cancer.gov`.

**Remote IDC API** posts that same SQL to `https://api.imaging.datacommons.cancer.gov/v3/sql`. **Remote IDC MCP** posts it to the `run_sql` tool at `https://api.imaging.datacommons.cancer.gov/mcp`. A typed question is still turned into SQL on this computer; only the query moves. Downloads, the viewer, and citations do not follow this switch. The filter lists stay counted from the local catalogue. The remote service returns at most 10,000 rows.

## Which URL each action calls

The public IDC services are:

- MCP: `https://api.imaging.datacommons.cancer.gov/mcp`
- API: `https://api.imaging.datacommons.cancer.gov/v3`

With **Query source** set to **Local** (the default), no request is sent to either address. Counts, filters, the chat, and the SQL playground read the catalogue already stored on this computer. Switching to **Remote IDC API** or **Remote IDC MCP** sends the catalogue SQL to the URL in the table below. The filter choice lists stay local either way.

| What you do | Query source | Request | URL |
|---|---|---|---|
| First start, loading a missing table (`ct_index`, `mr_index`, `pt_index`, `seg_index`, `analysis_results_index`) | any | `idc-index` downloads the parquet file once | `https://github.com/ImagingDataCommons/idc-index-data/releases/download/<release>/` |
| Filter choice lists | any | DuckDB query on this computer | none |
| Overview, Browse list, Licences table, chat SQL, SQL playground | Local | DuckDB query on this computer | none |
| Overview, Browse list, Licences table, chat SQL, SQL playground | Remote IDC API | `POST` JSON `{"sql", "max_rows"}` | `https://api.imaging.datacommons.cancer.gov/v3/sql` |
| Overview, Browse list, Licences table, chat SQL, SQL playground | Remote IDC MCP | `POST` JSON-RPC `tools/call` `run_sql` | `https://api.imaging.datacommons.cancer.gov/mcp` |
| Remote source selected | Remote | `GET` (once, to show the release) | `https://api.imaging.datacommons.cancer.gov/v3/version` |
| **Open** on a scan (CT, MRI, PET, and most other types) | any | Your browser opens the viewer | `https://viewer.imaging.datacommons.cancer.gov/v3/viewer/?StudyInstanceUIDs=…&initialSeriesInstanceUID=…` |
| **Open** on a pathology slide (SM) | any | Your browser opens the slim viewer | `https://viewer.imaging.datacommons.cancer.gov/slim/studies/…/series/…` |
| **Start download**, server Amazon | any | s5cmd copies objects | `https://s3.amazonaws.com` (bucket `idc-open-data`) |
| **Start download**, server Google | any | s5cmd copies objects | `https://storage.googleapis.com` |
| **Generate citations** | any | `idc-index` looks up each dataset DOI | `https://dx.doi.org/<doi>` |

The optional local assistant (`python assistant/server.py`) listens on `http://127.0.0.1:8765`. The Explorer does not call it, and that process does not call `api.imaging.datacommons.cancer.gov` either.

A typed question is sent with a short description of the filters on screen (patients,
scans, size). The download plan is added only when the question contains the word
download. The dialog then offers **Start this download**, which runs the same transfer
as the Download tab. With no filter chosen, that button asks you to pick a search first.
Files are never downloaded by the assistant itself.

Library questions (64, in `assistant/questions.jsonl`) ignore the filters on screen and
answer from the whole catalogue, using the SQL that was checked for that question.

Questions you send are stored on this computer in `~/.idc_explorer/memory.json`
(last 40). Delete that file to clear them.

---

## MCP, API, and skill

These are three different things. The Explorer always plans a typed question
with the in-process tools below. The **Query source** setting then decides
whether the SQL from those tools runs in local DuckDB or is posted to the
public IDC API or MCP server.

### MCP tools — used by the chat and the SQL playground

These tools run inside the Explorer process. With **Query source** set to
**Local**, they are not requests to
`https://api.imaging.datacommons.cancer.gov/mcp`. With **Remote IDC MCP**,
`engine.sql` posts the finished SQL to that server’s `run_sql` tool. With
**Remote IDC API**, it posts the same SQL to `/v3/sql` instead.

The tools live in `idc_explorer/assistant/tools.py`:

| Tool | Input | What it does |
|---|---|---|
| `ask` | `question`, optional `confirm_large` | `translate.py` turns a short English question into SQL, runs it, then adds a size warning and the SQL text (`guardrails.py`, `show_work.py`). |
| `query_index` | `sql`, optional `max_rows` | Runs one read-only `SELECT` or `WITH`. Refuses `;` and anything that is not a query. Caps the result at 5,000 rows. |

The Explorer calls them in-process:

```text
chat_memory.ask_mcp(question, engine.sql)   →  tools.call_tool("ask", ...)
chat_memory.sql_mcp(sql, engine.sql)        →  tools.call_tool("query_index", ...)
```

`chat_memory.mcp_tools` points `tools.query_index` at `engine.sql`. On **Local**,
that reads the DuckDB tables the app already loaded. On **Remote IDC API** or
**Remote IDC MCP**, `engine.sql` sends that statement to the public service
and returns the rows.

`ask` understands collection ids (`rider_pilot`), modalities (CT, MRI, PET, X-ray,
segmentation, pathology), body words (chest, lung, brain, head, abdomen, pelvis,
breast), and sex (male, female). It answers counts, licences, dataset lists, and a
small sample of series with viewer links. A question it cannot map gets a short note
and example questions. It does not download files.

### HTTP API — a separate program, not used by the Explorer

This local program is separate from `https://api.imaging.datacommons.cancer.gov/v3`.
The Explorer calls that NCI API only when **Query source** is **Remote IDC API**
(`/v3/sql` and, once, `/v3/version`). It never calls `assistant/server.py`.
`assistant/server.py` is an optional local server for the same tools, for notebooks or other machines.
Start it only when you want that:

```bash
../.venv/bin/python assistant/server.py
# http://127.0.0.1:8765
```

| Request | Body | Result |
|---|---|---|
| `GET /` | — | Small web page in `assistant/static/index.html` |
| `GET /mcp/tools` | — | The tool list |
| `POST /ask` | `{"question": "...", "confirm_large": false}` | The `ask` answer |
| `POST /mcp/call` | `{"name": "ask" or "query_index", "arguments": {...}}` | `{"result": ...}` |
| `POST /notebook` | `{"question": "..."}` or `{"answer": {...}}` | A Colab `.ipynb` |

There is no login. Leave it on `127.0.0.1`. This server uses `idc-index`’s own query
path, which is slower than the Explorer’s DuckDB copy. The Explorer does not start
this server and does not send questions to it.

### Stdio adapter — same tools, for another process

`assistant/mcp_stdio.py` reads one JSON object per line from stdin and writes one JSON
object per line to stdout:

```bash
cd assistant
echo '{"name":"ask","arguments":{"question":"How many patients are in rider_pilot?"}}' \
  | ../../.venv/bin/python mcp_stdio.py
```

That is a small line protocol (`{"name", "arguments"}` → `{"result"}` or `{"error"}`),
not the JSON-RPC session used by Claude Desktop (`initialize`, `tools/list`,
`tools/call`). The Explorer does not launch this process. To attach the tools to
Claude Desktop, wrap `TOOLS` and `call_tool` with the official MCP Python SDK. The
SQL and the guardrails stay in `tools.py`.

### Skill — for the coding agent, not for this app

A skill is a `SKILL.md` file an AI coding agent reads while editing a project.
This repo has Streamlit’s development skill at
`.claude/skills/developing-with-streamlit/SKILL.md` (and the same file under
`.agents/skills/`). It tells the agent how to edit Streamlit apps.

The running Explorer never reads a skill. End users never see one. There is no
IDC question skill on the chat path.

---

## Layout

```
idc_explorer/
├── app.py              Streamlit UI: filters, tabs, chat box, SQL playground
├── idc_engine.py       DuckDB queries, viewer links, download
├── chat_memory.py      Prompt text, local memory, ask_mcp, sql_mcp
├── assistant/
│   ├── tools.py        ask and query_index
│   ├── translate.py    English → SQL (rules)
│   ├── guardrails.py   Large-download warning and licence names
│   ├── show_work.py    SQL and Python shown with an answer
│   ├── questions.jsonl 64 checked questions
│   ├── mcp_stdio.py    Optional stdin/stdout adapter
│   ├── server.py       Optional HTTP API on port 8765
│   ├── to_colab.py     Answer → notebook (used by server.py)
│   └── static/index.html
├── requirements.txt    idc-index, streamlit, duckdb, pandas
└── .streamlit/config.toml

../solutions/           Not required to run the app
├── 03-notebook/        Jupyter version of the chat
├── 04-question-library Checked questions, QUESTIONS.md, check.py
├── 05-ai-guide/        llms.txt for people teaching another assistant
└── 06-guardrails/      Original of assistant/guardrails.py
```

Re-check the 64 questions after an IDC data update:

```bash
cd ../solutions/04-question-library
../../.venv/bin/python check.py
```

`--write` records new answers on purpose and rebuilds `QUESTIONS.md`.

Scripted use of the engine and the same tool the chat calls:

```python
from idc_engine import IDCEngine, Recipe
from chat_memory import ask_mcp

engine = IDCEngine()
recipe = Recipe(tumor_locations=["Brain"], modalities=["MR"])
print(engine.summary(recipe))
print(ask_mcp("How many patients have brain MRI?", engine.sql)["rows"])
```

Data citation: Fedorov A. et al., *National Cancer Institute Imaging Data Commons*,
RadioGraphics 43(12), 2023. https://doi.org/10.1148/rg.230180 — plus each dataset’s
DOI from the Licences tab.
