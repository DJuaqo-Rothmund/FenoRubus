// AeonCrop Web · IA de AeonScout (= scout_ai.py + scout_guide.py de la app): identifica las
// fotos con Pl@ntNet (malezas) y Gemini desde el navegador, muestra la ficha de la guía y la
// guía ilustrada de cómo sacar las fotos. Las claves quedan SOLO en este navegador. Un
// resultado sobre una foto ya respaldada se puede «Enviar a la app»: va a
// «AeonScout/identificaciones-web.json» y la app lo deja en la captura para aceptarlo.
// Datos (fichas, láminas y el texto de la consulta): scout/guia.json, generado desde la app.

export const PROVIDERS = { plantnet: "Pl@ntNet", gemini: "Gemini" };
export const ORDER = { malezas: ["plantnet", "gemini"], plagas: ["gemini"], enfermedades: ["gemini"] };   // = scout_ai.ORDER
const PLANTNET_URL = "https://my-api.plantnet.org/v2/identify/all";
const GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/";
const KEYS = "ac_ia_claves", OK_MODEL = "ac_gemini_ok";
const MAX_PHOTOS = 5, MAX_SIDE = 1280;

let G = null;                                  // scout/guia.json
export function setGuide(g) { G = g; }
export const loaded = () => !!G;
export async function guide() {
  if (!G) {
    const r = await fetch("scout/guia.json");
    if (!r.ok) throw new Error("No se encontró la guía de AeonScout (scout/guia.json).");
    G = await r.json();
  }
  return G;
}

// ------------------------------------------------------------------ lógica pura (probada)
export function norm(text) {                   // = scout_guide._norm
  return (text || "").normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase()
    .replace(/[^a-z0-9]+/g, " ").trim();
}

export function find(section, name = "", scientific = "") {   // = scout_guide.find
  const sci = norm(scientific), nm = norm(name);
  const pool = G.species.filter((s) => s.section === section);
  for (const s of pool) if (sci && norm(s.scientific) === sci) return s;
  for (const s of pool) if (nm && norm(s.name) === nm) return s;
  const genus = sci ? sci.split(" ")[0] : "";
  if (genus && genus !== "abiotico" && genus !== "virus") {
    for (const s of pool) {
      const w = norm(s.scientific).split(" ");
      if (w[0] === genus && (w.length === 1 || w[1] === "spp" || w[1] === "sp")) return s;
    }
  }
  return null;
}

export function cropsText(entry) {
  return [...entry.crops].map((ch) => G.crop_names[G.crops[ch]]).join(", ");
}

// Texto de la consulta: el mismo de la app (scout_ai.prompt), con lo de esta captura.
export function prompt(section, rec, views) {
  const crop = G.crop_names[rec.crop] ? rec.crop : "";
  const tpl = G.prompts[section][crop];
  const v = views.filter(Boolean).join(", ") || "sin indicar";
  return tpl.replace("§VISTAS§", v).replace("§ORGANO§", rec.organ || "sin indicar").replace("§NOTAS§", rec.notes || "—");
}

// Respuesta de cualquier servicio -> {provider, at, is_target, advice, notes, candidates} (= scout_ai.normalize,
// sin species_id: el catálogo es del teléfono).
const localNow = () => { const d = new Date(); return new Date(d - d.getTimezoneOffset() * 60000).toISOString().slice(0, 19); };
export function normalize(section, raw, provider, at = localNow()) {
  const stages = G.stages[section];
  const out = [];
  for (const c of (raw.candidates || []).slice(0, 3)) {
    if (!c || typeof c !== "object") continue;
    let name = (c.catalog_name || c.common_name || "").trim();
    let sci = (c.scientific_name || "").trim();
    const g = find(section, name, sci);
    const rank = (c.rank || "").toLowerCase();
    const exact = g && (norm(g.scientific) === norm(sci) || norm(g.name) === norm(name));
    if (g && (exact || ["género", "genero", "familia"].includes(rank) || !c.common_name)) {
      name = g.name;
      sci = sci || g.scientific;
    }
    let stage = (c.stage || "").trim();
    stage = stages.find((s) => s.toLowerCase() === stage.toLowerCase()) || "";
    const conf = Math.max(0, Math.min(1, Number(c.confidence) || 0));
    out.push({ name: name || sci || "?", scientific: sci, rank: c.rank || "", stage, confidence: conf, features: (c.features || "").trim() });
  }
  out.sort((a, b) => b.confidence - a.confidence);
  return { provider, at, is_target: raw.is_target !== false, advice: (raw.photo_advice || "").trim(), notes: (raw.notes || "").trim(), candidates: out };
}

export function parsePlantnet(code, j) {       // = la parte de respuesta de scout_ai.ask_plantnet
  if (code === 404) return { is_target: false, candidates: [], photo_advice: "", notes: "Pl@ntNet no reconoció la planta." };
  if (code === 429) throw new AIError("Pl@ntNet: se acabó la cuota de hoy.", "quota");
  if (code === 401 || code === 403) throw new AIError("Pl@ntNet: la clave no es válida (o este sitio no está autorizado en su cuenta).", "key");
  if (code !== 200) throw new AIError(`Pl@ntNet (${code}): ${j?.message || ""}`);
  return { is_target: true, photo_advice: "", notes: "", candidates: (j.results || []).slice(0, 3).map((r) => {
    const sp = r.species || {};
    return { common_name: (sp.commonNames || [""])[0], scientific_name: sp.scientificNameWithoutAuthor || "", rank: "especie",
      catalog_name: "", stage: "", confidence: Number(r.score) || 0, features: `Familia ${sp.family?.scientificNameWithoutAuthor || "?"}` };
  }) };
}

// Entradas de «identificaciones-web.json»: la nueva reemplaza la de la misma foto.
export function mergeEntries(old, entries) {
  const names = new Set(entries.map((e) => e.photo));
  return [...(Array.isArray(old) ? old : []).filter((e) => !names.has(e.photo)), ...entries];
}

export class AIError extends Error {
  constructor(msg, kind = "") { super(msg); this.kind = kind; }
}

// ------------------------------------------------------------------ claves (solo este navegador)
export function loadKeys() {
  try { return JSON.parse(localStorage.getItem(KEYS) || "{}") || {}; } catch { return {}; }
}
export function saveKeys(k) {
  const clean = Object.fromEntries(Object.entries(k).map(([a, b]) => [a, (b || "").trim()]).filter(([, b]) => b));
  try { localStorage.setItem(KEYS, JSON.stringify(clean)); } catch { /* sin almacenamiento */ }
  return clean;
}
export function chain(section) {
  const k = loadKeys();
  return (ORDER[section] || []).filter((p) => k[p]);
}

// ------------------------------------------------------------------ servicios
export async function prepare(blobs, maxSide = MAX_SIDE) {   // JPEG, lado mayor ≤ 1280 (= scout_ai.prepare)
  const out = [];
  for (const b of blobs.slice(0, MAX_PHOTOS)) {
    const bmp = await createImageBitmap(b);
    const k = Math.min(1, maxSide / Math.max(bmp.width, bmp.height));
    const c = document.createElement("canvas");
    c.width = Math.round(bmp.width * k); c.height = Math.round(bmp.height * k);
    c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
    out.push(await new Promise((res) => c.toBlob(res, "image/jpeg", 0.88)));
  }
  return out;
}

async function askPlantnet(key, images, organs) {
  const fd = new FormData();
  images.forEach((img, i) => { fd.append("images", img, `foto${i}.jpg`); fd.append("organs", organs[i] || "auto"); });
  let r;
  try {
    r = await fetch(`${PLANTNET_URL}?api-key=${encodeURIComponent(key)}&lang=es&nb-results=5`, { method: "POST", body: fd });
  } catch {
    throw new AIError(`Pl@ntNet no aceptó la consulta desde esta página. En my.plantnet.org › su cuenta › API, agregue «${location.hostname}» a los dominios autorizados (Authorized domains).`, "cors");
  }
  const j = await r.json().catch(() => ({}));
  return [parsePlantnet(r.status, j), j.remainingIdentificationRequests];
}

function geminiOrder() {
  let first = null;
  try { first = localStorage.getItem(OK_MODEL); } catch { /* nada */ }
  return [...(first ? [first] : []), ...G.gemini_models.filter((m) => m !== first)];
}

const toB64 = (blob) => new Promise((res) => { const fr = new FileReader(); fr.onload = () => res(String(fr.result).split(",")[1]); fr.readAsDataURL(blob); });

export async function askGemini(key, images, text, progress = () => {}, schema = null) {   // = scout_ai.ask_gemini
  await guide();
  const parts = [];
  for (const img of images) parts.push({ inline_data: { mime_type: img.type && !img.type.startsWith("image/") ? img.type : "image/jpeg", data: await toB64(img) } });
  parts.push({ text });
  const body = JSON.stringify({ contents: [{ role: "user", parts }],
    generationConfig: { responseMimeType: "application/json", responseSchema: schema || G.schema } });
  let quota = "";
  const errors = [];
  for (const model of geminiOrder()) {
    const short = model.replace("gemini-", "");
    progress(`Consultando a Gemini (${short})…`);
    let r;
    try {
      r = await fetch(`${GEMINI_URL}${model}:generateContent`, { method: "POST", body,
        headers: { "Content-Type": "application/json", "x-goog-api-key": key } });
    } catch { throw new AIError("Sin conexión con Gemini."); }
    const j = await r.json().catch(() => ({}));
    const msg = r.ok ? "" : (j.error?.message || "");
    if (r.status === 401 || r.status === 403 || (r.status === 400 && /api key/i.test(msg))) throw new AIError(`Gemini: la clave no es válida (${msg.slice(0, 120)}).`, "key");
    if (r.status === 429 && /limit:\s?0/.test(msg)) { errors.push(`${short}: sin nivel gratuito`); continue; }
    if (r.status === 429) { quota = msg; errors.push(`${short}: sin cuota`); continue; }
    if (!r.ok) { errors.push(`${short}: ${r.status} ${msg.slice(0, 80)}`); continue; }
    let out;
    try { out = JSON.parse((j.candidates[0].content.parts || []).map((p) => p.text || "").join("")); } catch {
      throw new AIError(`Gemini no dio una respuesta válida (${j.promptFeedback?.blockReason || j.candidates?.[0]?.finishReason || "?"}).`);
    }
    try { localStorage.setItem(OK_MODEL, model); } catch { /* nada */ }
    return out;
  }
  if (quota && errors.every((e) => e.endsWith("sin cuota"))) throw new AIError(`Gemini: sin cuota gratuita por ahora (${quota.slice(0, 140)}).`, "quota");
  throw new AIError(`Gemini: ningún modelo respondió · ${errors.join(" · ").slice(0, 300)}`);
}

// rec: {section, crop, organ, notes}; photos: [{blob, view}]. Igual que scout_ai.identify.
export async function identify(rec, photos, progress = () => {}) {
  await guide();
  const section = rec.section;
  const providers = chain(section);
  if (!providers.length) throw new AIError(`Falta la clave de ${section === "malezas" ? "Pl@ntNet o Gemini" : "Gemini"}: póngala en «Claves de IA».`, "nokey");
  progress("Preparando las fotos…");
  const images = await prepare(photos.map((p) => p.blob));
  const views = photos.slice(0, MAX_PHOTOS).map((p) => p.view || "");
  const keys = loadKeys();
  let weak = null, last = null;
  for (const prov of providers) {
    try {
      if (prov === "plantnet") {
        progress("Consultando a Pl@ntNet…");
        const [raw, remaining] = await askPlantnet(keys.plantnet, images, views.map((v) => G.plantnet_organs[v] || "auto"));
        const res = normalize(section, raw, prov);
        res.remaining = remaining;
        if ((res.candidates[0]?.confidence || 0) >= G.plantnet_min) return res;
        if (res.candidates.length) weak = res;           // segunda opinión con Gemini
        continue;
      }
      const raw = await askGemini(keys.gemini, images, prompt(section, rec, views), progress);
      return normalize(section, raw, prov);
    } catch (e) {
      last = e;
      if (e.kind === "quota" && prov !== "plantnet") break;
    }
  }
  if (weak) return weak;
  throw last || new AIError("Ningún servicio disponible.");
}

// Prueba corta de las claves (= scout_ai.test_keys, sin fotos).
export async function testKeys(progress = () => {}) {
  await guide();
  const k = loadKeys(), out = [];
  if (k.gemini) {
    try {
      progress("Probando Gemini…");
      const r = await fetch(`${GEMINI_URL.replace(/\/$/, "")}?pageSize=50`, { headers: { "x-goog-api-key": k.gemini } });
      if (!r.ok) throw new AIError(r.status === 400 || r.status === 403 ? "la clave no es válida" : `error ${r.status}`);
      const names = new Set(((await r.json()).models || []).map((m) => m.name.replace("models/", "")));
      const ok = G.gemini_models.filter((m) => names.has(m));
      out.push(`Gemini: clave válida · modelos gratuitos disponibles: ${ok.join(", ") || "ninguno de la lista"}.`);
    } catch (e) { out.push(`Gemini: ${e.message}`); }
  } else out.push("Gemini: sin clave.");
  if (k.plantnet) {
    try {
      progress("Probando Pl@ntNet…");
      const r = await fetch(`https://my-api.plantnet.org/v2/projects?api-key=${encodeURIComponent(k.plantnet)}&lang=es`);
      out.push(r.ok ? "Pl@ntNet: clave válida." : `Pl@ntNet: ${r.status === 401 || r.status === 403 ? "la clave no es válida" : `error ${r.status}`}.`);
    } catch {
      out.push(`Pl@ntNet: no acepta consultas desde esta página. En my.plantnet.org › su cuenta › API, agregue «${location.hostname}» a los dominios autorizados.`);
    }
  } else out.push("Pl@ntNet: sin clave (solo se usa en malezas).");
  return out;
}
