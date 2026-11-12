"""Contrato (c1-concurrencia-6): `exportar` con la plataforma viva y el partido en curso nunca arma el paquete con un
estado.json anterior a la foto de los proveedores que pidió.

La plataforma anota `testigos_guardados` en la auditoría y recién después guarda estado.json (misma pasada, pero
otro proceso no ve el candado). Si el comando exporta apenas aparece la entrada, el paquete lleva testigos y
auditoría nuevos con un estado viejo: una orden que la foto dio por aplicada figura sin `aplicada_min` y el
verificador da ✗. Acá se agranda esa ventana a propósito (la máquina cargada la abre sola) y se exige que, cuando
se llama a `exportar()`, estado.json ya refleje la auditoría hasta esa entrada (`aud_n >= n`).
"""
import json
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import marca.exportar as mod_exportar
from marca.__main__ import escribir_info_plataforma, exportar_paquete, plataforma_viva
from marca.api import servir
from marca.auditoria import leer_entradas

from tests.test_motor_verificar import correr_partido


class TestExportarEsperaElEstadoDeLaFoto(unittest.TestCase):
    def test_exportar_no_usa_un_estado_anterior_a_la_foto(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            motor, _sim, entrega, _cfg = correr_partido(base)
            salida = motor.salida
            ruta_aud = salida / "auditoria.jsonl"
            # Partido en curso: sin paquete del cierre, el comando exporta él mismo desde estado.json.
            shutil.rmtree(entrega, ignore_errors=True)
            motor.exportar_entrega = lambda: None  # el paquete del cierre no se rearma: rama «partido en curso»
            motor.guardar()

            original = motor.guardar_testigos

            def testigos_y_demora(*a, **k):  # entre la entrada y el guardar() que la sigue
                r = original(*a, **k)
                time.sleep(1.0)
                return r
            motor.guardar_testigos = testigos_y_demora

            visto = {}
            exportar_real = mod_exportar.exportar

            def exportar_espia(sal, destino, *a, **k):
                estado = json.loads((Path(sal) / "estado.json").read_text(encoding="utf-8"))
                ult = [x["n"] for x in leer_entradas(ruta_aud) if x["tipo"] == "testigos_guardados"][-1]
                visto["aud_n"], visto["n_testigos"] = estado.get("aud_n"), ult
                return exportar_real(sal, destino, *a, **k)

            servidor = servir(motor, "127.0.0.1", 0)
            hilo = threading.Thread(target=servidor.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
            hilo.start()
            try:
                escribir_info_plataforma(salida, "127.0.0.1", servidor.server_address[1], motor.instancia)
                self.assertTrue(plataforma_viva(salida))
                resultado, textos = {}, []
                with mock.patch.object(mod_exportar, "exportar", exportar_espia):
                    t = threading.Thread(target=lambda: resultado.setdefault(
                        "rc", exportar_paquete(salida, base / "viva", espera_s=10, imprimir=textos.append)))
                    t.start()
                    while t.is_alive():
                        motor.paso()
                        time.sleep(0.05)
                self.assertEqual(resultado.get("rc"), 0, textos)
                self.assertIn("Testigos refrescados por la plataforma.", textos)
                self.assertTrue(any(x.startswith("Exportado a ") for x in textos), textos)
                self.assertIsInstance(visto.get("aud_n"), int, visto)
                self.assertGreaterEqual(visto["aud_n"], visto["n_testigos"],
                                        f"se exportó un estado.json anterior a la foto: {visto}")
            finally:
                servidor.shutdown()
                servidor.server_close()
                motor.despacho._pool.shutdown(wait=False)
                if motor.auditoria:
                    motor.auditoria.cerrar()


if __name__ == "__main__":
    unittest.main()
