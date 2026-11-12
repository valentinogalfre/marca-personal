"""Ola C, punto 12 (P3 de a-kit, kit-2 cruzado): el sitio ajeno que cuelga del nombre bloqueado puede conocerse por
OTRA ubicación (otra IP), no por la del stream. Contrato: el kit de una orden por dominio deja resolver a TODO ajeno
conocido que cuelga de ese dominio, venga de la ubicación que sea."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import simulador_falso as sf
from tests.simulador_falso import deteccion
from tests.test_contratos_ronda2 import ronda
from tests.test_robustez import motor_con

A, B = "198.51.100.50", "198.51.100.51"
HOST = "cdn.hostingbarato.test"


class TestNoCortarCruzado(unittest.TestCase):
    def setUp(self):
        for p in (mock.patch.dict(sf.DNS, {A: [HOST, "tienda-lucia.cdn.hostingbarato.test"],
                                           B: ["s2.otro-pirata.test", "panaderia-sol.cdn.hostingbarato.test"]}),
                  mock.patch.dict(sf.ASN_DE_IP, {A: 64650, B: 64650}),
                  mock.patch.dict(sf.ASN, {"64650": "Hosting Barato SA"})):
            p.start()
            self.addCleanup(p.stop)
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.motor, self.sim, usuarios = motor_con(Path(d.name) / "m")
        self.sim.lista_detecciones = [
            deteccion("D-1", 1.0, HOST, A, "LP26-PRU-OFI-S0009", "https://futbolgratis.test/vivo", 64650),
            deteccion("D-2", 1.0, "s2.otro-pirata.test", B, "LP26-PRU-OFI-S0008", "https://otro.test/vivo", 64650)]
        usuarios.ingresar("a", "clave-de-prueba-a")
        self.sim.avanzar(1.2)
        self.motor._t_estado = float("-inf")
        self.motor.paso()

    def test_el_ajeno_de_otra_ubicacion_no_se_corta(self):
        ajenos = {n for exp in self.motor.e["expedientes"] for u in exp["ubicaciones"]
                  for n in (u.get("colateral") or {}).get("ajenos") or []}
        self.assertIn("panaderia-sol.cdn.hostingbarato.test", ajenos)  # premisa: se conoce, por U de la IP B
        for exp in self.motor.e["expedientes"]:
            for u in exp["ubicaciones"]:
                self.motor.aprobar("juez-a", exp["id"], u["n"], "ubicacion", None, None)
        ronda(self.motor)
        v = self.motor.vista_proveedor("valle")
        nc = [x.get("no_cortar") or [] for x in v["vigentes"] if x["tipo"] == "dominio" and x["objetivo"] == HOST]
        self.assertTrue(nc, v["vigentes"])  # premisa: hay orden por dominio contra el CDN
        self.assertIn("tienda-lucia.cdn.hostingbarato.test", nc[0])
        self.assertIn("panaderia-sol.cdn.hostingbarato.test", nc[0])


if __name__ == "__main__":
    unittest.main()
