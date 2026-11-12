"""Contratos c1-datos-raros-5 y -8: un dato raro pero entendible de una detección no deja al pirata sin bloquear.
- Un id entero se acepta pasándolo a texto (antes se descartaba la detección entera).
- Sin host_stream, el host se toma de stream_url (antes se descartaba)."""
from marca import evidencia
from tests.simulador_falso import deteccion
from tests.test_contratos_ronda2 import ConPartido
from tests.test_robustez import PIRATA


class TestDatosRaros(ConPartido):
    def test_id_entero_se_acepta_como_texto(self):
        d = deteccion("D-1", 1.0, *PIRATA)
        d["id"] = 101
        motor, sim, _ = self.preparar(det=[d], aprobar=False)
        self.assertIn("101", motor.e["detecciones_vistas"])
        self.assertEqual(len(motor.e["expedientes"]), 1)
        u = motor.e["expedientes"][0]["ubicaciones"][0]
        self.assertEqual(u["detecciones"], ["101"])

    def test_sin_host_stream_se_toma_el_de_la_url(self):
        d = deteccion("D-1", 1.0, *PIRATA)
        d.pop("host_stream")
        motor, sim, _ = self.preparar(det=[d], aprobar=False)
        self.assertEqual(len(motor.e["expedientes"]), 1)
        u = motor.e["expedientes"][0]["ubicaciones"][0]
        self.assertEqual(u["host"], PIRATA[0])
        motor.aprobar("juez-a", motor.e["expedientes"][0]["id"], 1, "ubicacion", None, None)
        self.assertTrue(all(o["objetivo"] for o in motor.e["ordenes"].values()))
        self.assertTrue(motor.e["ordenes"])

    def test_lo_que_no_se_entiende_se_sigue_descartando(self):
        for malo in ({"id": True}, {"id": 1.5}, {"id": "D-9", "host_stream": None, "stream_url": "no es url"}):
            d = evidencia.normalizar_deteccion(dict(deteccion("D-9", 1.0, *PIRATA), **malo))
            self.assertIsNotNone(evidencia.validar_deteccion(d), malo)
