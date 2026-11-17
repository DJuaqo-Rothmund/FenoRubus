// Planillas con columnas subdivididas (= sheet_layout.py): «Planta 1 · N.º laterales»,
// «Planta 1 · Largo»… se muestran con «Planta 1» arriba y sus evaluaciones abajo.
export const SEP = " · ";
export const MAX_SAMPLES = 50, MAX_VARS = 20;
export const REP_COL = "Rep.";

export function split(col) {
  const i = col.indexOf(SEP);
  if (i > 0) {
    const g = col.slice(0, i), s = col.slice(i + SEP.length);
    if (g.trim() && s.trim()) return [g, s];
  }
  return [null, col];
}
export const join = (g, s) => (g ? `${g}${SEP}${s}` : s);

export function groups(cols) {
  const out = [];
  for (const c of cols) {
    const [g] = split(c);
    if (g !== null && out.length && out[out.length - 1][0] === g) out[out.length - 1][1].push(c);
    else out.push([g, [c]]);
  }
  return out;
}
export const isGrouped = (cols) => cols.some((c) => split(c)[0] !== null);

const clean = (t) => String(t || "").replaceAll(SEP.trim(), " ").split(/\s+/).filter(Boolean).join(" ");
export function parseVars(text) {
  const out = [];
  for (const v of String(text || "").split(/[\n,;]/)) {
    const x = clean(v);
    if (x && !out.includes(x)) out.push(x);
  }
  return out.slice(0, MAX_VARS);
}

export function build(variables, samples = 1, sampleName = "Planta", repsCol = false) {
  variables = variables.filter(Boolean);
  if (!variables.length) throw new Error("Escriba al menos una evaluación (ej.: N.º laterales).");
  samples = Math.max(1, Math.min(MAX_SAMPLES, parseInt(samples, 10) || 1));
  sampleName = clean(sampleName) || "Planta";
  const cols = repsCol ? [REP_COL] : [];
  if (samples === 1) return cols.concat(variables);
  for (let i = 1; i <= samples; i++) for (const v of variables) cols.push(join(`${sampleName} ${i}`, v));
  return cols;
}

export function describe(cols) {
  const gs = groups(cols).filter(([g]) => g);
  if (!gs.length) return `${cols.length} columna(s): ${cols.slice(0, 6).join(", ")}${cols.length > 6 ? "…" : ""}`;
  return `${gs[0][0]} … ${gs[gs.length - 1][0]} (${gs.length}) × ${gs[0][1].length} evaluación(es): `
    + gs[0][1].map((c) => split(c)[1]).join(", ") + ` · ${cols.length} columnas`;
}

export function nextGroup(cols) {
  const gs = groups(cols).filter(([g]) => g);
  if (!gs.length) return null;
  const [last, sub] = gs[gs.length - 1];
  const names = new Set(gs.map(([g]) => g));
  const k = last.lastIndexOf(" "), head = last.slice(0, k), num = last.slice(k + 1);
  let name;
  if (k > 0 && /^\d+$/.test(num)) { let n = Number(num) + 1; while (names.has(`${head} ${n}`)) n++; name = `${head} ${n}`; }
  else { let n = 2; while (names.has(`${last} ${n}`)) n++; name = `${last} ${n}`; }
  return [name, sub.map((c) => join(name, split(c)[1]))];
}

export function addSub(cols, name) {
  const out = [];
  for (const [g, cs] of groups(cols)) { out.push(...cs); if (g !== null) out.push(join(g, name)); }
  return out;
}

export function unitWord(cols) {
  const g = (groups(cols).find(([x]) => x) || [""])[0] || "";
  const k = g.lastIndexOf(" ");
  let head = (k > 0 && /^\d+$/.test(g.slice(k + 1)) ? g.slice(0, k) : g).toLowerCase() || "muestra";
  return head.endsWith("s") ? head : head + ("lrnd".includes(head.slice(-1)) ? "es" : "s");
}

// Texto copiado de Excel / Sheets: filas por línea, columnas por tabulación.
export function table(text) {
  const t = String(text || "").replace(/\r\n?/g, "\n").replace(/\n+$/, "");
  return t ? t.split("\n").map((l) => l.split("\t")) : [];
}
