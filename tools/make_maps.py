"""
tools/make_maps.py
==================
Convierte el GeoJSON de sectores de un predio (lon/lat, el mismo plano que usa la app de
sanidad vegetal) al mapa liviano que dibuja la vista previa: metros desde la esquina
suroeste, y hacia arriba = norte.

    python tools/make_maps.py sectores-el-amanecer.json AM "El Amanecer"
    -> assets/maps/AM.json

MERGE une partes de un sector que en el plano están cortadas (necesita shapely, solo
aquí; la app no lo usa).
"""
import json
import math
import sys
from pathlib import Path


# Partes («parte» del GeoJSON) que se dibujan como un solo polígono.
MERGE = {"AM": {"E1-S1": [[1, 2, 3]]}}   # 1-1 norte en una pieza; el sur queda aparte


def _merge(rings: dict, groups) -> list:
    """rings: {parte: [x, y, …]} -> anillos con los grupos unidos (unión con un margen
    mínimo para cerrar las rendijas entre franjas)."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    out, used = [], set()
    for group in groups:
        polys = [Polygon(list(zip(rings[k][0::2], rings[k][1::2]))) for k in group]
        u = unary_union([p.buffer(1.0, join_style=2) for p in polys]).buffer(-1.0, join_style=2)
        u = u.simplify(0.3)
        if u.geom_type != "Polygon":
            u = max(u.geoms, key=lambda g: g.area)
        ring = []
        for x, y in list(u.exterior.coords)[:-1]:
            ring += [round(x, 1), round(y, 1)]
        out.append(ring)
        used |= set(group)
    return out + [r for k, r in sorted(rings.items()) if k not in used]


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
        s.setdefault("_rings", {})[pr.get("parte") or len(s["_rings"]) + 1] = ring
    for sid, s in sectors.items():
        rings = s.pop("_rings")
        groups = MERGE.get(code.upper(), {}).get(sid)
        s["parts"] = _merge(rings, groups) if groups else [r for _k, r in sorted(rings.items())]
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
