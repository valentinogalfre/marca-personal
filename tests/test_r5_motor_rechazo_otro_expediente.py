"""Revisión ola C (seguimiento). Contrato C22 + f-turnos-1: lo que un juez rechazó (una IP, un nombre) nunca se bloquea
solo por el seguimiento, TAMPOCO si lo trae la mudanza de OTRA filtración (otro expediente) que cae en esa misma IP."""
import unittest

from tests.simulador_falso import deteccion
from tests.test_contratos_ronda2 import CDN, ConPartido, ordenes
from tests.test_robustez import PIRATA

# Otra filtración (marca S0002, página cdn-pirata.test) que se muda a la IP que el juez rechazó en el expediente de S0001.
MUDA_B = ("s1-respaldo.pirata.test", "203.0.113.10", "LP26-PRU-OFI-S0002", "https://cdn-pirata.test/p", 64600)


class TestRechazoEnOtroExpediente(ConPartido):
    def test_mudanza_de_otra_filtracion_a_la_ip_rechazada_no_se_amplia_sola(self):
        motor, sim, _ = self.preparar(aprobar=False, det=[deteccion("D-1", 1.0, *PIRATA), deteccion("D-2", 1.1, *CDN)])
        exps = motor.e["expedientes"]
        self.assertEqual(len(exps), 2)  # premisa: dos filtraciones distintas
        exp_a = next(e for e in exps if e["ubicaciones"][0]["host"] == PIRATA[0])
        exp_b = next(e for e in exps if e["ubicaciones"][0]["host"] == CDN[0])
        motor.rechazar("juez-a", exp_a["id"], 1, "No bloqueo esa IP, es compartida")
        motor.aprobar("juez-a", exp_b["id"], 1, "filtracion", None, None)  # «Firmar y seguir» en la otra filtración
        sim.lista_detecciones.append(deteccion("D-9", 5.0, *MUDA_B))
        sim.avanzar(5.1)
        motor._t_estado = float("-inf")
        motor.paso()
        motor._paso_dinamicas()
        u = exp_b["ubicaciones"][-1]
        self.assertEqual(u["host"], MUDA_B[0])  # premisa: la mudanza cayó en el expediente B
        rechazados = {PIRATA[0], PIRATA[1]}
        amp = [o for o in ordenes(motor) if o["exp"] == exp_b["id"] and o["n"] == u["n"]]
        self.assertFalse([o for o in amp if o["objetivo"] in rechazados],
                         f"salió sola sobre lo rechazado: {[(o['orden_id'], o['objetivo']) for o in amp]}")
        self.assertEqual(u["estado"], "pendiente", u.get("automatica"))


if __name__ == "__main__":
    unittest.main()
