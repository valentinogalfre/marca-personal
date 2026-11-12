"""JSON canónico, sha256 y utilidades de tiempo compartidas."""
from __future__ import annotations

import datetime
import hashlib
import json
import math
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional

CEROS = "0" * 64


def canonico(obj: Any) -> bytes:
    """Serialización canónica: claves ordenadas, sin espacios, UTF-8."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def sha256_hex(datos: Any) -> str:
    if isinstance(datos, str):
        datos = datos.encode("utf-8")
    return hashlib.sha256(datos).hexdigest()


def huella(obj: Any) -> str:
    return sha256_hex(canonico(obj))


def nombre_captura(det_id) -> str:
    """Nombre de archivo de la captura de una detección (el mismo en el motor, la exportación y la verificación).

    Si el id ya es seguro se usa tal cual; si no, se sanea y se le agrega un trozo de su sha256 para que
    dos ids distintos nunca terminen en el mismo archivo.
    """
    texto = str(det_id)
    seguro = "".join(c for c in texto if c.isascii() and (c.isalnum() or c in "-_"))
    if seguro == texto and seguro:
        return seguro + ".ts"
    return (seguro[:60] or "sin-id") + "-" + sha256_hex(texto)[:12] + ".ts"


def r3(minuto: Optional[float]) -> Optional[float]:
    """Minutos redondeados a 3 decimales (o None)."""
    if minuto is None:
        return None
    return round(float(minuto), 3)


def min_txt(minuto: Any) -> str:
    """Un minuto para leer, con un decimal y coma: 60.25 -> «60,3», 5 -> «5,0», None -> «—».

    Es el único redondeo de minutos de la plataforma (ronda 3, C8): el valor binario exacto del número, un decimal,
    empates lejos del cero. Da lo mismo que `Number(x).toFixed(1)` en el navegador. Nunca escribe «-0,0». Lo que no
    es un número finito sale como «—»."""
    if minuto is None or isinstance(minuto, bool):
        return "—"
    try:
        x = float(minuto)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(x):
        return "—"
    texto = str(Decimal(x).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
    if texto == "-0.0":
        texto = "0.0"
    return texto.replace(".", ",")


def utc_ahora() -> str:
    ahora = datetime.datetime.now(datetime.timezone.utc)
    return ahora.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ahora.microsecond // 1000:03d}Z"


def hora_de_partido(inicio_iso: Optional[str], minuto: Optional[float]) -> Optional[str]:
    """Hora de partido (HH:MM:SS) a partir del inicio y el minuto, o None."""
    if not inicio_iso or minuto is None:
        return None
    try:
        inicio = datetime.datetime.fromisoformat(inicio_iso)
    except ValueError:
        return None
    return (inicio + datetime.timedelta(minutes=float(minuto))).strftime("%H:%M:%S")


def guardar_json_atomico(ruta, obj: Any) -> None:
    """Escribe a un temporal, fsync y renombra."""
    import os
    from pathlib import Path

    ruta = Path(ruta)
    tmp = ruta.with_name(ruta.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, ruta)
