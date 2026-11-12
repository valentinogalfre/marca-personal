"""Contratos del servidor HTTP de la plataforma (marca/api.py y el ingreso de marca/usuarios.py).

- La API nunca escribe al socket con motor.candado tomado: un cliente que no lee (un celular con mala señal)
  no frena el motor, el despacho ni a los demás clientes.
- Una conexión que no manda ni lee nada se corta sola (timeout de socket); la espera larga de /api/cambios
  conserva su duración.
- Hay un tope de conexiones simultáneas: las que sobran reciben 503 sin tomar un hilo.
- Un Content-Length negativo o inválido da 400 sin leer el cuerpo.
- El ingreso acota el largo de usuario y clave (sin derivar la clave) y el diccionario de intentos fallidos.
- Ronda 2b: POST /api/juez/marco, los cuerpos nuevos de ratificar (dinamicas) y revocar (levantar), las listas
  públicas de cada proveedor (/proveedor/<id>/…, sin caché) y /api/publico/consulta delegan en el motor con los
  nombres del contrato; cada pedido autenticado de un juez marca su actividad (y /api/cambios al empezar y al
  terminar la espera), siempre con el candado libre.
- Un error inesperado del motor da 500 con JSON, no una conexión cortada sin respuesta.
"""
import hashlib
import http.client
import json
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from marca import api, usuarios as usuarios_mod
from marca.api import Servidor, crear_manejador, servir
from marca.auditoria import leer_entradas
from marca.motor import Motor
from marca.usuarios import ErrorLogin, Usuarios

from tests.simulador_falso import SimuladorFalso

CONFIG = {
    "aviso": "pruebas",
    "usuarios": [{"usuario": "a", "clave_demo": "clave-de-prueba-a", "rol": "juez", "juez_id": "juez-a"},
                 {"usuario": "b", "clave_demo": "clave-de-prueba-b", "rol": "juez", "juez_id": "juez-b"},
                 {"usuario": "f", "clave_demo": "clave-de-prueba-f", "rol": "fiscalia", "nombre": "Fiscalía"}],
    "claves_firma_demo": {"juez-a": "clave-a", "juez-b": "clave-b"},
}


def motor_falso(base: Path):
    ruta = base / "jueces.json"
    ruta.write_text(json.dumps(CONFIG), encoding="utf-8")
    sim = SimuladorFalso()
    motor = Motor("http://falso", base / "salida", Usuarios(ruta), cliente=sim, tick=0.01, registro=lambda t: None)
    motor.arrancar(nueva=True, hilos=False)
    sim.avanzar(1.2)
    motor._t_estado = float("-inf")
    motor.paso()
    return motor


def cerrar_motor(motor):
    motor.despacho._pool.shutdown(wait=False)
    if motor.auditoria:
        motor.auditoria.cerrar()


def arrancar(servidor):
    hilo = threading.Thread(target=servidor.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    hilo.start()
    return servidor.server_address[1]


def parar(servidor):
    servidor.shutdown()
    servidor.server_close()


def pedir(puerto, metodo, ruta, cuerpo=None, cookie=None, timeout=5):
    c = http.client.HTTPConnection("127.0.0.1", puerto, timeout=timeout)
    cab = {}
    datos = None
    if cuerpo is not None:
        datos = json.dumps(cuerpo).encode("utf-8")
        cab["Content-Type"] = "application/json"
    if cookie:
        cab["Cookie"] = cookie
    c.request(metodo, ruta, body=datos, headers=cab)
    r = c.getresponse()
    texto = r.read()
    galleta = r.getheader("Set-Cookie")
    c.close()
    return r.status, texto, galleta


def leer_todo(s, limite_s=5.0):
    s.settimeout(limite_s)
    recibido = b""
    try:
        while True:
            trozo = s.recv(65536)
            if not trozo:
                return recibido, True
            recibido += trozo
    except socket.timeout:
        return recibido, False


class _Sonda:
    """Envuelve el wfile del manejador: en cada escritura prueba, desde otro hilo, si el candado está libre."""

    def __init__(self, real, motor, registro, bloqueo=None):
        self._real, self._motor, self._registro, self._bloqueo = real, motor, registro, bloqueo

    def _libre(self):
        r = []

        def probar():
            ok = self._motor.candado.acquire(timeout=1.0)
            if ok:
                self._motor.candado.release()
            r.append(ok)
        t = threading.Thread(target=probar)
        t.start()
        t.join()
        return r[0]

    def write(self, datos):
        self._registro.append(self._libre())
        if self._bloqueo is not None:
            self._bloqueo["entro"].set()
            self._bloqueo["soltar"].wait(10)
        return self._real.write(datos)

    def __getattr__(self, nombre):
        return getattr(self._real, nombre)


def manejador_con_sonda(motor, registro, bloqueos):
    base = crear_manejador(motor)

    class ConSonda(base):
        def setup(self):
            super().setup()
            bloqueo = bloqueos.pop(0) if bloqueos else None
            self.wfile = _Sonda(self.wfile, motor, registro, bloqueo)
    return ConSonda


class TestEscrituraFueraDelCandado(unittest.TestCase):
    """Contrato: la API nunca retiene motor.candado mientras escribe la respuesta al socket."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        cls.motor = motor_falso(Path(cls.dir.name))

    @classmethod
    def tearDownClass(cls):
        cerrar_motor(cls.motor)
        cls.dir.cleanup()

    def test_cada_ruta_escribe_con_el_candado_libre(self):
        registro, bloqueos = [], []
        servidor = Servidor(("127.0.0.1", 0), manejador_con_sonda(self.motor, registro, bloqueos))
        puerto = arrancar(servidor)
        try:
            exp = self.motor.e["expedientes"][0]["id"]
            casos = []

            def caso(nombre, metodo, ruta, cuerpo=None, cookie=None):
                antes = len(registro)
                estado, _, galleta = pedir(puerto, metodo, ruta, cuerpo, cookie)
                casos.append((nombre, estado, registro[antes:]))
                return galleta

            caso("salud", "GET", "/api/salud")
            caso("registro", "GET", "/api/publico/registro")
            caso("cambios", "GET", "/api/cambios?v=0")
            caso("orden inexistente", "GET", "/api/publico/ordenes/nada")
            caso("yo sin sesión", "GET", "/api/yo")
            caso("login fallido", "POST", "/api/login", {"usuario": "a", "clave": "mal"})
            ficha_j = caso("login juez", "POST", "/api/login", {"usuario": "a", "clave": "clave-de-prueba-a"})
            ficha_f = caso("login fiscalía", "POST", "/api/login", {"usuario": "f", "clave": "clave-de-prueba-f"})
            cj, cf = ficha_j.split(";")[0], ficha_f.split(";")[0]
            caso("yo", "GET", "/api/yo", cookie=cj)
            caso("bandeja", "GET", "/api/juez/bandeja", cookie=cj)
            caso("sala", "GET", "/api/sala", cookie=cf)
            caso("acción del juez", "POST", f"/api/juez/ubicaciones/{exp}/1/rechazar", {"motivo": "x"}, cj)
            caso("ratificar", "POST", "/api/juez/traspaso/ratificar", {}, cj)
            with mock.patch.object(self.motor, "firmar_marco", create=True, return_value={"id": "OM-01"}), \
                    mock.patch.object(self.motor, "vista_proveedor", create=True, return_value=VISTA_PROV), \
                    mock.patch.object(self.motor, "consulta_publica", create=True, return_value={"resultado": "x"}), \
                    mock.patch.object(api.kit, "lista_ips", create=True, return_value="203.0.113.9\n"):
                caso("orden marco", "POST", "/api/juez/marco", {"seguimiento": True}, cj)
                caso("vigentes.json", "GET", "/proveedor/p1/vigentes.json")
                caso("ips.txt", "GET", "/proveedor/p1/ips.txt")
                caso("consulta pública", "GET", "/api/publico/consulta?dominio=a.test")
            caso("logout", "POST", "/api/logout", {}, cj)
            caso("estático", "GET", "/")
        finally:
            parar(servidor)
        for nombre, estado, sondas in casos:
            with self.subTest(ruta=nombre, http=estado):
                self.assertTrue(sondas, "la respuesta no pasó por el socket")
                self.assertTrue(all(sondas), f"{nombre}: se escribió al socket con motor.candado tomado")

    def test_cliente_que_no_lee_no_traba_el_motor(self):
        registro = []
        bloqueo = {"entro": threading.Event(), "soltar": threading.Event()}
        servidor = Servidor(("127.0.0.1", 0), manejador_con_sonda(self.motor, registro, [bloqueo]))
        puerto = arrancar(servidor)
        trabado = threading.Thread(target=lambda: pedir(puerto, "GET", "/api/publico/registro", timeout=15),
                                   daemon=True)
        trabado.start()
        try:
            self.assertTrue(bloqueo["entro"].wait(5), "el pedido trabado nunca llegó a escribir")
            libre = self.motor.candado.acquire(timeout=1.0)
            if libre:
                self.motor.candado.release()
            self.assertTrue(libre, "con un cliente trabado en la escritura, el motor no consigue su candado")
            t0 = time.monotonic()
            estado, _, _ = pedir(puerto, "GET", "/api/salud", timeout=3)
            self.assertEqual(estado, 200)
            self.assertLess(time.monotonic() - t0, 2.0)
        finally:
            bloqueo["soltar"].set()
            trabado.join(5)
            parar(servidor)


VISTA_PROV = {"acelerar": 20.0, "v": 3, "proveedor": {"id": "p1", "nombre": "Proveedor Uno", "capacidades": ["ip"]}, "minuto": 10.0,
              "hora": "21:10", "vigentes": [], "retiradas": []}


def pedir_crudo(puerto, ruta):
    c = http.client.HTTPConnection("127.0.0.1", puerto, timeout=5)
    c.request("GET", ruta)
    r = c.getresponse()
    cuerpo, cab = r.read(), dict(r.getheaders())
    c.close()
    return r.status, cuerpo, cab


class TestRutasRonda2b(unittest.TestCase):
    """Contrato entre agentes: rutas y cuerpos nuevos, y a qué método del motor llaman (nombres exactos)."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        cls.motor = motor_falso(Path(cls.dir.name))
        cls.servidor = servir(cls.motor, "127.0.0.1", 0)
        cls.puerto = arrancar(cls.servidor)
        cls.exp = cls.motor.e["expedientes"][0]["id"]

    @classmethod
    def tearDownClass(cls):
        parar(cls.servidor)
        cerrar_motor(cls.motor)
        cls.dir.cleanup()

    def entrar(self, usuario, clave):
        _, _, galleta = pedir(self.puerto, "POST", "/api/login", {"usuario": usuario, "clave": clave})
        return galleta.split(";")[0]

    def setUp(self):
        self.cj = self.entrar("a", "clave-de-prueba-a")

    def test_orden_marco(self):
        with mock.patch.object(self.motor, "firmar_marco", create=True, return_value={"id": "OM-01"}) as firmar:
            estado, texto, _ = pedir(self.puerto, "POST", "/api/juez/marco", {"seguimiento": True}, self.cj)
            self.assertEqual(estado, 200, texto)
            datos = json.loads(texto)
            self.assertEqual(datos["resultado"], {"id": "OM-01"})
            self.assertIn("bandeja", datos)
            firmar.assert_called_once_with("juez-a", True)
            pedir(self.puerto, "POST", "/api/juez/marco", {}, self.cj)
            firmar.assert_called_with("juez-a", False)  # apagado por defecto
            firmar.reset_mock()
            for malo in ("si", 1, None, [True]):
                with self.subTest(seguimiento=malo):
                    estado, _, _ = pedir(self.puerto, "POST", "/api/juez/marco", {"seguimiento": malo}, self.cj)
                    self.assertEqual(estado, 422)
            self.assertEqual(pedir(self.puerto, "POST", "/api/juez/marco", {"seguimiento": True})[0], 401)
            cf = self.entrar("f", "clave-de-prueba-f")
            self.assertEqual(pedir(self.puerto, "POST", "/api/juez/marco", {"seguimiento": True}, cf)[0], 403)
            firmar.assert_not_called()

    def test_ratificar_con_dinamicas(self):
        with mock.patch.object(self.motor, "ratificar", return_value=None) as rat:
            for cuerpo in ({}, {"dinamicas": None}):
                rat.reset_mock()
                estado, texto, _ = pedir(self.puerto, "POST", "/api/juez/traspaso/ratificar", cuerpo, self.cj)
                self.assertEqual(estado, 200)
                rat.assert_called_once_with("juez-a")
                # Misma forma que herramientas/api_simulada.py: {ok, aviso (null si no hay), bandeja}.
                datos = json.loads(texto)
                self.assertLessEqual({"ok", "aviso", "bandeja"}, set(datos))
                self.assertIsNone(datos["aviso"])
            rat.reset_mock()
            rat.return_value = {"aviso": "Falta la orden marco con seguimiento: se ratificó lo demás."}
            estado, texto, _ = pedir(self.puerto, "POST", "/api/juez/traspaso/ratificar",
                                     {"dinamicas": [self.exp]}, self.cj)
            self.assertEqual(estado, 200)
            rat.assert_called_once_with("juez-a", [self.exp])
            self.assertIn("orden marco", json.loads(texto)["aviso"])
            rat.reset_mock()
            for malo in ("todas", [1], {"a": 1}):
                with self.subTest(dinamicas=malo):
                    self.assertEqual(pedir(self.puerto, "POST", "/api/juez/traspaso/ratificar",
                                           {"dinamicas": malo}, self.cj)[0], 422)
            rat.assert_not_called()

    def test_revocar_y_levantar(self):
        ruta = f"/api/juez/dinamicas/{self.exp}/revocar"
        with mock.patch.object(self.motor, "revocar_dinamica", return_value=None) as rev:
            self.assertEqual(pedir(self.puerto, "POST", ruta, {"motivo": "basta"}, self.cj)[0], 200)
            rev.assert_called_once_with("juez-a", self.exp, "basta")
            rev.reset_mock()
            self.assertEqual(pedir(self.puerto, "POST", ruta, {"motivo": "basta", "levantar": True}, self.cj)[0], 200)
            rev.assert_called_once_with("juez-a", self.exp, "basta", levantar=True)
            rev.reset_mock()
            self.assertEqual(pedir(self.puerto, "POST", ruta, {"levantar": "si"}, self.cj)[0], 422)
            rev.assert_not_called()

    def test_listas_del_proveedor(self):
        textos = {"dominios.txt": "lista_dominios", "ips.txt": "lista_ips", "unbound.conf": "unbound_conf",
                  "rpz.zone": "zona_rpz"}
        with mock.patch.object(self.motor, "vista_proveedor", create=True, return_value=VISTA_PROV) as vista:
            estado, cuerpo, cab = pedir_crudo(self.puerto, "/proveedor/p1/vigentes.json")
            self.assertEqual(estado, 200)
            self.assertEqual(json.loads(cuerpo), VISTA_PROV)
            self.assertEqual(cab["Cache-Control"], "no-store")
            self.assertTrue(cab["Content-Type"].startswith("application/json"))
            vista.assert_called_with("p1")
            for archivo, funcion in textos.items():
                with self.subTest(archivo=archivo), \
                        mock.patch.object(api.kit, funcion, create=True, return_value=f"# {funcion}\n") as f:
                    estado, cuerpo, cab = pedir_crudo(self.puerto, f"/proveedor/p%201/{archivo}")
                    self.assertEqual((estado, cuerpo.decode()), (200, f"# {funcion}\n"))
                    self.assertEqual(cab["Cache-Control"], "no-store")
                    self.assertTrue(cab["Content-Type"].startswith("text/plain"))
                    f.assert_called_once_with(VISTA_PROV)
                    vista.assert_called_with("p 1")
            self.assertEqual(pedir_crudo(self.puerto, "/proveedor/p1/otra.txt")[0], 404)
            self.assertEqual(pedir_crudo(self.puerto, "/proveedor/p1/../../config/jueces_demo.json")[0], 404)
        with mock.patch.object(self.motor, "vista_proveedor", create=True,
                               side_effect=api.ErrorAccion("no_encontrado", "No existe ese proveedor.")):
            estado, cuerpo, _ = pedir_crudo(self.puerto, "/proveedor/nadie/vigentes.json")
            self.assertEqual(estado, 404)
            self.assertEqual(json.loads(cuerpo)["codigo"], "no_encontrado")

    def test_consulta_publica(self):
        with mock.patch.object(self.motor, "consulta_publica", create=True,
                               return_value={"dominio": "a.test", "resultado": "no_alcanzado"}) as cons:
            estado, cuerpo, cab = pedir_crudo(self.puerto, "/api/publico/consulta?dominio=a.test")
            self.assertEqual((estado, json.loads(cuerpo)["resultado"]), (200, "no_alcanzado"))
            self.assertEqual(cab["Cache-Control"], "no-store")
            cons.assert_called_once_with("a.test")
            pedir_crudo(self.puerto, "/api/publico/consulta?dominio=" + "x" * 5000)
            self.assertEqual(len(cons.call_args[0][0]), api.MAX_DOMINIO_CONSULTA)
            pedir_crudo(self.puerto, "/api/publico/consulta")
            cons.assert_called_with("")

    def test_actividad_del_juez(self):
        libres = []

        def anotar(juez_id):
            r = []

            def probar():  # el RLock se suelta en el mismo hilo que lo tomó
                ok = self.motor.candado.acquire(timeout=1.0)
                if ok:
                    self.motor.candado.release()
                r.append(ok)
            t = threading.Thread(target=probar)
            t.start()
            t.join()
            libres.append(r[0])

        cf = self.entrar("f", "clave-de-prueba-f")
        with mock.patch.object(self.motor.usuarios, "marcar_actividad", create=True, side_effect=anotar) as marcar:
            casos = [("bandeja", "GET", "/api/juez/bandeja", None, self.cj, 1),
                     ("acción", "POST", f"/api/juez/ubicaciones/{self.exp}/1/rechazar", {"motivo": "x"}, self.cj, 1),
                     # C17: «presente» = la bandeja abierta. /api/yo y las esperas de páginas públicas no cuentan.
                     ("yo", "GET", "/api/yo", None, self.cj, 0),
                     ("cambios de la bandeja (inicio y fin de la espera)", "GET", "/api/cambios?v=0&de=juez", None,
                      self.cj, 2),
                     ("cambios de una página pública con la galleta del juez", "GET", "/api/cambios?v=0", None,
                      self.cj, 0),
                     ("cambios de la bandeja sin sesión", "GET", "/api/cambios?v=0&de=juez", None, None, 0),
                     ("cambios sin sesión", "GET", "/api/cambios?v=0", None, None, 0),
                     ("fiscalía", "GET", "/api/sala", None, cf, 0),
                     ("cambios de fiscalía", "GET", "/api/cambios?v=0", None, cf, 0),
                     ("público", "GET", "/api/publico/registro", None, None, 0),
                     ("juez en ruta de fiscalía", "GET", "/api/sala", None, self.cj, 0),
                     ("login", "POST", "/api/login", {"usuario": "b", "clave": "clave-de-prueba-b"}, None, 1)]
            for nombre, metodo, ruta, cuerpo, cookie, veces in casos:
                with self.subTest(caso=nombre):
                    marcar.reset_mock()
                    pedir(self.puerto, metodo, ruta, cuerpo, cookie)
                    self.assertEqual(marcar.call_count, veces)
                    for llamada in marcar.call_args_list:
                        self.assertIn(llamada[0][0], ("juez-a", "juez-b"))
        self.assertTrue(libres and all(libres), "marcar_actividad se llamó con motor.candado tomado")

    def test_error_inesperado_da_500(self):
        with mock.patch.object(self.motor, "vista_registro", side_effect=RuntimeError("roto")):
            estado, cuerpo, _ = pedir_crudo(self.puerto, "/api/publico/registro")
        self.assertEqual(estado, 500)
        self.assertEqual(json.loads(cuerpo)["codigo"], "interno")
        with mock.patch.object(self.motor, "rechazar", side_effect=KeyError("x")):
            estado, _, _ = pedir(self.puerto, "POST", f"/api/juez/ubicaciones/{self.exp}/1/rechazar",
                                 {"motivo": "x"}, self.cj)
        self.assertEqual(estado, 500)
        self.assertEqual(pedir(self.puerto, "GET", "/api/salud")[0], 200)  # el servidor sigue


class TestTiemposYTope(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        cls.motor = motor_falso(Path(cls.dir.name))

    @classmethod
    def tearDownClass(cls):
        cerrar_motor(cls.motor)
        cls.dir.cleanup()

    def test_el_manejador_tiene_timeout_de_socket(self):
        """Contrato: lectura y escritura del socket tienen un plazo (unos 15 s)."""
        self.assertEqual(crear_manejador(self.motor).timeout, api.TIMEOUT_SOCKET_S)
        self.assertTrue(5 <= api.TIMEOUT_SOCKET_S <= 60)

    def test_conexion_muda_se_corta_sola(self):
        """Contrato: un pedido que nunca termina de llegar libera su conexión y su hilo."""
        with mock.patch.object(api, "TIMEOUT_SOCKET_S", 0.5):
            servidor = servir(self.motor, "127.0.0.1", 0)
        puerto = arrancar(servidor)
        try:
            s = socket.create_connection(("127.0.0.1", puerto), timeout=3)
            s.sendall(b"GET /api/salud HTTP/1.1\r\n")
            t0 = time.monotonic()
            _, cerrada = leer_todo(s, 4.0)
            s.close()
            self.assertTrue(cerrada, "la conexión muda sigue abierta")
            self.assertLess(time.monotonic() - t0, 3.0)
        finally:
            parar(servidor)

    def test_espera_larga_conserva_su_duracion(self):
        """Contrato: el timeout del socket no corta la espera larga de /api/cambios."""
        with mock.patch.object(api, "TIMEOUT_SOCKET_S", 0.4), mock.patch.object(api, "ESPERA_CAMBIOS_S", 1.2):
            servidor = servir(self.motor, "127.0.0.1", 0)
            puerto = arrancar(servidor)
            try:
                t0 = time.monotonic()
                estado, texto, _ = pedir(puerto, "GET", f"/api/cambios?v={self.motor.v}", timeout=5)
                demora = time.monotonic() - t0
            finally:
                parar(servidor)
        self.assertEqual(estado, 200)
        self.assertIn(b'"v"', texto)
        self.assertGreaterEqual(demora, 1.1)

    def test_tope_de_conexiones_simultaneas(self):
        """Contrato: pasado el tope, la conexión nueva recibe 503 enseguida; al liberarse una, se atiende."""
        class Chico(Servidor):
            max_conexiones = 2
        servidor = Chico(("127.0.0.1", 0), crear_manejador(self.motor))
        puerto = arrancar(servidor)
        mudas = []
        try:
            for _ in range(2):
                s = socket.create_connection(("127.0.0.1", puerto), timeout=3)
                s.sendall(b"GET /api/salud HTTP/1.1\r\n")  # sin terminar: retiene su hilo
                mudas.append(s)
            time.sleep(0.2)
            s3 = socket.create_connection(("127.0.0.1", puerto), timeout=3)
            recibido, _ = leer_todo(s3, 3.0)  # el 503 sale al aceptar, sin leer nada
            s3.close()
            self.assertTrue(recibido.startswith(b"HTTP/1.1 503"), recibido[:80])
            mudas.pop().close()
            limite = time.monotonic() + 3
            estado = None
            while time.monotonic() < limite:
                try:
                    estado, _, _ = pedir(puerto, "GET", "/api/salud", timeout=2)
                except (OSError, http.client.HTTPException):
                    estado = None
                if estado == 200:
                    break
                time.sleep(0.05)
            self.assertEqual(estado, 200)
        finally:
            for s in mudas:
                s.close()
            parar(servidor)


class TestCuerpoYLargos(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        cls.motor = motor_falso(Path(cls.dir.name))
        cls.servidor = servir(cls.motor, "127.0.0.1", 0)
        cls.puerto = arrancar(cls.servidor)

    @classmethod
    def tearDownClass(cls):
        parar(cls.servidor)
        cerrar_motor(cls.motor)
        cls.dir.cleanup()

    def logins_auditados(self):
        return sum(1 for e in leer_entradas(self.motor.salida / "auditoria.jsonl")
                   if e["tipo"] in ("login_fallido", "sesion_iniciada"))

    def test_content_length_invalido_da_400_sin_leer(self):
        """Contrato: Content-Length negativo o no numérico → 400 enseguida, sin leer el cuerpo ni intentar el
        ingreso. Se mandan solo los encabezados: si el servidor intentara leer (read(-1) lee hasta el final),
        la respuesta no llegaría hasta que el cliente cierre."""
        for largo in ("-1", "-200000", "abc", "+5", "1e3", " -0"):
            with self.subTest(largo=largo):
                antes = self.logins_auditados()
                s = socket.create_connection(("127.0.0.1", self.puerto), timeout=3)
                s.sendall(b"POST /api/login HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
                          b"Content-Length: " + largo.encode() + b"\r\n\r\n")
                t0 = time.monotonic()
                recibido, cerrada = leer_todo(s, 3.0)
                s.close()
                self.assertLess(time.monotonic() - t0, 2.0)
                self.assertTrue(cerrada)
                self.assertTrue(recibido.startswith(b"HTTP/1.1 400"), recibido[:80])
                self.assertEqual(recibido.count(b"HTTP/1.1 "), 1, recibido[:300])
                self.assertEqual(self.logins_auditados(), antes)

    def test_usuario_o_clave_demasiado_largos(self):
        estado, _, _ = pedir(self.puerto, "POST", "/api/login", {"usuario": "a", "clave": "x" * 5000})
        self.assertEqual(estado, 401)
        estado, _, _ = pedir(self.puerto, "POST", "/api/login", {"usuario": "u" * 5000, "clave": "x"})
        self.assertEqual(estado, 401)


def derivar_rapido(clave, sal):
    return hashlib.sha256(sal + clave.encode("utf-8")).digest()


class TestIngreso(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.ruta = Path(self.dir.name) / "jueces.json"
        self.ruta.write_text(json.dumps(CONFIG), encoding="utf-8")

    def tearDown(self):
        self.dir.cleanup()

    def test_largo_acotado_sin_derivar(self):
        """Contrato: una clave o un usuario más largos que el tope se rechazan sin correr PBKDF2."""
        u = Usuarios(self.ruta)
        llamadas = []
        with mock.patch.object(usuarios_mod, "derivar", lambda c, s: llamadas.append(len(c)) or b""):
            for usuario, clave in (("a", "x" * 10_000), ("u" * 10_000, "x")):
                with self.assertRaises(ErrorLogin):
                    u.ingresar(usuario, clave)
        self.assertEqual(llamadas, [])

    def test_intentos_fallidos_acotados_sin_perder_la_traba(self):
        """Contrato: inundar con usuarios inventados no hace crecer _fallos sin límite ni borra el contador
        de un usuario real (la traba a los 5 intentos sigue funcionando)."""
        with mock.patch.object(usuarios_mod, "derivar", derivar_rapido):
            u = Usuarios(self.ruta)
            for _ in range(usuarios_mod.INTENTOS_MAX - 1):
                with self.assertRaises(ErrorLogin):
                    u.ingresar("a", "mal")
            for i in range(usuarios_mod.MAX_FALLOS_DESCONOCIDOS * 3):
                with self.assertRaises(ErrorLogin):
                    u.ingresar(f"inventado-{i}", "mal")
            self.assertLessEqual(len(u._fallos), usuarios_mod.MAX_FALLOS_DESCONOCIDOS + len(CONFIG["usuarios"]))
            with self.assertRaises(ErrorLogin):
                u.ingresar("a", "mal")
            with self.assertRaises(ErrorLogin) as ctx:
                u.ingresar("a", "clave-de-prueba-a")
            self.assertEqual(ctx.exception.codigo, "trabado")


if __name__ == "__main__":
    unittest.main()
