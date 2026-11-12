"""Release preflight with temporary artifacts only: no keys, signing or network."""
import hashlib
import importlib.util
from pathlib import Path
import zipfile

import pytest


_spec = importlib.util.spec_from_file_location(
    "release_signer", Path(__file__).resolve().parents[2] / "tools" / "sign_latest.py")
signer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(signer)

VERSION = "0.8.0"
HEADING_NOTES = """# NovaSolver Studio 0.8.0

## English
- First sentence with novasolver.jp and 0.8.0
  across a wrapped line. Second sentence.
- Another change.

## 日本語
- 日本語の最初の文を
  続けます。二番目の文。

## 中文
- 中文第一句。第二句。
"""


def write_wheel(root, *, version=VERSION, name="novasolver-studio", metadata=True):
    path = root / "dist-py" / f"novasolver_studio-{VERSION}-py3-none-any.whl"
    path.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(path, "w") as wheel:
        wheel.writestr("novastudio/__init__.py", f'__version__ = "{version}"\n')
        if metadata:
            wheel.writestr(f"novasolver_studio-{VERSION}.dist-info/METADATA",
                           f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n")
    return path


@pytest.fixture
def artifacts(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / f"RELEASE_NOTES_v{VERSION}.md").write_text(HEADING_NOTES, encoding="utf-8")
    (tmp_path / "release").mkdir()
    archive = tmp_path / "release" / f"NovaSolverStudio-{VERSION}-win64.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("NovaSolverStudio/dummy.txt", "test release")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_name(archive.name + ".sha256").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    write_wheel(tmp_path)
    return tmp_path, archive, digest


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
@pytest.mark.parametrize("spaced", [True, False])
def test_heading_notes_and_wrapped_bullets(newline, spaced):
    text = HEADING_NOTES if spaced else HEADING_NOTES.replace("## ", "##")
    result = signer.parse_notes(text.replace("\n", newline))
    assert result == {
        "en": "• First sentence with novasolver.jp and 0.8.0 across a wrapped line.\n• Another change.",
        "ja": "・日本語の最初の文を 続けます。",
        "zh": "・中文第一句。",
    }


def test_headings_override_horizontal_rules_and_section_order():
    text = "## 中文\n- 中文。\n---\n## English\n- English.\n---\n## 日本語\n- 日本語。\n"
    assert signer.parse_notes(text) == {"en": "• English.", "ja": "・日本語。", "zh": "・中文。"}


@pytest.mark.parametrize("chinese", [False, True])
def test_legacy_sections(chinese):
    text = "# Release\r\n- English. Detail.\r\n  ---  \r\n- 日本語。詳細。"
    if chinese:
        text += "\r\n---\r\n- 中文。详情。"
    assert signer.parse_notes(text) == {
        "en": "• English.", "ja": "・日本語。", "zh": "・中文。" if chinese else "• English."}


def test_english_only_fallback_and_bullet_limit():
    result = signer.parse_notes("## English\n" + "\n".join(f"* Change {i}. Detail." for i in range(7)))
    assert result["en"] == "\n".join(f"• Change {i}." for i in range(5))
    assert result["ja"] == result["zh"] == result["en"]


@pytest.mark.parametrize("text, message", [
    ("", "non-empty English"),
    ("# Release\nNo bullets", "non-empty English"),
    ("## 日本語\n- 日本語。", "non-empty English"),
    ("## English\n- Valid.\n## 日本語\nNo bullets", "no bullets: ja"),
    ("## English\n- Valid.\n## English\n- Duplicate.", "Duplicate"),
    ("- Valid.\n---\n", "no bullets: ja"),
])
def test_invalid_notes_are_rejected(text, message):
    with pytest.raises(ValueError, match=message):
        signer.parse_notes(text)


def test_notes_locations_and_missing_notes(artifacts):
    root, _, _ = artifacts
    docs = root / "docs" / f"RELEASE_NOTES_v{VERSION}.md"
    legacy = root / "release" / docs.name
    legacy.write_text("- Legacy English.\n---\n- 日本語。", encoding="utf-8")
    assert "First sentence" in signer.notes(VERSION, root)["en"]
    docs.write_text("# Empty notes", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid release notes"):
        signer.notes(VERSION, root)  # Do not hide malformed primary notes with legacy content.
    docs.unlink()
    assert signer.notes(VERSION, root)["en"] == "• Legacy English."
    legacy.unlink()
    with pytest.raises(FileNotFoundError, match="Missing release notes"):
        signer.build_payload(VERSION, root)


def test_payload_uses_verified_artifacts(artifacts):
    root, archive, digest = artifacts
    result = signer.build_payload(VERSION, root, date="2026-11-13")
    assert result["version"] == VERSION
    assert result["date"] == "2026-11-13"
    assert result["notes"] == signer.parse_notes(HEADING_NOTES)
    assert result["windows_zip"] == {
        "sha256": digest, "size": archive.stat().st_size,
        "urls": [f"https://github.com/novasolver/novasolver-studio/releases/download/v{VERSION}/{archive.name}",
                 f"https://novasolver.jp/dl/studio/{archive.name}"],
    }
    assert result["python"]["command"] == (
        "uvx --from https://github.com/novasolver/novasolver-studio/releases/download/"
        f"v{VERSION}/novasolver_studio-{VERSION}-py3-none-any.whl novasolver-studio")


def test_changed_archive_rejected_even_with_valid_sidecar(artifacts):
    root, archive, _ = artifacts
    with archive.open("ab") as stream:
        stream.write(b"changed after hashing")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        signer.build_payload(VERSION, root)


@pytest.mark.parametrize("sidecar", ["", "not-a-hash", "0" * 63, "g" * 64])
def test_invalid_sidecar(artifacts, sidecar):
    root, archive, _ = artifacts
    archive.with_name(archive.name + ".sha256").write_text(sidecar, encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid SHA-256 sidecar"):
        signer.build_payload(VERSION, root)


def test_uppercase_checksum_is_normalized(artifacts):
    _, archive, digest = artifacts
    archive.with_name(archive.name + ".sha256").write_text(digest.upper(), encoding="utf-8")
    assert signer.verified_zip(archive) == (digest, archive.stat().st_size)


@pytest.mark.parametrize("missing", ["zip", "sidecar", "wheel"])
def test_missing_artifact(artifacts, missing):
    root, archive, _ = artifacts
    paths = {"zip": archive, "sidecar": archive.with_name(archive.name + ".sha256"),
             "wheel": root / "dist-py" / f"novasolver_studio-{VERSION}-py3-none-any.whl"}
    paths[missing].unlink()
    with pytest.raises(FileNotFoundError):
        signer.build_payload(VERSION, root)


@pytest.mark.parametrize("kwargs, message", [
    ({"version": "0.7.0"}, "version mismatch"),
    ({"name": "unrelated-package"}, "name mismatch"),
    ({"metadata": False}, "exactly one"),
])
def test_wheel_metadata_must_match(artifacts, kwargs, message):
    root, _, _ = artifacts
    write_wheel(root, **kwargs)
    with pytest.raises(ValueError, match=message):
        signer.build_payload(VERSION, root)


def test_invalid_wheel_archive(artifacts):
    root, _, _ = artifacts
    path = write_wheel(root)
    path.write_bytes(b"not a wheel")
    with pytest.raises(ValueError, match="Invalid wheel archive"):
        signer.build_payload(VERSION, root)


@pytest.mark.parametrize("version", ["../0.8.0", "0.8.0-rc1", "0.8", "0.8.0;command"])
def test_version_rejected_before_artifact_access(tmp_path, version):
    with pytest.raises(ValueError, match="Invalid release version"):
        signer.build_payload(version, tmp_path)


def test_cli_preflight_fails_before_any_key_access(artifacts, monkeypatch):
    root, _, _ = artifacts
    (root / "dist-py" / f"novasolver_studio-{VERSION}-py3-none-any.whl").unlink()
    monkeypatch.setattr(signer, "ROOT", root)
    monkeypatch.setattr(signer.sys, "argv", ["sign_latest.py", VERSION])

    def forbidden_read(*args, **kwargs):
        pytest.fail("preflight must not read a signing key")

    monkeypatch.setattr(Path, "read_bytes", forbidden_read)
    with pytest.raises(SystemExit, match="Release validation failed: Missing built wheel"):
        signer.main()
    assert not (root / "release" / f"latest-{VERSION}.json").exists()
