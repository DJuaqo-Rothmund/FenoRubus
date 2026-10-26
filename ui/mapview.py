"""
ui/mapview.py
=============
Mapa liviano (teselas OpenStreetMap) para marcar la ubicación de una muestra.

El pin queda fijo en el centro: se arrastra el mapa debajo y se confirma el
punto. Zoom continuo con dos dedos (pellizco), botones, doble toque o rueda del mouse. Las teselas se guardan en caché,
así que las zonas ya vistas funcionan sin conexión.
"""
from __future__ import annotations

import math

from kivy.clock import Clock
from kivy.graphics import Color, Line, Rectangle
from kivy.properties import NumericProperty, StringProperty
from kivy.uix.stencilview import StencilView

import geo

MIN_ZOOM, MAX_ZOOM = 3, 20
MAX_TILE_ZOOM = 19      # calles: más cerca se amplía la tesela de este nivel


def tile_px() -> float:
    """Tamaño en pantalla de una tesela: legible sin ampliarla tanto que se vea borrosa."""
    from kivy.metrics import Metrics
    return geo.TILE_SIZE * max(1.0, Metrics.density / 1.5)


def default_layer() -> str:
    """Fondo elegido por última vez («sat» satelital, por defecto, u «osm» mapa de calles)."""
    try:
        from kivymd.app import MDApp
        return MDApp.get_running_app().workspaces.shared.get_setting("map_layer", "sat") or "sat"
    except Exception:  # noqa: BLE001
        return "sat"


def remember_layer(layer: str) -> None:
    try:
        from kivymd.app import MDApp
        MDApp.get_running_app().workspaces.shared.set_setting("map_layer", layer)
    except Exception:  # noqa: BLE001
        pass


class MapPicker(StencilView):
    """Mapa por teselas con zoom continuo: un dedo arrastra, dos dedos acercan/alejan
    (pellizco) y se mueven, doble toque acerca, la rueda del mouse también."""
    zoom = NumericProperty(16)      # puede ser fraccionario (pellizco)
    layer = StringProperty("sat")   # «sat» (Esri World Imagery) u «osm» (calles)
    cx = NumericProperty(0.0)       # centro en coordenadas de tesela al nivel entero del zoom
    cy = NumericProperty(0.0)

    def __init__(self, lat: float, lon: float, zoom: int = 16, workers=None, **kw):
        super().__init__(**kw)
        self.workers = workers
        self.layer = kw.get("layer") or default_layer()
        self._textures: dict = {}
        self._pending: set = set()
        self._touches: dict = {}
        self._pinch = None
        self._drag = None
        self.wx, self.wy = geo.latlon_to_tile(lat, lon, 0)   # centro en fracción del mundo (0-1)
        self.zoom = zoom
        self._sync()
        self.bind(pos=self._redraw, size=self._redraw, zoom=self._redraw, layer=self._redraw)
        Clock.schedule_once(self._redraw, 0)

    # --------------------------------------------------------------- estado
    def _sync(self):
        n = 2 ** int(self.zoom)
        self.cx, self.cy = self.wx * n, self.wy * n

    def _scale(self) -> float:
        """Píxeles de pantalla por unidad de mundo (el mundo entero mide 1×1)."""
        return tile_px() * 2 ** self.zoom

    def world_to_screen(self, wx: float, wy: float) -> tuple[float, float]:
        s = self._scale()
        return (self.center_x + (wx - self.wx) * s, self.center_y - (wy - self.wy) * s)

    def latlon_to_screen(self, lat: float, lon: float) -> tuple[float, float]:
        return self.world_to_screen(*geo.latlon_to_tile(lat, lon, 0))

    @property
    def center_latlon(self) -> tuple[float, float]:
        return geo.tile_to_latlon(self.wx % 1.0, self.wy, 0)

    def center_on(self, lat: float, lon: float, zoom: float | None = None):
        if zoom is not None:
            self.zoom = max(MIN_ZOOM, min(MAX_ZOOM, zoom))
        self.wx, self.wy = geo.latlon_to_tile(lat, lon, 0)
        self._sync()
        self._redraw()

    def toggle_layer(self) -> str:
        self.layer = "osm" if self.layer == "sat" else "sat"
        remember_layer(self.layer)
        return self.layer

    def zoom_at(self, new_zoom: float, focus=None):
        """Cambia el zoom dejando fijo el punto bajo `focus` (posición en pantalla)."""
        new_zoom = max(MIN_ZOOM, min(MAX_ZOOM, new_zoom))
        fx, fy = focus or self.center
        s0 = self._scale()
        ax = self.wx + (fx - self.center_x) / s0
        ay = self.wy - (fy - self.center_y) / s0
        s1 = tile_px() * 2 ** new_zoom
        self.wx = ax - (fx - self.center_x) / s1
        self.wy = ay + (fy - self.center_y) / s1
        self.zoom = new_zoom
        self._sync()
        self._redraw()

    def zoom_by(self, step: int):
        self.zoom_at(round(self.zoom) + step)

    def pan(self, dx: float, dy: float):
        s = self._scale()
        self.wx = (self.wx - dx / s) % 1.0
        self.wy = min(max(self.wy + dy / s, 0.0), 1.0)
        self._sync()
        self._redraw()

    # -------------------------------------------------------------- toques
    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return super().on_touch_down(touch)
        if touch.is_mouse_scrolling:
            self.zoom_at(self.zoom + (-.5 if touch.button == "scrollup" else .5), touch.pos)
            return True
        if touch.is_double_tap:
            self.zoom_at(round(self.zoom) + 1, touch.pos)
            return True
        touch.grab(self)
        self._touches[touch.uid] = touch.pos
        self._drag = touch.pos
        if len(self._touches) == 2:
            self._pinch = self._pinch_state()
        return True

    def _pinch_state(self):
        (x0, y0), (x1, y1) = list(self._touches.values())[:2]
        return math.hypot(x1 - x0, y1 - y0) or 1.0, ((x0 + x1) / 2, (y0 + y1) / 2), self.zoom

    def on_touch_move(self, touch):
        if touch.grab_current is not self or touch.uid not in self._touches:
            return super().on_touch_move(touch)
        prev = self._touches[touch.uid]
        self._touches[touch.uid] = touch.pos
        if len(self._touches) >= 2 and self._pinch:
            d0, (mx0, my0), z0 = self._pinch
            (x0, y0), (x1, y1) = list(self._touches.values())[:2]
            d = math.hypot(x1 - x0, y1 - y0) or 1.0
            mx, my = (x0 + x1) / 2, (y0 + y1) / 2
            self.zoom_at(z0 + math.log2(d / d0), (mx, my))     # pellizco: zoom en el centro de los dedos
            self.pan(mx - mx0, my - my0)                       # y se mueve con ellos
            self._pinch = (d, (mx, my), self.zoom)
        elif len(self._touches) == 1:
            self.pan(touch.x - prev[0], touch.y - prev[1])
        return True

    def on_touch_up(self, touch):
        if touch.grab_current is self:
            touch.ungrab(self)
            self._touches.pop(touch.uid, None)
            if len(self._touches) < 2:
                self._pinch = None
            self._drag = None
            return True
        return super().on_touch_up(touch)

    # -------------------------------------------------------------- dibujo
    def _texture(self, z, x, y):
        """Textura de la tesela; en satelital, más cerca que SAT_MAX_ZOOM se usa el trozo
        correspondiente de la tesela de ese nivel (ampliada)."""
        layer = self.layer
        if layer == "sat" and z > geo.SAT_MAX_ZOOM:
            d = z - geo.SAT_MAX_ZOOM
            parent = self._texture_at(geo.SAT_MAX_ZOOM, x >> d, y >> d, layer)
            if parent is None:
                return None
            k = 2 ** d
            sub = parent.width / k
            return parent.get_region((x % k) * sub, (k - 1 - y % k) * sub, sub, sub)
        return self._texture_at(z, x, y, layer)

    def _texture_at(self, z, x, y, layer):
        key = (layer, z, x, y)
        tex = self._textures.get(key)
        if tex is not None:
            return tex
        path = geo.tile_path(z, x, y, layer)
        import os
        if os.path.exists(path):
            try:
                from kivy.core.image import Image as CoreImage
                tex = CoreImage(path).texture
                self._textures[key] = tex
                if len(self._textures) > 160:
                    self._textures.pop(next(iter(self._textures)))
                return tex
            except Exception:  # noqa: BLE001 (tesela corrupta: se vuelve a bajar)
                try:
                    os.remove(path)
                except OSError:
                    pass
        if key not in self._pending:
            self._pending.add(key)

            def work():
                ok = geo.fetch_tile(z, x, y, layer)
                self._pending.discard(key)
                if ok:
                    Clock.schedule_once(self._redraw, 0)

            if self.workers is not None:
                self.workers.submit(work)
        return None

    def _redraw(self, *_):
        self.canvas.clear()
        top = geo.SAT_MAX_ZOOM + 2 if self.layer == "sat" else MAX_TILE_ZOOM
        z = max(0, min(int(math.floor(self.zoom + 1e-9)), top))
        n = 2 ** z
        size = tile_px() * 2 ** (self.zoom - z)          # tesela de nivel z en pantalla
        cx, cy = self.wx * n, self.wy * n
        w, h = self.width, self.height
        mx, my = self.x + w / 2, self.y + h / 2
        x0 = int(math.floor(cx - w / 2 / size)) - 1
        x1 = int(math.floor(cx + w / 2 / size)) + 1
        y0 = int(math.floor(cy - h / 2 / size)) - 1
        y1 = int(math.floor(cy + h / 2 / size)) + 1
        with self.canvas:
            Color(0.90, 0.93, 0.90, 1)
            Rectangle(pos=self.pos, size=self.size)
            for ty in range(max(y0, 0), min(y1, n - 1) + 1):
                for tx in range(x0, x1 + 1):
                    px = mx + (tx - cx) * size
                    py = my - (ty + 1 - cy) * size   # y de teselas crece hacia abajo
                    tex = self._texture(z, tx % n, ty)
                    if tex is not None:
                        Color(1, 1, 1, 1)
                        Rectangle(texture=tex, pos=(px, py), size=(size, size))
                    else:
                        Color(0.80, 0.85, 0.80, 1)
                        Line(rectangle=(px, py, size, size), width=1)
        # Atribución del fondo (obligatoria): abajo a la derecha, en chico.
        with self.canvas:
            credit_label(self, self.layer)


_credits: dict = {}


def credit_label(widget, layer: str):
    """Dibuja «© Esri…» / «© OpenStreetMap» abajo a la derecha del widget."""
    from kivy.core.text import Label as CoreLabel
    from kivy.metrics import sp
    tex = _credits.get(layer)
    if tex is None:
        lb = CoreLabel(text=geo.SAT_CREDIT if layer == "sat" else geo.OSM_CREDIT, font_size=sp(9))
        lb.refresh()
        tex = _credits[layer] = lb.texture
    x = widget.right - tex.width - 8
    Color(1, 1, 1, .75)
    Rectangle(pos=(x - 4, widget.y + 2), size=(tex.width + 8, tex.height + 2))
    Color(.2, .2, .2, 1)
    Rectangle(texture=tex, pos=(x, widget.y + 3), size=tex.size)


class TileCache:
    """Teselas para dibujar bajo otro plano (p. ej. el de sectores): textura si ya está en
    disco; si no, la baja en segundo plano y avisa con `on_ready`."""

    def __init__(self, workers, on_ready):
        self.workers, self.on_ready = workers, on_ready
        self._tex: dict = {}
        self._pending: set = set()

    def get(self, z, x, y, layer="sat"):
        if layer == "sat" and z > geo.SAT_MAX_ZOOM:
            d = z - geo.SAT_MAX_ZOOM
            parent = self.get(geo.SAT_MAX_ZOOM, x >> d, y >> d, layer)
            if parent is None:
                return None
            k = 2 ** d
            sub = parent.width / k
            return parent.get_region((x % k) * sub, (k - 1 - y % k) * sub, sub, sub)
        key = (layer, z, x, y)
        if key in self._tex:
            return self._tex[key]
        import os
        path = geo.tile_path(z, x, y, layer)
        if os.path.exists(path):
            try:
                from kivy.core.image import Image as CoreImage
                tex = CoreImage(path).texture
                self._tex[key] = tex
                if len(self._tex) > 220:
                    self._tex.pop(next(iter(self._tex)))
                return tex
            except Exception:  # noqa: BLE001
                try:
                    os.remove(path)
                except OSError:
                    pass
        if key not in self._pending and self.workers is not None:
            self._pending.add(key)

            def work():
                ok = geo.fetch_tile(z, x, y, layer)
                self._pending.discard(key)
                if ok:
                    Clock.schedule_once(lambda *_: self.on_ready(), 0)

            self.workers.submit(work)
        return None
