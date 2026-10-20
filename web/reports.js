// PhenoRubus Web · informes (mismo diseño que los de la app: templates/*.html + report.css).
// Cada informe se abre en una pestaña nueva con «Imprimir / Guardar PDF».
import * as C from "./core.js";
import * as ST from "./stats.js";

const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const wkShort = (w) => `S${C.isoWeek(C.parseDate(w))[0]}`;

export function makeReports(ctx) {
  // ctx: { state, ws, bbch, photoUrl(path) -> Promise<url|null>, progress(text) }
  const label = (code) => (ctx.bbch.stages.find((s) => s.code === code) || {}).label || "";
  const macroName = (code) => ctx.bbch.macros[String(C.macroOf(code))] || "";

  function chip(code) {
    if (code === null || code === undefined) return `<span class="chip empty">Sin estado</span>`;
    const [bg] = C.seqColor(code);
    return `<span class="chip"><span class="sw" style="background:${bg}"></span>BBCH ${C.codeStr(code)} · ${esc(label(code))}</span>`;
  }
  const vname = (v) => esc(C.unitMain(v)) + (C.unitPlace(v) ? ` <span class="muted small">· ${esc(C.unitPlace(v))}</span>` : "");

  async function urls(paths) {
    const out = new Map();
    let i = 0;
    for (const p of paths) {
      ctx.progress(`Preparando fotos ${++i}/${paths.length}…`);
      out.set(p, await ctx.photoUrl(p).catch(() => null));
    }
    return out;
  }
  const primary = (obs, kind) => obs ? C.photosFor(ctx.state, obs.uid).find((p) => p.kind === kind) || null : null;

  async function open(title, subtitle, meta, content) {
    const css = await (await fetch("report.css")).text();
    const now = new Date().toLocaleString("es", { dateStyle: "long", timeStyle: "short" });
    const html = `<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>${esc(title)}</title>
<style>${css}
.toolbar{position:sticky;top:0;z-index:5;display:flex;gap:8px;justify-content:flex-end;padding:10px 0;background:var(--bg)}
.toolbar button{font:inherit;border:1px solid var(--rule);background:var(--paper);border-radius:999px;padding:6px 14px;cursor:pointer}
.toolbar button.p{background:#9c3350;color:#fff;border-color:#9c3350}
@media print{.toolbar{display:none}}</style></head><body><div class="wrap">
<div class="toolbar"><button onclick="window.close()">Cerrar</button><button class="p" onclick="window.print()">Imprimir / Guardar PDF</button></div>
<header class="doc"><div class="kicker">Cuaderno de campo · Rubus idaeus · Escala BBCH</div>
<h1>${esc(title)}</h1><div class="sub">${esc(subtitle)}</div>
<div class="meta"><span>Generado: ${esc(now)}</span><span>PhenoRubus Web · ${esc(ctx.ws.name || ctx.ws.code)}</span>${meta.map((m) => `<span>${esc(m)}</span>`).join("")}</div></header>
${content}
<footer class="doc"><span>PhenoRubus — seguimiento fenológico y biométrico de ensayos en frambueso.</span>
<span>Estados BBCH asignados por el evaluador.</span></footer></div></body></html>`;
    const win = ctx.win && !ctx.win.closed ? ctx.win : window.open("", "_blank");
    if (!win) throw new Error("El navegador bloqueó la ventana nueva: permita ventanas emergentes para esta página.");
    win.document.open(); win.document.write(html); win.document.close();
  }

  function figure(src, cap) {
    return `<figure>${src ? `<img src="${src}" alt="">` : `<div class="nophoto">sin foto</div>`}<figcaption>${esc(cap)}</figcaption></figure>`;
  }

  // ------------------------------------------------------------ gráfico semana × BBCH
  function chart(heat, weeks, onlyUid = null) {
    const rowsSel = onlyUid ? heat.filter((r) => r.variety.uid === onlyUid) : heat;
    return chartSeries(rowsSel.map((r) => ({ name: C.unitMain(r.variety), pts: r.pts.map(([i, c]) => [i, C.bbchValue(c)]) })), weeks);
  }

  function chartSeries(series, weeks) {
    const W = 900, H = 320, L = 44, R = 130, T = 14, B = 34;
    const x = (i) => L + (weeks.length < 2 ? 0 : (i * (W - L - R)) / (weeks.length - 1));
    const y = (v) => T + (H - T - B) * (1 - v / 99);
    let g = "";
    for (const v of [0, 20, 40, 60, 80, 99]) g += `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text class="tick" x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${v}</text>`;
    const step = Math.max(1, Math.ceil(weeks.length / 12));
    weeks.forEach((w, i) => { if (i % step === 0) g += `<text class="tick" x="${x(i)}" y="${H - 12}" text-anchor="middle">${wkShort(w)}</text>`; });
    const colors = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#9c3350", "#5b6b3a", "#3e4a56", "#7a5ab8"];
    const labels = [];
    series.forEach((r, k) => {
      if (!r.pts.length) return;
      const col = colors[k % colors.length];
      const d = r.pts.map(([i, v], j) => `${j ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
      g += `<path d="${d}" fill="none" stroke="${col}" stroke-width="2.2" stroke-linejoin="round"/>`;
      for (const [i, v] of r.pts) g += `<circle cx="${x(i)}" cy="${y(v)}" r="3.2" fill="${col}"><title>${esc(r.name)} · ${wkShort(weeks[i])} · BBCH ${C.numEs(v)}</title></circle>`;
      const [li, lv] = r.pts[r.pts.length - 1];
      labels.push({ x: x(li) + 6, y: y(lv) + 4, col, t: esc(r.name).slice(0, 20) });
    });
    labels.sort((a, b) => a.y - b.y);                // sin encimarse: se separan hacia abajo
    for (let i = 1; i < labels.length; i++) labels[i].y = Math.max(labels[i].y, labels[i - 1].y + 13);
    for (const l of labels) g += `<text x="${l.x}" y="${l.y}" font-size="11.5" font-weight="600" fill="${l.col}">${l.t}</text>`;
    return `<div class="card" style="padding:8px"><svg class="chart" viewBox="0 0 ${W} ${H}">${g}</svg></div>`;
  }

  function heatTable(heat, weeks) {
    let h = `<div class="scroll-x"><table class="heat"><thead><tr><th class="name">Variedad / sector</th>${weeks.map((w) => `<th class="w">${wkShort(w)}</th>`).join("")}</tr></thead><tbody>`;
    for (const r of heat) {
      h += `<tr><td class="name">${vname(r.variety)}</td>`;
      for (const c of r.cells) {
        if (c.code === null) { h += `<td class="c na">·</td>`; continue; }
        const [bg, fg] = C.seqColor(c.code);
        h += `<td class="c" style="background:${bg};color:${fg}" title="${esc(label(c.code))}">${C.codeStr(c.code)}</td>`;
      }
      h += "</tr>";
    }
    return h + `</tbody></table></div><div class="legend-seq"><span>BBCH 0</span><span class="bar"></span><span>99</span></div>`;
  }

  // ------------------------------------------------------------ 1. semanal
  async function weekly(week) {
    const vs = C.varieties(ctx.state);
    const cards = vs.map((v) => {
      const obs = C.observationFor(ctx.state, v.uid, week);
      const photos = obs ? C.photosFor(ctx.state, obs.uid) : [];
      return { v, obs, code: obs ? obs.bbch_code ?? null : null, canopy: primary(obs, "canopy"), detail: primary(obs, "detail"),
        extras: photos.filter((p) => p !== primary(obs, "canopy") && p !== primary(obs, "detail")) };
    });
    const need = cards.flatMap((c) => [c.canopy, c.detail, ...c.extras].filter(Boolean).map((p) => p.path));
    const u = await urls(need);
    const done = cards.filter((c) => c.code !== null).length;
    let html = `<h2>Resumen</h2><div class="scroll-x"><table><thead><tr><th>Variedad / sector</th><th>Estado fenológico</th><th>Estadio principal</th><th>Fotos</th></tr></thead><tbody>`;
    for (const c of cards) html += `<tr><td><strong>${vname(c.v)}</strong></td><td>${chip(c.code)}</td><td class="muted">${c.code !== null ? esc(macroName(c.code)) : "—"}</td><td>${(c.canopy ? 1 : 0) + (c.detail ? 1 : 0) + c.extras.length}</td></tr>`;
    html += `</tbody></table></div><h2>Registro fotográfico</h2><div class="grid-cards">`;
    for (const c of cards) {
      html += `<article class="card vcard"><div class="head"><h3>${vname(c.v)}</h3>${c.v.code ? `<span class="vcode">${esc(c.v.code)}</span>` : ""}</div>
        <div class="photos">${figure(c.canopy && u.get(c.canopy.path), "Canopia")}${figure(c.detail && u.get(c.detail.path), "Detalle")}</div>
        ${c.extras.length ? `<div class="extras">${c.extras.map((p) => u.get(p.path) ? `<img src="${u.get(p.path)}" alt="">` : "").join("")}</div>` : ""}
        <div>${chip(c.code)}</div>${c.obs?.notes ? `<div class="notes">${esc(c.obs.notes)}</div>` : ""}</article>`;
    }
    html += "</div>";
    html += await measuresBlock(week);
    const photos = need.length;
    await open(`Reporte semanal · ${C.weekTitle(week)}`, `${C.weekLabel(week)} · ${C.weekRange(week)} · ${C.seasonTitle(C.seasonOf(C.parseDate(week)))}`,
      [`${done}/${cards.length} con estado BBCH`, `${photos} fotos`], html);
  }

  async function measuresBlock(week) {
    const vs = new Map(C.rows(ctx.state, "varieties").map((v) => [v.uid, v]));
    let html = "";
    for (const m of C.measures(ctx.state)) {
      const es = C.entriesFor(ctx.state, m.uid, week).filter(C.entryFilled);
      if (!es.length) continue;
      html += `<h3 class="measure">${esc(m.name)}</h3>`;
      if (m.kind === "table") {
        html += `<div class="scroll-x"><table><thead><tr><th>#</th><th>Variedad / sector</th>${m.columns.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>`;
        es.forEach((e, i) => { const v = vs.get(e.variety_id); html += `<tr><td class="muted">${i + 1}</td><td>${v ? vname(v) : "—"}</td>${m.columns.map((c) => `<td>${esc(e.data[c] ?? "")}</td>`).join("")}</tr>`; });
        html += "</tbody></table></div>";
      } else {
        const u = await urls(es.map((e) => e.path).filter(Boolean));
        html += `<div class="attach">${es.map((e) => { const v = vs.get(e.variety_id);
          return `<figure>${u.get(e.path) ? `<img src="${u.get(e.path)}" alt="">` : `<div class="nophoto">sin foto</div>`}<figcaption>${esc(e.caption || "")}${v ? `<span class="muted">${esc(C.unitMain(v))}</span>` : ""}</figcaption></figure>`; }).join("")}</div>`;
      }
    }
    return html ? `<h2>Mediciones de la semana</h2>${html}` : "";
  }

  // ------------------------------------------------------------ 4. tratamientos (= reporter.treatments)
  async function treatments(season) {
    const trts = C.treatments(ctx.state);
    if (trts.length < 1) throw new Error("Este ensayo no tiene tratamientos ni parcelas (se definen en la app: Ajustes › Parcelas).");
    const parcels = trts.flatMap((t) => t.parcels);
    const where = new Map(parcels.map((p) => [p.uid, [Number(p.treatment), Number(p.rep)]]));
    let weeks = C.seasonWeeks(ctx.state, season);
    const bbchAt = (p, w) => { const o = C.observationFor(ctx.state, p.uid, w); return o && o.bbch_code != null ? C.bbchValue(o.bbch_code) : null; };
    const tables = C.measures(ctx.state).filter((m) => m.kind === "table");
    const mEntries = tables.map((m) => ({ m, es: C.entriesFor(ctx.state, m.uid).filter((e) => where.has(e.variety_id) && C.seasonOf(C.parseDate(e.week_id)) === season) }));
    const used = weeks.filter((w) => parcels.some((p) => bbchAt(p, w) !== null) || mEntries.some(({ es }) => es.some((e) => e.week_id === w)));
    if (used.length) weeks = weeks.filter((w) => w >= used[0] && w <= used[used.length - 1]);
    if (!weeks.length) throw new Error("No hay semanas con registros de las parcelas en esa temporada.");
    const fmtP = (a) => !a ? "—" : (a.p < 0.001 ? "< 0,001" : C.numEs(a.p, 3)) + ` ${a.stars}`;
    const rowsT = trts.map((t) => ({ t, cells: [], pts: [] }));
    const tests = [];
    weeks.forEach((w, i) => {
      const data = new Map();
      for (const p of parcels) { const v = bbchAt(p, w); if (v !== null) data.set(`${p.treatment}|${p.rep}`, v); }
      const a = ST.anova(data);
      for (const r of rowsT) {
        const vals = r.t.parcels.map((p) => data.get(`${r.t.num}|${p.rep}`)).filter((v) => v !== undefined);
        const [m] = ST.meanSe(vals);
        r.cells.push({ mean: m, n: vals.length, of: r.t.parcels.length, letter: (a?.letters || {})[r.t.num] || "" });
        if (m !== null) r.pts.push([i, Math.round(m * 100) / 100]);
      }
      if (a) tests.push({ w, f: Number.isFinite(a.f) && a.f < 1000 ? C.numEs(a.f, 2) : "> 999", p: fmtP(a), df: `${a.df[0]}; ${a.df[1]}`,
        cv: a.cv !== null ? C.numEs(a.cv) + " %" : "—", lsd: a.lsd !== null ? C.numEs(a.lsd, 2) : "—" });
    });
    let html = `<h2>Tratamientos</h2><div class="scroll-x"><table><thead><tr><th>Tratamiento</th><th>Variedad</th><th>Descripción</th><th>Parcelas</th></tr></thead><tbody>`;
    for (const t of trts) html += `<tr><td><strong>${esc(t.label)}</strong></td><td>${esc(t.cultivar || "—")}</td><td>${esc(t.description || "—")}</td><td class="mono small">${t.parcels.map((p) => esc(p.name)).join(", ")}</td></tr>`;
    html += `</tbody></table></div><h2>Estado BBCH medio por tratamiento</h2><p class="lead">Promedio de las repeticiones en cada semana. Letras distintas = diferencias significativas (LSD de Fisher, p &lt; 0,05), solo en las semanas en que el ANOVA es significativo.</p>
      <div class="scroll-x"><table class="heat"><thead><tr><th class="name">Tratamiento</th>${weeks.map((w) => `<th class="w">${wkShort(w)}</th>`).join("")}</tr></thead><tbody>`;
    for (const r of rowsT) {
      html += `<tr><td class="name">${esc(r.t.label)}</td>`;
      for (const c of r.cells) {
        if (c.mean === null) { html += `<td class="c na">·</td>`; continue; }
        const [bg, fg] = C.seqColor(Math.round(c.mean));
        html += `<td class="c" style="background:${bg};color:${fg}" title="${c.n}/${c.of} repeticiones">${C.numEs(c.mean)}${c.letter ? ` <sup>${c.letter}</sup>` : ""}</td>`;
      }
      html += "</tr>";
    }
    html += `</tbody></table></div><h2>Evolución BBCH por tratamiento</h2>${chartSeries(rowsT.map((r) => ({ name: r.t.label, pts: r.pts })), weeks)}
      <p class="muted small">Cada línea: promedio de las repeticiones del tratamiento.</p>
      <h2>ANOVA por semana</h2><p class="lead">Bloques completos al azar (repetición = bloque); si faltan parcelas, ANOVA de un factor. ns = sin diferencias; * p &lt; 0,05; ** p &lt; 0,01; *** p &lt; 0,001.</p>
      <div class="scroll-x"><table><thead><tr><th>Semana</th><th>F</th><th>gl</th><th>p</th><th>CV</th><th>LSD 5 %</th></tr></thead><tbody>`;
    for (const a of tests) html += `<tr><td>${esc(C.weekTitle(a.w))}</td><td>${a.f}</td><td>${a.df}</td><td><strong>${a.p}</strong></td><td>${a.cv}</td><td>${a.lsd}</td></tr>`;
    if (!tests.length) html += `<tr><td colspan="6" class="muted">Se necesitan al menos dos tratamientos con repeticiones registradas en una misma semana.</td></tr>`;
    html += "</tbody></table></div>";
    // Precocidad
    const wm = weeks.map((_, i) => { const ms = rowsT.map((r) => r.cells[i].mean).filter((m) => m !== null); return ms.length >= 2 ? ms.reduce((a, b) => a + b, 0) / ms.length : null; });
    for (const r of rowsT) {
      const ds = wm.map((m, i) => (m !== null && r.cells[i].mean !== null ? r.cells[i].mean - m : null)).filter((d) => d !== null);
      r.delta = ds.length ? Math.round((ds.reduce((a, b) => a + b, 0) / ds.length) * 10) / 10 + 0 : null;
      const last = [...r.cells].reverse().find((c) => c.mean !== null);
      r.last = last ? C.numEs(last.mean) : "—";
    }
    const ranking = rowsT.filter((r) => r.delta !== null).sort((a, b) => b.delta - a.delta);
    const maxAbs = Math.max(1, ...ranking.map((r) => Math.abs(r.delta)));
    html += `<h2>Precocidad relativa</h2><p class="lead">Diferencia media, en unidades BBCH, entre cada tratamiento y el promedio de todos los tratamientos en las mismas semanas.</p>
      <div class="scroll-x"><table><thead><tr><th>#</th><th>Tratamiento</th><th>Δ BBCH vs. promedio</th><th>Último BBCH medio</th></tr></thead><tbody>`;
    ranking.forEach((r, i) => {
      const pct = (Math.abs(r.delta) / maxAbs) * 50;
      const fill = r.delta >= 0 ? `left:50%;width:${pct}%;background:var(--pos)` : `right:50%;width:${pct}%;background:var(--neg)`;
      html += `<tr><td class="muted">${i + 1}</td><td><strong>${esc(r.t.label)}</strong></td><td><div class="delta"><div class="track"><span class="mid"></span><span class="fill" style="${fill}"></span></div><span class="val">${r.delta >= 0 ? "+" : ""}${r.delta.toFixed(1)}</span></div></td><td>${r.last}</td></tr>`;
    });
    if (!ranking.length) html += `<tr><td colspan="4" class="muted">Sin datos suficientes.</td></tr>`;
    html += "</tbody></table></div>";
    // Hitos
    const ms = [];
    for (const [code, name] of C.MILESTONES) {
      const target = C.bbchValue(code), hit = new Map();
      for (const p of parcels) {
        const wk = weeks.find((w) => { const v = bbchAt(p, w); return v !== null && v >= target; });
        if (wk) hit.set(`${p.treatment}|${p.rep}`, C.isoWeek(C.parseDate(wk))[0]);
      }
      if (!hit.size) continue;
      const a = ST.anova(hit);
      ms.push({ code, name, p: fmtP(a), cells: trts.map((t) => {
        const vals = t.parcels.map((p) => hit.get(`${t.num}|${p.rep}`)).filter((v) => v !== undefined);
        const [m] = ST.meanSe(vals);
        return { text: m === null ? "—" : `S${C.numEs(m)}` + (a && Object.keys(a.letters).length ? ` ${a.letters[t.num] || ""}` : ""), n: `${vals.length}/${t.parcels.length}` };
      }) });
    }
    if (ms.length) {
      html += `<h2>Hitos fenológicos</h2><p class="lead">Semana del año (promedio de las repeticiones) en que cada tratamiento alcanzó el estado; entre paréntesis, cuántas repeticiones lo alcanzaron.</p>
        <div class="scroll-x"><table><thead><tr><th>Hito</th>${trts.map((t) => `<th>${esc(t.label)}</th>`).join("")}<th>p</th></tr></thead><tbody>`;
      for (const m of ms) html += `<tr><td><strong>${esc(m.name)}</strong> <span class="mono small">≥${C.codeStr(m.code)}</span></td>${m.cells.map((c) => `<td>${c.text} <span class="muted small">(${c.n})</span></td>`).join("")}<td>${m.p}</td></tr>`;
      html += "</tbody></table></div>";
    }
    // Mediciones numéricas
    for (const { m, es } of mEntries) {
      const cols = [];
      for (const e of es) for (const [k, v] of Object.entries(e.data)) if (!cols.includes(k) && C.asNumber(v) !== null) cols.push(k);
      if (!cols.length) continue;
      let block = "";
      for (const w of weeks) {
        const ew = es.filter((e) => e.week_id === w);
        if (!ew.length) continue;
        const trows = Object.fromEntries(trts.map((t) => [t.num, []])), pRow = [];
        for (const col of cols) {
          const per = new Map();
          for (const e of ew) { const v = C.asNumber(e.data[col]); if (v !== null) { const k = where.get(e.variety_id).join("|"); per.set(k, [...(per.get(k) || []), v]); } }
          const data = new Map([...per].map(([k, v]) => [k, v.reduce((a, b) => a + b, 0) / v.length]));
          const a = ST.anova(data);
          pRow.push(fmtP(a));
          for (const t of trts) {
            const [mm, se] = ST.meanSe([...data].filter(([k]) => Number(k.split("|")[0]) === t.num).map(([, v]) => v));
            trows[t.num].push(mm === null ? "—" : C.numEs(mm, 2) + (se !== null ? ` ± ${C.numEs(se, 2)}` : "") + (a && Object.keys(a.letters).length ? ` ${a.letters[t.num] || ""}` : ""));
          }
        }
        block += `<h3 style="margin:14px 0 6px">${esc(C.weekTitle(w))}</h3><div class="scroll-x"><table><thead><tr><th>Tratamiento</th>${cols.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>
          ${trts.map((t) => `<tr><td><strong>${esc(t.label)}</strong></td>${trows[t.num].map((v) => `<td>${v}</td>`).join("")}</tr>`).join("")}
          <tr><td class="muted">p (ANOVA)</td>${pRow.map((p) => `<td class="muted">${p}</td>`).join("")}</tr></tbody></table></div>`;
      }
      if (block) html += `<h2>${esc(m.name)}</h2><p class="lead">Promedio ± error estándar de las repeticiones (las submuestras de una parcela se promedian primero).</p>${block}`;
    }
    const heat = C.matrix(ctx.state, weeks).filter((r) => where.has(r.variety.uid));
    html += `<h2>Detalle por parcela</h2><p class="lead">Código BBCH registrado en cada parcela (T = tratamiento, R = repetición).</p>${heatTable(heat, weeks)}`;
    const nr = Math.max(...trts.map((t) => t.parcels.length));
    await open("Comparación de tratamientos", `${trts.length} tratamientos × ${nr} repeticiones · ${C.seasonTitle(season)} · Semanas ${wkShort(weeks[0]).slice(1)}–${wkShort(weeks[weeks.length - 1]).slice(1)}`,
      [`${trts.length} tratamientos`, `${nr} repeticiones`, `${weeks.length} semanas`], html);
  }

  // ------------------------------------------------------------ 2. matriz / período
  async function matrix(season, weeks, title, withStrips = false) {
    if (!weeks.length) throw new Error("No hay semanas con registros en ese rango.");
    const all = C.matrix(ctx.state, weeks);
    const heat = all.filter((r) => r.pts.length);
    const hidden = all.length - heat.length;
    let html = `<h2>Matriz fenológica</h2>${hidden ? `<p class="muted small">${hidden} variedad(es)/sector(es) sin registros en estas semanas no se muestran.</p>` : ""}<p class="lead">Estado BBCH por variedad (filas) y semana de muestreo (columnas).</p>${heatTable(heat, weeks)}`;
    html += `<h2>Estado BBCH por semana</h2>${chart(heat, weeks)}`;
    const ranking = heat.filter((r) => r.delta !== null).sort((a, b) => b.delta - a.delta);
    const maxAbs = Math.max(1, ...ranking.map((r) => Math.abs(r.delta)));
    html += `<h2>Precocidad relativa</h2><p class="lead">Diferencia media, en unidades BBCH, entre cada variedad y el promedio de todas en las mismas semanas. Positivo = adelantada; negativo = tardía.</p>
      <div class="scroll-x"><table><thead><tr><th>#</th><th>Variedad / sector</th><th>Δ BBCH vs. promedio</th><th>Último estado</th></tr></thead><tbody>`;
    ranking.forEach((r, i) => {
      const pct = (Math.abs(r.delta) / maxAbs) * 50;
      const fill = r.delta >= 0 ? `left:50%;width:${pct}%;background:var(--pos)` : `right:50%;width:${pct}%;background:var(--neg)`;
      html += `<tr><td class="muted">${i + 1}</td><td><strong>${vname(r.variety)}</strong></td><td><div class="delta"><div class="track"><span class="mid"></span><span class="fill" style="${fill}"></span></div><span class="val">${r.delta >= 0 ? "+" : ""}${r.delta.toFixed(1)}</span></div></td><td>${chip(r.last)}</td></tr>`;
    });
    if (!ranking.length) html += `<tr><td colspan="4" class="muted">Se necesitan al menos dos variedades registradas en una misma semana.</td></tr>`;
    html += `</tbody></table></div><h2>Hitos fenológicos</h2><p class="lead">Primera semana en que cada variedad alcanzó (o superó) el estado indicado.</p>
      <div class="scroll-x"><table><thead><tr><th>Variedad / sector</th>${C.MILESTONES.map(([c, n]) => `<th>${esc(n)}<br><span class="mono">≥${C.codeStr(c)}</span></th>`).join("")}</tr></thead><tbody>`;
    for (const r of heat) html += `<tr><td><strong>${vname(r.variety)}</strong></td>${r.hits.map((h) => `<td>${h ? wkShort(h) : `<span class="muted">—</span>`}</td>`).join("")}</tr>`;
    html += "</tbody></table></div>";
    // Galería paralela: foto de detalle (o la que haya) por semana.
    const pick = (o) => primary(o, "detail") || primary(o, "canopy");
    const need = heat.flatMap((r) => r.cells.map((c) => pick(c.obs)).filter(Boolean).map((p) => p.path));
    const u = await urls(need);
    html += withStrips ? `<h2>Evolución por variedad</h2>` : `<h2>Galería paralela (fotos de detalle)</h2>`;
    html += `<div class="scroll-x" style="padding:10px"><table><tbody>`;
    for (const r of heat) {
      html += `<tr><td style="white-space:nowrap;font-weight:600;position:sticky;left:0;background:var(--paper)">${vname(r.variety)}</td><td><div class="gal">`;
      for (const c of r.cells) {
        const p = pick(c.obs), src = p && u.get(p.path);
        html += `<div>${src ? `<img src="${src}" alt="">` : `<div class="nophoto">—</div>`}<div class="cap">${wkShort(c.week)}${c.code !== null ? " · " + C.codeStr(c.code) : ""}</div></div>`;
      }
      html += `</div></td></tr>`;
    }
    html += "</tbody></table></div>";
    await open(title, `Avance fenológico relativo · ${C.seasonTitle(season)} · Semanas ${wkShort(weeks[0]).slice(1)}–${wkShort(weeks[weeks.length - 1]).slice(1)}`,
      [`${heat.length} variedades/sectores`, `${weeks.length} semanas`], html);
  }

  // ------------------------------------------------------------ 3. ficha por variedad
  async function variety(v, season) {
    const weeks = C.seasonWeeks(ctx.state, season);
    const heat = C.matrix(ctx.state, weeks);
    const row = heat.find((r) => r.variety.uid === v.uid);
    const items = weeks.map((w) => ({ w, obs: C.observationFor(ctx.state, v.uid, w) })).filter((x) => x.obs && C.hasData(ctx.state, x.obs));
    const need = items.flatMap((x) => C.photosFor(ctx.state, x.obs.uid).map((p) => p.path));
    const u = await urls(need);
    let html = "";
    if (row && row.pts.length) html += `<h2>Evolución BBCH</h2>${chart(heat, weeks, v.uid)}`;
    html += `<h2>Hitos</h2><div class="stats">${C.MILESTONES.map(([c, n], i) => `<div class="card stat"><div class="v">${row && row.hits[i] ? wkShort(row.hits[i]) : "—"}</div><div class="l">${esc(n)} (≥${C.codeStr(c)})</div></div>`).join("")}</div>`;
    html += `<h2>Registro semana a semana</h2><div class="timeline">`;
    for (const { w, obs } of items) {
      const photos = C.photosFor(ctx.state, obs.uid);
      html += `<div class="tl-item"><div class="when">${esc(C.weekTitle(w))} · ${esc(C.weekLabel(w))}</div><div class="card tl-body">
        <div><div>${chip(obs.bbch_code ?? null)}</div>${obs.notes ? `<div class="notes" style="margin-top:8px">${esc(obs.notes)}</div>` : ""}</div>
        ${photos.length ? `<div class="photos ${photos.length === 1 ? "one" : ""}">${photos.map((p) => figure(u.get(p.path), p.kind === "canopy" ? "Canopia" : "Detalle")).join("")}</div>` : `<div class="muted small">Sin fotos esta semana.</div>`}</div></div>`;
    }
    if (!items.length) html += `<p class="muted">Sin registros en la ${esc(C.seasonTitle(season))}.</p>`;
    html += "</div>";
    await open(`Ficha fenológica · ${C.unitMain(v)}`, `${C.unitPlace(v) ? C.unitPlace(v) + " · " : ""}${C.seasonTitle(season)}`,
      [`${items.length} semanas con registro`, `${need.length} fotos`], html);
  }

  return { weekly, matrix, variety, treatments, heatTable, chip };
}
