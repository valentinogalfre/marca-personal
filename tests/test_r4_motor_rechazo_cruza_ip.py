"""Ola C, punto 1 (f-turnos-1, prueba del verificador). Contrato C22 (extensión): lo que un juez rechazó nunca sale solo por el seguimiento, tampoco si la misma
filtración reaparece con OTRO nombre sobre la IP rechazada."""
import unittest

from tests.simulador_falso import deteccion
from tests.test_contratos_ronda2 import ConPartido, ordenes
from tests.test_contratos_ronda2b import mudanza
from tests.test_robustez import PIRATA

# Misma IP que PIRATA (203.0.113.10), otro nombre que el DNS pasivo de esa IP ya conoce.
S1B = ("s1-respaldo.pirata.test", "203.0.113.10", "LP26-PRU-OFI-S0001", "https://pirata.test/vivo", 64600)


class TestRechazoCruzaIp(ConPartido):
    def _correr(self, rechazar):
        motor, sim, _ = self.preparar(aprobar=False)
        exp = motor.e["expedientes"][0]
        if rechazar:
            motor.rechazar("juez-a", exp["id"], 1, "No bloqueo esa IP")
        exp = mudanza(motor, sim, 2.0)
        motor.aprobar("juez-a", exp["id"], 2, "filtracion", None, None)  # «Firmar y seguir»
        sim.lista_detecciones.append(deteccion("D-9", 5.0, *S1B))
        sim.avanzar(5.1)
        motor._t_estado = float("-inf")
        motor.paso()
        motor._paso_dinamicas()
        u3 = exp["ubicaciones"][-1]
        return u3, [o for o in ordenes(motor) if o["n"] == u3["n"]]

    def test_otro_nombre_en_la_ip_rechazada_no_se_amplia_solo(self):
        u3, amp = self._correr(rechazar=True)
        self.assertEqual((u3["host"], u3["estado"]), (S1B[0], "pendiente"))
        self.assertFalse([o for o in amp if o["objetivo"] in (PIRATA[0], PIRATA[1])])
        self.assertFalse(amp)
        self.assertFalse(u3["automatica"]["posible"])
        self.assertIn("ya fue rechazado en el minuto", u3["automatica"]["motivo"])  # texto NV2 del coordinador

    def test_sin_rechazo_el_seguimiento_sigue_ampliando(self):
        """Control: la regla nueva no frena el seguimiento cuando nadie rechazó nada."""
        u3, amp = self._correr(rechazar=False)
        self.assertEqual(u3["estado"], "aprobada")
        self.assertTrue(any(o["orden_id"].startswith("amp-") for o in amp))


if __name__ == "__main__":
    unittest.main()


class TestRechazoQueQuedoAtras(ConPartido):
    """Ola C (criterio del verificador de f-turnos-1): si un juez firmó DESPUÉS ese mismo servidor rechazado, el
    rechazo quedó atrás y un nombre nuevo en esa IP vuelve a entrar solo por el seguimiento."""

    def test_firma_posterior_del_mismo_servidor_libera_la_regla(self):
        motor, sim, _ = self.preparar(aprobar=False)
        exp = motor.e["expedientes"][0]
        motor.rechazar("juez-a", exp["id"], 1, "No bloqueo esa IP")
        exp = mudanza(motor, sim, 2.0)
        motor.aprobar("juez-a", exp["id"], 2, "filtracion", None, None)  # «Firmar y seguir»
        sim.lista_detecciones.append(deteccion("D-8", 3.0, *PIRATA))  # vuelve el servidor rechazado
        sim.avanzar(3.1)
        motor._t_estado = float("-inf")
        motor.paso()
        motor._paso_dinamicas()
        u3 = exp["ubicaciones"][-1]
        self.assertEqual((u3["host"], u3["estado"]), (PIRATA[0], "pendiente"))  # premisa: C22, lo decide el juez
        motor.aprobar("juez-a", exp["id"], u3["n"], "ubicacion", None, None)  # y lo firma en persona
        sim.lista_detecciones.append(deteccion("D-9", 5.0, *S1B))
        sim.avanzar(5.1)
        motor._t_estado = float("-inf")
        motor.paso()
        motor._paso_dinamicas()
        u4 = exp["ubicaciones"][-1]
        self.assertEqual(u4["host"], S1B[0])
        self.assertEqual(u4["estado"], "aprobada", u4.get("automatica"))
