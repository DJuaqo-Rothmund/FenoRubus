"""
tools/make_splash_lottie.py
===========================
Genera assets/splash_lottie.json: la animación del logo en formato Lottie, que Android
reproduce de forma NATIVA en la pantalla de carga (buildozer: android.presplash_lottie).

Por qué: mientras Python arranca e importa Kivy no puede correr ningún código de la app,
así que una pantalla de carga normal es una imagen quieta. La animación Lottie la dibuja
Android en su propio hilo: se mueve desde el primer instante y sigue fluida mientras la
app arma y precarga todo detrás. Sale de las mismas cuentas que el logo de Kivy
(ui/splash_timeline.py), así que al quitarla no se nota el cambio.

Composición = el presplash (1080 × 2340): fondo con el nombre y la firma, y el logo en el
mismo lugar (62 % del ancho, centro al 60 % de la altura).

    python tools/make_splash_lottie.py      (después de tools/make_splash_layers.py)
"""
import base64
import io
import json
import math
import os
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
from ui import splash_timeline as tl  # noqa: E402

OUT = os.path.join(ROOT, "assets", "splash_lottie.json")
W, H = 1080, 2340
FPS = tl.LOTTIE_FPS
DURATION_S = 12          # luego vuelve a empezar (la app la quita mucho antes)
SIDE = int(W * .62)                       # = make_ui_assets.make_presplash
X0 = (W - SIDE) // 2
Y0 = int(H * (1 - .60)) - SIDE // 2
BG = (0xF2, 0xF4, 0xEE)


def comp(u, v):
    """(u, v) del cuadrado del logo (v hacia arriba) -> píxel de la composición."""
    return [round(X0 + u * SIDE, 2), round(Y0 + (1 - v) * SIDE, 2)]


def png_asset(aid, img):
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return {"id": aid, "w": img.width, "h": img.height, "u": "", "e": 1,
            "p": "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()}


def static(v):
    return {"a": 0, "k": v}


def anim(frames):
    """[(cuadro, valor)] -> propiedad animada lineal (valor escalar o lista)."""
    kfs = []
    for i, (t, v) in enumerate(frames):
        v = v if isinstance(v, list) else [v]
        kf = {"t": t, "s": [round(x, 3) for x in v]}
        if i < len(frames) - 1:
            n = len(v)
            kf["o"] = {"x": [0.0] * n, "y": [0.0] * n}
            kf["i"] = {"x": [1.0] * n, "y": [1.0] * n}
        kfs.append(kf)
    return {"a": 1, "k": kfs}


def squeeze(frames, eps=1e-3):
    """Quita cuadros intermedios que no cambian nada (menos peso, mismo resultado)."""
    out = []
    for i, (t, v) in enumerate(frames):
        if 0 < i < len(frames) - 1:
            pv, nv = frames[i - 1][1], frames[i + 1][1]
            a = v if isinstance(v, list) else [v]
            b = pv if isinstance(pv, list) else [pv]
            c = nv if isinstance(nv, list) else [nv]
            if all(abs(x - y) < eps and abs(x - z) < eps for x, y, z in zip(a, b, c)):
                continue
        out.append((t, v))
    return out


def layer(ind, name, ks, **extra):
    base = {"ddd": 0, "ind": ind, "nm": name, "sr": 1, "ks": ks, "ao": 0,
            "ip": 0, "op": DURATION_S * FPS, "st": 0, "bm": 0}
    base.update(extra)
    return base


def transform(p, a=(0, 0), s=(100, 100), r=0, o=100):
    return {"o": o if isinstance(o, dict) else static(o),
            "r": r if isinstance(r, dict) else static(r),
            "p": p if isinstance(p, dict) else static(list(p) + [0]),
            "a": static(list(a) + [0]),
            "s": s if isinstance(s, dict) else static(list(s) + [100])}


def main():
    L = tl.load_layout()
    n_frames = DURATION_S * FPS
    intro = int(math.ceil((tl.INTRO_S + .1) * FPS))
    scale = SIDE / 512 * 100

    # Fondo: el color lo pone Android (presplash_color); del presplash solo se recortan el
    # nombre y la firma (todo lo que no es fondo debajo del logo).
    import numpy as np
    bg = Image.open(os.path.join(ROOT, "assets", "presplash.png")).convert("RGB")
    arr = np.asarray(bg).astype(int)
    ink = np.abs(arr - np.array(BG)).sum(-1) > 12
    ink[:Y0 + SIDE + 4] = False
    texts = []
    rows = np.nonzero(ink.any(1))[0]
    groups, start = [], rows[0]
    for a, b in zip(rows, rows[1:]):
        if b - a > 60:                       # un hueco grande separa nombre y firma
            groups.append((start, a))
            start = b
    groups.append((start, rows[-1]))
    assets = []
    for gi, (y0, y1) in enumerate(groups):
        cols = np.nonzero(ink[y0:y1 + 1].any(0))[0]
        box = (int(cols[0]) - 2, int(y0) - 2, int(cols[-1]) + 3, int(y1) + 3)
        assets.append(png_asset(f"texto{gi}", bg.crop(box)))
        texts.append((f"texto{gi}", box))
    berry = Image.open(os.path.join(tl.DIR, "berry.png"))
    ring_img = Image.open(os.path.join(tl.DIR, "ring.png"))
    assets += [png_asset("berry", berry), png_asset("ring", ring_img)]

    layers = []
    ind = 1
    # --- manijas (arriba de todo) -------------------------------------------------
    face = comp(L["face"]["u"], L["face"]["v"])
    rgb = list(L["hand_rgb"]) + [1]
    width = L["hand_w"] * SIDE * tl.HAND_THICK
    hand_frames = [(f, tl.hands(L, f / FPS)) for f in range(n_frames + 1)]
    for key, idx in (("minute", 0), ("hour", 1)):
        ln = L[key]["len"] * SIDE
        rot = squeeze([(f, -h[idx]) for f, h in hand_frames])   # Lottie gira en sentido horario
        shapes = [{"ty": "gr", "nm": key, "it": [
            {"ty": "sh", "ks": static({"i": [[0, 0], [0, 0]], "o": [[0, 0], [0, 0]],
                                       "v": [[0, 0], [round(ln, 2), 0]], "c": False})},
            {"ty": "st", "c": static(rgb), "o": static(100), "w": static(round(width, 2)),
             "lc": 2, "lj": 2},
            {"ty": "tr", "p": static([0, 0]), "a": static([0, 0]), "s": static([100, 100]),
             "r": static(0), "o": static(100)}]}]
        layers.append(layer(ind, key, transform(face, r=anim(rot)), ty=4, shapes=shapes))
        ind += 1
    d = L["dot_r"] * SIDE * 2
    layers.append(layer(ind, "centro", transform(face), ty=4, shapes=[{"ty": "gr", "it": [
        {"ty": "el", "p": static([0, 0]), "s": static([round(d, 2), round(d, 2)])},
        {"ty": "fl", "c": static(rgb), "o": static(100), "r": 1},
        {"ty": "tr", "p": static([0, 0]), "a": static([0, 0]), "s": static([100, 100]),
         "r": static(0), "o": static(100)}]}]))
    ind += 1

    # --- frambuesa ---------------------------------------------------------------------
    layers.append(layer(ind, "frambuesa", transform(comp(.5, .5), a=(256, 256), s=(scale, scale)),
                        ty=2, refId="berry"))
    ind += 1

    # --- dibujos del ciclo -------------------------------------------------------------
    for i, ic in enumerate(L["icons"]):
        img = Image.open(os.path.join(tl.DIR, ic["file"]))
        aid = f"icon{i + 1}"
        assets.append(png_asset(aid, img))
        k = SIDE / 512        # el recorte del dibujo está en píxeles del cuadrado de 512
        pos, sc, op = [], [], []
        for f in range(intro + 1):
            st = tl.icons(L, f / FPS)[i]
            if st is None:
                pos.append((f, comp(ic["u"], ic["v"])))
                sc.append((f, [scale * .35, scale * .35]))
                op.append((f, 0))
            else:
                u, v, s, a = st
                pos.append((f, comp(u, v)))
                sc.append((f, [s * k * 100, s * k * 100]))
                op.append((f, a * 100))
        layers.append(layer(ind, aid, transform(
            anim(squeeze([(f, p) for f, p in pos])), a=(img.width / 2, img.height / 2),
            s=anim(squeeze([(f, v + [100]) for f, v in sc])), o=anim(squeeze(op))),
            ty=2, refId=aid))
        layers[-1]["ks"]["p"]["k"] = [dict(kf, s=kf["s"] + [0]) for kf in layers[-1]["ks"]["p"]["k"]]
        ind += 1

    # --- círculo punteado --------------------------------------------------------------
    rc = L["ring"]
    rot, op = [], []
    for f in range(intro + 1):
        ang, alpha = tl.ring(f / FPS)
        rot.append((f, -ang))
        op.append((f, alpha * 100))
    layers.append(layer(ind, "circulo", transform(
        comp(rc["u"], rc["v"]), a=(rc["u"] * 512, (1 - rc["v"]) * 512), s=(scale, scale),
        r=anim(squeeze(rot)), o=anim(squeeze(op))), ty=2, refId="ring"))
    ind += 1

    # --- nombre y firma ----------------------------------------------------------------
    for aid, (x0, y0, x1, y1) in texts:
        layers.append(layer(ind, aid, transform((x0, y0)), ty=2, refId=aid))
        ind += 1

    data = {"v": "5.7.4", "fr": FPS, "ip": 0, "op": n_frames, "w": W, "h": H,
            "nm": "PhenoRubus", "ddd": 0, "assets": assets, "layers": layers, "markers": []}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"))
    print(OUT, f"{os.path.getsize(OUT) / 1024:.0f} KB", len(layers), "capas")


if __name__ == "__main__":
    main()
