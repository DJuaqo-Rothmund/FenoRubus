// AeonCrop Web · «Aeon IA»: la IA interna (detector de estructuras entrenado con las marcas de
// IA+, tools/train_ia_v1.ipynb) corriendo en el navegador con ONNX Runtime Web. Sin internet
// para la IA, sin clave y sin costo: el modelo se baja una vez de Drive
// («…/Entrenamiento IA/modelos/<versión>/detector_<versión>.onnx» + model.json) y queda guardado.
//
// Entrada: foto RGB 0–1 en un cuadrado imgsz×imgsz (letterbox, relleno gris 114).
// Salida YOLOv8: [1, 4 + nc, N] → (cx, cy, w, h en píxeles del cuadrado, luego un puntaje por clase).
const ORT_VER = "1.20.1";
const ORT_URL = `https://cdn.jsdelivr.net/npm/onnxruntime-web@${ORT_VER}/dist/`;
export const CONF = 0.25;          // puntaje mínimo para sugerir una caja
export const IOU = 0.5;            // cajas de la misma clase que se tapan más que esto: queda una
export const MAX_BOXES = 150;

let ortP = null;
async function ort() {
  ortP ||= import(`${ORT_URL}ort.wasm.min.mjs`).then((m) => {
    const o = m.default || m;
    o.env.wasm.wasmPaths = ORT_URL;
    o.env.wasm.numThreads = self.crossOriginIsolated ? Math.min(4, navigator.hardwareConcurrency || 1) : 1;
    return o;
  }).catch((e) => { ortP = null; throw new Error(`No se pudo cargar el motor de la IA (${e.message})`); });
  return ortP;
}

// Modelo listo para usar: {meta, session}. bytes: ArrayBuffer del .onnx.
export async function loadModel(meta, bytes) {
  const o = await ort();
  const session = await o.InferenceSession.create(new Uint8Array(bytes), { executionProviders: ["wasm"] });
  return { meta, session, o };
}

// Foto (HTMLImageElement / ImageBitmap, ya derecha) → tensor letterbox y la escala usada.
function prepare(img, S) {
  const W = img.naturalWidth || img.width, H = img.naturalHeight || img.height;
  const k = Math.min(S / W, S / H);
  const w = Math.round(W * k), h = Math.round(H * k);
  const px = Math.floor((S - w) / 2), py = Math.floor((S - h) / 2);
  const cv = document.createElement("canvas");
  cv.width = S; cv.height = S;
  const g = cv.getContext("2d", { willReadFrequently: true });
  g.fillStyle = "rgb(114,114,114)";
  g.fillRect(0, 0, S, S);
  g.drawImage(img, px, py, w, h);
  const rgba = g.getImageData(0, 0, S, S).data;
  const n = S * S, out = new Float32Array(3 * n);
  for (let i = 0; i < n; i++) {
    out[i] = rgba[i * 4] / 255;
    out[n + i] = rgba[i * 4 + 1] / 255;
    out[2 * n + i] = rgba[i * 4 + 2] / 255;
  }
  return { data: out, k, px, py, W, H };
}

function iou(a, b) {
  const ix = Math.max(0, Math.min(a.x1, b.x1) - Math.max(a.x0, b.x0));
  const iy = Math.max(0, Math.min(a.y1, b.y1) - Math.max(a.y0, b.y0));
  const inter = ix * iy;
  const u = (a.x1 - a.x0) * (a.y1 - a.y0) + (b.x1 - b.x0) * (b.y1 - b.y0) - inter;
  return u > 0 ? inter / u : 0;
}

// Cajas sugeridas para la foto: [{c, x, y, w, h, s: "aeon", p}] (x, y, w, h de 0 a 1).
// keys: claves de las clases que se usan hoy (las demás del modelo se ignoran, p. ej. «lateral»).
export async function detect(model, img, keys, { conf = CONF } = {}) {
  const { meta, session, o } = model;
  const S = meta.imgsz || 640;
  const classes = meta.classes || [];
  const t = prepare(img, S);
  const feeds = { [session.inputNames[0]]: new o.Tensor("float32", t.data, [1, 3, S, S]) };
  const res = await session.run(feeds);
  const out = res[session.outputNames[0]];
  const [, rows, N] = out.dims;                 // [1, 4 + nc, N]
  const d = out.data, nc = rows - 4;
  const cand = [];
  for (let j = 0; j < N; j++) {
    let best = -1, ci = -1;
    for (let c = 0; c < nc; c++) {
      const v = d[(4 + c) * N + j];
      if (v > best) { best = v; ci = c; }
    }
    if (best < conf || !keys.includes(classes[ci])) continue;
    const cx = d[j], cy = d[N + j], w = d[2 * N + j], h = d[3 * N + j];
    const x0 = (cx - w / 2 - t.px) / t.k, y0 = (cy - h / 2 - t.py) / t.k;
    const x1 = (cx + w / 2 - t.px) / t.k, y1 = (cy + h / 2 - t.py) / t.k;
    cand.push({ c: classes[ci], p: best, x0: Math.max(0, x0), y0: Math.max(0, y0),
      x1: Math.min(t.W, x1), y1: Math.min(t.H, y1) });
  }
  cand.sort((a, b) => b.p - a.p);
  const keep = [];
  for (const b of cand) {
    if (keep.some((k) => k.c === b.c && iou(k, b) > IOU)) continue;
    keep.push(b);
    if (keep.length >= MAX_BOXES) break;
  }
  const r4 = (v) => Math.round(v * 10000) / 10000;
  return keep.filter((b) => b.x1 - b.x0 > 2 && b.y1 - b.y0 > 2).map((b) => ({
    c: b.c, x: r4(b.x0 / t.W), y: r4(b.y0 / t.H), w: r4((b.x1 - b.x0) / t.W), h: r4((b.y1 - b.y0) / t.H),
    s: "aeon", p: Math.round(b.p * 100) / 100 }));
}
