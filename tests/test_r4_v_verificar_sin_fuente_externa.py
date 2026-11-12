"""Contrato (f-integridad-1): sin una fuente externa, `verificar` nunca presenta un paquete como probado.

Sobre un paquete falsificado con herramientas/falsificar.py (todo lo que controla la plataforma recalculado, testigos
incluidos), `verificar` sin el registro oficial no puede notar nada. Lo que sí tiene que hacer es decirlo: la salida
avisa que sin el registro solo prueba coherencia y no dice «Resultado: todo verifica.». Con el registro oficial de un
paquete sano, sí lo dice.
"""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

from marca.verificar import main_verificar

from tests.test_motor_verificar import correr_partido

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "herramientas"))
import falsificar  # noqa: E402


def salida(*args):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main_verificar(*args)
    return rc, buf.getvalue()


class TestSinFuenteExterna(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        base = Path(cls.dir.name)
        cls.motor, cls.sim, cls.entrega, cls.cfg = correr_partido(base)
        cls.registro = base / "registro.jsonl"
        cls.registro.write_text("".join(json.dumps(r) + "\n" for r in cls.sim.registro), encoding="utf-8")
        cls.falsa = base / "falsa"
        falsificar.falsificar(cls.entrega, cls.falsa, str(cls.cfg))

    @classmethod
    def tearDownClass(cls):
        cls.motor.despacho._pool.shutdown(wait=False)
        if cls.motor.auditoria:
            cls.motor.auditoria.cerrar()
        cls.dir.cleanup()

    def test_falsificado_sin_registro_no_se_presenta_como_probado(self):
        rc, texto = salida(self.falsa)
        self.assertIn("Sin el registro oficial", texto)
        self.assertNotIn("Resultado: todo verifica.", texto.splitlines())

    def test_sano_con_registro_si_dice_todo_verifica(self):
        rc, texto = salida(self.entrega, self.registro)
        self.assertEqual(rc, 0, texto)
        self.assertIn("Resultado: todo verifica.", texto.splitlines())
        self.assertNotIn("Sin el registro oficial", texto)


if __name__ == "__main__":
    unittest.main()
