// PhenoRubus Web · mapas con OpenStreetMap (Leaflet): mapa de calor de dónde se tomaron las
// fotos (= ui/heatmap.py) y marcar la ubicación de un registro (= ui.mapview.MapPicker).
const CDN = window.__PR_CDN__ || "https://unpkg.com/";
const DEFAULT_CENTER = [-33.45, -70.66];          // Chile central (= geo.DEFAULT_CENTER)
const RAMP = { 0.0: "#6FA86A", 0.35: "#F4B400", 0.7: "#FF7043", 1.0: "#C62828" };   // = geo.HEAT_RAMP
let loading = null;

function load() {
  loading ||= new Promise((resolve, reject) => {
    const css = document.createElement("link");
    css.rel = "stylesheet"; css.href = `${CDN}leaflet@1.9.4/dist/leaflet.css`;
    document.head.appendChild(css);
    const js = (src) => new Promise((ok, bad) => {
      const s = document.createElement("script"); s.src = src; s.onload = ok; s.onerror = () => bad(new Error("No se pudo cargar el mapa."));
      document.head.appendChild(s);
    });
    js(`${CDN}leaflet@1.9.4/dist/leaflet.js`).then(() => js(`${CDN}leaflet.heat@0.2.0/dist/leaflet-heat.js`))
      .then(() => resolve(window.L), (e) => { loading = null; reject(e); });
  });
  return loading;
}

// Fondo satelital (Esri World Imagery) por defecto, con nombres de lugares encima; «Mapa»
// (OpenStreetMap) para ver calles. La elección se recuerda en este navegador.
function baseMap(L, el, center, zoom) {
  const map = L.map(el, { zoomControl: true, attributionControl: true, maxZoom: 20 }).setView(center, zoom);
  const esri = "https://server.arcgisonline.com/ArcGIS/rest/services";
  const sat = L.layerGroup([
    L.tileLayer(`${esri}/World_Imagery/MapServer/tile/{z}/{y}/{x}`, {
      maxNativeZoom: 18, maxZoom: 20, attribution: "Imágenes © Esri, Maxar, Earthstar Geographics" }),
    L.tileLayer(`${esri}/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}`, {
      maxNativeZoom: 18, maxZoom: 20, opacity: .85 }),
  ]);
  const osm = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxNativeZoom: 19, maxZoom: 20, attribution: "© OpenStreetMap" });
  const layers = { "Satélite": sat, "Mapa": osm };
  let pick = "Satélite";
  try { pick = localStorage.getItem("pr_basemap") || pick; } catch { /* sin almacenamiento */ }
  (layers[pick] || sat).addTo(map);
  L.control.layers(layers, null, { position: "topright", collapsed: false }).addTo(map);
  map.on("baselayerchange", (e) => { try { localStorage.setItem("pr_basemap", e.name); } catch { /* nada */ } });
  return map;
}

// Mapa de calor: points = [{lat, lon, weight, …}]; popup(p) -> nodo HTML del punto.
// fallback: [[lat, lon], [lat, lon]] del predio para encuadrar si no hay fotos (no Santiago).
// keepView: al cambiar entre temporada y semana se conserva la vista actual.
export async function photoHeat(el, points, popup, { fallback = null, keepView = false } = {}) {
  const L = await load();
  let map = el._map;
  if (!map || !el._heatLayer) {
    if (map) map.remove();
    map = baseMap(L, el, DEFAULT_CENTER, 12);
    el._map = map;
    keepView = false;
  }
  if (el._heatLayer) el._heatLayer.forEach((l) => l.remove());
  el._heatLayer = [];
  if (points.length) {
    const top = Math.max(...points.map((p) => p.weight));
    el._heatLayer.push(L.heatLayer(points.map((p) => [p.lat, p.lon, p.weight / top]),
      { radius: 30, blur: 22, maxZoom: 17, gradient: RAMP, minOpacity: .25 }).addTo(map));
    for (const p of points) {
      el._heatLayer.push(L.circleMarker([p.lat, p.lon], { radius: 5, color: "#fff", weight: 1.5, fillColor: "#A8184A", fillOpacity: 1 })
        .bindPopup(() => popup(p)).addTo(map));
    }
  }
  if (!keepView) {
    if (points.length) map.fitBounds(L.latLngBounds(points.map((p) => [p.lat, p.lon])).pad(.25), { maxZoom: 18 });
    else if (fallback) map.fitBounds(L.latLngBounds(fallback), { maxZoom: 17 });
  }
  setTimeout(() => map.invalidateSize(), 50);
  return map;
}

// Marcar un punto: tocar el mapa mueve el pin. Devuelve () => [lat, lon] | null.
export async function pickPoint(el, start) {
  const L = await load();
  if (el._map) { el._map.remove(); el._map = null; }
  const map = baseMap(L, el, start || DEFAULT_CENTER, start ? 18 : 12);
  el._map = map;
  let marker = start ? L.marker(start, { draggable: true }).addTo(map) : null;
  map.on("click", (e) => {
    if (marker) marker.setLatLng(e.latlng);
    else marker = L.marker(e.latlng, { draggable: true }).addTo(map);
  });
  setTimeout(() => map.invalidateSize(), 50);
  return () => (marker ? [marker.getLatLng().lat, marker.getLatLng().lng] : null);
}

// Plano de sectores del predio sobre el satélite (= ui.sector_map con «Satélite»): cada sector
// con el color de su equipo de riego y su número; un clic lo selecciona. El mapa se conserva
// entre redibujos (no pierde el zoom); solo se reencuadra al cambiar de equipo.
const NEON = { 1: "#FF3B3B", 2: "#FFC21A", 3: "#2E9BFF", 4: "#36E05A" };   // = ui.sector_map.NEON
export async function sectorMap(el, plan, { color, hasData, selected, eq, onSelect }) {
  const L = await load();
  let st = el._sector;
  if (!st || st.plan !== plan || !el._map) {
    if (el._map) el._map.remove();
    const g = plan.geo;
    const ll = (x, y) => [(y + g.y0) / g.ky, (x + g.x0) / g.kx];
    const map = baseMap(L, el, ll(plan.w / 2, plan.h / 2), 15);
    el._map = map;
    const items = new Map();
    for (const s of plan.sectors) {
      const rings = s.parts.map((p) => { const r = []; for (let i = 0; i < p.length; i += 2) r.push(ll(p[i], p[i + 1])); return r; });
      const poly = L.polygon(rings, { weight: 1.2 }).addTo(map);
      poly.bindTooltip(s.nombre, { sticky: true });
      poly.on("click", () => st.onSelect(s.id));
      const big = rings.reduce((a, b) => (b.length > a.length ? b : a));
      const c = big.reduce((a, p) => [a[0] + p[0] / big.length, a[1] + p[1] / big.length], [0, 0]);
      const label = L.marker(c, { interactive: false, icon: L.divIcon({ className: "seclabel", html: String(s.sector), iconSize: [22, 16] }) });
      items.set(s.id, { s, poly, label });
    }
    const showLabels = () => { const on = map.getZoom() >= 15; for (const it of items.values()) on ? it.label.addTo(map) : it.label.remove(); };
    map.on("zoomend", showLabels);
    st = el._sector = { plan, map, items, eq: undefined, showLabels };
  }
  st.onSelect = onSelect;
  for (const { s, poly } of st.items.values()) {
    const sel = s.id === selected;
    poly.setStyle({ fillColor: color(s), fillOpacity: hasData(s) ? .62 : .38,
      color: sel ? NEON[s.equipo] || "#fff" : "#ffffff", weight: sel ? 4 : 1.2, opacity: 1 });
    if (sel) poly.bringToFront();
  }
  if (st.eq !== eq) {
    const pick = [...st.items.values()].filter(({ s }) => !eq || s.equipo === eq).map(({ poly }) => poly.getBounds());
    if (pick.length) st.map.fitBounds(pick.reduce((a, b) => a.extend(b), L.latLngBounds(pick[0].getSouthWest(), pick[0].getNorthEast())), { padding: [12, 12] });
    st.eq = eq;
  }
  setTimeout(() => { st.map.invalidateSize(); st.showLabels(); }, 50);
  return st.map;
}
