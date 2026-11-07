// AeonCrop Web · visor de AeonScout: el banco de imágenes de plagas, malezas y enfermedades
// que la app sube a «AeonCrop/AeonScout/<Plagas|Malezas|Enfermedades>/<especie>/<estadio>/»
// (las no identificadas en «…/No identificadas/NI-003/…») y «registro.csv» (= scout.py).
// Solo lectura: las capturas se hacen en la app.
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
    h.innerHTML = `<b></b><span class="badge"></span>`;
    h.querySelector("b").textContent = sp.unidentified ? `${sp.name} · no identificada` : sp.name;
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
        t.onclick = async () => {
          const u = await photoUrl(p).catch(() => null);
          if (!u) return;
          $("vimg").src = u;
          $("vimg").alt = t.title;
          $("viewer").showModal();
        };
        grid.appendChild(t);
        observer.observe(t);
      }
      card.appendChild(grid);
    }
    box.appendChild(card);
  }
}

function count(list) { return list.reduce((n, sp) => n + sp.stages.reduce((m, s) => m + s.photos.length, 0), 0); }
