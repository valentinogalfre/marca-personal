"""R3B · C20 (fila E): con el partido ya exportado, un pedido de testigos rearma el paquete.

Contrato: después de `hitos.exportado`, el paquete de `entrega/` y su huella en `hitos.paquete` reflejan los
testigos más recientes; antes del cierre, pedir testigos no exporta nada.
"""
import json
import unittest

from marca.exportar import huella_paquete
from tests.test_contratos_ronda2 import ConPartido
from tests.test_robustez import entradas


class TestPedidoDeTestigosReexporta(ConPartido):
    def test_con_el_partido_exportado_el_paquete_trae_los_testigos_nuevos(self):
        motor, sim, _ = self.preparar()
        motor.despacho.ronda()
        motor.e["hitos"]["exportado"] = True
        destino = motor.exportar_entrega()
        antes = len(entradas(motor, "exportacion"))
        sim.avanzar(3.0)  # cambian los estados en el simulador: los testigos nuevos son otros
        motor.pedir_testigos()
        motor._paso_pedido_testigos()
        self.assertEqual(len(entradas(motor, "exportacion")), antes + 1)
        propios = json.loads((motor.salida / "testigos" / "proveedores.json").read_text(encoding="utf-8"))
        copiados = json.loads((destino / "testigos" / "proveedores.json").read_text(encoding="utf-8"))
        self.assertEqual(copiados, propios)
        self.assertEqual(motor.e["hitos"]["paquete"]["huella"], huella_paquete(destino))

    def test_antes_del_cierre_pedir_testigos_no_exporta(self):
        motor, sim, _ = self.preparar()
        motor.despacho.ronda()
        motor.pedir_testigos()
        motor._paso_pedido_testigos()
        self.assertEqual(entradas(motor, "exportacion"), [])
        self.assertNotIn("paquete", motor.e["hitos"])


if __name__ == "__main__":
    unittest.main()
