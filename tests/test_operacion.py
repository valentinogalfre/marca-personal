"""Contratos de operación del día del partido (marca/__main__.py y marca/exportar.py).

- Un segundo `servir` sobre una --salida en uso (candado tomado, plataforma viva o puerto ocupado) sale con
  código distinto de 0 y un mensaje claro, sin leer, mover ni escribir nada de la carpeta.
- `--nueva` nunca borra: aparta la carpeta a <salida>.anterior-<fecha>; si el simulador ya tiene órdenes se niega
  (salvo --descartar-anteriores) y no toca nada.
- `exportar` no deja restos de una exportación anterior; no pisa una carpeta que no es una exportación; un corte a
  mitad de camino no deja un paquete a medias.
- Con la salida redirigida y una codificación sin ✓/✗ (Windows), los comandos no se caen.
- herramientas/proxy_latencia.py: sin demora devuelve lo mismo que el simulador; con demora, cada pedido tarda lo
  pedido (± jitter); con --falla-cada N, uno de cada N responde 502 sin llegar al simulador.
"""
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from marca import exportar as exportar_mod
from marca.__main__ import (EXIT_NUEVA, EXIT_OCUPADA, EXIT_PUERTO, CandadoSalida, exportar_paquete,
                            preparar_nueva, ruta_candado)
from marca.auditoria import leer_entradas
from marca.exportar import ErrorDestino, escribir_manifiesto, exportar
from marca.simulador import ErrorRed
from marca.verificar import verificar

from tests.simulador_falso import SimuladorFalso
from tests.test_motor_verificar import correr_partido

RAIZ = Path(__file__).resolve().parent.parent
PY = sys.executable


def foto(carpeta: Path) -> dict:
    """Ruta relativa → sha256 de todo lo que hay en la carpeta padre (incluye hermanas y apartadas)."""
    base = carpeta.parent
    res = {}
    for p in sorted(base.rglob("*")):
        rel = p.relative_to(base).as_posix()
        if p.name.endswith(".candado"):
            continue
        res[rel] = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else "<dir>"
    return res


def salida_con_estado(base: Path) -> Path:
    salida = base / "salida"
    (salida / "capturas").mkdir(parents=True)
    (salida / "estado.json").write_text(json.dumps({"partido": {"id": "p"}, "minuto": 5.0}), encoding="utf-8")
    (salida / "auditoria.jsonl").write_text('{"n": 1}\n', encoding="utf-8")
    (salida / "capturas" / "D-0001.ts").write_bytes(b"\x47" * 188)
    return salida


def correr_servir(salida: Path, *extra, puerto=0, simulador="http://127.0.0.1:9", timeout=25):
    cmd = [PY, "-m", "marca", "servir", "--simulador", simulador, "--salida", str(salida),
           "--puerto", str(puerto)] + list(extra)
    try:
        r = subprocess.run(cmd, cwd=str(RAIZ), capture_output=True, text=True, timeout=timeout,
                           env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        return r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired as err:
        return None, f"no terminó en {timeout} s: {err.stdout!r}"


class _SimHTTP(BaseHTTPRequestHandler):
    """Expone un SimuladorFalso por HTTP (solo lecturas): lo que usan `chequear` y la guarda de --nueva."""
    sim = None

    def log_message(self, *a):
        pass

    def do_GET(self):
        s = self.server.sim
        partes = self.path.split("?")[0].strip("/").split("/")
        if partes == ["estado"]:
            datos = s.estado()
        elif partes == ["partido"]:
            datos = s.partido()
        elif partes == ["juzgados"]:
            datos = s.juzgados()
        elif partes == ["proveedores"]:
            datos = s.proveedores()
        elif len(partes) == 3 and partes[0] == "proveedores" and partes[2] == "ordenes":
            datos = s.ordenes(partes[1])
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        cuerpo = json.dumps(datos).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)


class SimConOrdenes(SimuladorFalso):
    """El simulador de un partido en curso: cada proveedor ya tiene una orden nuestra."""

    def ordenes(self, pid):
        return [{"orden_id": f"ord-0001-u1-{pid}-01-0123456789abcdef0123456789abcdef", "estado": "aplicada",
                 "tipo": "ip", "objetivo": "203.0.113.10"}]


def sim_http(sim):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _SimHTTP)
    srv.sim = sim
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


class TestSegundoServirNoTocaLaSalida(unittest.TestCase):
    """Contrato: un segundo servir sobre una --salida en uso no lee, mueve ni escribe nada de esa carpeta."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.salida = salida_con_estado(Path(self.dir.name))

    def tearDown(self):
        self.dir.cleanup()

    def test_candado_tomado(self):
        dueno = subprocess.Popen(
            [PY, "-c", "import sys, time\nfrom marca.__main__ import CandadoSalida\n"
                       "c = CandadoSalida(sys.argv[1])\nassert c.tomar()\nc.anotar(puerto=8700)\n"
                       "print('listo', flush=True)\ntime.sleep(120)\n", str(self.salida)],
            cwd=str(RAIZ), stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(dueno.stdout.readline().strip(), "listo")
            antes = foto(self.salida)
            for extra in ((), ("--nueva",), ("--nueva", "--descartar-anteriores")):
                with self.subTest(extra=extra):
                    codigo, texto = correr_servir(self.salida, *extra)
                    self.assertEqual(codigo, EXIT_OCUPADA, texto)
                    self.assertIn("Ya hay una plataforma corriendo", texto)
                    self.assertIn("No se tocó nada", texto)
                    self.assertIn("8700", texto)
                    self.assertEqual(foto(self.salida), antes)
        finally:
            dueno.kill()  # como un corte: el sistema suelta el candado solo
            dueno.wait(10)
            dueno.stdout.close()
        c = CandadoSalida(self.salida)
        self.assertTrue(c.tomar(), "el candado de un proceso muerto no se soltó")
        c.soltar()

    def test_puerto_ocupado(self):
        ocupado = socket.socket()
        ocupado.bind(("127.0.0.1", 0))
        ocupado.listen(1)
        puerto = ocupado.getsockname()[1]
        try:
            antes = foto(self.salida)
            for extra in ((), ("--nueva",)):
                with self.subTest(extra=extra):
                    codigo, texto = correr_servir(self.salida, *extra, puerto=puerto)
                    self.assertEqual(codigo, EXIT_PUERTO, texto)
                    self.assertIn(f"No se pudo abrir el puerto {puerto}", texto)
                    self.assertEqual(foto(self.salida), antes)
        finally:
            ocupado.close()

    def test_plataforma_viva_sin_candado(self):
        """Otra plataforma responde /api/salud con la instancia de plataforma.json (por ejemplo, en otra
        computadora sobre una carpeta compartida, donde el candado no alcanza)."""
        class Salud(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                cuerpo = json.dumps({"ok": True, "instancia": "abc123"}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(cuerpo)))
                self.end_headers()
                self.wfile.write(cuerpo)
        srv = ThreadingHTTPServer(("127.0.0.1", 0), Salud)
        threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        try:
            (self.salida / "plataforma.json").write_text(json.dumps(
                {"pid": 1, "host": "127.0.0.1", "puerto": srv.server_address[1], "instancia": "abc123"}),
                encoding="utf-8")
            antes = foto(self.salida)
            codigo, texto = correr_servir(self.salida, "--nueva")
            self.assertEqual(codigo, EXIT_OCUPADA, texto)
            self.assertIn("ya responde", texto)
            self.assertEqual(foto(self.salida), antes)
        finally:
            srv.shutdown()
            srv.server_close()

    def test_el_candado_va_al_lado_de_la_carpeta(self):
        self.assertEqual(ruta_candado(self.salida).parent, self.salida.resolve().parent)
        self.assertEqual(ruta_candado(self.salida).name, "salida.candado")


class TestNuevaNuncaBorra(unittest.TestCase):
    """Contrato: --nueva aparta (no borra) y se niega si el simulador ya tiene órdenes, sin tocar nada."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.salida = salida_con_estado(Path(self.dir.name))
        self.textos = []

    def tearDown(self):
        self.dir.cleanup()

    def test_simulador_con_ordenes_se_niega(self):
        antes = foto(self.salida)
        codigo = preparar_nueva(self.salida, SimConOrdenes(), False, self.textos.append, espera_s=0)
        self.assertEqual(codigo, EXIT_NUEVA)
        self.assertEqual(foto(self.salida), antes)
        texto = "\n".join(self.textos)
        self.assertIn("SIN --nueva", texto)
        self.assertIn("--descartar-anteriores", texto)

    def test_descartar_anteriores_aparta_sin_borrar(self):
        antes = foto(self.salida)
        codigo = preparar_nueva(self.salida, SimConOrdenes(), True, self.textos.append, espera_s=0)
        self.assertEqual(codigo, 0)
        self.assertFalse(self.salida.exists())
        apartadas = list(self.salida.parent.glob("salida.anterior-*"))
        self.assertEqual(len(apartadas), 1)
        movidos = {k.replace(apartadas[0].name, "salida", 1): v for k, v in foto(apartadas[0]).items()
                   if k.startswith(apartadas[0].name)}
        self.assertEqual(movidos, antes)

    def test_simulador_sin_ordenes_aparta(self):
        self.assertEqual(preparar_nueva(self.salida, SimuladorFalso(), False, self.textos.append, espera_s=0), 0)
        self.assertEqual(len(list(self.salida.parent.glob("salida.anterior-*"))), 1)
        # Dos --nueva seguidas en el mismo segundo no se pisan.
        salida_con_estado(Path(self.dir.name))
        self.assertEqual(preparar_nueva(self.salida, SimuladorFalso(), False, self.textos.append, espera_s=0), 0)
        self.assertEqual(len(list(self.salida.parent.glob("salida.anterior-*"))), 2)

    def test_simulador_sin_respuesta_no_toca_nada(self):
        class Caido:
            def proveedores(self):
                raise ErrorRed("sin conexión")
        antes = foto(self.salida)
        self.assertEqual(preparar_nueva(self.salida, Caido(), False, self.textos.append, espera_s=0), EXIT_NUEVA)
        self.assertEqual(foto(self.salida), antes)

    def test_servir_nueva_con_partido_en_curso(self):
        """De punta a punta: el comando real se niega antes de tocar la carpeta."""
        srv, url = sim_http(SimConOrdenes())
        try:
            antes = foto(self.salida)
            codigo, texto = correr_servir(self.salida, "--nueva", simulador=url)
            self.assertEqual(codigo, EXIT_NUEVA, texto)
            self.assertIn("SIN --nueva", texto)
            self.assertEqual(foto(self.salida), antes)
        finally:
            srv.shutdown()
            srv.server_close()

    def test_descartar_sin_nueva_es_un_error_de_uso(self):
        codigo, texto = correr_servir(self.salida, "--descartar-anteriores")
        self.assertEqual(codigo, 2, texto)


class TestExportarDestino(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        cls.base = Path(cls.dir.name)
        cls.motor, cls.sim, cls.entrega, cls.cfg = correr_partido(cls.base)
        cls.motor.despacho._pool.shutdown(wait=False)
        cls.motor.auditoria.cerrar()
        cls.salida = cls.motor.salida

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    def nuevo(self):
        return Path(tempfile.mkdtemp(dir=self.dir.name)) / "destino"

    def test_restos_de_una_exportacion_anterior_no_quedan(self):
        """Contrato: exportar sobre una exportación anterior la reemplaza entera y el resultado verifica."""
        d = self.nuevo()
        exportar(self.salida, d)
        (d / "expedientes" / "EXP-2026-999999.json").write_text("{}", encoding="utf-8")
        (d / "capturas" / "D-9999.ts").write_bytes(b"x")
        (d / "testigos" / "viejo.json").write_text("{}", encoding="utf-8")
        escribir_manifiesto(d)  # parece una exportación anterior de otro partido
        exportar(self.salida, d)
        self.assertFalse((d / "expedientes" / "EXP-2026-999999.json").exists())
        self.assertFalse((d / "capturas" / "D-9999.ts").exists())
        self.assertFalse((d / "testigos" / "viejo.json").exists())
        malas = [x for x in verificar(d, None, self.cfg).lineas if x.startswith("✗")]
        self.assertEqual(malas, [])
        self.assertEqual([p.name for p in d.parent.iterdir()], ["destino"])  # sin temporales

    def test_no_pisa_una_carpeta_que_no_es_exportacion(self):
        d = self.nuevo()
        d.mkdir()
        (d / "propuesta-normativa.md").write_text("no tocar", encoding="utf-8")
        with self.assertRaises(ErrorDestino) as ctx:
            exportar(self.salida, d)
        self.assertIn("MANIFIESTO.json", str(ctx.exception))
        self.assertEqual([p.name for p in d.iterdir()], ["propuesta-normativa.md"])
        # Por la línea de comandos: código 1, mensaje claro y la auditoría intacta (ni testigos pidió).
        antes = (self.salida / "auditoria.jsonl").read_bytes()
        textos = []
        self.assertEqual(exportar_paquete(self.salida, d, cliente=self.sim, imprimir=textos.append), 1)
        self.assertTrue(any("no es una exportación anterior" in t for t in textos), textos)
        self.assertEqual((self.salida / "auditoria.jsonl").read_bytes(), antes)

    def test_destino_vacio_o_inexistente_sirve(self):
        d = self.nuevo()
        exportar(self.salida, d)
        self.assertTrue((d / "MANIFIESTO.json").exists())
        d2 = self.nuevo()
        d2.mkdir()
        (d2 / ".DS_Store").write_bytes(b"\0")
        exportar(self.salida, d2)
        self.assertTrue((d2 / "MANIFIESTO.json").exists())

    def test_corte_a_mitad_deja_la_exportacion_anterior(self):
        d = self.nuevo()
        exportar(self.salida, d)
        manifiesto = (d / "MANIFIESTO.json").read_bytes()
        with mock.patch.object(exportar_mod, "acta_md", side_effect=RuntimeError("corte")):
            with self.assertRaises(RuntimeError):
                exportar(self.salida, d)
        self.assertEqual((d / "MANIFIESTO.json").read_bytes(), manifiesto)
        self.assertEqual([p.name for p in d.parent.iterdir()], ["destino"])
        self.assertEqual(verificar(d).fallas, 0)
        # Sin exportación anterior, un corte no deja un paquete a medias en el destino.
        d2 = self.nuevo()
        with mock.patch.object(exportar_mod, "acta_md", side_effect=RuntimeError("corte")):
            with self.assertRaises(RuntimeError):
                exportar(self.salida, d2)
        self.assertFalse(d2.exists())
        self.assertEqual(list(d2.parent.iterdir()), [])


class TestConsolaSinUnicode(unittest.TestCase):
    """Contrato: con la salida redirigida a una codificación sin ✓/✗ (Windows), los comandos no se caen."""

    def correr(self, *args):
        return subprocess.run([PY, "-m", "marca"] + list(args), cwd=str(RAIZ), capture_output=True, timeout=60,
                              env=dict(os.environ, PYTHONIOENCODING="cp1252"))

    def test_verificar_y_chequear(self):
        with tempfile.TemporaryDirectory() as d:
            r = self.correr("verificar", d)
            self.assertNotIn(b"UnicodeEncodeError", r.stderr)
            self.assertEqual(r.returncode, 1)
            self.assertIn("✗".encode("utf-8"), r.stdout)
            r = self.correr("chequear", "--simulador", "http://127.0.0.1:9", "--salida", str(Path(d) / "s"))
            self.assertNotIn(b"UnicodeEncodeError", r.stderr)
            self.assertIn("✗".encode("utf-8"), r.stdout)



def libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Eco(BaseHTTPRequestHandler):
    """Simulador mínimo: devuelve método, ruta y cuerpo; cuenta los pedidos que le llegan."""
    protocol_version = "HTTP/1.0"
    recibidos: list = []

    def log_message(self, *a):
        pass

    def _eco(self, estado=200):
        largo = int(self.headers.get("Content-Length") or 0)
        cuerpo = self.rfile.read(largo).decode() if largo else None
        _Eco.recibidos.append((self.command, self.path, cuerpo))
        datos = json.dumps({"metodo": self.command, "ruta": self.path, "cuerpo": cuerpo}).encode()
        self.send_response(404 if self.path.startswith("/no") else estado)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    do_GET = _eco
    do_POST = _eco


class TestProxyLatencia(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(RAIZ / "herramientas"))
        import proxy_latencia
        cls.mod = proxy_latencia
        cls.eco = ThreadingHTTPServer(("127.0.0.1", 0), _Eco)
        cls.eco.daemon_threads = True
        threading.Thread(target=cls.eco.serve_forever, daemon=True).start()
        cls.destino = f"http://127.0.0.1:{cls.eco.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.eco.shutdown()
        cls.eco.server_close()

    def proxy(self, **kw):
        srv = self.mod.arrancar(libre(), self.destino, **kw)
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return srv

    def pedir(self, srv, ruta, cuerpo=None):
        from marca.simulador import Cliente
        c = Cliente(f"http://127.0.0.1:{srv.server_address[1]}", timeout=5)
        t0 = time.monotonic()
        r = c._pedir("POST" if cuerpo is not None else "GET", ruta, cuerpo, timeout=5)
        return r, time.monotonic() - t0

    def test_sin_demora_es_transparente(self):
        srv = self.proxy()
        (estado, datos), _ = self.pedir(srv, "/estado?x=1")
        self.assertEqual((estado, datos["metodo"], datos["ruta"]), (200, "GET", "/estado?x=1"))
        (estado, datos), _ = self.pedir(srv, "/proveedores/p1/ordenes", {"tipo": "ip", "objetivo": "203.0.113.9"})
        self.assertEqual(estado, 200)
        self.assertEqual(json.loads(datos["cuerpo"]), {"tipo": "ip", "objetivo": "203.0.113.9"})
        (estado, _), _ = self.pedir(srv, "/no-existe")
        self.assertEqual(estado, 404)  # los errores del simulador pasan tal cual
        self.assertEqual([x["demora_ms"] for x in srv.pedidos], [0.0, 0.0, 0.0])

    def test_la_demora_es_la_pedida(self):
        srv = self.proxy(latencia_ms=300)
        for _ in range(3):
            _, dt = self.pedir(srv, "/estado")
            self.assertGreaterEqual(dt, 0.29)
            self.assertLess(dt, 1.5)
        self.assertTrue(all(x["demora_ms"] == 300.0 for x in srv.pedidos))

    def test_jitter_acotado_y_repetible(self):
        demoras = []
        for _ in range(2):
            srv = self.proxy(latencia_ms=200, jitter_ms=150, semilla=7)
            demoras.append([srv.turno()[1] for _ in range(200)])
        self.assertEqual(demoras[0], demoras[1])
        self.assertTrue(all(0.05 - 1e-9 <= d <= 0.35 + 1e-9 for d in demoras[0]))
        self.assertGreater(len(set(demoras[0])), 100)

    def test_falla_cada_n_no_llega_al_simulador(self):
        srv = self.proxy(falla_cada=3)
        _Eco.recibidos.clear()
        estados = [self.pedir(srv, "/proveedores/p1/ordenes", {"i": i})[0][0] for i in range(6)]
        self.assertEqual(estados, [200, 200, 502, 200, 200, 502])
        self.assertEqual([json.loads(c)["i"] for _, _, c in _Eco.recibidos], [0, 1, 3, 4])

    def test_simulador_caido_es_502(self):
        srv = self.mod.arrancar(libre(), f"http://127.0.0.1:{libre()}")
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        (estado, _), _ = self.pedir(srv, "/estado")
        self.assertEqual(estado, 502)

    def test_cli_sale_con_4_si_el_puerto_esta_ocupado(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            s.listen(1)
            r = subprocess.run([PY, str(RAIZ / "herramientas" / "proxy_latencia.py"), "--destino", self.destino,
                                "--puerto", str(s.getsockname()[1])], capture_output=True, timeout=20)
        self.assertEqual(r.returncode, 4, r.stderr)


if __name__ == "__main__":
    unittest.main()
