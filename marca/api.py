"""Servidor HTTP de la plataforma: API JSON, espera larga y archivos estáticos de marca/web/.

Regla: el candado del motor se toma solo para armar los bytes de la respuesta; la escritura al socket
va siempre fuera de él (un celular con mala señal no puede frenar el motor ni el despacho).

Presencia (C17): «presente» = la bandeja del juez abierta. La marcan los pedidos autenticados a /api/juez/* y la
espera larga de la bandeja (/api/cambios?de=juez), al empezar y al terminar (si la sesión sigue abierta). Las
páginas públicas nunca la marcan aunque lleven la galleta del juez, y cerrar sesión la corta en el acto. Es lo que
mira la ampliación automática para saber si el juez tiene la plataforma abierta.

Ingresos fallidos (C18, seguridad-3): una entrada `login_fallido` por origen cada VENTANA_FALLOS_S, con
`intentos_sin_anotar` (los que no se anotaron desde la entrada anterior de ese origen).
"""
from __future__ import annotations

import io
import ipaddress
import json
import mimetypes
import os
import re
import socket
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

from . import VERSION, kit
from .motor import ErrorAccion, Motor
from .usuarios import ErrorLogin

WEB = Path(__file__).resolve().parent / "web"
COOKIE = "mp_sesion"
ESTADOS_HTTP = {"no_autenticado": 401, "sin_permiso": 403, "fuera_de_turno": 403, "no_encontrado": 404,
                "conflicto": 409, "invalido": 422, "partido_finalizado": 409, "trabado": 429, "sin_conexion": 503,
                "pedido_invalido": 400, "interno": 500}
PAGINAS = {"/": "index.html", "/juez": "juez.html", "/sala": "sala.html", "/transparencia": "transparencia.html"}
MAX_CUERPO = 64 * 1024
# Lectura y escritura del socket: una conexión que no manda ni lee nada en este tiempo se corta sola.
# La espera larga de /api/cambios (ESPERA_CAMBIOS_S) es del lado del servidor y no cuenta.
TIMEOUT_SOCKET_S = 15.0
ESPERA_CAMBIOS_S = 20.0
# Conexiones atendidas a la vez. Las que sobran reciben 503 y se cierran, sin tomar un hilo.
MAX_CONEXIONES = 128
# Por origen (IP) que no sea esta misma máquina: una sola laptop de la WiFi no llena el cupo de todos.
# Un navegador abre hasta 6 por sitio; 24 alcanzan de sobra para un celular o una notebook.
MAX_CONEXIONES_POR_ORIGEN = 24
# Un pedido (cabeceras + cuerpo) tiene este plazo desde su primer byte: el goteo de a un byte no lo estira.
# La espera hasta el primer byte sigue siendo TIMEOUT_SOCKET_S (conexiones keep-alive quietas).
PLAZO_PEDIDO_S = 20.0
MAX_USUARIO = 64
MAX_CLAVE = 256
VENTANA_FALLOS_S = 30.0    # una entrada login_fallido por origen y por ventana
MAX_ORIGENES_FALLOS = 1000  # orígenes recordados para esa cuenta (el más viejo sale primero)

RE_UBIC = re.compile(r"^/api/juez/ubicaciones/([^/]+)/(\d+)/(aprobar|rechazar|levantar)$")
RE_DIN = re.compile(r"^/api/juez/dinamicas/([^/]+)/revocar$")
RE_RECL = re.compile(r"^/api/juez/reclamos/([^/]+)/resolver$")
RE_ORDEN = re.compile(r"^/api/publico/ordenes/([^/]+)$")
# Lista que el equipo de cada proveedor lee solo (pública, de solo lectura, sin caché).
RE_PROVEEDOR = re.compile(r"^/proveedor/([^/]+)/(vigentes\.json|dominios\.txt|ips\.txt|unbound\.conf|rpz\.zone)$")
TEXTOS_PROVEEDOR = {"dominios.txt": "lista_dominios", "ips.txt": "lista_ips", "unbound.conf": "unbound_conf",
                    "rpz.zone": "zona_rpz"}
# La consulta pública acepta la dirección completa pegada (https://Sitio.test/ruta?x=1): la normaliza el motor
# (C9). Tope de largo de una dirección razonable; lo que pasa del tope se corta (el nombre está al principio).
MAX_DOMINIO_CONSULTA = 2048
SIN_CACHE = {"Cache-Control": "no-store"}
CABECERA_AUTOMATICO = "X-Marca-Juez-Automatico"


class FalloApi(Exception):
    def __init__(self, codigo: str, texto: str) -> None:
        super().__init__(texto)
        self.codigo = codigo
        self.texto = texto


def crear_manejador(motor: Motor):
    usuarios = motor.usuarios
    fallos_por_origen: dict = {}   # origen → [monotónico de la última entrada anotada, intentos sin anotar]

    def _auditar_fallo(origen: str, usuario: str, motivo: str) -> None:
        """Con motor.candado tomado. Los intentos fallidos no inundan la auditoría (seguridad-3)."""
        ahora = time.monotonic()
        previo = fallos_por_origen.get(origen)
        if previo is not None and ahora - previo[0] < VENTANA_FALLOS_S:
            previo[1] += 1
            return
        datos = {"usuario": usuario[:40], "motivo": motivo}
        if previo is not None and previo[1]:
            datos["intentos_sin_anotar"] = previo[1]
        motor.auditar("login_fallido", "sistema", datos=datos)
        fallos_por_origen.pop(origen, None)
        while len(fallos_por_origen) >= MAX_ORIGENES_FALLOS:
            fallos_por_origen.pop(next(iter(fallos_por_origen)))
        fallos_por_origen[origen] = [ahora, 0]

    class Manejador(PlazoDePedido):
        server_version = "MarcaPersonal/" + VERSION
        protocol_version = "HTTP/1.1"
        timeout = TIMEOUT_SOCKET_S

        def log_message(self, formato: str, *args: Any) -> None:
            pass

        # --- respuestas ---------------------------------------------------------------
        def _enviar(self, estado: int, cuerpo: bytes, tipo: str, extra: Optional[dict] = None) -> None:
            cabeceras = {"Content-Type": tipo, "Content-Length": str(len(cuerpo)), "Cache-Control": "no-cache",
                         "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
                         "X-Frame-Options": "DENY"}
            cabeceras.update(extra or {})
            self._respondido = True
            self.send_response(estado)
            for k, v in cabeceras.items():
                self.send_header(k, v)
            if self.close_connection:
                self.send_header("Connection", "close")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(cuerpo)

        def _json(self, estado: int, datos: Any, extra: Optional[dict] = None) -> None:
            """Escribe al socket: nunca llamarla con motor.candado tomado (usar _bajo_candado)."""
            self._enviar_bytes_json(estado, _a_bytes(datos), extra)

        def _enviar_bytes_json(self, estado: int, cuerpo: bytes, extra: Optional[dict] = None) -> None:
            self._enviar(estado, cuerpo, "application/json; charset=utf-8", extra)

        def _bajo_candado(self, armar, extra: Optional[dict] = None) -> None:
            """Arma la respuesta con el candado del motor y la escribe al socket ya sin él."""
            with motor.candado:
                cuerpo = _a_bytes(armar())
            self._enviar_bytes_json(200, cuerpo, extra)

        def _error(self, codigo: str, texto: str) -> None:
            if self.command == "POST" and not getattr(self, "_cuerpo_leido", False):
                self.close_connection = True
            self._json(ESTADOS_HTTP.get(codigo, 400), {"error": texto, "codigo": codigo})

        # --- sesión -------------------------------------------------------------------
        def _ficha(self) -> Optional[str]:
            crudo = self.headers.get("Cookie")
            if not crudo:
                return None
            try:
                c = SimpleCookie(crudo)
            except Exception:
                return None
            return c[COOKIE].value if COOKIE in c else None

        def _usuario(self, rol: Optional[str] = None, presencia: bool = False) -> dict:
            """presencia=True solo en /api/juez/* (C17): la bandeja abierta es lo que cuenta."""
            u = usuarios.sesion(self._ficha())
            if u is None:
                raise FalloApi("no_autenticado", "Inicie sesión.")
            if presencia:
                _actividad(u)
            if rol and u["rol"] != rol:
                raise FalloApi("sin_permiso", "Su usuario no tiene permiso para esto.")
            return u

        def _cuerpo(self) -> dict:
            # Si el cuerpo no se lee, con keep-alive sus bytes se tomarían como el pedido siguiente:
            # en esos errores se cierra la conexión.
            tipo = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if tipo != "application/json":
                self.close_connection = True
                raise FalloApi("invalido", "El pedido debe ser JSON (Content-Type: application/json).")
            crudo = (self.headers.get("Content-Length") or "0").strip()
            if not crudo.isdigit():  # negativo, con signo, vacío raro o no numérico: no se lee nada
                self.close_connection = True
                raise FalloApi("pedido_invalido", "Content-Length inválido.")
            largo = int(crudo)
            if largo > MAX_CUERPO:
                self.close_connection = True
                raise FalloApi("invalido", "Pedido demasiado grande.")
            if self.headers.get("Transfer-Encoding"):
                self.close_connection = True
                raise FalloApi("invalido", "Transfer-Encoding no admitido: mandar Content-Length.")
            self._cuerpo_leido = True
            try:
                datos = json.loads(self.rfile.read(largo) or b"{}")
            except ValueError:
                raise FalloApi("invalido", "JSON inválido.")
            if not isinstance(datos, dict):
                raise FalloApi("invalido", "Se esperaba un objeto JSON.")
            return datos

        # --- GET ----------------------------------------------------------------------
        def do_HEAD(self) -> None:
            self.do_GET()

        def do_GET(self) -> None:
            self._respondido = False
            url = urlparse(self.path)
            ruta = url.path
            try:
                if ruta.startswith("/api/"):
                    return self._get_api(ruta, parse_qs(url.query))
                m = RE_PROVEEDOR.match(ruta)
                if m:
                    return self._lista_proveedor(unquote(m.group(1)), m.group(2))
                return self._estatico(ruta)
            except FalloApi as f:
                self._error(f.codigo, f.texto)
            except ErrorAccion as f:
                self._error(f.codigo, f.texto)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as err:  # un error del motor no deja al cliente sin respuesta
                self._interno(ruta, err)

        def _interno(self, ruta: str, err: Exception) -> None:
            try:
                motor.log(f"Error interno atendiendo {self.command} {ruta}: {err!r}")
            except Exception:
                pass
            if not getattr(self, "_respondido", False):
                self.close_connection = True
                try:
                    self._error("interno", "Error interno de la plataforma: reintentar.")
                except OSError:
                    pass

        def _get_api(self, ruta: str, consulta: dict) -> None:
            if ruta == "/api/salud":
                return self._bajo_candado(lambda: {
                    "ok": True, "version": VERSION, "conexion": motor.conexion, "minuto": round(motor.ahora(), 2),
                    "partido": motor.e["partido"].get("id"), "v": motor.v,
                    "cerrado": bool(motor.e["hitos"].get("cierre")),
                    "exportado": bool(motor.e["hitos"].get("exportado")), "instancia": motor.instancia})
            if ruta == "/api/yo":
                u = self._usuario()
                return self._bajo_candado(lambda: motor.vista_yo(u))
            if ruta == "/api/cambios":
                try:
                    v = int((consulta.get("v") or ["0"])[0])
                except ValueError:
                    v = 0
                # Sin sesión también responde (pantallas públicas). Solo la espera de la bandeja (de=juez) cuenta
                # como presencia, al empezar y al terminar; al terminar se vuelve a leer la sesión, así una espera
                # que termina después del cierre de sesión no la vuelve a marcar (C17).
                de_bandeja = (consulta.get("de") or [""])[0] == "juez"
                if de_bandeja:
                    _actividad(usuarios.sesion(self._ficha()))
                limite = time.monotonic() + ESPERA_CAMBIOS_S
                with motor.cond:
                    while motor.v <= v:
                        resto = limite - time.monotonic()
                        if resto <= 0:
                            break
                        motor.cond.wait(resto)
                    cuerpo = _a_bytes({"v": motor.v, "minuto": round(motor.ahora(), 2)})
                if de_bandeja:
                    _actividad(usuarios.sesion(self._ficha()))
                return self._enviar_bytes_json(200, cuerpo)
            if ruta == "/api/juez/bandeja":
                u = self._usuario("juez", presencia=True)
                return self._bajo_candado(lambda: motor.vista_bandeja(u))
            if ruta == "/api/sala":
                self._usuario("fiscalia")
                return self._bajo_candado(motor.vista_sala)
            if ruta == "/api/publico/registro":
                return self._bajo_candado(motor.vista_registro)
            if ruta == "/api/publico/consulta":
                dominio = str((consulta.get("dominio") or [""])[0])[:MAX_DOMINIO_CONSULTA]
                return self._bajo_candado(lambda: motor.consulta_publica(dominio), SIN_CACHE)
            m = RE_ORDEN.match(ruta)
            if m:
                oid = unquote(m.group(1))
                return self._bajo_candado(lambda: motor.vista_orden_publica(oid))
            raise FalloApi("no_encontrado", "Ruta inexistente.")

        def _lista_proveedor(self, pid: str, archivo: str) -> None:
            """Lo que el equipo del proveedor lee solo: vigentes.json o una lista en texto armada por marca/kit.py."""
            with motor.candado:
                vista = motor.vista_proveedor(pid)
                if archivo == "vigentes.json":
                    cuerpo, tipo = _a_bytes(vista), "application/json; charset=utf-8"
                else:
                    cuerpo = getattr(kit, TEXTOS_PROVEEDOR[archivo])(vista).encode("utf-8")
                    tipo = "text/plain; charset=utf-8"
            self._enviar(200, cuerpo, tipo, SIN_CACHE)

        def _estatico(self, ruta: str) -> None:
            if ruta in PAGINAS:
                archivo = WEB / PAGINAS[ruta]
            elif ruta.startswith("/orden/"):
                archivo = WEB / "orden.html"
            elif ruta.startswith("/static/"):
                archivo = WEB / "static" / unquote(ruta[len("/static/"):])
            else:
                return self._enviar(404, "No encontrado".encode("utf-8"), "text/plain; charset=utf-8")
            try:
                real = archivo.resolve()
                base = WEB.resolve()
                if base not in real.parents and real != base:
                    raise FileNotFoundError
                datos = real.read_bytes()
            except (FileNotFoundError, IsADirectoryError, PermissionError, OSError):
                return self._enviar(404, "No encontrado".encode("utf-8"), "text/plain; charset=utf-8")
            tipo = mimetypes.guess_type(str(real))[0] or "application/octet-stream"
            if tipo.startswith("text/") or tipo in ("application/javascript", "application/json"):
                tipo += "; charset=utf-8"
            self._enviar(200, datos, tipo)

        # --- POST ---------------------------------------------------------------------
        def do_POST(self) -> None:
            ruta = urlparse(self.path).path
            self._cuerpo_leido = False
            self._respondido = False
            try:
                return self._post_api(ruta)
            except FalloApi as f:
                self._error(f.codigo, f.texto)
            except ErrorAccion as f:
                self._error(f.codigo, f.texto)
            except ErrorLogin as f:
                self._error("trabado" if f.codigo == "trabado" else "no_autenticado", f.texto)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as err:
                self._interno(ruta, err)

        def _es_programa(self) -> bool:
            """Un programa (juez automático de ensayo), no un navegador: lo dice su cabecera o su User-Agent."""
            agente = self.headers.get("User-Agent") or ""
            return bool(self.headers.get(CABECERA_AUTOMATICO)) or agente.startswith("Python-urllib")

        def _bandeja_ok(self, u: dict, resultado: Optional[dict] = None, aviso_siempre: bool = False) -> None:
            def armar() -> dict:
                datos = {"ok": True, "bandeja": motor.vista_bandeja(u)}
                if aviso_siempre:
                    datos["aviso"] = (resultado or {}).get("aviso") or None
                if resultado:
                    datos["resultado"] = resultado
                    if resultado.get("aviso"):
                        datos["aviso"] = resultado["aviso"]
                return datos
            self._bajo_candado(armar)

        def _post_api(self, ruta: str) -> None:
            cuerpo = self._cuerpo()
            if ruta == "/api/login":
                usuario, clave = str(cuerpo.get("usuario") or ""), str(cuerpo.get("clave") or "")
                if len(usuario) > MAX_USUARIO or len(clave) > MAX_CLAVE:
                    raise FalloApi("no_autenticado", "Usuario o contraseña incorrectos.")
                try:
                    ficha, u = usuarios.ingresar(usuario, clave, ip=self.client_address[0])
                except ErrorLogin as f:
                    with motor.candado:
                        _auditar_fallo(str(self.client_address[0]), usuario, f.codigo)
                    raise
                with motor.candado:
                    actor = ("juez:" + u["juez_id"]) if u["rol"] == "juez" else "fiscalia:" + u["usuario"]
                    datos = {"usuario": u["usuario"], "rol": u["rol"]}
                    if self._es_programa():  # el acta dice si firmaron personas o el juez automático de ensayo
                        datos["programa"] = True
                    motor.auditar("sesion_iniciada", actor, datos=datos)
                    motor._marcar()
                    cuerpo_yo = _a_bytes(motor.vista_yo(u))
                _actividad(u)  # el formulario de ingreso del juez está en su bandeja
                cookie = f"{COOKIE}={ficha}; HttpOnly; SameSite=Strict; Path=/; Max-Age={12 * 3600}"
                return self._enviar_bytes_json(200, cuerpo_yo, {"Set-Cookie": cookie})
            if ruta == "/api/logout":
                u = self._usuario()
                usuarios.cerrar(self._ficha())
                with motor.candado:
                    actor = ("juez:" + u["juez_id"]) if u["rol"] == "juez" else "fiscalia:" + u["usuario"]
                    motor.auditar("sesion_cerrada", actor, datos={"usuario": u["usuario"]})
                    motor._marcar()
                return self._json(200, {"ok": True},
                                  {"Set-Cookie": f"{COOKIE}=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"})
            u = self._usuario("juez", presencia=ruta.startswith("/api/juez/"))
            juez = u["juez_id"]
            m = RE_UBIC.match(ruta)
            if m:
                exp_id, n, accion = unquote(m.group(1)), int(m.group(2)), m.group(3)
                resultado = None
                if accion == "aprobar":
                    resultado = motor.aprobar(juez, exp_id, n, str(cuerpo.get("alcance") or "ubicacion"),
                                              cuerpo.get("forzar_tipo"), cuerpo.get("fundamento"))
                elif accion == "rechazar":
                    motor.rechazar(juez, exp_id, n, str(cuerpo.get("motivo") or ""))
                else:
                    # turnos-2: el motor devuelve {"aviso": texto} o {}; la respuesta lleva «aviso» si viene.
                    resultado = motor.levantar_ubicacion(juez, exp_id, n, str(cuerpo.get("motivo") or ""))
                return self._bandeja_ok(u, resultado if isinstance(resultado, dict) else None)
            if ruta == "/api/juez/marco":
                seguimiento = cuerpo.get("seguimiento", False)
                if not isinstance(seguimiento, bool):
                    raise FalloApi("invalido", "«seguimiento» tiene que ser true o false.")
                return self._bandeja_ok(u, motor.firmar_marco(juez, seguimiento))
            if ruta == "/api/juez/traspaso/ratificar":
                dinamicas = cuerpo.get("dinamicas")
                if dinamicas is not None and not (isinstance(dinamicas, list)
                                                  and all(isinstance(x, str) for x in dinamicas)):
                    raise FalloApi("invalido", "«dinamicas» tiene que ser una lista de expedientes o null.")
                # null (o sin el campo) = ratificar todas: es la llamada de siempre.
                resultado = motor.ratificar(juez) if dinamicas is None else motor.ratificar(juez, dinamicas)
                # Como api_simulada.py (contra la que se probaron las pantallas): «aviso» siempre, null si no hay.
                return self._bandeja_ok(u, resultado if isinstance(resultado, dict) else None, aviso_siempre=True)
            m = RE_DIN.match(ruta)
            if m:
                levantar = cuerpo.get("levantar", False)
                if not isinstance(levantar, bool):
                    raise FalloApi("invalido", "«levantar» tiene que ser true o false.")
                exp_id, motivo = unquote(m.group(1)), str(cuerpo.get("motivo") or "")
                if levantar:
                    resultado = motor.revocar_dinamica(juez, exp_id, motivo, levantar=True)
                else:
                    resultado = motor.revocar_dinamica(juez, exp_id, motivo)
                return self._bandeja_ok(u, resultado if isinstance(resultado, dict) else None)
            m = RE_RECL.match(ruta)
            if m:
                motor.resolver_reclamo(juez, unquote(m.group(1)), str(cuerpo.get("accion") or ""),
                                       cuerpo.get("fundamento"))
                return self._bandeja_ok(u)
            raise FalloApi("no_encontrado", "Ruta inexistente.")

    def _actividad(u: Optional[dict]) -> None:
        """Presencia real del juez (sección 2 de la ronda 2b). Nunca con motor.candado tomado."""
        if u and u.get("rol") == "juez" and u.get("juez_id"):
            usuarios.marcar_actividad(u["juez_id"])

    return Manejador


def _a_bytes(datos: Any) -> bytes:
    return json.dumps(datos, ensure_ascii=False).encode("utf-8")


RESPUESTA_LLENO = (b"HTTP/1.1 503 Service Unavailable\r\nContent-Type: text/plain; charset=utf-8\r\n"
                   b"Content-Length: 31\r\nRetry-After: 2\r\nConnection: close\r\n\r\n"
                   b"Plataforma ocupada: reintentar.")


class _LecturaConPlazo(io.RawIOBase):
    """Lee del socket con un plazo total por pedido, contado desde su primer byte.

    El timeout del socket vale por cada recv: un cliente que gotea un byte cada pocos segundos lo esquiva y retiene
    la conexión para siempre. Acá, una vez que llegó el primer byte, cada recv espera como mucho lo que le queda al
    plazo; vencido, se corta con socket.timeout (BaseHTTPRequestHandler cierra la conexión)."""

    def __init__(self, sock: socket.socket, plazo_s: float, timeout_s: float) -> None:
        super().__init__()
        self._sock = sock
        self._plazo_s = plazo_s
        self._timeout_s = timeout_s
        self.limite: Optional[float] = None

    def readable(self) -> bool:
        return True

    def rearmar(self) -> None:
        self.limite = None

    def readinto(self, b) -> int:
        if self.limite is None:
            n = self._sock.recv_into(b)
        else:
            resto = self.limite - time.monotonic()
            if resto <= 0:
                raise socket.timeout("el pedido no terminó de llegar a tiempo")
            self._sock.settimeout(min(self._timeout_s, resto))
            try:
                n = self._sock.recv_into(b)
            finally:
                self._sock.settimeout(self._timeout_s)  # la respuesta se escribe con el timeout de siempre
        if n and self.limite is None:
            self.limite = time.monotonic() + self._plazo_s
        return n


class PlazoDePedido(BaseHTTPRequestHandler):
    """Manejador con plazo total por pedido (ver _LecturaConPlazo)."""
    plazo_pedido_s = PLAZO_PEDIDO_S
    timeout = TIMEOUT_SOCKET_S

    def setup(self) -> None:
        super().setup()
        original = self.rfile
        self._lectura = _LecturaConPlazo(self.connection, self.plazo_pedido_s, self.timeout)
        self.rfile = io.BufferedReader(self._lectura)
        original.close()

    def handle_one_request(self) -> None:
        self._lectura.rearmar()  # el plazo del pedido siguiente arranca con su primer byte
        super().handle_one_request()


def es_esta_maquina(ip: str) -> bool:
    try:
        dir_ip = ipaddress.ip_address(str(ip).split("%")[0])
    except ValueError:
        return False
    mapeada = getattr(dir_ip, "ipv4_mapped", None)  # «::ffff:127.0.0.1» cuando se sirve en «::»
    return (mapeada or dir_ip).is_loopback


class Servidor(ThreadingHTTPServer):
    """Un hilo por conexión, con tope: las que pasan de max_conexiones reciben 503 sin tomar un hilo."""
    daemon_threads = True
    # En Windows SO_REUSEADDR deja abrir dos veces el mismo puerto: ahí no se usa.
    allow_reuse_address = os.name != "nt"
    max_conexiones = MAX_CONEXIONES
    max_por_origen = MAX_CONEXIONES_POR_ORIGEN

    def __init__(self, direccion, manejador, bind_and_activate: bool = True) -> None:
        self._cupo = threading.BoundedSemaphore(self.max_conexiones)
        self._por_origen: dict = {}
        self._candado_origen = threading.Lock()
        super().__init__(direccion, manejador, bind_and_activate)

    def origen_con_tope(self, client_address) -> Optional[str]:
        """El origen que cuenta para el tope por IP, o None si no tiene tope (esta misma máquina: la sala,
        el ensayo con proxy, un túnel)."""
        ip = str(client_address[0]) if client_address else ""
        return None if es_esta_maquina(ip) else ip

    def _tomar_origen(self, origen: Optional[str]) -> bool:
        if origen is None:
            return True
        with self._candado_origen:
            n = self._por_origen.get(origen, 0)
            if n >= self.max_por_origen:
                return False
            self._por_origen[origen] = n + 1
            return True

    def _soltar_origen(self, origen: Optional[str]) -> None:
        if origen is None:
            return
        with self._candado_origen:
            n = self._por_origen.get(origen, 0) - 1
            if n > 0:
                self._por_origen[origen] = n
            else:
                self._por_origen.pop(origen, None)

    def _rechazar(self, request) -> None:
        try:
            request.setblocking(False)  # nunca bloquear el hilo que acepta
            request.send(RESPUESTA_LLENO)
            request.recv(65536)  # lo que ya llegó: así el cierre no manda RST encima del 503
        except OSError:
            pass
        self.shutdown_request(request)

    def process_request(self, request, client_address) -> None:
        origen = self.origen_con_tope(client_address)
        if not self._tomar_origen(origen):
            self._rechazar(request)
            return
        if not self._cupo.acquire(blocking=False):
            self._soltar_origen(origen)
            self._rechazar(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._cupo.release()
            self._soltar_origen(origen)
            raise

    def process_request_thread(self, request, client_address) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._cupo.release()
            self._soltar_origen(self.origen_con_tope(client_address))


class _SinMotor(BaseHTTPRequestHandler):
    """Manejador provisorio mientras el motor arranca (el puerto ya está tomado)."""
    timeout = TIMEOUT_SOCKET_S

    def handle(self) -> None:
        try:
            self.connection.sendall(RESPUESTA_LLENO)
        except OSError:
            pass


def abrir_servidor(host: str, puerto: int) -> Servidor:
    """Toma el puerto sin atender todavía (OSError si está ocupado). Después: instalar_motor."""
    return Servidor((host, puerto), _SinMotor)


def instalar_motor(servidor: Servidor, motor: Motor) -> Servidor:
    servidor.RequestHandlerClass = crear_manejador(motor)
    return servidor


def servir(motor: Motor, host: str, puerto: int) -> Servidor:
    return instalar_motor(abrir_servidor(host, puerto), motor)
