// PhenoRubus Web · «SEMANA x · COMPLETADA» con serpentinas y papel picado (= ui/celebrate.py).
// Se cierra sola a los 3,6 s o con un toque.
const PALETTE = ["#A8184A", "#E0718F", "#6FA86A", "#2F6B4F", "#F4B400", "#4FC3F7", "#FF8A65", "#BA68C8"];
const DURATION = 3600, PIECES = 70, STREAMERS = 12;

export function weekCompleted(weekText) {
  if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return card(weekText, null);
  const cv = document.createElement("canvas");
  cv.className = "confetti";
  const dpr = window.devicePixelRatio || 1;
  const W = window.innerWidth, H = window.innerHeight;
  cv.width = W * dpr; cv.height = H * dpr;
  const g = cv.getContext("2d");
  g.scale(dpr, dpr);
  const r = (a, b) => a + Math.random() * (b - a);
  const pick = () => PALETTE[Math.floor(Math.random() * PALETTE.length)];
  const pieces = Array.from({ length: PIECES }, () => ({ c: pick(), w: r(5, 9), h: r(9, 15), x: r(0, W), y: -r(0, H * .6),
    vy: r(160, 300), a: r(0, 360), spin: r(-360, 360), sway: r(10, 30), ph: r(0, 6.3) }));
  const streamers = Array.from({ length: STREAMERS }, () => ({ c: pick(), x: r(10, W - 10), y: -r(0, H * .5),
    vy: r(140, 230), len: r(70, 120), amp: r(7, 13), ph: r(0, 6.3), turns: r(2, 3.2) }));
  let t0 = null, raf = 0;
  const step = (now) => {
    t0 ??= now;
    const t = (now - t0) / 1000;
    g.clearRect(0, 0, W, H);
    for (const p of pieces) {
      const y = p.y + p.vy * t, x = p.x + Math.sin(t * 2.4 + p.ph) * p.sway;
      g.save(); g.translate(x, y); g.rotate(((p.a + p.spin * t) * Math.PI) / 180);
      g.fillStyle = p.c; g.fillRect(-p.w / 2, -p.h / 2, p.w, p.h); g.restore();
    }
    g.lineWidth = 2.2; g.lineCap = g.lineJoin = "round";
    for (const s of streamers) {
      const y0 = s.y + s.vy * t;
      g.strokeStyle = s.c; g.beginPath();
      for (let i = 0; i <= 14; i++) {
        const k = i / 14;
        const px = s.x + Math.sin(k * s.turns * 6.283 + s.ph + t * 5) * s.amp, py = y0 - k * s.len;
        i ? g.lineTo(px, py) : g.moveTo(px, py);
      }
      g.stroke();
    }
    raf = requestAnimationFrame(step);
  };
  raf = requestAnimationFrame(step);
  return card(weekText, cv, () => cancelAnimationFrame(raf));
}

function card(weekText, cv, stop = () => {}) {
  const box = document.createElement("div");
  box.className = "celebrate";
  if (cv) box.appendChild(cv);
  const c = document.createElement("div");
  c.className = "celebrate-card";
  c.innerHTML = `<div class="cw"></div><div class="cd">COMPLETADA</div><div class="cm">¡Buen trabajo!</div>`;
  c.querySelector(".cw").textContent = `SEMANA ${weekText}`;
  box.appendChild(c);
  document.body.appendChild(box);
  requestAnimationFrame(() => box.classList.add("on"));
  let closed = false;
  const close = () => {
    if (closed) return;
    closed = true;
    box.classList.remove("on");
    setTimeout(() => { stop(); box.remove(); }, 350);
  };
  box.onclick = close;
  setTimeout(close, DURATION);
  return close;
}
