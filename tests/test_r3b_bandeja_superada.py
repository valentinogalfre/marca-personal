"""R3B · C24 (humano-3). Contrato: en la bandeja, un pedido cuyo servidor ya fue reemplazado por la misma filtración (la
siguiente ubicación empezó a verse después de su última detección) va después del pedido vigente y viene marcado
con superada_por; si los dos servidores se ven a la vez, ninguno se marca ni se reordena."""
import unittest

from tests.simulador_falso import deteccion
from tests.test_contratos_ronda2 import Base, motor_con
from tests.test_robustez import PIRATA

S2 = ("s2.pirata.test", "203.0.113.11", "LP26-PRU-OFI-S0001", "https://pirata.test/vivo", 64600)
JUEZ = {"usuario": "a", "juez_id": "juez-a", "rol": "juez", "nombre": "Dra. A"}


class TestBandejaSuperada(Base):
    def correr(self, sub, dets, pasos):
        motor, sim, usuarios = motor_con(self.base / sub, None)
        sim.lista_detecciones = dets
        usuarios.ingresar("a", "clave-de-prueba-a")
        for m in pasos:
            sim.avanzar(m)
            motor._t_estado = float("-inf")  # «nunca»: en 3.9 el reloj monotónico arranca cerca de 0
            motor.paso()
        return motor.vista_bandeja(JUEZ)["pendientes"]

    def test_mudanza_el_vigente_va_primero_y_el_muerto_marcado(self):
        p = self.correr("m", [deteccion("D-1", 1.0, *PIRATA), deteccion("D-2", 3.0, *PIRATA),
                              deteccion("D-3", 4.5, *S2), deteccion("D-4", 7.5, *S2)], (1.2, 3.2, 4.7, 7.7))
        self.assertEqual([x["n"] for x in p], [2, 1])
        self.assertIsNone(p[0].get("superada_por"))
        self.assertEqual(p[1].get("superada_por"), 2)

    def test_dos_servidores_a_la_vez_no_se_marca(self):
        p = self.correr("s", [deteccion("D-1", 1.0, *PIRATA), deteccion("D-3", 2.0, *S2),
                              deteccion("D-2", 3.0, *PIRATA)], (1.2, 2.2, 3.2))
        self.assertEqual([x["n"] for x in p], [1, 2])
        self.assertEqual([x.get("superada_por") for x in p], [None, None])

    def test_si_el_viejo_vuelve_a_verse_la_marca_se_va(self):
        p = self.correr("v", [deteccion("D-1", 1.0, *PIRATA), deteccion("D-3", 2.0, *S2),
                              deteccion("D-4", 2.5, *S2), deteccion("D-2", 4.0, *PIRATA)], (1.2, 2.7, 4.2))
        self.assertEqual([x["n"] for x in p], [1, 2])
        self.assertEqual([x.get("superada_por") for x in p], [None, None])


if __name__ == "__main__":
    unittest.main()
