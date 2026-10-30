"""Side-by-side promo image: the 1862 patent drawing (US 35,600, public domain) and the Studio result."""
from pathlib import Path

import fitz
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent
RES = HERE.parent / "results"
page = fitz.open(HERE / "US35600.pdf")[0]
pix = page.get_pixmap(dpi=200)
sheet = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
W, H = sheet.size
drawing = sheet.crop((int(.05 * W), int(.06 * H), int(.95 * W), int(.70 * H)))     # title, Fig. 1 and Fig. 2
studio = Image.open(RES / "p4_gui_fire_ja.png").convert("RGB").crop((240, 48, 1280, 870))

h = 900
drawing = drawing.resize((int(drawing.width * h / drawing.height), h))
studio = studio.resize((int(studio.width * h / studio.height), h))
pad, top = 30, 110
out = Image.new("RGB", (drawing.width + studio.width + 3 * pad, h + top + pad), (18, 18, 20))
out.paste(drawing, (pad, top))
out.paste(studio, (2 * pad + drawing.width, top))
d = ImageDraw.Draw(out)
font = next((ImageFont.truetype(f, 40) for f in ("C:/Windows/Fonts/YuGothB.ttc", "C:/Windows/Fonts/meiryob.ttc")
             if Path(f).exists()), ImageFont.load_default())
small = next((ImageFont.truetype(f, 26) for f in ("C:/Windows/Fonts/YuGothM.ttc", "C:/Windows/Fonts/meiryo.ttc")
              if Path(f).exists()), ImageFont.load_default())
d.text((pad, 22), "1862年の特許「大砲つき鋤」を NovaSolver Studio で再現", fill=(240, 240, 240), font=font)
d.text((pad, top - 34), "US 35,600 (1862) 特許図面", fill=(170, 170, 170), font=small)
d.text((2 * pad + drawing.width, top - 34), "発射時の応力（鋳鉄・ガス圧 60 MPa・鋤を地面に固定）", fill=(170, 170, 170), font=small)
out.save(RES / "p4_patent_vs_studio_ja.png")
print(out.size)
