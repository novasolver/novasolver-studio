"""Promo image for US 43,449 (1864) 'Aereon': patent drawing | claimed vs computed speed | Studio flow field.
Speeds from the Studio run at 10 deg nose-up (Cd 0.2384, Cl 0.5627 on A = 65.55 m2): the aerodynamic resultant
balances the net buoyancy B, so v = sqrt(2 B / (rho A sqrt(Cd^2 + Cl^2))), climbing at atan(Cd / Cl) = 23 deg."""
import math
from pathlib import Path

import fitz
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent
RES = HERE.parent / "results"
CD, CL, A, RHO = 0.2384, 0.5627, 65.549, 1.2


def mph(lb):
    v = math.sqrt(2 * lb * 4.448 / (RHO * A * math.hypot(CD, CL)))
    return v * math.cos(math.atan(CD / CL)) / 0.44704


for f in ("C:/Windows/Fonts/YuGothM.ttc", "C:/Windows/Fonts/meiryo.ttc"):
    if Path(f).exists():
        font_manager.fontManager.addfont(f)
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=f).get_name()
        break
lbs = list(range(0, 201, 5))
fig, ax = plt.subplots(figsize=(6.4, 6.0), dpi=150, facecolor="#121214")
ax.set_facecolor("#121214")
ax.plot(lbs, lbs, color="#f59e0b", lw=3, label="特許の主張（1ポンド＝時速1マイル）")
ax.plot(lbs, [mph(x) for x in lbs], color="#22d3ee", lw=3, label="Studio の計算")
ax.annotate("時速200マイル", (200, 200), (120, 185), color="#f59e0b", fontsize=13, arrowprops=dict(color="#f59e0b", arrowstyle="->"))
ax.annotate(f"時速{mph(200):.1f}マイル", (200, mph(200)), (115, 45), color="#22d3ee", fontsize=13, arrowprops=dict(color="#22d3ee", arrowstyle="->"))
ax.set_xlabel("浮力の余り（ポンド）", color="#ddd", fontsize=12)
ax.set_ylabel("前進速度（マイル毎時）", color="#ddd", fontsize=12)
ax.tick_params(colors="#bbb")
for s in ax.spines.values():
    s.set_color("#555")
ax.grid(color="#333")
ax.legend(facecolor="#1c1c20", edgecolor="#444", labelcolor="#eee", fontsize=10.5, loc="upper left")
fig.tight_layout()
fig.savefig(RES / "p5_claim_vs_studio.png", facecolor=fig.get_facecolor())

page = fitz.open(HERE / "US43449.pdf")[0]
pix = page.get_pixmap(dpi=150)
sheet = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
W, H = sheet.size
drawing = sheet.crop((int(.10 * W), int(.03 * H), int(.92 * W), int(.90 * H)))
chart = Image.open(RES / "p5_claim_vs_studio.png").convert("RGB")
flow = Image.open(RES / "p5_gui_flow_close_ja.png").convert("RGB").crop((330, 200, 1180, 700))

h = 900
drawing = drawing.resize((int(drawing.width * h / drawing.height), h))
chart = chart.resize((int(chart.width * h / chart.height), h))
pad, top, cap = 30, 110, 50
fw = drawing.width + chart.width + pad                   # the flow field spans both panels above it
flow = flow.resize((fw, int(flow.height * fw / flow.width)))
out = Image.new("RGB", (fw + 2 * pad, top + h + cap + pad + flow.height + pad), (18, 18, 20))
out.paste(drawing, (pad, top))
out.paste(chart, (2 * pad + drawing.width, top))
out.paste(flow, (pad, top + h + cap + pad))
d = ImageDraw.Draw(out)
big = ImageFont.truetype("C:/Windows/Fonts/YuGothB.ttc", 40)
small = ImageFont.truetype("C:/Windows/Fonts/YuGothM.ttc", 26)
d.text((pad, 22), "1864年の飛行船「エアリオン」は時速200マイルで飛べたか", fill=(240, 240, 240), font=big)
d.text((pad, top - 34), "US 43,449 (1864) 特許図面", fill=(170, 170, 170), font=small)
d.text((2 * pad + drawing.width, top - 34), "浮力の余り → 前進速度（機首10°）", fill=(170, 170, 170), font=small)
d.text((pad, top + h + pad + 6), "NovaSolver Studio で計算した空気の流れ（全長24.4 m・風速5 m/s・機首10°）", fill=(170, 170, 170), font=small)
out.save(RES / "p5_patent_vs_studio_ja.png")
print(out.size, round(mph(1), 2), round(mph(200), 1))
