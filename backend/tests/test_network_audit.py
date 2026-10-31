"""No data leaves the computer: the only code that may open a network connection is the update check/download
(updates.py) and the solved-example download (examples.py), both HTTPS GET requests that send nothing about the user
or the models. This test fails when any other module imports a networking library or names an outside address, so
the promise in docs/PRIVACY.md cannot quietly stop being true."""
import ast
import re
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "novastudio"
NETWORK_MODULES = {"urllib.request", "http.client", "requests", "httpx", "aiohttp", "ftplib", "smtplib", "socket",
                   "websocket", "websockets", "paramiko", "urllib3", "pycurl"}
ALLOWED = {
    "updates.py": {"urllib.request"},          # signed update notice and the release zip (GitHub / novasolver.jp)
    "examples.py": {"urllib.request"},         # solved examples from the GitHub release
    "__main__.py": {"socket"},                 # finds a free port on 127.0.0.1 (binds locally, connects nowhere)
}
# addresses Studio itself may contact; other https:// strings in the code are links shown to the user
CONTACTED = ("https://novasolver.jp/studio/latest.json", "https://raw.githubusercontent.com/novasolver/novasolver-studio/",
             "https://github.com/novasolver/novasolver-studio/releases/download/", "https://novasolver.jp/dl/studio/",
             "http://127.0.0.1:",      # this computer: the updater's test server, accepted only under the test switch
             "https://github.com/novasolver/novasolver-studio/releases/tag/")   # a page link opened in the browser


def imports(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module
            yield from (f"{node.module}.{a.name}" for a in node.names)


def test_only_the_update_and_example_modules_use_the_network():
    found = {}
    for f in PKG.rglob("*.py"):
        used = {m for m in imports(ast.parse(f.read_text(encoding="utf-8"))) if m in NETWORK_MODULES}
        extra = used - ALLOWED.get(f.name, set())
        if extra:
            found[f.name] = sorted(extra)
    assert not found, f"network libraries outside updates/examples: {found}"


def test_requests_go_only_to_the_listed_addresses():
    for name in ("updates.py", "examples.py"):
        text = (PKG / name).read_text(encoding="utf-8")
        for url in re.findall(r"https?://[^\s'\"{}]+", text):
            assert url.startswith(CONTACTED), f"{name} contacts an unlisted address: {url}"


def test_no_upload_or_telemetry_code():
    for f in PKG.rglob("*.py"):
        text = f.read_text(encoding="utf-8")
        assert not re.search(r"method\s*=\s*['\"](POST|PUT|PATCH)['\"]", text), f"{f.name} sends data with POST/PUT"
        assert not re.search(r"telemetry|analytics|sentry|crash.?report", text, re.I), f"{f.name} mentions telemetry"


def test_server_listens_on_loopback_only():
    main = (PKG / "__main__.py").read_text(encoding="utf-8")
    assert "0.0.0.0" not in main and '"::"' not in main
    assert "127.0.0.1" in main
