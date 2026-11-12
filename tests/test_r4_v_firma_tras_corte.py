"""Contrato: una firma que la plataforma sabe que ya no puede salir nunca se presenta como bloqueo.

Escenario: x20, fin en el min 20 (margen de envío 0,667 min = 2 s reales); el juez firma en el min 19,5.
- La respuesta a aprobar trae un aviso que dice que la orden ya no llega a los proveedores.
- El simulador no recibe ningún POST (el despacho no la manda).
- El acta y el expediente exportados la muestran «no_enviada», nunca «por_enviar».
"""
import tempfile
import unittest
from pathlib import Path

from tests.simulador_falso import deteccion
from tests.test_robustez import PIRATA, cerrar_motores, motor_con


class TestFirmaTrasElCorteDeEnvio(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.base = Path(self._dir.name)

    def tearDown(self):
        cerrar_motores()
        self._dir.cleanup()

    def firmar(self, minuto):
        motor, sim, usuarios = motor_con(self.base / str(minuto))
        sim.acelerar = 20.0
        sim.lista_detecciones = [deteccion("F-1", minuto - 0.1, *PIRATA)]
        usuarios.ingresar("b", "clave-de-prueba-b")
        sim.avanzar(minuto - 0.05)
        motor._t_estado = float("-inf")
        motor.paso()
        exp = motor.e["expedientes"][0]
        sim.avanzar(minuto)
        res = motor.aprobar("juez-b", exp["id"], 1, "ubicacion", None, None)
        motor.despacho.ronda()
        return motor, sim, res

    def test_firma_tras_el_corte_avisa_y_el_acta_no_dice_por_enviar(self):
        motor, sim, res = self.firmar(19.5)
        self.assertTrue(res.get("aviso"), "el juez no se entera de que la orden ya no sale")
        self.assertIn("no llega a los proveedores", res["aviso"])
        self.assertEqual([r for r in sim.registro if r["evento"] == "orden_recibida"], [])
        for m in (20.0, 21.5, 26.0, 27.0):  # fin y cierre: se exporta la entrega
            sim.avanzar(m)
            motor._t_estado = float("-inf")
            motor.paso()
        acta = (motor.salida / "entrega" / "acta-del-partido.md").read_text(encoding="utf-8")
        self.assertNotIn("por_enviar", acta)
        self.assertNotIn("no_enviada", acta)
        # Decisión del coordinador (ola C): texto llano en el acta, no el código interno.
        self.assertIn("no enviada (el partido terminaba): 3", acta)
        for p in (motor.salida / "entrega" / "expedientes").glob("*.md"):
            texto = p.read_text(encoding="utf-8")
            self.assertNotIn("por_enviar", texto)
            self.assertNotIn("no_enviada", texto)
            self.assertIn("| no enviada (el partido terminaba) |", texto)

    def test_firma_a_tiempo_sale_sin_aviso(self):
        # Control: a 5 s reales del final (min 18,33) la orden sale y no hay aviso.
        motor, sim, res = self.firmar(18.33)
        self.assertIsNone(res.get("aviso"))
        self.assertTrue([r for r in sim.registro if r["evento"] == "orden_recibida"])


if __name__ == "__main__":
    unittest.main()
