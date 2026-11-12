"""Revisor colateral (ola C). Contrato (punto 4 de la ola C + C14): tras «Frenar y levantar» (bloqueo mantenido por
otra ubicación) y un reclamo fundado con reemplazo, cuando el juez levanta la ubicación que lo sostenía no queda
NINGÚN bloqueo vigente de la ubicación frenada: lo que el juez quiso levantar se levanta al soltarlo la última."""
from unittest import mock
from marca.motor import VIGENTES, ErrorAccion
from tests import simulador_falso
from tests import test_r3b_turnos2 as t2
from tests.test_contratos_ronda2 import ConPartido, ronda


class TestFrenoReclamoYLevantarDependiente(ConPartido):
    armar = t2.TestLevantarNoDesarmaOtraUbicacion.armar

    def test_no_queda_trabado_el_reemplazo(self):
        motor, e1, u2, u3 = self.armar()
        p = mock.patch.dict(simulador_falso.DNS, {"203.0.113.10": ["s1.pirata.test", "s1-respaldo.pirata.test",
                                                                    "kiosco.test"]})
        p.start(); self.addCleanup(p.stop)
        motor.revocar_dinamica("juez-a", e1["id"], "Saco lo automático.", levantar=True)
        ronda(motor, 2)
        sim = motor.cliente
        sim.lista_reclamos.append({"id": "R-001", "minuto": 2.3, "dominio": "kiosco.test", "proveedor": "aurora",
                                   "mensaje": "No carga."})
        motor._t_reclamos = float("-inf"); motor._paso_reclamos()
        r = motor.e["reclamos"]["R-001"]
        motor.resolver_reclamo("juez-a", "R-001", r["propuesta"]["accion"], None)
        ronda(motor, 2)
        e3 = [x for x in motor.e["expedientes"] if any(u is u3 for u in x["ubicaciones"])][0]
        motor.levantar_ubicacion("juez-a", e3["id"], u3["n"], "Ya no hace falta.")
        ronda(motor, 2)
        de_u2 = [(o["proveedor"], o["tipo"], o["objetivo"], o["origen"]) for o in motor.e["ordenes"].values()
                 if o["exp"] == e1["id"] and o["n"] == u2["n"] and o["estado"] in VIGENTES and not o.get("levantar")]
        print("\nVIGENTES DE LA FRENADA tras levantar la dependiente:", de_u2)
        try:
            motor.levantar_ubicacion("juez-a", e1["id"], u2["n"], "Lo frené.")
            print("levantar_ubicacion(u2): OK")
        except ErrorAccion as e:
            print("levantar_ubicacion(u2):", e)
        self.assertEqual(de_u2, [], "queda vigente un bloqueo de la ubicación que el juez frenó y levantó")


if __name__ == "__main__":
    import unittest; unittest.main()
