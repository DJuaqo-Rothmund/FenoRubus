// Dictado de datos a una planilla (= voice.py): en la web se sube un archivo de audio, Gemini lo
// transcribe (números con dígitos) y luego se ubica cada número en su celda, a mano o con la IA.
import * as AI from "./scout_ai.js";

export const NUM_RE = /(?<![A-Za-z\d])\d+(?:[.,]\d+)?(?![A-Za-z\d])/g;
export const TRANSCRIBE_PROMPT = "Transcribe en español este audio: es una persona dictando datos de un ensayo agrícola en terreno "
  + "(tratamientos, repeticiones, plantas y mediciones). Escribe TODOS los números con dígitos (12, 45, "
  + "3,5), con coma decimal. Escribe los códigos de parcela como T0R1, T3R2 (ej. «te cero erre uno» -> "
  + "T0R1). No resumas ni inventes: transcribe lo que se dice, en orden.";
const TRANSCRIBE_SCHEMA = { type: "OBJECT", required: ["text"], properties: { text: { type: "STRING" } } };

export function numbers(text) {
  return [...String(text || "").matchAll(NUM_RE)].map((m) => [m.index, m.index + m[0].length, m[0]]);
}
export function arrangePrompt(text, rows, cols) {
  return "Transcripción de un dictado de datos de terreno:\n«" + text + "»\n\n"
    + "Ubica cada dato dictado en la planilla. Filas posibles (exactas): " + rows.join(" | ") + ".\n"
    + "Columnas posibles (exactas): " + cols.join(" | ") + ".\n"
    + "Reglas: usa SOLO valores que se dijeron (con dígitos, coma decimal); si el dictado dice «planta 2» "
    + "y hay columnas «Planta 2 · …», úsalas; si no se puede saber la fila o la columna de un número, no "
    + "lo incluyas. Entrega una lista de {row, col, value}.";
}
export const arrangeSchema = (rows, cols) => ({ type: "ARRAY", items: { type: "OBJECT", required: ["row", "col", "value"], properties: {
  row: { type: "STRING", enum: rows }, col: { type: "STRING", enum: cols }, value: { type: "STRING" } } } });

export function cleanArrange(raw, rows, cols) {
  const out = [], seen = new Set();
  for (const it of Array.isArray(raw) ? raw : []) {
    const r = String(it?.row ?? ""), c = String(it?.col ?? ""), v = String(it?.value ?? "").replace(/\s/g, "");
    if (!rows.includes(r) || !cols.includes(c) || !/^\d+(?:[.,]\d+)?$/.test(v) || seen.has(r + "|" + c)) continue;
    seen.add(r + "|" + c);
    out.push({ row: r, col: c, value: v });
  }
  return out;
}

function key() {
  const k = AI.loadKeys().gemini;
  if (!k) throw new AI.AIError("Falta la clave de Gemini: AeonScout › 🔑 Claves de IA (es gratis).", "nokey");
  return k;
}
export async function transcribe(file, progress = () => {}) {
  if (file.size > 18 * 1024 * 1024) throw new Error("El audio es muy largo para transcribirlo de una vez (máx. ~18 MB): divídalo.");
  const ext = (file.name || "").toLowerCase().split(".").pop();
  const MIME = { m4a: "audio/mp4", mp4: "audio/mp4", aac: "audio/aac", mp3: "audio/mpeg", wav: "audio/wav", ogg: "audio/ogg",
    oga: "audio/ogg", opus: "audio/ogg", webm: "audio/webm", flac: "audio/flac", "3gp": "audio/3gpp", amr: "audio/amr" };
  const type = MIME[ext] || (file.type && !/x-m4a/.test(file.type) ? file.type : "audio/mp4");
  const out = await AI.askGemini(key(), [new Blob([file], { type })], TRANSCRIBE_PROMPT, progress, TRANSCRIBE_SCHEMA);
  return String(out?.text || "").trim();
}
export async function arrange(text, rows, cols, progress = () => {}) {
  if (!rows.length || !cols.length) return [];
  const raw = await AI.askGemini(key(), [], arrangePrompt(text, rows, cols), progress, arrangeSchema(rows, cols));
  return cleanArrange(raw, rows, cols);
}
