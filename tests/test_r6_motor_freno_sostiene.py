"""Revisión ola D (motor, g-colateral-2, variante). Contrato: tras «Frenar y levantar» de la ubicación dueña de una
orden por IP que otra ubicación sostiene, el reemplazo por reclamo NO deja sin bloqueo el stream de la ubicación que
sostiene (queda un bloqueo vigente por nombre sobre su host en cada proveedor que acepta dominio), y no vuelve a
bloquear el de la frenada."""
from unittest import mock
from marca.motor import VIGENTES
from tests import simulador_falso
from tests import test_r3b_turnos2 as t2
from tests.test_contratos_ronda2 import ConPartido, ronda


class TestFrenoSostiene(ConPartido):
    armar = t2.TestLevantarNoDesarmaOtraUbicacion.armar

    def test_la_que_sostiene_sigue_bloqueada(self):
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
        viv = [(o["proveedor"], o["tipo"], o["objetivo"], o["exp"], o["n"]) for o in motor.e["ordenes"].values()
               if o["estado"] in VIGENTES and not o.get("levantar")]
        print("\nU2 (frenada):", u2["host"], u2["ip"], u2["estado"], "| U3 (sostiene):", u3["host"], u3["ip"], u3["estado"])
        print("VIGENTES:", viv)
        for o in motor.e["ordenes"].values():
            print("  ORD", o["orden_id"][:24], o["proveedor"], o["tipo"], o["objetivo"], o["estado"], o["origen"], "lal=", bool(o.get("levantar_al_liberar")), "lev=", bool(o.get("levantar")), "rec=", o.get("reclamo"))
        print("U2 levantada_por_freno:", u2.get("levantada_por_freno"))
        dom = [x["id"] for x in motor.e["proveedores"] if "dominio" in (x.get("acepta") or x.get("tipos") or [])] \
            if isinstance(motor.e["proveedores"], list) else None
        print("PROVEEDORES:", motor.e["proveedores"] if not isinstance(motor.e["proveedores"], list) else dom)
        self.assertTrue([v for v in viv if v[2] == u3["host"] or v[2] == u3["ip"]],
                        "el stream de la ubicación que sostenía quedó sin bloqueo")
        reemp = [o for o in motor.e["ordenes"].values() if o["origen"] == "reemplazo_reclamo"]
        self.assertFalse([o for o in reemp if o["objetivo"] == u2["host"]], "el reemplazo volvió a bloquear la frenada")
