"""OpenFOAM scratch folder on Windows: a non-ASCII user name must not put the case on a non-ASCII path."""
import sys

import pytest

from novastudio import config


@pytest.mark.skipif(sys.platform != "win32", reason="Windows short names")
def test_non_ascii_data_folder_gets_an_ascii_scratch_root(tmp_path, monkeypatch):
    home = tmp_path / "田中 太郎"
    monkeypatch.setattr(config, "data_dir", lambda: home / "NovaSolverStudio")
    jd = tmp_path / "ジョブ" / "j1"
    jd.mkdir(parents=True)
    wd = config.foam_workdir(jd)
    assert str(wd).isascii() and " " not in str(wd)
    assert (jd / "of_location.txt").read_text(encoding="utf-8") == str(wd)


def test_scratch_runs_are_removed_with_their_case_or_when_orphaned(tmp_path, monkeypatch):
    import os
    import time
    root = tmp_path / "scratch"
    monkeypatch.setattr(config, "_private_runs", lambda: [root / "runs"])
    monkeypatch.setenv("NOVASTUDIO_WORKSPACE", str(tmp_path / "ws"))

    def run(case, job):
        jd = tmp_path / "ws" / "cases" / case / "run" / job
        jd.mkdir(parents=True)
        wd = root / "runs" / f"{job}_x" / "of"
        wd.mkdir(parents=True)
        (wd / "U").write_text("x")
        (jd / "of_location.txt").write_text(str(wd), encoding="utf-8")
        return jd, wd.parent

    jd1, run1 = run("c_a", "coarse")
    _, run2 = run("c_b", "normal")
    orphan = root / "runs" / "fine_y"
    (orphan / "of").mkdir(parents=True)
    outside = tmp_path / "elsewhere" / "of"                       # a pointer outside <root>/runs is never followed
    outside.mkdir(parents=True)
    (jd1.parent / "x").mkdir()
    (jd1.parent / "x" / "of_location.txt").write_text(str(outside), encoding="utf-8")

    # a pointer that climbs out of runs/ (e.g. from an imported case file) is never followed
    (root / "runs").mkdir(parents=True, exist_ok=True)
    (jd1.parent / "y").mkdir()
    (jd1.parent / "y" / "of_location.txt").write_text(str(root / "runs" / ".." / "of"), encoding="utf-8")
    config.remove_scratch(tmp_path / "ws" / "cases" / "c_a")
    assert root.exists()
    assert not run1.exists() and run2.exists() and outside.exists()

    assert config.sweep_scratch() == 0                            # the orphan is new: another workspace may use it
    old = time.time() - 30 * 86400
    for p in [orphan, orphan / "of", run2, run2 / "of", run2 / "of" / "U"]:
        os.utime(p, (old, old))
    assert config.sweep_scratch() == 1                            # run2 is still referenced by c_b
    assert not orphan.exists() and run2.exists()
