"""All configuration access is confined to synthetic temporary files."""
import importlib.util
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
import novastudio
from novastudio import codex_mcp, commands
from novastudio.api import app


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    return tmp_path / "codex" / "config.toml"


def test_preview_and_explicit_apply(config_path):
    client = TestClient(app, base_url="http://127.0.0.1")
    preview = client.get("/api/integrations/codex").json()
    assert preview["path"] == str(config_path)
    assert preview["status"] == "ready"
    assert not config_path.parent.exists()
    assert client.post("/api/integrations/codex", json={}).status_code == 400
    result = client.post("/api/integrations/codex", json=preview).json()
    assert result["status"] == "configured"
    assert config_path.read_text() == codex_mcp.TABLE
    assert client.post("/api/integrations/codex", json=result).json()["status"] == "configured"
    assert not list(config_path.parent.glob("*.novasolver-backup-*"))


@pytest.mark.parametrize("version", [novastudio.__version__, "9.8.7"])
def test_generated_recipe_tracks_packaged_version(config_path, monkeypatch, version):
    # Load as a fresh packaged module to catch a stale literal at the next version bump too.
    monkeypatch.setattr(novastudio, "__version__", version)
    spec = importlib.util.spec_from_file_location("novastudio._test_codex_recipe", codex_mcp.__file__)
    writer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(writer)
    preview = writer.preview(config_path)
    recipe = writer.tomllib.loads(preview["table"])["mcp_servers"]["novasolver-studio"]
    assert recipe == {"command": "uvx", "args": [f"novasolver-studio=={version}", "mcp"],
                      "startup_timeout_sec": 120, "tool_timeout_sec": 120}
    assert not config_path.parent.exists()
    writer.configure(config_path, apply=True, expected=preview["revision"])
    assert writer.tomllib.loads(config_path.read_text())["mcp_servers"]["novasolver-studio"] == recipe
    assert writer.preview(config_path)["status"] == "configured"


def test_previous_release_pin_is_preserved_as_conflict(config_path):
    config_path.parent.mkdir()
    original = b'[mcp_servers.novasolver-studio]\ncommand="uvx"\nargs=["novasolver-studio==0.7.6.post1", "mcp"]\n'
    config_path.write_bytes(original)
    preview = commands.codex_integration()
    assert preview["status"] == "blocked"
    assert commands.codex_integration(str(config_path), apply=True,
                                      revision=codex_mcp.revision(True, original))["status"] == "blocked"
    assert config_path.read_bytes() == original
    assert list(config_path.parent.iterdir()) == [config_path]


def test_stale_preview_refuses_write(config_path):
    preview = commands.codex_integration()
    config_path.parent.mkdir()
    config_path.write_bytes(b"# concurrent change\n")
    result = commands.codex_integration(str(config_path), apply=True, revision=preview["revision"])
    assert result["status"] == "blocked"
    assert config_path.read_bytes() == b"# concurrent change\n"
    assert list(config_path.parent.iterdir()) == [config_path]


@pytest.mark.parametrize("content", [b"[broken SECRET", b"mcp_servers=42", b'[mcp_servers.novasolver-studio]\ncommand="SECRET"', b"\xff"])
def test_invalid_or_conflict_is_private(config_path, content):
    config_path.parent.mkdir()
    config_path.write_bytes(content)
    result = commands.codex_integration()
    assert result["status"] == "blocked"
    assert "SECRET" not in json.dumps(result)
    assert config_path.read_bytes() == content


def test_custom_settings_preserved(config_path):
    config_path.parent.mkdir()
    original = (codex_mcp.TABLE + 'enabled = false\n').encode()
    config_path.write_bytes(original)
    preview = commands.codex_integration()
    assert preview["status"] == "configured"
    assert commands.codex_integration(str(config_path), apply=True, revision=preview["revision"])["status"] == "configured"
    assert config_path.read_bytes() == original


def test_rejects_external_origin(config_path):
    client = TestClient(app, base_url="http://127.0.0.1")
    assert client.post("/api/integrations/codex", headers={"origin": "https://example.org"}, json={}).status_code == 403
    assert not config_path.exists()


def test_requires_explicit_path_and_preview(config_path):
    assert commands.codex_integration(apply=True, revision="x")["status"] == "blocked"
    assert commands.codex_integration(str(config_path), apply=True)["status"] == "blocked"
    assert commands.codex_integration("relative/config.toml")["status"] == "blocked"
    assert not config_path.parent.exists()


def test_language_keys_match():
    root = Path(__file__).resolve().parents[2] / "frontend" / "src" / "i18n"
    keys = [set(json.loads((root / f"{lang}.json").read_text(encoding="utf-8"))) for lang in ("ja", "en", "zh")]
    assert keys[0] == keys[1] == keys[2]


def test_acl_failure_never_replaces_original(config_path, monkeypatch):
    config_path.parent.mkdir()
    original = b'# private settings\nmodel="existing"\n'
    config_path.write_bytes(original)
    preview = commands.codex_integration()
    def refuse(*args):
        raise OSError("private filesystem detail")
    monkeypatch.setattr(codex_mcp, "copy_existing", refuse)
    result = commands.codex_integration(str(config_path), apply=True, revision=preview["revision"])
    assert result["status"] == "blocked"
    assert "private filesystem detail" not in json.dumps(result)
    assert config_path.read_bytes() == original
    assert not config_path.with_name("config.toml.novasolver.lock").exists()
