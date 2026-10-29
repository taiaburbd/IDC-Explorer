"""Same tool functions as the portal, over stdin JSON lines.

Each input line is {"name": "ask", "arguments": {"question": "..."}}.
Each output line is {"result": ...} or {"error": ...}.
"""

from __future__ import annotations

import json
import sys

import tools


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
            result = tools.call_tool(message["name"], message.get("arguments") or {})
            sys.stdout.write(json.dumps({"result": result}) + "\n")
        except Exception as exc:
            sys.stdout.write(json.dumps({"error": str(exc)}) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
