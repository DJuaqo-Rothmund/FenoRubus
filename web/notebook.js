// PhenoRubus Web · Cuaderno de campo (= ui/notebook.py): línea de tiempo por día, página con
// texto que se guarda solo, fotos (arrastrar o elegir) y lápiz sobre la foto (mouse, dedo o
// lápiz con presión). Usa las mismas tablas que la app (notebook_entries / notebook_photos).
import * as C from "./core.js";

const $ = (id) => document.getElementById(id);
const WEEKDAYS = ["domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"];
const PEN_COLORS = ["#E53935", "#FFD54F", "#FFFFFF", "#212121", "#43A047"];
const PEN_WIDTHS = [["Fino", 2.5], ["Medio", 5], ["Grueso", 10]];
let X = null;                     // {S, send, photoUrl, uploadPhoto, resize, render}
let page = null;                  // día abierto
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
  $("nbtext").oninput = () => {
    $("nbsaved").textContent = "Escribiendo…";
    clearTimeout(saveTimer);
    saveTimer = setTimeout(saveText, 1500);
  };
  $("nbpage").addEventListener("close", () => { saveText(); renderNotebook(); });
  $("nbdate").onchange = (e) => moveTo(e.target.value);
  $("nbdel").onclick = deletePage;
  const zone = $("nbdrop"), input = zone.querySelector("input");
  zone.onclick = (e) => { if (!e.target.closest(".ph")) input.click(); };
  input.onclick = (e) => e.stopPropagation();
  input.onchange = () => { const l = [...input.files]; input.value = ""; addPhotos(l); };
  zone.ondragover = (e) => { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; zone.classList.add("over"); };
  zone.ondragleave = (e) => { if (!zone.contains(e.relatedTarget)) zone.classList.remove("over"); };
  zone.ondrop = (e) => { e.preventDefault(); zone.classList.remove("over"); addPhotos([...e.dataTransfer.files]); };
  Draw.init();
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
      <div class="nbtxt">${esc(excerpt(d.text)) || '<span class="muted">Sin texto</span>'}</div><div class="nbstrip"></div></div>`;
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

export function openPage(day) {
  page = day;
  const cur = current();
  $("nbtitle").textContent = niceDay(day);
  $("nbdate").value = day;
  $("nbtext").value = cur?.text || "";
  $("nbsaved").textContent = cur ? "Guardado" : "";
  $("nbmsg").textContent = "";
  renderPhotos();
  if (!$("nbpage").open) $("nbpage").showModal();
  $("nbtext").focus();
}

async function ensureEntry(fields = {}) {      // la página se crea al escribir o subir la primera foto
  const r = C.noteChange(X.S.state, page, fields);
  await X.send([r.change]);
  return r.uid;
}

async function saveText() {
  clearTimeout(saveTimer);
  if (!page) return;
  const text = $("nbtext").value;
  const cur = current();
  if ((cur?.text || "") === text) { if (cur) $("nbsaved").textContent = "Guardado"; return; }
  try { await ensureEntry({ text }); $("nbsaved").textContent = "Guardado"; }
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
  if (!confirm(`¿Borrar la página del ${niceDay(page, false)} con su texto y fotos?\n(Los archivos de fotos quedan en Drive.)`)) return;
  clearTimeout(saveTimer);
  await X.send(C.noteDeleteChanges(X.S.state, page));
  page = null;
  $("nbpage").close();
}

function renderPhotos() {
  const grid = $("nbphotos");
  grid.innerHTML = "";
  const photos = current()?.photos || [];
  $("nbdrop").classList.toggle("has", photos.length > 0);
  for (const p of photos) {
    const d = document.createElement("div");
    d.className = "ph pending";
    d.title = "Dibujar sobre la foto";
    d.innerHTML = `<em>Buscando…</em><b class="nbpen ${p.annotated ? "on" : ""}">✎</b><button type="button" class="pdel" title="Quitar de la página">✕</button>`;
    d.querySelector(".pdel").onclick = async (e) => {
      e.stopPropagation();
      if (!confirm("¿Quitar esta foto de la página?")) return;
      await X.send([{ entity: "notebook_photos", uid: p.uid, ts: C.nowTs(), deleted: 1 }]);
      renderPhotos();
    };
    grid.appendChild(d);
    X.photoUrl(p.path).then((u) => {
      const em = d.querySelector("em");
      if (!u) { em.textContent = "Aún no está en Drive"; return; }
      em.remove();
      d.classList.remove("pending");
      d.style.backgroundImage = `url(${u})`;
      d.onclick = (e) => { e.stopPropagation(); Draw.open(p, u); };
    });
  }
}

async function addPhotos(files) {
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
    let n = 1;
    for (const f of files) {
      let name;
      do { name = `${stem}-w${n++}.jpg`; } while (taken.has(name));
      taken.add(name);
      $("nbmsg").textContent = `Subiendo ${name}…`;
      await X.uploadPhoto(page, name, await X.resize(f));
      changes.push(C.notePhotoChange(uid, `photos/cuaderno/${name}`));
    }
    await X.send(changes);
    $("nbmsg").textContent = `${files.length} foto(s) subida(s). Haga clic en una para dibujar sobre ella.`;
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
