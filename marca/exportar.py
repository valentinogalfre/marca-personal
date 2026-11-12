"""Exporta expedientes, auditoría, testigos de los proveedores y acta del partido."""
from __future__ import annotations

import json
import secrets
import shutil
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

from . import VERSION, evidencia
from .marco import a_texto, texto_ampliacion as leyenda_ampliacion
from .canon import hora_de_partido, min_txt, nombre_captura, r3, sha256_hex, utc_ahora

CAMPOS_INTERNOS = ("en_vuelo", "incierta", "t_error", "levantar", "t_post", "post_timeout", "t_confirmada", "n_404",
                   "intentos_inciertos", "motivo_incierta", "lev_incierto", "lev_enviado")
MANIFIESTO = "MANIFIESTO.json"
# Archivos que el sistema operativo crea solo al abrir la carpeta: no cuentan como alteración.
IGNORAR = {".DS_Store", "Thumbs.db", "desktop.ini"}


def archivos_del_paquete(destino) -> List[Path]:
    destino = Path(destino)
    return sorted((p for p in destino.rglob("*") if p.is_file() and p.name not in IGNORAR
                   and p.relative_to(destino).as_posix() != MANIFIESTO),
                  key=lambda p: p.relative_to(destino).as_posix())


def escribir_manifiesto(destino) -> str:
    """MANIFIESTO.json: ruta, tamaño y sha256 de cada archivo del paquete. Devuelve la huella del paquete."""
    destino = Path(destino)
    archivos = []
    for p in archivos_del_paquete(destino):
        datos = p.read_bytes()
        archivos.append({"ruta": p.relative_to(destino).as_posix(), "bytes": len(datos), "sha256": sha256_hex(datos)})
    # Sin hora de generación (C20): la misma salida exporta siempre la misma huella.
    doc = {"version": 1, "plataforma": VERSION, "archivos": archivos}
    crudo = (json.dumps(doc, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    tmp = destino / (MANIFIESTO + ".tmp")
    tmp.write_bytes(crudo)
    tmp.replace(destino / MANIFIESTO)
    return sha256_hex(crudo)


def huella_paquete(destino) -> Optional[str]:
    ruta = Path(destino) / MANIFIESTO
    return sha256_hex(ruta.read_bytes()) if ruta.exists() else None


def escribir_testigos(salida, simulador: str, minuto: float, listas: Dict[str, list],
                      auditar: Callable[[str, dict], dict]) -> dict:
    """Escribe <salida>/testigos/proveedores.json y deja la entrada testigos_guardados con su sha256."""
    carpeta = Path(salida) / "testigos"
    carpeta.mkdir(parents=True, exist_ok=True)
    doc = {"consultado_min": r3(minuto), "consultado_utc": utc_ahora(), "simulador": simulador,
           "proveedores": listas}
    datos = json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True).encode("utf-8")
    ruta = carpeta / "proveedores.json"
    tmp = ruta.with_name(ruta.name + ".tmp")
    tmp.write_bytes(datos)
    tmp.replace(ruta)
    return auditar("testigos_guardados", {
        "archivo": "testigos/proveedores.json", "sha256": sha256_hex(datos), "consultado_min": doc["consultado_min"],
        "ordenes_por_proveedor": {pid: len(v or []) for pid, v in listas.items()}})


NO_ENVIADA_RATIFICACION = "no enviada (el juez entrante no recibió el turno)"
SIN_CONFIRMAR_AL_CIERRE = "sin confirmar (se envió y, al cierre, el proveedor no la tenía)"
NO_ENVIADA_FINAL = "no enviada (el partido terminaba)"


def estado_legible(o: dict) -> str:
    """El estado de una orden como lo lee el jurado. Una orden que ya no salió (no_enviada) no es una orden trabada
    «por_enviar» (f-desconocido-1), y el acta dice por qué no salió (g-despacho-1): esperaba que el juez entrante
    ratificara el turno, se mandó y el proveedor nunca la tuvo, o la cortó el margen del final."""
    est = o.get("estado")
    if o.get("no_enviada") and est in ("por_enviar", "espera_ratificacion"):
        if est == "espera_ratificacion":
            return NO_ENVIADA_RATIFICACION
        if o.get("enviada_min") is not None:
            return SIN_CONFIRMAR_AL_CIERRE
        return NO_ENVIADA_FINAL
    return str(est)


def _orden_exportable(o: dict) -> dict:
    return {k: v for k, v in o.items() if k not in CAMPOS_INTERNOS}


# Versión de los .md: verificar los vuelve a generar desde los .json y los compara. 3 = ronda 3 (minutos con
# canon.min_txt, leyenda de la ampliación de marco.texto_ampliacion, «seguimiento frenado»).
FORMATO = 3
ESTADOS_RETIRADOS = ("levantada", "vencida", "fallida", "rechazada", "perdida")


def _ventana(ubicaciones: List[dict], u: dict, ahora: float, fin: float):
    """La ventana de una ubicación la calcula un solo lugar: evidencia.ventana (adenda 3, A)."""
    return evidencia.ventana(ubicaciones, u, ahora, fin)


def tiempos_ubicacion(u: dict, proveedores: List[dict]) -> dict:
    """Los tres tiempos de una ubicación (sección 8): detección, firma, primer proveedor y todos los proveedores."""
    dec = u.get("decision") or {}
    firma = dec.get("min") if dec.get("aprobada") else None
    primero_por_prov: Dict[str, float] = {}
    for o in u.get("ordenes") or []:
        if o.get("aplicada_min") is not None:
            pid = o.get("proveedor")
            primero_por_prov[pid] = min(primero_por_prov.get(pid, 1e18), float(o["aplicada_min"]))
    ids = [p.get("id") for p in proveedores or []]
    todos = max(primero_por_prov.values()) if ids and all(i in primero_por_prov for i in ids) else None
    abierto = None
    if dec.get("aprobada") and dec.get("tipo") == "firma" and u.get("vista_min") is not None and firma is not None:
        abierto = r3(max(0.0, float(firma) - float(u["vista_min"])))
    tipo = None
    if dec.get("aprobada"):
        tipo = "ampliacion" if dec.get("tipo") == "ampliacion_dinamica" else "en_persona"
    return {"deteccion_min": u.get("primera_deteccion_min"), "firma_min": firma,
            "primer_proveedor_min": min(primero_por_prov.values()) if primero_por_prov else None,
            "todos_los_proveedores_min": todos, "expediente_abierto_min": abierto, "tipo": tipo}


def armar_expedientes(estado: dict) -> List[dict]:
    """Expedientes completos (con el bloque sellado, las órdenes y los tiempos de cada ubicación)."""
    ordenes = list(estado.get("ordenes", {}).values())
    proveedores = estado.get("proveedores") or []
    fin = float(estado["partido"]["fin_min"])
    ahora = float(estado.get("minuto") or fin)
    salida = []
    for exp in estado.get("expedientes") or []:
        e = {k: v for k, v in exp.items() if k != "ubicaciones"}
        e["ubicaciones"] = []
        for u in exp["ubicaciones"]:
            desde, hasta = _ventana(exp["ubicaciones"], u, ahora, fin)
            uu = {k: v for k, v in u.items() if k not in ("contadores",)}
            uu["ordenes"] = [_orden_exportable(o) for o in ordenes if o["exp"] == exp["id"] and o["n"] == u["n"]]
            uu["redetecciones"] = list(u["detecciones"][1:])
            uu["cobertura"] = evidencia.cobertura(desde, hasta, u["ip"], u["host"], ordenes, proveedores)
            uu["ventana"] = [r3(desde), r3(hasta)]
            uu["tiempos"] = tiempos_ubicacion(uu, proveedores)
            e["ubicaciones"].append(uu)
        salida.append(e)
    return salida


def armar_marcos(entradas: List[dict], expedientes: List[dict], partido: dict) -> List[dict]:
    """orden-marco/OM-xx.json: sale de las entradas orden_marco de la auditoría, con las ampliaciones hechas bajo cada una."""
    marcos = []
    for e in entradas:
        if e.get("tipo") != "orden_marco":
            continue
        d = e.get("datos") or {}
        c = d.get("contenido") or {}
        juez = c.get("juez") or {}
        marcos.append({"id": d.get("id"), "entrada": e.get("n"), "min": e.get("min"), "utc": e.get("utc"),
                       "hora": hora_de_partido(partido.get("inicio_iso"), e.get("min")),
                       "juez_id": d.get("juez_id"), "juez": juez.get("nombre"),
                       "juzgado_id": d.get("juzgado_id"), "juzgado": juez.get("juzgado"),
                       "huella": d.get("huella"), "seguimiento": bool(d.get("seguimiento")),
                       "contenido": c, "firma": d.get("firma"), "reemplaza": d.get("reemplaza"),
                       "reemplazada_por": None, "ampliaciones": []})
    for m in marcos:
        siguientes = [x for x in marcos if x["juez_id"] == m["juez_id"] and (x["entrada"] or 0) > (m["entrada"] or 0)]
        if siguientes:
            m["reemplazada_por"] = min(siguientes, key=lambda x: x["entrada"])["id"]
    por_entrada = {m["entrada"]: m for m in marcos}
    for e in entradas:
        if e.get("tipo") == "ampliacion_dinamica":
            om = (e.get("datos") or {}).get("orden_marco") or {}
            m = por_entrada.get(om.get("entrada"))
            if m is not None:
                m["ampliaciones"].append({"exp": e.get("exp"), "ubicacion": (e.get("datos") or {}).get("ubicacion"),
                                          "min": e.get("min"), "entrada": e.get("n")})
    for m in marcos:
        m["vigente"] = m["reemplazada_por"] is None
    return marcos


# --- textos legibles (siempre generados desde los .json: verificar los regenera y compara) -------------


def _m(x) -> str:
    """Minutos y porcentajes: un decimal, con coma. Un solo redondeo en toda la plataforma: canon.min_txt (C8)."""
    return min_txt(x)


def _pct(x) -> str:
    return "—" if x is None else f"{_m(x)} %"


def _sin_ventana(c: dict) -> bool:
    return bool(c.get("sin_ventana")) or c.get("visibilidad_residual_pct") is None


def contexto(resumen: dict, expedientes: List[dict], marcos: List[dict]) -> dict:
    """Lo que necesitan los .md, tomado solo de lo exportado (resumen.json, expedientes y órdenes marco)."""
    jueces: Dict[str, str] = {}
    for m in marcos:
        if m.get("juez_id") and m.get("juez"):
            jueces[m["juez_id"]] = m["juez"]
    for exp in expedientes:
        d = exp.get("dinamica") or {}
        for x in [d.get("otorgada_por") or {}] + list(d.get("ratificaciones") or []):
            if x.get("juez_id") and x.get("nombre"):
                jueces[x["juez_id"]] = x["nombre"]
        for u in exp.get("ubicaciones") or []:
            dec = u.get("decision") or {}
            if dec.get("juez_id") and dec.get("juez"):
                jueces[dec["juez_id"]] = dec["juez"]
    return {"partido": resumen.get("partido") or {}, "proveedores": resumen.get("proveedores") or [],
            "jueces": jueces, "marcos": marcos, "marcos_por_entrada": {m.get("entrada"): m for m in marcos},
            "resumen": resumen}


def _alcance(alcance) -> str:
    return {"filtracion": "sigue a la filtración", "ubicacion": "solo este servidor"}.get(alcance, str(alcance))


def _continuidad(c: dict) -> str:
    if c.get("criterio") == "misma_marca":
        return f"misma marca de agua que la ubicación {c.get('de_ubicacion')}"
    return f"continúa la ubicación {c.get('de_ubicacion')}"


def _sin_decidir(u: dict) -> str:
    motivo = str(u.get("motivo_sin_decidir") or "El partido terminó antes de la decisión.")
    frase = motivo.split(":")[0].strip().rstrip(".")
    return "sin decidir — " + (frase[:1].lower() + frase[1:])


def _nombre_y_min(x) -> Optional[dict]:
    x = x if isinstance(x, dict) else {}
    return {"nombre": x.get("nombre"), "min": x.get("min")} if x else None


def texto_ampliacion(exp: dict, u: dict, ctx: dict) -> str:
    """La leyenda de la ampliación sale de un solo lugar, marca.marco.texto_ampliacion (ronda 3, C7). Acá solo se
    juntan sus datos desde lo exportado: la orden marco que cita la decisión (la del juez con cuya clave salió),
    quién otorgó el seguimiento, quién lo ratificó (el juez de esa orden marco, si no es quien lo otorgó) y el
    minuto de la ampliación. Nunca la atribuye como una firma del juez."""
    dec = u.get("decision") or {}
    d = exp.get("dinamica") or {}
    marco = ctx["marcos_por_entrada"].get((dec.get("orden_marco") or {}).get("entrada"))
    om = {"id": marco.get("id"), "nombre": marco.get("juez"), "min": marco.get("min")} if marco is not None else None
    de_dec = dec.get("otorgada_por") if isinstance(dec.get("otorgada_por"), dict) else {}
    otorgante = d.get("otorgada_por") or de_dec or {}
    otorgada = {"nombre": otorgante.get("nombre") or de_dec.get("nombre"),
                "min": d.get("otorgada_min") if d.get("otorgada_min") is not None else de_dec.get("min")}
    respaldo = dec.get("juez_id")
    ratificada = None
    if respaldo and respaldo != otorgante.get("juez_id"):
        rats = [r for r in d.get("ratificaciones") or [] if isinstance(r, dict) and r.get("juez_id") == respaldo
                and (dec.get("min") is None or r.get("min") is None or r["min"] <= dec["min"])]
        if rats:
            ratificada = _nombre_y_min(rats[-1])
        else:
            ratificada = _nombre_y_min(dec.get("ratificada_por")) or {
                "nombre": ctx["jueces"].get(respaldo, respaldo), "min": None}
    return leyenda_ampliacion(om, otorgada, ratificada, dec.get("min"))


def texto_decision(exp: dict, u: dict, ctx: dict) -> str:
    dec = u.get("decision")
    if u.get("estado") == "sin_decidir":
        return "Sin decidir: " + str(u.get("motivo_sin_decidir") or "el partido terminó antes de la decisión.")
    if not dec:
        return "Pendiente de la firma del juez."
    if not dec.get("aprobada"):
        return f"Rechazada por {dec.get('juez')} en el minuto {_m(dec.get('min'))}: {dec.get('motivo_rechazo')}"
    if dec.get("tipo") == "ampliacion_dinamica":
        return texto_ampliacion(exp, u, ctx)
    texto = (f"Firmada en persona por {dec.get('juez')} en el minuto {_m(dec.get('min'))} "
             f"({_alcance(dec.get('alcance'))}). Sello `{dec.get('sello')}` (entrada {dec.get('entrada')}).")
    forzado = dec.get("forzado")
    if forzado:
        f = forzado if isinstance(forzado, dict) else {}
        col = u.get("colateral") or {}
        ajenos = list(col.get("ajenos") or [])
        prop = dec.get("propuesta_aplicada") or {}
        fundamento = f.get("fundamento") or dec.get("fundamento") or "—"
        texto += (f" El juez se apartó de la recomendación ({col.get('recomendacion')}) y ordenó bloquear la IP "
                  f"{u.get('ip')} hasta el minuto {_m(prop.get('vence_min'))}. Riesgo informado: la IP aloja otros "
                  f"{len(ajenos)} sitios ({', '.join(ajenos) or '—'}). Fundamento del juez: «{fundamento}».")
    return texto


def _firma_orden(o: dict) -> str:
    if o.get("reclamo"):
        return f"Reemplazo por reclamo {o['reclamo']}"  # g-paquete-7a: vale también para su reintento
    return "Ampliación automática" if str(o.get("orden_id", "")).startswith("amp-") else "Firmada en persona"


# --- Reclamos en castellano llano (g-paquete-6/7): nunca los valores internos (legitimo, cerrar, …) -------------------

_TIPO_BLOQUEO = {"ip": "por IP", "dominio": "por dominio"}


def _tipo_bloqueo(tipo) -> str:
    return _TIPO_BLOQUEO.get(tipo, f"por {tipo}")


def _juntar(xs: List[str]) -> str:
    xs = [x for x in xs if x]
    if len(xs) <= 1:
        return "".join(xs)
    return ", ".join(xs[:-1]) + " y " + xs[-1]


def _lista_reclamos(ids: List[str]) -> str:
    """R-002 a R-006 si son correlativos (tres o más); si no, R-002, R-004 y R-007."""
    ids = sorted(set(ids), key=lambda x: (len(x), x))
    try:
        nums = [int(x.split("-")[-1]) for x in ids]
        correlativos = len(ids) >= 3 and nums == list(range(nums[0], nums[0] + len(nums))) and \
            len({x.rsplit("-", 1)[0] for x in ids}) == 1
    except ValueError:
        correlativos = False
    return f"{ids[0]} a {ids[-1]}" if correlativos else _juntar(ids)


def _clase_reclamo(r: dict, corta: bool = False) -> str:
    ver = r.get("verificacion") or {}
    clase = ver.get("clase_reclamante")
    if clase == "legitimo" and ver.get("inferido"):
        return ("fundado (la plataforma lo había inferido del pirata, nunca lo vio transmitir)" if corta else
                "reclamo fundado, la plataforma lo había inferido del pirata pero nunca lo vio transmitir")
    return {"legitimo": ("fundado", "reclamo fundado, es un sitio ajeno al pirata"),
            "licenciatario": ("fundado (dominio autorizado de un licenciatario)",
                              "reclamo fundado, es un dominio autorizado de un licenciatario"),
            "operacion_pirata": ("no fundado (es parte de la operación pirata)",
                                 "reclamo no fundado, el dominio es parte de la operación pirata"),
            "sin_bloqueo": ("ningún bloqueo lo afectaba", "ningún bloqueo lo afectaba"),
            }.get(clase, ("sin verificar", "reclamo sin verificar"))[0 if corta else 1]


def _bloqueos_acta(pares: List[tuple], articulo: str) -> str:
    """Bloqueos distintos (tipo, objetivo) contados por objetivo, no por proveedor: «el bloqueo por IP»."""
    por_tipo: Dict[str, set] = {}
    for tipo, objetivo in pares:
        por_tipo.setdefault(tipo, set()).add(objetivo)
    partes = []
    for tipo in sorted(por_tipo, key=lambda t: (t != "ip", str(t))):
        n = len(por_tipo[tipo])
        uno = "el" if articulo == "el" else "un"
        partes.append(f"{uno} bloqueo {_tipo_bloqueo(tipo)}" if n == 1 else
                      f"{'los ' if articulo == 'el' else ''}{n} bloqueos {_tipo_bloqueo(tipo)}")
    return _juntar(partes)


def reclamo_acta(r: dict, ordenes: Dict[str, dict]) -> str:
    """Una línea del acta por reclamo, con quién lo resolvió, cuándo y qué hizo."""
    via = f", vía {r['proveedor_nombre']}" if r.get("proveedor_nombre") else ""
    cab = f"- {r.get('id')} {r.get('dominio')} (minuto {_m(r.get('minuto'))}){via}: "
    res = r.get("resolucion") or {}
    despues = f"{_m(res.get('minutos_hasta_resolver'))} min después"
    accion = res.get("accion")
    if not res:
        return cab + f"{_clase_reclamo(r)}. Quedó sin resolver al cierre."
    if accion == "cerrar":
        if res.get("por_reclamo"):
            return cab + f"cerrado por la resolución de {res['por_reclamo']} ({despues} del reclamo)."
        return cab + f"ningún bloqueo lo afectaba: se cerró sin intervención de un juez ({despues} del reclamo)."
    quien = res.get("juez") or res.get("juez_id") or "—"
    if accion == "desestimar":
        return cab + f"{_clase_reclamo(r)}. {quien} lo desestimó en el minuto {_m(res.get('min'))} ({despues}): " \
                     "el bloqueo se mantiene."
    causantes = {c.get("orden_id"): c for c in (r.get("verificacion") or {}).get("ordenes_causantes") or []}
    lev = [ordenes.get(x.get("orden_id")) or causantes.get(x.get("orden_id")) or {}
           for x in (r.get("propuesta") or {}).get("levantar") or []]
    pares = [(o.get("tipo"), o.get("objetivo")) for o in lev if o.get("tipo")]
    hizo = f"levantó {_bloqueos_acta(pares, 'el')}" if pares else "levantó el bloqueo"
    reemp = [ordenes.get(x) or {} for x in res.get("ordenes_reemplazo") or []]
    pares_r = [(o.get("tipo"), o.get("objetivo")) for o in reemp if o.get("tipo")]
    if accion == "levantar_y_reemplazar" and res.get("ordenes_reemplazo"):
        lo = "lo" if len(set(pares)) <= 1 else "los"
        hizo += f"{',' if ' y ' in hizo else ''} y {lo} reemplazó por {_bloqueos_acta(pares_r, 'un') if pares_r else 'un bloqueo por dominio'}"
    elif accion == "levantar_y_reemplazar":
        hizo += ", sin reemplazo"
    return cab + f"{_clase_reclamo(r)}. {quien} lo resolvió en el minuto {_m(res.get('min'))} ({despues}): {hizo}."


def _cuenta_bloqueos(ords: List[dict]) -> str:
    por_tipo: Dict[str, int] = {}
    for o in ords:
        por_tipo[o.get("tipo")] = por_tipo.get(o.get("tipo"), 0) + 1
    return _juntar([f"{'un bloqueo' if n == 1 else f'{n} bloqueos'} {_tipo_bloqueo(t)}"
                    for t, n in sorted(por_tipo.items(), key=lambda x: (x[0] != "ip", str(x[0])))])


def reclamos_de_ubicacion(exp: dict, u: dict, reclamos: List[dict]) -> List[str]:
    """Una línea por reclamo que tocó la ubicación: levantó o reemplazó órdenes de ella, o la nombró como causa y un
    juez lo desestimó o quedó sin resolver. Los cerrados por otro reclamo van en la línea del que los cerró."""
    ords = u.get("ordenes") or []
    L = []
    for r in sorted(reclamos, key=lambda x: (x.get("minuto") or 0, str(x.get("id")))):
        rid = r.get("id")
        res = r.get("resolucion") or {}
        if res.get("accion") == "cerrar":
            continue
        levantadas = [o for o in ords if (o.get("levantamiento") or {}).get("reclamo") == rid]
        reemplazos = [o for o in ords if o.get("reclamo") == rid]
        causa = any(c.get("exp") == exp.get("id") and c.get("n") == u.get("n")
                    for c in (r.get("verificacion") or {}).get("ordenes_causantes") or [])
        if not (levantadas or reemplazos or causa):
            continue
        txt = f"- Reclamo {rid} de {r.get('dominio')} (minuto {_m(r.get('minuto'))}): {_clase_reclamo(r, corta=True)}."
        quien = res.get("juez") or res.get("juez_id") or "—"
        entrada = f" (entrada {res['entrada']})" if res.get("entrada") is not None else ""
        if not res:
            txt += " Quedó sin resolver al cierre."
        elif res.get("accion") == "desestimar":
            txt += f" {quien} lo desestimó en el minuto {_m(res.get('min'))}{entrada}: el bloqueo se mantiene."
        else:
            pedidas = {x.get("orden_id") for x in (r.get("propuesta") or {}).get("levantar") or []}
            faltan = [o for o in ords if o.get("orden_id") in pedidas and o not in levantadas]
            txt += f" {quien} lo resolvió en el minuto {_m(res.get('min'))}{entrada}: "
            n = len(levantadas)
            txt += (f"se {'levantó' if n == 1 else 'levantaron'} {_cuenta_bloqueos(levantadas)}" if n
                    else "no se levantó ningún bloqueo de esta ubicación")
            if faltan:
                txt += f" ({_cuenta_bloqueos(faltan)} no {'llegó' if len(faltan) == 1 else 'llegaron'} a levantarse)"
            if reemplazos:
                sello = next((o.get("sello") for o in reemplazos if o.get("sello")), None)
                tipos = _juntar(sorted({_tipo_bloqueo(o.get("tipo")) for o in reemplazos}))
                txt += (f"{',' if ' y ' in _cuenta_bloqueos(levantadas) else ''} y se "
                        f"{'reemplazó' if n == 1 else 'reemplazaron'} por bloqueos {tipos}"
                        + (f" (sello `{str(sello)[:8]}…`)" if sello else ""))
            txt += "."
        cerro = [str(x.get("id")) for x in reclamos if (x.get("resolucion") or {}).get("por_reclamo") == rid]
        if cerro:
            txt += f" También cerró {_lista_reclamos(cerro)}, del mismo bloqueo."
        L.append(txt)
    return L


def expediente_md(exp: dict, ctx: dict) -> str:
    partido = ctx["partido"]
    nombres = {p["id"]: p.get("nombre") for p in ctx["proveedores"]}
    fil = exp.get("filtracion") or {}
    L = [f"# Expediente {exp['id']} — {exp['titulo']}", "",
         f"- Partido: {partido.get('nombre')}",
         f"- Filtración: {exp['id']} (marca de agua {fil.get('clave')}, sesión {fil.get('sesion') or '—'})",
         f"- Estado: {exp.get('estado')}", ""]
    d = exp.get("dinamica")
    if d:
        otorgada = d.get("otorgada_por") or {}
        L.append(f"- Seguimiento de la filtración: autorizado por {otorgada.get('nombre')} en el minuto "
                 f"{_m(d.get('otorgada_min'))}.")
        for r in d.get("ratificaciones") or []:
            L.append(f"- Ratificado por {r.get('nombre')} en el minuto {_m(r.get('min'))}.")
        if d.get("revocada"):
            rev = d["revocada"] if isinstance(d["revocada"], dict) else {}
            L.append(f"- Seguimiento frenado por {ctx['jueces'].get(rev.get('juez_id'), rev.get('nombre') or '—')}"
                     f" en el minuto {_m(rev.get('min'))}.")
        L.append("")
    for u in exp["ubicaciones"]:
        c = u.get("cobertura") or {}
        t = u.get("tiempos") or {}
        L += [f"## Ubicación {u['n']}: {u['host']} ({u['ip']})", "",
              f"- Primera detección: minuto {_m(u.get('primera_deteccion_min'))} — detecciones: "
              f"{', '.join(u.get('detecciones') or [])}"]
        for pr in u.get("promocion") or []:
            L.append(f"- Dónde se promocionó el enlace: {pr.get('red')} — {pr.get('url')} "
                     f"(minuto {_m(pr.get('minuto'))})")
        L += [f"- Señal: {(u.get('senal') or {}).get('motivo')}",
              f"- Servidor: ASN {u.get('asn')} — {u.get('organizacion')}",
              f"- Sitios en el mismo servidor (riesgo {(u.get('colateral') or {}).get('riesgo')}): "
              f"{(u.get('colateral') or {}).get('motivo')}",
              f"- Captura: sha256 `{(u.get('captura') or {}).get('sha256')}`. El hash prueba que la captura no "
              "cambió desde que llegó a la plataforma.",
              f"- Huella de la evidencia: `{u.get('huella')}`"]
        if u.get("continuidad"):
            L.append(f"- Continuidad: {_continuidad(u['continuidad'])}.")
        L.append(f"- Decisión: {texto_decision(exp, u, ctx)}")
        L.append(f"- Tiempos desde la detección: firma {_dif(t, 'firma_min')} min · primer proveedor "
                 f"{_dif(t, 'primer_proveedor_min')} min · todos los proveedores {_dif(t, 'todos_los_proveedores_min')}"
                 " min" + (f" · el pedido llegó a la bandeja del juez {_m(t['expediente_abierto_min'])} min antes de "
                           "que firmara" if t.get("expediente_abierto_min") is not None else ""))
        if _sin_ventana(c):
            L.append("- Cobertura: — (la ubicación no llegó a tener ventana propia)")
        else:
            L.append(f"- Cobertura: {_pct(c.get('clientes_cubiertos_pct'))} de los clientes; primer bloqueo a "
                     f"{_m(c.get('primer_bloqueo_min'))} min; visibilidad residual "
                     f"{_pct(c.get('visibilidad_residual_pct'))}")
        if u.get("ordenes"):
            L += ["", "| Orden | Firma | Proveedor | Tipo | Objetivo | Estado | Aplicada | Fin | Juez |",
                  "|---|---|---|---|---|---|---|---|---|"]
            for o in u["ordenes"]:
                L.append(f"| `{o['orden_id']}` | {_firma_orden(o)} | {nombres.get(o['proveedor'], o['proveedor'])} | "
                         f"{'IP' if o['tipo'] == 'ip' else o['tipo']} | {o['objetivo']} | {estado_legible(o)} | "
                         f"{_m(o.get('aplicada_min'))} | {_m(o.get('finalizada_min'))} | "
                         f"{ctx['jueces'].get(o.get('juez_id'), o.get('juez_id'))} |")
        lineas_reclamos = reclamos_de_ubicacion(exp, u, (ctx.get("resumen") or {}).get("reclamos") or [])
        if lineas_reclamos:
            L += [""] + lineas_reclamos
        L.append("")
    return "\n".join(L) + "\n"


def _dif(t: dict, campo: str):
    if t.get(campo) is None or t.get("deteccion_min") is None:
        return "—"
    return _m(float(t[campo]) - float(t["deteccion_min"]))


def marco_md(m: dict, ctx: dict) -> str:
    c = m.get("contenido") or {}
    L = [f"# Orden marco {m['id']} — {(c.get('partido') or {}).get('nombre') or ctx['partido'].get('nombre')}", "",
         f"Firmada por {m.get('juez')} ({m.get('juzgado')}) en el minuto {_m(m.get('min'))}"
         + (f" ({m['hora']})" if m.get("hora") else "") + f". Entrada {m.get('entrada')} de la auditoría.",
         f"Huella del texto: `{m.get('huella')}`."]
    if m.get("reemplaza"):
        L.append(f"Reemplaza a la orden marco de la entrada {m['reemplaza']}.")
    if m.get("reemplazada_por"):
        L.append(f"La reemplazó la orden marco {m['reemplazada_por']}.")
    # El texto legible sale de un solo lugar (marco.a_texto): las líneas y, si hay seguimiento, el título de la
    # casilla y sus condiciones.
    L += ["", "## Texto firmado", ""]
    L += [f"{i}. {linea}" for i, linea in enumerate(a_texto(c), start=1)]
    L += ["", "## Seguimiento de la misma filtración", "",
          "- [x] Autorizado por el juez." if m.get("seguimiento") else "- [ ] No autorizado."]
    if m.get("seguimiento"):
        L += ["", "Ampliaciones hechas bajo esta orden:" if m.get("ampliaciones") else
              "No se hizo ninguna ampliación bajo esta orden."]
        L += [f"- {a['exp']} ubicación {a['ubicacion']} (minuto {_m(a.get('min'))}, entrada {a['entrada']})"
              for a in m.get("ampliaciones") or []]
    else:
        L += ["", "No autorizado: cada servidor nuevo espera la firma del juez."]
    return "\n".join(L) + "\n"


def _promedio(valores: List[float]) -> Optional[float]:
    return sum(valores) / len(valores) if valores else None


def armar_tiempos(expedientes: List[dict], firmaron: str) -> dict:
    filas = []
    for exp in expedientes:
        for u in exp["ubicaciones"]:
            t = u.get("tiempos") or {}
            if not t.get("tipo"):
                continue

            def dif(campo):
                return None if t.get(campo) is None or t.get("deteccion_min") is None \
                    else r3(float(t[campo]) - float(t["deteccion_min"]))
            filas.append({"exp": exp["id"], "ubicacion": u["n"], "host": u["host"], "tipo": t["tipo"],
                          "deteccion_min": t.get("deteccion_min"), "firma_min": t.get("firma_min"),
                          "primer_proveedor_min": t.get("primer_proveedor_min"),
                          "todos_los_proveedores_min": t.get("todos_los_proveedores_min"),
                          "expediente_abierto_min": t.get("expediente_abierto_min"),
                          "hasta_firma_min": dif("firma_min"), "hasta_primer_proveedor_min": dif("primer_proveedor_min"),
                          "hasta_todos_min": dif("todos_los_proveedores_min")})
    promedios = {}
    for tipo in ("en_persona", "ampliacion"):
        fs = [f for f in filas if f["tipo"] == tipo]
        promedios[tipo] = {"ubicaciones": len(fs)}
        for campo in ("hasta_firma_min", "hasta_primer_proveedor_min", "hasta_todos_min"):
            vals = [f[campo] for f in fs if f[campo] is not None]
            promedios[tipo][campo] = r3(_promedio(vals)) if vals else None
        promedios[tipo]["sin_todos"] = sum(1 for f in fs if f["hasta_todos_min"] is None)
    return {"firmaron": firmaron, "ubicaciones": filas, "promedios": promedios}


def acta_md(resumen: dict, expedientes: List[dict], marcos: List[dict]) -> str:
    ctx = contexto(resumen, expedientes, marcos)
    partido = ctx["partido"]
    cabeza = resumen.get("cabeza_auditoria") or {}
    tiempos = resumen.get("tiempos") or {}
    L = [f"# Acta del partido — {partido.get('nombre')}", "",
         f"- Partido: {partido.get('id')} · titular: {partido.get('titular_derechos')} · fin: minuto "
         f"{_m(partido.get('fin_min'))}",
         f"- Plataforma Marca Personal {resumen.get('plataforma')} · simulador: {resumen.get('simulador')}",
         f"- Cabeza de la auditoría: entrada {cabeza.get('n')}, hash `{cabeza.get('hash')}`",
         f"- Firmaron: {tiempos.get('firmaron') or 'personas'}.", "", "## Orden marco", ""]
    if not marcos:
        L.append("- No se firmó ninguna orden marco: todo se decidió servidor por servidor.")
    for m in marcos:
        L.append(f"- {m['id']}: {m.get('juez')} ({m.get('juzgado')}), minuto {_m(m.get('min'))}"
                 + (f" ({m['hora']})" if m.get("hora") else "")
                 + f" · seguimiento: {'sí' if m.get('seguimiento') else 'no'} · huella `{m.get('huella')}` "
                 f"(entrada {m.get('entrada')})" + (f" · reemplazada por {m['reemplazada_por']}"
                                                     if m.get("reemplazada_por") else "")
                 + f". Texto en orden-marco/{m['id']}.md.")
        if m.get("ampliaciones"):
            L.append("  - Ampliaciones hechas bajo esta orden: " + "; ".join(
                f"{a['exp']} U{a['ubicacion']} (minuto {_m(a.get('min'))})" for a in m["ampliaciones"]) + ".")
        elif m.get("seguimiento"):
            L.append("  - No se hizo ninguna ampliación bajo esta orden.")
    L += ["", "## Filtraciones", "",
          "| Expediente | Sitio | Filtración | Ubicación | Host / IP | Decisión | Promoción | Primer bloqueo | Cobertura "
          "| Visibilidad residual |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    residuales = []
    for exp in expedientes:
        for u in exp["ubicaciones"]:
            c = u.get("cobertura") or {}
            dec = u.get("decision") or {}
            if u.get("estado") == "sin_decidir":
                tipo = _sin_decidir(u)
            elif dec.get("aprobada"):
                tipo = "ampliación automática" if dec.get("tipo") == "ampliacion_dinamica" else "firmada en persona"
            else:
                tipo = "rechazada" if dec else "pendiente"
            promo = "; ".join(f"{p.get('red')}: {p.get('url')}" for p in u.get("promocion") or []) or "—"
            if _sin_ventana(c):
                columnas = "— | — | —"
            else:
                columnas = (f"{_m(c.get('primer_bloqueo_min'))} min | {_pct(c.get('clientes_cubiertos_pct'))} | "
                            f"{_pct(c.get('visibilidad_residual_pct'))}")
                residuales.append(c["visibilidad_residual_pct"])
            L.append(f"| {exp['id']} | {exp['titulo']} | {exp['id']} | U{u['n']} | {u['host']} / {u['ip']} | {tipo} | "
                     f"{promo} | {columnas} |")
    if residuales:
        L += ["", f"Visibilidad residual promedio: {_pct(_promedio(residuales))}."]
    L += ["", "## Tiempos", "",
          "Minutos de partido desde la primera detección de cada ubicación.", "",
          "| Expediente | Ubicación | Firma | Hasta la firma | Hasta el primer proveedor | Hasta todos los proveedores "
          "| Pedido en la bandeja antes de firmar |",
          "|---|---|---|---|---|---|---|"]
    for f in tiempos.get("ubicaciones") or []:
        L.append(f"| {f['exp']} | U{f['ubicacion']} | "
                 f"{'en persona' if f['tipo'] == 'en_persona' else 'ampliación automática'} | "
                 f"{_m(f.get('hasta_firma_min'))} | {_m(f.get('hasta_primer_proveedor_min'))} | "
                 f"{_m(f.get('hasta_todos_min'))} | {_m(f.get('expediente_abierto_min'))} |")
    if not tiempos.get("ubicaciones"):
        L.append("| — | — | — | — | — | — | — |")
    prom = tiempos.get("promedios") or {}
    L.append("")
    for tipo, titulo in (("en_persona", "Firmadas en persona"), ("ampliacion", "Ampliaciones automáticas")):
        p = prom.get(tipo) or {}
        linea = (f"- {titulo} ({p.get('ubicaciones', 0)}): hasta la firma {_m(p.get('hasta_firma_min'))} min · "
                 f"hasta el primer proveedor {_m(p.get('hasta_primer_proveedor_min'))} min · hasta todos los "
                 f"proveedores {_m(p.get('hasta_todos_min'))} min")
        if p.get("sin_todos"):
            linea += f" ({p['sin_todos']} sin llegar a todos los proveedores)"
        L.append(linea + ".")
    ords = [o for exp in expedientes for u in exp["ubicaciones"] for o in u.get("ordenes") or []]
    ords += list(resumen.get("ordenes_sin_ubicacion") or [])
    cuenta: Dict[str, int] = {}
    for o in ords:
        cuenta[estado_legible(o)] = cuenta.get(estado_legible(o), 0) + 1
    amp = sum(1 for o in ords if str(o.get("orden_id", "")).startswith("amp-"))
    L += ["", "## Órdenes", "", ", ".join(f"{k}: {v}" for k, v in sorted(cuenta.items(), key=lambda x: str(x[0])))
          or "Ninguna.", f"Firmadas en persona (ord-): {len(ords) - amp}. Ampliaciones automáticas (amp-): {amp}.",
          "", "## Descartes (no se bloquean)", ""]
    descartes = sorted(resumen.get("descartes") or [], key=lambda x: x.get("minuto") or 0)
    for d in descartes:
        L.append(f"- {d['host']} ({CLASES_DESCARTE.get(d['clase'], d['clase'])}, {d['veces']} detecciones): "
                 f"{d['motivo']}")
    if not descartes:
        L.append("- Ninguno.")
    L += ["", "## Reclamos", ""]
    reclamos = sorted(resumen.get("reclamos") or [], key=lambda x: x.get("minuto") or 0)
    todas = {o.get("orden_id"): o for exp in expedientes for u in exp.get("ubicaciones") or []
             for o in u.get("ordenes") or []}
    for r in reclamos:
        L.append(reclamo_acta(r, todas))
    if not reclamos:
        L.append("- No hubo reclamos.")
    L += ["", "## Traspasos de turno", ""]
    for t in resumen.get("traspasos") or []:
        rat = t.get("ratificado")
        L.append(f"- Minuto {_m(t['min'])}: de {', '.join(x['nombre'] for x in t['de']) or '—'} a "
                 f"{', '.join(x['nombre'] for x in t['a'])}; "
                 + (f"ratificado por {rat['nombre']} en el minuto {_m(rat['min'])}." if rat
                    else _sin_recepcion(t, expedientes)))
    if not resumen.get("traspasos"):
        L.append("- No hubo traspasos.")
    hora = hora_de_partido(partido.get("inicio_iso"), resumen.get("minuto"))
    L += ["", f"Acta generada en el minuto {_m(resumen.get('minuto'))}" + (f" ({hora})" if hora else "") + "."]
    return "\n".join(L) + "\n"


def _sin_recepcion(t: dict, expedientes: List[dict]) -> str:
    """NV4: el entrante no tocó «Recibir el turno», pero pudo ratificar un seguimiento al firmar y seguir."""
    texto = "el juez entrante no confirmó la recepción del turno"
    sitios = {}
    for x in expedientes:
        hosts = [u.get("host") for u in x.get("ubicaciones") or [] if u.get("host")]
        sitios[x.get("id")] = x.get("titulo") or (hosts[0] if hosts else x.get("id"))
    partes = []
    for r in t.get("ratificadas_al_firmar") or []:
        if isinstance(r, dict):
            partes.append(f"el seguimiento de {sitios.get(r.get('id'), r.get('id'))} lo ratificó "
                          + (f"{r['nombre']} " if r.get("nombre") else "")
                          + f"al firmar y seguir en el minuto {_m(r.get('min'))}")
    return texto + ("; " + "; ".join(partes) if partes else "") + "."


# Lo que lee el jurado va en lenguaje llano, no con los códigos internos de la clase del descarte.
CLASES_DESCARTE = {"otra_senal": "otra señal", "sin_marca": "sin marca de agua"}


def legibles(resumen: dict, expedientes: List[dict], marcos: List[dict]) -> Dict[str, str]:
    """Todos los .md del paquete, generados solo desde lo exportado. `verificar` llama a esta misma función."""
    ctx = contexto(resumen, expedientes, marcos)
    salida = {f"expedientes/{exp['id']}.md": expediente_md(exp, ctx) for exp in expedientes}
    for m in marcos:
        salida[f"orden-marco/{m['id']}.md"] = marco_md(m, ctx)
    salida["acta-del-partido.md"] = acta_md(resumen, expedientes, marcos)
    salida["LEEME.md"] = LEEME  # las instrucciones también: un LEEME reescrito («el registro no hace falta») da ✗
    return salida


def quien_firmo(entradas: List[dict]) -> str:
    programas = [e for e in entradas if e.get("tipo") == "sesion_iniciada"
                 and (e.get("datos") or {}).get("rol") == "juez" and (e.get("datos") or {}).get("programa")]
    return "el juez automático de ensayo (solo pruebas)" if programas else "personas"


LEEME = """# Cómo verificar esta exportación

1. Sin conexión ni plataforma: `python3 -m marca verificar <esta carpeta>` recalcula la cadena de auditoría, las huellas, los sellos y las capturas, y cruza en los dos sentidos expedientes, ubicaciones y órdenes con la auditoría.
2. Con el registro oficial del simulador: agregar `--registro-simulador <registro.jsonl>`; con las claves de demostración, `--config config/jueces_demo.json` (toda decisión, ampliación y levantamiento tiene que traer su firma válida).
3. `testigos/proveedores.json` es lo que tenía cada proveedor en la última foto, pero lo guarda la plataforma: se cruza solo y su sha256 está en la auditoría (entrada `testigos_guardados`); si la auditoría dice que se guardaron, el archivo tiene que estar. No reemplaza al registro oficial del simulador: sin el registro, `verificar` solo dice que el paquete es coherente consigo mismo.
4. `MANIFIESTO.json` tiene el tamaño y el sha256 de cada archivo: cualquier cambio posterior, archivo faltante o agregado se informa con su nombre. La huella del paquete es el sha256 de `MANIFIESTO.json`.
5. Los `.md` (expedientes, orden marco, acta y este LEEME) los genera el código desde los `.json` del paquete: `verificar` los vuelve a generar y los compara; un `.md` editado da ✗ aunque se regenere el manifiesto.
6. La auditoría no lleva clave: lo anterior al último sello lo anclan los `orden_id` que tienen los proveedores; la cola posterior (vencimientos, testigos, exportación) la ancla solo la huella del paquete. Por eso la huella se publica al exportar, y se compara con `verificar <carpeta> --huella <huella publicada>`. Con el registro oficial, además, se cotejan contra el simulador los minutos de aplicación, los vencimientos y el estado final de cada orden, también los de la cola.
7. Las huellas (el `hash` de cada entrada de la auditoría y los sellos) son sha256 del JSON canónico de Python: `json.dumps(objeto, sort_keys=True, ensure_ascii=False, separators=(",", ":"))` en UTF-8. Quien verifique con otro lenguaje tiene que escribir los números igual que Python (por ejemplo `2.0`, no `2`). Un archivo JSON con una clave repetida da ✗.
"""


class ErrorDestino(Exception):
    """El destino de la exportación no se puede usar sin pisar algo que no es una exportación."""


def comprobar_destino(destino) -> None:
    """Un destino sirve si no existe, está vacío o es una exportación anterior (tiene MANIFIESTO.json)."""
    destino = Path(destino)
    if not destino.exists():
        return
    if not destino.is_dir():
        raise ErrorDestino(f"{destino} existe y no es una carpeta: no se toca.")
    if (destino / MANIFIESTO).is_file():
        return
    otros = [p.name for p in destino.iterdir() if p.name not in IGNORAR]
    if otros:
        raise ErrorDestino(
            f"{destino} no está vacía y no es una exportación anterior (no tiene {MANIFIESTO}): no se toca. "
            f"Tiene, por ejemplo: {', '.join(sorted(otros)[:5])}. Usá --destino entrega/partido-final "
            "(o cualquier carpeta vacía).")


def exportar(salida, destino) -> Path:
    """Arma el paquete en una carpeta hermana temporal y la pone en lugar de `destino` de una vez.

    Así no quedan restos de una exportación anterior mezclados con la nueva, y un corte a mitad de camino
    nunca deja un paquete a medias en `destino`.
    """
    salida, destino = Path(salida), Path(destino)
    return _armar_y_poner(lambda tmp: _escribir_paquete(salida, tmp), destino)


def _paquete_integro(carpeta: Path) -> bool:
    """Cada archivo del paquete coincide con su MANIFIESTO.json (ni de más ni de menos)."""
    try:
        doc = json.loads((carpeta / MANIFIESTO).read_text(encoding="utf-8"))
        esperado = {a["ruta"]: a["sha256"] for a in doc["archivos"]}
        reales = {p.relative_to(carpeta).as_posix(): sha256_hex(p.read_bytes()) for p in archivos_del_paquete(carpeta)}
        return esperado == reales
    except (OSError, ValueError, KeyError, TypeError):
        return False


def copiar_paquete(origen, destino, intentos: int = 3) -> Path:
    """Copia tal cual un paquete ya exportado (el que armó la plataforma al cierre, C20): misma huella.

    Misma atomicidad que `exportar`. Si el origen cambia mientras se copia (la plataforma reexportó), la copia no
    coincide con su manifiesto y se vuelve a copiar.
    """
    origen, destino = Path(origen), Path(destino)
    if not (origen / MANIFIESTO).is_file():
        raise ErrorDestino(f"{origen} no es un paquete exportado (no tiene {MANIFIESTO}).")
    if origen.resolve() == destino.resolve():
        return destino

    def copiar(tmp: Path) -> None:
        shutil.copytree(origen, tmp, ignore=shutil.ignore_patterns(*IGNORAR))
        if not _paquete_integro(tmp):
            raise OSError(f"el paquete {origen} cambió mientras se copiaba")

    for i in range(intentos):
        try:
            return _armar_y_poner(copiar, destino)
        except (OSError, shutil.Error):
            if i == intentos - 1:
                raise
            time.sleep(0.2)
    return destino


def _armar_y_poner(armar, destino: Path) -> Path:
    """Arma el paquete con `armar(tmp)` en una carpeta hermana temporal y la pone en lugar de `destino` de una vez."""
    comprobar_destino(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    marca = secrets.token_hex(4)
    tmp = destino.with_name(f".{destino.name}.exportando-{marca}")
    try:
        armar(tmp)
        comprobar_destino(destino)
        if destino.exists():
            viejo = destino.with_name(f".{destino.name}.reemplazada-{marca}")
            destino.rename(viejo)
            try:
                tmp.rename(destino)
            except OSError:
                viejo.rename(destino)
                raise
            shutil.rmtree(viejo, ignore_errors=True)
        else:
            tmp.rename(destino)
    finally:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
    return destino


def _escribir_paquete(salida: Path, destino: Path) -> None:
    with open(salida / "estado.json", encoding="utf-8") as f:
        estado = json.load(f)
    destino.mkdir(parents=True)
    (destino / "expedientes").mkdir(exist_ok=True)
    (destino / "capturas").mkdir(exist_ok=True)
    # Solo líneas completas (la plataforma puede estar escribiendo mientras se exporta).
    crudo = (salida / "auditoria.jsonl").read_bytes()
    corte = crudo.rfind(b"\n")
    (destino / "auditoria.jsonl").write_bytes(crudo[:corte + 1] if corte >= 0 else b"")
    cabeza = {"n": 0, "hash": None}
    entradas = []
    with open(destino / "auditoria.jsonl", encoding="utf-8") as f:
        for linea in f:
            if linea.strip():
                e = json.loads(linea)
                entradas.append(e)
                cabeza = {"n": e["n"], "hash": e["hash"]}
    expedientes = armar_expedientes(estado)
    marcos = armar_marcos(entradas, expedientes, estado["partido"])
    for exp in expedientes:
        with open(destino / "expedientes" / f"{exp['id']}.json", "w", encoding="utf-8") as f:
            json.dump(exp, f, ensure_ascii=False, indent=1)
        for u in exp["ubicaciones"]:
            for det in u["detecciones"]:
                origen = salida / "capturas" / nombre_captura(det)
                if origen.exists():
                    shutil.copyfile(origen, destino / "capturas" / nombre_captura(det))
    if marcos:
        (destino / "orden-marco").mkdir(exist_ok=True)
        for m in marcos:
            with open(destino / "orden-marco" / f"{m['id']}.json", "w", encoding="utf-8") as f:
                json.dump(m, f, ensure_ascii=False, indent=1)
    testigo = salida / "testigos" / "proveedores.json"
    if testigo.exists():
        (destino / "testigos").mkdir(exist_ok=True)
        shutil.copyfile(testigo, destino / "testigos" / "proveedores.json")
    # Colas de auditoría apartadas al reanudar (ver auditoria_reparada): se entregan tal cual, como evidencia.
    for apartada in sorted(salida.glob("auditoria.danada-*.jsonl")):
        (destino / "auditoria-apartada").mkdir(exist_ok=True)
        shutil.copyfile(apartada, destino / "auditoria-apartada" / apartada.name)
    exportadas = {(exp["id"], u["n"]) for exp in expedientes for u in exp["ubicaciones"]}
    sin_ubicacion = [_orden_exportable(o) for o in (estado.get("ordenes") or {}).values()
                     if (o.get("exp"), o.get("n")) not in exportadas]
    resumen = {"formato": FORMATO, "plataforma": VERSION, "partido": estado["partido"],
               "proveedores": estado.get("proveedores"), "simulador": estado.get("simulador"),
               "minuto": estado.get("minuto"), "descartes": list((estado.get("descartes") or {}).values()),
               "reclamos": list((estado.get("reclamos") or {}).values()), "traspasos": estado.get("traspasos") or [],
               "ordenes_sin_ubicacion": sin_ubicacion, "cerrado": bool((estado.get("hitos") or {}).get("cierre")),
               "cabeza_auditoria": cabeza, "tiempos": armar_tiempos(expedientes, quien_firmo(entradas)),
               "ordenes_marco": [m["id"] for m in marcos]}
    with open(destino / "resumen.json", "w", encoding="utf-8") as f:
        json.dump(resumen, f, ensure_ascii=False, indent=1)
    for rel, texto in legibles(resumen, expedientes, marcos).items():
        (destino / rel).write_text(texto, encoding="utf-8")
    escribir_manifiesto(destino)
