"""Contrato (convivencia f-colateral-2 + c1-integridad-2): un partido legítimo en el que el juez refuta una inferencia
mientras otro pedido del mismo registrable espera firma (la propuesta se rehace, campo «recalculada») se exporta y
`verificar` lo da por bueno. Un paquete legítimo nunca da ✗ por el colateral rehecho al refutar."""
import unittest

from marca.verificar import verificar
from tests import test_r4_motor_colateral2 as c2


class RefutadoConPedidoEnEspera(c2.Base):
    DNS, DETS = c2.OtraIP.DNS, c2.OtraIP.DETS

    def test_paquete_con_propuesta_rehecha_verifica(self):
        _, u2 = self.ubic("tv2.club.test")
        self.assertIn("ferreteria.club.test", u2["colateral"]["inferidos"])  # premisa: armado antes de refutar
        self.refutar("kiosco.club.test")
        exp, u2 = self.ubic("tv2.club.test")
        self.assertIn("recalculada", u2)  # premisa: la propuesta se rehizo
        self.motor.aprobar("juez-a", exp["id"], u2["n"], "ubicacion", None, None)
        for m in (3.8, 4.4, 5.0, 12.0, 20.0, 25.1, 25.2):
            self.paso(m)
        entrega = self.motor.salida / "entrega"
        self.assertTrue((entrega / "MANIFIESTO.json").is_file(), "el cierre no exportó el paquete")
        inf = verificar(entrega)
        malas = [t for t in getattr(inf, "lineas", []) if "colateral" in str(t)]
        self.assertEqual(inf.fallas, 0, f"un paquete legítimo no verifica: {malas or inf.__dict__}")


if __name__ == "__main__":
    unittest.main()
