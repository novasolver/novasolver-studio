"""Markdown table of a suite result, for the CI run page and for anyone checking the claimed accuracy.

    python validation/ci_summary.py validation/results/ci.json [--compare validation/results/0.7.1.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def rows(doc: dict) -> list[dict]:
    out = []
    for c in doc["cases"]:
        for r in c.get("rows") or [{}]:
            out.append({"id": c["id"], "status": c["status"], **r})
    return out


def table(doc: dict, prev: dict | None = None) -> str:
    old = {(r["id"], r.get("quantity")): r for r in rows(prev)} if prev else {}
    n = {s: sum(c["status"] == s for c in doc["cases"]) for s in ("pass", "fail", "error", "no-reference")}
    lines = [f"### Accuracy check: {n['pass']} pass, {n['fail']} fail, {n['error']} error, {n['no-reference']} without a reference",
             "", f"Studio {doc['version']}, {doc['machine']['os']}, {doc['date']}" + (", quick set" if doc.get("quick") else ""), ""]
    lines += ["| Case | Quantity | Computed | Reference | Error | Allowed | Moved since last release | Result |", "|---|---|---|---|---|---|---|---|"]
    for r in rows(doc):
        if "computed" not in r:
            lines.append(f"| {r['id']} | | | | | | | {r['status']} |")
            continue
        was = old.get((r["id"], r.get("quantity")), {}).get("computed")
        moved = f"{(r['computed'] - was) / abs(was) * 100:+.3f} %" if was and r["computed"] is not None else ""
        err = f"{r['error_pct']:+.3f} %" if r.get("error_pct") is not None else f"{r.get('error_abs', 0):+.4g} {r.get('unit', '')}"
        tol = f"{r['tol_pct']} %" if r.get("tol_pct") is not None else f"{r.get('tol_abs')} {r.get('unit', '')}"
        lines.append(f"| {r['id']} | {r.get('quantity') or ''} | {r['computed']:.5g} {r.get('unit') or ''} | {r['reference']:.5g} | {err} | {tol} | {moved} | "
                     f"{'pass' if r['pass'] else 'FAIL'} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("result")
    ap.add_argument("--compare")
    a = ap.parse_args()
    doc = json.loads(Path(a.result).read_text(encoding="utf-8"))
    prev = json.loads(Path(a.compare).read_text(encoding="utf-8")) if a.compare else None
    sys.stdout.reconfigure(encoding="utf-8")
    print(table(doc, prev))


if __name__ == "__main__":
    main()
