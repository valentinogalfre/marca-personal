"""Contrato (operación, «mensajes sin traceback»): si el operador escribe la dirección del simulador sin http://
(por ejemplo `--simulador 192.168.0.10` o `--simulador 192.168.0.10:8791`), `chequear` y `servir` salen al toque
con un mensaje llano que dice cómo escribirla: sin traceback, sin esperar 20 s callados y sin tocar la carpeta."""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]


def correr(*args, tope=15):
    t0 = time.monotonic()
    r = subprocess.run([sys.executable, "-m", "marca", *args], cwd=str(RAIZ), capture_output=True, text=True,
                       timeout=tope, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    return r, time.monotonic() - t0


class DireccionSinEsquema(unittest.TestCase):
    def test_chequear_y_servir_sin_http(self):
        with tempfile.TemporaryDirectory() as tmp:
            salida = Path(tmp) / "salida"
            for direccion in ("192.0.2.1", "192.0.2.1:8791", "localhost:8791/"):
                for cmd in (["chequear", "--simulador", direccion],
                            ["servir", "--simulador", direccion, "--puerto", "0", "--salida", str(salida), "--nueva"]):
                    with self.subTest(cmd=cmd):
                        r, seg = correr(*cmd)
                        texto = r.stdout + r.stderr
                        self.assertNotIn("Traceback", texto)
                        self.assertNotEqual(r.returncode, 0)
                        self.assertIn("http://", texto)
                        self.assertLess(seg, 10, "no tiene que quedarse esperando al simulador")
                        self.assertFalse(salida.exists(), "no se toca la carpeta")


if __name__ == "__main__":
    unittest.main()
