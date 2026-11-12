"""Contrato (reintento-1, C13): un proveedor que falla 8 veces seguidas igual queda bloqueando antes del final, con
una sola alerta, sin orden_id repetidos, sin rechazos y sin firmas fuera de turno (con traspaso en el medio)."""
import unittest

from tests.simulador_falso import SimuladorFalso, deteccion
from tests.test_robustez import Base, motor_con


class SimuladorQueFalla(SimuladorFalso):
    """Como el oficial (la falla se decide por orden): `fallas` órdenes seguidas de valle fallan y la siguiente anda."""

    def __init__(self, fallas: int) -> None:
        super().__init__()
        self.fallas = fallas
        self.vistas = 0

    def avanzar(self, minuto: float) -> None:
        for o in self._ords["valle"].values():
            if o["estado"] == "recibida" and minuto >= o["_aplica"] and not o.get("_decidida"):
                o["_decidida"] = True
                self.vistas += 1
                if self.vistas <= self.fallas:
                    o.update(estado="fallida", motivo="Error interno del proveedor (prueba)",
                             finalizada_min=round(o["_aplica"], 3))
        super().avanzar(minuto)


class TestReintentoSinTopeDeCantidad(Base):
    """Contrato: mientras falte más que el margen para el final, una orden fallida siempre tiene un reemplazo en
    camino. Después de MAX_INTENTOS fallas seguidas se avisa una sola vez, pero no se abandona al proveedor."""

    def test_proveedor_que_falla_8_veces_igual_queda_bloqueando(self):
        sim = SimuladorQueFalla(fallas=8)
        sim.lista_detecciones = [deteccion("C-1", 2.0, "live.cdn-pirata.test", "198.51.100.20", "LP26-PRU-OFI-S0002",
                                           "https://cdn-pirata.test/p", 64610)]
        motor, sim, usuarios = motor_con(self.base, sim)

        def paso(minuto):
            sim.avanzar(minuto)
            motor._t_estado = float("-inf")  # «nunca»: en 3.9 el reloj monotónico arranca cerca de 0
            motor.paso()
            motor.despacho.ronda()
            motor.paso()

        paso(2.2)
        usuarios.ingresar("a", "clave-de-prueba-a")
        motor.aprobar("juez-a", motor.e["expedientes"][0]["id"], 1, "ubicacion", None, None)
        ratificado = False
        for i in range(23, 190):  # minuto 2,3 a 18,9 de un partido que termina en el 20
            minuto = i / 10
            if minuto >= 10.5 and not ratificado:
                usuarios.ingresar("b", "clave-de-prueba-b")
                paso(minuto)
                motor.ratificar("juez-b")
                ratificado = True
            paso(minuto)
        valle = list(sim._ords["valle"].values())
        aplicadas = [o for o in valle if o.get("aplicada_min") is not None]
        self.assertEqual(len(aplicadas), 1, [(o["orden_id"], o["estado"]) for o in valle])
        self.assertEqual(len(valle), 9)
        self.assertLess(aplicadas[0]["aplicada_min"], 20)
        ids = [e["orden_id"] for e in sim.registro if e["evento"] == "orden_recibida"]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertFalse([e for e in sim.registro if e["evento"] == "orden_rechazada"])
        self.assertTrue(all(e["juez_de_turno"] for e in sim.registro if e["evento"] == "orden_recibida"))
        topes = [a for a in motor.e["avisos"] if a["tipo"] == "alerta" and "falló" in a["texto"]]
        self.assertEqual(len(topes), 1, topes)


if __name__ == "__main__":
    unittest.main()
