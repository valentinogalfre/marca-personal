"""Ola C, punto 4 (variante de turnos-2): tras «Frenar y levantar» con un bloqueo mantenido porque otra ubicación
firmada lo necesita, el juez levanta también esa otra ubicación.

Contrato: «lo que el juez de turno levantó, y nadie más necesita, se levanta»: levantar la ubicación dependiente
no da «no tiene bloqueos activos» y levanta (y veta) los bloqueos que se habían mantenido solo por ella.
"""
from marca.motor import ErrorAccion
from tests import test_r3b_turnos2 as t2
from tests.test_contratos_ronda2 import ConPartido, ronda


class TestLevantarLaDependienteLiberaElBloqueo(ConPartido):
    armar = t2.TestLevantarNoDesarmaOtraUbicacion.armar

    def test_levantar_la_dependiente_despues_de_frenar_y_levantar(self):
        motor, e1, u2, u3 = self.armar()
        r = motor.revocar_dinamica("juez-a", e1["id"], "Saco lo automático.", levantar=True)
        self.assertIn("Se mantiene", r["aviso"] or "")
        ronda(motor, 2)
        e3 = [x for x in motor.e["expedientes"] if any(u is u3 for u in x["ubicaciones"])][0]
        try:
            motor.levantar_ubicacion("juez-a", e3["id"], u3["n"], "Ya no hace falta.")
        except ErrorAccion as e:
            self.fail(f"no se puede levantar la ubicación firmada en persona: {e}")
        ronda(motor, 2)
        de_u2 = [o for o in motor.e["ordenes"].values() if o["exp"] == e1["id"] and o["n"] == u2["n"]]
        vivas = [(o["proveedor"], o["objetivo"]) for o in de_u2
                 if o["estado"] in ("recibida", "aplicada") and not o.get("levantar")]
        self.assertEqual(vivas, [])
        for o in de_u2:
            self.assertIn([o["tipo"], o["objetivo"]], motor.e["vetados"])

    def test_sin_freno_previo_la_dependiente_sigue_sin_bloqueos_propios(self):
        """Si nadie quiso levantar el bloqueo prestado, levantar la dependiente no toca las órdenes de otra."""
        motor, e1, u2, u3 = self.armar()
        e3 = [x for x in motor.e["expedientes"] if any(u is u3 for u in x["ubicaciones"])][0]
        with self.assertRaises(ErrorAccion):
            motor.levantar_ubicacion("juez-a", e3["id"], u3["n"], "Ya no hace falta.")
        self.assertFalse([o for o in motor.e["ordenes"].values() if o["exp"] == e1["id"] and o["n"] == u2["n"]
                          and o.get("levantar")])
