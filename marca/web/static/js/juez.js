/* Marca Personal — bandeja del juez (primero el celular).
   El expediente: papel y tinta. Cada pedido entra en una pantalla de celular. */
'use strict';

(function () {
  const { el } = MP;
  const app = MP.$('#app');

  const est = {
    yo: null,
    bandeja: null,
    vig: null,
    formas: new Map(),      // estado de cada formulario, por clave: sobrevive a los repintados
    ocupado: new Set(),     // claves con una acción en curso
    pendientesVistos: null, // claves de lo que pide atención, para detectar lo nuevo
    sellosVistos: null,
    audio: null,
    avisosActivos: false,
    nombres: new Map(),     // id de proveedor -> nombre
    nombresVersion: 0,      // cambia cuando se aprende un nombre: las tarjetas se rehacen con el nombre
    bloqueoHasta: 0,        // después de un salto de pantalla, los toques en botones se ignoran hasta acá
    toque: null,            // último toque: {y, t}, para saber qué está mirando el juez
    pantalla: null,         // Wake Lock de la pantalla, si el navegador lo da
    tituloBase: 'Bandeja del juez — Marca Personal',
    ampliacionesVistas: null, // avisos de ampliación ya vistos (n), para avisar cada una en el momento
  };

  /* ================================================================ inicio */
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
    document.title = 'Bandeja del juez — Marca Personal';
    MP.poner(app,
      el('main', { class: 'ingreso' },
        el('div', { class: 'ingreso__hoja' },
          el('div', { class: 'logo' }, MP.logo(), el('span', { class: 'logo__texto', text: 'Marca Personal' })),
          el('p', { class: 'rotulo ingreso__fuero', text: 'Órdenes de bloqueo en vivo' }),
          el('h1', { class: 'ingreso__titulo', text: 'Bandeja del juez' }),
          el('p', { class: 'ingreso__bajada', text: 'Ingrese con su usuario para ver y firmar los pedidos de su turno.' }),
          mensaje ? el('p', { class: 'error-campo', attrs: { role: 'alert' }, text: mensaje }) : null,
          MP.formIngreso({ alIngresar: entrar }))));
  }

  function entrar(yo) {
    est.yo = yo;
    if (yo.rol !== 'juez') {
      MP.poner(app, el('main', { class: 'ingreso' }, el('div', { class: 'ingreso__hoja' },
        el('h1', { class: 'ingreso__titulo', text: 'Esta bandeja es para jueces' }),
        el('p', { class: 'ingreso__bajada', text: 'Su usuario corresponde a otra función. La sala de situación está en /sala.' }),
        el('div', { class: 'fila-botones' },
          el('a', { class: 'boton boton--principal', href: '/sala', text: 'Ir a la sala' }),
          el('button', { class: 'boton', type: 'button', on: { click: MP.salir } }, 'Salir')))));
      return;
    }
    MP.ponerReloj(yo.reloj);
    armarEsqueleto(yo);
    est.vig = MP.vigilar({
      de: 'juez', // C17: la espera larga de la bandeja abierta marca presencia del juez
      cargar: async () => { const b = await MP.api('GET', '/api/juez/bandeja'); pintar(b); return b; },
      alPerderSesion: (e) => mostrarIngreso(e.codigo === 'no_autenticado' ? 'Su sesión terminó. Vuelva a ingresar.' : e.texto),
    });
  }

  /* ============================================================ esqueleto */
  const zonas = {};

  function armarEsqueleto(yo) {
    zonas.minuto = el('strong', { class: 'reloj__min num', text: '—' });
    zonas.hora = el('span', { class: 'reloj__hora num' });
    zonas.turno = el('p', { class: 'turno' });
    zonas.simulador = el('p', { class: 'caratula__simulador', hidden: true, attrs: { role: 'status' } });
    // Cartel fijo (ronda 2b): por http en la red local no hay notificaciones del sistema; el aviso depende de
    // que la pantalla siga encendida. El sonido se habilita con el primer toque.
    zonas.avisosEstado = el('span', { class: 'activar__estado', attrs: { role: 'status' }, text: 'Sonido: se activa con su primer toque.' });
    zonas.avisosBoton = el('button', { class: 'boton boton--chico activar__boton', type: 'button', on: { click: activarAvisos } }, 'Activar sonido');
    zonas.avisosBarra = el('div', { class: 'activar' },
      el('p', { class: 'activar__texto' },
        el('strong', { text: 'Deje esta pantalla abierta y encendida: si se apaga, las mudanzas esperan su firma.' }), ' ', zonas.avisosEstado),
      zonas.avisosBoton);
    // humano-4: línea al tope cuando los pedidos van antes que la orden marco sin firmar.
    zonas.pedidosArriba = el('p', { class: 'nota nota--alerta pedidos-arriba', hidden: true, attrs: { role: 'status' } });
    zonas.secciones = {};
    for (const s of ['fuera', 'marco', 'traspaso', 'reclamos', 'pendientes', 'dinamicas', 'avisos', 'historial']) {
      zonas.secciones[s] = el('section', { class: 'seccion seccion--' + s, attrs: { 'aria-labelledby': 'tit-' + s } });
    }

    MP.poner(app,
      el('header', { class: 'caratula' },
        el('div', { class: 'caratula__fila' },
          el('a', { class: 'logo', href: '/', attrs: { 'aria-label': 'Marca Personal, portada' } }, MP.logo(),
            el('span', { class: 'logo__texto', text: 'Marca Personal' })),
          el('button', { class: 'boton boton--chico caratula__salir', type: 'button', on: { click: MP.salir } }, 'Salir')),
        el('div', { class: 'caratula__juez' },
          el('h1', { class: 'caratula__nombre', text: yo.nombre }),
          el('p', { class: 'caratula__juzgado', text: yo.juzgado || '' }))),
      el('div', { class: 'tablero', attrs: { 'data-fijo-arriba': '' } },
        el('div', { class: 'reloj', attrs: { 'aria-label': 'Reloj del partido' } }, zonas.minuto, zonas.hora),
        zonas.turno),
      zonas.simulador,
      zonas.avisosBarra,
      el('main', { class: 'bandeja', id: 'bandeja' }, zonas.secciones.fuera, zonas.pedidosArriba,
        Object.values(zonas.secciones).filter((x) => x !== zonas.secciones.fuera)));

    MP.alTic(ticReloj);
    instalarGuardia();
    instalarPresencia();
  }

  /* El primer toque habilita el sonido (los navegadores no dejan sonar sin un gesto) y pide que la pantalla
     no se apague (Wake Lock, solo en contexto seguro). Al volver a la pestaña se vuelve a pedir. */
  let presenciaPuesta = false;
  function instalarPresencia() {
    if (presenciaPuesta) return;
    presenciaPuesta = true;
    const primero = () => {
      document.removeEventListener('pointerdown', primero, true);
      document.removeEventListener('keydown', primero, true);
      activarAvisos({ silencioso: true });
    };
    document.addEventListener('pointerdown', primero, true);
    document.addEventListener('keydown', primero, true);
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') { pedirPantalla(); dejarDeTitilar(); }
    });
    document.addEventListener('pointerdown', dejarDeTitilar, true);
  }

  async function pedirPantalla() {
    if (!('wakeLock' in navigator) || est.pantalla || document.visibilityState !== 'visible') return;
    try {
      est.pantalla = await navigator.wakeLock.request('screen');
      est.pantalla.addEventListener('release', () => { est.pantalla = null; ponerEstadoAvisos(); });
    } catch (e) { est.pantalla = null; }
    ponerEstadoAvisos();
  }

  function ponerEstadoAvisos() {
    if (!zonas.avisosEstado) return;
    const partes = [est.avisosActivos ? 'Sonido activo.' : 'Sonido: se activa con su primer toque.'];
    if (est.pantalla) partes.push('La pantalla se mantiene encendida.');
    else if (!('wakeLock' in navigator)) partes.push('Este navegador no puede mantener la pantalla encendida: ajústelo en el equipo.');
    zonas.avisosEstado.textContent = partes.join(' ');
    zonas.avisosBoton.hidden = est.avisosActivos;
    zonas.avisosBarra.classList.toggle('activar--listo', est.avisosActivos);
  }

  /* El título de la pestaña titila mientras haya algo nuevo que pide acción y nadie miró la pantalla. */
  let titila = null;
  function titilar(texto) {
    dejarDeTitilar();
    let par = false;
    titila = setInterval(() => {
      par = !par;
      document.title = par ? '● ' + texto : (est.tituloPlano || est.tituloBase);
    }, 1000);
  }
  function dejarDeTitilar() {
    if (!titila) return;
    clearInterval(titila);
    titila = null;
    document.title = est.tituloBase;
  }

  /* Si la pantalla acaba de saltar, un toque en un botón de acción puede caer en otro botón: se ignora
     durante unos 400 ms. Solo los toques (clic con detail > 0); el teclado no se bloquea. */
  let guardiaPuesta = false;
  function instalarGuardia() {
    if (guardiaPuesta) return;
    guardiaPuesta = true;
    document.addEventListener('pointerdown', (e) => { est.toque = { y: e.clientY, t: performance.now() }; }, true);
    document.addEventListener('click', (e) => {
      if (!e.detail || performance.now() >= est.bloqueoHasta) return;
      const b = e.target.closest && e.target.closest('button, summary, label.opcion');
      if (!b || !app.contains(b)) return;
      e.preventDefault();
      e.stopPropagation();
    }, true);
  }

  /* Antes de repintar se anota dónde está lo que el juez mira; después se corrige el scroll para que
     quede en el mismo lugar aunque arriba haya entrado o salido una tarjeta. */
  function tomarAncla() {
    const fijo = app.querySelector('.tablero');
    const tope = fijo ? fijo.getBoundingClientRect().bottom : 0;
    const alto = window.innerHeight;
    const ref = est.toque && performance.now() - est.toque.t < 10000 ? est.toque.y : (tope + alto) / 2;
    const foco = document.activeElement;
    const cand = [];
    for (const n of app.querySelectorAll('[data-clave]')) {
      const r = n.getBoundingClientRect();
      if (r.bottom <= tope || r.top >= alto) continue;
      const tieneFoco = foco && n.contains(foco) && foco !== document.body;
      const dist = ref >= r.top && ref <= r.bottom ? 0 : Math.min(Math.abs(ref - r.top), Math.abs(ref - r.bottom));
      cand.push({ clave: n.dataset.clave, top: r.top, peso: tieneFoco ? -1 : dist });
    }
    cand.sort((a, b) => a.peso - b.peso);
    const botones = [];
    for (const b of app.querySelectorAll('[data-clave] button')) {
      const r = b.getBoundingClientRect();
      if (!r.height || r.bottom <= tope || r.top >= alto) continue;
      const t = b.closest('[data-clave]');
      botones.push({ clave: t.dataset.clave, i: Array.from(t.querySelectorAll('button')).indexOf(b), top: r.top, texto: b.textContent });
    }
    return { cand, botones };
  }
  function buscarTarjeta(clave) { return app.querySelector('[data-clave="' + CSS.escape(clave) + '"]'); }
  function restaurarAncla(a) {
    if (!a) return;
    for (const c of a.cand) {
      const n = buscarTarjeta(c.clave);
      if (!n) continue;
      const delta = n.getBoundingClientRect().top - c.top;
      if (Math.abs(delta) >= 1) window.scrollBy(0, delta);
      break;
    }
    for (const b of a.botones) {
      const t = buscarTarjeta(b.clave);
      const nb = t && t.querySelectorAll('button')[b.i];
      if (!nb || nb.textContent !== b.texto || Math.abs(nb.getBoundingClientRect().top - b.top) > 2) {
        est.bloqueoHasta = performance.now() + 400;
        break;
      }
    }
  }

  /* Ola C (8): con unidad; en el último minuto, «falta menos de 1 min» (nunca «faltan 0»). */
  function faltanTxt(n) {
    if (!(n >= 1)) return 'falta menos de 1 min';
    return (n === 1 ? 'falta ' : 'faltan ') + n + ' min';
  }

  function ticReloj(m) {
    if (m === null) return;
    const b = est.bandeja;
    const fin = b ? b.reloj.fin_min : 105;
    // N4: antes del pitazo inicial no hay «min -3,3»: se dice cuánto falta.
    zonas.minuto.textContent = m < 0 ? 'Faltan ' + MP.minTxt(-m) + ' min' : MP.min(Math.min(m, fin + 5));
    zonas.minuto.title = m < 0 ? MP.antesDelInicio(m) : '';
    const h = MP.horaAhora();
    zonas.hora.textContent = h ? h : '';
    if (!b) return;
    const t = b.turno;
    let texto, clase;
    if (m >= fin) { texto = 'El partido terminó'; clase = 'fuera'; }
    else if (t.de_turno) {
      const faltan = Math.max(0, Math.floor(t.hasta_min - m));
      if (t.hasta_min >= fin) { texto = 'De turno hasta el final del partido'; clase = 'activo'; }
      else {
        texto = 'De turno hasta el ' + MP.min(t.hasta_min) + ' (' + faltanTxt(faltan) + ')';
        clase = faltan <= 5 ? 'cierra' : 'activo';
      }
    } else if (t.proximo) {
      const faltan = Math.max(0, Math.ceil(t.proximo.desde_min - m));
      texto = 'Su turno empieza en el ' + MP.min(t.proximo.desde_min) + ' (' + faltanTxt(faltan) + ')';
      clase = 'fuera';
    } else { texto = 'Su turno terminó'; clase = 'fuera'; }
    if (zonas.turno.textContent !== texto) zonas.turno.textContent = texto;
    zonas.turno.className = 'turno turno--' + clase;
  }

  /* ============================================================== pintar */
  function pintar(b, viejo) {
    const ancla = est.bandeja ? tomarAncla() : null;
    est.bandeja = b;
    if (!viejo) MP.ponerReloj(b.reloj); // un repintado local no debe atrasar el reloj
    aprenderNombres(b);
    const s = zonas.secciones;
    const conexionSim = b.reloj.conexion;
    zonas.simulador.hidden = conexionSim === 'ok';
    zonas.simulador.textContent = 'Sin conexión con el simulador del partido: los datos pueden estar atrasados.';
    // N19: con el partido terminado ya no llega nada que firmar: el cartel «Deje esta pantalla abierta…» sobra.
    // NV5: fuera de turno no hay mudanzas que esperen su firma: el cartel no va.
    zonas.avisosBarra.hidden = !!b.reloj.finalizado || !(b.turno && b.turno.de_turno);

    pintarFuera(s.fuera, b);
    pintarMarco(s.marco, b);
    pintarTraspaso(s.traspaso, b);
    pintarLista(s.reclamos, 'reclamos', 'Reclamos por daño colateral', b.reclamos, (r) => 'r:' + r.id, construirReclamo, null);
    pintarLista(s.pendientes, 'pendientes', 'Pedidos para firmar', b.turno.de_turno ? pendientesDe(b) : null,
      (p) => 'u:' + refDe(p), construirPedido,
      b.turno.de_turno ? 'No hay pedidos pendientes. La bandeja se actualiza sola.' : null);
    pintarLista(s.dinamicas, 'dinamicas', 'Filtraciones en seguimiento', b.dinamicas, (d) => 'd:' + d.exp, construirDinamica, null);
    pintarLista(s.avisos, 'avisos', 'Avisos', avisosDe(b), (a) => 'a:' + (a.clave || a.tipo + '|' + a.texto), construirAviso, null);
    pintarLista(s.historial, 'historial', 'Lo que usted decidió', historialDe(b), (x) => x.k, construirDecidido,
      'Todavía no decidió nada.');

    ordenarSecciones(b);
    detectarNuevos(b);
    restaurarAncla(ancla);
    if (est.sellosVistos === null) {
      est.sellosVistos = new Set();
      for (const h of b.historial) { const u = ubic(h); if (u && u.decision) est.sellosVistos.add(u.decision.sello); }
    }
  }

  /* humano-4: de turno, sin la orden marco firmada y con pedidos esperando, los pedidos van arriba («Firmar solo este
     servidor» no necesita la orden marco) y la orden marco debajo. Sin pedidos, la orden marco sigue primera. */
  function pedidosPrimero(b) {
    const n = b.turno && b.turno.de_turno && !(b.reloj && b.reloj.finalizado) ? pendientesDe(b).length : 0;
    return n > 0 && !!b.marco && !b.marco.firmada ? n : 0;
  }
  function lineaPedidosArriba(n) {
    return 'Tiene ' + (n === 1 ? '1 pedido esperando' : n + ' pedidos esperando') + '. Su orden marco está más abajo.';
  }
  function ordenarSecciones(b) {
    const s = zonas.secciones;
    const n = pedidosPrimero(b);
    zonas.pedidosArriba.hidden = !n;
    if (n) zonas.pedidosArriba.textContent = lineaPedidosArriba(n);
    const orden = n ? [s.fuera, zonas.pedidosArriba, s.pendientes, s.marco, s.traspaso, s.reclamos]
      : [s.fuera, zonas.pedidosArriba, s.marco, s.traspaso, s.reclamos, s.pendientes];
    const main = s.marco.parentNode;
    if (!main) return;
    const ahora = [...main.children].slice(0, orden.length);
    if (orden.every((x, i) => ahora[i] === x)) return; // ya está así: no se mueve nada (no se pierde el foco)
    const sigue = s.dinamicas;
    for (const x of orden) main.insertBefore(x, sigue);
  }

  /* Nombres de los proveedores: de bandeja.proveedores si viene; si no, de las órdenes y los reclamos que ya llegaron. */
  function aprenderNombres(b) {
    const antes = est.nombres.size;
    const poner = (id, nombre) => { if (id && nombre && est.nombres.get(id) !== nombre) { est.nombres.set(id, nombre); est.nombresVersion++; } };
    for (const p of b.proveedores || []) poner(p.id, p.nombre);
    const ver = (exp) => { for (const u of exp.ubicaciones || []) for (const o of u.ordenes || []) poner(o.proveedor, o.proveedor_nombre); };
    for (const h of b.historial || []) ver(h.expediente);
    for (const p of b.pendientes || []) ver(p.expediente);
    for (const r of (b.reclamos || []).concat(b.historial_reclamos || [])) poner(r.proveedor, r.proveedor_nombre);
    if (!b.proveedores) buscarNombresFaltantes(b);
    return est.nombres.size !== antes;
  }
  /* Respaldo mientras la bandeja no traiga `proveedores`: el registro público tiene los nombres de los que ya aplicaron. */
  let ultimaBusqueda = 0;
  function buscarNombresFaltantes(b) {
    const faltan = pendientesDe(b).some((p) => {
      const u = ubic(p);
      return u && Object.keys((u.propuesta || {}).objetivos_por_proveedor || {}).some((id) => !est.nombres.has(id));
    });
    if (!faltan || performance.now() - ultimaBusqueda < 30000) return;
    ultimaBusqueda = performance.now();
    MP.api('GET', '/api/publico/registro').then((r) => {
      let nuevos = false;
      for (const x of r.bloqueos || []) {
        if (x.proveedor && x.proveedor_nombre && est.nombres.get(x.proveedor) !== x.proveedor_nombre) {
          est.nombres.set(x.proveedor, x.proveedor_nombre); est.nombresVersion++; nuevos = true;
        }
      }
      if (nuevos && est.bandeja) pintar(est.bandeja, true);
    }).catch(() => { /* sin nombres: quedan los ids */ });
  }
  const nombreProv = (id) => MP.sinParentesis(est.nombres.get(id) || MP.capital(id));
  const ubic = (x) => (x.expediente.ubicaciones || []).find((u) => u.n === x.n);
  /* Adenda 3, B: «sin_decidir» es terminal (el partido terminó con el pedido pendiente): nunca se ofrece para firmar. */
  const sinDecidir = (x) => { const u = ubic(x); return !!u && u.estado === 'sin_decidir'; };
  const pendientesDe = (b) => (b.pendientes || []).filter((p) => !sinDecidir(p));
  const refDe = (x) => { const u = ubic(x); return u ? u.ref : x.expediente.id + '/U' + x.n; };

  function titulo(id, texto, cantidad) {
    return el('h2', { class: 'seccion__titulo', id: 'tit-' + id },
      el('span', { text: texto }),
      cantidad !== null && cantidad !== undefined ? el('span', { class: 'seccion__cuenta num', text: String(cantidad) }) : null);
  }

  /* Repinta una lista reutilizando las tarjetas que no cambiaron: no se pierde lo
     que el juez está escribiendo ni el foco. Las que cambiaron se rehacen desde
     est.formas, que guarda el estado de cada formulario. */
  function pintarLista(seccion, id, textoTitulo, items, clave, construir, vacio) {
    if (!items || (!items.length && !vacio)) { seccion.hidden = true; MP.vaciar(seccion); return; }
    seccion.hidden = false;
    let cab = seccion.querySelector(':scope > .seccion__titulo');
    const nuevoCab = titulo(id, textoTitulo, items.length);
    if (cab) seccion.replaceChild(nuevoCab, cab); else seccion.prepend(nuevoCab);
    let lista = seccion.querySelector(':scope > .lista');
    if (!lista) { lista = el('div', { class: 'lista lista--' + id }); seccion.appendChild(lista); }
    let vacioN = seccion.querySelector(':scope > .vacio');
    if (!items.length) {
      MP.vaciar(lista);
      if (!vacioN) seccion.appendChild(el('p', { class: 'vacio', text: vacio }));
      return;
    }
    if (vacioN) vacioN.remove();

    const foco = guardarFoco();
    const existentes = new Map();
    for (const n of Array.from(lista.children)) existentes.set(n.dataset.clave, n);
    const puede = est.bandeja.turno.puede_firmar + '|' + seguimientoAutorizado(est.bandeja) + '|' + !!est.bandeja.traspaso;
    const orden = [];
    for (const it of items) {
      const k = clave(it);
      const firma = JSON.stringify(it) + '|' + puede + '|' + est.ocupado.has(k) + '|' + est.nombresVersion;
      const viejo = existentes.get(k);
      let n = viejo;
      if (!n || n.dataset.firma !== firma) {
        n = construir(it, k);
        n.dataset.clave = k;
        n.dataset.firma = firma;
        if (viejo) viejo.replaceWith(n);
      }
      existentes.delete(k);
      orden.push(n);
    }
    for (const n of existentes.values()) n.remove();
    orden.forEach((n, i) => { if (lista.children[i] !== n) lista.insertBefore(n, lista.children[i] || null); });
    restaurarFoco(foco);
  }

  function guardarFoco() {
    const a = document.activeElement;
    if (!a || !a.dataset || !a.dataset.campo) return null;
    const tarjeta = a.closest('[data-clave]');
    return tarjeta ? { clave: tarjeta.dataset.clave, campo: a.dataset.campo, ini: a.selectionStart, fin: a.selectionEnd, nodo: a } : null;
  }
  function restaurarFoco(f) {
    if (!f || document.activeElement === f.nodo && document.contains(f.nodo)) return;
    const t = app.querySelector('[data-clave="' + CSS.escape(f.clave) + '"]');
    const n = t && t.querySelector('[data-campo="' + CSS.escape(f.campo) + '"]');
    if (!n) return;
    n.focus({ preventScroll: true });
    if (typeof f.ini === 'number' && n.setSelectionRange) { try { n.setSelectionRange(f.ini, f.fin); } catch (e) { /* radio */ } }
  }

  function forma(clave, inicial) {
    if (!est.formas.has(clave)) est.formas.set(clave, Object.assign({ error: '' }, inicial || {}));
    return est.formas.get(clave);
  }

  /* ======================================================= fuera de turno */
  function pintarFuera(sec, b) {
    const t = b.turno;
    if (t.de_turno && t.puede_firmar) { sec.hidden = true; MP.vaciar(sec); return; }
    sec.hidden = false;
    let titulo2, texto;
    if (b.reloj.finalizado) { titulo2 = 'El partido terminó'; texto = 'Ya no se firman órdenes. Su historial queda abajo.'; }
    else if (t.de_turno) { titulo2 = 'No puede firmar en este momento'; texto = t.motivo || ''; }
    else if (t.proximo) { titulo2 = 'Su turno todavía no empezó'; texto = 'Empieza en el ' + MP.min(t.proximo.desde_min) + '. Hasta entonces la bandeja solo muestra su historial.'; }
    else { titulo2 = 'Su turno terminó'; texto = 'Lo pendiente pasó al juez entrante. Puede consultar su historial; no puede firmar.'; }
    MP.poner(sec, el('div', { class: 'cartel cartel--fuera', attrs: { role: 'status' } },
      el('span', { class: 'tarjeta tarjeta--gris', text: b.reloj.finalizado ? 'Partido terminado' : 'Fuera de turno' }),
      el('h2', { class: 'cartel__titulo', id: 'tit-fuera', text: titulo2 }),
      texto ? el('p', { text: texto }) : null));
  }

  /* ========================================================== orden marco */
  /* Ronda 2b: el seguimiento depende de una orden marco que el juez firma al empezar su turno; viene apagado.
     Sin `bandeja.marco` (motor anterior) no hay tarjeta y rige la regla vieja (dinámica habilitada). */
  function seguimientoAutorizado(b) {
    if (!b.marco) return !!b.yo.dinamica_habilitada;
    return !!(b.marco.firmada && b.marco.firmada.seguimiento);
  }

  function cuerpoMarco(m, fir) {
    const p = m.propuesta || {};
    const conSeg = fir ? fir.seguimiento : false;
    return el('div', { class: 'marco__cuerpo' },
      el('ol', { class: 'marco__lineas' }, (p.lineas || []).map((t) => el('li', { text: t }))),
      fir ? el('div', { class: 'marco__seguimiento' },
        el('p', {}, el('strong', { text: (conSeg ? '✓ ' : '✕ ') + (p.titulo_casilla || 'Seguimiento de la misma filtración') + ': ' + (conSeg ? 'sí' : 'no') })),
        conSeg ? el('ul', { class: 'marco__condiciones' }, (p.condiciones_seguimiento || []).map((t) => el('li', { text: t }))) : null) : null,
      fir ? el('p', { class: 'ayuda' }, 'Firmada en el ' + MP.min(fir.min) + (fir.hora ? ' (' + String(fir.hora).slice(0, 5) + ')' : '') +
        (fir.entrada !== null && fir.entrada !== undefined ? ' · entrada ' + fir.entrada : '') + ' · huella ', MP.hash(fir.huella)) : null);
  }

  function pintarMarco(sec, b) {
    const m = b.marco;
    if (!m || !b.turno.de_turno || b.reloj.finalizado) { sec.hidden = true; MP.vaciar(sec); delete sec.dataset.firma; return; }
    const k = 'marco';
    const f = forma(k, { seguimiento: false, cambiando: false, ver: false });
    const firma = JSON.stringify(m) + '|' + est.ocupado.has(k) + '|' + f.cambiando + '|' + f.ver + '|' + f.error;
    if (sec.dataset.firma === firma) return;
    const foco = guardarFoco();
    sec.dataset.firma = firma;
    sec.hidden = false;
    const fir = m.firmada;
    const repintar = () => pintarMarco(sec, est.bandeja);

    if (fir && !f.cambiando) {
      MP.poner(sec, el('div', { class: 'marco-linea', dataset: { clave: k } },
        el('h2', { class: 'solo-lectores', id: 'tit-marco', text: 'Orden marco' }),
        el('div', { class: 'marco-linea__fila' },
          el('p', { class: 'marco-linea__texto' },
            el('span', { class: 'estado ' + (fir.seguimiento ? 'estado--ok' : 'estado--neutro') },
              el('span', { attrs: { 'aria-hidden': 'true' }, text: fir.seguimiento ? '✓' : '■' })),
            ' ', el('strong', { text: 'Orden marco firmada' }), ' · ' + MP.min(fir.min) + ' · seguimiento: ' + (fir.seguimiento ? 'sí' : 'no')),
          el('div', { class: 'marco-linea__botones' },
            el('button', { class: 'boton boton--chico', type: 'button', attrs: { 'aria-expanded': String(!!f.ver) },
              on: { click: () => { f.ver = !f.ver; repintar(); } } }, f.ver ? 'Ocultar' : 'Ver'),
            m.puede_firmar ? el('button', { class: 'boton boton--chico', type: 'button',
              on: { click: () => { f.cambiando = true; f.seguimiento = false; f.error = ''; repintar(); const c = sec.querySelector('input, button'); if (c) c.focus(); } } }, 'Cambiar') : null)),
        f.ver ? cuerpoMarco(m, fir) : null));
      restaurarFoco(foco);
      return;
    }

    const p = m.propuesta || {};
    const ocupado = est.ocupado.has(k);
    const casilla = m.seguimiento_disponible
      ? el('fieldset', { class: 'marco__casilla' },
        el('legend', { class: 'rotulo', text: 'Seguimiento (apagado salvo que lo marque)' }),
        el('label', { class: 'opcion', htmlFor: 'om-seguimiento' },
          el('input', { type: 'checkbox', id: 'om-seguimiento', checked: !!f.seguimiento, dataset: { campo: 'seguimiento' },
            on: { change: (e) => { f.seguimiento = e.target.checked; } } }),
          el('span', { class: 'opcion__texto' },
            el('strong', { text: p.titulo_casilla || 'Autorizo el seguimiento de la misma filtración' }),
            el('ul', { class: 'marco__condiciones' }, (p.condiciones_seguimiento || []).map((t) => el('li', { text: t }))))))
      : el('p', { class: 'ayuda', text: 'El seguimiento está deshabilitado en esta plataforma: la orden marco se firma sin seguimiento.' });
    MP.poner(sec,
      el('article', { class: 'foja foja--marco', dataset: { clave: k }, attrs: { 'aria-labelledby': 'tit-marco' } },
        el('header', { class: 'foja__cabeza' },
          el('span', { class: 'tarjeta tarjeta--amarilla', text: fir ? 'Cambiar la orden marco' : 'Falta su firma' }),
          el('span', { class: 'foja__hora num', text: 'Turno ' + MP.rangoTurno(b.turno.desde_min, b.turno.hasta_min, b.reloj.fin_min) })),
        el('h2', { class: 'foja__titulo', id: 'tit-marco', text: 'Orden marco' }),
        el('p', { class: 'ayuda', text: 'Fija los límites de su turno. Sin ella puede firmar servidor por servidor; para seguir a una filtración hace falta autorizarlo acá.' }),
        el('ol', { class: 'marco__lineas' }, (p.lineas || []).map((t) => el('li', { text: t }))),
        casilla,
        m.puede_firmar
          ? el('div', { class: 'fila-botones' },
            el('button', { class: 'boton boton--principal boton--ancho', type: 'button', disabled: ocupado,
              on: { click: () => accion(k, '/api/juez/marco', { seguimiento: !!(m.seguimiento_disponible && f.seguimiento) },
                'Orden marco firmada · seguimiento: ' + (m.seguimiento_disponible && f.seguimiento ? 'sí' : 'no') + '.') } },
            iconoFirma(), el('span', { class: 'boton__etiqueta', text: ocupado ? 'Firmando…' : 'Firmar orden marco' })),
            fir ? el('button', { class: 'boton boton--ancho', type: 'button', on: { click: () => { f.cambiando = false; f.error = ''; repintar(); } } }, 'Cancelar') : null)
          : el('p', { class: 'nota nota--fuera', text: m.motivo_no || 'No puede firmar en este momento.' }),
        el('p', { class: 'error-campo', attrs: { role: 'alert' }, hidden: !f.error, text: f.error })));
    restaurarFoco(foco);
  }

  /* ============================================================= traspaso */
  /* Ronda 2b: los seguimientos heredados (clave `dinamicas`) se ratifican uno por uno (casillas, nada marcado de antemano)
     y solo con la orden marco con seguimiento. Lo que quedó en espera sale igual al recibir el turno. */
  /* NV4: separa los seguimientos heredados que faltan ratificar de los que ya se ratificaron al firmar y seguir
     (`dinamicas_ratificadas` y, si viene, `ratificadas_al_firmar` con el minuto). */
  /* NV7: el aviso después de recibir sale de lo que el motor ratificó de verdad (`resultado.ratificadas` y
     `resultado.sin_ratificar`); sin eso (motor anterior), el texto de siempre. */
  function avisoRecibio(resp, t, siNoHay) {
    const res = resp && resp.resultado;
    if (!res || !Array.isArray(res.sin_ratificar)) return siNoHay;
    if (!res.sin_ratificar.length) return 'Recibió el turno.';
    const titulos = new Map((((t && t.resumen) || {}).dinamicas || []).map((d) => [d.exp, d.titulo]));
    const n = res.sin_ratificar.map((id) => titulos.get(id) || id);
    const lista = n.length > 1 ? n.slice(0, -1).join(', ') + ' y ' + n[n.length - 1] : n[0];
    return 'Recibió el turno. Sin ratificar: ' + lista + '; sus mudanzas vuelven a pedir su firma.';
  }
  function herenciaTraspaso(t, b) {
    const r = (t && t.resumen) || {};
    // NV7: casilla solo para lo que de verdad espera ratificación según la bandeja (un seguimiento propio, firmado
    // con «Firmar y seguir» sobre una filtración nueva, no es herencia). Sin la lista de la bandeja, como antes.
    const conLista = !!(b && Array.isArray(b.dinamicas));
    const esperan = new Set(conLista ? b.dinamicas.filter((d) => d && d.requiere_ratificacion).map((d) => d.exp) : []);
    const alFirmar = new Map(((t && t.ratificadas_al_firmar) || []).filter((x) => x && x.id).map((x) => [x.id, x]));
    const ids = new Set(((t && t.dinamicas_ratificadas) || []).concat([...alFirmar.keys()]));
    const pendientes = [];
    const ratificadas = [];
    for (const d of r.dinamicas || []) {
      if (!ids.has(d.exp)) { if (!conLista || esperan.has(d.exp)) pendientes.push(d); continue; }
      const x = alFirmar.get(d.exp);
      ratificadas.push(Object.assign({}, d, { ratificada_min: x ? x.min : null }));
    }
    return { pendientes, ratificadas };
  }

  function pintarTraspaso(sec, b) {
    const t = b.traspaso;
    if (!t) { sec.hidden = true; MP.vaciar(sec); delete sec.dataset.firma; return; }
    const k = 'traspaso';
    const f = forma(k, { marcadas: [] });
    const conSeg = seguimientoAutorizado(b);
    const fin = !!(b.reloj && b.reloj.finalizado);
    const firma = JSON.stringify(t) + '|' + est.ocupado.has(k) + '|' + b.turno.puede_firmar + '|' + conSeg + '|' + !!b.marco + '|' + fin + '|' + f.error;
    if (sec.dataset.firma === firma) return;
    const foco = guardarFoco();
    sec.dataset.firma = firma;
    sec.hidden = false;
    const r = t.resumen || {};
    const de = (t.de || []).map((x) => x.nombre).join(', ');
    // NV4: lo que ya se ratificó al «Firmar y seguir» no se vuelve a ofrecer: va aparte, sin casilla.
    const { pendientes: dins, ratificadas: yaRat } = herenciaTraspaso(t, b);
    const todas = dins.concat(yaRat);
    const ocupado = est.ocupado.has(k) || !b.turno.puede_firmar;
    const ruta = '/api/juez/traspaso/ratificar';
    const items = [
      ['Bloqueos vigentes', r.bloqueos_vigentes],
      ['Filtraciones en seguimiento', todas.length],
      ['Órdenes en espera de su firma', r.ordenes_en_espera],
      ['Pedidos pendientes', r.ubicaciones_pendientes],
      ['Reclamos pendientes', r.reclamos_pendientes],
    ];
    let acciones;
    if (fin) {
      // NV6: con el partido terminado no queda nada que recibir ni ratificar.
      acciones = el('p', { class: 'nota nota--fuera', text: 'El partido terminó sin que se confirmara la recepción del turno.' });
    } else if (!b.marco) {
      // Motor anterior a la ronda 2b: ratificación en bloque, como antes.
      acciones = el('button', { class: 'boton boton--principal boton--ancho boton--grande', type: 'button', disabled: ocupado,
        on: { click: () => accion(k, ruta, {}, 'Ratificó lo heredado. Los seguimientos quedan bajo su firma.') } }, 'Ratificar lo heredado');
    } else if (!dins.length) {
      acciones = el('button', { class: 'boton boton--principal boton--ancho', type: 'button', disabled: ocupado,
        on: { click: () => accion(k, ruta, { dinamicas: [] }, (resp) => avisoRecibio(resp, t, 'Recibió el turno. Lo que estaba en espera salió a los proveedores.')) } }, 'Recibir el turno');
    } else {
      const sinSeg = el('p', { class: 'nota nota--espera', id: 'tr-sin-om', hidden: conSeg },
        el('strong', { text: 'Para ratificar los seguimientos, firme antes la orden marco con el seguimiento autorizado (arriba). ' }),
        'Mientras tanto puede recibir el turno sin seguimiento.');
      acciones = el('div', { class: 'acciones acciones--pila' }, sinSeg,
        el('div', { class: 'acciones__par' },
          el('button', { class: 'boton boton--principal boton--ancho', type: 'button', disabled: ocupado || !conSeg,
            attrs: conSeg ? {} : { 'aria-describedby': 'tr-sin-om' },
            on: { click: () => {
              const marcadas = f.marcadas.filter((x) => dins.some((d) => d.exp === x));
              if (!marcadas.length) return errorEn(sec, f, 'Marque al menos un seguimiento, o elija «Recibir sin seguimiento».');
              accion(k, ruta, { dinamicas: marcadas }, (resp) => avisoRecibio(resp, t, 'Recibió el turno: ' + (dins.length === 1 ? 'ratificó el seguimiento heredado.'
                : 'ratificó ' + MP.num(marcadas.length, 0) + ' de ' + MP.plural(dins.length, 'seguimiento heredado', 'seguimientos heredados') + '.')));
            } } }, 'Ratificar las marcadas'),
          el('button', { class: 'boton boton--principal boton--ancho', type: 'button', disabled: ocupado,
            on: { click: () => accion(k, ruta, { dinamicas: [] }, (resp) => avisoRecibio(resp, t, 'Recibió el turno sin seguimiento: las mudanzas de esas filtraciones vuelven a pedir su firma.')) } },
          'Recibir sin seguimiento')));
    }
    MP.poner(sec,
      el('article', { class: 'foja foja--traspaso', dataset: { clave: k }, attrs: { 'aria-labelledby': 'tit-traspaso' } },
        el('header', { class: 'foja__cabeza' },
          el('span', { class: 'tarjeta ' + (fin ? 'tarjeta--gris' : 'tarjeta--amarilla'), text: fin ? 'Sin recibir' : 'Espera su decisión' }),
          el('span', { class: 'foja__hora num', text: 'Cambio de turno · ' + MP.min(t.min) })),
        el('h2', { class: 'foja__titulo', id: 'tit-traspaso' }, 'Recibe el turno', de ? el('span', { class: 'foja__titulo-sub', text: 'de ' + de }) : null),
        el('dl', { class: 'herencia' }, items.map(([a, v]) => el('div', { class: 'herencia__item' },
          el('dt', { text: a }), el('dd', { class: 'num', text: MP.num(v || 0, 0) })))),
        yaRat.length ? el('ul', { class: 'herencia__ratificadas' }, yaRat.map((d) => el('li', { class: 'herencia__dinamica' },
          el('strong', { class: 'cortar', text: d.titulo }), ' · ',
          el('span', { text: 'Ya ratificado al firmar y seguir' + (d.ratificada_min !== null && d.ratificada_min !== undefined ? ' (' + MP.min(d.ratificada_min) + ')' : '') + '.' })))) : null,
        dins.length && !fin ? el('fieldset', { class: 'herencia__dinamicas' },
          el('legend', { class: 'rotulo', text: b.marco ? 'Seguimientos heredados: marque los que ratifica' : 'Seguimientos heredados' }),
          dins.map((d) => {
            const id = 'tr-din-' + d.exp;
            const texto = el('span', { class: 'opcion__texto' }, el('strong', { class: 'cortar', text: d.titulo }),
              el('span', { class: 'mono', text: [d.exp, d.sesion ? 'sesión ' + d.sesion : null].filter(Boolean).join(' · ') }));
            if (!b.marco) return el('p', { class: 'herencia__dinamica' }, texto);
            return el('label', { class: 'opcion', htmlFor: id },
              el('input', { type: 'checkbox', id, checked: f.marcadas.includes(d.exp), disabled: !conSeg || ocupado, dataset: { campo: 'din-' + d.exp },
                on: { change: (e) => {
                  f.marcadas = f.marcadas.filter((x) => x !== d.exp).concat(e.target.checked ? [d.exp] : []);
                } } }),
              texto);
          })) : null,
        fin ? null : el('p', { class: 'nota', text: b.marco
          ? 'Lo que quedó en espera sale a los proveedores en cuanto reciba el turno.' + (dins.length ? ' Cada seguimiento que ratifique pasa a respaldarse con su firma; las demás filtraciones no se amplían solas.' : '')
          : 'Al ratificar, los seguimientos pasan a respaldarse con su firma y las órdenes en espera salen a los proveedores.' }),
        acciones,
        el('p', { class: 'error-campo', attrs: { role: 'alert' }, hidden: !f.error, text: f.error })));
    restaurarFoco(foco);
  }

  function errorEn(sec, f, texto) {
    f.error = texto;
    const e = sec.querySelector('.error-campo');
    if (e) { e.textContent = texto; e.hidden = false; }
  }

  /* ============================================================== pedidos */
  /* C4: la nota de continuidad del mismo servidor. Si el motor la manda (continuidad.nota o reabierta.nota) va
     tal cual; si no, se arma con `levantada_por_freno` de la ubicación anterior. */
  function notaMismoServidor(u, anterior) {
    const c = u.continuidad || {};
    const re = u.reabierta && typeof u.reabierta === 'object' ? u.reabierta : {};
    const dada = c.nota || u.nota_continuidad || re.nota || re.texto || (typeof u.reabierta === 'string' ? u.reabierta : null);
    if (dada) return String(dada);
    const lpf = anterior && anterior.levantada_por_freno;
    if (!lpf) return null;
    const amp = lpf.ampliada_min !== undefined && lpf.ampliada_min !== null ? lpf.ampliada_min : (anterior.decision || {}).min;
    const yo = est.bandeja && est.bandeja.yo ? est.bandeja.yo.juez_id : null;
    const quien = lpf.juez_id && lpf.juez_id === yo ? 'usted' : (lpf.juez || 'otro juez');
    return 'Mismo servidor: la plataforma lo había bloqueado sola en el minuto ' + MP.minTxt(amp) + '; ' +
      quien + ' levantó ese bloqueo en el minuto ' + MP.minTxt(lpf.min) + '.';
  }

  /* C24: «Mismo stream que ya bloqueó» solo si la ubicación anterior está aprobada. */
  function lineaMismoStream(anterior, de, n) {
    if (!anterior || anterior.estado === 'aprobada') return 'Mismo stream que ya bloqueó: ubicación ' + de + ' → ' + n;
    if (anterior.estado === 'pendiente') return 'Mismo stream que la ubicación ' + de + ' (todavía sin decidir)';
    if (anterior.estado === 'rechazada') return 'Mismo stream que la ubicación ' + de + ' (rechazada)';
    return 'Mismo stream que la ubicación ' + de;
  }
  function textoSuperada(u, n) {
    const ult = u.ultima_deteccion_min !== null && u.ultima_deteccion_min !== undefined ? u.ultima_deteccion_min : u.primera_deteccion_min;
    return 'Este servidor no se ve desde el ' + MP.min(ult) + '. La misma filtración apareció después en otro servidor ' +
      '(ubicación ' + n + '), que está más arriba.';
  }
  /* Ola C (6): la propuesta se rehízo al resolverse un reclamo; sin aviso, la tarjeta cambiaría en silencio. */
  function textoRecalculada(rc) {
    if (!rc || !rc.tipo) return null;
    const por = (t) => (t === 'ip' ? 'IP' : t === 'dominio' ? 'dominio' : String(t));
    const cuando = rc.min !== null && rc.min !== undefined ? ' en el minuto ' + MP.minTxt(rc.min) : '';
    const porQue = rc.reclamo ? ' al resolverse el reclamo ' + rc.reclamo : ' al resolverse un reclamo';
    const cambio = rc.tipo_antes && rc.tipo_antes !== rc.tipo
      ? ': antes proponía bloquear por ' + por(rc.tipo_antes) + '; ahora, por ' + por(rc.tipo) + '.'
      : ': ahora propone bloquear por ' + por(rc.tipo) + '.';
    return 'La propuesta cambió' + cuando + porQue + cambio;
  }

  function construirPedido(p, k) {
    const b = est.bandeja;
    const exp = p.expediente;
    const u = ubic(p);
    const col = u.colateral || {};
    const prop = u.propuesta || {};
    const rec = col.recomendacion;
    // Sin código de sesión el motor no puede seguir la filtración; sin orden marco con seguimiento, tampoco.
    const puedeSeguir = !!(b.yo.dinamica_habilitada && exp.filtracion && exp.filtracion.sesion);
    const f = forma(k, { forzar: null, fundamento: '', rechazando: false, motivo: '', causal: null });
    const ocupado = est.ocupado.has(k);
    const puede = b.turno.puede_firmar;
    const nodo = el('article', { class: 'foja foja--pedido', attrs: { 'aria-label': 'Pedido ' + u.ref } });

    /* --- cabecera y qué se pide --- */
    nodo.append(
      el('header', { class: 'foja__cabeza' },
        el('span', { class: 'tarjeta tarjeta--amarilla', text: 'Espera su firma' }),
        el('span', { class: 'foja__ref mono', text: exp.id + ' · U' + u.n }),
        el('span', { class: 'foja__hora num', text: 'Llegó en el ' + MP.min(u.notificada_min !== null && u.notificada_min !== undefined ? u.notificada_min : u.armado_min) })),
      el('h3', { class: 'foja__titulo' },
        el('span', { class: 'foja__verbo', text: 'Bloquear' }),
        el('span', { class: 'foja__objetivo cortar', text: u.host })),
      el('p', { class: 'foja__sitio' },
        'Sitio ', el('strong', { class: 'cortar', text: exp.sitio || exp.titulo }),
        exp.filtracion && exp.filtracion.sesion ? [' · sesión ', el('span', { class: 'mono', text: exp.filtracion.sesion })] : null));

    // C4 (N14): el mismo servidor cuya ampliación se levantó vuelve como pedido: no es una mudanza, y se firma
    // «solo este servidor» o se rechaza (el seguimiento de esa filtración ya se frenó).
    const deU = u.continuidad ? u.continuidad.de_ubicacion : null;
    const anteriorU = deU == null ? null : (exp.ubicaciones || []).find((x) => x.n === deU);
    const mismoServidor = !!u.reabierta || !!(u.continuidad && (u.continuidad.criterio === 'mismo_servidor' ||
      (anteriorU && anteriorU.host === u.host && anteriorU.ip === u.ip)));
    // C22: el mismo servidor vuelve porque se lo vio después de un rechazo; no hubo seguimiento que frenar.
    const porRechazo = mismoServidor && (!!u.rechazo_previo || !!(anteriorU && anteriorU.estado === 'rechazada'));
    // C24: la filtración ya dejó este servidor y apareció en otro (que está más arriba en la bandeja).
    if (p.superada_por !== null && p.superada_por !== undefined) {
      nodo.append(el('p', { class: 'nota nota--espera' }, textoSuperada(u, p.superada_por)));
    }
    const recalc = textoRecalculada(u.recalculada);
    if (recalc) nodo.append(el('p', { class: 'nota nota--espera', text: recalc }));
    if (u.continuidad) {
      const de = deU;
      const anterior = anteriorU;
      const notaC4 = notaMismoServidor(u, anterior);
      nodo.append(el('div', { class: 'mudanza' },
        el('div', { class: 'mudanza__pista', attrs: { 'aria-hidden': 'true' } },
          el('span', { class: 'mudanza__punto mudanza__punto--antes' }), el('span', { class: 'mudanza__linea' }), el('span', { class: 'mudanza__punto' })),
        el('p', { class: 'mudanza__texto' },
          el('strong', { text: mismoServidor ? 'Mismo servidor que la ubicación ' + de + (porRechazo ? ' (rechazada)' : '')
            : lineaMismoStream(anterior, de, u.n) }),
          el('span', { text: mismoServidor ? (notaC4 || 'Vuelve a transmitir desde ' + u.host + '.')
            : (anterior ? anterior.host + ' → ' + u.host + '. ' : '') +
              (u.continuidad.criterio === 'misma_marca' ? 'Se reconoce por la misma marca de agua.' : 'Se reconoce por el mismo sitio.') }))));
    }
    // Solo tiene sentido en una mudanza: en la primera ubicación nunca hubo un seguimiento que la alcance.
    // C6: el motor manda la oración completa; la pantalla solo le antepone «No se amplió solo: ».
    if (p.automatica && !p.automatica.posible && p.automatica.motivo && (u.continuidad || u.n > 1)) {
      nodo.append(el('p', { class: 'nota nota--espera' }, el('strong', { text: 'No se amplió solo: ' }), String(p.automatica.motivo)));
    }

    /* --- tres comprobaciones --- */
    nodo.append(el('ol', { class: 'comprobaciones' },
      comprobacionSenal(u), comprobacionServidor(u), comprobacionColateral(u)));

    /* --- qué se bloquea en cada proveedor --- */
    nodo.append(tablaBloqueos(u, prop, f, rec));

    /* --- evidencia completa --- */
    nodo.append(evidencia(u, exp, k, f));

    if (!puede) {
      nodo.append(el('p', { class: 'nota nota--fuera', text: b.turno.motivo || 'No puede firmar en este momento.' }));
      return nodo;
    }

    /* --- apartarse de la recomendación --- */
    nodo.append(apartarse(u, k, f, rec, prop));

    /* --- firmar: dos botones del mismo peso, nada preseleccionado (ronda 2b) --- */
    const frenado = mismoServidor && !porRechazo;
    const seguir = puedeSeguir && seguimientoAutorizado(b) && !frenado;
    let nota = null;
    if (frenado) nota = 'El seguimiento de esta filtración se frenó: este pedido se firma solo para este servidor.';
    else if (!b.yo.dinamica_habilitada) nota = 'El seguimiento está deshabilitado en esta plataforma: si se muda, llega un pedido nuevo.';
    else if (!puedeSeguir) nota = 'Esta marca no trae código de sesión: si se muda, llega un pedido nuevo.';
    else if (!seguir) nota = 'Para seguir a la filtración, autorícelo en la orden marco.';
    // C15 (textos-2): con los dos botones a la vista, una línea dice qué alcanza cada uno.
    else nota = '“Firmar y seguir”: si esta misma transmisión (sesión ' + exp.filtracion.sesion + ') aparece en otro ' +
      'servidor, se bloquea sin pedirle otra firma, bajo su orden marco y hasta el final del partido; se le avisa y ' +
      'puede frenarlo. “Solo este servidor”: si se muda, llega un pedido nuevo.' +
      // textos-3: sobre un seguimiento heredado que espera ratificación, «Firmar y seguir» también lo ratifica.
      ((b.dinamicas || []).some((d) => d.exp === exp.id && d.requiere_ratificacion)
        ? ' Firmar y seguir también ratifica el seguimiento heredado.' : '');
    const error =el('p', { class: 'error-campo', attrs: { role: 'alert' }, hidden: !f.error, text: f.error });
    const motivo = el('textarea', { class: 'entrada', id: 'mot-' + k, rows: 3, value: f.motivo, dataset: { campo: 'motivo' },
      attrs: { maxlength: '400', 'aria-describedby': 'mot-ayuda-' + k }, on: { input: (e) => { f.motivo = e.target.value; contarMotivo(); } } });
    const ayudaMotivo = el('p', { class: 'ayuda', id: 'mot-ayuda-' + k });
    function contarMotivo() { const n = f.motivo.trim().length; ayudaMotivo.textContent = n >= 10 ? n + ' caracteres.' : 'Faltan ' + (10 - n) + ' caracteres.'; }
    contarMotivo();
    const causales = el('div', { class: 'causales', attrs: { role: 'group', 'aria-label': 'Causales del rechazo' } },
      CAUSALES.map((c) => el('button', { class: 'boton boton--chico causal', type: 'button', attrs: { 'aria-pressed': String(f.causal === c) },
        on: { click: () => {
          f.causal = c;
          f.motivo = c === 'Otro motivo' ? '' : c + ': ';
          motivo.value = f.motivo;
          for (const x of causales.children) x.setAttribute('aria-pressed', String(x.textContent === c));
          contarMotivo();
          motivo.focus();
          motivo.setSelectionRange(f.motivo.length, f.motivo.length);
        } } }, c)));
    const formRechazo = el('div', { class: 'rechazo', hidden: !f.rechazando },
      el('p', { class: 'rotulo', text: 'Causal' }), causales,
      el('div', { class: 'campo' }, el('label', { htmlFor: 'mot-' + k, class: 'rotulo', text: 'Motivo del rechazo (obligatorio, mínimo 10 caracteres)' }), motivo, ayudaMotivo),
      el('div', { class: 'fila-botones' },
        el('button', { class: 'boton boton--peligro', type: 'button', disabled: ocupado, on: { click: () => {
          if (f.motivo.trim().length < 10) return mostrarError(nodo, f, 'Escriba el motivo del rechazo: al menos 10 caracteres.');
          accion(k, rutaUbic(exp, u, 'rechazar'), { motivo: f.motivo.trim() }, 'Pedido rechazado: ' + u.host + '.');
        } } }, 'Confirmar rechazo'),
        el('button', { class: 'boton', type: 'button', on: { click: () => { f.rechazando = false; formRechazo.hidden = true; botones.hidden = false; } } }, 'Cancelar')));
    const botonFirma = (alcance, texto) => el('button', { class: 'boton boton--principal boton--firmar boton--ancho', type: 'button', disabled: ocupado,
      dataset: { alcance }, on: { click: () => firmar(nodo, exp, u, k, f, rec, alcance) } },
    iconoFirma(), el('span', { class: 'boton__etiqueta', text: ocupado && f.firmando === alcance ? 'Firmando…' : texto }));
    const botones = el('div', { class: 'acciones acciones--pila', hidden: f.rechazando },
      el('p', { class: 'nota nota--alerta firma__forzado', attrs: { 'aria-live': 'polite' }, hidden: true }),
      el('div', { class: 'acciones__par' },
        botonFirma('ubicacion', 'Firmar solo este servidor'),
        seguir ? botonFirma('filtracion', 'Firmar y seguir a esta filtración') : null),
      nota ? el('p', { class: 'ayuda acciones__nota', text: nota }) : null,
      el('button', { class: 'boton boton--ancho', type: 'button', disabled: ocupado,
        on: { click: () => { f.rechazando = true; botones.hidden = true; formRechazo.hidden = false; motivo.focus(); } } }, 'Rechazar'));
    nodo.append(el('div', { class: 'decision' }, antesDeFirmar(u, prop, f, rec), botones, formRechazo, error));
    requestAnimationFrame(() => ponerEtiquetaFirma(nodo, k, f, rec));
    return nodo;
  }

  /* Antes de firmar: las tres comprobaciones en una línea y qué se bloquea, pegadas a los botones. En el celular,
     el detalle de arriba ocupa más de una pantalla: así el juez ve lo que firma junto al botón. Repite, no reemplaza. */
  function antesDeFirmar(u, prop, f, rec) {
    const forzado = f.forzar && f.forzar !== rec ? f.forzar : null;
    const real = forzado ? planForzado(u, forzado) : null;
    const plan = real || prop || {};
    const nombres = {};
    for (const id of Object.keys(plan.objetivos_por_proveedor || {})) nombres[id] = nombreProv(id);
    const linea = lineaBloqueo(plan, nombres);
    const vence = (prop || {}).vence_min;
    return el('section', { class: 'antes-de-firmar', attrs: { 'aria-label': 'Resumen antes de firmar' } },
      el('ul', { class: 'antes-de-firmar__chequeos' }, resumenComprobaciones(u, forzado).map((x) =>
        el('li', { class: 'chequeo chequeo--' + x.clase }, el('span', { attrs: { 'aria-hidden': 'true' }, text: x.icono + ' ' }), x.texto))),
      el('p', { class: 'antes-de-firmar__bloqueo' },
        el('strong', { text: forzado && !real ? 'Según la recomendación se bloquea: ' : 'Se bloquea: ' }),
        linea || 'nada: la plataforma no recomienda bloquear este servidor.',
        linea && vence !== undefined && vence !== null ? ' Hasta el ' + MP.min(vence) + '.' : ''));
  }

  /* Las tres comprobaciones, con los mismos criterios que las de arriba. Si el juez se apartó para bloquear por IP,
     el daño colateral es el de bloquear la IP (no el verde de la recomendación por nombre). */
  function resumenComprobaciones(u, forzado) {
    const s = u.senal || {};
    const c = u.coherencia || {};
    const col = u.colateral || {};
    const icono = (clase) => (clase === 'ok' ? '✓' : clase === 'alerta' ? '✕' : clase === 'espera' ? '◐' : '?');
    const senal = s.clase === 'pirata' ? 'ok' : 'alerta';
    const serv = c.completa ? 'ok' : c.ok ? 'espera' : 'alerta';
    const r = forzado === 'ip' ? (RIESGO[col.riesgo] || RIESGO.desconocido) : riesgoDelBloqueo(col);
    return [
      { clase: senal, icono: icono(senal), texto: senal === 'ok' ? 'Señal del partido' : 'No es la señal del partido' },
      { clase: serv, icono: icono(serv), texto: c.completa ? 'Servidor coherente' : c.ok ? 'Servidor: datos parciales' : 'Servidor: no coincide' },
      { clase: r.clase, icono: icono(r.clase), texto: r.texto },
    ];
  }

  /* «IP 203.0.113.10 en Aurora y Andina; s1.pelotaya.test en FibraValle.»: una frase, juntando a los proveedores
     que reciben lo mismo. Sin nada que bloquear, null. */
  function lineaBloqueo(plan, nombres) {
    const obj = (plan && plan.objetivos_por_proveedor) || {};
    const grupos = [];
    for (const id of Object.keys(obj)) {
      const objs = (obj[id] || []).map((o) => (o.tipo === 'ip' ? 'IP ' : '') + o.objetivo);
      if (!objs.length) continue;
      const clave = objs.join('|');
      let g = grupos.find((x) => x.clave === clave);
      if (!g) { g = { clave, objs, provs: [] }; grupos.push(g); }
      g.provs.push(nombres[id] || id);
    }
    if (!grupos.length) return null;
    const y = (xs) => (xs.length < 2 ? xs.join('') : xs.slice(0, -1).join(', ') + ' y ' + xs[xs.length - 1]);
    return grupos.map((g) => y(g.objs) + ' en ' + y(g.provs)).join('; ') + '.';
  }

  const CAUSALES = ['La evidencia no alcanza', 'Riesgo para sitios ajenos', 'No es la señal del partido', 'Otro motivo'];

  /* Si se apartó de la recomendación, una línea arriba de los botones dice qué tipo de bloqueo se firma. */
  function ponerEtiquetaFirma(nodo, k, f, rec) {
    const e = nodo.querySelector('.firma__forzado');
    if (!e) return;
    const forzado = f.forzar && f.forzar !== rec;
    e.hidden = !forzado;
    e.textContent = forzado ? 'Va a firmar un bloqueo por ' + MP.tipoBloqueo(f.forzar) + ': se aparta de la recomendación' +
      (rec && rec !== 'ninguna' ? ' (' + MP.tipoBloqueo(rec) + ')' : '') + '.' : '';
  }

  function iconoFirma() {
    return MP.svg('svg', { viewBox: '0 0 24 24', class: 'icono', 'aria-hidden': 'true' },
      MP.svg('path', { d: 'M3 17c3-1 4-6 6-6s1 5 3 5 3-3 4-3 1 2 5 2', fill: 'none', stroke: 'currentColor', 'stroke-width': '2', 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }),
      MP.svg('path', { d: 'M3 21h18', stroke: 'currentColor', 'stroke-width': '2', 'stroke-linecap': 'round' }));
  }

  const rutaUbic = (exp, u, acc) => '/api/juez/ubicaciones/' + encodeURIComponent(exp.id) + '/' + encodeURIComponent(u.n) + '/' + acc;

  function firmar(nodo, exp, u, k, f, rec, alcanceElegido) {
    f.alcance = alcanceElegido;
    f.firmando = alcanceElegido;
    const cuerpo = { alcance: alcanceElegido };
    const forzado = f.forzar && f.forzar !== rec;
    if (forzado) {
      if (f.fundamento.trim().length < 10) {
        const det = nodo.querySelector('.apartarse');
        if (det) det.open = true;
        return mostrarError(nodo, f, 'Para apartarse de la recomendación escriba un fundamento de al menos 10 caracteres.');
      }
      cuerpo.forzar_tipo = f.forzar;
      cuerpo.fundamento = f.fundamento.trim();
    }
    const alcance = alcanceElegido === 'filtracion' ? 'sigue a la filtración' : 'solo este servidor';
    accion(k, rutaUbic(exp, u, 'aprobar'), cuerpo, 'Firmado: ' + u.host + ' (' + alcance + '). La orden sale a los proveedores.');
  }

  function mostrarError(nodo, f, texto) {
    f.error = texto;
    const e = nodo.querySelector('.error-campo');
    if (e) { e.textContent = texto; e.hidden = false; }
  }

  function comprobacion(num, tituloTxt, resultado, clase, detalle) {
    return el('li', { class: 'comprobacion comprobacion--' + clase },
      el('div', { class: 'comprobacion__cab' },
        el('span', { class: 'comprobacion__num', attrs: { 'aria-hidden': 'true' }, text: String(num) }),
        el('h4', { class: 'comprobacion__titulo', text: tituloTxt }),
        el('span', { class: 'comprobacion__resultado' },
          el('span', { attrs: { 'aria-hidden': 'true' }, text: clase === 'ok' ? '✓' : clase === 'alerta' ? '✕' : clase === 'espera' ? '◐' : '?' }),
          resultado)),
      el('div', { class: 'comprobacion__detalle' }, detalle));
  }

  function comprobacionSenal(u) {
    const s = u.senal || {};
    const ok = s.clase === 'pirata';
    return comprobacion(1, 'Es la señal del partido', ok ? 'Sí' : 'No', ok ? 'ok' : 'alerta', [
      el('p', { class: 'mono cortar', text: s.marca || 'sin marca' }),
      el('p', { text: [s.origen, s.sesion ? 'sesión ' + s.sesion : null].filter(Boolean).join(' · ') }),
      (s.observaciones || []).map((o) => el('p', { class: 'ayuda', text: o })),
    ]);
  }

  function comprobacionServidor(u) {
    const c = u.coherencia || {};
    const vals = ['host_en_url', 'ip_en_dns_del_host', 'host_en_dns_de_la_ip', 'asn_coincide'].map((x) => c[x]);
    const si = vals.filter((x) => x === true).length;
    const clase = c.completa ? 'ok' : c.ok ? 'espera' : 'alerta';
    const res = c.completa ? 'Coherente' : c.ok ? 'Parcial' : 'No coincide';
    return comprobacion(2, 'Servidor identificado', res, clase, [
      el('p', {}, el('span', { class: 'mono cortar', text: u.host }), ' · ', el('span', { class: 'mono', text: u.ip })),
      el('p', { text: 'AS' + u.asn + ' · ' + (u.organizacion || 'organización desconocida') }),
      el('p', { class: 'ayuda', text: si + ' de 4 datos confirmados con el DNS pasivo.' }),
      (c.observaciones || []).map((o) => el('p', { class: 'ayuda', text: o })),
    ]);
  }

  const RIESGO = {
    nulo: { luz: 'verde', texto: 'Sin daño colateral', clase: 'ok' },
    medio: { luz: 'amarilla', texto: 'Riesgo medio', clase: 'espera' },
    alto: { luz: 'roja', texto: 'Riesgo alto', clase: 'alerta' },
    desconocido: { luz: 'ninguna', texto: 'Sin datos', clase: 'neutro' },
  };

  /* textos-5: `colateral.riesgo` es el riesgo de bloquear la IP. Si lo que se firma es solo el nombre, el semáforo
     describe ese bloqueo (que no toca a nadie) y deja dicho el riesgo de la IP. */
  function riesgoDelBloqueo(col) {
    const r = RIESGO[col.riesgo] || RIESGO.desconocido;
    if (col.recomendacion !== 'dominio' || (col.riesgo !== 'alto' && col.riesgo !== 'medio')) return r;
    return { luz: 'amarilla', texto: r.texto + ' si se bloquea la IP', clase: 'espera',
      nota: 'El bloqueo propuesto (por nombre) no afecta a sitios ajenos.' };
  }

  function semaforo(r) {
    return el('span', { class: 'semaforo', attrs: { role: 'img', 'aria-label': 'Semáforo: ' + r.texto } },
      ['roja', 'amarilla', 'verde'].map((luz) => el('span', { class: ['semaforo__luz', 'semaforo__luz--' + luz, r.luz === luz && 'semaforo__luz--encendida'] })));
  }

  function comprobacionColateral(u) {
    const col = u.colateral || {};
    const r = riesgoDelBloqueo(col);
    const ajenos = col.ajenos || [];
    const li = el('li', { class: 'comprobacion comprobacion--colateral comprobacion--' + r.clase },
      el('div', { class: 'comprobacion__cab' },
        el('span', { class: 'comprobacion__num', attrs: { 'aria-hidden': 'true' }, text: '3' }),
        el('h4', { class: 'comprobacion__titulo', text: 'Daño colateral' }),
        el('span', { class: 'comprobacion__resultado' }, semaforo(r), r.texto)),
      el('div', { class: 'comprobacion__detalle' },
        r.nota ? el('p', {}, el('strong', { text: r.nota })) : null,
        el('p', { class: 'colateral__oracion', text: col.motivo || '' }),
        ajenos.length ? el('details', { class: 'ajenos' },
          el('summary', { text: 'Sitios ajenos en la misma IP (' + ajenos.length + ')' }),
          el('ul', { class: 'ajenos__lista' }, ajenos.map((a) => el('li', { class: 'mono cortar', text: a })))) : null));
    return li;
  }

  /* N18: lo que sale de verdad si el juez se aparta de la recomendación. Copia la regla de `evidencia.proponer`
     del motor: por IP, la IP donde el proveedor bloquea por IP y los nombres del servidor (el host y sus
     dominios propios) donde solo bloquea por dominio; por dominio, el host donde se puede. Sin las capacidades
     de los proveedores (motor viejo) devuelve null y la tabla queda como antes. */
  const esIpLiteral = (h) => /^\d{1,3}(\.\d{1,3}){3}$/.test(String(h || '')) || String(h || '').includes(':');
  function planForzado(u, tipo) {
    const provs = (est.bandeja && est.bandeja.proveedores) || [];
    if (!provs.length || !provs.every((p) => Array.isArray(p.capacidades))) return null;
    const host = u.host;
    const propios = ((u.colateral || {}).propios || []).filter((n) => n && n !== host);
    const nombres = [host].concat(propios);
    const objetivos = {};
    const sin = [];
    for (const p of provs) {
      const caps = p.capacidades;
      if (tipo === 'ip') {
        if (caps.includes('ip')) objetivos[p.id] = [{ tipo: 'ip', objetivo: u.ip }];
        else if (caps.includes('dominio') && !esIpLiteral(host)) objetivos[p.id] = nombres.map((n) => ({ tipo: 'dominio', objetivo: n }));
        else sin.push(p.id);
      } else if (caps.includes('dominio') && !esIpLiteral(host)) objetivos[p.id] = [{ tipo: 'dominio', objetivo: host }];
      else sin.push(p.id);
    }
    return { tipo, objetivos_por_proveedor: objetivos, sin_cobertura: sin };
  }

  function tablaBloqueos(u, prop, f, rec) {
    const forzado = f.forzar && f.forzar !== rec;
    const real = forzado ? planForzado(u, f.forzar) : null;
    const plan = real || prop;
    const atenuado = forzado && !real;
    const obj = plan.objetivos_por_proveedor || {};
    const ids = Object.keys(obj);
    const sinCob = plan.sin_cobertura || [];
    const vence = prop.vence_min;
    // C26 (textos-7): la hora la da el motor (la misma que recibe el proveedor); sin ella, el reloj de la pantalla.
    const hora = prop.vence_hora ? String(prop.vence_hora).slice(0, 5) : MP.horaCorta(vence);
    const porIp = plan.tipo === 'ip' || (real && real.tipo === 'ip');
    return el('section', { class: ['bloqueos', atenuado && 'bloqueos--atenuado'] },
      el('h4', { class: 'rotulo', text: atenuado ? 'Qué se bloquea según la recomendación' : 'Qué se bloquea en cada proveedor' }),
      real ? el('p', { class: 'ayuda', text: 'Con su elección (bloquear por ' + (real.tipo === 'ip' ? 'IP' : 'dominio') + '), no con la recomendación.' }) : null,
      ids.length ? el('ul', { class: 'lista-bloqueos' }, ids.map((id) => el('li', { class: 'lista-bloqueos__fila' },
        el('span', { class: 'lista-bloqueos__prov', text: MP.sinParentesis(nombreProv(id)) }),
        el('span', { class: 'lista-bloqueos__objs' }, (obj[id] || []).map((o) => el('span', { class: 'objetivo' },
          el('span', { class: 'objetivo__tipo', text: MP.tipoBloqueo(o.tipo) }),
          el('span', { class: 'mono cortar', text: o.objetivo })))))))
        : el('p', { class: 'nota nota--alerta', text: 'La plataforma no recomienda bloquear este servidor. Si decide hacerlo, elija el tipo en «Apartarme de la recomendación».' }),
      sinCob.length ? el('p', { class: 'nota', text: 'Sin cobertura: ' + sinCob.map((x) => MP.sinParentesis(nombreProv(x))).join(', ') +
        (porIp ? (sinCob.length === 1 ? ' (no bloquea por IP ni por dominio).' : ' (no bloquean por IP ni por dominio).')
          : (sinCob.length === 1 ? ' (solo bloquea por IP).' : ' (solo bloquean por IP).')) }) : null,
      el('p', { class: 'vence' }, el('span', { class: 'rotulo', text: 'Hasta ' }),
        'el final del partido: ' + MP.min(vence) + (hora ? ' (' + hora + ')' : '')));
  }

  function evidencia(u, exp, k, f) {
    const det = el('details', { class: 'evidencia', open: !!f.evidencia, on: { toggle: (e) => { f.evidencia = e.target.open; } } },
      el('summary', { text: 'Ver evidencia completa' }));
    const cap = u.captura || {};
    const filas = [
      ['Huella de la evidencia', MP.hash(u.huella)],
      ['Captura (sha256)', MP.hash(cap.sha256)],
      ['Captura', [cap.bytes + ' bytes', cap.formato, cap.duracion_seg + ' s', 'capturada en el ' + MP.min(cap.capturada_min),
        cap.sync_mpegts ? 'sincronía MPEG-TS correcta' : 'sin sincronía MPEG-TS', cap.valida ? 'válida' : 'NO válida'].filter(Boolean).join(' · ')],
      ['Página', el('span', { class: 'mono cortar', text: u.pagina })],
      ['Stream', el('span', { class: 'mono cortar', text: u.stream_url })],
      ['Detecciones', (u.detecciones || []).join(', ') + ' (' + u.n_detecciones + '; de ' + MP.min(u.primera_deteccion_min) + ' a ' + MP.min(u.ultima_deteccion_min) + ')'],
      ['Dominios en la IP', el('span', { class: 'mono cortar', text: ((u.colateral || {}).dominios_en_ip || []).join(', ') || 'sin datos' })],
      ['Promoción', (u.promocion || []).length ? el('ul', {}, u.promocion.map((p) =>
        el('li', {}, el('span', { text: (p.red || '').toUpperCase() + ' · ' + MP.min(p.minuto) + ' · ' }), el('span', { class: 'mono cortar', text: p.url })))) : 'sin registros'],
      ['Armado', MP.min(u.armado_min) + (u.armado_utc ? ' · ' + u.armado_utc : '')],
      ['Fundamento propuesto', (u.propuesta || {}).fundamento || ''],
    ];
    det.append(el('dl', { class: 'datos' }, filas.map(([a, v]) => el('div', { class: 'datos__fila' }, el('dt', { text: a }), el('dd', {}, v)))));
    return det;
  }

  function apartarse(u, k, f, rec, prop) {
    const col = u.colateral || {};
    const ajenos = col.ajenos || [];
    const det = el('details', { class: 'apartarse', open: !!f.apartarse || !!(f.forzar && f.forzar !== rec),
      on: { toggle: (e) => { f.apartarse = e.target.open; } } },
    el('summary', { text: 'Apartarme de la recomendación' }));
    const aviso = el('div', { class: 'apartarse__aviso', attrs: { 'aria-live': 'polite' } });
    const fundamento = el('textarea', { class: 'entrada', id: 'fun-' + k, rows: 3, value: f.fundamento, dataset: { campo: 'fundamento' },
      attrs: { maxlength: '600', 'aria-describedby': 'fun-ayuda-' + k }, on: { input: (e) => { f.fundamento = e.target.value; contar(); } } });
    const ayuda = el('p', { class: 'ayuda', id: 'fun-ayuda-' + k });
    const campoFund = el('div', { class: 'campo' }, el('label', { htmlFor: 'fun-' + k, class: 'rotulo', text: 'Fundamento (obligatorio, mínimo 10 caracteres)' }), fundamento, ayuda);
    function contar() { const n = f.fundamento.trim().length; ayuda.textContent = n >= 10 ? n + ' caracteres.' : 'Faltan ' + (10 - n) + ' caracteres.'; }
    function actualizar() {
      const forzado = f.forzar && f.forzar !== rec;
      campoFund.hidden = !forzado;
      MP.vaciar(aviso);
      if (forzado && f.forzar === 'ip' && ajenos.length) {
        aviso.append(el('p', { class: 'alerta-roja' },
          el('strong', { text: 'Bloquear la IP ' + u.ip + ' deja sin servicio a ' + ajenos.length + (ajenos.length === 1 ? ' sitio ajeno' : ' sitios ajenos') + ': ' }),
          el('span', { class: 'mono', text: ajenos.slice(0, 4).join(', ') + (ajenos.length > 4 ? ' y ' + (ajenos.length - 4) + ' más' : '') + '.' })));
      } else if (forzado && f.forzar === 'ip' && col.red_compartida) {
        aviso.append(el('p', { class: 'alerta-roja', text: 'La IP ' + u.ip + ' pertenece a una red compartida: bloquearla puede afectar a otros clientes.' }));
      } else if (forzado && f.forzar === 'dominio') {
        aviso.append(el('p', { class: 'nota', text: 'Se bloqueará solo el nombre ' + u.host + ' en los proveedores que bloquean por dominio.' }));
      }
      // N18: la tabla muestra lo que va a salir con la elección actual (se rehace; no tiene campos editables).
      const tabla = det.parentNode && det.parentNode.querySelector('.bloqueos');
      if (tabla) tabla.replaceWith(tablaBloqueos(u, prop || {}, f, rec));
      const resumen = det.parentNode && det.parentNode.querySelector('.antes-de-firmar');
      if (resumen) resumen.replaceWith(antesDeFirmar(u, prop || {}, f, rec));
      if (det.parentNode) ponerEtiquetaFirma(det.parentNode, k, f, rec);
    }
    const opcion = (valor) => {
      const id = 'tipo-' + k + '-' + valor;
      const esRec = valor === rec;
      const actual = (f.forzar || rec) === valor;
      return el('label', { class: 'opcion opcion--compacta', htmlFor: id },
        el('input', { type: 'radio', id, name: 'tipo-' + k, value: valor, checked: actual, dataset: { campo: 'tipo-' + valor },
          on: { change: () => { f.forzar = valor; actualizar(); } } }),
        el('span', { class: 'opcion__texto' }, el('strong', { text: 'Bloquear por ' + MP.tipoBloqueo(valor) }),
          el('span', { text: esRec ? 'Es la recomendación.' : valor === 'ip' ? 'IP ' + u.ip : 'Nombre ' + u.host })));
    };
    det.append(el('fieldset', { class: 'apartarse__tipos' },
      el('legend', { class: 'rotulo', text: 'Recomendación: ' + (rec === 'ninguna' ? 'no bloquear' : MP.tipoBloqueo(rec)) }),
      opcion('ip'), opcion('dominio')), aviso, campoFund);
    contar();
    // El aviso se calcula cuando la tarjeta ya está en el documento.
    requestAnimationFrame(actualizar);
    return det;
  }

  /* ============================================================= reclamos */
  const CLASE_RECLAMANTE = {
    legitimo: { texto: 'Legítimo: no tiene relación con el pirata', clase: 'alerta' },
    licenciatario: { texto: 'Licenciatario autorizado', clase: 'alerta' },
    operacion_pirata: { texto: 'Parte de la operación pirata', clase: 'neutro' },
    sin_bloqueo: { texto: 'No hay bloqueos que lo afecten', clase: 'neutro' },
  };
  const ACCION_RECLAMO = {
    levantar_y_reemplazar: 'Levantar y reemplazar',
    levantar: 'Levantar',
    desestimar: 'Desestimar',
  };

  function construirReclamo(r, k) {
    const b = est.bandeja;
    const v = r.verificacion || {};
    const prop = r.propuesta || null;
    const f = forma(k, { desestimando: false, fundamento: '' });
    const ocupado = est.ocupado.has(k);
    // C14: un nombre solo inferido (nunca visto transmitiendo ni publicando) que reclama es legítimo, pero sí comparte
    // servidor y dominio con el pirata: el rótulo no dice «sin relación». La explicación del motor va tal cual.
    const cr = v.clase_reclamante === 'legitimo' && v.inferido
      ? { texto: 'Legítimo: se lo había tomado por parte del sitio pirata', clase: 'alerta' }
      : CLASE_RECLAMANTE[v.clase_reclamante] || { texto: v.clase_reclamante || '—', clase: 'neutro' };
    const nodo = el('article', { class: 'foja foja--reclamo', attrs: { 'aria-label': 'Reclamo ' + r.id } },
      el('header', { class: 'foja__cabeza' },
        el('span', { class: 'tarjeta tarjeta--roja', text: 'Reclamo · espera su decisión' }),
        el('span', { class: 'foja__ref mono', text: r.id }),
        el('span', { class: 'foja__hora num', text: MP.min(r.minuto) + ' · vía ' + MP.sinParentesis(r.proveedor_nombre || nombreProv(r.proveedor)) })),
      el('h3', { class: 'foja__titulo' }, el('span', { class: 'foja__verbo', text: 'Reclama' }), el('span', { class: 'foja__objetivo cortar', text: r.dominio })),
      el('blockquote', { class: 'reclamo__mensaje' }, el('span', { class: 'rotulo', text: 'Mensaje del reclamante' }), el('p', { text: r.mensaje || '' })),
      el('section', { class: 'reclamo__bloque' },
        el('h4', { class: 'rotulo', text: 'Qué comprobó la plataforma' }),
        el('p', {}, el('span', { class: 'estado estado--' + cr.clase, text: cr.texto })),
        el('p', { text: v.explicacion || '' }),
        (v.ips || []).length ? el('p', { class: 'ayuda' }, 'Resuelve a ', el('span', { class: 'mono', text: v.ips.join(', ') }), ' según el DNS pasivo.') : null,
        (v.ordenes_causantes || []).length ? el('ul', { class: 'causantes' }, v.ordenes_causantes.map((o) =>
          el('li', {}, el('strong', { text: nombreProv(o.proveedor) }), ' · ' + MP.tipoBloqueo(o.tipo) + ' ',
            el('span', { class: 'mono', text: o.objetivo }), el('span', { class: 'ayuda', text: ' · ' + o.exp + '/U' + o.n })))) : null),
      prop ? el('section', { class: 'reclamo__bloque' },
        el('h4', { class: 'rotulo', text: 'Qué propone' }),
        el('p', { class: 'reclamo__propuesta', text: prop.explicacion || '' }),
        (prop.reemplazo || []).length ? el('ul', { class: 'causantes' }, prop.reemplazo.map((x) =>
          el('li', {}, 'Nuevo: ', el('strong', { text: nombreProv(x.proveedor) }), ' · ' + MP.tipoBloqueo(x.tipo) + ' ', el('span', { class: 'mono', text: x.objetivo })))) : null) : null);

    if (!b.turno.puede_firmar) return nodo;
    const propuesta = prop ? prop.accion : null;
    const hayLevantar = prop && (prop.levantar || []).length > 0;
    const hayReemplazo = prop && prop.accion === 'levantar_y_reemplazar';
    const error = el('p', { class: 'error-campo', attrs: { role: 'alert' }, hidden: !f.error, text: f.error });
    const resolver = (accionR, fundamento) => accion(k, '/api/juez/reclamos/' + encodeURIComponent(r.id) + '/resolver',
      fundamento ? { accion: accionR, fundamento } : { accion: accionR },
      'Reclamo ' + r.id + ': ' + ACCION_RECLAMO[accionR].toLowerCase() + '.');
    const boton = (accionR, habilitado) => el('button', {
      class: ['boton', 'boton--ancho', accionR === propuesta && 'boton--principal', accionR === propuesta && 'boton--grande'],
      type: 'button', disabled: ocupado || !habilitado,
      on: { click: () => {
        if (accionR === 'desestimar') { f.desestimando = true; acciones.hidden = true; formDes.hidden = false; fund.focus(); return; }
        resolver(accionR);
      } } },
    ACCION_RECLAMO[accionR] + (accionR === propuesta ? ' (propuesto)' : ''));
    const orden = ['levantar_y_reemplazar', 'levantar', 'desestimar'].sort((a, c) => (a === propuesta ? -1 : c === propuesta ? 1 : 0));
    const acciones = el('div', { class: 'acciones', hidden: f.desestimando },
      orden.map((a) => boton(a, a === 'desestimar' || (a === 'levantar' ? hayLevantar : hayReemplazo))));
    const fund = el('textarea', { class: 'entrada', id: 'des-' + k, rows: 3, value: f.fundamento, dataset: { campo: 'fundamento' },
      attrs: { maxlength: '600' }, on: { input: (e) => { f.fundamento = e.target.value; } } });
    const formDes = el('div', { class: 'rechazo', hidden: !f.desestimando },
      el('div', { class: 'campo' }, el('label', { htmlFor: 'des-' + k, class: 'rotulo', text: 'Fundamento para desestimar (obligatorio)' }), fund),
      el('div', { class: 'fila-botones' },
        el('button', { class: 'boton boton--peligro', type: 'button', disabled: ocupado, on: { click: () => {
          if (f.fundamento.trim().length < 3) return mostrarError(nodo, f, 'Escriba el fundamento para desestimar.');
          resolver('desestimar', f.fundamento.trim());
        } } }, 'Confirmar desestimación'),
        el('button', { class: 'boton', type: 'button', on: { click: () => { f.desestimando = false; formDes.hidden = true; acciones.hidden = false; } } }, 'Cancelar')));
    nodo.append(el('div', { class: 'decision' }, acciones, formDes, error));
    return nodo;
  }

  /* ============================================================ dinámicas */
  const quienCuando = (q) => q.nombre + ' en el ' + MP.min(q.min) + (q.entrada !== null && q.entrada !== undefined ? ' (entrada ' + q.entrada + ')' : '');

  function construirDinamica(d, k) {
    const b = est.bandeja;
    const f = forma(k, { abierto: false, motivo: '' });
    const ocupado = est.ocupado.has(k);
    const motivo = el('textarea', { class: 'entrada', id: 'rev-' + k, rows: 2, value: f.motivo, dataset: { campo: 'motivo' },
      attrs: { maxlength: '400' }, on: { input: (e) => { f.motivo = e.target.value; } } });
    // Quién la otorgó y quién la ratificó (contrato); sin esos datos, solo el minuto.
    const o = d.otorgada_por;
    const r = d.ratificada_por;
    const respaldo = [];
    respaldo.push(o && o.nombre ? 'Otorgado por ' + quienCuando(Object.assign({ min: d.otorgada_min }, o)) : 'Otorgado en el ' + MP.min(d.otorgada_min));
    if (r && r.nombre) respaldo.push('ratificado por ' + quienCuando(r));
    else if (d.requiere_ratificacion && !b.reloj.finalizado) respaldo.push('espera la ratificación del juez de turno');
    // N19: después del final ya no hay nada que ratificar ni mudanzas que seguir.
    const fin = !!b.reloj.finalizado;
    const tarjeta = fin
      ? ['gris', d.requiere_ratificacion ? 'Sin ratificar: terminó con el partido' : 'Terminó con el partido']
      : d.requiere_ratificacion ? ['amarilla', 'Espera ratificación'] : ['verde', 'Vigente'];
    const nodo = el('article', { class: 'dinamica', id: 'din-' + d.exp },
      el('div', { class: 'dinamica__cab' },
        el('span', { class: ['tarjeta', 'tarjeta--' + tarjeta[0]], text: tarjeta[1] }),
        el('span', { class: 'foja__ref mono', text: d.exp })),
      el('p', { class: 'dinamica__titulo' }, el('strong', { class: 'cortar', text: d.titulo }), d.sesion ? [' · sesión ', el('span', { class: 'mono', text: d.sesion })] : null),
      el('p', { class: 'dinamica__respaldo', text: MP.conPunto(respaldo.join(' · ')) }),
      el('p', { class: 'ayuda', text: MP.plural(d.ubicaciones, 'ubicación firmada', 'ubicaciones firmadas') +
        (typeof d.ampliaciones === 'number' && d.ampliaciones ? ', ' + MP.plural(d.ampliaciones, 'ampliada sola y vigente', 'ampliadas solas y vigentes') : '') +
        (fin ? '.' : d.requiere_ratificacion ? '. Mientras espere ratificación, las mudanzas piden su firma.' : '. Si el stream se muda, el bloqueo se amplía solo.') }));
    if (b.turno.puede_firmar && !fin) {
      const error = el('p', { class: 'error-campo', attrs: { role: 'alert' }, hidden: !f.error, text: f.error });
      const rutaRev = '/api/juez/dinamicas/' + encodeURIComponent(d.exp) + '/revocar';
      // Ratificar una heredada después de recibir el turno (solo con la orden marco con seguimiento).
      if (d.requiere_ratificacion && !b.traspaso && b.marco) {
        nodo.append(seguimientoAutorizado(b)
          ? el('button', { class: 'boton boton--chico', type: 'button', disabled: ocupado,
            on: { click: () => accion(k, '/api/juez/traspaso/ratificar', { dinamicas: [d.exp] }, 'Ratificó el seguimiento de ' + d.titulo + '.') } }, 'Ratificar este seguimiento')
          : el('p', { class: 'ayuda', text: 'Para ratificarlo, firme la orden marco con el seguimiento autorizado.' }));
      }
      // Frenar: un toque abre las dos salidas (frenar, o frenar y levantar lo ampliado). El motivo es opcional.
      const n = typeof d.ampliaciones === 'number' ? d.ampliaciones : 0;
      const revocar = (levantar) => accion(k, rutaRev, { motivo: f.motivo.trim(), levantar },
        levantar ? 'Seguimiento frenado y ' + MP.plural(n, 'ampliación levantada', 'ampliaciones levantadas') + ': ' + d.titulo + '.'
          : 'Seguimiento frenado: ' + d.titulo + '. Las próximas mudanzas vuelven a pedir su firma.');
      const form = el('div', { class: 'rechazo', hidden: !f.abierto },
        el('p', { class: 'nota', text: 'Frenar: las próximas mudanzas de este stream vuelven a pedir su firma; los bloqueos ya aplicados siguen.' +
          (n ? ' Frenar y levantar: además levanta, con su firma, los bloqueos que se ampliaron solos.' : '') }),
        el('div', { class: 'acciones__par' },
          el('button', { class: 'boton boton--peligro boton--ancho', type: 'button', disabled: ocupado, on: { click: () => revocar(false) } },
            ocupado ? 'Frenando…' : 'Frenar las próximas mudanzas'),
          n ? el('button', { class: 'boton boton--peligro boton--ancho', type: 'button', disabled: ocupado, on: { click: () => revocar(true) } },
            n === 1 ? 'Frenar y levantar la ampliación' : 'Frenar y levantar las ' + n + ' ampliaciones') : null),
        el('button', { class: 'boton boton--chico', type: 'button', on: { click: () => { f.abierto = false; form.hidden = true; abrir.hidden = false; } } }, 'Cancelar'),
        el('details', { class: 'opcional', open: !!f.motivo },
          el('summary', { text: 'Agregar un motivo (opcional)' }),
          el('div', { class: 'campo' }, el('label', { htmlFor: 'rev-' + k, class: 'rotulo', text: 'Motivo para frenar el seguimiento' }), motivo)));
      const abrir = el('button', { class: 'boton boton--chico boton--peligro', type: 'button', hidden: f.abierto,
        on: { click: () => { f.abierto = true; form.hidden = false; abrir.hidden = true; const c = form.querySelector('.boton--peligro'); if (c) c.focus(); } } }, 'Frenar el seguimiento');
      nodo.append(abrir, form, error);
    }
    return nodo;
  }

  function abrirRevocacion(exp) {
    const k = 'd:' + exp;
    const f = forma(k, { abierto: false, motivo: '' });
    f.abierto = true;
    const n = buscarTarjeta(k);
    if (!n) return;
    const form = n.querySelector('.rechazo');
    const boton = Array.from(n.children).find((x) => x.matches('button.boton--peligro'));
    if (form) form.hidden = false;
    if (boton) boton.hidden = true;
    n.scrollIntoView({ behavior: 'smooth', block: 'center' });
    const c = form && form.querySelector('.boton--peligro');
    if (c) setTimeout(() => c.focus({ preventScroll: true }), 300);
  }

  /* =============================================================== avisos */
  const TIPO_AVISO = {
    ampliacion_dinamica: { texto: 'Ampliación automática', tarjeta: 'verde' },
    orden_fallida: { texto: 'Falla de un proveedor', tarjeta: 'gris' },
    reintento: { texto: 'Reintento aplicado', tarjeta: 'gris' },
    reclamo: { texto: 'Reclamo', tarjeta: 'roja' },
    traspaso: { texto: 'Traspaso de turno', tarjeta: 'amarilla' },
    alerta: { texto: 'Alerta', tarjeta: 'gris' },
  };

  /* Agrupados (×N) y con `atendido`. Si el motor todavía no manda `atendido`, se deduce de lo que se ve. */
  const seguimientoActivo = (b, exp) => (b.dinamicas || []).some((d) => d.exp === exp && !d.revocada);
  function avisosDe(b) {
    const lista = MP.agruparAvisos(b.avisos || []).map((a) => {
      if (a.atendido !== undefined && a.atendido !== null) return a;
      let atendido = false;
      if (a.tipo === 'traspaso') atendido = !b.traspaso;
      else if (a.tipo === 'reclamo') atendido = !(b.reclamos || []).some((r) => String(a.texto || '').includes(r.dominio));
      else if (a.tipo === 'ampliacion_dinamica') atendido = !!a.exp && !seguimientoActivo(b, a.exp);
      return Object.assign({}, a, { atendido });
    });
    // Primero lo que pide una acción; después, del más nuevo al más viejo.
    return lista.map((a, i) => [a, i]).sort((x, y) => (MP.pideAccion(y[0]) - MP.pideAccion(x[0])) || x[1] - y[1]).map((x) => x[0]);
  }

  /* C3 (N7): un aviso atendido queda apagado, con el texto de cómo se cerró y sin botones. */
  function construirAviso(a) {
    const b = est.bandeja;
    const t = TIPO_AVISO[a.tipo] || { texto: MP.capital(a.tipo), tarjeta: 'gris' };
    // NV6: terminado el partido, un traspaso sin recibir ya no pide nada.
    const finSinRecibir = a.tipo === 'traspaso' && !a.atendido && !!b.reloj.finalizado;
    const accionPendiente = MP.pideAccion(a) && !finSinRecibir;
    const cierre = MP.cierreAviso(a);
    const puedeFrenar = !a.atendido && a.tipo === 'ampliacion_dinamica' && a.exp && seguimientoActivo(b, a.exp) && !b.reloj.finalizado;
    const veces = a.cuenta > 1 ? el('span', { class: 'aviso__veces num', attrs: { 'aria-label': a.cuenta + ' veces' }, text: '×' + a.cuenta }) : null;
    const cuando = a.cuenta > 1 && a.desde_min !== a.min ? 'del ' + MP.min(a.desde_min) + ' al ' + MP.minTxt(a.min) : MP.min(a.min);
    let estado = null;
    if (a.atendido) {
      estado = el('span', { class: 'estado estado--neutro' }, el('span', { attrs: { 'aria-hidden': 'true' }, text: '✓' }),
        a.tipo === 'traspaso' ? 'Ratificado' : 'Atendido');
    } else if (finSinRecibir) {
      estado = el('span', { class: 'estado estado--neutro', text: 'Terminó el partido sin recibir el turno' });
    } else if (MP.AVISOS_DE_ACCION.has(a.tipo)) {
      estado = el('span', { class: 'estado estado--alerta' }, el('span', { attrs: { 'aria-hidden': 'true' }, text: '!' }), 'Pide su decisión');
    }
    return el('article', { class: ['aviso', accionPendiente ? 'aviso--accion' : 'aviso--info', a.atendido && 'aviso--atendido'] },
      el('div', { class: 'aviso__cab' },
        el('span', { class: 'tarjeta tarjeta--' + (accionPendiente ? t.tarjeta : 'gris'), text: t.texto }),
        veces, estado,
        el('span', { class: 'aviso__min num', text: cuando })),
      el('p', { class: 'aviso__texto', text: a.texto }),
      a.atendido && cierre ? el('p', { class: 'aviso__cierre' }, el('span', { attrs: { 'aria-hidden': 'true' }, text: '✓ ' }), cierre) : null,
      puedeFrenar && b.turno.puede_firmar ? el('button', { class: 'boton boton--chico boton--peligro', type: 'button',
        on: { click: () => abrirRevocacion(a.exp) } }, 'Frenar el seguimiento') : null);
  }

  /* ============================================================ historial */
  /* «Lo que usted decidió»: firmas y rechazos, reclamos resueltos y traspasos ratificados, del más nuevo al más viejo. */
  function historialDe(b) {
    const items = [];
    const vistos = new Set();
    for (const h of b.historial || []) {
      const u = ubic(h);
      vistos.add(refDe(h));
      items.push({ k: 'h:' + refDe(h), tipo: 'u', min: u && u.decision ? u.decision.min : u && u.estado === 'sin_decidir' ? (u.sin_decidir_min || (b.reloj || {}).fin_min || 0) : 0, h });
    }
    // Si el motor deja lo «sin decidir» entre los pendientes, se muestra acá (sin botones), no como pedido.
    for (const p of b.pendientes || []) {
      if (!sinDecidir(p) || vistos.has(refDe(p))) continue;
      items.push({ k: 'h:' + refDe(p), tipo: 'u', min: ubic(p).sin_decidir_min || (b.reloj || {}).fin_min || 0, h: p });
    }
    for (const r of b.historial_reclamos || []) items.push({ k: 'hr:' + r.id, tipo: 'r', min: (r.resolucion || {}).min, r });
    for (const t of b.historial_traspasos || []) items.push({ k: 'ht:' + t.min, tipo: 't', min: (t.ratificado || {}).min, t });
    return items.sort((a, c) => (c.min || 0) - (a.min || 0));
  }
  function construirDecidido(x, k) {
    if (x.tipo === 'r') return construirReclamoResuelto(x.r);
    if (x.tipo === 't') return construirTraspasoRatificado(x.t);
    return construirHistorial(x.h, k);
  }

  const DECIDIO_RECLAMO = {
    levantar_y_reemplazar: ['verde', 'Reclamo resuelto', 'Levantar y reemplazar'],
    levantar: ['verde', 'Reclamo resuelto', 'Levantar'],
    desestimar: ['gris', 'Reclamo desestimado', 'Desestimar'],
  };
  function construirReclamoResuelto(r) {
    const res = r.resolucion || {};
    const d = DECIDIO_RECLAMO[res.accion] || ['gris', 'Reclamo cerrado', MP.capital(res.accion)];
    const junto = r.cerrados_junto || [];
    const reemplazos = (res.ordenes_reemplazo || []).length;
    return el('article', { class: 'foja foja--firmada foja--decidido', attrs: { 'aria-label': 'Reclamo ' + r.id } },
      el('header', { class: 'foja__cabeza' },
        el('span', { class: 'tarjeta tarjeta--' + d[0], text: d[1] }),
        el('span', { class: 'foja__ref mono', text: r.id }),
        el('span', { class: 'foja__hora num', text: MP.min(res.min) })),
      el('h3', { class: 'firmada__host cortar', text: r.dominio }),
      el('p', { class: 'ayuda', text: 'Reclamó en el ' + MP.min(r.minuto) + (r.proveedor_nombre ? ' vía ' + MP.sinParentesis(r.proveedor_nombre) : '') + '.' }),
      el('p', { class: 'firmada__decision' }, 'Decidió ', el('strong', { text: '«' + d[2] + '»' }), ' en el ' + MP.min(res.min) +
        (res.minutos_hasta_resolver !== null && res.minutos_hasta_resolver !== undefined ? ', ' + MP.dur(res.minutos_hasta_resolver) + ' después del reclamo' : '') + '.'),
      reemplazos ? el('p', { class: 'ayuda', text: MP.plural(reemplazos, 'orden de reemplazo salió', 'órdenes de reemplazo salieron') + ' a los proveedores.' }) : null,
      junto.length ? el('p', { class: 'ayuda' }, 'Cerró también ' + MP.plural(junto.length, 'reclamo', 'reclamos') + ' por el mismo bloqueo: ',
        el('span', { class: 'mono', text: junto.join(', ') }), '.') : null,
      res.fundamento ? el('p', { class: 'ayuda', text: 'Fundamento: ' + res.fundamento }) : null);
  }

  function construirTraspasoRatificado(t) {
    const r = t.resumen || {};
    const rat = t.ratificado || {};
    const de = (t.de || []).map((x) => x.nombre).join(', ');
    const recibio = [
      MP.plural(r.bloqueos_vigentes, 'bloqueo vigente', 'bloqueos vigentes'),
      MP.plural((r.dinamicas || []).length, 'filtración en seguimiento', 'filtraciones en seguimiento'),
      MP.plural(r.ordenes_en_espera, 'orden en espera', 'órdenes en espera'),
      MP.plural(r.ubicaciones_pendientes, 'pedido pendiente', 'pedidos pendientes'),
      MP.plural(r.reclamos_pendientes, 'reclamo pendiente', 'reclamos pendientes'),
    ];
    const lev = r.levantamientos_pendientes || [];
    // Propuesta de la API simulada (no está en el contrato): qué dinámicas ratificó. Sin ese dato, el texto de antes.
    const porUna = Array.isArray(t.dinamicas_ratificadas);
    const titulos = new Map((r.dinamicas || []).map((d) => [d.exp, d.titulo]));
    const ratificadas = porUna ? t.dinamicas_ratificadas.map((x) => titulos.get(x) || x) : [];
    const sinRatificar = porUna ? (t.dinamicas_sin_ratificar || []).map((x) => titulos.get(x) || x) : [];
    return el('article', { class: 'foja foja--firmada foja--decidido', attrs: { 'aria-label': 'Traspaso del ' + MP.min(t.min) } },
      el('header', { class: 'foja__cabeza' },
        el('span', { class: 'tarjeta tarjeta--verde', text: 'Ratificado' }),
        el('span', { class: 'foja__ref', text: 'Cambio de turno · ' + MP.min(t.min) }),
        el('span', { class: 'foja__hora num', text: MP.min(rat.min) })),
      el('h3', { class: 'firmada__host', text: (porUna ? 'Recibió el turno' : 'Ratificó lo heredado') + (de ? ' de ' + de : '') }),
      el('p', { class: 'firmada__decision', text: 'En el ' + MP.min(rat.min) + (rat.entrada !== null && rat.entrada !== undefined ? ' (entrada ' + rat.entrada + ')' : '') +
        '. ' + (!porUna ? 'Los seguimientos heredados quedaron bajo su firma.'
          : ratificadas.length ? ((r.dinamicas || []).length === 1 ? 'Ratificó el seguimiento heredado: '
            : 'Ratificó ' + MP.num(ratificadas.length, 0) + ' de ' + MP.plural((r.dinamicas || []).length, 'seguimiento heredado', 'seguimientos heredados') + ': ') +
            ratificadas.join(', ') + '.'
            : (r.dinamicas || []).length ? 'No ratificó ningún seguimiento heredado: recibió el turno sin seguimiento.' : 'No había seguimientos para ratificar.') }),
      porUna && sinRatificar.length && ratificadas.length ? el('p', { class: 'ayuda', text: 'Quedaron sin seguimiento: ' + sinRatificar.join(', ') + '.' }) : null,
      el('p', { class: 'ayuda', text: 'Recibió: ' + recibio.join(' · ') + '.' }),
      lev.length ? el('div', { class: 'nota nota--espera' },
        el('strong', { text: MP.plural(lev.length, 'levantamiento quedó', 'levantamientos quedaron') + ' por enviar:' }),
        el('ul', { class: 'causantes' }, lev.map((x) => el('li', {},
          el('strong', { text: MP.sinParentesis(nombreProv(x.proveedor)) }), ' · ', el('span', { class: 'mono cortar', text: x.objetivo || '' }),
          x.reclamo ? el('span', { class: 'ayuda', text: ' · reclamo ' + x.reclamo }) : null)))) : null);
  }

  /* Una línea por orden, cada una con su estado: después de un reclamo se ve la orden por IP levantada y
     el reemplazo por dominio, no un solo estado por proveedor. */
  function detalleOrden(o) {
    const partes = [];
    if (o.origen === 'reemplazo_reclamo') partes.push('Reemplazo por dominio' + (o.reclamo ? ' · reclamo ' + o.reclamo : ''));
    else if (o.origen === 'reintento') partes.push('Reintento n.º ' + o.intento);
    if (o.estado === 'levantada') {
      const lev = o.levantamiento || {};
      const reclamo = lev.reclamo || ((/Reclamo (R-\d+)/.exec(o.motivo || '') || [])[1]);
      partes.push(MP.min(lev.min !== undefined && lev.min !== null ? lev.min : o.finalizada_min) + (reclamo ? ' · reclamo ' + reclamo : ''));
    } else if (o.estado === 'aplicada' && o.aplicada_min !== null && o.recibida_min !== null && o.aplicada_min !== undefined) {
      partes.push('en ' + MP.dur(o.aplicada_min - o.recibida_min));
    } else if (o.estado === 'vencida') partes.push('venció en el ' + MP.min(o.finalizada_min));
    else if (o.estado === 'fallida') partes.push('el proveedor informó una falla');
    return partes.join(' · ');
  }

  function construirSinDecidir(exp, u) {
    return el('article', { class: 'foja foja--firmada foja--sin-decidir', attrs: { 'aria-label': 'Sin decidir ' + u.ref } },
      el('header', { class: 'foja__cabeza' },
        el('span', { class: 'tarjeta tarjeta--gris', text: 'Sin decidir' }),
        el('span', { class: 'foja__ref mono', text: exp.id + ' · U' + u.n })),
      el('h3', { class: 'firmada__host cortar', text: u.host }),
      el('p', { class: 'ayuda' }, (exp.sitio || exp.titulo || '') + ' · ', el('span', { class: 'mono', text: u.ip || '' })),
      el('p', { class: 'firmada__decision', text: u.motivo_sin_decidir || 'El partido terminó antes de que se decidiera: ya no se pueden firmar órdenes.' }),
      el('p', { class: 'ayuda', text: 'No salió ninguna orden para este servidor.' }));
  }

  function construirHistorial(h, k) {
    const b = est.bandeja;
    const exp = h.expediente;
    const u = ubic(h);
    if (u && u.estado === 'sin_decidir') return construirSinDecidir(exp, u);
    const d = u.decision || {};
    const ordenes = u.ordenes || [];
    // C12: después del final nada sigue «en curso» ni «aplicado»: todo venció con el partido (o se levantó).
    const terminado = !!(b && b.reloj && b.reloj.finalizado);
    const activas = !terminado && ordenes.some((o) => !MP.noEnviada(o) && ['por_enviar', 'recibida', 'aplicada', 'espera_ratificacion'].includes(o.estado));
    const aplicadas = !terminado && ordenes.some((o) => o.estado === 'aplicada');
    let tarjeta;
    const fin = MP.finDeBloqueo(ordenes, terminado);
    if (!d.aprobada) tarjeta = ['roja', 'Rechazado'];
    else if (aplicadas) tarjeta = ['verde', 'Bloqueo aplicado'];
    else if (activas) tarjeta = ['amarilla', 'En curso'];
    else if (MP.nuncaSalio(ordenes)) tarjeta = ['gris', MP.causaNuncaSalio(ordenes).rotulo === 'Sin confirmar' ? 'Sin confirmar' : 'Sin bloquear'];  // nunca salió
    else if (fin === 'levantada') tarjeta = ['gris', 'Levantado'];        // C4/C12: no «Finalizado»
    else if (fin === 'vencida') tarjeta = ['gris', 'Venció con el partido'];
    else tarjeta = ['gris', 'Finalizado'];
    const nuevo = est.sellosVistos !== null && d.sello && !est.sellosVistos.has(d.sello);
    if (d.sello && est.sellosVistos) est.sellosVistos.add(d.sello);
    const esAmpliacion = d.tipo === 'ampliacion_dinamica';
    let texto;
    if (!d.aprobada) texto = 'Rechazó en el ' + MP.min(d.min) + '. Motivo: ' + (d.motivo_rechazo || '—');
    else if (esAmpliacion) {
      // El texto lo redacta el motor (ronda 2b ya dice «No se firmó en persona.»): no se repite.
      texto = MP.textoAmpliacion(d);
      if (!/no se firmó en persona/i.test(texto)) texto += ' No se firmó en persona.';
    } else texto = 'Firmó en persona en el ' + MP.min(d.min) + ' · ' + (d.alcance === 'filtracion' && exp.dinamica ? 'con seguimiento de la filtración' : 'solo este servidor') + '.';
    const c = u.cobertura || {};
    const f = forma(k, { abierto: false, motivo: '' });
    const ocupado = est.ocupado.has(k);

    const nodo = el('article', { class: ['foja', 'foja--firmada', !d.aprobada && 'foja--rechazada'], attrs: { 'aria-label': 'Decisión ' + u.ref } },
      el('header', { class: 'foja__cabeza' },
        el('span', { class: 'tarjeta tarjeta--' + tarjeta[0], text: tarjeta[1] }),
        el('span', { class: 'foja__ref mono', text: exp.id + ' · U' + u.n })),
      el('div', { class: 'firmada' },
        el('div', { class: 'firmada__texto' },
          el('h3', { class: 'firmada__host cortar', text: u.host }),
          el('p', { class: 'ayuda' }, (exp.sitio || exp.titulo) + ' · ', el('span', { class: 'mono', text: u.ip })),
          el('p', { class: 'firmada__decision', text: texto }),
          d.forzado ? el('p', { class: 'nota nota--alerta' }, el('strong', { text: 'Se apartó de la recomendación (' + MP.tipoBloqueo(d.forzado.tipo) + '). ' }), d.forzado.fundamento || '') : null),
        d.sello ? MP.sello({ titulo: !d.aprobada ? 'Rechazado' : esAmpliacion ? 'Ampliado' : 'Firmado', codigo: d.sello,
          pie: MP.min(d.min), rechazo: !d.aprobada, nuevo }) : null));

    if (d.aprobada) {
      // Agrupadas por proveedor solo para no repetir el nombre; cada orden lleva su propio estado.
      const porProv = new Map();
      for (const o of ordenes) { if (!porProv.has(o.proveedor)) porProv.set(o.proveedor, []); porProv.get(o.proveedor).push(o); }
      nodo.append(el('ul', { class: 'proveedores' }, [...porProv].map(([prov, lista]) => el('li', { class: 'proveedor' },
        el('span', { class: 'proveedor__nombre', text: MP.sinParentesis(lista[0].proveedor_nombre || nombreProv(prov)) }),
        el('ul', { class: 'proveedor__ordenes' }, lista.map((o) => {
          const det = MP.noEnviada(o) ? MP.causaNoEnviada(o).texto : detalleOrden(o);  // g-despacho-1: la causa
          return el('li', { class: ['orden-linea', ['levantada', 'vencida', 'fallida'].includes(o.estado) && 'orden-linea--terminada'] },
            MP.estadoOrden(MP.noEnviada(o) ? (MP.causaNoEnviada(o).clave === 'confirmar' ? 'sin_confirmar' : 'no_enviada') : o.estado),
            el('span', { class: 'objetivo' }, el('span', { class: 'objetivo__tipo', text: MP.tipoBloqueo(o.tipo) }), el('span', { class: 'mono cortar', text: o.objetivo })),
            det ? el('span', { class: 'orden-linea__detalle ayuda', text: det }) : null);
        }))))));
      const cob = MP.cobertura(c);
      nodo.append(cob.sinVentana
        ? el('p', { class: 'cobertura' },
          el('strong', { class: 'num', text: '—' }), ' de los clientes cubiertos · primer bloqueo — · visibilidad residual —',
          el('span', { class: 'ayuda', text: ' (no hubo tiempo para medir esta ubicación)' }))
        : el('p', { class: 'cobertura' },
          el('strong', { class: 'num', text: MP.pct(cob.cubiertos) }), ' de los clientes cubiertos',
          cob.primer !== null ? ' · primer bloqueo a los ' + MP.dur(cob.primer) : '',
          cob.completo !== null ? ' · completo a los ' + MP.dur(cob.completo) : ''));
      if ((d.ya_cubiertos || []).length) {
        nodo.append(el('p', { class: 'ayuda', text: 'Ya estaban cubiertos por otra orden: ' + d.ya_cubiertos.map((x) => MP.sinParentesis(nombreProv(x.proveedor)) + ' (' + x.objetivo + ')').join(', ') + '.' }));
      }
    }

    if (activas && b.turno.puede_firmar) {
      const motivo = el('textarea', { class: 'entrada', id: 'lev-' + k, rows: 2, value: f.motivo, dataset: { campo: 'motivo' },
        on: { input: (e) => { f.motivo = e.target.value; } } });
      const error = el('p', { class: 'error-campo', attrs: { role: 'alert' }, hidden: !f.error, text: f.error });
      const form = el('div', { class: 'rechazo', hidden: !f.abierto },
        el('div', { class: 'campo' }, el('label', { htmlFor: 'lev-' + k, class: 'rotulo', text: 'Motivo del levantamiento (obligatorio)' }), motivo),
        el('div', { class: 'fila-botones' },
          el('button', { class: 'boton boton--peligro', type: 'button', disabled: ocupado, on: { click: () => {
            if (f.motivo.trim().length < 3) return mostrarError(nodo, f, 'Escriba el motivo del levantamiento.');
            accion(k, rutaUbic(exp, u, 'levantar'), { motivo: f.motivo.trim() }, 'Bloqueo levantado: ' + u.host + '.');
          } } }, 'Confirmar levantamiento'),
          el('button', { class: 'boton', type: 'button', on: { click: () => { f.abierto = false; form.hidden = true; abrir.hidden = false; } } }, 'Cancelar')));
      const abrir = el('button', { class: 'boton boton--chico', type: 'button', hidden: f.abierto,
        on: { click: () => { f.abierto = true; form.hidden = false; abrir.hidden = true; motivo.focus(); } } }, 'Levantar bloqueo');
      nodo.append(el('div', { class: 'firmada__acciones' }, abrir, form, error));
    }
    return nodo;
  }

  /* ============================================================= acciones */
  async function accion(k, ruta, cuerpo, exito) {
    if (est.ocupado.has(k)) return;
    est.ocupado.add(k);
    const f = forma(k);
    f.error = '';
    if (est.bandeja) pintar(est.bandeja, true);
    try {
      const r = await MP.api('POST', ruta, cuerpo);
      est.ocupado.delete(k);
      est.formas.delete(k);
      if (r && r.bandeja) { pintar(r.bandeja); if (est.vig) est.vig.adoptar(r.bandeja.v); }
      // Ronda 2b: ratificar puede devolver un aviso (por ejemplo, sin orden marco con seguimiento). turnos-2:
      // «Levantar bloqueo» y «Frenar y levantar» avisan qué bloqueo se mantiene porque otra ubicación lo necesita.
      if (r && r.aviso) MP.avisar(r.aviso, 'alerta', 15);
      else MP.avisar((typeof exito === 'function' ? exito(r) : exito), 'ok');
    } catch (e) {
      est.ocupado.delete(k);
      if (e.codigo === 'no_autenticado') return mostrarIngreso('Su sesión terminó. Vuelva a ingresar.');
      /* pantallas-1: el motor contesta «fuera_de_turno» también por causas que se arreglan solas (simulador caído o
         lento, «su turno empieza en segundos»). Ningún error pasajero cambia lo que se va a firmar: la elección, el
         fundamento, el motivo y la causal se conservan y el error queda en la tarjeta. Si el turno terminó de verdad,
         la tarjeta se va con la próxima bandeja. */
      if (e.codigo === 'fuera_de_turno') {
        MP.avisar(e.texto, 'alerta', 7);
        f.error = e.texto || 'No puede firmar ahora: vuelva a intentar.';
        if (est.bandeja) pintar(est.bandeja, true);
        if (est.vig) est.vig.refrescar();
        return;
      }
      // El pedido de verdad cambió (ya decidido, no existe, partido terminado): el formulario viejo se descarta.
      if (e.codigo === 'partido_finalizado' || e.codigo === 'conflicto' || e.codigo === 'no_encontrado') {
        MP.avisar(e.texto, 'alerta', 7);
        est.formas.delete(k);
        if (est.vig) est.vig.refrescar();
        return;
      }
      f.error = e.texto || 'No se pudo completar la acción.';
      if (e.codigo === 'sin_conexion') f.error = 'Sin conexión con la plataforma: la acción no se envió. Vuelva a intentar.';
      if (est.bandeja) pintar(est.bandeja, true);
    }
  }

  /* ===================================================== avisos de pedido nuevo */
  function detectarNuevos(b) {
    const claves = new Set();
    for (const p of pendientesDe(b)) claves.add('u:' + refDe(p));
    for (const r of b.reclamos || []) claves.add('r:' + r.id);
    if (b.traspaso) claves.add('t:' + b.traspaso.min);
    const cant = claves.size;
    // N17: mientras haya una ampliación automática sin atender, el título lo dice. Un pedido nuevo manda
    // (titila por encima); los atendidos no cuentan (C3).
    const amps = avisosDe(b).filter((a) => a.tipo === 'ampliacion_dinamica' && !a.atendido);
    est.tituloPlano = (cant ? '(' + cant + ') ' : '') + 'Bandeja del juez — Marca Personal';
    est.tituloBase = amps.length ? (cant ? '(' + cant + ') ' : '') + '● Ampliación automática: ' + hostDeAviso(b, amps[0]) : est.tituloPlano;
    if (!titila) document.title = est.tituloBase;
    if (!cant) dejarDeTitilar();
    if (est.pendientesVistos !== null) {
      const nuevos = [...claves].filter((c) => !est.pendientesVistos.has(c));
      if (nuevos.length) alertar(nuevos, b);
    }
    est.pendientesVistos = claves;
    // Cada ampliación automática se le avisa en el momento, una vez por aviso nuevo (no pide acción, pero puede
    // frenarla): mismo sonido y vibración que un pedido nuevo.
    const vistas = est.ampliacionesVistas;
    const claveAmp = (a) => (a.clave || a.n) + '|' + (a.cuenta || 1);
    est.ampliacionesVistas = new Set((vistas ? [...vistas] : []).concat(amps.map(claveAmp)));
    if (vistas !== null) {
      const nueva = amps.find((a) => !vistas.has(claveAmp(a)));
      if (nueva) {
        MP.avisar('Ampliación automática: ' + nueva.texto, 'espera', 8);
        if (est.avisosActivos) {
          sonar();
          if (navigator.vibrate) { try { navigator.vibrate([140, 70, 140]); } catch (e) { /* sin vibración */ } }
        }
      }
    }
  }

  /* El servidor al que se amplió: `ubicacion` del aviso (motor ronda 3) o la última ampliación de ese expediente. */
  function hostDeAviso(b, a) {
    if (a.host) return a.host;
    const exps = (b.historial || []).map((h) => h.expediente).filter((x) => x && x.id === a.exp);
    const ubs = exps.length ? (exps[0].ubicaciones || []) : [];
    let u = a.ubicacion !== undefined && a.ubicacion !== null ? ubs.find((x) => x.n === a.ubicacion) : null;
    if (!u) {
      const amp = ubs.filter((x) => (x.decision || {}).tipo === 'ampliacion_dinamica');
      u = amp[amp.length - 1];
    }
    if (u && u.host) return u.host;
    const d = (b.dinamicas || []).find((x) => x.exp === a.exp);
    return d ? d.titulo : (a.exp || 'un servidor');
  }

  function alertar(nuevos, b) {
    let texto;
    const pedido = nuevos.find((c) => c.startsWith('u:'));
    if (nuevos.some((c) => c.startsWith('r:'))) texto = 'Reclamo nuevo por daño colateral.';
    else if (nuevos.some((c) => c.startsWith('t:'))) texto = 'Recibe el turno: revise lo heredado.';
    else {
      const p = (b.pendientes || []).find((x) => 'u:' + refDe(x) === pedido);
      texto = 'Pedido nuevo: ' + (p ? ubic(p).host : 'un servidor') + '.';
    }
    MP.avisar(texto, 'espera', 6);
    const quieto = !est.toque || performance.now() - est.toque.t > 15000;
    if (document.visibilityState !== 'visible' || quieto) titilar(texto);
    // El único pedido pendiente, con el juez sin tocar ni escribir: la pantalla lo trae a la vista (el ancla del
    // repintado lo dejaría fuera, arriba). Con otros pedidos abiertos no se mueve: puede estar leyendo uno.
    const escribiendo = document.activeElement && document.activeElement.dataset && document.activeElement.dataset.campo;
    if (pedido && quieto && !escribiendo && pendientesDe(b).length === 1) {
      // Después del repintado (que corrige el ancla al terminar). setTimeout y no requestAnimationFrame: con la
      // pantalla oculta no hay cuadros, y al volver el pedido tiene que estar a la vista. Salto directo, no suave:
      // el repintado de cada segundo corta una animación a medias.
      setTimeout(() => {
        const n = buscarTarjeta(pedido);
        if (!n) return;
        const fijo = app.querySelector('.tablero');
        const tope = fijo ? fijo.getBoundingClientRect().bottom : 0;
        window.scrollTo({ top: Math.max(0, window.scrollY + n.getBoundingClientRect().top - tope - 76), behavior: 'auto' });
      });
    }
    if (!est.avisosActivos) return;
    sonar();
    if (navigator.vibrate) { try { navigator.vibrate([140, 70, 140]); } catch (e) { /* sin vibración */ } }
    if ('Notification' in window && Notification.permission === 'granted' && document.visibilityState !== 'visible') {
      try { new Notification('Marca Personal', { body: texto, tag: 'marca-personal-bandeja' }); } catch (e) { /* sin notificación */ }
    }
  }

  function sonar() {
    const ctx = est.audio;
    if (!ctx) return;
    if (ctx.state === 'suspended') ctx.resume();
    const t0 = ctx.currentTime + 0.01;
    [[880, 0], [1175, 0.16]].forEach(([frec, ini]) => {
      const o = ctx.createOscillator();
      const g = ctx.createGain();
      o.type = 'sine';
      o.frequency.value = frec;
      g.gain.setValueAtTime(0.0001, t0 + ini);
      g.gain.exponentialRampToValueAtTime(0.25, t0 + ini + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, t0 + ini + 0.14);
      o.connect(g).connect(ctx.destination);
      o.start(t0 + ini);
      o.stop(t0 + ini + 0.16);
    });
  }

  /* Sonido (WebAudio) y, si el navegador lo permite, notificación y pantalla encendida. Con el primer toque
     se activa en silencio; el botón «Activar sonido» además lo hace sonar para probarlo. */
  async function activarAvisos(opciones) {
    const silencioso = !!(opciones && opciones.silencioso);
    try {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (AC && !est.audio) est.audio = new AC();
      if (est.audio && est.audio.state === 'suspended') await est.audio.resume();
    } catch (e) { est.audio = null; }
    est.avisosActivos = !!est.audio;
    if (!silencioso) {
      sonar();
      if (navigator.vibrate) { try { navigator.vibrate(60); } catch (e) { /* nada */ } }
      if ('Notification' in window && window.isSecureContext && Notification.permission === 'default') {
        try { await Notification.requestPermission(); } catch (e) { /* el navegador no lo permite */ }
      }
    }
    pedirPantalla();
    ponerEstadoAvisos();
  }

  arrancar();
})();
