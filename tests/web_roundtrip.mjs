// Usado por tests/test_web.py: lee un paquete exportado por la app (Python), arma el estado
// como la web y crea cambios con la lógica de la web.
import { readFileSync, writeFileSync } from "node:fs";
import * as C from "../web/core.js";
import * as ST from "../web/stats.js";

const [, , mode, input, output] = process.argv;
const data = JSON.parse(readFileSync(input, "utf-8"));
if (mode === "stats") {
  const res = data.cases.map((c) => {
    const a = ST.anova(new Map(c.map(([t, r, v]) => [`${t}|${r}`, v])));
    return a && { f: Number.isFinite(a.f) ? a.f : "inf", p: a.p, df: a.df, lsd: a.lsd, cv: a.cv, letters: a.letters, design: a.design };
  });
  writeFileSync(output, JSON.stringify({ res, ms: data.vals.map(ST.meanSe), tcrit: [2, 6, 20].map((d) => ST.tCrit(d)) }));
} else if (mode === "helpers") {
  const out = data.dates.map((d) => {
    const dt = C.parseDate(d);
    return { date: d, season: C.seasonOf(dt), iso: C.isoWeek(dt), monday: C.iso(C.mondayOf(dt)),
             folder: C.weekFolder(d), label: C.weekLabel(d) };
  });
  const names = data.varieties.map((v) => C.photoBasename(v, "2026-10-12", "detail", 2, "AM"));
  const units = data.varieties.map((v) => [C.unitMain(v), C.unitPlace(v)]);
  const seq = [null, 7, 31, 65, 891, 99].map(C.seqColor);
  const sect = [[1, 1, false], [2, 5, false], [3, 10, true], [4, 3, false]].map(([e, s, f]) => C.sectorColor(e, s, f));
  writeFileSync(output, JSON.stringify({ dates: out, names, units, codes: [7, 65, 891].map(C.codeStr), seq, sect }));
} else if (mode === "exif") {
  const out = data.files.map((f) => { const b = readFileSync(f); return C.exifGps(b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength)); });
  writeFileSync(output, JSON.stringify(out));
} else if (mode === "settings") {
  // Ajustes hechos en la web: unidad de predio, edición de variedad, ensayo de tratamientos,
  // nombre de un tratamiento y primera semana fija.
  const st = C.emptyState();
  C.applyBundle(st, "p1.json", data);
  const local = (changes) => C.applyBundle(st, `l${Math.random()}`, { changes });
  const errors = [];
  const tryErr = (f) => { try { f(); errors.push(null); } catch (e) { errors.push(e.message); } };
  const u = C.unitChange(st, null, { cultivar: "Tulameen", code: "TU", sector: 2, irrigation: 1, plant_year: 2019 });
  local([u]);
  tryErr(() => C.unitChange(st, null, { cultivar: "tulameen", sector: 2, irrigation: 1, plant_year: 2019 }));
  tryErr(() => C.varietyChange(st, null, { name: "variedad web" }));
  const v = C.allVarieties(st).find((x) => x.name === "Variedad Web");
  const e = C.varietyChange(st, v, { code: "VWX", notes: "editada en la web" });
  local([e]);
  const t1 = C.trialSetup(st, 3, 2);
  local(t1.changes);
  const t2 = C.trialSetup(st, 2, 2);          // reduce: archiva T3R1 y T3R2
  local(t2.changes);
  const tn = C.treatmentChange(st, 1, { name: "Testigo", description: "sin aplicación", cultivar: "Heritage" });
  const all = [u, e, ...t1.changes, ...t2.changes, tn];
  const settings = { ...t1.settings, ...t2.settings, ...C.firstWeekSettings(2026, "2026-09-07") };
  writeFileSync(output, JSON.stringify({ bundle: C.bundle("webtest", "AM", all, settings), errors,
    counts: [t1.added, t1.archived, t2.archived], unit: u.data.name }));
} else {
  const st = C.emptyState();
  C.applyBundle(st, "p1.json", data);
  const vs = C.varieties(st);
  const v = vs.find((x) => x.name === "Variedad Web");
  const before = C.observationFor(st, v.uid, "2026-10-12");
  const r1 = C.observationChanges(st, v.uid, "2026-10-12", { bbch_code: 65, notes: "desde la web" }, "Final de la floración");
  C.applyBundle(st, "local1", { changes: r1.changes });
  const r2 = C.observationChanges(st, v.uid, "2026-11-02", { bbch_code: 891, notes: "" }, "10 % de los frutos cosechados");
  C.applyBundle(st, "local2", { changes: r2.changes });
  const ph = C.photoChange(st, r2.uid, "detail", "photos/T2026/web/20261102-AM-GlwD.jpg");
  const all = [...r1.changes, ...r2.changes, ph];
  writeFileSync(output, JSON.stringify({ bundle: C.bundle("webtest", "AM", all),
    varieties: vs.length, had: before ? before.bbch_code : null }));
}
