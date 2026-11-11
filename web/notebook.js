// PhenoRubus Web · Cuaderno de campo (= ui/notebook.py): línea de tiempo por día; cada día con
// una o más hojas (‹ › o deslizando hacia el lado) de texto que se guarda solo y escritura a
// mano; fotos pegadas sobre la hoja (se mueven, agrandan y giran) y lápiz sobre la foto (mouse,
// dedo o lápiz con presión). Usa las mismas tablas que la app (notebook_entries / notebook_photos).
import * as C from "./core.js";

const $ = (id) => document.getElementById(id);
const WEEKDAYS = ["domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"];
const PEN_COLORS = ["#E53935", "#FFD54F", "#FFFFFF", "#212121", "#43A047"];
const PEN_WIDTHS = [["Fino", 2.5], ["Medio", 5], ["Grueso", 10]];
let X = null;                     // {S, send, photoUrl, uploadPhoto, resize, render}
let page = null;                  // día abierto
let sheet = 0;                    // hoja del día que se ve (0 = la primera)
let saveTimer = null;

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[ch]);
const base = (p) => (p || "").split(/[\\/]/).pop();

export function niceDay(day, weekday = true) {
  const d = C.parseDate(day);
  const txt = `${d.getUTCDate()} de ${C.MESES[d.getUTCMonth()]} de ${d.getUTCFullYear()}`;
  const w = WEEKDAYS[d.getUTCDay()];
  return weekday ? `${w[0].toUpperCase()}${w.slice(1)} ${txt}` : txt;
}
function excerpt(text, n = 220) {
  const t = (text || "").split(/\s+/).join(" ").trim();
  return t.length <= n ? t : `${t.slice(0, n - 1).replace(/\s+\S*$/, "")}…`;
}

export function init(ctx) {
  X = ctx;
  $("nbnew").onclick = () => openPage(C.iso(C.todayUTC()));
  $("nbtext").oninput = dirty;
  $("nbkeys").onclick = () => setPen(false);
  Ink.init();
  $("nbpage").addEventListener("close", () => { saveText(); renderNotebook(); });
  $("nbdate").onchange = (e) => moveTo(e.target.value);
  $("nbdel").onclick = deletePage;
  $("nbprev").onclick = () => flip(-1);
  $("nbnext").onclick = () => flip(1);
  $("nbaddpage").onclick = addSheet;
  const zone = $("nbdrop"), input = zone.querySelector("input");
  zone.onclick = () => input.click();
  input.onclick = (e) => e.stopPropagation();
  input.onchange = () => { const l = [...input.files]; input.value = ""; addPhotos(l); };
  zone.ondragover = (e) => { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; zone.classList.add("over"); };
  zone.ondragleave = (e) => { if (!zone.contains(e.relatedTarget)) zone.classList.remove("over"); };
  zone.ondrop = (e) => { e.preventDefault(); zone.classList.remove("over"); addPhotos([...e.dataTransfer.files]); };
  const wrap = document.querySelector(".nbwrap");          // también se sueltan sobre la hoja
  wrap.addEventListener("dragover", (e) => { if (e.dataTransfer.types.includes("Files")) e.preventDefault(); });
  wrap.addEventListener("drop", (e) => {
    if (!e.dataTransfer.files.length) return;
    e.preventDefault();
    addPhotos([...e.dataTransfer.files], Sticker.placeAt(e));
  });
  // Deslizar la hoja hacia el lado (pantalla táctil, fuera del modo lápiz): otra hoja.
  let sw = null;
  wrap.addEventListener("touchstart", (e) => {
    sw = e.touches.length === 1 && !Ink.penOn() && !e.target.closest(".nbst")
      ? { x: e.touches[0].clientX, y: e.touches[0].clientY, t: Date.now() } : null;
  }, { passive: true });
  wrap.addEventListener("touchend", (e) => {
    if (!sw || !e.changedTouches.length) return;
    const dx = e.changedTouches[0].clientX - sw.x, dy = e.changedTouches[0].clientY - sw.y;
    if (Math.abs(dx) > Math.max(80, wrap.clientWidth * .28) && Math.abs(dy) < Math.abs(dx) * .45 && Date.now() - sw.t < 800) flip(dx > 0 ? -1 : 1);
    sw = null;
  }, { passive: true });
  Sticker.init();
  Draw.init();
}

function dirty() {
  $("nbsaved").textContent = "Escribiendo…";
  clearTimeout(saveTimer);
  saveTimer = setTimeout(saveText, 1500);
}

function setPen(on) {
  document.querySelector(".nbsheet").classList.toggle("pen", on);
  if (on) $("nbtext").blur();
  else Ink.clearSel();
  Ink.syncBar();
  Ink.draw();
}

// ------------------------------------------------------------------ línea de tiempo
export function renderNotebook() {
  const box = $("nblist");
  const days = C.noteDays(X.S.state);
  $("nbempty").hidden = days.length > 0;
  box.innerHTML = "";
  for (const d of days) {
    const date = C.parseDate(d.day);
    const w = WEEKDAYS[date.getUTCDay()];
    const card = document.createElement("button");
    card.className = "card nbcard";
    const n = d.photos.length;
    card.innerHTML = `<div class="nbdate"><b>${date.getUTCDate()}</b><span>${C.MES3[date.getUTCMonth()].toUpperCase()}</span></div>
      <div class="nbinfo"><div class="nbhead"><span>${w[0].toUpperCase()}${w.slice(1)} · ${date.getUTCFullYear()}</span>
      <span class="muted">${n ? `${n} foto${n === 1 ? "" : "s"}` : ""}</span></div>
      <div class="nbtxt">${esc(excerpt(d.text)) || `<span class="muted">${(d.ink || "").length > 2 ? "✎ Escrito a mano" : "Sin texto"}</span>`}</div><div class="nbstrip"></div></div>`;
    card.onclick = () => openPage(d.day);
    const strip = card.querySelector(".nbstrip");
    for (const p of d.photos.slice(0, 6)) {
      const t = document.createElement("i");
      strip.appendChild(t);
      X.photoUrl(p.path).then((u) => { if (u) t.style.backgroundImage = `url(${u})`; });
    }
    box.appendChild(card);
  }
}

// ------------------------------------------------------------------ página
function current() { return page ? C.noteFor(X.S.state, page) : null; }

export function openPage(day, index = 0) {
  page = day;
  const cur = current();
  $("nbtitle").textContent = niceDay(day);
  $("nbdate").value = day;
  showSheet(Math.min(index, C.notePages(cur).length - 1));
  setPen(false);
  $("nbsaved").textContent = cur ? "Guardado" : "";
  $("nbmsg").textContent = "";
  if (!$("nbpage").open) $("nbpage").showModal();
  if (!Ink.strokes.length) $("nbtext").focus();
}

function showSheet(index) {
  const pages = C.notePages(current());
  sheet = Math.max(0, Math.min(index, pages.length - 1));
  $("nbtext").value = pages[sheet].text;
  $("nbtext").scrollTop = 0;
  Ink.load(pages[sheet].ink);
  $("nbpagenum").textContent = `${sheet + 1}/${pages.length}`;
  $("nbprev").disabled = sheet === 0;
  $("nbnext").disabled = sheet >= pages.length - 1;
  renderPhotos();
}

// Otra hoja del día (+1 siguiente, -1 anterior), con un pequeño deslizamiento.
async function flip(step) {
  const j = sheet + step, n = C.notePages(current()).length;
  if (j < 0 || j >= n) return;
  await saveText();
  const wrap = document.querySelector(".nbwrap");
  wrap.classList.add(step > 0 ? "out-l" : "out-r");
  setTimeout(() => {
    showSheet(j);
    wrap.classList.remove("out-l", "out-r");
  }, 120);
}

async function addSheet() {
  await saveText();
  const cur = current();
  const pages = C.notePages(cur);
  const fields = C.notePageFields(cur || {}, pages.length, "", "");
  await ensureEntry(fields);
  $("nbmsg").textContent = `Hoja ${pages.length + 1} agregada · se pasa de una a otra con ‹ › o deslizando la hoja.`;
  showSheet(pages.length);
}

async function ensureEntry(fields = {}) {      // la página se crea al escribir o subir la primera foto
  const r = C.noteChange(X.S.state, page, fields);
  await X.send([r.change]);
  return r.uid;
}

async function saveText() {
  clearTimeout(saveTimer);
  if (!page) return;
  const text = $("nbtext").value, ink = Ink.dumps();
  const cur = current();
  const was = C.notePages(cur)[sheet] || { text: "", ink: "" };
  if (was.text === text && was.ink === ink) { if (cur) $("nbsaved").textContent = "Guardado"; return; }
  try { await ensureEntry(C.notePageFields(cur || {}, sheet, text, ink)); $("nbsaved").textContent = "Guardado"; }
  catch (e) { $("nbsaved").textContent = `No se guardó: ${e.message}`; }
}

async function moveTo(day) {
  if (!day || day === page) return;
  const cur = current();
  if (!cur) { openPage(day); return; }
  if (C.noteFor(X.S.state, day)) {
    $("nbmsg").textContent = `Ya hay una página del ${niceDay(day, false)}.`;
    $("nbdate").value = page;
    return;
  }
  await saveText();
  await X.send([C.noteChange(X.S.state, page, { day }).change]);
  openPage(day);
}

async function deletePage() {
  const cur = current();
  if (!cur) { $("nbpage").close(); return; }
  const n = C.notePages(cur).length;
  if (n > 1 && confirm(`Este día tiene ${n} hojas.\n\nAceptar: borrar solo la hoja ${sheet + 1} (con sus fotos pegadas).\nCancelar: elegir si borrar el día completo.`)) {
    await saveText();
    const r = C.noteDeletePage(current(), sheet);
    await X.send([C.noteChange(X.S.state, page, r.fields).change, ...r.photos]);
    showSheet(Math.max(0, sheet - 1));
    $("nbmsg").textContent = "Hoja borrada.";
    return;
  }
  if (!confirm(`¿Borrar la página del ${niceDay(page, false)} con su texto y fotos?\n(Los archivos de fotos quedan en Drive.)`)) return;
  clearTimeout(saveTimer);
  await X.send(C.noteDeleteChanges(X.S.state, page));
  page = null;
  $("nbpage").close();
}

function renderPhotos() { Sticker.render(); }

async function addPhotos(files, at = null) {
  files = files.filter((f) => f.type.startsWith("image/") || /\.(jpe?g|png|heic|webp)$/i.test(f.name));
  if (!files.length) { $("nbmsg").textContent = "Solo se pueden subir imágenes."; return; }
  const zone = $("nbdrop");
  zone.classList.add("busy");
  try {
    await saveText();
    const uid = current()?.uid || await ensureEntry();
    const taken = new Set(C.rows(X.S.state, "notebook_photos").map((p) => base(p.path)));
    const stem = `${page.replaceAll("-", "")}-${X.S.ws.code}-cuaderno`;
    const changes = [];
    let n = 1, k = Sticker.count();
    for (const f of files) {
      let name;
      do { name = `${stem}-w${n++}.jpg`; } while (taken.has(name));
      taken.add(name);
      $("nbmsg").textContent = `Subiendo ${name}…`;
      await X.uploadPhoto(page, name, await X.resize(f));
      changes.push(C.notePhotoChange(uid, `photos/cuaderno/${name}`, sheet, Sticker.defaultPlace(k++, at)));
    }
    await X.send(changes);
    $("nbmsg").textContent = `${files.length} foto(s) pegada(s) en la hoja: arrástrelas, agrándelas o gírelas; un clic, para dibujar encima.`;
  } catch (e) { $("nbmsg").textContent = `No se pudieron subir: ${e.message}`; }
  finally { zone.classList.remove("busy"); renderPhotos(); }
}

// ------------------------------------------------------------------ lápiz sobre la foto
// Trazos en píxeles de la imagen: se ven igual con cualquier zoom y se pintan tal cual al guardar.
const Draw = {
  init() {
    this.cv = $("nbcanvas");
    this.g = this.cv.getContext("2d");
    const sw = $("nbswatches");
    PEN_COLORS.forEach((col) => {
      const b = document.createElement("button");
      b.type = "button"; b.className = "swatch"; b.style.background = col; b.title = col;
      b.onclick = () => this.setColor(col);
      sw.appendChild(b);
    });
    const ww = $("nbwidths");
    PEN_WIDTHS.forEach(([label, w]) => {
      const b = document.createElement("button");
      b.type = "button"; b.textContent = label; b.dataset.w = w;
      b.onclick = () => this.setWidth(w);
      ww.appendChild(b);
    });
    $("nbundo").onclick = () => { this.strokes.pop(); this.draw(); };
    $("nbclear").onclick = () => { this.strokes = []; this.draw(); };
    $("nbfit").onclick = () => { this.zoom = 1; this.pan = [0, 0]; this.draw(); };
    $("nbdsave").onclick = () => this.save();
    $("nbdclose").onclick = () => $("nbdraw").close();
    this.pointers = new Map();
    this.cv.addEventListener("pointerdown", (e) => this.down(e));
    this.cv.addEventListener("pointermove", (e) => this.move(e));
    for (const ev of ["pointerup", "pointercancel"]) this.cv.addEventListener(ev, (e) => this.up(e));
    this.cv.addEventListener("wheel", (e) => { e.preventDefault(); this.zoomAt(e.deltaY < 0 ? 1.15 : 1 / 1.15, e.offsetX, e.offsetY); }, { passive: false });
    new ResizeObserver(() => this.fitCanvas()).observe(this.cv);
    this.setColor(PEN_COLORS[0]);
    this.setWidth(PEN_WIDTHS[1][1]);
  },
  setColor(col) {
    this.color = col;
    [...$("nbswatches").children].forEach((b) => b.classList.toggle("on", b.title === col));
  },
  setWidth(w) {
    this.width = w;
    [...$("nbwidths").children].forEach((b) => b.classList.toggle("on", Number(b.dataset.w) === w));
  },
  open(photo, url) {
    this.photo = photo;
    this.strokes = []; this.cur = null; this.zoom = 1; this.pan = [0, 0];
    $("nbdmsg").textContent = "";
    this.img = new Image();
    this.img.onload = () => { this.fitCanvas(); };
    this.img.src = url;
    $("nbdraw").showModal();
  },
  fitCanvas() {
    const r = this.cv.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    this.cv.width = Math.max(1, Math.round(r.width * dpr));
    this.cv.height = Math.max(1, Math.round(r.height * dpr));
    this.dpr = dpr;
    this.draw();
  },
  scale() {                                    // px de pantalla (CSS) por px de imagen
    const iw = this.img?.naturalWidth || 1, ih = this.img?.naturalHeight || 1;
    const w = this.cv.width / this.dpr, h = this.cv.height / this.dpr;
    return Math.min(w / iw, h / ih) * this.zoom;
  },
  origin() {
    const s = this.scale();
    const w = this.cv.width / this.dpr, h = this.cv.height / this.dpr;
    return [w / 2 - this.img.naturalWidth * s / 2 + this.pan[0], h / 2 - this.img.naturalHeight * s / 2 + this.pan[1]];
  },
  toImage(x, y) {
    const [ox, oy] = this.origin(), s = this.scale();
    return [(x - ox) / s, (y - oy) / s];
  },
  draw() {
    const g = this.g;
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.fillStyle = "#1f1a14";
    g.fillRect(0, 0, this.cv.width, this.cv.height);
    if (!this.img?.naturalWidth) return;
    const [ox, oy] = this.origin(), s = this.scale();
    g.setTransform(this.dpr * s, 0, 0, this.dpr * s, this.dpr * ox, this.dpr * oy);
    g.drawImage(this.img, 0, 0);
    paint(g, this.cur ? [...this.strokes, this.cur] : this.strokes);
  },
  down(e) {
    if (!this.img?.naturalWidth) return;
    this.cv.setPointerCapture(e.pointerId);
    this.pointers.set(e.pointerId, [e.offsetX, e.offsetY]);
    if (this.pointers.size === 1 && e.button !== 1) {
      // Lápiz con presión: más presión, trazo más grueso (como el S-Pen en la app).
      const k = e.pointerType === "pen" && e.pressure > 0 ? .5 + e.pressure : 1;
      this.cur = { color: this.color, width: this.width * k / this.scale(), pts: this.toImage(e.offsetX, e.offsetY) };
    } else {
      this.cur = null;                          // segundo dedo: acercar y mover
      this.pinch = this.pinchState();
    }
    this.draw();
  },
  pinchState() {
    const [[x0, y0], [x1, y1]] = [...this.pointers.values()];
    return { d: Math.hypot(x1 - x0, y1 - y0) || 1, mid: [(x0 + x1) / 2, (y0 + y1) / 2] };
  },
  move(e) {
    if (!this.pointers.has(e.pointerId)) return;
    this.pointers.set(e.pointerId, [e.offsetX, e.offsetY]);
    if (this.pointers.size >= 2 && this.pinch) {
      const p = this.pinchState();
      this.zoomAt(p.d / this.pinch.d, p.mid[0], p.mid[1]);
      this.pan[0] += p.mid[0] - this.pinch.mid[0];
      this.pan[1] += p.mid[1] - this.pinch.mid[1];
      this.pinch = p;
      this.draw();
    } else if (this.cur) {
      const events = e.getCoalescedEvents ? e.getCoalescedEvents() : [e];
      for (const ev of events.length ? events : [e]) {
        const [x, y] = this.toImage(ev.offsetX, ev.offsetY);
        const n = this.cur.pts.length;
        if (Math.hypot(x - this.cur.pts[n - 2], y - this.cur.pts[n - 1]) * this.scale() >= 1.2) this.cur.pts.push(x, y);
      }
      this.draw();
    }
  },
  up(e) {
    this.pointers.delete(e.pointerId);
    if (this.cur && !this.pointers.size) { this.strokes.push(this.cur); this.cur = null; this.draw(); }
    if (this.pointers.size < 2) this.pinch = null;
  },
  zoomAt(f, x, y) {
    const z = Math.max(1, Math.min(8, this.zoom * f)), k = z / this.zoom;
    const w = this.cv.width / this.dpr, h = this.cv.height / this.dpr;
    this.pan[0] = (x - w / 2) - (x - w / 2 - this.pan[0]) * k;
    this.pan[1] = (y - h / 2) - (y - h / 2 - this.pan[1]) * k;
    this.zoom = z;
    this.draw();
  },
  async save() {
    if (!this.strokes.length) { $("nbdraw").close(); return; }
    const btn = $("nbdsave");
    btn.disabled = true;
    $("nbdmsg").textContent = "Guardando…";
    try {
      const cv = document.createElement("canvas");
      cv.width = this.img.naturalWidth; cv.height = this.img.naturalHeight;
      const g = cv.getContext("2d");
      g.drawImage(this.img, 0, 0);
      paint(g, this.strokes);
      const blob = await new Promise((res) => cv.toBlob(res, "image/jpeg", 0.85));
      const taken = new Set(C.rows(X.S.state, "notebook_photos").map((p) => base(p.path)));
      const name = C.annotatedName(base(this.photo.path), taken);
      await X.uploadPhoto(page, name, blob);
      await X.send([C.notePhotoUpdate(this.photo, { path: `photos/cuaderno/${name}`, annotated: 1 })]);
      $("nbdraw").close();
      $("nbmsg").textContent = "Foto con dibujos guardada (la original queda en Drive).";
      renderPhotos();
    } catch (e) { $("nbdmsg").textContent = `No se pudo guardar: ${e.message}`; }
    finally { btn.disabled = false; }
  },
};

function paint(g, strokes) {
  g.lineCap = g.lineJoin = "round";
  for (const st of strokes) {
    const p = st.pts;
    g.strokeStyle = g.fillStyle = st.color;
    g.lineWidth = Math.max(.6, st.width) * 2;       // = burn_strokes (grosor en la app: radio de la línea)
    if (p.length <= 2) {
      g.beginPath(); g.arc(p[0], p[1], g.lineWidth / 2, 0, Math.PI * 2); g.fill();
      continue;
    }
    g.beginPath();
    g.moveTo(p[0], p[1]);
    for (let i = 2; i < p.length; i += 2) g.lineTo(p[i], p[i + 1]);
    g.stroke();
  }
}

// ------------------------------------------------------------------ escritura a mano en la hoja
// Igual que la app (ui.notebook.InkLayer): trazos en renglones desde el borde superior
// izquierdo del texto, así la letra queda en el mismo renglón en el teléfono y en la web.
const LINE = 30, PAD_X = 14;
// Barra (= ui.notebook): teclado · pluma · destacador · goma · lazo | 5 colores | 3 grosores.
const INKS = ["#212121", "#1E3A8A", "#C62828", "#E65100", "#2E7D32"];
const HLS = ["#FFEB3B", "#76FF03", "#FF4081", "#40C4FF", "#FFAB40"];
const WIDTHS = { pen: [.11, .065, .04], hl: [.75, .55, .35] };
const ALPHA = { hl: .35 };                     // los demás trazos (pluma, plumón antiguo): 1

function inside(x, y, poly) {                 // punto dentro de un polígono (rayos)
  let hit = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / ((yj - yi) || 1e-9) + xi) hit = !hit;
  }
  return hit;
}

const Ink = {
  strokes: [], cur: null, mode: "pen", color: INKS[0], widthI: 1, pointers: new Map(),
  colors: {}, widths: {}, sel: [], lasso: null, drag: null,
  init() {
    this.cv = $("nbink");
    this.g = this.cv.getContext("2d");
    this.ta = $("nbtext");
    this.ta.addEventListener("scroll", () => { this.draw(); Sticker.position(); });
    new ResizeObserver(() => { this.fit(); Sticker.position(); }).observe(this.ta);
    document.querySelectorAll(".nbtools .tool[data-mode]").forEach((b) => (b.onclick = () => this.setMode(b.dataset.mode)));
    document.querySelectorAll("#nbinkw .wd").forEach((b) => (b.onclick = () => this.setWidth(+b.dataset.w)));
    $("nbinkundo").onclick = () => { if (this.strokes.pop()) { this.sel = []; this.draw(); dirty(); } };
    $("nbseldel").onclick = () => this.deleteSel();
    this.cv.addEventListener("pointerdown", (e) => this.down(e));
    this.cv.addEventListener("pointermove", (e) => this.move(e));
    for (const ev of ["pointerup", "pointercancel"]) this.cv.addEventListener(ev, (e) => this.up(e));
    this.cv.addEventListener("contextmenu", (e) => e.preventDefault());   // botón del lápiz
    this.cv.addEventListener("wheel", (e) => { e.preventDefault(); this.ta.scrollTop += e.deltaY; }, { passive: false });
    this.syncBar();
  },
  penOn() { return document.querySelector(".nbsheet").classList.contains("pen"); },
  setMode(m) {
    if (this.mode === "pen" || this.mode === "hl") { this.colors[this.mode] = this.color; this.widths[this.mode] = this.widthI; }
    if (m !== "lasso") this.clearSel();
    this.mode = m;
    if (m === "pen" || m === "hl") {
      this.color = this.colors[m] || (m === "hl" ? HLS[0] : INKS[0]);
      this.widthI = this.widths[m] ?? 1;
    }
    if (!this.penOn()) setPen(true); else this.syncBar();
  },
  setColor(col) {
    if (this.mode === "lasso" && this.sel.length) {           // pinta lo elegido
      for (const i of this.sel) this.strokes[i].c = col;
      this.draw(); dirty(); return;
    }
    if (this.mode !== "pen" && this.mode !== "hl") this.setMode("pen");
    this.color = this.colors[this.mode] = col;
    if (!this.penOn()) setPen(true); else this.syncBar();
  },
  setWidth(i) {
    if (this.mode !== "pen" && this.mode !== "hl") this.setMode("pen");
    this.widthI = this.widths[this.mode] = i;
    if (!this.penOn()) setPen(true); else this.syncBar();
  },
  syncBar() {
    const on = this.penOn(), drawing = on && (this.mode === "pen" || this.mode === "hl");
    $("nbkeys").classList.toggle("on", !on);
    document.querySelectorAll(".nbtools .tool[data-mode]").forEach((b) => b.classList.toggle("on", on && b.dataset.mode === this.mode));
    $("nbhlbar").setAttribute("fill", this.colors.hl || (this.mode === "hl" ? this.color : HLS[0]));
    const box = $("nbinks");
    box.innerHTML = "";
    for (const col of this.mode === "hl" ? HLS : INKS) {
      const b = document.createElement("button");
      b.type = "button"; b.className = "ink" + (drawing && col === this.color ? " on" : "");
      b.style.background = col;
      b.title = "Color";
      b.onclick = () => this.setColor(col);
      box.appendChild(b);
    }
    document.querySelectorAll("#nbinkw .wd").forEach((b) => b.classList.toggle("on", drawing && +b.dataset.w === this.widthI));
  },
  // selección (lazo)
  bounds() {
    if (!this.sel.length) return null;
    let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
    for (const i of this.sel) {
      const s = this.strokes[i], pad = s.w / 2;
      for (let j = 0; j < s.p.length; j += 2) {
        x0 = Math.min(x0, s.p[j] - pad); x1 = Math.max(x1, s.p[j] + pad);
        y0 = Math.min(y0, s.p[j + 1] - pad); y1 = Math.max(y1, s.p[j + 1] + pad);
      }
    }
    return [x0 - .25, y0 - .25, x1 + .25, y1 + .25];
  },
  inSel([x, y]) { const b = this.bounds(); return b && x >= b[0] - .1 && x <= b[2] + .1 && y >= b[1] - .1 && y <= b[3] + .1; },
  clearSel() { if (this.sel.length) { this.sel = []; this.draw(); } },
  deleteSel() {
    const drop = new Set(this.sel);
    this.strokes = this.strokes.filter((_, i) => !drop.has(i));
    this.sel = []; this.draw(); dirty();
  },
  closeLasso() {
    const p = this.lasso; this.lasso = null;
    const poly = [];
    for (let i = 0; i < p.length; i += 2) poly.push([p[i], p[i + 1]]);
    this.sel = poly.length < 3 ? [] : this.strokes.map((s, i) => {
      let n = 0;
      for (let j = 0; j < s.p.length; j += 2) if (inside(s.p[j], s.p[j + 1], poly)) n++;
      return n && n >= s.p.length / 2 * .6 ? i : -1;
    }).filter((i) => i >= 0);
    this.draw();
  },
  load(json) {
    try { this.strokes = json ? JSON.parse(json) : []; } catch { this.strokes = []; }
    this.cur = null; this.sel = []; this.lasso = null;
    this.fit();
  },
  dumps() { return this.strokes.length ? JSON.stringify(this.strokes) : ""; },
  fit() {
    const dpr = window.devicePixelRatio || 1;
    this.dpr = dpr;
    this.cv.width = Math.max(1, Math.round(this.ta.clientWidth * dpr));
    this.cv.height = Math.max(1, Math.round(this.ta.clientHeight * dpr));
    this.draw();
  },
  toLines(e) {
    const r = this.cv.getBoundingClientRect();
    const x = e.clientX - r.left, y = e.clientY - r.top + this.ta.scrollTop;
    return [Math.round((x - PAD_X) / LINE * 1000) / 1000, Math.round(y / LINE * 1000) / 1000];
  },
  draw() {
    if (!this.g) return;
    const g = this.g;
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.clearRect(0, 0, this.cv.width, this.cv.height);
    g.setTransform(this.dpr * LINE, 0, 0, this.dpr * LINE, this.dpr * PAD_X, -this.dpr * this.ta.scrollTop);
    const all = this.cur ? [...this.strokes, this.cur] : this.strokes;
    // El destacador, translúcido, va debajo de la tinta.
    for (const s of [...all.filter((s) => s.k === "hl"), ...all.filter((s) => s.k !== "hl")]) {
      const p = s.p, hl = s.k === "hl";
      g.globalAlpha = ALPHA[s.k] || 1;
      g.lineCap = hl ? "butt" : "round"; g.lineJoin = "round";
      g.strokeStyle = g.fillStyle = s.c;
      g.lineWidth = Math.max(.03, s.w * 2);
      g.beginPath();
      if (p.length <= 2) { g.arc(p[0], p[1], g.lineWidth / 2, 0, Math.PI * 2); g.fill(); continue; }
      g.moveTo(p[0], p[1]);
      for (let i = 2; i < p.length; i += 2) g.lineTo(p[i], p[i + 1]);
      g.stroke();
    }
    g.globalAlpha = 1;
    g.lineWidth = 1.5 / LINE; g.setLineDash([5 / LINE, 4 / LINE]); g.strokeStyle = "#1E88E5";
    if (this.lasso && this.lasso.length > 2) {
      g.beginPath(); g.moveTo(this.lasso[0], this.lasso[1]);
      for (let i = 2; i < this.lasso.length; i += 2) g.lineTo(this.lasso[i], this.lasso[i + 1]);
      g.closePath(); g.stroke();
    }
    const b = this.bounds(), del = $("nbseldel");
    if (b) {
      g.fillStyle = "rgba(30,136,229,.08)"; g.fillRect(b[0], b[1], b[2] - b[0], b[3] - b[1]);
      g.strokeRect(b[0], b[1], b[2] - b[0], b[3] - b[1]);
      del.hidden = false;
      del.style.left = `${PAD_X + b[2] * LINE - 17}px`;
      del.style.top = `${b[1] * LINE - this.ta.scrollTop - 17}px`;
    } else del.hidden = true;
    g.setLineDash([]);
  },
  // Botón del lápiz (barril, 2) o punta de goma (32): borra mientras se aprieta.
  penErasing(e) { return e.pointerType === "pen" && (e.buttons & 34) !== 0; },
  down(e) {
    this.cv.setPointerCapture(e.pointerId);
    this.pointers.set(e.pointerId, e.clientY);
    if (this.pointers.size > 1) { this.cur = this.lasso = this.drag = null; this.draw(); return; }  // dos dedos: desplazar
    this.erasing = this.mode === "erase" || this.penErasing(e);
    if (this.erasing) { this.eraseAt(e); return; }
    const pt = this.toLines(e);
    if (this.mode === "lasso") {
      if (this.inSel(pt)) { this.drag = pt; return; }          // arrastrar lo elegido
      this.sel = []; this.lasso = [...pt]; this.draw(); return;
    }
    this.clearSel();
    const hl = this.mode === "hl", w = WIDTHS[hl ? "hl" : "pen"][this.widthI];
    const k = !hl && e.pointerType === "pen" && e.pressure > 0 ? .55 + e.pressure * .9 : 1;
    this.cur = { c: this.color, w: Math.round(w * k * 1000) / 1000, p: pt };
    if (hl) this.cur.k = "hl";
    this.draw();
  },
  move(e) {
    if (!this.pointers.has(e.pointerId)) return;
    const prev = this.pointers.get(e.pointerId);
    this.pointers.set(e.pointerId, e.clientY);
    if (this.pointers.size > 1) { this.ta.scrollTop -= (e.clientY - prev) / this.pointers.size; return; }
    if (this.erasing) { this.eraseAt(e); return; }
    if (this.drag) {
      const [x, y] = this.toLines(e), dx = x - this.drag[0], dy = y - this.drag[1];
      this.drag = [x, y];
      for (const i of this.sel) this.strokes[i].p = this.strokes[i].p.map((v, j) => Math.round((v + (j % 2 ? dy : dx)) * 1000) / 1000);
      this.draw(); return;
    }
    if (this.lasso) { this.lasso.push(...this.toLines(e)); this.draw(); return; }
    if (!this.cur) return;
    for (const ev of e.getCoalescedEvents ? e.getCoalescedEvents() : [e]) {
      const [x, y] = this.toLines(ev), p = this.cur.p;
      if (Math.hypot(x - p[p.length - 2], y - p[p.length - 1]) * LINE >= 1.2) p.push(x, y);
    }
    this.draw();
  },
  up(e) {
    this.pointers.delete(e.pointerId);
    if (this.pointers.size) return;
    this.erasing = false;
    if (this.drag) { this.drag = null; dirty(); return; }
    if (this.lasso) { this.closeLasso(); return; }
    if (this.cur) { this.strokes.push(this.cur); this.cur = null; this.draw(); dirty(); }
  },
  eraseAt(e) {
    const [x, y] = this.toLines(e);
    const keep = this.strokes.filter((s) => {
      const r = .35 + (s.k === "hl" ? s.w / 2 : 0);
      return !s.p.some((v, i) => i % 2 === 0 && Math.abs(v - x) < r && Math.abs(s.p[i + 1] - y) < r);
    });
    if (keep.length !== this.strokes.length) { this.strokes = keep; this.sel = []; this.draw(); dirty(); }
  },
};

// ------------------------------------------------------------------ fotos pegadas en la hoja
// (= ui.notebook.Sticker) Lugar en renglones {x, y (centro), w (ancho), r (giro, grados
// antihorario como en la app)}: siguen al texto al desplazar la hoja.
const Sticker = {
  els: [],                 // [{el, p, pl, ratio}]
  init() {
    this.box = $("nbstickers");
    this.menu = $("nbstmenu");
    this.menu.onclick = (e) => {
      const b = e.target.closest("button");
      if (b && this.menuFor) this.action(b.dataset.a, this.menuFor);
      this.hideMenu();
    };
    document.addEventListener("pointerdown", (e) => { if (!e.target.closest(".nbstmenu")) this.hideMenu(); }, true);
  },
  ta() { return $("nbtext"); },
  count() { return this.els.length; },
  // En medio de lo que se ve, media hoja de ancho (las siguientes, un poco corridas).
  defaultPlace(i = 0, at = null) {
    const ta = this.ta();
    const cx = at ? at[0] : ta.clientWidth / 2, cy = at ? at[1] : ta.clientHeight / 2;
    const r3 = (v) => Math.round(v * 1000) / 1000;
    return { x: r3((cx + i * 18 - PAD_X) / LINE), y: r3((ta.scrollTop + cy + i * 18) / LINE),
      w: r3(ta.clientWidth * .45 / LINE), r: [-4, 3, -2, 5][i % 4] };
  },
  placeAt(e) {                  // punto donde se soltó una foto sobre la hoja (px de la hoja)
    const r = this.ta().getBoundingClientRect();
    return [e.clientX - r.left, e.clientY - r.top];
  },
  render() {
    this.hideMenu();
    this.box.innerHTML = "";
    this.els = [];
    const photos = (current()?.photos || []).filter((p) => Number(p.page || 0) === sheet);
    let free = 0;
    for (const p of photos) {
      const el = document.createElement("div");
      el.className = "nbst pending";
      el.title = "Arrastre para mover · esquina: tamaño · círculo: girar · clic: opciones";
      el.innerHTML = `<i class="hz rot"></i><i class="hz sz"></i>`;
      const it = { el, p, pl: C.notePlace(p) || this.defaultPlace(free++), ratio: .75 };
      this.els.push(it);
      this.box.appendChild(el);
      el.addEventListener("pointerdown", (e) => this.down(e, it));
      X.photoUrl(p.path).then((u) => {
        if (!u) { el.title = "La foto aún no está en Drive"; return; }
        const img = new Image();
        img.onload = () => { it.ratio = img.naturalHeight / img.naturalWidth || .75; it.url = u; this.position(); };
        img.src = u;
        el.classList.remove("pending");
        el.style.backgroundImage = `url(${u})`;
      });
    }
    this.position();
  },
  position() {
    const top = this.ta().scrollTop;
    for (const it of this.els) {
      const { x, y, w, r = 0 } = it.pl;
      const wp = w * LINE, hp = wp * it.ratio;
      Object.assign(it.el.style, { width: `${wp}px`, height: `${hp}px`, left: `${PAD_X + x * LINE - wp / 2}px`,
        top: `${y * LINE - top - hp / 2}px`, transform: `rotate(${-r}deg)` });
    }
  },
  // Arrastrar: mover; esquina: tamaño; círculo: giro; dos dedos: tamaño y giro; clic: menú.
  down(e, it) {
    if (Ink.penOn()) return;
    e.preventDefault(); e.stopPropagation();
    const el = it.el;
    const pts = it.pts ||= new Map();
    if (!it.active) {                               // nuevo gesto: al frente, sin dedos viejos
      pts.clear();
      if (this.box.lastElementChild !== el) this.box.appendChild(el);
    }
    el.classList.add("act");
    const r = el.getBoundingClientRect(), c = [r.left + r.width / 2, r.top + r.height / 2];
    const mode = e.target.classList.contains("sz") ? "size" : e.target.classList.contains("rot") ? "rot" : "move";
    pts.set(e.pointerId, [e.clientX, e.clientY]);
    const start = { mode: pts.size > 1 ? "pinch" : mode, c, pl: { ...it.pl }, p0: [e.clientX, e.clientY], t: Date.now(),
      d0: Math.hypot(e.clientX - c[0], e.clientY - c[1]) || 1, moved: false, pair: pts.size > 1 ? [...pts.values()] : null };
    it.start = start;
    const move = (ev) => {
      if (!pts.has(ev.pointerId)) return;
      pts.set(ev.pointerId, [ev.clientX, ev.clientY]);
      const s = it.start, r3 = (v) => Math.round(v * 1000) / 1000;
      if (Math.hypot(ev.clientX - s.p0[0], ev.clientY - s.p0[1]) > 4) s.moved = true;
      if (s.mode === "pinch" && pts.size > 1) {
        const [a, b] = [...pts.values()], [a0, b0] = s.pair;
        const k = Math.hypot(b[0] - a[0], b[1] - a[1]) / (Math.hypot(b0[0] - a0[0], b0[1] - a0[1]) || 1);
        const ang = Math.atan2(b[1] - a[1], b[0] - a[0]) - Math.atan2(b0[1] - a0[1], b0[0] - a0[0]);
        it.pl.w = r3(Math.max(1.5, Math.min(40, s.pl.w * k)));
        it.pl.r = Math.round((s.pl.r || 0) - ang * 180 / Math.PI);
      } else if (s.mode === "move") {
        it.pl.x = r3(s.pl.x + (ev.clientX - s.p0[0]) / LINE);
        it.pl.y = r3(s.pl.y + (ev.clientY - s.p0[1]) / LINE);
      } else if (s.mode === "size") {
        const k = Math.hypot(ev.clientX - s.c[0], ev.clientY - s.c[1]) / s.d0;
        it.pl.w = r3(Math.max(1.5, Math.min(40, s.pl.w * k)));
      } else if (s.mode === "rot") {
        const css = Math.atan2(ev.clientY - s.c[1], ev.clientX - s.c[0]) * 180 / Math.PI + 90;
        it.pl.r = Math.round(-css);
      }
      this.position();
    };
    const up = (ev) => {
      if (!pts.has(ev.pointerId)) return;
      pts.delete(ev.pointerId);
      if (pts.size) return;
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", up);
      it.active = false;
      el.classList.remove("act");
      const s = it.start;
      if (!s.moved && Date.now() - s.t < 450) this.showMenu(it, ev);
      else this.save(it);
    };
    if (!it.active) {                               // en la ventana: no se pierde el final
      it.active = true;
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", up);
      window.addEventListener("pointercancel", up);
    }
  },
  async save(it) {
    it.pl.r = ((Math.round((it.pl.r || 0) * 10) / 10) % 360 + 360) % 360;
    try {
      await X.send([C.notePhotoUpdate(it.p, { page: sheet, place: JSON.stringify(it.pl) })]);
      it.p = { ...it.p, page: sheet, place: JSON.stringify(it.pl) };
      $("nbsaved").textContent = "Guardado";
    } catch (e) { $("nbmsg").textContent = `No se guardó la foto: ${e.message}`; }
  },
  showMenu(it, ev) {
    const wrap = document.querySelector(".nbwrap").getBoundingClientRect();
    this.menuFor = it;
    this.menu.querySelector('[data-a="page"]').hidden = C.notePages(current()).length < 2;
    this.menu.hidden = false;
    this.menu.style.left = `${Math.min(ev.clientX - wrap.left, wrap.width - 230)}px`;
    this.menu.style.top = `${Math.min(ev.clientY - wrap.top, wrap.height - 130)}px`;
  },
  hideMenu() { if (this.menu) { this.menu.hidden = true; this.menuFor = null; } },
  async action(a, it) {
    if (a === "draw") {
      if (it.url) Draw.open(it.p, it.url); else $("nbmsg").textContent = "La foto aún no está en Drive.";
    } else if (a === "del") {
      if (!confirm("¿Quitar esta foto de la hoja?")) return;
      await X.send([{ entity: "notebook_photos", uid: it.p.uid, ts: C.nowTs(), deleted: 1 }]);
      renderPhotos();
    } else if (a === "page") {
      const n = C.notePages(current()).length;
      const k = Number(prompt(`¿A qué hoja (1 a ${n})?`, String(sheet === n - 1 ? 1 : sheet + 2)));
      if (!(k >= 1 && k <= n) || k - 1 === sheet) return;
      await X.send([C.notePhotoUpdate(it.p, { page: k - 1, place: JSON.stringify(this.defaultPlace()) })]);
      renderPhotos();
      $("nbmsg").textContent = `Foto pasada a la hoja ${k}.`;
    }
  },
};
