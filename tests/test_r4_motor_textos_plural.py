"""Ola C, punto 10 (NV3): los textos dicen singular o plural de verdad, nunca «orden(es)» ni «bloqueo(s)», y la
propuesta de un reclamo dice cuántos bloqueos son por IP y cuántos por nombre."""
import unittest

from marca import motor as motor_mod


class TestCant(unittest.TestCase):
    def test_singular_y_plural(self):
        self.assertEqual(motor_mod._cant(1, "orden", "órdenes"), "1 orden")
        self.assertEqual(motor_mod._cant(2, "orden", "órdenes"), "2 órdenes")
        self.assertEqual(motor_mod._cant(0, "orden", "órdenes"), "0 órdenes")


class TestPropuestaReclamo(unittest.TestCase):
    """La propuesta se arma sobre un motor mínimo: solo importa el texto."""

    def motor(self):
        m = motor_mod.Motor.__new__(motor_mod.Motor)
        m._otros_inferidos = lambda *a: []
        m._reemplazos = lambda causantes, dominio: [{"objetivo": "vivo.pirata.test"}]
        return m

    def test_una_por_ip(self):
        p = self.motor()._propuesta_reclamo("tienda.test", "legitimo", [{"orden_id": "O-1", "proveedor": "a",
                                                                         "tipo": "ip"}])
        self.assertTrue(p["explicacion"].startswith("Levantar 1 bloqueo por IP que alcanza a tienda.test y "
                                                    "reemplazarlo por un bloqueo por dominio de vivo.pirata.test"),
                        p["explicacion"])

    def test_por_ip_y_por_nombre(self):
        c = [{"orden_id": "O-1", "proveedor": "a", "tipo": "ip"}, {"orden_id": "O-2", "proveedor": "b", "tipo": "ip"},
             {"orden_id": "O-3", "proveedor": "a", "tipo": "dominio"}]
        p = self.motor()._propuesta_reclamo("tienda.test", "legitimo", c)
        self.assertIn("Levantar 2 bloqueos por IP y 1 bloqueo por nombre que alcanzan a tienda.test", p["explicacion"])
        self.assertNotIn("(s)", p["explicacion"])

    def test_solo_por_nombre(self):
        p = self.motor()._propuesta_reclamo("tienda.test", "legitimo", [{"orden_id": "O-1", "proveedor": "a",
                                                                         "tipo": "dominio"}])
        self.assertEqual(p["explicacion"], "Levantar 1 bloqueo por nombre contra tienda.test, sin reemplazo.")


if __name__ == "__main__":
    unittest.main()
