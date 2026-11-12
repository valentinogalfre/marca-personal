"""Contrato: nunca se firma fuera de turno ni en los segundos del cambio de turno."""
import unittest

from marca import turnos

TURNOS = [{"juez_id": "laura", "desde_min": -60, "hasta_min": 50},
          {"juez_id": "martin", "desde_min": 50, "hasta_min": 240}]


def est(minuto, de_turno, acelerar=6.0, finalizado=False):
    return {"minuto_actual": minuto, "acelerar": acelerar, "jueces_de_turno": de_turno, "finalizado": finalizado}


class TestTurnos(unittest.TestCase):
    def test_de_turno_con_margen(self):
        self.assertEqual(turnos.puede_firmar_con("laura", est(30.0, ["laura"]), TURNOS), (True, None))

    def test_margen_al_final(self):
        # x6: margen = max(0.05, 2 s × 6 / 60) = 0.2 min
        ok, motivo = turnos.puede_firmar_con("laura", est(49.85, ["laura"]), TURNOS)
        self.assertFalse(ok)
        self.assertIn("termina en segundos", motivo)
        self.assertTrue(turnos.puede_firmar_con("laura", est(49.7, ["laura"]), TURNOS)[0])

    def test_margen_al_final_escala_con_acelerar(self):
        self.assertFalse(turnos.puede_firmar_con("laura", est(48.5, ["laura"], acelerar=60), TURNOS)[0])
        self.assertTrue(turnos.puede_firmar_con("laura", est(47.9, ["laura"], acelerar=60), TURNOS)[0])

    def test_margen_minimo(self):
        self.assertFalse(turnos.puede_firmar_con("laura", est(49.96, ["laura"], acelerar=1), TURNOS)[0])
        self.assertTrue(turnos.puede_firmar_con("laura", est(49.9, ["laura"], acelerar=1), TURNOS)[0])

    def test_margen_al_principio(self):
        # x6: margen = max(0.02, 0.5 s × 6 / 60) = 0.05 min
        self.assertFalse(turnos.puede_firmar_con("martin", est(50.03, ["martin"]), TURNOS)[0])
        self.assertTrue(turnos.puede_firmar_con("martin", est(50.06, ["martin"]), TURNOS)[0])

    def test_saliente_no_firma(self):
        ok, motivo = turnos.puede_firmar_con("laura", est(51.0, ["martin"]), TURNOS)
        self.assertFalse(ok)

    def test_entrante_antes_de_turno(self):
        ok, motivo = turnos.puede_firmar_con("martin", est(40.0, ["laura"]), TURNOS)
        self.assertFalse(ok)
        self.assertIn("50", motivo)

    def test_nadie_de_turno(self):
        self.assertEqual(turnos.de_turno(TURNOS, 300), [])
        self.assertIsNone(turnos.primero_de_turno(TURNOS, []))
        self.assertFalse(turnos.puede_firmar_con("martin", est(300, []), TURNOS)[0])

    def test_estado_dice_otra_cosa_que_la_tabla(self):
        # Manda la respuesta fresca del simulador: si no figura de turno, no firma.
        self.assertFalse(turnos.puede_firmar_con("laura", est(30.0, []), TURNOS)[0])

    def test_partido_finalizado(self):
        self.assertFalse(turnos.puede_firmar_con("martin", est(105.0, ["martin"], finalizado=True), TURNOS)[0])

    def test_primero_segun_orden_de_turnos(self):
        self.assertEqual(turnos.primero_de_turno(TURNOS, ["martin", "laura"]), "laura")


if __name__ == "__main__":
    unittest.main()
