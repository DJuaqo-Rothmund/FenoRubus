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

export function bundle(device, workspace, changes) {
  return { format: 1, device, workspace, created: nowTs(),
    upto: changes.length ? changes[changes.length - 1].ts : null, changes, settings: {} };
}
export function stamp() {                 // nombre del paquete (= sync_drive._stamp)
  return new Date().toISOString().replace(/[-:]/g, "").replace("Z", "").replace(".", "").slice(0, 18);
}
