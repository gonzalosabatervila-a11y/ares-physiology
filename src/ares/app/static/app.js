'use strict';
const view = document.getElementById('view');
const tabsEl = document.getElementById('tabs');
const sheetEl = document.getElementById('sheet');
const sheetBody = document.getElementById('sheet-body');
const REDUCED = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
  ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const dias = (n) => `${n} ${n === 1 ? 'día' : 'días'}`;
const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);
const COLOR = {ok: '#A6BDA3', warn: '#D7A56B', bad: '#D67968', none: '#ABA99E'};

// ---------------------------------------------------------------- iconos
const P = { // trazos de 24x24
  home: '<path d="M4 11l8-7 8 7v8a1 1 0 0 1-1 1h-4v-6H9v6H5a1 1 0 0 1-1-1z"/>',
  chart: '<path d="M5 20V11M12 20V5M19 20v-6"/>',
  flask: '<path d="M9 3h6M10 3v6l-5 9a2 2 0 0 0 1.8 3h10.4A2 2 0 0 0 19 18l-5-9V3M8 15h8"/>',
  moon: '<path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z"/>',
  pulse: '<path d="M3 12h4l2-6 4 12 2-6h6"/>',
  run: '<circle cx="14.5" cy="5" r="1.8"/><path d="M8 21l3-6 3 2 2 4M11 15l-1-4 4-2 3 3h3M6 12l2-3 3-1"/>',
  chev: '<path d="M9 5l7 7-7 7"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
  back: '<path d="M15 5l-7 7 7 7"/>',
  sync: '<path d="M20 11a8 8 0 0 0-14.3-4.9L4 8M4 4v4h4M4 13a8 8 0 0 0 14.3 4.9L20 16M20 20v-4h-4"/>',
  db: '<ellipse cx="12" cy="6" rx="7" ry="3"/><path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6"/>',
};
const svg = (k, cls = '') => `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${P[k]}</svg>`;
const MARK = `<svg width="38" height="38" viewBox="0 0 22 22" aria-hidden="true">
<path d="M4.5 14.7A7.48 7.48 0 1 1 17.5 14.7" fill="none" stroke="#3A4548" stroke-width="4.2" stroke-linecap="round"/>
<path d="M4.5 14.7A7.48 7.48 0 0 1 14.6 4.4" fill="none" stroke="#D5B27A" stroke-width="4.2" stroke-linecap="round"/>
<circle cx="14.6" cy="4.4" r="2.5" fill="#D5B27A"/></svg>`;
const GLYPH = {
  intervals: '<svg class="gl" viewBox="0 0 22 22"><rect x="3" y="11" width="4" height="8" rx="1.5" fill="#D5B27A"/><rect x="9" y="6" width="4" height="13" rx="1.5" fill="#D5B27A" opacity=".72"/><rect x="15" y="3" width="4" height="16" rx="1.5" fill="#D5B27A" opacity=".45"/></svg>',
  tredict: '<svg class="gl" viewBox="0 0 22 22"><path d="M11 3l9 16H2z" fill="none" stroke="#D5B27A" stroke-width="2" stroke-linejoin="round"/></svg>',
};
const SRC_NAME = {intervals: 'Intervals', tredict: 'Tredict', whoop: 'WHOOP'};

// --------------------------------------------------------------- utilidades
function ageText(min) {
  if (min === null || min === undefined) return '—';
  if (min < 2) return 'ahora';
  if (min < 60) return `hace ${min} min`;
  if (min < 1440) return `hace ${Math.round(min / 60)} h`;
  return `hace ${Math.round(min / 1440)} d`;
}
function chipState(s) {
  const lvl = s.level || 'none';
  if (lvl === 'none') return {cls: 'none', text: 'Pendiente'};
  if (lvl === 'bad' && s.error) return {cls: 'bad', text: 'Caída'};
  return {cls: lvl, text: cap(ageText(s.age_min))};
}
function tagChip(tag, origin) {
  const cls = tag === 'CALC' ? 'calc' : tag === 'EST' ? 'est' : tag === 'EXP' ? 'exp' : '';
  return `<span class="tag ${cls}" title="${esc(tag)} · ${esc(origin)}">${esc(tag)} · ${esc(origin)}</span>`;
}
function splitUnit(v) {
  const m = /^(\S+)\s+(\S+)$/.exec(v || '');
  return m ? `${esc(m[1])}<small>${esc(m[2])}</small>` : esc(v);
}
function shortDate(iso) {
  const [, m, d] = iso.split('-');
  return `${d}/${m}`;
}
function syncDot(sources) {
  const live = sources.filter((s) => s.level !== 'none');
  if (!live.length) return 'none';
  if (live.some((s) => s.level === 'bad')) return 'bad';
  if (live.some((s) => s.level === 'warn')) return 'warn';
  return '';
}

// --------------------------------------------------------------- gráficos
function arc(cx, cy, r, p0, p1) {
  const a0 = (150 + 240 * p0) * Math.PI / 180, a1 = (150 + 240 * p1) * Math.PI / 180;
  const f = (n) => n.toFixed(1);
  return `M${f(cx + r * Math.cos(a0))} ${f(cy + r * Math.sin(a0))}A${r} ${r} 0 ${(p1 - p0) * 240 > 180 ? 1 : 0} 1 ${f(cx + r * Math.cos(a1))} ${f(cy + r * Math.sin(a1))}`;
}
const G = {noche: ['moon', 'Noche'], nervioso: ['pulse', 'Sist. nervioso'], carga: ['run', 'Carga']};
function valueSpans(key, v) {
  const m = key === 'noche' ? /^(\d+):(\d\d)$/.exec(v) : null;
  if (m) return `<tspan>${m[1]}</tspan><tspan font-size="11" dx="2" fill="#8C979B">h</tspan><tspan dx="3">${m[2]}</tspan>`;
  const u = /^(\S+)\s+(\S+)$/.exec(v);
  if (u) return `<tspan>${esc(u[1])}</tspan><tspan font-size="11" dx="3" fill="#8C979B">${esc(u[2])}</tspan>`;
  return `<tspan>${esc(v)}</tspan>`;
}
function gauge(d) {
  const col = COLOR[d.level] || COLOR.none, cx = 60, cy = 62, r = 46;
  const [icon, label] = G[d.key];
  const noRange = d.state.startsWith('sin rango');
  const stateTxt = noRange ? 'Sin rango' : cap(d.state);
  const trend = d.trend || (noRange ? d.state.replace('sin rango ', '').replace(/[()]/g, '') : '');
  const track = `<path d="${arc(cx, cy, r, 0, 1)}" fill="none" stroke="rgba(255,255,255,.09)" stroke-width="5" stroke-linecap="round"${d.p === null ? ' stroke-dasharray="2 6"' : ''}/>`;
  const band = d.band ? `<path d="${arc(cx, cy, r, d.band[0], d.band[1])}" fill="none" stroke="${col}" stroke-opacity=".5" stroke-width="8" stroke-linecap="round"/>` : '';
  const needle = d.p === null ? '' : `<circle class="needle" data-p="${d.p}" data-cx="${cx}" data-cy="${cy}" data-r="${r}" cx="${(cx + r * Math.cos(150 * Math.PI / 180)).toFixed(1)}" cy="${(cy + r * Math.sin(150 * Math.PI / 180)).toFixed(1)}" r="6.5" fill="#fff" style="filter:drop-shadow(0 0 5px ${col})"/>`;
  return `<a class="gauge" href="#/senal/${d.signal}" aria-label="${esc(label)}: ${esc(d.value)}, ${esc(stateTxt)}. Ver detalle">
<svg viewBox="0 0 120 112" role="img" aria-hidden="true">${track}${band}${needle}
<g transform="translate(50,30) scale(.83)" fill="none" stroke="#8C979B" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${P[icon]}</g>
<text x="60" y="72" text-anchor="middle" font-family="Archivo,sans-serif" font-size="22" font-weight="700" fill="#F0EEE7">${valueSpans(d.key, d.value)}</text>
<text x="60" y="89" text-anchor="middle" font-family="Archivo,sans-serif" font-size="11.5" font-weight="600" fill="${col}">${esc(stateTxt)}</text></svg>
<span class="lab">${esc(label)}</span><span class="trend">${esc(trend)}</span></a>`;
}
function animateGauges() {
  document.querySelectorAll('.needle').forEach((el) => {
    const p = parseFloat(el.dataset.p), cx = +el.dataset.cx, cy = +el.dataset.cy, r = +el.dataset.r;
    const put = (q) => {
      const a = (150 + 240 * q) * Math.PI / 180;
      el.setAttribute('cx', (cx + r * Math.cos(a)).toFixed(1));
      el.setAttribute('cy', (cy + r * Math.sin(a)).toFixed(1));
    };
    if (REDUCED) { put(p); return; }
    const t0 = performance.now(), dur = 850;
    const step = (t) => {
      const k = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - k, 3);
      put(p * e);
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  });
}
function spark(vals, color = '#D5B27A') {
  if (!vals || vals.length < 3) return '';
  const lo = Math.min(...vals), hi = Math.max(...vals), span = hi - lo || 1, w = 92, h = 34;
  const pts = vals.map((v, i) => [2 + i * (w - 6) / (vals.length - 1), 4 + (h - 8) * (1 - (v - lo) / span)]);
  const last = pts[pts.length - 1];
  return `<svg class="sp" viewBox="0 0 ${w} ${h}" aria-hidden="true"><polyline points="${pts.map((p) => p.map((n) => n.toFixed(1)).join(',')).join(' ')}" fill="none" stroke="${color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/><circle cx="${last[0].toFixed(1)}" cy="${last[1].toFixed(1)}" r="2.8" fill="#fff"/></svg>`;
}
let chartSeq = 0;
function lineChart(lines, opts = {}) {
  const {band = null, area = true} = opts;
  const W = 340, H = 176, L = 30, R = 8, T = 10, B = 26, id = `g${++chartSeq}`;
  const all = lines.flatMap((l) => l.pts.map((p) => p.v));
  if (all.length < 2) return '<p class="muted">Aún no hay datos suficientes para dibujar la serie.</p>';
  let lo = Math.min(...all, ...(band ? [band[0]] : [])), hi = Math.max(...all, ...(band ? [band[1]] : []));
  const pad = (hi - lo || 1) * 0.14; lo -= pad; hi += pad;
  const ts = lines.flatMap((l) => l.pts.map((p) => Date.parse(p.date)));
  const t0 = Math.min(...ts), t1 = Math.max(...ts), tspan = t1 - t0 || 1;
  const x = (d) => L + (W - L - R) * ((Date.parse(d) - t0) / tspan);
  const y = (v) => T + (H - T - B) * (1 - (v - lo) / (hi - lo));
  const f = (n) => n.toFixed(1);
  const ticks = [hi - pad, (hi + lo) / 2, lo + pad].map((v) =>
    `<line x1="${L}" x2="${W - R}" y1="${f(y(v))}" y2="${f(y(v))}" stroke="rgba(255,255,255,.06)"/><text x="${L - 6}" y="${f(y(v) + 3.5)}" text-anchor="end" font-size="10" fill="#65727A">${Math.round(v)}</text>`).join('');
  const bandSvg = band ? `<rect x="${L}" y="${f(y(band[1]))}" width="${W - L - R}" height="${f(y(band[0]) - y(band[1]))}" fill="rgba(69,212,229,.11)"/><line x1="${L}" x2="${W - R}" y1="${f(y(band[1]))}" y2="${f(y(band[1]))}" stroke="rgba(69,212,229,.35)" stroke-dasharray="3 4"/><line x1="${L}" x2="${W - R}" y1="${f(y(band[0]))}" y2="${f(y(band[0]))}" stroke="rgba(69,212,229,.35)" stroke-dasharray="3 4"/>` : '';
  const paths = lines.map((l, i) => {
    const d = l.pts.map((p, k) => `${k ? 'L' : 'M'}${f(x(p.date))} ${f(y(p.v))}`).join('');
    const last = l.pts[l.pts.length - 1];
    const fill = area && i === 0 ? `<path d="${d}L${f(x(last.date))} ${H - B}L${f(x(l.pts[0].date))} ${H - B}Z" fill="url(#${id})"/>` : '';
    return `${fill}<path d="${d}" fill="none" stroke="${l.color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"${l.dash ? ` stroke-dasharray="${l.dash}"` : ''}/><circle cx="${f(x(last.date))}" cy="${f(y(last.v))}" r="4.2" fill="${l.color}" stroke="#0F1518" stroke-width="2"/>`;
  }).join('');
  const dates = [...new Set(lines[0].pts.map((p) => p.date))];
  const xl = [dates[0], dates[Math.floor(dates.length / 2)], dates[dates.length - 1]].map((d, i) =>
    `<text x="${f(x(d))}" y="${H - 8}" text-anchor="${i === 0 ? 'start' : i === 2 ? 'end' : 'middle'}" font-size="10" fill="#65727A">${shortDate(d)}</text>`).join('');
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(opts.label || 'Serie temporal')}"><defs><linearGradient id="${id}" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="${lines[0].color}" stop-opacity=".28"/><stop offset="1" stop-color="${lines[0].color}" stop-opacity="0"/></linearGradient></defs>${ticks}${bandSvg}${paths}${xl}</svg>`;
}

// ------------------------------------------------------------ hojas inferiores
let lastFocus = null;
function openSheet(html) {
  lastFocus = document.activeElement;
  sheetBody.innerHTML = html + '<button class="close" data-close>Cerrar</button>';
  sheetEl.hidden = false;
  sheetEl.querySelector('.sheet-panel').focus();
}
function closeSheet() {
  sheetEl.hidden = true;
  if (lastFocus && lastFocus.focus) lastFocus.focus();
}
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !sheetEl.hidden) closeSheet(); });
const LEGEND_KV = `<div class="kv">
<div class="r"><span>MED</span><span>Medido por un dispositivo</span></div>
<div class="r"><span>CALC</span><span>Calculado a partir de datos medidos</span></div>
<div class="r"><span>EST</span><span>Estimado, con incertidumbre</span></div>
<div class="r"><span>EXP</span><span>Experimental, sin validar</span></div></div>`;
function howtoSheet() {
  openSheet(`<h3 id="sheet-title">Cómo leer estos indicadores</h3>
<p>La <b style="color:#F0EEE7">aguja</b> marca tu valor más reciente y la <b style="color:#F0EEE7">franja resaltada</b> es tu rango habitual: la media de tus días disponibles más o menos media desviación típica.</p>
<p><b style="color:#F0EEE7">Sistema nervioso</b> usa la media de los últimos 7 días; <b style="color:#F0EEE7">Noche</b>, la última noche; <b style="color:#F0EEE7">Carga</b> solo describe la dirección de tu forma y no la juzga. El texto de debajo compara con tu propia referencia y aparece cuando hay datos suficientes.</p>
<p>Cada dato lleva su naturaleza y su origen:</p>${LEGEND_KV}`);
}
function sourceSheet(name, sources) {
  const s = sources.find((x) => x.source === name);
  if (!s) return;
  const st = chipState(s);
  const rows = [['Estado', st.text]];
  if (s.last_ok) rows.push(['Última sincronización correcta', new Date(s.last_ok).toLocaleString('es-ES', {dateStyle: 'medium', timeStyle: 'short'})]);
  if (s.endpoint && s.endpoint !== '—') rows.push(['Datos', s.endpoint]);
  const extra = s.level === 'none'
    ? '<p>Esta fuente aún no ha sincronizado con este servicio. Cuando lo haga, aparecerá aquí con su hora.</p>'
    : s.error ? `<p style="color:#D67968">${esc(s.error)}</p>` : '';
  openSheet(`<h3 id="sheet-title">${esc(SRC_NAME[name] || name)}</h3><div class="kv">${rows.map(([k, v]) => `<div class="r"><span>${esc(k)}</span><span>${esc(v)}</span></div>`).join('')}</div>${extra}`);
}
document.addEventListener('click', (e) => {
  if (e.target.closest('[data-close]')) return closeSheet();
  if (e.target.closest('[data-howto]')) return howtoSheet();
  const c = e.target.closest('[data-chip]');
  if (c) return sourceSheet(c.dataset.chip, ROUTE_STATE.sources || []);
  if (e.target.closest('[data-sync]')) return route(true);
  const seg = e.target.closest('[data-days]');
  if (seg) return setDays(+seg.dataset.days);
});

// ------------------------------------------------------------------- vistas
const ROUTE_STATE = {sources: [], days: 28, progDays: 28, data: null, syncMode: 'read_only'};
function pageTop(sources) {
  const date = new Date().toLocaleDateString('es-ES', {weekday: 'long', day: 'numeric', month: 'long'});
  return `<header class="top"><div class="brand">${MARK}<div><h1>ARES</h1><div class="date">${esc(cap(date))}</div></div></div>
<button class="sync" data-sync aria-label="Recargar pantalla, no sincroniza las fuentes" title="Recargar datos locales, no sincroniza con los dispositivos">${svg('sync')}<span class="dot ${syncDot(sources)}"></span></button></header>`;
}
function chips(sources) {
  const rank = {none: 0, ok: 1, warn: 2, bad: 3};
  const by = {};
  sources.forEach((s) => {  // varios endpoints por fuente: manda el peor y, a igualdad, el más antiguo
    const cur = by[s.source];
    const worse = !cur || rank[s.level] > rank[cur.level] ||
      (s.level === cur.level && (s.age_min ?? 0) > (cur.age_min ?? 0));
    if (worse) by[s.source] = s;
  });
  const order = ['whoop', 'intervals', 'tredict'];
  const list = order.filter((k) => by[k]).map((k) => by[k]);
  return `<div class="chips">${list.map((s) => {
    const st = chipState(s);
    return `<button class="chip" data-chip="${esc(s.source)}" aria-label="${esc(SRC_NAME[s.source] || s.source)}: ${esc(st.text)}. Ver detalle">${GLYPH[s.source] || ''}<span class="${st.cls}"><b>${esc(SRC_NAME[s.source] || s.source)}</b><small><i class="dot-s"></i>${esc(st.text)}</small></span></button>`;
  }).join('')}</div>`;
}
const WAVE = `<svg class="wave" viewBox="0 0 200 110" fill="none" aria-hidden="true"><path d="M0 80C25 30 45 100 75 55S130 25 160 45 190 20 200 10" stroke="#D5B27A" stroke-opacity=".5" stroke-width="1.6"/><path d="M0 98C30 60 55 108 90 78S140 50 170 68 195 40 200 34" stroke="#D5B27A" stroke-opacity=".28" stroke-width="1.4"/></svg>`;
const LEVEL_TXT = {sin_cambios: 'Mantener plan', vigilar: 'Vigilar', evitar_intensidad: 'Evitar intensidad', descanso: 'Descanso o revisar salud'};
function hero(e) {
  if (e.mode === 'sombra') {
    const hasBaseline = e.nights >= e.target;
    return `<section class="card hero" aria-label="Estado de hoy"><div class="row"><span class="eyebrow">Estado de hoy</span><span class="pill sig">${hasBaseline ? 'Validación pendiente' : 'Modo sombra'}</span></div>
<h2>${hasBaseline ? 'Línea base disponible' : 'Construyendo tu línea base'}</h2><p>${hasBaseline
      ? 'Ya hay noches suficientes para calcular referencias. Las recomendaciones de entrenamiento siguen desactivadas hasta validar sus reglas.'
      : 'Estamos recopilando datos para establecer tu referencia personal. Mientras tanto puedes consultar tus datos y tendencias.'}</p>${WAVE}</section>`;
  }
  return `<section class="card hero" aria-label="Estado de hoy"><div class="row"><span class="eyebrow">Estado de hoy</span><span class="pill sig">${esc(e.date)}</span></div>
<h2>${esc(LEVEL_TXT[e.level] || e.level)}</h2>${e.cause ? `<p>${esc(e.cause)}</p>` : ''}${WAVE}</section>`;
}
function baseline(e) {
  const pct = Math.min(100, Math.round(100 * e.nights / e.target));
  const ready = e.nights >= e.target;
  return `<section class="card base" aria-label="Línea base"><div class="ic">${svg('db')}</div>
<div><div class="top2"><span class="eyebrow">Línea base</span><span class="mono" style="font-size:11px;color:var(--sig)">${pct} %</span></div><h3>${ready ? 'Referencia estadística disponible' : 'Construyendo tu referencia'}</h3></div>
<div class="full"><div class="bar" role="progressbar" aria-valuenow="${Math.min(e.nights, e.target)}" aria-valuemin="0" aria-valuemax="${e.target}" aria-label="Noches válidas"><i style="width:${pct}%"></i></div>
<div class="muted"><b style="color:var(--txt)">${e.nights} noches válidas</b> · objetivo inicial ${e.target}. ${ready ? 'Hay histórico suficiente para calcular referencias, pero las decisiones están pendientes de validación.' : 'Esperando más noches para construir la referencia.'}</div></div></section>`;
}
function sigRow(s) {
  const [title, sub] = s.label.split(' · ');
  return `<a class="sig-row" href="#/senal/${s.key}?d=28"><div class="l1"><b>${esc(title)}</b><span>${esc(sub || '')}</span></div>
<div class="side">${tagChip(s.tag, s.origin)}${spark(s.spark)}</div>
<div class="val">${splitUnit(s.value)}</div><div class="note">${esc(s.note)}</div></a>`;
}
function nativeWhoop(w) {
  if (!w || !w.nights) return '';
  const n = w.latest;
  const fmt = (v, unit = '', decimals = 0) =>
    v === null || v === undefined || !Number.isFinite(Number(v))
      ? '—'
      : Number(v).toLocaleString('es-ES', {maximumFractionDigits: decimals}) + unit;
  const h = n.sleep_min === null || n.sleep_min === undefined
    ? '—' : `${Math.floor(n.sleep_min / 60)}:${String(n.sleep_min % 60).padStart(2, '0')} h`;
  const quality = n.quality === 'high' ? 'Alta'
    : n.quality === 'fair' ? 'Aceptable' : 'No válida para línea base';
  return `<section class="card" aria-label="Datos fisiológicos directos de WHOOP">
    <div class="row" style="display:flex;justify-content:space-between;align-items:center;gap:12px">
      <span class="eyebrow">WHOOP · conexión directa</span>
      <span class="pill">${esc(quality)}</span>
    </div>
    <p class="muted" style="margin:9px 0 12px">Noche del ${esc(shortDate(n.date))} ·
      ${w.valid_nights} de ${w.nights} noches válidas en las últimas ${w.nights} registradas.
      ${esc(n.score_state === 'SCORED' ? '' : 'Puntuación pendiente o no disponible.')}</p>
    <div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px">
      <div><div class="eyebrow">Sueño efectivo</div><div class="big">${esc(h)}</div></div>
      <div><div class="eyebrow">VFC · rMSSD</div><div class="big">${esc(fmt(n.rmssd_ms, ' ms'))}</div></div>
      <div><div class="eyebrow">Pulso en reposo</div><div class="big">${esc(fmt(n.rhr, ' lpm'))}</div></div>
      <div><div class="eyebrow">Recovery WHOOP</div><div class="big">${esc(fmt(n.provider_recovery, ' %'))}</div></div>
    </div>
    <p class="muted" style="margin:12px 0 0">MED · Datos de WHOOP.
      La recuperación % es el cálculo propio de WHOOP, no una decisión de ARES.
      Los indicadores posteriores que indiquen «vía INTERVALS» proceden de otra fuente.</p>
  </section>`;
}

function pairedMetrics(f) {
  if (!f || !f.latest) return '';
  const last = f.latest;
  const label = (f.intervals_device || 'Reloj') + ' · Intervals';
  const show = (raw, kind) => {
    if (raw === null || raw === undefined || !Number.isFinite(Number(raw))) return '—';
    if (kind === 'sleep_min') {
      const minutes = Math.round(Number(raw));
      return `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, '0')} h`;
    }
    return Number(raw).toLocaleString('es-ES', {maximumFractionDigits: 1}) +
      (kind === 'hrv' ? ' ms' : ' lpm');
  };
  const metric = (title, key) => {
    const row = last.metrics[key];
    const cell = (name, value) => `<div><span class="eyebrow" style="font-size:10px">${esc(name)}</span><div style="font-size:17px;font-weight:650;margin-top:4px">${esc(show(value, key))}</div></div>`;
    return `<div style="padding:12px 0;border-top:1px solid rgba(255,255,255,.10)">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:9px"><b>${esc(title)}</b>
        <span class="tag ${key === 'hrv' ? 'exp' : 'calc'}">${key === 'hrv' ? 'EXP' : 'CALC'} · ARES</span></div>
      <div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px">
        ${cell('WHOOP', row.whoop)}
        ${cell(f.intervals_device || 'COROS', row.intervals)}
        ${cell('MEDIA', row.mean)}
      </div>
    </div>`;
  };
  const missing = f.matched_days === 0
    ? 'Todavía no hay fechas comparables entre ambas fuentes.'
    : `Comparación disponible en ${f.matched_days} fechas; medias solo entre valores del mismo día.`;
  return `<section class="card" aria-label="Media combinada COROS y WHOOP">
    <div class="row" style="display:flex;align-items:center;justify-content:space-between;gap:10px">
      <span class="eyebrow">ARES · DOS DISPOSITIVOS</span>
      <span class="pill">${esc(shortDate(last.date))}</span>
    </div>
    <h3 style="margin:10px 0 6px">Media WHOOP + ${esc(f.intervals_device)}</h3>
    <p class="muted" style="margin:0 0 12px;font-size:12px">${esc(missing)}</p>
    ${metric('Sueño efectivo', 'sleep_min')}
    ${metric('Pulso en reposo', 'rhr')}
    ${metric('VFC · rMSSD', 'hrv')}
    <p class="muted" style="font-size:12px;margin:12px 0 0">Cada media pondera 50/50 cuando hay dos registros compatibles. 
      Si falta un dato o WHOOP excluye la noche, se muestra «—». La VFC combinada es
      <b>experimental</b>: ambos sensores pueden usar ventanas de medición distintas;
      no se emplea para decidir el entrenamiento. La procedencia «${esc(label)}»
      es la declarada en ARES, no está certificada por la API de Intervals.</p>
  </section>`;
}

function renderInicio(d) {
  ROUTE_STATE.sources = d.sources;
  ROUTE_STATE.syncMode = d.sync_mode || ROUTE_STATE.syncMode;
  const steps = d.steps === null
    ? '<span class="muted">Sin pasos todavía.</span>'
    : `<div><div class="eyebrow">Pasos · ${esc(shortDate(d.steps_day || d.last_day))}</div><div class="big">${d.steps.toLocaleString('es-ES')}</div></div><span class="muted">${esc(d.steps_source || 'intervals.icu')}</span>`;
  view.innerHTML = pageTop(d.sources) + chips(d.sources) + syncNotice(ROUTE_STATE.syncMode) + hero(d.estado) + nativeWhoop(d.whoop) + pairedMetrics(d.fusion) +
    `<div class="gauges" role="group" aria-label="Indicadores principales">${d.dials.map(gauge).join('')}</div>
<button class="howto" data-howto>${svg('info')}Cómo leer estos indicadores</button>` + baseline(d.estado) +
    `<div class="h2"><span class="eyebrow">Señales principales</span></div>${d.signals.map(sigRow).join('')}
<div class="h2"><span class="eyebrow">Actividad</span></div><section class="card tile">${steps}</section>`;
  animateGauges();
}

function renderSenal(d) {
  ROUTE_STATE.sources = ROUTE_STATE.sources || [];
  const seg = `<div class="seg" role="group" aria-label="Periodo">${d.periods.map((p) =>
    `<button data-days="${p}" aria-pressed="${p === d.days}">${p === 365 ? '1 A' : p + ' D'}</button>`).join('')}</div>`;
  const head = `<header class="dtop"><a class="back" href="#/inicio" aria-label="Volver a Inicio">${svg('back')}</a>
<h1>${esc(d.label)}<small>${esc(d.long)}</small></h1>${tagChip(d.tag, d.origin)}</header>`;
  if (d.empty) {
    view.innerHTML = head + '<section class="card"><p class="muted" style="margin:0">Todavía no hay datos de esta señal en la base.</p></section>';
    return;
  }
  const lvl = d.level;
  const stateTxt = d.kind === 'trend' ? `Tendencia: ${d.state}`
    : d.range === null ? 'Sin rango' : `${d.agg === 'mean7' ? 'Media 7 d' : 'Última noche'} · ${d.state}`;
  const rows = [['Fuente', d.source_label || 'intervals.icu'], ['Naturaleza', d.nature], ['Actualizado', cap(ageText(d.updated_min))],
    ['Serie utilizada', dias(d.available_days)]];
  if (d.range) {
    rows.push(['Media de referencia', `${d.mean_ref} (${d.n_ref} d)`], ['Rango habitual', `${d.range.lo_s} – ${d.range.hi_s}`]);
  }
  if (d.agg === 'mean7') rows.push(['Media 7 d', d.mean7]);
  rows.push(['Cobertura del periodo', `${d.coverage} %`]);
  const s = d.stats;
  view.innerHTML = head + seg +
    `<section class="card"><div class="hval"><span class="n">${splitUnit(d.value)}</span><span class="state ${lvl === 'ok' ? 'ok' : lvl === 'warn' ? 'warn' : ''}">${esc(stateTxt)}</span></div>
<p class="muted" style="margin:6px 0 var(--sp3)">Último valor (${esc(shortDate(d.date))})${d.mean_ref ? ` · media ${d.n_ref} d: ${esc(d.mean_ref)}` : ''}</p>
${lineChart([{pts: d.series, color: '#D5B27A'}], {band: d.range ? [d.range.lo, d.range.hi] : null, label: `${d.label}, últimos ${d.days} días`})}
${d.partial ? `<p class="muted" style="margin:8px 0 0">Solo hay ${dias(d.available_days)} de datos en la base; el periodo de ${d.days === 365 ? '1 año' : d.days + ' días'} se completará con el tiempo.</p>` : ''}</section>
<section class="card"><div class="stats"><div><small>Mín</small><b>${esc(s.min)}</b></div><div><small>Media</small><b>${esc(s.mean)}</b></div><div><small>Máx</small><b>${esc(s.max)}</b></div><div><small>Último</small><b>${esc(s.last)}</b></div></div></section>
<section class="card callout ${lvl === 'warn' ? 'warn' : ''}"><h3>${esc(d.interpretation.title)}</h3><p>${esc(d.interpretation.text)}</p></section>
<section class="card"><div class="eyebrow" style="margin-bottom:6px">Procedencia</div><div class="kv">${rows.map(([k, v]) => `<div class="r"><span>${esc(k)}</span><span>${esc(v)}</span></div>`).join('')}</div></section>
<details class="card"><summary>Qué es ${esc(d.label)}${svg('chev', 'chev')}</summary><p>${esc(d.about)}</p></details>`;
}

function renderProgreso(d) {
  ROUTE_STATE.data = d;
  const days = ROUTE_STATE.progDays;
  const cut = (arr) => {
    if (!arr.length) return arr;
    const end = Date.parse(arr[arr.length - 1].date), from = end - (days - 1) * 86400000;
    return arr.filter((p) => Date.parse(p.date) >= from).map((p) => ({date: p.date, v: p.v}));
  };
  const seg = `<div class="seg" role="group" aria-label="Periodo">${[7, 28, 90, 365].map((p) =>
    `<button data-days="${p}" aria-pressed="${p === days}">${p === 365 ? '1 A' : p + ' D'}</button>`).join('')}</div>`;
  const st = d.stats;
  const sg = (v) => (v > 0 ? '+' : v < 0 ? '−' : '±') + Math.abs(v).toFixed(1);
  const head = `<div class="h2"><h2 style="margin:0;font-size:26px;font-weight:700">Progreso</h2></div>`;
  const form = st ? `<section class="card"><div class="row" style="display:flex;justify-content:space-between;align-items:center"><span class="eyebrow">Forma y fatiga</span>${tagChip('CALC', 'INTERVALS')}</div>
<div class="stats" style="grid-template-columns:repeat(3,1fr);margin:var(--sp3) 0"><div><small>Forma (CTL)</small><b style="font-size:24px">${st.ctl.toFixed(0)}</b></div><div><small>Fatiga (ATL)</small><b style="font-size:24px">${st.atl.toFixed(0)}</b></div><div><small>Balance</small><b style="font-size:24px">${sg(st.form)}</b></div></div>
${lineChart([{pts: cut(d.ctl), color: '#D5B27A'}, {pts: cut(d.atl), color: '#D7A56B', dash: '4 4'}], {label: 'Forma y fatiga'})}
<div class="muted" style="display:flex;gap:16px;margin-top:8px"><span><span class="dot-s ok" style="display:inline-block;margin-right:6px"></span>Forma (CTL)</span><span><span class="dot-s" style="display:inline-block;margin-right:6px;background:#D7A56B"></span>Fatiga (ATL)</span>${st.ramp !== null ? `<span style="margin-left:auto">Ritmo de subida ${sg(st.ramp)} / sem</span>` : ''}</div></section>
<details class="card"><summary>De dónde salen forma y fatiga${svg('chev', 'chev')}</summary>
<p>Son dos promedios de la carga diaria de entrenamiento que calcula intervals.icu (un modelo de tipo Banister/Coggan): la <b style="color:#F0EEE7">forma</b> mira semanas (por defecto 42 días) y la <b style="color:#F0EEE7">fatiga</b>, días (por defecto 7). Sube la forma si entrenas de forma sostenida; sube la fatiga si concentras carga en pocos días.</p>
<p><b style="color:#F0EEE7">Balance = forma − fatiga.</b> Negativo significa que la carga reciente supera a la habitual; positivo, que vienes de descansar.</p>
<p>La carga de cada sesión es una <b style="color:#F0EEE7">estimación de intervals.icu</b> (con FC, potencia o ritmo, según lo que traiga cada actividad), no una medida fisiológica. ARES la muestra tal cual y no la reinterpreta. Hoy: forma ${st.ctl.toFixed(0)}, fatiga ${st.atl.toFixed(0)}, balance ${sg(st.form)}.</p></details>` : '<section class="card"><p class="muted" style="margin:0">Sin datos de forma y fatiga todavía.</p></section>';
  const w = d.weeks, mx = Math.max(3, ...w.map((x) => x.sessions)), totS = w.reduce((a, x) => a + x.sessions, 0), totR = w.reduce((a, x) => a + x.running, 0);
  const bars = `<section class="card"><div class="row" style="display:flex;justify-content:space-between;align-items:center"><span class="eyebrow">Sesiones por semana</span>${tagChip('MED', 'TREDICT')}</div>
<div class="bars">${w.map((x) => `<div><b>${x.sessions || ''}</b><i class="${x.sessions ? '' : 'zero'}" style="height:${Math.max(3, 84 * x.sessions / mx)}px"></i><span>${shortDate(x.week)}</span></div>`).join('')}</div>
<p class="muted" style="margin:12px 0 0">${totS} sesiones en 8 semanas, ${totR} de carrera. La lista de Tredict no trae distancia, tiempo ni carga por sesión: esos datos llegan al sincronizar las actividades completas.</p></section>`;
  view.innerHTML = pageTop(ROUTE_STATE.sources) + head + seg + form + bars +
    `<section class="card"><p class="muted" style="margin:0"><b style="color:var(--txt)">Fase 2 · pendiente.</b> Ritmo a pulso fijo, durabilidad y la proyección hacia sub-3 no se muestran hasta que existan de verdad.</p></section>`;
}

function renderLab(d) {
  ROUTE_STATE.sources = d.sources;
  const src = d.sources.map((s) => {
    const st = chipState(s);
    return `<div class="r"><span class="dot-s ${st.cls === 'ok' ? 'ok' : ''}" style="${st.cls === 'warn' ? 'background:#D7A56B' : st.cls === 'bad' ? 'background:#D67968' : ''}"></span><div><b>${esc(SRC_NAME[s.source] || s.source)}</b><small>${esc(s.endpoint)}${s.error ? ' · ' + esc(s.error) : ''}</small></div><span class="mono" style="font-size:11px;color:var(--mut)">${esc(st.text)}</span></div>`;
  }).join('');
  const raw = d.raw.length
    ? `<table><thead><tr><th>FUENTE</th><th>FILAS</th><th>DESDE</th><th>HASTA</th></tr></thead><tbody>${d.raw.map((r) => `<tr><td>${esc(r.source)}/${esc(r.endpoint)}</td><td>${r.rows}</td><td>${esc(shortDate(r.from))}</td><td>${esc(shortDate(r.to))}</td></tr>`).join('')}</tbody></table>`
    : '<p class="muted" style="margin:0">Capa bruta vacía.</p>';
  const runs = d.runs.length
    ? `<div class="list">${d.runs.map((r) => `<div class="r" style="grid-template-columns:1fr auto"><div><b>${esc(r.job)}</b><small>${esc(r.started.slice(0, 16).replace('T', ' '))} UTC</small></div><span class="pill ${r.status === 'ok' ? 'sig' : ''}">${esc(r.status)}</span></div>`).join('')}</div>`
    : '<p class="muted" style="margin:0">Sin ejecuciones registradas.</p>';
  view.innerHTML = pageTop(d.sources) + `<div class="h2"><h2 style="margin:0;font-size:26px;font-weight:700">Laboratorio</h2></div>
<section class="card"><div class="eyebrow" style="margin-bottom:8px">Validación</div><p class="muted" style="margin:0">Todavía no hay decisiones que validar: el modo sombra dura hasta las 21 noches válidas.</p></section>
<section class="card"><div class="row" style="display:flex;justify-content:space-between;align-items:center"><span class="eyebrow">Gate técnico nº 1 · VFC de WHOOP frente a la H10</span><span class="pill">${esc(d.gate.level)}</span></div>
<p class="muted" style="margin:10px 0 0">${d.gate.n_h10} noches con la H10. ${esc(d.gate.criteria)}. Hasta superarlo, la VFC lleva la etiqueta EXP.</p></section>
<section class="card"><div class="eyebrow" style="margin-bottom:4px">Fuentes</div><div class="list">${src}</div></section>
<section class="card"><div class="eyebrow" style="margin-bottom:10px">Capa bruta</div>${raw}</section>
<section class="card"><div class="eyebrow" style="margin-bottom:4px">Últimas ejecuciones</div>${runs}</section>
<section class="card"><div class="eyebrow" style="margin-bottom:8px">Versiones</div><p class="muted mono" style="margin:0;font-size:12px">esquema v${esc(d.versions.schema)} · reglas ${esc(d.versions.rules)} · algoritmo ${esc(d.versions.algo)} · código ${esc(d.versions.code)}</p></section>
<section class="card"><div class="eyebrow" style="margin-bottom:8px">Leyenda</div>${LEGEND_KV}</section>`;
}

// ------------------------------------------------------ laboratorio fisiológico
function physFmt(value, unit) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—';
  const num = Number(value);
  if (unit === 'min') {
    const minutes = Math.round(num);
    return `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, '0')} h`;
  }
  return num.toLocaleString('es-ES', {maximumFractionDigits: unit === '°C' || unit === 'rpm' ? 1 : 0}) + ' ' + unit;
}
function physChart(points, title) {
  const valid = points.filter((p) => p.v !== null && Number.isFinite(Number(p.v)));
  if (valid.length < 2) return '<p class="muted" style="margin:12px 0">No hay suficientes medidas válidas para la gráfica.</p>';
  const W = 330, H = 110, top = 7, bottom = 22, left = 12, right = 8;
  const lo = Math.min(...valid.map((p) => p.v));
  const hi = Math.max(...valid.map((p) => p.v));
  const pad = (hi - lo || 1) * .15, lower = lo - pad, upper = hi + pad;
  const x = (i) => left + (W-left-right) * i / Math.max(points.length-1, 1);
  const y = (v) => top + (H-top-bottom) * (1 - (v-lower)/(upper-lower));
  // Un valor ausente interrumpe el trazo: no fingimos continuidad.
  let path = '', active = false;
  points.forEach((p, i) => {
    if (p.v === null || !Number.isFinite(Number(p.v))) { active = false; return; }
    path += `${active ? 'L' : 'M'}${x(i).toFixed(1)} ${y(p.v).toFixed(1)}`;
    active = true;
  });
  const first = points[0]?.date || '', last = points[points.length-1]?.date || '';
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img"
    aria-label="${esc(title)} · ${valid.length} registros válidos, ${esc(shortDate(first))} a ${esc(shortDate(last))}">
    <path d="${path}" fill="none" stroke="#D5B27A" stroke-width="2.4"
      stroke-linecap="round" stroke-linejoin="round"/>
    <text x="${left}" y="${H-3}" fill="#8C979B" font-size="11">${esc(shortDate(first))}</text>
    <text x="${W-right}" y="${H-3}" fill="#8C979B" text-anchor="end" font-size="11">${esc(shortDate(last))}</text>
    </svg>`;
}
function physCard(m) {
  const d = m.difference === null || m.relative_change_pct === null ? null : (m.difference > 0 ? '+' : '') + physFmt(m.difference, m.unit);
  return `<section class="card" aria-label="${esc(m.label)}">
    <div style="display:flex;justify-content:space-between;align-items:center;gap:8px">
      <span class="eyebrow">${esc(m.label)}</span>
      ${tagChip(m.key === 'recovery' ? 'CALC' : 'MED', m.origin)}
    </div>
    <div class="big" style="margin:12px 0 2px">${esc(physFmt(m.latest, m.unit))}</div>
    <p class="muted" style="margin:0 0 12px">Última noche registrada · ${m.n28} noches con medición en los últimos 28 días</p>
    ${physChart(m.series, m.label)}
    <div class="stats" style="grid-template-columns:repeat(3,1fr);margin-top:12px">
      <div><small>Media 7 días</small><b>${esc(physFmt(m.mean7, m.unit))}</b></div>
      <div><small>Media 28 días</small><b>${esc(physFmt(m.mean28, m.unit))}</b></div>
      <div><small>Referencia previa</small><b>${esc(physFmt(m.reference, m.unit))}</b></div>
    </div>
    <p class="muted" style="margin:12px 0 0">
      ${d === null ? 'Variación frente a referencia: datos insuficientes.' :
        'Cambio en media de 7 días frente a 28 días anteriores: ' + esc(d) +
        ' (' + (m.relative_change_pct > 0 ? '+' : '') +
        esc(m.relative_change_pct.toFixed(1)) + '%).'}
      ${m.n_reference} noches sustentan la referencia; interpretación estadística, no diagnóstica.
    </p>
  </section>`;
}
function renderFisiologia(d) {
  ROUTE_STATE.physDays = d.days;
  const controls = [28, 90, 365].map((n) =>
    `<button data-days="${n}" aria-pressed="${n===d.days}">${n===365 ? '1 año' : n+' días'}</button>`).join('');
  const quality = d.breakdown;
  const headline = d.anchor_date
    ? `${d.usable_nights} noches utilizables de ${d.nights} procesadas entre ${esc(shortDate(d.first_date))} y ${esc(shortDate(d.anchor_date))}.`
    : 'Todavía no hay noches sincronizadas desde WHOOP.';
  view.innerHTML = pageTop(ROUTE_STATE.sources) +
    `<div class="h2"><h2 style="margin:0;font-size:26px;font-weight:700">Tu fisiología</h2></div>
    <section class="card"><div class="eyebrow">Histórico de WHOOP</div>
    <h3 style="margin:12px 0">Un mapa de cómo responde tu cuerpo</h3>
    <p class="muted" style="margin:0">${headline}</p>
    <div class="seg" style="margin-top:14px" aria-label="Periodo fisiológico">${controls}</div>
    <p class="muted" style="margin:12px 0 0">Calidad de origen: ${quality.high} altas,
      ${quality.fair} aceptables, ${quality.excluded} excluidas.
      ${quality.night_flags ? quality.night_flags + ' noches con comprobaciones pendientes.' : ''}
      No se interpolan fechas ni se sustituyen datos ausentes.</p></section>` +
    d.metrics.map(physCard).join('') +
    `<details class="card"><summary>Cómo calcula ARES tu referencia${svg('chev','chev')}</summary>
      <p>${esc(d.reference_method)}</p><p>${esc(d.caution)}</p>
      <p>La VFC, el pulso y las etapas de sueño son estimaciones ópticas del dispositivo;
      para recomendaciones deportivas deberemos contrastarlos con las sesiones de COROS,
      Tredict y, cuando proceda, la banda pectoral H10.</p></details>`;
}

// ----------------------------------------------------- explorador de entrenos
function runTime(sec) {
  if (sec === null || sec === undefined || !Number.isFinite(Number(sec)) || sec < 0) return '—';
  const s = Math.round(sec);
  return s >= 3600
    ? `${Math.floor(s / 3600)}h ${String(Math.floor(s % 3600 / 60)).padStart(2, '0')}m`
    : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}
function runPace(sec) {
  if (sec === null || sec === undefined || !Number.isFinite(Number(sec)) || sec <= 0) return '—';
  const s = Math.round(sec);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')} /km`;
}
function runSeries(points, title, color) {
  const valid = points.filter((p) => p.v !== null && Number.isFinite(Number(p.v)));
  if (valid.length < 2) return '<p class="muted" style="margin:6px 0">Este sensor no aportó una serie suficiente.</p>';
  const W = 330, H = 112, left = 10, right = 8, top = 8, bottom = 18;
  const maxT = Math.max(...points.map((p) => p.second), 1);
  let min = Math.min(...valid.map((p) => p.v)), max = Math.max(...valid.map((p) => p.v));
  const pad = (max - min || 1) * .14; min -= pad; max += pad;
  const x = (t) => left + (W-left-right)*t/maxT;
  const y = (v) => top + (H-top-bottom)*(1-(v-min)/(max-min));
  let path = '', prev = false;
  for (const p of points) {
    if (p.v === null || !Number.isFinite(Number(p.v))) {prev = false; continue;}
    path += `${prev ? 'L' : 'M'}${x(p.second).toFixed(1)} ${y(p.v).toFixed(1)}`;
    prev = true;
  }
  return `<svg viewBox="0 0 ${W} ${H}" class="chart" role="img"
    aria-label="${esc(title)}, ${valid.length} puntos disponibles">
    <path d="${path}" stroke="${color}" stroke-width="2" fill="none" stroke-linecap="round"/>
    <text x="${left}" y="${H-3}" fill="#8C979B" font-size="10">0 min</text>
    <text x="${W-right}" y="${H-3}" text-anchor="end" fill="#8C979B" font-size="10">${Math.round(maxT/60)} min</text>
  </svg>`;
}
function syncNotice(mode) {
  return mode === 'automatic'
    ? `<div class="sync-note"><b>Sincronización automática activa.</b>
      ARES consulta las fuentes al arrancar y en sus ventanas programadas.
      El botón circular recarga la pantalla, no fuerza una descarga.</div>`
    : `<div class="sync-note"><b>Vista local · datos sin sincronización automática.</b>
      Para obtener nuevos datos, detén <code>ares app</code> y arranca
      <code>uv run ares serve</code>. El botón circular solo recarga la pantalla.</div>`;
}
function renderEntrenos(d) {
  ROUTE_STATE.syncMode = d.sync_mode || ROUTE_STATE.syncMode;
  const category = d.category === 'other' ? 'other' : 'running';
  const counts = d.counts || {running:0, other:0};
  const tabs = `<nav class="training-tabs" aria-label="Tipos de entrenamiento">
    <a href="#/entrenos?tipo=correr" ${category === 'running' ? 'aria-current="page"' : ''}>
      Correr <small>${counts.running}</small></a>
    <a href="#/entrenos?tipo=otros" ${category === 'other' ? 'aria-current="page"' : ''}>
      Otros <small>${counts.other}</small></a>
  </nav>`;
  const comparisons = (d.comparisons || []).map((p) => {
    const sign = p.speed_change_pct > 0 ? '+' : '';
    return `<div style="padding:12px 0;border-top:1px solid var(--line)">
      <div class="row" style="display:flex;justify-content:space-between;gap:8px">
        <span class="eyebrow">${esc(shortDate(p.old_date))} → ${esc(shortDate(p.new_date))}</span>
        <b class="mono" style="font-size:16px">${esc(sign + p.speed_change_pct.toFixed(1))} %</b>
      </div>
      <p class="muted" style="margin:6px 0 0">
        ${esc(runPace(p.old_pace_s_km))} → ${esc(runPace(p.new_pace_s_km))}
        · FC ${esc(p.old_avg_hr)} → ${esc(p.new_avg_hr)} lpm
        · ${esc(p.old_distance_km)} → ${esc(p.new_distance_km)} km.
      </p>
      <div style="display:flex;gap:18px;margin-top:9px">
        <a href="#/entreno/${encodeURIComponent(p.old_id)}" style="color:var(--sig)">Anterior</a>
        <a href="#/entreno/${encodeURIComponent(p.new_id)}" style="color:var(--sig)">Reciente</a>
      </div>
    </div>`;
  }).join('');
  const comparisonPanel = comparisons && category === 'running' ? `<section class="card">
    <div class="row" style="display:flex;align-items:center;justify-content:space-between">
      <span class="eyebrow">Comparador de sesiones</span>${tagChip('EXP','ARES')}
    </div><h3 style="margin:10px 0 6px">¿Mejora tu ritmo a pulso similar?</h3>
    <p class="muted" style="margin:0 0 12px">Parejas con distancia ±10 % y FC media ±5 lpm.
      Diferencias descriptivas, no causales.</p>${comparisons}</section>` : '';
  const dates = d.last_record_dates || {};
  const maxDate = (keys) => keys.map(k => dates[k]).filter(Boolean).sort().at(-1);
  const lastTraining = category === 'running'
    ? maxDate(['tredict/activity_detail', 'tredict/activity'])
    : maxDate(['whoop/workout', 'tredict/activity_detail', 'tredict/activity']);
  const cards = d.sessions.map((a) => {
    const isWhoop = a.source === 'whoop';
    const distance = a.distance_m === null ? '—' :
      (a.distance_m / 1000).toLocaleString('es-ES', {maximumFractionDigits:2})+' km';
    return `<a href="#/entreno/${encodeURIComponent(a.id)}" class="card workout-tile"
      aria-label="Abrir entrenamiento ${esc(a.title)}">
      <div class="row" style="display:flex;justify-content:space-between;gap:12px;align-items:center">
        <span class="eyebrow">${esc(a.sport)} · ${esc(shortDate(a.date))}</span>
        <span class="source-mark ${isWhoop ? 'source-whoop' : 'source-coros'}">
          ${isWhoop ? 'WHOOP' : 'COROS · Tredict'}</span>
      </div>
      <h3 style="margin:11px 0">${esc(a.title)}</h3>
      <div class="stats" style="grid-template-columns:repeat(3,1fr)">
        <div><small>Distancia</small><b>${esc(distance)}</b></div>
        <div><small>Tiempo</small><b>${esc(runTime(a.duration_s))}</b></div>
        <div><small>${category === 'running' ? 'Ritmo' : 'FC media'}</small>
          <b>${category === 'running' ? esc(runPace(a.pace_s_km))
          : (a.avg_hr === null ? '—' : esc(a.avg_hr.toFixed(0)) + ' lpm')}</b></div>
      </div>
      <p class="muted" style="margin:10px 0 0">
        ${a.has_series ? 'Series y detalles disponibles' :
          (isWhoop ? 'Resumen de WHOOP · sin series de ritmo' :
          'Resumen disponible · importa detalle de Tredict para ver curvas')}
      </p>
    </a>`;
  }).join('');
  view.innerHTML = pageTop(ROUTE_STATE.sources) +
    '<div class="h2"><h2 style="margin:0;font-size:26px;font-weight:700">Entrenamientos</h2></div>' +
    tabs +
    `<section class="card workout-intro">
      <span class="eyebrow">${category === 'running' ? 'COROS · vía Tredict' : 'WHOOP · actividades de vida'}</span>
      <h3>${category === 'running' ? 'Cada kilómetro cuenta' : 'Movimiento más allá de correr'}</h3>
      <p class="muted" style="margin:0">${category === 'running'
        ? 'Carreras y series de tu reloj, vueltas y evolución del rendimiento.'
        : 'Caminatas, senderismo, rucking explícito y otras actividades. WHOOP es la fuente prioritaria; se omiten coincidencias próximas de Tredict.'}</p>
      <p class="muted" style="margin:10px 0 0;font-size:12px">
        Último registro de entrenamiento en la base: ${lastTraining ? esc(shortDate(lastTraining)) : 'sin registros'}.
        ${esc(d.source_caveat || '')}</p>
    </section>` +
    syncNotice(ROUTE_STATE.syncMode) + comparisonPanel +
    (cards || `<section class="card"><h3>No hay actividades de este tipo todavía</h3>
       <p class="muted">Comprueba la sincronización de fuentes. En carreras, las
       series y vueltas requieren importar también los detalles de Tredict.</p></section>`);
}

function renderTrainingIntelligence(a) {
  if (!a) return '';
  const q = a.quality || {}, drift = a.drift || {}, laps = a.laps || {};
  const pct = (x) => x === null || x === undefined ? '—' :
    Number(x).toLocaleString('es-ES', {maximumFractionDigits:1})+' %';
  const row = (title, value, note) =>
    `<div style="padding:10px 0;border-top:1px solid var(--line)">
      <div class="row" style="display:flex;align-items:center;justify-content:space-between;gap:10px">
        <b style="font-size:14px">${esc(title)}</b><b class="mono">${esc(value)}</b>
      </div><p class="muted" style="font-size:12px;margin:6px 0 0">${esc(note)}</p>
    </div>`;
  const driftDesc = drift.available
    ? `FC media ${drift.first.hr} → ${drift.second.hr} lpm; velocidad
       ${drift.first.speed_m_s} → ${drift.second.speed_m_s} m/s.
       ${drift.caution}`
    : `No calculable: ${drift.reason || 'sin datos suficientes'}. No inferimos deriva con series,
       pausas, terrenos variables o sensores incompletos.`;
  const lapDesc = laps.available
    ? `${laps.count} vueltas de longitud comparable; ritmo medio
       ${runPace(laps.mean_pace_s_km)}. ${laps.caution}`
    : `No calculable: ${laps.reason || 'faltan vueltas comparables'}.`;
  return `<section class="card" aria-label="ARES Training Intelligence">
    <div class="row" style="display:flex;justify-content:space-between;align-items:center">
      <span class="eyebrow">ARES · Training Intelligence</span>${tagChip('EXP','ARES')}
    </div>
    <h3 style="margin:12px 0 6px">Cómo respondió tu cuerpo</h3>
    <p class="muted" style="margin:0 0 14px">Análisis exploratorio basado en series reales.
      No es una evaluación médica ni sustituye una prueba de esfuerzo.</p>
    <div class="stats" style="grid-template-columns:repeat(3,minmax(0,1fr));margin:10px 0 16px">
      <div><small>FC válida</small><b>${esc(pct(q.hr_coverage_pct))}</b></div>
      <div><small>Velocidad válida</small><b>${esc(pct(q.speed_coverage_pct))}</b></div>
      <div><small>Pares FC/ritmo</small><b>${esc(pct(q.paired_coverage_pct))}</b></div>
    </div>
    ${row('Deriva FC / velocidad', drift.available ?
      (drift.value_pct > 0 ? '+' : '') + pct(drift.value_pct) : 'No evaluable', driftDesc)}
    ${row('Consistencia de vueltas', laps.available ? 'CV '+pct(laps.pace_cv_pct) :
      'No evaluable', lapDesc)}
    <p class="muted" style="font-size:12px;margin:12px 0 0">Las métricas solo
      aparecen cuando cumplen los criterios de calidad definidos.
      El signo de la deriva, por sí solo, no determina mejora ni fatiga.</p>
  </section>`;
}
function renderHrZones(z) {
  if (!z?.available) return `<section class="card"><span class="eyebrow">Zonas de pulso</span>
    <p class="muted">Sin distribución de FC verificable para esta sesión:
      ${esc(z?.reason || 'no disponible')}.</p></section>`;
  const max = Math.max(1, ...z.zones.map(r => r.seconds));
  const bars = z.zones.map((r, i) => {
    const range = r.min_hr === -1 ? `≤ ${r.max_hr} lpm` :
      r.max_hr === -1 ? `≥ ${r.min_hr} lpm` :
      `${r.min_hr}–${r.max_hr} lpm`;
    const width = Math.max(0, Math.min(100, r.seconds / max * 100));
    return `<div style="margin-top:12px">
      <div style="display:flex;justify-content:space-between;gap:8px;font-size:12px">
        <b>${esc(r.name)}</b><span class="muted">${esc(range)}</span>
        <span class="mono">${esc(runTime(r.seconds))} · ${esc(r.percent_recorded)} %</span>
      </div>
      <div style="height:8px;border-radius:99px;background:var(--s3);margin-top:6px;overflow:hidden">
        <div style="width:${width}%;height:100%;background:var(--sig);border-radius:99px;
        opacity:${(0.4 + 0.1 * i).toFixed(2)}"></div>
      </div>
    </div>`;
  }).join('');
  return `<section class="card" aria-label="Zonas de frecuencia cardíaca">
    <div class="row" style="display:flex;justify-content:space-between;align-items:center">
      <span class="eyebrow">Distribución por zonas</span>${tagChip('CALC','TREDICT')}
    </div><h3 style="margin:12px 0 6px">¿Dónde estuvo tu esfuerzo?</h3>
    <p class="muted" style="font-size:12px;margin:0">Zonas configuradas para la fecha
      de este entrenamiento. ${z.coverage_pct === null ? '' :
        'Tiempo clasificado: ' + esc(z.coverage_pct) + ' % de la duración.'}</p>
    ${bars}
    <p class="muted" style="font-size:12px;margin:12px 0 0">${esc(z.method)}</p>
  </section>`;
}

function renderTrainingContext(ctx) {
  if (!ctx) return '';
  const num = (v, unit, decimals=0) => v === null || v === undefined ? '—' :
    Number(v).toLocaleString('es-ES', {maximumFractionDigits:decimals}) + unit;
  const item = (night, heading) => night ? `<div style="flex:1;min-width:0">
    <span class="eyebrow">${esc(heading)} · ${esc(shortDate(night.date))}</span>
    <div style="margin-top:10px;font-size:15px"><b>VFC</b> ${esc(num(night.rmssd_ms,' ms'))}</div>
    <div style="margin-top:7px;font-size:15px"><b>Reposo</b> ${esc(num(night.rhr,' lpm'))}</div>
    <div style="margin-top:7px;font-size:15px"><b>Sueño</b> ${esc(runTime(night.sleep_min === null ? null : night.sleep_min*60))}</div>
    <div style="margin-top:7px;font-size:15px"><b>Recovery</b> ${esc(num(night.recovery_whoop,' %'))}</div>
  </div>` : `<div style="flex:1;min-width:0"><span class="eyebrow">${esc(heading)}</span>
    <p class="muted">No hay noche válida dentro de la ventana de 72 h.</p></div>`;
  const d = ctx.difference || {};
  const delta = ctx.before && ctx.after ?
    `<p class="muted" style="margin:12px 0 0">Cambio registrado:
      VFC ${esc(num(d.rmssd_ms,' ms',1))},
      pulso ${esc(num(d.rhr,' lpm',1))},
      sueño ${esc(num(d.sleep_min,' min',0))}.
      Son diferencias observadas entre dos noches, no efectos atribuibles al ejercicio.</p>` : '';
  return `<section class="card" aria-label="Fisiología alrededor del entrenamiento">
    <div class="row" style="display:flex;justify-content:space-between;align-items:center;gap:8px">
      <span class="eyebrow">ARES · Relación entrenamiento y fisiología</span>
      ${tagChip('CALC','ARES')}
    </div>
    <h3 style="margin:12px 0 8px">Antes y después del esfuerzo</h3>
    <div style="display:flex;gap:14px;margin-top:16px">
      ${item(ctx.before, 'Antes')}
      <div style="width:1px;background:var(--line2)"></div>
      ${item(ctx.after, 'Después')}
    </div>
    ${delta}
    <p class="muted" style="font-size:12px;margin:14px 0 0">
      ${esc(ctx.method || ctx.reason || 'No hay contexto suficiente todavía.')}</p>
  </section>`;
}
function renderEntreno(d) {
  const laps = (d.laps || []).map((l) => `<tr><td>${l.number}</td>
    <td>${l.distance_m === null ? '—' : esc((l.distance_m/1000).toFixed(2)) + ' km'}</td>
    <td>${esc(runPace(l.pace_s_km))}</td>
    <td>${l.avg_hr === null ? '—' : esc(l.avg_hr.toFixed(0))}</td>
    <td>${l.power === null ? '—' : esc(l.power.toFixed(0))}</td></tr>`).join('');
  const s = d.series || {};
  const sensors = [
    ['Frecuencia cardíaca · lpm', s.heartrate || [], '#D5B27A'],
    ['Velocidad · m/s', s.speed || [], '#D7A56B'],
    ['Potencia · W', s.power || [], '#7ABBAA'],
    ['Cadencia', s.cadence || [], '#B9A5E3'],
  ].map(([title, pts, color]) =>
    `<section class="card"><span class="eyebrow">${esc(title)}</span>
    ${runSeries(pts,title,color)}</section>`).join('');
  view.innerHTML = `<header class="dtop"><a class="back" href="#/entrenos"
      aria-label="Volver a Entrenos">${svg('back')}</a>
      <h1>${esc(d.title)}<small>${esc(d.sport)} · ${esc(shortDate(d.date))}</small></h1>
      ${tagChip('MED', d.source === 'whoop' ? 'WHOOP' : 'COROS vía Tredict')}</header>
    <section class="card">
      <div class="stats" style="grid-template-columns:repeat(3,1fr)">
        <div><small>Distancia</small><b>${d.distance_m === null ? '—' :
          esc((d.distance_m/1000).toFixed(2)) + ' km'}</b></div>
        <div><small>Duración</small><b>${esc(runTime(d.duration_s))}</b></div>
        <div><small>Ritmo</small><b>${esc(runPace(d.pace_s_km))}</b></div>
        <div><small>FC media</small><b>${d.avg_hr === null ? '—' : esc(d.avg_hr.toFixed(0))}</b></div>
        <div><small>FC máx.</small><b>${d.max_hr === null ? '—' : esc(d.max_hr.toFixed(0))}</b></div>
        <div><small>Potencia</small><b>${d.avg_power === null ? '—' : esc(d.avg_power.toFixed(0)) + ' W'}</b></div>
        ${d.source === 'whoop' && d.score_strain !== null && d.score_strain !== undefined
          ? `<div><small>Strain WHOOP</small><b>${esc(Number(d.score_strain).toFixed(1))}</b></div>`
          : ''}
      </div>
      <p class="muted">${esc(d.attribution)}
        ${d.pace_calculated ? ' · Ritmo calculado desde tiempo y distancia' : ''}
      </p>
      ${d.source === 'whoop'
        ? '<span class="eyebrow" style="color:#A6BDA3">Datos de entrenamiento · WHOOP</span>'
        : `<a href="https://www.tredict.com/app/training/activity/${encodeURIComponent(d.id)}"
            target="_blank" rel="noopener noreferrer" style="color:var(--sig);font-size:13px">
            Abrir actividad original en Tredict ↗</a>`}</section>` + renderTrainingIntelligence(d.analysis) + renderTrainingContext(d.night_context) +
    renderHrZones(d.hr_zones) + sensors +
    `<section class="card"><h3>Vueltas y segmentos</h3>
      ${laps ? '<div style="overflow-x:auto"><table><thead><tr><th>#</th><th>Dist.</th><th>Ritmo</th><th>FC</th><th>W</th></tr></thead><tbody>'+
        laps+'</tbody></table></div>' : '<p class="muted">El sensor no proporcionó vueltas.</p>'}
      <p class="muted" style="margin:12px 0 0">${esc(d.method)}</p>
    </section>`;
}

// ------------------------------------------------------------------- router
const TABS = [['inicio', 'Inicio', 'home'], ['entrenos', 'Entrenos', 'run'], ['fisiologia', 'Fisiología', 'pulse'], ['progreso', 'Progreso', 'chart'], ['lab', 'Lab', 'flask']];
function setTabs(active) {
  tabsEl.innerHTML = TABS.map(([k, l, i]) => `<a href="#/${k}"${k === active ? ' aria-current="page"' : ''}>${svg(i)}<span>${l}</span></a>`).join('');
}
function setDays(n) {
  const [name] = currentHash().path.split('/');
  if (name === 'senal' || name === 'fisiologia') {
    location.hash = `#/${currentHash().path}?d=${n}`;
  } else {
    ROUTE_STATE.progDays = n;
    if (ROUTE_STATE.data) { renderProgreso(ROUTE_STATE.data); }
  }
}
function currentHash() {
  const h = location.hash.replace(/^#\/?/, '') || 'inicio';
  const [path, qs] = h.split('?');
  return {path, params: new URLSearchParams(qs || '')};
}
let lastPath = null;
async function route(refresh = false) {
  const {path, params} = currentHash();
  const parts = path.split('/');
  const tab = parts[0] === 'senal' ? 'inicio' : parts[0] === 'entreno' ? 'entrenos' : (['inicio', 'entrenos', 'progreso', 'fisiologia', 'lab'].includes(parts[0]) ? parts[0] : 'inicio');
  setTabs(tab);
  let url, fn;
  if (parts[0] === 'senal' && parts[1]) {
    const days = [7, 28, 90, 365].includes(+params.get('d')) ? +params.get('d') : 28;
    url = `/api/senal/${encodeURIComponent(parts[1])}?days=${days}`;
    fn = renderSenal;
  } else if (parts[0] === 'entreno' && parts[1]) {
    url = `/api/entreno/${encodeURIComponent(parts[1])}`; fn = renderEntreno;
  } else if (tab === 'entrenos') {
    const category = params.get('tipo') === 'otros' ? 'other' : 'running';
    url = `/api/entrenos?category=${category}`; fn = renderEntrenos;
  }
  else if (tab === 'progreso') { url = '/api/progreso'; fn = renderProgreso; }
  else if (tab === 'fisiologia') {
    const days = [28, 90, 365].includes(+params.get('d')) ? +params.get('d') : 90;
    url = `/api/fisiologia?days=${days}`; fn = renderFisiologia;
  }
  else if (tab === 'lab') { url = '/api/lab'; fn = renderLab; }
  else { url = '/api/home'; fn = renderInicio; }
  const btn = document.querySelector('[data-sync]');
  if (btn) btn.classList.add('spin');
  try {
    const r = await fetch(url, {cache: 'no-store'});
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await r.json();
    const y = window.scrollY;
    fn(data);
    view.classList.remove('view-in'); void view.offsetWidth; view.classList.add('view-in');
    window.scrollTo(0, refresh || lastPath === location.hash ? y : 0);
  } catch (err) {
    view.innerHTML = `<div class="errbox" style="margin-top:24px"><b>Sin conexión con ARES.</b><br>No se han podido cargar los datos (${esc(err.message)}). Comprueba que <span class="mono">ares app</span> sigue en marcha.</div>`;
  }
  lastPath = location.hash;
}
window.addEventListener('hashchange', () => route());
// La sincronización real pertenece al planificador de ares serve.
// Refrescar la vista local cada 5 minutos solo si está visible y el
// servidor declaró explícitamente que sincroniza en segundo plano.
window.setInterval(() => {
  if (ROUTE_STATE.syncMode === 'automatic' && document.visibilityState === 'visible') {
    route(true);
  }
}, 5 * 60 * 1000);
route();
