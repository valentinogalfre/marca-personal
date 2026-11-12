"""Ola C, punto 2 (f-despacho-1): C19 después de un reinicio. Un POST sin respuesta (todavía en camino) NO se reenvía con el mismo
orden_id antes de 12 s reales desde que salió, aunque la plataforma se haya reiniciado en el medio."""
import time

from marca.motor import Motor
from marca.usuarios import Usuarios
from tests.test_contratos_ronda2 import ConPartido, eventos, ordenes
from tests.test_robustez import MOTORES


class TestReinicioConIncierta(ConPartido):
    def test_reinicio_no_acorta_los_12_s(self):
        motor, sim, _ = self.preparar()
        sim.guion["enviar_orden"] = [(502, None)] * 3   # el POST salió y no hubo respuesta útil
        motor.despacho.ronda()

        ids = sorted(o["orden_id"] for o in ordenes(motor))
        self.assertTrue(all(o["incierta"] for o in ordenes(motor)))
        motor.guardar()
        motor.auditoria.cerrar()
        # kill -9 y reinicio inmediato (2 s después, como un operador rápido o un supervisor)
        u = Usuarios(self.base / "p" / "jueces.json")
        u.ingresar("a", "clave-de-prueba-a")
        m2 = Motor("http://falso", motor.salida, u, cliente=sim, tick=0.01, registro=lambda t: None)
        m2.arrancar(nueva=False, hilos=False)
        MOTORES.append(m2)
        posts_antes = len(eventos(sim, "orden_recibida")) + len(eventos(sim, "orden_rechazada"))
        for _ in range(3):
            for o in ordenes(m2):
                o["t_error"] = None   # sin esperas entre consultas, sin tocar t_post
            m2.despacho.ronda()
        reenviadas = sorted(e["orden_id"] for e in eventos(sim, "orden_recibida"))
        self.assertEqual(posts_antes, 0)
        self.assertEqual(reenviadas, [], "se reenvió antes de 12 s desde que salió el POST original")
