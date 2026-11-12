"""Ola C (motor): puntos 1, 5 y 8.

Contratos:
- Punto 1 (f-turnos-1): lo que un juez rechazó no se bloquea solo, aunque cambie de nombre: una ubicación que
  comparte IP, nombre u objetivos con una rechazada del expediente no se amplía sola (queda para firmar en persona
  con «un servidor con esta misma IP o este mismo nombre ya fue rechazado en el minuto X; queda para decidir en persona.»).
- Punto 5 (f-turnos-2): en un pedido del mismo servidor, `continuidad.de_ubicacion` es la ubicación de ESE servidor
  (la rechazada o la levantada), no la última del expediente; el `antecedente` del sellado sigue siendo la última.
- Punto 8 (guarda de vetados en aprobar, M9c): tras un reclamo resuelto con levantamiento, aprobar otra ubicación
  sobre ese mismo objetivo no crea una orden nueva: queda en `ya_cubiertos` sin `orden_id`.
"""
import unittest
from unittest import mock

from marca import canon
from tests import simulador_falso as sf
from tests.simulador_falso import deteccion
from tests.test_contratos_ronda2 import CDN, ConPartido, ordenes
from tests.test_contratos_ronda2b import S2, mudanza
from tests.test_robustez import PIRATA

S1B = ("s1-respaldo.pirata.test", PIRATA[1], "LP26-PRU-OFI-S0001", "https://pirata.test/vivo", 64600)
S1_OTRA_IP = (PIRATA[0], "203.0.113.12", "LP26-PRU-OFI-S0001", "https://pirata.test/vivo", 64600)
S3 = ("s3.pirata.test", "203.0.113.12", "LP26-PRU-OFI-S0001", "https://pirata.test/vivo", 64600)


def redetectar(motor, sim, did, minuto, srv=PIRATA):
    sim.lista_detecciones.append(deteccion(did, minuto, *srv))
    sim.avanzar(minuto + 0.1)
    motor._t_estado = float("-inf")
    motor.paso()


class ConDnsExtra(ConPartido):
    def setUp(self):
        super().setUp()
        dns = dict(sf.DNS)
        dns["203.0.113.12"] = ["s3.pirata.test", PIRATA[0]]
        p1 = mock.patch.dict(sf.DNS, dns)
        p2 = mock.patch.dict(sf.ASN_DE_IP, {"203.0.113.12": 64600})
        p1.start()
        p2.start()
        self.addCleanup(p1.stop)
        self.addCleanup(p2.stop)


class TestRechazadoNoSeBloqueaSolo(ConDnsExtra):
    def caso(self, srv):
        motor, sim, _ = self.preparar(aprobar=False)
        exp = motor.e["expedientes"][0]
        motor.rechazar("juez-a", exp["id"], 1, "Esa IP no la bloqueo: no alcanza")
        rmin = exp["ubicaciones"][0]["decision"]["min"]
        exp = mudanza(motor, sim, 2.0)
        motor.aprobar("juez-a", exp["id"], 2, "filtracion", None, None)  # «Firmar y seguir»
        self.assertTrue(exp["dinamica"]["activa"])
        redetectar(motor, sim, "D-9", 5.0, srv)
        motor._paso_dinamicas()
        u3 = exp["ubicaciones"][-1]
        self.assertEqual((u3["host"], u3["ip"]), (srv[0], srv[1]))
        self.assertEqual(u3["estado"], "pendiente")
        self.assertEqual([o for o in ordenes(motor) if o["n"] == u3["n"]], [], "no sale ninguna orden amp-")
        self.assertEqual(u3["automatica"]["motivo"],
                         f"un servidor con esta misma IP o este mismo nombre ya fue rechazado en el minuto {canon.min_txt(rmin)}; "
                         "queda para decidir en persona.")

    def test_otro_nombre_en_la_misma_ip(self):
        self.caso(S1B)

    def test_el_mismo_nombre_en_otra_ip(self):
        self.caso(S1_OTRA_IP)

    def test_sin_rechazo_la_mudanza_se_amplia_igual(self):
        motor, sim, _ = self.preparar(alcance="filtracion")
        exp = mudanza(motor, sim, 2.0)
        motor._paso_dinamicas()
        self.assertEqual(exp["ubicaciones"][1]["estado"], "aprobada")


class TestContinuidadDelMismoServidor(ConDnsExtra):
    def test_c22_apunta_a_la_rechazada(self):
        motor, sim, _ = self.preparar(aprobar=False)
        exp = motor.e["expedientes"][0]
        motor.rechazar("juez-a", exp["id"], 1, "La evidencia no alcanza")
        exp = mudanza(motor, sim, 2.0)
        motor.aprobar("juez-a", exp["id"], 2, "ubicacion", None, None)
        redetectar(motor, sim, "D-9", 5.0)
        u3 = exp["ubicaciones"][-1]
        self.assertEqual(u3["rechazo_previo"]["ref"], exp["ubicaciones"][0]["ref"])
        self.assertEqual(u3["continuidad"]["de_ubicacion"], 1)
        self.assertEqual(u3["sellado"]["antecedente"]["ubicacion"], 2, "la cadena del sellado no cambia")

    def test_c4_apunta_a_la_levantada(self):
        motor, sim, _ = self.preparar(alcance="filtracion")
        exp = mudanza(motor, sim, 2.0)
        motor._paso_dinamicas()
        redetectar(motor, sim, "D-3", 3.0, S3)
        motor._paso_dinamicas()
        self.assertEqual([u["estado"] for u in exp["ubicaciones"]], ["aprobada"] * 3)
        motor.revocar_dinamica("juez-a", exp["id"], "Frenamos todo", levantar=True)
        redetectar(motor, sim, "D-9", 6.0, S2)
        u4 = exp["ubicaciones"][-1]
        self.assertEqual(u4["reabierta"]["de_ubicacion"], 2)
        self.assertEqual(u4["continuidad"]["de_ubicacion"], 2)
        self.assertEqual(u4["sellado"]["antecedente"]["ubicacion"], 3)


class TestVetadoNoSeVuelveABloquear(ConPartido):
    def test_aprobar_sobre_un_objetivo_levantado_por_reclamo_no_crea_orden(self):
        motor, sim, _ = self.preparar(det=[deteccion("D-1", 1.0, *CDN)], aprobar=False)
        exp = motor.e["expedientes"][0]
        motor.aprobar("juez-a", exp["id"], 1, "ubicacion", "ip", "Prueba: forzar IP en una red compartida")
        motor.despacho.ronda()
        sim.lista_reclamos = [{"id": "R-1", "minuto": 1.3, "dominio": "panaderia.test", "proveedor": "aurora"}]
        motor._t_reclamos = float("-inf")
        motor._paso_reclamos()
        r = motor.e["reclamos"]["R-1"]
        motor.resolver_reclamo("juez-a", "R-1", r["propuesta"]["accion"], "Reclamo fundado")
        self.assertIn(["ip", CDN[1]], motor.e["vetados"])
        otro = ("tv.cdn-pirata.test",) + CDN[1:]
        redetectar(motor, sim, "D-2", 2.0, otro)
        exp2, u2 = [(e, u) for e in motor.e["expedientes"] for u in e["ubicaciones"] if u["host"] == otro[0]][0]
        antes = {o["orden_id"] for o in ordenes(motor)}
        motor.aprobar("juez-a", exp2["id"], u2["n"], "ubicacion", "ip", "Prueba: forzar IP otra vez")
        nuevas = [o for o in ordenes(motor) if o["orden_id"] not in antes and o["tipo"] == "ip"]
        self.assertEqual(nuevas, [], "salió una orden nueva sobre la IP vetada")
        cub = [y for y in u2["decision"]["ya_cubiertos"] if y["tipo"] == "ip" and y["objetivo"] == CDN[1]]
        self.assertTrue(cub and all(y["orden_id"] is None for y in cub))


if __name__ == "__main__":
    unittest.main()
