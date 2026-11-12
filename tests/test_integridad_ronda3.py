"""Contratos de integridad de la ronda 3 (agente I).

- Testigos con corte: lo que la plataforma anotó después de la foto de los proveedores (`corte_auditoria` de la
  última `testigos_guardados`) no se le exige a esa foto ni a los expedientes de esa foto: es una nota, porque el
  partido siguió después de exportar. Lo anterior a la foto que falta sigue siendo ✗.
- Una orden «perdida» (desapareció de la lista del proveedor) no se le exige a los testigos ni al registro: es una
  nota. Una orden que no está perdida y falta sigue siendo ✗.
- C7: la leyenda de la ampliación del acta sale de marca.marco.texto_ampliacion, con los textos exactos del
  contrato, y dice «Hecha en el minuto …».
- C8: los minutos que se leen en el acta pasan por canon.min_txt (60,25 -> «60,3», nunca «-0,0»).
- Vocabulario: «seguimiento» y «frenar» en lo que lee una persona; `--sin-dinamica` dice qué deshabilita.
- C9: la API no rechaza una dirección completa pegada en la consulta pública; tiene un tope de largo.
- G1: el ensayo no para el simulador antes del minuto del cierre (fin + 5) que evalúa el verificador oficial.
"""
import contextlib
import io
import json
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request
from pathlib import Path

from marca import exportar as exportar_mod
from marca.auditoria import leer_entradas
from marca.canon import min_txt
from marca.exportar import escribir_manifiesto, exportar
from marca.marco import texto_ampliacion as leyenda
from marca.motor import Motor
from marca.usuarios import Usuarios
from marca.verificar import main_verificar, verificar

from tests.simulador_falso import SimuladorFalso
from tests.test_motor_verificar import CONFIG, correr_partido
from tests.test_paquete import cerrar, recalcular_cadena

RAIZ = Path(__file__).resolve().parent.parent


def malas(inf):
    return [x for x in inf.lineas if x.startswith("✗")]


def notas(inf):
    return [x for x in inf.lineas if x.startswith("·")]


def rearmar(e: Path, testigos: dict = None) -> None:
    """Lo que haría quien rearma un paquete sin claves: testigos nuevos con su sha256 en la auditoría, cadena
    recalculada, cabeza en el resumen, .md regenerados y manifiesto nuevo. Sirve para armar casos de prueba."""
    ruta_aud = e / "auditoria.jsonl"
    entradas = leer_entradas(ruta_aud)
    if testigos is not None:
        datos = json.dumps(testigos, ensure_ascii=False, indent=1, sort_keys=True).encode("utf-8")
        (e / "testigos" / "proveedores.json").write_bytes(datos)
        import hashlib
        ultima = [x for x in entradas if x["tipo"] == "testigos_guardados"][-1]
        ultima["datos"]["sha256"] = hashlib.sha256(datos).hexdigest()
    recalcular_cadena(ruta_aud, entradas)
    entradas = leer_entradas(ruta_aud)
    resumen = json.loads((e / "resumen.json").read_text(encoding="utf-8"))
    resumen["cabeza_auditoria"] = {"n": entradas[-1]["n"], "hash": entradas[-1]["hash"]}
    (e / "resumen.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=1), encoding="utf-8")
    regenerar_md(e)


def regenerar_md(e: Path) -> None:
    resumen = json.loads((e / "resumen.json").read_text(encoding="utf-8"))
    expedientes = sorted((json.loads(p.read_text(encoding="utf-8")) for p in (e / "expedientes").glob("*.json")),
                         key=lambda x: (x.get("num") or 0, str(x.get("id"))))
    marcos = sorted((json.loads(p.read_text(encoding="utf-8")) for p in (e / "orden-marco").glob("*.json")),
                    key=lambda x: x.get("entrada") or 0) if (e / "orden-marco").is_dir() else []
    for rel, texto in exportar_mod.legibles(resumen, expedientes, marcos).items():
        (e / rel).write_text(texto, encoding="utf-8")
    escribir_manifiesto(e)


def partido_con_foto_temprana(base: Path):
    """El partido falso de test_motor_verificar, con una foto de los proveedores en el minuto 5 (antes de la
    ampliación del minuto 6,1) y sin la foto final. Devuelve (motor, sim, estado_de_la_foto, corte)."""
    ruta_cfg = base / "jueces.json"
    ruta_cfg.write_text(json.dumps(CONFIG), encoding="utf-8")
    sim = SimuladorFalso()
    usuarios = Usuarios(ruta_cfg)
    motor = Motor("http://falso", base / "salida", usuarios, cliente=sim, tick=0.01, registro=lambda t: None)
    motor.arrancar(nueva=True, hilos=False)

    def paso(minuto):
        sim.avanzar(minuto)
        motor._t_estado = float("-inf")
        motor.paso()
        motor.despacho.ronda()
        motor.paso()

    paso(1.2)
    exp = motor.e["expedientes"][0]
    usuarios.ingresar("a", "clave-de-prueba-a")
    motor.firmar_marco("juez-a", True)
    motor.aprobar("juez-a", exp["id"], 1, "filtracion", None, None)
    paso(1.3)
    paso(2.2)
    cdn = motor.e["expedientes"][1]
    motor.aprobar("juez-a", cdn["id"], 1, "ubicacion", None, None)
    for m in (2.3, 3.0, 4.0, 5.0):
        paso(m)
    entrada = motor.foto_testigos()  # guarda estado.json en la misma pasada
    estado_foto = (motor.salida / "estado.json").read_bytes()
    paso(6.1)  # mudanza s1 → s2: se amplía sola, después de la foto
    paso(6.2)
    paso(7.0)
    return motor, sim, estado_foto, entrada["datos"]["corte_auditoria"]


class TestTestigosConCorte(unittest.TestCase):
    """B1: el partido siguió después de la foto de los proveedores."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        cls.base = Path(cls.dir.name)
        cls.motor, cls.sim, estado_foto, cls.corte = partido_con_foto_temprana(cls.base)
        salida = cls.motor.salida
        # A: estado al día, testigos de la foto del minuto 5 (exportar sin refrescar testigos).
        with cls.motor.candado:
            cls.motor.guardar()
        cls.A = exportar(salida, cls.base / "A")
        # B: lo que lee `marca exportar` con la plataforma viva: estado.json de la foto y la auditoría que siguió.
        actual = (salida / "estado.json").read_bytes()
        (salida / "estado.json").write_bytes(estado_foto)
        try:
            cls.B = exportar(salida, cls.base / "B")
        finally:
            (salida / "estado.json").write_bytes(actual)
        aud = leer_entradas(cls.A / "auditoria.jsonl")
        cls.tardias = sorted({x["datos"]["orden_id"] for x in aud if x["tipo"] == "orden_enviada" and x["n"] > cls.corte})
        cls.tempranas = sorted({x["datos"]["orden_id"] for x in aud
                                if x["tipo"] == "orden_enviada" and x["n"] <= cls.corte})

    @classmethod
    def tearDownClass(cls):
        cerrar(cls.motor)
        cls.dir.cleanup()

    def copia(self, origen):
        destino = Path(tempfile.mkdtemp(dir=self.dir.name))
        shutil.copytree(origen, destino / "e")
        return destino / "e"

    def test_el_caso_existe(self):
        self.assertTrue(self.tardias, "no salió ninguna orden después de la foto: el caso no se armó")
        self.assertTrue(self.tempranas)
        self.assertTrue(all(o.startswith("amp-") for o in self.tardias), self.tardias)

    def test_orden_posterior_a_la_foto_es_nota_en_los_testigos(self):
        inf = verificar(self.A)
        self.assertEqual(malas(inf), [])
        self.assertTrue(any("después de la foto" in x and self.tardias[0] in x for x in notas(inf)), inf.lineas)

    def test_auditoria_posterior_al_estado_exportado_es_nota(self):
        inf = verificar(self.B)
        self.assertEqual(malas(inf), [])
        self.assertTrue(any("después de la foto" in x and "expedientes" in x for x in notas(inf)), inf.lineas)

    def test_con_firmas_y_registro_sigue_verde(self):
        registro = self.base / "registro.jsonl"
        registro.write_text("".join(json.dumps(r) + "\n" for r in self.sim.registro), encoding="utf-8")
        self.assertEqual(malas(verificar(self.A, registro, self.base / "jueces.json")), [])

    def test_inverso_orden_anterior_a_la_foto_que_falta_en_los_testigos_es_error(self):
        e = self.copia(self.A)
        testigos = json.loads((e / "testigos" / "proveedores.json").read_text(encoding="utf-8"))
        quitada = self.tempranas[0]
        for pid in testigos["proveedores"]:
            testigos["proveedores"][pid] = [o for o in testigos["proveedores"][pid] if o["orden_id"] != quitada]
        rearmar(e, testigos)
        m = malas(verificar(e))
        self.assertTrue(any("testigos: faltan" in x and quitada in x for x in m), m)

    def test_inverso_orden_anterior_a_la_foto_que_falta_en_los_expedientes_es_error(self):
        e = self.copia(self.B)
        quitada = self.tempranas[0]
        for arch in (e / "expedientes").glob("*.json"):
            exp = json.loads(arch.read_text(encoding="utf-8"))
            for u in exp["ubicaciones"]:
                u["ordenes"] = [o for o in u["ordenes"] if o["orden_id"] != quitada]
            arch.write_text(json.dumps(exp, ensure_ascii=False, indent=1), encoding="utf-8")
        regenerar_md(e)
        m = malas(verificar(e))
        self.assertTrue(any(quitada in x and "no está en ningún expediente exportado" in x for x in m), m)


class TestOrdenPerdida(unittest.TestCase):
    """B2: una orden perdida no se le exige a los testigos; una que no lo está y falta, sí."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        cls.base = Path(cls.dir.name)
        cls.motor, cls.sim, cls.entrega, cls.cfg = correr_partido(cls.base)

    @classmethod
    def tearDownClass(cls):
        cerrar(cls.motor)
        cls.dir.cleanup()

    def armar(self, perdida: bool):
        e = Path(tempfile.mkdtemp(dir=self.dir.name)) / "e"
        shutil.copytree(self.entrega, e)
        arch = sorted((e / "expedientes").glob("*.json"))[0]
        exp = json.loads(arch.read_text(encoding="utf-8"))
        o = exp["ubicaciones"][0]["ordenes"][0]
        if perdida:
            o["estado"] = "perdida"
            o["motivo"] = "Desapareció de la lista del proveedor antes de vencer."
        arch.write_text(json.dumps(exp, ensure_ascii=False, indent=1), encoding="utf-8")
        testigos = json.loads((e / "testigos" / "proveedores.json").read_text(encoding="utf-8"))
        testigos["proveedores"][o["proveedor"]] = [x for x in testigos["proveedores"][o["proveedor"]]
                                                    if x["orden_id"] != o["orden_id"]]
        rearmar(e, testigos)
        return e, o["orden_id"]

    def test_perdida_que_no_esta_en_los_testigos_es_nota(self):
        e, oid = self.armar(perdida=True)
        inf = verificar(e)
        # El estado «perdida» se escribió a mano en el .json (sin su orden_perdida en la auditoría): desde la tanda
        # R3B lo derivado se recalcula desde la auditoría y eso da su propio ✗ (paquete-1). Acá importa el cruce
        # con los testigos: ese no tiene que dar ✗.
        self.assertEqual([x for x in malas(inf) if "campo estado es 'perdida'" not in x], [])
        self.assertTrue(any("perdida" in x and oid in x for x in notas(inf)), inf.lineas)

    def test_inverso_la_misma_orden_sin_perder_es_error(self):
        e, oid = self.armar(perdida=False)
        m = malas(verificar(e))
        self.assertTrue(any("testigos: faltan" in x and oid in x for x in m), m)


class TestLeyendaDelActa(unittest.TestCase):
    """C7: el acta usa marca.marco.texto_ampliacion con los datos de la decisión de la ubicación ampliada."""

    def ctx(self, marcos):
        jueces = {m["juez_id"]: m["juez"] for m in marcos}
        jueces.update({"juez-l": "Dra. Laura Ficticia", "juez-m": "Dr. Martín Ejemplo"})
        return {"marcos_por_entrada": {m["entrada"]: m for m in marcos}, "jueces": jueces}

    OM2 = {"id": "OM-02", "entrada": 20, "juez_id": "juez-l", "juez": "Dra. Laura Ficticia", "min": 5.8}
    OM3 = {"id": "OM-03", "entrada": 142, "juez_id": "juez-m", "juez": "Dr. Martín Ejemplo", "min": 58.7}

    def test_sin_traspaso(self):
        exp = {"dinamica": {"otorgada_por": {"juez_id": "juez-l", "nombre": "Dra. Laura Ficticia"},
                            "otorgada_min": 39.8, "ratificaciones": []}}
        u = {"decision": {"tipo": "ampliacion_dinamica", "aprobada": True, "juez_id": "juez-l", "min": 44.06,
                          "orden_marco": {"id": "OM-02", "entrada": 20}}}
        self.assertEqual(
            exportar_mod.texto_ampliacion(exp, u, self.ctx([self.OM2])),
            "Ampliación automática del sistema bajo la orden marco OM-02 de Dra. Laura Ficticia (minuto 5,8) y el "
            "seguimiento que otorgó en el minuto 39,8. Hecha en el minuto 44,1. No se firmó en persona.")

    def test_con_traspaso(self):
        exp = {"dinamica": {"otorgada_por": {"juez_id": "juez-l", "nombre": "Dra. Laura Ficticia"},
                            "otorgada_min": 39.8,
                            "ratificaciones": [{"juez_id": "juez-m", "nombre": "Dr. Martín Ejemplo", "min": 60.25}]}}
        u = {"decision": {"tipo": "ampliacion_dinamica", "aprobada": True, "juez_id": "juez-m", "min": 71.0,
                          "orden_marco": {"id": "OM-03", "entrada": 142}}}
        self.assertEqual(
            exportar_mod.texto_ampliacion(exp, u, self.ctx([self.OM2, self.OM3])),
            "Ampliación automática del sistema bajo la orden marco OM-03 de Dr. Martín Ejemplo (minuto 58,7), que en "
            "el minuto 60,3 ratificó el seguimiento otorgado por Dra. Laura Ficticia (minuto 39,8). Hecha en el minuto "
            "71,0. No se firmó en persona.")

    def test_es_la_misma_funcion_que_usa_el_motor(self):
        exp = {"dinamica": {"otorgada_por": {"juez_id": "juez-l", "nombre": "Dra. Laura Ficticia"},
                            "otorgada_min": 39.8, "ratificaciones": []}}
        u = {"decision": {"tipo": "ampliacion_dinamica", "aprobada": True, "juez_id": "juez-l", "min": 44.06,
                          "orden_marco": {"id": "OM-02", "entrada": 20}}}
        self.assertEqual(exportar_mod.texto_ampliacion(exp, u, self.ctx([self.OM2])),
                         leyenda({"id": "OM-02", "nombre": "Dra. Laura Ficticia", "min": 5.8},
                                 {"nombre": "Dra. Laura Ficticia", "min": 39.8}, None, 44.06))

    def test_el_acta_del_partido_falso_la_trae(self):
        with tempfile.TemporaryDirectory() as d:
            motor, _, entrega, _ = correr_partido(Path(d))
            try:
                acta = "".join((entrega / "expedientes").joinpath(p.name).read_text(encoding="utf-8")
                               for p in (entrega / "expedientes").glob("*.md"))
            finally:
                cerrar(motor)
        self.assertIn("Ampliación automática del sistema bajo la orden marco OM-01 de Dra. A (minuto", acta)
        self.assertRegex(acta, r"Hecha en el minuto \d+,\d\. No se firmó en persona\.")


class TestMinutosYVocabulario(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        cls.motor, cls.sim, cls.entrega, cls.cfg = correr_partido(Path(cls.dir.name))

    @classmethod
    def tearDownClass(cls):
        cerrar(cls.motor)
        cls.dir.cleanup()

    def test_c8_un_solo_redondeo(self):
        for x in (60.25, 0.05, 39.75, -0.04, 5, None, 105.0):
            self.assertEqual(exportar_mod._m(x), min_txt(x))
        self.assertEqual(exportar_mod._m(60.25), "60,3")
        self.assertEqual(exportar_mod._m(-0.04), "0,0")
        acta = (self.entrega / "acta-del-partido.md").read_text(encoding="utf-8")
        self.assertIn("fin: minuto 20,0", acta)

    def test_seguimiento_frenado_en_el_expediente(self):
        exp = json.loads(sorted((self.entrega / "expedientes").glob("*.json"))[0].read_text(encoding="utf-8"))
        exp["dinamica"] = dict(exp.get("dinamica") or {}, revocada={"juez_id": "juez-a", "min": 9.5})
        resumen = json.loads((self.entrega / "resumen.json").read_text(encoding="utf-8"))
        ctx = exportar_mod.contexto(resumen, [exp], [])
        md = exportar_mod.expediente_md(exp, ctx)
        self.assertIn("- Seguimiento frenado por Dra. A en el minuto 9,5.", md)
        self.assertNotIn("revoc", md.lower())
        self.assertNotIn("orden dinámica", md.lower())

    def test_verificar_no_dice_orden_dinamica_ni_revocar(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main_verificar(self.entrega, None, str(self.cfg))
        texto = buf.getvalue().lower()
        self.assertNotIn("dinámic", texto)
        self.assertNotIn("revoc", texto)
        self.assertIn("ampliaciones automáticas", texto)

    def test_ayuda_de_sin_dinamica(self):
        from marca.__main__ import main
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), self.assertRaises(SystemExit):
            main(["servir", "--help"])
        ayuda = " ".join(buf.getvalue().split())
        self.assertIn("--sin-dinamica", ayuda)
        self.assertIn("deshabilita el seguimiento (ampliaciones automáticas)", ayuda)


class TestConsultaPublicaConDireccion(unittest.TestCase):
    """C9: la API pasa al motor la dirección completa pegada (el motor la normaliza), con un tope de largo."""

    def test_url_completa_llega_al_motor(self):
        from marca.api import servir
        with tempfile.TemporaryDirectory() as d:
            motor, _, _, _ = correr_partido(Path(d))
            recibidos = []
            original = motor.consulta_publica

            def espia(texto):
                recibidos.append(texto)
                return original(texto)
            motor.consulta_publica = espia
            servidor = servir(motor, "127.0.0.1", 0)
            hilo = threading.Thread(target=servidor.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
            hilo.start()
            try:
                base = f"http://127.0.0.1:{servidor.server_address[1]}/api/publico/consulta?dominio="
                abrir = urllib.request.build_opener(urllib.request.ProxyHandler({})).open
                url = "https://Sitio.test/ruta?x=1"
                with abrir(base + urllib.parse.quote(url, safe=""), timeout=5) as r:
                    self.assertEqual(r.status, 200)
                    json.loads(r.read())
                larga = "https://sitio.test/" + "a" * 5000
                with abrir(base + urllib.parse.quote(larga, safe=""), timeout=5) as r:
                    self.assertEqual(r.status, 200)
            finally:
                servidor.shutdown()
                servidor.server_close()
                cerrar(motor)
        self.assertEqual(recibidos[0], url)
        self.assertTrue(recibidos[1].startswith("https://sitio.test/"))
        self.assertLessEqual(len(recibidos[1]), 2048)
        self.assertGreater(len(recibidos[1]), 300)


class TestEnsayoEsperaElCierre(unittest.TestCase):
    """G1: el verificador oficial evalúa «bloqueos activos después del partido» solo si el registro llega al minuto
    fin + gracia (110). El ensayo no corta el simulador antes."""

    def setUp(self):
        sys.path.insert(0, str(RAIZ / "herramientas"))
        import ensayo
        self.ensayo = ensayo

    def test_espera_hasta_el_cierre(self):
        minutos = iter([104.0, 108.2, 110.4, 110.6, 111.0])
        dormidas = []
        m = self.ensayo.esperar_minuto(lambda: next(minutos), 110.5, tope_s=60, dormir=dormidas.append)
        self.assertEqual(m, 110.6)
        self.assertEqual(len(dormidas), 3)

    def test_sin_simulador_no_cuelga(self):
        def caido():
            raise OSError("caído")
        reloj = iter(range(0, 1000, 10))
        m = self.ensayo.esperar_minuto(caido, 110.5, tope_s=30, dormir=lambda s: None, ahora=lambda: next(reloj))
        self.assertIsNone(m)


if __name__ == "__main__":
    unittest.main()
