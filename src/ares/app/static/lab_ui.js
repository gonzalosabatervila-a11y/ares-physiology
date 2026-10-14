/* ARES LAB / one-tap event capture, mobile-first; no third-party requests.
   Loaded before app.js; resolves app shell helpers only when invoked. */
'use strict';

const LAB_NAMES = {coffee:'Café', dinner_end:'Cena terminada', bedtime:'Me acuesto'};
const LAB_SYMBOL = {coffee:'☕', dinner_end:'◒', bedtime:'☾'};
let labPending = null;
let labBusy = false;
let labMessage = '';
let labToastTimer;
function labToast(message, kind = 'success') {
  const toast = document.getElementById('ares-toast');
  if (!toast) return;
  window.clearTimeout(labToastTimer);
  toast.textContent = message;
  toast.dataset.kind = kind;
  toast.hidden = false;
  labToastTimer = window.setTimeout(() => { toast.hidden = true; }, 4400);
}


function labLocalInput(iso) {
  const d = new Date(iso);
  const p = n => String(n).padStart(2,'0');
  return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}
function labHumanTime(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('es-ES', {weekday:'short',day:'2-digit',
    month:'short',hour:'2-digit',minute:'2-digit',hour12:false});
}
function labDateOnly(iso) {
  return new Date(iso).toLocaleDateString('es-ES', {weekday:'short',day:'numeric',month:'short'});
}
function labEventText(e) {
  return e.event_type === 'coffee'
    ? `Café · ${esc(e.caffeine_mg)} mg
       <small>${e.amount_basis === 'estimated' ? 'estimado' :
       e.amount_basis === 'label' ? 'etiqueta' : 'medido'}</small>`
    : esc(LAB_NAMES[e.event_type] || e.event_type);
}
function labSignal(v, unit) {
  return v == null ? '—' : `${Number(v).toLocaleString('es-ES',{maximumFractionDigits:1})}${unit}`;
}
function renderAresLab(d) {
  ROUTE_STATE.lab = d;
  const enabled = Boolean(d.write_enabled);
  const mode = currentHash().params.get('ver') === 'analisis' ? 'analysis' : 'diary';
  view.classList.toggle('lab-view-analysis', mode === 'analysis');
  view.classList.toggle('lab-view-diary', mode === 'diary');
  const bands = d.dinner_sleep.bands || [];
  const groups = bands.map(b => {
    const enough = b.status === 'exploratory';
    return `<div class="lab-cohort">
      <div class="lab-cohort-top"><b>${esc(b.label)}</b>
        <span>${b.n} noches</span></div>
      <div class="lab-cohort-values">${enough ?
        `<span>VFC ${labSignal(b.hrv_mean_ms,' ms')}</span>
         <span>Reposo ${labSignal(b.rhr_mean,' lpm')}</span>
         <span>Sueño ${labSignal(b.sleep_mean_min,' min')}</span>` :
        `<span>Necesitamos al menos 5 noches en este grupo</span>`}</div>
    </div>`;
  }).join('');
  const recent = (d.events || []).slice(0,30).map(e => `<div class="lab-entry">
    <div class="lab-entry-icon">${LAB_SYMBOL[e.event_type] || '•'}</div>
    <div class="lab-entry-main">
      <b>${labEventText(e)}</b>
      <small>${esc(labHumanTime(e.occurred_at))}${e.note ? ' · '+esc(e.note) : ''}</small>
    </div>
    ${enabled ? `<button class="lab-edit" type="button" data-lab-edit="${esc(e.id)}"
      aria-label="Corregir ${esc(LAB_NAMES[e.event_type])}">Editar</button>`: ''}
  </div>`).join('');
  const timeline = (d.timeline || []).slice(0,35).map(e => {
    let detail = '';
    if (e.type==='coffee') detail = `${e.event.caffeine_mg} mg estimados/registrados`;
    if (e.type==='sleep') detail = `WHOOP · ${e.values.sleep_min==null ? '—' :
      Math.round(e.values.sleep_min)+' min'} de sueño · VFC
      ${labSignal(e.values.hrv_ms,' ms')} · reposo ${labSignal(e.values.rhr,' lpm')}`;
    return `<div class="lab-timeline-item">
      <div class="lab-timeline-line"></div>
      <div class="lab-timeline-dot ${e.source==='WHOOP'?'whoop':''}"></div>
      <div class="lab-timeline-text">
        <span>${esc(labHumanTime(e.at))}</span>
        <b>${esc(e.label)}</b>
        ${detail ? `<small>${esc(detail)}</small>`:''}
      </div>
    </div>`;
  }).join('');
  view.innerHTML = pageTop(ROUTE_STATE.sources) +
    `<div class="lab-head">
      <div class="eyebrow">ARES LAB · OBSERVATORIO PERSONAL</div>
      <h2>La ciencia de tus días</h2>
      <p>Registra una acción. ARES se encargará de relacionarla con tu fisiología,
        sin inventar explicaciones.</p>
    </div>
    <nav class="lab-section-tabs" aria-label="Vistas del laboratorio">
      <a href="#/laboratorio" ${mode === 'diary' ? 'aria-current="page"' : ''}>
        <span>01</span> Diario</a>
      <a href="#/laboratorio?ver=analisis" ${mode === 'analysis' ? 'aria-current="page"' : ''}>
        <span>02</span> Análisis</a>
    </nav>
    ${labMessage ? `<div class="lab-message" role="status">${esc(labMessage)}</div>`:''}
    <section class="lab-capture lab-diary-panel" aria-label="Registro de acontecimientos en un toque">
      <div class="lab-section-head"><span class="eyebrow">CAPTURA INSTANTÁNEA</span>
        <span class="lab-live">Europe/Madrid · hora del dispositivo</span></div>
      <div class="lab-quick">
        <button type="button" class="lab-action" data-lab-quick="coffee"
          ${enabled?'':'disabled'}><span>☕</span><b>Café</b>
          <small>+100 mg estimados</small></button>
        <button type="button" class="lab-action" data-lab-quick="dinner_end"
          ${enabled?'':'disabled'}><span>◒</span><b>Terminé de cenar</b>
          <small>Ahora</small></button>
        <button type="button" class="lab-action" data-lab-quick="bedtime"
          ${enabled?'':'disabled'}><span>☾</span><b>Me acuesto</b>
          <small>Ahora</small></button>
      </div>
      ${enabled ? `<div class="lab-custom-actions">
        <button type="button" data-lab-manual>Registrar otra hora / dosis ↗</button>
      </div>` : `<div class="lab-readonly">Registro deshabilitado en <code>ares app</code>.
        Para registrar acontecimientos, utiliza <code>uv run ares serve</code>.</div>`}
      <p class="lab-footnote">El café predeterminado es una estimación de 100 mg.
      Puedes corregir cantidad y hora. No se envía ningún dato a servicios de IA.</p>
    </section>
    <section class="card lab-now lab-diary-panel">
      <span class="eyebrow">TU DÍA · REGISTROS MANUALES</span>
      <div class="lab-now-stats">
        <div><small>Cafeína registrada hoy</small>
          <b>${esc(d.daily?.caffeine_logged_mg_today ?? 0)} <em>mg</em></b>
          <span>${esc(d.daily?.coffee_entries_today ?? 0)} café(s) anotados</span></div>
        <div><small>Última cena → acostarse</small>
          <b>${d.daily?.last_dinner_bedtime_gap_min == null ? '—' :
            `${Math.floor(d.daily.last_dinner_bedtime_gap_min/60)}:${String(d.daily.last_dinner_bedtime_gap_min%60).padStart(2,'0')} <em>h</em>`}</b>
          <span>${esc(d.daily?.manual_pairs_30d ?? 0)} intervalos emparejados en 30 días</span></div>
      </div>
      <p class="lab-footnote">Son cantidades y horarios anotados, no necesariamente
        toda la cafeína consumida. Cena→cama utiliza tu pulsación «Me acuesto»;
        el siguiente análisis utiliza el inicio de sueño estimado por WHOOP.</p>
    </section>
    <section class="card lab-insight lab-analysis-panel">
      <div class="eyebrow">CENA → SUEÑO WHOOP · OBSERVACIÓN</div>
      <div class="lab-stat-line">
        <div><b>${d.dinner_sleep.paired_nights}</b>
          <small>Noches con cena y sueño emparejados</small></div>
        <div><b>${d.dinner_sleep.total_valid_nights}</b>
          <small>Noches WHOOP puntuables</small></div>
      </div>
      <h3>¿Cuánto tiempo pasa entre la cena y dormir?</h3>
      <div class="lab-cohorts">${groups}</div>
      <p class="lab-evidence">${d.dinner_sleep.ready_for_comparison
        ? 'Comparación descriptiva disponible. No se ajusta por otros factores.'
        : 'Estamos construyendo tu muestra. Aún no hay evidencia suficiente para comparar grupos.'}</p>
      <details class="lab-method"><summary>Cómo calcula ARES este análisis</summary>
        <p>${esc(d.dinner_sleep.method)}</p>
      </details>
    </section>
    <section class="card lab-insight lab-analysis-panel" aria-label="Cafeína y sueño WHOOP">
      <div class="eyebrow">CAFÉ → SUEÑO WHOOP · OBSERVACIÓN</div>
      <div class="lab-stat-line">
        <div><b>${esc(d.caffeine_sleep?.paired_nights ?? 0)}</b>
          <small>Noches con café registrado antes del sueño</small></div>
        <div><b>${esc(d.caffeine_sleep?.total_valid_nights ?? 0)}</b>
          <small>Noches WHOOP puntuables</small></div>
      </div>
      <h3>¿Cuántas horas pasan desde tu último café?</h3>
      <div class="lab-cohorts">
        ${(d.caffeine_sleep?.bands || []).map(b => {
          const fmt = (v,unit) => v === null || v === undefined ?
             '—' : esc(Number(v).toLocaleString('es-ES',{maximumFractionDigits:1}))+' '+unit;
          const text = b.status !== 'exploratory'
            ? '<span>Se requieren al menos 5 noches con esta condición</span>'
            : `<span>VFC ${fmt(b.hrv.median,'ms')}
                ${b.hrv.p25 === null ? '' : `<small> P25–P75 ${fmt(b.hrv.p25,'')}–${fmt(b.hrv.p75,'')}</small>`}</span>
               <span>FC reposo ${fmt(b.rhr.median,'lpm')}</span>
               <span>Sueño ${fmt(b.sleep.median,'min')}</span>`;
          return `<div class="lab-cohort">
             <div class="lab-cohort-top"><b>${esc(b.label)}</b><span>${b.n} noches</span></div>
             <div class="lab-cohort-values">${text}</div>
          </div>`;
        }).join('')}
      </div>
      <p class="lab-evidence">${d.caffeine_sleep?.ready_for_comparison
        ? 'Comparación exploratoria disponible; pendientes ajustes por carga y horarios.'
        : 'Aún falta diversidad de noches registradas para comparar condiciones.'}</p>
      <details class="lab-method"><summary>Qué significa esta comparación</summary>
        <p>${esc(d.caffeine_sleep?.method || '')}</p>
      </details>
    </section>
    <section class="card lab-history lab-diary-panel">
      <div class="lab-section-head"><div><span class="eyebrow">REGISTRO PERSONAL</span>
        <h3>Tus acontecimientos</h3></div>
        <span class="pill">${d.count_30d} recientes</span></div>
      ${recent || '<p class="muted">Todavía no has registrado acontecimientos. Empieza con el siguiente café o cena.</p>'}
    </section>
    <section class="card lab-history lab-diary-panel">
      <div class="lab-section-head"><div><span class="eyebrow">CRONOLOGÍA</span>
        <h3>Tu línea temporal</h3></div><span class="pill">7 días</span></div>
      <p class="muted">Acontecimientos manuales y comienzos de sueño WHOOP.
        No representa curvas de pulso segundo a segundo.</p>
      <div class="lab-timeline">${timeline || '<p class="muted">Aún no hay registros temporales.</p>'}</div>
      <a href="#/fisiologia" class="lab-link">Ver fisiología longitudinal ↗</a>
    </section>`;
}
async function labApi(method, path, payload) {
  const r = await fetch(path, {
    method, cache:'no-store', credentials:'same-origin',
    headers:{'Content-Type':'application/json','X-ARES-LAB':'1'},
    body:payload ? JSON.stringify(payload) : undefined,
  });
  if (!r.ok) {
    let detail = '';
    try {const response=await r.json();detail=typeof response.detail==='string'?
      response.detail:JSON.stringify(response.detail)} catch(_){}
    throw Error(detail || `HTTP ${r.status}`);
  }
  return r.json();
}
async function labQuick(kind) {
  if (labBusy) return;
  // Stable idempotency key if the network failed and the user retries.
  if (!labPending || labPending.event_type !== kind) {
    labPending = {event_type:kind,occurred_at:new Date().toISOString(),
      client_event_key:crypto.randomUUID()};
    if (kind==='coffee') {
      labPending.caffeine_mg=100;
      labPending.amount_basis='estimated';
    }
  }
  labBusy=true;
  const buttons=document.querySelectorAll('[data-lab-quick]');
  buttons.forEach(el=>el.disabled=true);
  labMessage='Guardando en ARES…';
  try {
    await labApi('POST','/api/lab/events',labPending);
    labPending=null;labMessage='Registrado correctamente. Puedes corregirlo en el historial.';
    labToast('✓ Registrado en ARES. Puedes corregirlo en LAB.');
    await route(true);
  } catch(e) {
    labMessage=`No se ha confirmado el guardado: ${e.message}. Reintenta cuando haya conexión.`;
    labToast(labMessage, 'error');
    const notice=document.querySelector('.lab-message');
    if(notice) {notice.textContent=labMessage;}
  } finally {
    labBusy=false;
    document.querySelectorAll('[data-lab-quick]').forEach(el=>el.disabled=false);
  }
}
function labEditSheet(event, isNew=false) {
  if(!event) return;
  const type=event.event_type || 'coffee';
  const current=isNew ? new Date().toISOString() : event.occurred_at;
  const mg=event.caffeine_mg ?? 100;
  const notes=event.note || '';
  const options=Object.entries(LAB_NAMES).map(([key,label]) =>
    `<option value="${key}" ${key===type?'selected':''}>${label}</option>`).join('');
  openSheet(`<h3 id="sheet-title">${isNew?'Nuevo acontecimiento':'Corregir acontecimiento'}</h3>
    <p class="muted">Las horas se interpretan en la zona del dispositivo. Puedes corregir
      el instante registrado; ARES conserva la marca temporal de la edición.</p>
    <form id="lab-event-form" data-event-id="${esc(event.id||'')}">
      ${isNew ? `<label for="lab-kind">Tipo</label><select id="lab-kind"
        name="event_type" class="lab-field">${options}</select>`:
        `<p><b>${esc(LAB_NAMES[type])}</b></p>`}
      <label for="lab-when">Fecha y hora</label>
      <input id="lab-when" name="occurred_at" class="lab-field" type="datetime-local"
        value="${esc(labLocalInput(current))}" required>
      <div id="lab-coffee-controls" ${type==='coffee'?'':'hidden'}>
        <label for="lab-mg">Cafeína (mg)</label>
        <input id="lab-mg" name="caffeine_mg" class="lab-field" type="number"
          inputmode="decimal" min="0" max="500" step="1" value="${esc(mg)}">
        <label for="lab-basis">Procedencia de la dosis</label>
        <select id="lab-basis" name="amount_basis" class="lab-field">
          <option value="estimated" ${event.amount_basis!=='label'&&event.amount_basis!=='measured'?'selected':''}>Estimación</option>
          <option value="label" ${event.amount_basis==='label'?'selected':''}>Etiqueta del producto</option>
          <option value="measured" ${event.amount_basis==='measured'?'selected':''}>Medición registrada</option>
        </select>
      </div>
      <label for="lab-note">Nota opcional</label>
      <textarea id="lab-note" name="note" class="lab-field"
        rows="2" maxlength="280">${esc(notes)}</textarea>
      <button class="lab-primary" type="submit">Guardar acontecimiento</button>
    </form>
    ${!isNew ? `<button class="lab-delete" data-lab-delete="${esc(event.id)}"
      type="button">Anular este registro</button>`:''}
    <p id="lab-form-error" class="lab-error" role="status"></p>`);
}
async function labSaveForm(form) {
  if(labBusy) return;
  const fd=new FormData(form), origId=form.dataset.eventId;
  const raw=String(fd.get('occurred_at')||'');
  const when=new Date(raw);
  if(!raw||Number.isNaN(when.getTime())) {
    document.querySelector('#lab-form-error').textContent='Fecha u hora inválida';
    return;
  }
  const kind=origId ? ROUTE_STATE.lab.events.find(e=>e.id===origId)?.event_type :
    String(fd.get('event_type'));
  if(!kind) return;
  const note=String(fd.get('note')||'').trim();
  const data={occurred_at:when.toISOString(),note:note||null};
  if(kind==='coffee') {
    data.caffeine_mg=Number(fd.get('caffeine_mg'));
    data.amount_basis=String(fd.get('amount_basis'));
  }
  if(!origId) {
    data.event_type=kind;
    data.client_event_key=crypto.randomUUID();
  }
  labBusy=true;
  form.querySelector('[type=submit]').disabled=true;
  try {
    await labApi(origId?'PATCH':'POST',origId?
      `/api/lab/events/${encodeURIComponent(origId)}`:'/api/lab/events',data);
    closeSheet();labMessage='Registro guardado.';
    labToast('✓ Acontecimiento guardado.');
    await route(true);
  } catch(e) {
    document.querySelector('#lab-form-error').textContent=e.message;
    form.querySelector('[type=submit]').disabled=false;
  } finally {labBusy=false;}
}
document.addEventListener('click',(e)=>{
  const quick=e.target.closest('[data-lab-quick]');
  if(quick) {void labQuick(quick.dataset.labQuick);return;}
  const edit=e.target.closest('[data-lab-edit]');
  if(edit) {labEditSheet(ROUTE_STATE.lab?.events.find(x=>x.id===edit.dataset.labEdit));return;}
  if(e.target.closest('[data-lab-manual]')) {
    labEditSheet({event_type:'coffee'},true);return;
  }
  const del=e.target.closest('[data-lab-delete]');
  if(del) {
    if(!confirm('¿Anular este registro? Dejará de aparecer en los análisis.'))return;
    void (async()=>{
      try {
        await labApi('DELETE',`/api/lab/events/${encodeURIComponent(del.dataset.labDelete)}`);
        closeSheet();labMessage='Registro anulado.';
        labToast('Registro anulado. Ya no participa en los análisis.');
        await route(true);
      } catch(error){document.querySelector('#lab-form-error').textContent=error.message;}
    })();
  }
});
document.addEventListener('submit',(e)=>{
  if(e.target.id==='lab-event-form') {e.preventDefault();void labSaveForm(e.target);}
});
document.addEventListener('change',(e)=>{
  if(e.target.id==='lab-kind') {
    document.querySelector('#lab-coffee-controls').hidden=e.target.value!=='coffee';
  }
});
