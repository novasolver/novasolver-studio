"""Write the signed update notice for a release:  python tools/sign_latest.py <version> [out.json]

Reads release/NovaSolverStudio-<v>-win64.zip(.sha256), dist-py/<wheel> and release/RELEASE_NOTES_v<v>.md; signs the
payload with the Ed25519 key named by NOVASTUDIO_SIGNING_KEY (a PEM file kept outside every repository). The app
refuses a latest.json whose signature does not match the public key built into it (updates.PUBLIC_KEY).
Publish the output as https://novasolver.jp/studio/latest.json and as latest.json in the repository root.
"""
from __future__ import annotations

import base64
import datetime
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from novastudio.updates import PUBLIC_KEY, _valid_latest, canonical  # noqa: E402


def notes(v: str) -> dict:
    """First sentence of each bullet of the English, Japanese and (if present) Chinese sections, in that order,
    separated by '---'. A missing Chinese section falls back to English."""
    text = (ROOT / "release" / f"RELEASE_NOTES_v{v}.md").read_text(encoding="utf-8")
    parts = text.split("\n---\n")

    def summary(part, cjk):
        lines = [l.strip()[1:].strip() for l in part.splitlines() if l.strip().startswith(("- ", "* "))]
        # CJK sentences end at '。'; English at '. ' (so novasolver.jp stays whole)
        first = (lambda l: l.split("。")[0] + "。") if cjk else (lambda l: l.split(". ")[0].rstrip(".") + ".")
        return "\n".join(("・" if cjk else "• ") + first(l) for l in lines[:5])
    en = summary(parts[0], False)
    ja = summary(parts[1], True) if len(parts) > 1 else en
    zh = summary(parts[2], True) if len(parts) > 2 else en
    return {"en": en, "ja": ja, "zh": zh}


def main():
    from cryptography.hazmat.primitives import serialization
    v = sys.argv[1]
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "release" / f"latest-{v}.json"
    key = serialization.load_pem_private_key(Path(os.environ["NOVASTUDIO_SIGNING_KEY"]).read_bytes(), None)
    pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    assert base64.b64encode(pub).decode() == PUBLIC_KEY, "this key does not match the public key in updates.py"
    zip_name = f"NovaSolverStudio-{v}-win64.zip"
    zpath = ROOT / "release" / zip_name
    sha = (zpath.parent / (zip_name + ".sha256")).read_text().split()[0]
    wheel = f"novasolver_studio-{v}-py3-none-any.whl"
    gh = f"https://github.com/novasolver/novasolver-studio/releases/download/v{v}/"
    payload = {
        "version": v, "date": datetime.date.today().isoformat(), "notes": notes(v),
        "page": {"ja": "https://novasolver.jp/studio/", "en": "https://novasolver.jp/en/studio/",
                 "zh": "https://novasolver.jp/zh/studio/"},
        "windows_zip": {"urls": [gh + zip_name, f"https://novasolver.jp/dl/studio/{zip_name}"],
                        "sha256": sha, "size": zpath.stat().st_size},
        "python": {"command": f"uvx --from {gh}{wheel} novasolver-studio"},
    }
    assert _valid_latest(payload)
    sig = base64.b64encode(key.sign(canonical(payload))).decode()
    out.write_text(json.dumps({"payload": payload, "signature": sig}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
