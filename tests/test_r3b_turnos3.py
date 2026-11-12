"""Verificación turnos-3: después de «Frenar las próximas mudanzas», el juez de turno tiene que poder levantar
con su firma las ampliaciones automáticas que siguen vigentes (también las heredadas del turno anterior).

Contrato: «el juez de turno siempre puede levantar, con su firma, cualquier ampliación automática vigente de una
orden dinámica, aunque antes la haya frenado sin levantar; y la bandeja se lo ofrece mientras haya alguna».
"""
from marca.motor import ErrorAccion

from tests.test_contratos_ronda2 import ConPartido, ordenes, ronda
from tests.test_contratos_ronda2b import mudanza

B = {"usuario": "b", "juez_id": "juez-b", "rol": "juez", "nombre": "Dr. B"}


class TestFrenarDespuesLevantar(ConPartido):
    def heredada(self):
        """juez-a otorga la dinámica, se amplía sola (u2) en su turno y el turno pasa a juez-b."""
        motor, sim, usuarios = self.preparar(alcance="filtracion")
        ronda(motor)
        exp = mudanza(motor, sim)
        ronda(motor)
        self.assertEqual(exp["ubicaciones"][1]["decision"]["tipo"], "ampliacion_dinamica")
        self.assertEqual(exp["ubicaciones"][1]["decision"]["juez_id"], "juez-a")
        sim.avanzar(10.5)
        motor._t_estado = float("-inf")  # «nunca»: en 3.9 el reloj monotónico arranca cerca de 0
        motor.paso()
        usuarios.ingresar("b", "clave-de-prueba-b")
        motor.ratificar("juez-b")
        self.assertIn("juez-b", motor.de_turno())
        return motor, exp

    def test_frenar_y_despues_levantar_las_heredadas(self):
        motor, exp = self.heredada()
        b = motor.vista_bandeja(B)
        self.assertEqual([(d["exp"], d["ampliaciones"]) for d in b["dinamicas"]], [(exp["id"], 1)])
        r = motor.revocar_dinamica("juez-b", exp["id"], "")          # «Frenar las próximas mudanzas»
        self.assertEqual(r["levantadas"], [])
        self.assertEqual(len(motor.ampliadas_vigentes(exp)), 1)
        # El juez cambia de idea: «Frenar y levantar» tiene que levantar la ampliación vigente.
        r = motor.revocar_dinamica("juez-b", exp["id"], "Cambio de criterio.", levantar=True)
        self.assertEqual(r["levantadas"], [2])
        self.assertTrue(all(o.get("levantar") for o in ordenes(motor) if o["n"] == 2))
        self.assertFalse(any(o.get("levantar") for o in ordenes(motor) if o["n"] == 1))
        self.assertEqual(motor.ampliadas_vigentes(exp), [])

    def test_la_bandeja_ofrece_levantar_mientras_haya_ampliaciones(self):
        motor, exp = self.heredada()
        motor.revocar_dinamica("juez-b", exp["id"], "")
        b = motor.vista_bandeja(B)
        ofrecidas = [(d["exp"], d["ampliaciones"]) for d in b["dinamicas"]]
        en_historial = [(h["expediente"]["id"], h["n"]) for h in b["historial"]]
        # La bandeja tiene que ofrecer la ampliación vigente en algún lugar con acción de levantar.
        self.assertTrue((exp["id"], 1) in ofrecidas or (exp["id"], 2) in en_historial,
                        f"dinamicas={ofrecidas} historial={en_historial}")

    def test_frenar_dos_veces_sigue_siendo_error(self):
        """Lo que no cambia: frenar una dinámica ya frenada, sin levantar, sigue dando error."""
        motor, exp = self.heredada()
        motor.revocar_dinamica("juez-b", exp["id"], "")
        with self.assertRaises(ErrorAccion):
            motor.revocar_dinamica("juez-b", exp["id"], "")


if __name__ == "__main__":
    import unittest
    unittest.main()
