"""Contratos del paquete exportado, de `exportar` con la plataforma viva o caída, de la API y de la ampliación.

- MANIFIESTO.json: cualquier archivo cambiado, faltante o sobrante después de exportar se informa con su nombre.
- `exportar` con la plataforma respondiendo nunca escribe la auditoría (un solo escritor); caída, la escribe él.
- Un POST con cuerpo no leído cierra la conexión: los bytes no se toman como un pedido nuevo.
- La ampliación dinámica la anota el sistema, bajo una orden anterior del mismo expediente; un registro
  reescrito que apunte a otra entrada habilitante no verifica.
"""
import json
import shutil
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

from marca.__main__ import escribir_info_plataforma, exportar_paquete, plataforma_viva
from marca.api import servir
from marca.auditoria import hash_entrada, leer_entradas, verificar_cadena
from marca.canon import CEROS
from marca.exportar import escribir_manifiesto
from marca.verificar import verificar

from tests.test_motor_verificar import correr_partido


def cerrar(motor):
    motor.despacho._pool.shutdown(wait=False)
    if motor.auditoria:
        motor.auditoria.cerrar()


class TestManifiestoYAmpliacion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        cls.base = Path(cls.dir.name)
        cls.motor, cls.sim, cls.entrega, cls.cfg = correr_partido(cls.base)

    @classmethod
    def tearDownClass(cls):
        cerrar(cls.motor)
        cls.dir.cleanup()

    def copia(self):
        destino = Path(tempfile.mkdtemp(dir=self.dir.name))
        shutil.copytree(self.entrega, destino / "e")
        return destino / "e"

    def malas(self, carpeta, cfg=None):
        inf = verificar(carpeta, None, cfg)
        return [x for x in inf.lineas if x.startswith("✗")], inf

    def test_paquete_sano_tiene_huella(self):
        malas, inf = self.malas(self.entrega, self.cfg)
        self.assertEqual(malas, [])
        self.assertRegex(inf.huella_paquete or "", r"^[0-9a-f]{64}$")
        self.assertTrue(any("MANIFIESTO" in x for x in inf.lineas if x.startswith("✓")))

    def test_cambio_fuera_del_sellado(self):
        e = self.copia()
        arch = sorted((e / "expedientes").glob("*.json"))[0]
        exp = json.loads(arch.read_text(encoding="utf-8"))
        exp["titulo"] = exp["titulo"] + "x"
        arch.write_text(json.dumps(exp, ensure_ascii=False, indent=1), encoding="utf-8")
        malas, _ = self.malas(e)
        self.assertTrue(any(f"expedientes/{arch.name}" in x and "cambió" in x for x in malas), malas)

    def test_cambio_en_un_md_y_en_el_acta(self):
        e = self.copia()
        md = sorted((e / "expedientes").glob("*.md"))[0]
        md.write_text(md.read_text(encoding="utf-8").replace("Expediente", "Expedienta", 1), encoding="utf-8")
        acta = e / "acta-del-partido.md"
        acta.write_text(acta.read_text(encoding="utf-8") + " ", encoding="utf-8")
        malas, _ = self.malas(e)
        self.assertTrue(any(f"expedientes/{md.name}" in x for x in malas), malas)
        self.assertTrue(any("acta-del-partido.md" in x for x in malas), malas)

    def test_cambio_dentro_del_sellado_da_ademas_la_huella(self):
        e = self.copia()
        arch = sorted((e / "expedientes").glob("*.json"))[0]
        exp = json.loads(arch.read_text(encoding="utf-8"))
        exp["ubicaciones"][0]["sellado"]["servidor"]["ip"] = "203.0.113.99"
        arch.write_text(json.dumps(exp), encoding="utf-8")
        malas, _ = self.malas(e)
        self.assertTrue(any(arch.name in x and "cambió" in x for x in malas), malas)
        self.assertTrue(any("huella" in x for x in malas), malas)

    def test_faltante_y_sobrante(self):
        e = self.copia()
        (e / "resumen.json").unlink()
        (e / "nota-agregada.txt").write_text("hola", encoding="utf-8")
        (e / ".DS_Store").write_bytes(b"\0")  # lo crea el Finder: no cuenta
        malas, _ = self.malas(e)
        self.assertTrue(any("resumen.json" in x and "falta" in x for x in malas), malas)
        self.assertTrue(any("nota-agregada.txt" in x and "sobra" in x for x in malas), malas)
        self.assertFalse(any(".DS_Store" in x for x in malas), malas)

    def test_sin_manifiesto_es_nota(self):
        e = self.copia()
        (e / "MANIFIESTO.json").unlink()
        malas, inf = self.malas(e)
        self.assertEqual(malas, [])
        self.assertTrue(any("sin manifiesto" in x for x in inf.lineas))

    # --- ampliación dinámica transparente ---------------------------------------------------

    def test_ampliacion_la_anota_el_sistema_bajo_la_orden_del_juez(self):
        aud = leer_entradas(self.motor.salida / "auditoria.jsonl")
        amp = [e for e in aud if e["tipo"] == "ampliacion_dinamica"]
        self.assertEqual(len(amp), 1)
        d = amp[0]["datos"]
        self.assertEqual(amp[0]["actor"], "sistema")
        self.assertEqual(d["bajo_orden_dinamica_de"], "juez-a")
        self.assertNotIn("firma_decision", d)
        pir = self.motor.e["expedientes"][0]
        self.assertEqual(d["entrada_habilitante"], pir["ubicaciones"][0]["decision"]["entrada"])
        dec = pir["ubicaciones"][1]["decision"]
        self.assertEqual(dec["bajo_orden_de"]["juez_id"], "juez-a")
        # Sección 7 de la ronda 2b: la ampliación la hace el sistema bajo la orden de Dra. A; nunca se le atribuye
        # como firma en persona.
        self.assertTrue(dec["texto"].startswith("Ampliación automática"), dec["texto"])
        self.assertIn("Dra. A", dec["texto"])
        self.assertIn("No se firmó en persona", dec["texto"])
        with self.motor.candado:
            reg = self.motor.vista_registro()
            sala = self.motor.vista_sala()
            oid = next(o["orden_id"] for o in self.motor.e["ordenes"].values()
                       if o["exp"] == pir["id"] and o["n"] == 2)
            pub = self.motor.vista_orden_publica(oid)
        self.assertTrue(any(b["bajo_orden_de"] for b in reg["bloqueos"] if b["orden_id"] == oid))
        self.assertIn("Ampliación automática", pub["decision"]["texto"])
        self.assertTrue(any(u["decision"] and u["decision"].get("bajo_orden_de")
                            for x in sala["expedientes"] for u in x["ubicaciones"]))

    def test_registro_reescrito_con_otra_habilitante_no_verifica(self):
        e = self.copia()
        ruta = e / "auditoria.jsonl"
        entradas = leer_entradas(ruta)
        ultimo = entradas[-1]["n"]
        prev = CEROS
        for x in entradas:  # el falsificador recalcula toda la cadena y el manifiesto
            if x["tipo"] == "ampliacion_dinamica":
                x["datos"]["entrada_habilitante"] = ultimo
            x["prev"] = prev
            x["hash"] = hash_entrada(x)
            prev = x["hash"]
        ruta.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in entradas), encoding="utf-8")
        escribir_manifiesto(e)
        self.assertTrue(verificar_cadena(ruta)[0])
        malas, _ = self.malas(e, self.cfg)
        self.assertTrue(any("Ampliaciones automáticas que no cierran" in x and "no es anterior" in x for x in malas),
                        malas)


class TestExportarConPlataformaVivaYCaida(unittest.TestCase):
    def test_las_dos_ramas(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            motor, sim, _, _ = correr_partido(base)
            salida = motor.salida
            ruta_aud = salida / "auditoria.jsonl"
            # Las dos ramas que refrescan testigos son las del partido EN CURSO: sin el paquete del cierre. Con el
            # partido cerrado, exportar copia el paquete del cierre y no toca la auditoría (tests/test_r4_paquete.py).
            shutil.rmtree(salida / "entrega")
            servidor = servir(motor, "127.0.0.1", 0)
            hilo = threading.Thread(target=servidor.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
            hilo.start()
            try:
                escribir_info_plataforma(salida, "127.0.0.1", servidor.server_address[1], motor.instancia)
                self.assertTrue(plataforma_viva(salida))
                antes = sum(1 for x in leer_entradas(ruta_aud) if x["tipo"] == "testigos_guardados")
                textos = []
                resultado = {}
                t = threading.Thread(target=lambda: resultado.setdefault(
                    "rc", exportar_paquete(salida, base / "viva", espera_s=10, imprimir=textos.append)))
                t.start()
                while t.is_alive():  # la plataforma consume el pedido en su ciclo
                    motor.paso()
                    time.sleep(0.05)
                self.assertEqual(resultado["rc"], 0)
                self.assertFalse((salida / "pedir-testigos").exists())
                despues = [x for x in leer_entradas(ruta_aud) if x["tipo"] == "testigos_guardados"]
                self.assertEqual(len(despues), antes + 1)
                # Un solo escritor: la plataforma sigue anotando y la cadena verifica.
                with motor.candado:
                    motor.auditar("alerta", "sistema", datos={"texto": "sigue"})
                self.assertTrue(verificar_cadena(ruta_aud)[0])
                self.assertEqual(verificar(base / "viva").fallas, 0)
                self.assertTrue(any(x.startswith("Huella del paquete: ") for x in textos), textos)
            finally:
                servidor.shutdown()
                servidor.server_close()
                cerrar(motor)
            # Caída: plataforma.json viejo (el puerto ya no responde) → el comando escribe él mismo.
            self.assertFalse(plataforma_viva(salida))
            shutil.rmtree(salida / "entrega", ignore_errors=True)  # la plataforma cerrada la volvió a exportar
            textos = []
            self.assertEqual(exportar_paquete(salida, base / "caida", cliente=sim, imprimir=textos.append), 0)
            final = [x for x in leer_entradas(ruta_aud) if x["tipo"] == "testigos_guardados"]
            self.assertEqual(len(final), antes + 2)
            self.assertTrue(verificar_cadena(ruta_aud)[0])
            self.assertEqual(verificar(base / "caida").fallas, 0)
            self.assertTrue(any("no está corriendo" in x for x in textos), textos)


class TestApiCuerpoNoLeido(unittest.TestCase):
    def test_bytes_sin_leer_no_son_un_pedido_nuevo(self):
        with tempfile.TemporaryDirectory() as d:
            motor, _, _, _ = correr_partido(Path(d))
            servidor = servir(motor, "127.0.0.1", 0)
            hilo = threading.Thread(target=servidor.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
            hilo.start()
            try:
                contrabando = b"GET /api/salud HTTP/1.1\r\nHost: x\r\n\r\n"
                pedido = (b"POST /api/login HTTP/1.1\r\nHost: x\r\nContent-Type: text/plain\r\n"
                          b"Content-Length: " + str(len(contrabando)).encode() + b"\r\n\r\n" + contrabando)
                s = socket.create_connection(("127.0.0.1", servidor.server_address[1]), timeout=3)
                s.sendall(pedido)
                recibido = b""
                try:
                    while True:
                        trozo = s.recv(65536)
                        if not trozo:
                            break
                        recibido += trozo
                except socket.timeout:
                    pass
                s.close()
            finally:
                servidor.shutdown()
                servidor.server_close()
                cerrar(motor)
        self.assertEqual(recibido.count(b"HTTP/1.1 "), 1, recibido[:400])
        self.assertTrue(recibido.startswith(b"HTTP/1.1 422"), recibido[:100])
        self.assertNotIn(b'"instancia"', recibido)



# --- verificar: lo que mira el criterio «validez e integridad de la evidencia» -----------------------------

def recalcular_cadena(ruta, entradas):
    """Lo que haría un falsificador sin claves: reescribe la auditoría y recalcula prev y hash de toda la cadena."""
    prev = CEROS
    for i, x in enumerate(entradas, start=1):
        x["n"], x["prev"] = i, prev
        x["hash"] = hash_entrada(x)
        prev = x["hash"]
    ruta.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in entradas), encoding="utf-8")


def correr_main(*args, **kw):
    import contextlib
    import io
    from marca.verificar import main_verificar
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main_verificar(*args, **kw)
    return rc, buf.getvalue()


class TestVerificarIntegridad(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        cls.base = Path(cls.dir.name)
        cls.motor, cls.sim, cls.entrega, cls.cfg = correr_partido(cls.base)
        cls.registro = cls.base / "registro.jsonl"
        cls.registro.write_text("".join(json.dumps(r) + "\n" for r in cls.sim.registro), encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cerrar(cls.motor)
        cls.dir.cleanup()

    def copia(self):
        destino = Path(tempfile.mkdtemp(dir=self.dir.name))
        shutil.copytree(self.entrega, destino / "e")
        return destino / "e"

    def malas(self, carpeta, registro=None, cfg=None, **kw):
        inf = verificar(carpeta, registro, cfg, **kw)
        return [x for x in inf.lineas if x.startswith("✗")]

    def exp(self, e, i=0):
        arch = sorted((e / "expedientes").glob("*.json"))[i]
        return arch, json.loads(arch.read_text(encoding="utf-8"))

    def guardar(self, e, arch, exp):
        arch.write_text(json.dumps(exp, ensure_ascii=False, indent=1), encoding="utf-8")
        escribir_manifiesto(e)  # el falsificador regenera el manifiesto

    def test_control_sana_en_los_cuatro_modos(self):
        for reg in (None, self.registro):
            for cfg in (None, self.cfg):
                with self.subTest(registro=bool(reg), config=bool(cfg)):
                    self.assertEqual(self.malas(self.entrega, reg, cfg), [])
        inf = verificar(self.entrega, None, self.cfg)
        self.assertTrue(any("2 de 2 verificadas" in x for x in inf.lineas), inf.lineas)

    # 6a. Contrato: verificar nunca explota; cada archivo ilegible es un ✗ con su nombre y sigue.
    def test_json_mal_editado_es_un_tache_con_su_nombre(self):
        def sin_orden_id(e):
            arch, x = self.exp(e)
            del x["ubicaciones"][0]["ordenes"][0]["orden_id"]
            self.guardar(e, arch, x)
            return arch.name

        def orden_id_nulo(e):
            arch, x = self.exp(e)
            x["ubicaciones"][0]["ordenes"][0]["orden_id"] = None
            self.guardar(e, arch, x)
            return arch.name

        def expediente_lista(e):
            arch, _ = self.exp(e)
            arch.write_text("[1, 2]", encoding="utf-8")
            return arch.name

        def ubicaciones_texto(e):
            arch, x = self.exp(e)
            x["ubicaciones"] = "nada"
            self.guardar(e, arch, x)
            return arch.name

        def json_cortado(e):
            arch, _ = self.exp(e)
            arch.write_text(arch.read_text(encoding="utf-8")[:-40], encoding="utf-8")
            return arch.name

        def datos_nulos(e):
            ruta = e / "auditoria.jsonl"
            lineas = ruta.read_text(encoding="utf-8").splitlines()
            i = next(i for i, l in enumerate(lineas) if '"orden_enviada"' in l)
            x = json.loads(lineas[i])
            x["datos"] = None
            lineas[i] = json.dumps(x)
            ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8")
            return "auditoria.jsonl"

        def resumen_roto(e):
            (e / "resumen.json").write_text("{", encoding="utf-8")
            return "resumen.json"

        def testigos_rotos(e):
            (e / "testigos" / "proveedores.json").write_text("{", encoding="utf-8")
            return "testigos/proveedores.json"

        for romper in (sin_orden_id, orden_id_nulo, expediente_lista, ubicaciones_texto, json_cortado, datos_nulos,
                       resumen_roto, testigos_rotos):
            with self.subTest(caso=romper.__name__):
                e = self.copia()
                nombre = romper(e)
                rc, texto = correr_main(e, None, self.cfg)
                self.assertEqual(rc, 1, texto)
                self.assertNotIn("Traceback", texto)
                self.assertNotIn("error inesperado", texto)
                self.assertTrue(any(l.startswith("✗") and nombre in l for l in texto.splitlines()), texto)
                self.assertIn("✓ ", texto)  # siguió verificando lo demás

    def test_registro_con_la_ultima_linea_cortada(self):
        roto = self.base / "registro-roto.jsonl"
        roto.write_text(self.registro.read_text(encoding="utf-8") + '{"evento": "orden_rec', encoding="utf-8")
        rc, texto = correr_main(self.entrega, roto)
        self.assertEqual(rc, 1)
        self.assertIn("registro oficial: líneas que no son JSON válido", texto)
        self.assertIn("registro oficial: todas las órdenes enviadas figuran", texto)

    # 6b. Contrato: con --config toda decisión y levantamiento trae su firma válida; sin claves es un error.
    def test_config_sin_claves_es_error(self):
        sin = self.base / "sin-claves.json"
        sin.write_text(json.dumps({"turnos": []}), encoding="utf-8")
        malas = self.malas(self.entrega, None, sin)
        self.assertTrue(any("no tiene claves_firma_demo" in x for x in malas), malas)
        malas = self.malas(self.entrega, None, self.base / "no-existe.json")
        self.assertTrue(any("no-existe.json" in x for x in malas), malas)

    def test_decision_sin_firma_no_verifica(self):
        e = self.copia()
        ruta = e / "auditoria.jsonl"
        entradas = leer_entradas(ruta)
        for x in entradas:
            if x["tipo"] == "decision_juez":
                del x["datos"]["firma_decision"]
                break
        recalcular_cadena(ruta, entradas)
        malas = self.malas(e, None, self.cfg)
        self.assertTrue(any("decisión sin firma" in x for x in malas), malas)

    def test_firmas_obligatorias_por_entrada(self):
        from marca.verificar import Informe, verificar_firmas
        claves = {"juez-a": "clave-a"}
        entradas = [
            {"n": 1, "tipo": "decision_juez", "exp": "E", "datos": {"ubicacion": 1, "huella": "h", "aprobar": True,
                                                                     "alcance": "ubicacion", "juez_id": "juez-a"}},
            {"n": 2, "tipo": "orden_levantada", "datos": {"orden_id": "o1", "juez_id": "juez-a"}},
            {"n": 3, "tipo": "orden_levantada", "datos": {"orden_id": "o2", "anulada": True}},
            {"n": 4, "tipo": "decision_juez", "exp": "E", "datos": {"accion": "levantar_ubicacion", "ubicacion": 1}},
            {"n": 5, "tipo": "decision_juez", "exp": "E", "datos": {"ubicacion": 1, "huella": "h", "aprobar": True,
                                                                     "alcance": "ubicacion", "juez_id": "juez-x",
                                                                     "firma_decision": "f"}},
        ]
        inf = Informe()
        verificar_firmas(inf, entradas, claves)
        malas = [x for x in inf.lineas if x.startswith("✗")]
        self.assertEqual(len(malas), 3, malas)
        self.assertTrue(any("entrada 1" in x and "decisión sin firma" in x for x in malas))
        self.assertTrue(any("entrada 2" in x and "levantamiento sin firma" in x for x in malas))
        self.assertTrue(any("entrada 5" in x and "no hay clave" in x for x in malas))

    # 6c. Contrato: si la auditoría registra testigos, el archivo tiene que estar.
    def test_testigos_borrados_con_entrada_en_la_auditoria(self):
        e = self.copia()
        shutil.rmtree(e / "testigos")
        escribir_manifiesto(e)
        malas = self.malas(e)
        self.assertTrue(any("testigos/proveedores.json" in x and "testigos_guardados" in x for x in malas), malas)

    def test_sin_testigos_registrados_es_nota(self):
        e = self.copia()
        shutil.rmtree(e / "testigos")
        ruta = e / "auditoria.jsonl"
        recalcular_cadena(ruta, [x for x in leer_entradas(ruta) if x["tipo"] != "testigos_guardados"])
        escribir_manifiesto(e)
        inf = verificar(e)
        self.assertFalse(any(x.startswith("✗") and "estigos" in x for x in inf.lineas), inf.lineas)
        self.assertTrue(any("no disponible" in x for x in inf.lineas))

    # 6d. Contrato: el cruce va en los dos sentidos (auditoría, registro y testigos ⇄ exportación).
    def test_borrar_un_expediente(self):
        e = self.copia()
        arch, x = self.exp(e)
        arch.unlink()
        (e / "expedientes" / arch.name.replace(".json", ".md")).unlink()
        escribir_manifiesto(e)
        for reg in (None, self.registro):
            with self.subTest(registro=bool(reg)):
                malas = self.malas(e, reg, self.cfg)
                self.assertTrue(any(x["id"] in m and "no está exportado" in m for m in malas), malas)
                self.assertTrue(any("no está en ningún expediente exportado" in m for m in malas), malas)
        malas = self.malas(e, self.registro)
        self.assertTrue(any(m.startswith("✗ registro oficial") and "ningún expediente" in m for m in malas), malas)

    def test_borrar_la_ultima_ubicacion_o_una_orden(self):
        e = self.copia()
        arch, x = self.exp(e)
        x["ubicaciones"].pop()
        self.guardar(e, arch, x)
        malas = self.malas(e)
        self.assertTrue(any("ubicacion_armada" not in m and f"U2 de {x['id']} no está" in m for m in malas), malas)
        e = self.copia()
        arch, x = self.exp(e)
        quitada = x["ubicaciones"][0]["ordenes"].pop()
        self.guardar(e, arch, x)
        malas = self.malas(e)
        self.assertTrue(any(quitada["orden_id"] in m for m in malas), malas)

    def test_sellado_reescrito_con_la_huella_recalculada(self):
        from marca.canon import huella
        e = self.copia()
        arch, x = self.exp(e, 1)
        u = x["ubicaciones"][0]
        u["sellado"]["colateral"]["motivo"] = "nada que ver"
        u["huella"] = huella(u["sellado"])
        u["ordenes"], u["decision"] = [], None
        self.guardar(e, arch, x)
        malas = self.malas(e)
        self.assertTrue(any("no es la del sellado exportado" in m for m in malas), malas)

    # 6e. Contrato: una auditoría vacía o truncada no verifica; la cola la ancla la huella publicada.
    def test_auditoria_vacia(self):
        e = self.copia()
        (e / "auditoria.jsonl").write_text("", encoding="utf-8")
        escribir_manifiesto(e)
        malas = self.malas(e)
        self.assertTrue(any("auditoria.jsonl: está vacía" in m for m in malas), malas)
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "auditoria.jsonl").write_text("", encoding="utf-8")
            rc, texto = correr_main(d)
            self.assertEqual(rc, 1, texto)

    def test_cola_truncada(self):
        e = self.copia()
        ruta = e / "auditoria.jsonl"
        lineas = ruta.read_text(encoding="utf-8").splitlines(keepends=True)
        ruta.write_text("".join(lineas[:-3]), encoding="utf-8")
        escribir_manifiesto(e)
        malas = self.malas(e)
        self.assertTrue(any(m.startswith("✗ resumen.json") and "truncada" in m for m in malas), malas)
        self.assertTrue(any(m.startswith("✗ acta-del-partido.md") for m in malas), malas)

    def test_sin_entrada_inicio(self):
        e = self.copia()
        ruta = e / "auditoria.jsonl"
        recalcular_cadena(ruta, leer_entradas(ruta)[1:])
        malas = self.malas(e)
        self.assertTrue(any("no «inicio»" in m for m in malas), malas)

    def test_huella_publicada(self):
        inf = verificar(self.entrega)
        self.assertEqual(self.malas(self.entrega, huella_publicada=inf.huella_paquete), [])
        malas = self.malas(self.entrega, huella_publicada="0" * 64)
        self.assertTrue(any("distinta de la publicada" in m for m in malas), malas)
        rc, texto = correr_main(self.entrega)
        self.assertIn("Publicar esta huella", texto)

    # 6f. Contrato: lo que lee el jurado fuera del bloque sellado coincide con lo sellado y la auditoría.
    def test_campos_legibles(self):
        def ip(x):
            x["ubicaciones"][0]["ip"] = "198.51.100.77"
            return "campo ip"

        def host(x):
            x["ubicaciones"][0]["host"] = "inocente.example"
            return "campo host"

        def aprobada(x):
            x["ubicaciones"][0]["decision"]["aprobada"] = False
            return "decision.aprobada"

        def juez(x):
            x["ubicaciones"][0]["decision"]["juez_id"] = "juez-b"
            return "decision.juez_id"

        def objetivo(x):
            x["ubicaciones"][0]["ordenes"][0]["objetivo"] = "198.51.100.200"
            return "campo objetivo"

        def vence(x):
            x["ubicaciones"][0]["ordenes"][0]["vence_min"] = 999
            return "campo vence_min"

        for cambiar in (ip, host, aprobada, juez, objetivo, vence):
            with self.subTest(campo=cambiar.__name__):
                e = self.copia()
                shutil.rmtree(e / "testigos")  # sin testigos ni registro: solo la auditoría propia
                arch, x = self.exp(e)
                texto = cambiar(x)
                self.guardar(e, arch, x)
                malas = self.malas(e)
                self.assertTrue(any(texto in m and arch.name in m for m in malas), malas)

    # 6g. Menores.
    def test_captura_de_una_redeteccion(self):
        e = self.copia()
        arch, x = self.exp(e)
        u = next(u for u in x["ubicaciones"] if len(u["detecciones"]) > 1)
        from marca.canon import nombre_captura
        cap = e / "capturas" / nombre_captura(u["detecciones"][1])
        cap.write_bytes(cap.read_bytes()[:-1] + b"\x00")
        escribir_manifiesto(e)
        malas = self.malas(e)
        self.assertTrue(any(cap.name in m and "deteccion_recibida" in m for m in malas), malas)

    def test_clave_duplicada(self):
        e = self.copia()
        arch, _ = self.exp(e)
        texto = arch.read_text(encoding="utf-8")
        arch.write_text(texto.replace('"titulo"', '"titulo": "falso", "titulo"', 1), encoding="utf-8")
        escribir_manifiesto(e)
        malas = self.malas(e)
        self.assertTrue(any(arch.name in m and "clave duplicada 'titulo'" in m for m in malas), malas)

    def test_auditoria_recalculada_entera_lo_dice_una_vez(self):
        e = self.copia()
        ruta = e / "auditoria.jsonl"
        entradas = leer_entradas(ruta)
        dec = next(x for x in entradas if x["tipo"] == "decision_juez")
        dec["min"] = dec["min"] + 1
        recalcular_cadena(ruta, entradas)
        escribir_manifiesto(e)
        malas = self.malas(e)
        self.assertTrue(any(f"la entrada {dec['n']} ya no da el sello" in m for m in malas), malas)

    def test_detecion_sin_captura_es_nota(self):
        e = self.copia()
        from marca.canon import huella
        arch, x = self.exp(e, 1)
        u = x["ubicaciones"][0]
        u["sellado"]["captura"]["sha256"] = None
        u["sellado"]["deteccion"]["captura"] = None
        u["huella"] = huella(u["sellado"])
        self.guardar(e, arch, x)
        inf = verificar(e)
        self.assertTrue(any("se selló sin captura" in l for l in inf.lineas), inf.lineas)
        self.assertFalse(any("falta capturas" in l or "sellado.deteccion.captura no coincide" in l
                             for l in inf.lineas if l.startswith("✗")), inf.lineas)



# --- ronda 2b: orden marco, amp-, textos regenerados, tiempos ------------------------------------------------


def contenido_om(juez="juez-a", nombre="Dra. A", seguimiento=True):
    from marca.marco import CONDICIONES_SEGUIMIENTO
    return {"version": 1, "partido": {"id": "p1", "nombre": "Partido de prueba", "titular": "Liga", "fin_min": 90},
            "juez": {"juez_id": juez, "nombre": nombre, "juzgado_id": "jg-1", "juzgado": "Juzgado 1"},
            "turno": {"desde_min": 0, "hasta_min": 45}, "seguimiento": seguimiento,
            "lineas": ["Partido: Partido de prueba. Titular de los derechos: Liga.", "Segunda línea."],
            "condiciones_seguimiento": list(CONDICIONES_SEGUIMIENTO)}


def entrada_om(n, juez="juez-a", seguimiento=True, clave="clave-a", oid="OM-01", contenido=None):
    from marca import sello
    from marca.canon import huella
    c = contenido or contenido_om(juez, seguimiento=seguimiento)
    h = huella(c)
    return {"n": n, "min": float(n), "utc": "2026-11-13T21:00:00Z", "tipo": "orden_marco", "actor": f"juez:{juez}",
            "exp": None, "datos": {"id": oid, "juez_id": juez, "juzgado_id": "jg-1", "huella": h,
                                   "seguimiento": seguimiento, "contenido": c,
                                   "firma": sello.firma_marco(clave, "p1", h, juez, seguimiento), "reemplaza": None}}


def entrada_amp(n, om, exp="EXP-1", ubicacion=2, juez="juez-a"):
    return {"n": n, "min": float(n), "tipo": "ampliacion_dinamica", "actor": "sistema", "exp": exp,
            "datos": {"ubicacion": ubicacion, "bajo_orden_dinamica_de": juez,
                      "orden_marco": {"entrada": om["n"], "huella": om["datos"]["huella"]} if om else None}}


class TestOrdenMarco(unittest.TestCase):
    """Contrato (sección 1): cada OM con su huella y su firma; cada ampliación bajo una OM anterior, del juez que la
    respalda, con seguimiento y todavía vigente; lo exportado en orden-marco/ es lo de la auditoría."""

    def correr(self, orden, claves=None, exportar_om=True):
        from marca.exportar import armar_marcos
        from marca.verificar import Informe, verificar_marcos
        with tempfile.TemporaryDirectory() as d:
            carpeta = Path(d)
            if exportar_om:
                marcos = armar_marcos(orden, [], {"inicio_iso": None})
                if marcos:
                    (carpeta / "orden-marco").mkdir()
                for m in marcos:
                    (carpeta / "orden-marco" / f"{m['id']}.json").write_text(json.dumps(m), encoding="utf-8")
            inf = Informe()
            verificar_marcos(inf, carpeta, orden, {e["n"]: e for e in orden}, claves)
            return inf

    def malas(self, *a, **kw):
        return [x for x in self.correr(*a, **kw).lineas if x.startswith("✗")]

    def test_sana(self):
        om = entrada_om(2)
        inf = self.correr([om, entrada_amp(3, om)], {"juez-a": "clave-a"})
        self.assertEqual([x for x in inf.lineas if x.startswith("✗")], [])
        self.assertTrue(any("1 con su huella y su firma; 1 ampliaciones" in x for x in inf.lineas), inf.lineas)

    def test_sin_om_y_sin_ampliaciones_es_nota(self):
        inf = self.correr([])
        self.assertEqual(inf.fallas, 0)
        self.assertTrue(any("Sin orden marco" in x for x in inf.lineas))

    def test_casos_que_no_verifican(self):
        om = entrada_om(2)
        otro = entrada_om(2, juez="juez-b", clave="clave-b")
        sin_seg = entrada_om(2, seguimiento=False)
        texto_cambiado = entrada_om(2)
        texto_cambiado["datos"]["contenido"]["lineas"][1] = "Otra cosa."
        reemplazo = entrada_om(3, seguimiento=False, oid="OM-02")
        casos = {
            "ampliación sin orden marco": [entrada_amp(3, None)],
            "no existe o no es anterior": [entrada_amp(1, om), om],
            "es de 'juez-b'": [otro, entrada_amp(3, otro)],
            "no autoriza el seguimiento": [sin_seg, entrada_amp(3, sin_seg)],
            "ya estaba reemplazada": [om, reemplazo, entrada_amp(4, om)],
            "la huella no es la de su contenido": [texto_cambiado],
        }
        for texto, orden in casos.items():
            with self.subTest(caso=texto):
                malas = self.malas(orden)
                self.assertTrue(any(texto in m for m in malas), malas)

    def test_firma(self):
        om = entrada_om(2)
        self.assertEqual(self.malas([om], None), [])  # sin --config no se miran las firmas
        mala = entrada_om(2, clave="otra-clave")
        self.assertTrue(any("no verifica" in m for m in self.malas([mala], {"juez-a": "clave-a"})))
        sin = entrada_om(2)
        sin["datos"]["firma"] = None
        self.assertTrue(any("orden marco sin firma" in m for m in self.malas([sin], {"juez-a": "clave-a"})))
        self.assertTrue(any("no hay clave" in m for m in self.malas([om], {"juez-b": "clave-b"})))

    def test_exportado_en_los_dos_sentidos(self):
        om = entrada_om(2)
        malas = self.malas([om], exportar_om=False)
        self.assertTrue(any("falta orden-marco/OM-01.json" in m for m in malas), malas)
        from marca.exportar import armar_marcos
        from marca.verificar import Informe, verificar_marcos
        with tempfile.TemporaryDirectory() as d:
            carpeta = Path(d) / "orden-marco"
            carpeta.mkdir()
            m = armar_marcos([om], [], {})[0]
            m["seguimiento"] = False
            (carpeta / "OM-01.json").write_text(json.dumps(m), encoding="utf-8")
            (carpeta / "OM-09.json").write_text(json.dumps(m), encoding="utf-8")
            inf = Informe()
            verificar_marcos(inf, Path(d), [om], {2: om}, None)
            malas = [x for x in inf.lineas if x.startswith("✗")]
        self.assertTrue(any("OM-01.json: campo seguimiento" in x for x in malas), malas)
        self.assertTrue(any("OM-09.json: no hay entrada orden_marco" in x for x in malas), malas)


class TestPrefijosDeOrden(unittest.TestCase):
    """Contrato (sección 3): amp- ⇔ la decisión de la ubicación es una ampliación automática."""

    def test_amp_solo_en_ampliaciones(self):
        from marca.verificar import Informe, verificar_prefijos
        ordenes = [("EXP-1", "amp-0001-u2-p-01-aa", "decision"),          # bien
                   ("EXP-1", "amp-0001-u1-p-01-bb", "decision"),          # u1 la firmó un juez: mal
                   ("EXP-1", "ord-0001-u2-p-02-cc", "decision"),          # u2 es ampliación: mal
                   ("EXP-1", "ord-0001-u2-p-03-dd", "reemplazo_reclamo"),  # el reemplazo lo firma el juez: bien
                   ("EXP-1", "ord-0001-u1-p-01-ee", "decision")]          # bien
        inf = Informe()
        verificar_prefijos(inf, [("auditoría", ordenes), ("testigos", ordenes[:2])], {("EXP-1", 2)})
        malas = [x for x in inf.lineas if x.startswith("✗")]
        self.assertEqual(len(malas), 2, malas)
        self.assertTrue(any("amp-0001-u1-p-01-bb" in m and "auditoría, testigos" in m for m in malas))
        self.assertTrue(any("ord-0001-u2-p-02-cc" in m for m in malas))

    def test_orden_ajena_no_se_juzga_por_su_prefijo(self):
        """Una orden del registro o de los testigos que no está en nuestra auditoría (expediente desconocido) ya
        sale como «ajena»: no se puede decir si su ubicación fue ampliación, y no se inventa «la firmó un juez»."""
        from marca.verificar import Informe, verificar_prefijos
        inf = Informe()
        verificar_prefijos(inf, [("registro oficial", [(None, "amp-0001-u2-p-01-zz", None),
                                                       (None, "ord-0001-u2-p-01-yy", None)])], {("EXP-1", 2)})
        self.assertEqual([x for x in inf.lineas if x.startswith("✗")], [])


class TestExportacionLegible(unittest.TestCase):
    """Contrato (secciones 4, 7 y 8 y adenda 3): los .md salen solo de los .json, sin jerga, con la columna
    Filtración, la orden marco primero, los tres tiempos con promedios separados, «—» sin ventana y las
    ubicaciones sin decidir; verificar los regenera y un .md editado no verifica."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        cls.base = Path(cls.dir.name)
        cls.motor, cls.sim, cls.entrega, cls.cfg = correr_partido(cls.base)
        cls.resumen = json.loads((cls.entrega / "resumen.json").read_text(encoding="utf-8"))
        cls.expedientes = [json.loads(p.read_text(encoding="utf-8"))
                           for p in sorted((cls.entrega / "expedientes").glob("*.json"))]

    @classmethod
    def tearDownClass(cls):
        cerrar(cls.motor)
        cls.dir.cleanup()

    def copia(self):
        destino = Path(tempfile.mkdtemp(dir=self.dir.name)) / "e"
        shutil.copytree(self.entrega, destino)
        return destino

    def textos(self, expedientes=None, marcos=()):
        from marca.exportar import legibles
        return legibles(self.resumen, expedientes or self.expedientes, list(marcos))

    def test_md_regenerado_igual_y_editado_no_verifica(self):
        inf = verificar(self.entrega)
        self.assertTrue(any(x.startswith("✓ Textos legibles") for x in inf.lineas), inf.lineas)
        for rel in ("acta-del-partido.md", "expedientes/" + sorted(p.name for p in (self.entrega / "expedientes")
                                                                  .glob("*.md"))[0]):
            with self.subTest(archivo=rel):
                e = self.copia()
                ruta = e / rel
                ruta.write_text(ruta.read_text(encoding="utf-8").replace("\n## ", "\n## (editado) ", 1),
                                encoding="utf-8")
                escribir_manifiesto(e)  # el falsificador regenera el manifiesto
                malas = [x for x in verificar(e).lineas if x.startswith("✗")]
                self.assertTrue(any(rel in m and "texto editado" in m for m in malas), malas)
        e = self.copia()
        (e / "expedientes" / "EXP-9.md").write_text("# inventado\n", encoding="utf-8")
        escribir_manifiesto(e)
        self.assertTrue(any("EXP-9.md: no corresponde" in m for m in verificar(e).lineas))

    def test_sin_jerga_y_columna_filtracion(self):
        textos = self.textos()
        acta = textos["acta-del-partido.md"]
        self.assertIn("| Expediente | Sitio | Filtración |", acta)
        self.assertNotIn("Sesión", acta)
        self.assertLess(acta.index("## Orden marco"), acta.index("## Filtraciones"))
        self.assertIn("- Firmadas en persona (", acta)
        self.assertIn("- Ampliaciones automáticas (", acta)
        self.assertIn("Firmaron: ", acta)
        for rel, t in textos.items():
            with self.subTest(archivo=rel):
                for jerga in ("misma_marca", "alcance filtracion", "alcance ubicacion", "juez-a", "juez-b", "None",
                              "ampliación dinámica de"):
                    self.assertNotIn(jerga, t)
                self.assertIsNone(re_decimal_con_punto(t), rel)
        exp = next(t for r, t in textos.items() if "Ampliación automática del sistema" in t)
        self.assertIn("No se firmó en persona.", exp)
        self.assertIn("misma marca de agua que la ubicación 1", exp)

    def test_sin_ventana_y_sin_decidir(self):
        exps = json.loads(json.dumps(self.expedientes))
        u = exps[0]["ubicaciones"][0]
        u["cobertura"] = {"clientes_cubiertos_pct": 0.0, "primer_bloqueo_min": None, "completo_min": None,
                          "visibilidad_residual_pct": None, "sin_ventana": True}
        v = exps[-1]["ubicaciones"][-1]
        v.update(estado="sin_decidir", decision=None, ordenes=[],
                 motivo_sin_decidir="El partido terminó a los 0,4 min de la detección: ya no se pueden firmar órdenes.")
        textos = self.textos(exps)
        acta = textos["acta-del-partido.md"]
        fila = next(l for l in acta.splitlines() if l.startswith(f"| {exps[0]['id']} |") and "| U1 |" in l)
        self.assertTrue(fila.endswith("| — | — | — |"), fila)
        self.assertIn("sin decidir — el partido terminó a los 0,4 min de la detección", acta)
        self.assertNotIn("None", acta)
        self.assertNotIn("0,0 %", fila)
        md = textos[f"expedientes/{exps[0]['id']}.md"]
        self.assertIn("- Cobertura: —", md)

    def test_orden_marco_en_el_acta_y_en_su_md(self):
        from marca.exportar import armar_marcos
        exp = next(x for x in self.expedientes if any((u.get("decision") or {}).get("tipo") == "ampliacion_dinamica"
                                                       for u in x["ubicaciones"]))
        om = entrada_om(2)
        amp = entrada_amp(40, om, exp=exp["id"], ubicacion=2)
        marcos = armar_marcos([om, amp], self.expedientes, {})
        textos = self.textos(marcos=marcos)
        acta = textos["acta-del-partido.md"]
        self.assertIn("- OM-01: Dra. A (Juzgado 1), minuto 2,0 · seguimiento: sí", acta)
        self.assertIn(f"Ampliaciones hechas bajo esta orden: {exp['id']} U2 (minuto 40,0).", acta)
        md = textos["orden-marco/OM-01.md"]
        from marca.marco import CONDICIONES_SEGUIMIENTO, TITULO_CASILLA, a_texto
        renglones = a_texto(om["datos"]["contenido"])
        for i, r in enumerate(renglones, start=1):  # el texto legible es marco.a_texto, numerado
            self.assertIn(f"{i}. {r}\n", md)
        self.assertEqual(md.count(TITULO_CASILLA), 1)
        self.assertIn("- [x] Autorizado por el juez.", md)
        self.assertIn(om["datos"]["huella"], md)
        # Sin seguimiento: ni el título ni las condiciones.
        om2 = entrada_om(3, seguimiento=False, oid="OM-02")
        md2 = self.textos(marcos=armar_marcos([om2], self.expedientes, {}))["orden-marco/OM-02.md"]
        self.assertNotIn(TITULO_CASILLA, md2)
        self.assertFalse(any(x in md2 for x in CONDICIONES_SEGUIMIENTO))
        self.assertIn("- [ ] No autorizado.", md2)

    def test_tiempos_de_una_ubicacion(self):
        from marca.exportar import tiempos_ubicacion
        provs = [{"id": "p1"}, {"id": "p2"}]
        u = {"primera_deteccion_min": 10.0, "vista_min": 10.2,
             "decision": {"aprobada": True, "tipo": "firma", "min": 10.5},
             "ordenes": [{"proveedor": "p1", "aplicada_min": 11.0}, {"proveedor": "p1", "aplicada_min": 10.8},
                         {"proveedor": "p2", "aplicada_min": 14.0}, {"proveedor": "p2", "aplicada_min": None}]}
        t = tiempos_ubicacion(u, provs)
        self.assertEqual((t["firma_min"], t["primer_proveedor_min"], t["todos_los_proveedores_min"], t["tipo"]),
                         (10.5, 10.8, 14.0, "en_persona"))
        self.assertAlmostEqual(t["expediente_abierto_min"], 0.3)
        u["ordenes"] = u["ordenes"][:2]
        self.assertIsNone(tiempos_ubicacion(u, provs)["todos_los_proveedores_min"])  # p2 nunca aplicó
        u["decision"] = {"aprobada": True, "tipo": "ampliacion_dinamica", "min": 10.0}
        t = tiempos_ubicacion(u, provs)
        self.assertEqual((t["tipo"], t["expediente_abierto_min"]), ("ampliacion", None))
        self.assertIn("tiempos", self.resumen)
        self.assertEqual(set(self.resumen["tiempos"]["promedios"]), {"en_persona", "ampliacion"})

    def test_la_ventana_es_la_de_evidencia(self):
        """Adenda 3, A: la cobertura exportada usa evidencia.ventana (la ubicación 1 vuelve después de que
        apareció la 2: su ventana sigue hasta la primera detección ajena posterior a su última propia)."""
        from marca import evidencia
        from marca.exportar import armar_expedientes
        u1 = {"n": 1, "ip": "203.0.113.10", "host": "a.test", "primera_deteccion_min": 2.0,
              "detecciones_min": [2.0, 9.0], "detecciones": [{}, {}]}
        u2 = {"n": 2, "ip": "203.0.113.11", "host": "b.test", "primera_deteccion_min": 5.0,
              "detecciones_min": [5.0, 20.0], "detecciones": [{}, {}]}
        estado = {"partido": {"fin_min": 30.0}, "minuto": 30.0, "proveedores": [{"id": "p1", "clientes": 10}],
                  "ordenes": {"x": {"exp": "EXP-1", "n": 1, "tipo": "ip", "objetivo": "203.0.113.10",
                                    "proveedor": "p1", "aplicada_min": 3.0, "finalizada_min": None}},
                  "expedientes": [{"id": "EXP-1", "ubicaciones": [u1, u2]}]}
        exp = armar_expedientes(estado)[0]
        esperada = evidencia.ventana([u1, u2], u1, 30.0, 30.0)
        self.assertEqual(tuple(exp["ubicaciones"][0]["ventana"]), esperada)
        self.assertEqual(esperada, (2.0, 20.0))  # la regla vieja («hasta la siguiente») daba (2, 5)
        self.assertEqual(exp["ubicaciones"][0]["cobertura"],
                         evidencia.cobertura(2.0, 20.0, u1["ip"], u1["host"], list(estado["ordenes"].values()),
                                             estado["proveedores"]))


def re_decimal_con_punto(texto):
    """Un número con punto decimal fuera de código (`…`), hashes, URLs o direcciones IP."""
    import re
    sin_codigo = re.sub(r"`[^`]*`", "", texto)
    for m in re.finditer(r"(?<![\w./:-])\d+\.\d+(?![\w./:-])", sin_codigo):
        return m.group(0)
    return None


if __name__ == "__main__":
    unittest.main()
