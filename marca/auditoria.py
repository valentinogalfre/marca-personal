"""Registro de auditoría encadenado por hash (solo se agrega)."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .canon import CEROS, canonico, r3, sha256_hex, utc_ahora


def hash_entrada(entrada: dict) -> str:
    sin_hash = {k: v for k, v in entrada.items() if k != "hash"}
    return sha256_hex(canonico(sin_hash))


def leer_entradas(ruta) -> List[dict]:
    entradas = []
    with open(ruta, encoding="utf-8") as f:
        for linea in f:
            if linea.strip():
                entradas.append(json.loads(linea))
    return entradas


def verificar_cadena(ruta) -> Tuple[bool, int, List[str]]:
    """Recalcula la cadena completa. Devuelve (ok, cantidad, errores)."""
    errores: List[str] = []
    ruta = Path(ruta)
    if not ruta.exists():
        return False, 0, [f"{ruta}: no existe"]
    prev = CEROS
    cantidad = 0
    with open(ruta, encoding="utf-8") as f:
        for i, linea in enumerate(f, start=1):
            if not linea.strip():
                continue
            cantidad += 1
            try:
                e = json.loads(linea)
            except ValueError:
                errores.append(f"{ruta.name} línea {i}: no es JSON válido")
                prev = None
                continue
            if not isinstance(e, dict):
                errores.append(f"{ruta.name} línea {i}: no es un objeto")
                continue
            if e.get("n") != cantidad:
                errores.append(f"{ruta.name} línea {i}: campo n={e.get('n')}, se esperaba {cantidad} "
                               "(entrada borrada, agregada o fuera de orden)")
            if prev is not None and e.get("prev") != prev:
                errores.append(f"{ruta.name} línea {i} (n={e.get('n')}): campo prev no coincide con el hash "
                               "de la entrada anterior")
            calculado = hash_entrada(e)
            if e.get("hash") != calculado:
                errores.append(f"{ruta.name} línea {i} (n={e.get('n')}): campo hash no coincide con el contenido "
                               "(la entrada fue modificada)")
            prev = e.get("hash")
    return not errores, cantidad, errores


def recortar_linea_incompleta(ruta) -> Optional[str]:
    """Si la plataforma se cayó a mitad de una escritura, la última línea queda sin salto de línea.

    Esa entrada nunca llegó a escribirse entera: se descarta y se devuelve (para dejar constancia en la
    entrada de reanudación). Las líneas completas no se tocan nunca.
    """
    ruta = Path(ruta)
    if not ruta.exists():
        return None
    datos = ruta.read_bytes()
    if not datos or datos.endswith(b"\n"):
        return None
    corte = datos.rfind(b"\n")
    resto = datos[corte + 1:]
    with open(ruta, "r+b") as f:
        f.truncate(corte + 1)
        f.flush()
        os.fsync(f.fileno())
    return resto.decode("utf-8", errors="replace")[:500]


def primera_linea_mala(ruta) -> Optional[int]:
    """Número (desde 1) de la primera línea que rompe la cadena, o None si toda verifica."""
    prev = CEROS
    cantidad = 0
    with open(ruta, "rb") as f:
        for i, crudo in enumerate(f, start=1):
            if not crudo.strip():
                continue
            cantidad += 1
            try:
                e = json.loads(crudo.decode("utf-8"))
            except ValueError:
                return i
            if (not isinstance(e, dict) or e.get("n") != cantidad or e.get("prev") != prev
                    or e.get("hash") != hash_entrada(e)):
                return i
            prev = e["hash"]
    return None


def apartar_cola_danada(ruta, sufijo: str) -> Optional[dict]:
    """Si la cadena no verifica, aparta desde la primera línea mala hasta el final a otro archivo.

    Lo apartado no se borra: queda en `<nombre>.danada-<sufijo>.jsonl`, y la cadena original queda
    íntegra hasta la última línea buena. Devuelve qué se apartó, o None si no hacía falta.
    """
    ruta = Path(ruta)
    if not ruta.exists():
        return None
    linea = primera_linea_mala(ruta)
    if linea is None:
        return None
    lineas = ruta.read_bytes().splitlines(keepends=True)
    buenas, cola = lineas[:linea - 1], lineas[linea - 1:]
    datos = b"".join(cola)
    destino = ruta.with_name(f"{ruta.stem}.danada-{sufijo}.jsonl")
    with open(destino, "wb") as f:
        f.write(datos)
        f.flush()
        os.fsync(f.fileno())
    with open(ruta, "r+b") as f:
        f.truncate(sum(len(x) for x in buenas))
        f.flush()
        os.fsync(f.fileno())
    return {"archivo": destino.name, "sha256": sha256_hex(datos), "lineas": len(cola), "desde_linea": linea,
            "entradas_buenas": sum(1 for x in buenas if x.strip())}


class Auditoria:
    """Archivo JSONL encadenado. Escritura con candado, flush y fsync por entrada."""

    def __init__(self, ruta) -> None:
        self.ruta = Path(ruta)
        self.candado = threading.Lock()
        self.n = 0
        self.cabeza = CEROS
        self.ultimas: List[dict] = []  # cola en memoria para la sala
        self.recortado: Optional[str] = None
        if self.ruta.exists() and self.ruta.stat().st_size > 0:
            ok, cantidad, errores = verificar_cadena(self.ruta)
            if not ok:
                raise ValueError("La cadena de auditoría existente no verifica: " + "; ".join(errores[:3]))
            entradas = leer_entradas(self.ruta)
            self.n = cantidad
            self.cabeza = entradas[-1]["hash"] if entradas else CEROS
            self.ultimas = entradas[-200:]
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self.archivo = open(self.ruta, "a", encoding="utf-8")

    def agregar(self, tipo: str, actor: str, minuto: Optional[float], exp: Optional[str] = None,
                datos: Optional[Dict[str, Any]] = None) -> dict:
        with self.candado:
            entrada = {"n": self.n + 1, "utc": utc_ahora(), "min": r3(minuto), "tipo": tipo, "actor": actor,
                       "exp": exp, "datos": datos or {}, "prev": self.cabeza}
            entrada["hash"] = hash_entrada(entrada)
            self.archivo.write(json.dumps(entrada, ensure_ascii=False, separators=(",", ":")) + "\n")
            self.archivo.flush()
            os.fsync(self.archivo.fileno())
            self.n = entrada["n"]
            self.cabeza = entrada["hash"]
            self.ultimas.append(entrada)
            if len(self.ultimas) > 400:
                self.ultimas = self.ultimas[-200:]
            return entrada

    def cabeza_info(self) -> dict:
        return {"n": self.n, "hash": self.cabeza}

    def cerrar(self) -> None:
        with self.candado:
            try:
                self.archivo.close()
            except OSError:
                pass
