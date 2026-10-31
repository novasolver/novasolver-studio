"""Numbers-only mode: MCP replies never carry an image of the model (for confidential work with a cloud AI)."""
from novastudio import mcp_server


def test_images_kept_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("NOVASTUDIO_MCP_NO_IMAGES", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    r = mcp_server._ok("summary", {}, [b"\x89PNG"])
    assert [c.type for c in r.content] == ["text", "image"]


def test_env_switch_withholds_images(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("NOVASTUDIO_MCP_NO_IMAGES", "1")
    r = mcp_server._ok("summary", {"range": [0, 1]}, [b"\x89PNG"])
    assert [c.type for c in r.content] == ["text"]
    assert "numbers-only" in r.content[0].text
    assert r.structured_content == {"range": [0, 1]}


def test_file_switch_in_data_folder(monkeypatch, tmp_path):
    monkeypatch.delenv("NOVASTUDIO_MCP_NO_IMAGES", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    (tmp_path / "NovaSolverStudio").mkdir()
    (tmp_path / "NovaSolverStudio" / "mcp_no_images").write_text("")
    r = mcp_server._ok("summary", {}, [b"\x89PNG"])
    assert [c.type for c in r.content] == ["text"]
