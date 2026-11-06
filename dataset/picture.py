"""A small von Mises picture of one solved point for the data explorer: undeformed shape, dark ground, no axes or
title, colour = stress / the point's peak (so every thumbnail reads the same way: yellow is the hot spot)."""
from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path

import numpy as np

W, H = 480, 300            # pixels of the saved webp
VIEW = (24, -58)           # elevation, azimuth: the families put the critical feature towards +x/+y/+z


def save(case_id: str, path: Path, view: tuple[float, float] = VIEW, crop: float | None = None, quantity: str = "vm") -> dict:
    """quantity: the field drawn (a family's PICTURE_QUANTITY; vm falls back to the physics' default field)."""
    from novastudio import results, store
    f = results.field(store.load(case_id), quantity, "en")
    P = np.array(f["positions"], dtype=float).reshape(-1, 3)
    tri = np.array(f["indices"], dtype=int).reshape(-1, 3)
    s = np.array(f["scalars"], dtype=float)
    if os.environ.get("NSS_PICTURE_DUMP"):                       # keep the surface to try other views
        np.savez_compressed(path.with_suffix(".npz"), P=P, tri=tri, s=s)
    return render(P, tri, s, path, view, crop)


def render(P, tri, s, path: Path, view: tuple[float, float] = VIEW, crop: float | None = None) -> dict:
    """crop: keep only the slab within crop x the length of the peak along the longest axis (long parts: show the
    feature, not the whole bar)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    from PIL import Image
    peak = float(s.max()) or 1.0
    if crop:
        ax_ = int(np.argmax(np.ptp(P, axis=0)))
        c, h = P[s.argmax(), ax_], crop * np.ptp(P[:, ax_])
        P = P.copy()
        P[:, ax_] = np.clip(P[:, ax_], c - h, c + h)                 # a clean flat cut: the rest folds onto it
        tri = tri[np.abs(P[tri, ax_] - c).min(axis=1) < h]
    fig = plt.figure(figsize=(W / 100 * 2, H / 100 * 2), dpi=100, facecolor="#0b0f14")
    ax = fig.add_axes([0, 0, 1, 1], projection="3d", facecolor="#0b0f14")
    rgb = plt.get_cmap("inferno")(s[tri].mean(axis=1) / peak * 0.8 + 0.16)[:, :3]
    n = np.cross(P[tri[:, 1]] - P[tri[:, 0]], P[tri[:, 2]] - P[tri[:, 0]])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-30
    light = np.array([0.4, -0.5, 0.75]) / np.linalg.norm([0.4, -0.5, 0.75])
    rgb *= (0.7 + 0.3 * np.abs(n @ light))[:, None]          # soft two-sided shading so the shape reads
    ax.add_collection3d(Poly3DCollection(P[tri], facecolors=rgb, edgecolors="none"))
    used = P[np.unique(tri)]
    mn, mx = used.min(axis=0), used.max(axis=0)
    span = np.maximum(mx - mn, 1e-3 * (mx - mn).max())
    ctr = (mn + mx) / 2
    for setlim, c, sp in zip((ax.set_xlim, ax.set_ylim, ax.set_zlim), ctr, span):
        setlim(c - sp / 2, c + sp / 2)
    ax.set_box_aspect(tuple(span / span.max()), zoom=0.9)
    ax.view_init(*view)
    ax.set_axis_off()
    buf = BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    img = Image.open(buf).convert("RGB")
    a = np.asarray(img).astype(int)
    ys, xs = np.nonzero(np.abs(a - a[0, 0]).sum(axis=2) > 24)    # the drawn shape; then fit it into W x H with a margin
    box = [xs.min(), ys.min(), xs.max() + 1, ys.max() + 1]
    bw, bh = box[2] - box[0], box[3] - box[1]
    k = min(W * 0.9 / bw, H * 0.9 / bh)
    part = img.crop(box).resize((max(1, round(bw * k)), max(1, round(bh * k))), Image.LANCZOS)
    img = Image.new("RGB", (W, H), tuple(a[0, 0]))
    img.paste(part, ((W - part.width) // 2, (H - part.height) // 2))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "WEBP", quality=72, method=6)
    return {"peak_vm_mpa": round(peak, 4), "bytes": path.stat().st_size}
