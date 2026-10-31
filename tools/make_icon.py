"""Draw the app icon (same shapes as frontend/public/favicon.svg) into assets/NovaSolverStudio.ico for the exe,
the installer, shortcuts and .nscase files.  python tools/make_icon.py"""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
S = 1024                                     # drawn large, then downsampled per icon size


def draw() -> Image.Image:
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    k = S / 32
    d.rounded_rectangle((0, 0, S - 1, S - 1), radius=7 * k, fill="#0b1220")
    d.polygon([(16 * k, 5 * k), (27 * k, 16 * k), (16 * k, 27 * k), (5 * k, 16 * k)], fill="#22d3ee")
    d.polygon([(16 * k, 10 * k), (22 * k, 16 * k), (16 * k, 22 * k), (10 * k, 16 * k)], fill="#0b1220")
    return im


if __name__ == "__main__":
    out = ROOT / "assets" / "NovaSolverStudio.ico"
    out.parent.mkdir(exist_ok=True)
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    big = draw()
    big.resize((256, 256), Image.LANCZOS).save(out, sizes=[(s, s) for s in sizes])
    print(out, out.stat().st_size)
    # Microsoft Store package (MSIX) tiles, used by tools/make_msix.py
    msix = ROOT / "assets" / "msix"
    msix.mkdir(exist_ok=True)
    for name, (w, h) in {"Square44x44Logo": (44, 44), "Square150x150Logo": (150, 150), "StoreLogo": (50, 50),
                         "Wide310x150Logo": (310, 150), "Square44x44Logo.targetsize-256": (256, 256)}.items():
        tile = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        s = min(w, h)
        tile.paste(big.resize((s, s), Image.LANCZOS), ((w - s) // 2, (h - s) // 2))
        tile.save(msix / f"{name}.png")
    print(msix)
