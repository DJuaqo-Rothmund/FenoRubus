// Usado por tests/test_web.py: lee un paquete exportado por la app (Python), arma el estado
// como la web y crea cambios con la lógica de la web.
import { readFileSync, writeFileSync } from "node:fs";
import * as C from "../web/core.js";
import * as ST from "../web/stats.js";
import * as RC from "../web/reportcfg.js";

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
} else if (mode === "reportcfg") {
  // Configuración de informes guardada en la app -> la web la lee, la cambia y la devuelve.
  const st = C.emptyState();
  C.applyBundle(st, "p1.json", data);
  const get = (k, d) => C.setting(st, k, d);
  const cfg = RC.load(get);
  const changed = RC.toggle(RC.applyTemplate(cfg, "completo"), "gps");
  writeFileSync(output, JSON.stringify({ read: cfg, summary: RC.summary(changed), settings: RC.settingsFor(changed) }));
} else if (mode === "zip") {
  // ZIP de los informes semanales (sin compresión): lo debe abrir cualquier programa.
  const files = data.files.map(([n, t]) => [n, new TextEncoder().encode(t)]);
  writeFileSync(output, C.zipStore(files, new Date(2026, 10, 12, 9, 30, 0)));
} else if (mode === "notebook") {
  // Cuaderno: hojas del día y fotos pegadas (lo que hace la web), de vuelta a la app.
  const st = C.emptyState();
  C.applyBundle(st, "p1.json", data);
  const day = C.noteFor(st, "2026-11-20");
  const pages = C.notePages(day);
  const place = C.notePlace(day.photos[0]);
  const c1 = C.noteChange(st, "2026-11-20", C.notePageFields(day, 1, "hoja dos desde la web", "")).change;
  C.applyBundle(st, "l1", { changes: [c1] });
  const c2 = C.noteChange(st, "2026-11-20", C.notePageFields(C.noteFor(st, "2026-11-20"), 2, "hoja tres nueva", "")).change;
  C.applyBundle(st, "l2", { changes: [c2] });
  const ph0 = C.noteFor(st, "2026-11-20").photos[0];
  const c3 = C.notePhotoUpdate(ph0, { page: 2, place: JSON.stringify({ x: 3, y: 4, w: 5, r: 350 }) });
  const c4 = C.notePhotoChange(day.uid, "photos/cuaderno/20261120-AM-cuaderno-w1.jpg", 0, { x: 1, y: 2, w: 6, r: 4 });
  const all = [c1, c2, c3, c4];
  writeFileSync(output, JSON.stringify({ bundle: C.bundle("webtest", "AM", all), pages: pages.map((p) => p.text), place }));
} else if (mode === "lab") {
  // AeonCrop Web: ensayo con T0, fenología unificada por tratamiento y mover una semana.
  const st = C.emptyState();
  C.applyBundle(st, "p1.json", data);
  const local = (changes, settings = {}) => C.applyBundle(st, `l${Math.random()}`, { changes, settings });
  const t = C.trialSetup(st, 3, 2, true);
  local(t.changes, t.settings);
  const u = C.phenoUnitChanges(st, true, "treatment", ["Caña gruesa", "Caña delgada"]);
  local(u.changes, u.settings);
  const units = C.phenoUnits(st).map((x) => x.name);
  const parcels = C.varieties(st).filter(C.isParcel).map((x) => x.name);
  const trts = C.treatments(st).map((x) => x.num);
  const m = C.weekMoveChanges(st, "2026-10-12", "2026-10-19");
  local(m.changes);
  const all = [...t.changes, ...u.changes, ...m.changes];
  writeFileSync(output, JSON.stringify({ bundle: C.bundle("webtest", "AUF", all, { ...t.settings, ...u.settings }),
    units, parcels, trts, renames: m.renames.map((r) => [r.from, r.to, r.kind]),
    moved: { records: m.records, merged: m.merged, photos: m.photos, entries: m.entries } }));
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
