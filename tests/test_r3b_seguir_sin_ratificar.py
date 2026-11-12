"""Contrato (textos-3): si la firma del juez de turno responde y registra «sigue a la filtración», la orden dinámica
de ese expediente no queda esperando ratificación: la próxima mudanza con la misma marca se amplía sola, bajo su
firma, y la auditoría de esa ampliación verifica (entrada habilitante = su decisión con alcance filtración)."""
import unittest
from unittest import mock

from marca.auditoria import leer_entradas
from marca.verificar import Informe, verificar_ampliaciones

from tests import simulador_falso
from tests.simulador_falso import deteccion
from tests.test_contratos_ronda2 import ConPartido
from tests import test_contratos_ronda2b as r2b

S2 = ("s2.pirata.test", "203.0.113.11", "LP26-PRU-OFI-S0001", "https://pirata.test/vivo", 64600)
S3 = ("s3.pirata.test", "203.0.113.12", "LP26-PRU-OFI-S0001", "https://pirata.test/vivo", 64600)


def mudar(motor, sim, det, minuto, sitio):
    sim.lista_detecciones.append(deteccion(det, minuto, *sitio))
    sim.avanzar(minuto + 0.1)
    motor._t_estado = float("-inf")  # «nunca»: en 3.9 el reloj monotónico arranca cerca de 0
    motor.paso()
    exp = motor.e["expedientes"][0]
    return exp, exp["ubicaciones"][-1]


class TestSeguirConDinamicaHeredadaSinRatificar(ConPartido):
    def setUp(self):
        super().setUp()
        # Un tercer servidor del mismo pirata, solo para esta prueba.
        for tabla, extra in ((simulador_falso.DNS, {"203.0.113.12": ["s3.pirata.test"]}),
                             (simulador_falso.ASN_DE_IP, {"203.0.113.12": 64600})):
            p = mock.patch.dict(tabla, extra)
            p.start()
            self.addCleanup(p.stop)

    def _caso(self, recibir_sin_seguimiento):
        motor, sim, usuarios = self.preparar(alcance="filtracion")
        exp = r2b.TestTraspasoYRevocacion.traspaso(self, motor, sim, usuarios)
        motor.firmar_marco("juez-b", True)
        if recibir_sin_seguimiento:
            motor.ratificar("juez-b", [])  # «Recibir sin seguimiento»
        self.assertTrue(exp["dinamica"]["requiere_ratificacion"])
        exp, u2 = mudar(motor, sim, "D-2", 11.0, S2)
        self.assertEqual(u2["estado"], "pendiente")
        r = motor.aprobar("juez-b", exp["id"], u2["n"], "filtracion", None, None)
        # Lo que la pantalla lee para decir «sigue a la filtración».
        self.assertEqual(r["alcance_efectivo"], "filtracion")
        self.assertEqual(u2["decision"]["alcance"], "filtracion")
        # El contrato: entonces la dinámica no queda en espera y la respalda el juez que firmó.
        din = exp["dinamica"]
        self.assertFalse(din["requiere_ratificacion"])
        self.assertEqual(din["respaldada_por"], "juez-b")
        # Y se nota: la mudanza siguiente se amplía sola, bajo su firma.
        exp, u3 = mudar(motor, sim, "D-3", 12.0, S3)
        self.assertEqual(u3["estado"], "aprobada", u3.get("automatica"))
        self.assertEqual(u3["decision"]["tipo"], "ampliacion_dinamica")
        self.assertEqual(u3["decision"]["bajo_orden_de"]["juez_id"], "juez-b")
        # La auditoría de esa ampliación verifica.
        todas = {e["n"]: e for e in leer_entradas(motor.salida / "auditoria.jsonl")}
        inf = Informe()
        verificar_ampliaciones(inf, todas, None)
        self.assertEqual(inf.fallas, 0, "\n".join(inf.lineas))
        return motor, exp

    def test_firmar_y_seguir_antes_de_ratificar(self):
        self._caso(False)

    def test_firmar_y_seguir_despues_de_recibir_sin_seguimiento(self):
        motor, exp = self._caso(True)
        tr = motor.e["traspasos"][-1]
        self.assertIn(exp["id"], tr["dinamicas_ratificadas"])
        self.assertNotIn(exp["id"], tr["dinamicas_sin_ratificar"])


if __name__ == "__main__":
    unittest.main()
