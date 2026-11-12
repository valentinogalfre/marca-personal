"""Contratos de punta a punta sin red: motor + despacho contra un simulador falso, exportación y verificación.

- La plataforma solo firma con sesión y de turno; la mudanza con la misma marca se amplía sola.
- Nunca se manda una orden que el simulador rechace; nunca un orden_id repetido.
- Una exportación sana verifica; un byte cambiado en la captura, el sellado o la auditoría la rompe.
- Testigos: si el proveedor guarda otro objetivo, o una orden que no está en la auditoría, falla y dice cuál.
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from marca.motor import ErrorAccion, Motor
from marca.usuarios import Usuarios
from marca.verificar import verificar

from tests.simulador_falso import SimuladorFalso

CONFIG = {
    "aviso": "pruebas",
    "usuarios": [{"usuario": "a", "clave_demo": "clave-de-prueba-a", "rol": "juez", "juez_id": "juez-a"},
                 {"usuario": "b", "clave_demo": "clave-de-prueba-b", "rol": "juez", "juez_id": "juez-b"},
                 {"usuario": "f", "clave_demo": "clave-de-prueba-f", "rol": "fiscalia", "nombre": "Fiscalía"}],
    "claves_firma_demo": {"juez-a": "clave-a", "juez-b": "clave-b"},
}


def correr_partido(dir_base: Path):
    """Corre el partido falso completo, a mano, y devuelve (motor, sim, entrega, ruta_config)."""
    ruta_cfg = dir_base / "jueces.json"
    ruta_cfg.write_text(json.dumps(CONFIG), encoding="utf-8")
    sim = SimuladorFalso()
    usuarios = Usuarios(ruta_cfg)
    motor = Motor("http://falso", dir_base / "salida", usuarios, cliente=sim, tick=0.01, registro=lambda t: None)
    motor.arrancar(nueva=True, hilos=False)

    def paso(minuto):
        sim.avanzar(minuto)
        motor._t_estado = float("-inf")
        motor.paso()
        motor.despacho.ronda()
        motor.paso()

    paso(1.2)
    exp = motor.e["expedientes"][0]
    # Sin sesión de juez no se firma nada y el pedido queda pendiente.
    assert exp["ubicaciones"][0]["estado"] == "pendiente"
    usuarios.ingresar("a", "clave-de-prueba-a")
    motor.firmar_marco("juez-a", True)  # ronda 2b: seguir a la filtración exige la orden marco con seguimiento
    motor.aprobar("juez-a", exp["id"], 1, "filtracion", None, None)
    paso(1.3)
    paso(2.2)
    cdn = motor.e["expedientes"][1]
    motor.aprobar("juez-a", cdn["id"], 1, "ubicacion", None, None)
    for m in (2.3, 3.0, 4.0, 5.0):
        paso(m)
    paso(6.1)  # mudanza s1 → s2: se amplía sola
    paso(6.2)
    for m in (7.0, 8.0, 9.0, 10.2):
        paso(m)
    usuarios.ingresar("b", "clave-de-prueba-b")
    paso(10.5)
    motor.ratificar("juez-b")
    for m in (12.0, 20.0, 21.0, 25.1, 25.2):
        paso(m)
    return motor, sim, dir_base / "salida" / "entrega", ruta_cfg


class TestPartidoFalso(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        cls.base = Path(cls.dir.name)
        cls.motor, cls.sim, cls.entrega, cls.cfg = correr_partido(cls.base)

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    def copia(self):
        destino = Path(tempfile.mkdtemp(dir=self.dir.name))
        shutil.copytree(self.entrega, destino / "e")
        return destino / "e"

    def test_flujo_y_reglas(self):
        e = self.motor.e
        self.assertEqual(len(e["expedientes"]), 2)
        pir = e["expedientes"][0]
        self.assertEqual([u["host"] for u in pir["ubicaciones"]], ["s1.pirata.test", "s2.pirata.test"])
        self.assertEqual(pir["ubicaciones"][1]["decision"]["tipo"], "ampliacion_dinamica")
        self.assertEqual(pir["ubicaciones"][1]["continuidad"]["criterio"], "misma_marca")
        # El licenciatario se descarta, nunca llega al juez.
        self.assertEqual([d["clase"] for d in e["descartes"].values()], ["licenciatario"])
        # Valle (solo dominio) recibe el host y su respaldo; nunca IP.
        valle = sorted(o["objetivo"] for o in e["ordenes"].values() if o["proveedor"] == "valle")
        self.assertIn("s1-respaldo.pirata.test", valle)
        self.assertTrue(all(o["tipo"] == "dominio" for o in e["ordenes"].values() if o["proveedor"] == "valle"))
        # CDN: solo dominio.
        cdn = [o for o in e["ordenes"].values() if o["exp"] == e["expedientes"][1]["id"]]
        self.assertTrue(cdn and all(o["tipo"] == "dominio" for o in cdn))
        # Ningún rechazo; ningún orden_id repetido; nada fuera de turno.
        self.assertFalse([r for r in self.sim.registro if r["evento"] == "orden_rechazada"])
        recibidas = [r for r in self.sim.registro if r["evento"] == "orden_recibida"]
        self.assertEqual(len(recibidas), len({(r["proveedor"], r["orden_id"]) for r in recibidas}))
        self.assertTrue(all(r["juez_de_turno"] for r in recibidas))
        # Traspaso creado y ratificado.
        self.assertEqual(len(e["traspasos"]), 1)
        self.assertEqual(e["traspasos"][0]["ratificado"]["juez_id"], "juez-b")
        # La clave de firma no aparece en el estado, la auditoría ni la exportación.
        for archivo in list((self.base / "salida").rglob("*.json*")):
            texto = archivo.read_text(encoding="utf-8", errors="ignore")
            self.assertNotIn("clave-a", texto, archivo)
            self.assertNotIn("clave-de-prueba", texto, archivo)

    def test_saliente_no_firma_y_juez_ajeno_no_ve(self):
        with self.assertRaises(ErrorAccion) as ctx:
            self.motor.ratificar("juez-a")
        self.assertIn(ctx.exception.codigo, ("conflicto", "fuera_de_turno"))
        b = self.motor.vista_bandeja({"usuario": "a", "rol": "juez", "juez_id": "juez-a"})
        self.assertFalse(b["turno"]["de_turno"])
        self.assertEqual(b["pendientes"], [])

    def test_exportacion_sana_verifica(self):
        inf = verificar(self.entrega, None, self.cfg)
        self.assertEqual(inf.fallas, 0, "\n".join(inf.lineas))
        self.assertTrue(any("Testigos: sha256" in x for x in inf.lineas))

    def test_byte_cambiado_en_la_captura(self):
        e = self.copia()
        cap = sorted((e / "capturas").glob("*.ts"))[0]
        datos = bytearray(cap.read_bytes())
        datos[10] ^= 1
        cap.write_bytes(bytes(datos))
        inf = verificar(e)
        self.assertGreater(inf.fallas, 0)
        self.assertTrue(any(cap.name in x for x in inf.lineas if x.startswith("✗")))

    def test_byte_cambiado_en_el_sellado(self):
        e = self.copia()
        arch = sorted((e / "expedientes").glob("*.json"))[0]
        exp = json.loads(arch.read_text(encoding="utf-8"))
        exp["ubicaciones"][0]["sellado"]["servidor"]["ip"] = "203.0.113.99"
        arch.write_text(json.dumps(exp), encoding="utf-8")
        inf = verificar(e)
        self.assertTrue(any("huella" in x for x in inf.lineas if x.startswith("✗")), inf.lineas)

    def test_byte_cambiado_en_la_auditoria(self):
        e = self.copia()
        ruta = e / "auditoria.jsonl"
        texto = ruta.read_text(encoding="utf-8")
        ruta.write_text(texto.replace('"titular"', '"titulor"', 1), encoding="utf-8")
        inf = verificar(e)
        self.assertTrue(any("Auditoría" in x for x in inf.lineas if x.startswith("✗")), inf.lineas)

    def test_testigo_con_objetivo_cambiado(self):
        e = self.copia()
        ruta = e / "testigos" / "proveedores.json"
        doc = json.loads(ruta.read_text(encoding="utf-8"))
        orden = doc["proveedores"]["aurora"][0]
        orden["objetivo"] = "192.0.2.123"
        ruta.write_text(json.dumps(doc), encoding="utf-8")
        inf = verificar(e)
        malas = [x for x in inf.lineas if x.startswith("✗")]
        self.assertTrue(any("sha256" in x for x in malas), malas)
        self.assertTrue(any(orden["orden_id"] in x and "objetivo" in x for x in malas), malas)

    def test_testigo_con_orden_que_no_esta_en_la_auditoria(self):
        e = self.copia()
        ruta = e / "testigos" / "proveedores.json"
        doc = json.loads(ruta.read_text(encoding="utf-8"))
        intrusa = dict(doc["proveedores"]["aurora"][0], orden_id="ord-9999-u1-aurora-01-" + "0" * 32)
        doc["proveedores"]["aurora"].append(intrusa)
        ruta.write_text(json.dumps(doc), encoding="utf-8")
        inf = verificar(e)
        malas = [x for x in inf.lineas if x.startswith("✗")]
        self.assertTrue(any("ord-9999" in x and "auditoría" in x for x in malas), malas)

    def test_sin_testigos_no_es_error(self):
        # Un paquete exportado sin testigos (sin conexión al cierre): la auditoría no registra testigos guardados.
        # (Si la auditoría dice que se guardaron y el archivo falta, sí es una falla: lo cubre test_paquete.)
        from marca.auditoria import leer_entradas
        from tests.test_paquete import recalcular_cadena
        e = self.copia()
        shutil.rmtree(e / "testigos")
        ruta = e / "auditoria.jsonl"
        recalcular_cadena(ruta, [x for x in leer_entradas(ruta) if x["tipo"] != "testigos_guardados"])
        inf = verificar(e)
        # (El manifiesto y la cabeza cambian porque la prueba reescribe la auditoría: eso no es lo que se mira acá.)
        self.assertFalse(any(x.startswith("✗") and "testigos_guardados" in x for x in inf.lineas), inf.lineas)
        self.assertTrue(any("Testigos" in x and "no disponible" in x for x in inf.lineas))

    def test_registro_oficial_cruzado(self):
        e = self.copia()
        ruta = Path(self.dir.name) / "registro.jsonl"
        ruta.write_text("\n".join(json.dumps(r) for r in self.sim.registro) + "\n", encoding="utf-8")
        self.assertEqual(verificar(e, ruta).fallas, 0)
        extra = dict(next(r for r in self.sim.registro if r["evento"] == "orden_recibida"), juez_de_turno=False)
        ruta.write_text("\n".join(json.dumps(r) for r in self.sim.registro + [extra]) + "\n", encoding="utf-8")
        inf = verificar(e, ruta)
        self.assertTrue(any("fuera de turno" in x for x in inf.lineas if x.startswith("✗")))


class TestUsuarios(unittest.TestCase):
    def test_traba_y_sesion(self):
        with tempfile.TemporaryDirectory() as d:
            ruta = Path(d) / "c.json"
            ruta.write_text(json.dumps(CONFIG), encoding="utf-8")
            u = Usuarios(ruta)
            from marca.usuarios import ErrorLogin
            for _ in range(5):
                with self.assertRaises(ErrorLogin):
                    u.ingresar("a", "mal")
            with self.assertRaises(ErrorLogin) as ctx:
                u.ingresar("a", "clave-de-prueba-a")
            self.assertEqual(ctx.exception.codigo, "trabado")
            ficha, yo = u.ingresar("b", "clave-de-prueba-b")
            self.assertEqual(u.sesion(ficha)["juez_id"], "juez-b")
            self.assertTrue(u.tiene_sesion("juez-b"))
            self.assertNotIn("clave", json.dumps(yo))


if __name__ == "__main__":
    unittest.main()
