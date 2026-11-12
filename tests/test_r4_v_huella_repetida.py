"""Contrato C20 / OPERACION §3 (borde f-operacion-1): con el partido cerrado y la plataforma viva, correr `exportar`
de nuevo despues de publicar la huella no la cambia: el segundo paquete, /transparencia (hitos.paquete) y el primero
tienen la misma huella, y la auditoria no crece con una foto nueva por cada exportar."""
import tempfile
import threading
import time
import unittest
from pathlib import Path

from marca import api
from marca.__main__ import _contar_testigos, escribir_info_plataforma, exportar_paquete
from marca.exportar import huella_paquete
from marca.verificar import verificar
from tests.test_api import arrancar, parar


class TestReexportarNoCambiaLaHuella(unittest.TestCase):
    def test_dos_exportar_con_plataforma_viva_dan_la_misma_huella(self):
        from tests.test_motor_verificar import correr_partido
        from tests.test_paquete import cerrar
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            motor, _, _, _ = correr_partido(base)
            salida = motor.salida
            self.assertTrue(motor.e["hitos"].get("exportado"))
            servidor = api.servir(motor, "127.0.0.1", 0)
            arrancar(servidor)
            try:
                escribir_info_plataforma(salida, "127.0.0.1", servidor.server_address[1], motor.instancia)

                def correr(destino):
                    res, textos = {}, []
                    t = threading.Thread(target=lambda: res.setdefault(
                        "rc", exportar_paquete(salida, destino, espera_s=3, imprimir=textos.append)))
                    t.start()
                    while t.is_alive():
                        motor.paso()
                        time.sleep(0.05)
                    self.assertEqual(res["rc"], 0, textos)
                    return huella_paquete(destino)

                h1 = correr(base / "partido-final")
                n1 = _contar_testigos(salida / "auditoria.jsonl")
                h2 = correr(base / "otra-copia")
                h3 = correr(base / "partido-final")  # reexportar al mismo destino
                with motor.candado:
                    publicada = (motor.e["hitos"].get("paquete") or {}).get("huella")
                self.assertEqual(h1, h2)
                self.assertEqual(h1, h3)
                self.assertEqual(h1, publicada)
                self.assertEqual(_contar_testigos(salida / "auditoria.jsonl"), n1)
                self.assertEqual(verificar(base / "partido-final", huella_publicada=h1).fallas, 0)
            finally:
                parar(servidor)
                cerrar(motor)


if __name__ == "__main__":
    unittest.main()
