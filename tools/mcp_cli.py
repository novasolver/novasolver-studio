"""Call Studio's MCP tools from a shell, one server per call (cases and jobs live on disk), for agents that cannot
attach an MCP server themselves (e.g. a sub-agent in an eval).  The workspace is NSS_EVAL_WS (required).

    python tools/mcp_cli.py list                      tool names, descriptions and input schemas + server instructions
    python tools/mcp_cli.py call TOOL '{"a": 1}'      text result (as an MCP client shows it); the JSON may also
                                                      come on stdin (PowerShell: '{"a": 1}' | python ... call TOOL)
    python tools/mcp_cli.py grade TASK ANSWER_FILE    agent_eval's deterministic checks on this workspace"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

sys.stdout.reconfigure(encoding="utf-8")
STUDIO = Path(__file__).resolve().parents[1]


async def main(argv):
    ws = Path(os.environ["NSS_EVAL_WS"])
    env = dict(os.environ, NOVASTUDIO_WORKSPACE=str(ws / "ws"), NOVASTUDIO_MCP_NO_IMAGES="1")
    params = StdioServerParameters(command=sys.executable, args=["-m", "novastudio", "mcp"], env=env,
                                   cwd=str(STUDIO / "backend"))
    async with stdio_client(params) as (rd, wr), ClientSession(rd, wr) as s:
        init = await s.initialize()
        if argv[0] == "list":
            print(init.instructions, "\n")
            for t in (await s.list_tools()).tools:
                print(f"## {t.name}\n{t.description}\ninput: {json.dumps(t.input_schema, ensure_ascii=False)}\n")
        elif argv[0] == "call":
            raw = argv[2] if len(argv) > 2 else ("" if sys.stdin.isatty() else sys.stdin.read())
            raw = raw.lstrip("﻿")                                     # PowerShell pipes a BOM
            r = await s.call_tool(argv[1], json.loads(raw) if raw.strip() else {})
            print(("ERROR: " if r.is_error else "") + "\n".join(c.text for c in r.content if c.type == "text"))
            # A real client keeps the server (and the solver jobs it started) alive; this one exits after each call,
            # which would end the job. Stay until the job is over, quietly, so the agent still polls job_status.
            jobs = [x.get("job_id") for x in [r.structured_content or {}] + (r.structured_content or {}).get("cases", [])
                    if isinstance(x, dict) and x.get("job_id") and not x.get("done")]
            for job in jobs:
                for _ in range(1800):
                    st = (await s.call_tool("job_status", {"job_id": job})).structured_content or {}
                    if st.get("state") not in ("queued", "running", None):
                        break
                    await asyncio.sleep(2)
        elif argv[0] == "grade":
            sys.path.insert(0, str(Path(__file__).parent))
            import agent_eval
            answer = Path(argv[2]).read_text(encoding="utf-8")
            print(json.dumps(await agent_eval.GRADERS[argv[1]](s, answer), ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
