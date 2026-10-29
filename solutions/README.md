# IDC solutions

Extras around **IDC Explorer** (`../idc_explorer`), the point-and-click app with the chat assistant.
The assistant itself (the MCP tools, the translator, the HTTP API) lives in
`idc_explorer/assistant/`.

| Folder | What it is | Who it is for |
|---|---|---|
| `03-notebook` | A chat notebook: ask questions in plain English, 10 worked examples, a SQL playground | Anyone with Jupyter |
| `04-question-library` | 64 common questions with checked SQL and answers. The Explorer chat suggests them. | Users looking for ideas; maintainers checking a new release |
| `05-ai-guide` | `llms.txt`: one page that teaches an AI assistant to query IDC correctly | People using Claude, ChatGPT or an agent |
| `06-guardrails` | Original of the large-download warning and licence notes used by the assistant | Developers |

Run the assistant's HTTP API on its own:

```bash
.venv/bin/python idc_explorer/assistant/server.py     # http://127.0.0.1:8765
```
