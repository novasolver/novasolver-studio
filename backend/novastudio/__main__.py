"""CLI / app entry.

  novastudio                 start the app: local server + the UI in its own window (what the packaged exe does)
  novastudio FILE.nscase     open a case file in the running app (or start it)
  novastudio --case ID       open a saved case in the app window (used by the Blender add-on)
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
    if len(argv) == 1 and argv[0].lower().endswith(".nscase"):  # a double-clicked case file (file association)
        _app(argv[0])
        return
    if len(argv) == 2 and argv[0] == "--case":                 # open a case by id (the Blender add-on sends one)
        import re
        if not re.fullmatch(r"c_\d{8}_\d{6}_[0-9a-f]{4}", argv[1]):
            raise SystemExit("--case expects a case id such as c_20261031_120000_ab12")
        _app(None, f"?case={argv[1]}")
        return
    ap =argparse.ArgumentParser(prog="novastudio")
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
    elif a.cmd == "serve":
        import uvicorn

        from .api import app
        uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="warning")
    else:
        _app(None)


def _app(case_path: str | None, query: str = "") -> None:
    """App mode (double-click, Start menu, a double-clicked .nscase): one server per user, the UI in its own window.
    A second start only opens another window on the running server (and imports the file it was given)."""
    import os
    import threading
    import time
    import webbrowser

    from . import desktop
    case = desktop.case_file([case_path]) if case_path else None
    no_ui = bool(os.environ.get("NOVASTUDIO_NO_BROWSER"))     # set by the update tests

    def show(port: int) -> object:
        url = f"http://127.0.0.1:{port}/{desktop.open_case(case) if case else query}"
        if no_ui:
            return None
        proc = desktop.open_window(url)
        if proc is None:
            webbrowser.open(url)
        return proc

    inst = desktop.Instance()
    if not inst.acquire():
        for _ in range(100):                                   # the first start may still be starting its server
            port = desktop.running_port()
            if port:
                show(port)
                return
            time.sleep(0.1)
    (desktop.data_dir() / "running.json").unlink(missing_ok=True)   # left by a crashed start; we own the lock now

    import uvicorn

    from .api import app
    port = _free_port(8765)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started and thread.is_alive():
        time.sleep(0.05)
    if not thread.is_alive():
        raise SystemExit("the local server could not start")
    inst.publish(port)
    proc = show(port)
    try:
        if proc is not None:                                   # own window: the program ends with its last window
            desktop.hide_console()
            desktop.wait_closed(proc)
        else:
            print(f"NovaSolver Studio is running at http://127.0.0.1:{port}/  (close this window to quit)")
            while thread.is_alive():
                thread.join(0.5)
    except KeyboardInterrupt:
        pass
    server.should_exit = True
    thread.join(10)


if __name__ == "__main__":
    main()
