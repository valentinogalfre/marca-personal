"""Contrato: la auditoría encadenada detecta cualquier cambio, borrado o reordenamiento y dice dónde."""
import json
import tempfile
import unittest
from pathlib import Path

from marca.auditoria import Auditoria, verificar_cadena


class TestAuditoria(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.ruta = Path(self.dir.name) / "auditoria.jsonl"
        a = Auditoria(self.ruta)
        for i in range(5):
            a.agregar("deteccion_recibida", "titular", float(i), None, {"i": i})
        a.cerrar()

    def tearDown(self):
        self.dir.cleanup()

    def lineas(self):
        return self.ruta.read_text(encoding="utf-8").splitlines()

    def escribir(self, lineas):
        self.ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8")

    def test_sana(self):
        ok, n, errores = verificar_cadena(self.ruta)
        self.assertTrue(ok, errores)
        self.assertEqual(n, 5)
        primera = json.loads(self.lineas()[0])
        self.assertEqual(primera["prev"], "0" * 64)

    def test_cambiar_una_entrada(self):
        ls = self.lineas()
        e = json.loads(ls[2])
        e["datos"]["i"] = 99
        ls[2] = json.dumps(e, ensure_ascii=False)
        self.escribir(ls)
        ok, _, errores = verificar_cadena(self.ruta)
        self.assertFalse(ok)
        self.assertTrue(any("línea 3" in x and "modificada" in x for x in errores), errores)

    def test_borrar_una_entrada(self):
        ls = self.lineas()
        del ls[1]
        self.escribir(ls)
        ok, _, errores = verificar_cadena(self.ruta)
        self.assertFalse(ok)
        self.assertTrue(any("línea 2" in x for x in errores), errores)

    def test_reordenar(self):
        ls = self.lineas()
        ls[1], ls[2] = ls[2], ls[1]
        self.escribir(ls)
        ok, _, errores = verificar_cadena(self.ruta)
        self.assertFalse(ok)
        self.assertTrue(any("fuera de orden" in x for x in errores), errores)

    def test_reanudar_sigue_desde_la_cabeza(self):
        a = Auditoria(self.ruta)
        e = a.agregar("reanudacion", "sistema", 9.0)
        a.cerrar()
        self.assertEqual(e["n"], 6)
        self.assertTrue(verificar_cadena(self.ruta)[0])

    def test_caida_a_mitad_de_escritura_se_recorta_solo_lo_incompleto(self):
        from marca.auditoria import recortar_linea_incompleta
        with open(self.ruta, "a", encoding="utf-8") as f:
            f.write('{"n": 6, "tipo": "orden_env')
        resto = recortar_linea_incompleta(self.ruta)
        self.assertIn('"n": 6', resto)
        ok, n, _ = verificar_cadena(self.ruta)
        self.assertTrue(ok)
        self.assertEqual(n, 5)
        self.assertIsNone(recortar_linea_incompleta(self.ruta))

    def test_no_reanuda_sobre_cadena_rota(self):
        ls = self.lineas()
        del ls[0]
        self.escribir(ls)
        with self.assertRaises(ValueError):
            Auditoria(self.ruta)


if __name__ == "__main__":
    unittest.main()
