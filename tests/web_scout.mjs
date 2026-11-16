// Prueba de web/scout_ai.js desde Python (tests/test_scout_ai.py).
import fs from "node:fs";
import * as AI from "../web/scout_ai.js";

const [, , src, out] = process.argv;
const inp = JSON.parse(fs.readFileSync(src, "utf-8"));
AI.setGuide(JSON.parse(fs.readFileSync(new URL("../web/scout/guia.json", import.meta.url), "utf-8")));
fs.writeFileSync(out, JSON.stringify({
  finds: inp.finds.map(([sec, n, s]) => AI.find(sec, n, s)?.name ?? null),
  prompts: inp.prompts.map(([sec, rec, views]) => AI.prompt(sec, rec, views)),
  norm: inp.norm.map(([sec, raw, prov]) => AI.normalize(sec, raw, prov, "X")),
  plantnet: AI.parsePlantnet(200, inp.plantnet),
  merged: AI.mergeEntries([{ photo: "a" }, { photo: "b", at: 1 }], [{ photo: "b", at: 2 }]),
}));
