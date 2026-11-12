// AeonCrop Web · «Configuración de informes» (igual que report_config.py de la app):
// plantilla, formato y secciones del informe semanal. Se guarda como ajuste del ensayo
// («reportcfg»), así viaja con la sincronización entre la web y la app.
export const KEY = "reportcfg";
export const TEMPLATES_KEY = "reportcfg_templates";

export const SECTIONS = [
  ["summary", "Resumen ejecutivo", "Resumen"],
  ["bbch_table", "Tabla de estados BBCH", "Resumen"],
  ["change", "Cambio vs semana anterior", "Resumen"],
  ["missing", "Variedades sin registro", "Resumen"],
  ["photos", "Registro fotográfico", "Fotos y notas"],
  ["notes", "Notas del muestreo", "Fotos y notas"],
  ["ai", "Sugerencia de la IA", "Fotos y notas"],
  ["attachments", "Fotos adjuntas", "Fotos y notas"],
  ["gps", "Ubicación GPS", "Fotos y notas"],
  ["measures", "Mediciones de la semana", "Mediciones y ensayo"],
  ["progress", "Avance de mediciones", "Mediciones y ensayo"],
  ["matrix", "Matriz fenológica", "Evolución"],
  ["chart", "Gráfico BBCH por semana", "Evolución"],
  ["precocity", "Precocidad relativa", "Evolución"],
  ["milestones", "Hitos fenológicos", "Evolución"],
  ["gallery", "Galería paralela", "Evolución"],
  ["treatments", "Tratamientos y ANOVA", "Mediciones y ensayo"],
  ["parcels", "Detalle por parcela", "Mediciones y ensayo"],
  ["scout", "Plagas y enfermedades", "Del predio"],
  ["yield", "Rendimiento estimado + mapa", "Del predio"],
  ["notebook", "Cuaderno de campo de la semana", "Del predio"],
  ["map", "Mapa de los muestreos", "Del predio"],
];
export const SECTION_KEYS = SECTIONS.map((s) => s[0]);
export const GROUPS = ["Resumen", "Fotos y notas", "Evolución", "Mediciones y ensayo", "Del predio"];
export const NEW = new Set(["summary", "change", "missing", "scout", "yield", "notebook", "map"]);
export const PHOTO_MODES = { both: "General y detalle", canopy: "Solo general", detail: "Solo detalle", none: "Sin fotos" };
export const PHOTO_SIZES = { compact: "Compacto", normal: "Normal", large: "Grande" };
export const CLASSIC = ["bbch_table", "photos", "notes", "ai", "attachments", "gps", "measures"];
export const TEMPLATES = {
  completo: { name: "Completo", sections: [...SECTION_KEYS], photo_mode: "both", photo_size: "normal", all_photos: true, plain: false },
  resumido: { name: "Resumido", sections: ["summary", "bbch_table", "change", "missing", "chart", "measures"],
    photo_mode: "none", photo_size: "compact", all_photos: false, plain: false },
  fotos: { name: "Solo fotos", sections: ["photos", "notes", "attachments"], photo_mode: "both", photo_size: "large",
    all_photos: true, plain: false },
  cliente: { name: "Para el cliente", sections: ["summary", "bbch_table", "photos", "notes", "chart", "milestones", "yield", "map"],
    photo_mode: "both", photo_size: "normal", all_photos: false, plain: true },
};
const FORMAT = ["photo_mode", "photo_size", "all_photos", "plain", "no_date"];
const PARTS = ["notes", "ai", "attachments", "gps"];

// get(key, def): ajuste del ensayo ya leído (valor JSON), como Database.get_setting.
export function defaults(get) {
  const mode = get("report_photo_mode", "both");
  return { template: "", sections: [...CLASSIC], photo_mode: PHOTO_MODES[mode] ? mode : "both", photo_size: "normal",
    all_photos: !!get("report_all_photos", false), plain: !!get("report_plain_pdf", false), no_date: false };
}

export function normalize(cfg, base) {
  const out = { ...(base || defaults(() => null)) };
  if (cfg && typeof cfg === "object") {
    for (const k of [...FORMAT, "template"]) if (k in cfg) out[k] = cfg[k];
    if (Array.isArray(cfg.sections)) out.sections = SECTION_KEYS.filter((k) => cfg.sections.includes(k));
  }
  if (!PHOTO_MODES[out.photo_mode]) out.photo_mode = "both";
  if (!PHOTO_SIZES[out.photo_size]) out.photo_size = "normal";
  out.all_photos = !!out.all_photos; out.plain = !!out.plain;
  out.no_date = !!out.no_date;                    // sin «Generado dd-mm-aaaa hh:mm»
  return out;
}

export function load(get) {
  let raw = get(KEY, null);
  if (typeof raw === "string") { try { raw = JSON.parse(raw); } catch { raw = null; } }
  return normalize(raw, defaults(get));
}

// Ajustes a enviar ({clave: valor JSON}) al guardar.
export function settingsFor(cfg) {
  return { [KEY]: JSON.stringify(cfg) };
}

export function applyTemplate(cfg, key, saved = []) {
  let tpl = TEMPLATES[key];
  if (!tpl && key.startsWith("u:")) tpl = saved[Number(key.slice(2))];
  if (!tpl) return { ...cfg };
  const out = { ...cfg };
  for (const k of FORMAT) if (k in tpl) out[k] = tpl[k];
  out.sections = SECTION_KEYS.filter((k) => (tpl.sections || []).includes(k));
  out.template = key;
  return normalize(out);
}

export function toggle(cfg, section) {
  const sel = new Set(cfg.sections);
  if (sel.has(section)) sel.delete(section); else sel.add(section);
  if (section === "photos" && !sel.has(section)) PARTS.forEach((p) => sel.delete(p));
  if (PARTS.includes(section) && sel.has(section)) sel.add("photos");
  return normalize({ ...cfg, sections: [...sel], template: "" });
}

export function savedTemplates(get) {
  let raw = get(TEMPLATES_KEY, null);
  if (typeof raw === "string") { try { raw = JSON.parse(raw); } catch { raw = null; } }
  return Array.isArray(raw) ? raw.filter((t) => t && t.name) : [];
}

export function summary(cfg) {
  const name = TEMPLATES[cfg.template]?.name || (cfg.template ? "Plantilla guardada" : "Personalizado");
  const n = cfg.sections.length;
  return [name, `${n} ${n === 1 ? "sección" : "secciones"}`, `fotos: ${PHOTO_MODES[cfg.photo_mode].toLowerCase()}`,
    ...(cfg.plain ? ["PDF simple"] : []), ...(cfg.no_date ? ["sin fecha"] : [])].join(" · ");
}
