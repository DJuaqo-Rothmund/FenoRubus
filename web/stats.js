// PhenoRubus Web · estadística de ensayos de tratamientos × repeticiones (= trial_stats.py):
// ANOVA de bloques completos al azar (o de un factor si faltan datos), valor p por la
// distribución F y letras LSD de Fisher. Se prueba contra Python en tests/test_web.py.
export const ALPHA = 0.05;

function lgamma(x) {                      // Lanczos (precisión ~1e-13)
  const g = 7, c = [0.99999999999980993, 676.5203681218851, -1259.1392167224028, 771.32342877765313,
    -176.61502916214059, 12.507343278686905, -0.13857109526572012, 9.9843695780195716e-6, 1.5056327351493116e-7];
  if (x < 0.5) return Math.log(Math.PI / Math.abs(Math.sin(Math.PI * x))) - lgamma(1 - x);
  x -= 1;
  let a = c[0];
  const t = x + g + 0.5;
  for (let i = 1; i < g + 2; i++) a += c[i] / (x + i);
  return 0.5 * Math.log(2 * Math.PI) + (x + 0.5) * Math.log(t) - t + Math.log(a);
}

function betacf(a, b, x) {
  const tiny = 1e-300, eps = 3e-14, qab = a + b, qap = a + 1, qam = a - 1;
  let c = 1, d = 1 - (qab * x) / qap;
  d = 1 / (Math.abs(d) > tiny ? d : tiny);
  let h = d;
  for (let m = 1; m < 300; m++) {
    const m2 = 2 * m;
    let aa = (m * (b - m) * x) / ((qam + m2) * (a + m2));
    d = 1 + aa * d; d = 1 / (Math.abs(d) > tiny ? d : tiny);
    c = 1 + aa / c; c = Math.abs(c) > tiny ? c : tiny;
    h *= d * c;
    aa = (-(a + m) * (qab + m) * x) / ((a + m2) * (qap + m2));
    d = 1 + aa * d; d = 1 / (Math.abs(d) > tiny ? d : tiny);
    c = 1 + aa / c; c = Math.abs(c) > tiny ? c : tiny;
    const delta = d * c;
    h *= delta;
    if (Math.abs(delta - 1) < eps) break;
  }
  return h;
}

export function betainc(a, b, x) {
  if (x <= 0) return 0;
  if (x >= 1) return 1;
  const front = Math.exp(lgamma(a + b) - lgamma(a) - lgamma(b) + a * Math.log(x) + b * Math.log(1 - x));
  return x < (a + 1) / (a + b + 2) ? (front * betacf(a, b, x)) / a : 1 - (front * betacf(b, a, 1 - x)) / b;
}
export function fPvalue(f, d1, d2) {
  if (f === null || Number.isNaN(f)) return NaN;
  if (!Number.isFinite(f)) return 0;
  if (f <= 0) return 1;
  return Math.max(0, Math.min(1, betainc(d2 / 2, d1 / 2, d2 / (d2 + d1 * f))));
}
const tTwoSidedP = (t, df) => betainc(df / 2, 0.5, df / (df + t * t));
export function tCrit(df, alpha = ALPHA) {
  let lo = 0, hi = 1000;
  for (let i = 0; i < 200; i++) { const mid = (lo + hi) / 2; if (tTwoSidedP(mid, df) > alpha) lo = mid; else hi = mid; }
  return (lo + hi) / 2;
}

export function meanSe(values) {
  const v = values.filter((x) => x !== null && x !== undefined).map(Number);
  if (!v.length) return [null, null];
  const m = v.reduce((a, b) => a + b, 0) / v.length;
  if (v.length < 2) return [m, null];
  const variance = v.reduce((a, x) => a + (x - m) ** 2, 0) / (v.length - 1);
  return [m, Math.sqrt(variance / v.length)];
}
export function stars(p) {
  if (p === null || p === undefined || Number.isNaN(p)) return "";
  return p < 0.001 ? "***" : p < 0.01 ? "**" : p < 0.05 ? "*" : "ns";
}
export function letters(means, lsd) {
  const order = Object.keys(means).sort((a, b) => means[b] - means[a]);
  const groups = [];
  let lastEnd = -1;
  order.forEach((k, i) => {
    let j = i;
    while (j + 1 < order.length && means[k] - means[order[j + 1]] <= lsd + 1e-12) j++;
    if (j > lastEnd) { groups.push([i, j]); lastEnd = j; }
  });
  const out = Object.fromEntries(order.map((k) => [k, ""]));
  groups.forEach(([i, j], g) => { for (const k of order.slice(i, j + 1)) out[k] += g < 26 ? String.fromCharCode(97 + g) : "?"; });
  return out;
}

// values: Map("t|r" -> número). Devuelve null si no hay datos suficientes.
export function anova(values) {
  const data = new Map([...values].filter(([, v]) => v !== null && v !== undefined).map(([k, v]) => [k, Number(v)]));
  const key = (k) => k.split("|").map(Number);
  const trts = [...new Set([...data.keys()].map((k) => key(k)[0]))].sort((a, b) => a - b);
  if (trts.length < 2) return null;
  const byT = Object.fromEntries(trts.map((t) => [t, [...data].filter(([k]) => key(k)[0] === t).map(([, v]) => v)]));
  const n = data.size;
  const all = [...data.values()];
  const grand = all.reduce((a, b) => a + b, 0) / n;
  const means = Object.fromEntries(trts.map((t) => [t, byT[t].reduce((a, b) => a + b, 0) / byT[t].length]));
  const reps = [...new Set([...data.keys()].map((k) => key(k)[1]))].sort((a, b) => a - b);
  const complete = reps.length >= 2 && trts.every((t) => reps.every((r) => data.has(`${t}|${r}`)));
  const ssTot = all.reduce((a, v) => a + (v - grand) ** 2, 0);
  const ssT = trts.reduce((a, t) => a + byT[t].length * (means[t] - grand) ** 2, 0);
  let design, dfT, dfE, ssE;
  if (complete) {
    design = "bloques completos al azar";
    const rmeans = reps.map((r) => trts.reduce((a, t) => a + data.get(`${t}|${r}`), 0) / trts.length);
    const ssB = trts.length * rmeans.reduce((a, m) => a + (m - grand) ** 2, 0);
    dfT = trts.length - 1; dfE = (trts.length - 1) * (reps.length - 1);
    ssE = Math.max(0, ssTot - ssT - ssB);
  } else {
    design = "un factor";
    dfT = trts.length - 1; dfE = n - trts.length;
    ssE = Math.max(0, ssTot - ssT);
  }
  if (dfE <= 0) return null;
  const msT = ssT / dfT, msE = ssE / dfE;
  const f = msE <= 1e-12 ? (msT <= 1e-12 ? 0 : Infinity) : msT / msE;
  const p = fPvalue(f, dfT, dfE);
  const out = { design, f, p, df: [dfT, dfE], means, mse: msE, stars: stars(p), letters: {}, lsd: null,
    cv: grand ? (Math.sqrt(msE) / grand) * 100 : null };
  if (p < ALPHA) {
    const nH = trts.length / trts.reduce((a, t) => a + 1 / byT[t].length, 0);
    out.lsd = tCrit(dfE) * Math.sqrt((2 * msE) / nH);
    out.letters = letters(means, out.lsd);
  }
  return out;
}
