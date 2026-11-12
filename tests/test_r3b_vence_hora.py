"""R3B · C26 (textos-7): la tarjeta del juez recibe la hora de vencimiento calculada por el motor.

Contrato: `vista_ubicacion(...).propuesta.vence_hora` es la misma hora que dice la orden pública para ese
`vence_min`; la propuesta guardada (y sellada) no lleva ese campo.
"""
import unittest

from tests.test_contratos_ronda2 import ConPartido, ordenes


class TestVenceHora(ConPartido):
    def test_la_vista_trae_la_hora_de_la_orden_y_lo_guardado_no_cambia(self):
        motor, sim, _ = self.preparar()
        exp = motor.e["expedientes"][0]
        u = exp["ubicaciones"][0]
        v = motor.vista_ubicacion(exp, u)
        o = [x for x in ordenes(motor) if x["vence_min"] == u["propuesta"]["vence_min"]][0]
        publica = motor.vista_orden_publica(o["orden_id"])
        self.assertIn(f"(hora {v['propuesta']['vence_hora']})", publica["texto_llano"])
        self.assertTrue(v["propuesta"]["vence_hora"])
        self.assertNotIn("vence_hora", u["propuesta"])
        self.assertNotIn("vence_hora", u["sellado"]["propuesta"])


if __name__ == "__main__":
    unittest.main()
