"""Usuarios, contraseñas (PBKDF2) y sesiones. Las claves de firma no salen de este objeto."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

VUELTAS = 200_000
DURACION_SESION_S = 12 * 3600
INTENTOS_MAX = 5
TRABA_S = 30
# Tope de usuarios inexistentes con intentos fallidos anotados: el diccionario no crece sin límite.
# Los usuarios de la configuración se anotan siempre (nadie les borra el contador inundando con nombres).
MAX_FALLOS_DESCONOCIDOS = 1000
MAX_FALLOS_TOTAL = 5000
MAX_USUARIO = 64
MAX_CLAVE = 256


def derivar(clave: str, sal: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", clave.encode("utf-8"), sal, VUELTAS)


class ErrorLogin(Exception):
    def __init__(self, codigo: str, texto: str) -> None:
        super().__init__(texto)
        self.codigo = codigo
        self.texto = texto


class Usuarios:
    def __init__(self, ruta_config) -> None:
        self.ruta = Path(ruta_config)
        with open(self.ruta, encoding="utf-8") as f:
            config = json.load(f)
        self._usuarios: Dict[str, dict] = {}
        for u in config.get("usuarios") or []:
            sal = os.urandom(16)
            self._usuarios[u["usuario"]] = {
                "usuario": u["usuario"], "rol": u["rol"], "juez_id": u.get("juez_id"),
                "nombre": u.get("nombre"), "sal": sal, "derivada": derivar(str(u["clave_demo"]), sal),
            }
        self.__claves_firma: Dict[str, str] = dict(config.get("claves_firma_demo") or {})
        self._sesiones: Dict[str, dict] = {}
        self._fallos: Dict[Tuple[str, str], Tuple[int, float]] = {}  # (usuario, origen) → (fallos, trabado hasta)
        self._actividad: Dict[str, float] = {}   # juez_id → último pedido autenticado (reloj monotónico)
        self._candado = threading.Lock()

    # --- claves de firma (nunca se exponen) ---------------------------------------------
    def tiene_clave(self, juez_id: str) -> bool:
        return juez_id in self.__claves_firma

    def firmar_con(self, juez_id: str, funcion, *args):
        """Aplica una función de firma con la clave del juez sin devolver la clave."""
        clave = self.__claves_firma.get(juez_id)
        if clave is None:
            raise KeyError(f"No hay clave de firma para {juez_id}")
        return funcion(clave, *args)

    def jueces_configurados(self) -> List[str]:
        return [u["juez_id"] for u in self._usuarios.values() if u["rol"] == "juez" and u.get("juez_id")]

    def usuario_de_juez(self, juez_id: str) -> Optional[str]:
        for u in self._usuarios.values():
            if u.get("juez_id") == juez_id:
                return u["usuario"]
        return None

    # --- ingreso ------------------------------------------------------------------------
    def _anotar_fallo(self, clave_traba: Tuple[str, str], valor: Tuple[int, float]) -> None:
        """Con self._candado tomado. clave_traba = (usuario, origen)."""
        if clave_traba not in self._fallos:
            if clave_traba[0] not in self._usuarios:
                desconocidos = [k for k in self._fallos if k[0] not in self._usuarios]
                for viejo in desconocidos[:max(0, len(desconocidos) - MAX_FALLOS_DESCONOCIDOS + 1)]:
                    del self._fallos[viejo]  # los más viejos primero (orden de inserción)
            if len(self._fallos) >= MAX_FALLOS_TOTAL:  # muchos orígenes contra usuarios reales: tope igual
                for viejo in list(self._fallos)[:len(self._fallos) - MAX_FALLOS_TOTAL + 1]:
                    del self._fallos[viejo]
        self._fallos[clave_traba] = valor

    def ingresar(self, usuario: str, clave: str, ip: Optional[str] = None) -> Tuple[str, dict]:
        """La traba por intentos fallidos es por (usuario, origen): un tercero que se equivoca desde otra
        máquina no deja afuera al juez (seguridad-2). Sin origen (llamadas internas) vale el origen vacío."""
        usuario, clave = str(usuario), str(clave)
        if len(usuario) > MAX_USUARIO or len(clave) > MAX_CLAVE:
            raise ErrorLogin("credenciales", "Usuario o contraseña incorrectos.")
        clave_traba = (usuario, str(ip or ""))
        ahora = time.time()
        with self._candado:
            fallos, hasta = self._fallos.get(clave_traba, (0, 0.0))
            if hasta > ahora:
                raise ErrorLogin("trabado", f"Demasiados intentos fallidos. Espere {int(hasta - ahora) + 1} segundos.")
        u = self._usuarios.get(usuario)
        sal = u["sal"] if u else b"sin-usuario-0000"
        derivada = derivar(str(clave), sal)
        ok = u is not None and hmac.compare_digest(derivada, u["derivada"])
        with self._candado:
            if not ok:
                fallos, hasta_previo = self._fallos.get(clave_traba, (0, 0.0))
                if hasta_previo > ahora:  # otro intento en paralelo ya trabó: no se pisa la traba
                    raise ErrorLogin("credenciales", "Usuario o contraseña incorrectos.")
                fallos += 1
                hasta = ahora + TRABA_S if fallos >= INTENTOS_MAX else 0.0
                self._anotar_fallo(clave_traba, (0 if hasta else fallos, hasta))
                raise ErrorLogin("credenciales", "Usuario o contraseña incorrectos.")
            self._fallos.pop(clave_traba, None)
            ficha = secrets.token_urlsafe(32)
            self._sesiones[ficha] = {"usuario": usuario, "creada": ahora}
            if u.get("juez_id"):
                self._actividad[u["juez_id"]] = time.monotonic()  # entrar (desde la bandeja) es actividad
            return ficha, self.publico(usuario)

    def sesion(self, ficha: Optional[str]) -> Optional[dict]:
        if not ficha:
            return None
        with self._candado:
            s = self._sesiones.get(ficha)
            if s is None:
                return None
            if time.time() - s["creada"] > DURACION_SESION_S:
                self._sesiones.pop(ficha, None)
                return None
            return self.publico(s["usuario"])

    def cerrar(self, ficha: Optional[str]) -> Optional[str]:
        """Cerrar la sesión corta la presencia en el acto si el juez no tiene otra sesión abierta (C17)."""
        with self._candado:
            s = self._sesiones.pop(ficha or "", None)
            if s is None:
                return None
            juez_id = (self._usuarios.get(s["usuario"]) or {}).get("juez_id")
            if juez_id and not any((self._usuarios.get(o["usuario"]) or {}).get("juez_id") == juez_id
                                   for o in self._sesiones.values()):
                self._actividad.pop(juez_id, None)
            return s["usuario"]

    def tiene_sesion(self, juez_id: str) -> bool:
        ahora = time.time()
        with self._candado:
            for s in self._sesiones.values():
                u = self._usuarios.get(s["usuario"])
                if u and u.get("juez_id") == juez_id and ahora - s["creada"] <= DURACION_SESION_S:
                    return True
        return False

    # --- presencia: actividad reciente, no una sesión de hace horas ---------------------------
    def marcar_actividad(self, juez_id: str) -> None:
        """La API lo llama en cada pedido del juez a /api/juez/* y en la espera larga de la bandeja (de=juez)."""
        if not juez_id:
            return
        with self._candado:
            self._actividad[str(juez_id)] = time.monotonic()

    def hace_s(self, juez_id: str) -> Optional[float]:
        """Segundos reales desde la última actividad del juez (None si nunca hubo)."""
        with self._candado:
            t = self._actividad.get(str(juez_id))
        return None if t is None else max(0.0, time.monotonic() - t)

    def activo(self, juez_id: str, ventana_s: float) -> bool:
        h = self.hace_s(juez_id)
        return h is not None and h <= float(ventana_s)

    def publico(self, usuario: str) -> dict:
        u = self._usuarios[usuario]
        return {"usuario": u["usuario"], "rol": u["rol"], "juez_id": u.get("juez_id"), "nombre": u.get("nombre")}
