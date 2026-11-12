"""Contrato: registrable y cobertura de dominios (base de la regla de daño colateral y del licenciatario)."""
import unittest

from marca import dominios


class TestDominios(unittest.TestCase):
    def test_registrable_dos_rotulos(self):
        self.assertEqual(dominios.registrable("s1.pelotaya.test"), "pelotaya.test")
        self.assertEqual(dominios.registrable("pelotaya.test"), "pelotaya.test")

    def test_registrable_sufijo_segundo_nivel(self):
        self.assertEqual(dominios.registrable("tv.sitio.com.ar"), "sitio.com.ar")
        self.assertEqual(dominios.registrable("a.b.sitio.co.uk"), "sitio.co.uk")

    def test_registrable_ip_literal_tal_cual(self):
        self.assertEqual(dominios.registrable("203.0.113.10"), "203.0.113.10")

    def test_normalizar(self):
        self.assertEqual(dominios.normalizar(" S1.Pelotaya.TEST. "), "s1.pelotaya.test")

    def test_es_ip(self):
        self.assertTrue(dominios.es_ip("192.0.2.1"))
        self.assertTrue(dominios.es_ip("2001:db8::1"))
        self.assertFalse(dominios.es_ip("canalnorte.test"))

    def test_cubre(self):
        self.assertTrue(dominios.cubre("canalnorte.test", "canalnorte.test"))
        self.assertTrue(dominios.cubre("canalnorte.test", "envivo.canalnorte.test"))
        self.assertFalse(dominios.cubre("canalnorte.test", "falsocanalnorte.test"))
        self.assertFalse(dominios.cubre("canalnorte.test", "canalnorte.test.pirata.test"))

    def test_host_de(self):
        self.assertEqual(dominios.host_de("https://S1.Pelotaya.test/hls/x.m3u8"), "s1.pelotaya.test")
        self.assertIsNone(dominios.host_de(None))


if __name__ == "__main__":
    unittest.main()
