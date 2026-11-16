// AeonCrop Web · visor de AeonScout: el banco de imágenes de plagas, malezas y enfermedades
// que la app sube a «AeonCrop/AeonScout/<Plagas|Malezas|Enfermedades>/<especie>/<estadio>/»
// (las no identificadas en «…/No identificadas/NI-003/…») y «registro.csv» (= scout.py).
// Las capturas se hacen en la app; aquí además se identifican con IA (scout_ai.js), con la
// ficha de la guía y la guía ilustrada de cómo sacar las fotos.
import * as AI from "./scout_ai.js";
const FOLDER = "application/vnd.google-apps.folder";
const DRIVE_FOLDER = "AeonScout", UNIDENTIFIED = "No identificadas";
export const SECTIONS = [          // (= scout.SECTIONS) clave, carpeta en Drive, color
  ["plagas", "Plagas", "#A0441E"],
  ["malezas", "Malezas", "#2E6B34"],
  ["enfermedades", "Enfermedades", "#6E4A9E"],
];
const $ = (id) => document.getElementById(id);

let X = null;                       // funciones de Drive de app.js
let top = null;                     // carpeta AeonScout
let section = "plagas";
const tree = new Map();             // sección -> [{name, unidentified, stages: [{name, photos: [{id, name}]}]}]
const info = new Map();             // nombre de foto -> fila de registro.csv
const urls = new Map();             // id -> URL de la foto (blob)
let observer = null;

// ------------------------------------------------------------------ lógica pura (probada)
// Planilla «registro.csv» de la app: separada por «;», con BOM y comillas de CSV.
export function parseCsv(text) {
  text = text.replace(/^﻿/, "");
  const rows = [];
  let row = [], cell = "", quoted = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"' && text[i + 1] === '"') { cell += '"'; i++; } else if (ch === '"') quoted = false; else cell += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ";") { row.push(cell); cell = ""; } else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && text[i + 1] === "\n") i++;
      row.push(cell); cell = "";
      if (row.some((c) => c !== "")) rows.push(row);
      row = [];
    } else cell += ch;
  }
  row.push(cell);
  if (row.some((c) => c !== "")) rows.push(row);
  if (!rows.length) return [];
  const head = rows.shift();
  return rows.map((r) => Object.fromEntries(head.map((h, i) => [h, r[i] ?? ""])));
}

// Texto corto de una captura: «12-10-2026 · Maleza en Nuevas variedades (NV) · sector 3».
export function describe(r) {
  if (!r) return "";
  const date = (r.Fecha || "").slice(0, 10).split("-").reverse().join("-");
  const where = [r.Lugar && `${r.Lugar}${r["Código"] ? ` (${r["Código"]})` : ""}`, r.Sector && `sector ${r.Sector}`]
    .filter(Boolean).join(" · ");
  return [date, r.Cultivo, where, r["Órgano"], r.Abundancia && `abundancia ${r.Abundancia}`, r.Vista, r.Notas]
    .filter(Boolean).join(" · ");
}

// ------------------------------------------------------------------ Drive
async function kids(id) {
  return X.list(`'${id}' in parents and trashed=false`, "files(id,name,mimeType)");
}

async function loadSection(key, fresh = false) {
  if (tree.has(key) && !fresh) return tree.get(key);
  const sec = SECTIONS.find((s) => s[0] === key);
  const dir = top && await X.folder(sec[1], top, false);
  const out = [];
  if (dir) {
    const species = (await kids(dir)).filter((f) => f.mimeType === FOLDER);
    const groups = [];
    for (const sp of species) {
      if (sp.name === UNIDENTIFIED) {
        for (const ni of (await kids(sp.id)).filter((f) => f.mimeType === FOLDER)) groups.push([ni, true]);
      } else groups.push([sp, false]);
    }
    await pool(groups, 4, async ([sp, unidentified]) => {
      const item = { name: sp.name, unidentified, stages: [] };
      const loose = [];
      for (const f of await kids(sp.id)) {
        if (f.mimeType === FOLDER) {
          const photos = (await kids(f.id)).filter((p) => (p.mimeType || "").startsWith("image/"));
          if (photos.length) item.stages.push({ name: f.name, photos });
        } else if ((f.mimeType || "").startsWith("image/")) loose.push(f);
      }
      if (loose.length) item.stages.push({ name: "Sin estadio", photos: loose });
      if (item.stages.length) out.push(item);
    });
  }
  out.sort((a, b) => a.unidentified - b.unidentified || a.name.localeCompare(b.name, "es"));
  tree.set(key, out);
  return out;
}

async function loadCsv() {
  const f = (await X.list(`name='registro.csv' and '${top}' in parents and trashed=false`, "files(id,name)"))[0];
  if (!f) return;
  const text = await (await X.download(f.id)).text();
  info.clear();
  for (const r of parseCsv(text)) if (r.Foto) info.set(r.Foto, r);
}

async function pool(items, n, fn) {
  let next = 0;
  const run = async () => { while (next < items.length) { const i = next++; await fn(items[i], i); } };
  await Promise.all(Array.from({ length: Math.min(n, items.length) }, run));
}

async function photoUrl(p) {
  if (urls.has(p.id)) return urls.get(p.id);
  const key = `scout:${p.id}`;
  let blob = await X.cacheGet(key, "photos");
  if (!blob) { blob = await (await X.download(p.id)).blob(); X.cachePut(key, blob, "photos"); }
  const u = URL.createObjectURL(blob);
  urls.set(p.id, u);
  return u;
}

// ------------------------------------------------------------------ pantalla
export async function open(ctx) {
  X = ctx;
  $("screload").onclick = () => { tree.clear(); render(true); };
  $("skeys").onclick = openKeys;
  $("sguidebtn").onclick = () => openGuide(section);
  $("snew").onchange = (e) => { const f = [...e.target.files]; e.target.value = ""; if (f.length) identifyNew(f); };
  AI.guide().catch(() => {});
  observer ||= new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (!e.isIntersecting) continue;
      const el = e.target;
      observer.unobserve(el);
      photoUrl(JSON.parse(el.dataset.p)).then((u) => { el.style.backgroundImage = `url(${u})`; el.classList.add("ok"); })
        .catch(() => el.classList.add("err"));
    }
  }, { rootMargin: "200px" });
  try {
    if (!top) {
      const t = await ctx.root();
      top = t && await X.folder(DRIVE_FOLDER, t, false);
    }
    if (!top) {
      $("ssections").innerHTML = "";
      $("sspecies").innerHTML = "";
      $("smsg").textContent = "Aún no hay capturas de AeonScout en Drive: tómelas con la app (botón AeonScout) y respalde.";
      return;
    }
    loadCsv().catch(() => {});
    await render();
  } catch (e) { $("smsg").textContent = e.message; }
}

async function render(fresh = false) {
  await AI.guide().catch(() => {});
  const nav = $("ssections");
  nav.innerHTML = "";
  for (const [key, name, color] of SECTIONS) {
    const b = document.createElement("button");
    b.className = key === section ? "on" : "";
    b.style.setProperty("--sec", color);
    b.innerHTML = `<img src="scout/scout_${key}.png" alt=""><span></span>`;
    b.querySelector("span").textContent = name + (tree.has(key) ? ` (${count(tree.get(key))})` : "");
    b.onclick = () => { section = key; render(); };
    nav.appendChild(b);
  }
  const box = $("sspecies");
  box.innerHTML = "";
  $("smsg").textContent = "Leyendo Drive…";
  const list = await loadSection(section, fresh);
  nav.querySelector("button.on span").textContent = `${SECTIONS.find((s) => s[0] === section)[1]} (${count(list)})`;
  $("smsg").textContent = list.length ? `${list.length} especie(s) · ${count(list)} foto(s)` : "Sin fotos en esta sección.";
  for (const sp of list) {
    const card = document.createElement("section");
    card.className = "card scoutsp";
    const h = document.createElement("div");
    h.className = "scouth";
    h.innerHTML = `<b></b><span class="grow"></span><span class="badge"></span>`;
    h.querySelector("b").textContent = sp.unidentified ? `${sp.name} · no identificada` : sp.name;
    const g = !sp.unidentified && AI.loaded() ? AI.find(section, sp.name) : null;
    if (g) {
      const fb = document.createElement("button");
      fb.className = "ghost small";
      fb.textContent = "📖 Ficha";
      fb.onclick = () => showFicha(g);
      h.insertBefore(fb, h.querySelector(".badge"));
    }
    h.querySelector(".badge").textContent = `${sp.stages.reduce((n, s) => n + s.photos.length, 0)} FOTO(S)`;
    card.appendChild(h);
    for (const st of sp.stages) {
      const lab = document.createElement("div");
      lab.className = "label";
      lab.textContent = st.name.toUpperCase();
      card.appendChild(lab);
      const grid = document.createElement("div");
      grid.className = "scoutgrid";
      for (const p of st.photos) {
        const t = document.createElement("button");
        t.className = "sthumb";
        t.dataset.p = JSON.stringify({ id: p.id, name: p.name });
        t.title = [p.name, describe(info.get(p.name))].filter(Boolean).join("\n");
        t.onclick = () => openPhoto(sp, st, p);
        grid.appendChild(t);
        observer.observe(t);
      }
      card.appendChild(grid);
    }
    box.appendChild(card);
  }
}

function count(list) { return list.reduce((n, sp) => n + sp.stages.reduce((m, s) => m + s.photos.length, 0), 0); }

// ------------------------------------------------------------------ IA y guía
const esc = (t) => String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function fichaHtml(g) {
  const parts = [["Cómo reconocerla", g.look], ["Estadios", g.stages], ["Daño / síntoma", g.damage],
    ["Se confunde con", g.confuse], ["Cultivos", AI.cropsText(g)]];
  return `<div class="ficha"><div><b>${esc(g.name)}</b> <i>${esc(g.scientific)}</i></div>` +
    parts.filter(([, v]) => v).map(([k, v]) => `<p><b>${k}:</b> ${esc(v)}</p>`).join("") + "</div>";
}
function showFicha(g) {
  $("sdtitle").textContent = g.name;
  $("sdsub").textContent = g.scientific;
  $("sdimg").hidden = true;
  $("sdactions").hidden = true;
  $("sdbody").innerHTML = fichaHtml(g) + `<p class="muted small">Ficha de campo de la guía de AeonScout: una ayuda, no reemplaza a un especialista o laboratorio.</p>`;
  $("sdlg").showModal();
}

function openKeys() {
  const k = AI.loadKeys();
  $("kplantnet").value = k.plantnet || "";
  $("kgemini").value = k.gemini || "";
  $("kmsg").textContent = "";
  $("kdlg").showModal();
  $("ksave").onclick = async () => {
    AI.saveKeys({ plantnet: $("kplantnet").value, gemini: $("kgemini").value });
    $("kmsg").textContent = "Guardadas en este navegador. Probando…";
    $("kmsg").textContent = (await AI.testKeys((t) => { $("kmsg").textContent = t; })).join("\n");
  };
}

async function openGuide(sec) {
  const G = await AI.guide();
  const cards = [...(G.cards[sec] || []), ...G.cards._];
  $("sdtitle").textContent = `Cómo sacar las fotos · ${SECTIONS.find((s) => s[0] === sec)[1]}`;
  $("sdsub").textContent = "Así la IA (y quien revise) reconoce mejor lo fotografiado.";
  $("sdimg").hidden = true;
  $("sdactions").hidden = true;
  $("sdbody").innerHTML = `<div class="sguide">${cards.map(([img, t, d]) =>
    `<figure><img src="scout/guia/${img}.jpg" alt="" loading="lazy" onerror="this.src='scout/guia/${img}.png'"><figcaption><b>${esc(t)}</b><span>${esc(d)}</span></figcaption></figure>`).join("")}</div>`;
  $("sdlg").showModal();
}

// Fotos de la misma captura: misma fecha y hora en registro.csv (la app guarda una fila por foto).
function recordOf(sp, st, p) {
  const row = info.get(p.name);
  const photos = [];
  if (row) {
    const all = sp.stages.flatMap((s) => s.photos);
    for (const q of all) { const r = info.get(q.name); if (r && r.Fecha === row.Fecha && r.Especie === row.Especie) photos.push({ p: q, view: r.Vista || "" }); }
  }
  if (!photos.length) photos.push({ p, view: row?.Vista || "" });
  return { rec: { section, crop: row?.Cultivo || "", organ: row?.["Órgano"] || "", notes: row?.Notas || "" }, photos, row };
}

async function openPhoto(sp, st, p) {
  const { rec, photos, row } = recordOf(sp, st, p);
  $("sdtitle").textContent = sp.unidentified ? `${sp.name} · no identificada` : sp.name;
  $("sdsub").textContent = [st.name, describe(row)].filter(Boolean).join(" · ");
  $("sdimg").hidden = false;
  $("sdimg").src = "";
  $("sdactions").hidden = false;
  $("sdbody").innerHTML = photos.length > 1 ? `<p class="muted small">La consulta usa las ${photos.length} fotos de esta captura.</p>` : "";
  $("sdlg").showModal();
  photoUrl(p).then((u) => { $("sdimg").src = u; $("sdimg").onclick = () => window.open(u, "_blank"); }).catch(() => {});
  $("sdai").onclick = async () => {
    const blobs = [];
    for (const x of photos) { const u = await photoUrl(x.p); blobs.push({ blob: await (await fetch(u)).blob(), view: x.view }); }
    runAI(rec, blobs, photos.map((x) => x.p.name));
  };
  $("sdguide").onclick = () => openGuide(section);
}

async function identifyNew(files) {
  $("sdtitle").textContent = `Identificar · ${SECTIONS.find((s) => s[0] === section)[1]}`;
  $("sdsub").textContent = `${files.length} foto(s) de este computador (no se guardan: para el registro, tómelas con la app).`;
  $("sdimg").hidden = false;
  $("sdimg").src = URL.createObjectURL(files[0]);
  $("sdactions").hidden = true;
  $("sdbody").innerHTML = "";
  $("sdlg").showModal();
  runAI({ section, crop: "", organ: "", notes: "" }, files.map((f) => ({ blob: f, view: "" })), null);
}

async function runAI(rec, blobs, names) {
  const box = $("sdbody");
  box.innerHTML = `<p class="aiwait">Preparando…</p>`;
  const wait = box.querySelector(".aiwait");
  const t0 = Date.now();
  let step = "Preparando…";
  const tick = setInterval(() => { wait.textContent = `${step} ${Math.round((Date.now() - t0) / 1000)} s`; }, 1000);
  try {
    const res = await AI.identify(rec, blobs, (t) => { step = t; wait.textContent = t; });
    clearInterval(tick);
    showResult(res, rec.section, names);
  } catch (e) {
    clearInterval(tick);
    box.innerHTML = `<p class="warn">${esc(e.message)}</p>` + (["key", "nokey", "cors"].includes(e.kind) ? `<button class="ghost" id="sdkeys">🔑 Revisar claves de IA</button>` : "");
    const kb = $("sdkeys");
    if (kb) kb.onclick = () => { $("sdlg").close(); openKeys(); };
  }
}

function showResult(res, sec, names) {
  const box = $("sdbody");
  const head = `<p class="muted small">Según ${esc(AI.PROVIDERS[res.provider] || res.provider)}${res.remaining != null ? ` · Pl@ntNet: quedan ${res.remaining} consultas hoy` : ""}</p>`;
  const warn = res.is_target ? "" : `<p class="warn">La IA no ve en la foto lo que se busca (${esc(sec)}). Revise la guía de fotos.</p>`;
  const cands = res.candidates.map((c, i) => {
    const g = AI.find(sec, c.name, c.scientific);
    return `<div class="aicand"><div class="aitop"><b>${i + 1}. ${esc(c.name)}</b> <i>${esc(c.scientific)}</i>
      <span class="badge">${Math.round(c.confidence * 100)} %</span></div>
      <div class="aibar"><span style="width:${Math.round(c.confidence * 100)}%"></span></div>
      ${c.stage ? `<div class="small">Estadio: <b>${esc(c.stage)}</b></div>` : ""}
      ${c.features ? `<div class="small muted">${esc(c.features)}</div>` : ""}
      ${g ? `<details><summary>Ficha de la guía</summary>${fichaHtml(g)}</details>` : `<div class="small muted">No está en la guía de la zona.</div>`}</div>`;
  }).join("") || `<p class="muted">Sin candidatas.</p>`;
  const advice = res.advice ? `<p class="small"><b>Para confirmar:</b> ${esc(res.advice)}</p>` : "";
  const send = names ? `<div class="actions"><span id="sdsent" class="muted small grow"></span><button id="sdsend" class="primary">Enviar a la app</button></div>
    <p class="muted small">En la app, la captura queda con este resultado para aceptarlo (Sincronizar o Respaldar AeonScout).</p>` : "";
  box.innerHTML = head + warn + cands + advice + send;
  if (names) $("sdsend").onclick = () => sendToApp(res, names);
}

async function sendToApp(res, names) {
  const btn = $("sdsend"), msg = $("sdsent");
  btn.disabled = true;
  msg.textContent = "Guardando en Drive…";
  try {
    const G = await AI.guide();
    const found = (await X.list(`name='${G.web_file}' and '${top}' in parents and trashed=false`, "files(id,name)"))[0];
    const old = found ? await (await X.download(found.id)).json().catch(() => []) : [];
    const { provider, at, is_target, advice, notes, candidates } = res;
    const entries = names.map((photo) => ({ photo, at, provider, result: { is_target, advice, notes, candidates } }));
    const blob = new Blob([JSON.stringify(AI.mergeEntries(old, entries))], { type: "application/json" });
    if (found) await X.updateFile(found.id, blob, "application/json");
    else await X.upload(top, G.web_file, blob, "application/json");
    msg.textContent = "Enviado: aparece en la app en el próximo respaldo de AeonScout.";
  } catch (e) {
    msg.textContent = `No se pudo guardar: ${e.message}`;
    btn.disabled = false;
  }
}
