"""
tools/make_maps.py
==================
Convierte el GeoJSON de sectores de un predio (lon/lat, el mismo plano que usa la app de
sanidad vegetal) al mapa liviano que dibuja la vista previa: metros desde la esquina
suroeste, y hacia arriba = norte.

    python tools/make_maps.py sectores-el-amanecer.json AM "El Amanecer"
    -> assets/maps/AM.json
"""
import json
import math
import sys
from pathlib import Path


def convert(src: str, code: str, name: str) -> Path:
    d = json.loads(Path(src).read_text(encoding="utf-8"))
    pts = [p for f in d["features"] for p in f["geometry"]["coordinates"][0]]
    lat0 = sum(p[1] for p in pts) / len(pts)
    kx, ky = math.cos(math.radians(lat0)) * 111320, 110574
    x0 = min(p[0] for p in pts) * kx
    y0 = min(p[1] for p in pts) * ky
    sectors: dict = {}
    for f in d["features"]:
        pr = f["properties"]
        ring, last = [], None
        for lon, lat in f["geometry"]["coordinates"][0]:
            xy = (round(lon * kx - x0, 1), round(lat * ky - y0, 1))
            if xy != last:
                ring += xy
                last = xy
        if ring[:2] == ring[-2:]:
            ring = ring[:-2]
        s = sectors.setdefault(pr["sector_id"], {
            "id": pr["sector_id"], "equipo": int(pr["equipo"]), "sector": int(pr["sector"]),
            "nombre": pr["nombre"], "variedades": pr.get("variedades_sector") or [],
            "ha": pr.get("ha_sector"), "hileras": pr.get("hileras_sector"), "parts": []})
        s["parts"].append(ring)
    xs = [x for s in sectors.values() for r in s["parts"] for x in r[0::2]]
    ys = [y for s in sectors.values() for r in s["parts"] for y in r[1::2]]
    out = {"name": name, "origin": d.get("origen", ""), "w": round(max(xs), 1),
           "h": round(max(ys), 1),
           "sectors": sorted(sectors.values(), key=lambda s: (s["equipo"], s["sector"]))}
    dst = Path(__file__).resolve().parent.parent / "assets" / "maps" / f"{code}.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return dst


if __name__ == "__main__":
    print(convert(*sys.argv[1:4]))
