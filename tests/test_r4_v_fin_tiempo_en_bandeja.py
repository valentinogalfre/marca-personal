"""f-humano-1. Contrato: el expediente y el acta no le atribuyen al juez un tiempo «con el expediente abierto» que la
plataforma no mide. Lo que se mide es desde que el pedido le apareció en la bandeja hasta que firmó, y así se dice."""
import tempfile
import unittest
from pathlib import Path

from tests.simulador_falso import deteccion
from tests.test_robustez import PIRATA, cerrar_motores, motor_con

JUEZ_B = {"usuario": "b", "juez_id": "juez-b", "rol": "juez", "nombre": "Dr. B"}


class TestTiempoEnBandeja(unittest.TestCase):
    def tearDown(self):
        cerrar_motores()

    def test_no_dice_expediente_abierto_si_el_juez_no_volvio(self):
        from marca.exportar import exportar
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            motor, sim, _ = motor_con(base)
            sim.lista_detecciones = [deteccion("D-1", 10.5, *PIRATA)]
            sim.avanzar(10.7)
            motor._t_estado = float("-inf")
            motor.paso()
            sim.avanzar(11.2)
            pend = motor.vista_bandeja(JUEZ_B)["pendientes"]     # única vez que el pedido se le muestra
            self.assertEqual(len(pend), 1)
            exp_id = motor.e["expedientes"][0]["id"]
            sim.avanzar(18.8)                                    # 7,6 min sin ningún pedido del juez
            motor._t_estado = float("-inf")
            motor.paso()
            motor.aprobar("juez-b", exp_id, 1, "ubicacion", None, None)
            with motor.candado:
                motor.guardar()
            paquete = exportar(motor.salida, base / "paquete")
            md_exp = (paquete / "expedientes" / f"{exp_id}.md").read_text(encoding="utf-8")
            actas = [p.read_text(encoding="utf-8") for p in paquete.rglob("acta*.md")]
            self.assertTrue(actas)
            for texto in [md_exp] + actas:
                self.assertNotIn("expediente abierto", texto.lower())
            self.assertRegex(md_exp, r"el pedido llegó a la bandeja del juez \d+,\d min antes de que firmara")
            self.assertTrue(any("Pedido en la bandeja antes de firmar" in a for a in actas))


if __name__ == "__main__":
    unittest.main()
