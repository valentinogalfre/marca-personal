"""R3B · C23 (humano-2). Contrato [ronda2b §2, OPERACION «La pantalla del juez, prendida»]: cada episodio de ausencia del juez de turno
con pedidos esperando avisa a la sala con un aviso nuevo (arriba de la lista), y mientras dura la ausencia el
aviso dice cuántos pedidos esperan ahora; la misma ausencia no repite la alerta."""
import time
import unittest

from tests.test_contratos_ronda2 import ConPartido
from tests.test_robustez import entradas


def alertas_ausencia(motor):
    return [e for e in entradas(motor, "alerta") if "no tiene la plataforma" in e["datos"]["texto"]]


def avisos_sala_ausencia(motor):
    return [a for a in motor.e["avisos"] if a.get("para") is None and "no tiene la plataforma" in a["texto"]]


class TestAusenciaRepetida(ConPartido):
    def test_cada_ausencia_del_turno_avisa_a_la_sala(self):
        motor, sim, usuarios = self.preparar(aprobar=False)
        usuarios._actividad["juez-a"] = time.monotonic() - 200      # episodio 1
        motor._paso_presencia()
        motor._paso_presencia()                                      # misma ausencia: no repite
        self.assertEqual(len(alertas_ausencia(motor)), 1)
        usuarios.marcar_actividad("juez-a")                          # vuelve
        motor._paso_presencia()
        motor.aviso("reintento", "otro aviso cualquiera")            # la sala sigue recibiendo otras cosas
        usuarios._actividad["juez-a"] = time.monotonic() - 200      # episodio 2
        motor._paso_presencia()
        self.assertEqual(len(alertas_ausencia(motor)), 2, "la segunda ausencia del mismo turno no avisa a la sala")
        ultimo = max(motor.e["avisos"], key=lambda a: a["n"])
        self.assertIn("no tiene la plataforma", ultimo["texto"], "el aviso de la segunda ausencia no queda arriba")

    def test_el_numero_de_pedidos_sigue_al_dia(self):
        motor, sim, usuarios = self.preparar(aprobar=False)
        usuarios._actividad["juez-a"] = time.monotonic() - 200
        motor._paso_presencia()
        exp = motor.e["expedientes"][0]
        extra = dict(exp["ubicaciones"][0]); extra["n"] = 99
        exp["ubicaciones"].append(extra)                             # llega otro pedido para el mismo juez
        motor._paso_presencia()
        self.assertEqual(len(alertas_ausencia(motor)), 1)
        self.assertIn("hay 2 pedidos esperando.", avisos_sala_ausencia(motor)[-1]["texto"])
        exp["ubicaciones"].remove(extra)                             # y si vuelve a quedar uno, en singular
        motor._paso_presencia()
        self.assertIn("hay 1 pedido esperando.", avisos_sala_ausencia(motor)[-1]["texto"])
        self.assertEqual(len(alertas_ausencia(motor)), 1)


if __name__ == "__main__":
    unittest.main()
