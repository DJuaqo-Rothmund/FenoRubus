// tools/aeon_anim.js — cuadros de la animación de apertura de AeonCrop (assets/src/AeonCrop.svg):
// la huella (líneas verdes) se dibuja trazo a trazo y la planta rosada crece desde la base
// del reloj de arena; el reloj y el nombre están desde el comienzo.
//   node tools/aeon_anim.js <salida_dir> [ancho=480] [fps=20] [segundos=2.6]
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");
(async () => {
  const [out, W = 480, FPS = 20, SECS = 2.6] = process.argv.slice(2);
  fs.mkdirSync(out, { recursive: true });
  const svg = fs.readFileSync(path.join(__dirname, "..", "assets", "src", "AeonCrop.svg"), "utf8");
  const b = await chromium.launch();
  const H = Math.round(W * 220.2 / 211.01);
  const p = await b.newPage({ viewport: { width: Number(W), height: H } });
  await p.setContent(`<html><body style="margin:0;background:transparent">${svg}</body></html>`);
  await p.evaluate(({ W, H }) => {
    const s = document.querySelector("svg");
    s.setAttribute("width", W); s.setAttribute("height", H);
    const NS = "http://www.w3.org/2000/svg";
    const defs = s.querySelector("defs");
    const green = [...s.querySelectorAll(".cls-3")];
    // Orden de dibujo: de afuera hacia adentro (distancia al centro de la huella).
    const cx = 105, cy = 85;
    green.forEach((el) => { const bb = el.getBBox(); el._d = -Math.hypot(bb.x + bb.width / 2 - cx, bb.y + bb.height / 2 - cy); });
    green.sort((a, b) => a._d - b._d);
    window._green = green.map((el, i) => {
      const m = document.createElementNS(NS, "mask");
      m.setAttribute("id", "m" + i); m.setAttribute("maskUnits", "userSpaceOnUse");
      const st = el.cloneNode(); st.removeAttribute("class");
      st.setAttribute("fill", "none"); st.setAttribute("stroke", "#fff"); st.setAttribute("stroke-width", "9");
      st.setAttribute("stroke-linecap", "round");
      const L = el.getTotalLength ? el.getTotalLength() : 0;
      st.setAttribute("stroke-dasharray", `${L} ${L}`);
      m.appendChild(st); defs.appendChild(m);
      el.setAttribute("mask", `url(#m${i})`);
      return { st, L, k: i / green.length };
    });
    // Planta: piezas rosadas sobre la base del reloj (no las letras «Aeon»).
    const cp = document.createElementNS(NS, "clipPath"); cp.setAttribute("id", "grow");
    const r = document.createElementNS(NS, "rect"); r.setAttribute("x", 0); r.setAttribute("width", 211);
    cp.appendChild(r); defs.appendChild(cp); window._growRect = r;
    [...s.querySelectorAll(".cls-2")].forEach((el) => { if (el.getBBox().y < 150) el.setAttribute("clip-path", "url(#grow)"); });
  }, { W: Number(W), H });
  const N = Math.round(SECS * FPS);
  const ease = (x) => 1 - Math.pow(1 - Math.min(1, Math.max(0, x)), 3);
  for (let f = 0; f < N; f++) {
    const t = f / FPS;
    await p.evaluate((t) => {
      for (const g of window._green) {
        const start = 0.1 + g.k * 1.2, dur = 0.7;
        const q = Math.min(1, Math.max(0, (t - start) / dur));
        const e = 1 - Math.pow(1 - q, 2);
        // El contorno de una línea rellena va y vuelve: con la mitad (+) ya se ve completa.
        g.st.setAttribute("stroke-dashoffset", g.L * (1 - 0.56 * e));
      }
      const q = Math.min(1, Math.max(0, (t - 0.45) / 1.6));
      const e = 1 - Math.pow(1 - q, 3);
      const base = 136.5, top = 0;
      const y = base - (base - top) * e;
      window._growRect.setAttribute("y", y); window._growRect.setAttribute("height", base - y + 1);
    }, t);
    await p.screenshot({ path: path.join(out, `f${String(f).padStart(3, "0")}.png`), omitBackground: true });
  }
  await b.close();
})();
