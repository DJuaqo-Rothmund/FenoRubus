// tools/render_ia_brain.js — el cerebro de assets/src/IA_color.svg SIN las letras «IA+»
// (clase .cls-11): para el botón «Entrenador IA»; el dibujo completo es el de «IA+».
//   node tools/render_ia_brain.js <salida.png> [ancho=900]
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");
(async () => {
  const [out, W = 900] = process.argv.slice(2);
  const svg = fs.readFileSync(path.join(__dirname, "..", "assets", "src", "IA_color.svg"), "utf8");
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: Number(W), height: Number(W) } });
  await p.setContent(`<html><body style="margin:0;background:transparent">${svg}</body></html>`);
  await p.evaluate((W) => {
    const s = document.querySelector("svg");
    s.querySelectorAll(".cls-11").forEach((el) => el.remove());
    const bb = s.getBBox(), side = Math.max(bb.width, bb.height) * 1.02;
    s.setAttribute("viewBox", `${bb.x + bb.width / 2 - side / 2} ${bb.y + bb.height / 2 - side / 2} ${side} ${side}`);
    s.setAttribute("width", W); s.setAttribute("height", W);
  }, Number(W));
  await p.screenshot({ path: out, omitBackground: true });
  await b.close();
})();
