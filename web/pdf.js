// PhenoRubus Web · informes en PDF idénticos a los de la app: el mismo código Python
// (reporter.py / pdf_report.py, empaquetado en py.zip) corre con Pyodide en un Web Worker
// (pdf-worker.js) sobre una base SQLite armada con los paquetes de sincronización.
const PYODIDE = window.__PR_PYODIDE__ || "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/";
let worker = null, seq = 0;
const jobs = new Map();

function call(msg, handlers = {}) {
  worker ||= new Worker("pdf-worker.js", { type: "module" });
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

// ctx: {ws, bundles: [[nombre, paquete]…], photoBlob(path) -> Blob|null, progress(texto)}
export async function makePdf(ctx, kind, arg, season) {
  const r = await call({ op: "pdf", ws: ctx.ws, bundles: ctx.bundles, kind, arg, season }, {
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
  return { name: r.name, blob: new Blob([r.pdf], { type: "application/pdf" }) };
}
