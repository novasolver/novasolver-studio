"""Pack the built app as an MCP Bundle: release/novasolver-studio-<version>-win64.mcpb (+ .sha256).
The manifest text and icon come from the previous bundle; the version is the app's and the tool list is read
from the built exe itself (`NovaSolverStudio.exe mcp`, tools/list), so new tools are never left out.
usage: .venv\\Scripts\\python make_mcpb.py <previous .mcpb>   (run after build_release.ps1)"""
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path


def built_tools(exe: Path) -> list[dict]:
    p = subprocess.Popen([str(exe), "mcp"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         text=True, encoding="utf-8")

    def ask(i, method, params=None):
        p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": i, "method": method, "params": params or {}}) + "\n")
        p.stdin.flush()
        while True:
            m = json.loads(p.stdout.readline())
            if m.get("id") == i:
                return m["result"]

    ask(1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "make_mcpb", "version": "1"}})
    p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
    tools = ask(2, "tools/list")["tools"]
    p.terminate()
    # one line each, like the earlier bundles
    return [{"name": t["name"], "description": " ".join(t.get("description", "").split())[:120]} for t in tools]

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))
from novastudio import __version__  # noqa: E402

app = ROOT / "build" / "dist" / "NovaSolverStudio"
prev = zipfile.ZipFile(sys.argv[1])
manifest = json.loads(prev.read("manifest.json"))
manifest["version"] = __version__
assert (app / "NovaSolverStudio.exe").exists(), app
manifest["tools"] = built_tools(app / "NovaSolverStudio.exe")
out = ROOT / "release" / f"novasolver-studio-{__version__}-win64.mcpb"
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
    z.writestr("icon.png", prev.read("icon.png"))
    for f in sorted(app.rglob("*")):
        if f.is_file():
            z.write(f, "server/" + f.relative_to(app).as_posix())
h = hashlib.sha256(out.read_bytes()).hexdigest()
(out.parent / (out.name + ".sha256")).write_text(f"{h}  {out.name}\n", encoding="ascii")
print(out, f"{out.stat().st_size / 1e6:.1f} MB", h)
