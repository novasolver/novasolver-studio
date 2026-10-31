"""Promo image for US 1,119,732 (Tesla): patent drawing | field in the cross-section (smooth, with elements P) |
voltage at which the air breaks down (3 MV/m). Field from the Studio runs at 1 MV (cases given on the command line).
python compose_tesla.py <workspace> <smooth case id> <bumps case id>"""
import os
import sys
from pathlib import Path

import fitz
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.tri as mtri
import numpy as np
from matplotlib import font_manager
from PIL import Image, ImageDraw, ImageFont

ws, smooth_id, bumps_id = sys.argv[1:4]
os.environ["NOVASTUDIO_WORKSPACE"] = ws
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from novastudio import results as R, store  # noqa: E402

HERE = Path(__file__).parent
RES = HERE.parent / "results"
for f in ("C:/Windows/Fonts/YuGothM.ttc", "C:/Windows/Fonts/meiryo.ttc"):
    if Path(f).exists():
        font_manager.fontManager.addfont(f)
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=f).get_name()
        break


def section(cid):
    """|E| on the wedge face y = 0 (the x-z cross-section through the axis), in MV/m at 1 MV."""
    out = R.field(store.load(cid), "emag", "ja")
    P = np.array(out["positions"]).reshape(-1, 3)
    T = np.array(out["indices"]).reshape(-1, 3)
    s = np.array(out["scalars"])
    keep = np.all(np.abs(P[T, 1]) < 1e-6, axis=1)
    return P[:, 0], P[:, 2], T[keep], s                   # kV/mm = MV/m


fig, axes = plt.subplots(1, 3, figsize=(15, 5.6), dpi=150, facecolor="#121214",
                         gridspec_kw={"width_ratios": [1, 1, 0.9]})
vmax = 0.24
for ax, cid, title in ((axes[0], smooth_id, "なめらかなトーラス"), (axes[1], bumps_id, "半球 P で覆ったトーラス（特許の図面）")):
    x, z, T, s = section(cid)
    for sign in (1, -1):                                   # mirror: the full cross-section through the tower
        tri = mtri.Triangulation(sign * x, z, T)
        tc = ax.tripcolor(tri, s, shading="gouraud", cmap="inferno", vmin=0, vmax=vmax)
    ax.set_xlim(-20, 20); ax.set_ylim(45, 69); ax.set_aspect("equal")
    ax.set_facecolor("#121214"); ax.set_title(title, color="#eeeeee", fontsize=13)
    ax.tick_params(colors="#888888"); [sp.set_color("#444444") for sp in ax.spines.values()]
    ax.set_xlabel("m", color="#888888")
cb = fig.colorbar(tc, ax=axes[:2], orientation="horizontal", fraction=0.05, pad=0.14, shrink=0.7)
cb.set_label("電界の強さ [MV/m]（電極 1 MV のとき）", color="#cccccc"); cb.ax.tick_params(colors="#aaaaaa")
ax = axes[2]
names = ["なめらかな\nトーラス", "半球 P\n（特許の図面）", "角のある円盤\n（比較用）"]
volts = [22.0, 12.6, 4.0]
bars = ax.bar(names, volts, color=["#46c8e6", "#e6a046", "#e05a5a"], width=0.6)
for b, v, lab in zip(bars, volts, ("22 MV", "12.6 MV", "4 MV 以下")):
    ax.text(b.get_x() + b.get_width() / 2, v + 0.5, lab, ha="center", color="#eeeeee", fontsize=13)
ax.set_title("空気が絶縁破壊する電圧（3 MV/m）", color="#eeeeee", fontsize=13)
ax.set_facecolor("#121214"); ax.tick_params(colors="#bbbbbb"); ax.set_ylim(0, 26)
[sp.set_color("#444444") for sp in ax.spines.values()]
ax.set_ylabel("電極の電圧 [MV]", color="#bbbbbb")
plot = RES / "p7_field_and_voltage.png"
fig.savefig(plot, facecolor=fig.get_facecolor(), bbox_inches="tight")

page = fitz.open(HERE / "US1119732.pdf")[0]
pix = page.get_pixmap(dpi=200)
sheet = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
W, H = sheet.size
drawing = sheet.crop((int(.17 * W), int(.17 * H), int(.72 * W), int(.83 * H)))
chart = Image.open(plot).convert("RGB")
h = 900
drawing = drawing.resize((int(drawing.width * h / drawing.height), h))
chart = chart.resize((int(chart.width * h / chart.height), h))


def font(size, bold=False):
    names = ("YuGothB.ttc", "meiryob.ttc") if bold else ("YuGothM.ttc", "meiryo.ttc")
    return next((ImageFont.truetype("C:/Windows/Fonts/" + n, size) for n in names
                 if Path("C:/Windows/Fonts/" + n).exists()), ImageFont.load_default())


pad, top = 30, 120
facts = ["電極を大きく丸くすると、同じ電圧でも表面の電界が弱まり、空気中へ放電しにくくなる（テスラの主張どおり）",
         "なめらかなトーラスなら約 22 MV まで溜められる。図面の小さな半球 P は頂点に電界が集まり、上限は約 12.6 MV に下がる",
         "角のある円盤は角で電界が集中し、4 MV にも届かない。テスラが「大きな曲率半径」にこだわった理由が数字で分かる"]
fh = 44 * len(facts) + 30
out = Image.new("RGB", (drawing.width + chart.width + 3 * pad, h + top + pad + fh), (18, 18, 20))
out.paste(drawing, (pad, top))
out.paste(chart, (2 * pad + drawing.width, top))
d = ImageDraw.Draw(out)
d.text((pad, 24), "テスラの無線送電塔（特許 1914年）は何ボルトまで溜められたか — NovaSolver Studio で電界を計算",
       fill=(240, 240, 240), font=font(40, True))
d.text((pad, top - 36), "US 1,119,732 特許図面", fill=(170, 170, 170), font=font(26))
d.text((2 * pad + drawing.width, top - 36), "塔の断面の電界（高さ 57 m、トーラス外径 30 m・管径 7.4 m）",
       fill=(170, 170, 170), font=font(26))
for i, t in enumerate(facts):
    d.text((pad, top + h + 24 + 44 * i), "・" + t, fill=(225, 225, 225), font=font(30))
out.save(RES / "p7_patent_vs_studio_ja.png")
print(out.size)
