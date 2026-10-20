// PhenoRubus Web · generador de PDF en segundo plano (Web Worker): Pyodide y el código de
// informes de la app (py.zip) corren aquí, así la página nunca se congela.
let booting = null;

function boot(indexURL) {
  booting ||= (async () => {
    const { loadPyodide } = await import(`${indexURL}pyodide.mjs`);
    const py = await loadPyodide({ indexURL });
    await py.loadPackage(["sqlite3", "jinja2", "pillow"]);
    const zip = await (await fetch(`py.zip?v=${Date.now() >> 22}`)).arrayBuffer();
    py.unpackArchive(zip, "zip", { extractDir: "/app" });
    py.runPython("import os, sys; sys.path.insert(0, '/app'); os.environ['FENORUBUS_DATA'] = '/data'; os.makedirs('/data', exist_ok=True)");
    return { py, wr: py.pyimport("webreport") };
  })();
  booting.catch(() => { booting = null; });
  return booting;
}

const waiting = new Map();                // id -> resolve (fotos pedidas a la página)

self.onmessage = async ({ data: m }) => {
  if (m.op === "photos") { waiting.get(m.id)?.(m.photos); waiting.delete(m.id); return; }
  const say = (progress) => self.postMessage({ id: m.id, progress });
  try {
    if (m.op === "warm") { await boot(m.indexURL); self.postMessage({ id: m.id, done: true }); return; }
    say("Cargando el generador de informes (la primera vez tarda un poco)…");
    const { py, wr } = await boot(m.indexURL);
    say("Preparando los datos…");
    wr.load(m.ws.code, JSON.stringify(m.ws), JSON.stringify(m.bundles));
    const paths = m.kind === "treatments" ? [] : JSON.parse(wr.photos(m.ws.code, m.kind, m.arg, m.season));
    const need = [...new Set(paths)].filter((p) => !py.FS.analyzePath(`/data/${p}`).exists);
    if (need.length) {
      const photos = await new Promise((res) => { waiting.set(m.id, res); self.postMessage({ id: m.id, need }); });
      for (const [rel, buf] of photos) {
        const file = `/data/${rel}`;
        py.FS.mkdirTree(file.slice(0, file.lastIndexOf("/")));
        py.FS.writeFile(file, new Uint8Array(buf));
      }
    }
    say("Generando el PDF…");
    const path = wr.report(m.ws.code, m.kind, m.arg, m.season);
    const bytes = py.FS.readFile(path);
    py.FS.unlink(path);
    self.postMessage({ id: m.id, name: path.split("/").pop(), pdf: bytes.buffer }, [bytes.buffer]);
  } catch (e) {
    self.postMessage({ id: m.id, error: String(e.message || e).split("\n").filter(Boolean).pop() });
  }
};
