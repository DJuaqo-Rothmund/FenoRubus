"""
ui/sector_map.py
================
Mapa de sectores de un predio (vista previa «Por sector»).

* `load_map(code)`: el plano del predio (`assets/maps/<código>.json`, hecho con
  `tools/make_maps.py`) o None si ese predio no tiene plano.
* `SectorMap`: dibuja los sectores (polígonos cóncavos teselados), los pinta según su
  estado y los selecciona al tocarlos. Con `zoomable` se acerca con dos dedos y se mueve
  con uno (vista a pantalla completa); con `rotate` el plano gira 90° para aprovechar
  una pantalla vertical (el norte queda a la derecha).
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from kivy.clock import Clock
from kivy.core.text import Label as CoreLabel
from kivy.graphics import Color, Ellipse, Line, Mesh, PopMatrix, PushMatrix, Rectangle, Translate
from kivy.graphics.tesselator import TYPE_POLYGONS, WINDING_ODD, Tesselator
from kivy.metrics import dp, sp
from kivy.properties import BooleanProperty, DictProperty, NumericProperty, StringProperty
from kivy.uix.stencilview import StencilView

from ui import theme
from ui.theme import c

# Relleno por macroestadio BBCH (más intenso que las fichas, para leerse en el plano):
# (color, texto claro encima).
MAP_STAGE = {
    0: ("#A9805A", True), 1: ("#9CCB82", False), 3: ("#4E9A52", True), 5: ("#CFDC6A", False),
    6: ("#F3EAB5", False), 7: ("#2F7D4F", True), 8: ("#C2185B", True), 9: ("#B08A3E", True),
}
NO_STAGE = ("#BFD9C2", False)   # con fotos o mediciones, sin estado BBCH


def stage_fill(code):
    """(rgba, texto claro) del sector según su último estado BBCH (None = sin estado)."""
    if code is None:
        col, dark = NO_STAGE
    else:
        import phenology as ph
        col, dark = MAP_STAGE.get(ph.macro_of(code), NO_STAGE)
    return c(col), dark


MAPS_DIR = Path(__file__).resolve().parent.parent / "assets" / "maps"
_cache: dict = {}


def load_map(code: str | None) -> dict | None:
    code = (code or "").upper()
    if code not in _cache:
        path = MAPS_DIR / f"{code}.json"
        try:
            _cache[code] = json.loads(path.read_text(encoding="utf-8")) if code and path.exists() else None
        except Exception:  # noqa: BLE001
            _cache[code] = None
    return _cache[code]


def _point_in(ring, x, y) -> bool:
    inside = False
    n = len(ring) // 2
    j = n - 1
    for i in range(n):
        xi, yi, xj, yj = ring[2 * i], ring[2 * i + 1], ring[2 * j], ring[2 * j + 1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _area_centroid(ring):
    a = cx = cy = 0.0
    n = len(ring) // 2
    for i in range(n):
        x0, y0 = ring[2 * i], ring[2 * i + 1]
        x1, y1 = ring[2 * ((i + 1) % n)], ring[2 * ((i + 1) % n) + 1]
        cr = x0 * y1 - x1 * y0
        a += cr
        cx += (x0 + x1) * cr
        cy += (y0 + y1) * cr
    if abs(a) < 1e-9:
        return 0.0, ring[0], ring[1]
    return abs(a) / 2, cx / (3 * a), cy / (3 * a)


def _label_point(ring):
    """Punto para el rótulo: el centroide, o (en formas en «C») el centro de la franja
    horizontal más ancha que cruza el polígono a esa altura."""
    _a, cx, cy = _area_centroid(ring)
    if _point_in(ring, cx, cy):
        return cx, cy
    xs = []
    n = len(ring) // 2
    for i in range(n):
        x0, y0 = ring[2 * i], ring[2 * i + 1]
        x1, y1 = ring[2 * ((i + 1) % n)], ring[2 * ((i + 1) % n) + 1]
        if (y0 > cy) != (y1 > cy):
            xs.append(x0 + (cy - y0) * (x1 - x0) / (y1 - y0))
    xs.sort()
    spans = [(xs[i + 1] - xs[i], (xs[i] + xs[i + 1]) / 2) for i in range(0, len(xs) - 1, 2)]
    return (max(spans)[1], cy) if spans else (cx, cy)


class SectorMap(StencilView):
    """Plano de sectores (recortado a su recuadro al acercar).
    `status` = {id_sector: {"fill": rgba, "dark": texto claro, "dot": tiene mediciones}}."""
    selected = StringProperty("")
    rotate = BooleanProperty(False)
    zoomable = BooleanProperty(False)
    status = DictProperty()
    zoom = NumericProperty(1.0)

    MAX_ZOOM = 6.0

    def __init__(self, plan: dict, on_select=None, **kw):
        super().__init__(**kw)
        self.plan = plan
        self.on_select = on_select
        self._pan = [0.0, 0.0]
        self._touches: dict = {}
        self._pinch = None
        self._multi: set = set()   # dedos que hicieron zoom (no cuentan como toque)
        self._parts = []         # (id, anillo, [(vértices, índices)], área)
        self._labels = {}        # id -> (x, y) en metros
        self._textures = {}
        for s in plan["sectors"]:
            best = None
            for ring in s["parts"]:
                tess = Tesselator()
                tess.add_contour(ring)
                meshes = []
                if tess.tesselate(WINDING_ODD, TYPE_POLYGONS):
                    meshes = [(list(v), list(i)) for v, i in tess.meshes]
                area = _area_centroid(ring)[0]
                self._parts.append((s["id"], ring, meshes, area))
                if best is None or area > best[0]:
                    best = (area, ring)
            self._labels[s["id"]] = _label_point(best[1])
        self._shift = None
        self._redraw = Clock.create_trigger(self._draw, -1)
        self.bind(pos=self._move)
        self.bind(size=self._redraw, selected=self._redraw,
                  status=self._redraw, zoom=self._redraw, rotate=self._redraw)

    # ----------------------------------------------------------- coordenadas
    def _dims(self):
        w, h = self.plan["w"], self.plan["h"]
        return (h, w) if self.rotate else (w, h)

    def _base(self):
        mw, mh = self._dims()
        if not self.width or not self.height:
            return 1.0
        return min(self.width / mw, self.height / mh) * .97

    def _local(self, x, y):
        """Metros del plano -> coordenadas dentro del widget (el canvas se traslada a pos)."""
        if self.rotate:       # 90° horario: el norte (arriba) queda a la derecha
            x, y = y, self.plan["w"] - x
        mw, mh = self._dims()
        s = self._base() * self.zoom
        return (self.width / 2 + (x - mw / 2) * s + self._pan[0],
                self.height / 2 + (y - mh / 2) * s + self._pan[1])

    def to_screen(self, x, y):
        lx, ly = self._local(x, y)
        return lx + self.x, ly + self.y

    def _move(self, *_):
        # Al desplazarse (scroll, cambio de pestaña) solo se mueve el dibujo, sin rehacerlo.
        if self._shift is not None:
            self._shift.xy = self.pos

    def to_map(self, sx, sy):
        mw, mh = self._dims()
        s = self._base() * self.zoom
        x = (sx - self.center_x - self._pan[0]) / s + mw / 2
        y = (sy - self.center_y - self._pan[1]) / s + mh / 2
        if self.rotate:
            x, y = self.plan["w"] - y, x
        return x, y

    def _clamp_pan(self):
        mw, mh = self._dims()
        s = self._base() * self.zoom
        lim_x = max(0.0, (mw * s - self.width) / 2 + dp(24))
        lim_y = max(0.0, (mh * s - self.height) / 2 + dp(24))
        self._pan[0] = max(-lim_x, min(lim_x, self._pan[0]))
        self._pan[1] = max(-lim_y, min(lim_y, self._pan[1]))

    # ---------------------------------------------------------------- dibujo
    def _texture(self, sid):
        if sid not in self._textures:
            eq, se = sid[1:].split("-S")
            lb = CoreLabel(text=f"{eq}-{se}", font_size=sp(10), bold=True)
            lb.refresh()
            self._textures[sid] = lb.texture
        return self._textures[sid]

    def _draw(self, *_):
        self.canvas.clear()
        if not self.width or not self.height:
            return
        empty = c("#E3E6DF")
        sel = self.selected
        ts = self._local
        w, h = self.size
        with self.canvas:
            PushMatrix()
            self._shift = Translate(*self.pos)
            for sid, ring, meshes, _a in self._parts:
                st = self.status.get(sid) or {}
                Color(*(st.get("fill") or empty))
                for verts, idx in meshes:
                    v = list(verts)
                    for k in range(0, len(v), 4):
                        v[k], v[k + 1] = ts(v[k], v[k + 1])
                    Mesh(vertices=v, indices=idx, mode="triangle_fan")
            Color(1, 1, 1, .95)
            outlines = {}
            for sid, ring, _m, _a in self._parts:
                pts = []
                for k in range(0, len(ring), 2):
                    pts += ts(ring[k], ring[k + 1])
                outlines.setdefault(sid, []).append(pts)
                Line(points=pts, close=True, width=dp(.9))
            # Rótulos «equipo-sector» donde caben; un punto si tiene mediciones.
            s = self._base() * self.zoom
            for sid, (lx, ly) in self._labels.items():
                tex = self._texture(sid)
                x, y = ts(lx, ly)
                area = max(a for i, _r, _m, a in self._parts if i == sid)
                if math.sqrt(area) * s < tex.width * .9:
                    continue
                st = self.status.get(sid) or {}
                Color(*(c(theme.INK, .78) if not st.get("fill") else c("#FFFFFF", 1)
                        if st.get("dark") else c(theme.INK, .9)))
                Rectangle(texture=tex, size=tex.size, pos=(x - tex.width / 2, y - tex.height / 2))
                if st.get("dot"):
                    r = dp(3.2)
                    Color(*c(theme.BERRY))
                    Ellipse(pos=(x + tex.width / 2 + dp(1), y + tex.height / 2 - r * 1.6),
                            size=(r * 2, r * 2))
            if sel in outlines:
                Color(*c(theme.INK, .35))
                for pts in outlines[sel]:
                    Line(points=pts, close=True, width=dp(4.2))
                Color(*c(theme.BERRY))
                for pts in outlines[sel]:
                    Line(points=pts, close=True, width=dp(2.4))
            if self.rotate:          # norte
                nx, ny = w - dp(26), h - dp(26)
                Color(*c(theme.LEAF_DARK, .85))
                Line(points=[nx - dp(10), ny, nx + dp(10), ny], width=dp(1.6))
                Line(points=[nx + dp(4), ny + dp(5), nx + dp(10), ny, nx + dp(4), ny - dp(5)],
                     width=dp(1.6))
                tex = self._north()
                Rectangle(texture=tex, size=tex.size, pos=(nx - tex.width / 2, ny + dp(6)))
            PopMatrix()

    def _north(self):
        if "_N" not in self._textures:
            lb = CoreLabel(text="N", font_size=sp(11), bold=True)
            lb.refresh()
            self._textures["_N"] = lb.texture
        return self._textures["_N"]

    # ---------------------------------------------------------------- toques
    def sector_at(self, sx, sy):
        x, y = self.to_map(sx, sy)
        hits = [(a, sid) for sid, ring, _m, a in self._parts if _point_in(ring, x, y)]
        if hits:
            return min(hits)[1]   # la parte más chica (sectores encajados)
        best, dist = None, dp(26)  # toque cerca de un sector pequeño
        for sid, (lx, ly) in self._labels.items():
            px, py = self.to_screen(lx, ly)
            d = math.hypot(px - sx, py - sy)
            if d < dist:
                best, dist = sid, d
        return best

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return False
        if self.zoomable and touch.is_mouse_scrolling:
            f = 1.15 if touch.button == "scrolldown" else 1 / 1.15
            self._zoom_at(f, touch.pos)
            return True
        touch.grab(self)
        self._touches[touch.uid] = list(touch.pos)
        touch.ud["sector_map_start"] = touch.pos
        if len(self._touches) == 2:
            self._pinch = self._pinch_state()
            self._multi |= set(self._touches)
        return True

    def _pinch_state(self):
        (x0, y0), (x1, y1) = list(self._touches.values())[:2]
        return math.hypot(x1 - x0, y1 - y0) or 1.0

    def _zoom_at(self, factor, pos):
        old = self.zoom
        new = max(1.0, min(self.MAX_ZOOM, old * factor))
        if new == old:
            return
        # El punto bajo los dedos queda fijo.
        k = new / old
        self._pan[0] = (pos[0] - self.center_x) - (pos[0] - self.center_x - self._pan[0]) * k
        self._pan[1] = (pos[1] - self.center_y) - (pos[1] - self.center_y - self._pan[1]) * k
        self.zoom = new
        self._clamp_pan()
        self._redraw()

    def on_touch_move(self, touch):
        if touch.grab_current is not self:
            return False
        if not self.zoomable or touch.uid not in self._touches:
            return True
        prev = self._touches[touch.uid]
        self._touches[touch.uid] = list(touch.pos)
        if len(self._touches) >= 2 and self._pinch:
            d = self._pinch_state()
            (x0, y0), (x1, y1) = list(self._touches.values())[:2]
            self._zoom_at(d / self._pinch, ((x0 + x1) / 2, (y0 + y1) / 2))
            self._pinch = d
        elif self.zoom > 1.0:
            self._pan[0] += touch.x - prev[0]
            self._pan[1] += touch.y - prev[1]
            self._clamp_pan()
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
        start = touch.ud.get("sector_map_start", touch.pos)
        if multi or math.hypot(touch.x - start[0], touch.y - start[1]) > dp(12):
            return True
        if touch.is_double_tap and self.zoomable:
            self._zoom_at(2.5 if self.zoom < 1.5 else 1 / self.zoom, touch.pos)
            return True
        sid = self.sector_at(*touch.pos)
        if sid:
            self.selected = sid
            if self.on_select:
                self.on_select(sid)
        return True
