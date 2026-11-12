"""Contrato [pantallas-2]: un aviso que pide decisión deja de pedirla cuando esa decisión se toma.

Con el motor real, después de resolver un reclamo (levantar, levantar_y_reemplazar o desestimar), el aviso de tipo
«reclamo» de ese reclamo tiene que salir con atendido=True en la bandeja del juez y en la vista de la sala; si no, las
pantallas (comun.js MP.pideAccion) lo siguen pintando como «Pide su decisión».
"""
import unittest

from tests.simulador_falso import deteccion
from tests.test_contratos_ronda2 import CDN, ConPartido


class TestAvisoDeReclamoQuedaAtendido(ConPartido):
    def _con_reclamo(self, sub, dominio="panaderia.test"):
        motor, sim, _ = self.preparar(sub=sub, det=[deteccion("D-1", 1.0, *CDN)], aprobar=False)
        exp = motor.e["expedientes"][0]
        motor.aprobar("juez-a", exp["id"], 1, "ubicacion", "ip", "Prueba: forzar IP en una red compartida")
        motor.despacho.ronda()
        sim.lista_reclamos = [{"id": "R-1", "minuto": 1.3, "dominio": dominio, "proveedor": "aurora"}]
        motor._t_reclamos = float("-inf")  # «nunca»: en 3.9 el reloj monotónico arranca cerca de 0
        motor._paso_reclamos()
        self.assertEqual(motor.e["reclamos"]["R-1"]["estado"], "pendiente")
        return motor

    def _avisos_reclamo(self, motor):
        juez = {"usuario": "a", "juez_id": "juez-a", "rol": "juez", "nombre": "Dra. A"}
        bandeja = [a for a in motor.vista_bandeja(juez)["avisos"] if a["tipo"] == "reclamo"]
        sala = [a for a in motor.vista_sala()["avisos"] if a["tipo"] == "reclamo"]
        return bandeja, sala

    def _verificar(self, accion, fundamento=None):
        motor = self._con_reclamo(accion)
        bandeja, sala = self._avisos_reclamo(motor)
        self.assertTrue(bandeja and sala, "antes de resolver hay aviso de reclamo")
        self.assertFalse(any(a["atendido"] for a in bandeja + sala), "antes de resolver pide decisión")
        motor.resolver_reclamo("juez-a", "R-1", accion, fundamento)
        self.assertNotEqual(motor.e["reclamos"]["R-1"]["estado"], "pendiente")
        bandeja, sala = self._avisos_reclamo(motor)
        self.assertTrue(bandeja and sala)
        self.assertTrue(all(a["atendido"] for a in bandeja),
                        f"{accion}: la bandeja del juez sigue pidiendo decisión: {bandeja}")
        self.assertTrue(all(a["atendido"] for a in sala),
                        f"{accion}: la sala sigue pidiendo decisión: {sala}")

    def test_levantar_y_reemplazar(self):
        self._verificar("levantar_y_reemplazar")

    def test_levantar(self):
        self._verificar("levantar")

    def test_desestimar(self):
        self._verificar("desestimar", "Es parte de la operación pirata")

    def test_agrupado_sigue_pidiendo_mientras_quede_un_reclamo_pendiente(self):
        """Dos reclamos por la misma causa comparten aviso: desestimar uno no apaga el pedido del otro."""
        motor, sim, _ = self.preparar(sub="dos", det=[deteccion("D-1", 1.0, *CDN)], aprobar=False)
        exp = motor.e["expedientes"][0]
        motor.aprobar("juez-a", exp["id"], 1, "ubicacion", "ip", "Prueba: forzar IP en una red compartida")
        motor.despacho.ronda()
        sim.lista_reclamos = [{"id": "R-1", "minuto": 1.3, "dominio": "panaderia.test", "proveedor": "aurora"},
                              {"id": "R-2", "minuto": 1.31, "dominio": "municipio.example", "proveedor": "aurora"}]
        motor._t_reclamos = float("-inf")  # «nunca»: en 3.9 el reloj monotónico arranca cerca de 0
        motor._paso_reclamos()
        motor.resolver_reclamo("juez-a", "R-1", "desestimar", "Es parte de la operación pirata")
        self.assertEqual(motor.e["reclamos"]["R-2"]["estado"], "pendiente")
        bandeja, _ = self._avisos_reclamo(motor)
        self.assertTrue(bandeja and not any(a["atendido"] for a in bandeja))
        motor.resolver_reclamo("juez-a", "R-2", "levantar", None)
        bandeja, sala = self._avisos_reclamo(motor)
        self.assertTrue(all(a["atendido"] for a in bandeja + sala))

    def test_un_reclamo_nuevo_por_la_misma_causa_vuelve_a_pedir_decision(self):
        """Lo atendido no tapa un reclamo posterior: el agrupador no suma a un aviso ya atendido."""
        motor = self._con_reclamo("nuevo")
        motor.resolver_reclamo("juez-a", "R-1", "desestimar", "Es parte de la operación pirata")
        motor.aviso("reclamo", "Reclamo de otro.test: x", para="juez-a",
                    clave=[a for a in motor.e["avisos"] if a["tipo"] == "reclamo"][0]["clave"])
        bandeja, _ = self._avisos_reclamo(motor)
        self.assertEqual(sum(1 for a in bandeja if not a["atendido"]), 1)


if __name__ == "__main__":
    unittest.main()
