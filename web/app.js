// PhenoRubus Web: inicio de sesión con Google, lectura/escritura de los paquetes de
// sincronización en Drive (los mismos de la app) y pantallas de muestreo semanal.
import * as C from "./core.js";
import * as NB from "./notebook.js";
import * as TR from "./train.js";
import { CLIENT_ID } from "./config.js";
import { makeReports } from "./reports.js";
import { warm as warmPdf, makePdf } from "./pdf.js";
import { weekCompleted } from "./celebrate.js";
import { photoHeat, pickPoint, sectorMap } from "./maps.js";

const SCOPE = "https://www.googleapis.com/auth/drive.file";
const API = "https://www.googleapis.com/drive/v3/files";
const UPLOAD = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id";
const ROOT = "PhenoRubus · Imágenes de Fenología";
const SYNC = "Sincronización";
const FOLDER = "application/vnd.google-apps.folder";
const PROFILES = { id: "I+D", predio: "Predio" };
const $ = (id) => document.getElementById(id);

const S = {
  token: null, tokenClient: null, bbch: null, device: null,
  root: null, sync: null, workspaces: [], ws: null, wsFolder: null,
  state: C.emptyState(), bundles: [], week: C.iso(C.mondayOf(C.todayUTC())),
  folders: new Map(), photoUrls: new Map(), photoIds: new Map(), photoErr: new Map(), current: null,
  tab: "sampling", mSeason: null, mMonth: null, maps: new Map(), mapSel: null, mapEq: 0,
};

// ================================================================== Google
function device() {
  let d = localStorage.getItem("pr_device");
  if (!d) { d = "web" + C.newUid().slice(0, 9); localStorage.setItem("pr_device", d); }
  return d;
}

// Sesión recordada: el permiso de Google dura 1 hora y se guarda en este navegador; al
// vencer basta un clic («Continuar como …», sin elegir cuenta ni volver a aceptar permisos).
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { v === null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch { /* sin almacenamiento */ } },
};
function savedToken() {
  try { const o = JSON.parse(store.get("pr_token") || "null"); return o && o.exp > Date.now() ? o.t : null; } catch { return null; }
}

function signIn(prompt = "") {
  return new Promise((resolve, reject) => {
    if (window.__PR_TOKEN__) { S.token = window.__PR_TOKEN__; return resolve(S.token); }   // pruebas
    if (!CLIENT_ID) return reject(new Error("Falta configurar el ID de cliente de Google (web/config.js)."));
    if (!window.google?.accounts?.oauth2) return reject(new Error("No se pudo cargar el inicio de sesión de Google."));
    S.tokenClient ||= google.accounts.oauth2.initTokenClient({ client_id: CLIENT_ID, scope: SCOPE, callback: () => {} });
    S.tokenClient.callback = (r) => {
      if (r.error) return reject(new Error(r.error_description || r.error));
      S.token = r.access_token;
      store.set("pr_token", JSON.stringify({ t: r.access_token, exp: Date.now() + (Number(r.expires_in || 3600) - 120) * 1000 }));
      $("relogin").hidden = true;
      resolve(S.token);
    };
    S.tokenClient.error_callback = (e) => reject(new Error(e.message || e.type || "inicio de sesión cancelado"));
    const hint = store.get("pr_email");
    S.tokenClient.requestAccessToken({ prompt, ...(hint ? { login_hint: hint } : {}) });
  });
}

async function rememberUser() {
  try {
    const r = await api("GET", "https://www.googleapis.com/drive/v3/about?fields=user(emailAddress)");
    if (r.user?.emailAddress) store.set("pr_email", r.user.emailAddress);
  } catch { /* no es indispensable */ }
}

function loginLabel() {
  const hint = store.get("pr_email");
  $("signin").textContent = hint ? `Continuar como ${hint}` : "Iniciar sesión con Google";
}

async function api(method, url, body, ctype, raw = false) {
  for (let attempt = 0; attempt < 2; attempt++) {
    const headers = { Authorization: `Bearer ${S.token}` };
    if (ctype) headers["Content-Type"] = ctype;
    const r = await fetch(url, { method, headers, body });
    if (r.status === 401) {                 // venció la sesión: un clic en «Reconectar»
      store.set("pr_token", null);
      if (!window.__PR_TOKEN__) $("relogin").hidden = false;
      throw new Error("La sesión de Google venció: pulse «Reconectar».");
    }
    if (!r.ok) throw new Error(`Drive ${r.status}: ${(await r.text()).slice(0, 160)}`);
    return raw ? r : r.json();
  }
}
const q = (s) => s.replace(/\\/g, "\\\\").replace(/'/g, "\\'");

async function list(query, fields = "files(id,name,mimeType)") {
  const out = [];
  let token = "";
  do {
    const p = new URLSearchParams({ q: query, fields: `nextPageToken,${fields}`, pageSize: "1000",
      orderBy: "name", spaces: "drive" });
    if (token) p.set("pageToken", token);
    const r = await api("GET", `${API}?${p}`);
    out.push(...(r.files || []));
    token = r.nextPageToken || "";
  } while (token);
  return out;
}

async function folder(name, parent, create = true) {
  const key = `${parent || "root"}/${name}`;
  if (S.folders.has(key)) return S.folders.get(key);
  let query = `name='${q(name)}' and mimeType='${FOLDER}' and trashed=false`;
  if (parent) query += ` and '${parent}' in parents`;
  const found = await list(query, "files(id,name)");
  let id = found[0]?.id || null;
  if (!id && create) {
    const meta = { name, mimeType: FOLDER, ...(parent ? { parents: [parent] } : {}) };
    id = (await api("POST", `${API}?fields=id`, JSON.stringify(meta), "application/json")).id;
  }
  if (id) S.folders.set(key, id);
  return id;
}

async function upload(parent, name, blob, mime) {
  const b = "pr" + C.newUid();
  const meta = JSON.stringify({ name, parents: [parent] });
  const body = new Blob([`--${b}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n`, meta,
    `\r\n--${b}\r\nContent-Type: ${mime}\r\n\r\n`, blob, `\r\n--${b}--\r\n`]);
  return (await api("POST", UPLOAD, body, `multipart/related; boundary=${b}`)).id;
}

async function updateFile(id, blob, mime) {
  const b = "pr" + C.newUid();
  const body = new Blob([`--${b}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{}`,
    `\r\n--${b}\r\nContent-Type: ${mime}\r\n\r\n`, blob, `\r\n--${b}--\r\n`]);
  return api("PATCH", `https://www.googleapis.com/upload/drive/v3/files/${id}?uploadType=multipart&fields=id`, body,
    `multipart/related; boundary=${b}`);
}

// Marcas para entrenar el detector (web/train.js): UN archivo para todos los ensayos y
// predios (es la misma especie), «PhenoRubus · Imágenes de Fenología/Entrenamiento IA/
// marcas.json», aparte de los registros. Los archivos por ensayo de la primera versión
// (<código>.json) se suman al leer.
const TRAIN_DIR = "Entrenamiento IA", TRAIN_FILE = "marcas.json";
async function trainDir(create) {
  const root = await folder(ROOT, null, create);
  return root && await folder(TRAIN_DIR, root, create);
}
async function loadLabels() {
  const dir = await trainDir(false);
  if (!dir) return (await cacheGet("train/all")) || null;
  const files = (await list(`'${dir}' in parents and trashed=false`, "files(id,name)")).filter((f) => f.name.endsWith(".json"));
  const main = files.find((f) => f.name === TRAIN_FILE);
  const out = main ? await (await download(main.id)).json() : { version: 1, photos: {} };
  out.photos ||= {};
  for (const f of files) {
    if (f === main) continue;
    const old = await (await download(f.id)).json().catch(() => null);
    for (const [k, v] of Object.entries(old?.photos || {})) if (!out.photos[k] || (v.ts || "") > (out.photos[k].ts || "")) out.photos[k] = v;
  }
  cachePut("train/all", out);
  return out;
}
// Antes de escribir se suma lo que otro equipo (teléfono o PC) guardó entretanto: por foto
// gana la marca más reciente, así se puede marcar en ambos a la vez sin perder nada.
async function saveLabels(data) {
  const dir = await trainDir(true);
  const f = await list(`'${dir}' in parents and name='${TRAIN_FILE}' and trashed=false`, "files(id,name)");
  if (f[0]) {
    const remote = await (await download(f[0].id)).json().catch(() => null);
    for (const [k, v] of Object.entries(remote?.photos || {})) {
      if (!data.photos[k] || (v.ts || "") > (data.photos[k].ts || "")) data.photos[k] = v;
    }
  }
  cachePut("train/all", data);
  const blob = new Blob([JSON.stringify(data)], { type: "application/json" });
  if (f[0]) await updateFile(f[0].id, blob, "application/json");
  else await upload(dir, TRAIN_FILE, blob, "application/json");
}

// Registros de TODOS los ensayos y predios (para entrenar con las fotos de todos): lo
// guardado en el navegador y, si hay conexión, lo nuevo de Drive.
async function allStates(progress = () => {}) {
  const out = [];
  let i = 0;
  for (const ws of S.workspaces) {
    progress(`Leyendo ${ws.name || ws.code} (${++i}/${S.workspaces.length})…`);
    if (S.ws && ws.code === S.ws.code) { out.push({ ws, state: S.state }); continue; }
    const st = C.emptyState();
    const names = (await cacheGet(`${ws.code}/__index`)) || [];
    for (const n of names) { const b = await cacheGet(`${ws.code}/${n}`); if (b) C.applyBundle(st, n, b); }
    try {
      const dir = S.sync && await folder(ws.code, S.sync, false);
      if (dir) {
        const files = (await list(`'${dir}' in parents and trashed=false`))
          .filter((f) => f.name.endsWith(".json")).sort((a, b) => a.name.localeCompare(b.name));
        const todo = files.filter((f) => !st.seen.has(f.name));
        const got = new Array(todo.length);
        await pool(todo, 8, async (f, k) => {
          let b = await cacheGet(`${ws.code}/${f.name}`);
          if (!b) { b = await (await download(f.id)).json(); cachePut(`${ws.code}/${f.name}`, b); }
          got[k] = b;
        });
        todo.forEach((f, k) => C.applyBundle(st, f.name, got[k]));
        cachePut(`${ws.code}/__index`, files.map((f) => f.name));
      }
    } catch { /* sin conexión: lo guardado */ }
    out.push({ ws, state: st });
  }
  return out;
}

async function download(id) {
  return api("GET", `${API}/${id}?alt=media`, undefined, undefined, true);
}

// ================================================================== caché (IndexedDB)
// «bundles»: paquetes ya leídos; «photos»: fotos ya bajadas (no se vuelven a pedir a Drive).
const idb = new Promise((resolve) => {
  try {
    const r = indexedDB.open("phenorubus", 2);
    r.onupgradeneeded = () => {
      for (const st of ["bundles", "photos"]) if (!r.result.objectStoreNames.contains(st)) r.result.createObjectStore(st);
    };
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => resolve(null);
  } catch { resolve(null); }
});
async function cacheGet(key, store = "bundles") {
  const db = await idb; if (!db) return null;
  return new Promise((res) => {
    try {
      const r = db.transaction(store).objectStore(store).get(key);
      r.onsuccess = () => res(r.result || null); r.onerror = () => res(null);
    } catch { res(null); }
  });
}
async function cachePut(key, val, store = "bundles") {
  const db = await idb; if (!db) return;
  try { db.transaction(store, "readwrite").objectStore(store).put(val, key); } catch { /* caché llena: se ignora */ }
}

async function pool(items, n, fn) {        // fn(item, i) con n en paralelo
  let next = 0;
  const run = async () => { while (next < items.length) { const i = next++; await fn(items[i], i); } };
  await Promise.all(Array.from({ length: Math.min(n, items.length) }, run));
}

// ================================================================== sincronización
function status(t) { $("status").textContent = t || ""; }

async function loadWorkspaces() {
  S.root = await folder(ROOT, null, false);
  S.sync = S.root && await folder(SYNC, S.root, false);
  if (!S.sync) throw new Error("Aún no hay datos en Drive: abra la app del celular con Google Drive conectado y pulse «Sincronizar».");
  const files = await list(`'${S.sync}' in parents and trashed=false`);
  const byCode = new Map();
  const lists = new Array(files.length);
  await pool(files, 6, async (f, i) => {
    if (f.mimeType !== FOLDER && /^ensayos-.*\.json$/.test(f.name)) lists[i] = await (await download(f.id)).json();
  });
  for (const l of lists) for (const ws of l || []) byCode.set(ws.code, ws);
  for (const f of files) if (f.mimeType === FOLDER && !byCode.has(f.name)) byCode.set(f.name, { code: f.name, name: f.name, profile: "" });
  S.workspaces = [...byCode.values()];
  for (const f of files) if (f.mimeType === FOLDER) S.folders.set(`${S.sync}/${f.name}`, f.id);
}

// Abre el ensayo al instante con lo guardado en el navegador; Drive se consulta después.
async function openCached(code) {
  S.ws = S.workspaces.find((w) => w.code === code) || S.workspaces[0];
  store.set("pr_ws", S.ws.code);
  store.set(`pr_ws_${profileOf(S.ws)}`, S.ws.code);
  fillWorkspaces();
  S.state = C.emptyState();
  S.bundles = [];
  S.photoIds.clear();
  S.wsFolder = null;
  const names = (await cacheGet(`${S.ws.code}/__index`)) || [];
  const got = await Promise.all(names.map((n) => cacheGet(`${S.ws.code}/${n}`)));
  names.forEach((n, i) => { if (got[i]) { C.applyBundle(S.state, n, got[i]); S.bundles.push([n, got[i]]); } });
  for (const p of pending()) { C.applyBundle(S.state, p.name, p.bundle); S.bundles.push([p.name, p.bundle]); }
}

async function loadWorkspace(code) {
  await openCached(code);
  if (S.bundles.length) render();
  else { $("rows").innerHTML = `<p class="muted">Cargando desde Google Drive…</p>`; $("mlist").innerHTML = ""; }
  S.wsFolder = await folder(S.ws.code, S.sync);
  await pull();
}

async function pull() {
  status("Sincronizando…");
  const files = (await list(`'${S.wsFolder}' in parents and trashed=false`))
    .filter((f) => f.name.endsWith(".json")).sort((a, b) => a.name.localeCompare(b.name));
  let n = 0, done = 0;
  const todo = files.filter((f) => !S.state.seen.has(f.name));
  const got = new Array(todo.length);
  await pool(todo, 8, async (f, i) => {      // en paralelo; se aplican después en orden
    const key = `${S.ws.code}/${f.name}`;
    let bundle = await cacheGet(key);
    if (!bundle) {
      bundle = await (await download(f.id)).json();
      cachePut(key, bundle);
    }
    got[i] = bundle;
    if (todo.length > 8) status(`Sincronizando ${++done}/${todo.length}…`);
  });
  todo.forEach((f, i) => {
    n += C.applyBundle(S.state, f.name, got[i]);
    S.bundles.push([f.name, got[i]]);
  });
  cachePut(`${S.ws.code}/__index`, files.map((f) => f.name));
  await pushPending();
  status(`Sincronizado ${new Date().toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" })}`);
  return n;
}

function pending() { return JSON.parse(localStorage.getItem(`pr_pending_${S.ws.code}`) || "[]"); }
function setPending(list_) { localStorage.setItem(`pr_pending_${S.ws.code}`, JSON.stringify(list_)); }

async function send(changes, settings = {}) {
  const name = `${C.stamp()}-${S.device}.json`;
  const bundle = C.bundle(S.device, S.ws.code, changes, settings);
  C.applyBundle(S.state, name, bundle);            // se ve al instante
  S.bundles.push([name, bundle]);
  setPending([...pending(), { name, bundle }]);
  await pushPending();
}

async function pushPending() {
  if (!S.wsFolder) return;                 // aún conectando con Drive: se envía al sincronizar
  const left = [];
  for (const p of pending()) {
    try {
      await upload(S.wsFolder, p.name, new Blob([JSON.stringify(p.bundle)], { type: "application/json" }), "application/json");
      cachePut(`${S.ws.code}/${p.name}`, p.bundle);
      C.applyBundle(S.state, p.name, p.bundle);
    } catch (e) { left.push(p); status("Sin conexión: se enviará después"); }
  }
  setPending(left);
}

// ================================================================== fotos
function base(path) { return (path || "").split(/[\\/]/).pop(); }

// Búsqueda de fotos en Drive por nombre, de a varias por consulta (una por cada 40 fotos).
const lookups = new Map();
let lookupTimer = null;
function findId(name) {
  return new Promise((resolve, reject) => {
    if (!lookups.has(name)) lookups.set(name, []);
    lookups.get(name).push([resolve, reject]);
    lookupTimer ||= setTimeout(flushLookups, 0);
  });
}
async function flushLookups() {
  lookupTimer = null;
  const batch = [...lookups];
  lookups.clear();
  const parts = [];
  for (let i = 0; i < batch.length; i += 40) parts.push(batch.slice(i, i + 40));
  await pool(parts, 4, async (part) => {
    try {
      const found = await list(`(${part.map(([n]) => `name='${q(n)}'`).join(" or ")}) and trashed=false`, "files(id,name)");
      const ids = new Map(found.map((f) => [f.name, f.id]));
      for (const [n, waiters] of part) waiters.forEach(([res]) => res(ids.get(n) || null));
    } catch (e) {
      for (const [, waiters] of part) waiters.forEach(([, rej]) => rej(e));
    }
  });
}

const inflight = new Map();
function photoUrl(path) {
  const name = base(path);
  if (S.photoUrls.has(name)) return Promise.resolve(S.photoUrls.get(name));
  if (!inflight.has(name)) inflight.set(name, fetchPhoto(name).finally(() => inflight.delete(name)));
  return inflight.get(name);
}

async function fetchPhoto(name) {
  const cached = await cacheGet(name, "photos");
  if (cached) { const url = URL.createObjectURL(cached); S.photoUrls.set(name, url); return url; }
  try {
    let id = S.photoIds.get(name);
    if (id === undefined) { id = await findId(name); S.photoIds.set(name, id); }
    if (!id) { S.photoErr.set(name, "missing"); return null; }   // aún no está en Drive
    const blob = await (await download(id)).blob();
    cachePut(name, blob, "photos");
    const url = URL.createObjectURL(blob);
    S.photoUrls.set(name, url);
    S.photoErr.delete(name);
    return url;
  } catch (e) {
    S.photoErr.set(name, e.message);
    return null;
  }
}

async function firstUrl(photos) {         // la principal o, si aún no está en Drive, otra
  for (const p of photos) { const u = await photoUrl(p.path); if (u) return u; }
  return null;
}

async function resize(file) {
  const bmp = await createImageBitmap(file, { imageOrientation: "from-image" });
  const k = Math.min(1, 1600 / Math.max(bmp.width, bmp.height));
  const cv = document.createElement("canvas");
  cv.width = Math.round(bmp.width * k); cv.height = Math.round(bmp.height * k);
  cv.getContext("2d").drawImage(bmp, 0, 0, cv.width, cv.height);
  return new Promise((res) => cv.toBlob(res, "image/jpeg", 0.78));
}

async function weekFolderId(week = S.week, sub = "") {
  const prefix = `${PROFILES[S.ws.profile] || "Otros"}/${(S.ws.name || S.ws.code).replace(/\//g, "-").trim()}`;
  let parent = await folder(ROOT, null, true);
  for (const part of `${prefix}/${C.weekFolder(week)}${sub ? `/${sub}` : ""}`.split("/")) parent = await folder(part, parent, true);
  return parent;
}

// Foto del cuaderno: carpeta exclusiva «PhenoRubus · …/Cuaderno de campo» (= notebook_export).
async function uploadNotePhoto(day, name, blob) {
  const dir = await folder("Cuaderno de campo", await folder(ROOT, null, true), true);
  const id = await upload(dir, name, blob, "image/jpeg");
  S.photoIds.set(name, id);
  S.photoUrls.set(name, URL.createObjectURL(blob));
  cachePut(name, blob, "photos");
}

async function addPhotos(v, files, kind) {
  const changes = [];
  let obs = C.observationFor(S.state, v.uid, S.week);
  if (!obs) {
    const r = C.observationChanges(S.state, v.uid, S.week, {}, "");
    changes.push(...r.changes);
    C.applyBundle(S.state, `local-${C.newUid()}`, { changes: r.changes });
    obs = C.observationFor(S.state, v.uid, S.week);
  }
  const taken = new Set(C.rows(S.state, "photos").map((p) => base(p.path)));
  const dir = await weekFolderId();
  const season = C.seasonOf(C.parseDate(S.week));
  // Sin ubicación: la toma del GPS de la primera foto que lo traiga (como la app).
  if (obs.latitude == null || obs.longitude == null) {
    for (const f of files) {
      const gps = C.exifGps(await f.arrayBuffer().catch(() => new ArrayBuffer(0)));
      if (gps) {
        const r = C.observationChanges(S.state, v.uid, S.week, { latitude: gps[0], longitude: gps[1], gps_accuracy: null, gps_source: "foto" });
        changes.push(...r.changes);
        C.applyBundle(S.state, `local-${C.newUid()}`, { changes: r.changes });
        break;
      }
    }
  }
  for (const f of files) {
    let seq = 1, name;
    do { name = `${C.photoBasename(v, S.week, kind, seq++, S.ws.code)}.jpg`; } while (taken.has(name));
    taken.add(name);
    $("dmsg").textContent = `Subiendo ${name}…`;
    const blob = await resize(f);
    const id = await upload(dir, name, blob, "image/jpeg");
    S.photoIds.set(name, id);
    S.photoUrls.set(name, URL.createObjectURL(blob));
    cachePut(name, blob, "photos");
    const ch = C.photoChange(S.state, obs.uid, kind, `photos/T${season}/web/${name}`);
    changes.push(ch);
    C.applyBundle(S.state, `local-${C.newUid()}`, { changes: [ch] });
  }
  await send(changes);
  $("dmsg").textContent = `${files.length} foto(s) subida(s). El celular las descarga en su próxima sincronización.`;
}

// ================================================================== pantalla
function stageLabel(code) {
  const s = S.bbch.stages.find((x) => x.code === code);
  return s ? s.label : "";
}

function stageText(obs) {                 // nombre actual de la escala (no el guardado antes)
  return stageLabel(obs.bbch_code) || (obs.bbch_label || "").replace(/^BBCH\s*[\d-]+\s*[:·-]\s*/i, "");
}

function seasonOptions(sel, current) {
  sel.innerHTML = "";
  for (const s of C.seasons(S.state)) {
    const o = document.createElement("option");
    o.value = s; o.textContent = C.seasonTitle(s);
    sel.appendChild(o);
  }
  if (![...sel.options].some((o) => Number(o.value) === current)) {
    const o = document.createElement("option"); o.value = current; o.textContent = C.seasonTitle(current); sel.appendChild(o);
  }
  sel.value = current;
}

function goSeason(season) {                 // la semana actual o la última con datos
  if (season === C.seasonOf(C.todayUTC())) S.week = C.iso(C.mondayOf(C.todayUTC()));
  else { const ws = C.seasonWeeks(S.state, season); S.week = ws.length ? ws[ws.length - 1] : C.iso(C.seasonFirstMonday(season)); }
}

function renderWeek() {
  const season = C.seasonOf(C.parseDate(S.week));
  seasonOptions($("season"), season);
  $("kicker").textContent = C.weekTitle(S.week).toUpperCase();
  $("wtitle").textContent = C.weekLabel(S.week);
  $("wrange").textContent = C.weekRange(S.week);
}

function render() {
  if (S.tab === "matrix") renderMatrix();
  if (S.tab === "reports") renderReports();
  if (S.tab === "settings") renderSettings();
  if (S.tab === "notebook") NB.renderNotebook();

  renderSampling();
}

async function setSkipped(on) {
  try {
    await send(C.weekSkipChanges(S.state, S.week, on));
    status(on ? `${C.weekTitle(S.week)} marcada como no muestreada: no aparecerá en los informes`
      : `${C.weekTitle(S.week)} vuelve a incluirse en los informes`);
    render();
  } catch (e) { status(`No se pudo guardar: ${e.message}`); $("skipweek").checked = !on; }
}

async function clearWeek() {
  const r = C.weekClearChanges(S.state, S.week);
  if (!r.changes.length) { status(`${C.weekTitle(S.week)} no tiene registros.`); return; }
  const parts = [r.observations && `${r.observations} registro(s) BBCH/notas`, r.photos && `${r.photos} foto(s)`,
    r.entries && `${r.entries} dato(s) de mediciones`].filter(Boolean).join(", ");
  if (!confirm(`¿Vaciar ${C.weekTitle(S.week)} (${C.weekLabel(S.week)})?\n\nSe borrarán ${parts || "los registros vacíos"}.\n` +
    "También se borran en el celular al sincronizar. Los archivos de fotos quedan en Drive.\n\nEsto no se puede deshacer.")) return;
  try { await send(r.changes); status(`${C.weekTitle(S.week)} vaciada.`); render(); }
  catch (e) { status(`No se pudo vaciar: ${e.message}`); }
}

function renderSampling() {
  renderWeek();
  const wk = C.weekRow(S.state, S.week);
  const skipped = !!wk?.skipped;
  $("skipweek").checked = skipped;
  if (skipped) $("kicker").textContent += " · NO MUESTREADA";
  $("rows").classList.toggle("faded", skipped);
  const vs = C.varieties(S.state);
  const box = $("rows");
  box.innerHTML = "";
  let done = 0;
  const isPredio = S.ws.profile === "predio";
  $("listlabel").textContent = (isPredio ? "SECTORES" : "VARIEDADES") + " · TOQUE PARA REGISTRAR";
  if (!vs.length) {
    box.innerHTML = `<p class="muted">Este ${isPredio ? "predio" : "ensayo"} aún no tiene registros en Drive. Ábralo en el celular y sincronice.</p>`;
  }
  for (const v of vs) {
    const obs = C.observationFor(S.state, v.uid, S.week);
    const photos = obs ? C.photosFor(S.state, obs.uid) : [];
    if (obs && obs.bbch_code !== null && obs.bbch_code !== undefined) done++;
    const el = document.createElement("button");
    el.className = "card row";
    const sub = obs?.bbch_code != null ? `BBCH ${C.codeStr(obs.bbch_code)}: ${stageText(obs)}` : "Pendiente de registro";
    el.innerHTML = `<div class="thumb">🌱</div>
      <div><div class="place"></div><div class="name"></div><div class="sub"></div></div>
      <div class="badges"><span class="badge">${photos.length ? photos.length + " FOTO" + (photos.length > 1 ? "S" : "") : "SIN FOTOS"}</span>
      <span class="badge ${obs?.bbch_code != null ? "bbch" : "none"}">BBCH ${obs?.bbch_code != null ? C.codeStr(obs.bbch_code) : "—"}</span></div>`;
    el.querySelector(".place").textContent = C.unitPlace(v);
    el.querySelector(".name").textContent = C.unitMain(v);
    el.querySelector(".sub").textContent = sub + (obs?.notes ? ` · ${obs.notes}` : "");
    el.onclick = () => openDetail(v);
    box.appendChild(el);
    if (photos.length) firstUrl(photos).then((u) => {
      if (u) { const t = el.querySelector(".thumb"); t.style.backgroundImage = `url(${u})`; t.textContent = ""; }
    }).catch(() => {});
  }
  $("pbar").style.width = vs.length ? `${(100 * done) / vs.length}%` : "0";
  $("ptext").textContent = skipped ? "omitida" : `${done}/${vs.length} completas`;
  // Semana recién completada (pasó de incompleta a completa mientras se miraba): confeti,
  // como en la app. Abrir una semana que ya estaba completa no lo repite.
  const full = vs.length > 0 && done === vs.length && !skipped;
  const key = `${S.ws.code}|${S.week}`;
  S.weekDone ||= new Map();
  if (full && S.weekDone.get(key) === false) setTimeout(() => weekCompleted(String(C.isoWeek(C.parseDate(S.week))[0])), 250);
  S.weekDone.set(key, full);
  renderMeasures();
}

function fillBbch(sel, code) {
  sel.innerHTML = `<option value="">— Sin estado —</option>`;
  for (const [m, title] of Object.entries(S.bbch.macros)) {
    const g = document.createElement("optgroup");
    g.label = `${m} · ${title}`;
    for (const s of S.bbch.stages.filter((x) => String(x.macro) === m)) {
      const o = document.createElement("option");
      o.value = s.code; o.textContent = `${s.text} · ${s.label}`;
      if (s.code === code) o.selected = true;
      g.appendChild(o);
    }
    sel.appendChild(g);
  }
}

// Casilla que recibe fotos arrastradas o elegidas con un clic (fuera de las miniaturas).
function dropZone(el, input, onFiles, { click = true, msg = "dmsg" } = {}) {
  const take = (list) => {
    const files = [...list].filter((f) => f.type.startsWith("image/") || /\.(jpe?g|png|heic|webp)$/i.test(f.name));
    if (files.length) onFiles(files);
    else if (list.length) $(msg).textContent = "Solo se pueden subir imágenes.";
  };
  if (click) {
    el.onclick = (e) => { if (!e.target.closest(".ph:not(.pending)")) input.click(); };
    input.onclick = (e) => e.stopPropagation();
  }
  input.onchange = () => { const l = [...input.files]; input.value = ""; take(l); };
  el.ondragover = (e) => { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; el.classList.add("over"); };
  el.ondragleave = (e) => { if (!el.contains(e.relatedTarget)) el.classList.remove("over"); };
  el.ondrop = (e) => { e.preventDefault(); el.classList.remove("over"); take(e.dataTransfer.files); };
}

async function uploadTo(kind, files) {
  const zone = document.querySelector(`#detail .drop[data-kind="${kind}"]`);
  zone.classList.add("busy");
  try { await addPhotos(S.current, files, kind); renderPhotos(S.current); renderLocation(); render(); }
  catch (er) { $("dmsg").textContent = `No se pudieron subir: ${er.message}`; }
  finally { zone.classList.remove("busy"); }
}

async function deletePhotos(uids) {
  if (!uids.length) return;
  const what = uids.length === 1 ? "esta foto" : `estas ${uids.length} fotos`;
  if (!confirm(`¿Eliminar ${what} del registro?\n(Se quita también en el celular al sincronizar; el archivo queda en Drive.)`)) return;
  try {
    await send(C.photoDeleteChanges(S.state, uids));
    S.photoSel.clear();
    $("dmsg").textContent = uids.length === 1 ? "Foto eliminada." : `${uids.length} fotos eliminadas.`;
    renderPhotos(S.current);
    render();
  } catch (e) { $("dmsg").textContent = `No se pudo eliminar: ${e.message}`; }
}

function selBar() {
  const n = S.photoSel.size;
  $("dselbar").hidden = !n;
  $("dseltext").textContent = n === 1 ? "1 foto seleccionada" : `${n} fotos seleccionadas`;
}

function renderPhotos(v) {
  const obs = C.observationFor(S.state, v.uid, S.week);
  S.photoSel ||= new Set();
  const live = new Set((obs ? C.photosFor(S.state, obs.uid) : []).map((p) => p.uid));
  for (const u of [...S.photoSel]) if (!live.has(u)) S.photoSel.delete(u);
  selBar();
  const boxes = {};
  document.querySelectorAll("#detail .drop").forEach((z) => {
    boxes[z.dataset.kind] = z.querySelector(".photos");
    boxes[z.dataset.kind].innerHTML = "";
  });
  const photos = obs ? C.photosFor(S.state, obs.uid) : [];
  const jobs = photos.map((p) => {
    const d = document.createElement("div");
    d.className = "ph pending";
    d.innerHTML = `<span>${p.is_primary ? "★ Principal" : ""}</span><em>Buscando…</em>`;
    if (!p.is_primary) d.querySelector("span").remove();
    const pick = document.createElement("button");
    pick.type = "button"; pick.className = "pick"; pick.title = "Seleccionar";
    const del = document.createElement("button");
    del.type = "button"; del.className = "pdel"; del.textContent = "✕"; del.title = "Eliminar esta foto";
    if (!p.is_primary) {
      const star = document.createElement("button");
      star.type = "button"; star.className = "pstar"; star.textContent = "★"; star.title = "Hacer principal";
      star.onclick = async (e) => {
        e.stopPropagation();
        try { await send(C.photoPrimaryChanges(S.state, p.uid)); renderPhotos(S.current); render(); }
        catch (er) { $("dmsg").textContent = `No se pudo cambiar: ${er.message}`; }
      };
      d.append(star);
    }
    const mark = () => { pick.textContent = S.photoSel.has(p.uid) ? "✓" : ""; d.classList.toggle("selected", S.photoSel.has(p.uid)); };
    pick.onclick = (e) => { e.stopPropagation(); S.photoSel.has(p.uid) ? S.photoSel.delete(p.uid) : S.photoSel.add(p.uid); mark(); selBar(); };
    del.onclick = (e) => { e.stopPropagation(); deletePhotos([p.uid]); };
    d.append(pick, del);
    mark();
    (boxes[p.kind] || boxes.detail).appendChild(d);
    return photoUrl(p.path).then((u) => {
      const em = d.querySelector("em");
      if (!u) {
        const err = S.photoErr.get(base(p.path));
        em.textContent = err === "missing" ? "No está en Drive" : "Error al bajar";
        d.title = `${base(p.path)}${err && err !== "missing" ? " · " + err : ""}`;
        return err === "missing" ? "missing" : "error";
      }
      em.remove();
      d.classList.remove("pending");
      d.style.backgroundImage = `url(${u})`;
      d.onclick = (e) => { e.stopPropagation(); $("vimg").src = u; $("viewer").showModal(); };
      return "ok";
    }).catch(() => "error");
  });
  Promise.all(jobs).then((res) => {
    const missing = res.filter((r) => r === "missing").length, errors = res.filter((r) => r === "error").length;
    const msg = [];
    if (missing) msg.push(`${missing} foto(s) aún no están en Google Drive: en el celular, Ajustes › Respaldo en ` +
      "Google Drive › «Subir anteriores» (con Wi-Fi si está activado «Subir solo con Wi-Fi»).");
    if (errors) msg.push(`${errors} foto(s) no se pudieron descargar (pase el mouse sobre la foto para ver el detalle).`);
    if (msg.length && !$("dmsg").textContent) $("dmsg").textContent = msg.join(" ");
  });
}

// ------------------------------------------------------------ ubicación del registro
const GPS_SOURCES = { gps: "GPS del equipo", foto: "desde la foto", mapa: "marcada en el mapa" };
function renderLocation() {
  const obs = C.observationFor(S.state, S.current.uid, S.week);
  const has = obs && obs.latitude != null && obs.longitude != null;
  $("dloc").textContent = has
    ? `${Number(obs.latitude).toFixed(6)}, ${Number(obs.longitude).toFixed(6)} · ${GPS_SOURCES[obs.gps_source] || obs.gps_source || ""}`
      + (obs.gps_accuracy ? ` · ±${Math.round(obs.gps_accuracy)} m` : "")
    : "Sin ubicación (opcional; se completa sola si la foto trae GPS)";
  $("dlocdel").hidden = !has;
}
async function setLocation(lat, lon, accuracy, source) {
  const { changes } = C.observationChanges(S.state, S.current.uid, S.week,
    { latitude: lat, longitude: lon, gps_accuracy: accuracy ?? null, gps_source: source });
  await send(changes);
  renderLocation();
  render();
}
function locateMe() {
  if (!navigator.geolocation) { $("dmsg").textContent = "Este navegador no entrega la ubicación."; return; }
  $("dmsg").textContent = "Buscando ubicación…";
  navigator.geolocation.getCurrentPosition(
    (p) => setLocation(p.coords.latitude, p.coords.longitude, p.coords.accuracy, "gps")
      .then(() => { $("dmsg").textContent = "Ubicación guardada."; }),
    (e) => { $("dmsg").textContent = `No se pudo obtener la ubicación: ${e.code === 1 ? "permiso denegado" : e.message}`; },
    { enableHighAccuracy: true, timeout: 20000, maximumAge: 0 });
}

function openDetail(v) {
  S.current = v;
  const obs = C.observationFor(S.state, v.uid, S.week);
  $("dplace").textContent = C.unitPlace(v);
  $("dname").textContent = C.unitMain(v);
  $("dweek").textContent = `${C.weekTitle(S.week)} · ${C.weekLabel(S.week)}`;
  fillBbch($("dbbch"), obs?.bbch_code ?? null);
  $("dnotes").value = obs?.notes || "";
  $("dmsg").textContent = "";
  S.photoSel = new Set();
  renderPhotos(v);
  renderLocation();
  $("detail").showModal();
}

async function saveDetail(ev) {
  ev.preventDefault();
  const v = S.current;
  const raw = $("dbbch").value;
  const code = raw === "" ? null : Number(raw);
  const obs = C.observationFor(S.state, v.uid, S.week);
  const notes = $("dnotes").value.trim();
  if ((obs?.bbch_code ?? null) === code && (obs?.notes || "") === notes) { $("detail").close(); return; }
  $("dsave").disabled = true;
  try {
    const { changes } = C.observationChanges(S.state, v.uid, S.week, { bbch_code: code, notes }, code === null ? "" : stageLabel(code));
    await send(changes);
    $("detail").close();
    render();
  } catch (e) {
    $("dmsg").textContent = `No se pudo guardar: ${e.message}`;
  } finally { $("dsave").disabled = false; }
}

function shift(days) {
  const d = C.addDays(C.parseDate(S.week), days);
  if (d.getUTCFullYear() < 2020 || d.getUTCFullYear() > 2050) return;
  S.week = C.iso(d);
  render();
}

// ================================================================== mediciones
const KIND_NAME = { table: "Planilla de datos", images: "Registro de imágenes" };

function renderMeasures() {
  const box = $("mlist");
  box.innerHTML = "";
  for (const m of C.measures(S.state)) {
    const n = C.entriesFor(S.state, m.uid, S.week).filter(C.entryFilled).length;
    const el = document.createElement("button");
    el.className = "card row mrow";
    el.innerHTML = `<div class="thumb">${m.kind === "images" ? "📷" : "📋"}</div>
      <div><div class="place"></div><div class="name"></div><div class="sub"></div></div>
      <div class="badges"><span class="badge ${n ? "bbch" : "none"}">${n ? n + (m.kind === "images" ? " FOTO" : " FILA") + (n > 1 ? "S" : "") : "SIN DATOS"}</span></div>`;
    el.querySelector(".place").textContent = KIND_NAME[m.kind] || m.kind;
    el.querySelector(".name").textContent = m.name;
    el.querySelector(".sub").textContent = m.kind === "table" ? m.columns.join(" · ") : "Fotos con descripción";
    el.onclick = () => openMeasure(m.uid);
    box.appendChild(el);
  }
  const add = document.createElement("button");
  add.className = "card row mrow add";
  add.textContent = "＋ Nueva medición";
  add.onclick = () => { $("nname").value = ""; $("nmsg").textContent = ""; $("newmeasure").showModal(); };
  box.appendChild(add);
}

function varietySelect(value) {
  const sel = document.createElement("select");
  sel.innerHTML = `<option value="">— Sin variedad —</option>`;
  for (const v of C.varieties(S.state)) {
    const o = document.createElement("option");
    o.value = v.uid; o.textContent = C.unitMain(v) + (C.unitPlace(v) ? ` · ${C.unitPlace(v)}` : "");
    sel.appendChild(o);
  }
  sel.value = value || "";
  return sel;
}

async function createMeasure(ev) {
  ev.preventDefault();
  const name = $("nname").value.trim(), kind = $("nkind").value;
  if (!name) { $("nmsg").textContent = "Póngale un nombre a la medición."; return; }
  const order = Math.max(0, ...C.measures(S.state).map((m) => Number(m.sort_order) || 0)) + 1;
  const ch = C.measureChange(null, { name, kind, sort_order: order, columns: kind === "table" ? ["Columna 1", "Columna 2", "Columna 3"] : [] });
  try {
    await send([ch]);
    $("newmeasure").close();
    render();
    openMeasure(ch.uid);
  } catch (e) { $("nmsg").textContent = `No se pudo crear: ${e.message}`; }
}

function openMeasure(uid) {
  const m = C.measures(S.state).find((x) => x.uid === uid);
  if (!m) return;
  const entries = C.entriesFor(S.state, m.uid, S.week);
  S.meas = { m, cols: m.columns.map((c) => ({ orig: c, name: c })),
    rows: entries.map((e) => ({ e, variety_id: e.variety_id || "", data: { ...e.data }, caption: e.caption || "", gone: false })) };
  if (m.kind === "table" && !S.meas.rows.length) S.meas.rows.push({ e: null, variety_id: "", data: {}, caption: "", gone: false });
  $("mkind").textContent = KIND_NAME[m.kind] || m.kind;
  $("mname").value = m.name;
  $("mweek").textContent = `${C.weekTitle(S.week)} · ${C.weekLabel(S.week)}`;
  $("mmsg").textContent = "";
  renderMeasureBody();
  $("mdelweek").hidden = !entries.length;
  if (!$("measure").open) $("measure").showModal();
}

function renderMeasureBody() {
  const M = S.meas, box = $("mbody");
  box.innerHTML = "";
  box.className = "";
  if (M.m.kind === "table") {
    const t = document.createElement("table");
    t.className = "mgrid";
    const hr = document.createElement("tr");
    hr.innerHTML = `<th>#</th><th>Variedad / sector</th>`;
    M.cols.forEach((c, i) => {
      const th = document.createElement("th");
      const hc = document.createElement("div");
      hc.className = "hcol"; th.appendChild(hc);
      const inp = document.createElement("input");
      inp.value = c.name; inp.title = "Nombre de la columna";
      inp.oninput = () => { c.name = inp.value; };
      hc.appendChild(inp);
      if (M.cols.length > 1) {
        const del = document.createElement("button");
        del.type = "button"; del.className = "del"; del.textContent = "✕"; del.title = "Eliminar la columna (y sus datos en todas las semanas)";
        del.onclick = () => { if (confirm(`¿Eliminar la columna «${c.name}» y sus datos en todas las semanas?`)) { M.cols.splice(i, 1); renderMeasureBody(); } };
        hc.appendChild(del);
      }
      hr.appendChild(th);
    });
    hr.insertAdjacentHTML("beforeend", `<th class="x"></th>`);
    const thead = document.createElement("thead"); thead.appendChild(hr); t.appendChild(thead);
    const tb = document.createElement("tbody");
    M.rows.filter((r) => !r.gone).forEach((r, i) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td class="n">${i + 1}</td>`;
      const tdv = document.createElement("td");
      const sel = varietySelect(r.variety_id);
      sel.onchange = () => { r.variety_id = sel.value; };
      tdv.appendChild(sel); tr.appendChild(tdv);
      for (const c of M.cols) {
        const td = document.createElement("td");
        const inp = document.createElement("input");
        inp.value = r.data[c.orig] ?? ""; inp.inputMode = "decimal";
        inp.oninput = () => { r.data[c.orig] = inp.value; };
        td.appendChild(inp); tr.appendChild(td);
      }
      const tdx = document.createElement("td");
      tdx.className = "x";
      const del = document.createElement("button");
      del.type = "button"; del.className = "del"; del.textContent = "🗑"; del.title = "Eliminar la fila";
      del.onclick = () => { r.gone = true; renderMeasureBody(); };
      tdx.appendChild(del); tr.appendChild(tdx);
      tb.appendChild(tr);
    });
    t.appendChild(tb);
    const wrap = document.createElement("div"); wrap.className = "heatwrap"; wrap.appendChild(t);
    box.appendChild(wrap);
    const tools = document.createElement("div");
    tools.className = "mtools";
    tools.innerHTML = `<button type="button" class="ghost" id="maddrow">＋ Fila</button><button type="button" class="ghost" id="maddcol">＋ Columna</button>`;
    box.appendChild(tools);
    $("maddrow").onclick = () => {
      const last = M.rows.filter((r) => !r.gone).pop();
      M.rows.push({ e: null, variety_id: last ? last.variety_id : "", data: {}, caption: "", gone: false });
      renderMeasureBody();
    };
    $("maddcol").onclick = () => {
      let n = M.cols.length + 1;
      while (M.cols.some((c) => c.name === `Columna ${n}`)) n++;
      M.cols.push({ orig: `Columna ${n}`, name: `Columna ${n}`, added: true });
      renderMeasureBody();
    };
  } else {
    const head = document.createElement("div");
    head.className = "photohead";
    head.innerHTML = `<span class="muted small">Arrastre fotos aquí o use «Subir fotos»; luego agregue la descripción y, si corresponde, la variedad.</span><span class="spacer"></span>
      <label class="ghost upload">＋ Subir fotos<input id="mfiles" type="file" accept="image/*" multiple hidden></label>`;
    box.appendChild(head);
    const grid = document.createElement("div");
    grid.className = "mimgs";
    const live = M.rows.filter((r) => !r.gone);
    if (!live.length) grid.innerHTML = `<p class="muted small">Sin fotos esta semana.</p>`;
    for (const r of live) {
      const card = document.createElement("div");
      card.className = "mimg";
      card.innerHTML = `<div class="ph"><em>Buscando…</em></div>`;
      const cap = document.createElement("input");
      cap.placeholder = "Descripción"; cap.value = r.caption;
      cap.oninput = () => { r.caption = cap.value; };
      const sel = varietySelect(r.variety_id);
      sel.onchange = () => { r.variety_id = sel.value; };
      const del = document.createElement("button");
      del.type = "button"; del.className = "del"; del.textContent = "Quitar del registro";
      del.onclick = () => { r.gone = true; renderMeasureBody(); };
      card.append(cap, sel, del);
      grid.appendChild(card);
      const ph = card.querySelector(".ph");
      photoUrl(r.e.path).then((u) => {
        if (!u) { ph.querySelector("em").textContent = S.photoErr.get(base(r.e.path)) === "missing" ? "No está en Drive" : "Error al bajar"; return; }
        ph.innerHTML = ""; ph.style.backgroundImage = `url(${u})`;
        ph.onclick = () => { $("vimg").src = u; $("viewer").showModal(); };
      }).catch(() => {});
    }
    box.appendChild(grid);
    box.classList.add("drop", "mdrop");
    dropZone(box, $("mfiles"), async (files) => {
      try { await addMeasureImages(files); renderMeasureBody(); render(); }
      catch (er) { $("mmsg").textContent = `No se pudieron subir: ${er.message}`; }
    }, { click: false, msg: "mmsg" });
  }
}

async function addMeasureImages(files) {
  const M = S.meas;
  const season = C.seasonOf(C.parseDate(S.week));
  const stem = `${S.week.replaceAll("-", "")}-${S.ws.code ? S.ws.code + "-" : ""}${C.slugify(M.m.name).slice(0, 40) || "medicion"}`;
  const taken = new Set([...C.rows(S.state, "measure_entries"), ...C.rows(S.state, "photos")].map((r) => base(r.path)).filter(Boolean));
  let dir = await weekFolderId();
  dir = await folder(M.m.name.replace(/\//g, "-").trim() || "Otras", dir, true);
  const changes = C.weekChange(S.state, S.week);
  let seq = 1;
  for (const f of files) {
    let name;
    do { name = `${stem}${seq > 1 ? "-" + seq : ""}.jpg`; seq++; } while (taken.has(name));
    taken.add(name);
    $("mmsg").textContent = `Subiendo ${name}…`;
    const blob = await resize(f);
    const id = await upload(dir, name, blob, "image/jpeg");
    S.photoIds.set(name, id);
    S.photoUrls.set(name, URL.createObjectURL(blob));
    const ch = C.entryChange({ measure_id: M.m.uid, week_id: S.week, path: `photos/T${season}/mediciones/${name}`, data: {} });
    changes.push(ch);
    M.rows.push({ e: { uid: ch.uid, path: ch.data.path, created_at: ch.data.created_at, data: {} }, variety_id: "", data: {}, caption: "", gone: false });
  }
  await send(changes);
  $("mmsg").textContent = `${files.length} foto(s) subida(s). Agregue la descripción y pulse Guardar.`;
}

function measureChanges() {
  const M = S.meas, m = M.m;
  const name = $("mname").value.trim();
  if (!name) throw new Error("Póngale un nombre a la medición.");
  const changes = [];
  const cols = M.cols.map((c) => ({ ...c, name: c.name.trim() }));
  if (m.kind === "table") {
    if (cols.some((c) => !c.name)) throw new Error("Hay una columna sin nombre.");
    if (new Set(cols.map((c) => c.name)).size !== cols.length) throw new Error("Hay dos columnas con el mismo nombre.");
  }
  const newCols = cols.map((c) => c.name);
  if (name !== m.name || JSON.stringify(newCols) !== JSON.stringify(m.columns)) changes.push(C.measureChange(m, { name, columns: newCols }));
  // Columnas renombradas o eliminadas: los datos se mueven en todas las semanas (= rename/delete_measure_column).
  const keep = new Map(cols.filter((c) => !c.added).map((c) => [c.orig, c.name]));
  const added = new Set(M.cols.filter((c) => c.added).map((c) => c.orig));
  const clean = (d) => Object.fromEntries(Object.entries(d || {}).map(([k, v]) => [k, String(v ?? "").trim()]).filter(([, v]) => v !== ""));
  const remap = (data) => {
    const out = {};
    for (const [k, v] of Object.entries(data || {})) {
      if (keep.has(k)) out[keep.get(k)] = v;
      else if (!m.columns.includes(k) && !added.has(k)) out[k] = v;   // claves ajenas a la planilla: se respetan
    }
    for (const c of cols) if (c.added && data && data[c.orig] !== undefined) out[c.name] = data[c.orig];
    return out;
  };
  const colsChanged = m.kind === "table" && m.columns.some((c) => keep.get(c) !== c);
  if (colsChanged) {
    for (const e of C.entriesFor(S.state, m.uid)) {
      if (e.week_id === S.week) continue;
      const data = remap(e.data);
      if (JSON.stringify(data) !== JSON.stringify(e.data)) changes.push(C.entryChange({ ...e, data }));
    }
  }
  let touched = false;
  for (const r of M.rows) {
    if (r.gone) { if (r.e) { changes.push(C.entryDelete(r.e.uid)); } continue; }
    const data = m.kind === "table" ? remap(clean(r.data)) : (r.e?.data || {});
    const entry = { ...(r.e || {}), measure_id: m.uid, week_id: S.week, variety_id: r.variety_id || null, caption: r.caption, data };
    if (!r.e) { if (C.entryFilled(entry)) { changes.push(C.entryChange(entry)); touched = true; } continue; }
    const same = (r.e.variety_id || "") === (r.variety_id || "") && (r.e.caption || "") === r.caption.trim()
      && JSON.stringify(m.kind === "table" ? clean(r.e.data) : r.e.data || {}) === JSON.stringify(data);
    if (!same) { changes.push(C.entryChange(entry)); touched = true; }
  }
  if (touched) changes.unshift(...C.weekChange(S.state, S.week));
  return changes;
}

async function deleteMeasure(all) {
  const m = S.meas.m;
  const nWeek = C.entriesFor(S.state, m.uid, S.week).length, nAll = C.entriesFor(S.state, m.uid).length;
  const text = all ? `¿Eliminar la medición «${m.name}» y sus ${nAll} registro(s) de todas las semanas?`
    : `¿Borrar los ${nWeek} registro(s) de «${m.name}» de ${C.weekTitle(S.week)}? La medición sigue para las demás semanas.`;
  if (!confirm(text + "\n\nTambién se borra en el celular al sincronizar. Las fotos quedan en Drive.")) return;
  try {
    await send(C.measureDeleteChanges(S.state, m.uid, all ? null : S.week));
    $("measure").close();
    status(all ? `Medición «${m.name}» eliminada` : `«${m.name}»: ${nWeek} registro(s) de esta semana eliminados`);
    render();
  } catch (e) { $("mmsg").textContent = `No se pudo eliminar: ${e.message}`; }
}

async function saveMeasure(ev) {
  ev.preventDefault();
  let changes;
  try { changes = measureChanges(); } catch (e) { $("mmsg").textContent = e.message; return; }
  if (!changes.length) { $("measure").close(); return; }
  $("msave").disabled = true;
  try {
    await send(changes);
    $("measure").close();
    render();
  } catch (e) {
    $("mmsg").textContent = `No se pudo guardar: ${e.message}`;
  } finally { $("msave").disabled = false; }
}

// ================================================================== ajustes
function isPredio() { return S.ws?.profile === "predio"; }

function renderSettings() {
  const predio = isPredio();
  $("vlabel").textContent = predio ? "SECTORES DEL PREDIO" : "VARIEDADES Y PARCELAS";
  $("vadd").textContent = predio ? "＋ Nuevo sector" : "＋ Nueva variedad";
  const show = $("vshowarch").checked;
  const box = $("vlist");
  box.innerHTML = "";
  const list = C.allVarieties(S.state).filter((v) => show || v.active !== 0);
  if (!list.length) box.innerHTML = `<p class="muted small">Aún no hay ${predio ? "sectores" : "variedades"}.</p>`;
  for (const v of list) {
    const b = document.createElement("button");
    b.className = "vrow" + (v.active === 0 ? " arch" : "");
    b.innerHTML = `<div><div class="place"></div><b></b><div class="tag"></div></div><span class="badge"></span>`;
    b.querySelector(".place").textContent = C.unitPlace(v);
    b.querySelector("b").textContent = C.unitMain(v);
    b.querySelector(".tag").textContent = [v.code && `Código ${v.code}`, v.treatment && `Tratamiento ${v.treatment} · repetición ${v.rep}`,
      v.notes].filter(Boolean).join(" · ");
    b.querySelector(".badge").textContent = v.active === 0 ? "ARCHIVADA" : "EDITAR";
    b.onclick = () => openVariety(v);
    box.appendChild(b);
  }
  // Ensayo de tratamientos (solo I+D)
  $("trialcard").hidden = predio;
  if (!predio) {
    const parcels = C.allVarieties(S.state).filter((v) => v.active !== 0 && v.treatment != null);
    const nt = C.setting(S.state, "trial_treatments", 0) || Math.max(0, ...parcels.map((v) => Number(v.treatment)));
    const nr = C.setting(S.state, "trial_reps", 0) || Math.max(0, ...parcels.map((v) => Number(v.rep)));
    if (document.activeElement !== $("tnum")) $("tnum").value = nt || "";
    if (document.activeElement !== $("trep")) $("trep").value = nr || "";
    const tl = $("tlist");
    tl.innerHTML = "";
    const meta = new Map(C.rows(S.state, "treatments").map((t) => [Number(t.num), t]));
    for (let t = 1; t <= nt; t++) {
      const m = meta.get(t) || {};
      const row = document.createElement("div");
      row.className = "trow";
      row.innerHTML = `<b>T${t}</b><input placeholder="Nombre (ej. Testigo)"><input placeholder="Descripción"><input placeholder="Variedad (opcional)"><button class="ghost">Guardar</button>`;
      const [n, d, cv] = row.querySelectorAll("input");
      n.value = m.name || ""; d.value = m.description || ""; cv.value = m.cultivar || "";
      row.querySelector("button").onclick = async () => {
        try {
          await send([C.treatmentChange(S.state, t, { name: n.value, description: d.value, cultivar: cv.value })]);
          $("tmsg").textContent = `T${t} guardado.`;
        } catch (e) { $("tmsg").textContent = e.message; }
      };
      tl.appendChild(row);
    }
  }
  // Primera semana
  const season = C.seasonOf(C.parseDate(S.week));
  $("fwseason").textContent = C.seasonTitle(season).replace("Temporada", "temporada");
  const sel = $("fweek");
  const fixed = C.setting(S.state, `first_week:${season}`);
  sel.innerHTML = `<option value="">Automática (la primera con registros)</option>`;
  for (let d = C.seasonFirstMonday(season), i = 0; i < 53 && C.seasonOf(d) === season; d = C.addDays(d, 7), i++) {
    const o = document.createElement("option");
    o.value = C.iso(d); o.textContent = `${C.weekTitle(C.iso(d))} · ${C.weekLabel(C.iso(d))}`;
    sel.appendChild(o);
  }
  sel.value = fixed || "";
  sel.dataset.season = season;
}

const RIEGO = [1, 2, 3, 4];
function openVariety(v) {
  S.editV = v || null;
  const predio = isPredio();
  $("vtitle").textContent = v ? (predio ? "Editar sector" : "Editar variedad") : (predio ? "Nuevo sector" : "Nueva variedad");
  const f = $("vfields");
  const field = (label, html, full = false) => `<label class="field${full ? " full" : ""}">${label}${html}</label>`;
  f.innerHTML = predio
    ? field("Variedad", `<input id="fcult" placeholder="Ej. Tulameen">`, true)
      + field("Equipo de riego", `<select id="firr"><option value="">—</option>${RIEGO.map((n) => `<option value="${n}">Equipo ${n}</option>`).join("")}</select>`)
      + field("Sector", `<input id="fsec" type="number" min="1" max="99">`)
      + field("Año de plantación", `<input id="fyear" type="number" min="1950" max="2100" placeholder="Opcional">`)
      + field("Código", `<input id="fcode" placeholder="Opcional">`)
    : field("Nombre", `<input id="fname" placeholder="Ej. Glen Ample">`, true)
      + field("Código", `<input id="fcode" placeholder="Opcional (va en el nombre de las fotos)">`)
      + field("Notas", `<input id="fnotes" placeholder="Opcional">`, true);
  const set = (id, val) => { if ($(id)) $(id).value = val ?? ""; };
  if (v) {
    set("fcult", v.cultivar); set("firr", v.irrigation); set("fsec", v.sector); set("fyear", v.plant_year);
    set("fcode", v.code); set("fname", v.name); set("fnotes", v.notes);
  }
  $("vmsg").textContent = "";
  $("varchive").hidden = !v;
  $("varchive").textContent = v && v.active === 0 ? "Restaurar" : "Archivar";
  $("vdialog").showModal();
}

async function saveVariety(ev) {
  ev.preventDefault();
  const v = S.editV;
  try {
    const ch = isPredio()
      ? C.unitChange(S.state, v, { cultivar: $("fcult").value, code: $("fcode").value.trim(), sector: $("fsec").value,
        irrigation: $("firr").value, plant_year: $("fyear").value })
      : C.varietyChange(S.state, v, { name: $("fname").value, code: $("fcode").value.trim(), notes: $("fnotes").value.trim() });
    await send([ch]);
    $("vdialog").close();
    render();
  } catch (e) { $("vmsg").textContent = e.message; }
}

async function toggleArchive() {
  const v = S.editV;
  if (!v) return;
  const archive = v.active !== 0;
  if (archive && !confirm(`¿Archivar «${C.unitMain(v)}»?\nDeja de aparecer en el muestreo; sus registros se conservan y se puede restaurar.`)) return;
  try {
    await send([C.varietyChange(S.state, v, { active: archive ? 0 : 1 })]);
    $("vdialog").close();
    render();
  } catch (e) { $("vmsg").textContent = e.message; }
}

async function applyTrial() {
  try {
    const r = C.trialSetup(S.state, $("tnum").value, $("trep").value);
    if (r.archived && !confirm(`Se archivarán ${r.archived} parcela(s) que sobran (sus registros se conservan). ¿Continuar?`)) return;
    await send(r.changes, r.settings);
    $("tmsg").textContent = `Listo: ${r.added} parcela(s) nuevas, ${r.restored} restaurada(s), ${r.archived} archivada(s).`;
    render();
  } catch (e) { $("tmsg").textContent = e.message; }
}

async function setFirstWeek() {
  const sel = $("fweek");
  try {
    await send([], C.firstWeekSettings(Number(sel.dataset.season), sel.value || null));
    status(sel.value ? `Primera semana: ${C.weekLabel(sel.value)}` : "Primera semana automática");
    render();
  } catch (e) { status(e.message); }
}

// ================================================================== matriz y plano
function renderMatrix() {
  const season = S.mSeason ?? C.seasonOf(C.parseDate(S.week));
  seasonOptions($("mseason"), season);
  const all = C.seasonWeeks(S.state, season);
  const months = [...new Set(all.map((w) => w.slice(0, 7)))];
  if (S.mMonth && !months.includes(S.mMonth)) S.mMonth = null;
  const mbox = $("mmonths");
  mbox.innerHTML = "";
  for (const m of [null, ...months]) {
    const b = document.createElement("button");
    b.textContent = m ? `${C.MESES[Number(m.slice(5)) - 1][0].toUpperCase()}${C.MESES[Number(m.slice(5)) - 1].slice(1)} ${m.slice(0, 4)}` : "Toda la temporada";
    b.className = S.mMonth === m ? "on" : "";
    b.onclick = () => { S.mMonth = m; renderMatrix(); };
    mbox.appendChild(b);
  }
  const weeks = S.mMonth ? all.filter((w) => w.startsWith(S.mMonth)) : all;
  const box = $("mheat");
  if (!weeks.length) { box.innerHTML = `<p class="muted">Sin registros en la ${C.seasonTitle(season)}.</p>`; }
  else {
    const all = C.matrix(S.state, weeks);
    const heat = all.filter((r) => r.pts.length);
    const t = document.createElement("table");
    t.className = "hm";
    t.innerHTML = `<thead><tr><th></th>${weeks.map((w) => `<th title="${C.weekLabel(w)}">S${C.isoWeek(C.parseDate(w))[0]}</th>`).join("")}</tr></thead>`;
    const tb = document.createElement("tbody");
    for (const r of heat) {
      const tr = document.createElement("tr");
      const n = document.createElement("td");
      n.className = "n"; n.textContent = C.unitMain(r.variety);
      if (C.unitPlace(r.variety)) { const sm = document.createElement("small"); sm.textContent = C.unitPlace(r.variety); n.appendChild(sm); }
      tr.appendChild(n);
      r.cells.forEach((c) => {
        const td = document.createElement("td");
        td.className = "c" + (c.code === null ? " na" : "");
        td.textContent = c.code === null ? "·" : C.codeStr(c.code);
        if (c.code !== null) { const [bg, fg] = C.seqColor(c.code); td.style.background = bg; td.style.color = fg; td.title = stageLabel(c.code); }
        td.onclick = () => { S.week = c.week; openDetail(r.variety); };
        tr.appendChild(td);
      });
      tb.appendChild(tr);
    }
    t.appendChild(tb);
    box.innerHTML = "";
    const wrap = document.createElement("div"); wrap.className = "heatwrap"; wrap.appendChild(t);
    box.appendChild(wrap);
    if (all.length > heat.length) box.insertAdjacentHTML("beforeend", `<p class="muted small">${all.length - heat.length} sin registros en estas semanas (no se muestran).</p>`);
  }
  renderMap(season);
  renderHeat(season);
}

// Mapa de calor de las fotos (= «Mapa de fotos» de la app).
async function renderHeat(season) {
  const week = S.hScope === "week" ? S.week : null;
  const { rows, missing } = C.photoLocations(S.state, season, week);
  const n = rows.reduce((a, r) => a + r.weight, 0);
  const where = week ? C.weekTitle(week) : C.seasonTitle(season);
  $("hinfo").textContent = rows.length
    ? `${where} · ${n} foto${n !== 1 ? "s" : ""} en ${rows.length} punto${rows.length !== 1 ? "s" : ""}${missing ? ` · ${missing} sin ubicación` : ""}`
    : `${where}: aún no hay fotos con ubicación. Al registrar, use «Mi ubicación», márquela en el mapa o suba fotos con GPS.`;
  const vs = new Map(C.rows(S.state, "varieties").map((v) => [v.uid, v]));
  // Sin fotos: encuadra el predio (su plano georreferenciado) o los registros con ubicación.
  let fallback = null;
  const plan = S.ws.profile === "predio" ? await mapFor(S.ws.code) : null;
  if (plan?.geo) {
    const g = plan.geo;
    fallback = [[g.y0 / g.ky, g.x0 / g.kx], [(plan.h + g.y0) / g.ky, (plan.w + g.x0) / g.kx]];
  } else {
    const all = C.rows(S.state, "observations").filter((o) => o.latitude != null && o.longitude != null);
    if (all.length) fallback = all.map((o) => [Number(o.latitude), Number(o.longitude)]);
  }
  const keepView = S.hKeep === true;
  S.hKeep = false;
  try {
    await photoHeat($("hmap"), rows, (p) => {
      const v = vs.get(p.variety_id) || {};
      const d = document.createElement("div");
      d.className = "hpop";
      d.innerHTML = `<b></b><div class="muted small"></div><div class="small"></div><button class="primary">Abrir registro</button>`;
      d.querySelector("b").textContent = C.unitMain(v);
      d.querySelector(".muted").textContent = C.unitPlace(v);
      d.querySelector(".small:not(.muted)").textContent = [C.weekLabel(p.week_id), `${p.weight} foto${p.weight !== 1 ? "s" : ""}`,
        p.bbch_code != null ? `BBCH ${C.codeStr(p.bbch_code)}` : ""].filter(Boolean).join(" · ");
      d.querySelector("button").onclick = () => { S.week = p.week_id; openDetail(v); };
      return d;
    }, { fallback, keepView });
  } catch (e) { $("hinfo").textContent = e.message; }
}

async function openPickMap() {
  const obs = C.observationFor(S.state, S.current.uid, S.week);
  let start = obs && obs.latitude != null ? [Number(obs.latitude), Number(obs.longitude)] : null;
  if (!start) {   // si no tiene, cerca de los otros registros con ubicación
    const any = C.rows(S.state, "observations").find((o) => o.latitude != null && o.longitude != null);
    if (any) start = [Number(any.latitude), Number(any.longitude)];
  }
  $("pmsg").textContent = "";
  $("pickmap").showModal();
  try { S.pickGet = await pickPoint($("pmap"), start); } catch (e) { $("pmsg").textContent = e.message; }
}

async function savePickMap(ev) {
  ev.preventDefault();
  const pt = S.pickGet && S.pickGet();
  if (!pt) { $("pmsg").textContent = "Toque el mapa para marcar el lugar."; return; }
  try { await setLocation(pt[0], pt[1], null, "mapa"); $("pickmap").close(); $("dmsg").textContent = "Ubicación guardada."; }
  catch (e) { $("pmsg").textContent = e.message; }
}

async function mapFor(code) {
  if (!S.maps.has(code)) {
    const r = await fetch(`maps/${code}.json`).catch(() => null);
    S.maps.set(code, r && r.ok ? await r.json() : null);
  }
  return S.maps.get(code);
}

async function renderMap(season) {
  const plan = S.ws.profile === "predio" ? await mapFor(S.ws.code) : null;
  $("mapcard").hidden = !plan;
  if (!plan) return;
  const vs = C.varieties(S.state);
  const weeks = new Set(C.seasonWeeks(S.state, season));
  const obs = C.rows(S.state, "observations").filter((o) => weeks.has(o.week_id) && o.bbch_code != null);
  const inSector = (s) => vs.filter((v) => Number(v.irrigation) === s.equipo && Number(v.sector) === s.sector);
  const hasData = (s) => inSector(s).some((v) => obs.some((o) => o.variety_id === v.uid));
  const chips = $("mapchips");
  chips.innerHTML = "";
  for (const eq of [0, ...new Set(plan.sectors.map((s) => s.equipo))].sort()) {
    const b = document.createElement("button");
    b.textContent = eq ? `Equipo ${eq}` : "Todo";
    b.className = S.mapEq === eq ? "on" : "";
    if (eq) b.style.borderColor = C.equipoDark(eq);
    b.onclick = () => { S.mapEq = eq; renderMap(season); };
    chips.appendChild(b);
  }
  if (plan.geo) {                 // sobre la imagen satelital (Leaflet)
    $("map").classList.add("leaf");
    try {
      await sectorMap($("map"), plan, { color: (s) => C.sectorColor(s.equipo, s.sector, false)[0], hasData,
        selected: S.mapSel, eq: S.mapEq, onSelect: (id) => { S.mapSel = id; renderMap(season); } });
    } catch {                     // sin conexión al mapa: el plano dibujado de siempre
      $("map")._sector = null;
      drawPlanSvg(plan, hasData, season);
    }
  } else drawPlanSvg(plan, hasData, season);
  sectorInfo(plan, obs, inSector);
}

function drawPlanSvg(plan, hasData, season) {
  const shown = plan.sectors.filter((s) => !S.mapEq || s.equipo === S.mapEq);
  let [x0, y0, x1, y1] = [Infinity, Infinity, -Infinity, -Infinity];
  for (const s of shown) for (const part of s.parts) for (let i = 0; i < part.length; i += 2) {
    x0 = Math.min(x0, part[i]); x1 = Math.max(x1, part[i]); y0 = Math.min(y0, part[i + 1]); y1 = Math.max(y1, part[i + 1]);
  }
  const pad = Math.max(x1 - x0, y1 - y0) * 0.03;
  const H = plan.h;
  const vb = `${x0 - pad} ${H - y1 - pad} ${x1 - x0 + 2 * pad} ${y1 - y0 + 2 * pad}`;
  let svg = `<svg viewBox="${vb}" xmlns="http://www.w3.org/2000/svg">`;
  for (const s of plan.sectors) {
    const [fill, light] = C.sectorColor(s.equipo, s.sector, !hasData(s));
    let big = s.parts[0];
    for (const part of s.parts) {
      if (part.length > big.length) big = part;
      const d = part.reduce((acc, v, i) => acc + (i % 2 ? `,${(H - v).toFixed(1)}` : `${i ? "L" : "M"}${v.toFixed(1)}`), "") + "Z";
      svg += `<path d="${d}" fill="${fill}" data-id="${s.id}" class="${S.mapSel === s.id ? "sel" : ""}"><title>${s.nombre}</title></path>`;
    }
    let cx = 0, cy = 0;
    for (let i = 0; i < big.length; i += 2) { cx += big[i]; cy += big[i + 1]; }
    cx /= big.length / 2; cy /= big.length / 2;
    const fs = Math.max(x1 - x0, y1 - y0) / 32;
    svg += `<text x="${cx}" y="${H - cy}" text-anchor="middle" dominant-baseline="middle" font-size="${fs}" fill="${light ? "#fff" : "#1B2A23"}">${s.sector}</text>`;
  }
  $("map").innerHTML = svg + "</svg>";
  $("map").classList.remove("leaf");
  $("map").querySelectorAll("path").forEach((p) => (p.onclick = () => { S.mapSel = p.dataset.id; renderMap(season); }));
}

function sectorInfo(plan, obs, inSector) {
  const sel = plan.sectors.find((s) => s.id === S.mapSel);
  const info = $("mapinfo");
  info.innerHTML = "";
  if (!sel) { info.innerHTML = `<p class="muted small">Toque un sector para ver sus variedades.</p>`; return; }
  const head = document.createElement("div");
  head.innerHTML = `<b>${sel.nombre}</b> <span class="muted small">· ${sel.ha ?? "?"} ha · ${sel.hileras ?? "?"} hileras · ${(sel.variedades || []).join(", ")}</span>`;
  info.appendChild(head);
  const units = inSector(sel);
  if (!units.length) info.insertAdjacentHTML("beforeend", `<p class="muted small">Sin registros creados en este sector (se crean en Ajustes › Nuevo sector).</p>`);
  for (const v of units) {
    const mine = obs.filter((o) => o.variety_id === v.uid).sort((a, b) => a.week_id.localeCompare(b.week_id));
    const last = mine[mine.length - 1];
    const d = document.createElement("div");
    d.className = "unit";
    d.innerHTML = `<span><b></b><br><span class="muted small"></span></span><span class="badge bbch">BBCH ${last ? C.codeStr(last.bbch_code) : "—"}</span>`;
    d.querySelector("b").textContent = C.unitMain(v);
    d.querySelector(".muted").textContent = last ? `Último registro: ${C.weekTitle(last.week_id)}` : "Sin registros esta temporada";
    d.onclick = () => { if (last) S.week = last.week_id; openDetail(v); };
    info.appendChild(d);
  }
}

// ================================================================== informes
function renderReports() {
  const season = S.rSeason ?? C.seasonOf(C.parseDate(S.week));
  seasonOptions($("rseason"), season);
  const weeks = C.seasonWeeks(S.state, season);
  const fill = (sel, items) => {
    const keep = sel.value; sel.innerHTML = "";
    for (const [v, t] of items) { const o = document.createElement("option"); o.value = v; o.textContent = t; sel.appendChild(o); }
    if ([...sel.options].some((o) => o.value === keep)) sel.value = keep;
  };
  fill($("rweek"), [...weeks].reverse().map((w) => [w, `${C.weekTitle(w)} · ${C.weekLabel(w)}`]));
  if (weeks.includes(S.week) && !$("rweek").dataset.touched) $("rweek").value = S.week;
  const wopts = weeks.map((w) => [w, `${C.weekTitle(w)} · ${C.weekLabel(w)}`]);
  const hadFrom = $("rfrom").value;
  fill($("rfrom"), wopts); fill($("rto"), wopts);
  if (!hadFrom && weeks.length) { $("rfrom").value = weeks[Math.max(0, weeks.length - 4)]; $("rto").value = weeks[weeks.length - 1]; }
  $("rxls").hidden = !C.measures(S.state).length;
  fill($("rmonth"), [...new Set(weeks.map((w) => w.slice(0, 7)))].map((m) => [m, `${C.MESES[Number(m.slice(5)) - 1]} ${m.slice(0, 4)}`]));
  $("rtrt").hidden = !C.treatments(S.state).length;
  fill($("rvar"), C.varieties(S.state).map((v) => [v.uid, C.unitMain(v) + (C.unitPlace(v) ? ` · ${C.unitPlace(v)}` : "")]));
}

async function runReport(kind) {
  const season = Number($("rseason").value);
  const win = window.open("", "_blank");       // en el mismo clic: así no lo bloquea el navegador
  if (win) win.document.write("<p style='font:16px system-ui;padding:24px'>Preparando informe…</p>");
  const rep = makeReports({ state: S.state, ws: S.ws, bbch: S.bbch, photoUrl, win,
    progress: (t) => { $("rmsg").textContent = t; } });
  try {
    if (kind === "weekly") await rep.weekly($("rweek").value);
    else if (kind === "matrix") await rep.matrix(season, C.seasonWeeks(S.state, season), "Matriz comparativa inter-varietal");
    else if (kind === "month") {
      const m = $("rmonth").value;
      await rep.matrix(season, C.seasonWeeks(S.state, season).filter((w) => w.startsWith(m)),
        `Reporte mensual · ${C.MESES[Number(m.slice(5)) - 1]} ${m.slice(0, 4)}`, true);
    } else if (kind === "variety") {
      await rep.variety(C.varieties(S.state).find((v) => v.uid === $("rvar").value), season);
    } else if (kind === "treatments") await rep.treatments(season);
    else if (kind === "period") {
      const [a, b] = [$("rfrom").value, $("rto").value].sort();
      await rep.matrix(season, C.seasonWeeks(S.state, season).filter((w) => w >= a && w <= b),
        `Evolución · Semanas ${C.isoWeek(C.parseDate(a))[0]}–${C.isoWeek(C.parseDate(b))[0]}`, true);
    }
    $("rmsg").textContent = "Informe listo (pestaña nueva).";
  } catch (e) {
    $("rmsg").textContent = e.message;
    if (win) win.close();
  }
}

async function photoBlob(path) {
  const u = await photoUrl(path);
  return u ? (await fetch(u)).blob() : null;
}

async function runPdf(kind) {
  const season = Number($("rseason").value);
  const arg = { weekly: $("rweek").value, month: $("rmonth").value, variety: $("rvar").value,
    period: `${$("rfrom").value}|${$("rto").value}` }[kind] || "";
  const btns = document.querySelectorAll("[data-pdf]");
  btns.forEach((b) => (b.disabled = true));
  try {
    const { name, blob } = await makePdf({ ws: S.ws, bundles: S.bundles, photoBlob,
      progress: (t) => { $("rmsg").textContent = t; } }, kind, arg, season);
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 60000);
    $("rmsg").textContent = `${name.endsWith(".xlsx") ? "Excel" : "PDF"} listo: ${name} (${Math.max(1, Math.round(blob.size / 1024))} KB, en Descargas).`;
  } catch (e) {
    console.error(e);
    $("rmsg").textContent = `No se pudo generar el PDF: ${String(e.message || e).split("\n").filter(Boolean).pop()}`;
  } finally { btns.forEach((b) => (b.disabled = false)); }
}

async function start() {
  $("login").hidden = true;
  $("app").hidden = false;
  ["sync", "logout", "ws"].forEach((id) => ($(id).hidden = false));
  rememberUser();
  setInterval(() => S.wsFolder && pull().then((n) => n && render()).catch(() => {}), 5 * 60 * 1000);
  let cached = null;
  try { cached = JSON.parse(store.get("pr_wslist") || "null"); } catch { /* sin caché */ }
  if (cached?.length) {                    // se muestra al instante lo guardado; Drive, en segundo plano
    S.workspaces = cached;
    fillWorkspaces();
    await openCached($("ws").value);
    render();
    status("Sincronizando…");
    try {
      await loadWorkspaces();
      store.set("pr_wslist", JSON.stringify(S.workspaces));
      fillWorkspaces();
      if (S.workspaces.some((w) => w.code === S.ws.code)) {
        S.ws = S.workspaces.find((w) => w.code === S.ws.code);
        S.wsFolder = await folder(S.ws.code, S.sync);
        if (await pull()) render();
      } else { await loadWorkspace($("ws").value); render(); }
    } catch (e) { status(e.message); }
    return;
  }
  status("Cargando…");
  await loadWorkspaces();
  store.set("pr_wslist", JSON.stringify(S.workspaces));
  fillWorkspaces();
  await loadWorkspace($("ws").value);
  render();
}

// I+D y Predio separados (como el menú de la app): botones arriba y la lista solo del perfil.
const PROFILE_TABS = [["id", "I+D · Ensayos"], ["predio", "Predios"], ["", "Otros"]];
const profileOf = (w) => (PROFILES[w.profile] ? w.profile : "");

function fillWorkspaces() {
  const profs = PROFILE_TABS.filter(([p]) => S.workspaces.some((w) => profileOf(w) === p));
  const saved = S.workspaces.find((w) => w.code === store.get("pr_ws"));
  const cur = S.ws ? profileOf(S.ws) : saved ? profileOf(saved)
    : store.get("pr_prof") ?? (S.workspaces[0] ? profileOf(S.workspaces[0]) : "");
  const prof = profs.some(([p]) => p === cur) ? cur : profs[0]?.[0] ?? "";
  store.set("pr_prof", prof);
  const seg = $("profiles");
  seg.innerHTML = "";
  seg.hidden = profs.length < 2;
  for (const [p, label] of profs) {
    const b = document.createElement("button");
    b.textContent = `${label} (${S.workspaces.filter((w) => profileOf(w) === p).length})`;
    b.className = p === prof ? "on" : "";
    b.onclick = () => { if (p !== prof) switchProfile(p); };
    seg.appendChild(b);
  }
  const mine = S.workspaces.filter((w) => profileOf(w) === prof);
  const sel = $("ws");
  const keep = S.ws?.code || store.get(`pr_ws_${prof}`) || store.get("pr_ws");
  sel.innerHTML = "";
  for (const w of mine) {
    const o = document.createElement("option");
    o.value = w.code; o.textContent = `${w.name} (${w.code})`;
    sel.appendChild(o);
  }
  sel.value = mine.some((w) => w.code === keep) ? keep : mine[0]?.code;
}

function openWs(code) {
  return (S.sync ? loadWorkspace(code) : openCached(code)).then(render).catch((er) => status(er.message));
}

function switchProfile(p) {                // al último ensayo/predio usado en ese perfil
  const mine = S.workspaces.filter((w) => profileOf(w) === p);
  const last = store.get(`pr_ws_${p}`);
  openWs((mine.find((w) => w.code === last) || mine[0]).code);
}

async function boot() {
  S.device = device();
  S.bbch = await (await fetch("bbch.json")).json();
  $("signin").onclick = async () => {
    $("login-msg").textContent = "";
    try { await signIn(""); await start(); } catch (e) { $("login-msg").textContent = e.message; $("login").hidden = false; $("app").hidden = true; }
  };
  $("relogin").onclick = () => signIn("").then(() => pull()).then(render).catch((e) => status(e.message));
  $("logout").onclick = () => {
    if (S.token && window.google?.accounts?.oauth2) google.accounts.oauth2.revoke(S.token, () => {});
    S.token = null;
    for (const k of ["pr_token", "pr_email", "pr_wslist", "pr_ws"]) store.set(k, null);
    idb.then((db) => { db?.close(); indexedDB.deleteDatabase("phenorubus"); }).finally(() => location.reload());   // en un PC compartido no quedan datos
  };
  $("sync").onclick = () => pull().then(render).catch((e) => status(e.message));
  $("ws").onchange = (e) => openWs(e.target.value);
  document.querySelectorAll(".tabs button").forEach((b) => (b.onclick = () => {
    S.tab = b.dataset.tab;
    document.querySelectorAll(".tabs button").forEach((x) => x.classList.toggle("on", x === b));
    for (const t of ["sampling", "matrix", "notebook", "reports", "settings"]) $(`tab-${t}`).hidden = t !== S.tab;
    if (S.tab === "reports") warmPdf().catch(() => {});     // el generador de PDF se precarga
    render();
  }));
  $("season").onchange = (e) => { goSeason(Number(e.target.value)); render(); };
  $("mseason").onchange = (e) => { S.mSeason = Number(e.target.value); S.mMonth = null; renderMatrix(); };
  $("rseason").onchange = (e) => { S.rSeason = Number(e.target.value); renderReports(); };
  $("rweek").onchange = (e) => { e.target.dataset.touched = "1"; };
  document.querySelectorAll("[data-rep]").forEach((b) => (b.onclick = () => runReport(b.dataset.rep)));
  document.querySelectorAll("[data-pdf]").forEach((b) => (b.onclick = () => runPdf(b.dataset.pdf)));
  $("prev").onclick = () => shift(-7);
  $("next").onclick = () => shift(7);
  $("today").onclick = () => { S.week = C.iso(C.mondayOf(C.todayUTC())); render(); };
  NB.init({ S, send, photoUrl, resize, uploadPhoto: uploadNotePhoto });
  $("trainfab").hidden = !TR.enabled();      // se activa abriendo la web con «#lab» una vez
  TR.init({ S, photoUrl, loadLabels, saveLabels, allStates, email: () => store.get("pr_email") });
  $("dsave").onclick = saveDetail;
  $("msave").onclick = saveMeasure;
  $("vadd").onclick = () => openVariety(null);
  $("vsave").onclick = saveVariety;
  $("varchive").onclick = toggleArchive;
  $("vshowarch").onchange = renderSettings;
  $("tapply").onclick = applyTrial;
  $("fweek").onchange = setFirstWeek;
  $("mdelweek").onclick = () => deleteMeasure(false);
  $("mdelall").onclick = () => deleteMeasure(true);
  $("skipweek").onchange = (e) => setSkipped(e.target.checked);
  $("clearweek").onclick = clearWeek;
  $("ncreate").onclick = createMeasure;
  $("dseldel").onclick = () => deletePhotos([...S.photoSel]);
  $("dgps").onclick = locateMe;
  $("dmap").onclick = openPickMap;
  $("psave").onclick = savePickMap;
  document.querySelectorAll("#hscope button").forEach((b) => (b.onclick = () => {
    S.hScope = b.dataset.scope;
    S.hKeep = true;                       // misma vista al cambiar temporada ↔ semana
    document.querySelectorAll("#hscope button").forEach((x) => x.classList.toggle("on", x === b));
    renderHeat(S.mSeason ?? C.seasonOf(C.parseDate(S.week)));
  }));
  $("dlocdel").onclick = () => setLocation(null, null, null, null).then(() => { $("dmsg").textContent = "Ubicación quitada."; });
  $("dselnone").onclick = () => { S.photoSel.clear(); renderPhotos(S.current); };
  document.querySelectorAll("#detail .drop").forEach((z) =>
    dropZone(z, z.querySelector("input"), (files) => uploadTo(z.dataset.kind, files)));
  // Soltar una foto fuera de las casillas no debe abrirla en el navegador (se perdería la página).
  window.addEventListener("dragover", (e) => e.preventDefault());
  window.addEventListener("drop", (e) => e.preventDefault());
  loginLabel();
  if (window.__PR_TOKEN__) { await signIn(); await start(); return; }
  const saved = savedToken();
  if (saved) {                              // sesión aún vigente: entra directo
    S.token = saved;
    try { await start(); } catch (e) {
      $("login-msg").textContent = e.message; $("login").hidden = false; $("app").hidden = true;
      ["sync", "logout", "ws"].forEach((id) => ($(id).hidden = true));
    }
  }
}

boot().catch((e) => { $("login-msg").textContent = e.message; });
