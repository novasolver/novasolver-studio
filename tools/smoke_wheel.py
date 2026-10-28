"""Exercise the installed wheel in a fresh environment, without the source checkout on PYTHONPATH."""
from __future__ import annotations

import argparse
import os
import json
import queue
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import venv
from pathlib import Path


def _stop_server(server: subprocess.Popen) -> None:
    import psutil
    from novastudio.external import _kill_tree
    try:
        children = psutil.Process(server.pid).children(recursive=True)
    except psutil.Error:
        children = []
    if server.poll() is None:
        _kill_tree(server)                        # Windows console launchers can have a Python child
    server.wait(timeout=10)
    psutil.wait_procs(children, timeout=10)


def check_mcp(command: str, env: dict) -> None:
    from importlib.resources import files
    from mcp.types import LATEST_PROTOCOL_VERSION

    # Exercise the wire protocol with ordinary stdio, independently of the SDK client's process transport.
    with Path("mcp.log").open("w", encoding="utf-8") as log:
        server = subprocess.Popen([command, "mcp"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log,
                                  text=True, encoding="utf-8", env=env)
        messages = queue.Queue()
        def read_messages():
            try:
                for line in server.stdout:
                    messages.put(json.loads(line))
            except Exception as exc:
                messages.put(exc)
            finally:
                messages.put(None)
        reader = threading.Thread(target=read_messages, daemon=True)
        reader.start()
        deadline = time.monotonic() + 300
        request_id = 0

        def send(message):
            server.stdin.write(json.dumps({"jsonrpc": "2.0", **message}) + "\n")
            server.stdin.flush()

        def request(method, params=None):
            nonlocal request_id
            request_id += 1
            send({"id": request_id, "method": method, "params": params or {}})
            while True:
                message = messages.get(timeout=max(0.1, deadline - time.monotonic()))
                if message is None or isinstance(message, Exception):
                    raise RuntimeError(f"MCP server ended: {message}; " + Path("mcp.log").read_text(encoding="utf-8"))
                if message.get("id") == request_id:
                    assert "error" not in message, message
                    return message["result"]

        def tool(name, **arguments):
            result = request("tools/call", {"name": name, "arguments": arguments})
            assert not result.get("isError"), result
            return result["structuredContent"]

        try:
            request("initialize", {"protocolVersion": LATEST_PROTOCOL_VERSION, "capabilities": {},
                                   "clientInfo": {"name": "novastudio-wheel-smoke", "version": "1.0"}})
            send({"method": "notifications/initialized"})
            tools = request("tools/list")["tools"]
            assert len(tools) == 24, len(tools)
            cid = tool("create_case", template="cantilever", changes={"mesh.size": "coarse"}, language="en")["case_id"]
            result = tool("run_simulation", case_id=cid, mode="preview", language="en")
            while not result.get("done"):
                assert time.monotonic() < deadline, "cantilever solve timed out"
                time.sleep(1)
                status = tool("job_status", job_id=result["job_id"], language="en")
                assert status["state"] not in ("failed", "stopped"), status
                if status["state"] == "done":
                    result = {"done": True, "results": tool("get_results", case_id=cid, language="en")}
            assert result["results"]["gates"] == {"ran": True, "converged": True, "verified": True}, result
            env_check = tool("environment_check", language="en")
            # the installed package starts the MCP server with its own interpreter (uvx is only an alternative)
            assert env_check["mcp_command"]["args"] == ["-m", "novastudio", "mcp"], env_check
            assert Path(env_check["mcp_command"]["command"]).is_file(), env_check
            assert files("novastudio").joinpath("samples", "l_bracket.step").is_file()
            assert files("novastudio").joinpath("i18n", "ja.json").is_file()
        finally:
            server.stdin.close()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                _stop_server(server)
            reader.join(timeout=2)
            server.stdout.close()
    print("MCP: 24 tools, installed MCP command, samples and verified cantilever solve passed", flush=True)


def check_gui(command: str, env: dict, root: Path) -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    with (root / "gui.log").open("w", encoding="utf-8") as log:
        server = subprocess.Popen([command, "serve", "--port", str(port)], env=env, cwd=root,
                                  stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 60
            while True:
                try:
                    with urllib.request.urlopen(base + "/", timeout=2) as response:
                        html = response.read().decode("utf-8")
                        assert response.status == 200
                    break
                except (urllib.error.URLError, TimeoutError):
                    if server.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError((root / "gui.log").read_text(encoding="utf-8"))
                    time.sleep(0.2)
            asset = re.search(r'(?:src|href)="(/assets/[^" ]+)"', html)
            assert asset, html
            with urllib.request.urlopen(base + asset[1], timeout=10) as response:
                assert response.status == 200 and response.read()
        finally:
            _stop_server(server)
    print("GUI: index and bundled asset passed", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", nargs="?", type=Path)
    parser.add_argument("--check-installed", metavar="COMMAND", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.check_installed:
        check_mcp(args.check_installed, dict(os.environ))
        check_gui(args.check_installed, dict(os.environ), Path.cwd())
        return
    wheels = sorted((Path(__file__).resolve().parents[1] / "dist-py").glob("*.whl"), key=lambda p: p.stat().st_mtime)
    wheel = (args.wheel or (wheels[-1] if wheels else Path("missing.whl"))).resolve()
    if not wheel.is_file():
        parser.error("build a wheel first with tools/build_wheel.py")
    # Keep all test state inside the worktree's ignored .tmp when run from this checkout.
    temp = Path(__file__).resolve().parents[1] / ".tmp"
    temp.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="wheel-smoke-", dir=temp) as folder:
        root = Path(folder)
        venv.EnvBuilder(with_pip=True).create(root / "venv")
        scripts = root / "venv" / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")
        command = scripts / ("novasolver-studio.exe" if os.name == "nt" else "novasolver-studio")
        env = dict(os.environ, NOVASTUDIO_WORKSPACE=str(root / "解析 workspace"), LOCALAPPDATA=str(root / "data"))
        env.pop("PYTHONPATH", None)
        subprocess.run([str(python), "-m", "pip", "install", "--no-compile", str(wheel)], check=True, env=env, cwd=root)
        subprocess.run([str(python), str(Path(__file__).resolve()), "--check-installed", str(command)],
                       check=True, env=env, cwd=root, timeout=420)


if __name__ == "__main__":
    main()
