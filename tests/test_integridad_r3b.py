"""Contratos de la segunda tanda de la ronda 3 (integridad): C17, C18, turnos-2 (respuesta de la API).

- C18 (seguridad-1/-4): abierta a la red, la plataforma no acepta contraseñas publicadas en config/jueces_demo.json;
  `claves` arma el archivo del partido final sin mostrar contraseñas; `chequear --host` avisa lo mismo.
- C18 (seguridad-2): la traba de ingreso es por (usuario, origen).
- C18 (seguridad-3): los ingresos fallidos no inundan la auditoría (una entrada por origen y ventana, con contador).
- C17 (marco-1/-2): «presente» = la bandeja abierta; cerrar sesión la corta en el acto.
- turnos-2: /levantar y /revocar devuelven el «aviso» del motor.
Las contraseñas de las pruebas se leen por programa y nunca se imprimen.
"""
import io
import json
import os
import shutil
import stat
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from marca import __main__ as m
from marca import api, usuarios as usuarios_mod
from marca.api import Servidor, crear_manejador
from marca.motor import Motor
from marca.usuarios import ErrorLogin, Usuarios

from tests.simulador_falso import SimuladorFalso, deteccion
from tests.test_api import CONFIG, arrancar, cerrar_motor, derivar_rapido, motor_falso, parar, pedir
from tests.test_robustez import PIRATA

RAIZ = Path(__file__).resolve().parent.parent
S2 = ("s2.pirata.test", "203.0.113.11", "LP26-PRU-OFI-S0001", "https://pirata.test/vivo", 64600)


def claves_demo():
    with open(RAIZ / "config" / "jueces_demo.json", encoding="utf-8") as f:
        return [str(u["clave_demo"]) for u in json.load(f)["usuarios"]]


class Abierto(Exception):
    pass


def correr_main(argv):
    """main() en el mismo proceso, con abrir_servidor reemplazado: nunca se abre un puerto."""
    buf = io.StringIO()
    abrir = mock.Mock(side_effect=Abierto())
    with mock.patch.object(api, "abrir_servidor", abrir), redirect_stdout(buf):
        try:
            codigo = m.main(argv)
        except Abierto:
            codigo = "abrió"
    return codigo, buf.getvalue(), abrir.called


def config_propio(destino: Path) -> Path:
    """Mismo contenido que el de demostración, con contraseñas nuevas (lo arma el propio comando `claves`)."""
    with redirect_stdout(io.StringIO()):
        assert m.armar_claves(destino) == 0
    return destino


class TestRedConClavesPublicadas(unittest.TestCase):
    """Contrato C18: abierta a la red (--host que no es de loopback), la plataforma no arranca con contraseñas
    publicadas en config/jueces_demo.json: sale con código 6, explica qué hacer, no muestra contraseñas y no toca
    ni la carpeta de salida ni el puerto."""

    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix="r3b-red-"))
        self.salida = self.base / "salida"

    def tearDown(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def servir(self, *extra, salida=None):
        # Una salida por corrida: el doble de abrir_servidor corta cmd_servir con el candado de la carpeta tomado.
        return correr_main(["servir", "--simulador", "http://127.0.0.1:9", "--puerto", "0",
                            "--salida", str(salida or self.salida)] + list(extra))

    def test_red_con_config_de_demostracion_no_arranca_ni_toca_nada(self):
        for host in ("0.0.0.0", "::", "192.168.0.10", "192.0.2.1", "mi-mac.local"):
            with self.subTest(host=host):
                codigo, texto, abrio = self.servir("--host", host)
                self.assertEqual(codigo, m.EXIT_CLAVES, texto)
                self.assertFalse(abrio)
                self.assertFalse(self.salida.exists())
                self.assertFalse(m.ruta_candado(self.salida).exists())
                self.assertIn("jueces_demo.json", texto)
                self.assertIn("python3 -m marca claves", texto)
                for clave in claves_demo():
                    self.assertNotIn(clave, texto)

    def test_copia_del_archivo_de_demostracion_en_otra_ruta_tambien(self):
        copia = self.base / "otra.json"
        shutil.copy(RAIZ / "config" / "jueces_demo.json", copia)
        codigo, _, abrio = self.servir("--host", "0.0.0.0", "--config", str(copia))
        self.assertEqual(codigo, m.EXIT_CLAVES)
        self.assertFalse(abrio)

    def test_solo_esta_maquina_con_demostracion_sigue_andando(self):
        for host in ("127.0.0.1", "localhost", "::1", "127.0.0.2"):
            with self.subTest(host=host):
                codigo, _, abrio = self.servir("--host", host, salida=self.base / f"salida-{host}")
                self.assertEqual(codigo, "abrió")
                self.assertTrue(abrio)

    def test_red_con_contrasenas_propias_arranca(self):
        cfg = config_propio(self.base / "final.json")
        codigo, _, abrio = self.servir("--host", "0.0.0.0", "--config", str(cfg))
        self.assertEqual(codigo, "abrió")
        self.assertTrue(abrio)

    def test_chequear_con_host_de_red_avisa(self):
        codigo, texto, _ = correr_main(["chequear", "--simulador", "http://127.0.0.1:9", "--host", "192.0.2.1",
                                        "--salida", str(self.salida)])
        self.assertEqual(codigo, 1)
        self.assertIn("✗ Abierta a la red", texto)
        self.assertIn("jueces_demo.json", texto)
        cfg = config_propio(self.base / "final.json")
        _, texto, _ = correr_main(["chequear", "--simulador", "http://127.0.0.1:9", "--host", "192.0.2.1",
                                   "--config", str(cfg), "--salida", str(self.salida)])
        self.assertNotIn("✗ Abierta a la red", texto)
        self.assertIn("✓ Abierta a la red", texto)
        _, texto, _ = correr_main(["chequear", "--simulador", "http://127.0.0.1:9", "--salida", str(self.salida)])
        self.assertNotIn("Abierta a la red", texto)


class TestComandoClaves(unittest.TestCase):
    """Contrato C18: `claves` arma el archivo del partido final: mismos usuarios, roles, jueces y claves de firma
    que el de demostración, contraseñas de ingreso nuevas al azar, permisos 600, sin pisar uno existente salvo con
    --reemplazar; imprime la ruta y los usuarios, nunca las contraseñas. Va en .gitignore."""

    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix="r3b-claves-"))
        self.destino = self.base / "config" / "jueces_final.json"

    def tearDown(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def claves(self, *extra):
        return correr_main(["claves", "--salida", str(self.destino)] + list(extra))

    def test_arma_el_archivo_sin_mostrar_contrasenas(self):
        codigo, texto, _ = self.claves()
        self.assertEqual(codigo, 0, texto)
        demo = json.loads((RAIZ / "config" / "jueces_demo.json").read_text(encoding="utf-8"))
        final = json.loads(self.destino.read_text(encoding="utf-8"))
        self.assertEqual(final["claves_firma_demo"], demo["claves_firma_demo"])  # las del simulador
        sin_clave = [{k: v for k, v in u.items() if k != "clave_demo"} for u in demo["usuarios"]]
        self.assertEqual([{k: v for k, v in u.items() if k != "clave_demo"} for u in final["usuarios"]], sin_clave)
        nuevas = [u["clave_demo"] for u in final["usuarios"]]
        self.assertEqual(len(set(nuevas)), len(nuevas))
        for clave in nuevas:
            self.assertGreaterEqual(len(clave), 12)
            self.assertNotIn(clave, claves_demo())
            self.assertNotIn(clave, texto)
        for clave in claves_demo():
            self.assertNotIn(clave, texto)
        self.assertIn(str(self.destino), texto)
        for u in demo["usuarios"]:
            self.assertIn(u["usuario"], texto)
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(self.destino.stat().st_mode), 0o600)
        self.assertEqual(m.usuarios_con_clave_publicada(self.destino), [])
        # El archivo armado sirve para entrar (y la contraseña de demostración ya no).
        with mock.patch.object(usuarios_mod, "derivar", derivar_rapido):
            u = Usuarios(self.destino)
            primero = final["usuarios"][0]
            ficha, _ = u.ingresar(primero["usuario"], primero["clave_demo"])
            self.assertTrue(ficha)
            with self.assertRaises(ErrorLogin):
                u.ingresar(demo["usuarios"][0]["usuario"], demo["usuarios"][0]["clave_demo"])

    def test_no_pisa_sin_reemplazar(self):
        self.assertEqual(self.claves()[0], 0)
        antes = self.destino.read_bytes()
        codigo, texto, _ = self.claves()
        self.assertEqual(codigo, 1)
        self.assertIn("--reemplazar", texto)
        self.assertEqual(self.destino.read_bytes(), antes)
        codigo, _, _ = self.claves("--reemplazar")
        self.assertEqual(codigo, 0)
        self.assertNotEqual(self.destino.read_bytes(), antes)
        self.assertEqual([p.name for p in self.destino.parent.iterdir()], ["jueces_final.json"])  # sin temporales

    def test_gitignore_deja_afuera_el_archivo_final(self):
        lineas = (RAIZ / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("config/jueces_final.json", lineas)


class TestTrabaPorOrigen(unittest.TestCase):
    """Contrato C18 (seguridad-2): los intentos fallidos de un tercero desde otro origen no impiden que el juez entre
    con su clave; el que se equivoca sí queda trabado; /api/login traba por la IP real de la conexión."""

    def test_fallos_desde_otro_origen_no_traban_al_juez(self):
        with tempfile.TemporaryDirectory() as d:
            ruta = Path(d) / "j.json"
            ruta.write_text(json.dumps(CONFIG), encoding="utf-8")
            clave_a = next(x["clave_demo"] for x in CONFIG["usuarios"] if x["usuario"] == "a")
            with mock.patch.object(usuarios_mod, "derivar", derivar_rapido):
                u = Usuarios(ruta)
                for _ in range(usuarios_mod.INTENTOS_MAX):
                    with self.assertRaises(ErrorLogin):
                        u.ingresar("a", "mal", ip="10.0.0.66")
                ficha, yo = u.ingresar("a", clave_a, ip="10.0.0.5")
                self.assertTrue(ficha)
                self.assertEqual(yo["usuario"], "a")
                with self.assertRaises(ErrorLogin) as ctx:
                    u.ingresar("a", clave_a, ip="10.0.0.66")
                self.assertEqual(ctx.exception.codigo, "trabado")

    def test_api_pasa_la_ip_de_origen(self):
        with tempfile.TemporaryDirectory() as d:
            motor = motor_falso(Path(d))
            srv = api.servir(motor, "127.0.0.1", 0)
            puerto = arrancar(srv)
            try:
                with mock.patch.object(motor.usuarios, "ingresar", wraps=motor.usuarios.ingresar) as ing:
                    pedir(puerto, "POST", "/api/login", {"usuario": "a", "clave": "mal"})
                self.assertEqual(ing.call_args.kwargs.get("ip"), "127.0.0.1")
            finally:
                parar(srv)
                cerrar_motor(motor)


class TestFallosNoInundanLaAuditoria(unittest.TestCase):
    """Contrato C18 (seguridad-3): los ingresos fallidos no hacen crecer la auditoría ni el panel de la sala más allá
    de una entrada por origen y ventana; los omitidos se cuentan en la entrada siguiente; un ingreso correcto se sigue
    auditando."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.motor = motor_falso(Path(self.dir.name))
        self.servidor = api.servir(self.motor, "127.0.0.1", 0)
        self.puerto = arrancar(self.servidor)

    def tearDown(self):
        parar(self.servidor)
        cerrar_motor(self.motor)
        self.dir.cleanup()

    def golpear(self, usuarios):
        with mock.patch.object(usuarios_mod, "derivar", derivar_rapido):
            return [pedir(self.puerto, "POST", "/api/login", {"usuario": u, "clave": "mal"})[0] for u in usuarios]

    def fallidos(self):
        return [e for e in self.motor.auditoria.ultimas if e["tipo"] == "login_fallido"]

    def test_muchos_fallos_del_mismo_usuario(self):
        antes = self.motor.auditoria.n
        estados = self.golpear(["b"] * 60)
        self.assertIn(429, estados)
        self.assertEqual(self.motor.auditoria.n - antes, 1)
        sala = self.motor.vista_sala()["auditoria"]
        self.assertLessEqual(sum(1 for e in sala if e["tipo"] == "login_fallido"), 1)
        clave_f = next(x["clave_demo"] for x in CONFIG["usuarios"] if x["usuario"] == "f")
        self.assertEqual(pedir(self.puerto, "POST", "/api/login", {"usuario": "f", "clave": clave_f})[0], 200)
        self.assertEqual(self.motor.auditoria.ultimas[-1]["tipo"], "sesion_iniciada")

    def test_usuarios_inventados_rotando(self):
        antes = self.motor.auditoria.n
        self.golpear([f"nadie-{i}" for i in range(20)])
        self.assertEqual(self.motor.auditoria.n - antes, 1)

    def test_los_omitidos_se_cuentan_en_la_entrada_siguiente(self):
        self.golpear(["b"] * 3)
        with mock.patch.object(api, "VENTANA_FALLOS_S", 0.0):
            self.golpear(["b"])
        ult = self.fallidos()
        self.assertEqual(len(ult), 2)
        self.assertNotIn("intentos_sin_anotar", ult[0]["datos"])
        self.assertEqual(ult[-1]["datos"].get("intentos_sin_anotar"), 2)


class TestPresenciaEsLaBandeja(unittest.TestCase):
    """Contrato C17 (marco-1, marco-2): «presente» = la bandeja del juez abierta. Cerrar sesión deja al juez ausente en
    el acto (aun con una espera larga en curso) y una mudanza bajo su orden marco con seguimiento no se amplía con su
    clave; con otra sesión abierta del mismo juez, cerrar una no lo deja ausente. Una página pública con la galleta
    del juez no lo mantiene presente; la espera de la bandeja (de=juez) sí."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        (base / "j.json").write_text(json.dumps(CONFIG), encoding="utf-8")
        self.sim = SimuladorFalso()
        self.usuarios = Usuarios(base / "j.json")
        self.motor = Motor("http://falso", base / "salida", self.usuarios, cliente=self.sim, tick=0.01,
                           registro=lambda t: None)
        self.motor.arrancar(nueva=True, hilos=False)
        self.sim.lista_detecciones = [deteccion("D-1", 1.0, *PIRATA)]
        self.sim.avanzar(1.2)
        self.motor._t_estado = float("-inf")
        self.motor.paso()
        self.servidor = Servidor(("127.0.0.1", 0), crear_manejador(self.motor))
        self.puerto = arrancar(self.servidor)

    def tearDown(self):
        parar(self.servidor)
        cerrar_motor(self.motor)
        self._tmp.cleanup()

    def entrar(self):
        clave_a = next(x["clave_demo"] for x in CONFIG["usuarios"] if x["usuario"] == "a")
        st, _, galleta = pedir(self.puerto, "POST", "/api/login", {"usuario": "a", "clave": clave_a})
        self.assertEqual(st, 200)
        return galleta.split(";")[0]

    def firmar_y_aprobar(self, cookie):
        self.assertEqual(pedir(self.puerto, "POST", "/api/juez/marco", {"seguimiento": True}, cookie)[0], 200)
        exp = self.motor.e["expedientes"][0]
        st, _, _ = pedir(self.puerto, "POST", f"/api/juez/ubicaciones/{exp['id']}/1/aprobar",
                         {"alcance": "filtracion"}, cookie)
        self.assertEqual(st, 200)

    def mudanza(self):
        self.sim.lista_detecciones.append(deteccion("D-2", 1.5, *S2))
        self.sim.avanzar(1.6)
        self.motor._t_estado = float("-inf")
        self.motor.paso()
        return self.motor.e["expedientes"][0]["ubicaciones"][1]

    def amp(self):
        return [o["orden_id"] for o in self.motor.e["ordenes"].values() if o["orden_id"].startswith("amp-")]

    def test_cerrar_sesion_deja_ausente_y_no_amplia(self):
        cookie = self.entrar()
        self.firmar_y_aprobar(cookie)
        self.assertEqual(pedir(self.puerto, "POST", "/api/logout", {}, cookie)[0], 200)
        self.assertFalse(self.usuarios.activo("juez-a", 90))
        self.assertEqual(self.mudanza()["estado"], "pendiente")
        self.assertEqual(self.amp(), [])

    def test_cerrar_sesion_con_la_espera_de_la_bandeja_en_curso(self):
        cookie = self.entrar()
        self.firmar_y_aprobar(cookie)
        hilo = threading.Thread(target=pedir, args=(self.puerto, "GET", f"/api/cambios?v={self.motor.v}&de=juez",
                                                    None, cookie, 25))
        hilo.start()
        time.sleep(0.3)
        self.assertEqual(pedir(self.puerto, "POST", "/api/logout", {}, cookie)[0], 200)
        hilo.join(25)
        self.assertFalse(hilo.is_alive())
        self.assertFalse(self.usuarios.activo("juez-a", 90))
        self.assertEqual(self.mudanza()["estado"], "pendiente")
        self.assertEqual(self.amp(), [])

    def test_dos_sesiones_cerrar_una_no_lo_deja_ausente(self):
        cookie = self.entrar()
        otra = self.entrar()
        self.firmar_y_aprobar(cookie)
        self.assertEqual(pedir(self.puerto, "POST", "/api/logout", {}, cookie)[0], 200)
        self.assertTrue(self.usuarios.activo("juez-a", 90))
        self.assertEqual(pedir(self.puerto, "GET", "/api/juez/bandeja", cookie=otra)[0], 200)
        self.assertEqual(self.mudanza()["decision"]["tipo"], "ampliacion_dinamica")
        self.assertTrue(self.amp())

    def test_pagina_publica_con_la_galleta_no_es_presencia(self):
        cookie = self.entrar()
        self.firmar_y_aprobar(cookie)
        self.usuarios._actividad["juez-a"] = time.monotonic() - 200
        with mock.patch.object(api, "ESPERA_CAMBIOS_S", 0.2):
            pedir(self.puerto, "GET", f"/api/cambios?v={self.motor.v}", None, cookie)
        pedir(self.puerto, "GET", "/api/yo", None, cookie)
        pedir(self.puerto, "GET", "/api/publico/registro", None, cookie)
        self.assertFalse(self.usuarios.activo("juez-a", 90))
        self.assertFalse({j["juez_id"]: j for j in self.motor.vista_jueces()}["juez-a"]["activo"])
        self.assertEqual(self.mudanza()["estado"], "pendiente")
        self.assertEqual(self.amp(), [])

    def test_la_espera_de_la_bandeja_si_es_presencia(self):
        cookie = self.entrar()
        self.firmar_y_aprobar(cookie)
        self.usuarios._actividad["juez-a"] = time.monotonic() - 200
        with mock.patch.object(api, "ESPERA_CAMBIOS_S", 0.2):
            pedir(self.puerto, "GET", f"/api/cambios?v={self.motor.v}&de=juez", None, cookie)
        self.assertTrue(self.usuarios.activo("juez-a", 90))
        self.assertEqual((self.mudanza()["decision"] or {}).get("tipo"), "ampliacion_dinamica")


class TestAvisoDeLevantarYRevocar(unittest.TestCase):
    """Contrato turnos-2 (parte de la API): la respuesta de /levantar y /revocar lleva el «aviso» que devuelve el
    motor ({"aviso": texto} o {}), y no inventa uno cuando no viene."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.motor = motor_falso(Path(self.dir.name))
        self.servidor = api.servir(self.motor, "127.0.0.1", 0)
        self.puerto = arrancar(self.servidor)
        clave_a = next(x["clave_demo"] for x in CONFIG["usuarios"] if x["usuario"] == "a")
        _, _, galleta = pedir(self.puerto, "POST", "/api/login", {"usuario": "a", "clave": clave_a})
        self.cj = galleta.split(";")[0]

    def tearDown(self):
        parar(self.servidor)
        cerrar_motor(self.motor)
        self.dir.cleanup()

    def test_levantar_y_revocar_llevan_el_aviso(self):
        casos = (("levantar_ubicacion", "/api/juez/ubicaciones/EXP-1/1/levantar", {"motivo": "ya no transmite"}),
                 ("revocar_dinamica", "/api/juez/dinamicas/EXP-1/revocar", {"motivo": "x", "levantar": True}))
        for metodo, ruta, cuerpo in casos:
            for devuelve, esperado in (({"aviso": "Se mantuvo 1 bloqueo"}, "Se mantuvo 1 bloqueo"), ({}, None)):
                with self.subTest(metodo=metodo, devuelve=devuelve):
                    with mock.patch.object(self.motor, metodo, return_value=devuelve):
                        st, texto, _ = pedir(self.puerto, "POST", ruta, cuerpo, self.cj)
                    self.assertEqual(st, 200, texto)
                    self.assertEqual(json.loads(texto).get("aviso"), esperado)


def _sim_http_con_posts(sim):
    """El simulador por HTTP (lecturas), anotando cualquier POST: la plataforma no tiene que mandar nada."""
    from http.server import ThreadingHTTPServer
    from tests.test_operacion import _SimHTTP

    class Manejador(_SimHTTP):
        def do_POST(self):
            self.server.posts.append(self.path)
            self.send_response(500)
            self.send_header("Content-Length", "0")
            self.end_headers()

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Manejador)
    srv.sim = sim
    srv.posts = []
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


class TestReanudarSinEstadoConPartidoEnCurso(unittest.TestCase):
    """Contrato robustez-1: `servir` sin --nueva sobre una --salida sin estado.json nunca arranca un partido nuevo en
    silencio cuando el simulador ya tiene órdenes: sale con 5, explica, no crea estado ni auditoría y no manda nada
    al simulador. Con el simulador sin órdenes (el arranque del partido) sigue arrancando."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="r3b-reanudar-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_salida_equivocada_con_partido_en_curso(self):
        from tests.test_operacion import SimConOrdenes, correr_servir
        for nombre, preparar in (("inexistente", lambda p: None), ("vacia", lambda p: p.mkdir())):
            with self.subTest(salida=nombre):
                salida = self.tmp / ("salida-" + nombre)
                preparar(salida)
                srv, url = _sim_http_con_posts(SimConOrdenes())
                try:
                    codigo, texto = correr_servir(salida, simulador=url)
                finally:
                    srv.shutdown()
                    srv.server_close()
                self.assertEqual(codigo, m.EXIT_NUEVA, texto)
                self.assertIn("estado.json", texto)
                self.assertIn("--nueva --descartar-anteriores", texto)
                self.assertFalse((salida / "estado.json").exists())
                self.assertFalse((salida / "auditoria.jsonl").exists())
                self.assertEqual(srv.posts, [])

    def test_revisar_sin_estado(self):
        from tests.test_operacion import SimConOrdenes
        textos = []
        self.assertEqual(m.revisar_sin_estado(self.tmp, SimuladorFalso(), textos.append), 0)
        self.assertEqual(textos, [])
        self.assertEqual(m.revisar_sin_estado(self.tmp, SimConOrdenes(), textos.append), m.EXIT_NUEVA)


class TestHuellaUnica(unittest.TestCase):
    """Contrato C20 (paquete-2): una sola huella por partido. Exportar dos veces la misma salida, sin entradas nuevas
    en la auditoría, da la misma huella; con la plataforma viva y el partido cerrado, `exportar` entrega una copia
    exacta del paquete de la plataforma, con la huella que muestran /transparencia y la sala (hitos.paquete)."""

    def test_exportar_dos_veces_da_la_misma_huella(self):
        from marca.exportar import MANIFIESTO, exportar, huella_paquete
        from tests.test_motor_verificar import correr_partido
        from tests.test_paquete import cerrar
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            motor, _, _, _ = correr_partido(base)
            try:
                with motor.candado:
                    motor.guardar()
                exportar(motor.salida, base / "uno")
                time.sleep(1.1)
                exportar(motor.salida, base / "dos")
                self.assertEqual(huella_paquete(base / "uno"), huella_paquete(base / "dos"))
                self.assertNotIn("generado_utc", json.loads((base / "uno" / MANIFIESTO).read_text(encoding="utf-8")))
            finally:
                cerrar(motor)

    def test_la_huella_entregada_es_la_publicada(self):
        from marca.__main__ import escribir_info_plataforma, exportar_paquete
        from marca.exportar import huella_paquete
        from marca.verificar import verificar
        from tests.test_motor_verificar import correr_partido
        from tests.test_paquete import cerrar
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            motor, _, _, _ = correr_partido(base)
            salida = motor.salida
            self.assertTrue(motor.e["hitos"].get("exportado"), "el partido falso tiene que haber cerrado")
            servidor = api.servir(motor, "127.0.0.1", 0)
            arrancar(servidor)
            try:
                escribir_info_plataforma(salida, "127.0.0.1", servidor.server_address[1], motor.instancia)
                resultado, textos = {}, []
                from marca import exportar as exportar_mod
                t = threading.Thread(target=lambda: resultado.setdefault(
                    "rc", exportar_paquete(salida, base / "partido-final", espera_s=3, imprimir=textos.append)))
                with mock.patch.object(exportar_mod, "copiar_paquete", wraps=exportar_mod.copiar_paquete) as copia:
                    t.start()
                    while t.is_alive():  # la plataforma sigue su ciclo mientras se exporta
                        motor.paso()
                        time.sleep(0.05)
                # Se entrega el paquete de la plataforma copiado tal cual, no uno rearmado por el comando.
                self.assertEqual([Path(c.args[0]) for c in copia.call_args_list], [salida / "entrega"])
                self.assertEqual(resultado["rc"], 0, textos)
                with motor.candado:
                    publicada = (motor.e["hitos"].get("paquete") or {}).get("huella")
                self.assertEqual(huella_paquete(base / "partido-final"), publicada, textos)
                self.assertEqual(huella_paquete(base / "partido-final"), huella_paquete(salida / "entrega"))
                self.assertIn(f"Huella del paquete: {publicada}", textos)
                self.assertEqual(verificar(base / "partido-final", huella_publicada=publicada).fallas, 0)
            finally:
                parar(servidor)
                cerrar(motor)

    def test_copiar_paquete_es_exacto_y_no_copia_uno_roto(self):
        from marca.exportar import ErrorDestino, MANIFIESTO, copiar_paquete, escribir_manifiesto, huella_paquete
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            origen = base / "entrega"
            (origen / "sub").mkdir(parents=True)
            (origen / "a.txt").write_text("uno", encoding="utf-8")
            (origen / "sub" / "b.json").write_text("{}", encoding="utf-8")
            h = escribir_manifiesto(origen)
            self.assertEqual(copiar_paquete(origen, base / "final"), base / "final")
            self.assertEqual(huella_paquete(base / "final"), h)
            self.assertEqual((base / "final" / "sub" / "b.json").read_text(encoding="utf-8"), "{}")
            (origen / "a.txt").write_text("otro", encoding="utf-8")  # ya no coincide con su manifiesto
            with self.assertRaises(OSError):
                copiar_paquete(origen, base / "final", intentos=1)
            self.assertEqual(huella_paquete(base / "final"), h)  # el destino anterior quedó intacto
            (base / "nada").mkdir()
            with self.assertRaises(ErrorDestino):
                copiar_paquete(base / "nada", base / "otro")
            self.assertFalse((base / "otro" / MANIFIESTO).exists())


class TestManipulacionDespuesDeLaFoto(unittest.TestCase):
    """Contrato paquete-3 / revisión del desvío de la tanda A: lo anotado después de la foto de los proveedores es
    nota solo mientras el estado exportado puede no tenerlo. Si después hay una `exportacion` del cierre (la
    plataforma guarda el estado en la misma pasada), sacar una orden posterior a la foto da ✗. Sin esa entrada, la
    misma manipulación queda como nota sin fuentes, pero el registro oficial y la huella publicada la detectan."""

    @classmethod
    def setUpClass(cls):
        from marca.exportar import exportar, huella_paquete
        from tests.test_integridad_ronda3 import partido_con_foto_temprana
        cls.dir = tempfile.TemporaryDirectory()
        cls.base = Path(cls.dir.name)
        cls.motor, cls.sim, _, cls.corte = partido_con_foto_temprana(cls.base)
        with cls.motor.candado:
            cls.motor.guardar()
        cls.en_curso = exportar(cls.motor.salida, cls.base / "en-curso")     # sin exportacion: partido en curso
        cls.huella_en_curso = huella_paquete(cls.en_curso)
        cls.cierre = cls.motor.exportar_entrega()                           # con la exportacion del cierre
        aud = [json.loads(x) for x in (cls.cierre / "auditoria.jsonl").read_text(encoding="utf-8").splitlines()]
        cls.tardia = sorted({x["datos"]["orden_id"] for x in aud
                             if x["tipo"] == "orden_enviada" and x["n"] > cls.corte})[0]
        cls.registro = cls.base / "registro.jsonl"
        cls.registro.write_text("".join(json.dumps(r) + "\n" for r in cls.sim.registro), encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        from tests.test_paquete import cerrar
        cerrar(cls.motor)
        cls.dir.cleanup()

    def sin_la_tardia(self, origen):
        """El falsificador prolijo: saca la orden y recalcula cobertura y tiempos con las funciones del exportador."""
        from marca import evidencia, exportar as ex
        from marca.auditoria import leer_entradas
        from tests.test_integridad_ronda3 import regenerar_md
        e = Path(tempfile.mkdtemp(dir=self.dir.name)) / "e"
        shutil.copytree(origen, e)
        resumen = json.loads((e / "resumen.json").read_text(encoding="utf-8"))
        provs = resumen["proveedores"]
        fin = float(resumen["partido"]["fin_min"])
        ahora = float(resumen.get("minuto") or fin)
        archivos = sorted((e / "expedientes").glob("*.json"))
        exps = [json.loads(a.read_text(encoding="utf-8")) for a in archivos]
        for exp in exps:
            for u in exp["ubicaciones"]:
                u["ordenes"] = [o for o in u["ordenes"] if o["orden_id"] != self.tardia]
        todas = [o for x in exps for u in x["ubicaciones"] for o in u["ordenes"]] + resumen["ordenes_sin_ubicacion"]
        for exp in exps:
            for u in exp["ubicaciones"]:
                desde, hasta = evidencia.ventana(exp["ubicaciones"], u, ahora, fin)
                u["cobertura"] = evidencia.cobertura(desde, hasta, u["ip"], u["host"], todas, provs)
                u["tiempos"] = ex.tiempos_ubicacion(u, provs)
        for arch, exp in zip(archivos, exps):
            arch.write_text(json.dumps(exp, ensure_ascii=False, indent=1), encoding="utf-8")
        exps.sort(key=lambda x: (x.get("num") or 0, str(x.get("id"))))
        resumen["tiempos"] = ex.armar_tiempos(exps, ex.quien_firmo(leer_entradas(e / "auditoria.jsonl")))
        (e / "resumen.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=1), encoding="utf-8")
        regenerar_md(e)  # también rehace el manifiesto
        return e

    def malas(self, inf):
        return [x for x in inf.lineas if x.startswith("✗")]

    def test_los_dos_paquetes_sin_tocar_verifican(self):
        from marca.verificar import verificar
        for paquete in (self.en_curso, self.cierre):
            self.assertEqual(self.malas(verificar(paquete, self.registro, self.base / "jueces.json")), [])

    def test_despues_del_cierre_sacar_una_orden_posterior_a_la_foto_da_cruz(self):
        from marca.verificar import verificar
        m = self.malas(verificar(self.sin_la_tardia(self.cierre)))
        self.assertTrue(any(self.tardia in x and "no está en ningún expediente exportado" in x for x in m), m)

    def test_en_curso_la_misma_manipulacion_la_detectan_el_registro_y_la_huella(self):
        from marca.verificar import verificar
        e = self.sin_la_tardia(self.en_curso)
        inf = verificar(e)
        self.assertEqual(self.malas(inf), [])  # sin fuentes: solo nota (el partido siguió después de exportar)
        self.assertTrue(any(self.tardia in x for x in inf.lineas if x.startswith("·")), inf.lineas)
        self.assertNotEqual(self.malas(verificar(e, self.registro, self.base / "jueces.json")), [])
        self.assertNotEqual(self.malas(verificar(e, huella_publicada=self.huella_en_curso)), [])


class TestCapturaBase64ConSaltos(unittest.TestCase):
    """Contrato c1-integridad-m1: una captura en base64 cortada en renglones (base64 «de mail») la acepta el motor y
    también el verificador: la exportación sin tocar verifica. Un carácter fuera del alfabeto sigue siendo ✗."""

    def armar(self, base, transformar):
        from marca.exportar import exportar
        from tests.test_robustez import motor_con
        motor, sim, _ = motor_con(base)
        det = deteccion("D-1", 1.0, *PIRATA)
        crudo = det["captura"]["contenido_b64"]
        det["captura"]["contenido_b64"] = transformar(crudo)
        sim.lista_detecciones = [det]
        sim.avanzar(1.2)
        motor._t_estado = float("-inf")
        motor.paso()
        with motor.candado:
            motor.guardar()
        paquete = exportar(motor.salida, base / "paquete")
        cerrar_motor(motor)
        return paquete

    def test_saltos_de_linea_verifican(self):
        from marca.verificar import verificar
        with tempfile.TemporaryDirectory() as d:
            paquete = self.armar(Path(d), lambda b: "\n".join(b[i:i + 76] for i in range(0, len(b), 76)) + "\n")
            exp = json.loads(sorted((paquete / "expedientes").glob("*.json"))[0].read_text(encoding="utf-8"))
            self.assertIsNotNone(exp["ubicaciones"][0]["sellado"]["captura"]["sha256"])
            self.assertEqual([x for x in verificar(paquete).lineas if x.startswith("✗")], [])

    def test_un_caracter_ajeno_sigue_dando_cruz(self):
        from marca.exportar import escribir_manifiesto
        from marca.verificar import verificar
        with tempfile.TemporaryDirectory() as d:
            paquete = self.armar(Path(d), lambda b: b)
            arch = sorted((paquete / "expedientes").glob("*.json"))[0]
            exp = json.loads(arch.read_text(encoding="utf-8"))
            cap = exp["ubicaciones"][0]["sellado"]["deteccion"]["captura"]
            cap["contenido_b64"] = cap["contenido_b64"][:10] + "*" + cap["contenido_b64"][10:]
            arch.write_text(json.dumps(exp, ensure_ascii=False, indent=1), encoding="utf-8")
            escribir_manifiesto(paquete)
            m = [x for x in verificar(paquete).lineas if x.startswith("✗")]
            self.assertTrue(any("sellado.deteccion.captura no coincide" in x for x in m), m)


class TestRegistroOficialConRechazadas(unittest.TestCase):
    """Contrato (c1-pruebas-y-operacion-7, M8): si el registro oficial del simulador tiene una orden_rechazada (p. ej. un
    409 por reenviar un orden_id), `verificar` con ese registro da ✗ y la nombra. Sin rechazadas, da ✓."""

    def test_una_rechazada_da_cruz(self):
        from marca.verificar import verificar
        with tempfile.TemporaryDirectory() as d:
            paquete = TestCapturaBase64ConSaltos().armar(Path(d), lambda b: b)
            limpio = Path(d) / "registro_limpio.jsonl"
            limpio.write_text("", encoding="utf-8")
            con = Path(d) / "registro_con_rechazo.jsonl"
            con.write_text(json.dumps({"evento": "orden_rechazada", "orden_id": "ord-X-U1-1", "motivo": "duplicada"})
                           + "\n", encoding="utf-8")
            bien = verificar(paquete, registro=limpio).lineas
            self.assertTrue(any(x.startswith("✓") and "ninguna orden rechazada" in x for x in bien), bien)
            mal = [x for x in verificar(paquete, registro=con).lineas if x.startswith("✗")]
            self.assertTrue(any("1 órdenes rechazadas" in x and "ord-X-U1-1 (duplicada)" in x for x in mal), mal)


class TestLeemeYActa(unittest.TestCase):
    """Contratos paquete-4 y paquete-5.
    - Todo .md del paquete, LEEME.md incluido, es el que genera el código: uno editado da ✗ aunque se rehaga el
      manifiesto (un LEEME que dice «el registro no hace falta» no puede verificar en verde).
    - El acta que lee el jurado no trae los códigos internos de la clase del descarte."""

    def test_leeme_editado_da_cruz(self):
        from marca.exportar import escribir_manifiesto
        from marca.verificar import verificar
        with tempfile.TemporaryDirectory() as d:
            paquete = TestCapturaBase64ConSaltos().armar(Path(d), lambda b: b)
            self.assertEqual([x for x in verificar(paquete).lineas if x.startswith("✗")], [])
            leeme = paquete / "LEEME.md"
            leeme.write_text(leeme.read_text(encoding="utf-8").replace(
                "2. Con el registro oficial", "2. El registro oficial del simulador no hace falta. Con el registro"),
                encoding="utf-8")
            escribir_manifiesto(paquete)
            m = [x for x in verificar(paquete).lineas if x.startswith("✗")]
            self.assertTrue(any("LEEME.md" in x for x in m), m)

    def test_el_acta_no_trae_codigos_internos(self):
        from marca.exportar import acta_md
        resumen = {"partido": {}, "minuto": 10, "ordenes": [], "descartes": [
            {"host": "rt.otra.test", "clase": "otra_senal", "veces": 2, "motivo": "otra señal", "minuto": 1},
            {"host": "vod.sin.test", "clase": "sin_marca", "veces": 2, "motivo": "sin marca", "minuto": 2}]}
        acta = acta_md(resumen, [], [])
        self.assertNotIn("otra_senal", acta)
        self.assertNotIn("sin_marca", acta)
        self.assertIn("rt.otra.test (otra señal, 2 detecciones)", acta)
        self.assertIn("vod.sin.test (sin marca de agua, 2 detecciones)", acta)


class TestCaidaEntreAuditarYGuardar(unittest.TestCase):
    """Contrato robustez-3: una caída entre anotar en la auditoría (fsync por entrada) y guardar estado.json deja,
    al reanudar, una exportación que verifica: la ubicación vuelta a armar vale; la primera queda como nota que nombra
    la entrada. Simula el kill -9 restaurando el estado.json de antes del paso y conservando la auditoría."""

    def test_reanudar_tras_el_hueco_verifica(self):
        from marca.auditoria import leer_entradas
        from marca.exportar import exportar
        from marca.motor import Motor
        from marca.usuarios import Usuarios
        from marca.verificar import verificar
        from tests.simulador_falso import SimuladorFalso
        from tests.test_motor_verificar import CONFIG
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            (base / "jueces.json").write_text(json.dumps(CONFIG), encoding="utf-8")
            sim = SimuladorFalso()
            m1 = Motor("http://falso", base / "salida", Usuarios(base / "jueces.json"), cliente=sim, tick=0.01,
                       registro=lambda t: None)
            m1.arrancar(nueva=True, hilos=False)
            ruta = base / "salida" / "estado.json"
            antes = ruta.read_bytes()
            sim.avanzar(1.2)
            m1.paso()
            ruta.write_bytes(antes)  # el «kill -9»: el estado en disco es el de antes del paso
            cerrar_motor(m1)
            m2 = Motor("http://falso", base / "salida", Usuarios(base / "jueces.json"), cliente=sim, tick=0.01,
                       registro=lambda t: None)
            m2.arrancar(nueva=False, hilos=False)
            m2.paso()
            cerrar_motor(m2)
            aud = leer_entradas(base / "salida" / "auditoria.jsonl")
            armadas = [e for e in aud if e["tipo"] == "ubicacion_armada"]
            self.assertEqual(len(armadas), 2, "el escenario tiene que rearmar la misma ubicación")
            self.assertNotEqual(armadas[0]["datos"]["huella"], armadas[1]["datos"]["huella"])
            inf = verificar(exportar(base / "salida", base / "paquete"))
            self.assertEqual([x for x in inf.lineas if x.startswith("✗")], [])
            self.assertTrue(any(f"entrada {armadas[0]['n']}:" in x and "volvió a armar" in x for x in inf.lineas),
                            inf.lineas)
            # La excusa es angosta: con el mismo hueco, un sellado reescrito (huella recalculada) sigue dando ✗.
            from marca.canon import huella
            from marca.exportar import escribir_manifiesto
            paquete = base / "paquete"
            arch = sorted((paquete / "expedientes").glob("*.json"))[0]
            x = json.loads(arch.read_text(encoding="utf-8"))
            u = x["ubicaciones"][0]
            u["sellado"]["colateral"]["motivo"] = "nada que ver"
            u["huella"] = huella(u["sellado"])
            u["ordenes"], u["decision"] = [], None
            arch.write_text(json.dumps(x, ensure_ascii=False, indent=1), encoding="utf-8")
            escribir_manifiesto(paquete)
            malas = [y for y in verificar(paquete).lineas if y.startswith("✗")]
            self.assertTrue(any("no es la del sellado exportado" in y for y in malas), malas)


if __name__ == "__main__":
    unittest.main()
