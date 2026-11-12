"""Dominio registrable, cobertura de dominios y detección de IP literales (funciones puras)."""
from __future__ import annotations

import ipaddress
import re
from typing import Optional
from urllib.parse import urlparse

SUFIJOS_SEGUNDO_NIVEL = {
    "com.ar", "gob.ar", "gov.ar", "org.ar", "net.ar", "edu.ar",
    "com.br", "com.mx", "com.uy", "com.py", "com.bo", "com.pe", "com.co", "com.cl", "co.uk",
}


def normalizar(host: Optional[str]) -> str:
    if host is None:
        return ""
    return str(host).strip().lower().rstrip(".")


def es_ip(host: Optional[str]) -> bool:
    texto = normalizar(host)
    if texto.startswith("[") and texto.endswith("]"):
        texto = texto[1:-1]
    try:
        ipaddress.ip_address(texto)
        return True
    except ValueError:
        return False


_ROTULO = re.compile(r"[a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9_])?")
_CARACTERES_IP = re.compile(r"[0-9A-Fa-f:.]+")
# Direcciones que nunca pueden ser el servidor de un stream en internet. Los rangos de documentación
# (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24, 2001:db8::/32) NO están: el escenario oficial los usa, y por eso
# la regla no puede ser `is_global` ni `is_private` (ipaddress los marca como privados o reservados).
_NO_ENRUTABLES = [ipaddress.ip_network(r) for r in (
    "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16", "172.16.0.0/12",
    "192.0.0.0/24", "192.168.0.0/16", "198.18.0.0/15", "224.0.0.0/4", "240.0.0.0/4",
    "::/128", "::1/128", "::ffff:0:0/96", "fc00::/7", "fe80::/10", "ff00::/8")]


def ip_valida(texto) -> bool:
    """IP literal estricta: todo el texto son dígitos hexadecimales, «:» y «.» (nada de zona «%…», corchetes,
    espacios ni saltos de línea) y no es loopback, privada, CGNAT, link-local, multicast, broadcast, reservada,
    ULA ni no especificada."""
    if not isinstance(texto, str) or not _CARACTERES_IP.fullmatch(texto):
        return False
    try:
        ip = ipaddress.ip_address(texto)
    except ValueError:
        return False
    return not any(ip.version == red.version and ip in red for red in _NO_ENRUTABLES)


def es_hostname(texto) -> bool:
    """Nombre de host sintácticamente válido: rótulos de letras, dígitos, guion o guion bajo (todo el texto, en
    ASCII: el signo Kelvin «\u212a» se volvería una «k» al pasar a minúsculas)."""
    if not isinstance(texto, str) or not texto or not texto.isascii() or any(c.isspace() for c in texto):
        return False
    h = texto.lower()
    if h.endswith("."):
        h = h[:-1]
    if not h or len(h) > 253:
        return False
    return all(_ROTULO.fullmatch(r) for r in h.split("."))


# Sufijos de registro que nunca pueden ser, solos, el objetivo de un bloqueo por dominio (bloquearían a todos los
# sitios que cuelgan de ellos). Lista corta a propósito: la plataforma solo bloquea hosts concretos de un stream.
SUFIJOS_PELADOS = {
    "com", "net", "org", "edu", "gov", "gob", "mil", "int", "info", "biz", "io", "tv", "co", "me", "app", "dev",
    "ar", "br", "mx", "uy", "py", "bo", "pe", "cl", "uk", "es", "us",
    "test", "example", "invalid", "localhost", "local", "internal", "lan", "home", "arpa", "onion",
    "in-addr.arpa", "ip6.arpa", "int.ar", "mil.ar", "tur.ar",
} | SUFIJOS_SEGUNDO_NIVEL


def objetivo_valido(tipo: str, objetivo) -> bool:
    """Lo que puede ir en una orden o en un comando de router. Un dominio es un nombre de host (`es_hostname`:
    letras, dígitos, guion y guion bajo; C16) con al menos dos rótulos, sin punto final, que nunca es un sufijo de
    registro pelado («com.ar», «test»), ni termina en un rótulo numérico, ni en un rótulo «rpz-…» (kit-3: dentro de
    una zona RPZ de BIND, rpz-ip, rpz-client-ip, rpz-nsip o rpz-nsdname son disparadores por IP del cliente, IP de
    respuesta o servidor de nombres, y rpz-passthru o rpz-drop son acciones; ningún dominio real termina así).
    `herramientas/cliente_proveedor.py` repite estas reglas (no importa la plataforma): cambiarlas en los dos."""
    if tipo == "ip":
        return ip_valida(objetivo)
    if tipo == "dominio":
        if not es_hostname(objetivo) or str(objetivo).endswith(".") or ip_valida(str(objetivo)):
            return False
        h = str(objetivo).lower()
        rotulos = h.split(".")
        return (len(rotulos) >= 2 and h not in SUFIJOS_PELADOS and not rotulos[-1].isdigit()
                and not rotulos[-1].startswith("rpz-"))
    return False


def registrable(host: Optional[str]) -> str:
    h = normalizar(host)
    if not h or es_ip(h):
        return h
    rotulos = h.split(".")
    if len(rotulos) >= 3 and ".".join(rotulos[-2:]) in SUFIJOS_SEGUNDO_NIVEL:
        return ".".join(rotulos[-3:])
    return ".".join(rotulos[-2:])


def dominio_autorizado(dominio: Optional[str]) -> str:
    """Un dominio autorizado de licenciatario tal como puede venir escrito: «*.tv.test», «https://tv.test/»,
    «TV.test.» o «tv.test/vivo» quedan todos como «tv.test»."""
    texto = str(dominio or "").strip()
    if "://" in texto:
        texto = host_de(texto) or ""
    texto = texto.split("/", 1)[0]
    texto = normalizar(texto)
    while texto.startswith("*."):
        texto = texto[2:]
    return texto.lstrip(".")


def cubre(dominio: Optional[str], host: Optional[str]) -> bool:
    """¿El host está dentro del dominio autorizado `dominio` (él o un subdominio)?"""
    d, h = dominio_autorizado(dominio), normalizar(host)
    if not d or not h:
        return False
    return h == d or h.endswith("." + d)


def host_de(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    try:
        host = urlparse(str(url)).hostname
    except ValueError:
        return None
    return normalizar(host) or None
