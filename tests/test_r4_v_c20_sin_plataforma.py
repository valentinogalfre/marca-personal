"""Contrato C20 (f-integridad-3): sin entradas nuevas en la auditoría, la huella entregada es la que la plataforma
publicó al cierre, con o sin plataforma. Apagar la plataforma (y el simulador) después del cierre y recién ahí correr
`exportar` no puede producir otra huella solo porque estado.json siguió avanzando el minuto."""

import json
import tempfile
import unittest
from pathlib import Path

from marca.__main__ import exportar_paquete
from marca.exportar import huella_paquete
from marca.simulador import ErrorRed
from marca.verificar import verificar
from tests.test_motor_verificar import correr_partido
from tests.test_paquete import cerrar


class _SimuladorCaido:
    def ordenes(self, proveedor):
        raise ErrorRed("sin conexión")

    def estado(self):
        raise ErrorRed("sin conexión")


class TestHuellaConPlataformaApagada(unittest.TestCase):
    def test_sin_entradas_nuevas_se_entrega_el_paquete_publicado(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            motor, sim, entrega, _ = correr_partido(base)
            salida = motor.salida
            try:
                self.assertTrue(motor.e["hitos"].get("exportado"), "el partido falso tiene que haber cerrado")
                # La plataforma sigue corriendo después del cierre: el minuto de estado.json avanza.
                for m in (26.0, 27.0, 28.5):
                    sim.avanzar(m)
                    motor._t_estado = float("-inf")
                    motor.paso()
                    motor.despacho.ronda()
                    motor.paso()
                with motor.candado:
                    motor.guardar()
                    publicada = (motor.e["hitos"].get("paquete") or {}).get("huella")
            finally:
                cerrar(motor)
            self.assertIsNotNone(publicada)
            self.assertEqual(huella_paquete(entrega), publicada)
            lineas_antes = (salida / "auditoria.jsonl").read_bytes()
            self.assertGreater(json.loads((salida / "estado.json").read_text(encoding="utf-8"))["minuto"], 25.2)
            textos = []
            rc = exportar_paquete(salida, base / "partido-final", cliente=_SimuladorCaido(), imprimir=textos.append)
            self.assertEqual(rc, 0, textos)
            self.assertEqual((salida / "auditoria.jsonl").read_bytes(), lineas_antes, "no hubo entradas nuevas")
            self.assertEqual(huella_paquete(base / "partido-final"), publicada, textos)
            self.assertIn(f"Huella del paquete: {publicada}", textos)
            self.assertEqual(verificar(base / "partido-final", huella_publicada=publicada).fallas, 0)


if __name__ == "__main__":
    unittest.main()
