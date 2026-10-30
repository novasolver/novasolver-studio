"""Promo image for US 6,469 (1849, A. Lincoln): patent drawing | Studio result | the numbers.
Studio run (make_lincoln.py chamber, spar tops held, water 1.2 m deep on the bottom = 11.77 kPa): reaction 158.9 kN
(hand calculation 159 kN), max von Mises 10.96 MPa at the spar joints, max displacement 8.7 mm."""
from pathlib import Path

import fitz
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent
RES = HERE.parent / "results"
SHOT = Path(r"C:\Users\kiwat\AppData\Local\Temp\claude\E--03-------NovaSolver\a64cc5ca-4647-4f6a-a2cb-620501c231da"
            r"\scratchpad\promo\out\p6_gui_ja.png")

page = fitz.open(HERE / "US6469.pdf")[0]
pix = page.get_pixmap(dpi=200)
sheet = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
W, H = sheet.size
drawing = sheet.crop((int(.12 * W), int(.13 * H), int(.82 * W), int(.985 * H))).rotate(-90, expand=True)
studio = Image.open(SHOT).convert("RGB").crop((240, 48, 1280, 870))

w = 1500
drawing = drawing.resize((w, int(drawing.height * w / drawing.width)))
studio = studio.resize((int(studio.width * drawing.height / studio.height), drawing.height))


def font(size, bold=False):
    names = ("YuGothB.ttc", "meiryob.ttc") if bold else ("YuGothM.ttc", "meiryo.ttc")
    return next((ImageFont.truetype("C:/Windows/Fonts/" + n, size) for n in names
                 if Path("C:/Windows/Fonts/" + n).exists()), ImageFont.load_default())


pad, top = 30, 120
facts = ["1室の浮力 159 kN（約16 t）→ 4室で約65 t。全長40 m級の川船なら約20 cm浮く",
         "底板（オーク75 mm）の最大応力 11 MPa：湿ったオークの曲げ強さ約50 MPaの約1/4.5。壊れるのは支柱の付け根から",
         "ただし押し下げる力も同じ65 t。仕事0.38 MJ＝人力(75 W)なら約85分、蒸気機関なら数秒"]
fh = 44 * len(facts) + 30
out = Image.new("RGB", (drawing.width + studio.width + 3 * pad, drawing.height + top + pad + fh), (18, 18, 20))
out.paste(drawing, (pad, top))
out.paste(studio, (2 * pad + drawing.width, top))
d = ImageDraw.Draw(out)
d.text((pad, 24), "リンカーン大統領の特許（1849年）「浅瀬で船を浮かせる装置」を NovaSolver Studio で検証",
       fill=(240, 240, 240), font=font(40, True))
d.text((pad, top - 36), "US 6,469 (1849) 特許図面：船の脇の空気室Aを軸Cとロープで水中へ押し下げて膨らませる",
       fill=(170, 170, 170), font=font(26))
d.text((2 * pad + drawing.width, top - 36), "空気室の底板と支柱D・水深1.2 mの水圧（ミーゼス応力）",
       fill=(170, 170, 170), font=font(26))
for i, t in enumerate(facts):
    d.text((pad, top + drawing.height + 24 + 44 * i), "・" + t, fill=(225, 225, 225), font=font(30))
out.save(RES / "p6_patent_vs_studio_ja.png")
print(out.size)
