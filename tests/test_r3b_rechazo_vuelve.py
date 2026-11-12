"""R3B · C22 (humano-1): un rechazo no absorbe en silencio lo que se ve después.

Contratos:
(a) Rechazo + detección del mismo servidor con minuto posterior → ubicación nueva, pendiente, con `rechazo_previo`
    {ref, min, juez_id, juez, motivo}, `continuidad.criterio = "mismo_servidor"` y la nota («usted» para quien
    rechazó, el nombre para otro juez). El rechazo original no se toca; la detección siguiente se suma a la nueva.
(b) Con la filtración seguida bajo una orden marco con seguimiento, el servidor rechazado que reaparece no sale como
    `amp-`: queda pendiente con «este servidor ya fue rechazado en el minuto X; queda para decidir en persona.»
(c) Una detección con minuto ≤ al del rechazo se suma a la rechazada, sin pedido nuevo.
(d) Un reinicio entre el rechazo y la detección no cambia (a).
"""
import unittest

from marca import canon
from marca.motor import Motor
from marca.usuarios import Usuarios
from tests.simulador_falso import deteccion
from tests.test_contratos_ronda2 import ConPartido, ordenes
from tests.test_contratos_ronda3 import JUEZ_A
from tests.test_robustez import MOTORES, PIRATA, entradas


class TestRechazoVuelveAlJuez(ConPartido):
    def rechazado(self):
        motor, sim, usuarios = self.preparar(aprobar=False)
        exp = motor.e["expedientes"][0]
        motor.rechazar("juez-a", exp["id"], 1, "La evidencia no alcanza")
        return motor, sim, exp

    def redetectar(self, motor, sim, did, minuto):
        sim.lista_detecciones.append(deteccion(did, minuto, *PIRATA))
        sim.avanzar(minuto + 0.1)
        motor._t_estado = float("-inf")
        motor.paso()

    def comprobar_pedido_nuevo(self, motor, exp_id):
        exp = motor.idx_exp[exp_id]
        u1 = exp["ubicaciones"][0]
        nuevas = [u for u in exp["ubicaciones"] if u["n"] != 1 and u["host"] == PIRATA[0] and u["ip"] == PIRATA[1]]
        self.assertEqual(len(nuevas), 1, "la detección posterior al rechazo quedó absorbida sin pedido")
        u2 = nuevas[0]
        self.assertEqual(u2["estado"], "pendiente")
        self.assertNotIn("D-9", u1["detecciones"])
        self.assertEqual(u1["estado"], "rechazada")
        rp = u2["rechazo_previo"]
        self.assertEqual((rp["ref"], rp["min"], rp["juez_id"], rp["juez"], rp["motivo"]),
                         (u1["ref"], u1["decision"]["min"], "juez-a", "Dra. A", "La evidencia no alcanza"))
        self.assertEqual(u2["continuidad"], {"de_ubicacion": 1, "criterio": "mismo_servidor"})
        x, y = canon.min_txt(rp["min"]), canon.min_txt(u2["primera_deteccion_min"])
        pend = [p for p in motor.vista_bandeja(JUEZ_A)["pendientes"] if p["n"] == u2["n"]]
        self.assertEqual(len(pend), 1)
        texto_a = (f"Mismo servidor: usted rechazó este pedido en el minuto {x}; la plataforma lo volvió a ver "
                   f"transmitiendo en el minuto {y}.")
        self.assertEqual(pend[0]["nota_continuidad"], texto_a)
        vu2 = [v for v in pend[0]["expediente"]["ubicaciones"] if v["n"] == u2["n"]][0]
        self.assertEqual(vu2["continuidad"]["nota"], texto_a)
        sala = [v for e in motor.vista_sala()["expedientes"] for v in e["ubicaciones"] if v["ref"] == u2["ref"]][0]
        self.assertEqual(sala["continuidad"]["nota"], texto_a.replace("usted rechazó", "Dra. A rechazó"))
        self.assertEqual(sala["rechazo_previo"]["ref"], u1["ref"])
        armada = [e for e in entradas(motor, "ubicacion_armada") if e["datos"]["ubicacion"] == u2["n"]][-1]
        self.assertEqual(armada["datos"]["rechazo_previo"]["ref"], u1["ref"])
        self.assertEqual(len([e for e in entradas(motor, "decision_juez") if e["datos"].get("aprobar") is False]), 1)
        return u2

    def test_a_deteccion_posterior_vuelve_al_juez(self):
        motor, sim, exp = self.rechazado()
        self.redetectar(motor, sim, "D-9", 5.0)
        u2 = self.comprobar_pedido_nuevo(motor, exp["id"])
        self.redetectar(motor, sim, "D-10", 6.0)
        self.assertIn("D-10", u2["detecciones"], "la siguiente se suma al pedido nuevo")
        self.assertEqual(len(exp["ubicaciones"]), 2)

    def test_b_lo_rechazado_no_se_amplia_solo_bajo_el_seguimiento(self):
        from tests.test_contratos_ronda2b import mudanza
        motor, sim, exp = self.rechazado()
        exp = mudanza(motor, sim, 2.0)
        u2 = exp["ubicaciones"][1]
        motor.aprobar("juez-a", exp["id"], u2["n"], "filtracion", None, None)
        self.assertTrue(exp["dinamica"]["activa"])
        self.redetectar(motor, sim, "D-9", 5.0)
        motor._paso_dinamicas()
        u3 = [u for u in exp["ubicaciones"] if u["host"] == PIRATA[0] and u["n"] != 1]
        self.assertEqual(len(u3), 1)
        self.assertEqual(u3[0]["estado"], "pendiente")
        self.assertFalse([o for o in ordenes(motor) if o["n"] == u3[0]["n"]], "no sale ninguna orden amp-")
        rmin = canon.min_txt(exp["ubicaciones"][0]["decision"]["min"])
        self.assertEqual(u3[0]["automatica"]["motivo"],
                         f"este servidor ya fue rechazado en el minuto {rmin}; queda para decidir en persona.")

    def test_c_deteccion_anterior_o_igual_al_rechazo_se_suma(self):
        motor, sim, exp = self.rechazado()
        dmin = exp["ubicaciones"][0]["decision"]["min"]
        for did, m in (("D-viejo", round(dmin - 0.05, 3)), ("D-igual", dmin)):
            with motor.candado:
                motor._procesar_deteccion(deteccion(did, m, *PIRATA),
                                          {"clase": "pirata", "motivo": "x", "sesion": "S0001"})
            self.assertIn(did, exp["ubicaciones"][0]["detecciones"])
        self.assertEqual(len(exp["ubicaciones"]), 1)

    def test_d_reinicio_entre_el_rechazo_y_la_deteccion(self):
        motor, sim, exp = self.rechazado()
        motor.detener()
        otro = Motor("http://falso", motor.salida, Usuarios(self.base / "p" / "jueces.json"), cliente=sim, tick=0.01,
                     registro=lambda t: None)
        otro.arrancar(nueva=False, hilos=False)
        MOTORES.append(otro)
        self.redetectar(otro, sim, "D-9", 5.0)
        self.comprobar_pedido_nuevo(otro, exp["id"])

    def test_despues_del_final_no_se_arma_nada(self):
        motor, sim, exp = self.rechazado()
        motor.e["hitos"]["fin"] = True
        with motor.candado:
            motor._procesar_deteccion(deteccion("D-tarde", 9.0, *PIRATA),
                                      {"clase": "pirata", "motivo": "x", "sesion": "S0001"})
        self.assertEqual(len(exp["ubicaciones"]), 1)


if __name__ == "__main__":
    unittest.main()
