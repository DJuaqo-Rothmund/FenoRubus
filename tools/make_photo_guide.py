"""
tools/make_photo_guide.py
=========================
Láminas de la guía «Cómo sacar las fotos» de AeonScout (assets/ui/guia/*.png).

    python tools/make_photo_guide.py            # SVG en /tmp/guia_svg y PNG en assets/ui/guia

Cada lámina son uno o más «visores» de cámara con un ejemplo dibujado; los pares llevan ✓ (así)
y ✗ (así no). El texto de cada tarjeta está en scout_guide.PHOTO_CARDS.
"""
from __future__ import annotations

import math
import os
import random
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "ui", "guia")
TMP = os.environ.get("GUIA_SVG", "/tmp/guia_svg")

BG = "#F4F7F1"
FRAME_BG = "#FBFCF8"
INK = "#1E4A3A"
OK = "#2E9E5B"
BAD = "#C8384A"
BEETLE = "#4A3020"
BEETLE_2 = "#6B4630"
LEAF = "#4F8F45"
LEAF_D = "#2F6B34"
LEAF_U = "#A9C99A"
SOIL = "#8A6A4A"
FONT = "font-family='DejaVu Sans, Arial, sans-serif'"

_uid = [0]


def uid(p="c"):
    _uid[0] += 1
    return f"{p}{_uid[0]}"


# ----------------------------------------------------------------- piezas
def badge(x, y, ok: bool | None):
    if ok is None:
        return ""
    col = OK if ok else BAD
    mark = (f"<path d='M{x-11},{y+1} L{x-3},{y+9} L{x+12},{y-8}' fill='none' stroke='white' stroke-width='5' "
            f"stroke-linecap='round' stroke-linejoin='round'/>" if ok else
            f"<path d='M{x-9},{y-9} L{x+9},{y+9} M{x+9},{y-9} L{x-9},{y+9}' stroke='white' stroke-width='5' "
            f"stroke-linecap='round'/>")
    return f"<circle cx='{x}' cy='{y}' r='22' fill='{col}' stroke='white' stroke-width='3'/>{mark}"


def frame(x, y, w, h, content, ok=None, label="", bg=FRAME_BG):
    cid = uid("clip")
    s = [f"<clipPath id='{cid}'><rect x='{x}' y='{y}' width='{w}' height='{h}' rx='18'/></clipPath>",
         f"<rect x='{x}' y='{y}' width='{w}' height='{h}' rx='18' fill='{bg}' stroke='#C9D6C4' stroke-width='2'/>",
         f"<g clip-path='url(#{cid})'>{content}</g>"]
    L, m = 26, 14   # esquinas de visor
    for cx, cy, dx, dy in ((x + m, y + m, 1, 1), (x + w - m, y + m, -1, 1), (x + m, y + h - m, 1, -1),
                           (x + w - m, y + h - m, -1, -1)):
        s.append(f"<path d='M{cx},{cy + dy * L} L{cx},{cy} L{cx + dx * L},{cy}' fill='none' stroke='{INK}' "
                 f"stroke-opacity='.55' stroke-width='4' stroke-linecap='round'/>")
    s.append(badge(x + w - 14, y + 14, ok))
    if label:
        s.append(f"<text x='{x + w / 2}' y='{y + h + 34}' text-anchor='middle' {FONT} font-size='27' "
                 f"font-weight='bold' fill='{INK}'>{label}</text>")
    return "".join(s)


def legs_dorsal(cx, cy, s):
    out = []
    for side in (-1, 1):
        for i, (a, b) in enumerate(((-.55, -.95), (-.1, -.15), (.35, .75))):
            x0, y0 = cx + side * .3 * s, cy + a * s
            x1, y1 = cx + side * .85 * s, cy + (a + (b - a) * .4) * s
            x2, y2 = cx + side * 1.0 * s, cy + b * s
            out.append(f"<polyline points='{x0},{y0} {x1},{y1} {x2},{y2}' fill='none' stroke='{BEETLE}' "
                       f"stroke-width='{.07 * s}' stroke-linecap='round' stroke-linejoin='round'/>")
    return "".join(out)


def beetle(cx, cy, s, view="dorsal", spots=True):
    """Gorgojo (burrito) dibujado de arriba, de lado o de abajo."""
    w = .07 * s
    if view == "lateral":
        legs = "".join(
            f"<polyline points='{cx + dx * s},{cy + .2 * s} {cx + (dx - .12) * s},{cy + .55 * s} "
            f"{cx + (dx - .02) * s},{cy + .78 * s}' fill='none' stroke='{BEETLE}' stroke-width='{w}' "
            f"stroke-linecap='round' stroke-linejoin='round'/>" for dx in (-.45, 0, .45))
        return (legs +
                f"<ellipse cx='{cx + .15 * s}' cy='{cy}' rx='{.75 * s}' ry='{.42 * s}' fill='{BEETLE}'/>"
                f"<path d='M{cx - .55 * s},{cy - .3 * s} Q{cx + .2 * s},{cy - .62 * s} {cx + .88 * s},{cy - .05 * s}' "
                f"fill='none' stroke='{BEETLE_2}' stroke-width='{.05 * s}'/>"
                f"<ellipse cx='{cx - .65 * s}' cy='{cy - .05 * s}' rx='{.28 * s}' ry='{.26 * s}' fill='{BEETLE_2}'/>"
                f"<path d='M{cx - .85 * s},{cy - .05 * s} Q{cx - 1.15 * s},{cy + .05 * s} {cx - 1.2 * s},{cy + .32 * s}' "
                f"fill='none' stroke='{BEETLE_2}' stroke-width='{.16 * s}' stroke-linecap='round'/>"
                f"<polyline points='{cx - 1.05 * s},{cy + .05 * s} {cx - 1.05 * s},{cy - .45 * s} {cx - 1.35 * s},{cy - .6 * s}' "
                f"fill='none' stroke='{BEETLE}' stroke-width='{.045 * s}' stroke-linecap='round'/>"
                f"<circle cx='{cx - .78 * s}' cy='{cy - .1 * s}' r='{.05 * s}' fill='#111'/>")
    body = BEETLE if view == "dorsal" else "#8C6A4E"
    s_ = [legs_dorsal(cx, cy, s)]
    # antenas acodadas
    for side in (-1, 1):
        s_.append(f"<polyline points='{cx + side * .08 * s},{cy - 1.05 * s} {cx + side * .3 * s},{cy - 1.3 * s} "
                  f"{cx + side * .55 * s},{cy - 1.35 * s}' fill='none' stroke='{BEETLE}' stroke-width='{.045 * s}' "
                  f"stroke-linecap='round'/>")
    s_.append(f"<rect x='{cx - .12 * s}' y='{cy - 1.2 * s}' width='{.24 * s}' height='{.35 * s}' rx='{.1 * s}' fill='{BEETLE_2}'/>")
    s_.append(f"<ellipse cx='{cx}' cy='{cy - .82 * s}' rx='{.22 * s}' ry='{.2 * s}' fill='{BEETLE_2}'/>")
    s_.append(f"<ellipse cx='{cx}' cy='{cy - .5 * s}' rx='{.36 * s}' ry='{.27 * s}' fill='{body}'/>")
    s_.append(f"<ellipse cx='{cx}' cy='{cy + .25 * s}' rx='{.55 * s}' ry='{.75 * s}' fill='{body}'/>")
    if view == "dorsal":
        s_.append(f"<line x1='{cx}' y1='{cy - .45 * s}' x2='{cx}' y2='{cy + .98 * s}' stroke='#2A1A10' stroke-width='{.03 * s}'/>")
        if spots:
            rnd = random.Random(3)
            for _ in range(10):
                px = cx + rnd.uniform(-.38, .38) * s
                py = cy + rnd.uniform(-.25, .75) * s
                s_.append(f"<circle cx='{px}' cy='{py}' r='{.045 * s}' fill='#D9B64A'/>")
    else:   # ventral: segmentos y coxas
        for k in range(4):
            yy = cy + (.15 + k * .2) * s
            s_.append(f"<path d='M{cx - .45 * s},{yy} Q{cx},{yy + .08 * s} {cx + .45 * s},{yy}' fill='none' "
                      f"stroke='#5A3E2A' stroke-width='{.03 * s}'/>")
        for yy in (-.55, -.1, .35):
            for side in (-1, 1):
                s_.append(f"<circle cx='{cx + side * .18 * s}' cy='{cy + yy * s}' r='{.08 * s}' fill='#5A3E2A'/>")
    return "".join(s_)


def leaf(cx, cy, s, under=False, angle=0, bites=False, bg=FRAME_BG, color=None):
    col = color or (LEAF_U if under else LEAF)
    vein = "#E9F2E2" if under else LEAF_D
    vw = .045 * s if under else .03 * s
    path = (f"M0,{-1 * s} C{.62 * s},{-.6 * s} {.62 * s},{.5 * s} 0,{1 * s} "
            f"C{-.62 * s},{.5 * s} {-.62 * s},{-.6 * s} 0,{-1 * s} Z")
    veins = [f"<line x1='0' y1='{-.95 * s}' x2='0' y2='{1.15 * s}' stroke='{vein}' stroke-width='{vw * 1.4}' stroke-linecap='round'/>"]
    for k in range(-3, 4):
        y = k * .25 * s
        veins.append(f"<path d='M0,{y + .12 * s} Q{.2 * s},{y} {.38 * s},{y - .12 * s}' fill='none' stroke='{vein}' stroke-width='{vw}'/>")
        veins.append(f"<path d='M0,{y + .12 * s} Q{-.2 * s},{y} {-.38 * s},{y - .12 * s}' fill='none' stroke='{vein}' stroke-width='{vw}'/>")
    bite = ""
    if bites:
        for (bx, by, r) in ((.42, -.25, .14), (.4, .25, .12), (-.43, .05, .13)):
            bite += f"<circle cx='{bx * s}' cy='{by * s}' r='{r * s}' fill='{bg}'/>"
    return (f"<g transform='translate({cx},{cy}) rotate({angle})'><path d='{path}' fill='{col}'/>"
            f"{''.join(veins)}{bite}</g>")


def plant(cx, base, s, flower=True, roots=False):
    out = []
    if roots:
        out.append(f"<rect x='{cx - 1.6 * s}' y='{base}' width='{3.2 * s}' height='{1.2 * s}' fill='#C9AE8C'/>")
        for dx, dy in ((-.5, .9), (-.15, 1.05), (.2, 1.0), (.5, .8), (0, .7)):
            out.append(f"<path d='M{cx},{base} Q{cx + dx * .5 * s},{base + dy * .5 * s} {cx + dx * s},{base + dy * s}' "
                       f"fill='none' stroke='{SOIL}' stroke-width='{.05 * s}' stroke-linecap='round'/>")
        out.append(f"<path d='M{cx - .2 * s},{base + .2 * s} L{cx - 1.3 * s},{base + .35 * s}' stroke='#F1E6D0' "
                   f"stroke-width='{.09 * s}' stroke-linecap='round'/>")   # rizoma
    out.append(f"<path d='M{cx},{base} C{cx + .05 * s},{base - .8 * s} {cx - .05 * s},{base - 1.5 * s} {cx},{base - 2.1 * s}' "
               f"fill='none' stroke='{LEAF_D}' stroke-width='{.07 * s}'/>")
    for k, (dy, side) in enumerate(((.3, -1), (.55, 1), (.95, -1), (1.3, 1), (1.65, -1))):
        out.append(leaf(cx + side * .35 * s, base - dy * s, .32 * s * (1.2 - k * .1), angle=side * 55))
    if flower:
        fy = base - 2.2 * s
        for a in range(0, 360, 60):
            px, py = cx + math.cos(math.radians(a)) * .17 * s, fy + math.sin(math.radians(a)) * .17 * s
            out.append(f"<circle cx='{px}' cy='{py}' r='{.13 * s}' fill='#F2D04A'/>")
        out.append(f"<circle cx='{cx}' cy='{fy}' r='{.1 * s}' fill='#C98A1E'/>")
    return "".join(out)


def flower_close(cx, cy, s):
    out = []
    for a in range(0, 360, 45):
        px, py = cx + math.cos(math.radians(a)) * .55 * s, cy + math.sin(math.radians(a)) * .55 * s
        out.append(f"<ellipse cx='{px}' cy='{py}' rx='{.32 * s}' ry='{.2 * s}' fill='#F2D04A' "
                   f"transform='rotate({a} {px} {py})'/>")
    out.append(f"<circle cx='{cx}' cy='{cy}' r='{.32 * s}' fill='#C98A1E'/>")
    rnd = random.Random(5)
    for _ in range(14):
        out.append(f"<circle cx='{cx + rnd.uniform(-.2, .2) * s}' cy='{cy + rnd.uniform(-.2, .2) * s}' "
                   f"r='{.03 * s}' fill='#7A4E10'/>")
    return "".join(out)


def lesion(cx, cy, r, mold=False):
    out = [f"<circle cx='{cx}' cy='{cy}' r='{r * 1.35}' fill='#E8D86A' opacity='.85'/>",
           f"<circle cx='{cx}' cy='{cy}' r='{r}' fill='#7A4A26'/>",
           f"<circle cx='{cx}' cy='{cy}' r='{r * .55}' fill='#5A3218'/>"]
    rnd = random.Random(int(cx + cy))
    for _ in range(int(14 if mold else 6)):
        a, d = rnd.uniform(0, 6.28), rnd.uniform(0, r * .85)
        out.append(f"<circle cx='{cx + math.cos(a) * d}' cy='{cy + math.sin(a) * d}' r='{r * (.07 if mold else .06)}' "
                   f"fill='{'#D0D0C8' if mold else '#1A1A1A'}'/>")
    return "".join(out)


def larva(cx, cy, s, legs=True):
    """Gusano blanco en «C» (cabeza arriba a la derecha); con o sin las 3 pares de patas."""
    r = .6 * s
    sx, sy = cx + r * math.cos(math.radians(-60)), cy + r * math.sin(math.radians(-60))
    ex, ey = cx + r * math.cos(math.radians(60)), cy + r * math.sin(math.radians(60))
    out = [f"<path d='M{sx},{sy} A{r},{r} 0 1 0 {ex},{ey}' fill='none' stroke='#CDBE9C' "
           f"stroke-width='{.5 * s}' stroke-linecap='round'/>",
           f"<path d='M{sx},{sy} A{r},{r} 0 1 0 {ex},{ey}' fill='none' stroke='#F1E7D0' "
           f"stroke-width='{.44 * s}' stroke-linecap='round'/>"]
    for k in range(10):   # segmentos
        a = math.radians(-75 - k * 23)
        out.append(f"<line x1='{cx + math.cos(a) * .4 * s}' y1='{cy + math.sin(a) * .4 * s}' "
                   f"x2='{cx + math.cos(a) * .8 * s}' y2='{cy + math.sin(a) * .8 * s}' stroke='#D8C9A6' "
                   f"stroke-width='{.025 * s}'/>")
    if legs:
        for k in range(3):
            a = math.radians(-95 - k * 20)
            x1, y1 = cx + math.cos(a) * .38 * s, cy + math.sin(a) * .38 * s
            x2, y2 = cx + math.cos(a + .25) * .2 * s, cy + math.sin(a + .25) * .2 * s
            out.append(f"<line x1='{x1}' y1='{y1}' x2='{x2}' y2='{y2}' stroke='#B5651D' stroke-width='{.06 * s}' "
                       f"stroke-linecap='round'/>")
    out.append(f"<circle cx='{sx + .05 * s}' cy='{sy - .02 * s}' r='{.24 * s}' fill='#B5651D'/>")
    out.append(f"<circle cx='{sx + .14 * s}' cy='{sy + .02 * s}' r='{.045 * s}' fill='#3A1E08'/>")
    out.append(f"<path d='M{sx + .2 * s},{sy + .12 * s} l{.1 * s},{.06 * s}' stroke='#3A1E08' stroke-width='{.04 * s}'/>")
    return "".join(out)


def coin(cx, cy, r):
    return (f"<circle cx='{cx}' cy='{cy}' r='{r}' fill='#C8B06A' stroke='#9C8644' stroke-width='3'/>"
            f"<circle cx='{cx}' cy='{cy}' r='{r * .72}' fill='none' stroke='#9C8644' stroke-width='2'/>"
            f"<text x='{cx}' y='{cy + r * .3}' text-anchor='middle' {FONT} font-size='{r * .8}' "
            f"font-weight='bold' fill='#8A7438'>100</text>")


def sun(cx, cy, r):
    rays = "".join(f"<line x1='{cx + math.cos(math.radians(a)) * r * 1.3}' y1='{cy + math.sin(math.radians(a)) * r * 1.3}' "
                   f"x2='{cx + math.cos(math.radians(a)) * r * 1.8}' y2='{cy + math.sin(math.radians(a)) * r * 1.8}' "
                   f"stroke='#F2B33A' stroke-width='5' stroke-linecap='round'/>" for a in range(0, 360, 45))
    return rays + f"<circle cx='{cx}' cy='{cy}' r='{r}' fill='#F7C548'/>"


def cloud(cx, cy, s):
    return (f"<g fill='#DDE5EA'><circle cx='{cx - .5 * s}' cy='{cy}' r='{.45 * s}'/><circle cx='{cx + .1 * s}' "
            f"cy='{cy - .25 * s}' r='{.6 * s}'/><circle cx='{cx + .7 * s}' cy='{cy}' r='{.45 * s}'/>"
            f"<rect x='{cx - .5 * s}' y='{cy}' width='{1.2 * s}' height='{.45 * s}'/></g>")


def messy(x, y, w, h, seed=1):
    rnd = random.Random(seed)
    out = [f"<rect x='{x}' y='{y}' width='{w}' height='{h}' fill='#7FA265'/>"]
    for _ in range(70):
        px, py = rnd.uniform(x, x + w), rnd.uniform(y, y + h)
        col = rnd.choice(("#4E7A3A", "#9BBF6E", "#5E8C46", "#B8A06A", "#3E6A30"))
        out.append(f"<path d='M{px},{py} q{rnd.uniform(-20, 20)},{-rnd.uniform(20, 60)} {rnd.uniform(-30, 30)},"
                   f"{-rnd.uniform(40, 90)}' fill='none' stroke='{col}' stroke-width='{rnd.uniform(3, 7)}' "
                   f"stroke-linecap='round'/>")
    for _ in range(14):
        out.append(leaf(rnd.uniform(x, x + w), rnd.uniform(y, y + h), rnd.uniform(18, 30),
                        angle=rnd.uniform(0, 360), color=rnd.choice(("#6E9A50", "#A3B86B", "#567F3E"))))
    return "".join(out)


def blur_group(content):
    fid = uid("blur")
    return (f"<filter id='{fid}' x='-20%' y='-20%' width='140%' height='140%'><feGaussianBlur stdDeviation='7'/>"
            f"</filter><g filter='url(#{fid})'>{content}</g>")


def svg(w, h, body):
    return (f"<svg xmlns='http://www.w3.org/2000/svg' viewBox=\"0 0 {w} {h}\" width='{w}' height='{h}'>"
            f"<rect width='{w}' height='{h}' rx='26' fill='{BG}'/>{body}</svg>")


# ----------------------------------------------------------------- láminas
FW, FH = 380, 300


def pair(ok_content, bad_content, labels=("Así", "Así no"), badges=(True, False), bg=(FRAME_BG, FRAME_BG)):
    x1, x2, y = 40, 480, 30
    return svg(900, 410, frame(x1, y, FW, FH, ok_content, badges[0], labels[0], bg[0])
               + frame(x2, y, FW, FH, bad_content, badges[1], labels[1], bg[1]))


def row(contents, labels, w=900):
    n = len(contents)
    gap = 20
    fw = (w - 2 * 30 - gap * (n - 1)) / n
    fh = min(260, fw * 1.15)
    out = []
    for i, (cnt, lab) in enumerate(zip(contents, labels)):
        x = 30 + i * (fw + gap)
        out.append(frame(x, 30, fw, fh, cnt(x + fw / 2, 30 + fh / 2, fw), None, lab))
    return svg(w, int(fh + 100), "".join(out))


def sheets() -> dict[str, str]:
    C = (40 + FW / 2, 30 + FH / 2)
    D = (480 + FW / 2, 30 + FH / 2)
    out = {}
    out["g_enfoque"] = pair(beetle(*C, 85), blur_group(beetle(*D, 85)), ("Nítida", "Movida o borrosa"))
    out["g_luz"] = pair(
        cloud(C[0] + 100, 75, 55) + f"<ellipse cx='{C[0] + 8}' cy='{C[1] + 100}' rx='70' ry='14' fill='#000' opacity='.08'/>"
        + beetle(C[0], C[1] + 20, 70),
        sun(D[0] + 120, 80, 32) + f"<ellipse cx='{D[0] - 60}' cy='{D[1] + 95}' rx='110' ry='30' fill='#1B1B1B' "
        f"opacity='.55' transform='rotate(-20 {D[0] - 60} {D[1] + 95})'/>" + beetle(D[0], D[1] + 20, 70)
        + f"<circle cx='{D[0] + 20}' cy='{D[1] - 10}' r='26' fill='white' opacity='.85'/>",
        ("Sombra suave", "Sol directo o flash"))
    out["g_llenar"] = pair(beetle(C[0], C[1] + 15, 95), beetle(D[0] + 60, D[1] + 40, 18),
                           ("Que llene la foto", "Muy lejos"))
    out["g_fondo"] = pair(
        f"<rect x='{C[0] - 150}' y='{C[1] - 115}' width='300' height='235' rx='6' fill='white' "
        f"stroke='#DDD' transform='rotate(-4 {C[0]} {C[1]})'/>" + beetle(C[0], C[1] + 15, 70, spots=True),
        messy(480, 30, FW, FH) + beetle(D[0], D[1] + 15, 70),
        ("Fondo simple", "Fondo recargado"))
    out["g_escala"] = pair(beetle(C[0] - 55, C[1] + 15, 70) + coin(C[0] + 105, C[1] + 60, 38)
                           + f"<rect x='{C[0] - 170}' y='{C[1] + 115}' width='340' height='26' fill='#F3E3A0' stroke='#C9B36A'/>"
                           + "".join(f"<line x1='{C[0] - 170 + k * 17}' y1='{C[1] + 115}' x2='{C[0] - 170 + k * 17}' "
                                     f"y2='{C[1] + (127 if k % 5 else 135)}' stroke='#8A7438' stroke-width='2'/>"
                                     for k in range(21)),
                           beetle(D[0], D[1] + 15, 70), ("Con moneda o regla", "Sin escala"))
    out["g_contexto"] = pair(plant(C[0], C[1] + 120, 95) + beetle(C[0] + 40, C[1] - 40, 16, spots=False),
                             leaf(D[0], D[1], 120) + beetle(D[0] + 10, D[1] - 10, 20, spots=False),
                             ("La planta y el lugar", "Solo el detalle"), badges=(None, None))
    # --- plagas
    out["p_set"] = row([lambda x, y, w: beetle(x, y + 15, w * .26),
                        lambda x, y, w: beetle(x + 10, y + 5, w * .24, "lateral"),
                        lambda x, y, w: beetle(x, y + 15, w * .26, "ventral"),
                        lambda x, y, w: leaf(x, y, w * .38, bites=True)],
                       ["Dorsal", "Lateral", "Ventral", "Daño"])
    out["p_larva"] = pair(larva(C[0] - 15, C[1] + 12, 150, True), larva(D[0] - 15, D[1] + 12, 150, False),
                          ("Con patas: pololo", "Sin patas: gorgojo"), badges=(None, None))
    jar = (f"<rect x='{C[0] - 80}' y='{C[1] - 70}' width='160' height='180' rx='22' fill='#E4F1F6' stroke='#9FB8C2' stroke-width='4'/>"
           f"<rect x='{C[0] - 90}' y='{C[1] - 95}' width='180' height='32' rx='8' fill='#9FB8C2'/>"
           + beetle(C[0], C[1] + 30, 40, spots=False)
           + "".join(f"<line x1='{C[0] + 120}' y1='{C[1] - 60}' x2='{C[0] + 120 + math.cos(math.radians(a)) * 34}' "
                     f"y2='{C[1] - 60 + math.sin(math.radians(a)) * 34}' stroke='#5FA8D3' stroke-width='6' "
                     f"stroke-linecap='round'/>" for a in range(0, 360, 60)))
    paper = (f"<rect x='{D[0] - 140}' y='{D[1] - 105}' width='280' height='220' fill='white' stroke='#DDD'/>"
             + beetle(D[0], D[1] + 15, 65))
    out["p_frio"] = pair(jar, paper, ("5 min al refrigerador", "Luego sobre papel"),
                         badges=(None, True))
    out["p_dano"] = pair(leaf(C[0] - 60, C[1], 110, bites=True, angle=-15) + beetle(C[0] + 90, C[1] + 40, 38),
                         leaf(D[0], D[1], 120, bites=True, angle=10),
                         ("Insecto y su daño", "Solo el daño"), badges=(None, None))
    # --- malezas
    out["m_set"] = row([lambda x, y, w: plant(x, y + w * .5, w * .22),
                        lambda x, y, w: leaf(x, y, w * .4),
                        lambda x, y, w: leaf(x, y, w * .4, under=True),
                        lambda x, y, w: flower_close(x, y, w * .36)],
                       ["Planta completa", "Hoja (haz)", "Hoja (envés)", "Flor / semilla"])
    out["m_raiz"] = pair(plant(C[0], C[1] + 30, 70, roots=True), plant(D[0], D[1] + 140, 95),
                         ("Con raíz o base", "Solo lo de arriba"), badges=(True, None))
    blade = (f"<path d='M{C[0] - 18},{C[1] + 150} L{C[0] - 18},{C[1] - 20} L{C[0] + 18},{C[1] - 20} L{C[0] + 18},{C[1] + 150} Z' fill='{LEAF}'/>"
             f"<path d='M{C[0] + 10},{C[1] - 10} Q{C[0] + 120},{C[1] - 80} {C[0] + 150},{C[1] - 150} L{C[0] + 125},{C[1] - 150} "
             f"Q{C[0] + 95},{C[1] - 85} {C[0] - 10},{C[1] - 25} Z' fill='{LEAF_D}'/>"
             f"<path d='M{C[0] - 20},{C[1] - 22} Q{C[0]},{C[1] - 55} {C[0] + 22},{C[1] - 22} Z' fill='#F2F5EC' stroke='#C9D6C4' stroke-width='2'/>"
             f"<path d='M{C[0] - 18},{C[1] - 15} q-30,8 -36,-14' fill='none' stroke='{LEAF_D}' stroke-width='6' stroke-linecap='round'/>"
             f"<circle cx='{C[0]}' cy='{C[1] - 35}' r='62' fill='none' stroke='{BAD}' stroke-width='4' stroke-dasharray='10 8'/>")
    spike = "".join(f"<ellipse cx='{D[0] + (12 if k % 2 else -12)}' cy='{D[1] - 110 + k * 26}' rx='12' ry='22' "
                    f"fill='#B9B26A' transform='rotate({25 if k % 2 else -25} {D[0] + (12 if k % 2 else -12)} {D[1] - 110 + k * 26})'/>"
                    for k in range(8)) + f"<line x1='{D[0]}' y1='{D[1] - 130}' x2='{D[0]}' y2='{D[1] + 150}' stroke='{LEAF_D}' stroke-width='6'/>"
    out["m_graminea"] = pair(blade, spike, ("Unión hoja-tallo", "La espiga"), badges=(None, None))
    # --- enfermedades
    sick = (leaf(C[0], C[1], 125) + lesion(C[0] - 25, C[1] - 30, 22) + lesion(C[0] + 30, C[1] + 45, 16))
    zoom = (f"<rect x='480' y='30' width='{FW}' height='{FH}' fill='{LEAF}'/>"
            + lesion(D[0] - 30, D[1], 90)
            + f"<path d='M{D[0] + 90},{30} Q{D[0] + 120},{D[1]} {D[0] + 60},{30 + FH}' fill='none' stroke='{LEAF_D}' stroke-width='10'/>")
    out["e_set"] = pair(sick, zoom, ("Órgano completo", "Detalle de la lesión"), badges=(None, None))
    out["e_borde"] = pair(
        f"<rect x='40' y='30' width='{FW}' height='{FH}' fill='{LEAF}'/>" + lesion(C[0] - 40, C[1], 85),
        f"<rect x='480' y='30' width='{FW}' height='{FH}' fill='#5A3218'/>" + lesion(D[0], D[1], 260),
        ("Con borde sano", "Solo lo podrido"))
    mag = (f"<rect x='40' y='30' width='{FW}' height='{FH}' fill='{LEAF}'/>" + lesion(C[0] - 50, C[1] + 20, 70, mold=True)
           + f"<circle cx='{C[0] + 70}' cy='{C[1] - 40}' r='75' fill='white' stroke='{INK}' stroke-width='8'/>"
           + f"<line x1='{C[0] + 125}' y1='{C[1] + 15}' x2='{C[0] + 175}' y2='{C[1] + 70}' stroke='{INK}' stroke-width='16' stroke-linecap='round'/>"
           + "".join(f"<circle cx='{C[0] + 70 + dx}' cy='{C[1] - 40 + dy}' r='7' fill='#B0B0A8'/>"
                     f"<line x1='{C[0] + 70 + dx}' y1='{C[1] - 40 + dy}' x2='{C[0] + 70 + dx}' y2='{C[1] - 40 + dy + 18}' stroke='#B0B0A8' stroke-width='3'/>"
                     for dx, dy in ((-30, -20), (0, -35), (25, -10), (-15, 15), (30, 25), (-40, 20))))
    roots = (f"<rect x='480' y='{30 + FH * .55}' width='{FW}' height='{FH * .45}' fill='#C9AE8C'/>"
             f"<rect x='{D[0] - 110}' y='{D[1] - 60}' width='70' height='190' rx='14' fill='#7A5A3A'/>"
             f"<rect x='{D[0] - 100}' y='{D[1] - 40}' width='50' height='140' rx='10' fill='#9A4A2A'/>"
             f"<rect x='{D[0] + 40}' y='{D[1] - 60}' width='70' height='190' rx='14' fill='#7A5A3A'/>"
             f"<rect x='{D[0] + 50}' y='{D[1] - 40}' width='50' height='140' rx='10' fill='#F4EEDC'/>"
             f"<text x='{D[0] - 75}' y='{D[1] - 80}' text-anchor='middle' {FONT} font-size='20' fill='{BAD}' font-weight='bold'>enferma</text>"
             f"<text x='{D[0] + 75}' y='{D[1] - 80}' text-anchor='middle' {FONT} font-size='20' fill='{OK}' font-weight='bold'>sana</text>")
    out["e_moho_raiz"] = pair(mag, roots, ("Moho: muy de cerca", "Cuello cortado"),
                              badges=(None, None))
    return out


def main():
    os.makedirs(TMP, exist_ok=True)
    os.makedirs(OUT, exist_ok=True)
    files = []
    for name, data in sheets().items():
        p = os.path.join(TMP, name + ".svg")
        with open(p, "w", encoding="utf-8") as f:
            f.write(data)
        files.append(p)
    subprocess.run(["node", os.path.join(ROOT, "tools", "render_svgs.js"), "900", OUT, *files], check=True)
    from PIL import Image
    for f in files:   # PNG con paleta: livianos
        png = os.path.join(OUT, os.path.basename(f)[:-4] + ".png")
        im = Image.open(png).convert("RGBA")
        im.quantize(colors=128, method=Image.Quantize.FASTOCTREE).save(png, optimize=True)
    print("listo:", OUT, len(files))


if __name__ == "__main__":
    main()
    sys.exit(0)
