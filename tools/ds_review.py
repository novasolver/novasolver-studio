"""Cheap first-pass review with DeepSeek. Claude (or Codex) then verifies every finding; nothing here is trusted as is.

    python tools/ds_review.py diff v0.6.3            # review git diff v0.6.3..HEAD (backend, frontend/src, tests)
    python tools/ds_review.py files backend/novastudio/updates.py ...
    python tools/ds_review.py i18n                   # ja/en/zh strings: meaning drift, untranslated text, placeholders

Writes reviews/<date>_<label>.deepseek.md and .json. The key comes from DEEPSEEK_API_KEY or the file named by
DEEPSEEK_KEY_FILE (default E:\\_SECRETS\\deepseek.txt); it is never printed or written anywhere.
Only send code that is public anyway (this repository is). Inputs are scrubbed of e-mail addresses, home paths and
anything that looks like a key before they leave the machine.
"""
from __future__ import annotations

import concurrent.futures as cf
import datetime
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.deepseek.com/chat/completions"
CHUNK = 48_000          # characters per request (~12k tokens of code; leaves room for the answer)
WORKERS = 4

SCRUB = [
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "sk-REDACTED"),
    (re.compile(r"ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"), "TOKEN-REDACTED"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S), "PRIVATE-KEY-REDACTED"),
    # an address starts with a letter or digit: "+@mcp.tool" in a diff line is a decorator, not an e-mail address
    (re.compile(r"(?<![\w.+-])[A-Za-z0-9][\w.+-]*@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"), "user@example.com"),
    (re.compile(r"(?i)[A-Z]:\\Users\\[^\\\s\"']+"), r"C:\\Users\\USER"),
    (re.compile(r"/home/[^/\s\"']+|/Users/[^/\s\"']+"), "/home/USER"),
]


def scrub(text: str) -> str:
    for pat, rep in SCRUB:
        text = pat.sub(rep, text)
    return text


def api_key() -> str:
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        f = Path(os.environ.get("DEEPSEEK_KEY_FILE", r"E:\_SECRETS\deepseek.txt"))
        key = f.read_text(encoding="utf-8-sig").strip() if f.exists() else ""
    if not key:
        sys.exit("no DeepSeek key: set DEEPSEEK_API_KEY or DEEPSEEK_KEY_FILE")
    return key


def ask(system: str, user: str, model: str, max_tokens: int = 8000) -> tuple[dict, dict]:
    """One JSON-mode call. Returns (parsed answer, usage). Raises on HTTP errors after three tries."""
    body = json.dumps({"model": model, "temperature": 0, "max_tokens": max_tokens,
                       "response_format": {"type": "json_object"},
                       "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}).encode()
    for attempt in range(3):
        req = urllib.request.Request(API, body, {"Content-Type": "application/json",
                                                 "Authorization": "Bearer " + api_key()})
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                doc = json.load(r)
            break
        except (urllib.error.URLError, TimeoutError) as e:
            code = getattr(e, "code", None)
            if code in (400, 401, 402, 403) or attempt == 2:
                raise RuntimeError(f"DeepSeek HTTP {code or e}") from None   # never echo the request (it has the key)
            time.sleep(5 * (attempt + 1))
    choice = doc["choices"][0]
    text = choice["message"]["content"] or "{}"
    try:
        out = json.loads(text)
    except json.JSONDecodeError:
        out = {"findings": [], "error": "answer was not JSON"}
    if choice.get("finish_reason") == "length":
        out["truncated"] = True
    return out, doc.get("usage", {})


REVIEW_SYSTEM = """You review code of NovaSolver Studio: a desktop CAE app (Python FastAPI + MCP backend, a built-in tet10 FEM,
CalculiX and OpenFOAM drivers, gmsh meshing; React + three.js frontend; ja/en/zh UI). You get a diff or files.
Report only real defects: wrong results, crashes, data loss, security holes (path traversal, injection, unsafe
extraction, unverified downloads), races, resource leaks, Windows-specific breakage, wrong physics or units,
i18n keys missing in one language. No style, naming or "consider" remarks. If unsure, say so in "confidence".
Answer JSON: {"findings":[{"severity":"high|medium|low","file":"path","line":123,"summary":"one sentence",
"scenario":"concrete input -> wrong result","fix":"short suggestion","confidence":"high|medium|low"}]}.
Return {"findings":[]} when you find nothing. Line numbers refer to the new version of the file.
At most 12 findings, most severe first; keep every field under 300 characters."""

I18N_SYSTEM = """You check UI strings of a CAE desktop app in Japanese (ja, the master), English (en) and Chinese (zh, simplified).
You get rows key | ja | en | zh. Report only: a translation that says something different from ja (wrong meaning,
wrong number or unit, lost negation), text left in the wrong language, placeholders like {n} or {name} that differ,
and Chinese that a native engineer would find wrong or unnatural. Do not report harmless wording choices.
Answer JSON: {"findings":[{"severity":"high|medium|low","file":"i18n","line":0,"key":"the.key","lang":"en|zh",
"summary":"what is wrong","fix":"suggested text","confidence":"high|medium|low"}]}."""


def git(*args) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=True).stdout


def chunks_of(pieces: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Pack (name, text) pieces into requests of at most CHUNK characters; split a piece that is larger by lines."""
    out, cur, names = [], "", []
    for name, text in pieces:
        parts = [text]
        if len(text) > CHUNK:
            lines, parts, buf = text.splitlines(keepends=True), [], ""
            for ln in lines:
                if len(buf) + len(ln) > CHUNK and buf:
                    parts.append(buf)
                    buf = ""
                buf += ln
            parts.append(buf)
        for i, p in enumerate(parts):
            label = name if len(parts) == 1 else f"{name} (part {i + 1}/{len(parts)})"
            if len(cur) + len(p) > CHUNK and cur:
                out.append((", ".join(names), cur))
                cur, names = "", []
            cur += f"\n===== {label} =====\n{p}"
            names.append(label)
    if cur:
        out.append((", ".join(names), cur))
    return out


def diff_pieces(since: str) -> list[tuple[str, str]]:
    rng = since if ".." in since else f"{since}..HEAD"          # "A..B" reviews an older range
    files = [f for f in git("diff", "--name-only", rng, "--", "backend", "frontend/src", "tests",
                            "tools").splitlines() if f and not f.endswith((".png", ".json", ".lock", ".svg"))]
    return [(f, git("diff", "-U30", rng, "--", f)) for f in files]


def file_pieces(paths: list[str]) -> list[tuple[str, str]]:
    out = []
    for p in paths:
        path = (ROOT / p) if not Path(p).is_absolute() else Path(p)
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        out.append((str(path.relative_to(ROOT)).replace("\\", "/") if path.is_relative_to(ROOT) else path.name,
                    "\n".join(f"{i + 1:5d}  {l}" for i, l in enumerate(lines))))
    return out


def i18n_pieces() -> list[tuple[str, str]]:
    out = []
    for where in ("frontend/src/i18n", "backend/novastudio/i18n"):
        d = ROOT / where
        if not (d / "ja.json").exists():
            continue
        langs = {l: json.loads((d / f"{l}.json").read_text(encoding="utf-8")) for l in ("ja", "en", "zh")}

        def flat(obj, pre=""):
            for k, v in obj.items():
                if isinstance(v, dict):
                    yield from flat(v, pre + k + ".")
                else:
                    yield pre + k, str(v)
        f = {l: dict(flat(v)) for l, v in langs.items()}
        rows = [f"{k} | {f['ja'][k]} | {f['en'].get(k, '(missing)')} | {f['zh'].get(k, '(missing)')}" for k in f["ja"]]
        rows += [f"{k} | (missing in ja) | {f['en'].get(k, '')} | {f['zh'].get(k, '')}"
                 for k in sorted((set(f["en"]) | set(f["zh"])) - set(f["ja"]))]
        out.append((where, "\n".join(rows)))
    return out


def run(label: str, system: str, pieces: list[tuple[str, str]], model: str) -> Path:
    reqs = chunks_of([(n, scrub(t)) for n, t in pieces if t.strip()])
    print(f"{len(pieces)} inputs -> {len(reqs)} requests to {model}")
    findings, usage, problems = [], {"prompt_tokens": 0, "completion_tokens": 0, "prompt_cache_hit_tokens": 0}, []

    def one(req):
        names, text = req
        ans, use = ask(system, text, model, 32000 if "reasoner" in model else 8000)   # reasoning counts against the limit
        if ans.get("truncated") and text.count("\n") > 200:  # answer cut off: review each half on its own
            lines = text.splitlines(keepends=True)
            half = len(lines) // 2
            a, ua = one((names + " [first half]", "".join(lines[:half])))[1:]
            b, ub = one((names + " [second half]", "(continued)\n" + "".join(lines[half:])))[1:]
            ans = {"findings": a.get("findings", []) + b.get("findings", []),
                   "truncated": a.get("truncated") or b.get("truncated")}
            use = {k: (use.get(k) or 0) + (ua.get(k) or 0) + (ub.get(k) or 0) for k in usage}
        return names, ans, use
    with cf.ThreadPoolExecutor(WORKERS) as ex:
        for fut in cf.as_completed([ex.submit(one, r) for r in reqs]):
            try:
                names, ans, use = fut.result()
            except Exception as e:                       # keep the other chunks
                problems.append(str(e))
                continue
            for k in usage:
                usage[k] += use.get(k, 0) or 0
            if ans.get("truncated") or ans.get("error"):
                problems.append(f"{names}: {'answer cut off' if ans.get('truncated') else ans['error']}")
            for f in ans.get("findings", []):
                text = (str(f.get("summary", "")) + " " + str(f.get("scenario", ""))).lower() if isinstance(f, dict) else ""
                if isinstance(f, dict) and "no defect" not in text and not any(  # drop self-cleared and repeated items
                        (g.get("file"), g.get("line"), g.get("summary")) == (f.get("file"), f.get("line"), f.get("summary"))
                        for g in findings):
                    f["chunk"] = names
                    findings.append(f)
    order = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda f: (order.get(f.get("severity"), 3), order.get(f.get("confidence"), 3), str(f.get("file"))))
    date = datetime.date.today().isoformat()
    base = ROOT / "reviews" / f"{date}_{label}.{model}"
    base.parent.mkdir(exist_ok=True)
    md_path, json_path = base.with_name(base.name + ".md"), base.with_name(base.name + ".json")
    json_path.write_text(json.dumps({"model": model, "usage": usage, "problems": problems,
                                                    "findings": findings}, ensure_ascii=False, indent=1),
                                        encoding="utf-8")
    md = [f"# DeepSeek first pass: {label} ({date}, {model})", "",
          "Unverified. Each finding must be checked against the code and recorded as fixed / rejected (reason).", "",
          f"Tokens: prompt {usage['prompt_tokens']} (cache hit {usage['prompt_cache_hit_tokens']}), "
          f"answer {usage['completion_tokens']}. Problems: {len(problems)}", ""]
    md += [f"- problem: {p}" for p in problems]
    md += ["", "| # | sev | conf | where | summary |", "|---|---|---|---|---|"]
    for i, f in enumerate(findings, 1):
        where = f"{f.get('file')}:{f.get('line')}" + (f" `{f['key']}` {f.get('lang', '')}" if f.get("key") else "")
        md.append(f"| {i} | {f.get('severity')} | {f.get('confidence')} | {where} | {str(f.get('summary')).replace('|', '/')} |")
    for i, f in enumerate(findings, 1):
        md += ["", f"## {i}. {f.get('summary')}", f"- where: {f.get('file')}:{f.get('line')}",
               f"- scenario: {f.get('scenario', '')}", f"- fix: {f.get('fix', '')}"]
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"{len(findings)} findings, {len(problems)} problems -> {md_path}")
    return md_path


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("diff", "files", "i18n"):
        sys.exit(__doc__)
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
    mode, args = sys.argv[1], sys.argv[2:]
    if mode == "diff":
        since = args[0] if args else sys.exit("diff needs a tag or commit")
        run("since-" + since.replace("..", "_to_"), REVIEW_SYSTEM, diff_pieces(since), model)
    elif mode == "files":
        run("files-" + "-".join(Path(a).stem for a in args)[:60], REVIEW_SYSTEM, file_pieces(args), model)
    else:
        run("i18n", I18N_SYSTEM, i18n_pieces(), model)


if __name__ == "__main__":
    main()
