"""
Estética «frambuesa»: verdes de hoja + rojos de fruto sobre un fondo claro
difuminado, con tarjetas translúcidas tipo vidrio (glassmorphism).

KivyMD 1.2 solo acepta paletas con nombre; se re-definen las rampas «Green»
(-> verde hoja) y «Pink» (-> frambuesa) antes de construir la app.
"""
import os

from kivy.utils import get_color_from_hex

from platform_utils import resource_path

# --- Verdes (hoja) --------------------------------------------------------
LEAF_DARK = "#1E4A3A"     # tinta principal / trazos
LEAF = "#2F6B4F"
LEAF_LIGHT = "#6FA86A"
LEAF_SOFT = "#DDEFD8"
# --- Rojos (fruto) --------------------------------------------------------
BERRY = "#A8184A"         # acción principal / estado activo
BERRY_DARK = "#7E1238"
BERRY_LIGHT = "#E0718F"
BERRY_SOFT = "#F8DCE4"
# --- Neutros y vidrio -----------------------------------------------------
INK = "#1B2A23"
INK_2 = "#41534A"
MUTED = "#6E7E75"
WARN = "#B7791F"
GLASS = "#FFFFFFA8"       # tarjetas translúcidas (~66 %)
GLASS_STRONG = "#FFFFFFD9"
GLASS_EDGE = "#FFFFFFE6"  # borde luminoso del vidrio
LINE = "#1E4A3A2E"        # líneas finas verdes translúcidas
CLEAR = "#00000000"
SURFACE = "#FFFFFF"       # superficies claras (barras, botones fantasma, campos) con su alfa
FILL_DARK = "#1E4A3A"     # rellenos oscuros con texto blanco (franja del ensayo, avisos)
NAV_TILE = "#FFFFFF"      # azulejos de la barra inferior (sus íconos son oscuros)
ON_BERRY = "#FFFFFF"      # texto sobre el color de la fruta (píldoras elegidas)

# --- «Mente del sistema» (módulo de IA): negros/azules con grises -------------
MIND_BG = resource_path("assets", "ui", "mind_bg.jpg")
MIND_CARD = "#0F1A2CC7"      # vidrio oscuro
MIND_CARD_2 = "#16233ACC"
MIND_EDGE = "#4FC3F740"      # borde cian tenue
MIND_TEXT = "#DCE6F2"
MIND_MUTED = "#8C9BB3"
MIND_ACCENT = "#4FC3F7"      # cian
MIND_ACCENT_2 = "#7C8CFF"    # índigo
MIND_INK = "#06121F"         # texto sobre botones cian
MIND_OK = "#34D399"
MIND_BAD = "#F87171"
MIND_FIRE = "#FFB454"

BACKGROUND = resource_path("assets", "ui", "background.jpg")
LOGO = resource_path("assets", "ui", "logo.png")
APP_LOGO = resource_path("assets", "ui", "app_logo.png")   # los tres frutos (pantalla de cultivos)
WORDMARK = resource_path("assets", "ui", "wordmark.png")
# Frambuesas ilustradas (vista previa): color = semana con registro; gris = sin registro.
BERRY_KEYS = ("meeker", "wakefield", "lagorai", "cascade_harvest", "codigo_11", "codigo_24",
              "codigo_31", "codigo_55", "codigo_81")


def berry_art(*names: str, gray: bool = False) -> str:
    """Dibujo de la variedad (por nombre o variedad del sector); si no tiene uno propio,
    siempre el mismo de los 9 (según el nombre) para que cada una se reconozca."""
    import unicodedata
    import zlib

    def slug(t):
        t = unicodedata.normalize("NFKD", t or "")
        t = "".join(ch for ch in t if not unicodedata.combining(ch)).lower()
        t = t.replace("n°", "").replace("nº", "").replace("no.", "")
        return "_".join(w for w in "".join(ch if ch.isalnum() else " " for ch in t).split())

    if crop_id != "frambuesa":     # PhenoBlue / PhenoCran: su fruto (gris sin registro)
        return resource_path("assets", "crops", crop_id, "fruit_gris.png" if gray else "fruit.png")
    keys = [slug(n) for n in names if n]
    key = next((k for k in keys if k in BERRY_KEYS), None)
    if key is None:
        base = keys[0] if keys else ""
        key = BERRY_KEYS[zlib.crc32(base.encode()) % len(BERRY_KEYS)]
    return resource_path("assets", "ui", "berries", f"{key}{'_gris' if gray else ''}.png")
   # letra «PhenoRubus App»
# Pantalla de inicio: botones circulares e ícono de la IA (frambuesa-cerebro delineada)
START_ID = resource_path("assets", "ui", "start_id.png")           # trazo frambuesa
START_PREDIO = resource_path("assets", "ui", "start_predio.png")   # trazo verde
START_AI = resource_path("assets", "ui", "start_ai.png")           # azul estelar
LOGO_LINE = resource_path("assets", "ui", "logo_line.png")         # logo a línea
START_BG = resource_path("assets", "ui", "start_bg.jpg")           # degradado + trazos tenues
BLOB_ID = resource_path("assets", "ui", "blob_id.png")
BLOB_PREDIO = resource_path("assets", "ui", "blob_predio.png")
BLOB_AI = resource_path("assets", "ui", "blob_ai.png")             # burbuja nocturna con estrellas
START_AI_NIGHT = resource_path("assets", "ui", "start_ai_night.png")
AI_GLOW = resource_path("assets", "ui", "ai_glow.png")
START_NOTEBOOK = resource_path("assets", "ui", "start_notebook.png")   # cuaderno con frambuesa
BLOB_NOTEBOOK = resource_path("assets", "ui", "blob_notebook.png")
IAPLUS = resource_path("assets", "ui", "iaplus.png")              # IA+ celeste con aura roja tenue
AI_BAR = resource_path("assets", "ui", "ai_bar.png")               # cerebro azul (barra)
DRIVE_UP = resource_path("assets", "ui", "drive_up.png")           # hay algo por subir
DRIVE_OK = resource_path("assets", "ui", "drive_ok.png")           # todo al día
DRIVE_OFF = resource_path("assets", "ui", "drive_off.png")         # sin cuenta conectada
DRIVE_SPIN = [resource_path("assets", "ui", f"spin_{k}.png") for k in range(8)]
AI_ICON = resource_path("assets", "ui", "ai_outline.png")
GOOGLE_G = resource_path("assets", "ui", "google_g.png")
# Fondo liso de la pantalla de inicio: el MISMO color que el presplash de Android
# (buildozer.spec › android.presplash_color) para que ambas se vean como una sola.
SPLASH_BG = "#F2F4EE"


def nav_icon(name: str, active: bool) -> str:
    return resource_path("assets", "ui", f"nav_{name}_{'active' if active else 'idle'}.png")


_HEX: dict = {}


def c(hex_color: str, alpha: float | None = None):
    """Color Kivy desde hex (#RRGGBB o #RRGGBBAA); `alpha` lo sobrescribe. Cada hex se
    interpreta una sola vez (las reglas KV lo llaman miles de veces)."""
    base = _HEX.get(hex_color)
    if base is None:
        rgba = get_color_from_hex(hex_color)
        if len(rgba) == 3:
            rgba.append(1.0)
        base = _HEX[hex_color] = tuple(rgba)
    rgba = list(base)
    if alpha is not None:
        rgba[3] = alpha
    return rgba


# Colores de etiqueta por estadio principal BBCH: del verde vegetativo al rojo
# de maduración (fondo, texto).
STAGE_COLORS = {
    0: ("#EDE3D6", "#6B4A2E"),   # yemas
    1: ("#DDEFD8", "#1E4A3A"),   # hojas
    3: ("#C8E4C0", "#1E4A3A"),   # brotes
    5: ("#EAF2D4", "#4D6B1F"),   # botón floral
    6: ("#FFFFFF", "#2F6B4F"),   # floración (pétalo blanco)
    7: ("#B9DDB0", "#1E4A3A"),   # fruto verde
    8: ("#F8D3DD", "#A8184A"),   # maduración
    9: ("#F3E7CC", "#7A5A1E"),   # senescencia
}


def stage_colors(code):
    if code is None:
        return c(SURFACE, .55), c(MUTED)
    import phenology as ph
    bg, fg = STAGE_COLORS.get(ph.macro_of(code), ("#FFFFFF", INK))
    return c(bg, .92), c(fg)


LEAF_RAMP = {
    "50": "EEF7EC", "100": "DDEFD8", "200": "BCDDB4", "300": "96C78C", "400": "6FA86A",
    "500": "2F6B4F", "600": "295E46", "700": "22513C", "800": "1E4A3A", "900": "143326",
    "A100": "C9EBC0", "A200": "9CD68E", "A400": "6FB85F", "A700": "4F9A45",
}
BERRY_RAMP = {
    "50": "FCEEF2", "100": "F8DCE4", "200": "F0B3C4", "300": "E78AA4", "400": "E0718F",
    "500": "A8184A", "600": "961541", "700": "7E1238", "800": "690F2F", "900": "4D0A22",
    "A100": "FF9FBA", "A200": "FF6E97", "A400": "F23D72", "A700": "D81B5A",
}


def install_palette() -> None:
    from kivymd.color_definitions import colors
    if crop_id == "frambuesa" and style == "pastel":
        colors["Green"].update(LEAF_RAMP)
        colors["Pink"].update(BERRY_RAMP)
    else:
        colors["Green"].update(_ramp(LEAF if style not in DARK_STYLES else LEAF_LIGHT))
        colors["Pink"].update(_ramp(BERRY))
    colors["Light"].update({"StatusBar": "1E4A3A", "AppBar": "2F6B4F",
                            "Background": "F3F7F2", "CardsDialogs": "FBFDFB"})
    if style in DARK_STYLES:
        colors["Dark"].update({"StatusBar": SPLASH_BG[1:7], "AppBar": SURFACE[1:7],
                               "Background": SPLASH_BG[1:7], "CardsDialogs": SURFACE[1:7]})


def apply(theme_cls) -> None:
    theme_cls.theme_style = "Dark" if style in DARK_STYLES else "Light"
    theme_cls.primary_palette = "Green"
    theme_cls.primary_hue = "500"
    theme_cls.accent_palette = "Pink"
    theme_cls.material_style = "M2"


# ---------------------------------------------------------------------------
# Rendimiento: KivyMD 1.2 registra CADA widget en el tema con `theme_cls.bind(...)`.
# `bind` de Kivy compara contra todos los registros anteriores (también los de widgets
# ya destruidos), así que crear una pantalla se volvía más lento cuanto más se usaba
# la app. `fbind(..., ref=True)` registra lo mismo (referencia débil) sin esa búsqueda,
# y `purge_theme_observers` borra cada tanto los registros de widgets que ya no existen.
# ---------------------------------------------------------------------------
def speed_up_theme_bindings() -> None:
    from kivymd.theming import ThemeManager
    if getattr(ThemeManager, "_fast_bind", False):
        return

    def bind(self, **kwargs):
        for name, callback in kwargs.items():
            if self.fbind(name, callback, ref=True) == 0:   # nombre desconocido: como antes
                raise KeyError(name)

    ThemeManager.bind = bind
    ThemeManager._fast_bind = True


def purge_theme_observers(theme_cls) -> int:
    """Quita los observadores muertos (widgets destruidos) de las propiedades del tema."""
    removed = 0
    for name in theme_cls.properties():
        try:
            observers = theme_cls.get_property_observers(name, args=True)
        except Exception:  # noqa: BLE001
            continue
        for callback, _largs, _kwargs, is_ref, uid in observers:
            if is_ref and getattr(callback, "is_dead", lambda: False)():
                theme_cls.unbind_uid(name, uid)
                removed += 1
    return removed

# Hoja de tareas pendientes (inicio): dibujos de frambueso estilo cuaderno de Da Vinci y
# letra manuscrita Caveat (SIL Open Font License, assets/fonts/Caveat-OFL.txt).
DV_CANE = resource_path("assets", "ui", "dv_cane.png")
DV_CLUSTER = resource_path("assets", "ui", "dv_cluster.png")
DV_FLOWER = resource_path("assets", "ui", "dv_flower.png")
DV_CUT = resource_path("assets", "ui", "dv_cut.png")
DV_BRANCH = resource_path("assets", "ui", "dv_branch.png")
HAND_FONT = resource_path("assets", "fonts", "Caveat.ttf")


# ---------------------------------------------------------------------------
# Cultivo y estilo de la app (Ajustes › Estilo). configure() reemplaza los colores y
# las imágenes de arriba; las pantallas que se construyen después ya los usan (la app las
# rehace al cambiar de cultivo o de estilo).
# ---------------------------------------------------------------------------
STYLES = {
    "pastel": ("Pastel de fruta", "Verdes suaves y el color de la fruta, con tarjetas de vidrio"),
    "bosque": ("Bosque", "Verdes oscuros lisos y bordes simples; íconos y logos con su color"),
    "lino": ("Lino", "Claro y cálido, como papel de cuaderno, con detalles verde oliva"),
    "noche": ("Noche de huerto", "Azul noche y ciruela, con la fruta encendida como neón"),
}
DEFAULT_STYLE = "pastel"

# Color de la fruta (acento): frambuesa, arándano azul, cranberry carmesí.
FRUIT = {
    "frambuesa": {"BERRY": "#A8184A", "BERRY_DARK": "#7E1238", "BERRY_LIGHT": "#E0718F", "BERRY_SOFT": "#F8DCE4"},
    "arandano": {"BERRY": "#3E5AA8", "BERRY_DARK": "#2A3F7E", "BERRY_LIGHT": "#8EA3DC", "BERRY_SOFT": "#DEE5F7"},
    "cranberry": {"BERRY": "#9C1C34", "BERRY_DARK": "#741427", "BERRY_LIGHT": "#D7707F", "BERRY_SOFT": "#F6DADF"},
}
# Fruta sobre fondos oscuros: más luminosa.
FRUIT_GLOW = {
    "frambuesa": {"BERRY": "#FF6A93", "BERRY_DARK": "#FF9AB5", "BERRY_LIGHT": "#C8496F"},
    "arandano": {"BERRY": "#8FADFF", "BERRY_DARK": "#B5C8FF", "BERRY_LIGHT": "#5B78C8"},
    "cranberry": {"BERRY": "#FF5D78", "BERRY_DARK": "#FF95A6", "BERRY_LIGHT": "#C43B55"},
}
_BASE = {k: globals()[k] for k in (
    "LEAF_DARK", "LEAF", "LEAF_LIGHT", "LEAF_SOFT", "INK", "INK_2", "MUTED", "WARN", "GLASS",
    "GLASS_STRONG", "GLASS_EDGE", "LINE", "SURFACE", "SPLASH_BG", "FILL_DARK", "NAV_TILE", "ON_BERRY")}
STYLE_COLORS = {
    "pastel": {},
    "bosque": {
        "LEAF_DARK": "#E3F0E6", "LEAF": "#9FD3B0", "LEAF_LIGHT": "#7FC29B", "LEAF_SOFT": "#2C5547",
        "INK": "#EEF5F0", "INK_2": "#C5D8CC", "MUTED": "#94B3A2", "WARN": "#E8B55A",
        "GLASS": "#214739F5", "GLASS_STRONG": "#26503FFA", "GLASS_EDGE": "#3B6A59",
        "LINE": "#FFFFFF24", "SURFACE": "#245043", "SPLASH_BG": "#17332B",
        "BERRY_SOFT": "#35574C", "FILL_DARK": "#0E2620", "NAV_TILE": "#DCEBE1", "ON_BERRY": "#0E2620"},
    "lino": {
        "LEAF_DARK": "#3D4A27", "LEAF": "#5E6E38", "LEAF_LIGHT": "#93A266", "LEAF_SOFT": "#E9EBD9",
        "INK": "#2E2A24", "INK_2": "#4F483E", "MUTED": "#8A8070", "WARN": "#B7791F",
        "GLASS": "#FFFFFFEB", "GLASS_STRONG": "#FFFFFFF7", "GLASS_EDGE": "#E3DACB",
        "LINE": "#5E6E3833", "SURFACE": "#FFFDF8", "SPLASH_BG": "#F6F1E7", "FILL_DARK": "#3D4A27"},
    "noche": {
        "LEAF_DARK": "#B6F0D4", "LEAF": "#72DCAC", "LEAF_LIGHT": "#4FB386", "LEAF_SOFT": "#1F3A40",
        "INK": "#ECE9F5", "INK_2": "#C4C0D6", "MUTED": "#9A96B0", "WARN": "#F2B65A",
        "GLASS": "#1E2240D9", "GLASS_STRONG": "#232849F0", "GLASS_EDGE": "#FFFFFF26",
        "LINE": "#FFFFFF22", "SURFACE": "#262B4E", "SPLASH_BG": "#15172B",
        "FILL_DARK": "#0D0F1F", "NAV_TILE": "#D9DCF2", "ON_BERRY": "#12142A"},
}
DARK_STYLES = ("bosque", "noche")
FRUIT_SOFT_DARK = {"noche": {"frambuesa": "#42223A", "arandano": "#252F58", "cranberry": "#45202C"}}

crop_id = "frambuesa"
style = DEFAULT_STYLE


def _crop_asset(name: str, crop: str) -> str:
    path = resource_path("assets", "crops", crop, name)
    return path if crop != "frambuesa" and os.path.exists(path) else resource_path("assets", "ui", name)


def is_dark() -> bool:
    return style in DARK_STYLES


def configure(crop: str | None = None, style_name: str | None = None) -> None:
    """Colores e imágenes del cultivo y del estilo (antes de construir las pantallas)."""
    global crop_id, style, BACKGROUND, START_BG, BLOB_ID, LOGO, WORDMARK
    crop_id = crop or crop_id
    style = style_name if style_name in STYLES else (style if style_name is None else DEFAULT_STYLE)
    g = globals()
    g.update(_BASE)
    g.update(FRUIT.get(crop_id, FRUIT["frambuesa"]))
    g.update(STYLE_COLORS[style])
    if style in DARK_STYLES:
        glow = FRUIT_GLOW.get(crop_id, FRUIT_GLOW["frambuesa"])
        g.update(glow if style == "noche" else {k: glow[k] for k in ("BERRY", "BERRY_DARK")})
        if style == "noche":
            g["BERRY_SOFT"] = FRUIT_SOFT_DARK["noche"].get(crop_id, "#42223A")
    LOGO = _crop_asset("logo.png", crop_id)
    WORDMARK = _crop_asset("wordmark.png", crop_id)
    if style == "pastel":
        BACKGROUND = _crop_asset("background.jpg", crop_id)
        START_BG = _crop_asset("start_bg.jpg", crop_id)
    else:
        BACKGROUND = START_BG = resource_path("assets", "styles", style, "background.jpg")
    BLOB_ID = _crop_asset("blob_id.png", crop_id)
    install_palette()


def _ramp(hex_color: str) -> dict:
    """Rampa de KivyMD (50…900) a partir del color medio."""
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))

    def mix(t, to):
        return "".join(f"{int(v + (to - v) * t):02X}" for v in (r, g, b))
    ramp = {"500": f"{r:02X}{g:02X}{b:02X}"}
    for k, t in (("50", .92), ("100", .84), ("200", .68), ("300", .5), ("400", .3)):
        ramp[k] = mix(t, 255)
    for k, t in (("600", .1), ("700", .22), ("800", .34), ("900", .5)):
        ramp[k] = mix(t, 0)
    ramp.update({"A100": ramp["200"], "A200": ramp["300"], "A400": ramp["400"], "A700": ramp["600"]})
    return ramp


def crop_accent(crop: str) -> str:
    """Color de la fruta de un cultivo en el estilo actual (tarjetas de la pantalla de cultivos)."""
    if style in DARK_STYLES:
        return FRUIT_GLOW.get(crop, FRUIT_GLOW["frambuesa"])["BERRY"]
    return FRUIT.get(crop, FRUIT["frambuesa"])["BERRY"]


def crop_logo(crop: str) -> str:
    return _crop_asset("logo.png", crop)


def on_bg(hex_color: str) -> list:
    """Un color fijo de texto (p. ej. el nombre de cada botón del inicio) legible en el
    estilo actual: en los oscuros se aclara."""
    if style not in DARK_STYLES:
        return c(hex_color)
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return c("#" + "".join(f"{int(v + (255 - v) * .55):02X}" for v in (r, g, b)))


def nav_tile_alpha() -> float:
    return .9 if style in DARK_STYLES else .55
