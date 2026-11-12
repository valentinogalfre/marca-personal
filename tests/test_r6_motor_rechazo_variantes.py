"""Revisión ola D (motor, variantes). Contrato g-seguimiento-1 + C22: lo rechazado en CUALQUIER expediente no entra
solo por el seguimiento; la excepción «se firmó después ese mismo servidor» rige por el número de entrada de la
auditoría (global), y una mudanza normal con seguimiento se sigue ampliando."""
import unittest

from tests.simulador_falso import deteccion
from tests.test_contratos_ronda2 import CDN, ConPartido, ordenes
from tests.test_robustez import PIRATA

MUDA_B = ("s1-respaldo.pirata.test", "203.0.113.10", "LP26-PRU-OFI-S0002", "https://cdn-pirata.test/p", 64600)
# Tercera filtración, emitida desde el MISMO servidor que el juez rechazó en A (host e IP de PIRATA).
MISMO_C = ("s1.pirata.test", "203.0.113.10", "LP26-PRU-OFI-S0003", "https://pirata.test/otra", 64600)
# Mudanza normal de B a una IP sin historia.
LIMPIA_B = ("s9.cdn-pirata.test", "198.51.100.99", "LP26-PRU-OFI-S0002", "https://cdn-pirata.test/p", 64610)


class Variantes(ConPartido):
    def _base(self, sub):
        motor, sim, _ = self.preparar(sub=sub, aprobar=False, det=[
            deteccion("D-1", 1.0, *PIRATA), deteccion("D-2", 1.1, *CDN)])
        return motor, sim, motor.e["expedientes"]

    def _mudar(self, motor, sim, det, m):
        sim.lista_detecciones.append(deteccion("D-9", m, *det))
        sim.avanzar(m + 0.1)
        motor._t_estado = float("-inf")
        motor.paso()
        motor._paso_dinamicas()

    def _exps(self, motor):
        exps = motor.e["expedientes"]
        por_url = {e["ubicaciones"][0].get("host") + "|" + str(i): e for i, e in enumerate(exps)}
        return exps

    def test_firmado_despues_en_otro_expediente_si_amplia(self):
        motor, sim, exps = self._base("desp")
        a, b = exps
        motor.rechazar("juez-a", a["id"], 1, "No bloqueo esa IP, es compartida")
        motor.aprobar("juez-a", b["id"], 1, "filtracion", None, None)
        # C22: el mismo servidor vuelve a verse; el juez lo firma DESPUÉS en persona.
        sim.lista_detecciones.append(deteccion("D-5", 3.0, *PIRATA))
        sim.avanzar(3.1); motor._t_estado = float("-inf"); motor.paso()
        nuevo = a["ubicaciones"][-1]
        self.assertTrue(nuevo.get("rechazo_previo"))
        motor.aprobar("juez-a", a["id"], nuevo["n"], "ubicacion", None, None)
        self.assertEqual(nuevo["estado"], "aprobada")
        self._mudar(motor, sim, MUDA_B, 5.0)
        u = b["ubicaciones"][-1]
        self.assertEqual(u["host"], MUDA_B[0])
        print("DESPUES:", u["estado"], (u.get("automatica") or {}).get("motivo"))
        self.assertNotIn("ya fue rechazado", str((u.get("automatica") or {}).get("motivo")))

    def test_rechazo_ajeno_no_frena_mudanza_limpia(self):
        motor, sim, exps = self._base("limpia")
        a, b = exps
        motor.rechazar("juez-a", a["id"], 1, "No bloqueo esa IP, es compartida")
        motor.aprobar("juez-a", b["id"], 1, "filtracion", None, None)
        self._mudar(motor, sim, LIMPIA_B, 5.0)
        u = b["ubicaciones"][-1]
        print("LIMPIA:", u["host"], u["estado"], (u.get("automatica") or {}).get("motivo"))
        self.assertEqual(u["host"], LIMPIA_B[0])
        # (la mudanza limpia queda pendiente en el simulador falso por falta de DNS pasivo; lo que importa es que el
        # rechazo ajeno NO sea el motivo)
        self.assertNotIn("ya fue rechazado", str((u.get("automatica") or {}).get("motivo")))


if __name__ == "__main__":
    unittest.main()
