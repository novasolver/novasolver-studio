"""Write the validation manual from a suite result: docs/VALIDATION.md (ja), VALIDATION.en.md, VALIDATION.zh.md.
    python validation/report.py validation/results/0.6.4.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TXT = {
    "ja": {
        "title": "NovaSolver Studio 検証マニュアル",
        "intro": ("この文書は、Studio {v} が既知の答えのある問題をどれだけ正しく解くかの記録です。"
                  "すべての問題は `validation/suite.py` で誰でも再計算できます。数値は {date} に下記の環境で解いた結果で、"
                  "手で書き写したものではありません。"),
        "env": "環境", "how": "再計算の方法",
        "summary": "まとめ", "count": "{n} 題中 {p} 題が許容差内（不合格 {f}・エラー {e}・参照値なし {r}）。",
        "gates": ("判定欄の「メッシュ収束」は、粗・標準・細の3段階メッシュで答えが変わらないこと（GCI）を Studio 自身が確認した"
                  "ものです。「1メッシュ」はメモリなどの理由で1段階だけ解いたものです。"),
        "cols": ["題材", "確かめること", "量", "Studio", "参照値", "差", "許容差", "判定", "メッシュ"],
        "phys": {"structural": "構造", "thermal": "伝熱", "flow": "流れ", "cfd": "流れ", "external": "外部流れ",
                 "conjugate": "水冷（流れ＋伝熱）", "electric": "電気"},
        "ok": "合格", "ng": "不合格", "err": "エラー", "noref": "参照値なし",
        "conv": "収束確認済み", "one": "1メッシュ", "notconv": "収束未確認",
        "sources": "出典", "moved": "前の版からの変化", "moved_none": "{v} から 0.1 % を超えて変わった値はありません。",
        "moved_some": "{v} から 0.1 % を超えて変わった値：",
        "limits": "分かっている限界",
        "limit_items": [
            "乱流の壁摩擦（円管の摩擦係数）は、壁の近くのメッシュに強く左右されます。表の Blasius の結果を確認してから使ってください。",
            "固定面の角や鋭い入隅の応力は理論上無限大（特異点）です。Studio は警告を出し、比べる値には使いません。",
            "NAFEMS LE10 の細かいメッシュは 16 GB のメモリでは解けないため、標準メッシュ1段階の値です。",
            "接触・座屈・疲労・陽解法の衝突は、この版の検証範囲に含まれていません（実装予定）。",
        ],
        "repro": "Windows の zip 版または `pip install novasolver-studio` の環境で、リポジトリを取得して次を実行します。",
    },
    "en": {
        "title": "NovaSolver Studio validation manual",
        "intro": ("This document records how accurately Studio {v} solves problems with known answers. Anyone can "
                  "re-run every problem with `validation/suite.py`. The numbers were produced on {date} on the machine "
                  "below; none were typed in by hand."),
        "env": "Machine", "how": "How to reproduce",
        "summary": "Summary", "count": "{p} of {n} problems are within tolerance (failed {f}, errors {e}, no reference {r}).",
        "gates": ("'Mesh-converged' means Studio itself checked that the answer does not change between a coarse, a "
                  "normal and a fine mesh (GCI). 'One mesh' means only one level was solved, for memory or run time."),
        "cols": ["Problem", "What it tests", "Quantity", "Studio", "Reference", "Error", "Tolerance", "Result", "Mesh"],
        "phys": {"structural": "Structural", "thermal": "Heat transfer", "flow": "Flow", "cfd": "Flow",
                 "external": "External flow", "conjugate": "Liquid cooling (flow + heat)", "electric": "Electric"},
        "ok": "pass", "ng": "fail", "err": "error", "noref": "no reference",
        "conv": "converged", "one": "one mesh", "notconv": "not converged",
        "sources": "Sources", "moved": "Changes since the previous version",
        "moved_none": "No value changed by more than 0.1 % since {v}.", "moved_some": "Values that changed by more than 0.1 % since {v}:",
        "limits": "Known limits",
        "limit_items": [
            "Turbulent wall friction (pipe friction factor) depends strongly on the mesh next to the wall. Check the Blasius row before relying on it.",
            "Stress at the corner of a fixed face or a sharp re-entrant corner is infinite in theory (a singularity). Studio warns and does not use it for comparison.",
            "NAFEMS LE10 on the fine mesh needs more than 16 GB, so its value comes from the normal mesh only.",
            "Contact, buckling, fatigue and explicit crash are not part of this version's validation (planned).",
        ],
        "repro": "With the Windows zip or `pip install novasolver-studio`, clone the repository and run:",
    },
    "zh": {
        "title": "NovaSolver Studio 验证手册",
        "intro": ("本文档记录 Studio {v} 求解已知答案问题的准确程度。所有问题都可以用 `validation/suite.py` 重新计算。"
                  "数值是 {date} 在下列环境中求解的结果，没有手工抄写。"),
        "env": "环境", "how": "重新计算的方法",
        "summary": "汇总", "count": "{n} 个问题中 {p} 个在容差范围内（不合格 {f}，错误 {e}，无参考值 {r}）。",
        "gates": ("“网格收敛”表示 Studio 自身确认了在粗、标准、细三级网格下答案不变（GCI）。“单一网格”表示由于内存或时间原因只求解了一级。"),
        "cols": ["问题", "检验内容", "量", "Studio", "参考值", "误差", "容差", "结果", "网格"],
        "phys": {"structural": "结构", "thermal": "传热", "flow": "流动", "cfd": "流动", "external": "外部流动",
                 "conjugate": "水冷（流动＋传热）", "electric": "电"},
        "ok": "合格", "ng": "不合格", "err": "错误", "noref": "无参考值",
        "conv": "已收敛", "one": "单一网格", "notconv": "未确认收敛",
        "sources": "出处", "moved": "与上一版本相比的变化",
        "moved_none": "与 {v} 相比，没有变化超过 0.1 % 的数值。", "moved_some": "与 {v} 相比变化超过 0.1 % 的数值：",
        "limits": "已知的限制",
        "limit_items": [
            "湍流壁面摩擦（圆管摩擦系数）强烈依赖壁面附近的网格。使用前请先查看表中 Blasius 的结果。",
            "固定面的角点或尖锐内角处的应力在理论上为无穷大（奇异点）。Studio 会给出警告，不用于比较。",
            "NAFEMS LE10 的细网格需要 16 GB 以上内存，因此采用标准网格的结果。",
            "接触、屈曲、疲劳和显式碰撞不在本版本的验证范围内（计划中）。",
        ],
        "repro": "使用 Windows zip 版或 `pip install novasolver-studio`，获取仓库后运行：",
    },
}
ORDER = ["structural", "thermal", "electric", "cfd", "flow", "external", "conjugate"]


def num(x):
    if x is None:
        return "—"
    a = abs(x)
    return f"{x:.4g}" if a >= 1e-3 or a == 0 else f"{x:.3e}"


def err_txt(r):
    if r.get("tol_abs") is not None:
        return f"{r['error_abs']:+.3g} {r['unit']}"
    return "—" if r.get("error_pct") is None else f"{r['error_pct']:+.2f} %"


def tol_txt(r):
    if r.get("tol_abs") is not None:
        return f"±{r['tol_abs']:g} {r['unit']}"
    return "—" if r.get("tol_pct") is None else f"±{r['tol_pct']:g} %"


def write(doc, lang):
    t = TXT[lang]
    v = doc["version"]
    L = [f"# {t['title']} — {v}", "", t["intro"].format(v=v, date=doc["date"]), "",
         f"{t['env']}: {doc['machine']['os']}, Python {doc['machine']['python']}, {doc['machine']['cpu_count']} CPU", ""]
    cases = doc["cases"]
    n = {s: sum(c["status"] == s for c in cases) for s in ("pass", "fail", "error", "no-reference")}
    L += [f"## {t['summary']}", "", t["count"].format(n=len(cases), p=n["pass"], f=n["fail"], e=n["error"], r=n["no-reference"]),
          "", t["gates"], ""]
    for ph in ORDER:
        group = [c for c in cases if c["physics"] == ph]
        if not group:
            continue
        L += [f"## {t['phys'].get(ph, ph)}", "", "| " + " | ".join(t["cols"]) + " |", "|" + "---|" * len(t["cols"])]
        for c in group:
            g = (c.get("info") or {}).get("gates") or {}
            mesh = t["conv"] if g.get("verified") else t["one"] if not (c.get("info") or {}).get("study") else t["notconv"]
            title, tests = c["title"].get(lang, c["id"]), (c.get("tests") or {}).get(lang, "").replace("|", "/")
            if c["status"] == "error" or not c.get("rows"):
                res = t["err"] if c["status"] == "error" else t["noref"]
                L.append(f"| {title} | {tests} | — | — | — | — | — | {res} | {mesh} |")
                continue
            for i, r in enumerate(c["rows"]):
                L.append("| " + " | ".join([title if i == 0 else "", tests if i == 0 else "", str(r["quantity"]),
                                            f"{num(r['computed'])} {r['unit']}", f"{num(r['reference'])} {r['unit']}",
                                            err_txt(r), tol_txt(r), t["ok"] if r["pass"] else f"**{t['ng']}**",
                                            mesh if i == 0 else ""]) + " |")
        L.append("")
    if doc.get("moved_since"):
        m = doc["moved_since"]
        L += [f"## {t['moved']}", ""]
        if not m["items"]:
            L.append(t["moved_none"].format(v=m["version"]))
        else:
            L.append(t["moved_some"].format(v=m["version"]))
            L += [f"- {x['id']} / {x['quantity']}: {num(x['before'])} → {num(x['after'])} ({x['change_pct']:+.2f} %)" for x in m["items"]]
        L.append("")
    L += [f"## {t['limits']}", ""] + [f"- {x}" for x in t["limit_items"]] + [""]
    L += [f"## {t['sources']}", ""] + sorted({f"- **{c['title'].get(lang, c['id'])}**: {c['source']}" for c in cases}) + [""]
    L += [f"## {t['how']}", "", t["repro"], "", "```", "python validation/suite.py", "python validation/report.py validation/results/<version>.json", "```", ""]
    name = "VALIDATION.md" if lang == "ja" else f"VALIDATION.{lang}.md"
    (ROOT / "docs" / name).write_text("\n".join(L), encoding="utf-8")
    return ROOT / "docs" / name


if __name__ == "__main__":
    d = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    for lang in ("ja", "en", "zh"):
        print(write(d, lang))
