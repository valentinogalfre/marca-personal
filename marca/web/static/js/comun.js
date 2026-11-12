/* Marca Personal — utilidades comunes de las pantallas.
   Regla: todo dato de la API es no confiable. Se pone con textContent o
   creando nodos; nunca con innerHTML. MP.el se niega a recibir HTML. */
'use strict';

(function () {
  const MP = {};
  window.MP = MP;

  /* ------------------------------------------------------------------ nodos */
  const PROHIBIDAS = new Set(['innerHTML', 'outerHTML', 'insertAdjacentHTML', 'srcdoc']);

  function agregarHijos(nodo, hijos) {
    for (const h of hijos) {
      if (h === null || h === undefined || h === false || h === '') continue;
      if (Array.isArray(h)) { agregarHijos(nodo, h); continue; }
      nodo.appendChild(h instanceof Node ? h : document.createTextNode(String(h)));
    }
  }

  function aplicar(nodo, props, esSvg) {
    if (!props) return;
    for (const [k, v] of Object.entries(props)) {
      if (v === undefined || v === null || v === false) continue;
      if (PROHIBIDAS.has(k)) throw new Error('MP.el no acepta ' + k);
      if (k === 'class') nodo.setAttribute('class', Array.isArray(v) ? v.filter(Boolean).join(' ') : v);
      else if (k === 'text') nodo.textContent = String(v);
      else if (k === 'on') for (const [ev, fn] of Object.entries(v)) nodo.addEventListener(ev, fn);
      else if (k === 'attrs') for (const [a, av] of Object.entries(v)) { if (av !== null && av !== undefined && av !== false) nodo.setAttribute(a, av === true ? '' : String(av)); }
      else if (k === 'dataset') for (const [a, av] of Object.entries(v)) nodo.dataset[a] = String(av);
      else if (k === 'style') for (const [a, av] of Object.entries(v)) nodo.style.setProperty(a, String(av));
      else if (esSvg) nodo.setAttribute(k, String(v));
      else nodo[k] = v;
    }
  }

  MP.el = function (tag, props, ...hijos) {
    const n = document.createElement(tag);
    aplicar(n, props, false);
    agregarHijos(n, hijos);
    return n;
  };

  MP.svg = function (tag, props, ...hijos) {
    const n = document.createElementNS('http://www.w3.org/2000/svg', tag);
    aplicar(n, props, true);
    agregarHijos(n, hijos);
    return n;
  };

  MP.vaciar = function (n) { while (n && n.firstChild) n.removeChild(n.firstChild); return n; };
  MP.poner = function (n, ...hijos) { MP.vaciar(n); agregarHijos(n, hijos); return n; };
  MP.$ = (sel, raiz) => (raiz || document).querySelector(sel);

  /* --------------------------------------------------------------- formatos */
  const nf = {};
  MP.num = function (x, dec) {
    if (x === null || x === undefined || x === '' || !Number.isFinite(Number(x))) return '—';
    const d = dec === undefined ? 1 : dec;
    const k = String(d);
    nf[k] = nf[k] || new Intl.NumberFormat('es-AR', { minimumFractionDigits: 0, maximumFractionDigits: d });
    return nf[k].format(Number(x));
  };
  // Un valor ausente o no numérico se muestra «—», nunca «None», «null», «NaN» ni «— min».
  const sinValor = (x) => x === null || x === undefined || x === '' || !Number.isFinite(Number(x));
  /* Ronda 3, C8: el ÚNICO redondeo de minutos de las pantallas. Igual que `canon.min_txt` del motor
     (`toFixed(1)`: valor binario exacto, un decimal, coma) y, como `marco._num`, sin «,0» en los enteros
     («min 105», «min 60,3»). Nunca «-0,0»; lo que no es número sale «—». */
  MP.minTxt = function (x) {
    if (sinValor(x)) return '—';
    const n = Number(x);
    let s = n.toFixed(1);
    if (s === '-0.0') s = '0.0';
    s = s.replace(/\.0$/, '');  // como `marco._num`: «104,98» → «105», no «105,0»
    return s.replace('.', ',');
  };
  MP.min = (x) => (sinValor(x) ? '—' : 'min ' + MP.minTxt(x));
  MP.dur = (x) => (sinValor(x) ? '—' : MP.minTxt(x) + ' min');
  /* N4: antes del pitazo inicial el minuto es negativo; se dice cuánto falta, nunca «min -3,3». */
  MP.antesDelInicio = (m) => (sinValor(m) ? 'Todavía no empezó'
    : 'Todavía no empezó (faltan ' + MP.minTxt(Math.max(0, -Number(m))) + ' min)');
  MP.pct = (x) => (sinValor(x) ? '—' : MP.num(x, 1) + ' %');
  /* Adenda 3, A: cobertura normalizada. Con `sin_ventana` (ubicación sin tiempo para medir) los tres datos van «—». */
  MP.cobertura = function (c) {
    const v = (x) => (sinValor(x) ? null : Number(x));
    c = c || {};
    if (c.sin_ventana === true) return { sinVentana: true, cubiertos: null, primer: null, completo: null, residual: null };
    return { sinVentana: false, cubiertos: v(c.clientes_cubiertos_pct), primer: v(c.primer_bloqueo_min),
      completo: v(c.completo_min), residual: v(c.visibilidad_residual_pct) };
  };
  MP.clientes = function (n) {
    if (n === null || n === undefined) return '—';
    if (n >= 1e6) return MP.num(n / 1e6, 1) + ' M';
    if (n >= 1e3) return MP.num(n / 1e3, 0) + ' k';
    return MP.num(n, 0);
  };
  /* «1 descarte», «3 descartes»: el número y la palabra concuerdan. */
  MP.plural = (n, uno, varios) => MP.num(n || 0, 0) + ' ' + (Number(n) === 1 ? uno : varios);
  MP.conPunto = (s) => { const t = String(s || '').trim(); return t && !/[.!?…]$/.test(t) ? t + '.' : t; };
  /* Un turno que termina después del partido se lee «hasta el final del partido». */
  MP.hastaTurno = (hasta, fin) => (hasta !== null && hasta !== undefined && fin !== null && fin !== undefined && hasta >= fin
    ? 'hasta el final del partido' : 'hasta el ' + MP.min(hasta));
  /* «Turno desde antes del partido hasta el min 50», «Turno desde el min 50 hasta el final del partido». */
  MP.rangoTurno = (desde, hasta, fin) => (desde !== null && desde !== undefined && desde < 0 ? 'desde antes del partido' : 'desde el ' + MP.min(desde)) +
    ' ' + MP.hastaTurno(hasta, fin);
  MP.capital = (s) => (s ? String(s).charAt(0).toUpperCase() + String(s).slice(1) : '');
  MP.sinParentesis = (s) => String(s || '').replace(/\s*\([^)]*\)\s*$/, '');
  MP.tipoBloqueo = (t) => (t === 'ip' ? 'IP' : t === 'dominio' ? 'Dominio' : MP.capital(t));

  /* El hash en grupos de cuatro, en spans: se lee fácil y al copiar sale sin espacios. */
  MP.hash = function (texto, clase) {
    const s = String(texto || '');
    const grupos = [];
    for (let i = 0; i < s.length; i += 4) grupos.push(MP.el('span', { text: s.slice(i, i + 4) }));
    return MP.el('span', { class: ['hash', clase], attrs: { title: s } }, grupos);
  };

  MP.sello = function (opc) {
    return MP.el('div', { class: ['sello', opc.rechazo && 'sello--rechazo', opc.nuevo && 'sello--nuevo'],
      attrs: { role: 'img', 'aria-label': (opc.titulo || 'Sello') + ' ' + (opc.codigo || '') } },
    MP.el('span', { class: 'sello__titulo', text: opc.titulo || 'Firmado' }),
    opc.codigo ? MP.el('span', { class: 'sello__codigo' },
      String(opc.codigo).match(/.{1,16}/g).map((linea) => MP.el('span', { text: linea }))) : null,
    opc.pie ? MP.el('span', { class: 'sello__pie', text: opc.pie }) : null);
  };

  MP.logo = function () {
    return MP.svg('svg', { viewBox: '0 0 32 32', 'aria-hidden': 'true' },
      MP.svg('circle', { cx: '13', cy: '16', r: '5.5', fill: 'currentColor' }),
      MP.svg('path', { d: 'M20.5 6.2A11 11 0 1 0 20.5 25.8', fill: 'none', stroke: 'currentColor', 'stroke-width': '3', 'stroke-linecap': 'round' }),
      MP.svg('circle', { cx: '25.5', cy: '16', r: '2.2', fill: 'currentColor', opacity: '.55' }));
  };

  /* Una ampliación automática nunca se presenta como firma en persona: se dice bajo qué seguimiento salió.
     Si el motor ya redactó el texto (decision.texto o, en el registro, decision_texto; ronda 3, C7) se usa tal
     cual; si no, se arma con bajo_orden_de = {juez_id, nombre, entrada, min, otorgada_por, ratificada_por}
     con la forma «sin orden marco» de C7. */
  MP.textoAmpliacion = function (d) {
    const x = d || {};
    const texto = x.texto || x.decision_texto;
    if (texto) return MP.conPunto(texto);
    const b = x.bajo_orden_de;
    const otorgada = b && (b.otorgada_por || (b.nombre ? b : null));
    const fin = ' No se firmó en persona.';
    if (otorgada && otorgada.nombre) {
      const r = b.ratificada_por;
      return 'Ampliación automática del sistema bajo el seguimiento otorgado por ' + otorgada.nombre +
        ' en el minuto ' + MP.minTxt(otorgada.min) +
        (r && r.nombre ? ', ratificado por ' + r.nombre + ' en el minuto ' + MP.minTxt(r.min) : '') + '.' + fin;
    }
    return 'Ampliación automática del sistema' + (x.juez ? ', bajo el seguimiento que respalda ' + x.juez : '') +
      (x.min !== null && x.min !== undefined ? ', en el ' + MP.min(x.min) : '') + '.' + fin;
  };

  /* Ronda 3 (N16): el tipo de cada entrada de auditoría con su nombre para leer. Las claves no cambian. */
  MP.TIPO_AUDITORIA = {
    inicio: 'Inicio de la plataforma',
    reanudacion: 'Reanudación tras un reinicio',
    sesion_iniciada: 'Sesión iniciada',
    sesion_cerrada: 'Sesión cerrada',
    login_fallido: 'Ingreso fallido',
    deteccion_recibida: 'Detección recibida',
    deteccion_descartada: 'Detección descartada',
    deteccion_invalida: 'Detección inválida',
    expediente_abierto: 'Expediente abierto',
    expediente_anulado: 'Expediente anulado',
    expediente_visto: 'Expediente visto por el juez',
    ubicacion_armada: 'Ubicación armada',
    ubicacion_sin_decidir: 'Ubicación sin decidir',
    notificacion_juez: 'Aviso al juez',
    alerta: 'Alerta',
    orden_marco: 'Orden marco firmada',
    decision_juez: 'Decisión del juez',
    orden_dinamica_otorgada: 'Seguimiento otorgado',
    ampliacion_dinamica: 'Ampliación automática',
    dinamica_revocada: 'Seguimiento frenado',
    traspaso_de_turno: 'Cambio de turno',
    traspaso_ratificado: 'Turno recibido',
    aviso_corte_en_origen: 'Aviso de corte en origen',
    orden_enviada: 'Orden enviada',
    orden_recibida: 'Orden recibida por el proveedor',
    orden_aplicada: 'Orden aplicada',
    orden_fallida: 'Orden fallida',
    orden_reintentada: 'Orden reintentada',
    orden_en_espera: 'Orden en espera',
    orden_vencida: 'Orden vencida',
    orden_levantada: 'Orden levantada',
    orden_perdida: 'Orden perdida',
    orden_rechazada: 'Orden rechazada',
    orden_reconciliada: 'Orden reconciliada',
    reclamo_recibido: 'Reclamo recibido',
    reclamo_verificado: 'Reclamo verificado',
    reclamo_resuelto: 'Reclamo resuelto',
    reclamo_invalido: 'Reclamo inválido',
    partido_finalizado: 'Partido terminado',
    vencimiento_verificado: 'Vencimiento verificado',
    exportacion: 'Exportación',
    auditoria_reparada: 'Auditoría reparada',
    testigos_guardados: 'Testigos guardados',
  };
  MP.tipoAuditoria = (t) => (Object.prototype.hasOwnProperty.call(MP.TIPO_AUDITORIA, t) ? MP.TIPO_AUDITORIA[t]
    : MP.capital(String(t || '').replace(/_/g, ' ')));

  /* Ronda 3, C2: estado de una orden marco. Con `estado` del motor; sin él, como antes (`vigente`). */
  MP.estadoMarco = function (m) {
    const x = m || {};
    const e = x.estado || (x.vigente === false ? 'reemplazada' : 'vigente');
    const cuando = (x.estado_min !== null && x.estado_min !== undefined) ? x.estado_min : null;
    if (e === 'vigente') return { clave: e, vigente: true, texto: 'Vigente' };
    if (e === 'reemplazada') return { clave: e, vigente: false, texto: cuando === null ? 'Reemplazada' : 'Reemplazada en el ' + MP.min(cuando) };
    if (e === 'turno_terminado') return { clave: e, vigente: false, texto: 'Terminó con su turno' + (cuando === null ? '' : ' (' + MP.min(cuando) + ')') };
    if (e === 'partido_terminado') return { clave: e, vigente: false, texto: 'Terminó con el partido' + (cuando === null ? '' : ' (' + MP.min(cuando) + ')') };
    return { clave: e, vigente: false, texto: MP.capital(String(e).replace(/_/g, ' ')) };
  };

  /* Ronda 3 (C4, C12): cómo terminó el bloqueo de una ubicación sin órdenes activas. Cuentan las órdenes que
     llegaron a aplicarse (si ninguna trae `aplicada_min`, las levantadas y vencidas). «levantada» si todas se
     levantaron; «vencida» si alguna siguió hasta el final del partido; null si sigue activa o no se sabe.
     Con `terminado` (el partido terminó), lo que el proveedor todavía no informó cuenta como vencido: su
     `vence_min` ya pasó y no rige más, aunque el estado no se haya actualizado. */
  MP.finDeBloqueo = function (ordenes, terminado) {
    const ACTIVAS = ['por_enviar', 'recibida', 'aplicada', 'espera_ratificacion'];
    let lista = ordenes || [];
    if (terminado) lista = lista.map((o) => (ACTIVAS.includes(o.estado) ? Object.assign({}, o, { estado: 'vencida' }) : o));
    if (lista.some((o) => ACTIVAS.includes(o.estado))) return null;
    const conMin = lista.filter((o) => o.aplicada_min !== null && o.aplicada_min !== undefined);
    const base = conMin.length ? conMin : lista.filter((o) => o.estado === 'levantada' || o.estado === 'vencida');
    if (!base.length) return terminado && lista.length ? 'vencida' : null;
    if (base.every((o) => o.estado === 'levantada')) return 'levantada';
    if (base.some((o) => o.estado === 'vencida')) return 'vencida';
    return null;
  };

  /* Ronda 3, C3: el texto con que se cerró un aviso atendido (o null). */
  MP.cierreAviso = (a) => (a && a.cierre && a.cierre.texto ? String(a.cierre.texto) : null);

  /* Avisos: los repetidos van juntos (por `clave`, o por texto si no viene) con su cuenta; el más nuevo manda.
     Recibe la lista del más nuevo al más viejo y la devuelve igual. */
  MP.agruparAvisos = function (avisos) {
    const grupos = new Map();
    for (const a of avisos || []) {
      const k = a.clave || (a.tipo + '|' + a.texto);
      const veces = Number(a.cuenta) > 0 ? Number(a.cuenta) : 1;
      const g = grupos.get(k);
      if (g) { g.cuenta += veces; g.desde_min = a.min; }
      else grupos.set(k, Object.assign({}, a, { cuenta: veces, desde_min: a.min }));
    }
    return [...grupos.values()];
  };
  /* Los que piden algo al juez pesan más que los informativos, mientras no estén atendidos. */
  MP.AVISOS_DE_ACCION = new Set(['reclamo', 'traspaso']);
  MP.pideAccion = (a) => MP.AVISOS_DE_ACCION.has(a.tipo) && !a.atendido;

  /* Cabecera de las pantallas públicas (registro y orden). */
  MP.cabeceraPublica = function (actual) {
    return MP.el('header', { class: 'publico__cabeza' },
      MP.el('a', { class: 'logo', href: '/' }, MP.logo(), MP.el('span', { class: 'logo__texto', text: 'Marca Personal' })),
      MP.el('nav', { class: 'publico__nav', attrs: { 'aria-label': 'Secciones' } },
        MP.el('a', { href: '/', text: 'Portada' }),
        MP.el('a', { href: '/transparencia', text: 'Registro público', attrs: { 'aria-current': actual === 'registro' ? 'page' : null } })));
  };

  /* Estados de una orden: texto + ícono + clase (nunca solo color). */
  MP.ESTADO_ORDEN = {
    por_enviar: { texto: 'Por enviar', icono: '…', clase: 'espera' },
    recibida: { texto: 'Recibida', icono: '◷', clase: 'espera' },
    aplicada: { texto: 'Aplicada', icono: '✓', clase: 'ok' },
    fallida: { texto: 'Falló', icono: '✕', clase: 'alerta' },
    vencida: { texto: 'Vencida', icono: '■', clase: 'neutro' },
    levantada: { texto: 'Levantada', icono: '↥', clase: 'neutro' },
    rechazada: { texto: 'Rechazada', icono: '✕', clase: 'alerta' },
    espera_ratificacion: { texto: 'Espera ratificación', icono: '⏸', clase: 'espera' },
    // Ola C (parte 6): firmada en los últimos segundos; nunca salió (como el acta).
    no_enviada: { texto: 'No enviada', icono: '○', clase: 'neutro' },
    sin_confirmar: { texto: 'Sin confirmar', icono: '?', clase: 'neutro' },
  };
  /* g-despacho-1: tres causas distintas de una orden que no llegó a bloquear (las mismas del acta). */
  MP.CAUSAS_NO_ENVIADA = {
    turno: { rotulo: 'No enviada', texto: 'Sin bloquear: el juez entrante no recibió el turno.' },
    confirmar: { rotulo: 'Sin confirmar', texto: 'Sin confirmar: se envió y, al cierre, el proveedor no la tenía.' },
    final: { rotulo: 'No enviada', texto: 'Sin bloquear: la firma llegó cuando el partido terminaba.' },
  };
  /* La orden quedó sin salir: el motor la marca `no_enviada` y sigue en por_enviar o en espera del entrante. */
  MP.noEnviada = (o) => !!(o && o.no_enviada && ['por_enviar', 'espera_ratificacion'].includes(o.estado));
  /* Todas las órdenes de la lista quedaron sin salir y ninguna se aplicó: nunca hubo bloqueo. */
  MP.causaNoEnviada = function (o) {
    if (!MP.noEnviada(o)) return null;
    const k = o.estado === 'espera_ratificacion' ? 'turno' : (o.enviada_min !== null && o.enviada_min !== undefined) ? 'confirmar' : 'final';
    return Object.assign({ clave: k }, MP.CAUSAS_NO_ENVIADA[k]);
  };
  /* Para una ubicación cuyas órdenes nunca salieron: la causa común o, si son varias, una frase general. */
  MP.causaNuncaSalio = function (ordenes) {
    const cs = new Map((ordenes || []).map(MP.causaNoEnviada).filter(Boolean).map((c) => [c.clave, c]));
    if (cs.size === 1) return [...cs.values()][0];
    return { clave: 'varias', rotulo: 'Sin bloquear', texto: 'Sin bloquear: ninguna de sus órdenes llegó a aplicarse.' };
  };
  MP.nuncaSalio = (ordenes) => !!(ordenes && ordenes.length && ordenes.every((o) => MP.noEnviada(o) && (o.aplicada_min === null || o.aplicada_min === undefined)));
  MP.estadoOrden = function (estado) {
    const e = MP.ESTADO_ORDEN[estado] || { texto: MP.capital(estado), icono: '·', clase: 'neutro' };
    return MP.el('span', { class: ['estado', 'estado--' + e.clase] }, MP.el('span', { attrs: { 'aria-hidden': 'true' }, text: e.icono }), e.texto);
  };

  /* Resume las órdenes de una ubicación por proveedor. Ronda 3 (C12/N20): de cada objetivo manda su ÚLTIMO
     intento (un fallido que después se reintentó bien no es el estado); entre objetivos, el más relevante. */
  MP.porProveedor = function (ordenes) {
    const grupos = new Map();
    for (const o of ordenes || []) {
      if (!grupos.has(o.proveedor)) grupos.set(o.proveedor, []);
      grupos.get(o.proveedor).push(o);
    }
    const res = [];
    for (const [prov, lista] of grupos) {
      const hay = (e) => lista.filter((o) => o.estado === e);
      const fallidas = hay('fallida').length;
      const ultimos = new Map();
      for (const o of lista) ultimos.set(o.tipo + '|' + o.objetivo, o); // la lista viene en orden de creación
      const vivos = [...ultimos.values()];
      let estado = 'ninguna'; let ref = null;
      const orden = [['aplicada'], ['recibida', 'por_enviar'], ['espera_ratificacion'], ['fallida'], ['levantada'], ['vencida'], ['rechazada']];
      for (const grupo of orden) {
        const x = vivos.filter((o) => grupo.includes(o.estado));
        if (x.length) { estado = x[x.length - 1].estado; ref = x[x.length - 1]; break; }
      }
      const reintento = fallidas > 0 && ['recibida', 'por_enviar', 'espera_ratificacion'].includes(estado);
      const demora = ref && ref.aplicada_min !== null && ref.aplicada_min !== undefined && ref.recibida_min !== null && ref.recibida_min !== undefined
        ? ref.aplicada_min - ref.recibida_min : null;
      // Objetivos distintos que este proveedor tiene o tuvo bloqueados (sin repetir los reintentos).
      const objetivos = [];
      for (const o of lista) if (!objetivos.some((x) => x.tipo === o.tipo && x.objetivo === o.objetivo)) objetivos.push({ tipo: o.tipo, objetivo: o.objetivo });
      res.push({ proveedor: prov, nombre: lista[0].proveedor_nombre, estado, ref, fallidas, reintento, demora, objetivos, ordenes: lista });
    }
    return res;
  };

  /* ------------------------------------------------------------------- reloj */
  const reloj = { base: null, t: 0, alTic: [] };
  MP.reloj = reloj;

  MP.ponerReloj = function (r) {
    if (!r) return;
    reloj.base = Object.assign({}, r);
    reloj.t = performance.now();
    tic();
  };
  MP.ajustarMinuto = function (minuto) {
    if (!reloj.base || typeof minuto !== 'number') return;
    const est = MP.minutoAhora();
    // Solo se corrige si la estimación se fue más de un instante: evita saltos visibles.
    if (est === null || Math.abs(est - minuto) > 0.05) {
      const delta = minuto - reloj.base.minuto;
      if (reloj.base.hora) reloj.base.hora = sumarSegundos(reloj.base.hora, delta * 60);
      reloj.base.minuto = minuto;
      reloj.t = performance.now();
    }
  };
  MP.minutoAhora = function () {
    const b = reloj.base;
    if (!b || typeof b.minuto !== 'number') return null;
    const acel = Number(b.acelerar) || 0;
    return b.minuto + ((performance.now() - reloj.t) / 1000) * acel / 60;
  };
  function sumarSegundos(hhmmss, seg) {
    const p = String(hhmmss).split(':').map(Number);
    if (p.length < 2 || p.some((x) => Number.isNaN(x))) return null;
    let s = Math.round(p[0] * 3600 + p[1] * 60 + (p[2] || 0) + seg);
    s = ((s % 86400) + 86400) % 86400;
    const dos = (x) => String(x).padStart(2, '0');
    return dos(Math.floor(s / 3600)) + ':' + dos(Math.floor((s % 3600) / 60)) + ':' + dos(s % 60);
  }
  MP.horaAhora = function () {
    const b = reloj.base;
    if (!b || !b.hora) return null;
    const m = MP.minutoAhora();
    return sumarSegundos(b.hora, (m - b.minuto) * 60);
  };
  /* Ronda 3, C5: la hora de pared de un minuto del partido = hora_inicio + minuto, en segundos enteros
     truncados, igual que `canon.hora_de_partido` del motor (timedelta redondea a microsegundos y strftime
     corta). Sin `hora_inicio` (motor viejo) cae al cálculo anterior, desde el reloj en vivo. */
  MP.horaDeMinutoDesde = function (horaInicio, minuto) {
    const p = String(horaInicio || '').split(':').map(Number);
    if (p.length < 2 || p.some((x) => Number.isNaN(x)) || sinValor(minuto)) return null;
    const micro = Math.round(Number(minuto) * 60 * 1e6);
    let s = p[0] * 3600 + p[1] * 60 + (p[2] || 0) + Math.floor(micro / 1e6);
    s = ((s % 86400) + 86400) % 86400;
    const dos = (x) => String(x).padStart(2, '0');
    return dos(Math.floor(s / 3600)) + ':' + dos(Math.floor((s % 3600) / 60)) + ':' + dos(s % 60);
  };
  MP.horaDeMinuto = function (minuto) {
    const b = reloj.base;
    if (!b || minuto === null || minuto === undefined) return null;
    if (b.hora_inicio) return MP.horaDeMinutoDesde(b.hora_inicio, minuto);
    if (!b.hora) return null;
    return sumarSegundos(b.hora, (minuto - b.minuto) * 60);
  };
  /* «19:45»: el final del partido sale siempre con `fin_hora` del motor; el resto, con horaDeMinuto. */
  MP.horaCorta = function (minuto) {
    const b = reloj.base;
    if (sinValor(minuto)) return null;
    if (b && b.fin_hora && !sinValor(b.fin_min) && Math.abs(Number(minuto) - Number(b.fin_min)) < 1e-9) return String(b.fin_hora).slice(0, 5);
    const h = MP.horaDeMinuto(minuto);
    return h ? h.slice(0, 5) : null;
  };
  MP.alTic = function (fn) { reloj.alTic.push(fn); };
  function tic() {
    const m = MP.minutoAhora();
    for (const fn of reloj.alTic) { try { fn(m); } catch (e) { console.error(e); } }
  }
  setInterval(tic, 250);

  /* --------------------------------------------------------------------- API */
  class ErrorApi extends Error {
    constructor(estado, codigo, texto) { super(texto); this.estado = estado; this.codigo = codigo; this.texto = texto; }
  }
  MP.ErrorApi = ErrorApi;

  MP.api = async function (metodo, ruta, cuerpo, senal) {
    const op = { method: metodo, credentials: 'same-origin', cache: 'no-store', headers: { Accept: 'application/json' }, signal: senal };
    if (metodo !== 'GET') {
      op.headers['Content-Type'] = 'application/json';
      op.body = JSON.stringify(cuerpo || {});
    }
    let r;
    try {
      r = await fetch(ruta, op);
    } catch (e) {
      if (e && e.name === 'AbortError') throw e;
      throw new ErrorApi(0, 'sin_conexion', 'Sin conexión con la plataforma.');
    }
    let datos = null;
    try { datos = await r.json(); } catch (e) { datos = null; }
    if (!r.ok) {
      throw new ErrorApi(r.status, (datos && datos.codigo) || 'error', (datos && datos.error) || ('La plataforma respondió con un error (' + r.status + ').'));
    }
    return datos;
  };

  /* ------------------------------------------------- conexión y avisos flotantes */
  let cartelConexion = null;
  MP.conexion = function (ok) {
    if (!cartelConexion) {
      cartelConexion = MP.el('div', { class: 'conexion', attrs: { role: 'status', 'aria-live': 'assertive' }, hidden: true },
        'Sin conexión con la plataforma. Reintentando cada 2 segundos…');
      document.body.appendChild(cartelConexion);
    }
    cartelConexion.hidden = !!ok;
    document.documentElement.classList.toggle('sin-conexion', !ok);
  };

  let flotantes = null;
  MP.avisar = function (texto, tipo, segundos) {
    if (!flotantes) {
      flotantes = MP.el('div', { class: 'flotantes', attrs: { 'aria-live': 'polite', role: 'status' } });
      document.body.appendChild(flotantes);
    }
    // Debajo de lo que queda fijo arriba (el reloj del juez): nunca lo tapa. No captura toques.
    const fijo = document.querySelector('[data-fijo-arriba]');
    const abajo = fijo ? fijo.getBoundingClientRect().bottom : 0;
    flotantes.style.setProperty('--arriba', Math.max(12, Math.round(abajo) + 8) + 'px');
    const n = MP.el('div', { class: ['flotante', tipo && 'flotante--' + tipo] }, texto);
    flotantes.appendChild(n);
    setTimeout(() => n.remove(), (segundos || 5) * 1000);
  };

  /* -------------------------------------------------- vigilancia de cambios
     Pide el dato de la pantalla y se queda en /api/cambios?v=<v>. Cuando la versión
     cambia, vuelve a pedir. Si falla, reintenta cada 2 s con el cartel visible. */
  MP.vigilar = function (opc) {
    let v = null;
    let activo = true;
    let ctrl = null;
    let despertar = null;
    const esperar = (ms) => new Promise((res) => { const t = setTimeout(res, ms); despertar = () => { clearTimeout(t); res(); }; });

    async function bucle() {
      while (activo) {
        try {
          if (v === null) {
            const datos = await opc.cargar();
            if (!activo) return;
            v = datos && typeof datos.v === 'number' ? datos.v : 0;
            MP.conexion(true);
          }
          ctrl = new AbortController();
          // C17: solo la bandeja del juez pasa `de: 'juez'` (marca presencia); las páginas públicas no lo mandan.
          const de = opc.de ? '&de=' + encodeURIComponent(opc.de) : '';
          const c = await MP.api('GET', '/api/cambios?v=' + encodeURIComponent(v) + de, undefined, ctrl.signal);
          ctrl = null;
          MP.conexion(true);
          if (c && typeof c.minuto === 'number') MP.ajustarMinuto(c.minuto);
          if (c && c.v !== v) v = null;
        } catch (e) {
          ctrl = null;
          if (!activo) return;
          if (e && e.name === 'AbortError') continue; // adoptar() o refrescar() ya dejaron v como corresponde
          if (e instanceof ErrorApi && ['no_autenticado', 'sin_permiso'].includes(e.codigo)) {
            activo = false;
            if (opc.alPerderSesion) opc.alPerderSesion(e);
            return;
          }
          MP.conexion(false);
          v = null;
          await esperar(2000);
        }
      }
    }
    bucle();
    return {
      /* Tras una acción que ya devolvió el dato nuevo: se adopta su versión. */
      adoptar(nuevaV) { if (typeof nuevaV === 'number') v = nuevaV; if (ctrl) ctrl.abort(); },
      refrescar() { v = null; if (ctrl) ctrl.abort(); if (despertar) despertar(); },
      detener() { activo = false; if (ctrl) ctrl.abort(); if (despertar) despertar(); },
    };
  };

  /* ------------------------------------------------------- formulario de ingreso */
  MP.formIngreso = function (opc) {
    const error = MP.el('p', { class: 'error-campo', attrs: { role: 'alert' }, hidden: true });
    const usuario = MP.el('input', { class: 'entrada', id: 'ingreso-usuario', name: 'usuario', type: 'text', required: true,
      attrs: { autocomplete: 'username', autocapitalize: 'none', spellcheck: 'false' } });
    const clave = MP.el('input', { class: 'entrada', id: 'ingreso-clave', name: 'clave', type: 'password', required: true,
      attrs: { autocomplete: 'current-password' } });
    const boton = MP.el('button', { class: 'boton boton--principal boton--ancho', type: 'submit' }, 'Ingresar');
    const form = MP.el('form', { class: 'ingreso__form', attrs: { novalidate: true } },
      MP.el('div', { class: 'campo' }, MP.el('label', { htmlFor: 'ingreso-usuario', class: 'rotulo', text: 'Usuario' }), usuario),
      MP.el('div', { class: 'campo' }, MP.el('label', { htmlFor: 'ingreso-clave', class: 'rotulo', text: 'Contraseña' }), clave),
      error, boton);
    form.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      error.hidden = true;
      if (!usuario.value.trim() || !clave.value) {
        MP.poner(error, 'Escriba el usuario y la contraseña.');
        error.hidden = false;
        return;
      }
      boton.disabled = true;
      MP.poner(boton, 'Ingresando…');
      try {
        const yo = await MP.api('POST', '/api/login', { usuario: usuario.value.trim(), clave: clave.value });
        clave.value = '';
        opc.alIngresar(yo);
      } catch (e) {
        MP.poner(error, e.texto || 'No se pudo ingresar.');
        error.hidden = false;
        clave.select();
      } finally {
        boton.disabled = false;
        MP.poner(boton, 'Ingresar');
      }
    });
    setTimeout(() => usuario.focus(), 50);
    return form;
  };

  MP.salir = async function () {
    try { await MP.api('POST', '/api/logout', {}); } catch (e) { /* la sesión ya no existe */ }
    location.reload();
  };
})();
