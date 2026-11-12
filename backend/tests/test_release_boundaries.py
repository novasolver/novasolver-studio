"""Light release/privacy regressions; no CAD applications, solvers or network sockets."""
import ast
import io
import os
from email.message import Message
from pathlib import Path
from types import SimpleNamespace
import urllib.error
import urllib.request
import urllib.response

import pytest

import test_network_audit as audit


@pytest.mark.parametrize("name", sorted(audit.CAD_LINKS))
@pytest.mark.parametrize("replacement", ["http://outside.invalid:", "http://127.0.0.1@outside.invalid:"])
def test_cad_audit_rejects_external_destinations(name, replacement):
    text = (audit.ROOT / name).read_text(encoding="utf-8")
    with pytest.raises(AssertionError, match="loopback"):
        audit.assert_no_upload_or_telemetry(name, text.replace("http://127.0.0.1:", replacement))


@pytest.mark.parametrize("name", sorted(audit.CAD_LINKS))
def test_cad_exception_does_not_allow_other_uploads(name):
    text = (audit.ROOT / name).read_text(encoding="utf-8")
    with pytest.raises(AssertionError, match="unapproved upload"):
        audit.assert_no_upload_or_telemetry(name, text.replace('f"/api/import?{q}"', 'f"/other?{q}"'))
    with pytest.raises(AssertionError, match="unapproved upload"):
        audit.assert_no_upload_or_telemetry(name, text + '\n_json(port, "/other", method="POST")\n')
    with pytest.raises(AssertionError, match="telemetry"):
        audit.assert_no_upload_or_telemetry(name, text + "\n# telemetry\n")


def test_cad_exception_is_scoped_to_exact_files(monkeypatch):
    text = (audit.ROOT / sorted(audit.CAD_LINKS)[0]).read_text(encoding="utf-8")
    name = "integrations/other/nss_link.py"
    with pytest.raises(AssertionError, match="sends data"):
        audit.assert_no_upload_or_telemetry(name, text)
    monkeypatch.setattr(audit, "audited_sources", lambda: iter([(name, text)]))
    with pytest.raises(AssertionError, match="network libraries"):
        audit.test_only_the_update_and_example_modules_use_the_network()


def fake_transport(monkeypatch, redirect=None, status=302):
    """Keep urllib's real redirect handling; replace only transport, so no sockets can open."""
    seen = []

    def respond(handler, req):
        seen.append((req.full_url, req.get_method(), req.data))
        assert req.host == "127.0.0.1:8765", f"CAD transport attempted an external request: {req.full_url}"
        headers = Message()
        if redirect:
            headers["Location"] = redirect
        response = urllib.response.addinfourl(io.BytesIO(b"{}"), headers, req.full_url, status if redirect else 200)
        response.msg = "Found" if redirect else "OK"
        return response

    monkeypatch.setattr(urllib.request, "_opener", None)
    monkeypatch.setattr(urllib.request, "getproxies", lambda: {})
    monkeypatch.setattr(urllib.request.HTTPHandler, "http_open", respond)
    monkeypatch.setattr(urllib.request.HTTPSHandler, "https_open", respond)
    return seen


def load_link(name):
    path = audit.ROOT / name
    namespace = {"__file__": str(path)}
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
    return namespace


@pytest.mark.parametrize("name", sorted(audit.CAD_LINKS))
def test_cad_import_request_stays_local(monkeypatch, name):
    seen = fake_transport(monkeypatch)
    link = load_link(name)
    with link["_request"](8765, "/api/import", data=b"synthetic CAD", method="POST") as response:
        assert response.read() == b"{}"
    assert seen == [("http://127.0.0.1:8765/api/import", "POST", b"synthetic CAD")]


@pytest.mark.parametrize("name", sorted(audit.CAD_LINKS))
@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
@pytest.mark.parametrize("method", ["GET", "POST"])
def test_cad_transport_refuses_external_redirect(monkeypatch, name, status, method):
    seen = fake_transport(monkeypatch, redirect="http://outside.invalid/redirected", status=status)
    link = load_link(name)
    with pytest.raises(urllib.error.HTTPError):
        link["_request"](8765, "/api/import", data=b"synthetic CAD" if method == "POST" else None,
                         method=method, timeout=1)
    assert len(seen) == 1


@pytest.mark.parametrize("name", sorted(audit.CAD_LINKS))
@pytest.mark.parametrize("target", [
    "https://outside.invalid/file", "//outside.invalid/file",
    "http://127.0.0.1@outside.invalid/file", "http://127.0.0.1:8765/local",
])
def test_cad_transport_rejects_every_redirect_target(monkeypatch, name, target):
    seen = fake_transport(monkeypatch, redirect=target)
    with pytest.raises(urllib.error.HTTPError):
        load_link(name)["_request"](8765, "/api/cases", timeout=1)
    assert len(seen) == 1


@pytest.mark.parametrize("name", sorted(audit.CAD_LINKS))
def test_cad_transport_ignores_proxies_and_global_opener(monkeypatch, name):
    seen = fake_transport(monkeypatch)
    monkeypatch.setattr(urllib.request, "getproxies", lambda: {"http": "http://outside.invalid:8080"})
    monkeypatch.setattr(urllib.request, "proxy_bypass", lambda host: False)

    def unexpected(*args, **kwargs):
        raise AssertionError("CAD transport used the process-global opener")

    monkeypatch.setattr(urllib.request, "_opener", SimpleNamespace(open=unexpected))
    with load_link(name)["_request"](8765, "/api/import", data=b"synthetic CAD", method="POST") as response:
        assert response.read() == b"{}"
    assert seen == [("http://127.0.0.1:8765/api/import", "POST", b"synthetic CAD")]


@pytest.mark.parametrize("name", sorted(audit.CAD_LINKS))
@pytest.mark.parametrize("port,path", [
    ("8765@outside.invalid", "/api/cases"), (True, "/api/cases"), (1023, "/api/cases"), (65536, "/api/cases"),
    (8765, "//outside.invalid/file"), (8765, "http://outside.invalid/file"), (8765, "/api/cases\n"),
])
def test_cad_transport_rejects_invalid_address_before_transport(monkeypatch, name, port, path):
    seen = fake_transport(monkeypatch)
    with pytest.raises(ValueError):
        load_link(name)["_request"](port, path)
    assert not seen


def test_cad_link_copies_are_identical():
    paths = [audit.ROOT / name for name in sorted(audit.CAD_LINKS)]
    assert paths[0].read_bytes() == paths[1].read_bytes()


@pytest.mark.parametrize("override", [None, "private-input/screenshot.png"])
def test_promo_screenshot_uses_private_temp_or_explicit_path(monkeypatch, override):
    if override is None:
        monkeypatch.delenv("NOVASTUDIO_LINCOLN_SCREENSHOT", raising=False)
    else:
        monkeypatch.setenv("NOVASTUDIO_LINCOLN_SCREENSHOT", override)
    path = audit.ROOT / "promo/patents/compose_lincoln.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    # Evaluate the path assignment only: importing the script would render an image.
    shot = next(n.value for n in tree.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "SHOT" for t in n.targets))
    result = eval(compile(ast.Expression(shot), str(path), "eval"),
                  {"Path": Path, "os": os, "tempfile": SimpleNamespace(gettempdir=lambda: "private-temp")})
    assert result == (Path(override) if override else Path("private-temp/NovaSolverStudio/promo/p6_gui_ja.png"))
