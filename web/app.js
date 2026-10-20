// PhenoRubus Web: inicio de sesión con Google, lectura/escritura de los paquetes de
// sincronización en Drive (los mismos de la app) y pantallas de muestreo semanal.
import * as C from "./core.js";
import { CLIENT_ID } from "./config.js";

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
  state: C.emptyState(), week: C.iso(C.mondayOf(C.todayUTC())),
  folders: new Map(), photoUrls: new Map(), photoIds: new Map(), photoErr: new Map(), current: null,
};

// ================================================================== Google
function device() {
  let d = localStorage.getItem("pr_device");
  if (!d) { d = "web" + C.newUid().slice(0, 9); localStorage.setItem("pr_device", d); }
  return d;
}

function signIn(prompt = "") {
  return new Promise((resolve, reject) => {
    if (window.__PR_TOKEN__) { S.token = window.__PR_TOKEN__; return resolve(S.token); }   // pruebas
    if (!CLIENT_ID) return reject(new Error("Falta configurar el ID de cliente de Google (web/config.js)."));
    if (!window.google?.accounts?.oauth2) return reject(new Error("No se pudo cargar el inicio de sesión de Google."));
    S.tokenClient ||= google.accounts.oauth2.initTokenClient({ client_id: CLIENT_ID, scope: SCOPE, callback: () => {} });
    S.tokenClient.callback = (r) => r.error ? reject(new Error(r.error_description || r.error)) : resolve(S.token = r.access_token);
    S.tokenClient.error_callback = (e) => reject(new Error(e.message || e.type || "inicio de sesión cancelado"));
    S.tokenClient.requestAccessToken({ prompt });
  });
}

async function api(method, url, body, ctype, raw = false) {
  for (let attempt = 0; attempt < 2; attempt++) {
    const headers = { Authorization: `Bearer ${S.token}` };
    if (ctype) headers["Content-Type"] = ctype;
    const r = await fetch(url, { method, headers, body });
    if (r.status === 401 && attempt === 0) { await signIn(""); continue; }
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

async function download(id) {
  return api("GET", `${API}/${id}?alt=media`, undefined, undefined, true);
}

// ================================================================== caché (IndexedDB)
const idb = new Promise((resolve) => {
  try {
    const r = indexedDB.open("phenorubus", 1);
    r.onupgradeneeded = () => r.result.createObjectStore("bundles");
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => resolve(null);
  } catch { resolve(null); }
});
async function cacheGet(key) {
  const db = await idb; if (!db) return null;
  return new Promise((res) => {
    const r = db.transaction("bundles").objectStore("bundles").get(key);
    r.onsuccess = () => res(r.result || null); r.onerror = () => res(null);
  });
}
async function cachePut(key, val) {
  const db = await idb; if (!db) return;
  db.transaction("bundles", "readwrite").objectStore("bundles").put(val, key);
}

// ================================================================== sincronización
function status(t) { $("status").textContent = t || ""; }

async function loadWorkspaces() {
  S.root = await folder(ROOT, null, false);
  S.sync = S.root && await folder(SYNC, S.root, false);
  if (!S.sync) throw new Error("Aún no hay datos en Drive: abra la app del celular con Google Drive conectado y pulse «Sincronizar».");
  const files = await list(`'${S.sync}' in parents and trashed=false`);
  const byCode = new Map();
  for (const f of files) {
    if (f.mimeType === FOLDER) continue;
    if (!/^ensayos-.*\.json$/.test(f.name)) continue;
    const res = await download(f.id);
    for (const ws of await res.json()) byCode.set(ws.code, ws);
  }
  for (const f of files) if (f.mimeType === FOLDER && !byCode.has(f.name)) byCode.set(f.name, { code: f.name, name: f.name, profile: "" });
  S.workspaces = [...byCode.values()];
  for (const f of files) if (f.mimeType === FOLDER) S.folders.set(`${S.sync}/${f.name}`, f.id);
}

async function loadWorkspace(code) {
  S.ws = S.workspaces.find((w) => w.code === code) || S.workspaces[0];
  localStorage.setItem("pr_ws", S.ws.code);
  S.state = C.emptyState();
  S.photoIds.clear();
  S.wsFolder = await folder(S.ws.code, S.sync);
  await pull();
}

async function pull() {
  status("Sincronizando…");
  const files = (await list(`'${S.wsFolder}' in parents and trashed=false`))
    .filter((f) => f.name.endsWith(".json")).sort((a, b) => a.name.localeCompare(b.name));
  let n = 0;
  for (const f of files) {
    if (S.state.seen.has(f.name)) continue;
    const key = `${S.ws.code}/${f.name}`;
    let bundle = await cacheGet(key);
    if (!bundle) {
      bundle = await (await download(f.id)).json();
      cachePut(key, bundle);
    }
    n += C.applyBundle(S.state, f.name, bundle);
  }
  await pushPending();
  status(`Sincronizado ${new Date().toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" })}`);
  return n;
}

function pending() { return JSON.parse(localStorage.getItem(`pr_pending_${S.ws.code}`) || "[]"); }
function setPending(list_) { localStorage.setItem(`pr_pending_${S.ws.code}`, JSON.stringify(list_)); }

async function send(changes) {
  const name = `${C.stamp()}-${S.device}.json`;
  const bundle = C.bundle(S.device, S.ws.code, changes);
  C.applyBundle(S.state, name, bundle);            // se ve al instante
  setPending([...pending(), { name, bundle }]);
  await pushPending();
}

async function pushPending() {
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

async function photoUrl(path) {
  const name = base(path);
  if (S.photoUrls.has(name)) return S.photoUrls.get(name);
  let id = S.photoIds.get(name);
  if (id === undefined) {
    const found = await list(`name='${q(name)}' and trashed=false`, "files(id,name)");
    id = found[0]?.id || null;
    S.photoIds.set(name, id);
  }
  if (!id) { S.photoErr.set(name, "missing"); return null; }   // aún no está en Drive
  try {
    const url = URL.createObjectURL(await (await download(id)).blob());
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

async function weekFolderId() {
  const prefix = `${PROFILES[S.ws.profile] || "Otros"}/${(S.ws.name || S.ws.code).replace(/\//g, "-").trim()}`;
  let parent = await folder(ROOT, null, true);
  for (const part of `${prefix}/${C.weekFolder(S.week)}`.split("/")) parent = await folder(part, parent, true);
  return parent;
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
  for (const f of files) {
    let seq = 1, name;
    do { name = `${C.photoBasename(v, S.week, kind, seq++, S.ws.code)}.jpg`; } while (taken.has(name));
    taken.add(name);
    $("dmsg").textContent = `Subiendo ${name}…`;
    const blob = await resize(f);
    const id = await upload(dir, name, blob, "image/jpeg");
    S.photoIds.set(name, id);
    S.photoUrls.set(name, URL.createObjectURL(blob));
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

function renderWeek() {
  const season = C.seasonOf(C.parseDate(S.week));
  $("season").textContent = C.seasonTitle(season);
  $("kicker").textContent = C.weekTitle(S.week).toUpperCase();
  $("wtitle").textContent = C.weekLabel(S.week);
  $("wrange").textContent = C.weekRange(S.week);
}

function render() {
  renderWeek();
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
  $("ptext").textContent = `${done}/${vs.length} completas`;
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

function renderPhotos(v) {
  const obs = C.observationFor(S.state, v.uid, S.week);
  const box = $("dphotos");
  box.innerHTML = "";
  const photos = obs ? C.photosFor(S.state, obs.uid) : [];
  if (!photos.length) box.innerHTML = `<p class="muted small">Sin fotos esta semana.</p>`;
  const jobs = photos.map((p) => {
    const d = document.createElement("div");
    d.className = "ph pending";
    d.innerHTML = `<span>${p.kind === "canopy" ? "Canopia" : "Detalle"}${p.is_primary ? " ★" : ""}</span><em>Buscando…</em>`;
    box.appendChild(d);
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
      d.onclick = () => { $("vimg").src = u; $("viewer").showModal(); };
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

function openDetail(v) {
  S.current = v;
  const obs = C.observationFor(S.state, v.uid, S.week);
  $("dplace").textContent = C.unitPlace(v);
  $("dname").textContent = C.unitMain(v);
  $("dweek").textContent = `${C.weekTitle(S.week)} · ${C.weekLabel(S.week)}`;
  fillBbch($("dbbch"), obs?.bbch_code ?? null);
  $("dnotes").value = obs?.notes || "";
  $("dmsg").textContent = "";
  renderPhotos(v);
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

async function start() {
  $("login").hidden = true;
  $("app").hidden = false;
  ["sync", "logout", "ws"].forEach((id) => ($(id).hidden = false));
  status("Cargando…");
  await loadWorkspaces();
  const sel = $("ws");
  sel.innerHTML = "";
  for (const w of S.workspaces) {
    const o = document.createElement("option");
    o.value = w.code; o.textContent = `${PROFILES[w.profile] ? PROFILES[w.profile] + " · " : ""}${w.name} (${w.code})`;
    sel.appendChild(o);
  }
  const saved = localStorage.getItem("pr_ws");
  sel.value = S.workspaces.some((w) => w.code === saved) ? saved : S.workspaces[0]?.code;
  await loadWorkspace(sel.value);
  render();
  setInterval(() => pull().then((n) => n && render()).catch(() => {}), 5 * 60 * 1000);
}

async function boot() {
  S.device = device();
  S.bbch = await (await fetch("bbch.json")).json();
  $("signin").onclick = async () => {
    $("login-msg").textContent = "";
    try { await signIn("consent"); await start(); } catch (e) { $("login-msg").textContent = e.message; $("login").hidden = false; $("app").hidden = true; }
  };
  $("logout").onclick = () => {
    if (S.token && window.google?.accounts?.oauth2) google.accounts.oauth2.revoke(S.token, () => {});
    S.token = null; location.reload();
  };
  $("sync").onclick = () => pull().then(render).catch((e) => status(e.message));
  $("ws").onchange = (e) => loadWorkspace(e.target.value).then(render).catch((er) => status(er.message));
  $("prev").onclick = () => shift(-7);
  $("next").onclick = () => shift(7);
  $("today").onclick = () => { S.week = C.iso(C.mondayOf(C.todayUTC())); render(); };
  $("dsave").onclick = saveDetail;
  $("dfiles").onchange = async (e) => {
    const files = [...e.target.files];
    e.target.value = "";
    if (!files.length) return;
    try { await addPhotos(S.current, files, $("dkind").value); renderPhotos(S.current); render(); }
    catch (er) { $("dmsg").textContent = `No se pudieron subir: ${er.message}`; }
  };
  if (window.__PR_TOKEN__) { await signIn(); await start(); }
}

boot().catch((e) => { $("login-msg").textContent = e.message; });
