"""Verificador de integridad de una exportación. No necesita conexión ni la plataforma.

Reglas de esta herramienta:
- Nunca explota: un archivo ilegible o un campo con otro tipo es un ✗ con su nombre, y la verificación sigue.
- El cruce va en los dos sentidos: lo que nombra la auditoría (y el registro oficial o los testigos) tiene que
  estar en la exportación, y lo que está en la exportación tiene que estar en la auditoría.
- Un tipo de entrada desconocido no rompe nada: se informa como nota.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import sello as sello_mod
from .auditoria import hash_entrada
from .canon import CEROS, huella as calcular_huella, nombre_captura, sha256_hex

TIPOS_DECISION = ("decision_juez", "ampliacion_dinamica")
TIPOS_SELLO = ("decision_juez", "ampliacion_dinamica", "reclamo_resuelto")
TIPOS_CONOCIDOS = {
    "inicio", "reanudacion", "auditoria_reparada", "deteccion_recibida", "deteccion_descartada", "deteccion_invalida",
    "expediente_abierto", "expediente_anulado", "ubicacion_armada", "notificacion_juez", "expediente_visto",
    "decision_juez", "orden_dinamica_otorgada", "ampliacion_dinamica", "dinamica_revocada", "aviso_corte_en_origen",
    "orden_enviada", "orden_recibida", "orden_aplicada", "orden_fallida", "orden_reintentada", "orden_rechazada",
    "orden_vencida", "orden_levantada", "orden_en_espera", "orden_reconciliada", "orden_perdida",
    "traspaso_de_turno", "traspaso_ratificado", "reclamo_recibido", "reclamo_verificado", "reclamo_resuelto",
    "reclamo_invalido", "sesion_iniciada", "sesion_cerrada", "login_fallido", "partido_finalizado",
    "vencimiento_verificado", "testigos_guardados", "exportacion", "alerta",
    "orden_marco", "ubicacion_sin_decidir",
}
RE_UBIC_EN_ID = re.compile(r"^(?:ord|amp)-\d+-u(\d+)-")
RE_CABEZA_ACTA = re.compile(r"Cabeza de la auditoría: entrada (\d+), hash `([0-9a-f]{64}|None)`")


class Informe:
    def __init__(self) -> None:
        self.lineas: List[str] = []
        self.fallas = 0
        self.huella_paquete: Optional[str] = None

    def ok(self, texto: str) -> None:
        self.lineas.append("✓ " + texto)

    def mal(self, texto: str) -> None:
        self.fallas += 1
        self.lineas.append("✗ " + texto)

    def nota(self, texto: str) -> None:
        self.lineas.append("· " + texto)

    def chequear(self, condicion: bool, bien: str, mal: str) -> bool:
        (self.ok if condicion else self.mal)(bien if condicion else mal)
        return condicion

    def lista(self, malas: List[str], bien: str, titulo: str, tope: int = 8) -> None:
        """Un ✓ si no hay nada malo; si no, un ✗ por cada problema (hasta `tope`) y un resumen del resto."""
        if not malas:
            self.ok(bien)
            return
        for m in malas[:tope]:
            self.mal(m)
        if len(malas) > tope:
            self.mal(f"{titulo}: {len(malas) - tope} problema(s) más del mismo tipo")


class ClaveDuplicada(ValueError):
    pass


def _sin_duplicadas(pares):
    d = {}
    for k, v in pares:
        if k in d:
            raise ClaveDuplicada(f"clave duplicada {k!r}")
        d[k] = v
    return d


def loads(texto) -> Any:
    """json.loads que rechaza claves repetidas (una persona vería la primera; el hash cubre la última)."""
    return json.loads(texto, object_pairs_hook=_sin_duplicadas)


def cargar_json(inf: Informe, ruta: Path, nombre: str) -> Tuple[bool, Any]:
    try:
        return True, loads(ruta.read_bytes().decode("utf-8"))
    except FileNotFoundError:
        inf.mal(f"{nombre}: falta")
    except ClaveDuplicada as err:
        inf.mal(f"{nombre}: {err}")
    except (OSError, UnicodeDecodeError, ValueError) as err:
        inf.mal(f"{nombre}: no se puede leer como JSON ({type(err).__name__}: {str(err)[:120]})")
    return False, None


def _d(e: Any) -> dict:
    d = e.get("datos") if isinstance(e, dict) else None
    return d if isinstance(d, dict) else {}


def _dic(x: Any) -> dict:
    return x if isinstance(x, dict) else {}


def _lis(x: Any) -> list:
    return x if isinstance(x, list) else []


def llego_a_enviarse(o: dict) -> bool:
    if o.get("anulada"):
        return False
    return (o.get("recibida_min") is not None or o.get("aplicada_min") is not None
            or o.get("estado") in ("recibida", "aplicada", "fallida", "vencida", "levantada"))


# --- auditoría -------------------------------------------------------------------------------


def leer_auditoria(inf: Informe, ruta: Path) -> Tuple[Dict[int, dict], List[dict], bool]:
    """Recalcula la cadena y devuelve (entradas por n, entradas en orden, cadena_ok). Nunca lanza."""
    entradas: Dict[int, dict] = {}
    orden: List[dict] = []
    errores: List[str] = []
    try:
        crudo = ruta.read_bytes()
    except FileNotFoundError:
        inf.mal("auditoria.jsonl: falta")
        return entradas, orden, False
    except OSError as err:
        inf.mal(f"auditoria.jsonl: no se puede leer ({err})")
        return entradas, orden, False
    prev, cantidad = CEROS, 0
    for i, linea in enumerate(crudo.split(b"\n"), start=1):
        if not linea.strip():
            continue
        cantidad += 1
        try:
            e = loads(linea.decode("utf-8"))
        except ClaveDuplicada as err:
            errores.append(f"auditoria.jsonl línea {i}: {err}")
            prev = None
            continue
        except (UnicodeDecodeError, ValueError):
            errores.append(f"auditoria.jsonl línea {i}: no es JSON válido")
            prev = None
            continue
        if not isinstance(e, dict):
            errores.append(f"auditoria.jsonl línea {i}: no es un objeto")
            prev = None
            continue
        if e.get("n") != cantidad:
            errores.append(f"auditoria.jsonl línea {i}: campo n={e.get('n')}, se esperaba {cantidad} "
                           "(entrada borrada, agregada o fuera de orden)")
        if prev is not None and e.get("prev") != prev:
            errores.append(f"auditoria.jsonl línea {i} (n={e.get('n')}): campo prev no coincide con el hash de la "
                           "entrada anterior")
        try:
            calculado = hash_entrada(e)
        except (TypeError, ValueError):
            calculado = None
        if e.get("hash") != calculado:
            errores.append(f"auditoria.jsonl línea {i} (n={e.get('n')}): campo hash no coincide con el contenido "
                           "(la entrada fue modificada)")
        prev = e.get("hash")
        if isinstance(e.get("n"), int) and not isinstance(e.get("n"), bool):
            entradas[e["n"]] = e
            orden.append(e)
    if errores:
        for x in errores[:10]:
            inf.mal("Auditoría: " + x)
        if len(errores) > 10:
            inf.mal(f"Auditoría: {len(errores) - 10} error(es) más en la cadena")
    elif cantidad == 0:
        inf.mal("auditoria.jsonl: está vacía (una auditoría sin entradas no prueba nada)")
    else:
        inf.ok(f"Cadena de auditoría íntegra ({cantidad} entradas)")
    if orden and orden[0].get("tipo") != "inicio":
        inf.mal(f"auditoria.jsonl: la primera entrada es {orden[0].get('tipo')!r}, no «inicio» (falta el principio)")
    desconocidos = sorted({str(e.get("tipo")) for e in orden if e.get("tipo") not in TIPOS_CONOCIDOS})
    if desconocidos:
        inf.nota("Auditoría: tipos de entrada que esta versión no conoce (no se revisan): " + ", ".join(desconocidos))
    return entradas, orden, not errores and cantidad > 0


# --- manifiesto ------------------------------------------------------------------------------


def verificar_manifiesto(inf: Informe, carpeta: Path) -> None:
    """Paso 0: cada archivo del paquete contra MANIFIESTO.json (cambiado, faltante o sobrante)."""
    from .exportar import MANIFIESTO, archivos_del_paquete
    ruta = carpeta / MANIFIESTO
    if not ruta.exists():
        inf.nota("Paquete: sin manifiesto (no se puede detectar un cambio fuera de lo sellado)")
        return
    try:
        crudo = ruta.read_bytes()
    except OSError as err:
        inf.mal(f"MANIFIESTO.json: no se puede leer ({err})")
        return
    inf.huella_paquete = sha256_hex(crudo)
    try:
        doc = loads(crudo.decode("utf-8"))
        listados = {a["ruta"]: a for a in doc["archivos"]}
        if not all(isinstance(k, str) and isinstance(a, dict) for k, a in listados.items()):
            raise TypeError
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        inf.mal("MANIFIESTO.json no es válido")
        return
    malos = 0
    for rel, a in sorted(listados.items()):
        partes = Path(rel).parts
        if Path(rel).is_absolute() or ".." in partes:
            inf.mal(f"MANIFIESTO.json: ruta no permitida {rel}")
            malos += 1
            continue
        p = carpeta / rel
        if not p.is_file():
            inf.mal(f"{rel}: falta (figura en el manifiesto)")
            malos += 1
            continue
        datos = p.read_bytes()
        if len(datos) != a.get("bytes") or sha256_hex(datos) != a.get("sha256"):
            inf.mal(f"{rel}: cambió después de exportar (no coincide con el manifiesto)")
            malos += 1
    for p in archivos_del_paquete(carpeta):
        rel = p.relative_to(carpeta).as_posix()
        if rel not in listados:
            inf.mal(f"{rel}: no estaba en la exportación (sobra)")
            malos += 1
    if not malos:
        inf.ok(f"Paquete íntegro según MANIFIESTO.json ({len(listados)} archivos)")


# --- firmas ----------------------------------------------------------------------------------


def verificar_ampliaciones(inf: Informe, entradas: Dict[int, dict], claves: Optional[dict]) -> None:
    """Cada ampliación dinámica la hace el sistema, bajo una orden dinámica anterior del mismo expediente.

    Con claves (--config), su firma es obligatoria y tiene que verificar.
    """
    malas, buenas = [], 0
    for e in sorted(entradas.values(), key=lambda x: x["n"]):
        if e.get("tipo") != "ampliacion_dinamica":
            continue
        d = _d(e)
        juez, hab_n = d.get("bajo_orden_dinamica_de"), d.get("entrada_habilitante")
        hab = entradas.get(hab_n) if isinstance(hab_n, int) else None
        motivo = None
        if e.get("actor") != "sistema":
            motivo = f"actor {e.get('actor')!r} (una ampliación la hace el sistema, no el juez)"
        elif hab is None or hab["n"] >= e["n"]:
            motivo = f"la entrada habilitante {hab_n} no existe o no es anterior"
        elif hab.get("tipo") == "decision_juez":
            hd = _d(hab)
            if not (hab.get("exp") == e.get("exp") and hd.get("aprobar") and hd.get("alcance") == "filtracion"):
                motivo = f"la entrada habilitante {hab_n} no es una firma con alcance filtración de {e.get('exp')}"
        elif hab.get("tipo") == "traspaso_ratificado":
            hd = _d(hab)
            if e.get("exp") not in _lis(hd.get("dinamicas")) or hd.get("juez_id") != juez:
                motivo = f"la ratificación {hab_n} no alcanza a {e.get('exp')} o es de otro juez"
        else:
            motivo = f"la entrada habilitante {hab_n} es de tipo {hab.get('tipo')}"
        if motivo is None and claves is not None:
            clave = claves.get(juez)
            if not clave:
                motivo = f"no hay clave de firma para {juez!r} en --config"
            elif not d.get("firma_ampliacion"):
                motivo = "ampliación sin firma"
            else:
                try:
                    esperada = sello_mod.firma_ampliacion(clave, e.get("exp"), d.get("ubicacion"), d.get("huella"),
                                                          juez, hab_n)
                except (TypeError, ValueError, AttributeError):
                    esperada = None
                if esperada != d.get("firma_ampliacion"):
                    motivo = "la firma de la ampliación no verifica"
        if motivo:
            malas.append(f"entrada {e['n']}: {motivo}")
        else:
            buenas += 1
    if malas or buenas:
        inf.chequear(not malas, f"Ampliaciones automáticas ({buenas}) hechas por el sistema bajo una orden anterior"
                     + (", con su firma" if claves is not None else ""),
                     "Ampliaciones automáticas que no cierran: " + "; ".join(malas[:5]))


def cargar_claves(inf: Informe, config) -> Optional[dict]:
    """None si no se pidió --config; {} si se pidió y no sirve (ya informado como ✗)."""
    if not config:
        return None
    ok, cfg = cargar_json(inf, Path(config), f"--config {config}")
    if not ok:
        return {}
    claves = _dic(cfg).get("claves_firma_demo")
    if not isinstance(claves, dict) or not claves:
        inf.mal(f"--config {config}: no tiene claves_firma_demo: no se pueden verificar las firmas")
        return {}
    return {str(k): str(v) for k, v in claves.items()}


def verificar_firmas(inf: Informe, orden: List[dict], claves: dict) -> None:
    """Con --config: toda decisión del juez y todo levantamiento enviado traen su firma, y verifica."""
    malas: List[str] = []
    buenas = total = 0
    for e in orden:
        d, tipo, n = _d(e), e.get("tipo"), e.get("n")
        if tipo == "decision_juez" and "accion" not in d:
            total += 1
            juez = d.get("juez_id")
            ref = f"entrada {n} (decision_juez de {e.get('exp')} U{d.get('ubicacion')})"
            if not d.get("firma_decision"):
                malas.append(f"Firmas: {ref}: decisión sin firma")
                continue
            clave = claves.get(juez)
            if not clave:
                malas.append(f"Firmas: {ref}: no hay clave de firma para {juez!r} en --config")
                continue
            try:
                esperada = sello_mod.firma_decision(clave, e.get("exp"), d.get("ubicacion"), d.get("huella"),
                                                    bool(d.get("aprobar")), d.get("alcance"), juez)
            except (TypeError, ValueError, AttributeError):
                esperada = None
            if esperada == d["firma_decision"]:
                buenas += 1
            else:
                malas.append(f"Firmas: {ref}: la firma no verifica")
        elif tipo == "orden_levantada" and not d.get("anulada"):
            ref = f"entrada {n} (orden_levantada de {d.get('orden_id')})"
            if not d.get("firma") and d.get("confirmada_por_consulta"):
                inf.nota(f"Firmas: {ref}: levantamiento confirmado por consulta, sin firma registrada")
                continue
            total += 1
            juez = d.get("juez_id")
            if not d.get("firma"):
                malas.append(f"Firmas: {ref}: levantamiento sin firma")
                continue
            clave = claves.get(juez)
            if not clave:
                malas.append(f"Firmas: {ref}: no hay clave de firma para {juez!r} en --config")
                continue
            try:
                esperada = sello_mod.firma_levantamiento(clave, d.get("orden_id"), juez)
            except (TypeError, ValueError, AttributeError):
                esperada = None
            if esperada == d["firma"]:
                buenas += 1
            else:
                malas.append(f"Firmas: {ref}: la firma no verifica")
    inf.lista(malas, f"Firmas de decisión y levantamiento: {buenas} de {total} verificadas con las claves",
              "Firmas")


# --- orden marco (ronda 2b, sección 1) ---------------------------------------------------------


def verificar_marcos(inf: Informe, carpeta: Path, orden: List[dict], entradas: Dict[int, dict],
                     claves: Optional[dict]) -> None:
    """Cada orden marco: huella recalculada desde su contenido y, con --config, su firma. Cada ampliación cita una
    orden marco anterior del juez que la respalda, con el seguimiento autorizado y todavía vigente."""
    marcos = [e for e in orden if e.get("tipo") == "orden_marco"]
    amps = [e for e in orden if e.get("tipo") == "ampliacion_dinamica"]
    if not marcos and not amps:
        inf.nota("Sin orden marco: no se firmó ninguna y no hubo ampliaciones automáticas")
        return
    malas: List[str] = []
    for e in marcos:
        d = _d(e)
        ref = f"auditoría entrada {e['n']} (orden_marco {d.get('id')})"
        contenido = d.get("contenido")
        try:
            h = calcular_huella(contenido)
        except (TypeError, ValueError):
            h = None
        if not isinstance(contenido, dict) or h != d.get("huella"):
            malas.append(f"{ref}: la huella no es la de su contenido (texto cambiado)")
            continue
        juez = d.get("juez_id")
        if e.get("actor") != f"juez:{juez}" or _dic(contenido.get("juez")).get("juez_id") != juez:
            malas.append(f"{ref}: la firma un juez distinto del que figura en el texto ({e.get('actor')})")
        if bool(contenido.get("seguimiento")) != bool(d.get("seguimiento")):
            malas.append(f"{ref}: campo seguimiento no coincide con el texto firmado")
        if claves is not None:
            clave = claves.get(juez)
            pid = _dic(contenido.get("partido")).get("id")
            if not d.get("firma"):
                malas.append(f"{ref}: orden marco sin firma")
            elif not clave:
                malas.append(f"{ref}: no hay clave de firma para {juez!r} en --config")
            elif sello_mod.firma_marco(clave, pid, d.get("huella"), juez, bool(d.get("seguimiento"))) != d.get("firma"):
                malas.append(f"{ref}: la firma de la orden marco no verifica")
    for e in amps:
        d = _d(e)
        ref = f"auditoría entrada {e['n']} (ampliación de {e.get('exp')} U{d.get('ubicacion')})"
        om = _dic(d.get("orden_marco"))
        m = entradas.get(om.get("entrada")) if isinstance(om.get("entrada"), int) else None
        respaldo = d.get("bajo_orden_dinamica_de", d.get("juez_id"))
        if not om:
            malas.append(f"{ref}: ampliación sin orden marco")
        elif m is None or m.get("tipo") != "orden_marco" or m["n"] >= e["n"]:
            malas.append(f"{ref}: cita la orden marco de la entrada {om.get('entrada')}, que no existe o no es anterior")
        elif _d(m).get("juez_id") != respaldo:
            malas.append(f"{ref}: la orden marco citada es de {_d(m).get('juez_id')!r} y la ampliación la respalda "
                         f"{respaldo!r}")
        elif not _d(m).get("seguimiento"):
            malas.append(f"{ref}: la orden marco citada (entrada {m['n']}) no autoriza el seguimiento")
        elif om.get("huella") != _d(m).get("huella"):
            malas.append(f"{ref}: la huella de la orden marco citada no es la de la entrada {m['n']}")
        else:
            nuevas = [x for x in marcos if m["n"] < x["n"] < e["n"] and _d(x).get("juez_id") == respaldo]
            if nuevas:
                malas.append(f"{ref}: la orden marco de la entrada {m['n']} ya estaba reemplazada por la de la "
                             f"entrada {nuevas[0]['n']}")
    for e in orden:
        if e.get("tipo") == "decision_juez" and _d(e).get("orden_marco"):
            om = _dic(_d(e).get("orden_marco"))
            m = entradas.get(om.get("entrada")) if isinstance(om.get("entrada"), int) else None
            if m is None or m.get("tipo") != "orden_marco" or m["n"] >= e["n"] \
                    or _d(m).get("juez_id") != _d(e).get("juez_id") or om.get("huella") != _d(m).get("huella"):
                malas.append(f"auditoría entrada {e['n']}: la decisión cita una orden marco que no es una anterior "
                             "del mismo juez")
    # lo exportado en orden-marco/ es lo de la auditoría, en los dos sentidos
    exportados: Dict[str, dict] = {}
    carpeta_om = carpeta / "orden-marco"
    for arch in sorted(carpeta_om.glob("*.json")) if carpeta_om.is_dir() else []:
        ok, x = cargar_json(inf, arch, f"orden-marco/{arch.name}")
        if ok and isinstance(x, dict):
            exportados[arch.stem] = x
    for e in marcos:
        d = _d(e)
        x = exportados.pop(str(d.get("id")), None)
        if x is None:
            malas.append(f"auditoría entrada {e['n']}: la orden marco {d.get('id')} no está exportada "
                         f"(falta orden-marco/{d.get('id')}.json)")
            continue
        for campo, valor in (("entrada", e["n"]), ("huella", d.get("huella")), ("firma", d.get("firma")),
                             ("seguimiento", bool(d.get("seguimiento"))), ("contenido", d.get("contenido")),
                             ("juez_id", d.get("juez_id"))):
            if x.get(campo) != valor:
                malas.append(f"orden-marco/{d.get('id')}.json: campo {campo} no coincide con la entrada {e['n']}")
    for nombre in exportados:
        malas.append(f"orden-marco/{nombre}.json: no hay entrada orden_marco en la auditoría")
    inf.lista(malas, f"Orden marco: {len(marcos)} con su huella" + (" y su firma" if claves is not None else "")
              + f"; {len(amps)} ampliaciones bajo una orden marco vigente con seguimiento", "Orden marco")


def verificar_prefijos(inf: Informe, fuentes: List[Tuple[str, List[Tuple[Any, Any, Any]]]],
                       ampliadas: set) -> None:
    """amp- ⇔ la decisión de esa ubicación es una ampliación automática (sección 3). `fuentes`: (nombre,
    [(exp, orden_id, origen)])."""
    problemas: Dict[str, Tuple[str, List[str]]] = {}
    for fuente, ordenes in fuentes:
        for exp_id, oid, origen in ordenes:
            if not isinstance(oid, str) or exp_id is None:
                continue  # orden ajena a nuestra auditoría: ya sale en el cruce; su ubicación no se conoce
            m = RE_UBIC_EN_ID.match(oid)
            if not m:
                continue
            ampliada = (exp_id, int(m.group(1))) in ampliadas
            texto = None
            if oid.startswith("amp-") and not ampliada:
                texto = "empieza con amp- y la ubicación no es una ampliación automática (la firmó un juez en persona)"
            elif oid.startswith("ord-") and ampliada and origen == "decision":
                texto = "empieza con ord- y la ubicación es una ampliación automática (tendría que empezar con amp-)"
            if texto:
                problemas.setdefault(oid, (texto, []))[1].append(fuente)
    malas = [f"{oid} {texto} (en {', '.join(dict.fromkeys(donde))})" for oid, (texto, donde) in problemas.items()]
    inf.lista(malas, "Números de orden: amp- solo en ampliaciones automáticas, y toda ampliación con amp-",
              "Números de orden")


def verificar_legibles(inf: Informe, carpeta: Path, orden: List[dict]) -> None:
    """Los .md se vuelven a generar desde los .json y se comparan: un .md editado no verifica (sección 8)."""
    from . import exportar as exportar_mod
    ok, resumen = cargar_json(inf, carpeta / "resumen.json", "resumen.json") if (carpeta / "resumen.json").exists() \
        else (False, None)
    if not ok or not isinstance(resumen, dict):
        return
    if (resumen.get("formato") or 0) < exportar_mod.FORMATO:
        inf.nota("Exportación de una versión anterior: no se comparan los .md con los .json")
        return
    expedientes = []
    for arch in sorted((carpeta / "expedientes").glob("*.json")):
        ok, x = cargar_json(inf, arch, f"expedientes/{arch.name}")
        if not ok or not isinstance(x, dict):
            return  # ya informado: sin todos los .json no se puede regenerar
        expedientes.append(x)
    expedientes.sort(key=lambda x: (x.get("num") or 0, str(x.get("id"))))
    marcos = []
    for arch in sorted((carpeta / "orden-marco").glob("*.json")) if (carpeta / "orden-marco").is_dir() else []:
        ok, x = cargar_json(inf, arch, f"orden-marco/{arch.name}")
        if not ok or not isinstance(x, dict):
            return
        marcos.append(x)
    marcos.sort(key=lambda x: x.get("entrada") or 0)
    try:
        esperados = exportar_mod.legibles(resumen, expedientes, marcos)
    except Exception as err:
        inf.mal(f"Los .md no se pueden regenerar desde los .json ({type(err).__name__}: {str(err)[:100]})")
        return
    malas: List[str] = []
    for rel, texto in esperados.items():
        ruta = carpeta / rel
        try:
            actual = ruta.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            malas.append(f"{rel}: falta o no se puede leer")
            continue
        if actual != texto:
            malas.append(f"{rel}: no es el que sale de los .json (texto editado a mano)")
    for ruta in list((carpeta / "expedientes").glob("*.md")) + list((carpeta / "orden-marco").glob("*.md")):
        rel = ruta.relative_to(carpeta).as_posix()
        if rel not in esperados:
            malas.append(f"{rel}: no corresponde a ningún .json exportado")
    inf.lista(malas, f"Textos legibles ({len(esperados)} .md) iguales a los que salen de los .json", "Textos legibles")
    verificar_derivados(inf, resumen, expedientes, marcos, orden)


def _comparar_campos(malas: List[str], ref: str, campo: str, exportado: Any, esperado: Any, fuente: str) -> None:
    """Como _comparar, pero en un dict nombra solo las claves que difieren (un ✗ corto y que dice qué cambió)."""
    if isinstance(exportado, dict) and isinstance(esperado, dict):
        for k in sorted(set(exportado) | set(esperado), key=str):
            _comparar(malas, ref, f"{campo}.{k}" if campo else str(k), exportado.get(k), esperado.get(k), fuente)
    else:
        _comparar(malas, ref, campo, exportado, esperado, fuente)


def _hechos_de_ordenes(entradas: List[dict]) -> Tuple[Dict[Any, Any], Dict[Any, Tuple[str, Any]]]:
    """(aplicada_min de la primera orden_aplicada, último estado final con su minuto) de cada orden_id."""
    aplicada: Dict[Any, Any] = {}
    final: Dict[Any, Tuple[str, Any]] = {}
    for e in entradas:
        t, d = e.get("tipo"), _d(e)
        oid = d.get("orden_id")
        if t == "orden_aplicada":
            aplicada.setdefault(oid, d.get("aplicada_min"))
        elif t == "orden_vencida":
            final[oid] = ("vencida", d.get("finalizada_min"))
        elif t == "orden_levantada":
            # Anulada = nunca salió: no trae minuto de fin del proveedor.
            final[oid] = ("levantada", None if d.get("anulada") else d.get("finalizada_min"))
        elif t in ("orden_fallida", "orden_perdida", "orden_rechazada"):
            final[oid] = (t[len("orden_"):], None)
    return aplicada, final


def verificar_derivados(inf: Informe, resumen: dict, expedientes: List[dict], marcos: List[dict],
                        orden: List[dict]) -> None:
    """Lo que el acta muestra y no está sellado (estado y minutos de cada orden, tiempos, cobertura, órdenes marco,
    nombres de jueces, descartes y reclamos) se recalcula desde la auditoría con las mismas funciones del exportador
    (paquete-1). Así un .json editado no verifica aunque se regeneren los .md y el manifiesto.

    La auditoría siempre va adelante del estado.json exportado (se anota antes de guardar). Lo que la plataforma
    anotó después de la foto de los proveedores (el corte) puede no estar en ese estado.json: una diferencia que se
    explica por entradas posteriores al corte es nota; cualquier otra es ✗."""
    from . import evidencia, exportar as ex
    malas: List[str] = []
    notas: List[str] = []
    por_tipo: Dict[str, List[dict]] = {}
    for e in orden:
        por_tipo.setdefault(e.get("tipo"), []).append(e)
    corte = corte_del_estado(por_tipo)
    posteriores = [e for e in orden if corte is not None and isinstance(e.get("n"), int) and e["n"] > corte]
    tocadas_despues = {_d(e).get("orden_id") for e in posteriores if _d(e).get("orden_id") is not None}
    aplicada, final = _hechos_de_ordenes(orden)
    todas = [o for x in expedientes for u in _lis(x.get("ubicaciones")) for o in _lis(_dic(u).get("ordenes"))]
    todas += _lis(resumen.get("ordenes_sin_ubicacion"))
    for o in todas:
        if not isinstance(o, dict):
            continue
        oid, est = o.get("orden_id"), o.get("estado")
        propias: List[str] = []
        if oid in aplicada:
            _comparar(propias, f"orden {oid}", "aplicada_min", o.get("aplicada_min"), aplicada[oid],
                      "su orden_aplicada")
        elif o.get("aplicada_min") is not None and est != "levantada":
            propias.append(f"orden {oid}: campo aplicada_min es {o.get('aplicada_min')!r} y no hay entrada "
                           "orden_aplicada")
        if oid in final:
            fe, fmin = final[oid]
            _comparar(propias, f"orden {oid}", "estado", est, fe, f"su entrada orden_{fe}")
            if fe == "vencida" or (fe == "levantada" and fmin is not None):
                _comparar(propias, f"orden {oid}", "finalizada_min", o.get("finalizada_min"), fmin, f"su orden_{fe}")
        elif est in ex.ESTADOS_RETIRADOS or (est == "aplicada" and oid not in aplicada):
            propias.append(f"orden {oid}: campo estado es {est!r} y la auditoría no lo registra")
        (notas if propias and oid in tocadas_despues else malas).extend(propias)
    provs = _lis(resumen.get("proveedores"))
    partido = _dic(resumen.get("partido"))
    try:
        fin = float(partido.get("fin_min") or 0)
        ahora = float(resumen.get("minuto") or fin)
    except (TypeError, ValueError):
        malas.append("resumen.json: minuto o fin del partido ilegibles")
        fin = ahora = 0.0
    todas_ubics = [u for x in expedientes for u in _lis(x.get("ubicaciones")) if isinstance(u, dict)]
    for x in expedientes:
        ubics = [u for u in _lis(x.get("ubicaciones")) if isinstance(u, dict)]
        for u in ubics:
            ref = f"expedientes/{x.get('id')}.json U{u.get('n')}"
            # c1-integridad-2: el colateral que se muestra es el sellado (el sellado lo ancla la huella).
            # f-colateral-2: si una refutación anotada en la auditoría rehízo el pedido en espera, el colateral es el
            # que sale de rehacer el análisis con la MISMA evidencia sellada y los registrables refutados hasta ahí.
            _comparar(malas, ref, "colateral", u.get("colateral"), _colateral_esperado(u, orden, todas_ubics, x.get("id")),
                      "sellado.colateral (o su recálculo por la refutación de la auditoría)")
            try:
                desde, hasta = evidencia.ventana(ubics, u, ahora, fin)
                _comparar(malas, ref, "ventana", u.get("ventana"), [ex.r3(desde), ex.r3(hasta)], "el recálculo")
                _comparar_campos(malas, ref, "cobertura", u.get("cobertura"),
                                 evidencia.cobertura(desde, hasta, u.get("ip"), u.get("host"), todas, provs),
                                 "el recálculo")
                _comparar_campos(malas, ref, "tiempos", u.get("tiempos"), ex.tiempos_ubicacion(u, provs),
                                 "el recálculo")
            except Exception as err:  # un .json roto no deja al verificador sin informe
                malas.append(f"{ref}: no se puede recalcular ventana, cobertura y tiempos "
                             f"({type(err).__name__}: {str(err)[:80]})")
    try:
        _comparar_campos(malas, "resumen.json", "tiempos", resumen.get("tiempos"),
                         ex.armar_tiempos(expedientes, ex.quien_firmo(orden)), "el recálculo desde la auditoría")
        esperados = {m.get("id"): m for m in ex.armar_marcos(orden, expedientes, partido)}
    except Exception as err:
        malas.append(f"resumen.json: no se pueden recalcular los tiempos ni las órdenes marco "
                     f"({type(err).__name__}: {str(err)[:80]})")
        esperados = {}
    for m in marcos:
        _comparar_campos(malas, f"orden-marco/{m.get('id')}.json", "", m, esperados.get(m.get("id")) or {},
                         "la auditoría")
    nombres = {_d(e).get("juez_id"): _dic(_dic(_d(e).get("contenido")).get("juez")).get("nombre")
               for e in orden if e.get("tipo") == "orden_marco"}
    for x in expedientes:
        for u in _lis(x.get("ubicaciones")):
            dec = _dic(_dic(u).get("decision"))
            if dec.get("juez_id") in nombres and dec.get("juez") is not None:
                _comparar(malas, f"expedientes/{x.get('id')}.json U{_dic(u).get('n')}", "decision.juez",
                          dec.get("juez"), nombres[dec["juez_id"]], "el texto de su orden marco")
    # Descartes y reclamos: lo anotado hasta el corte tiene que estar en el resumen, y el resumen no puede tener nada
    # que la auditoría no anotó. Sitio y clase, no «veces»: tras un corte la auditoría puede tener uno más.
    def conjunto(tipo: str, clave) -> Tuple[set, set]:
        todo = {clave(_d(e)) for e in orden if e.get("tipo") == tipo}
        hasta = {clave(_d(e)) for e in orden if e.get("tipo") == tipo
                 and (corte is None or not isinstance(e.get("n"), int) or e["n"] <= corte)}
        return todo, hasta

    def cotejar(ref: str, exportado: set, todo: set, hasta: set, fuente: str) -> None:
        de_mas, faltan = sorted(exportado - todo, key=str), sorted(hasta - exportado, key=str)
        if de_mas:
            malas.append(f"{ref}: {de_mas[:5]} no figuran en {fuente}")
        if faltan:
            malas.append(f"{ref}: faltan {faltan[:5]}, que están en {fuente}")
        tarde = sorted((todo - hasta) - exportado, key=str)
        if tarde:
            notas.append(f"{ref}: {len(tarde)} anotado(s) en la auditoría después de la foto, no están en el resumen")

    clave_desc = lambda d: (str(d.get("host")), str(d.get("clase")))  # noqa: E731
    cotejar("resumen.json descartes (sitio y clase)",
            {clave_desc(d) for d in _lis(resumen.get("descartes")) if isinstance(d, dict)},
            *conjunto("deteccion_descartada", clave_desc), "deteccion_descartada")
    rec_exp = {str(r.get("id")): r for r in _lis(resumen.get("reclamos")) if isinstance(r, dict)}
    cotejar("resumen.json reclamos", set(rec_exp), *conjunto("reclamo_recibido", lambda d: str(d.get("reclamo"))),
            "reclamo_recibido")
    resueltos = {str(_d(e).get("reclamo")): (_d(e).get("accion"), e.get("n")) for e in orden
                 if e.get("tipo") == "reclamo_resuelto"}
    for rid, r in rec_exp.items():
        accion = _dic(r.get("resolucion")).get("accion")
        if accion is None and rid not in resueltos:
            continue
        esperado, n_res = resueltos.get(rid, (None, None))
        if accion != esperado:
            texto = (f"resumen.json reclamo {rid}: campo resolucion.accion es {accion!r} y reclamo_resuelto dice "
                     f"{esperado!r}")
            tarde = accion is None and corte is not None and isinstance(n_res, int) and n_res > corte
            (notas if tarde else malas).append(texto)
    for texto in notas[:8]:
        inf.nota(texto)
    inf.lista(malas, "Lo derivado (estado y minutos de las órdenes, tiempos, cobertura, órdenes marco, jueces, "
              "descartes y reclamos) se recalcula igual desde la auditoría", "Lo derivado")


# --- cruces con fuentes externas ---------------------------------------------------------------


def cruzar_ordenes(inf: Informe, fuente: str, ajenas: List[dict], nuestras: Dict[str, dict], enviadas_audit,
                   sellos: Dict[str, Optional[str]], perdidas=frozenset(), tardias=frozenset(),
                   corte: Optional[int] = None) -> None:
    """Compara órdenes de una fuente externa (registro oficial o testigos) con las nuestras, en los dos sentidos.

    No se le exige a la fuente: una orden perdida (la auditoría anotó `orden_perdida` o su estado es «perdida»:
    desapareció de la lista del proveedor) ni, en los testigos, una orden `tardia` (se envió después de la foto de
    los proveedores, `corte`). Las dos se informan como nota si faltan; cualquier otra que falta es ✗."""
    por_id = {}
    for a in ajenas:
        if isinstance(a, dict):
            por_id[(a.get("proveedor"), a.get("orden_id"))] = a
    faltan, distintas, extras, sin_exp, mal_sello = [], [], [], [], []
    no_exigidas_perdidas, no_exigidas_tardias = [], []
    for o in nuestras.values():
        if not llego_a_enviarse(o) and o.get("estado") != "perdida":
            continue
        a = por_id.get((o.get("proveedor"), o["orden_id"]))
        if a is None:
            if o["orden_id"] in perdidas or o.get("estado") == "perdida":
                no_exigidas_perdidas.append(o["orden_id"])
            elif o["orden_id"] in tardias:
                no_exigidas_tardias.append(o["orden_id"])
            else:
                faltan.append(o["orden_id"])
            continue
        for campo in ("tipo", "objetivo", "vence_min", "juez_id"):
            if a.get(campo) != o.get(campo):
                distintas.append(f"{o['orden_id']}: campo {campo} es {a.get(campo)!r} en {fuente} y "
                                 f"{o.get(campo)!r} en la exportación")
    for (pid, oid), a in por_id.items():
        if oid not in enviadas_audit:
            extras.append(f"{pid}/{oid}")
        o = nuestras.get(oid)
        if o is None or o.get("proveedor") != pid:
            sin_exp.append(f"{pid}/{oid}")
            continue
        esperado = sellos.get(oid)
        if esperado is None or not str(oid).endswith("-" + esperado):
            mal_sello.append(str(oid))
    inf.chequear(not faltan, f"{fuente}: todas las órdenes enviadas figuran",
                 f"{fuente}: faltan {len(faltan)} órdenes: {', '.join(faltan[:5])}")
    if no_exigidas_perdidas:
        inf.nota(f"{fuente}: {len(no_exigidas_perdidas)} orden(es) perdida(s) (desaparecieron de la lista del "
                 f"proveedor y se volvieron a emitir) no figuran; no se les exige: {', '.join(no_exigidas_perdidas[:5])}")
    if no_exigidas_tardias:
        inf.nota(f"{fuente}: {len(no_exigidas_tardias)} orden(es) enviada(s) después de la foto de los proveedores "
                 f"(entrada {corte} de la auditoría) no figuran; el partido siguió después de exportar: "
                 f"{', '.join(no_exigidas_tardias[:5])}")
    inf.chequear(not distintas, f"{fuente}: tipo, objetivo, vencimiento y juez coinciden",
                 f"{fuente}: {len(distintas)} diferencias: " + "; ".join(distintas[:5]))
    inf.chequear(not extras, f"{fuente}: no hay órdenes ajenas a nuestra auditoría",
                 f"{fuente}: {len(extras)} órdenes que no están en la auditoría: {', '.join(extras[:5])}")
    inf.chequear(not sin_exp, f"{fuente}: cada orden está en un expediente exportado",
                 f"{fuente}: {len(sin_exp)} órdenes que no están en ningún expediente exportado "
                 f"(expediente, ubicación u orden borrados): {', '.join(sin_exp[:5])}")
    inf.chequear(not mal_sello, f"{fuente}: cada orden_id termina en su sello recalculado",
                 f"{fuente}: orden_id con sello que no cierra: {', '.join(mal_sello[:5])}")


def leer_registro(inf: Informe, registro) -> Optional[List[dict]]:
    try:
        crudo = Path(registro).read_bytes()
    except OSError as err:
        inf.mal(f"registro oficial {registro}: no se puede leer ({err})")
        return None
    eventos, malas = [], []
    for i, linea in enumerate(crudo.split(b"\n"), start=1):
        if not linea.strip():
            continue
        try:
            ev = loads(linea.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            malas.append(i)
            continue
        if isinstance(ev, dict):
            eventos.append(ev)
        else:
            malas.append(i)
    if malas:
        inf.mal(f"registro oficial: líneas que no son JSON válido: {malas[:10]}")
    return eventos


# --- verificación ----------------------------------------------------------------------------


def corte_de_la_foto(por_tipo: Dict[str, List[dict]]) -> Optional[int]:
    """Última entrada de la auditoría anterior a la foto de los proveedores del paquete: el `corte_auditoria` de la
    última `testigos_guardados` (sin ese dato, la entrada anterior a ella: la foto se sacó antes de anotarla).
    None si el paquete no tiene testigos. Lo que la plataforma anotó después del corte puede no estar en esa foto
    ni en el estado.json que se exportó con ella: el partido siguió después de exportar."""
    guardados = [e for e in por_tipo.get("testigos_guardados", []) if isinstance(e.get("n"), int)]
    if not guardados:
        return None
    ultima = guardados[-1]
    corte = _d(ultima).get("corte_auditoria")
    if isinstance(corte, int) and not isinstance(corte, bool) and 0 <= corte < ultima["n"]:
        return corte
    return ultima["n"] - 1


def corte_del_estado(por_tipo: Dict[str, List[dict]]) -> Optional[int]:
    """Hasta qué entrada de la auditoría el estado.json exportado tiene que reflejar todo, anclado en la propia
    auditoría (nadie lo puede correr sin romper la cadena): la plataforma guarda el estado en la misma pasada en que
    anota la foto de los proveedores (corte) y la exportación del cierre (`exportacion`). Lo posterior puede faltar
    en un estado exportado con el partido en curso; con el paquete del cierre no queda nada posterior. None si no
    hay ninguna de las dos (entonces no se tolera nada)."""
    candidatos = [c for c in (corte_de_la_foto(por_tipo),) if c is not None]
    candidatos += [e["n"] for e in por_tipo.get("exportacion", []) if isinstance(e.get("n"), int)
                   and not isinstance(e.get("n"), bool) and e.get("actor") == "sistema"]
    return max(candidatos) if candidatos else None


def _colateral_esperado(u: dict, orden: List[dict], ubics: List[dict], exp_id: Any = None) -> Any:
    """El colateral que debe mostrar la ubicación: el sellado, salvo que `recalculada` cite una inferencia_refutada de
    la auditoría; entonces, el del motor (`_recalcular_pendientes`) con esa evidencia sellada y lo refutado hasta esa
    entrada. Lo «observado» no puede salir de la nada: solo lo sellado o hosts de ubicaciones del paquete."""
    from . import evidencia
    sel = _dic(u.get("sellado"))
    rec = _dic(u.get("recalculada"))
    refut = [e for e in orden if e.get("tipo") == "inferencia_refutada"]
    hasta = next((e.get("n") for e in refut if rec and _d(e).get("reclamo") == rec.get("reclamo")
                  and _d(e).get("registrable") == rec.get("registrable")), None)
    if hasta is None:
        return sel.get("colateral")
    # El motor rehace solo pedidos que esperaban firma: si la ubicación ya estaba decidida antes de la refutación, su
    # colateral es el sellado, diga lo que diga `recalculada`.
    decidida = any(e.get("tipo") in ("decision_juez", "ampliacion_dinamica") and e.get("exp") == exp_id
                   and _d(e).get("ubicacion") == u.get("n") and "aprobar" in _d(e)
                   and isinstance(e.get("n"), int) and e["n"] < hasta for e in orden)
    if decidida:
        return sel.get("colateral")
    try:
        col = _dic(u.get("colateral"))
        hosts = {str(x.get("host")) for x in ubics}
        piratas = set(_lis(_dic(sel.get("colateral")).get("observados"))) | {
            h for h in _lis(col.get("observados")) if h in hosts}
        refutados = [_d(e).get("registrable") for e in refut if isinstance(e.get("n"), int) and e["n"] <= hasta]
        dns = _dic(sel.get("dns_pasivo"))
        an = evidencia.analizar_servidor(_dic(sel.get("deteccion")), _dic(dns.get("por_ip")).get(u.get("ip")),
                                         _dic(dns.get("por_host")).get(u.get("host")), piratas, refutados)
        esperado = dict(an["colateral"])
        esperado["limpia"] = evidencia.es_limpia(_dic(u.get("senal")), an["coherencia"], sel.get("captura"), esperado)
        return esperado
    except Exception:  # evidencia sellada ilegible: que la comparación con lo sellado lo marque
        return sel.get("colateral")


def _comparar(malas: List[str], ref: str, campo: str, exportado: Any, esperado: Any, fuente: str) -> None:
    if exportado != esperado:
        malas.append(f"{ref}: campo {campo} es {exportado!r} y {fuente} dice {esperado!r}")


def verificar(carpeta, registro=None, config=None, huella_publicada=None, inf: Optional[Informe] = None) -> Informe:
    carpeta = Path(carpeta)
    inf = inf if inf is not None else Informe()
    if not carpeta.is_dir():
        inf.mal(f"{carpeta}: la carpeta no existe" if not carpeta.exists() else
                f"{carpeta}: no es una carpeta (se verifica la carpeta exportada, por ejemplo entrega/partido-final)")
        return inf

    # 0. Manifiesto del paquete.
    verificar_manifiesto(inf, carpeta)
    if huella_publicada:
        inf.chequear(inf.huella_paquete == str(huella_publicada).strip().lower(),
                     "Huella del paquete igual a la publicada",
                     f"Huella del paquete {inf.huella_paquete} distinta de la publicada {huella_publicada}")

    # 1. Cadena de auditoría.
    entradas, orden, cadena_ok = leer_auditoria(inf, carpeta / "auditoria.jsonl")
    pos_cadena = len(inf.lineas)
    por_tipo: Dict[str, List[dict]] = {}
    for e in orden:
        por_tipo.setdefault(str(e.get("tipo")), []).append(e)
    enviadas: Dict[str, dict] = {}
    for e in por_tipo.get("orden_enviada", []):
        oid = _d(e).get("orden_id")
        if isinstance(oid, str):
            enviadas[oid] = e  # la última manda (reintentos con el mismo orden_id)
    levantadas = {_d(e).get("orden_id") for e in por_tipo.get("orden_levantada", [])}
    perdidas = {_d(e).get("orden_id") for e in por_tipo.get("orden_perdida", [])}
    anulados = {e.get("exp") for e in por_tipo.get("expediente_anulado", [])}
    det_sha = {}
    for e in por_tipo.get("deteccion_recibida", []):
        det_sha[_d(e).get("deteccion")] = (e["n"], _d(e).get("captura_sha256"))

    claves = cargar_claves(inf, config)

    # 2-4. Expedientes.
    nuestras: Dict[str, dict] = {}
    sellos: Dict[str, Optional[str]] = {}
    exportadas: Dict[Tuple[str, Any], str] = {}   # (exp, n) -> huella recalculada
    decisiones_citadas = set()
    exps_exportados = set()
    legibles: List[str] = []
    sellos_rotos: List[int] = []
    capturas_malas: List[str] = []
    try:
        archivos = sorted((carpeta / "expedientes").glob("*.json"))
    except OSError:
        archivos = []
    if not archivos:
        inf.nota("No hay expedientes exportados.")
    for arch in archivos:
        ok, exp = cargar_json(inf, arch, f"expedientes/{arch.name}")
        if not ok:
            continue
        try:
            _verificar_expediente(inf, carpeta, arch, exp, entradas, enviadas, levantadas, det_sha, nuestras, sellos,
                                  exportadas, decisiones_citadas, exps_exportados, legibles, sellos_rotos,
                                  capturas_malas)
        except Exception as err:  # un campo con otro tipo: se informa y se sigue con el resto
            inf.mal(f"expedientes/{arch.name}: estructura inválida ({type(err).__name__}: {str(err)[:120]})")
    if nuestras:
        inf.ok(f"{len(nuestras)} órdenes revisadas contra sus sellos")
    inf.lista(capturas_malas, "Capturas de las redetecciones coinciden con su sha256 en la auditoría", "Capturas")
    inf.lista(legibles, "Lo legible coincide con lo sellado y la auditoría (host, ip, decisión y órdenes)",
              "Lo legible")
    if cadena_ok and sellos_rotos:
        primera = min(sellos_rotos)
        inf.lineas.insert(pos_cadena, f"✗ Auditoría: la cadena verifica, pero la entrada {primera} ya no da el sello que "
                          "anclan los orden_id: la auditoría se reescribió y se recalculó entera desde la entrada "
                          f"{primera} o antes")
        inf.fallas += 1

    # 4b. Lo que nombra la auditoría tiene que estar en la exportación. Lo anotado después de la foto de los
    #     proveedores (corte) o de la exportación del cierre puede no estar en el estado exportado: es nota, no ✗.
    corte = corte_del_estado(por_tipo)
    faltan: List[str] = []
    posteriores: List[str] = []

    def falta(e: dict, texto: str) -> None:
        (posteriores if corte is not None and e["n"] > corte else faltan).append(texto)

    for e in por_tipo.get("expediente_abierto", []):
        if e.get("exp") not in anulados and e.get("exp") not in exps_exportados:
            falta(e, f"auditoría entrada {e['n']}: el expediente {e.get('exp')} no está exportado "
                     f"(falta expedientes/{e.get('exp')}.json)")
    # robustez-3: una caída entre auditar y guardar estado.json deja entradas que el estado no refleja; al reanudar,
    # la entrada «reanudacion» dice hasta dónde llegaba el estado (estado_hasta_entrada < n <= entradas_previas) y la
    # ubicación se vuelve a armar después. Vale la posterior; la anterior es nota, no «evidencia reescrita».
    sin_estado = []
    for e in por_tipo.get("reanudacion", []):
        hasta, previas = _d(e).get("estado_hasta_entrada"), _d(e).get("entradas_previas")
        if isinstance(hasta, int) and isinstance(previas, int) and not isinstance(hasta, bool) and hasta < previas:
            sin_estado.append((hasta, previas, e["n"]))
    armadas_todas = por_tipo.get("ubicacion_armada", [])
    for e in armadas_todas:
        d = _d(e)
        clave = (e.get("exp"), d.get("ubicacion"))
        if e.get("exp") in anulados:
            continue
        if any(h < e["n"] <= p and any(x["n"] > r and (x.get("exp"), _d(x).get("ubicacion")) == clave
                                       for x in armadas_todas) for h, p, r in sin_estado):
            inf.nota(f"Auditoría entrada {e['n']}: {e.get('exp')} U{d.get('ubicacion')} se armó y la plataforma se "
                     "cayó antes de guardarla; al reanudar se volvió a armar (vale la entrada posterior).")
            continue
        if clave not in exportadas:
            falta(e, f"auditoría entrada {e['n']}: la ubicación U{d.get('ubicacion')} de {e.get('exp')} no está "
                     f"en expedientes/{e.get('exp')}.json")
        elif exportadas[clave] != d.get("huella"):
            faltan.append(f"auditoría entrada {e['n']}: la huella de {e.get('exp')} U{d.get('ubicacion')} no es la "
                          "del sellado exportado (evidencia reescrita)")
    for e in por_tipo.get("decision_juez", []) + por_tipo.get("ampliacion_dinamica", []):
        d = _d(e)
        if e.get("tipo") == "decision_juez" and "accion" in d:
            continue
        if e.get("exp") not in anulados and e["n"] not in decisiones_citadas:
            falta(e, f"auditoría entrada {e['n']} ({e.get('tipo')} de {e.get('exp')} U{d.get('ubicacion')}): "
                     f"ninguna ubicación de expedientes/{e.get('exp')}.json tiene esa decisión")
    for oid, e in enviadas.items():
        if oid not in nuestras:
            falta(e, f"auditoría entrada {e['n']}: la orden enviada {oid} no está en ningún expediente exportado")
    armadas = {(e.get("exp"), _d(e).get("ubicacion")) for e in por_tipo.get("ubicacion_armada", [])}
    for (exp_id, n) in exportadas:
        if (exp_id, n) not in armadas:
            faltan.append(f"expedientes/{exp_id}.json U{n}: no hay entrada ubicacion_armada en la auditoría")
    inf.lista(faltan, "Expedientes, ubicaciones, decisiones y órdenes cruzados con la auditoría en los dos sentidos",
              "Cruce con la auditoría")
    if posteriores:
        inf.nota(f"Cruce con la auditoría: {len(posteriores)} entrada(s) anotadas después de la foto de los proveedores "
                 f"(entrada {corte}) todavía no están en los expedientes exportados con esa foto; el partido siguió "
                 "después de exportar (la huella publicada y el registro oficial las cubren): "
                 + "; ".join(posteriores[:5]))

    # 4c. Entradas mínimas y cabeza de la auditoría.
    verificar_cola(inf, carpeta, orden, por_tipo)

    # 4d. Ubicaciones que el partido dejó sin decidir: sin órdenes.
    sin_decidir = [e for e in por_tipo.get("ubicacion_sin_decidir", [])]
    if sin_decidir:
        con_orden = []
        for e in sin_decidir:
            clave = (_d(e).get("expediente", e.get("exp")), _d(e).get("ubicacion"))
            for oid, env in enviadas.items():
                m = RE_UBIC_EN_ID.match(oid)
                if env.get("exp") == clave[0] and m and int(m.group(1)) == clave[1]:
                    con_orden.append(f"auditoría entrada {e['n']}: {clave[0]} U{clave[1]} quedó sin decidir y tiene "
                                     f"la orden {oid}")
        inf.lista(con_orden, f"Ubicaciones sin decidir al terminar el partido ({len(sin_decidir)}): ninguna tiene "
                             "órdenes", "Sin decidir")

    # 5. Firmas (con las claves de demostración).
    if claves:
        verificar_firmas(inf, orden, claves)
    verificar_ampliaciones(inf, entradas, claves if config else None)
    verificar_marcos(inf, carpeta, orden, entradas, claves if config else None)

    # 5b. Números de orden amp-/ord- y textos legibles.
    ampliadas = {(e.get("exp"), _d(e).get("ubicacion")) for e in por_tipo.get("ampliacion_dinamica", [])}
    fuentes = [("auditoría", [(env.get("exp"), oid, _d(env).get("origen")) for oid, env in enviadas.items()]),
               ("expedientes", [(o.get("exp"), oid, o.get("origen")) for oid, o in nuestras.items()])]
    verificar_legibles(inf, carpeta, orden)

    # 6. Registro oficial del simulador.
    if registro:
        eventos = leer_registro(inf, registro)
        if eventos is not None:
            recibidas = [e for e in eventos if e.get("evento") == "orden_recibida"]
            rechazadas = [e for e in eventos if e.get("evento") == "orden_rechazada"]
            fuera = [e for e in recibidas if e.get("juez_de_turno") is False]
            cruzar_ordenes(inf, "registro oficial", recibidas, nuestras, set(enviadas), sellos, perdidas)
            fuentes.append(("registro oficial", [((nuestras.get(e.get("orden_id")) or {}).get("exp"), e.get("orden_id"),
                                                  (nuestras.get(e.get("orden_id")) or {}).get("origen"))
                                                 for e in recibidas]))
            inf.chequear(not fuera, "registro oficial: ninguna orden firmada fuera de turno",
                         f"registro oficial: {len(fuera)} órdenes firmadas fuera de turno (juez_de_turno false): "
                         + ", ".join(str(e.get("orden_id")) for e in fuera[:5]))
            cotejar_tiempos_con_registro(inf, eventos, nuestras)
            inf.chequear(not rechazadas, "registro oficial: ninguna orden rechazada",
                         f"registro oficial: {len(rechazadas)} órdenes rechazadas: "
                         + "; ".join(f"{e.get('orden_id')} ({e.get('motivo')})" for e in rechazadas[:5]))

    # 7. Testigos: lo que guardó cada proveedor.
    ruta_t = carpeta / "testigos" / "proveedores.json"
    guardados = por_tipo.get("testigos_guardados", [])
    foto = corte_de_la_foto(por_tipo)  # lo enviado después de la foto no se le exige a los testigos
    if not ruta_t.exists():
        if guardados:
            inf.mal(f"testigos/proveedores.json: falta, y la auditoría dice que se guardaron (entrada "
                    f"{guardados[-1]['n']}, testigos_guardados)")
        else:
            inf.nota("Testigos de los proveedores: no disponible (la auditoría no registra testigos guardados)")
    else:
        try:
            datos = ruta_t.read_bytes()
        except OSError as err:
            inf.mal(f"testigos/proveedores.json: no se puede leer ({err})")
            datos = None
        if datos is not None:
            sha = sha256_hex(datos)
            ultimo = guardados[-1] if guardados else None
            inf.chequear(ultimo is not None and _d(ultimo).get("sha256") == sha,
                         "Testigos: sha256 coincide con la entrada testigos_guardados",
                         "Testigos: el sha256 de testigos/proveedores.json no coincide con la última entrada "
                         "testigos_guardados de la auditoría")
            try:
                doc = loads(datos.decode("utf-8"))
                provs = _dic(_dic(doc).get("proveedores"))
                ajenas = [dict(o, proveedor=pid) for pid, lista in provs.items() for o in _lis(lista)
                          if isinstance(o, dict)]
                cruzar_ordenes(inf, "testigos", ajenas, nuestras, set(enviadas), sellos, perdidas,
                               ordenes_tardias(por_tipo, enviadas, foto), foto)
                fuentes.append(("testigos", [((nuestras.get(o.get("orden_id")) or {}).get("exp"), o.get("orden_id"),
                                              (nuestras.get(o.get("orden_id")) or {}).get("origen")) for o in ajenas]))
            except ClaveDuplicada as err:
                inf.mal(f"testigos/proveedores.json: {err}")
            except (UnicodeDecodeError, ValueError):
                inf.mal("Testigos: testigos/proveedores.json no es JSON válido")
    verificar_prefijos(inf, fuentes, ampliadas)
    return inf


def ordenes_tardias(por_tipo: Dict[str, List[dict]], enviadas: Dict[str, dict], corte: Optional[int]) -> set:
    """Órdenes que se enviaron después de la foto de los proveedores: su última `orden_enviada` es posterior al
    corte y ningún proveedor había confirmado tenerla antes (`orden_recibida`, `orden_aplicada` u
    `orden_reconciliada` hasta el corte)."""
    if corte is None:
        return set()
    confirmadas = {_d(e).get("orden_id") for t in ("orden_recibida", "orden_aplicada", "orden_reconciliada")
                   for e in por_tipo.get(t, []) if e["n"] <= corte}
    return {oid for oid, e in enviadas.items() if e["n"] > corte and oid not in confirmadas}


def _verificar_expediente(inf, carpeta, arch, exp, entradas, enviadas, levantadas, det_sha, nuestras, sellos,
                          exportadas, decisiones_citadas, exps_exportados, legibles, sellos_rotos,
                          capturas_malas) -> None:
    nombre = f"expedientes/{arch.name}"
    if not isinstance(exp, dict):
        inf.mal(f"{nombre}: no es un objeto JSON")
        return
    ubicaciones = exp.get("ubicaciones")
    if not isinstance(ubicaciones, list):
        inf.mal(f"{nombre}: el campo ubicaciones no es una lista")
        return
    exps_exportados.add(exp.get("id"))
    anterior = None
    for u in ubicaciones:
        if not isinstance(u, dict):
            inf.mal(f"{nombre}: una ubicación no es un objeto")
            continue
        ref = f"{arch.name} U{u.get('n')}"
        s = _dic(u.get("sellado"))
        # captura
        det = _dic(s.get("deteccion"))
        sha_sellado = _dic(s.get("captura")).get("sha256")
        ruta_cap = carpeta / "capturas" / nombre_captura(det.get("id"))
        if sha_sellado is None:
            inf.nota(f"{ref}: la detección no traía una captura válida; la evidencia se selló sin captura")
        elif ruta_cap.exists():
            sha_archivo = hashlib.sha256(ruta_cap.read_bytes()).hexdigest()
            inf.chequear(sha_archivo == sha_sellado, f"{ref}: captura {ruta_cap.name} coincide con su sha256",
                         f"{ref}: capturas/{ruta_cap.name} no coincide con sellado.captura.sha256")
        else:
            inf.mal(f"{ref}: falta capturas/{ruta_cap.name}")
        try:
            crudo_b64 = _dic(det.get("captura")).get("contenido_b64")
            # Igual que el motor (evidencia.decodificar_captura): se toleran saltos de línea y espacios
            # (base64 «de mail»); cualquier otro carácter fuera del alfabeto sigue siendo un error.
            sha_b64 = hashlib.sha256(base64.b64decode("".join(str(crudo_b64).split()), validate=True)).hexdigest() \
                if crudo_b64 else None
        except (binascii.Error, ValueError):
            sha_b64 = None
        if sha_b64 != sha_sellado:
            inf.mal(f"{ref}: sellado.deteccion.captura no coincide con sellado.captura.sha256")
        # capturas de las redetecciones, contra la auditoría
        for did in _lis(u.get("detecciones"))[1:]:
            n_det, sha_aud = det_sha.get(did, (None, None))
            ruta = carpeta / "capturas" / nombre_captura(did)
            if sha_aud is None:
                continue
            if not ruta.exists():
                capturas_malas.append(f"{ref}: falta capturas/{ruta.name} (redetección {did})")
            elif hashlib.sha256(ruta.read_bytes()).hexdigest() != sha_aud:
                capturas_malas.append(f"{ref}: capturas/{ruta.name} no coincide con deteccion_recibida "
                                      f"(entrada {n_det})")
        # huella y antecedente
        h = calcular_huella(s)
        inf.chequear(h == u.get("huella"), f"{ref}: huella recalculada desde el sellado",
                     f"{ref}: campo huella no coincide con el sellado (evidencia alterada)")
        esperado = {"ubicacion": anterior["n"], "huella": anterior["huella"]} if anterior else None
        inf.chequear(s.get("antecedente") == esperado, f"{ref}: encadenada con su antecedente",
                     f"{ref}: campo sellado.antecedente no coincide con la ubicación anterior")
        anterior = {"n": u.get("n"), "huella": h}
        exportadas[(exp.get("id"), u.get("n"))] = h
        # lo legible contra lo sellado
        srv = _dic(s.get("servidor"))
        for campo in ("host", "ip"):
            _comparar(legibles, ref, campo, u.get(campo), srv.get(campo), "sellado.servidor")
        # decisión
        dec = u.get("decision")
        if dec:
            dec = _dic(dec)
            ent = entradas.get(dec.get("entrada"))
            de = _d(ent)
            bien = (ent is not None and ent.get("tipo") in TIPOS_DECISION and ent.get("exp") == exp.get("id")
                    and de.get("ubicacion") == u.get("n") and de.get("huella") == h)
            inf.chequear(bien, f"{ref}: decisión en la auditoría (entrada {dec.get('entrada')})",
                         f"{ref}: la entrada {dec.get('entrada')} no es la decisión de esta ubicación con esta huella")
            if ent is not None:
                decisiones_citadas.add(ent["n"])
                recalculado = sello_mod.calcular_sello(h, ent.get("hash"))
                if not inf.chequear(recalculado == dec.get("sello"), f"{ref}: sello recalculado",
                                    f"{ref}: campo decision.sello no se recalcula") and bien and h == u.get("huella"):
                    sellos_rotos.append(ent["n"])  # la evidencia está intacta: lo que cambió es la entrada
                if bien:
                    fuente = f"la entrada {ent['n']}"
                    es_amp = ent.get("tipo") == "ampliacion_dinamica"
                    _comparar(legibles, ref, "decision.tipo", dec.get("tipo"),
                              "ampliacion_dinamica" if es_amp else "firma", fuente)
                    _comparar(legibles, ref, "decision.aprobada", dec.get("aprobada"), bool(de.get("aprobar")), fuente)
                    _comparar(legibles, ref, "decision.juez_id", dec.get("juez_id"),
                              de.get("bajo_orden_dinamica_de", de.get("juez_id")) if es_amp else de.get("juez_id"), fuente)
                    _comparar(legibles, ref, "decision.alcance", dec.get("alcance"), de.get("alcance"), fuente)
                    _comparar(legibles, ref, "decision.min", dec.get("min"), ent.get("min"), fuente)
        # órdenes
        ordenes = u.get("ordenes", [])
        if not isinstance(ordenes, list):
            inf.mal(f"{ref}: el campo ordenes no es una lista")
            continue
        if u.get("estado") == "sin_decidir" and (ordenes or (dec and _dic(dec).get("aprobada"))):
            inf.mal(f"{ref}: figura «sin decidir» y tiene decisión aprobada u órdenes")
        for o in ordenes:
            if not isinstance(o, dict) or not isinstance(o.get("orden_id"), str):
                inf.mal(f"{ref}: una orden no tiene un orden_id válido")
                continue
            oid = o["orden_id"]
            nuestras[oid] = o
            ent = entradas.get(o.get("entrada_sello"))
            sello_ok = None
            if ent is not None and ent.get("tipo") in TIPOS_SELLO:
                sello_ok = sello_mod.calcular_sello(h, ent.get("hash"))
            sellos[oid] = sello_ok
            cierra = sello_ok is not None and sello_ok == o.get("sello") and oid.endswith("-" + sello_ok)
            if not cierra:
                inf.mal(f"{ref}: la orden {oid} no termina en el sello recalculado")
                if (ent is not None and h == u.get("huella") and _d(ent).get("huella") == h
                        and isinstance(o.get("sello"), str) and oid.endswith("-" + o["sello"])):
                    sellos_rotos.append(ent["n"])
            if o.get("estado") == "levantada" and oid not in levantadas:
                inf.mal(f"{ref}: la orden {oid} figura levantada y no hay entrada orden_levantada")
            env = enviadas.get(oid)
            if llego_a_enviarse(o) and env is None:
                inf.mal(f"{ref}: la orden {oid} se envió y no hay entrada orden_enviada")
            if env is not None:
                for campo in ("proveedor", "tipo", "objetivo", "vence_min", "juez_id"):
                    _comparar(legibles, f"{ref} orden {oid}", campo, o.get(campo), _d(env).get(campo),
                              f"su orden_enviada (entrada {env['n']})")


def verificar_cola(inf: Informe, carpeta: Path, orden: List[dict], por_tipo: Dict[str, List[dict]]) -> None:
    """Las entradas mínimas y la cabeza: una auditoría vacía, truncada o con la cola cambiada no verifica."""
    if not orden:
        return
    ultima = orden[-1]
    malas = []
    resumen = None
    ruta_r = carpeta / "resumen.json"
    if ruta_r.exists():
        ok, resumen = cargar_json(inf, ruta_r, "resumen.json")
        resumen = _dic(resumen) if ok else None
    if resumen is not None:
        cab = resumen.get("cabeza_auditoria")
        if isinstance(cab, dict) and (cab.get("n") != ultima.get("n") or cab.get("hash") != ultima.get("hash")):
            malas.append(f"resumen.json: la cabeza de la auditoría es la entrada {cab.get('n')} y auditoria.jsonl "
                         f"termina en la {ultima.get('n')} (auditoría truncada o con entradas agregadas)")
        if resumen.get("cerrado"):
            for tipo in ("partido_finalizado", "vencimiento_verificado"):
                if not por_tipo.get(tipo):
                    malas.append(f"auditoria.jsonl: el partido figura cerrado y falta la entrada {tipo}")
    ruta_a = carpeta / "acta-del-partido.md"
    try:
        m = RE_CABEZA_ACTA.search(ruta_a.read_text(encoding="utf-8")) if ruta_a.exists() else None
    except (OSError, UnicodeDecodeError):
        m = None
    if m and (int(m.group(1)) != ultima.get("n") or m.group(2) != str(ultima.get("hash"))):
        malas.append(f"acta-del-partido.md: dice que la auditoría termina en la entrada {m.group(1)} y "
                     f"auditoria.jsonl termina en la {ultima.get('n')}")
    inf.lista(malas, f"Auditoría completa: empieza en «inicio» y termina en la cabeza del acta "
                     f"(entrada {ultima.get('n')})", "Cola de la auditoría")


TOLERANCIA_REGISTRO_MIN = 0.002  # redondeo a 3 decimales de minutos entre el simulador y la plataforma


def cotejar_tiempos_con_registro(inf: Informe, eventos: List[dict], nuestras: Dict[str, dict]) -> None:
    """f-integridad-2: con el registro oficial, el minuto de aplicación y el estado final de cada orden del paquete
    son los del simulador. El registro sigue después de una exportación en pleno partido: lo que el paquete todavía
    no sabe (una orden aplicada después de exportar) no es falla; lo que el paquete afirma tiene que estar."""
    por_orden: Dict[str, Dict[str, float]] = {}
    for e in eventos:
        ev, oid = e.get("evento"), e.get("orden_id")
        if not isinstance(oid, str) or ev not in ("orden_recibida", "orden_aplicada", "orden_fallida",
                                                  "orden_vencida", "orden_levantada"):
            continue
        por_orden.setdefault(oid, {}).setdefault(ev, e.get("min"))

    # El simulador oficial anota orden_vencida; un registro sin ninguna (otro simulador, uno de prueba) no se usa para
    # exigirla, pero si la trae se coteja el minuto.
    registra_vencidas = any(e.get("evento") == "orden_vencida" for e in eventos)

    def cerca(a: Any, b: Any) -> bool:
        try:
            return abs(float(a) - float(b)) <= TOLERANCIA_REGISTRO_MIN
        except (TypeError, ValueError):
            return False
    malas: List[str] = []
    for oid, o in sorted(nuestras.items()):
        reg = por_orden.get(oid)
        if not reg or "orden_recibida" not in reg:
            continue  # sin recepción en el registro: lo informa el cruce de órdenes
        est, apl, fin = o.get("estado"), o.get("aplicada_min"), o.get("finalizada_min")
        if apl is not None:
            if "orden_aplicada" not in reg:
                malas.append(f"orden {oid}: el paquete dice aplicada en el minuto {apl} y el registro oficial no "
                             "tiene su orden_aplicada")
            elif not cerca(apl, reg["orden_aplicada"]):
                malas.append(f"orden {oid}: aplicada_min es {apl} y el registro oficial dice "
                             f"{reg['orden_aplicada']}")
        if est == "aplicada" and apl is None:
            malas.append(f"orden {oid}: figura aplicada sin minuto de aplicación")
        if est == "fallida" and "orden_fallida" not in reg:
            malas.append(f"orden {oid}: figura fallida y el registro oficial no tiene su orden_fallida")
        if est in ("aplicada", "vencida", "levantada") and "orden_fallida" in reg:
            malas.append(f"orden {oid}: figura {est} y el registro oficial dice que falló")
        if est == "vencida":
            if "orden_vencida" not in reg and registra_vencidas:
                malas.append(f"orden {oid}: figura vencida y el registro oficial no tiene su orden_vencida")
            elif "orden_vencida" in reg and fin is not None and not cerca(fin, reg["orden_vencida"]):
                malas.append(f"orden {oid}: finalizada_min es {fin} y el registro oficial dice que venció en el "
                             f"minuto {reg['orden_vencida']}")
        if est == "levantada" and "orden_levantada" not in reg:
            malas.append(f"orden {oid}: figura levantada y el registro oficial no tiene su orden_levantada")
    malas = [f"tiempos o estado distintos del registro oficial: {m}" for m in malas]
    inf.lista(malas, "registro oficial: minutos de aplicación, vencimientos y estado final de cada orden iguales",
              "registro oficial: tiempos o estado distintos del registro oficial")


AVISO_SIN_REGISTRO = ("Sin el registro oficial del simulador, esto prueba que el paquete es coherente consigo "
                      "mismo, no que sea verdadero: los testigos también los guarda la plataforma, y quien la maneja "
                      "podría haberlo recalculado todo. Para descartar una falsificación: --registro-simulador "
                      "<registro.jsonl> y --huella <huella publicada>.")
RESULTADO_COHERENTE = "Resultado: coherente consigo mismo (sin cotejar con el registro oficial del simulador)."
RESULTADO_OK = "Resultado: todo verifica."


def main_verificar(carpeta, registro=None, config=None, huella=None) -> int:
    inf = Informe()
    try:
        verificar(carpeta, registro, config, huella, inf=inf)
    except Exception as err:  # red de seguridad: nunca un traceback sin ✓/✗
        inf.mal(f"error inesperado verificando: {type(err).__name__}: {str(err)[:200]}")
    for linea in inf.lineas:
        print(linea)
    if inf.huella_paquete:
        print(f"\nHuella del paquete: {inf.huella_paquete}")
        if not huella:
            print("Publicar esta huella: ancla la cola de la auditoría posterior al último sello (vencimientos, "
                  "testigos, exportación). Con --huella <publicada> se compara.")
    if inf.fallas:
        print(f"\nResultado: {inf.fallas} problema(s). La exportación NO verifica.")
        return 1
    if not registro:
        # f-integridad-1: sin una fuente externa, nunca se presenta el paquete como probado.
        print("\n" + AVISO_SIN_REGISTRO)
        print("\n" + RESULTADO_COHERENTE)
        return 0
    print("\n" + RESULTADO_OK)
    return 0
