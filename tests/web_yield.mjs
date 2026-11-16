// Prueba de web/yield.js desde Python (tests/test_yield_sync.py): lee paquetes de la app,
// calcula las estimaciones y arma los cambios de una edición en la web.
import fs from "node:fs";
import * as C from "../web/core.js";
import * as Y from "../web/yield.js";

globalThis.window ||= { addEventListener() {} };     // train.js registra teclas al importarse
const { cropClasses } = await import("../web/train.js");

const [, , src, out] = process.argv;
const inp = JSON.parse(fs.readFileSync(src, "utf-8"));
const st = C.emptyState();
inp.bundles.forEach((b, i) => C.applyBundle(st, `b${i}`, b));
const classes = cropClasses(inp.mod);
const sets = Y.buildSets(st, classes);
const s = sets[0];
const counts = {};
counts[s.photoRows[0].uid] = inp.counts;
const changes = Y.editChanges(s, inp.fields, counts);
const plan = inp.plan;
fs.writeFileSync(out, JSON.stringify({
  sets: sets.map((x) => ({ place: x.place, per_plant: x.per_plant, kg_ha: x.kg_ha, t_ha: x.t_ha, real_t_ha: x.real_t_ha,
    photo_error: x.photo_error, counted: x.counted, photos: x.photos, totals: x.totals })),
  changes, csv: Y.toCsv(sets, classes), bundle: C.bundle("web1", "rendimiento", changes, {}),
  sector: plan ? Y.planSector({ latitude: inp.lat, longitude: inp.lon }, plan)?.id ?? null : null,
  byName: plan ? Y.planSector({ sector: "Equipo de riego 2 · sector 7 · Meeker" }, plan)?.id ?? null : null,
  color: Y.yieldColor(1, 0, 4),
}));
