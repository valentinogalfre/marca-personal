"""Contrato: la firma es la que acepta el simulador y el sello ata la orden a la evidencia y a la decisión."""
import hashlib
import hmac
import unittest

from marca import sello
from marca.canon import huella


class TestSello(unittest.TestCase):
    def test_firma_coincide_con_la_del_simulador(self):
        # Mismo algoritmo que simulador/servidor.py: HMAC-SHA256 hex sobre orden_id|tipo|objetivo|vence_min|juez_id
        clave, msg = "demo-clave-laura-0b7e", "ord-1|ip|203.0.113.10|105|jueza-laura-ficticia"
        esperada = hmac.new(clave.encode(), msg.encode(), hashlib.sha256).hexdigest()
        self.assertEqual(sello.firma_orden(clave, "ord-1", "ip", "203.0.113.10", 105, "jueza-laura-ficticia"), esperada)
        self.assertEqual(esperada, sello.firma_orden(clave, "ord-1", "ip", "203.0.113.10", 105, "jueza-laura-ficticia"))

    def test_firma_valor_fijo(self):
        # Vector conocido de HMAC-SHA256 (RFC 4231 no aplica a claves de texto; se fija el valor calculado).
        self.assertEqual(sello.firmar("demo-clave-laura-0b7e", "x|ip|1.2.3.4|105|jueza-laura-ficticia"),
                         hmac.new(b"demo-clave-laura-0b7e", b"x|ip|1.2.3.4|105|jueza-laura-ficticia",
                                  hashlib.sha256).hexdigest())

    def test_firma_levantamiento(self):
        esperada = hmac.new(b"c", b"LEVANTAR|ord-9|juez", hashlib.sha256).hexdigest()
        self.assertEqual(sello.firma_levantamiento("c", "ord-9", "juez"), esperada)

    def test_sello_cambia_con_un_byte_de_la_evidencia_o_de_la_entrada(self):
        ev = {"captura": "abc", "host": "s1.pelotaya.test"}
        h = huella(ev)
        s = sello.calcular_sello(h, "e" * 64)
        self.assertEqual(len(s), 32)
        self.assertNotEqual(s, sello.calcular_sello(huella({"captura": "abd", "host": "s1.pelotaya.test"}), "e" * 64))
        self.assertNotEqual(s, sello.calcular_sello(h, "e" * 63 + "f"))

    def test_orden_id(self):
        oid = sello.orden_id(1, 1, "Aurora Net!", 1, "9f3a2b1c4d5e6f708192a3b4c5d6e7f8")
        self.assertEqual(oid, "ord-0001-u1-auroranet-01-9f3a2b1c4d5e6f708192a3b4c5d6e7f8")
        self.assertEqual(sello.sello_de_orden_id(oid), "9f3a2b1c4d5e6f708192a3b4c5d6e7f8")

    def test_firma_decision_distingue_aprobar_y_alcance(self):
        a = sello.firma_decision("k", "EXP-1", 1, "h", True, "filtracion", "j")
        self.assertNotEqual(a, sello.firma_decision("k", "EXP-1", 1, "h", False, "filtracion", "j"))
        self.assertNotEqual(a, sello.firma_decision("k", "EXP-1", 1, "h", True, "ubicacion", "j"))


if __name__ == "__main__":
    unittest.main()
