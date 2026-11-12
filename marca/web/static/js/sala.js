/* Marca Personal — sala de situación (fiscalía; pensada para proyector).
   La pizarra táctica: una pista por expediente. La filtración se muda de
   servidor en servidor y la marca la sigue; en cada ubicación, un punto por
   proveedor que se enciende cuando aplica el bloqueo. */
'use strict';

(function () {
  const { el } = MP;
  const app = MP.$('#app');
  const est = { sala: null, vig: null, lamparas: null, auditoriaVista: null };
  const z = {};

  async function arrancar() {
    try {
      const yo = await MP.api('GET', '/api/yo');
      entrar(yo);
    } catch (e) {
      if (e.codigo === 'no_autenticado') return mostrarIngreso();
      MP.conexion(false);
      setTimeout(arrancar, 2000);
    }
  }

  function mostrarIngreso(mensaje) {
    if (est.vig) est.vig.detener();
    est.vig = null;
    MP.poner(app, el('main', { class: 'sala-ingreso' },
      el('div', { class: 'sala-ingreso__caja' },
        el('div', { class: 'logo' }, MP.logo(), el('span', { class: 'logo__texto', text: 'Marca Personal' })),
        el('h1', { class: 'sala-ingreso__titulo', text: 'Sala de situación' }),
        el('p', { class: 'sala-ingreso__bajada', text: 'Acceso de la fiscalía. La pantalla se actualiza sola durante el partido.' }),
        mensaje ? el('p', { class: 'error-campo', attrs: { role: 'alert' }, text: mensaje }) : null,
        MP.formIngreso({ alIngresar: entrar }))));
  }

  function entrar(yo) {
    if (yo.rol !== 'fiscalia') {
      MP.poner(app, el('main', { class: 'sala-ingreso' }, el('div', { class: 'sala-ingreso__caja' },
        el('h1', { class: 'sala-ingreso__titulo', text: 'Esta sala es para la fiscalía' }),
        el('p', { class: 'sala-ingreso__bajada', text: 'Su usuario es de juez: su bandeja está en /juez.' }),
        el('div', { class: 'fila-botones' },
          el('a', { class: 'boton boton--principal', href: '/juez', text: 'Ir a la bandeja' }),
          el('button', { class: 'boton', type: 'button', on: { click: MP.salir } }, 'Salir')))));
      return;
    }
    MP.ponerReloj(yo.reloj);
    esqueleto();
    est.vig = MP.vigilar({
      cargar: async () => { const s = await MP.api('GET', '/api/sala'); pintar(s); return s; },
      alPerderSesion: (e) => mostrarIngreso(e.codigo === 'no_autenticado' ? 'La sesión terminó. Vuelva a ingresar.' : e.texto),
    });
  }

  /* ============================================================ esqueleto */
  const panel = (titulo, cuerpo, clase) => el('section', { class: ['panel', clase] }, el('h2', { class: 'panel__titulo rotulo', text: titulo }), cuerpo);

  function esqueleto() {
    z.min = el('span', { class: 'marcador__min num', text: '—' });
    z.rot = el('span', { class: 'marcador__rot', text: 'min' });
    z.hora = el('span', { class: 'marcador__hora num' });
    z.fase = el('span', { class: 'marcador__fase rotulo' });
    z.barra = el('div', { class: 'linea-tiempo', attrs: { 'aria-hidden': 'true' } });
    z.partido = el('div', { class: 'marcador__partido' });
    z.turno = el('div', { class: 'marcador__turno' });
    z.conexion = el('p', { class: 'marcador__conexion', attrs: { role: 'status' } });
    z.kpis = el('section', { class: 'indicadores', attrs: { 'aria-label': 'Indicadores' } });
    z.pistas = el('div', { class: 'pistas__lista' });
    z.pistasCab = el('p', { class: 'pistas__resumen' });
    z.proveedores = el('div', { class: 'panel__cuerpo' });
    z.reclamos = el('div', { class: 'panel__cuerpo' });
    z.descartes = el('div', { class: 'panel__cuerpo' });
    z.avisos = el('div', { class: 'panel__cuerpo' });
    z.jueces = el('div', { class: 'panel__cuerpo' });
    z.panelJueces = panel('Jueces y orden marco', z.jueces, 'panel--jueces');
    z.panelJueces.hidden = true;
    z.cabeza = el('p', { class: 'auditoria__cabeza' });
    z.auditoria = el('ol', { class: 'auditoria__lista' });


    MP.poner(app,
      el('header', { class: 'marcador' },
        el('div', { class: 'marcador__marca' },
          el('a', { class: 'logo', href: '/', attrs: { 'aria-label': 'Marca Personal, portada' } }, MP.logo(), el('span', { class: 'logo__texto', text: 'Marca Personal' })),
          el('span', { class: 'marcador__pantalla', text: 'Sala de situación' })),
        z.partido,
        el('div', { class: 'marcador__reloj', attrs: { 'aria-label': 'Reloj del partido' } },
          z.fase, el('div', { class: 'marcador__cifras' }, z.rot, z.min), z.hora, z.barra),
        z.turno,
        el('div', { class: 'marcador__lado' }, z.conexion,
          el('button', { class: 'boton boton--chico marcador__salir', type: 'button', on: { click: MP.salir } }, 'Salir'))),
      z.kpis,
      el('div', { class: 'tablero-sala' },
        el('main', { class: 'pistas', attrs: { 'aria-labelledby': 'tit-pistas' } },
          el('div', { class: 'pistas__cab' },
            el('h2', { class: 'pistas__titulo', id: 'tit-pistas' }, 'Marca personal', el('span', { text: ' · cada filtración, seguida de servidor en servidor' })),
            z.pistasCab),
          leyenda(),
          z.pistas,
          el('section', { class: 'auditoria', attrs: { 'aria-labelledby': 'tit-aud' } },
            el('h2', { class: 'panel__titulo rotulo', id: 'tit-aud', text: 'Auditoría en vivo' }), z.cabeza, z.auditoria)),
        el('aside', { class: 'lateral' },
          z.panelJueces,
          panel('Proveedores', z.proveedores, 'panel--proveedores'),
          panel('Reclamos y traspasos', z.reclamos, 'panel--reclamos'),
          panel('Avisos', z.avisos, 'panel--avisos'),
          panel('Descartes', z.descartes, 'panel--descartes'))));
    MP.alTic(ticReloj);
  }

  function leyenda() {
    const item = (clase, texto) => el('li', {}, el('span', { class: 'lampara lampara--' + clase, attrs: { 'aria-hidden': 'true' } }), texto);
    return el('ul', { class: 'leyenda', attrs: { 'aria-label': 'Referencias' } },
      item('aplicada', 'Bloqueo aplicado'), item('recibida', 'Enviado, esperando al proveedor'),
      item('espera', 'En espera del juez entrante'), item('no_enviada', 'No enviada o sin confirmar'),
      item('fallida', 'Falló (se reintenta)'), item('ninguna', 'Sin orden'), item('vencida', 'Vencido o levantado'));
  }

  function ticReloj(m) {
    const s = est.sala;
    if (m === null || !s) return;
    const r = s.reloj;
    const fin = r.fin_min;
    const mm = Math.min(m, fin + 5);
    // N4: antes del inicio se dice cuánto falta («Todavía no empezó (faltan 3,3 min)»), nunca «min -3,3».
    z.rot.textContent = mm < 0 ? 'faltan' : 'min';
    z.min.textContent = MP.minTxt(mm < 0 ? Math.min(-mm, 99) : mm);
    const h = MP.horaAhora();
    z.hora.textContent = h || '';
    z.fase.textContent = mm >= fin + 5 ? 'Cierre verificado' : mm >= fin ? 'Final del partido' : mm < 0 ? MP.antesDelInicio(mm) : 'En juego';
    z.barra.style.setProperty('--avance', Math.max(0, Math.min(100, (mm / fin) * 100)).toFixed(2) + '%');
  }

  /* =============================================================== pintar */
  function pintar(s) {
    est.sala = s;
    MP.ponerReloj(s.reloj);
    const r = s.reloj;
    document.title = 'Sala · ' + (r.minuto < 0 ? 'todavía no empezó' : MP.min(r.minuto)) + ' — Marca Personal';

    MP.poner(z.partido,
      el('span', { class: 'rotulo', text: (r.partido && r.partido.titular) || '' }),
      el('strong', { class: 'marcador__nombre', text: (r.partido && r.partido.nombre) || '' }));

    const turnos = (r.de_turno || []);
    const cortes = new Set();
    for (const t of turnos) { if (t.hasta_min < r.fin_min) cortes.add(t.hasta_min); }
    for (const t of s.traspasos || []) cortes.add(t.min);
    MP.poner(z.barra, el('span', { class: 'linea-tiempo__avance' }),
      [45, 90].map((x) => el('span', { class: 'linea-tiempo__marca', style: { '--en': (x / r.fin_min * 100) + '%' } })),
      [...cortes].map((x) => el('span', { class: 'linea-tiempo__turno', style: { '--en': (x / r.fin_min * 100) + '%' } })));
    MP.poner(z.turno,
      el('span', { class: 'rotulo', text: 'De turno' }),
      turnos.length ? turnos.map((t) => [el('strong', { class: 'marcador__juez', text: t.nombre }),
        el('span', { class: 'marcador__juzgado', text: MP.sinParentesis(t.juzgado || '') + ' · ' + MP.hastaTurno(t.hasta_min, r.fin_min) })])
        : el('strong', { class: 'marcador__juez marcador__juez--nadie', text: 'Nadie de turno' }));
    const ok = r.conexion === 'ok';
    z.conexion.className = 'marcador__conexion ' + (ok ? 'marcador__conexion--ok' : 'marcador__conexion--mal');
    z.conexion.textContent = ok ? 'Simulador conectado' : 'Sin conexión con el simulador';

    pintarKpis(s);
    pintarPistas(s);
    pintarJueces(s);
    pintarProveedores(s);
    pintarReclamos(s);
    pintarAvisos(s);
    pintarDescartes(s);
    pintarAuditoria(s);
    ticReloj(MP.minutoAhora());
  }

  function kpi(clase, rotulo, valor, unidad, pie, icono) {
    return el('div', { class: ['kpi', clase && 'kpi--' + clase] },
      el('span', { class: 'kpi__rotulo rotulo', text: rotulo }),
      el('span', { class: 'kpi__valor num' }, icono ? el('span', { class: 'kpi__icono', attrs: { 'aria-hidden': 'true' }, text: icono }) : null,
        valor, unidad ? el('span', { class: 'kpi__unidad', text: unidad }) : null),
      pie ? el('span', { class: 'kpi__pie', text: pie }) : null);
  }

  /* Daño colateral: grande, lo que sigue bloqueando a sitios ajenos ahora; chico, el total del partido y lo levantado. */
  function kpiDano(s, k) {
    const total = k.ordenes_con_dano_colateral || 0;
    let levantadas = 0;
    for (const e of s.expedientes || []) for (const u of e.ubicaciones || []) for (const o of u.ordenes || []) {
      if (o.estado === 'levantada' && ((o.levantamiento && o.levantamiento.reclamo) || /Reclamo R-/.test(o.motivo || ''))) levantadas++;
    }
    let vigentes = k.ordenes_con_dano_colateral_vigentes;
    // Sin el dato del motor: aproximación (al final del partido no queda ninguna vigente).
    if (vigentes === undefined || vigentes === null) vigentes = s.reloj && s.reloj.finalizado ? 0 : Math.max(0, total - levantadas);
    const detalle = total ? MP.plural(total, 'orden', 'órdenes') + ' en el partido' + (levantadas ? ' · ' + MP.plural(levantadas, 'levantada', 'levantadas') + ' por reclamo' : '') : null;
    if (vigentes > 0) {
      return kpi('alerta', 'Daño colateral', MP.num(vigentes, 0), vigentes === 1 ? 'orden' : 'órdenes',
        (vigentes === 1 ? 'deja' : 'dejan') + ' sitios ajenos bloqueados ahora' + (detalle && total !== vigentes ? ' · ' + detalle : ''), '!');
    }
    if (total > 0) {
      return kpi('espera', 'Daño colateral', '0', 'vigentes',
        (total === 1 ? 'Una orden dejó' : MP.num(total, 0) + ' órdenes dejaron') + ' sitios ajenos bloqueados' +
        (levantadas ? '; ' + (levantadas === 1 ? 'se levantó' : 'se levantaron') + ' por reclamo' : '; ya no están vigentes'), '✓');
    }
    return kpi('ok', 'Daño colateral', '0', 'órdenes', 'ningún sitio ajeno quedó bloqueado', '✓');
  }

  function pintarKpis(s) {
    const k = s.kpis || {};
    const cubiertos = k.clientes_cubiertos_pct;
    const ubTot = (s.expedientes || []).reduce((a, e) => a + (e.ubicaciones || []).length, 0);
    MP.poner(z.kpis,
      kpi(cubiertos === null || cubiertos === undefined ? null : cubiertos >= 99.5 ? 'ok' : 'espera', 'Clientes cubiertos',
        cubiertos === null || cubiertos === undefined ? '—' : MP.num(cubiertos, 1), cubiertos === null || cubiertos === undefined ? '' : '%',
        'de ' + MP.clientes(k.clientes_total) + ' de clientes, en las ubicaciones firmadas'),
      kpi(null, 'Primer bloqueo', MP.minTxt(k.primer_bloqueo_promedio_min),
        k.primer_bloqueo_promedio_min === null || k.primer_bloqueo_promedio_min === undefined ? '' : 'min', 'promedio desde que aparece cada servidor'),
      kpi(null, 'Visibilidad residual', k.visibilidad_residual_promedio_pct === null || k.visibilidad_residual_promedio_pct === undefined ? '—' : MP.num(k.visibilidad_residual_promedio_pct, 1),
        k.visibilidad_residual_promedio_pct === null || k.visibilidad_residual_promedio_pct === undefined ? '' : '%', 'de los clientes que lo pudieron ver, en promedio'),
      kpiDano(s, k),
      kpi(k.reclamos_pendientes ? 'alerta' : null, 'Reclamos', MP.num(k.reclamos_pendientes || 0, 0), k.reclamos_pendientes === 1 ? 'pendiente' : 'pendientes',
        MP.plural(k.reclamos_resueltos, 'resuelto', 'resueltos')),
      // C12 (N20): «6 de 7 · 1 levantada» cuando alguna se levantó.
      kpi(k.ubicaciones_pendientes ? 'espera' : null, 'Ubicaciones bloqueadas', MP.num(k.ubicaciones_bloqueadas || 0, 0),
        'de ' + ubTot + (Number(k.ubicaciones_levantadas) > 0 ? ' · ' + MP.plural(k.ubicaciones_levantadas, 'levantada', 'levantadas') : ''),
        (k.ubicaciones_pendientes ? MP.plural(k.ubicaciones_pendientes, 'espera', 'esperan') + ' firma · ' : '') + MP.plural(k.expedientes, 'expediente', 'expedientes')));
  }

  /* ================================================================ pistas */
  function estadoLampara(p) {
    if (!p) return 'ninguna';
    // Ola C (parte 6): firmada en los últimos segundos, nunca salió: ni «enviado» ni «en espera».
    if (MP.noEnviada(p.ref) && (p.ordenes || [p.ref]).every((o) => o.estado !== 'aplicada')) return 'no_enviada';
    if (p.estado === 'aplicada') return 'aplicada';
    if (p.reintento) return 'reintento';
    // Ola C (7): en espera del juez entrante todavía no salió: no es «enviado».
    if (p.estado === 'espera_ratificacion') return 'espera';
    if (['recibida', 'por_enviar'].includes(p.estado)) return 'recibida';
    if (p.estado === 'fallida' || p.estado === 'rechazada') return 'fallida';
    if (p.estado === 'levantada') return 'levantada';
    if (p.estado === 'vencida') return 'vencida';
    return 'ninguna';
  }
  /* g-despacho-1: la lámpara apagada dice por qué no bloqueó (cada causa, como el acta). */
  function textoLampara(st, p) {
    if (st === 'no_enviada') { const c = MP.causaNoEnviada(p && p.ref); if (c) return c.texto; }
    return TEXTO_LAMPARA[st];
  }
  const TEXTO_LAMPARA = {
    aplicada: 'aplicado', recibida: 'enviado', espera: 'En espera: sale cuando el juez entrante reciba el turno.', no_enviada: 'No enviada', reintento: 'reintentando', fallida: 'falló', levantada: 'levantado', vencida: 'vencido', ninguna: 'sin orden',
  };

  function pintarPistas(s) {
    const exps = (s.expedientes || []).slice().sort((a, b) => a.num - b.num);
    const nuevas = new Map();
    const k = s.kpis || {};
    z.pistasCab.textContent = MP.plural(k.expedientes || exps.length, 'filtración', 'filtraciones') + ' · ' +
      MP.plural((s.descartes || []).length, 'descarte', 'descartes');
    if (!exps.length) {
      MP.poner(z.pistas, el('p', { class: 'pistas__vacio', text: 'Todavía no hay filtraciones detectadas. La sala se actualiza sola.' }));
      est.lamparas = nuevas;
      return;
    }
    MP.poner(z.pistas, exps.map((e) => pista(e, s, nuevas)));
    est.lamparas = nuevas;
  }

  function pista(e, s, nuevas) {
    const d = e.dinamica;
    let din = null;
    if (d) {
      const resp = d.revocada ? null : (d.ratificaciones && d.ratificaciones.length ? d.ratificaciones[d.ratificaciones.length - 1].nombre : (d.otorgada_por || {}).nombre);
      const fin = !!(s.reloj && s.reloj.finalizado);
      if (d.revocada) din = el('span', { class: 'pista__dinamica pista__dinamica--revocada', text: 'Seguimiento frenado' });
      else if (d.requiere_ratificacion) din = el('span', { class: 'pista__dinamica pista__dinamica--' + (fin ? 'revocada' : 'espera'),
        text: fin ? 'Seguimiento sin ratificar: terminó con el partido' : 'Seguimiento · espera ratificación' });
      else if (d.activa && fin) din = el('span', { class: 'pista__dinamica pista__dinamica--revocada', text: 'Seguimiento · terminó con el partido' });
      else if (d.activa) din = el('span', { class: 'pista__dinamica' }, el('span', { class: 'pista__dinamica-icono', attrs: { 'aria-hidden': 'true' }, text: '↻' }),
        'Seguimiento · la sigue adonde vaya' + (resp ? ' · ' + resp : ''));
    }
    const ubs = (e.ubicaciones || []).slice().sort((a, b) => a.n - b.n);
    const recorrido = el('ol', { class: 'pista__recorrido' });
    ubs.forEach((u, i) => {
      if (i > 0) recorrido.append(tramo(ubs[i - 1], u));
      recorrido.append(estacion(e, u, i === ubs.length - 1, s, nuevas));
    });
    let estadoExp = { pendiente: ['espera', 'Espera firma'], activo: ['ok', 'Bloqueado'], rechazado: ['alerta', 'Rechazado'], cerrado: ['neutro', 'Cerrado'] }[e.estado] || ['neutro', e.estado];
    // C12 (N20): si nada sigue activo, el chip dice cómo terminó: levantado o vencido con el partido.
    if (e.estado === 'activo' || e.estado === 'cerrado') {
      const fin = MP.finDeBloqueo([].concat(...ubs.filter((u) => u.estado === 'aprobada').map((u) => u.ordenes || [])),
        !!(s.reloj && s.reloj.finalizado));
      const aprob = ubs.filter((u) => u.estado === 'aprobada');
      if (aprob.length && aprob.every((u) => MP.nuncaSalio(u.ordenes))) {
        estadoExp = ['neutro', MP.causaNuncaSalio([].concat(...aprob.map((u) => u.ordenes))).rotulo === 'Sin confirmar' ? 'Sin confirmar' : 'Sin bloquear'];
      }
      else if (fin === 'levantada') estadoExp = ['neutro', 'Levantado'];
      else if (fin === 'vencida') estadoExp = ['neutro', 'Venció con el partido'];
    }
    return el('article', { class: ['pista', 'pista--' + e.estado], attrs: { 'aria-label': 'Expediente ' + e.id } },
      el('header', { class: 'pista__cab' },
        el('span', { class: 'pista__exp mono', text: e.id }),
        el('h3', { class: 'pista__titulo', text: e.titulo }),
        e.filtracion && e.filtracion.sesion ? el('span', { class: 'pista__sesion mono', text: 'sesión ' + e.filtracion.sesion }) : null,
        din,
        el('span', { class: 'estado estado--' + estadoExp[0], text: estadoExp[1] })),
      recorrido);
  }

  function tramo(antes, u) {
    const d = u.decision || {};
    const c = MP.cobertura(u.cobertura);
    const auto = d.tipo === 'ampliacion_dinamica';
    let abajo = null;
    if (u.estado === 'sin_decidir') abajo = el('span', { class: 'tramo__seguida', text: 'sin decidir' });
    else if (u.estado === 'pendiente') abajo = el('span', { class: 'tramo__seguida tramo__seguida--espera', text: 'espera la firma' });
    else if (u.estado === 'rechazada') abajo = el('span', { class: 'tramo__seguida tramo__seguida--alerta', text: 'rechazada' });
    else if (c.primer !== null) {
      abajo = el('span', { class: 'tramo__seguida' }, (auto ? 'la siguió sola · ' : 'firmada · ') + 'bloqueo a ' + MP.dur(c.primer));
    } else if (auto) abajo = el('span', { class: 'tramo__seguida', text: 'la siguió sola' });
    // C4 (N14): el mismo servidor que vuelve después de «frenar y levantar» no es una mudanza.
    const mismo = !!u.reabierta || (u.continuidad && u.continuidad.criterio === 'mismo_servidor') ||
      (antes.host === u.host && antes.ip === u.ip);
    return el('li', { class: ['tramo', auto && 'tramo--auto'],
      attrs: { 'aria-label': mismo ? u.host + ' volvió a transmitir' : 'Se mudó de ' + antes.host + ' a ' + u.host } },
      el('span', { class: 'tramo__arriba', text: (mismo ? 'volvió a transmitir · ' : 'se mudó · ') + MP.min(u.primera_deteccion_min) }),
      el('span', { class: 'tramo__linea', attrs: { 'aria-hidden': 'true' } }),
      abajo);
  }

  function estacion(e, u, ultima, s, nuevas) {
    const c = MP.cobertura(u.cobertura);
    const d = u.decision || {};
    const provs = MP.porProveedor(u.ordenes);
    const porId = new Map(provs.map((p) => [p.proveedor, p]));
    const algunaActiva = (u.ordenes || []).some((o) => !MP.noEnviada(o) && ['aplicada', 'recibida', 'por_enviar', 'espera_ratificacion'].includes(o.estado));
    let estadoNodo = u.estado === 'pendiente' ? 'pendiente' : u.estado === 'rechazada' ? 'rechazada' : algunaActiva ? 'marcada' : 'cerrada';
    let decision;
    if (u.estado === 'sin_decidir') decision = el('span', { class: 'estacion__decision' }, el('span', { class: 'tarjeta tarjeta--gris', text: 'Sin decidir' }), ' ' + (u.motivo_sin_decidir || 'El partido terminó antes de la firma.'));
    else if (u.estado === 'pendiente') decision = el('span', { class: 'tarjeta tarjeta--amarilla', text: 'Espera firma' });
    else if (u.estado === 'rechazada') decision = el('span', { class: 'tarjeta tarjeta--roja', text: 'Rechazada' });
    else if (d.tipo === 'ampliacion_dinamica') decision = el('span', { class: 'estacion__decision estacion__decision--auto', text: MP.textoAmpliacion(d) });
    else decision = el('span', { class: 'estacion__decision', text: 'Firmada · ' + MP.min(d.min) + (d.forzado ? ' · por ' + MP.tipoBloqueo(d.forzado.tipo) : '') });
    // C4/C12: una ubicación cuyo bloqueo terminó lo dice (no queda «Bloqueado»).
    const finU = u.estado === 'aprobada' ? MP.finDeBloqueo(u.ordenes, !!(s.reloj && s.reloj.finalizado)) : null;
    // Ola C (parte 6): si ninguna orden salió, nunca hubo bloqueo: ni «Bloqueado» ni «Venció con el partido».
    const sinBloquear = u.estado === 'aprobada' && MP.nuncaSalio(u.ordenes);
    const rotuloFin = sinBloquear ? el('span', { class: 'tarjeta tarjeta--gris estacion__fin', text: MP.causaNuncaSalio(u.ordenes).texto })
      : finU ? el('span', { class: 'tarjeta tarjeta--gris estacion__fin', text: finU === 'levantada' ? 'Levantado' : 'Venció con el partido' }) : null;

    const lamparas = el('ul', { class: 'lamparas', attrs: { 'aria-label': 'Estado por proveedor' } }, (s.proveedores || []).map((pv) => {
      const p = porId.get(pv.id);
      const st = estadoLampara(p);
      const clave = u.ref + '|' + pv.id;
      nuevas.set(clave, st);
      const antes = est.lamparas ? est.lamparas.get(clave) : st;
      const recien = est.lamparas !== null && antes !== st && st === 'aplicada';
      let dato = '';
      if (p && st === 'aplicada' && p.demora !== null) dato = MP.minTxt(p.demora) + '′';
      else if (st === 'reintento') dato = '↻ ' + (p.fallidas + 1);
      else if (st === 'recibida' && p && p.ref && p.ref.recibida_min !== null && p.ref.recibida_min !== undefined) dato = '…';
      return el('li', { class: ['lamparas__item', recien && 'lamparas__item--recien'], attrs: { title: (pv.nombre || pv.id) + ': ' + textoLampara(st, p) } },
        el('span', { class: 'lampara lampara--' + st, attrs: { 'aria-hidden': 'true' } }),
        el('span', { class: 'lamparas__nombre', text: MP.capital(pv.id) }),
        el('span', { class: 'lamparas__dato num', text: dato }),
        el('span', { class: 'solo-lectores', text: textoLampara(st, p) }));
    }));

    const pct = c.cubiertos || 0;
    const nodo = el('div', { class: 'estacion__nodo', style: { '--cob': pct + '%' }, attrs: { 'aria-hidden': 'true' } },
      el('span', { class: 'estacion__anillo' }),
      el('span', { class: ['estacion__jugador', ultima && 'estacion__jugador--aca'] }),
      u.estado === 'rechazada' ? el('span', { class: 'estacion__cruz', text: '✕' }) : null);

    const ciclo = cicloReclamo(u);
    return el('li', { class: ['estacion', 'estacion--' + estadoNodo, ultima && 'estacion--actual'] },
      el('div', { class: 'estacion__arriba' }, nodo,
        el('div', { class: 'estacion__id' },
          el('span', { class: 'estacion__u', text: 'Ubicación ' + u.n }),
          el('strong', { class: 'estacion__host mono', text: u.host }),
          el('span', { class: 'estacion__ip mono', text: u.ip + ' · AS' + u.asn }))),
      decision,
      rotuloFin,
      lamparas,
      ciclo,
      u.estado === 'aprobada' ? el('p', { class: 'estacion__cob' },
        el('strong', { class: 'num', text: MP.pct(c.cubiertos) }), ' cubiertos',
        c.sinVentana ? ' · primer bloqueo — · residual — (sin tiempo para medir)'
          : c.residual !== null ? ' · residual ' + MP.pct(c.residual) : '') : null);
  }

  /* Después de un reclamo: «por IP → levantada por reclamo → reemplazo por dominio», en la tira del expediente. */
  function cicloReclamo(u) {
    const ords = u.ordenes || [];
    const reclamoDe = (o) => (o.levantamiento && o.levantamiento.reclamo) || ((/Reclamo (R-\d+)/.exec(o.motivo || '') || [])[1]) || null;
    const levantadas = ords.filter((o) => o.estado === 'levantada' && reclamoDe(o));
    const reemplazos = ords.filter((o) => o.origen === 'reemplazo_reclamo');
    if (!levantadas.length && !reemplazos.length) return null;
    const tipos = [...new Set(levantadas.map((o) => o.tipo))].map(MP.tipoBloqueo).join(' y ') || 'IP';
    const reclamos = [...new Set(levantadas.map(reclamoDe).concat(reemplazos.map((o) => o.reclamo)).filter(Boolean))];
    const minLev = levantadas.length ? Math.min(...levantadas.map((o) => (o.levantamiento && o.levantamiento.min) || o.finalizada_min || 0)) : null;
    const paso = (txt, clase) => el('li', { class: ['ciclo__paso', clase && 'ciclo__paso--' + clase], text: txt });
    return el('ol', { class: 'ciclo', attrs: { 'aria-label': 'Ciclo del bloqueo después del reclamo' } },
      paso('Por ' + tipos, 'antes'),
      paso('Levantada por reclamo' + (reclamos.length ? ' ' + reclamos.join(', ') : '') + (minLev !== null ? ' · ' + MP.min(minLev) : ''), 'levantada'),
      reemplazos.length ? paso('Reemplazo por dominio', 'reemplazo') : null);
  }

  /* ============================================================== lateral */
  /* Ronda 2b: quién está de turno, si tiene la plataforma abierta (actividad real) y su orden marco. */
  function pintarJueces(s) {
    if (!Array.isArray(s.jueces) && !Array.isArray(s.marcos)) { z.panelJueces.hidden = true; return; }
    z.panelJueces.hidden = false;
    const jueces = (s.jueces || []).slice().sort((a, b) => (b.de_turno - a.de_turno));
    const ahora = MP.minutoAhora() !== null ? MP.minutoAhora() : (s.reloj || {}).minuto;
    const filas = jueces.map((j) => {
      let act;
      const t = turnoDe(s, j);
      // N8: fuera de turno la presencia es ruido («Activo» o «Sin actividad hace N s»): desde cuándo, o cuándo entra.
      if (!j.de_turno && t && t.hasta_min !== null && t.hasta_min !== undefined && ahora !== null && ahora >= t.hasta_min) act = ['neutro', '■', 'Fuera de turno desde el ' + MP.min(t.hasta_min)];
      else if (!j.de_turno && t && t.desde_min !== null && t.desde_min !== undefined && ahora !== null && ahora < t.desde_min) act = ['neutro', '■', 'Entra de turno en el ' + MP.min(t.desde_min)];
      else if (j.activo) act = ['ok', '✓', 'Activo'];
      else act = [j.de_turno ? 'alerta' : 'neutro', j.de_turno ? '!' : '■',
        j.hace_s === null || j.hace_s === undefined ? 'Sin actividad' : 'Sin actividad hace ' + MP.num(j.hace_s, 0) + ' s'];
      return el('li', { class: ['fila-lateral', j.de_turno && !j.activo && 'fila-lateral--accion'] },
        el('div', { class: 'fila-lateral__cab' },
          el('span', { class: 'tarjeta ' + (j.de_turno ? 'tarjeta--verde' : 'tarjeta--gris'), text: j.de_turno ? 'De turno' : 'Fuera de turno' }),
          el('span', { class: 'estado estado--' + act[0] }, el('span', { attrs: { 'aria-hidden': 'true' }, text: act[1] }), act[2])),
        el('p', { class: 'fila-lateral__texto' }, el('strong', { text: j.nombre })),
        el('p', { class: 'fila-lateral__texto', text: j.marco ? 'Orden marco ' + j.marco.id + ' · seguimiento: ' + (j.marco.seguimiento ? 'sí' : 'no') : 'Sin orden marco: firma servidor por servidor.' }));
    });
    const marcos = (s.marcos || []).slice().reverse();
    MP.poner(z.jueces,
      filas.length ? el('ul', { class: 'lista-lateral' }, filas) : null,
      el('h3', { class: 'rotulo sala-marcos__titulo', text: 'Órdenes marco firmadas' }),
      marcos.length ? el('ul', { class: 'lista-lateral' }, marcos.map((m) => {
        // C2 (N12): Vigente / Reemplazada en el min X / Terminó con su turno (min X) / Terminó con el partido (min X).
        const em = MP.estadoMarco(m);
        return el('li', { class: ['fila-lateral', !em.vigente && 'fila-lateral--info'] },
          el('div', { class: 'fila-lateral__cab' },
            el('span', { class: 'mono', text: m.id }),
            el('span', { class: 'estado ' + (em.vigente ? 'estado--ok' : 'estado--neutro') },
              el('span', { attrs: { 'aria-hidden': 'true' }, text: em.vigente ? '✓' : '■' }), em.texto),
            el('span', { class: 'fila-lateral__min num', text: MP.min(m.min) })),
          el('p', { class: 'fila-lateral__texto', text: m.juez + ' · seguimiento: ' + (m.seguimiento ? 'sí' : 'no') }),
          el('p', { class: 'fila-lateral__texto' }, 'Huella ', MP.hash(m.huella)));
      }))
        : el('p', { class: 'panel__vacio', text: 'Ninguna todavía.' }));
  }

  /* El turno de un juez: de `jueces[]` si el motor lo manda; si no, de sus órdenes marco o del cambio de turno. */
  function turnoDe(s, j) {
    if (j.turno && typeof j.turno === 'object') return j.turno;
    if (j.hasta_min !== undefined || j.desde_min !== undefined) return { desde_min: j.desde_min, hasta_min: j.hasta_min };
    const mios = (s.marcos || []).filter((m) => (m.juez_id && m.juez_id === j.juez_id) || (!m.juez_id && m.juez === j.nombre));
    const conTurno = mios.filter((m) => m.turno && (m.turno.hasta_min !== null && m.turno.hasta_min !== undefined));
    if (conTurno.length) return conTurno[conTurno.length - 1].turno;
    const tr = (s.traspasos || []).filter((t) => (t.de || []).some((x) => x.nombre === j.nombre));
    if (tr.length) return { desde_min: null, hasta_min: tr[tr.length - 1].min };
    return null;
  }

  function pintarProveedores(s) {
    MP.poner(z.proveedores, el('table', { class: 'tabla-sala' },
      el('thead', {}, el('tr', {},
        el('th', { scope: 'col', text: 'Proveedor' }), el('th', { scope: 'col', class: 'der', text: 'Clientes' }),
        el('th', { scope: 'col', text: 'Bloquea por' }), el('th', { scope: 'col', class: 'der', text: 'Activas' }),
        el('th', { scope: 'col', class: 'der', text: 'Fallas' }), el('th', { scope: 'col', class: 'der', text: 'Demora' }))),
      el('tbody', {}, (s.proveedores || []).map((p) => el('tr', {},
        el('th', { scope: 'row', text: MP.sinParentesis(p.nombre) }),
        el('td', { class: 'der num', text: MP.clientes(p.clientes) }),
        el('td', { text: (p.capacidades || []).length === 1 ? 'Solo ' + (p.capacidades[0] === 'ip' ? 'IP' : 'dominio') : (p.capacidades || []).map(MP.tipoBloqueo).join(' y ') }),
        el('td', { class: 'der num', text: MP.num(p.activas, 0) }),
        el('td', { class: ['der', 'num', p.fallidas ? 'texto-alerta' : null], text: MP.num(p.fallidas, 0) }),
        el('td', { class: 'der num', text: p.demora_promedio_min === null || p.demora_promedio_min === undefined ? '—' : MP.minTxt(p.demora_promedio_min) + '′' }))))));
  }

  const ESTADO_RECLAMO = { pendiente: ['alerta', 'Pendiente'], resuelto: ['ok', 'Resuelto'], desestimado: ['neutro', 'Desestimado'], cerrado: ['neutro', 'Cerrado'] };
  const ACCION = { levantar_y_reemplazar: 'levantado y reemplazado por dominio', levantar: 'levantado', desestimar: 'desestimado', cerrar: 'cerrado' };

  /* NV4: un traspaso sin recibir cuyo seguimiento ya se ratificó al «Firmar y seguir» no está «esperando la ratificación». */
  function textoTraspaso(t, s) {
    if (t.ratificado) return 'Ratificado en el ' + MP.min(t.ratificado.min) + '.';
    const ids = ((t.ratificadas_al_firmar || []).map((x) => x && x.id)).concat(t.dinamicas_ratificadas || []).filter(Boolean);
    if (!ids.length) return 'Espera la ratificación del juez entrante.';
    const titulos = new Map((s.expedientes || []).map((e) => [e.id, e.titulo]));
    const nombres = [...new Set(ids)].map((id) => titulos.get(id) || id);
    return 'El juez entrante todavía no confirmó la recepción del turno; el seguimiento de ' +
      (nombres.length > 1 ? nombres.slice(0, -1).join(', ') + ' y ' + nombres[nombres.length - 1] : nombres[0]) +
      ' ya lo ratificó al firmar y seguir.';
  }

  function pintarReclamos(s) {
    const items = [];
    const recl = (s.reclamos || []).slice().sort((a, b) => (b.minuto || 0) - (a.minuto || 0));
    for (const r of recl) {
      const e = ESTADO_RECLAMO[r.estado] || ['neutro', r.estado];
      const res = r.resolucion;
      items.push(el('li', { class: 'fila-lateral' },
        el('div', { class: 'fila-lateral__cab' },
          el('span', { class: 'tarjeta ' + (r.estado === 'pendiente' ? 'tarjeta--roja' : 'tarjeta--gris'), text: 'Reclamo ' + r.id }),
          el('span', { class: 'estado estado--' + e[0], text: e[1] }),
          el('span', { class: 'fila-lateral__min num', text: MP.min(r.minuto) })),
        el('p', { class: 'mono cortar', text: r.dominio }),
        res ? el('p', { class: 'fila-lateral__texto', text: (res.juez ? res.juez + ': ' : '') + (ACCION[res.accion] || res.accion) +
          (res.minutos_hasta_resolver !== null && res.minutos_hasta_resolver !== undefined ? ' en ' + MP.dur(res.minutos_hasta_resolver) : '') +
          (res.por_reclamo ? ' (por ' + res.por_reclamo + ')' : '') + '.' })
          : el('p', { class: 'fila-lateral__texto', text: (r.verificacion && r.verificacion.explicacion) || '' })));
    }
    for (const t of (s.traspasos || []).slice().reverse()) {
      const de = (t.de || []).map((x) => x.nombre).join(', ');
      const a = (t.a || []).map((x) => x.nombre).join(', ');
      items.push(el('li', { class: 'fila-lateral' },
        el('div', { class: 'fila-lateral__cab' },
          el('span', { class: 'tarjeta ' + (t.ratificado ? 'tarjeta--verde' : 'tarjeta--amarilla'), text: 'Traspaso de turno' }),
          el('span', { class: 'fila-lateral__min num', text: MP.min(t.min) })),
        el('p', { class: 'fila-lateral__texto' }, el('strong', { text: de + ' → ' + a })),
        el('p', { class: 'fila-lateral__texto', text: textoTraspaso(t, s) })));
    }
    MP.poner(z.reclamos, items.length ? el('ul', { class: 'lista-lateral' }, items) : el('p', { class: 'panel__vacio', text: 'Sin reclamos ni traspasos.' }));
  }

  const TIPO_AVISO = {
    ampliacion_dinamica: ['verde', 'Ampliación'], orden_fallida: ['roja', 'Falla'], reintento: ['verde', 'Reintento'],
    reclamo: ['roja', 'Reclamo'], traspaso: ['amarilla', 'Traspaso'], alerta: ['roja', 'Alerta'],
  };
  function pintarAvisos(s) {
    const orden = (s.avisos || []).slice().sort((a, b) => (b.n || 0) - (a.n || 0));
    const avisos = MP.agruparAvisos(orden).slice(0, 8);
    MP.poner(z.avisos, avisos.length ? el('ul', { class: 'lista-lateral' }, avisos.map((a) => {
      const t = TIPO_AVISO[a.tipo] || ['gris', MP.capital(String(a.tipo || ''))];
      const accion = MP.pideAccion(a);
      // C3 (N7): el atendido queda apagado, con el texto de cómo se cerró.
      const cierre = a.atendido ? MP.cierreAviso(a) : null;
      return el('li', { class: ['fila-lateral', accion ? 'fila-lateral--accion' : 'fila-lateral--info', a.atendido && 'fila-lateral--atendido'] },
        el('div', { class: 'fila-lateral__cab' },
          el('span', { class: 'tarjeta tarjeta--' + (accion ? t[0] : 'gris'), text: t[1] }),
          a.cuenta > 1 ? el('span', { class: 'fila-lateral__veces num', attrs: { 'aria-label': a.cuenta + ' veces' }, text: '×' + a.cuenta }) : null,
          a.atendido ? el('span', { class: 'estado estado--neutro' }, el('span', { attrs: { 'aria-hidden': 'true' }, text: '✓' }), 'Atendido') : null,
          el('span', { class: 'fila-lateral__min num', text: MP.min(a.min) })),
        el('p', { class: 'fila-lateral__texto', text: a.texto }),
        cierre ? el('p', { class: 'fila-lateral__cierre' }, el('span', { attrs: { 'aria-hidden': 'true' }, text: '✓ ' }), cierre) : null);
    })) : el('p', { class: 'panel__vacio', text: 'Sin avisos.' }));
  }

  const CLASE_DESCARTE = { licenciatario: 'Licenciatario', otra_senal: 'Otra señal', sin_marca: 'Sin marca' };
  function pintarDescartes(s) {
    const ds = s.descartes || [];
    MP.poner(z.descartes, ds.length ? el('ul', { class: 'lista-lateral' }, ds.map((d) =>
      el('li', { class: 'fila-lateral' },
        el('div', { class: 'fila-lateral__cab' },
          el('span', { class: 'estado estado--neutro', text: CLASE_DESCARTE[d.clase] || d.clase }),
          el('span', { class: 'mono cortar', text: d.host }),
          el('span', { class: 'fila-lateral__min num', text: '×' + d.veces })),
        el('p', { class: 'fila-lateral__texto', text: d.motivo || '' })))) : el('p', { class: 'panel__vacio', text: 'Sin descartes.' }));
  }

  function pintarAuditoria(s) {
    const c = s.cabeza_auditoria || {};
    const pq = s.paquete;
    MP.poner(z.cabeza, el('span', { class: 'rotulo', text: 'Cabeza n.º ' + MP.num(c.n, 0) }), MP.hash(c.hash, 'auditoria__hash'),
      pq && pq.huella ? el('span', { class: 'paquete' },
        el('span', { class: 'rotulo', text: 'Huella del paquete' + (pq.exportado_min !== null && pq.exportado_min !== undefined ? ' · ' + MP.min(pq.exportado_min) : '') }),
        MP.hash(pq.huella, 'auditoria__hash'),
        el('span', { class: 'paquete__para', text: 'Es lo que se publica al cerrar: con esta huella nadie puede cambiar la entrega después sin que se note.' })) : null);
    const previa = est.auditoriaVista;
    const lista = (s.auditoria || []).slice(0, 14);
    MP.poner(z.auditoria, lista.map((a) => el('li', { class: ['auditoria__fila', previa !== null && a.n > previa && 'auditoria__fila--nueva'] },
      el('span', { class: 'num auditoria__n', text: '#' + a.n }),
      el('span', { class: 'num auditoria__min', text: MP.min(a.min) }),
      el('span', { class: 'auditoria__tipo', text: MP.tipoAuditoria(a.tipo) }),
      el('span', { class: 'auditoria__actor mono', text: a.actor || '' }),
      el('span', { class: 'auditoria__exp mono', text: a.exp || '' }),
      el('span', { class: 'auditoria__hashcorto mono', text: String(a.hash || '').slice(0, 10) }))));
    est.auditoriaVista = lista.length ? lista[0].n : est.auditoriaVista;
  }

  arrancar();
})();
