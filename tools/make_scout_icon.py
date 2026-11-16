"""Ícono y pantalla de carga de la app AeonScout sola (release_scout.env):
logo de AeonScout (assets/ui/scout_logo.png) sobre el fondo del ícono de AeonCrop."""
import os

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
A = lambda *p: os.path.join(ROOT, "assets", *p)   # noqa: E731

logo = Image.open(A("ui", "scout_logo.png")).convert("RGBA")
bg = Image.open(A("icon_aeoncrop_bg.png")).convert("RGBA")

# Ícono adaptativo: fondo y logo dentro de la zona segura (66 % central).
fg = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
L = logo.resize((330, 330), Image.LANCZOS)
fg.alpha_composite(L, (91, 91))
fg.save(A("icon_scout_fg.png"))
bg.convert("RGB").save(A("icon_scout_bg.png"))

# Ícono clásico: esquinas redondeadas como el de AeonCrop.
icon = bg.copy()
icon.alpha_composite(logo.resize((420, 420), Image.LANCZOS), (46, 46))
mask = Image.new("L", (512, 512), 0)
ImageDraw.Draw(mask).rounded_rectangle((0, 0, 511, 511), radius=96, fill=255)
icon.putalpha(mask)
icon.save(A("icon_scout.png"))

# Pantalla de carga (mismo tamaño y color que assets/presplash.png).
pre = Image.open(A("presplash.png")).convert("RGB")
w, h = pre.size
out = Image.new("RGB", (w, h), pre.getpixel((2, 2)))
side = int(w * .55)
out.paste(logo.resize((side, side), Image.LANCZOS), ((w - side) // 2, int(h * .45 - side / 2)),
          logo.resize((side, side), Image.LANCZOS))
out.save(A("presplash_scout.png"), optimize=True)
print("ícono y pantalla de carga de AeonScout listos")
