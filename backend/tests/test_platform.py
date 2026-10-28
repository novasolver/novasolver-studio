"""OS branches are exercised on any host; native solver execution is covered by CI."""
from __future__ import annotations

import ctypes
import importlib.resources
import importlib.util
import json
import re
import shlex
import sys
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest
from fastapi.testclient import TestClient

from novastudio import commands, config, fem_tet10
from novastudio import osdirs as locations


@pytest.mark.parametrize("os_name, data, workspace", [
    ("win32", "NovaSolverStudio", "Documents/NovaSolverStudio/workspace"),
    ("darwin", "Library/Application Support/NovaSolverStudio", "NovaSolverStudio/workspace"),
    ("linux", ".local/share/NovaSolverStudio", "NovaSolverStudio/workspace"),
])
def test_locations(monkeypatch, tmp_path, os_name, data, workspace):
    monkeypatch.setattr(sys, "platform", os_name)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    for name in ("LOCALAPPDATA", "XDG_DATA_HOME", "NOVASTUDIO_WORKSPACE"):
        monkeypatch.delenv(name, raising=False)
    assert locations.data_dir() == tmp_path / data
    assert locations.default_workspace() == tmp_path / workspace
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("NOVASTUDIO_WORKSPACE", str(tmp_path / "chosen"))
    assert locations.data_dir() == tmp_path / "local" / "NovaSolverStudio"
    assert locations.default_workspace() == tmp_path / "chosen"
    assert config.workspace() == tmp_path / "chosen"


def test_xdg_data(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert locations.data_dir() == tmp_path / "xdg" / "NovaSolverStudio"


@pytest.mark.parametrize("os_name", ["win32", "darwin", "linux"])
def test_solver_slot_uses_data_dir(monkeypatch, tmp_path, os_name):
    from novastudio.run_worker import _acquire_solver_slot, _release_solver_slot
    monkeypatch.setattr(sys, "platform", os_name)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    slot = _acquire_solver_slot(tmp_path / "job")
    try:
        assert slot == locations.data_dir() / "solver.lock"
        assert json.loads((slot / "owner.json").read_text())["job"] == "job"
    finally:
        _release_solver_slot(slot)
    assert not slot.exists()


@pytest.mark.parametrize("frozen, installed", [(False, False), (True, False), (False, True)])
def test_workspace_modes(monkeypatch, tmp_path, frozen, installed):
    monkeypatch.setattr(config, "FROZEN", frozen)
    monkeypatch.setattr(config, "INSTALLED", installed)
    monkeypatch.setattr(config, "STUDIO_ROOT", tmp_path / "source")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.delenv("NOVASTUDIO_WORKSPACE", raising=False)
    expected = tmp_path / "NovaSolverStudio" / "workspace" if frozen or installed else tmp_path / "source" / "workspace"
    assert config.workspace() == expected


@pytest.mark.parametrize("os_name", ["darwin", "linux"])
@pytest.mark.parametrize("name", ["ccx", "ccx_2.22", "ccx_2.21"])
def test_calculix_path(monkeypatch, tmp_path, os_name, name):
    monkeypatch.setattr(sys, "platform", os_name)
    monkeypatch.delenv("NOVASTUDIO_CCX", raising=False)
    binary = tmp_path / name
    binary.touch()
    monkeypatch.setattr(config.shutil, "which", lambda n: str(binary) if n == name else None)
    assert config.find_calculix() == str(binary)
    override = tmp_path / "chosen ccx"
    override.touch()
    monkeypatch.setenv("NOVASTUDIO_CCX", str(override))
    assert config.find_calculix() == str(override)


@pytest.mark.parametrize("folder", ["/opt/homebrew/bin", "/usr/local/bin"])
def test_calculix_homebrew(monkeypatch, folder):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.delenv("NOVASTUDIO_CCX", raising=False)
    monkeypatch.setattr(config.shutil, "which", lambda n: None)
    binary = Path(folder) / "ccx_2.22"
    monkeypatch.setattr(Path, "is_file", lambda self: self == binary)
    assert config.find_calculix() == str(binary)


def test_calculix_windows_pack(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(config, "STUDIO_ROOT", tmp_path)
    monkeypatch.delenv("NOVASTUDIO_CCX", raising=False)
    monkeypatch.setattr(config.shutil, "which", lambda n: None)
    binary = tmp_path / "solvers" / "calculix" / "ccx_static.exe"
    binary.parent.mkdir(parents=True)
    binary.touch()
    assert config.find_calculix() == str(binary)


def test_openfoam_mac_newest(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.delenv("NOVASTUDIO_OPENFOAM", raising=False)
    apps = [Path("/Applications/OpenFOAM-v2512.app"), Path("/Applications/OpenFOAM-v2606.app")]
    monkeypatch.setattr(Path, "glob", lambda self, pattern: iter(apps))
    monkeypatch.setattr(Path, "is_dir", lambda self: self in apps)
    monkeypatch.setattr(Path, "is_file", lambda self: self.name == "openfoam")
    foam = config.find_openfoam()
    assert foam["root"] == str(apps[1]) and foam["version"] == "v2606"
    assert config.engines()["openfoam"]["available"]  # no MS-MPI on POSIX


def test_openfoam_mac_path_and_override(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.delenv("NOVASTUDIO_OPENFOAM", raising=False)
    monkeypatch.setattr(Path, "glob", lambda self, pattern: iter(()))
    monkeypatch.setattr(config.shutil, "which", lambda n: "/opt/homebrew/bin/openfoam" if n == "openfoam" else None)
    assert config.find_openfoam()["launcher"] == "/opt/homebrew/bin/openfoam"
    app = tmp_path / "My OpenFOAM-v2606.app"
    launcher = app / "Contents" / "Resources" / "etc" / "openfoam"
    launcher.parent.mkdir(parents=True)
    launcher.touch()
    monkeypatch.setenv("NOVASTUDIO_OPENFOAM", str(app))
    assert config.find_openfoam()["launcher"] == str(launcher)


@pytest.mark.parametrize("override", ["WM_PROJECT_DIR", "NOVASTUDIO_OPENFOAM"])
def test_openfoam_linux_override(monkeypatch, tmp_path, override):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("NOVASTUDIO_OPENFOAM", raising=False)
    monkeypatch.delenv("WM_PROJECT_DIR", raising=False)
    project = tmp_path / "openfoam2606"
    bashrc = project / "etc" / "bashrc"
    bashrc.parent.mkdir(parents=True)
    bashrc.touch()
    monkeypatch.setenv(override, str(project))
    assert config.find_openfoam()["bashrc"] == str(bashrc)
    assert config.engines()["openfoam"]["available"]


def test_openfoam_linux_packages(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    for name in ("NOVASTUDIO_OPENFOAM", "WM_PROJECT_DIR"):
        monkeypatch.delenv(name, raising=False)
    projects = [tmp_path / "openfoam2512", tmp_path / "openfoam2606"]
    for p in projects:
        (p / "etc").mkdir(parents=True)
        (p / "etc" / "bashrc").touch()
    monkeypatch.setattr(Path, "glob", lambda self, pattern: iter(projects))
    assert config.find_openfoam()["root"] == str(projects[-1])


def test_openfoam_windows_and_msmpi(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    # shutil.which takes its Windows code path (it needs _winapi) once sys.platform says win32, so on a Linux/macOS
    # runner it must be faked; the solver lookup is what is under test here
    monkeypatch.setattr(config.shutil, "which", lambda *a, **k: None)
    monkeypatch.setattr(config, "STUDIO_ROOT", tmp_path)
    root = tmp_path / "OpenFOAM"
    binary = root / "OpenFOAM-v2606" / "platforms" / "mingw" / "bin" / "blockMesh.exe"
    binary.parent.mkdir(parents=True)
    binary.touch()
    monkeypatch.setenv("NOVASTUDIO_OPENFOAM", str(root))
    foam = config.find_openfoam()
    assert foam["bin"] == str(binary.parent)
    assert not config.engines()["openfoam"]["available"]
    mpi = tmp_path / "msmpi"
    mpi.mkdir()
    (mpi / "msmpi.dll").touch()
    assert config.engines()["openfoam"]["available"]
    assert config.openfoam_env(foam)["PATH"].split(config.os.pathsep)[0] == str(mpi)


@pytest.mark.parametrize("os_name", ["win32", "darwin", "linux"])
def test_foam_argv(monkeypatch, os_name):
    monkeypatch.setattr(sys, "platform", os_name)
    foam = {"bin": "/foam/bin", "launcher": "/Applications/OpenFOAM-v2606.app/Contents/Resources/etc/openfoam",
            "bashrc": "/usr/lib/openfoam/with space/etc/bashrc"}
    args = ["-case", "/解析 dir/it's here; $(whoami)", "-overwrite"]
    argv = config.foam_argv(foam, "blockMesh", args)
    if os_name == "win32":
        assert argv == [str(Path(foam["bin"]) / "blockMesh.exe"), *args]
    elif os_name == "darwin":
        assert argv[:2] == [foam["launcher"], "-c"]
        assert shlex.split(argv[2]) == ["blockMesh", *args]
        assert config.openfoam_env(foam) == dict(config.os.environ)
    else:
        assert argv[:2] == ["bash", "-c"]
        assert shlex.split(argv[2]) == ["source", foam["bashrc"], "&&", "blockMesh", *args]
        assert config.openfoam_env(foam) == dict(config.os.environ)


def test_foam_argv_simple_space(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert config.foam_argv({"launcher": "/app/etc/openfoam"}, "blockMesh", ["-case", "/dir with space"]) == [
        "/app/etc/openfoam", "-c", "blockMesh -case '/dir with space'"]


@pytest.mark.parametrize("os_name, expected", [("win32", 6000), ("darwin", 7000), ("linux", 3000)])
def test_committable_memory(monkeypatch, os_name, expected):
    monkeypatch.setattr(sys, "platform", os_name)
    monkeypatch.setattr(psutil, "virtual_memory", lambda: SimpleNamespace(available=2000, total=10000))
    monkeypatch.setattr(psutil, "swap_memory", lambda: SimpleNamespace(free=1000))
    def memory_status(pointer):
        pointer._obj.avail_page = 6000
        return 1
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(kernel32=SimpleNamespace(GlobalMemoryStatusEx=memory_status)), raising=False)
    assert fem_tet10.committable_bytes() == expected > 0


@pytest.mark.parametrize("os_name", ["darwin", "linux"])
@pytest.mark.parametrize("lang", ["ja", "en", "zh"])
def test_install_messages(monkeypatch, os_name, lang):
    monkeypatch.setattr(sys, "platform", os_name)
    text = commands._solver_install(lang)
    assert "calculix-ccx" in text["calculix"]
    assert ("brew install gerlero/openfoam/openfoam" if os_name == "darwin" else "openfoam.com") in text["openfoam"]
    assert not any(s.startswith("install.") for s in text.values())
    if lang in ("ja", "zh"):
        assert all(any(ord(c) > 127 for c in s) for s in text.values())


def test_installed_mcp_command(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "INSTALLED", True)
    monkeypatch.setenv("NOVASTUDIO_WORKSPACE", str(tmp_path))
    # second opinion (0.4.1) #2: an installed package starts with its own interpreter; uvx is only an alternative,
    # offered when it exists (uv is not a dependency)
    monkeypatch.setattr(commands.shutil, "which", lambda name: None)
    check = commands.environment_check("en")
    assert check["mcp_command"] == {"command": sys.executable, "args": ["-m", "novastudio", "mcp"],
                                    "env": {"NOVASTUDIO_WORKSPACE": str(tmp_path)}}
    assert check["mcp_command_alternatives"] == []
    monkeypatch.setattr(commands.shutil, "which", lambda name: "/usr/local/bin/uvx" if name == "uvx" else None)
    assert commands.environment_check("en")["mcp_command_alternatives"] == [{"command": "uvx", "args": ["novasolver-studio", "mcp"]}]


def test_openfoam_scratch_path_has_no_spaces(monkeypatch, tmp_path):
    """second opinion (0.4.1) #1: POSIX OpenFOAM strips spaces from -case, and the macOS data dir is
    'Application Support'; a non-ASCII or spaced job folder must solve in a scratch folder without either."""
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(config.Path, "home", lambda: tmp_path / "home")
    for jd in (tmp_path / "解析" / "job1", tmp_path / "with space" / "job2"):
        jd.mkdir(parents=True)
        wd = config.foam_workdir(jd)
        assert str(wd).isascii() and " " not in str(wd), wd
        assert (jd / "of_location.txt").read_text(encoding="utf-8") == str(wd)
    plain = tmp_path / "plain" / "job3"
    plain.mkdir(parents=True)
    if str(plain).isascii() and " " not in str(plain):
        assert config.foam_workdir(plain) == plain / "of"


def test_package_frontend_resource():
    package = importlib.resources.files("novastudio")
    assert package.joinpath("i18n", "ja.json").is_file()
    index = package.joinpath("frontend_dist", "index.html")
    if index.is_file():
        assert "/assets/" in index.read_text(encoding="utf-8")
    else:
        assert not (config.PACKAGE_ROOT / "frontend_dist" / "index.html").exists()


@pytest.mark.parametrize("bundled", [False, True])
def test_server_frontend_fallback(monkeypatch, tmp_path, bundled):
    monkeypatch.setattr(config, "RESOURCES", tmp_path / "source")
    package = tmp_path / "package"
    monkeypatch.setattr(config, "PACKAGE_ROOT", package)
    if bundled:
        dist = package / "frontend_dist"
        (dist / "assets").mkdir(parents=True)
        (dist / "index.html").write_text("wheel frontend", encoding="utf-8")
        (dist / "assets" / "app.js").write_text("// asset", encoding="utf-8")
    # A separate module instance avoids disturbing the routes used by other tests.
    spec = importlib.util.spec_from_file_location("novastudio._test_api", Path(commands.__file__).with_name("api.py"))
    api = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(api)
    client = TestClient(api.app, base_url="http://localhost")
    assert client.get("/api/openapi.json").status_code == 200
    assert client.get("/").status_code == (200 if bundled else 404)
    if bundled:
        assert client.get("/").text == "wheel frontend"
        assert client.get("/assets/app.js").text == "// asset"


def test_platform_literal_audit():
    root = Path(config.__file__).parent
    allowed = json.loads(Path(__file__).with_name("platform_literal_allowlist.json").read_text(encoding="utf-8"))
    found = set()
    for file in root.rglob("*.py"):
        if file.name == "osdirs.py":
            continue
        for line, text in enumerate(file.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r'\.exe["\']|LOCALAPPDATA', text):
                key = f"{file.relative_to(root).as_posix()}:{line}"
                assert allowed.get(key), f"unguarded platform literal: {key}: {text}"
                found.add(key)
    assert found == set(allowed), "update stale allow-list line numbers"
