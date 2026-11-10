// Interfaz de NovaRent: HTML + JavaScript puro. Se sirve desde la misma API (/ui), sin CORS.
const $ = (s, r = document) => r.querySelector(s);
const money = n => '$' + Number(n).toLocaleString('es-MX', { minimumFractionDigits: 2 });
const csv = s => (s || '').split(',').map(x => x.trim()).filter(Boolean);
const iso = v => v && v.length === 16 ? v + ':00' : v;   // datetime-local -> ISO

function toast(msg, ok = true) {
  const t = $('#toast'); t.textContent = msg; t.style.background = ok ? 'var(--ok)' : 'var(--bad)';
  t.style.display = 'block'; clearTimeout(toast.h); toast.h = setTimeout(() => t.style.display = 'none', 4500);
}

// Llamada genérica a la API: muestra código HTTP y JSON en el panel inferior.
async function api(method, url, body) {
  let res, data;
  try {
    res = await fetch(url, { method, headers: body ? { 'Content-Type': 'application/json' } : {}, body: body ? JSON.stringify(body) : undefined });
    data = await res.json().catch(() => ({}));
  } catch (e) { toast('No se pudo conectar con la API', false); throw e; }
  $('#log-pre').textContent = `${method} ${url} → ${res.status}\n` + JSON.stringify(data, null, 2);
  if (!res.ok) {
    const d = data.detail;
    const msg = typeof d === 'string' ? d : Array.isArray(d) ? d.map(x => x.loc.slice(1).join('.') + ': ' + x.msg).join(' | ') : 'Error';
    const hint = res.status === 409 ? 'Estado inválido (409): ' : res.status === 422 ? 'Regla de negocio (422): ' : res.status === 404 ? 'No encontrado (404): ' : '';
    toast(hint + msg, false); throw new Error(msg);
  }
  return data;
}
const run = (fn) => async (e) => { if (e && e.preventDefault) e.preventDefault(); try { await fn(e); } catch (_) {} };

// ---------- Navegación ----------
$('#nav').onclick = e => {
  const t = e.target.dataset.tab; if (!t) return;
  document.querySelectorAll('nav button').forEach(b => b.classList.toggle('active', b === e.target));
  document.querySelectorAll('.tab').forEach(s => s.classList.toggle('active', s.id === t));
  if (t === 'flota') cargarFlota();
  if (t === 'reservacion') cargarReservacion().catch(() => {});
};
$('#log-x').onclick = () => $('#log-pre').textContent = '';

// ---------- Flota ----------
async function cargarFlota() {
  const cat = $('#f-cat').value;
  const vs = await api('GET', '/vehiculos' + (cat ? '?categoria=' + cat : ''));
  const cnt = {}; vs.forEach(v => cnt[v.estatus] = (cnt[v.estatus] || 0) + 1);
  $('#f-count').innerHTML = Object.entries(cnt).map(([k, n]) => `<span class="tag ${k}">${k.replace('_', ' ')}: ${n}</span>`).join('');
  $('#f-table tbody').innerHTML = vs.map(v => `<tr>
    <td>${v.vehiculo_id}</td><td>${v.placas}</td><td>${v.categoria}</td>
    <td><span class="tag ${v.estatus}">${v.estatus.replace('_', ' ')}</span></td>
    <td>${acciones(v)}</td></tr>`).join('');
}
function acciones(v) {
  if (v.estatus === 'EN_REVISION') return `<button class="sm" data-a="iniciar" data-id="${v.vehiculo_id}">Iniciar limpieza</button>`;
  if (v.estatus === 'LIMPIEZA') return `<button class="sm" data-a="terminado" data-id="${v.vehiculo_id}">Terminado</button> <button class="sm sec" data-a="mant" data-id="${v.vehiculo_id}">Mant. mayor</button>`;
  return '<span class="hint">—</span>';
}
$('#f-table').onclick = run(async e => {
  const b = e.target.closest('button[data-a]'); if (!b) return;
  const id = b.dataset.id, a = b.dataset.a;
  if (a === 'iniciar') await api('POST', `/vehiculos/${id}/limpieza/iniciar`);
  if (a === 'terminado') await api('POST', `/vehiculos/${id}/limpieza/terminado`);
  if (a === 'mant') {
    const motivo = prompt('Motivo del mantenimiento mayor:'); if (!motivo) return;
    const monto = parseFloat(prompt('Monto del cargo retroactivo (MXN):')); if (!(monto > 0)) return;
    await api('POST', `/vehiculos/${id}/mantenimiento-mayor`, { motivo, monto_mxn: monto });
  }
  toast('Listo'); cargarFlota();
});
$('#f-reload').onclick = run(cargarFlota); $('#f-cat').onchange = run(cargarFlota);

// ---------- Reservación ----------
const rid = () => $('#r-id').value;
const ESTADO_MSG = {
  CONFIRMADA: '',
  ENTREGADA: 'Esta reservación ya fue ENTREGADA: los pasos 1, 2 y 3 ya no aplican. Elige otra reservación o ve a Contrato.',
  DOCUMENTACION_INVALIDA: 'La documentación fue inválida: la reservación se cerró con retención. Elige otra reservación.',
  CANCELADA: 'Esta reservación fue CANCELADA. Elige otra reservación.'
};
// Habilita cada paso solo cuando el estado de la reservación lo permite (evita errores 409).
function aplicarEstado(r) {
  const conf = r.estatus === 'CONFIRMADA';
  const set = (el, on) => el.querySelectorAll('input,select,button').forEach(x => x.disabled = !on);
  set($('#r-doc'), conf);
  set($('#r-comp-card'), conf);
  set($('#r-ent'), conf && r.documentacion_verificada);
  $('#r-ent-hint').classList.toggle('hidden', !(conf && !r.documentacion_verificada));
  const aviso = $('#r-aviso'), msg = ESTADO_MSG[r.estatus] ?? '';
  aviso.textContent = msg; aviso.classList.toggle('hidden', !msg);
}
async function cargarReservacion() {
  const r = await api('GET', `/reservaciones/${rid()}`);
  const box = $('#r-info'); box.classList.remove('hidden');
  box.innerHTML = `<div class="kv"><span>ID</span><b>${r.reservacion_id}</b><span>Categoría reservada</span><b>${r.categoria}</b>
    <span>Categoría de entrega</span><b>${r.categoria_entrega}</b><span>Estatus</span><b>${r.estatus}</b>
    <span>Tarifa diaria</span><b>${money(r.tarifa_diaria_mxn)}</b><span>Retención</span><b>${money(r.retencion_mxn)}</b></div>`;
  aplicarEstado(r);
}
$('#r-load').onclick = run(cargarReservacion);
$('#r-id').onchange = run(cargarReservacion);

$('#r-doc').onsubmit = run(async e => {
  const f = Object.fromEntries(new FormData(e.target));
  const r = await api('POST', `/reservaciones/${rid()}/validar-documentacion`, f);
  toast(r.documentacion_valida ? 'Documentación válida ✔' : `Documentación inválida. Retención ${money(r.retencion_mxn)}`, r.documentacion_valida);
  cargarReservacion();
});
$('#r-oferta').onclick = run(async () => {
  const r = await api('GET', `/reservaciones/${rid()}/oferta-compensacion`);
  const o = r.oferta;
  toast(o ? `Oferta: ${o.tipo} a ${o.categoria} (${money(o.tarifa_diaria_mxn)}/día, ${o.descuento_adicional_pct}% desc.)` : 'No hay oferta: hay autos de la categoría reservada o ninguna alternativa.');
});
$('#r-comp').onclick = run(async () => {
  const r = await api('POST', `/reservaciones/${rid()}/compensacion`, { acepta_upgrade: $('#c-up').checked, acepta_inferior: $('#c-down').checked });
  toast(`Resultado: ${r.resultado} → ${r.categoria_entrega}`); cargarReservacion();
});
const inspeccion = f => ({ esquema_completado: f.esquema === 'on', fotos: csv(f.fotos), kilometraje: +f.kilometraje, combustible: f.combustible, danos: csv(f.danos) });
$('#r-ent').onsubmit = run(async e => {
  const f = Object.fromEntries(new FormData(e.target));
  const r = await api('POST', `/reservaciones/${rid()}/entrega`, { ultimos_4: f.ultimos_4, titular: f.titular, inspeccion_salida: inspeccion(f) });
  guardarContrato(r.contrato_id); $('#k-id').value = r.contrato_id; toast('Entregado. Contrato ' + r.contrato_id); cargarReservacion();
});

// ---------- Contrato ----------
// La API no lista contratos: se recuerdan en el navegador los que se generan al entregar.
const LS = 'novarent.contratos';
const leerContratos = () => { try { return JSON.parse(localStorage.getItem(LS)) || []; } catch { return []; } };
function pintarContratos(sel) {
  const ids = leerContratos(), cur = sel || $('#k-id').value;
  $('#k-id').innerHTML = '<option value="">Selecciona un contrato</option>' + ids.map(i => `<option>${i}</option>`).join('');
  $('#k-id').value = ids.includes(cur) ? cur : '';
}
function guardarContrato(id) {
  try { const l = leerContratos(); if (!l.includes(id)) localStorage.setItem(LS, JSON.stringify([...l, id])); } catch {}
  pintarContratos(id);
}
const kid = () => $('#k-id').value.trim();
async function verCargos() {
  if (!kid()) { toast('Selecciona un contrato', false); return; }
  const r = await api('GET', `/contratos/${kid()}/cargos`);
  const box = $('#k-resumen'); box.classList.remove('hidden');
  box.innerHTML = `<h3>Cargos de ${r.contrato_id}</h3>` + (r.cargos.length ? `<table><thead><tr><th>#</th><th>Tipo</th><th>Monto</th><th>Detalle</th><th></th></tr></thead><tbody>` +
    r.cargos.map(c => `<tr><td>${c.indice}</td><td>${c.tipo}</td><td>${money(c.monto_mxn)}</td><td>${c.descripcion}</td><td>${c.cancelado ? '<span class="tag RENTADO">cancelado</span>' : ''}</td></tr>`).join('') +
    `</tbody></table>` : '<p class="hint">Sin cargos.</p>') + `<div class="big">Total: ${money(r.total_mxn)}</div>`;
}
$('#k-cargos').onclick = run(verCargos);
$('#k-dev').onsubmit = run(async e => {
  const f = Object.fromEntries(new FormData(e.target));
  await api('POST', `/contratos/${kid()}/devolucion`, { hora_devolucion: iso(f.hora), inspeccion_devolucion: inspeccion(f) });
  toast('Devolución registrada'); verCargos();
});
$('#k-ext').onsubmit = run(async e => {
  const f = Object.fromEntries(new FormData(e.target));
  const r = await api('POST', `/contratos/${kid()}/extension`, { nuevo_fin: iso(f.nuevo_fin), vehiculo_reservado_por_otro: f.reservado === 'on' });
  toast(`Extendida. Cobro por adelantado: ${money(r.monto_mxn)}`);
});
$('#k-dan').onsubmit = run(async e => {
  const f = Object.fromEntries(new FormData(e.target));
  await api('POST', `/contratos/${kid()}/cargos/danos`, { monto_mxn: +f.monto, descripcion: f.descripcion });
  toast('Cargo por daños registrado'); verCargos();
});
$('#k-can').onsubmit = run(async e => {
  const f = Object.fromEntries(new FormData(e.target));
  await api('POST', `/contratos/${kid()}/cargos/${f.indice}/cancelacion`, { rol: f.rol, pin: f.pin, motivo: f.motivo });
  toast('Cargo cancelado'); verCargos();
});

// ---------- Reportes ----------
$('#rp-util').onclick = run(async () => {
  const r = await api('GET', '/reportes/tasa-de-utilizacion');
  const pct = x => (x * 100).toFixed(1) + '%';
  const rows = (r.por_categoria || []).map(c => `<div>${c.categoria}: ${c.rentados}/${c.flota}<div class="bar-bg"><div class="bar-fg" style="width:${c.flota ? 100 * c.rentados / c.flota : 0}%"></div></div></div>`).join('');
  $('#rp-util-out').innerHTML = `<pre>${JSON.stringify(r, null, 2)}</pre>` + rows;
});
$('#rp-ing').onclick = run(async () => {
  const d = $('#rp-desde').value;
  const r = await api('GET', '/reportes/ingresos-por-cargos' + (d ? '?desde=' + d : ''));
  $('#rp-ing-out').innerHTML = `<pre>${JSON.stringify(r, null, 2)}</pre>`;
});

// ---------- Inicio ----------
(async () => {
  try { await api('GET', '/health'); $('#health').textContent = 'API en línea'; $('#health').className = 'pill ok'; }
  catch { $('#health').textContent = 'API sin conexión'; $('#health').className = 'pill bad'; }
  const now = new Date(); now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
  $('#k-dev [name=hora]').value = now.toISOString().slice(0, 16);
  pintarContratos();
  cargarFlota().catch(() => {});
})();
