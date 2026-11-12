"""Ola C, punto 16 (f-kit-2): un nombre con «_» que la plataforma bloqueó por orden (válido por C16) no puede ser
«inválido» en la consulta pública «¿Tu sitio quedó bloqueado?»: si hay un bloqueo vigente, la consulta lo dice."""
import unittest

from tests.simulador_falso import deteccion
from tests.test_contratos_ronda2 import ConPartido, ordenes

HOST = "live_hd.pirata.test"


class TestConsultaConGuionBajo(ConPartido):
    def test_nombre_con_guion_bajo_bloqueado_se_informa_bloqueado(self):
        motor, sim, _ = self.preparar(det=[deteccion("D-1", 1.0, HOST, "203.0.113.10", "LP26-PRU-OFI-S0001",
                                                     "https://pirata.test/vivo", 64600)])
        for _ in range(4):
            motor.despacho.ronda(); sim.avanzar(0.5); motor._t_estado = float("-inf"); motor.paso()
        self.assertTrue([o for o in ordenes(motor) if o["tipo"] == "dominio" and o["objetivo"] == HOST],
                        "premisa: hay una orden por dominio contra el nombre con guion bajo")
        for q in (HOST, "https://" + HOST + "/hls/index.m3u8"):
            self.assertEqual(motor.consulta_publica(q)["resultado"], "bloqueado", q)

    def test_lo_invalido_sigue_siendo_invalido(self):
        motor, sim, _ = self.preparar()
        for q in ("", "sin-punto", "a..b.test", "203.0.113.10"):
            self.assertEqual(motor.consulta_publica(q)["resultado"], "invalido", q)


if __name__ == "__main__":
    unittest.main()
