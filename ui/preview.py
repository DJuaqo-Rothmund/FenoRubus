"""
ui/preview.py
=============
Vista previa: avance, mapas de calor y matriz de estados.
(Antes en ui/screens.py; el diseño está en ui/kv/.)
"""
from __future__ import annotations

import datetime as _dt
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.widget import Widget
from kivy.properties import ColorProperty, ListProperty, NumericProperty, ObjectProperty, StringProperty
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
import phenology as ph
from ui import theme
from ui.theme import c
from ui.common import _crop, app, bbch_tag_colors, fast_clear, themed


# ===========================================================================
# Widgets gráficos de la vista previa
# ===========================================================================
@themed(color=("BERRY", None), track=("BERRY_SOFT", None))
class ProgressRing(Widget):
    """Anillo de avance (0..1) con el porcentaje al centro."""
    value = NumericProperty(0)
    thickness = NumericProperty(dp(9))
    color = ColorProperty(c(theme.BERRY))
    track = ColorProperty(c(theme.BERRY_SOFT))


def _muted_label(text: str):
    return MDLabel(text=text, font_style="Caption", adaptive_height=True, halign="center",
                   theme_text_color="Custom", text_color=c(theme.MUTED))


@themed(fg=("INK", None))
class StageChip(BoxLayout):
    """Etiqueta de estadio (leyenda del mapa)."""
    text = StringProperty()
    bg = ColorProperty(c("#FFFFFF"))
    fg = ColorProperty(c(theme.INK))


@themed(sub_color=("MUTED", None), badge_fg=("INK", None))
class PreviewTile(ButtonBehavior, BoxLayout):
    """Ficha de la vista previa: la frambuesa dibujada de la variedad (gris si esa semana
    no tiene registro), su estado BBCH y nombre. El botón ES la frambuesa: solo responde
    al tocar el fruto (no un recuadro)."""
    title = StringProperty()
    subtitle = StringProperty()
    sub_color = ColorProperty(c(theme.MUTED))
    badge = StringProperty()
    badge_bg = ColorProperty(c("#FFFFFF", .9))
    badge_fg = ColorProperty(c(theme.INK))
    berry = StringProperty()

    def collide_point(self, x, y):
        img = self.ids.get("art")
        if img is None or not img.collide_point(x, y) or not self.berry:
            return False
        w, h = img.norm_image_size
        if not w or not h:
            return False
        u = (x - (img.center_x - w / 2)) / w
        v = (y - (img.center_y - h / 2)) / h
        if not (0 <= u < 1 and 0 <= v < 1):
            return False
        mask = berry_mask(self.berry)
        if mask is None:
            return True
        mw, mh = mask.size
        return mask.getpixel((int(u * mw), int((1 - v) * mh))) > 60


_berry_masks: dict = {}


def berry_mask(path: str):
    """Silueta (canal alfa reducido) de la frambuesa para saber si el toque cae en el
    fruto. Se lee con Pillow, aparte: leerla con Kivy reemplazaba la textura en caché y
    las frambuesas podían verse como cuadros negros."""
    if path not in _berry_masks:
        try:
            from PIL import Image as PILImage
            with PILImage.open(path) as im:
                _berry_masks[path] = im.convert("RGBA").getchannel("A").resize((48, 56))
        except Exception:  # noqa: BLE001
            _berry_masks[path] = None
    return _berry_masks[path]


class StageNames(Widget):
    """Columna fija con el nombre COMPLETO de cada variedad (a la par del mapa)."""
    rows = ListProperty([])
    MAX_W = dp(170)

    def __init__(self, **kw):
        super().__init__(**kw)
        self.size_hint = (None, None)
        self.bind(rows=self._layout, pos=self._redraw)
        self._layout()

    def _layout(self, *_):
        from kivy.core.text import Label as CoreLabel
        self._tex = []
        widest = dp(40)
        for r in self.rows:
            lb = CoreLabel(text=r["name"], font_size=dp(11), bold=True)
            lb.refresh()
            tex = lb.texture
            if tex.width > self.MAX_W:   # muy largo: en dos líneas
                lb = CoreLabel(text=r["name"], font_size=dp(10), bold=True,
                               text_size=(self.MAX_W, None), halign="left")
                lb.refresh()
                tex = lb.texture
            self._tex.append(tex)
            widest = max(widest, tex.width)
        self.width = min(widest, self.MAX_W) + dp(8)
        self.height = StageHeatmap.HEAD + len(self.rows) * (StageHeatmap.CELL_H + StageHeatmap.GAP)
        self._redraw()

    def _redraw(self, *_):
        from kivy.graphics import Color, Rectangle
        self.canvas.clear()
        with self.canvas:
            Color(*c(theme.INK))
            for i, tex in enumerate(getattr(self, "_tex", [])):
                y = self.top - StageHeatmap.HEAD - (i + 1) * (StageHeatmap.CELL_H + StageHeatmap.GAP)
                Rectangle(texture=tex, size=tex.size,
                          pos=(self.x, y + (StageHeatmap.CELL_H - tex.height) / 2))


class StageHeatmap(Widget):
    """Mapa variedad × semana coloreado por estadio BBCH (con el código en la celda).
    Tocar una celda abre ese registro (on_cell)."""
    rows = ListProperty([])
    weeks = ListProperty([])
    NAME_W, CELL_W, CELL_H, GAP, HEAD = 0, dp(34), dp(24), dp(3), dp(18)   # nombres: StageNames

    def __init__(self, on_cell=None, **kw):
        super().__init__(**kw)
        self.on_cell = on_cell
        self.size_hint = (None, None)
        self._tex = {}
        self.bind(rows=self._layout, weeks=self._layout, pos=self._redraw)

    def _layout(self, *_):
        self.width = self.NAME_W + max(1, len(self.weeks)) * self.CELL_W
        self.height = self.HEAD + len(self.rows) * (self.CELL_H + self.GAP)
        self._redraw()

    def _text(self, text, size, bold=False):
        key = (text, size, bold)
        if key not in self._tex:
            from kivy.core.text import Label as CoreLabel
            lb = CoreLabel(text=text, font_size=size, bold=bold)
            lb.refresh()
            self._tex[key] = lb.texture
        return self._tex[key]

    def _cell_rect(self, i, j):
        x = self.x + self.NAME_W + j * self.CELL_W + self.GAP / 2
        y = self.top - self.HEAD - (i + 1) * (self.CELL_H + self.GAP)
        return x, y, self.CELL_W - self.GAP, self.CELL_H

    def _redraw(self, *_):
        from kivy.graphics import Color, Line, Rectangle, RoundedRectangle
        self.canvas.clear()
        with self.canvas:
            for j, wk in enumerate(self.weeks):
                t = self._text(wk, dp(10), True)
                Color(*c(theme.MUTED))
                x = self.x + self.NAME_W + j * self.CELL_W + (self.CELL_W - t.size[0]) / 2
                Rectangle(texture=t, size=t.size, pos=(x, self.top - self.HEAD + dp(3)))
            for i, r in enumerate(self.rows):
                for j, cell in enumerate(r["cells"]):
                    x, y, w, h = self._cell_rect(i, j)
                    code = cell["code"]
                    bg, fg = theme.stage_colors(code)
                    if code is None:
                        Color(*c("#FFFFFF", .5))
                        RoundedRectangle(pos=(x, y), size=(w, h), radius=[dp(6)])
                        if cell["n_photos"]:   # foto sin estado: punto frambuesa
                            Color(*c(theme.BERRY_LIGHT))
                            RoundedRectangle(pos=(x + w / 2 - dp(3), y + h / 2 - dp(3)),
                                             size=(dp(6), dp(6)), radius=[dp(3)])
                        continue
                    Color(*bg)
                    RoundedRectangle(pos=(x, y), size=(w, h), radius=[dp(6)])
                    Color(*c(theme.LEAF_DARK, .18))
                    Line(rounded_rectangle=(x, y, w, h, dp(6)), width=dp(.8))
                    t = self._text(ph.code_str(code), dp(10), True)
                    Color(*fg)
                    Rectangle(texture=t, size=t.size, pos=(x + (w - t.size[0]) / 2, y + (h - t.size[1]) / 2))

    def on_touch_up(self, touch):
        if not self.collide_point(*touch.pos) or self.on_cell is None:
            return False
        if abs(touch.x - touch.ox) > dp(12) or abs(touch.y - touch.oy) > dp(12):
            return False   # fue un desplazamiento, no un toque
        for i, r in enumerate(self.rows):
            for j, cell in enumerate(r["cells"]):
                x, y, w, h = self._cell_rect(i, j)
                if x <= touch.x <= x + w and y <= touch.y <= y + h:
                    self.on_cell(cell)
                    return True
        return False


# ===========================================================================
# Vista previa de informes (sin enviar)
# ===========================================================================
class PreviewTab(MDScreen):
    """Vista previa: «Por variedad» (la frambuesa de cada variedad; tocarla abre todo su
    informe) y «Matriz global» (estados BBCH de la temporada, o de un mes)."""
    kind = StringProperty("variety")
    KIND_NAMES = {"variety": "Por variedad", "matrix": "Matriz global"}
    sel_month = ObjectProperty(None, allownone=True)   # (año, mes) o None = toda la temporada
    variety_label = StringProperty("Por variedad")    # «Por sector» en predios con plano
    sel_sector = StringProperty("")

    def _plan(self):
        """Plano de sectores del predio activo (None en I+D o si no hay plano)."""
        a = app()
        ws = getattr(a, "workspace", None) or {}
        if ws.get("profile") != "predio":
            return None
        from ui.sector_map import load_map
        return load_map(ws.get("code"))

    def pick_season(self):
        season_dialog(self.refresh)

    def refresh(self):
        a = app()
        if getattr(self, "_season", None) != a.season:
            self._season = a.season
            self.sel_month = None
        self.ids.season_chip.text = ph.season_title(a.season)
        plan = self._plan()
        if plan is not getattr(self, "_plan_on", None):
            self._plan_on, self.sel_sector = plan, ""
        self.variety_label = "Por sector" if plan else "Por variedad"
        self._build_params()
        self._summarize()

    def set_kind(self, kind: str):
        self.kind = kind
        self.refresh()

    # ------------------------------------------------------------ parámetros
    def _months(self):
        out = []
        for w in app().db.list_weeks(app().season, trim_empty=True):
            d = _dt.date.fromisoformat(w["start_date"])
            if (d.year, d.month) not in out:
                out.append((d.year, d.month))
        return out

    def _build_params(self):
        box = self.ids.params
        fast_clear(box)
        if self.kind == "variety":
            box.add_widget(MDLabel(text=("Toque un sector del plano para ver su información; tocando "
                                         "un equipo de riego se acerca." if self._plan() else
                                         f"Toque un{'a' if _crop().id == 'frambuesa' else ''} {_crop().fruit} para ver todo el informe de esa variedad."),
                                   font_style="Caption", adaptive_height=True,
                                   theme_text_color="Custom", text_color=c(theme.MUTED)))
            return
        from kivy.factory import Factory
        from kivy.uix.stacklayout import StackLayout
        chips = StackLayout(size_hint_y=None, spacing=dp(6))
        chips.bind(minimum_height=chips.setter("height"))
        options = [(None, "Toda la temporada")] + [
            (ym, f"{ph.MESES[ym[1] - 1].capitalize()} {ym[0]}") for ym in self._months()]
        for ym, label in options:
            b = Factory.SegButton(text=label, selected=self.sel_month == ym, size_hint_x=None,
                                  height=dp(36), font_size="14sp")
            b.text_size = (None, None)          # el ancho lo da el texto (no se corta)
            b.texture_update()
            b.width = b.texture_size[0] + dp(30)
            b.bind(on_release=lambda w, ym=ym: self._set_month(ym))
            chips.add_widget(b)
        box.add_widget(chips)

    def _set_month(self, ym):
        self.sel_month = ym
        self.refresh()

    def _range(self):
        """(desde, hasta) en número de semana de muestreo; None = toda la temporada."""
        if not self.sel_month:
            return None
        ws = [w for w in app().db.list_weeks(app().season)
              if _dt.date.fromisoformat(w["start_date"]).timetuple()[:2] == tuple(self.sel_month)]
        if not ws:
            return None
        return ws[0]["week_number"], ws[-1]["week_number"]

    # --------------------------------------------------------------- resumen
    def _summarize(self):
        from reporter import report_summary
        a = app()
        rng = self._range() if self.kind == "matrix" else None
        if rng:
            sm = report_summary(a.db, "period", a.season, week_from=rng[0], week_to=rng[1])
        else:
            sm = report_summary(a.db, "matrix", a.season)
        ids = self.ids
        ids.sum_title.text = ("Matriz global · " + (f"{ph.MESES[self.sel_month[1] - 1].capitalize()} "
                                                   f"{self.sel_month[0]}" if rng else "toda la temporada")
                              if self.kind == "matrix" else f"{self.variety_label} · toda la temporada")
        ratio = sm["complete"] / sm["cells"] if sm["cells"] else 0
        ids.ring.value = ratio
        ids.ring_text.text = f"{ratio:.0%}"
        ids.metric_photos.text = f"{sm['photos']}/{sm['photos_expected']}"
        ids.metric_bbch.text = f"{sm['bbch']}/{sm['cells']}"
        ids.metric_notes.text = str(sm["notes"])
        self._build_visual(sm)
        lack = []
        if sm["missing_photos"]:
            n = sm["missing_photos"]   # registros sin ninguna foto
            lack.append(f"{n} registro" + ("s" if n != 1 else "") + " sin fotos")
        if sm["missing_bbch"]:
            lack.append(f"{sm['missing_bbch']} estado" + ("s" if sm["missing_bbch"] != 1 else ""))
        ids.lack_text.text = ("Faltan " + " y ".join(lack)) if lack else "Completo"
        ids.lack_text.text_color = c(theme.BERRY) if lack else c(theme.LEAF)
        mb = sm["est_kb"] / 1024
        ids.size_text.text = f"≈ {mb:.1f} MB" if mb >= 1 else f"≈ {sm['est_kb']} KB"
        # «Por variedad»: el informe completo se abre desde cada frambuesa.
        ids.preview_btn.opacity = 1 if self.kind == "matrix" else 0
        ids.preview_btn.disabled = self.kind != "matrix"
        ids.preview_btn.height = dp(48) if self.kind == "matrix" else 0

    # ------------------------------------------------- frambuesas y mapa de estados
    def _open_cell(self, cell):
        """Celda del mapa: la línea de tiempo de esa variedad, en esa semana."""
        app().open_timeline(cell["variety_id"], cell["week_id"])

    def _build_visual(self, sm):
        a = app()
        box = self.ids.visual
        fast_clear(box)
        unit = "sectores" if (a.workspace or {}).get("profile") == "predio" else "variedades"
        codes = [cl["code"] for r in sm["rows"] for cl in r["cells"] if cl["code"] is not None]
        span = ""
        if codes:
            lo, hi = min(codes, key=ph.bbch_value), max(codes, key=ph.bbch_value)
            span = (f"BBCH {ph.code_str(lo)}" if lo == hi
                    else f"BBCH {ph.code_str(lo)} a {ph.code_str(hi)}")
        if self.kind == "variety" and self._plan():
            self._build_map(sm, self._plan(), box, span)
            return
        if self.kind == "variety" and a.db.is_predio:
            no_map_card(box, (a.workspace or {}).get("name") or "este predio")
        if self.kind == "variety":
            started = sum(1 for r in sm["rows"] if any(cl["code"] is not None or cl["n_photos"]
                                                       for cl in r["cells"]))
            self.ids.headline.text = " · ".join(x for x in (
                f"{started} de {len(sm['rows'])} {unit} con registros", span) if x)
            from kivy.uix.gridlayout import GridLayout
            grid = GridLayout(cols=3, spacing=dp(8), size_hint_y=None)
            grid.bind(minimum_height=grid.setter("height"))
            for r in sm["rows"]:
                grid.add_widget(self._tile(r))
            box.add_widget(grid)
            return
        self.ids.headline.text = " · ".join(x for x in (
            f"{len(sm['rows'])} {unit} × {len(sm['week_labels'])} semanas", span) if x) + \
            "  ·  toque una celda para abrir el registro"
        from kivy.uix.scrollview import ScrollView
        rows = [dict(r, name=ph.unit_compact(r)) for r in sm["rows"]]   # predio: «Meeker 2019 · E1-S1»
        names = StageNames(rows=rows)
        hm = StageHeatmap(on_cell=self._open_cell)
        hm.weeks, hm.rows = sm["week_labels"], rows
        row = BoxLayout(size_hint_y=None, height=hm.height)
        row.add_widget(names)
        sv = ScrollView(do_scroll_x=True, do_scroll_y=False, bar_width=dp(3),
                        scroll_type=["bars", "content"])
        sv.add_widget(hm)
        row.add_widget(sv)
        box.add_widget(row)
        if hm.width > dp(200):     # muchas semanas: arrancar en las más recientes
            Clock.schedule_once(lambda *_: setattr(sv, "scroll_x", 1), 0)
        macros = sorted({ph.macro_of(cd) for cd in codes})
        if macros:
            from kivy.uix.stacklayout import StackLayout
            legend = StackLayout(size_hint_y=None, spacing=dp(6))
            legend.bind(minimum_height=legend.setter("height"))
            for m in macros:
                bg, fg = theme.stage_colors(m * 10)
                legend.add_widget(StageChip(text=ph.MACRO_STAGES.get(m, ""), bg=bg, fg=fg))
            box.add_widget(legend)

    # ------------------------------------------------------- plano del predio
    def _sector_data(self, sm, plan):
        """Por sector del plano: sus unidades y totales; y las unidades sin ubicar."""
        counts = app().db.measure_counts(app().season)
        known = {s["id"]: s for s in plan["sectors"]}
        data = {sid: {"plan": s, "rows": [], "records": 0, "photos": 0, "measures": 0,
                      "last": None} for sid, s in known.items()}
        loose = []
        for r in sm["rows"]:
            sid = f"E{r.get('irrigation') or 0}-S{r.get('sector') or 0}"
            if sid not in data:
                loose.append(r)
                continue
            d = data[sid]
            d["rows"].append(r)
            d["records"] += sum(1 for cl in r["cells"] if cl["code"] is not None or cl["n_photos"])
            d["photos"] += sum(cl["n_photos"] for cl in r["cells"])
            d["measures"] += counts.get(r["variety_id"], 0)
            for i, cl in enumerate(r["cells"]):
                if cl["code"] is not None:
                    key = (i, ph.bbch_value(cl["code"]))
                    if d["last"] is None or key > d["last"][0]:
                        d["last"] = (key, cl)
        status = {}
        for sid, d in data.items():
            if d["records"] or d["measures"]:
                status[sid] = {"data": True, "dot": d["measures"] > 0}
        return data, status, loose

    def _build_map(self, sm, plan, box, span):
        data, status, loose = self._sector_data(sm, plan)
        self._sectors = data
        active = [sid for sid in data if sid in status]
        self.ids.headline.text = " · ".join(x for x in (
            f"{len(active)} de {len(data)} sectores con datos", span) if x)
        if self.sel_sector not in data:
            latest = max(active, key=lambda sid: (data[sid]["last"] or ((-1, -1), None))[0],
                         default="")
            self.sel_sector = latest

        self._map = sector_map_block(box, plan, status, self.sel_sector, self._select_sector)
        self._sector_box = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing=dp(8))
        box.add_widget(self._sector_box)
        self._fill_sector(self._sector_box, self.sel_sector)
        if loose:
            box.add_widget(MDLabel(text=f"Sin ubicar en el plano ({len(loose)}): falta su sector o "
                                        "equipo de riego en Ajustes › Variedades.",
                                   font_style="Caption", adaptive_height=True,
                                   theme_text_color="Custom", text_color=c(theme.MUTED)))
            box.add_widget(self._tile_grid(loose))

    def _select_sector(self, sid):
        self.sel_sector = sid
        if getattr(self, "_map", None) is not None:
            self._map.selected = sid
        if getattr(self, "_sector_box", None) is not None:
            self._fill_sector(self._sector_box, sid)

    def _tile_grid(self, rows, before_open=None):
        from kivy.uix.gridlayout import GridLayout
        grid = GridLayout(cols=3, spacing=dp(8), size_hint_y=None)
        grid.bind(minimum_height=grid.setter("height"))
        for r in rows:
            grid.add_widget(self._tile(r, before_open))
        return grid

    def _fill_sector(self, box, sid, before_open=None):
        """Ficha del sector elegido: datos del plano, totales y sus unidades (frambuesas)."""
        fast_clear(box)
        d = (getattr(self, "_sectors", None) or {}).get(sid)
        if not d:
            box.add_widget(MDLabel(text="Toque un sector del plano para ver su información.",
                                   font_style="Body2", adaptive_height=True,
                                   theme_text_color="Custom", text_color=c(theme.MUTED)))
            return
        p = d["plan"]
        box.add_widget(MDLabel(text=f"Equipo de riego {p['equipo']} · sector {p['sector']}",
                               font_style="Subtitle1", bold=True, adaptive_height=True,
                               theme_text_color="Custom", text_color=c(theme.LEAF_DARK)))
        info = []
        if p.get("ha"):
            info.append(f"{p['ha']:.2f} ha".replace(".", ","))
        if p.get("hileras"):
            info.append(f"{p['hileras']} hileras")
        if p.get("variedades"):
            info.append("plano: " + ", ".join(p["variedades"]))
        if info:
            box.add_widget(MDLabel(text=" · ".join(info), font_style="Caption", adaptive_height=True,
                                   theme_text_color="Custom", text_color=c(theme.MUTED)))
        if not d["rows"]:
            box.add_widget(MDLabel(text="Sin unidades en este sector (se agregan en Ajustes › "
                                        "Variedades con este equipo de riego y sector).",
                                   font_style="Body2", adaptive_height=True,
                                   theme_text_color="Custom", text_color=c(theme.MUTED)))
            return
        n = len(d["rows"])
        parts = [f"{n} unidad" + ("es" if n != 1 else ""),
                 f"{d['records']} registro" + ("s" if d["records"] != 1 else ""),
                 f"{d['photos']} foto" + ("s" if d["photos"] != 1 else ""),
                 f"{d['measures']} medici" + ("ones" if d["measures"] != 1 else "ón")]
        if d["last"]:
            cl = d["last"][1]
            parts.append(f"último: {cl['week']} · BBCH {ph.code_str(cl['code'])}")
        box.add_widget(MDLabel(text=" · ".join(parts), font_style="Body2", adaptive_height=True,
                               theme_text_color="Custom", text_color=c(theme.INK)))
        # Lo que se mide en el sector: cada variedad (con su año de plantación y código).
        rows = [dict(r, display=ph.unit_label(r)) for r in d["rows"]]
        box.add_widget(self._tile_grid(rows, before_open))

    def _tile(self, row, before_open=None):
        """Frambuesa de la variedad: a color si tiene registros en la temporada."""
        cells = [cl for cl in row["cells"] if cl["code"] is not None or cl["n_photos"]]
        last = next((cl for cl in reversed(row["cells"]) if cl["code"] is not None), None)
        if last is not None:
            code = last["code"]
            sub, col = f"{last['week']} · {ph.bbch_label(code)}", c(theme.MUTED)
        else:
            code = None
            sub, col = ("Sin estado registrado" if cells else "Sin registros"), c(theme.BERRY)
        bg, fg = bbch_tag_colors(code)
        tile = PreviewTile(title=row.get("display") or ph.unit_main(row), subtitle=sub, sub_color=col,
                           badge=f"BBCH {ph.code_str(code)}" if code is not None else "",
                           badge_bg=bg, badge_fg=fg,
                           berry=theme.berry_art(row.get("cultivar") or "", row["name"],
                                                 gray=not cells))

        def go(*_):
            if before_open:
                before_open()
            app().open_timeline(row["variety_id"])
        tile.bind(on_release=go)
        return tile

    # ----------------------------------------------------------- vista previa
    def open_preview(self):
        """Matriz global completa (de la temporada o del mes elegido)."""
        a = app()
        r = a.configured_reports()
        rng = self._range()
        self.ids.preview_btn.disabled = True
        self.ids.preview_btn.text = "Preparando vista previa…"

        def work():
            try:
                res = (r.matrix(a.season, rng[0], rng[1], package="preview") if rng
                       else r.matrix(a.season, package="preview"))
                Clock.schedule_once(lambda *_: self._ready(res, None))
            except Exception as exc:  # noqa: BLE001
                error = exc
                Clock.schedule_once(lambda *_: self._ready(None, error))

        a.workers.submit(work)

    def _ready(self, res, error):
        self.ids.preview_btn.disabled = False
        self.ids.preview_btn.text = "Ver vista previa completa"
        if error:
            app().toast(f"No se pudo preparar la vista previa: {error}")
            return
        app().media.preview(res.path, res.title)


# Referencias a otras pantallas (al final: así no hay importaciones circulares).
from ui.sectors_ui import no_map_card, sector_map_block  # noqa: E402
from ui.sampling import season_dialog  # noqa: E402
