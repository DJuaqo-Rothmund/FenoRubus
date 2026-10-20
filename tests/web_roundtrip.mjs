// Usado por tests/test_web.py: lee un paquete exportado por la app (Python), arma el estado
// como la web y crea cambios con la lógica de la web.
import { readFileSync, writeFileSync } from "node:fs";
import * as C from "../web/core.js";

const [, , mode, input, output] = process.argv;
const data = JSON.parse(readFileSync(input, "utf-8"));
if (mode === "helpers") {
  const out = data.dates.map((d) => {
    const dt = C.parseDate(d);
    return { date: d, season: C.seasonOf(dt), iso: C.isoWeek(dt), monday: C.iso(C.mondayOf(dt)),
             folder: C.weekFolder(d), label: C.weekLabel(d) };
  });
  const names = data.varieties.map((v) => C.photoBasename(v, "2026-10-12", "detail", 2, "AM"));
  const units = data.varieties.map((v) => [C.unitMain(v), C.unitPlace(v)]);
  writeFileSync(output, JSON.stringify({ dates: out, names, units, codes: [7, 65, 891].map(C.codeStr) }));
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
