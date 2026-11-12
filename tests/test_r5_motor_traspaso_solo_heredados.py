"""Ola D (NV7): mientras el traspaso no está ratificado, la tarjeta lista en «dinamicas» solo los seguimientos
HEREDADOS. Contrato: si el juez entrante firma y sigue una filtración NUEVA antes de recibir el turno, ese seguimiento
es suyo: no aparece para ratificar (ni en la bandeja ni en la sala), `ratificar(juez, None)` le da el turno, y su
seguimiento sigue activo, sin esperar ratificación, y se amplía solo."""
import unittest
from unittest import mock

from tests import simulador_falso
from tests import test_contratos_ronda2b as r2b
from tests.simulador_falso import deteccion
from tests.test_contratos_ronda2 import ConPartido

JUEZ_B = {"usuario": "b", "juez_id": "juez-b", "rol": "juez", "nombre": "Dr. B"}
OTRA = ("tv.otra-filtracion.test", "203.0.113.30", "LP26-PRU-OFI-S0077", "https://otra-filtracion.test/vivo", 64600)
OTRA2 = ("tv2.otra-filtracion.test", "203.0.113.31", "LP26-PRU-OFI-S0077", "https://otra-filtracion.test/vivo", 64600)


class TestTraspasoSoloHeredados(ConPartido):
    def setUp(self):
        super().setUp()
        for tabla, extra in ((simulador_falso.DNS, {OTRA[1]: [OTRA[0]], OTRA2[1]: [OTRA2[0]]}),
                             (simulador_falso.ASN_DE_IP, {OTRA[1]: 64600, OTRA2[1]: 64600})):
            p = mock.patch.dict(tabla, extra)
            p.start()
            self.addCleanup(p.stop)

    def detectar(self, motor, sim, did, minuto, sitio):
        sim.lista_detecciones.append(deteccion(did, minuto, *sitio))
        sim.avanzar(minuto + 0.1)
        motor._t_estado = float("-inf")
        motor.paso()
        motor._paso_dinamicas()

    def test_el_seguimiento_propio_no_se_ofrece_para_ratificar(self):
        motor, sim, usuarios = self.preparar(alcance="filtracion")
        heredada = r2b.TestTraspasoYRevocacion.traspaso(self, motor, sim, usuarios)
        motor.firmar_marco("juez-b", True)
        self.detectar(motor, sim, "D-77", 11.0, OTRA)
        nueva = next(e for e in motor.e["expedientes"] if e is not heredada)
        u = nueva["ubicaciones"][-1]
        motor.aprobar("juez-b", nueva["id"], u["n"], "filtracion", None, None)  # «Firmar y seguir», sin recibir el turno
        tr = motor.e["traspasos"][-1]
        self.assertIsNone(tr.get("ratificado"))  # premisa: el turno todavía no se recibió
        for vista in (motor.vista_bandeja(JUEZ_B)["traspaso"], motor.vista_sala()["traspasos"][-1]):
            self.assertEqual([d["exp"] for d in vista["resumen"]["dinamicas"]], [heredada["id"]], vista["resumen"])
        motor.ratificar("juez-b", None)
        self.assertIsNotNone(tr["ratificado"])
        self.assertTrue(nueva["dinamica"]["activa"])
        self.assertFalse(nueva["dinamica"].get("requiere_ratificacion"))
        self.detectar(motor, sim, "D-78", 12.0, OTRA2)  # la filtración propia se muda: se amplía sola
        u2 = nueva["ubicaciones"][-1]
        self.assertEqual((u2["host"], u2["estado"]), (OTRA2[0], "aprobada"), u2.get("automatica"))


if __name__ == "__main__":
    unittest.main()
