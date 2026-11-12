"""Análisis puro de la evidencia: señal, servidor, daño colateral, captura y propuesta de bloqueo.

Nada en este módulo hace entrada/salida: recibe datos y devuelve diccionarios.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import math
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from . import dominios

PALABRAS_RED_COMPARTIDA = ("cdn", "compartid", "shared")


def lista_corta(nombres: List[str], mostrar: int = 2) -> str:
    """'a, b y 9 más' o 'a y b' o 'a'."""
    nombres = list(nombres)
    if not nombres:
        return ""
    if len(nombres) <= mostrar:
        if len(nombres) == 1:
            return nombres[0]
        return ", ".join(nombres[:-1]) + " y " + nombres[-1]
    return ", ".join(nombres[:mostrar]) + f" y {len(nombres) - mostrar} más"


# --- Validación de lo que llega del simulador ----------------------------------------------


def _numero(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _asn(x) -> Optional[int]:
    """ASN como número: acepta 64600, 64600.0, "64600" o "AS64600"; cualquier otra cosa es None (sin dato)."""
    if isinstance(x, bool) or x is None:
        return None
    if isinstance(x, (int, float)):
        return int(x) if math.isfinite(x) and float(x).is_integer() else None
    texto = str(x).strip().upper()
    if texto.startswith("AS"):
        texto = texto[2:].strip()
    try:
        valor = float(texto)
    except ValueError:
        return None
    return int(valor) if math.isfinite(valor) and valor.is_integer() else None


def _corto(x, largo: int = 60) -> str:
    return " ".join(repr(x).split())[:largo]


def normalizar_deteccion(d):
    """Arreglos chicos antes de validar (c1-datos-raros-5 y -8), sin perder lo que llegó:
    - un id entero (no booleano) pasa a texto: descartarlo dejaba al pirata sin bloquear;
    - sin host_stream (o vacío), se toma el host de stream_url si es un nombre o una IP válidos.
    Devuelve una copia con `normalizada` = lista de campos tocados; lo demás, tal cual."""
    if not isinstance(d, dict):
        return d
    cambios = []
    nueva = dict(d)
    did = d.get("id")
    if isinstance(did, int) and not isinstance(did, bool):
        nueva["id"] = str(did)
        cambios.append("id")
    elif isinstance(did, float) and math.isfinite(did) and did.is_integer():
        # Ola C (P3 de a-kit): un id float entero también pasa a texto (101.0 → "101"). Un 1.5, un bool o un NaN no
        # son un id: la detección sigue descartándose con su motivo (el simulador oficial usa «D-0001»).
        nueva["id"] = str(int(did))
        cambios.append("id")
    host = d.get("host_stream")
    if host is None or (isinstance(host, str) and not host.strip()):
        url_host = dominios.host_de(d.get("stream_url")) if isinstance(d.get("stream_url"), str) else None
        if url_host and (dominios.es_hostname(url_host) or dominios.ip_valida(url_host)):
            nueva["host_stream"] = url_host
            cambios.append("host_stream")
    if not cambios:
        return d
    nueva["normalizada"] = cambios
    return nueva


def validar_deteccion(d) -> Optional[str]:
    """None si la detección se puede analizar; si no, el motivo en una línea."""
    if not isinstance(d, dict):
        return f"no es un objeto: {_corto(d)}"
    did = d.get("id")
    if not isinstance(did, str) or not did.strip():
        return f"falta el id o no es texto: {_corto(did)}"
    if not _numero(d.get("minuto")):
        return f"minuto no numérico: {_corto(d.get('minuto'))}"
    host = d.get("host_stream")
    if not (dominios.es_hostname(host) or dominios.ip_valida(host)):
        return f"host_stream no es un nombre de host ni una IP válida: {_corto(host)}"
    if not dominios.ip_valida(d.get("ip_servidor")):
        return f"ip_servidor no es una IP válida: {_corto(d.get('ip_servidor'))}"
    for campo in ("marca_de_agua_extraida", "pagina", "stream_url"):
        if d.get(campo) is not None and not isinstance(d.get(campo), str):
            return f"{campo} no es texto: {_corto(d.get(campo))}"
    if d.get("captura") is not None and not isinstance(d.get("captura"), dict):
        return f"captura no es un objeto: {_corto(d.get('captura'))}"
    if d.get("promocion") is not None and not isinstance(d.get("promocion"), list):
        return f"promocion no es una lista: {_corto(d.get('promocion'))}"
    return None


def validar_reclamo(r) -> Optional[str]:
    """None si el reclamo se puede verificar; si no, el motivo en una línea."""
    if not isinstance(r, dict):
        return f"no es un objeto: {_corto(r)}"
    rid = r.get("id")
    if not isinstance(rid, str) or not rid.strip():
        return f"falta el id o no es texto: {_corto(rid)}"
    if not dominios.es_hostname(r.get("dominio")) or dominios.ip_valida(str(r.get("dominio")).rstrip(".")):
        return f"dominio inválido: {_corto(r.get('dominio'))}"
    if not _numero(r.get("minuto")):
        return f"minuto no numérico: {_corto(r.get('minuto'))}"
    if r.get("proveedor") is not None and not isinstance(r.get("proveedor"), str):
        return f"proveedor no es texto: {_corto(r.get('proveedor'))}"
    if r.get("mensaje") is not None and not isinstance(r.get("mensaje"), str):
        return f"mensaje no es texto: {_corto(r.get('mensaje'))}"
    return None


# --- 4.2 La señal ------------------------------------------------------------------------


def _licenciatario_de_prefijo(partido: dict, prefijo: Optional[str]) -> Optional[dict]:
    for lic in partido.get("licenciatarios") or []:
        if prefijo and lic.get("prefijo_marca") == prefijo:
            return lic
    return None


def analizar_senal(marca: Optional[str], partido: dict, host: Optional[str],
                   pagina_host: Optional[str] = None) -> dict:
    """Clasifica la señal: pirata | licenciatario | otra_senal | sin_marca."""
    marca_txt = (marca or "").strip()
    resultado: Dict[str, Any] = {"marca": marca_txt or None, "prefijo": None, "origen": None,
                                 "sesion": None, "clase": None, "motivo": "", "observaciones": []}
    if not marca_txt:
        resultado["clase"] = "sin_marca"
        resultado["motivo"] = ("La detección no trae marca de agua: no se puede probar que sea la señal "
                               "de este partido, así que no se pide ningún bloqueo.")
        return resultado

    validos = sorted(partido.get("marcas_de_agua_validas") or [], key=lambda m: len(m.get("prefijo", "")),
                     reverse=True)
    elegido = None
    for m in validos:
        prefijo = m.get("prefijo") or ""
        if prefijo and (marca_txt == prefijo or marca_txt.startswith(prefijo + "-")):
            elegido = m
            break
    if elegido is None:
        resultado["clase"] = "otra_senal"
        resultado["motivo"] = (f"La marca de agua {marca_txt} no corresponde a ninguna señal de este partido: "
                               "no es la señal que se protege y no se bloquea.")
        return resultado

    prefijo = elegido["prefijo"]
    resultado["prefijo"] = prefijo
    resultado["origen"] = elegido.get("origen")
    resto = marca_txt[len(prefijo) + 1:] if len(marca_txt) > len(prefijo) else ""
    resultado["sesion"] = resto or None

    lic_del_prefijo = _licenciatario_de_prefijo(partido, prefijo)
    # Licenciatario: el host del stream (o la página) está dentro de sus dominios autorizados.
    for lic in partido.get("licenciatarios") or []:
        autorizados = lic.get("dominios_autorizados") or []
        en_stream = any(dominios.cubre(d, host) for d in autorizados)
        en_pagina = bool(pagina_host) and any(dominios.cubre(d, pagina_host) for d in autorizados)
        if en_stream or en_pagina:
            resultado["clase"] = "licenciatario"
            donde = "el servidor" if en_stream else "la página"
            resultado["motivo"] = (f"Retransmisión autorizada: {donde} está dentro de los dominios autorizados de "
                                   f"{lic.get('nombre')}. Nunca se bloquea.")
            if lic.get("prefijo_marca") != prefijo:
                resultado["observaciones"].append(
                    f"La marca {marca_txt} no es la de {lic.get('nombre')} ({lic.get('prefijo_marca')}): "
                    "conviene avisarle al titular, pero no se bloquea a un licenciatario.")
            return resultado

    resultado["clase"] = "pirata"
    resultado["motivo"] = texto_senal(resultado, lic_del_prefijo, con_sesion=True)
    resultado["texto_publico"] = texto_senal(resultado, lic_del_prefijo, con_sesion=False)
    if not resultado["sesion"]:
        resultado["observaciones"].append("La marca no trae código de sesión: la filtración se sigue por el sitio.")
    return resultado


def texto_senal(senal: dict, licenciatario: Optional[dict] = None, con_sesion: bool = True) -> str:
    """La plataforma no extrae la marca: compara la que informa el detector (sección 7 de la ronda 2b).

    `con_sesion=False` es el texto público: la sesión identifica la cuenta de un abonado (sección 4).
    """
    prefijo = senal.get("prefijo") or senal.get("marca") or ""
    sesion = senal.get("sesion")
    informada = f"El detector informó la marca {prefijo}" + (f" (sesión {sesion})" if con_sesion and sesion else "")
    if licenciatario is not None:
        return (informada + f". La plataforma comprobó que ese prefijo es del licenciatario "
                f"{licenciatario.get('nombre')} y que se transmite fuera de sus dominios autorizados.")
    return (informada + ". La plataforma comprobó que ese prefijo es de la señal oficial del partido y que no es de "
            "un licenciatario en su dominio.")


def texto_senal_publico(senal: dict) -> str:
    """Texto de la señal para lo público, sin la sesión del abonado."""
    if senal.get("texto_publico"):
        return senal["texto_publico"]
    if senal.get("clase") != "pirata":
        return senal.get("motivo") or ""
    return texto_senal(senal, None, con_sesion=False)


TEXTO_HASH_CAPTURA = "El hash prueba que la captura no cambió desde que llegó a la plataforma."


# --- 4.3 El servidor y el daño colateral ------------------------------------------------


def controla_registrable(pagina_host: Optional[str], registrable: str) -> bool:
    """El pirata controla el dominio registrable R si la página de la detección vive en R o en www.R."""
    return bool(pagina_host) and bool(registrable) and pagina_host in (registrable, "www." + registrable)


def motivo_ip_exclusiva(host: str, observados: List[str], inferidos: List[str], registrable: str,
                        propios_txt: str) -> str:
    """C14: el motivo de «IP exclusiva» dice qué se vio y qué se infirió, y concuerda en número."""
    n = len(set(observados) | set(inferidos))
    if n <= 1:
        return f"La IP es exclusiva del sitio pirata ({propios_txt}). Bloquear la IP no afecta a nadie más."
    vistos = [host] + [d for d in observados if d != host] if host in observados else list(observados)
    partes = [f"La IP es exclusiva del sitio pirata: la plataforma vio {lista_corta(vistos)}"]
    if inferidos:
        uno = len(inferidos) == 1
        partes.append(f", y toma también como {'suyo' if uno else 'suyos'} a {lista_corta(inferidos)}, porque "
                      f"{'cuelga' if uno else 'cuelgan'} de {registrable}, donde está la página del pirata")
    total = "los dos nombres" if n == 2 else f"los {n} nombres"
    return "".join(partes) + f". Bloquear la IP corta {total}."


def analizar_servidor(det: dict, dns_ip: Optional[dict], dns_host: Optional[dict],
                      hosts_piratas: Iterable[str], refutados: Iterable[str] = frozenset()) -> dict:
    """Servidor, coherencia y regla de daño colateral para una detección.

    Ronda 3, C14 (una sola regla). Nombres de la IP:
    - `observados`: lo que la plataforma vio. El host del stream (y los hosts de stream ya vistos en otras
      ubicaciones, `hosts_piratas`). El host de la página, solo si comparte el registrable con el del stream (o si
      el stream sale de una IP literal: ahí sigue la regla anterior).
    - `inferidos`: los otros nombres de la IP que cuelgan del registrable R del stream, solo si la página del pirata
      está en R o en www.R (`controla_registrable`) y R no está en `refutados` (un reclamo fundado la refutó).
    - `propios` = observados + inferidos; `ajenos` = el resto. La página de otro registrable es ajena.
    """
    host_crudo = str(det.get("host_stream") or "").strip()
    host = dominios.normalizar(host_crudo)
    ip = str(det.get("ip_servidor") or "").strip()
    pagina_host = dominios.host_de(det.get("pagina"))
    host_literal = dominios.es_ip(host)
    piratas = {dominios.normalizar(h) for h in hosts_piratas}
    refutados = {dominios.normalizar(r) for r in (refutados or ())}

    registrable_host = "" if host_literal else dominios.registrable(host)
    controla = controla_registrable(pagina_host, registrable_host)
    infiere = controla and registrable_host not in refutados
    operacion = {registrable_host} if infiere else set()
    operacion.discard("")
    pagina_propia = bool(pagina_host) and (host_literal or (
        bool(registrable_host) and dominios.registrable(pagina_host) == registrable_host))
    exactos = {host} | ({pagina_host} if pagina_propia else set())

    crudos_en_ip = [str(d) for d in (dns_ip or {}).get("dominios") or []]
    dominios_en_ip = [dominios.normalizar(d) for d in crudos_en_ip]
    # El nombre tal como lo escribe el simulador: es el que va en las órdenes por dominio.
    como_lo_escribe = {dominios.normalizar(d): d.strip() for d in crudos_en_ip}
    como_lo_escribe[host] = host_crudo
    observados = [d for d in dominios_en_ip if d in exactos or d in piratas]
    inferidos = [d for d in dominios_en_ip if d not in observados and infiere
                 and dominios.registrable(d) == registrable_host]
    propios = [d for d in dominios_en_ip if d in observados or d in inferidos]
    ajenos = [d for d in dominios_en_ip if d not in propios]
    hermanos_ajenos = [d for d in ajenos if registrable_host and dominios.registrable(d) == registrable_host]
    organizacion = (dns_ip or {}).get("organizacion")
    red_compartida = bool(organizacion) and any(p in str(organizacion).lower() for p in PALABRAS_RED_COMPARTIDA)

    # Coherencia entre la detección y el DNS pasivo.
    url_host = dominios.host_de(det.get("stream_url"))
    host_en_url = None if not det.get("stream_url") else (url_host == host)
    if host_literal:
        ip_en_dns_del_host = (host == ip)
        host_en_dns_de_la_ip = None
    else:
        ip_en_dns_del_host = None if dns_host is None else ip in [x.get("ip") for x in dns_host.get("ips") or []]
        host_en_dns_de_la_ip = None if dns_ip is None else host in dominios_en_ip
    asn_det = det.get("asn")
    asn_dns = (dns_ip or {}).get("asn")
    asn_coincide = None if (dns_ip is None or _asn(asn_det) is None or _asn(asn_dns) is None) \
        else (_asn(asn_det) == _asn(asn_dns))
    coherencia = {"host_en_url": host_en_url, "ip_en_dns_del_host": ip_en_dns_del_host,
                  "host_en_dns_de_la_ip": host_en_dns_de_la_ip, "asn_coincide": asn_coincide}
    observaciones = []
    if host_en_url is False:
        observaciones.append(f"El host de la URL del stream ({url_host}) no coincide con el host informado ({host}).")
    if ip_en_dns_del_host is False:
        observaciones.append(f"El DNS pasivo no ve el nombre {host} en la IP {ip}.")
    if host_en_dns_de_la_ip is False:
        observaciones.append(f"El DNS pasivo de la IP {ip} no incluye el nombre {host}.")
    if asn_coincide is False:
        observaciones.append(f"El ASN de la detección ({asn_det}) no coincide con el del DNS pasivo ({asn_dns}).")
    valores = list(coherencia.values())
    coherencia["ok"] = all(v is not False for v in valores)
    coherencia["completa"] = all(v is True for v in valores)
    coherencia["observaciones"] = observaciones

    ips_del_host = [x.get("ip") for x in (dns_host or {}).get("ips") or []] if not host_literal else []
    otras_ips = sorted({i for i in ips_del_host if i and i != ip})
    propios_txt = lista_corta(propios) if propios else host

    # Recomendación (la primera que se cumple).
    if host_literal and (ajenos or red_compartida or dns_ip is None or not coherencia["ok"]):
        recomendacion, riesgo = "ninguna", "alto"
        motivo = (f"El stream se sirve directamente desde la IP {host}, sin nombre de dominio, y no se puede "
                  "asegurar que esa IP sea exclusiva del pirata. Ningún bloqueo es seguro sin revisión: decide el juez.")
    elif dns_ip is None:
        recomendacion, riesgo = "dominio", "desconocido"
        motivo = (f"No hay datos de DNS pasivo de la IP {ip}: no se sabe qué otros sitios aloja. "
                  "Se bloquea solo el nombre del stream.")
    elif ajenos and hermanos_ajenos:
        recomendacion, riesgo = "dominio", "alto"
        motivo = (f"{host} comparte la IP con otros subdominios de {registrable_host} que no podemos atribuir al "
                  f"pirata ({lista_corta(ajenos)}). Bloquear la IP podría dejarlos sin servicio: se bloquea solo el "
                  "nombre del stream.")
    elif ajenos:
        recomendacion, riesgo = "dominio", "alto"
        n = len(ajenos)
        plural = "otro sitio que no tiene" if n == 1 else f"otros {n} sitios que no tienen"
        motivo = (f"La IP aloja {plural} que ver con el pirata ({lista_corta(ajenos)}). Bloquearla los dejaría "
                  "sin servicio: se bloquea solo el nombre del stream.")
    elif red_compartida:
        recomendacion, riesgo = "dominio", "medio"
        motivo = (f"La IP pertenece a una red compartida ({organizacion}): puede alojar otros sitios aunque el "
                  "DNS pasivo no los vea. Se bloquea solo el nombre del stream.")
    elif otras_ips:
        recomendacion, riesgo = "dominio", "nulo"
        motivo = (f"El nombre {host} también se ve en otras IP ({lista_corta(otras_ips)}): bloquear una sola IP "
                  "no alcanza. Se bloquea el nombre del stream.")
    elif not coherencia["ok"]:
        recomendacion, riesgo = "dominio", "desconocido"
        motivo = ("Los datos de la detección y del DNS pasivo no coinciden del todo; no conviene bloquear la IP "
                  "sin estar seguros. Se bloquea solo el nombre del stream.")
    else:
        recomendacion, riesgo = "ip", "nulo"
        motivo = motivo_ip_exclusiva(host, observados, inferidos, registrable_host, propios_txt)

    return {
        "servidor": {"pagina": det.get("pagina"), "stream_url": det.get("stream_url"), "host": host, "ip": ip,
                     "asn": asn_det, "organizacion": organizacion, "host_crudo": host_crudo,
                     "nombres_crudos": {p: como_lo_escribe.get(p, p) for p in [host] + propios}},
        "coherencia": coherencia,
        "colateral": {"dominios_en_ip": dominios_en_ip, "propios": propios, "ajenos": ajenos,
                      "observados": observados, "inferidos": inferidos,
                      "red_compartida": red_compartida, "riesgo": riesgo, "recomendacion": recomendacion,
                      "motivo": motivo},
        "operacion": sorted(operacion),
    }


# --- 4.4 La captura ----------------------------------------------------------------------


def decodificar_captura(captura: Optional[dict]) -> Optional[bytes]:
    if not isinstance(captura, dict) or not captura.get("contenido_b64"):
        return None
    try:
        # Se toleran saltos de línea y espacios (base64 «de mail», cortado cada 76 caracteres).
        return base64.b64decode("".join(str(captura["contenido_b64"]).split()), validate=True)
    except (binascii.Error, ValueError):
        return None


def analizar_captura(captura: Optional[dict], vistas: Optional[Set[str]] = None) -> dict:
    """`vistas` = sha256 ya vistos en OTRAS detecciones."""
    captura = captura or {}
    datos = decodificar_captura(captura)
    sha = hashlib.sha256(datos).hexdigest() if datos is not None else None
    formato = captura.get("formato")
    sync = None
    if datos is not None and formato == "mpegts":
        sync = len(datos) > 0 and datos[0] == 0x47
    elif datos is not None:
        sync = True  # Sin comprobación de sincronía para otros formatos.
    repetida = bool(sha and vistas and sha in vistas)
    return {
        "sha256": sha, "bytes": len(datos) if datos is not None else 0, "formato": formato,
        "duracion_seg": captura.get("duracion_seg"), "capturada_min": captura.get("capturada_min"),
        "sync_mpegts": bool(sync), "repetida": repetida,
        "valida": bool(datos) and bool(sync) and not repetida,
        "texto": TEXTO_HASH_CAPTURA if sha else None,
    }


def es_limpia(senal: dict, coherencia: dict, captura: dict, colateral: dict) -> bool:
    return (senal.get("clase") == "pirata" and bool(coherencia.get("completa")) and bool(captura.get("valida"))
            and colateral.get("recomendacion") != "ninguna")


# --- Cobertura (misma cuenta que el verificador oficial) --------------------------------------


def _minutos_detecciones(u: dict) -> List[float]:
    xs = [float(x) for x in (u.get("detecciones_min") or []) if _numero(x)]
    if not xs:
        xs = [float(x) for x in (u.get("primera_deteccion_min"), u.get("ultima_deteccion_min")) if _numero(x)]
    return xs


def ventana(ubicaciones: List[dict], u: dict, ahora: float, fin: float) -> Tuple[float, float]:
    """Ventana de una ubicación (adenda 3, A): desde su primera detección hasta la primera detección de OTRA
    ubicación del mismo expediente que sea posterior a su última detección propia; si no hay, sigue viva hasta
    min(ahora, fin). Único lugar donde se calcula."""
    propias = _minutos_detecciones(u)
    desde = min(propias) if propias else float(u.get("primera_deteccion_min") or 0)
    ultima = max(propias) if propias else desde
    vivo = min(float(ahora), float(fin))
    posteriores = [m for x in ubicaciones if x is not u and x.get("n") != u.get("n")
                   for m in _minutos_detecciones(x) if m > ultima]
    hasta = min(posteriores) if posteriores else vivo
    hasta = max(desde, min(hasta, max(vivo, desde)))
    return desde, hasta


def cobertura(desde: float, hasta: float, ip: str, host: str, ordenes: Iterable[dict],
              proveedores: List[dict]) -> dict:
    """Cobertura de una ubicación en la ventana [desde, hasta] con las órdenes que llegaron a aplicarse.

    Cuenta un bloqueo si es por IP con la IP de la ubicación o por dominio con exactamente su host.
    """
    hasta = max(float(hasta), float(desde))
    h = dominios.normalizar(host)
    coinciden = [o for o in ordenes if o.get("aplicada_min") is not None and (
        (o["tipo"] == "ip" and o["objetivo"] == ip)
        or (o["tipo"] == "dominio" and dominios.normalizar(o["objetivo"]) == h))]
    clientes = {p["id"]: p.get("clientes", 0) for p in proveedores}
    total = sum(clientes.values()) or 1
    duracion = max(hasta - desde, 1e-9)
    primer: Dict[str, float] = {}
    minutos: Dict[str, float] = {}
    for o in coinciden:
        ini = max(float(o["aplicada_min"]), desde)
        fin_o = min(float(o["finalizada_min"]) if o.get("finalizada_min") is not None else hasta, hasta)
        if fin_o - ini > 0:
            minutos[o["proveedor"]] = minutos.get(o["proveedor"], 0.0) + (fin_o - ini)
            primer[o["proveedor"]] = min(primer.get(o["proveedor"], 1e18), ini)
        elif hasta - desde < 1e-6 and float(o["aplicada_min"]) <= desde:
            primer[o["proveedor"]] = min(primer.get(o["proveedor"], 1e18), desde)
    aplicados = [p for p in clientes if p in primer]
    cubiertos = sum(clientes.get(p, 0) * min(m, duracion) for p, m in minutos.items())
    if hasta - desde < 1e-9:
        # Ventana de duración cero: no hay nada que medir (nunca «0,0 %» ni «None %»).
        return {"clientes_cubiertos_pct": round(100.0 * sum(clientes[p] for p in aplicados) / total, 1),
                "proveedores_aplicados": len(aplicados), "proveedores_total": len(clientes),
                "primer_bloqueo_min": None, "completo_min": None, "visibilidad_residual_pct": None,
                "sin_ventana": True}
    return {"sin_ventana": False,
            "clientes_cubiertos_pct": round(100.0 * sum(clientes[p] for p in aplicados) / total, 1),
            "proveedores_aplicados": len(aplicados), "proveedores_total": len(clientes),
            "primer_bloqueo_min": round(min(primer.values()) - desde, 2) if primer else None,
            "completo_min": round(max(primer.values()) - desde, 2) if primer and len(aplicados) == len(clientes)
            else None,
            "visibilidad_residual_pct": round(100.0 * (1 - cubiertos / (total * duracion)), 1)
            if hasta > desde else None}


# --- 4.5 La propuesta de bloqueo ---------------------------------------------------------


def texto_apartarse(colateral: dict, tipo: str, ip: str, host: str, vence: int,
                    fundamento_juez: Optional[str]) -> str:
    """El juez se aparta de la recomendación: el texto no puede contradecirse (sección 7)."""
    rec = colateral.get("recomendacion")
    if tipo == "ip":
        ordeno = f"ordenó bloquear la IP {ip} hasta el minuto {vence}"
    else:
        ordeno = f"ordenó bloquear el nombre {host} hasta el minuto {vence}"
    ajenos = list(colateral.get("ajenos") or [])
    if tipo == "ip" and ajenos:
        n = len(ajenos)
        riesgo = (f"Riesgo informado: la IP aloja {'otro sitio' if n == 1 else f'otros {n} sitios'} "
                  f"({lista_corta(ajenos, 5)}).")
    else:
        riesgo = f"Riesgo informado: {colateral.get('motivo')}"
    texto = f"El juez se apartó de la recomendación ({rec}) y {ordeno}. {riesgo}"
    if (fundamento_juez or "").strip():
        texto += f" Fundamento del juez: «{' '.join(fundamento_juez.split())}»."
    return texto


def proponer(analisis: dict, proveedores: List[dict], fin_min: float, forzar_tipo: Optional[str] = None,
             fundamento_juez: Optional[str] = None) -> dict:
    """Qué se bloquea en cada proveedor. Un solo tipo por proveedor."""
    servidor = analisis["servidor"]
    colateral = analisis["colateral"]
    host, ip = servidor["host"], servidor["ip"]
    vence = int(math.ceil(float(fin_min)))
    tipo = forzar_tipo or colateral["recomendacion"]
    objetivos: Dict[str, List[dict]] = {}
    sin_cobertura: List[str] = []
    host_literal = dominios.es_ip(host)

    if tipo == "ninguna":
        return {"tipo": "ninguna", "vence_min": vence,
                "fundamento": "No hay un bloqueo seguro recomendado: decide el juez. " + colateral["motivo"],
                "objetivos_por_proveedor": {}, "sin_cobertura": [p["id"] for p in proveedores]}

    # Las órdenes por dominio llevan el nombre EXACTAMENTE como lo escribe el simulador (mayúsculas, punto final):
    # lo normalizado se usa solo para comparar y para consultar.
    crudos = servidor.get("nombres_crudos") or {}
    host_obj = servidor.get("host_crudo") or host
    # Un nombre del DNS pasivo que no valida como objetivo (texto raro, saltos de línea) nunca va a una orden.
    nombres = [host_obj] + [n for n in (crudos.get(p, p) for p in colateral.get("propios") or [] if p != host)
                            if dominios.objetivo_valido("dominio", dominios.normalizar(n))]
    for p in proveedores:
        caps = p.get("capacidades") or []
        if tipo == "ip":
            if "ip" in caps:
                objetivos[p["id"]] = [{"tipo": "ip", "objetivo": ip}]
            elif "dominio" in caps and not host_literal:
                objetivos[p["id"]] = [{"tipo": "dominio", "objetivo": n} for n in nombres]
            else:
                sin_cobertura.append(p["id"])
        else:
            if "dominio" in caps and not host_literal:
                objetivos[p["id"]] = [{"tipo": "dominio", "objetivo": host_obj}]
            else:
                sin_cobertura.append(p["id"])

    if tipo == "ip":
        fundamento = (f"Bloqueo por IP de {ip} hasta el minuto {vence} (final del partido). "
                      "A los proveedores que solo bloquean por dominio se les piden los nombres del servidor pirata. "
                      + colateral["motivo"])
    else:
        fundamento = f"Bloqueo por dominio de {host} hasta el minuto {vence} (final del partido). " + colateral["motivo"]
    if forzar_tipo and forzar_tipo != colateral["recomendacion"]:
        fundamento = texto_apartarse(colateral, tipo, ip, host, vence, fundamento_juez)
    return {"tipo": tipo, "vence_min": vence, "fundamento": fundamento,
            "objetivos_por_proveedor": objetivos, "sin_cobertura": sin_cobertura}
