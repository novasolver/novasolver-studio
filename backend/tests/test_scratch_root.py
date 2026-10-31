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