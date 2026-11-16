// AeonCrop Web · cajas automáticas (sugeridas) con Gemini sobre una foto de detalle
// (= box_ai.py de la app): botones, flores y frutos por estadio. La persona revisa, cambia el
// tipo de cada caja y borra o agrega las que falten. Usa la clave de Gemini de AeonScout
// (guardada solo en este navegador).
import * as AI from "./scout_ai.js";

export const MAX_BOXES = 150;
export const DESCRIPTIONS = {         // = box_ai.DESCRIPTIONS
  yema: "yema cerrada en la caña o tallo",
  brote: "brote vegetativo nuevo (hojas pequeñas)",
  lateral: "lateral: rama florífera que sale de la caña",
  upright: "brote vertical (upright) de cranberry",
  estolon: "estolón (guía rastrera) de cranberry",
  boton: "botón floral cerrado, verde",
  boton_blanco: "botón floral blanco a punto de abrir",
  racimo: "racimo floral de arándano (varias flores cerradas juntas)",
  gancho: "gancho: botón floral curvado de cranberry",
  flor: "flor abierta",
  flor_pasada: "flor pasada: pétalos caídos o secos, aún sin fruto formado",
  fruto_verde: "fruto verde (cuajado, sin color)",
  fruto_pinton: "fruto que empieza a tomar color (pintón / rosado / blush)",
  fruto_maduro: "fruto maduro de color pleno",
};

export function schema(keys) {
  return { type: "ARRAY", items: { type: "OBJECT", required: ["box_2d", "label"], properties: {
    box_2d: { type: "ARRAY", items: { type: "INTEGER" } }, label: { type: "STRING", enum: [...keys] } } } };
}

export function prompt(classes, cropName = "") {     // = box_ai.prompt
  const lines = classes.map(([k, n]) => `- ${k}: ${n} — ${DESCRIPTIONS[k] || n}`).join("\n");
  return `Foto de detalle de una planta de ${cropName || "berries"}. Marca con una caja ajustada CADA ` +
    "estructura de estas clases que se vea (también las parcialmente tapadas o pequeñas):\n" +
    `${lines}\n\n` +
    "No marques hojas ni tallos sueltos, ni lo que esté fuera de foco al fondo. Una caja por " +
    "estructura (no agrupes varias). Para cada una entrega box_2d = [ymin, xmin, ymax, xmax] " +
    `normalizado de 0 a 1000 y label con la clave exacta. Máximo ${MAX_BOXES} cajas.`;
}

const r4 = (v) => Math.round(v * 10000) / 10000;
const clip = (v) => Math.max(0, Math.min(1, v));
export function toBoxes(raw, keys) {                  // = box_ai.to_boxes
  const out = [];
  for (const it of Array.isArray(raw) ? raw : []) {
    const b = it?.box_2d;
    if (!Array.isArray(b) || b.length < 4 || b.slice(0, 4).some((v) => !Number.isFinite(Number(v)))) continue;
    if (!keys.includes(it.label)) continue;
    let [y0, x0, y1, x1] = b.slice(0, 4).map((v) => Number(v) / 1000);
    [x0, x1] = [clip(x0), clip(x1)].sort((a, c) => a - c);
    [y0, y1] = [clip(y0), clip(y1)].sort((a, c) => a - c);
    if (x1 - x0 < 0.004 || y1 - y0 < 0.004) continue;
    out.push({ c: it.label, x: r4(x0), y: r4(y0), w: r4(x1 - x0), h: r4(y1 - y0), s: "ia" });
  }
  return out.slice(0, MAX_BOXES);
}

export function iou(a, b) {
  const ix = Math.max(0, Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x));
  const iy = Math.max(0, Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y));
  const inter = ix * iy, union = a.w * a.h + b.w * b.h - inter;
  return union > 0 ? inter / union : 0;
}
export function merge(existing, add, thr = 0.5) {    // las de la persona mandan
  return [...existing, ...add.filter((n) => existing.every((e) => iou(n, e) < thr))];
}

// Cajas sugeridas para la foto (blob). classes: [[clave, nombre, color]].
export async function suggest(blob, classes, cropName, progress = () => {}) {
  const key = AI.loadKeys().gemini;
  if (!key) throw new AI.AIError("Falta la clave de Gemini: AeonScout › 🔑 Claves de IA (es gratis).", "nokey");
  progress("Preparando la foto…");
  const imgs = await AI.prepare([blob], 1600);
  const keys = classes.map(([k]) => k);
  const raw = await AI.askGemini(key, imgs, prompt(classes, cropName), progress, schema(keys));
  return toBoxes(raw, keys);
}
