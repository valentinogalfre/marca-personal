"""Cliente HTTP del simulador oficial (solo biblioteca estándar)."""
from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from typing import Any, Optional, Tuple

PISO_GET_S = 1.5
PISO_POST_S = 3.0
TECHO_POST_S = 10.0
LATENCIAS_RECIENTES = 8
# turnos-1: lo que tardan los POST entra en el margen de fin de turno. Con techo (un POST que agota su tiempo no
# estira el margen a 17 s) y con memoria corta (un POST lento de hace rato no infla el margen para siempre).
TECHO_LAT_POST_S = 5.0
VENTANA_LAT_POST_S = 120.0


class ErrorRed(Exception):
    """No hubo respuesta HTTP (conexión rechazada, tiempo agotado, respuesta cortada)."""


class Cliente:
    """Tiempos de espera proporcionales a la latencia medida, con piso y techo.

    GET: entre 1,5 s y el `timeout` del constructor (5 s por defecto). POST: entre 3 s y 10 s (o el doble del
    `timeout` del constructor, si es mayor). Un pedido que agota su tiempo cuenta como una latencia igual a ese
    tiempo, así una red que empeora de golpe agranda los tiempos en vez de cortar todos los pedidos.
    """

    def __init__(self, base: str, timeout: float = 5.0) -> None:
        self.base = base.rstrip("/")
        self.timeout = timeout
        # Sin proxies: el simulador es una dirección directa.
        self._abridor = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self._latencias: deque = deque(maxlen=LATENCIAS_RECIENTES)
        self._latencias_post: deque = deque(maxlen=LATENCIAS_RECIENTES)  # (instante monotónico, segundos)
        self._candado_lat = threading.Lock()

    # --- latencia y tiempos de espera -----------------------------------------------------
    def latencia(self) -> float:
        with self._candado_lat:
            return max(self._latencias) if self._latencias else 0.0

    def latencia_post(self) -> float:
        """turnos-1: la mayor latencia de los POST (envíos y levantamientos) de los últimos VENTANA_LAT_POST_S
        segundos reales, con techo TECHO_LAT_POST_S; 0 si no hubo."""
        ahora = time.monotonic()
        with self._candado_lat:
            recientes = [s for t, s in self._latencias_post if ahora - t <= VENTANA_LAT_POST_S]
        return min(TECHO_LAT_POST_S, max(recientes)) if recientes else 0.0

    def _anotar_latencia(self, segundos: float, metodo: str = "GET") -> None:
        with self._candado_lat:
            self._latencias.append(max(0.0, float(segundos)))
            if metodo == "POST":
                self._latencias_post.append((time.monotonic(), max(0.0, float(segundos))))

    def timeout_get(self) -> float:
        techo = max(PISO_GET_S, float(self.timeout))
        return min(techo, max(PISO_GET_S, 1.0 + 3.0 * self.latencia()))

    def timeout_post(self) -> float:
        techo = max(PISO_POST_S, TECHO_POST_S, 2.0 * float(self.timeout))
        return min(techo, max(PISO_POST_S, 2.0 + 4.0 * self.latencia()))

    def _pedir(self, metodo: str, ruta: str, cuerpo: Optional[dict] = None,
               timeout: Optional[float] = None) -> Tuple[int, Any]:
        datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
        req = urllib.request.Request(self.base + ruta, data=datos, method=metodo,
                                     headers={"Content-Type": "application/json", "Accept": "application/json"})
        espera = timeout or (self.timeout_post() if metodo == "POST" else self.timeout_get())
        t0 = time.monotonic()
        try:
            with self._abridor.open(req, timeout=espera) as resp:
                texto = resp.read()
                self._anotar_latencia(time.monotonic() - t0, metodo)
                return resp.status, json.loads(texto) if texto else None
        except urllib.error.HTTPError as err:
            self._anotar_latencia(time.monotonic() - t0, metodo)
            try:
                texto = err.read()
                return err.code, json.loads(texto) if texto else None
            except (ValueError, OSError):
                return err.code, None
        except (urllib.error.URLError, socket.timeout, ConnectionError, OSError, ValueError) as err:
            if isinstance(err, socket.timeout) or "timed out" in str(err):
                self._anotar_latencia(espera, metodo)
            raise ErrorRed(str(err)) from err

    def _get_ok(self, ruta: str) -> Any:
        estado, datos = self._pedir("GET", ruta)
        if estado != 200:
            raise ErrorRed(f"GET {ruta} respondió {estado}")
        return datos

    # --- lecturas -----------------------------------------------------------------------
    def estado(self) -> dict:
        return self._get_ok("/estado")

    def partido(self) -> dict:
        return self._get_ok("/partido")

    def juzgados(self) -> dict:
        return self._get_ok("/juzgados")

    def proveedores(self) -> list:
        return self._get_ok("/proveedores")

    def detecciones(self, desde: float) -> dict:
        return self._get_ok(f"/detecciones?desde={desde!r}")

    def reclamos(self) -> dict:
        # Siempre desde=-1: el minuto que devuelve /reclamos está redondeado y puede saltear reclamos.
        return self._get_ok("/reclamos?desde=-1")

    def dns_ip(self, ip: str) -> Optional[dict]:
        estado, datos = self._pedir("GET", "/dns-pasivo?ip=" + urllib.parse.quote(ip, safe=""))
        if estado == 404:
            return None
        if estado != 200:
            raise ErrorRed(f"DNS pasivo respondió {estado}")
        return datos

    def dns_dominio(self, dominio: str) -> Optional[dict]:
        estado, datos = self._pedir("GET", "/dns-pasivo?dominio=" + urllib.parse.quote(dominio, safe=""))
        if estado == 404:
            return None
        if estado != 200:
            raise ErrorRed(f"DNS pasivo respondió {estado}")
        return datos

    def ordenes(self, pid: str) -> list:
        return self._get_ok(f"/proveedores/{urllib.parse.quote(pid, safe='')}/ordenes")

    def orden(self, pid: str, oid: str) -> Tuple[int, Any]:
        return self._pedir("GET", f"/proveedores/{urllib.parse.quote(pid, safe='')}/ordenes/"
                                  f"{urllib.parse.quote(oid, safe='')}")

    # --- escrituras ---------------------------------------------------------------------
    def enviar_orden(self, pid: str, cuerpo: dict) -> Tuple[int, Any]:
        return self._pedir("POST", f"/proveedores/{urllib.parse.quote(pid, safe='')}/ordenes", cuerpo)

    def levantar(self, pid: str, oid: str, cuerpo: dict) -> Tuple[int, Any]:
        return self._pedir("POST", f"/proveedores/{urllib.parse.quote(pid, safe='')}/ordenes/"
                                   f"{urllib.parse.quote(oid, safe='')}/levantar", cuerpo)
