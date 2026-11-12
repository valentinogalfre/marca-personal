"""Contrato (NV1, variante): una orden de reemplazo por reclamo la ordena el juez al resolver el reclamo, también cuando
la ubicación reemplazada se había ampliado sola (seguimiento). /orden/<id> y el registro público no pueden rotularla
«Ampliación automática»: dicen que se decidió al resolver el reclamo. Corre el JS real con node y el motor real."""
import json, shutil, subprocess, tempfile, unittest
from pathlib import Path
from unittest import mock
from marca.motor import Motor
from marca.usuarios import Usuarios
from tests import simulador_falso
from tests.simulador_falso import SimuladorFalso, deteccion
from tests.test_motor_verificar import CONFIG

RAIZ = Path(__file__).resolve().parent.parent
JS = RAIZ / "marca" / "web" / "static" / "js"
NODE = shutil.which("node")
IPA, IPB = "198.51.100.71", "198.51.100.72"
DNS = {IPA: ["tv.club.test", "kiosco.club.test"], IPB: ["tv2.club.test", "ferreteria.club.test"]}
JA = {"usuario": "a", "juez_id": "juez-a", "rol": "juez", "nombre": "Dra. A"}


@unittest.skipUnless(NODE, "sin node")
class ReemplazoDeUnaAmpliacion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        base = Path(cls.dir.name)
        cls.parches = [mock.patch.dict(simulador_falso.DNS, DNS),
                       mock.patch.dict(simulador_falso.ASN_DE_IP, {ip: 64601 for ip in DNS})]
        for p in cls.parches:
            p.start()
        ruta = base / "jueces.json"
        ruta.write_text(json.dumps(CONFIG), encoding="utf-8")
        sim = SimuladorFalso()
        sim.lista_detecciones = [
            deteccion("D-0201", 1.0, "tv.club.test", IPA, "LP26-PRU-OFI-S0201", "https://club.test/tv", 64601),
            deteccion("D-0202", 2.7, "tv2.club.test", IPB, "LP26-PRU-OFI-S0201", "https://club.test/tv2", 64601)]
        us = Usuarios(ruta)
        m = Motor("http://falso", base / "salida", us, cliente=sim, tick=0.01, registro=lambda t: None)
        m.arrancar(nueva=True, hilos=False)

        def paso(x):
            sim.avanzar(x); m._t_estado = float("-inf"); m.paso(); m.despacho.ronda(); m.paso()
        paso(1.2)
        us.ingresar("a", "clave-de-prueba-a")
        m.firmar_marco("juez-a", True)
        m.aprobar("juez-a", m.e["expedientes"][0]["id"], 1, "filtracion", None, None)
        for x in (1.4, 2.1, 2.6, 3.0, 3.2):
            m.vista_bandeja(JA); paso(x)
        u2 = m.e["expedientes"][0]["ubicaciones"][1]
        assert u2["decision"]["tipo"] == "ampliacion_dinamica", u2["decision"]["tipo"]  # premisa
        sim.lista_reclamos.append({"id": "R-077", "minuto": 3.3, "dominio": "ferreteria.club.test",
                                   "proveedor": "aurora", "mensaje": "somos un comercio"})
        m._t_reclamos = float("-inf"); m._paso_reclamos()
        m.resolver_reclamo("juez-a", "R-077", "levantar_y_reemplazar", None)
        for x in (3.6, 4.2, 5.0):
            paso(x)
        cls.reem = [o for o in m.e["ordenes"].values() if o.get("origen") == "reemplazo_reclamo" and o["n"] == 2]
        cls.vistas = {o["orden_id"]: json.loads(json.dumps(m.vista_orden_publica(o["orden_id"]), default=str)) for o in cls.reem}
        cls.registro = json.loads(json.dumps(m.vista_registro(), default=str))

    @classmethod
    def tearDownClass(cls):
        for p in cls.parches:
            p.stop()
        cls.dir.cleanup()

    def pintar(self, pagina, rutas, ruta, clase):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({k: [200, json.dumps(v)] for k, v in rutas.items()}, f)
        try:
            r = subprocess.run([NODE, str(RAIZ / "tests" / "arnes_dom.js"), str(JS / "comun.js"), str(JS / pagina), f.name,
                                ruta, ""], capture_output=True, text=True, timeout=60, env={"APPCLASS": clase, "PATH": ""})
        finally:
            Path(f.name).unlink()
        o = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(o["errores"], [])
        return [x.strip() for x in o["texto"].split("|") if x.strip()]

    def test_premisa_hay_reemplazo_en_la_ubicacion_ampliada(self):
        self.assertTrue(self.reem)

    def test_la_orden_publica_dice_que_se_decidio_al_resolver_el_reclamo(self):
        for oid, v in self.vistas.items():
            t = self.pintar("orden.js", {"/api/publico/ordenes/" + oid: v}, "/orden/" + oid, "publico app-orden")
            self.assertNotIn("Ampliación automática", t)
            self.assertIn("Decidida al resolver el reclamo R-077 ·", t)

    def test_el_registro_no_la_rotula_ampliacion(self):
        t = self.pintar("transparencia.js", {"/api/publico/registro": self.registro}, "/transparencia", "publico app-registro")
        ids = {o["orden_id"] for o in self.reem}
        filas = [b for b in self.registro["bloqueos"] if b["orden_id"] in ids]
        self.assertTrue(filas)  # premisa: el reemplazo llegó al registro
        for k, x in enumerate(t):
            if x.startswith("Decidida por") and "R-077" in x:
                self.assertNotEqual(t[k - 1], "Ampliación automática", t[k - 2:k + 1])


if __name__ == "__main__":
    unittest.main()
