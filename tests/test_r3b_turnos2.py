"""Contrato [turnos-2]: levantar una ubicación nunca deja sin bloqueo a otra ubicación aprobada que no se levantó.

Una ubicación firmada cuyo objetivo ya estaba cubierto por la orden de otra ubicación no crea orden propia (queda en
`ya_cubiertos`, ESPECIFICACION «Sin duplicar objetivos»). Si después se levanta la otra (revocar con «frenar y
levantar», o «Levantar bloqueo»), ese objetivo tiene que seguir con una orden activa y no quedar vetado.
"""
import unittest

from tests.simulador_falso import deteccion
from tests.test_contratos_ronda2 import ConPartido, ronda
from marca.motor import ErrorAccion

S2 = ("s2.pirata.test", "203.0.113.11", "LP26-PRU-OFI-S0001", "https://pirata.test/vivo", 64600)
S1 = ("s1.pirata.test", "203.0.113.10", "LP26-PRU-OFI-S0001", "https://pirata.test/vivo", 64600)
RESP = ("s1-respaldo.pirata.test", "203.0.113.10", "LP26-PRU-OFI-S0007", "https://otro-pirata.test/vivo", 64600)


class TestLevantarNoDesarmaOtraUbicacion(ConPartido):
    def armar(self):
        motor, sim, _ = self.preparar(det=[deteccion("D-1", 1.0, *S2)], alcance="filtracion")
        ronda(motor)

        def paso(m):
            sim.avanzar(m)
            motor._t_estado = float("-inf")  # «nunca»: en 3.9 el reloj monotónico arranca cerca de 0
            motor.paso()
        sim.lista_detecciones.append(deteccion("D-2", 1.5, *S1))  # se muda a s1: ampliación automática (u2)
        paso(1.6)
        ronda(motor)
        e1 = motor.e["expedientes"][0]
        u2 = e1["ubicaciones"][1]
        self.assertEqual(u2["decision"]["tipo"], "ampliacion_dinamica")
        sim.lista_detecciones.append(deteccion("D-3", 2.0, *RESP))  # misma IP, otro nombre: la firma el juez
        paso(2.1)
        e3 = motor.e["expedientes"][1]
        u3 = e3["ubicaciones"][0]
        motor.aprobar("juez-a", e3["id"], u3["n"], "ubicacion", None, None)
        ronda(motor)
        self.assertEqual(u3["decision"]["tipo"], "firma")
        self.assertTrue(u3["decision"]["ya_cubiertos"])  # precondición: se apoya en las órdenes de u2
        return motor, e1, u2, u3

    def sin_bloqueo(self, motor, u3):
        faltan = []
        for pid, objs in u3["decision"]["propuesta_aplicada"]["objetivos_por_proveedor"].items():
            for ob in objs:
                if not motor.objetivo_activo(pid, ob["tipo"], ob["objetivo"]):
                    faltan.append((pid, ob["tipo"], ob["objetivo"]))
                if [ob["tipo"], ob["objetivo"]] in motor.e["vetados"]:
                    faltan.append(("vetado", ob["tipo"], ob["objetivo"]))
        return faltan

    def test_revocar_y_levantar_no_deja_sin_bloqueo_a_la_firmada_en_persona(self):
        motor, e1, _, u3 = self.armar()
        r = motor.revocar_dinamica("juez-a", e1["id"], "Saco lo automático.", levantar=True)
        ronda(motor, 2)
        self.assertEqual(self.sin_bloqueo(motor, u3), [])
        self.assertIn("Se mantiene", r["aviso"] or "")

    def test_levantar_ubicacion_no_deja_sin_bloqueo_a_la_firmada_en_persona(self):
        motor, e1, u2, u3 = self.armar()
        try:
            motor.levantar_ubicacion("juez-a", e1["id"], u2["n"], "Ya no transmite ahí.")
        except ErrorAccion as ex:
            self.assertIn("Se mantiene", str(ex))
        ronda(motor, 2)
        self.assertEqual(self.sin_bloqueo(motor, u3), [])


if __name__ == "__main__":
    unittest.main()
