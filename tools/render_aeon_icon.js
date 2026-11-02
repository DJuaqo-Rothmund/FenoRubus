// tools/render_aeon_icon.js — ícono de AeonCrop para el teléfono: la huella y el reloj de
// arena con la planta, SIN el nombre (el logo con letras queda dentro de la app).
//   node tools/render_aeon_icon.js <salida.png> [lado=1024]
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");
(async () => {
  const [out, N = 1024] = process.argv.slice(2);
  const svg = fs.readFileSync(path.join(__dirname, "..", "assets", "src", "AeonCrop.svg"), "utf8");
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: Number(N), height: Number(N) } });
  await p.setContent(`<html><body style="margin:0;background:transparent">${svg}</body></html>`);
  await p.evaluate((N) => {
    const s = document.querySelector("svg");
    for (const el of s.querySelectorAll("path,polygon")) if (el.getBBox().y > 175) el.remove();   // el nombre
    const bb = s.getBBox(), side = Math.max(bb.width, bb.height) * 1.06;
    s.setAttribute("viewBox", `${bb.x + bb.width / 2 - side / 2} ${bb.y + bb.height / 2 - side / 2} ${side} ${side}`);
    s.setAttribute("width", N); s.setAttribute("height", N);
  }, Number(N));
  await p.screenshot({ path: out, omitBackground: true });
  await b.close();
})();
