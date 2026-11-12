"""Ola C, puntos 6 (NV1) y 7 (NV4).

Contratos:
- NV1: una orden de reemplazo por reclamo dice, en /orden/<id> y en el registro público, la decisión que la sella
  (la resolución del reclamo: su minuto, su hora y su entrada, `decision_origen = "reclamo"`, `reclamo = R-…`), no la
  firma original de la ubicación. Las órdenes comunes siguen con la firma de la ubicación (`decision_origen =
  "ubicacion"`).
- NV4: después de que «Firmar y seguir» ratificó un seguimiento heredado, el traspaso lo dice
  (`ratificadas_al_firmar`: [{id, min, juez_id, nombre}], también en la bandeja) y `ratificar()` con ese id lo ignora en
  silencio y recibe el turno normalmente; el traspaso no se cierra solo.
"""
import unittest
from unittest import mock

from marca import sello
from marca.auditoria import leer_entradas
from tests import simulador_falso
from tests import test_contratos_ronda2b as r2b
from tests import test_r3b_seguir_sin_ratificar as t3
from tests.simulador_falso import deteccion
from tests.test_contratos_ronda2 import CDN, ConPartido, ordenes

JUEZ_B = {"usuario": "b", "juez_id": "juez-b", "rol": "juez", "nombre": "Dr. B"}


class TestDecisionDelReemplazo(ConPartido):
    def test_el_reemplazo_dice_la_resolucion_del_reclamo(self):
        motor, sim, _ = self.preparar(det=[deteccion("D-1", 1.0, *CDN)], aprobar=False)
        exp = motor.e["expedientes"][0]
        u = exp["ubicaciones"][0]
        motor.aprobar("juez-a", exp["id"], 1, "ubicacion", "ip", "Prueba: forzar IP en una red compartida")
        motor.despacho.ronda()
        sim.avanzar(3.0)
        sim.lista_reclamos = [{"id": "R-1", "minuto": 2.9, "dominio": "panaderia.test", "proveedor": "aurora"}]
        motor._t_estado = float("-inf")
        motor.paso()
        motor._t_reclamos = float("-inf")
        motor._paso_reclamos()
        r = motor.e["reclamos"]["R-1"]
        self.assertEqual(r["propuesta"]["accion"], "levantar_y_reemplazar")
        motor.resolver_reclamo("juez-a", "R-1", "levantar_y_reemplazar", "Reclamo fundado")
        res = r["resolucion"]
        self.assertGreater(res["min"], u["decision"]["min"])
        reemplazos = [o for o in ordenes(motor) if o["origen"] == "reemplazo_reclamo"]
        self.assertTrue(reemplazos)
        for m in (4.0, 6.0, 8.0):
            motor.despacho.ronda()
            sim.avanzar(m)
            motor._t_estado = float("-inf")
            motor.paso()
            motor.despacho.ronda()
        entradas = {e["n"]: e for e in leer_entradas(motor.salida / "auditoria.jsonl")}
        for o in reemplazos:
            ent = entradas[o["entrada_sello"]]
            self.assertEqual(ent["tipo"], "reclamo_resuelto")
            self.assertEqual(o["sello"], sello.calcular_sello(u["huella"], ent["hash"]))
            v = motor.vista_orden_publica(o["orden_id"])
            self.assertEqual((v["decision_min"], v["decision_origen"], v["reclamo"]), (ent["min"], "reclamo", "R-1"))
            self.assertEqual(v["decision"]["entrada"], o["entrada_sello"])
            self.assertIn("al resolver el reclamo R-1", v["decision"]["texto"])
            fila = [b for b in motor.vista_registro()["bloqueos"] if b["orden_id"] == o["orden_id"]]
            if fila:  # solo las aplicadas van al registro
                self.assertEqual((fila[0]["decision_min"], fila[0]["decision_origen"], fila[0]["reclamo"]),
                                 (ent["min"], "reclamo", "R-1"))
        self.assertTrue([b for b in motor.vista_registro()["bloqueos"] if b["decision_origen"] == "reclamo"],
                        "premisa: algún reemplazo llegó a aplicarse")
        comun = [o for o in ordenes(motor) if o["origen"] != "reemplazo_reclamo"][0]
        v = motor.vista_orden_publica(comun["orden_id"])
        self.assertEqual((v["decision_min"], v["decision_origen"], v["reclamo"]),
                         (u["decision"]["min"], "ubicacion", None))


class TestTraspasoTrasFirmarYSeguir(ConPartido):
    def setUp(self):
        super().setUp()
        for tabla, extra in ((simulador_falso.DNS, {"203.0.113.12": ["s3.pirata.test"]}),
                             (simulador_falso.ASN_DE_IP, {"203.0.113.12": 64600})):
            p = mock.patch.dict(tabla, extra)
            p.start()
            self.addCleanup(p.stop)

    def test_ratificar_lo_ya_ratificado_es_idempotente_y_se_ve(self):
        motor, sim, usuarios = self.preparar(alcance="filtracion")
        exp = r2b.TestTraspasoYRevocacion.traspaso(self, motor, sim, usuarios)
        motor.firmar_marco("juez-b", True)
        exp, u2 = t3.mudar(motor, sim, "D-2", 11.0, t3.S2)
        motor.aprobar("juez-b", exp["id"], u2["n"], "filtracion", None, None)  # «Firmar y seguir»
        tr = motor.e["traspasos"][-1]
        self.assertIsNone(tr.get("ratificado"), "recibir el turno sigue siendo un acto del juez")
        al_firmar = tr["ratificadas_al_firmar"]
        self.assertEqual([(x["id"], x["juez_id"]) for x in al_firmar], [(exp["id"], "juez-b")])
        self.assertEqual(set(al_firmar[0]), {"id", "min", "juez_id", "nombre"})
        band = motor.vista_bandeja(JUEZ_B)
        self.assertEqual(band["traspaso"]["ratificadas_al_firmar"], al_firmar)
        r = motor.ratificar("juez-b", [exp["id"]])  # la tarjeta vieja lo manda marcado: no es un error
        self.assertEqual(r["ratificadas"], [])
        self.assertIsNotNone(tr["ratificado"])
        self.assertIn(exp["id"], tr["dinamicas_ratificadas"])
        self.assertEqual(tr["dinamicas_sin_ratificar"], [])


if __name__ == "__main__":
    unittest.main()
