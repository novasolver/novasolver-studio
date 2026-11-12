"""The only internet requests in the app are the update check/download
(updates.py) and the solved-example download (examples.py), both HTTPS GET requests that send nothing about the user
or the models. This test fails when any other module imports a networking library or names an outside address, so
the promise in docs/PRIVACY.md cannot quietly stop being true. CAD add-ons may send imports to loopback only;
test_release_boundaries.py also checks that their transport refuses external redirects."""
import ast
import re
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "novastudio"
ROOT = PKG.parents[1]
CAD_LINKS = {
    "integrations/freecad/NovaSolverStudio/nss_link.py",
    "integrations/fusion/NovaSolverStudio/nss_link.py",
}
NETWORK_MODULES = {"urllib.request", "http.client", "requests", "httpx", "aiohttp", "ftplib", "smtplib", "socket",
                   "websocket", "websockets", "paramiko", "urllib3", "pycurl"}
ALLOWED = {
    "updates.py": {"urllib.request"},          # signed update notice and the release zip (GitHub / novasolver.jp)
    "examples.py": {"urllib.request"},         # solved examples from the GitHub release
    "__main__.py": {"socket"},                 # finds a free port on 127.0.0.1 (binds locally, connects nowhere)
    # the Blender add-on runs inside Blender and talks to Studio on this computer: see the test below
    "integrations/blender/novasolver_studio/__init__.py": {"socket", "urllib.request"},
    **{name: {"socket", "urllib.request"} for name in CAD_LINKS},
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


def audited_sources():
    """Check build copies when present and canonical add-ons even in an unstaged checkout."""
    for f in PKG.rglob("*.py"):
        yield f.relative_to(PKG).as_posix(), f.read_text(encoding="utf-8")
    for f in (ROOT / "integrations").rglob("*.py"):
        yield f.relative_to(ROOT).as_posix(), f.read_text(encoding="utf-8")


def assert_cad_loopback(text):
    calls = [n for n in ast.walk(ast.parse(text)) if isinstance(n, ast.Call)]
    network = [n for n in calls if re.fullmatch(r"(?:socket|urllib\.request)\.\w+", ast.unparse(n.func))]
    assert sorted(ast.unparse(n.func) for n in network) == [
        "socket.create_connection", "urllib.request.ProxyHandler", "urllib.request.Request", "urllib.request.build_opener"]
    expected = {
        "socket.create_connection": '("127.0.0.1", port)',
        "urllib.request.ProxyHandler": "{}",
        "urllib.request.Request": 'f"http://127.0.0.1:{port}{path}"',
        "urllib.request.build_opener": "urllib.request.ProxyHandler({})",
    }
    for n in network:
        assert n.args and ast.dump(n.args[0]) == ast.dump(ast.parse(expected[ast.unparse(n.func)], mode="eval").body), \
            "CAD transport must use the fixed loopback URL"
    opener = next(n for n in network if ast.unparse(n.func) == "urllib.request.build_opener")
    assert len(opener.args) == 2 and ast.unparse(opener.args[1]) == "_NoRedirects()"
    opened = [n for n in calls if ast.unparse(n.func) == "opener.open"]
    assert len(opened) == 1 and ast.unparse(opened[0].args[0]) == "req"


def assert_no_upload_or_telemetry(name, text):
    assert not re.search(r"telemetry|analytics|sentry|crash.?report", text, re.I), f"{name} mentions telemetry"
    uploads = re.findall(r"method\s*=\s*['\"](POST|PUT|PATCH)['\"]", text)
    if not uploads:
        return
    assert name in CAD_LINKS, f"{name} sends data with POST/PUT/PATCH"
    assert_cad_loopback(text)
    # The sole exception is the known CAD import call, not arbitrary uploads anywhere in an allowed file.
    tree = ast.parse(text)
    post_import = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "post_import")
    allowed = [n for n in ast.walk(post_import) if isinstance(n, ast.Call)
               and ast.unparse(n.func) == "_json" and len(n.args) == 2
               and ast.unparse(n.args[0]) == "port"
               and ast.dump(n.args[1]) == ast.dump(ast.parse('f"/api/import?{q}"', mode="eval").body)
               and any(k.arg == "method" and isinstance(k.value, ast.Constant) and k.value.value == "POST"
                       for k in n.keywords)]
    assert uploads == ["POST"] and len(allowed) == 1, f"{name} has an unapproved upload"


def test_only_the_update_and_example_modules_use_the_network():
    found = {}
    for name, text in audited_sources():
        used = {m for m in imports(ast.parse(text)) if m in NETWORK_MODULES}
        extra = used - ALLOWED.get(name, set())
        if extra:
            found[name] = sorted(extra)
        if name in CAD_LINKS:
            assert_cad_loopback(text)
    assert not found, f"network libraries outside updates/examples: {found}"


def test_the_blender_addon_only_connects_to_this_computer():
    sources = [src for name, src in audited_sources() if name == "integrations/blender/novasolver_studio/__init__.py"]
    assert sources, "Blender add-on source is missing"
    for src in sources:
        assert re.findall(r"create_connection\(\(\s*([^,]+),", src) == ['"127.0.0.1"']
        assert re.findall(r"urllib\.request\.Request\(\s*(f?\"[^\"]*\")", src) == ['f"http://127.0.0.1:{port}{path}"']


def test_requests_go_only_to_the_listed_addresses():
    for name in ("updates.py", "examples.py"):
        text = (PKG / name).read_text(encoding="utf-8")
        for url in re.findall(r"https?://[^\s'\"{}]+", text):
            assert url.startswith(CONTACTED), f"{name} contacts an unlisted address: {url}"


def test_no_upload_or_telemetry_code():
    for name, text in audited_sources():
        assert_no_upload_or_telemetry(name, text)


def test_server_listens_on_loopback_only():
    main = (PKG / "__main__.py").read_text(encoding="utf-8")
    assert "0.0.0.0" not in main and '"::"' not in main
    assert "127.0.0.1" in main
