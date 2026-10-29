"""Solve every built-in verification template once and package the results as solved examples.

    python tools/build_examples.py [--only a,b] [--jobs N] [--allow-missing]

Writes release/examples/<version>/: example-<template>.nscase, examples.json (the index the app reads) and
README.md (the table for the GitHub release page). Runs in a private workspace and data folder, never the user's.
A template whose result does not match its reference is not published.
TODO: examples for OpenFOAM/CalculiX-only templates (channel, sphere-drag) once a build machine has both solvers.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
LANGS = ("ja", "en", "zh")


def eligible() -> list[str]:
    from novastudio.templates import TEMPLATES
    return [k for k, tp in TEMPLATES.items()
            if (tp.get("case", {}).get("reference") or {}).get("kind") not in (None, "none")
            and any(str(e).startswith("builtin") for e in tp.get("engines", []))]


def solve(tid: str) -> dict:
    from novastudio import commands as C, jobs, results, store, templates
    t0 = time.time()
    cid = C.create_case(tid, lang="en")["case"]["case_id"]
    job = C.run_simulation(cid, wait_s=1, lang="en")["job"]
    j = jobs.wait(job["job_id"], 3600)
    out = {"template": tid, "case_id": cid, "state": j["state"], "solve_s": round(time.time() - t0, 1)}
    if j["state"] != "done":
        return {**out, "ok": False, "reason": f"job {j['state']}: {C.job_status(job['job_id'], 'en').get('message', '')}"}
    case = store.load(cid)
    pls = {lang: results.payload(case, lang) for lang in LANGS}
    ver = pls["en"]["verification"]
    if not ver or not ver["pass"]:
        return {**out, "ok": False, "reason": "no reference" if not ver else f"error {ver['error_pct']:+.3f}% > {ver['tolerance_pct']}%"}
    summary = {lang: {x["id"]: x for x in templates.summary(lang)} for lang in LANGS}
    stats = next((c for c in pls["en"]["cards"] if c["key"] == "nodes"), {}), next((c for c in pls["en"]["cards"] if c["key"] == "elements"), {})
    return {**out, "ok": True, "verification": ver,
            "title": {lang: summary[lang][tid]["title"] for lang in LANGS},
            "description": {lang: summary[lang][tid].get("description", "") for lang in LANGS},
            "label": {lang: pls[lang]["verification"]["label"] for lang in LANGS},
            "physics": summary["en"][tid]["physics"],
            "mesh": {"nodes": int(stats[0].get("value", 0)), "elements": int(stats[1].get("value", 0))}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--allow-missing", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "release" / "examples"))
    args = ap.parse_args()
    scratch = Path(tempfile.mkdtemp(prefix="nss_examples_"))
    os.environ["NOVASTUDIO_WORKSPACE"] = str(scratch / "workspace")
    os.environ["LOCALAPPDATA"] = str(scratch / "data")
    from novastudio import __version__, archive, commands as C
    names = [n for n in args.only.split(",") if n] or eligible()
    unknown = sorted(set(names) - set(eligible()))
    if unknown:
        print("not eligible:", ", ".join(unknown)); return 2
    out = Path(args.out) / __version__
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    with cf.ThreadPoolExecutor(max(1, args.jobs)) as pool:
        runs = list(pool.map(solve, names))
    index, report = [], []
    for r in runs:
        report.append(f"{r['template']:24s} {'PASS' if r['ok'] else 'FAIL'} {r['solve_s']:7.1f} s  " +
                      (f"{r['verification']['error_pct']:+.3f}%" if r["ok"] else r["reason"]))
        if not r["ok"]:
            continue
        v = r["verification"]
        src = archive.export_case(r["case_id"], True, {k: v[k] for k in ("label", "reference", "computed", "unit", "error_pct", "pass")})
        name = r["template"]
        target = out / f"example-{name}.nscase"
        shutil.copyfile(src, target)
        data = target.read_bytes()
        index.append({"name": name, "template": name, "physics": r["physics"], "title": r["title"],
                      "description": r["description"], "file": target.name, "size": len(data),
                      "sha256": hashlib.sha256(data).hexdigest(),
                      "reference": {"label": r["label"], "value": v["reference"], "unit": v["unit"]},
                      "result": {"value": v["computed"], "unit": v["unit"]}, "error_pct": v["error_pct"],
                      "tolerance_pct": v["tolerance_pct"], "mesh": r["mesh"], "solve_s": r["solve_s"]})
    (out / "examples.json").write_text(json.dumps({"format": 1, "studio_version": __version__, "examples": index},
                                                  ensure_ascii=False, indent=1), encoding="utf-8")
    g = lambda x, n=4: f"{x:.{n}g}"
    rows = "\n".join(f"| {e['title']['en']} | {g(e['reference']['value'])} {e['reference']['unit']} | "
                     f"{g(e['result']['value'])} {e['result']['unit']} | {e['error_pct']:+.2f}% | {e['size'] / 1e6:.1f} MB |" for e in index)
    rows_ja = "\n".join(f"| {e['title']['ja']} | {g(e['reference']['value'])} {e['reference']['unit']} | "
                        f"{g(e['result']['value'])} {e['result']['unit']} | {e['error_pct']:+.2f}% |" for e in index)
    total = sum(e["size"] for e in index) / 1e6
    (out / "README.md").write_text(f"""# Solved examples, NovaSolver Studio {__version__}

Each file is a verification case solved by Studio's built-in solver, with its result. Open it with
**Open case file** in Studio, or from an AI assistant with `open_example`. Studio downloads these by itself from the
Start screen ("Solved examples"); you only need them by hand when offline. {len(index)} examples, {total:.1f} MB.

| Case | Reference | Studio | Error | Size |
|---|---|---|---|---|
{rows}

## 解析済みの例

Studio 内蔵ソルバーで解いた検証ケースを、結果ごと収めたファイルです。Studio の「ケースファイルを開く」か、AI アシスタントの
`open_example` で開けます。通常はスタート画面の「解析済みの例」から自動でダウンロードされます。

| ケース | 理論値 | Studio | 誤差 |
|---|---|---|---|
{rows_ja}
""", encoding="utf-8")
    (out / "build_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report))
    print(f"{len(index)}/{len(runs)} published, {total:.1f} MB -> {out}")
    shutil.rmtree(scratch, ignore_errors=True)
    return 0 if len(index) == len(runs) or args.allow_missing else 1


if __name__ == "__main__":
    sys.exit(main())
