// PhenoRubus Web · informes (mismo diseño que los de la app: templates/*.html + report.css).
// Cada informe se abre en una pestaña nueva con «Imprimir / Guardar PDF».
import * as C from "./core.js";

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
    const W = 900, H = 320, L = 44, R = 130, T = 14, B = 34;
    const x = (i) => L + (weeks.length < 2 ? 0 : (i * (W - L - R)) / (weeks.length - 1));
    const y = (v) => T + (H - T - B) * (1 - v / 99);
    let g = "";
    for (const v of [0, 20, 40, 60, 80, 99]) g += `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text class="tick" x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${v}</text>`;
    const step = Math.max(1, Math.ceil(weeks.length / 12));
    weeks.forEach((w, i) => { if (i % step === 0) g += `<text class="tick" x="${x(i)}" y="${H - 12}" text-anchor="middle">${wkShort(w)}</text>`; });
    const colors = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#9c3350", "#5b6b3a", "#3e4a56", "#7a5ab8"];
    const rowsSel = onlyUid ? heat.filter((r) => r.variety.uid === onlyUid) : heat;
    const labels = [];
    rowsSel.forEach((r, k) => {
      if (!r.pts.length) return;
      const col = colors[k % colors.length];
      const d = r.pts.map(([i, c], j) => `${j ? "L" : "M"}${x(i).toFixed(1)},${y(C.bbchValue(c)).toFixed(1)}`).join("");
      g += `<path d="${d}" fill="none" stroke="${col}" stroke-width="2.2" stroke-linejoin="round"/>`;
      for (const [i, c] of r.pts) g += `<circle cx="${x(i)}" cy="${y(C.bbchValue(c))}" r="3.2" fill="${col}"><title>${esc(C.unitMain(r.variety))} · ${wkShort(weeks[i])} · BBCH ${C.codeStr(c)}</title></circle>`;
      const [li, lc] = r.pts[r.pts.length - 1];
      labels.push({ x: x(li) + 6, y: y(C.bbchValue(lc)) + 4, col, t: esc(C.unitMain(r.variety)).slice(0, 20) });
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
    const photos = need.length;
    await open(`Reporte semanal · ${C.weekTitle(week)}`, `${C.weekLabel(week)} · ${C.weekRange(week)} · ${C.seasonTitle(C.seasonOf(C.parseDate(week)))}`,
      [`${done}/${cards.length} con estado BBCH`, `${photos} fotos`], html);
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

  return { weekly, matrix, variety, heatTable, chip };
}
