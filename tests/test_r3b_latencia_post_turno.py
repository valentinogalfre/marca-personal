"""Contrato: ninguna firma llega al simulador fuera del turno del juez firmante.

La orden llega al simulador una latencia de POST después del chequeo de turno. Si los POST tardan más que
GET /estado (red asimétrica), el margen antes del cambio de turno tiene que contar lo que tardan los POST.
Escenario: x20, cambio de turno en el min 10 (juez-a -> juez-b), /estado instantáneo, POST de 2,5 s reales.
Llegada estimada del POST chequeado en el min 9,3: 9,3 + 2,5 × 20 / 60 = 10,13 -> fuera de turno.
"""
import tempfile
import unittest
from pathlib import Path

from marca.simulador import Cliente
from tests.test_robustez import cerrar_motores, motor_con


class TestLatenciaPostEnElMargenDeTurno(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.base = Path(self._dir.name)

    def tearDown(self):
        cerrar_motores()
        self._dir.cleanup()

    def preparar(self, latencia_post_s):
        motor, sim, _ = motor_con(self.base / "m")
        sim.latencia_post = lambda: latencia_post_s  # el cliente midió así sus últimos POST
        sim.acelerar = 20.0
        sim.avanzar(9.3)  # faltan 0,7 min = 2,1 s reales para el cambio de turno
        return motor

    def test_post_lento_cierra_la_firma_de_la_saliente(self):
        motor = self.preparar(2.5)
        ok, motivo = motor.puede_firmar_con("juez-a", motor.estado_fresco())
        self.assertFalse(ok, "con POST de 2,5 s la orden llegaría en el min 10,13 con la saliente")
        self.assertIn("termina en segundos", motivo)

    def test_post_lento_agranda_el_margen_de_envio(self):
        motor = self.preparar(2.5)
        est = motor.estado_fresco()
        margen = motor.margen_envio(est.get("acelerar"), motor.latencia_para(est))
        self.assertGreaterEqual(margen, 2.5 * 20 / 60, "el margen no cubre lo que tarda un POST")

    def test_post_rapido_sigue_firmando(self):
        # Control: sin POST lento, a 2,1 s reales del cambio, la saliente todavía firma (margen 2 s).
        motor = self.preparar(0.0)
        self.assertTrue(motor.puede_firmar_con("juez-a", motor.estado_fresco())[0])

    def test_cliente_mide_los_post_aparte(self):
        c = Cliente("http://127.0.0.1:9")
        c._anotar_latencia(2.5, "POST")
        for _ in range(20):  # muchos GET rápidos no borran el POST lento
            c._anotar_latencia(0.01, "GET")
        self.assertAlmostEqual(c.latencia_post(), 2.5)


    def test_un_post_que_agota_su_tiempo_no_estira_el_margen_mas_alla_del_techo(self):
        """[turnos-1] Techo: un POST de 10 s cuenta como TECHO_LAT_POST_S (5 s), no como 10."""
        from marca import simulador
        c = Cliente("http://127.0.0.1:9")
        c._anotar_latencia(10.0, "POST")
        self.assertEqual(c.latencia_post(), simulador.TECHO_LAT_POST_S)

    def test_un_post_lento_viejo_se_olvida(self):
        """[turnos-1] Memoria corta: un POST lento de hace más de VENTANA_LAT_POST_S ya no infla el margen."""
        from marca import simulador
        c = Cliente("http://127.0.0.1:9")
        c._anotar_latencia(3.0, "POST")
        t, seg = c._latencias_post[-1]
        c._latencias_post[-1] = (t - simulador.VENTANA_LAT_POST_S - 1, seg)
        self.assertEqual(c.latencia_post(), 0.0)

if __name__ == "__main__":
    unittest.main()
