"""Firmas (orden, levantamiento, decisión), sello y orden_id."""
from __future__ import annotations

import hashlib
import hmac
import re

PREFIJO_SELLO = "MARCA-PERSONAL-SELLO-v1"


def firmar(clave: str, mensaje: str) -> str:
    """HMAC-SHA256 en hexadecimal (mismo algoritmo que el simulador)."""
    return hmac.new(clave.encode("utf-8"), mensaje.encode("utf-8"), hashlib.sha256).hexdigest()


def mensaje_orden(orden_id: str, tipo: str, objetivo: str, vence_min: int, juez_id: str) -> str:
    return f"{orden_id}|{tipo}|{objetivo}|{vence_min}|{juez_id}"


def firma_orden(clave: str, orden_id: str, tipo: str, objetivo: str, vence_min: int, juez_id: str) -> str:
    return firmar(clave, mensaje_orden(orden_id, tipo, objetivo, vence_min, juez_id))


def firma_levantamiento(clave: str, orden_id: str, juez_id: str) -> str:
    return firmar(clave, f"LEVANTAR|{orden_id}|{juez_id}")


def mensaje_decision(exp: str, n: int, huella: str, aprobar: bool, alcance: str, juez_id: str) -> str:
    return f"DECISION|{exp}|U{n}|{huella}|{'APROBAR' if aprobar else 'RECHAZAR'}|{alcance}|{juez_id}"


def firma_decision(clave: str, exp: str, n: int, huella: str, aprobar: bool, alcance: str, juez_id: str) -> str:
    return firmar(clave, mensaje_decision(exp, n, huella, aprobar, alcance, juez_id))


def mensaje_ampliacion(exp: str, n: int, huella: str, juez_id: str, entrada_habilitante: int) -> str:
    """Ampliación automática: la hace el sistema bajo la orden dinámica de un juez, no el juez en persona."""
    return f"AMPLIACION|{exp}|U{n}|{huella}|filtracion|{juez_id}|E{int(entrada_habilitante)}"


def firma_ampliacion(clave: str, exp: str, n: int, huella: str, juez_id: str, entrada_habilitante: int) -> str:
    return firmar(clave, mensaje_ampliacion(exp, n, huella, juez_id, entrada_habilitante))


def mensaje_marco(partido_id: str, huella: str, juez_id: str, seguimiento: bool) -> str:
    """Orden marco: la firma el juez en la plataforma; S1 si autoriza el seguimiento de la filtración.

    Una sola fuente: el formato lo define `marco.mensaje_firma`; esta función solo lo reexpone."""
    from . import marco
    return marco.mensaje_firma(partido_id, huella, juez_id, seguimiento)


def firma_marco(clave: str, partido_id: str, huella: str, juez_id: str, seguimiento: bool) -> str:
    return firmar(clave, mensaje_marco(partido_id, huella, juez_id, seguimiento))


def calcular_sello(huella: str, hash_entrada: str) -> str:
    return hashlib.sha256(f"{PREFIJO_SELLO}|{huella}|{hash_entrada}".encode("utf-8")).hexdigest()[:32]


def sanear_proveedor(pid: str) -> str:
    return re.sub(r"[^a-z0-9_-]", "", str(pid).lower())


PREFIJOS_ORDEN = ("ord", "amp")


def orden_id(num_exp: int, n: int, proveedor: str, k: int, sello: str, prefijo: str = "ord") -> str:
    """`ord-` para lo firmado en persona (y sus reenvíos y reemplazos); `amp-` para lo que sale de una ampliación
    automática bajo una orden marco: el proveedor ve en el propio texto firmado cuál es cuál."""
    if prefijo not in PREFIJOS_ORDEN:
        raise ValueError(f"prefijo de orden_id desconocido: {prefijo!r}")
    return f"{prefijo}-{int(num_exp):04d}-u{int(n)}-{sanear_proveedor(proveedor)}-{int(k):02d}-{sello}"


def sello_de_orden_id(oid: str) -> str:
    return str(oid).rsplit("-", 1)[-1]
