// PhenoRubus Web · «Entrenar IA»: marcar con cajas las estructuras de la planta (brotes,
// botones, flores, frutos…) en las fotos de detalle, para entrenar el detector que contará
// flores y frutos y estimará la etapa BBCH. Es una sola especie: se trabaja con las fotos de
// TODOS los ensayos y predios y las marcas van a un solo archivo en Drive («PhenoRubus ·
// Imágenes de Fenología/Entrenamiento IA/marcas.json»), aparte de los registros.
import * as C from "./core.js";

export const CLASSES = [            // la tecla de cada clase es su posición (0–9)
  ["yema", "Yema", "#A1887F"],
  ["brote", "Brote", "#8BC34A"],
  ["lateral", "Lateral", "#5C6BC0"],
  ["boton", "Botón", "#00897B"],
  ["boton_blanco", "Botón blanco", "#78909C"],
  ["flor", "Flor", "#F9A825"],
  ["flor_pasada", "Flor pasada", "#8D6E63"],
  ["fruto_verde", "Fruto verde", "#2E7D32"],
  ["fruto_pinton", "Fruto pintón", "#EC407A"],
  ["fruto_maduro", "Fruto maduro", "#B71C1C"],
];
const COLOR = Object.fromEntries(CLASSES.map(([k, , c]) => [k, c]));
const NAME = Object.fromEntries(CLASSES.map(([k, n]) => [k, n]));
const GOAL = 300;
const $ = (id) => document.getElementById(id);
const base = (p) => (p || "").split(/[\\/]/).pop();

let X = null;              // {S, photoUrl, loadLabels(), saveLabels(data), allStates(progress), email()}
let data = null;           // {version, classes, photos: {nombre: {w, h, boxes, empty, by, ts}}}
let photos = null;         // fotos de detalle de todos los ensayos (se leen al abrir)
let filter = "todo";       // «todo» | «sin» | «con»
let wsFilter = "";         // código del ensayo/predio o «» (todos)
let list = [];             // fotos de detalle visibles (orden de la lista)
let saveTimer = null;

export function enabled() {
  try {
    if (location.hash.includes("lab")) localStorage.setItem("pr_lab", "1");
    return localStorage.getItem("pr_lab") === "1";
  } catch { return location.hash.includes("lab"); }
}

export function init(ctx) {
  X = ctx;
  document.querySelectorAll("#tfilter button").forEach((b) => (b.onclick = () => {
    filter = b.dataset.f;
    document.querySelectorAll("#tfilter button").forEach((x) => x.classList.toggle("on", x === b));
    renderList();
  }));
  $("trainfab").onclick = () => { $("tpage").showModal(); load(false); };
  $("tpageclose").onclick = () => $("tpage").close();
  $("treload").onclick = () => load(true);
  Ed.init();
}

async function load(fresh) {
  $("tgrid").innerHTML = "";
  const say = (t) => { $("tstats").textContent = t; };
  if (!data || fresh) {
    say("Cargando marcas…");
    data = { version: 1, classes: CLASSES.map(([k]) => k), photos: {} };
    try {
      const got = await X.loadLabels();
      if (got && got.photos) data = { ...data, ...got, classes: data.classes };
    } catch (e) { say(`No se pudieron leer las marcas: ${e.message}`); }
  }
  if (!photos || fresh) photos = detailPhotos(await X.allStates(say));
  renderWs();
  renderList();
}
function scheduleSave() {
  clearTimeout(saveTimer);
  $("tsaved").textContent = "Sin guardar…";
  saveTimer = setTimeout(saveNow, 1500);
}

async function saveNow() {
  clearTimeout(saveTimer);
  if (!data) return;
  try {
    await X.saveLabels(data);
    $("tsaved").textContent = "Guardado en Drive";
  } catch (e) { $("tsaved").textContent = `No se guardó: ${e.message}`; }
}

function detailPhotos(states) {
  const out = [];
  for (const { ws, state } of states) {
    const obs = new Map(C.rows(state, "observations").map((o) => [o.uid, o]));
    const vars = new Map(C.rows(state, "varieties").map((v) => [v.uid, v]));
    for (const p of C.rows(state, "photos")) {
      if (p.kind !== "detail" || !p.path) continue;
      const o = obs.get(p.observation_id) || {};
      const v = vars.get(o.variety_id) || {};
      out.push({ ...p, name: base(p.path), code: ws.code, wsName: ws.name || ws.code, week: o.week_id || "",
        variety: C.unitMain(v) || v.name || "" });
    }
  }
  const seen = new Set();        // la misma foto no se repite (mismo nombre de archivo)
  return out.filter((p) => !seen.has(p.name) && seen.add(p.name))
    .sort((a, b) => (b.week || "").localeCompare(a.week || "") || a.name.localeCompare(b.name));
}

function renderWs() {
  const box = $("tws");
  const codes = [...new Map(photos.map((p) => [p.code, p.wsName])).entries()];
  box.innerHTML = "";
  box.hidden = codes.length < 2;
  for (const [code, name] of [["", "Todos"], ...codes]) {
    const b = document.createElement("button");
    b.textContent = code ? `${name} (${photos.filter((p) => p.code === code).length})` : `Todos (${photos.length})`;
    b.className = code === wsFilter ? "on" : "";
    b.onclick = () => { wsFilter = code; renderWs(); renderList(); };
    box.appendChild(b);
  }
}

function marked(name) {
  const r = data?.photos?.[name];
  return !!(r && (r.empty || (r.boxes || []).length));
}

function renderList() {
  if (!photos) return;
  const all = photos;
  const done = all.filter((p) => marked(p.name));
  const totals = Object.fromEntries(CLASSES.map(([k]) => [k, 0]));
  for (const r of Object.values(data?.photos || {})) for (const b of r.boxes || []) totals[b.c] = (totals[b.c] || 0) + 1;
  $("tstats").innerHTML = `<b>${done.length}</b> fotos marcadas de ${all.length} (todos los ensayos y predios) · meta ${GOAL}
    <div class="tbar"><i style="width:${Math.min(100, done.length / GOAL * 100)}%"></i></div>
    <div class="tclasses">${CLASSES.map(([k, n, c]) => `<span><i style="background:${c}"></i>${n} <b>${totals[k] || 0}</b></span>`).join("")}</div>`;
  list = all.filter((p) => (!wsFilter || p.code === wsFilter) && (filter === "todo" || (filter === "con") === marked(p.name)));
  const grid = $("tgrid");
  grid.innerHTML = "";
  if (!list.length) grid.innerHTML = `<p class="muted">${all.length ? "No hay fotos en este filtro." : "Aún no hay fotos de detalle en los ensayos y predios."}</p>`;
  const io = new IntersectionObserver((ents) => ents.forEach((en) => {
    if (!en.isIntersecting) return;
    io.unobserve(en.target);
    const p = list[Number(en.target.dataset.i)];
    X.photoUrl(p.path).then((u) => { if (u) en.target.style.backgroundImage = `url(${u})`; });
  }), { rootMargin: "300px" });
  list.forEach((p, i) => {
    const r = data.photos[p.name];
    const n = (r?.boxes || []).length;
    const d = document.createElement("button");
    d.className = "tthumb";
    d.dataset.i = i;
    d.title = p.name;
    d.innerHTML = `<span class="tc">${p.code}</span><span class="tw">${p.week ? C.weekTitle(p.week).replace(", año", " ·") : ""}</span>
      <span class="tv">${p.variety || ""}</span>${marked(p.name) ? `<span class="tn">${r.empty && !n ? "vacía" : n}</span>` : ""}`;
    d.onclick = () => Ed.open(i);
    grid.appendChild(d);
    io.observe(d);
  });
}

// ------------------------------------------------------------------ editor de cajas
const Ed = {
  init() {
    this.cv = $("tcanvas");
    this.g = this.cv.getContext("2d");
    const bar = $("tclassbar");
    CLASSES.forEach(([k, n, c], i) => {
      const b = document.createElement("button");
      b.type = "button"; b.dataset.k = k;
      b.innerHTML = `<i style="background:${c}"></i>${i} · ${n}`;
      b.onclick = () => this.setClass(k);
      bar.appendChild(b);
    });
    this.setClass("flor");
    $("tprev").onclick = () => this.go(-1);
    $("tnext").onclick = () => this.go(1);
    $("tdel").onclick = () => this.deleteSel();
    $("tempty").onclick = () => this.toggleEmpty();
    $("tcopy").onclick = () => this.copyPrev();
    $("tfit").onclick = () => { this.fitView(); this.draw(); };
    $("tclose").onclick = () => this.close();
    $("tdialog").addEventListener("close", () => { saveNow(); renderList(); });
    this.cv.addEventListener("pointerdown", (e) => this.down(e));
    this.cv.addEventListener("pointermove", (e) => this.move(e));
    for (const ev of ["pointerup", "pointercancel"]) this.cv.addEventListener(ev, (e) => this.up(e));
    this.cv.addEventListener("wheel", (e) => { e.preventDefault(); this.zoomAt(e.deltaY < 0 ? 1.15 : 1 / 1.15, e.offsetX, e.offsetY); }, { passive: false });
    this.cv.addEventListener("contextmenu", (e) => e.preventDefault());
    new ResizeObserver(() => this.fitCanvas()).observe(this.cv);
    window.addEventListener("keydown", (e) => this.key(e));
  },
  setClass(k) {
    this.cls = k;
    [...$("tclassbar").children].forEach((b) => b.classList.toggle("on", b.dataset.k === k));
    if (this.sel != null && this.rec) { this.rec.boxes[this.sel].c = k; this.changed(); }
  },
  async open(i) {
    this.i = i;
    const p = list[i];
    this.photo = p;
    this.sel = null;
    this.rec = data.photos[p.name] ||= { w: 0, h: 0, boxes: [], empty: false };
    $("ttitle").textContent = `${p.wsName} · ${p.variety || "Foto"} · ${p.week ? C.weekLabel(p.week) : ""}`;
    $("tname").textContent = p.name;
    $("tsaved").textContent = "";
    if (!$("tdialog").open) $("tdialog").showModal();
    this.img = null;
    this.draw();
    const url = await X.photoUrl(p.path);
    if (this.photo !== p) return;
    if (!url) { $("tname").textContent = `${p.name} · aún no está en Drive`; return; }
    const img = new Image();
    img.onload = () => {
      if (this.photo !== p) return;
      this.img = img;
      this.rec.w = img.naturalWidth; this.rec.h = img.naturalHeight;
      this.fitView(); this.fitCanvas(); this.summary();
    };
    img.src = url;
    this.summary();
    $("tprev").disabled = i <= 0;
    $("tnext").disabled = i >= list.length - 1;
  },
  close() { $("tdialog").close(); },
  go(d) {
    const j = this.i + d;
    if (j < 0 || j >= list.length) return;
    this.cleanRec();
    saveNow();
    this.open(j);
  },
  cleanRec() {           // una foto abierta y sin marcas no cuenta como marcada
    const r = this.rec;
    if (r && !r.boxes.length && !r.empty) delete data.photos[this.photo.name];
  },
  changed() {
    this.rec.by = X.email() || "";
    this.rec.ts = C.nowTs();
    if (this.rec.boxes.length) this.rec.empty = false;
    data.photos[this.photo.name] = this.rec;
    this.summary(); this.draw(); scheduleSave();
  },
  summary() {
    const r = this.rec || { boxes: [] };
    const n = {};
    for (const b of r.boxes) n[b.c] = (n[b.c] || 0) + 1;
    $("tcount").innerHTML = r.empty && !r.boxes.length ? "Sin estructuras (foto vacía)" :
      CLASSES.filter(([k]) => n[k]).map(([k, nm, c]) => `<span><i style="background:${c}"></i>${nm} <b>${n[k]}</b></span>`).join("") || "Sin cajas aún";
    $("tempty").classList.toggle("on", !!r.empty);
  },
  toggleEmpty() {
    if (!this.rec) return;
    this.rec.empty = !this.rec.empty;
    if (this.rec.empty) this.rec.boxes = [];
    this.sel = null;
    this.changed();
  },
  copyPrev() {
    const prev = list[this.i - 1];
    const r = prev && data.photos[prev.name];
    if (!r || !r.boxes?.length) { $("tsaved").textContent = "La foto anterior no tiene cajas"; return; }
    this.rec.boxes = r.boxes.map((b) => ({ ...b }));
    this.changed();
  },
  deleteSel() {
    if (this.sel == null) return;
    this.rec.boxes.splice(this.sel, 1);
    this.sel = null;
    this.changed();
  },
  key(e) {
    if (!$("tdialog").open || e.target.tagName === "INPUT") return;
    if (/^[0-9]$/.test(e.key) && CLASSES[Number(e.key)]) { this.setClass(CLASSES[Number(e.key)][0]); e.preventDefault(); }
    else if (e.key === "Delete" || e.key === "Backspace") { this.deleteSel(); e.preventDefault(); }
    else if (e.key === "ArrowRight" || e.key === "Enter") { this.go(1); e.preventDefault(); }
    else if (e.key === "ArrowLeft") { this.go(-1); e.preventDefault(); }
    else if (e.key.toLowerCase() === "f") { this.fitView(); this.draw(); }
    else if (e.key.toLowerCase() === "v") this.toggleEmpty();
    else if (e.key.toLowerCase() === "c") this.copyPrev();
    else if (e.key === " ") { this.space = true; e.preventDefault(); }
  },
  // geometría: cajas en coordenadas 0..1 de la imagen
  fitCanvas() {
    const r = this.cv.getBoundingClientRect();
    this.dpr = window.devicePixelRatio || 1;
    this.cv.width = Math.max(1, Math.round(r.width * this.dpr));
    this.cv.height = Math.max(1, Math.round(r.height * this.dpr));
    if (!this.view) this.fitView();
    this.draw();
  },
  fitView() {
    const r = this.cv.getBoundingClientRect();
    const iw = this.img?.naturalWidth || 1, ih = this.img?.naturalHeight || 1;
    const s = Math.min(r.width / iw, r.height / ih) * .98;
    this.view = { s, ox: (r.width - iw * s) / 2, oy: (r.height - ih * s) / 2 };
  },
  toImg(x, y) {
    const v = this.view, iw = this.img.naturalWidth, ih = this.img.naturalHeight;
    return [(x - v.ox) / v.s / iw, (y - v.oy) / v.s / ih];
  },
  toScr(nx, ny) {
    const v = this.view;
    return [v.ox + nx * this.img.naturalWidth * v.s, v.oy + ny * this.img.naturalHeight * v.s];
  },
  zoomAt(f, x, y) {
    if (!this.view) return;
    const v = this.view, s = Math.max(.05, Math.min(20, v.s * f)), k = s / v.s;
    v.ox = x - (x - v.ox) * k; v.oy = y - (y - v.oy) * k; v.s = s;
    this.draw();
  },
  hit(x, y) {           // caja bajo el puntero (la más pequeña) y si es una esquina
    if (!this.rec) return [null, null];
    let best = null, bestA = Infinity, corner = null;
    this.rec.boxes.forEach((b, i) => {
      const [x0, y0] = this.toScr(b.x, b.y), [x1, y1] = this.toScr(b.x + b.w, b.y + b.h);
      const near = (px, py) => Math.abs(x - px) < 9 && Math.abs(y - py) < 9;
      if (i === this.sel) {
        for (const [cx, cy, n] of [[x0, y0, "nw"], [x1, y0, "ne"], [x0, y1, "sw"], [x1, y1, "se"]]) if (near(cx, cy)) { best = i; corner = n; bestA = -1; }
      }
      const a = (x1 - x0) * (y1 - y0);
      if (x >= x0 && x <= x1 && y >= y0 && y <= y1 && a < bestA) { best = i; bestA = a; corner = null; }
    });
    return [best, corner];
  },
  down(e) {
    if (!this.img) return;
    this.cv.setPointerCapture(e.pointerId);
    const x = e.offsetX, y = e.offsetY;
    if (e.button === 1 || e.button === 2 || this.space) { this.drag = { mode: "pan", x, y }; return; }
    const [i, corner] = this.hit(x, y);
    if (i != null) {
      this.sel = i;
      const b = this.rec.boxes[i];
      this.drag = { mode: corner ? "resize" : "move", corner, x, y, b0: { ...b } };
      this.setClassButton(b.c);
    } else {
      const [nx, ny] = this.toImg(x, y);
      this.drag = { mode: "new", x0: nx, y0: ny };
      this.sel = null;
    }
    this.draw();
  },
  setClassButton(k) {
    this.cls = k;
    [...$("tclassbar").children].forEach((b) => b.classList.toggle("on", b.dataset.k === k));
  },
  move(e) {
    const d = this.drag;
    if (!this.img) return;
    const x = e.offsetX, y = e.offsetY;
    if (!d) {
      const [, corner] = this.hit(x, y);
      this.cv.style.cursor = corner ? "nwse-resize" : this.space ? "grab" : "crosshair";
      return;
    }
    if (d.mode === "pan") { this.view.ox += x - d.x; this.view.oy += y - d.y; d.x = x; d.y = y; this.draw(); return; }
    const [nx, ny] = this.toImg(x, y);
    const clamp = (v) => Math.max(0, Math.min(1, v));
    if (d.mode === "new") { d.x1 = clamp(nx); d.y1 = clamp(ny); this.draw(); return; }
    const b = this.rec.boxes[this.sel], b0 = d.b0;
    const [px, py] = this.toImg(d.x, d.y), dx = nx - px, dy = ny - py;
    if (d.mode === "move") {
      b.x = clamp(Math.min(1 - b0.w, b0.x + dx)); b.y = clamp(Math.min(1 - b0.h, b0.y + dy));
    } else {
      let x0 = b0.x, y0 = b0.y, x1 = b0.x + b0.w, y1 = b0.y + b0.h;
      if (d.corner.includes("w")) x0 = clamp(x0 + dx); else x1 = clamp(x1 + dx);
      if (d.corner.includes("n")) y0 = clamp(y0 + dy); else y1 = clamp(y1 + dy);
      b.x = Math.min(x0, x1); b.y = Math.min(y0, y1); b.w = Math.abs(x1 - x0); b.h = Math.abs(y1 - y0);
    }
    this.draw();
  },
  up(e) {
    const d = this.drag;
    this.drag = null;
    if (!d || d.mode === "pan") return;
    if (d.mode === "new") {
      if (d.x1 == null) { this.draw(); return; }
      const b = { c: this.cls, x: Math.min(d.x0, d.x1), y: Math.min(d.y0, d.y1), w: Math.abs(d.x1 - d.x0), h: Math.abs(d.y1 - d.y0) };
      const [sx0, sy0] = this.toScr(b.x, b.y), [sx1, sy1] = this.toScr(b.x + b.w, b.y + b.h);
      if (sx1 - sx0 < 6 || sy1 - sy0 < 6) { this.draw(); return; }     // un clic suelto no crea caja
      this.rec.boxes.push(b);
      this.sel = this.rec.boxes.length - 1;
    }
    const r4 = (v) => Math.round(v * 10000) / 10000;
    for (const b of this.rec.boxes) { b.x = r4(b.x); b.y = r4(b.y); b.w = r4(b.w); b.h = r4(b.h); }
    this.changed();
  },
  draw() {
    const g = this.g, dpr = this.dpr || 1;
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.fillStyle = "#15130f"; g.fillRect(0, 0, this.cv.width, this.cv.height);
    if (!this.img || !this.view) return;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    const v = this.view;
    g.drawImage(this.img, v.ox, v.oy, this.img.naturalWidth * v.s, this.img.naturalHeight * v.s);
    const boxes = this.rec.boxes.map((b, i) => [b, i]);
    const d = this.drag;
    if (d && d.mode === "new" && d.x1 != null) boxes.push([{ c: this.cls, x: Math.min(d.x0, d.x1), y: Math.min(d.y0, d.y1), w: Math.abs(d.x1 - d.x0), h: Math.abs(d.y1 - d.y0) }, -1]);
    g.font = "600 12px system-ui, sans-serif";
    for (const [b, i] of boxes) {
      const [x0, y0] = this.toScr(b.x, b.y), [x1, y1] = this.toScr(b.x + b.w, b.y + b.h);
      const col = COLOR[b.c] || "#fff";
      g.lineWidth = i === this.sel ? 3 : 2;
      g.strokeStyle = col;
      g.fillStyle = col + "22";
      g.fillRect(x0, y0, x1 - x0, y1 - y0);
      g.strokeRect(x0, y0, x1 - x0, y1 - y0);
      const t = NAME[b.c] || b.c, tw = g.measureText(t).width + 8;
      g.fillStyle = col; g.fillRect(x0, y0 - 16, tw, 16);
      g.fillStyle = "#fff"; g.fillText(t, x0 + 4, y0 - 4);
      if (i === this.sel) {
        g.fillStyle = "#fff";
        for (const [cx, cy] of [[x0, y0], [x1, y0], [x0, y1], [x1, y1]]) { g.fillRect(cx - 4, cy - 4, 8, 8); g.strokeRect(cx - 4, cy - 4, 8, 8); }
      }
    }
  },
};

window.addEventListener("keyup", (e) => { if (e.key === " ") Ed.space = false; });
