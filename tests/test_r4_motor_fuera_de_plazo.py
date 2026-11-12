"""Ola C (f-desconocido-1): en los últimos segundos reales del partido (pasado fin − margen_envio) una firma queda
registrada pero el despacho ya no manda nada. Contrato: «una firma que la plataforma sabe que no puede salir nunca no
se presenta como bloqueo»: aprobar() devuelve un aviso llano (TEXTO_FIRMA_TARDE, criterio del verificador) y las
órdenes que no salieron quedan marcadas no_enviada en la vista (no «por enviar» a secas). El margen no cambia."""
import tempfile
import unittest
from pathlib import Path

from tests.simulador_falso import deteccion
from tests.test_robustez import PIRATA, motor_con

from marca.motor import TEXTO_FIRMA_TARDE as TEXTO


class TestFirmaTrasElCorte(unittest.TestCase):
    def armar(self, firma_min):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        motor, sim, usuarios = motor_con(Path(d.name) / "p")
        sim.acelerar = 60.0
        sim.lista_detecciones = [deteccion("D-1", firma_min - 0.1, *PIRATA)]
        usuarios.ingresar("b", "clave-de-prueba-b")
        sim.avanzar(firma_min)
        motor._t_estado = float("-inf")
        motor.paso()
        return motor, sim, motor.e["expedientes"][0]

    def test_tras_el_corte_la_respuesta_avisa(self):
        motor, sim, exp = self.armar(18.6)  # fin 20, margen 2 min de partido a ×60
        self.assertGreaterEqual(motor.ahora(), motor.fin_min() - motor.margen_envio())  # premisa
        r = motor.aprobar("juez-b", exp["id"], 1, "ubicacion", None, None)
        self.assertEqual(r["aviso"], TEXTO)
        for _ in range(3):
            motor.despacho.ronda()
        self.assertEqual(sum(1 for x in sim.registro if x["evento"] == "orden_recibida"), 0)
        vistas = [motor.vista_orden(o) for o in motor.e["ordenes"].values()]
        self.assertTrue(vistas)
        self.assertTrue(all(x["no_enviada"] and x["motivo"] for x in vistas), vistas)

    def test_antes_del_corte_no_avisa(self):
        motor, sim, exp = self.armar(14.0)  # juez-b de turno desde el 10
        r = motor.aprobar("juez-b", exp["id"], 1, "ubicacion", None, None)
        self.assertIsNone(r["aviso"])
        motor.despacho.ronda()
        self.assertFalse(any(motor.vista_orden(o)["no_enviada"] for o in motor.e["ordenes"].values()))


if __name__ == "__main__":
    unittest.main()
