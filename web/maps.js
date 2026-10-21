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
export async function photoHeat(el, points, popup) {
  const L = await load();
  if (el._map) { el._map.remove(); el._map = null; }
  const map = baseMap(L, el, DEFAULT_CENTER, 12);
  el._map = map;
  if (points.length) {
    const top = Math.max(...points.map((p) => p.weight));
    L.heatLayer(points.map((p) => [p.lat, p.lon, p.weight / top]), { radius: 30, blur: 22, maxZoom: 17, gradient: RAMP, minOpacity: .25 }).addTo(map);
    for (const p of points) {
      L.circleMarker([p.lat, p.lon], { radius: 5, color: "#fff", weight: 1.5, fillColor: "#A8184A", fillOpacity: 1 })
        .bindPopup(() => popup(p)).addTo(map);
    }
    map.fitBounds(L.latLngBounds(points.map((p) => [p.lat, p.lon])).pad(.25), { maxZoom: 18 });
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
