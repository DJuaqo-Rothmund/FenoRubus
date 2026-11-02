// tools/render_svgs.js — SVG de assets/src a PNG transparente (con el Chromium de Playwright).
//   node tools/render_svgs.js <ancho> <salida_dir> archivo.svg...
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");
(async () => {
  const [w, out, ...files] = process.argv.slice(2);
  const b = await chromium.launch();
  for (const f of files) {
    const svg = fs.readFileSync(f, "utf8");
    const vb = svg.match(/viewBox="([^"]+)"/)[1].split(/\s+/).map(Number);
    const W = Number(w), H = Math.round(W * vb[3] / vb[2]);
    const p = await b.newPage({ viewport: { width: W, height: H } });
    await p.setContent(`<html><body style="margin:0;background:transparent">
      <img style="width:${W}px;height:${H}px;display:block" src="data:image/svg+xml;base64,${Buffer.from(svg).toString("base64")}"></body></html>`);
    await p.screenshot({ path: path.join(out, path.basename(f, ".svg") + ".png"), omitBackground: true });
    await p.close();
  }
  await b.close();
})();
