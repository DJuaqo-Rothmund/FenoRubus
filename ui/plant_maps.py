"""
ui/plant_maps.py
================
Mapas del módulo Plantas (ver plantas.py):

* `RowMap`  — el plano del predio (sectores con la paleta de Predio, fondo satelital) con
  TODAS las hileras del campo encima, cada una con el tono de su sector. Al acercar
  aparecen los números; tocar una hilera la elige (`on_row`), tocar fuera de las hileras
  elige el sector (`on_sector`). «Destacar ensayos» las pinta en su color con brillo y
  rótulo; «Por revisar» las marca con borde rojo punteado.
* `PlantMap` — las hileras de un ensayo en columnas, de sur (abajo, 0 m) a norte, con cada
  hoyo en su metro: plantas (color por variedad, estado o medición), fallas, separaciones,
  eliminadas y los drenajes como franjas azules. Se arrastra y se pellizca a lo largo;
  tocar una planta la elige (`on_plant`).
"""
from __future__ import annotations

import math
import zlib

from kivy.clock import Clock
from kivy.core.text import Label as CoreLabel
from kivy.graphics import Color, Ellipse, Line, Mesh, Rectangle, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.properties import BooleanProperty, DictProperty, ListProperty, NumericProperty, StringProperty
from kivy.uix.stencilview import StencilView

from ui.sector_map import SectorMap, _hex, sector_color

TRIAL_COLOR = "#E0306A"
REVIEW_RED = "#FF4D4D"
_TEX: dict = {}


def text_tex(text: str, size: float = 10, bold: bool = True, color=(1, 1, 1, 1)):
    key = (text, size, bold, tuple(color))
    if key not in _TEX:
        lb = CoreLabel(text=text, font_size=sp(size), bold=bold, color=color)
        lb.refresh()
        _TEX[key] = lb.texture
    return _TEX[key]


def _quads(segs, width):
    """[(x0, y0, x1, y1)…] -> vértices e índices de cuadriláteros de ese ancho (en pantalla)."""
    verts, idx, hw = [], [], width / 2
    for x0, y0, x1, y1 in segs:
        dx, dy = x1 - x0, y1 - y0
        ln = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / ln * hw, dx / ln * hw
        n = len(verts) // 4
        verts += [x0 + nx, y0 + ny, 0, 0, x0 - nx, y0 - ny, 0, 0, x1 - nx, y1 - ny, 0, 0, x1 + nx, y1 + ny, 0, 0]
        idx += [n, n + 1, n + 2, n, n + 2, n + 3]
    return verts, idx


def _mesh(segs, width):
    # Un Mesh admite hasta 65 535 vértices: se parte en trozos.
    for k in range(0, len(segs), 12000):
        v, i = _quads(segs[k:k + 12000], width)
        if v:
            Mesh(vertices=v, indices=i, mode="triangles")


# ================================================================== hileras del campo
class RowMap(SectorMap):
    rows = ListProperty()                # plantas.PlantDB.field_rows(...)
    highlight = BooleanProperty(True)    # «Destacar ensayos»
    trials_on = ListProperty()           # códigos de ensayo a destacar ([] = todos)
    trial_colors = DictProperty()        # código -> color
    trial_names = DictProperty()         # código -> nombre
    review = BooleanProperty(False)      # «Por revisar»
    selected_row = StringProperty("")
    MAX_ZOOM = 160.0

    def __init__(self, plan, on_row=None, on_sector=None, **kw):
        super().__init__(plan, on_select=on_sector, zoomable=True, **kw)
        self.on_row = on_row
        self.fill_k = .4
        self.bind(rows=self._redraw, highlight=self._redraw, trials_on=self._redraw, review=self._redraw,
                  selected_row=self._redraw, trial_colors=self._redraw)

    def _max_zoom(self) -> float:            # hasta ver hilera por hilera (la imagen se amplía)
        return self.MAX_ZOOM

    def _texture(self, sid, text=None):
        """Rótulo del sector: su número en la vista general (como Predio) y «E2-S1» al acercar."""
        if text is None and self.zoom >= 2.5:
            text = sid
        return super()._texture(sid, text)

    def _px_per_m(self) -> float:
        return self._base() * self.zoom

    def _lit(self, r) -> bool:
        return bool(self.highlight and r["trial"] and (not self.trials_on or r["trial"] in self.trials_on))

    def _overlay(self, ts):
        if not self.rows:
            return
        s = self._px_per_m()
        w, h = self.size
        spacing = 3.0 * s                       # px entre hileras (cada ~3 m)
        width = max(dp(.7), min(dp(4), spacing * .42))
        groups: dict = {}
        lit, rev, hidden = [], [], []
        pad = dp(20)
        for r in self.rows:
            x0, y0 = ts(r["x0"], r["y0"])
            x1, y1 = ts(r["x1"], r["y1"])
            if max(x0, x1) < -pad or min(x0, x1) > w + pad or max(y0, y1) < -pad or min(y0, y1) > h + pad:
                continue
            seg = (x0, y0, x1, y1)
            if r["hidden"]:
                hidden.append(seg)
                continue
            groups.setdefault((r["e"], r["s"]), []).append(seg)
            if self._lit(r):
                lit.append((r, seg))
            if self.review and r["rev"]:
                rev.append(seg)
        dim = self.highlight and any(self._lit(r) for r in self.rows)
        for (e, se), segs in groups.items():
            rgba, _light = sector_color(e, se)
            Color(*rgba[:3], .55 if dim else (.6 if self.review else .95))
            _mesh(segs, width)
        if self.review and hidden:
            Color(1, 1, 1, .25)
            _mesh(hidden, width)
        # Ensayos: brillo + núcleo en su color, y su nombre en la cabecera norte.
        names: dict = {}
        for r, seg in lit:
            col = _hex(self.trial_colors.get(r["trial"], TRIAL_COLOR))
            Color(*col, .35)
            _mesh([seg], width * 4 + dp(4))
            Color(*col, 1)
            _mesh([seg], max(width * 1.3, dp(1.6)))
            top = max(seg[1], seg[3])
            cx = (seg[0] + seg[2]) / 2
            prev = names.get(r["trial"])
            if prev is None or top > prev[1]:
                names[r["trial"]] = (cx, top)
        # Por revisar: borde rojo punteado (sin tapar el color del sector).
        if rev:
            dash, gap = dp(5), dp(4)
            pieces = []
            for x0, y0, x1, y1 in rev:
                ln = math.hypot(x1 - x0, y1 - y0)
                if ln < 1:
                    continue
                ux, uy = (x1 - x0) / ln, (y1 - y0) / ln
                t = 0.0
                while t < ln:
                    t1 = min(ln, t + dash)
                    pieces.append((x0 + ux * t, y0 + uy * t, x0 + ux * t1, y0 + uy * t1))
                    t = t1 + gap
            Color(*_hex(REVIEW_RED), 1)
            _mesh(pieces, max(width * 1.1, dp(1.8)))
        # Hilera elegida: halo blanco.
        sel = next((r for r in self.rows if r["key"] == self.selected_row), None)
        if sel is not None:
            x0, y0 = ts(sel["x0"], sel["y0"])
            x1, y1 = ts(sel["x1"], sel["y1"])
            Color(1, 1, 1, .45)
            _mesh([(x0, y0, x1, y1)], width * 3 + dp(8))
            Color(1, 1, 1, 1)
            _mesh([(x0, y0, x1, y1)], max(width, dp(2)))
        # Números de hilera al acercar (al pie, cabecera sur).
        if spacing >= dp(15) or sel is not None:
            for r in self.rows:
                if r["hidden"] or (spacing < dp(15) and r is not sel):
                    continue
                x0, y0 = ts(r["x0"], r["y0"])
                if r is sel and not -pad < y0 < h + pad:
                    x0, y0 = ts(r["x1"], r["y1"])
                    y0 += dp(18)
                if not (-pad < x0 < w + pad and -pad < y0 < h + pad):
                    continue
                tex = text_tex(r["label"], 9 if r is not sel else 11)
                Color(0, 0, 0, .55)
                Rectangle(texture=tex, size=tex.size, pos=(x0 - tex.width / 2 + dp(1), y0 - tex.height - dp(3)))
                Color(*((1, 1, 1, 1) if not r["rev"] or not self.review else _hex("#FFD0D0") + [1]))
                Rectangle(texture=tex, size=tex.size, pos=(x0 - tex.width / 2, y0 - tex.height - dp(2)))
        for code, (cx, top) in names.items():
            tex = text_tex(self.trial_names.get(code, code), 10.5)
            bw, bh = tex.width + dp(14), tex.height + dp(8)
            bx, by = cx - bw / 2, top + dp(8)
            Color(*_hex(self.trial_colors.get(code, TRIAL_COLOR)), 1)
            RoundedRectangle(pos=(bx, by), size=(bw, bh), radius=[dp(8)])
            Mesh(vertices=[cx - dp(5), by, 0, 0, cx + dp(5), by, 0, 0, cx, by - dp(6), 0, 0],
                 indices=[0, 1, 2], mode="triangles")
            Color(1, 1, 1, 1)
            Line(rounded_rectangle=(bx, by, bw, bh, dp(8)), width=dp(1))
            Rectangle(texture=tex, size=tex.size, pos=(bx + dp(7), by + dp(4)))

    # ------------------------------------------------------------------ toques
    def row_at(self, sx, sy):
        """Hilera bajo el dedo (si se ve lo bastante separada), o None."""
        s = self._px_per_m()
        if 3.0 * s < dp(3.5):
            return None
        best, dist = None, max(dp(9), 3.0 * s * .5)
        for r in self.rows:
            if r["hidden"] and not self.review:
                continue
            x0, y0 = self.to_screen(r["x0"], r["y0"])
            x1, y1 = self.to_screen(r["x1"], r["y1"])
            lo, hi = min(y0, y1) - dp(8), max(y0, y1) + dp(8)
            if not lo <= sy <= hi:
                continue
            t = 0 if y1 == y0 else (sy - y0) / (y1 - y0)
            x = x0 + (x1 - x0) * max(0.0, min(1.0, t))
            d = abs(sx - x)
            if d < dist:
                best, dist = r, d
        return best

    def on_touch_up(self, touch):
        if touch.grab_current is not self:
            return False
        touch.ungrab(self)
        multi = touch.uid in self._multi
        self._multi.discard(touch.uid)
        self._touches.pop(touch.uid, None)
        if len(self._touches) < 2:
            self._pinch = None
        start = touch.ud.get("sector_map_start", touch.pos)
        if multi or math.hypot(touch.x - start[0], touch.y - start[1]) > dp(12):
            return True
        if touch.is_double_tap:
            self._zoom_at(2.5, touch.pos)
            return True
        r = self.row_at(*touch.pos)
        if r is not None:
            self.selected_row = r["key"]
            if self.on_row:
                self.on_row(r)
            return True
        sid = self.sector_at(*touch.pos)
        if sid:
            self.selected = sid
            self.selected_row = ""
            if self.on_select:
                self.on_select(sid)
        return True

    def focus_row(self, r, span: float = .62):
        """Acerca la hilera hasta ocupar ~62 % del alto y la centra."""
        if not self.width or not self.height:
            Clock.schedule_once(lambda *_: self.focus_row(r, span), 0)
            return
        length = math.hypot(r["x1"] - r["x0"], r["y1"] - r["y0"]) or 50
        base = self._base()
        target = max(1.0, min(self._max_zoom(), span * self.height / (length * base)))
        target = max(target, dp(18) / (3.0 * base))      # que se vean los números
        mw, mh = self._dims()
        cx, cy = (r["x0"] + r["x1"]) / 2, (r["y0"] + r["y1"]) / 2
        self.focused = ""
        self.zoom = target
        s = base * target
        self._pan = [-(cx - mw / 2) * s, -(cy - mh / 2) * s]
        self.selected_row = r["key"]
        self._redraw()


# ================================================================== plantas de un ensayo
VAR_COLORS = {"cascade harvest": "#26A69A", "wakefield": "#7CB342", "meeker": "#5C8DD6", "lagorai": "#E57373",
              "#11": "#F0A04B", "#24": "#A1887F", "#31": "#9575CD", "#55": "#F06292", "#81": "#C9A400"}
_PALETTE = ["#26A69A", "#7CB342", "#5C8DD6", "#E57373", "#F0A04B", "#9575CD", "#F06292", "#C9A400",
            "#8D6E63", "#00ACC1", "#AB47BC", "#66BB6A"]
STATUS_COLORS = {"": "#43A047", "muerta": "#37474F", "replante": "#00ACC1"}
EVENT_COLORS = {"enfermedad": "#8E24AA", "plaga": "#E65100", "dano": "#6D4C41", "poda": "#43A047",
                "nota": "#43A047", "replante": "#00ACC1", "muerta": "#37474F"}


def var_color(name: str) -> str:
    key = (name or "").strip().lower()
    if key in VAR_COLORS:
        return VAR_COLORS[key]
    return _PALETTE[zlib.crc32(key.encode()) % len(_PALETTE)]


def value_color(v, lo, hi):
    """Verde claro (poco) → verde oscuro (mucho)."""
    if v is None:
        return "#C9CFC4"
    t = 0 if hi <= lo else max(0.0, min(1.0, (v - lo) / (hi - lo)))
    a, b = _hex("#D7EFC6"), _hex("#1B5E20")
    r = [x + (y - x) * t for x, y in zip(a, b)]
    return "#%02x%02x%02x" % tuple(int(x * 255) for x in r)


class PlantMap(StencilView):
    """Hileras del ensayo en columnas (sur abajo). rows = [{label, field_n, segments, plants}]."""
    mode = StringProperty("variedad")         # variedad · estado · <clave de medición>
    values = DictProperty()                   # {plant_id: valor} (modo medición)
    events = DictProperty()                   # {plant_id: último evento} (modo estado)
    selected = NumericProperty(0)
    k = NumericProperty(1.5)                  # px por metro

    def __init__(self, rows, on_plant=None, **kw):
        super().__init__(**kw)
        self.rows = rows
        self.on_plant = on_plant
        self.length = max([p["pos"] for r in rows for p in r["plants"]] + [r.get("largo") or 0 for r in rows]
                          + [10]) + 1.5
        self.off = 0.0                        # metro en el borde inferior del área de dibujo
        self._touches: dict = {}
        self._pinch = None
        self._multi: set = set()
        self._fit = True
        self._redraw = Clock.create_trigger(self._draw, -1)
        self.bind(size=self._on_size, pos=self._redraw, mode=self._redraw, values=self._redraw,
                  events=self._redraw, selected=self._redraw, k=self._redraw)

    # ------------------------------------------------------------ geometría
    TOP, BOTTOM = dp(34), dp(26)

    def _area_h(self):
        return max(1.0, self.height - self.TOP - self.BOTTOM)

    def _min_k(self):
        return self._area_h() / self.length

    def _max_k(self):
        return dp(36) / .7

    def _on_size(self, *_):
        if self._fit or self.k < self._min_k():
            self.k = self._min_k()
            self.off = 0.0
        self._clamp()
        self._redraw()

    def _clamp(self):
        vis = self._area_h() / self.k
        self.off = max(-1.0, min(self.off, self.length - vis + 1.0)) if vis < self.length else 0.0

    def col_x(self, i):
        n = len(self.rows)
        return self.x + self.width * (i + 1) / (n + 1)

    def y_of(self, m):
        return self.y + self.BOTTOM + (m - self.off) * self.k

    def m_of(self, y):
        return (y - self.y - self.BOTTOM) / self.k + self.off

    def _radius(self):
        return max(dp(1.4), min(dp(12), self.k * .7 * .46))

    def color_of(self, p) -> str | None:
        if p["kind"] != "planta":
            return None
        if self.mode == "variedad":
            return var_color(p["variety"])
        if self.mode == "estado":
            if p["status"] == "muerta":
                return STATUS_COLORS["muerta"]
            ev = self.events.get(p["id"])
            if ev and ev["kind"] in ("enfermedad", "plaga", "dano"):
                return EVENT_COLORS[ev["kind"]]
            return STATUS_COLORS.get(p["status"], STATUS_COLORS[""])
        lo, hi = getattr(self, "_range", (0, 1))
        return value_color(self.values.get(p["id"]), lo, hi)

    # ------------------------------------------------------------ dibujo
    def _draw(self, *_):
        self.canvas.clear()
        if not self.width or not self.height:
            return
        k, r = self.k, self._radius()
        vals = [v for v in self.values.values() if v is not None]
        self._range = (min(vals), max(vals)) if vals else (0, 1)
        lo_m, hi_m = self.m_of(self.y) - 2, self.m_of(self.top) + 2
        with self.canvas:
            Color(*_hex("#EEEBE2"), 1)
            Rectangle(pos=self.pos, size=self.size)
            # Regla de metros a la izquierda.
            step = next(s for s in (1, 2, 5, 10, 20, 50, 100) if s * k >= dp(38))
            m = math.ceil(max(0.0, lo_m) / step) * step
            while m <= min(hi_m, self.length):
                y = self.y_of(m)
                Color(*_hex("#D9D4C6"), 1)
                Line(points=[self.x + dp(34), y, self.right - dp(6), y], width=dp(.6), dash_length=dp(3),
                     dash_offset=dp(3))
                tex = text_tex(f"{int(m)} m", 8.5, False, (.42, .47, .44, 1))
                Rectangle(texture=tex, size=tex.size, pos=(self.x + dp(4), y - tex.height / 2))
                m += step
            for i, row in enumerate(self.rows):
                x = self.col_x(i)
                Color(*_hex("#D9D4C6"), 1)
                Line(points=[x, self.y_of(0), x, self.y_of(self.length - 1.5)], width=dp(1))
                # Tramos: drenajes (franja azul) y eliminados (gris).
                for sg in row.get("segments", []):
                    if sg["d1"] < lo_m or sg["d0"] > hi_m:
                        continue
                    y0, y1 = self.y_of(sg["d0"]), self.y_of(sg["d1"])
                    if sg["kind"] == "drenaje":
                        Color(*_hex("#64B5F6"), .9)
                        Rectangle(pos=(x - r * 1.9 - dp(4), y0), size=(r * 3.8 + dp(8), max(dp(2), y1 - y0)))
                    elif sg["kind"] == "eliminada":
                        Color(*_hex("#B8B0A2"), .35)
                        Rectangle(pos=(x - r * 1.5 - dp(2), y0), size=(r * 3 + dp(4), y1 - y0))
                for p in row["plants"]:
                    if not lo_m <= p["pos"] <= hi_m:
                        continue
                    y = self.y_of(p["pos"])
                    col = self.color_of(p)
                    if col is None:          # falla / separación / eliminada: aro gris
                        Color(*_hex("#8F978F"), .9 if p["kind"] == "falla" else .45)
                        Line(circle=(x, y, max(dp(1.2), r * .85)), width=dp(1) if r > dp(4) else dp(.7))
                        continue
                    Color(*_hex(col), 1)
                    Ellipse(pos=(x - r, y - r), size=(2 * r, 2 * r))
                    if p["status"] == "muerta" and r >= dp(5):
                        Color(1, 1, 1, .9)
                        Line(points=[x - r * .5, y - r * .5, x + r * .5, y + r * .5], width=dp(1))
                        Line(points=[x - r * .5, y + r * .5, x + r * .5, y - r * .5], width=dp(1))
                    elif r >= dp(5.5):
                        tex = text_tex(str(p["num"]), (7.5 if p["num"] < 100 else 6.5) * min(1.25, r / dp(6.5)))
                        Color(1, 1, 1, 1)
                        Rectangle(texture=tex, size=tex.size, pos=(x - tex.width / 2, y - tex.height / 2))
                    if p["id"] == self.selected:
                        Color(*_hex("#A8184A"), 1)
                        Line(circle=(x, y, r + dp(4)), width=dp(2))
                # Rótulos de tramo (variedad · bloque y su rango de plantas) donde caben.
                self._tramo_labels(row, x, r, lo_m, hi_m, left=i % 2 == 0)
            # Cabecera: hilera del campo y etiqueta del ensayo.
            Color(*_hex("#EEEBE2"), .92)
            Rectangle(pos=(self.x, self.top - self.TOP), size=(self.width, self.TOP))
            for i, row in enumerate(self.rows):
                tex = text_tex(f"{row.get('field_n') or ''}  ·  {row['label']}", 11, True, _hex("#1E4A3A") + [1])
                Color(1, 1, 1, 1)
                Rectangle(texture=tex, size=tex.size, pos=(self.col_x(i) - tex.width / 2, self.top - self.TOP + dp(9)))
            Color(*_hex("#EEEBE2"), .92)
            Rectangle(pos=self.pos, size=(self.width, self.BOTTOM))
            tex = text_tex("Cabecera sur (0 m) · planta 1 abajo", 9, True, _hex("#41534A") + [1])
            Color(1, 1, 1, 1)
            Rectangle(texture=tex, size=tex.size, pos=(self.center_x - tex.width / 2, self.y + dp(6)))

    def _tramo_labels(self, row, x, r, lo_m, hi_m, left: bool):
        groups = []
        for p in row["plants"]:
            if p["kind"] not in ("planta", "falla"):
                if groups and groups[-1]["open"]:
                    groups[-1]["open"] = p["kind"] == "falla"
                continue
            key = (p["variety"], p["bloque"])
            if groups and groups[-1]["key"] == key and p["pos"] - groups[-1]["hi"] < 3:
                g = groups[-1]
                g["hi"] = p["pos"]
                if p["kind"] == "planta":
                    g["nums"].append(p["num"])
            else:
                groups.append({"key": key, "lo": p["pos"], "hi": p["pos"], "open": True,
                               "nums": [p["num"]] if p["kind"] == "planta" else []})
        from plantas import short_var
        for g in groups:
            if g["hi"] < lo_m or g["lo"] > hi_m or not g["nums"]:
                continue
            h = (g["hi"] - g["lo"]) * self.k
            if h < dp(26):
                continue
            var, bloque = g["key"]
            txt = f"{short_var(var)}·B{bloque}" + (f"  {min(g['nums'])}–{max(g['nums'])}" if h > dp(60) else "")
            tex = text_tex(txt, 9, True, _hex("#41534A") + [1])
            mid = (max(g["lo"], lo_m) + min(g["hi"], hi_m)) / 2
            y = self.y_of(mid) - tex.height / 2
            px = x - r - dp(8) - tex.width if left else x + r + dp(8)
            Color(1, 1, 1, 1)
            Rectangle(texture=tex, size=tex.size, pos=(px, y))

    # ------------------------------------------------------------ acciones
    def focus_plant(self, p, window_m: float = 20.0):
        self._fit = False
        self.k = max(self._min_k(), min(self._max_k(), self._area_h() / window_m))
        self.off = p["pos"] - window_m / 2
        self._clamp()
        self.selected = p["id"]
        self._redraw()

    def plant_at(self, sx, sy):
        r = max(self._radius(), dp(10))
        best, dist = None, None
        for i, row in enumerate(self.rows):
            x = self.col_x(i)
            if abs(sx - x) > max(dp(34), r * 2):
                continue
            for p in row["plants"]:
                d = abs(self.y_of(p["pos"]) - sy)
                if d <= max(r, self.k * .35) and (dist is None or d < dist):
                    best, dist = p, d
        return best

    def _zoom_at(self, f, y):
        m = self.m_of(y)
        self._fit = False
        self.k = max(self._min_k(), min(self._max_k(), self.k * f))
        self.off = m - (y - self.y - self.BOTTOM) / self.k
        self._clamp()
        self._redraw()

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return False
        if touch.is_mouse_scrolling:
            self._zoom_at(1.15 if touch.button == "scrolldown" else 1 / 1.15, touch.y)
            return True
        touch.grab(self)
        self._touches[touch.uid] = list(touch.pos)
        touch.ud["pm_start"] = touch.pos
        if len(self._touches) == 2:
            (a, b) = list(self._touches.values())[:2]
            self._pinch = abs(a[1] - b[1]) + abs(a[0] - b[0]) * .3 or 1.0
            self._multi |= set(self._touches)
        return True

    def on_touch_move(self, touch):
        if touch.grab_current is not self or touch.uid not in self._touches:
            return False
        prev = self._touches[touch.uid]
        self._touches[touch.uid] = list(touch.pos)
        if len(self._touches) >= 2 and self._pinch:
            (a, b) = list(self._touches.values())[:2]
            d = abs(a[1] - b[1]) + abs(a[0] - b[0]) * .3 or 1.0
            self._zoom_at(d / self._pinch, (a[1] + b[1]) / 2)
            self._pinch = d
        else:
            self._fit = False
            self.off -= (touch.y - prev[1]) / self.k
            self._clamp()
            self._redraw()
        return True

    def on_touch_up(self, touch):
        if touch.grab_current is not self:
            return False
        touch.ungrab(self)
        multi = touch.uid in self._multi
        self._multi.discard(touch.uid)
        self._touches.pop(touch.uid, None)
        if len(self._touches) < 2:
            self._pinch = None
        start = touch.ud.get("pm_start", touch.pos)
        if multi or math.hypot(touch.x - start[0], touch.y - start[1]) > dp(10):
            return True
        if touch.is_double_tap:
            self._zoom_at(2.5, touch.y)
            return True
        p = self.plant_at(*touch.pos)
        if p is not None:
            self.selected = p["id"]
            if self.on_plant:
                self.on_plant(p)
        return True
