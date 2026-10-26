"""
ui/heatmap.py
=============
Mapa de calor de dónde se tomaron las fotos (se abre desde «Vista previa»).

Cada registro (variedad × semana) con ubicación —GPS del teléfono, de la foto o marcada en
el mapa— aporta tantas fotos como tenga. La capa de calor se calcula una vez por zoom en
coordenadas de tesela (al arrastrar solo se mueve) y encima van puntos que se pueden tocar
para ver y abrir ese registro.
"""
from __future__ import annotations

import datetime as _dt
import math

from kivy.graphics import Color, Ellipse, Rectangle
from kivy.graphics.texture import Texture
from kivy.metrics import dp
from kivy.properties import BooleanProperty, StringProperty
from kivymd.app import MDApp
from kivymd.uix.screen import MDScreen

import geo
import phenology as ph
from geo import heat_grid, ramp
from ui.mapview import MIN_ZOOM, MapPicker, tile_px

CELL = 4            # px de pantalla por celda de la grilla de calor
RADIUS = 40         # radio de cada punto (dp)
DOTS_FROM = 17      # los puntos se dibujan desde este zoom (antes, solo el calor)


def workspace_bounds() -> tuple[float, float, float, float] | None:
    """(lat_min, lat_max, lon_min, lon_max) del predio activo según su plano georreferenciado;
    si no hay plano, de los registros con ubicación de cualquier temporada. None si nada."""
    a = MDApp.get_running_app()
    ws = getattr(a, "workspace", None) or {}
    try:
        from ui.sector_map import load_map
        plan = load_map(ws.get("code")) if ws.get("profile") == "predio" else None
    except Exception:  # noqa: BLE001
        plan = None
    if plan and plan.get("geo"):
        g = plan["geo"]
        return (g["y0"] / g["ky"], (plan["h"] + g["y0"]) / g["ky"],
                g["x0"] / g["kx"], (plan["w"] + g["x0"]) / g["kx"])
    rows = a.db.query("SELECT MIN(latitude) a, MAX(latitude) b, MIN(longitude) c, MAX(longitude) d "
                      "FROM observations WHERE latitude IS NOT NULL AND longitude IS NOT NULL")
    r = rows[0] if rows else None
    if r and r["a"] is not None:
        return r["a"], r["b"], r["c"], r["d"]
    return None


def fit_bounds(bounds, max_zoom: float = 18) -> tuple[float, float, float]:
    """(lat, lon, zoom) que muestra todo el recuadro en la pantalla."""
    if not bounds:
        return geo.DEFAULT_CENTER[0], geo.DEFAULT_CENTER[1], 12
    la0, la1, lo0, lo1 = bounds
    lat, lon = (la0 + la1) / 2, (lo0 + lo1) / 2
    (x0, y0), (x1, y1) = geo.latlon_to_tile(la1, lo0, 0), geo.latlon_to_tile(la0, lo1, 0)
    span = max((x1 - x0) * tile_px() / dp(300), (y1 - y0) * tile_px() / dp(420), 1e-12)
    zoom = min(max_zoom, max(MIN_ZOOM, -math.log2(span)))
    return lat, lon, zoom


class HeatMap(MapPicker):
    """Mapa (satelital o calles) con capa de calor y puntos tocables (sin el pin central)."""

    def __init__(self, points: list[dict], on_pick=None, **kw):
        self.points = points            # {lat, lon, weight, ...}
        self.on_pick = on_pick
        self._heat = None               # (z, textura, x0, y0, ancho, alto) en teselas de nivel z
        self._down = None
        lat, lon, zoom = self.fit(points)
        super().__init__(lat, lon, zoom, **kw)

    # ------------------------------------------------------------ encuadre
    @staticmethod
    def fit(points) -> tuple[float, float, float]:
        if points:
            lats = [p["lat"] for p in points]
            lons = [p["lon"] for p in points]
            return fit_bounds((min(lats), max(lats), min(lons), max(lons)))
        return fit_bounds(workspace_bounds())     # sin fotos: el predio (no Santiago)

    def set_points(self, points: list[dict], refit: bool = True):
        self.points = points
        self._heat = None
        if refit:
            self.center_on(*self.fit(points))
        self._redraw()

    # ------------------------------------------------------------- calor
    def _heat_layer(self, z: int):
        if self._heat and self._heat[0] == z:
            return self._heat
        size = tile_px()
        scale = size / CELL                  # celdas por tesela
        pts = []
        for p in self.points:
            tx, ty = geo.latlon_to_tile(p["lat"], p["lon"], z)
            pts.append((tx * scale, ty * scale, p["weight"]))
        radius = dp(RADIUS) / CELL
        grid, gw, gh, (x0, y0) = heat_grid(pts, radius)
        if not grid:
            self._heat = (z, None, 0, 0, 0, 0)
            return self._heat
        top = max(grid) or 1
        buf = bytearray(gw * gh * 4)
        for j in range(gh):
            src = (gh - 1 - j) * gw          # textura: fila 0 abajo; grilla: fila 0 arriba (y crece hacia abajo)
            dst = j * gw * 4
            for i in range(gw):
                v = grid[src + i]
                if v <= 0:
                    continue
                t = min(1.0, (v / top) ** .5)
                r, g, b = ramp(t)
                k = dst + i * 4
                buf[k:k + 4] = bytes((r, g, b, int(min(1.0, t * 2.2) * 205)))
        tex = Texture.create(size=(gw, gh), colorfmt="rgba")
        tex.blit_buffer(bytes(buf), colorfmt="rgba", bufferfmt="ubyte")
        tex.mag_filter = tex.min_filter = "linear"
        self._heat = (z, tex, x0 / scale, y0 / scale, gw / scale, gh / scale)
        return self._heat

    def _redraw(self, *_):
        super()._redraw()
        if not hasattr(self, "points"):
            return
        z = max(0, min(20, int(math.floor(self.zoom + 1e-9))))
        _z, tex, x0, y0, w, h = self._heat_layer(z)
        n = 2 ** z
        with self.canvas:
            if tex is not None:          # recuadro del calor (teselas de nivel z → mundo → pantalla)
                left, top = self.world_to_screen(x0 / n, y0 / n)
                right, bottom = self.world_to_screen((x0 + w) / n, (y0 + h) / n)
                Color(1, 1, 1, 1)
                Rectangle(texture=tex, pos=(left, bottom), size=(right - left, top - bottom))
            r = dp(4) if self.zoom >= DOTS_FROM else dp(2.5)
            for p in self.points:
                sx, sy = self.latlon_to_screen(p["lat"], p["lon"])
                Color(1, 1, 1, .95)
                Ellipse(pos=(sx - r - dp(1.5), sy - r - dp(1.5)), size=(2 * r + dp(3), 2 * r + dp(3)))
                Color(0.66, 0.09, 0.29, 1)
                Ellipse(pos=(sx - r, sy - r), size=(2 * r, 2 * r))

    # ------------------------------------------------------------- toques
    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos) and not touch.is_double_tap and not self._touches:
            self._down = touch.pos
        elif self._touches:
            self._down = None                # segundo dedo: es pellizco, no un toque
        return super().on_touch_down(touch)

    def on_touch_up(self, touch):
        down, self._down = self._down, None
        handled = super().on_touch_up(touch)
        if down and self.on_pick and math.dist(down, touch.pos) < dp(8):
            best, dist = None, dp(26)
            for p in self.points:
                d = math.dist(self.latlon_to_screen(p["lat"], p["lon"]), touch.pos)
                if d < dist:
                    best, dist = p, d
            self.on_pick(best)
        return handled


# ---------------------------------------------------------------------------- pantalla

class HeatmapScreen(MDScreen):
    """Mapa de fotos: toda la temporada o solo la semana actual; tocar un punto muestra
    el registro y permite abrirlo."""
    whole_season = BooleanProperty(True)
    info = StringProperty("")
    pick_title = StringProperty("")
    pick_detail = StringProperty("")
    has_pick = BooleanProperty(False)

    def on_pre_enter(self, *_):
        self._fresh = True                   # al entrar, encuadra de nuevo
        self.refresh()

    def on_enter(self, *_):
        from android_bridge import allow_rotation
        allow_rotation(True)                 # el mapa se puede ver con el teléfono horizontal

    def on_leave(self, *_):
        from android_bridge import allow_rotation
        allow_rotation(False)

    def set_scope(self, whole: bool):
        self.whole_season = whole
        self.refresh()

    def refresh(self):
        a = MDApp.get_running_app()
        week = None if self.whole_season else a.week["id"]
        rows, missing = a.db.photo_locations(a.season, week)
        self._rows = rows
        n = sum(r["weight"] for r in rows)
        where = ph.season_title(a.season) if self.whole_season else ph.week_title(a.week)
        self.ids.bar.title = "Mapa de fotos"
        if not rows:
            self.info = (f"{where}: aún no hay fotos con ubicación. Al registrar, use el GPS o "
                         "ubique el registro en el mapa.")
        else:
            self.info = (f"{where} · {n} foto{'s' if n != 1 else ''} en {len(rows)} punto"
                         f"{'s' if len(rows) != 1 else ''}"
                         + (f" · {missing} sin ubicación" if missing else ""))
        self.has_pick = False
        stage = self.ids.stage
        if getattr(self, "_map", None) is None:
            self._map = HeatMap(rows, on_pick=self.pick, workers=a.workers, size_hint=(1, 1),
                                pos_hint={"x": 0, "y": 0})
            stage.add_widget(self._map, index=len(stage.children))   # debajo de botones y tarjetas
            self.ids.layer_btn.icon = "map-outline" if self._map.layer == "sat" else "satellite-variant"
        else:
            # Al cambiar entre temporada y semana se mantiene la vista (el predio).
            self._map.set_points(rows, refit=getattr(self, "_fresh", False))
        self._fresh = False

    def zoom(self, step: int):
        self._map.zoom_by(step)

    def toggle_layer(self):
        """Satélite ↔ calles; el ícono muestra a cuál se cambia."""
        layer = self._map.toggle_layer()
        self.ids.layer_btn.icon = "map-outline" if layer == "sat" else "satellite-variant"

    def pick(self, row):
        if row is None:
            self.has_pick = False
            return
        a = MDApp.get_running_app()
        v = a.db.get_variety(row["variety_id"]) or {}
        place = ph.unit_place(v)
        self._picked = row
        self.pick_title = ph.unit_main(v) + (f"  ·  {place}" if place else "")
        bits = [ph.week_label(_dt.date.fromisoformat(row["start_date"][:10])),
                f"{row['weight']} foto{'s' if row['weight'] != 1 else ''}"]
        if row["bbch_code"] is not None:
            bits.append(f"BBCH {ph.code_str(row['bbch_code'])}")
        self.pick_detail = " · ".join(bits)
        self.has_pick = True

    def open_pick(self):
        row = getattr(self, "_picked", None)
        if row:
            MDApp.get_running_app().open_observation(row["variety_id"], row["week_id"])
