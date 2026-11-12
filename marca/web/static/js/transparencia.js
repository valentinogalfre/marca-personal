/* Marca Personal — registro público de bloqueos (sin sesión).
   Cualquiera puede ver qué se bloqueó, quién lo firmó, hasta cuándo y con qué sello. */
'use strict';

(function () {
  const { el } = MP;
  const app = MP.$('#app');
  const est = { filtro: 'todos', datos: null };
  const z = {};

  const FILTROS = [
    ['todos', 'Todos', () => true],
    ['aplicada', 'Vigentes', (b) => b.estado === 'aplicada'],
    ['vencida', 'Vencidos', (b) => b.estado === 'vencida'],
    ['levantada', 'Levantados', (b) => b.estado === 'levantada'],
  ];
  const ESTADO = {
    aplicada: ['ok', '✓', 'Vigente'], vencida: ['neutro', '■', 'Vencido'], levantada: ['neutro', '↥', 'Levantado'],
    recibida: ['espera', '◷', 'Enviado'], fallida: ['alerta', '✕', 'Falló'],
  };


  /* NV1: un reemplazo por reclamo se decidió al resolver el reclamo, no en la firma del pedido original. */
  function textoDecision(b) {
    if (b.decision_origen === 'reclamo' && b.reclamo) return 'decidida al resolver el reclamo ' + b.reclamo + ' en el ' + MP.min(b.decision_min);
    return 'firmó en el ' + MP.min(b.decision_min);
  }
  function esqueleto() {
    z.partido = el('p', { class: 'portadilla__partido' });
    z.cifras = el('dl', { class: 'cifras' });
    z.verif = el('div', { class: 'verificacion' });
    z.filtros = el('div', { class: 'filtros', attrs: { role: 'group', 'aria-label': 'Filtrar por estado' } });
    z.tabla = el('div', { class: 'registro-caja' });
    z.vivo = el('p', { class: 'solo-lectores', attrs: { 'aria-live': 'polite' } });
    z.marcos = el('section', { class: 'publico__seccion marcos', hidden: true, attrs: { 'aria-labelledby': 'tit-marcos' } });
    z.listas = el('section', { class: 'publico__seccion listas', hidden: true, attrs: { 'aria-labelledby': 'tit-listas' } });
    z.consulta = consulta();
    MP.poner(app,
      MP.cabeceraPublica('registro'),
      el('main', { id: 'registro', class: 'publico__cuerpo' },
        el('section', { class: 'portadilla' },
          el('p', { class: 'rotulo', text: 'Transparencia' }),
          el('h1', { class: 'portadilla__titulo', text: 'Registro público de bloqueos' }),
          el('p', { class: 'portadilla__bajada', text: 'Cada bloqueo ordenado durante el partido, con el juez que lo firmó, hasta cuándo dura y el sello que lo ata a la evidencia. Se actualiza solo.' }),
          z.partido),
        z.cifras, z.consulta, z.verif, z.marcos, z.filtros, z.tabla, z.listas, z.vivo));
  }

  /* «¿Tu sitio quedó bloqueado?» (ronda 2b): consulta pública, sin red y sin cambiar nada en la plataforma. */
  function consulta() {
    const entrada = el('input', { class: 'entrada', id: 'consulta-dominio', type: 'text', name: 'dominio',
      attrs: { inputmode: 'url', autocomplete: 'off', autocapitalize: 'none', spellcheck: 'false', maxlength: '253', placeholder: 'mitienda.com.ar', 'aria-describedby': 'consulta-ayuda' } });
    const resultado = el('div', { class: 'consulta__resultado', attrs: { 'aria-live': 'polite' } });
    const boton = el('button', { class: 'boton boton--principal', type: 'submit' }, 'Consultar');
    const ESTADO_CONSULTA = { bloqueado: ['alerta', '✕', 'Bloqueado'], comparte_servidor: ['espera', '◐', 'Comparte servidor'],
      no_alcanzado: ['ok', '✓', 'No alcanzado'], invalido: ['neutro', '?', 'Dominio inválido'] };
    const form = el('form', { class: 'consulta__form', attrs: { role: 'search', novalidate: '' }, on: { submit: async (ev) => {
      ev.preventDefault();
      const d = entrada.value.trim();
      if (!d) { MP.poner(resultado, el('p', { class: 'error-campo', text: 'Escriba el dominio de su sitio.' })); entrada.focus(); return; }
      boton.disabled = true;
      MP.poner(resultado, el('p', { class: 'ayuda', text: 'Consultando…' }));
      try {
        const r = await MP.api('GET', '/api/publico/consulta?dominio=' + encodeURIComponent(d));
        const e = ESTADO_CONSULTA[r.resultado] || ['neutro', '·', MP.capital(r.resultado || '')];
        MP.poner(resultado,
          el('p', { class: 'consulta__estado' }, el('span', { class: 'estado estado--' + e[0] }, el('span', { attrs: { 'aria-hidden': 'true' }, text: e[1] }), e[2]),
            ' ', el('strong', { class: 'mono cortar', text: r.dominio || d })),
          // C9 (N13): si pegó una dirección completa, se dice qué dominio se consultó.
          r.dominio && r.dominio !== d ? el('p', { class: 'ayuda' }, 'Se consultó el dominio ', el('span', { class: 'mono', text: r.dominio }), '.') : null,
          el('p', { text: r.texto || '' }),
          (r.ordenes || []).length ? el('ul', { class: 'consulta__ordenes' }, r.ordenes.map((o) => el('li', {},
            el('a', { href: '/orden/' + encodeURIComponent(o.orden_id), text: MP.tipoBloqueo(o.tipo) + ' ' + o.objetivo }),
            el('span', { class: 'ayuda', text: ' · ' + MP.sinParentesis(o.juzgado || '') + ' · vence en el ' + MP.min(o.vence_min) })))) : null);
      } catch (e) {
        MP.poner(resultado, el('p', { class: 'error-campo', text: e.codigo === 'no_encontrado'
          ? 'La consulta todavía no está disponible en esta plataforma.' : (e.texto || 'No se pudo consultar. Vuelva a intentar.') }));
      } finally { boton.disabled = false; }
    } } },
    el('div', { class: 'campo' }, el('label', { htmlFor: 'consulta-dominio', class: 'rotulo', text: 'Dominio de su sitio' }),
      el('div', { class: 'consulta__fila' }, entrada, boton)),
    el('p', { class: 'ayuda', id: 'consulta-ayuda', text: 'Podés pegar la dirección completa: se toma solo el dominio. Se compara con las órdenes vigentes y con los sitios que comparten cada servidor bloqueado. No se guarda lo que escribas.' }));
    return el('section', { class: 'publico__seccion consulta', attrs: { 'aria-labelledby': 'tit-consulta' } },
      el('h2', { class: 'publico__titulo', id: 'tit-consulta', text: '¿Tu sitio quedó bloqueado?' }), form, resultado);
  }

  /* Órdenes marco firmadas (ronda 2b): el marco de cada turno, con el seguimiento sí o no. */
  function pintarMarcos(r) {
    if (!Array.isArray(r.marcos)) { z.marcos.hidden = true; return; }
    z.marcos.hidden = false;
    const firma = JSON.stringify(r.marcos);
    if (z.marcos.dataset.firma === firma) return;
    z.marcos.dataset.firma = firma;
    MP.poner(z.marcos,
      el('h2', { class: 'publico__titulo', id: 'tit-marcos', text: 'Orden marco' }),
      el('p', { class: 'publico__bajada', text: 'Cada juez de turno firma una orden marco con los límites del partido. Solo si lo autoriza ahí, la plataforma puede ampliar sola un bloqueo cuando la misma filtración se muda de servidor; esas órdenes empiezan con amp-.' }),
      r.marcos.length ? el('ul', { class: 'marcos__lista' }, r.marcos.slice().reverse().map((m) => { const em = MP.estadoMarco(m); return el('li', { class: ['marco-pub', !em.vigente && 'marco-pub--reemplazada'] },
        // C2 (N12): Vigente / Reemplazada en el min X / Terminó con su turno (min X) / Terminó con el partido (min X).
        el('p', { class: 'marco-pub__cab' }, el('strong', { class: 'mono', text: m.id }), ' ',
          el('span', { class: 'estado ' + (em.vigente ? 'estado--ok' : 'estado--neutro') }, el('span', { attrs: { 'aria-hidden': 'true' }, text: em.vigente ? '✓' : '■' }), em.texto)),
        el('p', {}, el('strong', { text: m.juez || '—' }), el('span', { class: 'ayuda', text: ' · ' + MP.sinParentesis(m.juzgado || '') })),
        el('p', { class: 'ayuda num', text: 'Firmada en el ' + MP.min(m.min) + (m.hora ? ' (' + String(m.hora).slice(0, 5) + ')' : '') +
          (m.turno ? ' · turno ' + MP.rangoTurno(m.turno.desde_min, m.turno.hasta_min, (r.reloj || {}).fin_min) : '') + (m.entrada !== null && m.entrada !== undefined ? ' · entrada ' + m.entrada : '') }),
        el('p', {}, 'Seguimiento de la misma filtración: ', el('strong', { text: m.seguimiento ? 'sí' : 'no' })),
        el('p', { class: 'ayuda' }, 'Huella ', MP.hash(m.huella))); }))
        : el('p', { class: 'registro__vacio', text: 'Todavía no se firmó ninguna orden marco. Sin ella, cada servidor se firma en persona.' }));
  }

  /* La lista que el equipo de cada proveedor puede leer solo (ronda 2b). */
  const LISTAS = [['vigentes.json', 'Vigentes (JSON)'], ['dominios.txt', 'Dominios'], ['ips.txt', 'IP'], ['unbound.conf', 'Unbound'], ['rpz.zone', 'Zona RPZ']];
  function pintarListas(r) {
    const provs = new Map();
    for (const p of r.proveedores || []) provs.set(p.id, p.nombre || p.id);
    for (const b of r.bloqueos || []) if (b.proveedor && !provs.has(b.proveedor)) provs.set(b.proveedor, b.proveedor_nombre || b.proveedor);
    // C1 (N1): con `proveedores` en el registro la lista está desde el minuto cero, aunque no haya bloqueos.
    if (!provs.size || !(Array.isArray(r.marcos) || Array.isArray(r.proveedores))) { z.listas.hidden = true; return; }
    z.listas.hidden = false;
    const firma = JSON.stringify([...provs]);
    if (z.listas.dataset.firma === firma) return;
    z.listas.dataset.firma = firma;
    MP.poner(z.listas,
      el('h2', { class: 'publico__titulo', id: 'tit-listas', text: 'Lista de cada proveedor' }),
      el('p', { class: 'publico__bajada', text: 'Lo que cada proveedor tiene que tener bloqueado ahora, para que su equipo lo lea sin depender de esta pantalla. Son datos, no comandos: cada equipo decide cómo aplicarlos.' }),
      el('ul', { class: 'listas__proveedores' }, [...provs].map(([id, nombre]) => el('li', { class: 'listas__fila' },
        el('strong', { class: 'listas__nombre', text: MP.sinParentesis(nombre) }),
        el('span', { class: 'listas__enlaces' }, LISTAS.map(([arch, txt]) => el('a', { href: '/proveedor/' + encodeURIComponent(id) + '/' + arch, text: txt,
          attrs: { 'aria-label': txt + ' de ' + MP.sinParentesis(nombre) } })))))));
  }

  function pintar(r) {
    est.datos = r;
    MP.ponerReloj(Object.assign({ acelerar: 0 }, r.reloj));
    const rel = r.reloj || {};
    const p = rel.partido || {};
    MP.poner(z.partido,
      el('span', {}, 'Partido ', el('strong', { text: p.nombre || '—' })),
      p.titular ? el('span', {}, 'Titular de los derechos ', el('strong', { text: p.titular })) : null,
      // N4: antes del inicio, «Todavía no empezó (faltan 3,3 min)», nunca «En juego · min -3,3».
      rel.minuto < 0 && !rel.finalizado ? el('span', { class: 'num', text: MP.antesDelInicio(rel.minuto) })
        : el('span', { class: 'num' }, rel.finalizado ? 'Partido terminado' : 'En juego · ', rel.finalizado ? null : el('strong', { text: MP.min(rel.minuto) }),
          rel.hora && !rel.finalizado ? ' (' + rel.hora.slice(0, 5) + ')' : null));

    const res = r.resumen || {};
    const cifra = (txt, valor, clase) => el('div', { class: ['cifra', clase] }, el('dt', { text: txt }), el('dd', { class: 'num', text: MP.num(valor || 0, 0) }));
    MP.poner(z.cifras,
      cifra('Bloqueos vigentes', res.bloqueos_vigentes, 'cifra--vigentes'),
      cifra('Vencidos', res.bloqueos_vencidos), cifra('Levantados', res.bloqueos_levantados),
      cifra('Sitios bloqueados', res.sitios_bloqueados),
      cifra('Reclamos recibidos', res.reclamos_recibidos), cifra('Reclamos resueltos', res.reclamos_resueltos));

    const c = r.cabeza_auditoria || {};
    const pq = r.paquete;
    MP.poner(z.verif,
      el('p', { class: 'verificacion__cabeza' }, el('strong', { text: 'Auditoría: ' + MP.plural(c.n, 'entrada encadenada', 'entradas encadenadas') + '.' }),
        el('span', {}, 'Última huella ', MP.hash(c.hash))),
      el('p', { text: 'Cada decisión, envío y respuesta de los proveedores queda en un registro donde cada entrada incluye la huella de la anterior. Si alguien cambiara una sola entrada, esta huella dejaría de coincidir con la de la exportación verificada al final del partido.' }),
      pq && pq.huella ? el('div', { class: 'verificacion__paquete' },
        el('p', { class: 'verificacion__cabeza' }, el('strong', { text: 'Huella del paquete' + (pq.exportado_min !== null && pq.exportado_min !== undefined ? ' (exportado en el ' + MP.min(pq.exportado_min) + ')' : '') }),
          MP.hash(pq.huella)),
        el('p', { text: 'Es la huella de la entrega completa del partido. Se publica para que nadie pueda cambiar la entrega después: quien tenga el paquete puede recalcularla y comprobar que es el mismo.' })) : null);

    pintarMarcos(r);
    pintarListas(r);
    pintarFiltros();
    pintarTabla();
  }

  function pintarFiltros() {
    const bloqueos = (est.datos && est.datos.bloqueos) || [];
    MP.poner(z.filtros, FILTROS.map(([id, txt, fn]) => el('button', {
      class: 'filtro', type: 'button', attrs: { 'aria-pressed': est.filtro === id ? 'true' : 'false' },
      on: { click: () => { est.filtro = id; pintarFiltros(); pintarTabla(); z.vivo.textContent = txt + ': ' + MP.plural(bloqueos.filter(fn).length, 'bloqueo', 'bloqueos') + '.'; } },
    }, txt, el('span', { class: 'num', text: String(bloqueos.filter(fn).length) }))));
  }

  function pintarTabla() {
    const fn = (FILTROS.find((f) => f[0] === est.filtro) || FILTROS[0])[2];
    const lista = ((est.datos && est.datos.bloqueos) || []).filter(fn)
      .slice().sort((a, b) => (b.desde_min || 0) - (a.desde_min || 0) || String(a.orden_id).localeCompare(String(b.orden_id)));
    if (!lista.length) {
      MP.poner(z.tabla, el('p', { class: 'registro__vacio', text: est.filtro === 'todos' ? 'Todavía no hay bloqueos aplicados.' : 'No hay bloqueos en este estado.' }));
      return;
    }
    MP.poner(z.tabla, el('table', { class: 'registro' },
      el('caption', { class: 'solo-lectores', text: 'Bloqueos ordenados durante el partido' }),
      el('thead', {}, el('tr', {},
        ['Qué se bloquea', 'Estado', 'Vigencia', 'Quién lo ordenó', 'Sello', ''].map((t) => el('th', { scope: 'col', text: t })))),
      el('tbody', {}, lista.map(fila))));
  }

  function fila(b) {
    const e = ESTADO[b.estado] || ['neutro', '·', MP.capital(b.estado)];
    const hasta = b.estado === 'aplicada' ? 'hasta el ' + MP.min(b.vence_min) : 'terminó en el ' + MP.min(b.hasta_min);
    const lev = b.levantamiento;
    // Ronda 2b: el número de orden dice si es una ampliación (amp-); sin ese prefijo, lo dice la decisión.
    // g-pantallas-1: el reemplazo por reclamo no es una ampliación automática.
    const ampl = b.decision_origen !== 'reclamo' && (/^amp-/.test(b.orden_id || '') || b.decision_tipo === 'ampliacion_dinamica' || !!b.bajo_orden_de);
    return el('tr', {},
      el('td', { class: 'registro__que' },
        el('strong', { class: 'mono cortar', text: b.objetivo }),
        el('span', { class: 'ayuda', text: 'Por ' + (b.tipo === 'ip' ? 'IP' : 'dominio') + ' en ' + MP.sinParentesis(b.proveedor_nombre || b.proveedor) + ' · ' + b.expediente }),
        lev ? el('span', { class: 'ayuda', text: 'Levantado en el ' + MP.min(lev.min) + ((lev.juez_nombre || lev.juez) ? ' por ' + (lev.juez_nombre || lev.juez) : '') + (lev.reclamo ? ' (reclamo ' + lev.reclamo + ')' : '') + '.' }) : null),
      el('td', { class: 'registro__estado' }, el('span', { class: 'estado estado--' + e[0] }, el('span', { attrs: { 'aria-hidden': 'true' }, text: e[1] }), e[2])),
      el('td', { class: 'num', dataset: { rotulo: 'Vigencia' } }, 'desde el ' + MP.min(b.desde_min) + ', ' + hasta),
      el('td', { dataset: { rotulo: 'Ordenó' } },
        el('span', { class: 'rotulo registro__firma', text: ampl ? 'Ampliación automática' : 'Firmada en persona' }),
        ampl ? el('span', { text: MP.textoAmpliacion(b) }) : [el('span', { text: b.juez || '—' }),
          el('span', { class: 'ayuda', text: MP.sinParentesis(b.juzgado || '') + (b.decision_min !== null && b.decision_min !== undefined ? ' · ' + textoDecision(b) : '') })]),
      el('td', { class: 'registro__sello', dataset: { rotulo: 'Sello' } }, MP.hash(b.sello)),
      el('td', { class: 'registro__ver' }, el('a', { href: '/orden/' + encodeURIComponent(b.orden_id), text: 'Ver la orden →',
        attrs: { 'aria-label': 'Ver la orden de ' + b.objetivo + ' en ' + (b.proveedor_nombre || b.proveedor) } })));
  }

  if (app && app.classList.contains('app-registro')) {
    esqueleto();
    MP.vigilar({
      cargar: async () => { const r = await MP.api('GET', '/api/publico/registro'); pintar(r); return r; },
      alPerderSesion: () => {},
    });
  }
})();
