"""Ola C, punto 12 (P3 de a-kit): un id de detección float entero (101.0) pasa a texto en vez de descartar la detección entera
(un descarte deja al pirata sin bloquear). Un 1.5, un bool o un NaN no son un id: se siguen descartando con su motivo."""
import unittest

from marca import evidencia


class TestIdsRaros(unittest.TestCase):
    def test_float_finito_pasa_a_texto(self):
        for crudo, texto in ((101.0, "101"), (-3.0, "-3")):
            d = evidencia.normalizar_deteccion({"id": crudo})
            self.assertEqual((d["id"], d["normalizada"]), (texto, ["id"]), crudo)

    def test_bool_y_nan_se_siguen_descartando(self):
        for crudo in (True, 1.5, float("nan"), float("inf")):
            d = evidencia.normalizar_deteccion({"id": crudo})
            self.assertNotIn("normalizada", d)
            self.assertIn("falta el id o no es texto", evidencia.validar_deteccion(d))


if __name__ == "__main__":
    unittest.main()
