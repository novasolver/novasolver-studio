"""Can a cheap model drive Studio through MCP?  Runs fixed tasks against the real MCP server (stdio) with a
tool-calling model, then grades the resulting cases with deterministic checks (not the model's own report).

    python tools/agent_eval.py [--model deepseek-chat] [--tasks t1,t2] [--structured text|json] [--out DIR]

--structured json also appends the structured result as JSON text (what clients that ignore structuredContent miss).
The workspace is a fresh temp folder; nothing touches the person's cases. The DeepSeek key comes from
DEEPSEEK_API_KEY or DEEPSEEK_KEY_FILE (default E:\\_SECRETS\\deepseek.txt) and is never printed."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

STUDIO = Path(__file__).resolve().parents[1]
SAMPLES = STUDIO / "samples"
API = "https://api.deepseek.com/chat/completions"

TASKS = {
    "t1": ("片持ち梁のテンプレートで、長さを300 mm、先端の荷重を下向き2 kN、材料をアルミにして解析してください。"
           "最大のミーゼス応力と先端のたわみを教えて。メッシュによる誤差も確かめてください。"),
    "t2": (f"{SAMPLES / 'l_bracket.step'} を強度解析して。一番下の面（z が最も小さい面）を固定し、"
           "一番上の面（z が最も大きい面）に下向き 500 N をかけて、材料は鋼。最大応力と最大変位を教えて。"),
    "t3": "解析済みの例題を1つ開いて、参照解と比べてどれくらい合っているか教えて。",
    "t4": (f"{SAMPLES / 'wall_hook.stl'} は mm 単位で書き出した PLA の 3D プリント部品です。"
           "z が最も小さい面を固定、x が最も大きい面に下向き (-z) 20 N をかけて、どの向きに印刷するのが一番強いか教えて。"),
}


def deepseek_key() -> str:
    k = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not k:
        k = Path(os.environ.get("DEEPSEEK_KEY_FILE", r"E:\_SECRETS\deepseek.txt")).read_text(encoding="utf-8").strip()
    return k


def chat(model: str, key: str, messages: list, tools: list) -> dict:
    body = json.dumps({"model": model, "messages": messages, "tools": tools, "temperature": 0}).encode()
    req = urllib.request.Request(API, body, {"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.loads(r.read())
        except Exception as e:                                   # never echo the request (it has the key)
            if attempt == 3:
                raise RuntimeError(f"model API failed: {type(e).__name__}") from None
            time.sleep(5 * (attempt + 1))


def result_text(r, structured: str) -> str:
    text = "\n".join(c.text for c in r.content if getattr(c, "type", "") == "text")
    if structured == "json" and r.structured_content:
        text += "\n" + json.dumps(r.structured_content, ensure_ascii=False)[:6000]
    return ("ERROR: " if r.is_error else "") + text


async def run_task(tid: str, prompt: str, model: str, key: str, structured: str, log: Path) -> dict:
    ws = Path(tempfile.mkdtemp(prefix=f"nss_eval_{tid}_"))
    env = dict(os.environ, NOVASTUDIO_WORKSPACE=str(ws / "ws"), NOVASTUDIO_MCP_NO_IMAGES="1")
    params = StdioServerParameters(command=sys.executable, args=["-m", "novastudio", "mcp"], env=env,
                                   cwd=str(STUDIO / "backend"))
    calls, t0 = [], time.time()
    async with stdio_client(params) as (rd, wr), ClientSession(rd, wr) as s:
        init = await s.initialize()
        tools = [{"type": "function", "function": {"name": t.name, "description": t.description or "",
                                                   "parameters": t.input_schema}} for t in (await s.list_tools()).tools]
        msgs = [{"role": "system", "content": init.instructions or ""}, {"role": "user", "content": prompt}]
        answer = ""
        for _ in range(40):
            m = chat(model, key, msgs, tools)["choices"][0]["message"]
            msgs.append({k: v for k, v in m.items() if k in ("role", "content", "tool_calls")})
            if not m.get("tool_calls"):
                answer = m.get("content") or ""
                break
            for tc in m["tool_calls"]:
                name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"]["arguments"] or "{}")
                    r = await s.call_tool(name, args)
                    out, err = result_text(r, structured), bool(r.is_error)
                except Exception as e:
                    out, err = f"ERROR: bad call: {e}", True
                calls.append({"tool": name, "args": tc["function"]["arguments"][:400], "error": err, "out": out[:300]})
                msgs.append({"role": "tool", "tool_call_id": tc["id"], "content": out[:12000]})
        grade = await GRADERS[tid](s, answer)
    log.write_text(json.dumps({"task": tid, "prompt": prompt, "answer": answer, "calls": calls, "grade": grade},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    return {"task": tid, "calls": len(calls), "tool_errors": sum(c["error"] for c in calls),
            "seconds": round(time.time() - t0), **grade}


# ------------------------------------------------------------------ graders (read the cases, not the model's words)

async def _cases(s) -> list[dict]:
    return (await s.call_tool("list_cases", {})).structured_content["cases"]


async def _full(s, cid) -> dict:
    return (await s.call_tool("describe_case", {"case_id": cid, "detail": "full", "language": "en"})).structured_content


async def _results(s, cid) -> dict | None:
    r = await s.call_tool("get_results", {"case_id": cid, "language": "en"})
    return None if r.is_error else r.structured_content


def _no_false_verified(answer: str) -> bool:
    """No sentence claims the result is verified/validated (a sentence that negates it, or names the field
    gates.verified_by, is fine)."""
    import re
    for sent in re.split(r"[。\n.!?！？]", answer):
        if re.search(r"ない|ません|not|n't|未確認|verified_by", sent):
            continue
        if any(w in sent for w in ("検証済み", "verified", "validated", "妥当性が確認")):
            return False
    return True


def _num(v) -> float | None:
    if isinstance(v, dict):
        v = v.get("value")
    if isinstance(v, str):
        v = v.split()[0]
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


async def grade_t1(s, answer):
    checks = {}
    for c in await _cases(s):
        case = (await _full(s, c["case_id"]))["case"]
        L = case["geometry"]["params"]["length"]
        checks["length_300mm"] = abs(_num(L) * {"mm": 1, "m": 1000}.get(L["unit"], 1) - 300) < 0.5
        x1 = case["boundaries"].get("x1", {})
        F = x1.get("force") or {}
        checks["force_2kN"] = abs((_num(F) or 0) * {"N": 1, "kN": 1000}.get(F.get("unit"), 1) - 2000) < 1 \
            and x1.get("direction") == "-z"
        checks["aluminium"] = case["materials"]["solid"].get("preset") in ("aluminium", "aluminum")
        r = await _results(s, c["case_id"])
        checks["solved"] = bool(r and r["gates"].get("ran") and not r.get("stale"))
        checks["mesh_study"] = bool(r and r.get("convergence"))
    checks["no_false_verified"] = _no_false_verified(answer)
    checks["answer_has_numbers"] = "MPa" in answer and "mm" in answer
    return {"pass": all(checks.values()) and bool(checks), "checks": checks}


async def _imported_roles(s):
    for c in await _cases(s):
        d = await _full(s, c["case_id"])
        if d.get("faces") or d.get("boundaries"):
            return c["case_id"], d
    return None, None


def _face_table(d) -> dict:
    faces = {}
    for f in d.get("faces") or d.get("geometry", {}).get("faces", []):
        key = f.get("key") or f.get("face")
        if key:
            faces[key] = f
    return faces


async def grade_import(s, answer, fixed_axis, load_axis, load_n, extra=None):
    checks = {}
    cid, d = await _imported_roles(s)
    checks["case_created"] = cid is not None
    if cid:
        bnd = d["case"].get("boundaries") or {}
        cen = {f["key"]: f["centroid_mm"] for f in d.get("faces") or [] if f.get("centroid_mm")}
        ax = {"x": 0, "y": 1, "z": 2}
        lo = min(cen, key=lambda k: cen[k][ax[fixed_axis[1]]]) if cen and fixed_axis[0] == "min" else \
            max(cen, key=lambda k: cen[k][ax[fixed_axis[1]]]) if cen else None
        hi = max(cen, key=lambda k: cen[k][ax[load_axis]]) if cen else None
        role = lambda k: (bnd.get(k) or {}).get("role")
        checks["fixed_face_right"] = lo is not None and role(lo) == "fixed"
        lb = bnd.get(hi) or {}
        checks["load_face_right"] = lb.get("role") == "load" and abs((_num(lb.get("force")) or 0) - load_n) / load_n < 0.01 \
            and lb.get("direction") == "-z"
        r = await _results(s, cid)
        checks["solved"] = bool(r and r["gates"].get("ran") and not r.get("stale"))
        if extra:
            checks.update(await extra(s, cid, d))
        checks["_faces_debug"] = f"lowest/highest by centroid: {lo}/{hi}; roles {role(lo)}/{lb.get('role')}"
    checks["no_false_verified"] = _no_false_verified(answer)
    ok = all(v for k, v in checks.items() if not k.startswith("_"))
    return {"pass": ok, "checks": checks}


async def grade_t2(s, answer):
    async def steel(s, cid, d):
        return {"steel": "steel" in json.dumps(d["case"].get("materials"), ensure_ascii=False).lower()
                or d["parameters"].get("materials.solid.E") == "205 GPa"}
    return await grade_import(s, answer, ("min", "z"), "z", 500.0, steel)


async def grade_t3(s, answer):
    checks = {}
    cs = await _cases(s)
    checks["example_opened"] = bool(cs)
    if cs:
        r = await _results(s, cs[0]["case_id"])
        checks["has_result"] = bool(r and r["gates"].get("ran"))
    checks["answer_has_percent"] = "%" in answer
    checks["no_false_verified"] = _no_false_verified(answer)
    return {"pass": all(checks.values()), "checks": checks}


async def grade_t4(s, answer):
    async def pla(s, cid, d):
        return {"pla": "pla" in json.dumps(d["case"].get("materials"), ensure_ascii=False).lower(),
                "answer_names_axis": any(a in answer for a in ("x", "y", "z", "X", "Y", "Z"))}
    return await grade_import(s, answer, ("min", "z"), "x", 20.0, pla)


GRADERS = {"t1": grade_t1, "t2": grade_t2, "t3": grade_t3, "t4": grade_t4}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="deepseek-chat")
    ap.add_argument("--tasks", default=",".join(TASKS))
    ap.add_argument("--structured", choices=["text", "json"], default="text")
    ap.add_argument("--out", default=str(STUDIO / "validation" / "results" / "agent_eval"))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    key = deepseek_key()
    rows = []
    for tid in a.tasks.split(","):
        log = out / f"{a.model}_{a.structured}_{tid}.json"
        try:
            row = await run_task(tid, TASKS[tid], a.model, key, a.structured, log)
        except Exception as e:
            row = {"task": tid, "pass": False, "error": f"{type(e).__name__}: {e}"[:300]}
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    print(f"{a.model} ({a.structured}): {sum(r.get('pass', False) for r in rows)}/{len(rows)} passed")


if __name__ == "__main__":
    asyncio.run(main())
