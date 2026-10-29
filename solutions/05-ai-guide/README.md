# AI guide

[`llms.txt`](llms.txt) is a single page that teaches an AI assistant (Claude, ChatGPT, a coding
agent, or an MCP client) how to answer IDC questions correctly: the tables, the rules that change
the answer, and examples that have been checked to run.

How to use it:
- **Chat with an AI**: paste `llms.txt` at the start of the conversation, then ask your question.
- **Your own app or agent**: put it in the system prompt, or serve it as an MCP resource next to
  the `ask` and `query_index` tools in `idc_explorer/assistant/`.
- **More examples**: `../04-question-library/QUESTIONS.md` (64 checked questions).

Every SQL example in `llms.txt` was run against idc-index-data 25.0.5. Re-check them after a new
IDC release.
