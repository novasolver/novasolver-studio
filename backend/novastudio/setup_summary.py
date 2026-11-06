"""The setup in words: which face carries what, which way, and what holds the part. A load pointing the wrong way or
on the wrong face gives a valid answer to a different question, so no check can flag it; this summary is for the
person (or the AI, with the person) to compare with what they meant before solving."""
from __future__ import annotations

import numpy as np

from . import templates, units
from .i18n import t

AXES = {"+x": (1, 0, 0), "-x": (-1, 0, 0), "+y": (0, 1, 0), "-y": (0, -1, 0), "+z": (0, 0, 1), "-z": (0, 0, -1)}
HOLDS = ("fixed", "beam-clamp", "symmetry", "constraint", "displacement", "spring")


def _num(x: float) -> str:
    return f"{x:,.4g}"


def summary(case: dict, lang: str) -> list[str]:
    from .commands import face_label
    tp = templates.get(case["template"])
    info = {f["key"]: f for f in case["geometry"].get("faces", [])}
    b = case["boundaries"]

    def label(k):
        return f"{k} ({face_label(tp, k, lang, case).split(' · ')[0]})"

    out: list[str] = []
    if tp["physics"] == "structural":
        held = [k for k, v in b.items() if v.get("role") in HOLDS]
        for k, v in b.items():
            role, f = v.get("role"), info.get(k, {})
            area = f.get("area")
            if role == "load":
                F = units.to_si(v["force"])
                d = v.get("direction", "-z")
                n = f.get("normal")
                vec = -np.array(n, float) if d == "normal" and n else np.array(AXES.get(d, (0, 0, 0)), float)
                if n:
                    c = float(np.dot(vec, n))
                    rel = t("setup.push" if c < -0.9 else "setup.pull" if c > 0.9 else "setup.along" if abs(c) < 0.2
                            else "setup.angle", lang, deg=round(float(np.degrees(np.arccos(np.clip(abs(c), 0, 1))))))
                    out.append(t("setup.load", lang, face=label(k), force=_num(F), dir=d, normal=_dir(n), relation=rel,
                                 traction=_num(F / area / 1e6) if area else "-", area=_num(area * 1e6) if area else "-"))
                else:
                    out.append(t("setup.load_curved", lang, face=label(k), force=_num(F), dir=d,
                                 area=_num(area * 1e6) if area else "-"))
                arm = _arm(f, [info.get(h, {}) for h in held], held, vec)
                if arm:
                    out.append(t("setup.lever", lang, support=label(arm[1]), arm=_num(arm[0] * 1e3),
                                 moment=_num(F * arm[0])))
            elif role == "pressure":
                p = units.to_si(v["pressure"])
                out.append(t("setup.pressure", lang, face=label(k), p=_num(p / 1e6),
                             force=_num(p * area) if area else "-", area=_num(area * 1e6) if area else "-"))
            elif role in ("moment", "bearing", "remote-force"):
                vals = ", ".join(f"{x} {q['value']} {q['unit']}" if isinstance(q, dict) and "value" in q else f"{x} {q}"
                                 for x, q in v.items() if x not in ("role", "thermal"))
                out.append(t("setup.other", lang, face=label(k), role=t(f"role.{role}", lang), values=vals))
        out.append(t("setup.held", lang, faces=", ".join(f"{label(k)} = {t('role.' + b[k]['role'], lang)}" for k in held)
                     if held else "-"))
        for name, m in _materials(case, lang):
            out.append(t("setup.material", lang, name=name, E=_num(m["E"] / 1e9),
                         sy=_num(m["sy"] / 1e6) if m.get("sy") else "-"))
    elif tp["physics"] == "thermal":
        for k, v in b.items():
            if v.get("role") == "temperature":
                out.append(t("setup.temperature", lang, face=label(k), T=_num(units.to_si(v["temperature"]) - 273.15)))
            elif v.get("role") == "convection":
                out.append(t("setup.convection", lang, face=label(k), h=_num(units.to_si(v["h"])),
                             T=_num(units.to_si(v["tinf"]) - 273.15)))
            elif v.get("role") == "heat-flux":
                out.append(t("setup.flux", lang, face=label(k), q=_num(units.to_si(v["flux"]))))
        for name, m in _materials(case, lang):
            out.append(t("setup.conductivity", lang, name=name, k=_num(m["k"])))
    return out


def _dir(n) -> str:
    from .commands import axis_word
    return axis_word(n) or "[" + ", ".join(f"{x:.2f}" for x in n) + "]"


def _arm(load: dict, supports: list[dict], keys: list[str], vec):
    """Distance across the load line from the load face centroid to the nearest support centroid: the lever arm of
    the bending moment at that support (exact for a straight cantilever, a rough size otherwise)."""
    if "centroid" not in load or not np.any(vec):
        return None
    c = np.array(load["centroid"], float)
    best = None
    for s, k in zip(supports, keys):
        if "centroid" in s:
            r = c - np.array(s["centroid"], float)
            d = float(np.linalg.norm(np.cross(r, vec / np.linalg.norm(vec))))
            if best is None or float(np.linalg.norm(r)) < best[2]:
                best = (d, k, float(np.linalg.norm(r)))
    return best[:2] if best and best[0] > 0 else None


def _materials(case: dict, lang: str):
    if case.get("body_materials"):
        return [(f"{body}: {t('material.' + preset, lang)}", templates.solid_props(case, body))
                for body, preset in case["body_materials"].items()]
    preset = case["materials"].get("solid", {}).get("preset")
    return [(t("material." + preset, lang) if preset else "-", templates.solid_props(case))]
