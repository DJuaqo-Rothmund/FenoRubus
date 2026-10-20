// PhenoRubus Web · informes en PDF idénticos a los de la app: el mismo código Python
// (reporter.py / pdf_report.py, empaquetado en py.zip) corre en el navegador con Pyodide
// sobre una base SQLite armada con los paquetes de sincronización.
const PYODIDE = window.__PR_PYODIDE__ || "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/";
let booting = null;

export function warm() {                  // se carga una vez (~10 MB, queda en caché del navegador)
  booting ||= (async () => {
    const { loadPyodide } = await import(`${PYODIDE}pyodide.mjs`);
    const py = await loadPyodide({ indexURL: PYODIDE });
    await py.loadPackage(["sqlite3", "jinja2", "pillow"]);
    const zip = await (await fetch(`py.zip?v=${Date.now() >> 22}`)).arrayBuffer();
    py.unpackArchive(zip, "zip", { extractDir: "/app" });
    py.runPython("import os, sys; sys.path.insert(0, '/app'); os.environ['FENORUBUS_DATA'] = '/data'; os.makedirs('/data', exist_ok=True)");
    return { py, wr: py.pyimport("webreport") };
  })();
  booting.catch(() => { booting = null; });
  return booting;
}

// ctx: {ws, bundles: [[nombre, paquete]…], photoBlob(path) -> Blob|null, progress(texto)}
export async function makePdf(ctx, kind, arg, season) {
  ctx.progress("Cargando el generador de informes (la primera vez tarda un poco)…");
  const { py, wr } = await warm();
  ctx.progress("Preparando los datos…");
  wr.load(ctx.ws.code, JSON.stringify(ctx.ws), JSON.stringify(ctx.bundles));
  const paths = kind === "treatments" ? [] : JSON.parse(wr.photos(ctx.ws.code, kind, arg, season));
  const todo = [...new Set(paths)].filter((p) => !py.FS.analyzePath(`/data/${p}`).exists);
  let done = 0;
  const worker = async () => {
    while (todo.length) {
      const rel = todo.shift();
      const blob = await ctx.photoBlob(rel).catch(() => null);
      if (blob) {
        const file = `/data/${rel}`;
        py.FS.mkdirTree(file.slice(0, file.lastIndexOf("/")));
        py.FS.writeFile(file, new Uint8Array(await blob.arrayBuffer()));
      }
      ctx.progress(`Descargando fotos ${++done}/${done + todo.length}…`);
    }
  };
  await Promise.all([worker(), worker(), worker(), worker()]);
  ctx.progress("Generando el PDF…");
  await new Promise((r) => setTimeout(r, 30));        // deja pintar el mensaje
  const path = wr.report(ctx.ws.code, kind, arg, season);
  const data = py.FS.readFile(path);
  py.FS.unlink(path);
  return { name: path.split("/").pop(), blob: new Blob([data], { type: "application/pdf" }) };
}
