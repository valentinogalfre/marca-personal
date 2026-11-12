"""Contrato c1-seguridad-web-3: con --host 0.0.0.0, una sola máquina de la WiFi no deja sin servicio a los demás.

- Plazo por pedido: desde su primer byte, un pedido (cabeceras + cuerpo) tiene PLAZO_PEDIDO_S para llegar entero.
  El goteo de a un byte (que esquiva el timeout por recv) se corta al vencer. Una conexión keep-alive quieta antes
  del primer byte no cuenta contra ese plazo (sigue TIMEOUT_SOCKET_S).
- Tope por origen: una IP que no sea esta máquina no ocupa más de MAX_CONEXIONES_POR_ORIGEN; las de más reciben
  503 y otra IP sigue siendo atendida. Esta máquina (sala, ensayo con proxy, túnel) no tiene ese tope.
"""
import socket
import threading
import time
import unittest

from marca import api


class _Hola(api.PlazoDePedido):
    protocol_version = "HTTP/1.1"
    plazo_pedido_s = 1.0
    timeout = 5.0

    def log_message(self, *a):
        pass

    def do_GET(self):
        cuerpo = b"hola"
        self.send_response(200)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)


def _servidor(clase=api.Servidor, manejador=_Hola):
    s = clase(("127.0.0.1", 0), manejador)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


def _pedir(puerto, espera=3.0):
    c = socket.create_connection(("127.0.0.1", puerto), timeout=espera)
    try:
        c.sendall(b"GET / HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
        datos = b""
        while True:
            parte = c.recv(4096)
            if not parte:
                return datos
            datos += parte
    finally:
        c.close()


class TestPlazoPorPedido(unittest.TestCase):
    def setUp(self):
        self.s = _servidor()
        self.puerto = self.s.server_address[1]

    def tearDown(self):
        self.s.shutdown()
        self.s.server_close()

    def test_el_goteo_se_corta_al_vencer_el_plazo(self):
        c = socket.create_connection(("127.0.0.1", self.puerto), timeout=5)
        c.sendall(b"GET / HTTP/1.1\r\n")
        t0 = time.monotonic()
        cortada = None
        try:
            while time.monotonic() - t0 < 4.0:  # sin plazo, el goteo la mantendría viva los 4 s
                time.sleep(0.25)
                c.sendall(b"X")
        except OSError:
            cortada = time.monotonic() - t0
        if cortada is None:
            c.settimeout(1.0)
            try:
                cortada = time.monotonic() - t0 if c.recv(1) == b"" else None
            except OSError:
                cortada = time.monotonic() - t0
        c.close()
        self.assertIsNotNone(cortada, "el goteo sigue vivo después del plazo")
        self.assertLess(cortada, 3.0)

    def test_la_espera_antes_del_primer_byte_no_cuenta(self):
        c = socket.create_connection(("127.0.0.1", self.puerto), timeout=5)
        try:
            time.sleep(1.5)  # más que el plazo del pedido, menos que el timeout del socket
            c.sendall(b"GET / HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
            self.assertIn(b"200", c.recv(4096).split(b"\r\n")[0])
        finally:
            c.close()

    def test_keep_alive_rearma_el_plazo(self):
        c = socket.create_connection(("127.0.0.1", self.puerto), timeout=5)
        try:
            for _ in range(3):  # tres pedidos en la misma conexión, separados más que el plazo
                c.sendall(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
                r = b""
                while not r.endswith(b"hola"):
                    r += c.recv(4096)
                self.assertTrue(r.startswith(b"HTTP/1.1 200"))
                time.sleep(1.2)
        finally:
            c.close()

    def test_el_manejador_de_la_plataforma_tiene_el_plazo(self):
        from unittest import mock
        self.assertTrue(issubclass(api.crear_manejador(mock.MagicMock()), api.PlazoDePedido))


class TestTopePorOrigen(unittest.TestCase):
    def test_una_ip_no_llena_el_cupo_de_todos(self):
        class TodosDeAfuera(api.Servidor):
            max_por_origen = 3
            # en la prueba todo llega por 127.0.0.1: el puerto de origen par hace de «la laptop» de afuera
            def origen_con_tope(self, client_address):
                return "laptop" if client_address[1] % 2 == 0 else "celular-%d" % client_address[1]
        s = _servidor(TodosDeAfuera)
        puerto = s.server_address[1]
        quietas = []
        try:
            while len(quietas) < 3:
                c = socket.socket()
                c.bind(("127.0.0.1", 0))
                if c.getsockname()[1] % 2:
                    c.close()
                    continue
                c.connect(("127.0.0.1", puerto))
                c.sendall(b"GET / HTTP/1.1\r\n")  # a medias, ocupa su lugar
                quietas.append(c)
            time.sleep(0.2)
            # una cuarta de «la laptop»: 503
            while True:
                c = socket.socket()
                c.bind(("127.0.0.1", 0))
                if c.getsockname()[1] % 2 == 0:
                    break
                c.close()
            c.settimeout(3)
            c.connect(("127.0.0.1", puerto))
            self.assertIn(b"503", c.recv(4096))
            c.close()
            # otro origen sigue siendo atendido
            while True:
                c = socket.socket()
                c.bind(("127.0.0.1", 0))
                if c.getsockname()[1] % 2:
                    break
                c.close()
            c.settimeout(3)
            c.connect(("127.0.0.1", puerto))
            c.sendall(b"GET / HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
            self.assertIn(b"200", c.recv(4096))
            c.close()
            # al cerrarse las de la laptop, el lugar se libera
            for q in quietas:
                q.close()
            quietas = []
            for _ in range(50):
                if not s._por_origen.get("laptop"):
                    break
                time.sleep(0.05)
            self.assertEqual(s._por_origen.get("laptop", 0), 0)
        finally:
            for q in quietas:
                q.close()
            s.shutdown()
            s.server_close()

    def test_esta_maquina_no_tiene_tope_y_la_red_si(self):
        s = api.Servidor(("127.0.0.1", 0), _Hola, bind_and_activate=False)
        try:
            self.assertIsNone(s.origen_con_tope(("127.0.0.1", 5)))
            self.assertIsNone(s.origen_con_tope(("::1", 5, 0, 0)))
            self.assertIsNone(s.origen_con_tope(("::ffff:127.0.0.1", 5, 0, 0)))
            self.assertEqual(s.origen_con_tope(("192.168.0.7", 5)), "192.168.0.7")
            self.assertEqual(s.origen_con_tope(("::ffff:192.168.0.7", 5, 0, 0)), "::ffff:192.168.0.7")
        finally:
            s.server_close()


if __name__ == "__main__":
    unittest.main()
