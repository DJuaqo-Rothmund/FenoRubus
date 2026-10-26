// PhenoRubus Web · lógica pura (sin Drive ni pantalla): semanas y temporadas, nombres de
// foto y el formato de los paquetes de sincronización (el mismo de sync.py en la app).
// Se prueba con Node junto a las pruebas de Python (tests/test_web_core.mjs).

export const MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
  "agosto", "septiembre", "octubre", "noviembre", "diciembre"];
export const MES3 = MESES.map((m) => m.slice(0, 3));

// ------------------------------------------------------------------ fechas
export function iso(d) {               // Date (UTC) -> "aaaa-mm-dd"
  return d.toISOString().slice(0, 10);
}
export function parseDate(s) {          // "aaaa-mm-dd" -> Date UTC
  const [y, m, d] = s.slice(0, 10).split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}
export function addDays(d, n) {
  return new Date(d.getTime() + n * 86400000);
}
export function mondayOf(d) {
  const wd = (d.getUTCDay() + 6) % 7;   // lunes = 0
  return addDays(d, -wd);
}
export function todayUTC() {
  const n = new Date();
  return new Date(Date.UTC(n.getFullYear(), n.getMonth(), n.getDate()));
}

// Temporada abril-marzo, decidida por el lunes de la semana (= phenology.season_of).
export function seasonFirstMonday(season) {
  return mondayOf(new Date(Date.UTC(season, 3, 1)));
}
export function seasonOf(d) {
  const monday = mondayOf(d);
  const y = monday.getUTCFullYear();
  return monday >= seasonFirstMonday(y) ? y : y - 1;
}
export function seasonTitle(s) {
  return `Temporada ${s}-${s + 1}`;
}

// Semana ISO-8601 (= phenology.iso_week): [semana, año].
export function isoWeek(d) {
  const t = addDays(d, 3 - ((d.getUTCDay() + 6) % 7));
  const y = t.getUTCFullYear();
  const first = new Date(Date.UTC(y, 0, 4));
  const w = 1 + Math.round(((t - first) / 86400000 - 3 + ((first.getUTCDay() + 6) % 7)) / 7);
  return [w, y];
}
export function weekTitle(start) {      // «Semana 42, año 2026»
  const [w, y] = isoWeek(parseDate(start));
  return `Semana ${w}, año ${y}`;
}
export function weekLabel(start) {      // «Semana del 12 de octubre»
  const d = parseDate(start);
  return `Semana del ${d.getUTCDate()} de ${MESES[d.getUTCMonth()]}`;
}
export function weekRange(start) {      // «12 oct – 18 oct 2026»
  const a = parseDate(start), b = addDays(a, 6);
  return `${a.getUTCDate()} ${MES3[a.getUTCMonth()]} – ${b.getUTCDate()} ${MES3[b.getUTCMonth()]} ${b.getUTCFullYear()}`;
}
// Carpeta de la semana en Drive (= DriveBackup.week_folder): «Año 2026/Semana 42 · 12-10-2026».
export function weekFolder(start) {
  const d = parseDate(start);
  const [w, y] = isoWeek(d);
  const dd = String(d.getUTCDate()).padStart(2, "0"), mm = String(d.getUTCMonth() + 1).padStart(2, "0");
  return `Año ${y}/Semana ${String(w).padStart(2, "0")} · ${dd}-${mm}-${d.getUTCFullYear()}`;
}

// ------------------------------------------------------------------ BBCH
export function codeStr(code) {         // 7 -> «07», 891 -> «89-1»
  if (code === null || code === undefined) return "—";
  code = Number(code);
  return code >= 100 ? `${Math.floor(code / 10)}-${code % 10}` : String(code).padStart(2, "0");
}
export function macroOf(code) {
  if (code === null || code === undefined) return null;
  code = Number(code);
  return code >= 100 ? Math.floor(code / 100) : Math.floor(code / 10);
}

// ------------------------------------------------------------------ variedades
export function isUnit(v) {
  return !!((v.cultivar || "").trim() && (v.sector || v.irrigation) && !v.treatment);
}
export function unitMain(v) {
  if (!isUnit(v)) return v.name || "";
  return [v.cultivar.trim(), v.plant_year].filter(Boolean).join(" · ");
}
export function unitPlace(v) {
  if (!isUnit(v)) return "";
  const parts = [];
  if (v.irrigation) parts.push(`Equipo de riego ${v.irrigation}`);
  if (v.sector) parts.push((parts.length ? "sector" : "Sector") + ` ${v.sector}`);
  return parts.join(" · ");
}

function clean(t) {
  return (t || "").normalize("NFKD").replace(/[̀-ͯ]/g, "").replace(/[^A-Za-z0-9]/g, "");
}
export function varietyTag(name, code) {   // = phenology.variety_tag
  let tag = clean(code);
  if (!tag) {
    const digits = (name || "").match(/\d+/g) || [];
    const letters = clean(name);
    tag = digits.length && letters ? letters.slice(0, 1) + digits[0] : letters.slice(0, 3);
  }
  if (/^[A-Za-z]+$/.test(tag) && tag.length >= 3) tag = tag[0].toUpperCase() + tag.slice(1).toLowerCase();
  return tag || "Var";
}
export function locationTag(v) {
  return (v.sector ? `S${v.sector}` : "") + (v.irrigation ? `ER${v.irrigation}` : "");
}
const KIND_LETTER = { canopy: "G", detail: "D", attachment: "A" };
export function photoBasename(v, weekStart, kind, seq = 1, trial = "") {   // = phenology.photo_basename
  let date = weekStart.slice(0, 10).replaceAll("-", "");
  if (trial) date = `${date}-${trial}`;
  const base = `${date}-${varietyTag(v.cultivar || v.name || "", v.code)}${locationTag(v)}${KIND_LETTER[kind] || "X"}`;
  return seq <= 1 ? base : `${base}-${seq}`;
}

// ------------------------------------------------------------------ paquetes
// Estado de un ensayo: {tabla: Map(uid -> {ts, deleted, data})}; gana el cambio más reciente.
export function emptyState() {
  return { tables: {}, settings: {}, seen: new Set() };
}
export function applyBundle(state, name, bundle) {
  if (state.seen.has(name)) return 0;
  state.seen.add(name);
  let n = 0;
  for (const ch of bundle.changes || []) {
    const t = (state.tables[ch.entity] ||= new Map());
    const cur = t.get(ch.uid);
    if (cur && cur.ts > ch.ts) continue;
    t.set(ch.uid, { ts: ch.ts, deleted: !!ch.deleted, data: ch.data || (cur && cur.data) || {} });
    n++;
  }
  Object.assign(state.settings, bundle.settings || {});
  return n;
}
export function rows(state, entity) {
  const out = [];
  for (const [uid, r] of state.tables[entity] || []) if (!r.deleted) out.push({ uid, ...r.data });
  return out;
}

export function nowTs() {                 // mismo formato que SQLite: sin la «Z»
  return new Date().toISOString().replace("Z", "");
}
export function newUid() {
  const a = new Uint8Array(16);
  crypto.getRandomValues(a);
  return Array.from(a, (b) => b.toString(16).padStart(2, "0")).join("");
}

export function varieties(state) {
  return rows(state, "varieties").filter((v) => v.active !== 0)
    .sort((a, b) => (a.sort_order || 0) - (b.sort_order || 0) || (a.name || "").localeCompare(b.name || "", "es"));
}
export function observationFor(state, varietyUid, weekStart) {
  return rows(state, "observations").find((o) => o.variety_id === varietyUid && o.week_id === weekStart) || null;
}
export function photosFor(state, obsUid) {
  return rows(state, "photos").filter((p) => p.observation_id === obsUid)
    .sort((a, b) => (b.is_primary || 0) - (a.is_primary || 0) || (a.captured_at || "").localeCompare(b.captured_at || ""));
}
export function weekStarts(state) {
  return new Set(rows(state, "sampling_weeks").map((w) => w.start_date || w.uid));
}

// Cambios para guardar un registro (estado BBCH / notas) de una variedad en una semana.
export function observationChanges(state, varietyUid, weekStart, fields, bbchLabel) {
  const ts = nowTs();
  const changes = [];
  if (!weekStarts(state).has(weekStart)) {
    const season = seasonOf(parseDate(weekStart));
    changes.push({ entity: "sampling_weeks", uid: weekStart, ts, deleted: 0,
      data: { season, week_number: 0, start_date: weekStart, label: weekLabel(weekStart), skipped: 0 } });
  }
  const cur = observationFor(state, varietyUid, weekStart);
  const uid = cur ? cur.uid : newUid();
  const base = cur ? { ...cur } : { variety_id: varietyUid, week_id: weekStart, bbch_code: null, bbch_label: "",
    ai_code: null, ai_confidence: null, ai_detail: "", ai_accepted: null, notes: "", observed_at: null,
    latitude: null, longitude: null, gps_accuracy: null, gps_source: null, created_at: ts };
  delete base.uid;
  const data = { ...base, ...fields, updated_at: ts };
  if ("bbch_code" in fields) {
    data.bbch_label = fields.bbch_code === null ? "" : bbchLabel || "";
    data.observed_at = ts;
  }
  changes.push({ entity: "observations", uid, ts, deleted: 0, data });
  return { uid, changes };
}

export function photoChange(state, obsUid, kind, relPath) {
  const has = photosFor(state, obsUid).some((p) => p.kind === kind && p.is_primary);
  const ts = nowTs();
  return { entity: "photos", uid: newUid(), ts, deleted: 0,
    data: { observation_id: obsUid, kind, path: relPath, source: "web", captured_at: ts, is_primary: has ? 0 : 1 } };
}

// Foto principal de su tipo en el registro (= Database.set_primary).
export function photoPrimaryChanges(state, photoUid) {
  const all = rows(state, "photos");
  const p = all.find((x) => x.uid === photoUid);
  if (!p) return [];
  const ts = nowTs();
  return all.filter((x) => x.observation_id === p.observation_id && x.kind === p.kind
    && (x.uid === photoUid ? !x.is_primary : x.is_primary))
    .map(({ uid, ...data }) => ({ entity: "photos", uid, ts, deleted: 0, data: { ...data, is_primary: uid === photoUid ? 1 : 0 } }));
}

// Coordenadas GPS guardadas por la cámara en un JPEG (EXIF), como geo.exif_gps. null si no hay.
export function exifGps(buf) {
  const v = new DataView(buf instanceof ArrayBuffer ? buf : buf.buffer);
  if (v.byteLength < 4 || v.getUint16(0) !== 0xffd8) return null;
  let off = 2;
  while (off + 4 < v.byteLength) {
    const marker = v.getUint16(off), len = v.getUint16(off + 2);
    if (marker === 0xffe1 && v.getUint32(off + 4) === 0x45786966) return tiffGps(v, off + 10);
    if ((marker & 0xff00) !== 0xff00 || marker === 0xffda) return null;
    off += 2 + len;
  }
  return null;
}
function tiffGps(v, t) {
  try {
    const le = v.getUint16(t) === 0x4949;
    const u16 = (o) => v.getUint16(t + o, le), u32 = (o) => v.getUint32(t + o, le);
    const entries = (ifd) => { const n = u16(ifd); return Array.from({ length: n }, (_, i) => ifd + 2 + i * 12); };
    const gpsPtr = entries(u32(4)).find((e) => u16(e) === 0x8825);
    if (gpsPtr === undefined) return null;
    const tags = {};
    for (const e of entries(u32(gpsPtr + 8))) tags[u16(e)] = e;
    const ref = (tag) => tags[tag] === undefined ? "" : String.fromCharCode(v.getUint8(t + tags[tag] + 8));
    const deg = (tag) => {
      if (tags[tag] === undefined) return null;
      const o = u32(tags[tag] + 8);
      const r = (i) => { const d = u32(o + i * 8 + 4); return d ? u32(o + i * 8) / d : 0; };
      return r(0) + r(1) / 60 + r(2) / 3600;
    };
    let lat = deg(2), lon = deg(4);
    if (lat === null || lon === null) return null;
    if (ref(1).toUpperCase() === "S") lat = -lat;
    if (ref(3).toUpperCase() === "W") lon = -lon;
    if (Math.abs(lat) < 1e-9 && Math.abs(lon) < 1e-9) return null;
    if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return null;
    return [lat, lon];
  } catch { return null; }
}

// Borra fotos (= Database.delete_photo): si se va la principal de un tipo, pasa a principal
// la más reciente que quede de ese tipo. El archivo en Drive no se toca (como en la app).
export function photoDeleteChanges(state, uids) {
  const gone = new Set(uids);
  const all = rows(state, "photos");
  const ts = nowTs();
  const changes = [...gone].map((uid) => ({ entity: "photos", uid, ts, deleted: 1 }));
  const groups = new Set(all.filter((p) => gone.has(p.uid) && p.is_primary).map((p) => `${p.observation_id}|${p.kind}`));
  for (const g of groups) {
    const left = all.filter((p) => `${p.observation_id}|${p.kind}` === g && !gone.has(p.uid));
    if (!left.length || left.some((p) => p.is_primary)) continue;
    const next = left.sort((a, b) => (b.captured_at || "").localeCompare(a.captured_at || ""))[0];
    const { uid, ...data } = next;
    changes.push({ entity: "photos", uid, ts, deleted: 0, data: { ...data, is_primary: 1 } });
  }
  return changes;
}

export function bundle(device, workspace, changes, settings = {}) {
  return { format: 1, device, workspace, created: nowTs(),
    upto: changes.length ? changes[changes.length - 1].ts : null, changes, settings };
}
export function stamp() {                 // nombre del paquete (= sync_drive._stamp)
  return new Date().toISOString().replace(/[-:]/g, "").replace("Z", "").replace(".", "").slice(0, 18);
}

// ------------------------------------------------------------------ análisis (= reporter.py)
export function bbchValue(code) {         // 891 -> 89,1
  if (code === null || code === undefined) return null;
  code = Number(code);
  return code < 100 ? code : Math.floor(code / 10) + (code % 10) / 10;
}
const SEQ_LIGHT = [0xEE, 0xF0, 0xE2], SEQ_DARK = [0x2B, 0x36, 0x14];
export function seqColor(code) {          // [fondo, texto] (= reporter.seq_color)
  if (code === null || code === undefined) return ["transparent", "inherit"];
  const t = Math.max(0, Math.min(1, bbchValue(code) / 99)) ** 0.85;
  const rgb = SEQ_LIGHT.map((a, i) => Math.round(a + (SEQ_DARK[i] - a) * t));
  const lum = (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) / 255;
  return ["#" + rgb.map((x) => x.toString(16).padStart(2, "0")).join(""), lum < 0.5 ? "#ffffff" : "#1f2413"];
}
export const MILESTONES = [[51, "Botón floral"], [61, "Inicio floración"], [65, "50 % de flores"],
  [71, "Cuajado"], [81, "Inicio coloración"], [891, "Inicio cosecha"]];

// Semanas con registros de una temporada (de la primera a la última con datos, sin las
// marcadas «no muestreada»), como la matriz y los informes de la app.
export function hasData(state, obs) {
  return obs.bbch_code !== null && obs.bbch_code !== undefined || !!(obs.notes || "").trim()
    || rows(state, "photos").some((p) => p.observation_id === obs.uid);
}
export function seasonWeeks(state, season) {
  const skipped = new Set(rows(state, "sampling_weeks").filter((w) => w.skipped).map((w) => w.start_date || w.uid));
  const withData = new Set(rows(state, "observations").filter((o) => hasData(state, o)).map((o) => o.week_id));
  // Primera semana fija en Ajustes (= report_first_week): desde ahí, sin borrar las anteriores.
  const fixed = setting(state, `first_week:${season}`);
  const starts = [...withData].filter((s) => seasonOf(parseDate(s)) === season && !skipped.has(s)
    && (!fixed || s >= fixed)).sort();
  if (!starts.length) return [];
  const out = [];
  for (let d = parseDate(fixed && fixed < starts[0] ? fixed : starts[0]); iso(d) <= starts[starts.length - 1]; d = addDays(d, 7)) {
    if (!skipped.has(iso(d))) out.push(iso(d));
  }
  return out;
}
export function seasons(state) {
  const s = new Set(rows(state, "observations").filter((o) => hasData(state, o)).map((o) => seasonOf(parseDate(o.week_id))));
  s.add(seasonOf(todayUTC()));
  return [...s].sort((a, b) => b - a);
}

// Matriz: filas por variedad con su código BBCH en cada semana + precocidad e hitos.
export function matrix(state, weeks) {
  const vs = varieties(state);
  const obsBy = new Map(rows(state, "observations").map((o) => [`${o.variety_id}|${o.week_id}`, o]));
  const heat = vs.map((v) => ({ variety: v,
    cells: weeks.map((w) => { const o = obsBy.get(`${v.uid}|${w}`); return { week: w, code: o ? o.bbch_code ?? null : null, obs: o || null }; }) }));
  const means = weeks.map((_, i) => {
    const vals = heat.map((r) => r.cells[i].code).filter((c) => c !== null).map(bbchValue);
    return vals.length >= 2 ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
  });
  for (const r of heat) {
    const pts = r.cells.map((c, i) => [i, c.code]).filter(([, c]) => c !== null);
    const deltas = pts.filter(([i]) => means[i] !== null).map(([i, c]) => bbchValue(c) - means[i]);
    r.delta = deltas.length ? Math.round((deltas.reduce((a, b) => a + b, 0) / deltas.length) * 10) / 10 + 0 : null;
    r.last = pts.length ? pts[pts.length - 1][1] : null;
    r.pts = pts;
    r.hits = MILESTONES.map(([code]) => {
      const hit = pts.find(([, c]) => bbchValue(c) >= bbchValue(code));
      return hit ? weeks[hit[0]] : null;
    });
  }
  return heat;
}

// ------------------------------------------------------------------ plano de sectores
const EQUIPO_RAMP = { 1: ["#F2978B", "#7A1414"], 2: ["#F2D266", "#8A5A06"], 3: ["#93C0EC", "#163F78"], 4: ["#A3D88F", "#235A20"] };
const EMPTY = "#E6E8E3";
const hex = (c) => [1, 3, 5].map((i) => parseInt(c.slice(i, i + 2), 16) / 255);
export function sectorColor(equipo, sector, faded = false) {   // = ui.sector_map.sector_color
  const [lo, hi] = EQUIPO_RAMP[Number(equipo) || 0] || ["#DDDDDD", "#555555"];
  const t = Math.min(1, Math.max(0, ((Number(sector) || 1) - 1) / 9));
  let rgb = hex(lo).map((a, i) => a + (hex(hi)[i] - a) * t);
  if (faded) rgb = rgb.map((x, i) => x * 0.14 + hex(EMPTY)[i] * 0.86);
  const lum = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2];
  return ["#" + rgb.map((x) => Math.round(x * 255).toString(16).padStart(2, "0")).join(""), lum < 0.55 && !faded];
}
export function equipoDark(equipo) { return (EQUIPO_RAMP[Number(equipo)] || ["#999", "#333"])[1]; }

// ------------------------------------------------------------------ mediciones
export function asNumber(v) {             // = measures_export.as_number: «23,5» -> 23.5
  if (typeof v === "number") return v;
  const t = String(v ?? "").trim();
  if (!/^[+-]?(\d+([.,]\d*)?|[.,]\d+)$/.test(t)) return null;
  return Number(t.replace(",", "."));
}
export function slugify(text) {           // = platform_utils.slugify
  const t = (text || "").normalize("NFKD").replace(/[̀-ͯ]/g, "").replace(/[^\x00-\x7f]/g, "");
  return t.replace(/[^a-zA-Z0-9]+/g, "-").replace(/^-+|-+$/g, "").toLowerCase() || "informe";
}
const parseJson = (v, d) => { if (v && typeof v === "object") return v; try { return JSON.parse(v || ""); } catch { return d; } };
export function measures(state) {
  return rows(state, "measures").map((m) => ({ ...m, columns: parseJson(m.columns, []) }))
    .sort((a, b) => (a.sort_order || 0) - (b.sort_order || 0) || (a.created_at || "").localeCompare(b.created_at || ""));
}
export function entriesFor(state, measureUid, weekStart = null) {
  return rows(state, "measure_entries").filter((e) => e.measure_id === measureUid && (!weekStart || e.week_id === weekStart))
    .map((e) => ({ ...e, data: parseJson(e.data, {}) }))
    .sort((a, b) => (a.week_id || "").localeCompare(b.week_id || "") || (a.created_at || "").localeCompare(b.created_at || ""));
}
export function entryFilled(e) {
  return !!e.path || Object.values(e.data || {}).some((v) => String(v ?? "").trim() !== "");
}
// Cambios: alta/edición de un registro de medición, y edición de la medición (columnas).
export function entryChange(e) {
  const ts = nowTs();
  const data = { measure_id: e.measure_id, week_id: e.week_id, variety_id: e.variety_id || null, path: e.path || null,
    caption: (e.caption || "").trim(), data: JSON.stringify(e.data || {}), created_at: e.created_at || ts };
  return { entity: "measure_entries", uid: e.uid || newUid(), ts, deleted: 0, data };
}
export function entryDelete(uid) { return { entity: "measure_entries", uid, ts: nowTs(), deleted: 1 }; }
export function measureChange(m, fields) {
  const ts = nowTs();
  const base = m ? { name: m.name, kind: m.kind, columns: m.columns, sort_order: m.sort_order || 0, created_at: m.created_at || ts }
    : { name: "", kind: "table", columns: ["Columna 1", "Columna 2", "Columna 3"], sort_order: 0, created_at: ts };
  const data = { ...base, ...fields };
  data.columns = JSON.stringify(data.columns || []);
  return { entity: "measures", uid: (m && m.uid) || newUid(), ts, deleted: 0, data };
}
export function weekChange(state, weekStart) {   // la semana, si aún no existe en los paquetes
  if (weekStarts(state).has(weekStart)) return [];
  return [{ entity: "sampling_weeks", uid: weekStart, ts: nowTs(), deleted: 0,
    data: { season: seasonOf(parseDate(weekStart)), week_number: 0, start_date: weekStart, label: weekLabel(weekStart), skipped: 0 } }];
}

// ------------------------------------------------------------------ mapa de fotos
// Registros con fotos y ubicación (= Database.photo_locations): peso = n.º de fotos.
export function photoLocations(state, season, weekStart = null) {
  const skipped = new Set(rows(state, "sampling_weeks").filter((w) => w.skipped).map((w) => w.start_date || w.uid));
  const count = new Map();
  for (const p of rows(state, "photos")) count.set(p.observation_id, (count.get(p.observation_id) || 0) + 1);
  const out = [];
  let missing = 0;
  for (const o of rows(state, "observations")) {
    const n = count.get(o.uid) || 0;
    if (!n || skipped.has(o.week_id) || seasonOf(parseDate(o.week_id)) !== season) continue;
    if (weekStart && o.week_id !== weekStart) continue;
    if (o.latitude == null || o.longitude == null) { missing += n; continue; }
    out.push({ uid: o.uid, lat: Number(o.latitude), lon: Number(o.longitude), weight: n,
      variety_id: o.variety_id, week_id: o.week_id, bbch_code: o.bbch_code });
  }
  return { rows: out, missing };
}

// ------------------------------------------------------------------ semanas
export function weekRow(state, weekStart) {
  return rows(state, "sampling_weeks").find((w) => (w.start_date || w.uid) === weekStart) || null;
}
// «No muestreada» (= Database.set_week_skipped): fuera de los informes, sin borrar datos.
export function weekSkipChanges(state, weekStart, skipped) {
  const w = weekRow(state, weekStart);
  if (!w) return weekChange(state, weekStart).map((c) => ({ ...c, data: { ...c.data, skipped: skipped ? 1 : 0 } }));
  const { uid, ...data } = w;
  return [{ entity: "sampling_weeks", uid, ts: nowTs(), deleted: 0, data: { ...data, skipped: skipped ? 1 : 0 } }];
}
// Vaciar la semana: registros (BBCH/notas), sus fotos y los datos de mediciones de esa semana.
export function weekClearChanges(state, weekStart) {
  const ts = nowTs();
  const obs = rows(state, "observations").filter((o) => o.week_id === weekStart);
  const ids = new Set(obs.map((o) => o.uid));
  const photos = rows(state, "photos").filter((p) => ids.has(p.observation_id));
  const entries = rows(state, "measure_entries").filter((e) => e.week_id === weekStart);
  const del = (entity) => (r) => ({ entity, uid: r.uid, ts, deleted: 1 });
  return { observations: obs.filter((o) => hasData(state, o)).length, photos: photos.length, entries: entries.length,
    changes: [...photos.map(del("photos")), ...entries.map(del("measure_entries")), ...obs.map(del("observations"))] };
}
// Basurero de una medición (= delete_measure_dialog): lo de una semana o la medición completa.
export function measureDeleteChanges(state, measureUid, weekStart = null) {
  const ts = nowTs();
  const changes = rows(state, "measure_entries").filter((e) => e.measure_id === measureUid && (!weekStart || e.week_id === weekStart))
    .map((e) => ({ entity: "measure_entries", uid: e.uid, ts, deleted: 1 }));
  if (!weekStart) changes.push({ entity: "measures", uid: measureUid, ts, deleted: 1 });
  return changes;
}

// ------------------------------------------------------------------ ajustes (variedades, ensayo)
export function setting(state, key, def = null) {     // = Database.get_setting (valor JSON)
  const raw = state.settings[key];
  if (raw === undefined || raw === null) return def;
  try { const v = JSON.parse(raw); return v === null ? def : v; } catch { return raw; }
}
export function allVarieties(state) {                 // con las archivadas
  return rows(state, "varieties")
    .sort((a, b) => (a.sort_order || 0) - (b.sort_order || 0) || (a.name || "").localeCompare(b.name || "", "es"));
}
function sameName(a, b) { return (a || "").trim().toLowerCase() === (b || "").trim().toLowerCase(); }

// Alta o edición de una variedad (= add_variety / update_variety): el nombre no se repite.
export function varietyChange(state, v, fields) {
  const ts = nowTs();
  const data = { name: "", code: "", sector: null, irrigation: null, notes: "", active: 1,
    sort_order: 0, created_at: ts, updated_at: ts, treatment: null, rep: null, cultivar: null, plant_year: null };
  if (v) { const { uid: _u, ...old } = v; Object.assign(data, old); }
  Object.assign(data, fields, { updated_at: ts });
  data.name = (data.name || "").trim();
  if (!data.name) throw new Error("El nombre no puede quedar vacío.");
  const other = allVarieties(state).find((x) => x.uid !== v?.uid && sameName(x.name, data.name));
  if (other && other.active !== 0) throw new Error(`Ya existe «${other.name}».`);
  if (other && !v) return { entity: "varieties", uid: other.uid, ts, deleted: 0, data: { ...other, ...fields, name: other.name, active: 1, updated_at: ts } };
  if (!v) data.sort_order = Math.max(0, ...allVarieties(state).map((x) => Number(x.sort_order) || 0)) + 1;
  return { entity: "varieties", uid: v?.uid || newUid(), ts, deleted: 0, data };
}

export function unitName(sector, irrigation) {        // = phenology.unit_name
  const parts = [];
  if (irrigation) parts.push(`Equipo de riego ${Number(irrigation)}`);
  if (sector) parts.push((parts.length ? "sector" : "Sector") + ` ${Number(sector)}`);
  return parts.join(", ");
}
// Unidad de predio (= Database.save_unit): «Equipo de riego n, sector m» + variedad aparte.
export function unitChange(state, v, { cultivar, code = "", sector = null, irrigation = null, plant_year = null }) {
  cultivar = (cultivar || "").trim();
  sector = sector ? Number(sector) : null; irrigation = irrigation ? Number(irrigation) : null;
  plant_year = plant_year ? Number(plant_year) : null;
  if (!cultivar) throw new Error("Indique la variedad.");
  if (!sector && !irrigation) throw new Error("Elija el sector y/o el equipo de riego.");
  if (plant_year !== null && !(plant_year >= 1950 && plant_year <= 2100)) throw new Error("El año de plantación no es válido.");
  const base = unitName(sector, irrigation);
  const all = allVarieties(state);
  const dup = all.find((x) => x.active !== 0 && x.uid !== v?.uid && (Number(x.sector) || 0) === (sector || 0)
    && (Number(x.irrigation) || 0) === (irrigation || 0) && sameName(x.cultivar, cultivar) && (Number(x.plant_year) || 0) === (plant_year || 0));
  if (dup) throw new Error(`Ya existe «${base}» con la variedad ${cultivar}${plant_year ? ` (${plant_year}).` : "."}`);
  const cands = [base, `${base} · ${cultivar}`, ...(plant_year ? [`${base} · ${cultivar} ${plant_year}`] : [])];
  const name = cands.find((c) => { const o = all.find((x) => sameName(x.name, c)); return !o || o.uid === v?.uid || (o.active === 0 && !v); });
  if (!name) throw new Error(`Ya existe «${base}» con la variedad ${cultivar}.`);
  const reuse = !v && all.find((x) => sameName(x.name, name) && x.active === 0);
  return varietyChange(state, v || reuse || null, { name, code: code || "", cultivar, sector, irrigation, plant_year, active: 1 });
}

// Ensayo de tratamientos × repeticiones (= Database.setup_trial): parcelas T1R1…TnRm; las que
// sobran se archivan (sus registros quedan) y reaparecen al volver a aumentar.
export const MAX_TREATMENTS = 30, MAX_REPS = 12;
export function trialSetup(state, nt, nr) {
  nt = Number(nt); nr = Number(nr);
  if (!(nt >= 1 && nt <= MAX_TREATMENTS) || !(nr >= 1 && nr <= MAX_REPS)) {
    throw new Error(`Tratamientos: 1 a ${MAX_TREATMENTS} · repeticiones: 1 a ${MAX_REPS}.`);
  }
  const ts = nowTs();
  const changes = [];
  const out = { added: 0, restored: 0, archived: 0 };
  const all = allVarieties(state);
  const tre = new Map(rows(state, "treatments").map((t) => [Number(t.num), t]));
  for (let t = 1; t <= nt; t++) {
    if (!tre.has(t)) changes.push({ entity: "treatments", uid: `T${t}`, ts, deleted: 0, data: { num: t, name: "", description: "", cultivar: null } });
    for (let r = 1; r <= nr; r++) {
      const name = `T${t}R${r}`;
      const cur = all.find((x) => Number(x.treatment) === t && Number(x.rep) === r) || all.find((x) => sameName(x.name, name));
      if (!cur) out.added++; else if (cur.active === 0) out.restored++;
      if (cur && cur.active !== 0 && Number(cur.treatment) === t && Number(cur.rep) === r && Number(cur.sort_order) === t * 100 + r) continue;
      const base = cur ? (({ uid: _u, ...o }) => o)(cur) : { name, code: name, sector: null, irrigation: null, notes: "", created_at: ts, cultivar: null, plant_year: null };
      changes.push({ entity: "varieties", uid: cur?.uid || newUid(), ts, deleted: 0,
        data: { ...base, treatment: t, rep: r, active: 1, sort_order: t * 100 + r, updated_at: ts } });
    }
  }
  for (const v of all) {
    if (v.active !== 0 && v.treatment != null && (Number(v.treatment) > nt || Number(v.rep) > nr)) {
      const { uid, ...o } = v;
      changes.push({ entity: "varieties", uid, ts, deleted: 0, data: { ...o, active: 0, updated_at: ts } });
      out.archived++;
    }
  }
  return { ...out, changes, settings: { trial_treatments: JSON.stringify(nt), trial_reps: JSON.stringify(nr) } };
}
export function treatmentChange(state, num, { name = "", description = "", cultivar = null }) {
  return { entity: "treatments", uid: `T${num}`, ts: nowTs(), deleted: 0,
    data: { num: Number(num), name: (name || "").trim(), description: (description || "").trim(), cultivar: (cultivar || "").trim() || null } };
}
// Primera semana fija de la temporada (null = automática, la primera con datos).
export function firstWeekSettings(season, start) {
  return { [`first_week:${season}`]: JSON.stringify(start || null) };
}

// ------------------------------------------------------------------ tratamientos
export function treatments(state) {
  const vs = varieties(state).filter((v) => v.treatment);
  const meta = new Map(rows(state, "treatments").map((t) => [Number(t.num), t]));
  const nums = [...new Set(vs.map((v) => Number(v.treatment)))].sort((a, b) => a - b);
  return nums.map((num) => {
    const t = meta.get(num) || { num, name: "" };
    const name = (t.name || "").trim();
    return { num, name, description: t.description || "", cultivar: t.cultivar || "",
      label: name ? `T${num} · ${name}` : `T${num}`,
      parcels: vs.filter((v) => Number(v.treatment) === num).sort((a, b) => (a.rep || 0) - (b.rep || 0)) };
  });
}
export function numEs(v, digits = 1) {    // = ReportGenerator._num: «23,5», «7»
  if (v === null || v === undefined || v === "") return "—";
  const f = Number(v);
  if (Number.isNaN(f)) return String(v);
  return Number.isInteger(f) ? String(f) : f.toFixed(digits).replace(".", ",");
}

// ------------------------------------------------------------------ cuaderno de campo (= Database.note_*)
// Una página por día (notebook_entries) con sus fotos (notebook_photos, path relativo).
// Si dos equipos crearon el mismo día por separado, se muestran juntas (la app las une por día).
export function noteDays(state) {
  const photos = rows(state, "notebook_photos");
  const byDay = new Map();
  for (const e of rows(state, "notebook_entries")) {
    const d = byDay.get(e.day);
    if (!d) byDay.set(e.day, { ...e, uids: [e.uid] });
    else {
      d.uids.push(e.uid);
      if ((e.updated_at || "") > (d.updated_at || "")) Object.assign(d, { ...e, uid: e.uid, uids: d.uids });
    }
  }
  return [...byDay.values()].map((d) => ({ ...d,
    photos: photos.filter((p) => d.uids.includes(p.entry_id)).sort((a, b) => (a.created_at || "").localeCompare(b.created_at || "")) }))
    .sort((a, b) => b.day.localeCompare(a.day));
}
export function noteFor(state, day) {
  return noteDays(state).find((d) => d.day === day) || null;
}
// Cambio de la página (crear, texto o día). Devuelve {uid, change}.
export function noteChange(state, day, fields = {}) {
  const cur = noteFor(state, day);
  const ts = nowTs();
  const data = cur ? { day: cur.day, text: cur.text || "", ink: cur.ink || "", created_at: cur.created_at || ts }
    : { day, text: "", ink: "", created_at: ts };
  const uid = cur ? cur.uid : newUid();
  return { uid, change: { entity: "notebook_entries", uid, ts, deleted: 0, data: { ...data, ...fields, updated_at: ts } } };
}
export function noteDeleteChanges(state, day) {
  const cur = noteFor(state, day);
  if (!cur) return [];
  const ts = nowTs();
  return [...cur.photos.map((p) => ({ entity: "notebook_photos", uid: p.uid, ts, deleted: 1 })),
    ...cur.uids.map((uid) => ({ entity: "notebook_entries", uid, ts, deleted: 1 }))];
}
export function notePhotoChange(entryUid, relPath) {
  const ts = nowTs();
  return { entity: "notebook_photos", uid: newUid(), ts, deleted: 0,
    data: { entry_id: entryUid, path: relPath, caption: "", annotated: 0, created_at: ts } };
}
export function notePhotoUpdate(photo, fields) {
  const { uid, ...data } = photo;
  return { entity: "notebook_photos", uid, ts: nowTs(), deleted: 0, data: { ...data, ...fields } };
}
// «…-cuaderno.jpg» -> «…-cuaderno-a1.jpg», «-a2»… (= ui.notebook.annotated_name)
export function annotatedName(name, taken) {
  const m = name.match(/^(.*?)(?:-a(\d+))?(\.\w+)?$/);
  const stem = m[1], ext = m[3] || ".jpg";
  let n = m[2] ? Number(m[2]) + 1 : 1;
  while (taken.has(`${stem}-a${n}${ext}`)) n++;
  return `${stem}-a${n}${ext}`;
}
