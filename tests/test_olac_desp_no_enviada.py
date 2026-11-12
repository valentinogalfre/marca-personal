"""g-despacho-1. Contrato: el acta dice la VERDAD sobre por qué una orden no salió. «no enviada (el partido terminaba)»
es solo para la orden que cortó el margen del final; una orden firmada mucho antes que esperó toda la segunda parte la
ratificación del entrante, o que se mandó y el proveedor nunca confirmó, no puede figurar como cortada por el final."""
from marca.exportar import estado_legible
from tests.simulador_falso import PARTIDO
from tests.test_contratos_ronda2 import ConPartido, ordenes

CORTE = "el partido terminaba"


def _cerrar(motor, sim):
    fin = float(PARTIDO["fin_min"])
    for m in (fin - 0.5, fin + 0.2, fin + 1.5, fin + 6, fin + 6.5):
        sim.avanzar(m)
        motor._t_estado = float("-inf")
        motor._t_fin_listas = float("-inf")
        motor.paso()


class TestMotivoNoEnviada(ConPartido):
    def test_espera_de_ratificacion_no_se_atribuye_al_final(self):
        motor, sim, _ = self.preparar(aprobar=False, minuto=9.6)
        motor.aprobar("juez-a", motor.e["expedientes"][0]["id"], 1, "ubicacion", None, None)
        sim.avanzar(10.4)
        motor._t_estado = float("-inf")
        motor.paso()
        motor.despacho.ronda()
        self.assertTrue(all(o["estado"] == "espera_ratificacion" for o in ordenes(motor)))
        _cerrar(motor, sim)
        for o in ordenes(motor):
            self.assertNotIn(CORTE, estado_legible(o), o["orden_id"])

    def test_enviada_sin_confirmar_no_se_atribuye_al_final(self):
        motor, sim, _ = self.preparar(aprobar=False)
        sim.guion["enviar_orden"] = [(502, None)] * 500
        motor.aprobar("juez-a", motor.e["expedientes"][0]["id"], 1, "ubicacion", None, None)
        motor.despacho.ronda()
        _cerrar(motor, sim)
        for o in ordenes(motor):
            self.assertIsNotNone(o["enviada_min"])
            self.assertNotIn(CORTE, estado_legible(o), o["orden_id"])
