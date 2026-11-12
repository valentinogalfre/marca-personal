#!/usr/bin/env python3
"""Cliente de referencia del proveedor chico (Marca Personal).

Lee cada pocos segundos la lista de solo lectura que la plataforma publica para un proveedor
(`GET /proveedor/<id>/vigentes.json`), muestra qué hay que bloquear o quitar y, si se lo pide,
escribe archivos que el equipo del proveedor usa tal cual (Unbound, lista de IP).

La plataforma manda datos, nunca comandos: este programa no ejecuta nada que venga en la lista.
Solo biblioteca estándar de Python 3.9 o más nuevo. Se puede copiar y correr aparte.

Uso:
  python3 cliente_proveedor.py --plataforma http://HOST:PUERTO --proveedor ID [--cada 5]
      [--salida-unbound RUTA] [--salida-ips RUTA] [--estado RUTA]
      [--al-cambiar "comando fijo"] [--una-vez]

Si no se pasa --estado y hay alguna salida, lo aplicado se guarda en un archivo oculto al lado de la
primera salida: `.<nombre de la salida>.estado.json` (un `include` de Unbound no lo toma).

Códigos de salida de --una-vez (cron, timer):
  0  quedó todo aplicado: leyó una lista nueva, escribió los archivos y la recarga anduvo
  1  no pudo leer una lista nueva (plataforma caída, respuesta fuera de contrato, lista vieja o repetida)
  2  faltan datos o hay uno mal escrito en la línea de comandos
  3  no pudo escribir un archivo de salida o el estado
  4  el comando de --al-cambiar falló o no existe (se reintenta en la próxima corrida)

Qué se valida
-------------
- IP: solo dígitos, letras a-f, «:» y «.» (nada de zonas «%…»), y nunca direcciones que una orden real no
  apunta: loopback, privadas, CGNAT, link-local, multicast, broadcast, reservadas, ULA, IPv4 metidas en IPv6.
  Se aceptan las públicas y las de documentación (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24,
  2001:db8::/32), que son las que usa el simulador.
- Nombre de host: las mismas reglas que el kit de la plataforma. Letras, dígitos, guion y guion bajo, al menos
  dos rótulos, 253 caracteres como máximo, nunca un sufijo de registro (com.ar), una IP ni un último rótulo
  «rpz-…» (en BIND es un disparador de RPZ, no un nombre). Cada línea de los archivos se vuelve a revisar al armarlos: si una
  falla, no se escribe nada y se avisa.
- `local-zone: "<host>." always_nxdomain` corta ese nombre y los que cuelgan de él (sus subdominios). Si la orden
  trae `no_cortar` (sitios ajenos conocidos que cuelgan de ese nombre), cada uno va con
  `local-zone: "<ajeno>." transparent`: Unbound aplica la zona más específica y ese sitio sigue resolviendo.
  Mismas líneas que el unbound.conf de la plataforma.

Vencimiento local (para quitar lo vencido aunque la plataforma no responda)
---------------------------------------------------------------------------
La lista trae el minuto del partido (`minuto`) y, por orden, el minuto en que vence (`vence_min`). Si la
plataforma se cae, hay que saber qué hora es acá. Cada vez que llega una lista nueva, a cada orden se le
calcula la hora local en que vence:

    hora en que vence = t + min((vence_min - minuto) * 60 / velocidad, TOPE_VENCE_LOCAL_S)

- `t`: reloj monotónico del proceso cuando terminó de llegar la respuesta. La plataforma calculó `minuto`
  entre el pedido y la respuesta: anclar en la respuesta nunca adelanta el vencimiento por ese motivo.
- velocidad (minutos de partido por minuto real): si la lista trae `"acelerar": número` entre 1 y RITMO_MAX,
  se usa ese. Si no, se mide: por cada tramo entre lecturas seguidas de los últimos VENTANA_RITMO_S
  segundos se calcula una cota que nunca supera la velocidad real,
      (minuto1 - minuto0 - RESOLUCION_MIN) * 60 / (t1 - t0 + duración del pedido 0),
  y se usa la menor, con piso 1 y techo RITMO_MAX. Con una sola lectura, 1. Así un pedido lento, un salto
  del minuto o un cambio de velocidad solo pueden hacer que se quite un poco más tarde, nunca antes.
- Tope: ningún bloqueo dura más de TOPE_VENCE_LOCAL_S (6 horas) desde la última lista buena.
- Dentro del proceso todo se mide con reloj monotónico; el reloj del sistema solo se usa para pasar el
  estado de un arranque al siguiente.
- Cuando la plataforma responde, manda la plataforma. La estimación se usa si está caída, si responde algo
  fuera de contrato, si la lista es más vieja que la última aceptada (esa solo puede quitar) o si devuelve
  exactamente el mismo cuerpo (un caché o un espejo: más de REPETIDA_S segundos así se avisa una vez).
- Una orden que alguna lista trajo como levantada no se vuelve a bloquear aunque reaparezca.

Al arrancar
-----------
- El primer arranque recarga siempre (`--al-cambiar`): no se sabe qué tiene cargado el DNS o el cortafuegos.
  Si la recarga falla o el programa no existe, se reintenta en cada vuelta hasta que ande.
- Los archivos de salida se alinean con lo guardado. Las líneas que este programa no puede justificar (no
  figuran en el estado: no se sabe de qué orden son ni cuándo vencen) se quitan, salvo que la plataforma las
  confirme como vigentes: un bloqueo nunca vive más que su orden.
- Un estado ilegible o de otra versión se mueve a `<estado>.danado`; uno de otro proveedor no se toca.
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import ipaddress
import json
import math
import os
import reprlib
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

TIMEOUT_S = 3.0                      # por operación de socket; el tope total del pedido es 3 * TIMEOUT_S
MAX_BYTES = 2 * 1024 * 1024
MAX_ENTRADAS = 5000
VENTANA_RITMO_S = 120.0
MAX_LECTURAS = 50
RESOLUCION_MIN = 0.01                # la plataforma redondea el minuto a centésimas
TOLERANCIA_MINUTO = 0.5              # una lista con el minuto más bajo que esto es vieja
RITMO_MAX = 1000.0
TOPE_VENCE_LOCAL_S = 6 * 3600.0
REPETIDA_S = 60.0
TIMEOUT_AL_CAMBIAR_S = 60.0
MAX_AVISOS_RECORDADOS = 1000
MAX_AVISOS_POR_PASADA = 50
MAX_PEDIDOS_COLGADOS = 2
VERSION_ESTADO = 1

SALIDA_OK = 0
SALIDA_SIN_LISTA = 1
SALIDA_ARGUMENTOS = 2
SALIDA_ARCHIVOS = 3
SALIDA_RECARGA = 4

_ROTULO = re.compile(r"[a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9_])?")
_ORDEN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_HORA = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]")
_IP_TEXTO = re.compile(r"[0-9A-Fa-f:.]+")
_HOST_TEXTO = re.compile(r"[a-z0-9._-]+")
_LINEA_UNBOUND = re.compile(r'local-zone: "(.*)\." always_nxdomain')
_LINEA_TRANSPARENT = re.compile(r'local-zone: "(.*)\." transparent')
MAX_NO_CORTAR = 100  # nombres ajenos por orden (`no_cortar`), igual que el kit de la plataforma
# Sufijos de registro que nunca son objetivo: bloquear uno de estos tiraría miles de sitios. Es la misma lista que
# marca/dominios.py (SUFIJOS_PELADOS); este programa no importa la plataforma, así que se repite acá.
_SUFIJOS = {
    "com", "net", "org", "edu", "gov", "gob", "mil", "int", "info", "biz", "io", "tv", "co", "me", "app", "dev",
    "ar", "br", "mx", "uy", "py", "bo", "pe", "cl", "uk", "es", "us",
    "test", "example", "invalid", "localhost", "local", "internal", "lan", "home", "arpa", "onion",
    "in-addr.arpa", "ip6.arpa", "int.ar", "mil.ar", "tur.ar",
    "com.ar", "gob.ar", "gov.ar", "org.ar", "net.ar", "edu.ar",
    "com.br", "com.mx", "com.uy", "com.py", "com.bo", "com.pe", "com.co", "com.cl", "co.uk",
}
# Redes que una orden real nunca apunta (la red del proveedor, de sus abonados o rangos especiales). Incluye
# las formas de meter una IPv4 en IPv6: ::ffff:0:0/96, 64:ff9b::/96, 2002::/16 (6to4) y 2001::/32 (Teredo).
_IP_NUNCA = tuple(ipaddress.ip_network(n) for n in (
    "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16", "172.16.0.0/12",
    "192.0.0.0/24", "192.168.0.0/16", "198.18.0.0/15", "224.0.0.0/4", "240.0.0.0/4", "255.255.255.255/32",
    "::/8", "::ffff:0:0/96", "64:ff9b::/96", "64:ff9b:1::/48", "100::/64", "2001::/32", "2002::/16",
    "fc00::/7", "fe80::/10", "fec0::/10", "ff00::/8"))
# Rangos de documentación: no son públicos, pero son los que usa el simulador.
_IP_DOCUMENTACION = tuple(ipaddress.ip_network(n) for n in (
    "192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24", "2001:db8::/32"))
MOTIVOS = {"levantada": "levantada", "vencida": "vencida"}
SIN_ORDEN = "no sé de qué orden es ni cuándo vence"


class ListaInvalida(Exception):
    """La respuesta no cumple el contrato de vigentes.json (o supera los topes)."""


# --- validación ------------------------------------------------------------------------------

def orden_id_valido(texto: Any) -> bool:
    return isinstance(texto, str) and _ORDEN_ID.fullmatch(texto) is not None


def hora_valida(texto: Any) -> bool:
    return isinstance(texto, str) and _HORA.fullmatch(texto) is not None


def ip_valida(texto: Any) -> Optional[str]:
    """Devuelve la IP en forma canónica, o None si no es una IP que una orden real pueda apuntar."""
    if not isinstance(texto, str) or len(texto) > 45 or not _IP_TEXTO.fullmatch(texto):
        return None  # sin zona «%…»: con zona, ipaddress acepta saltos de línea y texto cualquiera
    try:
        ip = ipaddress.ip_address(texto)
    except ValueError:
        return None
    if any(ip in n for n in _IP_NUNCA):
        return None
    if ip.is_unspecified or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
        return None
    if not (ip.is_global or any(ip in n for n in _IP_DOCUMENTACION)):
        return None
    return ip.compressed


def host_valido(texto: Any) -> Optional[str]:
    """Nombre de host en minúsculas y sin punto final, o None. Las mismas reglas que el kit de la plataforma
    (marca/kit.py y marca/dominios.py): rótulos de letras, dígitos, guion y guion bajo; 253 caracteres como máximo;
    al menos dos rótulos; nunca un sufijo de registro (com.ar), una IP, un último rótulo numérico ni un último
    rótulo «rpz-…» (en una zona RPZ es un disparador por IP o por servidor de nombres, no un nombre)."""
    if not isinstance(texto, str) or not texto.isascii():
        return None  # isascii antes de lower(): el signo Kelvin se volvería una «k»
    h = texto.lower()
    if h.endswith("."):
        h = h[:-1]  # el punto final no cambia el nombre (igual que el kit)
    if not h or len(h) > 253 or not _HOST_TEXTO.fullmatch(h):
        return None
    rotulos = h.split(".")
    if len(rotulos) < 2 or not all(_ROTULO.fullmatch(r) for r in rotulos):
        return None
    if h in _SUFIJOS or rotulos[-1].isdigit() or rotulos[-1].startswith("rpz-"):
        return None
    try:
        ipaddress.ip_address(h)
        return None
    except ValueError:
        pass
    return h


def no_cortar(valor: Any, objetivo: str) -> List[str]:
    """Sitios ajenos conocidos que cuelgan de `objetivo` (campo opcional `no_cortar` de una orden por dominio):
    validados como cualquier nombre, sin repetir y en orden; lo que no valida o no cuelga de `objetivo` se ignora.
    Mismas reglas que el kit de la plataforma (marca/kit.py, `_no_cortar`)."""
    if not isinstance(valor, list):
        return []
    nombres = set()
    for n in valor[:MAX_NO_CORTAR]:
        h = host_valido(n)
        if h is not None and h.endswith("." + objetivo):
            nombres.add(h)
    return sorted(nombres)


def objetivo_valido(tipo: Any, objetivo: Any) -> Optional[str]:
    if tipo == "ip":
        return ip_valida(objetivo)
    if tipo == "dominio":
        return host_valido(objetivo)
    return None


def _numero(x: Any) -> Optional[float]:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    try:
        x = float(x)
    except OverflowError:
        return None  # un entero de cientos de dígitos no es un minuto
    return x if math.isfinite(x) else None


_repr = reprlib.Repr()
_repr.maxstring = 80
_repr.maxother = 80
_repr.maxlevel = 2


def _mostrar(x: Any, largo: int = 60) -> str:
    """Texto seguro para la terminal: repr escapa saltos de línea y caracteres de control."""
    try:
        r = repr(x) if isinstance(x, str) and len(x) <= 4 * largo else _repr.repr(x)
    except Exception:  # noqa: BLE001 — un valor raro no puede tirar el aviso
        r = f"<{type(x).__name__}>"
    return r if len(r) <= largo else r[:largo] + "…"


def _limpio(texto: str) -> str:
    """Última barrera antes de la pantalla: ningún carácter de control llega crudo."""
    if texto.isprintable():
        return texto
    return "".join(c if c.isprintable() else ascii(c)[1:-1] for c in texto)


def _rechazar_constante(nombre: str) -> Any:
    raise ValueError(f"valor no permitido: {nombre}")


def interpretar(cuerpo: bytes, proveedor: str) -> Tuple[dict, List[str]]:
    """Valida el JSON contra el contrato (sección 5.2). Devuelve (lista, avisos).

    La lista tiene `minuto`, `acelerar` (o None), `vigentes` (solo entradas válidas, por orden_id) y
    `retiradas` (orden_id -> motivo). Levanta ListaInvalida si la respuesta entera no sirve."""
    if len(cuerpo) > MAX_BYTES:
        raise ListaInvalida(f"la respuesta pesa más de {MAX_BYTES // (1024 * 1024)} MB")
    try:
        datos = json.loads(cuerpo.decode("utf-8"), parse_constant=_rechazar_constante)
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise ListaInvalida("la respuesta no es una lista válida (no es JSON)")
    if not isinstance(datos, dict):
        raise ListaInvalida("la respuesta no es una lista válida")
    prov = datos.get("proveedor")
    if not isinstance(prov, dict) or prov.get("id") != proveedor:
        raise ListaInvalida("la lista es de otro proveedor o no dice de cuál es")
    minuto = _numero(datos.get("minuto"))
    if minuto is None:
        raise ListaInvalida("la lista no trae el minuto del partido")
    vigentes, retiradas = datos.get("vigentes"), datos.get("retiradas", [])
    if not isinstance(vigentes, list) or not isinstance(retiradas, list):
        raise ListaInvalida("la lista no trae «vigentes» y «retiradas»")
    if len(vigentes) > MAX_ENTRADAS or len(retiradas) > MAX_ENTRADAS:
        raise ListaInvalida(f"la lista trae más de {MAX_ENTRADAS} órdenes")

    avisos: List[str] = []
    acelerar = None
    if "acelerar" in datos:
        acelerar = _numero(datos.get("acelerar"))
        if acelerar is None or not (1.0 <= acelerar <= RITMO_MAX):
            avisos.append("no uso la velocidad del reloj del partido que manda la plataforma "
                          f"({_mostrar(datos.get('acelerar'), 20)}): la mido yo")
            acelerar = None

    salida_ret: Dict[str, str] = {}
    for r in retiradas:
        if isinstance(r, dict) and orden_id_valido(r.get("orden_id")):
            m = r.get("motivo")
            salida_ret[r["orden_id"]] = MOTIVOS.get(m, "retirada") if isinstance(m, str) else "retirada"

    salida_vig: Dict[str, dict] = {}
    for v in vigentes:
        if not isinstance(v, dict):
            avisos.append("descarto una entrada que no es una orden")
            continue
        oid = v.get("orden_id")
        if not orden_id_valido(oid):
            avisos.append(f"descarto una orden con número inválido: {_mostrar(oid)}")
            continue
        tipo = v.get("tipo")
        obj = objetivo_valido(tipo, v.get("objetivo"))
        if obj is None:
            avisos.append(f"descarto la orden {oid}: objetivo inválido ({_mostrar(tipo, 12)} {_mostrar(v.get('objetivo'))})")
            continue
        vence_min = _numero(v.get("vence_min"))
        if vence_min is None:
            avisos.append(f"descarto la orden {oid}: no dice cuándo vence")
            continue
        if vence_min <= minuto:
            continue  # ya venció según la misma lista: no rige
        if oid in salida_ret:
            avisos.append(f"la orden {oid} figura como vigente y como retirada: no la aplico")
            continue
        hora = v.get("vence_hora")
        salida_vig[oid] = {"orden_id": oid, "tipo": tipo, "objetivo": obj, "vence_min": vence_min,
                           "vence_hora": hora if hora_valida(hora) else None}
        libres = no_cortar(v.get("no_cortar"), obj) if tipo == "dominio" else []
        if libres:
            salida_vig[oid]["no_cortar"] = libres
    return {"minuto": minuto, "acelerar": acelerar, "vigentes": salida_vig, "retiradas": salida_ret}, avisos


# --- archivos --------------------------------------------------------------------------------

def _copiar_dueno(tmp: str, previo: os.stat_result, ruta: str,
                  avisar: Optional[Callable[[str], None]]) -> None:
    """Deja el temporal con el dueño y el grupo del archivo que reemplaza (0640 root:unbound sigue legible)."""
    if not hasattr(os, "chown"):
        return  # Windows: no hay dueño ni grupo POSIX
    actual = os.stat(tmp)
    if (actual.st_uid, actual.st_gid) == (previo.st_uid, previo.st_gid):
        return
    try:
        os.chown(tmp, previo.st_uid, previo.st_gid)
        return
    except OSError:
        pass
    try:
        os.chown(tmp, -1, previo.st_gid)  # sin root: al menos el grupo, si el usuario pertenece a él
        if actual.st_uid == previo.st_uid:
            return
    except OSError:
        pass
    if avisar:
        avisar(f"no pude dejar {ruta} con su dueño y grupo de antes ({previo.st_uid}:{previo.st_gid}): "
               "el servidor DNS o el cortafuegos puede no leerlo. Lo escribo igual.")


def escribir_si_cambia(ruta: str, contenido: str, avisar: Optional[Callable[[str], None]] = None) -> bool:
    """Escritura atómica (temporal en la misma carpeta + reemplazo), solo si el contenido cambió. Conserva
    permisos y, si se puede, dueño y grupo del archivo anterior."""
    datos = contenido.encode("utf-8")
    try:
        with open(ruta, "rb") as f:
            if f.read() == datos:
                return False
    except FileNotFoundError:
        pass
    carpeta = os.path.dirname(os.path.abspath(ruta))
    try:
        previo: Optional[os.stat_result] = os.stat(ruta)
    except FileNotFoundError:
        previo = None
    modo = (previo.st_mode & 0o777) if previo else 0o644  # el servidor DNS suele correr con otro usuario
    fd, tmp = tempfile.mkstemp(dir=carpeta, prefix="." + os.path.basename(ruta) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(datos)
            f.flush()
            os.fsync(f.fileno())
        if previo is not None:
            _copiar_dueno(tmp, previo, ruta, avisar)  # antes del chmod: chown puede limpiar bits de modo
        os.chmod(tmp, modo)
        os.replace(tmp, ruta)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return True


def texto_unbound(proveedor: str, aplicadas: Dict[str, dict]) -> str:
    """Las líneas `always_nxdomain` de lo bloqueado y, por cada sitio ajeno conocido que cuelga de un nombre
    bloqueado (`no_cortar`), una línea `transparent`: Unbound aplica la zona más específica, así que ese sitio
    sigue resolviendo y el stream (y cualquier otro subdominio) sigue cortado."""
    dominios_ = [o for o in aplicadas.values() if o["tipo"] == "dominio"]
    hosts = sorted({o["objetivo"] for o in dominios_})
    bloqueados = set(hosts)
    libres = sorted({n for o in dominios_ for n in (o.get("no_cortar") or ())
                     if isinstance(n, str) and n not in bloqueados
                     and any(n.endswith("." + h) for h in bloqueados)})
    for h in hosts + libres:  # segunda barrera: nada que no sea un nombre de host válido entra al archivo
        if not isinstance(h, str) or host_valido(h) != h or not _HOST_TEXTO.fullmatch(h):
            raise ValueError(f"un dominio no pasó la segunda revisión ({_mostrar(h)})")
    cab = [f"# Marca Personal · proveedor {proveedor} · dominios bloqueados por orden judicial",
           "# Son datos, no comandos. Incluir dentro de server: (include: este archivo).",
           "# Cada línea corta el nombre y sus subdominios."]
    if libres:
        cab.append("# Las líneas transparent son sitios ajenos que cuelgan de un nombre bloqueado: siguen resolviendo.")
    return "\n".join(cab + [f'local-zone: "{h}." always_nxdomain' for h in hosts]
                      + [f'local-zone: "{n}." transparent' for n in libres]) + "\n"


def texto_ips(proveedor: str, aplicadas: Dict[str, dict]) -> str:
    ips = sorted({o["objetivo"] for o in aplicadas.values() if o["tipo"] == "ip"}, key=str)
    for x in ips:  # segunda barrera: nada que no sea una IP bloqueable entra al archivo
        if not isinstance(x, str) or ip_valida(x) != x:
            raise ValueError(f"una IP no pasó la segunda revisión ({_mostrar(x)})")
    ips.sort(key=lambda s: (ipaddress.ip_address(s).version, ipaddress.ip_address(s)))
    cab = [f"# Marca Personal · proveedor {proveedor} · IP bloqueadas por orden judicial",
           "# Son datos, no comandos. Una IP por línea."]
    return "\n".join(cab + ips) + "\n"


def estado_por_defecto(salida: Optional[str]) -> Optional[str]:
    """Archivo oculto al lado de la salida: un `include` de Unbound (*.conf, *) nunca lo toma."""
    if not salida:
        return None
    carpeta, nombre = os.path.split(os.path.abspath(salida))
    return os.path.join(carpeta, "." + nombre + ".estado.json")


def partir_comando(texto: str, windows: Optional[bool] = None) -> List[str]:
    """Parte el comando de --al-cambiar sin shell. En Windows, sin el modo POSIX (que se come las barras
    invertidas de C:\\ruta) y sacando las comillas que encierran un argumento."""
    if windows is None:
        windows = os.name == "nt"
    partes = shlex.split(texto, posix=not windows)
    if windows:
        partes = [p[1:-1] if len(p) >= 2 and p[0] == p[-1] == '"' else p for p in partes]
    return partes


# --- red -------------------------------------------------------------------------------------

class _SinRedirecciones(urllib.request.HTTPRedirectHandler):
    """El contrato no prevé redirecciones: un 3xx queda como «la plataforma respondió 3xx»."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _con_anotacion(base: type, anotados: list) -> type:
    """Conexión que anota su socket (el TLS, si es https) apenas conecta, para poder cortarlo al vencer el
    tope total: urllib suelta la conexión después de las cabeceras, pero la respuesta sigue en ese socket."""
    class Conexion(base):  # type: ignore[misc, valid-type]
        def connect(self) -> None:
            super().connect()
            anotados.append(self.sock)
    return Conexion


class _ManejadorHTTP(urllib.request.HTTPHandler):
    def __init__(self, anotados: list) -> None:
        super().__init__()
        self._clase = _con_anotacion(http.client.HTTPConnection, anotados)

    def http_open(self, req):  # noqa: ANN001
        return self.do_open(self._clase, req)


class _ManejadorHTTPS(urllib.request.HTTPSHandler):
    def __init__(self, anotados: list) -> None:
        super().__init__()
        self._clase = _con_anotacion(http.client.HTTPSConnection, anotados)

    def https_open(self, req):  # noqa: ANN001
        extra = {"check_hostname": self._check_hostname} if hasattr(self, "_check_hostname") else {}
        return self.do_open(self._clase, req, context=self._context, **extra)


# --- cliente ---------------------------------------------------------------------------------

class Cliente:
    def __init__(self, plataforma: str, proveedor: str, *, salida_unbound: Optional[str] = None,
                 salida_ips: Optional[str] = None, estado: Optional[str] = None,
                 al_cambiar: Optional[List[str]] = None, reloj: Callable[[], float] = time.time,
                 monotonico: Optional[Callable[[], float]] = None,
                 decir: Optional[Callable[[str], None]] = None, avisar: Optional[Callable[[str], None]] = None,
                 correr: Callable[..., Any] = subprocess.run) -> None:
        if urllib.parse.urlsplit(plataforma).scheme not in ("http", "https"):
            raise ValueError("la plataforma tiene que empezar con http:// o https://")
        self.url = (plataforma.rstrip("/") + "/proveedor/" + urllib.parse.quote(proveedor, safe="")
                    + "/vigentes.json")
        self.proveedor = proveedor
        self.salida_unbound = salida_unbound
        self.salida_ips = salida_ips
        self.ruta_estado = estado
        self.al_cambiar = list(al_cambiar) if al_cambiar else None
        self.reloj = reloj                                   # reloj del sistema: solo para el estado
        self.mono = monotonico or (time.monotonic if reloj is time.time else reloj)
        self.decir = decir or (lambda t: print(t, flush=True))
        self.avisar = avisar or (lambda t: print("aviso: " + t, file=sys.stderr, flush=True))
        self.correr = correr
        self.aplicadas: Dict[str, dict] = {}
        self.lecturas: List[List[float]] = []                # [t, minuto, duración del pedido] (monotónico)
        self.max_minuto: Optional[Tuple[float, float]] = None  # (minuto más alto aceptado, cuándo)
        self.levantadas: "OrderedDict[str, None]" = OrderedDict()
        self.avisados: "OrderedDict[str, None]" = OrderedDict()
        self.huella: Optional[Tuple[str, float, bool]] = None  # (sha256 del cuerpo, desde cuándo, era nueva)
        self.recarga_pendiente = bool(self.al_cambiar)       # al arrancar no sé qué tiene cargado el DNS
        self.archivos_pendientes = bool(salida_unbound or salida_ips)  # al arrancar se alinean con el estado
        self.lineas_pendientes = False
        self.huerfanos: List[Tuple[str, str]] = []
        self.fallo_archivos = False
        self.fallo_recarga = False
        self._colgados: List[threading.Thread] = []
        self._desfase = self.reloj() - self.mono()
        self._cargar_estado()
        self._buscar_huerfanos()

    # pantalla --------------------------------------------------------------------------------

    def _decir(self, texto: str) -> None:
        self.decir(_limpio(texto))

    def _avisar(self, texto: str) -> None:
        self.avisar(_limpio(texto))

    def _avisar_una_vez(self, texto: str, clave: Optional[str] = None) -> bool:
        clave = clave or texto
        if clave in self.avisados:
            self.avisados.move_to_end(clave)
            return False
        self.avisados[clave] = None
        while len(self.avisados) > MAX_AVISOS_RECORDADOS:
            self.avisados.popitem(last=False)
        self._avisar(texto)
        return True

    def _avisar_lote(self, avisos: List[str]) -> None:
        mostrados = callados = 0
        for texto in avisos:
            if texto in self.avisados:
                self.avisados.move_to_end(texto)
                continue
            if mostrados >= MAX_AVISOS_POR_PASADA:
                callados += 1
                continue
            self._avisar_una_vez(texto)
            mostrados += 1
        if callados:
            self._avisar(f"y {callados} avisos más en esta lista que no detallo")

    # estado ----------------------------------------------------------------------------------

    def _cargar_estado(self) -> None:
        ruta = self.ruta_estado
        if not ruta or not os.path.exists(ruta):
            return
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                datos = json.loads(f.read(), parse_constant=_rechazar_constante)
            if not isinstance(datos, dict):
                raise ValueError("no tiene la forma esperada")
            prov = datos.get("proveedor")
            if isinstance(prov, str) and prov != self.proveedor:
                self._avisar(f"el estado guardado en {ruta} es de otro proveedor ({_mostrar(prov, 40)}): no lo "
                             "uso ni lo toco. Para este proveedor pasá otro --estado.")
                self.ruta_estado = None
                return
            if datos.get("v") != VERSION_ESTADO or prov != self.proveedor:
                raise ValueError("es de otra versión de este programa")
            ahora_sis, ahora = self.reloj(), self.mono()
            a_mono = ahora - ahora_sis                           # hora del sistema -> reloj monotónico
            aplicadas = {}
            for oid, o in (datos.get("aplicadas") or {}).items():
                if not isinstance(o, dict) or not orden_id_valido(oid):
                    continue
                obj = objetivo_valido(o.get("tipo"), o.get("objetivo"))
                vence = _numero(o.get("vence_local"))
                if obj is None or vence is None:
                    continue
                aplicadas[oid] = {"orden_id": oid, "tipo": o["tipo"], "objetivo": obj,
                                  "vence_min": _numero(o.get("vence_min")),
                                  "vence_hora": o["vence_hora"] if hora_valida(o.get("vence_hora")) else None,
                                  "vence_local": min(vence + a_mono, ahora + TOPE_VENCE_LOCAL_S)}
                libres = no_cortar(o.get("no_cortar"), obj) if o["tipo"] == "dominio" else []
                if libres:
                    aplicadas[oid]["no_cortar"] = libres
            lecturas = []
            for x in datos.get("lecturas") or []:
                if not isinstance(x, list) or len(x) not in (2, 3):
                    continue
                t, m = _numero(x[0]), _numero(x[1])
                d = _numero(x[2]) if len(x) == 3 else 3 * TIMEOUT_S
                if t is None or m is None or d is None:
                    continue
                lecturas.append([t + a_mono, m, max(0.0, d)])
            maximo = datos.get("max_minuto")
            if isinstance(maximo, dict):
                m, t = _numero(maximo.get("minuto")), _numero(maximo.get("t"))
                if m is not None and t is not None and ahora_sis - t <= TOPE_VENCE_LOCAL_S:
                    self.max_minuto = (m, min(t, ahora_sis) + a_mono)
            for oid in (datos.get("levantadas") or [])[-MAX_ENTRADAS:]:
                if orden_id_valido(oid):
                    self.levantadas[oid] = None
            huella = datos.get("huella")
            if isinstance(huella, dict) and isinstance(huella.get("sha256"), str):
                t = _numero(huella.get("desde"))
                if t is not None:
                    self.huella = (huella["sha256"], min(t, ahora_sis) + a_mono, huella.get("nueva") is True)
            self.aplicadas = aplicadas
            # Solo las de la ventana: una lectura «del futuro» (el reloj del sistema se atrasó) también se descarta.
            self.lecturas = [x for x in lecturas if 0 <= ahora - x[0] <= VENTANA_RITMO_S][-MAX_LECTURAS:]
        except Exception as e:  # noqa: BLE001 — cualquier estado raro se aparta, no tira el programa
            self._apartar_estado(ruta, e)

    def _apartar_estado(self, ruta: str, error: Exception) -> None:
        self.aplicadas, self.lecturas, self.max_minuto, self.huella = {}, [], None, None
        self.levantadas.clear()
        destino = ruta + ".danado"
        try:
            os.replace(ruta, destino)
            self._avisar(f"no pude usar el estado guardado ({_mostrar(str(error), 80)}): lo dejé en {destino} "
                         "y arranco sin él.")
        except OSError as e:
            self._avisar(f"no pude usar el estado guardado ({_mostrar(str(error), 80)}) ni apartarlo ({e}): "
                         "arranco sin él y no lo piso.")
            self.ruta_estado = None

    def _buscar_huerfanos(self) -> None:
        """Líneas de los archivos de salida que no figuran en lo aplicado: no se sabe de qué orden son ni
        cuándo vencen. Se quitan en la primera escritura, salvo que la plataforma las confirme."""
        justificadas = {(o["tipo"], o["objetivo"]) for o in self.aplicadas.values()}
        vistos: Set[Tuple[str, str]] = set()
        for ruta, tipo in ((self.salida_unbound, "dominio"), (self.salida_ips, "ip")):
            if not ruta:
                continue
            try:
                with open(ruta, "rb") as f:
                    texto = f.read(MAX_BYTES).decode("utf-8", "replace")
            except OSError:
                continue
            for linea in texto.splitlines():
                s = linea.strip()
                if not s or s.startswith("#") or (tipo == "dominio" and _LINEA_TRANSPARENT.fullmatch(s)):
                    continue  # una excepción «transparent» no es un bloqueo: se rehace con lo aplicado
                m = _LINEA_UNBOUND.fullmatch(s) if tipo == "dominio" else None
                obj = m.group(1) if m else s
                if (tipo, obj) not in justificadas and (tipo, obj) not in vistos:
                    vistos.add((tipo, obj))
                    self.huerfanos.append((tipo, obj))
        if self.huerfanos:
            self._avisar(f"encontré {len(self.huerfanos)} bloqueos en los archivos de salida que no figuran en lo "
                         "que tengo guardado: no sé de qué orden son ni cuándo vencen. Un bloqueo no puede durar "
                         "más que su orden: los quito ahora, salvo los que la plataforma confirme como vigentes.")

    def _guardar_estado(self) -> None:
        if not self.ruta_estado:
            return
        desfase = self.reloj() - self.mono()
        if abs(desfase - self._desfase) > 1.0:   # el reloj del sistema saltó: el estado tiene que reflejarlo
            self._desfase = desfase
        a_sis = self._desfase
        datos = {
            "v": VERSION_ESTADO, "proveedor": self.proveedor,
            "aplicadas": {oid: dict(o, vence_local=round(o["vence_local"] + a_sis, 3))
                          for oid, o in self.aplicadas.items()},
            "lecturas": [[round(t + a_sis, 3), m, round(d, 3)] for t, m, d in self.lecturas],
            "max_minuto": ({"minuto": self.max_minuto[0], "t": round(self.max_minuto[1] + a_sis, 3)}
                           if self.max_minuto else None),
            "levantadas": list(self.levantadas),
            "huella": ({"sha256": self.huella[0], "desde": round(self.huella[1] + a_sis, 3),
                        "nueva": self.huella[2]} if self.huella else None),
        }
        try:
            texto = json.dumps(datos, ensure_ascii=False, sort_keys=True, indent=1, allow_nan=False)
            escribir_si_cambia(self.ruta_estado, texto, self._avisar_una_vez)
        except (OSError, ValueError) as e:
            self.fallo_archivos = True
            self._avisar(f"no pude guardar el estado en {self.ruta_estado}: {e}. Lo reintento en la próxima vuelta.")

    # red -------------------------------------------------------------------------------------

    def _pedir(self) -> bytes:
        """Pide la lista con un tope total de tiempo real (cabeceras y cuerpo): un servidor que manda de a
        gotas no frena la vuelta. El pedido corre en un hilo; al vencer el tope se corta su conexión."""
        self._colgados = [h for h in self._colgados if h.is_alive()]
        if len(self._colgados) >= MAX_PEDIDOS_COLGADOS:
            raise ListaInvalida("los pedidos anteriores a la plataforma siguen sin terminar")
        tope = 3 * TIMEOUT_S
        sockets: List[socket.socket] = []
        resultado: Dict[str, Any] = {}

        def trabajo() -> None:
            try:
                resultado["cuerpo"] = self._descargar(sockets, time.monotonic() + tope)
            except BaseException as e:  # noqa: BLE001 — se vuelve a levantar en el hilo principal
                resultado["error"] = e

        hilo = threading.Thread(target=trabajo, name="pedido-vigentes", daemon=True)
        hilo.start()
        hilo.join(tope)
        if hilo.is_alive():
            for s in list(sockets):
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except (AttributeError, OSError):
                    pass
            hilo.join(0.5)
            if hilo.is_alive():
                self._colgados.append(hilo)
            raise ListaInvalida("la plataforma tarda demasiado en mandar la lista")
        if "error" in resultado:
            raise resultado["error"]
        return resultado["cuerpo"]

    def _descargar(self, sockets: List[socket.socket], limite: float) -> bytes:
        abridor = urllib.request.build_opener(urllib.request.ProxyHandler({}), _SinRedirecciones,
                                              _ManejadorHTTP(sockets), _ManejadorHTTPS(sockets))
        pedido = urllib.request.Request(self.url, headers={"Accept": "application/json",
                                                           "User-Agent": "cliente-proveedor/2"})
        partes: List[bytes] = []
        leidos = 0
        try:
            with abridor.open(pedido, timeout=TIMEOUT_S) as r:
                if r.status != 200:
                    raise ListaInvalida(f"la plataforma respondió {r.status}")
                while leidos <= MAX_BYTES:
                    parte = r.read(64 * 1024)
                    if not parte:
                        break
                    partes.append(parte)
                    leidos += len(parte)
                    if time.monotonic() > limite:
                        raise ListaInvalida("la plataforma tarda demasiado en mandar la lista")
        except urllib.error.HTTPError as e:
            try:
                e.close()
            except Exception:  # noqa: BLE001
                pass
            raise ListaInvalida(f"la plataforma respondió {e.code}")
        except ListaInvalida:
            raise
        except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError):
            raise ListaInvalida("la plataforma no responde")
        if leidos > MAX_BYTES:
            raise ListaInvalida(f"la respuesta pesa más de {MAX_BYTES // (1024 * 1024)} MB")
        if time.monotonic() > limite:
            raise ListaInvalida("la plataforma tarda demasiado en mandar la lista")  # nunca un cuerpo cortado
        return b"".join(partes)

    # velocidad del reloj del partido ---------------------------------------------------------

    def _medir_ritmo(self, t: float, minuto: float, duracion: float) -> float:
        self.lecturas.append([t, minuto, max(0.0, duracion)])
        self.lecturas = [x for x in self.lecturas if 0 <= t - x[0] <= VENTANA_RITMO_S][-MAX_LECTURAS:]
        cotas = []
        for (t0, m0, d0), (t1, m1, _d1) in zip(self.lecturas, self.lecturas[1:]):
            base = t1 - t0 + d0          # lo más que pudo pasar entre los dos instantes en que se calculó el minuto
            if base > 0:
                cotas.append((m1 - m0 - RESOLUCION_MIN) * 60.0 / base)
        if not cotas:
            return 1.0
        return min(RITMO_MAX, max(1.0, min(cotas)))

    # una pasada ------------------------------------------------------------------------------

    @staticmethod
    def _vence(o: dict) -> str:
        if o.get("vence_hora"):
            return o["vence_hora"]
        return f"min {o['vence_min']:g}" if o.get("vence_min") is not None else "sin hora"

    def _linea_bloquear(self, o: dict) -> Tuple[str, str]:
        return o["tipo"], f"+ BLOQUEAR {o['tipo']} {o['objetivo']} · orden {o['orden_id']} · vence {self._vence(o)}"

    @staticmethod
    def _linea_quitar(o: dict, motivo: str) -> Tuple[str, str]:
        return o["tipo"], f"− QUITAR {o['tipo']} {o['objetivo']} · orden {o['orden_id']} · {motivo}"

    def _lista_vieja(self, minuto: float, t: float) -> bool:
        if self.max_minuto and t - self.max_minuto[1] > TOPE_VENCE_LOCAL_S:
            self.max_minuto = None  # de hace más de 6 horas: otro partido
        return bool(self.max_minuto) and minuto < self.max_minuto[0] - TOLERANCIA_MINUTO

    def _anotar_levantadas(self, lista: dict) -> None:
        for oid, motivo in lista["retiradas"].items():
            if motivo == "levantada":
                self.levantadas[oid] = None
                self.levantadas.move_to_end(oid)
        while len(self.levantadas) > MAX_ENTRADAS:
            self.levantadas.popitem(last=False)

    def _aplicar_nueva(self, lista: dict, t: float, duracion: float, lineas: List[Tuple[str, str]]) -> None:
        ritmo = self._medir_ritmo(t, lista["minuto"], duracion)
        if lista["acelerar"] is not None:
            ritmo = lista["acelerar"]
        maximo = max(lista["minuto"], self.max_minuto[0]) if self.max_minuto else lista["minuto"]
        self.max_minuto = (maximo, t)
        self._anotar_levantadas(lista)
        antes = self.aplicadas
        nuevas: Dict[str, dict] = {}
        for oid, o in lista["vigentes"].items():
            if oid in self.levantadas:
                self._avisar_una_vez(f"la orden {oid} ya figuró como levantada: no la vuelvo a bloquear aunque "
                                     "aparezca de nuevo")
                continue
            falta_s = (o["vence_min"] - lista["minuto"]) * 60.0 / ritmo
            o = dict(o, vence_local=t + min(falta_s, TOPE_VENCE_LOCAL_S))
            previa = antes.get(oid)
            if previa and (previa["tipo"], previa["objetivo"]) != (o["tipo"], o["objetivo"]):
                lineas.append(self._linea_quitar(previa, "cambió el objetivo"))
                previa = None
            if previa is None:
                lineas.append(self._linea_bloquear(o))
            elif previa.get("vence_min") != o["vence_min"]:
                lineas.append((o["tipo"], f"~ CAMBIA {o['tipo']} {o['objetivo']} · orden {oid} · "
                                          f"ahora vence {self._vence(o)}"))
            nuevas[oid] = o
        for oid, o in antes.items():
            if oid not in nuevas:
                motivo = (lista["retiradas"].get(oid) or ("levantada" if oid in self.levantadas else None)
                          or ("vencida" if o["vence_local"] <= t else "ya no figura"))
                lineas.append(self._linea_quitar(o, motivo))
        self.aplicadas = nuevas

    def _aplicar_vieja(self, lista: dict, lineas: List[Tuple[str, str]]) -> None:
        """Una lista más vieja que la última aceptada solo puede quitar: nunca agrega ni renueva."""
        self._avisar_una_vez(
            f"llegó una lista del minuto {lista['minuto']:g} y ya había recibido el {self.max_minuto[0]:g}: puede "
            "ser una copia vieja. Con esa lista solo quito, no agrego. Si empezó otro partido, borrá "
            f"{self.ruta_estado or 'el estado guardado'} y volvé a arrancar.",
            clave=f"vieja:{self.max_minuto[0]!r}")
        self._anotar_levantadas(lista)
        for oid, o in list(self.aplicadas.items()):
            sigue = lista["vigentes"].get(oid)
            if sigue and oid not in self.levantadas and (sigue["tipo"], sigue["objetivo"]) == (o["tipo"], o["objetivo"]):
                continue
            lineas.append(self._linea_quitar(o, lista["retiradas"].get(oid) or "ya no figura"))
            del self.aplicadas[oid]

    def _quitar_vencidas(self, lineas: List[Tuple[str, str]]) -> None:
        ahora = self.mono()
        for oid, o in list(self.aplicadas.items()):
            if o["vence_local"] <= ahora:
                lineas.append(self._linea_quitar(o, "vencida (según la última lista)"))
                del self.aplicadas[oid]

    def pasada(self) -> bool:
        """Una vuelta completa. Devuelve True si pudo leer una lista nueva y aplicarla."""
        self.fallo_archivos = self.fallo_recarga = False
        lineas: List[Tuple[str, str]] = []
        antes = dict(self.aplicadas)
        t_pedido = self.mono()
        lista: Optional[dict] = None
        cuerpo = b""
        t = t_pedido
        try:
            cuerpo = self._pedir()
            t = self.mono()
            lista, avisos = interpretar(cuerpo, self.proveedor)
            self._avisar_lote(avisos)
        except ListaInvalida as e:
            lista = None
            self._avisar(f"{e}. Sigo con lo último que apliqué.")
        except Exception as e:  # noqa: BLE001 — nada que venga de la red puede cortar la vuelta
            lista = None
            self._avisar(f"la respuesta no es una lista válida ({type(e).__name__}). Sigo con lo último que apliqué.")

        nueva = leida = False
        if lista is not None:
            huella = hashlib.sha256(cuerpo).hexdigest()
            if self.huella and self.huella[0] == huella:
                # El mismo cuerpo byte a byte: no trae nada nuevo (la plataforma viva cambia generado_utc).
                edad = t - self.huella[1]
                leida = self.huella[2] and edad <= REPETIDA_S
                if edad > REPETIDA_S and self.aplicadas:
                    self._avisar_una_vez(
                        "la plataforma devuelve siempre la misma lista desde hace más de un minuto: parece una copia "
                        "vieja (un caché o un espejo), no la plataforma. No la tomo como nueva y quito cada bloqueo "
                        "a la hora en que vence.", clave="misma lista:" + huella)
            elif self._lista_vieja(lista["minuto"], t):
                self._aplicar_vieja(lista, lineas)
                self.huella = (huella, t, False)
            else:
                self._aplicar_nueva(lista, t, t - t_pedido, lineas)
                self.huella = (huella, t, True)
                nueva = leida = True
        if not nueva:
            self._quitar_vencidas(lineas)

        if self.huerfanos:
            justificadas = {(o["tipo"], o["objetivo"]) for o in self.aplicadas.values()}
            for tipo, obj in self.huerfanos:
                if (tipo, obj) not in justificadas:
                    lineas.append((tipo, f"− QUITAR {tipo} {obj} · {SIN_ORDEN}"))
            self.huerfanos = []
            self.archivos_pendientes = True

        self._guardar_estado()  # antes que los archivos: si el proceso muere en el medio, el arranque alinea
        fallidos: Set[str] = set()
        if nueva or self.aplicadas != antes or self.archivos_pendientes:
            fallidos = self._sincronizar_archivos()
        for tipo, texto in lineas:
            if tipo in fallidos:
                texto += " · PENDIENTE: no pude escribir el archivo, lo reintento en cada vuelta"
            self._decir(texto)
        if fallidos:
            self.lineas_pendientes = True
        elif self.lineas_pendientes and not self.archivos_pendientes:
            self._decir("Ya pude escribir los archivos: lo que había quedado pendiente está aplicado.")
            self.lineas_pendientes = False
        if self.al_cambiar and self.recarga_pendiente:
            ok = self._correr_al_cambiar()
            self.recarga_pendiente = not ok
            self.fallo_recarga = not ok
        return leida

    def codigo_de_salida(self, leida: bool) -> int:
        if self.fallo_archivos:
            return SALIDA_ARCHIVOS
        if self.fallo_recarga:
            return SALIDA_RECARGA
        return SALIDA_OK if leida else SALIDA_SIN_LISTA

    def _sincronizar_archivos(self) -> Set[str]:
        """Escribe los archivos. Devuelve los tipos ("dominio", "ip") cuyo archivo no se pudo escribir."""
        salidas = [(r, armar, tipo) for r, armar, tipo in ((self.salida_unbound, texto_unbound, "dominio"),
                                                          (self.salida_ips, texto_ips, "ip")) if r]
        try:
            textos = [(r, armar(self.proveedor, self.aplicadas), tipo) for r, armar, tipo in salidas]
        except ValueError as e:
            self._avisar(f"no escribo ningún archivo: {e}. Lo reviso de nuevo en la próxima vuelta.")
            self.fallo_archivos = self.archivos_pendientes = True
            return {tipo for _r, _a, tipo in salidas}
        fallidos: Set[str] = set()
        cambio = False
        for ruta, texto, tipo in textos:
            try:
                cambio |= escribir_si_cambia(ruta, texto, self._avisar_una_vez)
            except OSError as e:
                self._avisar(f"no pude escribir {ruta}: {e}. Lo reintento en la próxima vuelta.")
                fallidos.add(tipo)
        if cambio:
            self.recarga_pendiente = True
        self.archivos_pendientes = bool(fallidos)
        self.fallo_archivos |= bool(fallidos)
        return fallidos

    def _correr_al_cambiar(self) -> bool:
        """Corre el comando fijo (sin shell, sin stdin, con tope de tiempo). True solo si terminó con 0."""
        try:
            r = self.correr(self.al_cambiar, shell=False, timeout=TIMEOUT_AL_CAMBIAR_S,
                            stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            self._avisar(f"el comando de --al-cambiar tardó más de {TIMEOUT_AL_CAMBIAR_S:g} s y lo corté. "
                         "Lo reintento en la próxima vuelta.")
            return False
        except (OSError, subprocess.SubprocessError, ValueError) as e:
            self._avisar(f"no pude correr el comando de --al-cambiar ({e}). Lo reintento en la próxima vuelta.")
            return False
        codigo = getattr(r, "returncode", 0)
        if codigo:
            self._avisar(f"el comando de --al-cambiar terminó con error ({codigo}). "
                         "Lo reintento en la próxima vuelta.")
            return False
        return True


# --- línea de comandos -----------------------------------------------------------------------

def _utf8() -> None:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


class _Argumentos(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # argparse habla en inglés: lo decimos en criollo
        sys.stderr.write(f"error: faltan datos o hay uno mal escrito ({message}).\n"
                         "Probá: cliente_proveedor.py --help\n")
        sys.exit(SALIDA_ARGUMENTOS)


_EPILOGO = """\
Si la plataforma no responde, sigue con lo último que aplicó y quita cada bloqueo a la hora en que
vence. Ningún bloqueo dura más de 6 horas desde la última lista buena.

La lista puede traer "acelerar": a qué velocidad corre el reloj del partido (1 en la vida real). Si no
lo trae, el programa lo mide, y si se equivoca es para quitar un poco más tarde, nunca antes.

Códigos de salida con --una-vez:
  0  quedó todo aplicado
  1  no pude leer una lista nueva (plataforma caída, respuesta rara, lista vieja o repetida)
  2  faltan datos o hay uno mal escrito en la línea de comandos
  3  no pude escribir un archivo de salida o el estado
  4  el comando de --al-cambiar falló o no existe (se reintenta en la próxima corrida)
"""


class _Formato(argparse.RawDescriptionHelpFormatter):
    def add_usage(self, usage, actions, groups, prefix=None):  # noqa: ANN001
        return super().add_usage(usage, actions, groups, prefix="uso: ")


def armar_argumentos() -> argparse.ArgumentParser:
    p = _Argumentos(add_help=False, formatter_class=_Formato,
                    usage="%(prog)s --plataforma http://HOST:PUERTO --proveedor ID [opciones]",
                    description="Lee la lista de órdenes vigentes de un proveedor y la aplica en archivos.",
                    epilog=_EPILOGO)
    p._optionals.title = "opciones"
    p.add_argument("-h", "--help", action="help", help="muestra esta ayuda")
    p.add_argument("--plataforma", required=True, metavar="URL",
                   help="dirección de la plataforma, por ejemplo http://10.0.0.5:8080")
    p.add_argument("--proveedor", required=True, metavar="ID", help="identificador del proveedor")
    p.add_argument("--cada", type=float, default=5.0, metavar="SEGUNDOS",
                   help="segundos entre lecturas (por defecto 5)")
    p.add_argument("--salida-unbound", metavar="RUTA", help="archivo para Unbound (local-zone … always_nxdomain)")
    p.add_argument("--salida-ips", metavar="RUTA", help="archivo con una IP por línea")
    p.add_argument("--estado", metavar="RUTA",
                   help="archivo donde se guarda lo aplicado y a qué hora vence, para reiniciar sin perder nada. "
                        "Por defecto: .<nombre>.estado.json al lado de la primera salida")
    p.add_argument("--al-cambiar", metavar="COMANDO",
                   help="comando fijo (sin shell) que se corre al arrancar, cada vez que cambia algún archivo y, "
                        "si falla, en cada vuelta hasta que ande")
    p.add_argument("--una-vez", action="store_true", help="hace una sola lectura y termina (ver códigos de salida)")
    return p


def main(argv: Optional[List[str]] = None, *, reloj: Callable[[], float] = time.time,
         dormir: Callable[[float], None] = time.sleep) -> int:
    _utf8()
    a = armar_argumentos().parse_args(argv)
    if urllib.parse.urlsplit(a.plataforma).scheme not in ("http", "https"):
        print("error: --plataforma tiene que empezar con http:// o https://", file=sys.stderr)
        return SALIDA_ARGUMENTOS
    if not orden_id_valido(a.proveedor):
        print("error: --proveedor solo puede tener letras, dígitos y . _ : -", file=sys.stderr)
        return SALIDA_ARGUMENTOS
    if not (0.5 <= a.cada <= 3600):
        print("error: --cada tiene que estar entre 0,5 y 3600 segundos", file=sys.stderr)
        return SALIDA_ARGUMENTOS
    comando = None
    if a.al_cambiar:
        try:
            comando = partir_comando(a.al_cambiar)
        except ValueError as e:
            print(f"error: no entiendo el comando de --al-cambiar ({e})", file=sys.stderr)
            return SALIDA_ARGUMENTOS
        if not comando:
            print("error: el comando de --al-cambiar está vacío", file=sys.stderr)
            return SALIDA_ARGUMENTOS
        if shutil.which(comando[0]) is None:
            print(f"aviso: no encuentro el programa de --al-cambiar ({_limpio(comando[0])}). "
                  "Lo intento igual en cada vuelta.", file=sys.stderr, flush=True)
    estado = a.estado or estado_por_defecto(a.salida_unbound or a.salida_ips)
    cliente = Cliente(a.plataforma, a.proveedor, salida_unbound=a.salida_unbound, salida_ips=a.salida_ips,
                      estado=estado, al_cambiar=comando, reloj=reloj)
    if a.una_vez:
        try:
            leida = cliente.pasada()
        except Exception as e:  # noqa: BLE001 — sin traceback: una línea y un código
            print(f"aviso: falló la vuelta ({type(e).__name__}: {_mostrar(str(e))}).", file=sys.stderr, flush=True)
            return SALIDA_SIN_LISTA
        return cliente.codigo_de_salida(leida)
    guardo = f" Guardo lo aplicado en {estado}." if estado else ""
    print(f"Leo la lista de {a.proveedor} cada {a.cada:g} s.{guardo} Para cortar: Ctrl-C.", flush=True)
    try:
        while True:
            try:
                cliente.pasada()
            except Exception as e:  # noqa: BLE001 — el bucle nunca muere: lo vencido se sigue quitando
                print(f"aviso: falló una vuelta ({type(e).__name__}: {_mostrar(str(e))}); sigo.",
                      file=sys.stderr, flush=True)
            dormir(a.cada)
    except KeyboardInterrupt:
        print("\nListo, corté. Lo aplicado queda como está.", flush=True)
        return SALIDA_OK


if __name__ == "__main__":
    sys.exit(main())
