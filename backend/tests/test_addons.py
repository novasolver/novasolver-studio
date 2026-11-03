"""Blender add-on / FreeCAD macro installer (addons.py): the zip Blender installs, the macro folder FreeCAD uses, and
the refusal to run a program that was not found by the search."""
import zipfile

import pytest

from novastudio import addons
from novastudio.store import StudioError


def test_addon_zip_has_the_manifest_at_its_root(tmp_path):
    z = addons._addon_zip(tmp_path)
    names = zipfile.ZipFile(z).namelist()
    assert "blender_manifest.toml" in names and "__init__.py" in names
    assert not any("__pycache__" in n or n.endswith(".pyc") for n in names)
    assert addons.addon_version() in z.name


def test_freecad_macro_folder_from_user_cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(addons, "_roaming", lambda: tmp_path)
    monkeypatch.setattr(addons.sys, "platform", "win32")
    base = tmp_path / "FreeCAD"
    base.mkdir()
    assert addons.macro_dir() == base / "Macro"                       # nothing configured yet: the default
    (base / "user.cfg").write_text('<FCParameters><FCText Name="MacroPath">D:\\my macros</FCText></FCParameters>',
                                   encoding="utf-8")
    assert str(addons.macro_dir()) == "D:\\my macros"
    (base / "user.cfg").write_text('<FCParameters><FCText Name="MacroPath">D:\\CAD &amp; FEA</FCText></FCParameters>', encoding="utf-8")
    assert str(addons.macro_dir()) == "D:\\CAD & FEA"                  # user.cfg is XML
    v11 = base / "v1-1"                                                 # FreeCAD 1.1 keeps a folder per version
    v11.mkdir()
    (v11 / "user.cfg").write_text("<FCParameters/>", encoding="utf-8")
    assert addons.macro_dir() == v11 / "Macro"


def test_freecad_install_and_state(tmp_path, monkeypatch):
    monkeypatch.setattr(addons, "_roaming", lambda: tmp_path)
    monkeypatch.setattr(addons.sys, "platform", "win32")
    assert addons.freecad_status()["installed"] is None
    out = addons.install_freecad()
    assert out["path"].endswith(addons.MACRO)
    assert addons.freecad_status()["installed"] == "current"
    (tmp_path / "FreeCAD" / "Macro" / addons.MACRO).write_text("# an older macro", encoding="utf-8")
    assert addons.freecad_status()["installed"] == "other"


def test_blender_install_only_for_a_found_program(monkeypatch, tmp_path):
    monkeypatch.setattr(addons, "_blender_candidates", lambda: [])
    with pytest.raises(StudioError) as e:
        addons.install_blender(str(tmp_path / "evil.exe"))
    assert e.value.key == "err.addon_program"


def test_blender_version_from_folder_name(tmp_path):
    exe = tmp_path / "Blender 4.2" / "blender.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"")
    assert addons._blender_version(exe) == (4, 2)
