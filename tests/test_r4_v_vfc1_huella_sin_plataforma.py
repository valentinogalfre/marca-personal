"""f-consigna-1 · C20: la huella que imprime `exportar` después del cierre es la que publicó la plataforma.

Contrato: con el partido cerrado y exportado por la plataforma (hitos.paquete.huella, la de /transparencia), si
después la plataforma se corta y el simulador ya no responde, `python3 -m marca exportar` entrega un paquete con
ESA misma huella mientras la auditoría no tenga entradas nuevas, aunque estado.json se haya guardado con un minuto
posterior.
"""
import io
import unittest
from contextlib import redirect_stdout

from marca.__main__ import exportar_paquete
from marca.exportar import huella_paquete
from marca.simulador import ErrorRed
from tests.test_contratos_ronda2 import ConPartido


class _SinSimulador:
    def ordenes(self, *_a, **_k):
        raise ErrorRed("sin conexión")

    def estado(self, *_a, **_k):
        raise ErrorRed("sin conexión")


class TestHuellaDespuesDeCortarLaPlataforma(ConPartido):
    def test_exportar_sin_plataforma_ni_simulador_da_la_huella_publicada(self):
        motor, sim, _ = self.preparar()
        motor.despacho.ronda()
        motor.e["hitos"]["exportado"] = True
        motor.exportar_entrega()
        publicada = motor.e["hitos"]["paquete"]["huella"]
        n_aud = motor.auditoria.n
        sim.avanzar(1.8)  # la plataforma sigue guardando estado.json con el minuto corriente
        motor._leer_estado(red=True)  # solo el reloj: después del cierre no hay entradas nuevas en la auditoría
        motor.guardar()
        self.assertGreater(motor.e["minuto"], 1.7, "estado.json debe llevar un minuto posterior al de la exportación")
        self.assertEqual(motor.auditoria.n, n_aud, "el escenario exige que no haya entradas nuevas")
        destino = self.base / "partido-final"
        with redirect_stdout(io.StringIO()):
            rc = exportar_paquete(motor.salida, destino, cliente=_SinSimulador(), imprimir=lambda *_: None)
        self.assertEqual(rc, 0)
        self.assertEqual(huella_paquete(destino), publicada)


if __name__ == "__main__":
    unittest.main()
