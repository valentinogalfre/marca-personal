"""Contrato (paquete-3): un paquete sin tocar, exportado con el partido en curso, verifica sin ✗.

`foto_testigos` anota `testigos_guardados` y recién después guarda estado.json. `exportar` (otro proceso) no puede
leer estado.json en ese hueco: si lo hace, una orden que pasó a aplicada en la misma foto queda con aplicada_min
None en el paquete y la auditoría (dentro del corte) dice que se aplicó → el verificador da ✗ sobre un paquete
legítimo. Acá el hueco se agranda a propósito (guardar() demorado 1 s después de los testigos) para que el
resultado no dependa de la suerte.
"""
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from marca.__main__ import escribir_info_plataforma, exportar_paquete, plataforma_viva
from marca.api import servir
from marca.motor import Motor
from marca.usuarios import Usuarios
from marca.verificar import verificar

from tests.simulador_falso import SimuladorFalso
from tests.test_motor_verificar import CONFIG


class TestExportarEsperaElEstadoDeLaFoto(unittest.TestCase):
    def test_paquete_en_curso_sin_tocar_verifica(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            ruta_cfg = base / "jueces.json"
            ruta_cfg.write_text(json.dumps(CONFIG), encoding="utf-8")
            sim = SimuladorFalso()
            usuarios = Usuarios(ruta_cfg)
            motor = Motor("http://falso", base / "salida", usuarios, cliente=sim, tick=0.01, registro=lambda t: None)
            motor.arrancar(nueva=True, hilos=False)

            def paso(minuto):
                sim.avanzar(minuto)
                motor._t_estado = float("-inf")
                motor.paso()
                motor.despacho.ronda()
                motor.paso()

            paso(1.2)
            exp = motor.e["expedientes"][0]
            usuarios.ingresar("a", "clave-de-prueba-a")
            motor.firmar_marco("juez-a", True)
            motor.aprobar("juez-a", exp["id"], 1, "filtracion", None, None)
            paso(1.3)  # la orden sale; todavía no está aplicada
            enviadas = [o for o in motor.e["ordenes"].values() if o["estado"] != "aplicada"]
            self.assertTrue(enviadas, "hace falta al menos una orden enviada y no aplicada")
            sim.avanzar(2.2)  # el proveedor ya la aplicó; la plataforma se entera recién en la foto de testigos
            motor._t_estado = float("inf")  # que el ciclo no la vea antes por su consulta periódica

            # El hueco entre la entrada testigos_guardados y el estado.json que la refleja, agrandado.
            original_testigos, original_guardar = motor.guardar_testigos, motor.guardar
            demorar = {"si": False}

            def testigos(*a, **k):
                r = original_testigos(*a, **k)
                demorar["si"] = True
                return r

            def guardar():
                if demorar["si"]:
                    demorar["si"] = False
                    time.sleep(1.0)
                original_guardar()

            motor.guardar_testigos, motor.guardar = testigos, guardar

            salida = motor.salida
            servidor = servir(motor, "127.0.0.1", 0)
            hilo = threading.Thread(target=servidor.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
            hilo.start()
            try:
                escribir_info_plataforma(salida, "127.0.0.1", servidor.server_address[1], motor.instancia)
                self.assertTrue(plataforma_viva(salida))
                textos, resultado = [], {}
                t = threading.Thread(target=lambda: resultado.setdefault(
                    "rc", exportar_paquete(salida, base / "en-curso", espera_s=10, imprimir=textos.append)))
                t.start()
                while t.is_alive():  # la etapa del ciclo que atiende el pedido de `exportar`, sola: así la orden
                    motor._paso_pedido_testigos()  # pasa a aplicada en la foto y no antes, por otra etapa
                    time.sleep(0.05)
                self.assertEqual(resultado["rc"], 0, textos)
                aplicadas = [o for o in motor.e["ordenes"].values() if o["estado"] == "aplicada"]
                self.assertTrue(aplicadas, "la foto tenía que pasar la orden a aplicada")
                inf = verificar(base / "en-curso")
                malas = [x for x in inf.lineas if x.startswith("✗")]
                self.assertEqual(malas, [], "\n".join(inf.lineas))
            finally:
                servidor.shutdown()
                servidor.server_close()
                motor.despacho._pool.shutdown(wait=False)
                if motor.auditoria:
                    motor.auditoria.cerrar()


if __name__ == "__main__":
    unittest.main()
