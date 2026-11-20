// PhenoRubus Web · informes en PDF idénticos a los de la app: el mismo código Python
// (reporter.py / pdf_report.py, empaquetado en py.zip) corre con Pyodide en un Web Worker
// (pdf-worker.js) sobre una base SQLite armada con los paquetes de sincronización.
const PYODIDE = window.__PR_PYODIDE__ || "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/";
let worker = null, seq = 0;
const jobs = new Map();

// Si el generador se cae (p. ej. sin memoria), los trabajos pendientes terminan con un aviso
// en vez de quedarse esperando para siempre; el próximo informe parte con uno nuevo.
function crashed(e) {
  const msg = "El generador de informes se cerró (poca memoria en el navegador). Cierre otras pestañas y pruebe de nuevo; "
    + "si se repite, en «Ajustar» desactive «Todas las fotos» o la galería paralela.";
  console.error("pdf-worker", e);
  for (const job of jobs.values()) job.reject(new Error(msg));
  jobs.clear();
  try { worker?.terminate(); } catch { /* ya cerrado */ }
  worker = null;
}

function call(msg, handlers = {}) {
  if (!worker) {
    worker = new Worker("pdf-worker.js", { type: "module" });
    worker.onerror = crashed;
    worker.onmessageerror = crashed;
  }
  worker.onmessage = ({ data: m }) => {
    const job = jobs.get(m.id);
    if (!job) return;
    if (m.progress) return job.progress?.(m.progress);
    if (m.need) return job.need(m.need, m.id);
    jobs.delete(m.id);
    m.error ? job.reject(new Error(m.error)) : job.resolve(m);
  };
  const id = ++seq;
  return new Promise((resolve, reject) => {
    jobs.set(id, { resolve, reject, ...handlers });
    worker.postMessage({ id, indexURL: PYODIDE, ...msg });
  });
}

export function warm() { return call({ op: "warm" }); }

// Consulta corta al código de la app (temperaturas del predio). extra: [{ws, bundles}] de otros
// ensayos/predios que necesita; file: {name, buf}. Devuelve el JSON ya leído.
export async function py(fn, args, { extra = [], crop, file = null, text = "", progress } = {}) {
  const r = await call({ op: "py", fn, args, extra, crop, file, text }, { progress });
  return JSON.parse(r.json);
}

// ctx: {ws, bundles, crop (módulo), plain (PDF simple), cfg (configuración de informes): [[nombre, paquete]…], photoBlob(path) -> Blob|null, progress(texto)}
export async function makePdf(ctx, kind, arg, season) {
  const r = await call({ op: "pdf", ws: ctx.ws, bundles: ctx.bundles, extra: ctx.extra || [], kind, arg, season,
    crop: ctx.crop, plain: !!ctx.plain, cfg: ctx.cfg || null, labels: ctx.labels || null }, {
    progress: ctx.progress,
    need: async (paths, jid) => {
      const out = [];
      let done = 0;
      const todo = [...paths];
      const run = async () => {
        while (todo.length) {
          const rel = todo.shift();
          const blob = await ctx.photoBlob(rel).catch(() => null);
          if (blob) out.push([rel, await blob.arrayBuffer()]);
          ctx.progress(`Descargando fotos ${++done}/${paths.length}…`);
        }
      };
      await Promise.all([run(), run(), run(), run(), run(), run()]);
      worker.postMessage({ op: "photos", id: jid, photos: out }, out.map(([, b]) => b));
    },
  });
  const type = r.name.endsWith(".xlsx") ? "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" : "application/pdf";
  return { name: r.name, blob: new Blob([r.pdf], { type }) };
}
