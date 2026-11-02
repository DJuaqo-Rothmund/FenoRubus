// tools/crop_splash_layers.js — capas de la animación de carga de PhenoBlue y PhenoCran
// (como las de PhenoRubus): del SVG de assets/src salen, sobre el cuadrado del anillo,
//   ring.png (solo el anillo punteado) y body.png (fruto, esfera e íconos SIN anillo ni
//   manijas), más geom.json (esfera y manijas). tools/make_crop_splash.py arma el resto.
//   node tools/crop_splash_layers.js <salida> PhenoBlue PhenoCran
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");
const N = 1024;
(async () => {
  const [out, ...names] = process.argv.slice(2);
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: N, height: N } });
  for (const name of names) {
    const svg = fs.readFileSync(path.join(__dirname, "..", "assets", "src", `${name}.svg`), "utf8");
    await p.setContent(`<html><body style="margin:0;background:transparent">${svg}</body></html>`);
    const geom = await p.evaluate((N) => {
      const s = document.querySelector("svg");
      const els = [...s.querySelectorAll("path,circle,ellipse,polygon,rect,line,polyline")];
      const fill = (el) => getComputedStyle(el).fill;
      const ring = els.find((el) => fill(el) === "rgb(181, 175, 167)");
      const dark = els.filter((el) => fill(el) === "rgb(62, 63, 59)");
      const face = dark.find((el) => el.tagName === "path" && el.getBBox().width > 60);
      const hands = dark.find((el) => el.tagName === "path" && el !== face);
      const rb = ring.getBBox(), fb = face.getBBox(), hb = hands.getBBox();
      // Cuadrado con margen (como el de PhenoRubus: el anillo ocupa ~88 %), centrado en el anillo.
      const side = rb.width / 0.877, cx = rb.x + rb.width / 2, cy = rb.y + rb.height / 2;
      s.setAttribute("viewBox", `${cx - side / 2} ${cy - side / 2} ${side} ${side}`);
      s.setAttribute("overflow", "visible");
      s.setAttribute("width", N); s.setAttribute("height", N);
      window._ring = ring; window._hands = hands; window._els = els;
      return { box: [cx - side / 2, cy - side / 2, side], ring: [rb.x, rb.y, rb.width, rb.height], face: [fb.x + fb.width / 2, fb.y + fb.height / 2, fb.width / 2],
               hands: [hb.x, hb.y, hb.width, hb.height] };
    }, N);
    const shot = async (file) => p.screenshot({ path: path.join(out, `${name}_${file}.png`), omitBackground: true });
    await p.evaluate(() => { for (const el of window._els) el.style.visibility = el === window._ring ? "visible" : "hidden"; });
    await shot("ring");
    await p.evaluate(() => { for (const el of window._els) el.style.visibility = (el === window._ring || el === window._hands) ? "hidden" : "visible"; });
    await shot("body");
    fs.writeFileSync(path.join(out, `${name}_geom.json`), JSON.stringify(geom));
  }
  await b.close();
})();
