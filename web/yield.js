// AeonCrop Web · Rendimiento: las estimaciones de rendimiento de la app (= rendimiento.py).
// La app las sincroniza por paquetes en «<módulo>/Estimaciones de rendimiento/Sincronización»
// (tablas yield_sets, yield_photos, yield_counts): aquí se leen, se ven sus resultados, fotos
// y el mapa por sector del predio, y se corrigen conteos y parámetros (vuelven a la app).
import * as C from "./core.js";

export const DRIVE_DIR = "Estimaciones de rendimiento", SYNC_DIR = "Sincronización";
const VEGETATIVE = new Set(["yema", "brote", "lateral", "upright", "estolon"]);   // = rendimiento.VEGETATIVE
export const FRUIT_SET = 80;
export const KINDS = { foto: "Foto", real: "Foto + conteo real" };
const $ = (id) => document.getElementById(id);

// ------------------------------------------------------------------ lógica pura (probada)
export const stagesOf = (classes) => classes.filter(([k]) => !VEGETATIVE.has(k));
const isFruit = (k) => k.startsWith("fruto");

// = rendimiento.estimate
export function estimate(totals, fruitG, fruitSet, coverage, plantsHa) {
  let fruits = 0, flowers = 0;
  for (const [k, n] of Object.entries(totals)) { if (isFruit(k)) fruits += n; else flowers += n; }
  const cuaja = (fruitSet == null ? FRUIT_SET : fruitSet) / 100;
  const sample = fruits + cuaja * flowers;
  const cov = (coverage || 100) / 100;
  const perPlant = cov > 0 ? sample / cov : 0;
  const kgPlant = fruitG ? perPlant * fruitG / 1000 : null;
  const kgHa = kgPlant != null && plantsHa ? kgPlant * plantsHa : null;
  return { fruits, flowers, sample, per_plant: perPlant, kg_plant: kgPlant, kg_ha: kgHa, t_ha: kgHa != null ? kgHa / 1000 : null };
}

// = rendimiento.real_result
export function realResult(s, photo) {
  if ((s.kind || "foto") !== "real" || !s.real_per_plant) return { real_kg_plant: null, real_t_ha: null, photo_error: null };
  let kg = s.real_kg_plant;
  if (!kg && s.fruit_g) kg = s.real_per_plant * s.fruit_g / 1000;
  const tHa = kg && s.plants_ha ? kg * s.plants_ha / 1000 : null;
  const err = photo.per_plant != null ? (photo.per_plant - s.real_per_plant) / s.real_per_plant * 100 : null;
  return { real_kg_plant: kg || null, real_t_ha: tHa, photo_error: err };
}
export const bestTHa = (s) => (s.real_t_ha != null ? s.real_t_ha : s.t_ha);

// Estimaciones con sus fotos, conteos y resultado (la más reciente primero) = YieldDB.sets.
export function buildSets(state, classes) {
  const keys = stagesOf(classes).map(([k]) => k);
  const photos = C.rows(state, "yield_photos");
  const counts = C.rows(state, "yield_counts");
  const byPhoto = new Map();
  for (const c of counts) {
    if (!byPhoto.has(c.photo_id)) byPhoto.set(c.photo_id, []);
    byPhoto.get(c.photo_id).push(c);
  }
  const out = [];
  for (const s of C.rows(state, "yield_sets")) {
    const mine = photos.filter((p) => p.set_id === s.uid).sort((a, b) => String(a.created_at).localeCompare(String(b.created_at)));
    const totals = Object.fromEntries(keys.map((k) => [k, 0]));
    let counted = 0;
    for (const p of mine) {
      p.counts = Object.fromEntries((byPhoto.get(p.uid) || []).map((c) => [c.stage, c]));
      if (Object.keys(p.counts).length) counted++;
      for (const c of Object.values(p.counts)) totals[c.stage] = (totals[c.stage] || 0) + (Number(c.n) || 0);
    }
    const res = estimate(totals, s.fruit_g, s.fruit_set, s.coverage, s.plants_ha);
    out.push({ ...s, ...res, ...realResult(s, res), totals, photoRows: mine, photos: mine.length, counted });
  }
  return out.sort((a, b) => String(b.taken_on).localeCompare(String(a.taken_on)) || String(b.created_at).localeCompare(String(a.created_at)));
}

function inside(ring, x, y) {             // = geo._inside
  let ins = false;
  const n = ring.length / 2;
  for (let i = 0, j = n - 1; i < n; j = i++) {
    const [xi, yi, xj, yj] = [ring[2 * i], ring[2 * i + 1], ring[2 * j], ring[2 * j + 1]];
    if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) ins = !ins;
  }
  return ins;
}
export function sectorAt(plan, lat, lon, nearM = 40) {      // = geo.sector_at
  if (!plan?.geo) return null;
  const g = plan.geo;
  const x = lon * g.kx - g.x0, y = lat * g.ky - g.y0;
  let best = null, bestD = null;
  for (const s of plan.sectors || []) for (const ring of s.parts || []) {
    if (inside(ring, x, y)) return s;
    for (let i = 0; i < ring.length; i += 2) {
      const d = Math.hypot(ring[i] - x, ring[i + 1] - y);
      if (bestD == null || d < bestD) { best = s; bestD = d; }
    }
  }
  return bestD != null && bestD * (111320 / g.ky) <= nearM ? best : null;
}
const SECTOR_RE = /equipo(?:\s+de\s+riego)?\s*(\d+)\D+?sector\s*(\d+)/i;
export function planSector(s, plan) {      // = rendimiento.plan_sector
  if (!plan) return null;
  if (s.latitude != null && s.longitude != null) {
    const hit = sectorAt(plan, s.latitude, s.longitude);
    if (hit) return hit;
  }
  const m = SECTOR_RE.exec(s.sector || "");
  if (m) return plan.sectors.find((x) => x.id === `E${Number(m[1])}-S${Number(m[2])}`) || null;
  return null;
}
export function mapLayers(sets, plan) {    // = rendimiento.map_layers (sin los puntos)
  const acc = {};
  for (const s of sets) {
    const sec = planSector(s, plan), t = bestTHa(s);
    if (!sec || t == null) continue;
    const d = (acc[sec.id] ||= { sum: 0, n: 0, real: 0, sets: [] });
    d.sum += t; d.n++; d.real += s.kind === "real" ? 1 : 0; d.sets.push(s);
  }
  const sectors = Object.fromEntries(Object.entries(acc).map(([k, v]) => [k, { t_ha: v.sum / v.n, n: v.n, real: v.real, sets: v.sets }]));
  const vals = Object.values(sectors).map((v) => v.t_ha);
  return { sectors, lo: vals.length ? Math.min(...vals) : null, hi: vals.length ? Math.max(...vals) : null };
}
const RAMP = [[0, [198, 40, 40]], [0.5, [244, 180, 0]], [1, [46, 125, 50]]];   // = rendimiento.YIELD_RAMP
export function yieldColor(t, lo, hi) {
  let k = hi == null || lo == null || hi - lo < 1e-9 ? 0.5 : (t - lo) / (hi - lo);
  k = Math.max(0, Math.min(1, k));
  for (let i = 0; i < RAMP.length - 1; i++) {
    const [t0, c0] = RAMP[i], [t1, c1] = RAMP[i + 1];
    if (k <= t1) {
      const f = (k - t0) / (t1 - t0);
      return `rgb(${c0.map((a, j) => Math.round(a + (c1[j] - a) * f)).join(",")})`;
    }
  }
  return `rgb(${RAMP[RAMP.length - 1][1].join(",")})`;
}

// Planilla como la de la app (estimaciones.csv: «;» y coma decimal).
export function toCsv(sets, classes) {
  const keys = stagesOf(classes);
  const num = (v, d = 1) => (v == null || v === "" ? "" : Number(v).toFixed(d).replace(".", ","));
  const cell = (v) => (/[;"\n]/.test(String(v ?? "")) ? `"${String(v).replace(/"/g, '""')}"` : String(v ?? ""));
  const head = ["Fecha", "Lugar", "Código", "Sector / variedad", "Fotos", "Fotos contadas", ...keys.map(([, n]) => n),
    "Cuaja (%)", "Parte fotografiada (%)", "Peso fruto (g)", "Plantas/ha", "Frutos por planta", "kg por planta", "kg/ha", "Tipo",
    "Frutos por planta (conteo real)", "kg por planta (real)", "kg/ha (real)", "Diferencia foto vs real (%)", "Latitud", "Longitud", "Notas"];
  const lines = [head.map(cell).join(";")];
  for (const s of sets) {
    lines.push([s.taken_on, s.place, s.place_code, s.sector, s.photos, s.counted, ...keys.map(([k]) => s.totals[k] || 0),
      num(s.fruit_set, 0), num(s.coverage, 0), num(s.fruit_g), num(s.plants_ha, 0), num(s.per_plant), num(s.kg_plant, 2),
      num(s.kg_ha, 0), KINDS[s.kind || "foto"] || "Foto", num(s.real_per_plant), num(s.real_kg_plant, 2),
      num(s.real_t_ha != null ? s.real_t_ha * 1000 : null, 0), num(s.photo_error, 0), num(s.latitude, 6), num(s.longitude, 6),
      s.notes || ""].map(cell).join(";"));
  }
  return "﻿" + lines.join("\r\n") + "\r\n";
}

// Cambios de una edición en la web (filas completas, como las manda la app).
export function editChanges(set, fields, counts, ts = C.nowTs()) {
  const changes = [];
  const data = { ...set };
  for (const k of ["uid", "ts", "photoRows", "photos", "counted", "totals", "fruits", "flowers", "sample", "per_plant", "kg_plant",
    "kg_ha", "t_ha", "real_kg_plant", "real_t_ha", "photo_error", "_sector"]) delete data[k];
  let changed = false;
  for (const [k, v] of Object.entries(fields)) if ((data[k] ?? null) !== (v ?? null)) { data[k] = v; changed = true; }
  if (changed) changes.push({ entity: "yield_sets", uid: set.uid, ts, deleted: 0, data });
  for (const p of set.photoRows) {
    for (const [stage, n] of Object.entries(counts[p.uid] || {})) {
      const cur = p.counts?.[stage];
      if (cur ? Number(cur.n) === n : n === 0) continue;
      const row = { photo_id: p.uid, stage, n, source: "manual" };
      changes.push({ entity: "yield_counts", uid: cur ? cur.uid : C.newUid(), ts, deleted: 0, data: row });
    }
  }
  return changes;
}

// ------------------------------------------------------------------ Drive y pantalla
let X = null;                      // funciones de app.js
let state = C.emptyState();
let syncDir = null;
let all = [];
let plans = new Map();             // código del predio -> plano (o null)
let selPlace = "", selSector = null;
let loadedCrop = null;

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmt = (v, d = 1) => (v == null ? "—" : Number(v).toLocaleString("es-CL", { minimumFractionDigits: d, maximumFractionDigits: d }));
const dmy = (d) => String(d || "").slice(0, 10).split("-").reverse().join("-");

export function init(ctx) {
  X = ctx;
  $("yreload").onclick = () => load(true);
  $("ycsv").onclick = downloadCsv;
  $("yplace").onchange = (e) => { selPlace = e.target.value; selSector = null; render(); };
  $("ydclose").onclick = () => $("ydlg").close();
  $("ydsave").onclick = saveDetail;
}

async function folderOf(create) {
  if (syncDir) return syncDir;
  const root = await X.moduleRoot(X.crop(), create);
  const top = root && await X.folder(DRIVE_DIR, root, create);
  syncDir = top && await X.folder(SYNC_DIR, top, create);
  return syncDir;
}

export async function load(fresh = false) {
  if (loadedCrop !== X.crop()) { state = C.emptyState(); syncDir = null; loadedCrop = X.crop(); }
  const msg = $("ymsg");
  msg.textContent = "Leyendo las estimaciones…";
  const idxKey = "rend/__index";
  for (const n of (await X.cacheGet(idxKey)) || []) {
    const b = await X.cacheGet(`rend/${n}`);
    if (b) C.applyBundle(state, n, b);
  }
  render();
  try {
    const dir = await folderOf(false);
    if (dir) {
      const files = (await X.list(`'${dir}' in parents and trashed=false`, "files(id,name)"))
        .filter((f) => f.name.endsWith(".json")).sort((a, b) => a.name.localeCompare(b.name));
      const todo = files.filter((f) => fresh || !state.seen.has(f.name));
      const got = new Array(todo.length);
      let done = 0;
      await X.pool(todo, 8, async (f, k) => {
        let b = fresh ? null : await X.cacheGet(`rend/${f.name}`);
        if (!b) { b = await (await X.download(f.id)).json(); X.cachePut(`rend/${f.name}`, b); }
        got[k] = b;
        msg.textContent = `Leyendo las estimaciones… ${++done}/${todo.length}`;
      });
      todo.forEach((f, k) => C.applyBundle(state, f.name, got[k]));
      X.cachePut(idxKey, files.map((f) => f.name));
    }
    msg.textContent = dir ? "" : "Aún no hay estimaciones en Drive: en la app, abra Rendimiento y pulse «Sincronizar» (la app debe estar actualizada).";
  } catch (e) {
    msg.textContent = `Sin conexión con Drive: se muestra lo guardado (${e.message}).`;
  }
  render();
}

async function planOf(code) {
  if (!code) return null;
  if (!plans.has(code)) plans.set(code, await X.mapFor(code).catch(() => null));
  return plans.get(code);
}

function render() {
  const classes = X.classes();
  all = buildSets(state, classes);
  const places = [...new Set(all.map((s) => s.place || "Sin lugar"))].sort((a, b) => a.localeCompare(b, "es"));
  const sel = $("yplace");
  sel.innerHTML = `<option value="">Todos los lugares (${all.length})</option>` +
    places.map((p) => `<option value="${esc(p)}">${esc(p)} (${all.filter((s) => (s.place || "Sin lugar") === p).length})</option>`).join("");
  if (selPlace && !places.includes(selPlace)) selPlace = "";
  sel.value = selPlace;
  const shown = all.filter((s) => !selPlace || (s.place || "Sin lugar") === selPlace);
  const list = $("ylist");
  if (!shown.length) {
    list.innerHTML = `<p class="muted small">${all.length ? "Sin estimaciones en este lugar." : "Sin estimaciones todavía."}</p>`;
  } else {
    list.innerHTML = `<table class="ytable"><thead><tr><th>Fecha</th><th>Lugar · sector</th><th>Fotos</th>
      <th>Frutos/planta</th><th>kg/planta</th><th>t/ha</th></tr></thead><tbody>${shown.map((s, i) => `
      <tr data-i="${i}" class="${selSector && s._sector === selSector ? "hl" : ""}"><td>${dmy(s.taken_on).slice(0, 5)}<span class="yr">${dmy(s.taken_on).slice(5)}</span></td>
      <td><b>${esc(s.place || "Sin lugar")}</b>${s.sector ? ` · ${esc(s.sector)}` : ""}${s.kind === "real" ? ` <span class="badge">conteo real</span>` : ""}</td>
      <td>${s.counted}/${s.photos}</td><td>${fmt(s.per_plant)}</td><td>${fmt(s.real_kg_plant ?? s.kg_plant, 2)}</td>
      <td><b>${fmt(bestTHa(s), 2)}</b></td></tr>`).join("")}</tbody></table>`;
    list.querySelectorAll("tr[data-i]").forEach((tr) => (tr.onclick = () => openDetail(shown[Number(tr.dataset.i)])));
  }
  renderMap(shown).catch((e) => console.error(e));
}

async function renderMap(shown) {
  const card = $("ymapcard");
  const codes = [...new Set(shown.filter((s) => s.place_code).map((s) => s.place_code))];
  let code = null, plan = null;
  for (const c of codes) { const p = await planOf(c); if (p) { code = c; plan = p; break; } }
  card.hidden = !plan;
  if (!plan) return;
  const sets = shown.filter((s) => s.place_code === code);
  const lay = mapLayers(sets, plan);
  for (const s of sets) s._sector = planSector(s, plan)?.id || null;
  $("ymaptitle").textContent = `${sets[0]?.place || code} · t/ha por sector`;
  $("ylegend").innerHTML = lay.lo == null ? "Sin estimaciones ubicadas en un sector." : lay.hi - lay.lo < 0.005 ?
    `<span style="background:${yieldColor(lay.lo, lay.lo, lay.hi)}"></span>${fmt(lay.lo, 2)} t/ha` :
    `<span style="background:${yieldColor(lay.lo, lay.lo, lay.hi)}"></span>${fmt(lay.lo, 2)} t/ha
     <span style="background:${yieldColor((lay.lo + lay.hi) / 2, lay.lo, lay.hi)}"></span>
     <span style="background:${yieldColor(lay.hi, lay.lo, lay.hi)}"></span>${fmt(lay.hi, 2)} t/ha`;
  const color = (s) => (lay.sectors[s.id] ? yieldColor(lay.sectors[s.id].t_ha, lay.lo, lay.hi) : "#9E9E9E");
  const info = () => {
    const sec = plan.sectors.find((s) => s.id === selSector);
    const d = sec && lay.sectors[sec.id];
    $("ymapinfo").innerHTML = !sec ? `<p class="muted small">Toque un sector para ver sus estimaciones.</p>` :
      `<b>${esc(sec.nombre)}</b> <span class="muted small">· ${d ? `${fmt(d.t_ha, 2)} t/ha promedio de ${d.n} estimación(es)${d.real ? `, ${d.real} con conteo real` : ""}` : "sin estimaciones"}</span>`;
  };
  const el = $("ymap");
  const onSelect = (id) => { selSector = id; render(); };
  if (plan.geo) {
    try {
      el.classList.add("leaf");
      await X.sectorMap(el, plan, { color, hasData: (s) => !!lay.sectors[s.id], selected: selSector, eq: 0, onSelect });
      info();
      return;
    } catch { el._sector = null; el._map?.remove(); el._map = null; }
  }
  // Sin conexión al mapa (o plano sin coordenadas): el plano dibujado.
  let [x0, y0, x1, y1] = [Infinity, Infinity, -Infinity, -Infinity];
  for (const s of plan.sectors) for (const p of s.parts) for (let i = 0; i < p.length; i += 2) {
    x0 = Math.min(x0, p[i]); x1 = Math.max(x1, p[i]); y0 = Math.min(y0, p[i + 1]); y1 = Math.max(y1, p[i + 1]);
  }
  const H = plan.h;
  let svg = `<svg viewBox="${x0} ${H - y1} ${x1 - x0} ${y1 - y0}" xmlns="http://www.w3.org/2000/svg">`;
  for (const s of plan.sectors) for (const p of s.parts) {
    const d = p.reduce((a, v, i) => a + (i % 2 ? `,${(H - v).toFixed(1)}` : `${i ? "L" : "M"}${v.toFixed(1)}`), "") + "Z";
    svg += `<path d="${d}" fill="${color(s)}" data-id="${s.id}" class="${s.id === selSector ? "sel" : ""}"><title>${esc(s.nombre)}</title></path>`;
  }
  el.innerHTML = svg + "</svg>";
  el.classList.remove("leaf");
  el.querySelectorAll("path").forEach((p) => (p.onclick = () => onSelect(p.dataset.id)));
  info();
}

let current = null;
function numIn(id, v, step = "any") {
  return `<input id="${id}" type="number" inputmode="decimal" step="${step}" min="0" value="${v ?? ""}">`;
}
async function openDetail(s) {
  current = s;
  const classes = stagesOf(X.classes());
  $("ydtitle").textContent = `${s.place || "Sin lugar"}${s.sector ? ` · ${s.sector}` : ""}`;
  $("ydsub").textContent = `${dmy(s.taken_on)} · ${KINDS[s.kind || "foto"] || "Foto"} · ${s.counted} de ${s.photos} fotos contadas`;
  $("ydparams").innerHTML = `
    <label>Sector / variedad<input id="yf_sector" value="${esc(s.sector)}"></label>
    <label>Peso medio del fruto (g)${numIn("yf_fruit_g", s.fruit_g)}</label>
    <label>Cuaja de botones y flores (%)${numIn("yf_fruit_set", s.fruit_set)}</label>
    <label>Parte de la planta fotografiada (%)${numIn("yf_coverage", s.coverage)}</label>
    <label>Plantas por hectárea${numIn("yf_plants_ha", s.plants_ha, "1")}</label>
    ${s.kind === "real" ? `<label>Frutos por planta (conteo real)${numIn("yf_real_per_plant", s.real_per_plant)}</label>
    <label>kg por planta pesados${numIn("yf_real_kg_plant", s.real_kg_plant)}</label>` : ""}
    <label class="wide">Notas<textarea id="yf_notes" rows="2">${esc(s.notes)}</textarea></label>`;
  const photos = $("ydphotos");
  photos.innerHTML = s.photoRows.length ? "" : `<p class="muted small">Esta estimación no tiene fotos.</p>`;
  for (const p of s.photoRows) {
    const card = document.createElement("div");
    card.className = "yphoto";
    const src = Object.values(p.counts).some((c) => c.source === "ia") ? `<span class="badge">cajas de IA+</span>` : "";
    card.innerHTML = `<div class="ythumb"></div><div class="ycounts">${src}${classes.map(([k, n, c]) =>
      `<label><i style="background:${c}"></i>${esc(n)}<input type="number" min="0" step="1" data-p="${p.uid}" data-k="${k}" value="${p.counts[k] ? Number(p.counts[k].n) : ""}" placeholder="0"></label>`).join("")}</div>`;
    photos.appendChild(card);
    const th = card.querySelector(".ythumb");
    X.photoUrl(p.path).then((u) => {
      if (u) { th.style.backgroundImage = `url(${u})`; th.onclick = () => window.open(u, "_blank"); } else th.textContent = "Foto aún no está en Drive";
    }).catch(() => { th.textContent = "Sin foto"; });
  }
  photos.oninput = () => liveResult();
  $("ydparams").oninput = () => liveResult();
  liveResult();
  $("ydmsg").textContent = "";
  $("ydlg").showModal();
}

function readForm() {
  const num = (id) => { const el = $(id); if (!el || el.value === "") return null; return Number(el.value.replace(",", ".")); };
  const fields = { sector: $("yf_sector").value.trim(), fruit_g: num("yf_fruit_g"), fruit_set: num("yf_fruit_set"),
    coverage: num("yf_coverage"), plants_ha: num("yf_plants_ha"), notes: $("yf_notes").value };
  if ($("yf_real_per_plant")) { fields.real_per_plant = num("yf_real_per_plant"); fields.real_kg_plant = num("yf_real_kg_plant"); }
  const counts = {};
  for (const el of $("ydphotos").querySelectorAll("input[data-p]")) {
    if (el.value === "" && !current.photoRows.find((p) => p.uid === el.dataset.p)?.counts[el.dataset.k]) continue;
    (counts[el.dataset.p] ||= {})[el.dataset.k] = Math.max(0, Math.round(Number(el.value) || 0));
  }
  return { fields, counts };
}

function liveResult() {
  const { fields, counts } = readForm();
  const totals = { ...current.totals };
  for (const p of current.photoRows) for (const [k, n] of Object.entries(counts[p.uid] || {})) {
    totals[k] += n - (p.counts[k] ? Number(p.counts[k].n) : 0);
  }
  const s = { ...current, ...fields };
  const r = estimate(totals, s.fruit_g, s.fruit_set, s.coverage, s.plants_ha);
  const real = realResult(s, r);
  $("ydresult").innerHTML = `
    <div><b>${fmt(r.fruits, 0)}</b><span>frutos cuajados</span></div>
    <div><b>${fmt(r.flowers, 0)}</b><span>botones y flores</span></div>
    <div><b>${fmt(r.per_plant)}</b><span>frutos por planta</span></div>
    <div><b>${fmt(r.kg_plant, 2)}</b><span>kg por planta</span></div>
    <div class="big"><b>${fmt(r.t_ha, 2)}</b><span>t/ha (foto)</span></div>
    ${real.real_t_ha != null ? `<div class="big"><b>${fmt(real.real_t_ha, 2)}</b><span>t/ha (conteo real${real.photo_error != null ? ` · foto ${real.photo_error > 0 ? "+" : ""}${fmt(real.photo_error, 0)} %` : ""})</span></div>` : ""}`;
}

async function saveDetail() {
  const { fields, counts } = readForm();
  const changes = editChanges(current, fields, counts);
  if (!changes.length) { $("ydmsg").textContent = "No hay cambios que guardar."; return; }
  $("ydsave").disabled = true;
  $("ydmsg").textContent = "Guardando en Drive…";
  try {
    const name = `${C.stamp()}-${X.device()}.json`;
    const bundle = C.bundle(X.device(), "rendimiento", changes, {});
    const dir = await folderOf(true);
    await X.upload(dir, name, new Blob([JSON.stringify(bundle)], { type: "application/json" }), "application/json");
    C.applyBundle(state, name, bundle);
    X.cachePut(`rend/${name}`, bundle);
    X.cachePut("rend/__index", [...((await X.cacheGet("rend/__index")) || []), name]);
    $("ydlg").close();
    render();
    $("ymsg").textContent = "Cambios guardados: llegan a la app en la próxima sincronización.";
  } catch (e) {
    $("ydmsg").textContent = `No se pudo guardar: ${e.message}`;
  } finally { $("ydsave").disabled = false; }
}

function downloadCsv() {
  const shown = all.filter((s) => !selPlace || (s.place || "Sin lugar") === selPlace);
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([toCsv(shown, X.classes())], { type: "text/csv;charset=utf-8" }));
  a.download = "estimaciones.csv";
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 60000);
}
