"""Download the solver binaries bundled with the Windows release from their original publishers and check them
against pinned hashes: CalculiX 2.23 Windows build (dhondt.de, GPL-2.0) and the MS-MPI 10.1 runtime (conda-forge
build of github.com/microsoft/Microsoft-MPI, MIT). Used by .github/workflows/release-windows.yml.

  python tools/fetch_build_deps.py <calculix-dir> <msmpi-dir>
"""
from __future__ import annotations

import hashlib
import io
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

CCX_ZIP = ("http://www.dhondt.de/calculix_2.23_4win.zip",
           "87fc4e1721df37370ec67d0a244bb14f9bf804b0a95df49e2ae7369d30ec72e8")
CCX_EXE = "e18360eb32a5cd48f91a212c57069212cd8e27d2f798a599a78106bd0b3ecc1f"
MSMPI_CONDA = ("https://conda.anaconda.org/conda-forge/win-64/msmpi-10.1.1-h571195b_8.conda",
               "1805d513b0e54b728842aca820b60d717d102f45d2bdd7396a112c3a8420220c")
MSMPI_DLL = "534f869ea0f1f7e81ebd2343351c8eff1fb47026e35e54460fdae148bddee5b8"
MSMPI_FILES = ("msmpi.dll", "mpiexec.exe", "smpd.exe", "msmpiLaunchSvc.exe")


def get(url: str, sha: str) -> bytes:
    with urllib.request.urlopen(url, timeout=300) as r:
        data = r.read()
    got = hashlib.sha256(data).hexdigest()
    if got != sha:
        sys.exit(f"hash mismatch for {url}: {got}")
    return data


def main(ccx_dir: Path, mpi_dir: Path) -> None:
    ccx_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(get(*CCX_ZIP))) as z:
        exe = z.read("calculix_2.23_4win/ccx_static.exe")
    assert hashlib.sha256(exe).hexdigest() == CCX_EXE
    (ccx_dir / "ccx_static.exe").write_bytes(exe)

    import zstandard
    mpi_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(get(*MSMPI_CONDA))) as z:
        pkg = next(n for n in z.namelist() if n.startswith("pkg-") and n.endswith(".tar.zst"))
        tar_bytes = zstandard.ZstdDecompressor().stream_reader(io.BytesIO(z.read(pkg))).read()
    with tarfile.open(fileobj=io.BytesIO(tar_bytes)) as t:
        members = {Path(m.name).name: m for m in t.getmembers() if m.isfile()}
        for name in MSMPI_FILES:
            if name in members:
                (mpi_dir / name).write_bytes(t.extractfile(members[name]).read())
        lic = next((m for n, m in members.items() if n.lower().startswith("license")), None)
        if lic:
            (mpi_dir / "LICENSE-msmpi.txt").write_bytes(t.extractfile(lic).read())
    assert hashlib.sha256((mpi_dir / "msmpi.dll").read_bytes()).hexdigest() == MSMPI_DLL, "msmpi.dll differs"
    (mpi_dir / "SOURCE.txt").write_text(f"conda-forge {MSMPI_CONDA[0].rsplit('/', 1)[1]} (sha256 {MSMPI_CONDA[1]}), "
                                        "built from github.com/microsoft/Microsoft-MPI, MIT\n", encoding="utf-8")
    print("ok", sorted(p.name for p in mpi_dir.iterdir()))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
