"""Quién está de turno y si puede firmar (funciones puras sobre una consulta fresca de /estado)."""
from __future__ import annotations

from typing import List, Optional, Tuple

TEXTO_TERMINA = "Su turno termina en segundos: este pedido pasa al juez entrante."
TEXTO_LENTO = ("La conexión con el simulador está lenta (la consulta del turno tardó {:.1f} s): no se firma en este "
               "momento; se vuelve a intentar enseguida.")
DURACION_MAXIMA_S = 3.0  # si la consulta fresca de /estado tardó más que esto, no se firma con ella


def margen_fin(acelerar: float, duracion_s: float = 0.0) -> float:
    """Margen antes del fin de turno, del final del partido y del vencimiento de una orden.

    (2 s + 1,5 × D) reales en minutos de partido, mínimo 0,05 min. D es la duración medida de la consulta fresca a
    /estado: el POST llega al simulador más o menos una D después del minuto con que se chequeó.
    """
    acel = float(acelerar or 1.0)
    return max(0.05, 2.0 * acel / 60.0, (2.0 + 1.5 * max(0.0, float(duracion_s or 0.0))) * acel / 60.0)


def margen_inicio(acelerar: float, duracion_s: float = 0.0) -> float:
    """Margen después del inicio de turno: (0,5 s + D) reales, mínimo 0,02 min."""
    acel = float(acelerar or 1.0)
    return max(0.02, 0.5 * acel / 60.0, (0.5 + max(0.0, float(duracion_s or 0.0))) * acel / 60.0)


def turno_de(juez_id: str, turnos: List[dict], minuto: float) -> Optional[dict]:
    """El turno del juez que contiene el minuto, o None."""
    for t in turnos:
        if t.get("juez_id") == juez_id and t["desde_min"] <= minuto < t["hasta_min"]:
            return t
    return None


def proximo_turno(juez_id: str, turnos: List[dict], minuto: float) -> Optional[dict]:
    futuros = [t for t in turnos if t.get("juez_id") == juez_id and t["desde_min"] > minuto]
    return min(futuros, key=lambda t: t["desde_min"]) if futuros else None


def de_turno(turnos: List[dict], minuto: float) -> List[str]:
    """Jueces de turno en el orden de la lista de turnos (sin repetir)."""
    vistos: List[str] = []
    for t in turnos:
        if t["desde_min"] <= minuto < t["hasta_min"] and t["juez_id"] not in vistos:
            vistos.append(t["juez_id"])
    return vistos


def primero_de_turno(turnos: List[dict], jueces_de_turno: List[str]) -> Optional[str]:
    for t in turnos:
        if t.get("juez_id") in jueces_de_turno:
            return t["juez_id"]
    return jueces_de_turno[0] if jueces_de_turno else None


def puede_firmar_con(juez_id: str, estado: dict, turnos: List[dict],
                     duracion_s: Optional[float] = None) -> Tuple[bool, Optional[str]]:
    """Evalúa el permiso de firma con una respuesta fresca de GET /estado.

    `duracion_s` es la latencia que se toma en cuenta (por defecto, la que trae la consulta en `_dur_s`).
    """
    if estado.get("finalizado"):
        return False, "El partido terminó: ya no se firman órdenes."
    minuto = float(estado["minuto_actual"])
    acelerar = float(estado.get("acelerar") or 1.0)
    dur_pedido = float(estado.get("_dur_s") or 0.0)
    if dur_pedido > DURACION_MAXIMA_S:
        return False, TEXTO_LENTO.format(dur_pedido)
    dur = max(dur_pedido, float(duracion_s or 0.0))
    if juez_id not in (estado.get("jueces_de_turno") or []):
        prox = proximo_turno(juez_id, turnos, minuto)
        if prox is not None:
            return False, f"Su turno empieza en el min {prox['desde_min']:g}."
        return False, "No está de turno."
    turno = turno_de(juez_id, turnos, minuto)
    if turno is None:
        return False, "No está de turno."
    if turno["hasta_min"] - minuto <= margen_fin(acelerar, dur):
        return False, TEXTO_TERMINA
    if minuto - turno["desde_min"] <= margen_inicio(acelerar, dur):
        return False, "Su turno empieza en segundos: espere un momento y vuelva a intentar."
    return True, None
