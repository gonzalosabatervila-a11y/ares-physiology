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
const COLOR = {ok: '#45D4E5', warn: '#F0A33A', bad: '#E8573A', none: '#8C979B'};

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
<path d="M4.5 14.7A7.48 7.48 0 0 1 14.6 4.4" fill="none" stroke="#45D4E5" stroke-width="4.2" stroke-linecap="round"/>
<circle cx="14.6" cy="4.4" r="2.5" fill="#45D4E5"/></svg>`;
const GLYPH = {
  intervals: '<svg class="gl" viewBox="0 0 22 22"><rect x="3" y="11" width="4" height="8" rx="1.5" fill="#45D4E5"/><rect x="9" y="6" width="4" height="13" rx="1.5" fill="#45D4E5" opacity=".72"/><rect x="15" y="3" width="4" height="16" rx="1.5" fill="#45D4E5" opacity=".45"/></svg>',
  tredict: '<svg class="gl" viewBox="0 0 22 22"><path d="M11 3l9 16H2z" fill="none" stroke="#45D4E5" stroke-width="2" stroke-linejoin="round"/></svg>',
  polar: '<svg class="gl" viewBox="0 0 22 22"><circle cx="11" cy="11" r="7" fill="none" stroke="#8C979B" stroke-width="2.4" stroke-dasharray="3 3"/></svg>',
};
const SRC_NAME = {intervals: 'Intervals', tredict: 'Tredict', polar: 'Polar'};

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
function latestSyncText(sources) {
  const times = sources.map((s) => s.last_ok).filter(Boolean).map((v) => new Date(v)).filter((d) => !Number.isNaN(d.getTime()));
  if (!times.length) return 'Sin sincronizaciones todavía';
  const latest = new Date(Math.max(...times.map((d) => d.getTime())));
  return `Última sincronización · ${latest.toLocaleTimeString('es-ES', {hour: '2-digit', minute: '2-digit'})}`;
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
<text x="60" y="72" text-anchor="middle" font-family="Archivo,sans-serif" font-size="22" font-weight="700" fill="#EEF1F2">${valueSpans(d.key, d.value)}</text>
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
function spark(vals, color = '#45D4E5') {
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
<p>La <b style="color:#EEF1F2">aguja</b> marca tu valor más reciente y la <b style="color:#EEF1F2">franja resaltada</b> es tu rango habitual: la media de tus días disponibles más o menos media desviación típica.</p>
<p><b style="color:#EEF1F2">Sistema nervioso</b> usa la media de los últimos 7 días; <b style="color:#EEF1F2">Noche</b>, la última noche; <b style="color:#EEF1F2">Carga</b> solo describe la dirección de tu forma y no la juzga. El texto de debajo compara con tu propia referencia y aparece cuando hay datos suficientes.</p>
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
    ? '<p>Polar aún no ha sincronizado con este servicio. Cuando lo haga, aparecerá aquí con su hora.</p>'
    : s.error ? `<p style="color:#E8573A">${esc(s.error)}</p>` : '';
  openSheet(`<h3 id="sheet-title">${esc(SRC_NAME[name] || name)}</h3><div class="kv">${rows.map(([k, v]) => `<div class="r"><span>${esc(k)}</span><span>${esc(v)}</span></div>`).join('')}</div>${extra}`);
}
document.addEventListener('click', (e) => {
  if (e.target.closest('[data-close]')) return closeSheet();
  if (e.target.closest('[data-howto]')) return howtoSheet();
  const c = e.target.closest('[data-chip]');
  if (c) return sourceSheet(c.dataset.chip, ROUTE_STATE.sources || []);
  if (e.target.closest('[data-sync]')) return manualSync();
  const seg = e.target.closest('[data-days]');
  if (seg) return setDays(+seg.dataset.days);
});

async function manualSync() {
  let btn = document.querySelector('[data-sync]');
  if (!btn || btn.disabled) return;
  btn.disabled = true;
  btn.classList.add('spin');
  let msg = document.querySelector('.sync-msg');
  if (msg) msg.textContent = 'Actualizando…';
  try {
    const r = await fetch('/api/sync', {method: 'POST', cache: 'no-store'});
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    await route(true);
    msg = document.querySelector('.sync-msg');
    if (msg) msg.textContent = 'Actualizado ahora';
    window.setTimeout(() => {
      const current = document.querySelector('.sync-msg');
      if (current && current.textContent === 'Actualizado ahora') current.textContent = '';
    }, 2200);
  } catch (err) {
    msg = document.querySelector('.sync-msg');
    if (msg) msg.textContent = 'Error al actualizar';
  } finally {
    btn = document.querySelector('[data-sync]');
    if (btn) {
      btn.disabled = false;
      btn.classList.remove('spin');
    }
  }
}

// ------------------------------------------------------------------- vistas
const ROUTE_STATE = {sources: [], days: 28, progDays: 28, data: null};
function pageTop(sources) {
  const date = new Date().toLocaleDateString('es-ES', {weekday: 'long', day: 'numeric', month: 'long'});
  return `<header class="top"><div class="brand">${MARK}<div><h1>ARES</h1><div class="date">${esc(cap(date))}</div></div></div>
<div class="sync-wrap"><button class="sync" data-sync aria-label="Sincronizar ahora">${svg('sync')}<span class="dot ${syncDot(sources)}"></span></button><small class="sync-msg" aria-live="polite"></small></div></header>`;
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
  const list = ['intervals', 'tredict', 'polar'].filter((k) => by[k]).map((k) => by[k]);
  return `<div class="chips">${list.map((s) => {
    const st = chipState(s);
    return `<button class="chip" data-chip="${esc(s.source)}" aria-label="${esc(SRC_NAME[s.source] || s.source)}: ${esc(st.text)}. Ver detalle">${GLYPH[s.source] || ''}<span class="${st.cls}"><b>${esc(SRC_NAME[s.source] || s.source)}</b><small><i class="dot-s"></i>${esc(st.text)}</small></span></button>`;
  }).join('')}</div>`;
}
const HERO_ART = `<svg class="hero-art" viewBox="0 0 420 220" fill="none" aria-hidden="true">
<defs>
  <linearGradient id="mtn" x1="110" y1="20" x2="330" y2="205" gradientUnits="userSpaceOnUse"><stop stop-color="#8EA0A7" stop-opacity=".42"/><stop offset="1" stop-color="#182126" stop-opacity=".1"/></linearGradient>
  <linearGradient id="fade" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#45D4E5" stop-opacity=".22"/><stop offset="1" stop-color="#45D4E5" stop-opacity="0"/></linearGradient>
</defs>
<path d="M70 190L182 52l54 67 40-46 98 117H70Z" fill="url(#mtn)"/>
<path d="M124 190l87-112 29 37 35-40 91 115H124Z" fill="url(#fade)"/>
<path d="M70 190h304" stroke="rgba(255,255,255,.16)" stroke-width="1"/>
<g transform="translate(280 92)" stroke="#EEF1F2" stroke-width="6" stroke-linecap="round" stroke-linejoin="round">
  <circle cx="22" cy="10" r="8" fill="#EEF1F2" stroke="none"/>
  <path d="M18 24l-16 28m16-28 27 15m-27-15 17 31m10-16 21 3M18 55 2 82m33-27 25 21"/>
</g>
</svg>`;
const LEVEL_TXT = {sin_cambios: 'Mantener plan', vigilar: 'Vigilar', evitar_intensidad: 'Evitar intensidad', descanso: 'Descanso o revisar salud'};
function hero(e) {
  if (e.mode === 'sombra') {
    return `<section class="card hero" aria-label="Estado de hoy"><div class="row"><span class="eyebrow">Estado de hoy</span><span class="pill sig">Modo sombra</span></div>
<h2>Construyendo tu línea base</h2><p>Estamos recopilando tus datos para establecer tu referencia personal. Mientras tanto puedes consultar tus datos y tendencias.</p>${HERO_ART}</section>`;
  }
  return `<section class="card hero" aria-label="Estado de hoy"><div class="row"><span class="eyebrow">Estado de hoy</span><span class="pill sig">${esc(e.date)}</span></div>
<h2>${esc(LEVEL_TXT[e.level] || e.level)}</h2>${e.cause ? `<p>${esc(e.cause)}</p>` : ''}${HERO_ART}</section>`;
}
function baseline(e) {
  const pct = Math.round(100 * e.nights / e.target);
  return `<section class="card base" aria-label="Línea base"><div class="ic">${svg('db')}</div>
<div><div class="top2"><span class="eyebrow">Línea base</span><span class="mono" style="font-size:11px;color:var(--sig)">${pct} %</span></div><h3>${e.mode === 'sombra' ? 'Construyendo tu referencia' : 'Referencia disponible'}</h3></div>
<div class="full"><div class="bar" role="progressbar" aria-valuenow="${e.nights}" aria-valuemin="0" aria-valuemax="${e.target}" aria-label="Noches válidas"><i style="width:${pct}%"></i></div>
<div class="muted"><b style="color:var(--txt)">${e.nights} de ${e.target}</b> noches válidas. Empezarán a contar cuando ARES procese cada noche de la Loop (siguiente paso).</div></div></section>`;
}
function sigRow(s) {
  const [title, sub] = s.label.split(' · ');
  return `<a class="sig-row" href="#/senal/${s.key}?d=28"><div class="l1"><b>${esc(title)}</b><span>${esc(sub || '')}</span></div>
<div class="side">${tagChip(s.tag, s.origin)}${spark(s.spark)}</div>
<div class="val">${splitUnit(s.value)}</div><div class="note">${esc(s.note)}</div></a>`;
}
function renderInicio(d) {
  ROUTE_STATE.sources = d.sources;
  const steps = d.steps === null
    ? '<span class="muted">Sin pasos todavía.</span>'
    : `<div><div class="eyebrow">Pasos · ${esc(shortDate(d.steps_day || d.last_day))}</div><div class="big">${d.steps.toLocaleString('es-ES')}</div></div><span class="muted">${esc(d.steps_source || 'intervals.icu')}</span>`;
  view.innerHTML = pageTop(d.sources) + chips(d.sources) + `<div class="sync-summary">${esc(latestSyncText(d.sources))}</div>` + hero(d.estado) +
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
${lineChart([{pts: d.series, color: '#45D4E5'}], {band: d.range ? [d.range.lo, d.range.hi] : null, label: `${d.label}, últimos ${d.days} días`})}
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
${lineChart([{pts: cut(d.ctl), color: '#45D4E5'}, {pts: cut(d.atl), color: '#F0A33A', dash: '4 4'}], {label: 'Forma y fatiga'})}
<div class="muted" style="display:flex;gap:16px;margin-top:8px"><span><span class="dot-s ok" style="display:inline-block;margin-right:6px"></span>Forma (CTL)</span><span><span class="dot-s" style="display:inline-block;margin-right:6px;background:#F0A33A"></span>Fatiga (ATL)</span>${st.ramp !== null ? `<span style="margin-left:auto">Ritmo de subida ${sg(st.ramp)} / sem</span>` : ''}</div></section>
<details class="card"><summary>De dónde salen forma y fatiga${svg('chev', 'chev')}</summary>
<p>Son dos promedios de la carga diaria de entrenamiento que calcula intervals.icu (un modelo de tipo Banister/Coggan): la <b style="color:#EEF1F2">forma</b> mira semanas (por defecto 42 días) y la <b style="color:#EEF1F2">fatiga</b>, días (por defecto 7). Sube la forma si entrenas de forma sostenida; sube la fatiga si concentras carga en pocos días.</p>
<p><b style="color:#EEF1F2">Balance = forma − fatiga.</b> Negativo significa que la carga reciente supera a la habitual; positivo, que vienes de descansar.</p>
<p>La carga de cada sesión es una <b style="color:#EEF1F2">estimación de intervals.icu</b> (con FC, potencia o ritmo, según lo que traiga cada actividad), no una medida fisiológica. ARES la muestra tal cual y no la reinterpreta. Hoy: forma ${st.ctl.toFixed(0)}, fatiga ${st.atl.toFixed(0)}, balance ${sg(st.form)}.</p></details>` : '<section class="card"><p class="muted" style="margin:0">Sin datos de forma y fatiga todavía.</p></section>';
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
    return `<div class="r"><span class="dot-s ${st.cls === 'ok' ? 'ok' : ''}" style="${st.cls === 'warn' ? 'background:#F0A33A' : st.cls === 'bad' ? 'background:#E8573A' : ''}"></span><div><b>${esc(SRC_NAME[s.source] || s.source)}</b><small>${esc(s.endpoint)}${s.error ? ' · ' + esc(s.error) : ''}</small></div><span class="mono" style="font-size:11px;color:var(--mut)">${esc(st.text)}</span></div>`;
  }).join('');
  const raw = d.raw.length
    ? `<table><thead><tr><th>FUENTE</th><th>FILAS</th><th>DESDE</th><th>HASTA</th></tr></thead><tbody>${d.raw.map((r) => `<tr><td>${esc(r.source)}/${esc(r.endpoint)}</td><td>${r.rows}</td><td>${esc(shortDate(r.from))}</td><td>${esc(shortDate(r.to))}</td></tr>`).join('')}</tbody></table>`
    : '<p class="muted" style="margin:0">Capa bruta vacía.</p>';
  const runs = d.runs.length
    ? `<div class="list">${d.runs.map((r) => `<div class="r" style="grid-template-columns:1fr auto"><div><b>${esc(r.job)}</b><small>${esc(r.started.slice(0, 16).replace('T', ' '))} UTC</small></div><span class="pill ${r.status === 'ok' ? 'sig' : ''}">${esc(r.status)}</span></div>`).join('')}</div>`
    : '<p class="muted" style="margin:0">Sin ejecuciones registradas.</p>';
  view.innerHTML = pageTop(d.sources) + `<div class="h2"><h2 style="margin:0;font-size:26px;font-weight:700">Laboratorio</h2></div>
<section class="card"><div class="eyebrow" style="margin-bottom:8px">Validación</div><p class="muted" style="margin:0">Todavía no hay decisiones que validar: el modo sombra dura hasta las 21 noches válidas.</p></section>
<section class="card"><div class="row" style="display:flex;justify-content:space-between;align-items:center"><span class="eyebrow">Gate técnico nº 1 · PPI de la Loop</span><span class="pill">${esc(d.gate.level)}</span></div>
<p class="muted" style="margin:10px 0 0">${d.gate.n_h10} noches con la H10. ${esc(d.gate.criteria)}. Hasta superarlo, el respaldo es Nightly Recharge.</p></section>
<section class="card"><div class="eyebrow" style="margin-bottom:4px">Fuentes</div><div class="list">${src}</div></section>
<section class="card"><div class="eyebrow" style="margin-bottom:10px">Capa bruta</div>${raw}</section>
<section class="card"><div class="eyebrow" style="margin-bottom:4px">Últimas ejecuciones</div>${runs}</section>
<section class="card"><div class="eyebrow" style="margin-bottom:8px">Versiones</div><p class="muted mono" style="margin:0;font-size:12px">esquema v${esc(d.versions.schema)} · reglas ${esc(d.versions.rules)} · filtro ${esc(d.versions.filter)} · código ${esc(d.versions.code)}</p></section>
<section class="card"><div class="eyebrow" style="margin-bottom:8px">Leyenda</div>${LEGEND_KV}</section>`;
}

// ------------------------------------------------------------------- router
const TABS = [['inicio', 'Inicio', 'home'], ['progreso', 'Progreso', 'chart'], ['lab', 'Lab', 'flask']];
function setTabs(active) {
  tabsEl.innerHTML = TABS.map(([k, l, i]) => `<a href="#/${k}"${k === active ? ' aria-current="page"' : ''}>${svg(i)}<span>${l}</span></a>`).join('');
}
function setDays(n) {
  const [name] = currentHash().path.split('/');
  if (name === 'senal') {
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
  const tab = parts[0] === 'senal' ? 'inicio' : (['inicio', 'progreso', 'lab'].includes(parts[0]) ? parts[0] : 'inicio');
  setTabs(tab);
  let url, fn;
  if (parts[0] === 'senal' && parts[1]) {
    const days = [7, 28, 90, 365].includes(+params.get('d')) ? +params.get('d') : 28;
    url = `/api/senal/${encodeURIComponent(parts[1])}?days=${days}`;
    fn = renderSenal;
  } else if (tab === 'progreso') { url = '/api/progreso'; fn = renderProgreso; }
  else if (tab === 'lab') { url = '/api/lab'; fn = renderLab; }
  else { url = '/api/home'; fn = renderInicio; }
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
route();
window.setInterval(() => {
  if (!document.hidden) route(true);
}, 10 * 60 * 1000);
