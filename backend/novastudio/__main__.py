"""CLI / app entry.

  novastudio                 start the app: local server + open the browser (what the packaged exe does)
  novastudio serve [--port]  server only (127.0.0.1)
  novastudio mcp             MCP server on stdio
  novastudio env             print available engines
  novastudio run-worker DIR  (internal) solver job process
  novastudio mesh-worker F   (internal) Gmsh worker process
"""
from __future__ import annotations

import argparse
import json
import multiprocessing
import socket
import sys


def _free_port(preferred: int) -> int:
    for port in (preferred, *range(preferred + 1, preferred + 20)):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return preferred


def main() -> None:
    multiprocessing.freeze_support()
    argv = sys.argv[1:]
    if argv and argv[0] == "run-worker":                       # internal: must stay fast and import little
        from .run_worker import main as run_main
        run_main(argv[1])
        return
    if argv and argv[0] == "mesh-worker":
        from .mesh_worker import main as mesh_main
        mesh_main(argv[1])
        return
    ap = argparse.ArgumentParser(prog="novastudio")
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("serve", help="run the local UI server (127.0.0.1 only)")
    s.add_argument("--port", type=int, default=8765)
    sub.add_parser("mcp", help="run the MCP server on stdio")
    sub.add_parser("env", help="print available engines")
    export = sub.add_parser('export-results',help='export VTU, CSV or a printable HTML report')
    export.add_argument('case_id')
    export.add_argument('format',choices=('vtu','csv','report'))
    export.add_argument('--lang',choices=('ja','en','zh'),default='ja')
    a = ap.parse_args(argv)
    if a.cmd == "mcp":
        from .mcp_server import main as mcp_main
        mcp_main()
    elif a.cmd == "env":
        from .commands import environment_check
        print(json.dumps(environment_check("en"), indent=1, ensure_ascii=False))
    elif a.cmd == 'export-results':
        from .commands import export_results
        print(json.dumps(export_results(a.case_id,a.format,a.lang),ensure_ascii=False))
    else:
        import threading
        import webbrowser

        import uvicorn

        from .api import app
        port = a.port if a.cmd == "serve" else _free_port(8765)
        if a.cmd is None:                                      # app mode: open the UI once the server is up
            import os
            if not os.environ.get("NOVASTUDIO_NO_BROWSER"):    # set by the update tests
                threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}/")).start()
            print(f"NovaSolver Studio is running at http://127.0.0.1:{port}/  (close this window to quit)")
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
