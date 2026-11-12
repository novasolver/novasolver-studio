"""Write the signed update notice for a release:  python tools/sign_latest.py <version> [out.json]

Reads release/NovaSolverStudio-<v>-win64.zip(.sha256), dist-py/<wheel> and docs/RELEASE_NOTES_v<v>.md
(or the legacy release/ location); validates the artifacts before reading the signing key, then signs the
payload with the Ed25519 key named by NOVASTUDIO_SIGNING_KEY (a PEM file kept outside every repository). The app
refuses a latest.json whose signature does not match the public key built into it (updates.PUBLIC_KEY).
Publish the output as https://novasolver.jp/studio/latest.json and as latest.json in the repository root.
"""
from __future__ import annotations

import base64
import datetime
import hashlib
import json
import os
import re
import sys
import zipfile
from email.parser import BytesParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _summary(part: str, cjk: bool) -> str:
    bullets = []
    continuing = False
    for line in part.splitlines():
        stripped = line.strip()
        if stripped.startswith(("- ", "* ")):
            bullets.append(stripped[2:].strip())
            continuing = True
        elif continuing and stripped and line[:1].isspace():
            bullets[-1] += " " + stripped
        else:
            continuing = False
    # Join wrapped bullets before extracting their first sentence. Keep domains and decimals intact.
    if cjk:
        return "\n".join("・" + b.split("。")[0] + "。" for b in bullets[:5] if b)
    return "\n".join("• " + re.split(r"\.\s+", b)[0].rstrip(".") + "." for b in bullets[:5] if b)


def parse_notes(text: str) -> dict[str, str]:
    """Summarize language headings, or legacy English/Japanese/Chinese '---' sections.

    Absent translations retain the legacy English fallback; present but empty sections are errors.
    """
    text = text.replace("\r\n", "\n")
    languages = {"english": "en", "日本語": "ja", "中文": "zh"}
    sections = {}
    current = None
    for line in text.splitlines():
        heading = re.fullmatch(r"\s*##\s*([^#].*?)(?:\s+#+)?\s*", line)
        if heading:
            current = languages.get(heading[1].strip().lower())
            if current:
                if current in sections:
                    raise ValueError(f"Duplicate release notes section: {current}")
                sections[current] = []
        elif current:
            sections[current].append(line)
    if sections:
        parts = {lang: "\n".join(lines) for lang, lines in sections.items()}
    else:
        legacy = re.split(r"(?m)^[ \t]*---[ \t]*$", text)
        if len(legacy) > 3:
            raise ValueError("Release notes need language headings or at most three legacy sections")
        parts = dict(zip(("en", "ja", "zh"), legacy))
    summaries = {lang: _summary(part, lang != "en") for lang, part in parts.items()}
    if not summaries.get("en"):
        raise ValueError("Release notes require a non-empty English bullet section")
    for lang, summary in summaries.items():
        if not summary:
            raise ValueError(f"Release notes section has no bullets: {lang}")
    return {lang: summaries.get(lang, summaries["en"]) for lang in ("en", "ja", "zh")}


def notes(v: str, root: Path | None = None) -> dict[str, str]:
    root = ROOT if root is None else root
    candidates = [root / directory / f"RELEASE_NOTES_v{v}.md" for directory in ("docs", "release")]
    for path in candidates:
        if path.is_file():
            try:
                return parse_notes(path.read_text(encoding="utf-8-sig"))
            except ValueError as exc:
                raise ValueError(f"Invalid release notes {path}: {exc}") from exc
    raise FileNotFoundError("Missing release notes; expected " + " or ".join(map(str, candidates)))


def verified_zip(path: Path) -> tuple[str, int]:
    """Hash the actual archive and require its SHA-256 sidecar to agree."""
    sidecar = path.with_name(path.name + ".sha256")
    fields = sidecar.read_text(encoding="utf-8-sig").split()
    if not fields or not re.fullmatch(r"[0-9a-fA-F]{64}", fields[0]):
        raise ValueError(f"Invalid SHA-256 sidecar: {sidecar}")
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as archive:
        for chunk in iter(lambda: archive.read(1 << 20), b""):
            digest.update(chunk)
            size += len(chunk)
    actual = digest.hexdigest()
    if actual != fields[0].lower():
        raise ValueError(f"SHA-256 mismatch for {path}: sidecar {fields[0]}, actual {actual}")
    return actual, size


def built_wheel(v: str, root: Path) -> Path:
    """Require the built universal wheel and verify its embedded package identity."""
    path = root / "dist-py" / f"novasolver_studio-{v}-py3-none-any.whl"
    if not path.is_file():
        raise FileNotFoundError(f"Missing built wheel: {path}")
    try:
        with zipfile.ZipFile(path) as wheel:
            metadata = [name for name in wheel.namelist()
                        if re.fullmatch(r"[^/]+\.dist-info/METADATA", name)]
            if len(metadata) != 1:
                raise ValueError(f"Wheel must contain exactly one .dist-info/METADATA: {path}")
            info = BytesParser().parsebytes(wheel.read(metadata[0]), headersonly=True)
    except zipfile.BadZipFile as exc:
        raise ValueError(f"Invalid wheel archive: {path}") from exc
    if info.get_all("Version") != [v]:
        raise ValueError(f"Wheel metadata version mismatch for {path}: expected {v}, got {info.get_all('Version')}")
    names = info.get_all("Name", [])
    if len(names) != 1 or re.sub(r"[-_.]+", "-", names[0]).lower() != "novasolver-studio":
        raise ValueError(f"Wheel metadata name mismatch for {path}: {names}")
    return path


def build_payload(v: str, root: Path | None = None, *, date: str | None = None) -> dict:
    """Prepare an unsigned notice using local artifacts only; never access a key or the network."""
    if not re.fullmatch(r"[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}", v):
        raise ValueError(f"Invalid release version (expected x.y.z): {v}")
    root = ROOT if root is None else root
    release_notes = notes(v, root)
    zip_name = f"NovaSolverStudio-{v}-win64.zip"
    sha, size = verified_zip(root / "release" / zip_name)
    wheel = built_wheel(v, root).name
    gh = f"https://github.com/novasolver/novasolver-studio/releases/download/v{v}/"
    return {
        "version": v, "date": date or datetime.date.today().isoformat(), "notes": release_notes,
        "page": {"ja": "https://novasolver.jp/studio/", "en": "https://novasolver.jp/en/studio/",
                 "zh": "https://novasolver.jp/zh/studio/"},
        "windows_zip": {"urls": [gh + zip_name, f"https://novasolver.jp/dl/studio/{zip_name}"],
                        "sha256": sha, "size": size},
        "python": {"command": f"uvx --from {gh}{wheel} novasolver-studio"},
    }


def main():
    if len(sys.argv) not in (2, 3):
        raise SystemExit("Usage: python tools/sign_latest.py <version> [out.json]")
    v = sys.argv[1]
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "release" / f"latest-{v}.json"
    try:
        payload = build_payload(v)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"Release validation failed: {exc}") from exc

    sys.path.insert(0, str(ROOT / "backend"))
    from novastudio.updates import PUBLIC_KEY, _valid_latest, canonical
    from cryptography.hazmat.primitives import serialization

    if not _valid_latest(payload):
        raise ValueError("Invalid release manifest payload")
    key = serialization.load_pem_private_key(Path(os.environ["NOVASTUDIO_SIGNING_KEY"]).read_bytes(), None)
    pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    if base64.b64encode(pub).decode() != PUBLIC_KEY:
        raise ValueError("this key does not match the public key in updates.py")
    sig = base64.b64encode(key.sign(canonical(payload))).decode()
    out.write_text(json.dumps({"payload": payload, "signature": sig}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
