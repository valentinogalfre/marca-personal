/* Marca Personal — la orden pública (/orden/<id>): el oficio que recibe el proveedor,
   en lenguaje llano, con el sello, la evidencia y el kit listo para aplicar. */
'use strict';

(function () {
  const { el } = MP;
  const app = MP.$('#app');
  if (!app || !app.classList.contains('app-orden')) return;
  const id = decodeURIComponent(location.pathname.replace(/^\/orden\//, '').replace(/\/$/, ''));
  const est = { selloVisto: null, traeV: null };
  const cuerpo = el('main', { id: 'orden', class: 'publico__cuerpo' });
  MP.poner(app, MP.cabeceraPublica('orden'), cuerpo);

  const ESTADO = { aplicada: ['verde', 'Bloqueo vigente'], recibida: ['amarilla', 'Enviada al proveedor'], por_enviar: ['amarilla', 'Por enviar'],
    espera_ratificacion: ['amarilla', 'Espera ratificación'], fallida: ['roja', 'Falló'], vencida: ['gris', 'Vencida'],
    levantada: ['gris', 'Levantada'], rechazada: ['roja', 'Rechazada'] };

  function noExiste() {
    document.title = 'Orden inexistente — Marca Personal';
    MP.poner(cuerpo, el('section', { class: 'portadilla' },
      el('p', { class: 'rotulo', text: 'Orden de bloqueo' }),
      el('h1', { class: 'portadilla__titulo', text: 'No existe esa orden' }),
      el('p', { class: 'portadilla__bajada' }, 'Revise el enlace o busque la orden en el ', el('a', { href: '/transparencia', text: 'registro público' }), '.'),
      el('p', { class: 'mono cortar ayuda', text: id })));
  }

  async function cargar() {
    // La vista de la orden trae su versión (`v`): con eso alcanza. Si no la trae (motor anterior), se toma la
    // versión vigente y se vuelve a leer la orden, así ningún cambio se pierde entre las dos lecturas.
    const ruta = '/api/publico/ordenes/' + encodeURIComponent(id);
    try {
      let d = await MP.api('GET', ruta);
      if (typeof d.v === 'number') { pintar(d); return { v: d.v }; }
      const actual = await MP.api('GET', '/api/cambios?v=-1');
      d = await MP.api('GET', ruta);
      pintar(d);
      return { v: actual && typeof actual.v === 'number' ? actual.v : 0 };
    } catch (e) {
      if (e.codigo !== 'no_encontrado') throw e;
      noExiste();
      // Un número de orden que no existe casi nunca aparece después: se vuelve a mirar cada 30 s, no en cada
      // cambio de la plataforma (antes eran dos pedidos por cambio, sin fin).
      await new Promise((res) => setTimeout(res, 30000));
      const actual = await MP.api('GET', '/api/cambios?v=-1');
      return { v: actual && typeof actual.v === 'number' ? actual.v : 0 };
    }
  }

  const NO_RIGE = new Set(['levantada', 'vencida', 'fallida', 'rechazada', 'perdida']);
  // La sesión del abonado no es pública (ronda 2b): si la marca llega entera, se muestra solo el prefijo.
  const sinSesion = (m) => String(m || '').replace(/-S\d+$/, '');

  function hecho(rotulo, ...valor) { return el('div', { class: 'hecho' }, el('dt', { text: rotulo }), el('dd', {}, ...valor)); }

  function pintar(d) {
    const o = d.orden || {};
    const e = ESTADO[o.estado] || ['gris', MP.capital(o.estado)];
    document.title = 'Orden ' + (o.objetivo || '') + ' — Marca Personal';
    const dec = d.decision || {};
    // Ronda 2b: el número de orden dice si es una ampliación (amp-) o una firma en persona (ord-).
    // g-pantallas-1: un reemplazo por reclamo lo decidió el juez al resolver el reclamo, aunque reemplace una ampliación.
    const ampl = !(d.decision_origen === 'reclamo' && !!d.reclamo) &&
      (/^amp-/.test(o.orden_id || id) || dec.tipo === 'ampliacion_dinamica' || !!(d.bajo_orden_de || dec.bajo_orden_de));
    const rige = !NO_RIGE.has(o.estado);
    const lev = d.levantamiento;
    // NV1: un reemplazo por reclamo lo ordenó la resolución del reclamo, no la firma del pedido original.
    const porReclamo = !ampl && d.decision_origen === 'reclamo' && !!d.reclamo;
    const nuevo = est.selloVisto !== null && est.selloVisto !== d.sello;
    est.selloVisto = d.sello;

    let vigencia;
    if (o.aplicada_min === null || o.aplicada_min === undefined) vigencia = 'Todavía no aplicada · vence en el ' + MP.min(o.vence_min);
    else if (o.estado === 'aplicada') vigencia = 'Desde el ' + MP.min(o.aplicada_min) + ' hasta el ' + MP.min(o.vence_min) + ' (final del partido)';
    else vigencia = 'Del ' + MP.min(o.aplicada_min) + ' al ' + MP.min(o.finalizada_min);

    const ev = d.evidencia || {};
    const kit = d.kit || [];
    const leyendaEnNotas = kit.some((k) => /Ejemplos de referencia|estas líneas en (tu|su) equipo/.test(k.nota || ''));

    MP.poner(cuerpo,
      el('article', { class: 'oficio', attrs: { 'aria-labelledby': 'tit-orden' } },
        el('header', { class: 'oficio__cabeza' },
          el('span', { class: 'tarjeta tarjeta--' + e[0], text: e[1] }),
          el('span', { class: 'rotulo', text: 'Orden de bloqueo · ' + (d.expediente || '') + ' · ubicación ' + (d.ubicacion || '—') }),
          o.origen === 'reintento' ? el('span', { class: 'estado estado--neutro', text: 'Reintento n.º ' + o.intento }) : null,
          o.origen === 'reemplazo_reclamo' ? el('span', { class: 'estado estado--espera', text: 'Reemplazo por reclamo' }) : null,
          el('span', { class: 'estado ' + (ampl ? 'estado--espera' : 'estado--ok') + ' oficio__firma-tipo' },
            el('span', { attrs: { 'aria-hidden': 'true' }, text: ampl ? '↻' : '✍' }), ampl ? 'Ampliación automática' : 'Firmada en persona')),
        el('h1', { class: 'oficio__texto', id: 'tit-orden', text: d.texto_llano || '' }),
        // El texto de la ampliación lo redacta el motor: se usa tal cual (solo se agrega la aclaración si no la trae).
        ampl ? (() => {
          const t = MP.textoAmpliacion({ texto: dec.texto, bajo_orden_de: dec.bajo_orden_de || d.bajo_orden_de });
          return el('p', { class: 'nota' }, el('strong', { text: t }),
            /no se firmó en persona/i.test(t) ? null : ' El juez no firmó este servidor en persona: lo alcanzó el seguimiento que había autorizado para esta filtración.');
        })() : null,
        lev ? el('p', { class: 'nota nota--alerta' }, el('strong', { text: 'Levantada en el ' + MP.min(lev.min) + ((lev.juez_nombre || lev.juez) ? ' por ' + (lev.juez_nombre || lev.juez) : '') + '. ' }),
          lev.motivo || '', lev.reclamo ? ' (reclamo ' + lev.reclamo + ')' : '') : null,
        el('dl', { class: 'oficio__hechos' },
          hecho('Proveedor', o.proveedor_nombre || o.proveedor || '—'),
          hecho('Qué se bloquea', MP.tipoBloqueo(o.tipo) + ' ', el('span', { class: 'mono cortar', text: o.objetivo || '' })),
          hecho('Estado', MP.estadoOrden(o.estado)),
          hecho('Vigencia', el('span', { class: 'num', text: vigencia })),
          hecho(ampl ? 'Juez que la respalda' : 'Ordenó', d.juez || '—', d.juzgado ? el('span', { class: 'ayuda', text: MP.sinParentesis(d.juzgado) }) : null),
          hecho(ampl ? 'Ampliación automática' : 'Decisión', porReclamo ? 'Decidida al resolver el reclamo ' + d.reclamo + ' · ' : null,
            el('span', { class: 'num', text: MP.min(d.decision_min) + (d.decision_hora ? ' · ' + String(d.decision_hora).slice(0, 8) : '') }))),

        el('section', { class: 'oficio__seccion', attrs: { 'aria-labelledby': 'tit-porque' } },
          el('h2', { id: 'tit-porque', text: 'Por qué se ordena' }),
          el('ol', { class: 'porque' }, (d.por_que || []).map((t) => el('li', { text: t })))),

        el('section', { class: 'oficio__seccion firma-oficio', attrs: { 'aria-label': 'Sello' } },
          MP.sello({ titulo: o.estado === 'levantada' ? 'Levantada' : 'Ordenado', codigo: d.sello, pie: (porReclamo ? 'Reclamo ' + d.reclamo + ' · ' : '') + MP.min(d.decision_min), nuevo }),
          el('div', { class: 'firma-oficio__texto' },
            el('p', { class: 'rotulo', text: 'Sello' }), MP.hash(d.sello),
            el('p', { class: 'rotulo', text: 'Huella de la evidencia' }), MP.hash(d.huella),
            // N11/C10: qué une el sello lo dice el motor en «Por qué se ordena» (distinto para amp- y ord-); acá no se repite.
            el('p', { class: 'ayuda', text: 'Con la exportación del partido, cualquiera puede recalcular el sello.' }))),

        el('section', { class: 'oficio__seccion', attrs: { 'aria-labelledby': 'tit-ev' } },
          el('h2', { id: 'tit-ev', text: 'Evidencia' }),
          el('dl', { class: 'oficio__hechos' },
            hecho('Marca de agua', el('span', { class: 'mono cortar', text: sinSesion(ev.marca) || '—' }),
              el('span', { class: 'ayuda', text: 'Solo el prefijo de la señal: la sesión identifica a un abonado y no se publica.' })),
            d.filtracion ? hecho('Filtración', el('span', { class: 'mono', text: d.filtracion })) : null,
            hecho('Servidor', el('span', { class: 'mono cortar', text: ev.host || '—' })),
            hecho('IP y red', el('span', { class: 'mono', text: (ev.ip || '—') }), ' · AS' + (ev.asn || '—') + (ev.organizacion ? ' ' + ev.organizacion : '')),
            hecho('Captura (sha256)', MP.hash(ev.captura_sha256)),
            hecho('Daño colateral', riesgo(ev.riesgo, o.tipo)),
            hecho('Por qué ese tipo de bloqueo', ev.motivo_colateral || '—'))),

        el('section', { class: 'oficio__seccion', attrs: { 'aria-labelledby': 'tit-kit' } },
          el('h2', { id: 'tit-kit', text: rige ? 'Para el proveedor: cómo aplicarlo' : 'Para el proveedor: cómo quitarlo' }),
          // Si el motor ya lo dice en la nota de cada equipo, no se repite.
          rige || kit.some((k) => /ya no rige/i.test(k.nota || '')) ? null
            : el('p', { class: 'nota nota--alerta kit__aviso' }, el('strong', { text: 'Esta orden ya no rige. ' }), 'Si la aplicó, quítela.'),
          rige ? notaHoras(d) : null,
          el('div', { class: 'kit' }, kit.map((k) => equipo(k, rige))),
          leyendaEnNotas || !rige ? null : el('p', { class: 'kit__leyenda', text: 'Pruebe estas líneas en su equipo antes del partido. Lo que obliga es la orden (objetivo y vencimiento); las líneas son una ayuda.' }),
          o.proveedor ? el('p', { class: 'ayuda' }, 'Lo vigente de este proveedor, para que su equipo lo lea solo: ',
            el('a', { href: '/proveedor/' + encodeURIComponent(o.proveedor) + '/vigentes.json', text: 'lista del proveedor' }), '.') : null),

        el('section', { class: 'oficio__seccion', attrs: { 'aria-labelledby': 'tit-obj' } },
          el('h2', { id: 'tit-obj', text: 'Cómo objetar esta orden' }),
          el('p', { class: 'objetar', text: d.como_objetar || '' })),

        el('p', { class: 'ayuda' }, el('a', { href: '/transparencia', text: '← Volver al registro público' }))));
  }

  // textos-5: `riesgo` es el de bloquear la IP; una orden por nombre no toca a los otros sitios de esa IP.
  /* Ola C (kit): con el partido acelerado, el texto dice la hora del partido y las líneas del equipo la hora real
     (la del reloj del equipo, con segundos). Si no coinciden, se rotula cada una; nunca dos horas sin decir cuál es cuál. */
  function horasDeLaOrden(d) {
    const p = /\(hora (\d{1,2}:\d{2}(?::\d{2})?)\)/.exec(d.texto_llano || '');
    let real = null;
    for (const k of d.kit || []) {
      const x = /vence (?:a las )?(\d{1,2}:\d{2}(?::\d{2})?)/.exec([k.aplicar, k.vencer, k.nota].filter(Boolean).join(' '));
      if (x) { real = x[1]; break; }
    }
    return { partido: p ? p[1] : null, real };
  }
  function notaHoras(d) {
    const h = horasDeLaOrden(d);
    if (!h.partido || !h.real || h.partido.slice(0, 5) === h.real.slice(0, 5)) return null;
    return el('p', { class: 'nota kit__horas' },
      el('strong', { text: 'Dos horas distintas. ' }),
      'La hora ' + h.partido + ' del texto de la orden es la hora del partido. Las líneas para su equipo vencen a las ' +
      h.real + ': esa es la hora real, la del reloj de su equipo.');
  }

  function riesgo(r, tipo) {
    if (tipo === 'dominio' && (r === 'alto' || r === 'medio')) {
      return el('span', { class: 'estado estado--ok', text: 'Ninguno: se bloquea solo el nombre (bloquear la IP era riesgo ' + r + ')' });
    }
    // pantallas-3: el motor emite nulo/medio/alto/desconocido («bajo» queda por datos viejos).
    const m = { nulo: ['ok', 'Nulo'], bajo: ['ok', 'Bajo'], medio: ['espera', 'Medio'], alto: ['alerta', 'Alto'],
      desconocido: ['neutro', 'Sin datos'] }[r] || ['neutro', r ? MP.capital(r) : '—'];
    return el('span', { class: 'estado estado--' + m[0], text: m[1] });
  }

  /* Ronda 2b: preparar (una sola vez), aplicar, quitar y vencer. Si la orden ya no rige, solo quitar. */
  function equipo(k, rige) {
    return el('div', { class: 'kit__equipo' },
      el('p', { class: 'kit__nombre', text: k.equipo }),
      rige ? linea('Preparar (una sola vez)', k.preparar) : null,
      rige ? linea('Aplicar', k.aplicar) : null,
      linea('Quitar', k.quitar),
      rige ? linea('Vencer', k.vencer) : null,
      k.nota ? el('p', { class: 'kit__nota', text: k.nota }) : null);
  }

  function linea(rotulo, texto) {
    if (!texto) return null;
    const codigo = el('pre', { class: 'kit__codigo', text: texto });
    const estado = el('span', { class: 'ayuda', attrs: { role: 'status' } });
    const boton = el('button', { class: 'boton boton--chico', type: 'button', on: { click: async () => {
      try {
        await navigator.clipboard.writeText(texto);
        estado.textContent = 'Copiado.';
      } catch (_) {
        const rango = document.createRange();
        rango.selectNodeContents(codigo);
        const sel = window.getSelection();
        sel.removeAllRanges(); sel.addRange(rango);
        estado.textContent = 'Seleccionado: copie con Ctrl+C o ⌘C.';
      }
      setTimeout(() => { estado.textContent = ''; }, 2500);
    } }, attrs: { 'aria-label': 'Copiar el comando para ' + rotulo.toLowerCase() } }, 'Copiar');
    return el('div', { class: 'kit__linea' },
      el('div', { class: 'kit__fila' }, el('span', { class: 'rotulo', text: rotulo }), el('span', {}, estado, ' ', boton)),
      codigo);
  }

  MP.poner(cuerpo, el('p', { class: 'cargando', text: 'Cargando la orden…' }));
  MP.vigilar({ cargar, alPerderSesion: () => {} });
})();
