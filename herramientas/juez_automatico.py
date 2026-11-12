#!/usr/bin/env python3
"""Juez automático de ENSAYO. Entra por la API web igual que una persona y firma lo que le llega.

Solo para pruebas: en el partido final firman personas.
"""
from __future__ import annotations

import http.cookiejar
import json
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple

AVISO = "JUEZ AUTOMÁTICO DE ENSAYO — solo para pruebas. En el partido final firman personas."


class JuezAutomatico:
    def __init__(self, base: str, usuario: str, clave: str, demora_min: float = 0.3, alcance: str = "filtracion",
                 forzar_ip: Optional[str] = None, registro=print, serial: bool = False) -> None:
        self.base = base.rstrip("/")
        self.usuario = usuario
        self._clave = clave
        self.demora = demora_min
        self.alcance = alcance
        self.forzar_ip = forzar_ip
        self.registro = registro
        # C25 (humano-5): `serial` atiende de a un pedido, como una persona: la demora corre desde que vio el pedido
        # o desde su última acción (lo que sea después), y vale también para la orden marco y la ratificación.
        # Sin serial, firma en paralelo, como siempre.
        self.serial = serial
        self._ultima_min = float("-inf")
        self._minuto = 0.0
        self.vistos: Dict[str, float] = {}
        self.acciones: list = []
        self._ultimo_intento: Dict[str, float] = {}   # para no repetir en ráfaga una acción que falló
        self._parar = threading.Event()
        self._hilo: Optional[threading.Thread] = None
        self._nuevo_abridor()

    def _nuevo_abridor(self) -> None:
        self.cookies = http.cookiejar.CookieJar()
        self.abridor = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                                   urllib.request.HTTPCookieProcessor(self.cookies))

    def _pedir(self, metodo: str, ruta: str, cuerpo: Optional[dict] = None) -> Tuple[int, Any]:
        datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
        req = urllib.request.Request(self.base + ruta, data=datos, method=metodo,
                                     headers={"Content-Type": "application/json"})
        try:
            with self.abridor.open(req, timeout=10) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read() or b"null")
            except ValueError:
                return e.code, None

    def entrar(self) -> bool:
        self._nuevo_abridor()
        estado, _ = self._pedir("POST", "/api/login", {"usuario": self.usuario, "clave": self._clave})
        return estado == 200

    def iniciar(self) -> threading.Thread:
        self._hilo = threading.Thread(target=self._bucle, name="juez-" + self.usuario, daemon=True)
        self._hilo.start()
        return self._hilo

    def detener(self) -> None:
        self._parar.set()
        if self._hilo:
            self._hilo.join(timeout=5)

    def _bucle(self) -> None:
        logueado = False
        while not self._parar.is_set():
            try:
                if not logueado:
                    logueado = self.entrar()
                    if not logueado:
                        self._parar.wait(1.0)
                        continue
                estado, b = self._pedir("GET", "/api/juez/bandeja")
                if estado == 401:
                    logueado = False
                    continue
                if estado == 200 and b:
                    self._atender(b)
            except (urllib.error.URLError, OSError, ValueError):
                logueado = False
                self._parar.wait(0.5)
                continue
            self._parar.wait(0.1)

    def _listo(self, clave: str, minuto: float) -> bool:
        if clave not in self.vistos:
            self.vistos[clave] = minuto
        desde = max(self.vistos[clave], self._ultima_min) if self.serial else self.vistos[clave]
        return minuto - desde >= self.demora

    def _accion(self, ruta: str, cuerpo: dict, desc: str) -> Tuple[int, Any]:
        estado, r = self._pedir("POST", ruta, cuerpo)
        self._ultima_min = self._minuto
        texto = "ok" if estado == 200 else f"{estado} {(r or {}).get('codigo')}: {(r or {}).get('error')}"
        esperado = False
        if estado == 409 and "ya fue decidida" in str((r or {}).get("error") or ""):
            # La mudanza se amplió sola bajo la orden marco entre la bandeja y la firma: la plataforma hizo lo
            # correcto (adenda 3, C). No es un error.
            texto, esperado = "la amplió el sistema", True
        elif estado == 200 and isinstance(r, dict) and r.get("aviso"):
            texto = "ok (aviso: " + str(r["aviso"]) + ")"
        self.acciones.append({"accion": desc, "http": estado, "resultado": texto, "esperado": esperado})
        self.registro(f"[juez {self.usuario}] {desc} → {texto}")
        return estado, r

    def _puede_intentar(self, clave: str, cada_s: float = 2.0) -> bool:
        ahora = time.monotonic()
        if ahora - self._ultimo_intento.get(clave, -1e9) < cada_s:
            return False
        self._ultimo_intento[clave] = ahora
        return True

    def quiere_seguimiento(self, b: dict) -> bool:
        return self.alcance == "filtracion" and bool(b["yo"].get("dinamica_habilitada"))

    def _atender(self, b: dict) -> None:
        minuto = float(b["reloj"]["minuto"])
        self._minuto = minuto
        if not b["turno"]["de_turno"] or not b["turno"]["puede_firmar"]:
            return
        marco = b.get("marco") or {}
        firmada = marco.get("firmada")
        # Al entrar de turno, lo primero es la orden marco (con seguimiento salvo --alcance ubicacion o plataforma sin
        # dinámica), antes de decidir o ratificar (ronda 2b, sección 1).
        seguimiento = self.quiere_seguimiento(b) and bool(marco.get("seguimiento_disponible", True))
        if marco and marco.get("puede_firmar") and (firmada is None or bool(firmada.get("seguimiento")) != seguimiento):
            if (not self.serial or self._listo("marco", minuto)) and self._puede_intentar("marco"):
                self._accion("/api/juez/marco", {"seguimiento": seguimiento},
                             f"firma la orden marco (seguimiento: {'sí' if seguimiento else 'no'})")
            return
        tr = b.get("traspaso")
        if tr and self._listo("traspaso-%s" % tr["min"], minuto):
            self._accion("/api/juez/traspaso/ratificar", {}, f"ratifica el traspaso del min {tr['min']}")
            return
        for r in b.get("reclamos") or []:
            if self._listo("reclamo-" + r["id"], minuto):
                accion = r["propuesta"]["accion"]
                if accion == "cerrar":
                    continue
                cuerpo = {"accion": accion}
                if accion == "desestimar":
                    cuerpo["fundamento"] = "El reclamante forma parte de la operación pirata."
                self._accion(f"/api/juez/reclamos/{r['id']}/resolver", cuerpo, f"resuelve {r['id']} ({accion})")
                return
        for p in b.get("pendientes") or []:
            exp = p["expediente"]
            u = next(x for x in exp["ubicaciones"] if x["n"] == p["n"])
            if not self._listo(u["ref"], minuto):
                continue
            con_seguimiento = bool((firmada or {}).get("seguimiento"))
            cuerpo: Dict[str, Any] = {"alcance": "filtracion" if (self.quiere_seguimiento(b) and con_seguimiento)
                                      else "ubicacion"}
            recomendado = u["propuesta"]["tipo"]
            if self.forzar_ip and u["host"] == self.forzar_ip and recomendado != "ip":
                cuerpo["forzar_tipo"] = "ip"
                cuerpo["fundamento"] = "Ensayo: se fuerza el bloqueo por IP para provocar reclamos."
            elif recomendado == "ninguna":
                cuerpo["forzar_tipo"] = "dominio"
                cuerpo["fundamento"] = "Ensayo: sin recomendación segura, se bloquea el dominio."
            self._accion(f"/api/juez/ubicaciones/{exp['id']}/{u['n']}/aprobar", cuerpo,
                         f"firma {u['ref']} ({cuerpo.get('forzar_tipo') or recomendado}, {cuerpo['alcance']})")
            return
