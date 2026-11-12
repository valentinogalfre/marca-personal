"""Ola C, punto 3. Contrato (robustez-2): una reanudación de la plataforma no convierte, por sí sola, una mudanza ampliable en un
pedido para firmar en persona. Las sesiones y la actividad de los jueces viven en memoria y se pierden al reiniciar;
mientras la plataforma lleva menos de PRESENCIA_S desde que arrancó y el juez todavía no volvió a entrar, la mudanza
espera (sin «definitivo»). Si el juez entra en ese lapso, se amplía. Pasado ese lapso sin que entre, rige la regla de
siempre (ausencia → firma en persona, definitivo)."""
import time

from marca import motor as motor_mod
from marca.motor import Motor
from marca.usuarios import Usuarios

from tests.simulador_falso import deteccion
from tests.test_contratos_ronda2 import ConPartido, ronda
from tests.test_robustez import MOTORES

S2 = ("s2.pirata.test", "203.0.113.11", "LP26-PRU-OFI-S0001", "https://pirata.test/vivo", 64600)


class TestReanudarPresencia(ConPartido):
    def _caida_con_mudanza(self):
        motor, sim, _ = self.preparar(alcance="filtracion")
        ronda(motor, 2)
        # La misma sesión aparece en otro servidor mientras la plataforma está caída.
        sim.lista_detecciones.append(deteccion("D-2", 1.5, *S2))
        sim.avanzar(1.6)
        motor.guardar()
        motor.despacho._pool.shutdown(wait=False)
        motor.auditoria.cerrar()
        usuarios = Usuarios(self.base / "p" / "jueces.json")   # proceso nuevo: sin sesiones ni actividad
        otro = Motor("http://falso", motor.salida, usuarios, cliente=sim, tick=0.01, registro=lambda t: None)
        otro.arrancar(nueva=False, hilos=False)
        MOTORES.append(otro)
        otro._t_estado = float("-inf")
        otro.paso()                                             # primer ciclo: antes de que la web atienda
        return otro, usuarios, otro.e["expedientes"][0]["ubicaciones"][1]

    def test_juez_que_vuelve_a_entrar_tras_el_reinicio_recibe_la_ampliacion(self):
        motor, usuarios, u2 = self._caida_con_mudanza()
        self.assertEqual(u2["estado"], "pendiente")
        self.assertFalse(u2["automatica"].get("definitivo"), u2["automatica"])
        self.assertNotIn("no tenía la plataforma abierta", u2["automatica"].get("motivo") or "")
        usuarios.marcar_actividad("juez-a")                     # el juez vuelve a entrar
        motor._t_estado = float("-inf")
        motor.paso()
        self.assertEqual(u2["estado"], "aprobada", u2["automatica"])
        self.assertEqual((u2.get("decision") or {}).get("tipo"), "ampliacion_dinamica")

    def test_pasado_el_lapso_sin_que_el_juez_entre_rige_la_ausencia(self):
        motor, usuarios, u2 = self._caida_con_mudanza()
        motor._t_arranque = time.monotonic() - motor_mod.PRESENCIA_S - 1
        motor._t_estado = float("-inf")
        motor.paso()
        self.assertTrue(u2["automatica"].get("definitivo"), u2["automatica"])
        usuarios.marcar_actividad("juez-a")
        motor._t_estado = float("-inf")
        motor.paso()
        self.assertEqual(u2["estado"], "pendiente")


if __name__ == "__main__":
    import unittest
    unittest.main()
