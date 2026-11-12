"""Contrato C19 (c1-tiempos-6): una orden cuyo POST quedó sin respuesta no se reenvía con el mismo orden_id antes de
12 s reales desde que salió (aunque haya dos 404), y levantarla mientras está en duda no la anula a ciegas: queda con
el levantamiento pendiente; si aparece en el proveedor se le manda el levantamiento, y solo si se confirma que nunca
llegó se anula."""
import time

from marca import despacho as despacho_mod
from tests.test_contratos_ronda2 import ConPartido, eventos, ordenes


def consultar(motor):
    """Una ronda sin esperas entre consultas, pero sin tocar t_post (el instante en que salió el POST)."""
    for o in ordenes(motor):
        o["t_error"] = None
    motor.despacho.ronda()


def atrasar_post(motor, segundos):
    for o in ordenes(motor):
        if o.get("t_post") is not None:
            o["t_post"] -= segundos


class TestReenvioDeInciertas(ConPartido):
    def test_dos_404_antes_de_12_s_no_reenvian(self):
        motor, sim, _ = self.preparar()
        sim.guion["enviar_orden"] = [(502, None)] * 3
        motor.despacho.ronda()
        for o in ordenes(motor):
            o["post_timeout"] = 3.0  # un POST corto: su tiempo vence antes que los 12 s
        atrasar_post(motor, 6.0)  # pasó el tiempo del POST pero no los 12 s
        for _ in range(3):
            consultar(motor)
        self.assertEqual(eventos(sim, "orden_recibida"), [])
        self.assertTrue(all(o["incierta"] for o in ordenes(motor)))

    def test_pasados_12_s_y_dos_404_se_reenvia_el_mismo_orden_id(self):
        motor, sim, _ = self.preparar()
        sim.guion["enviar_orden"] = [(502, None)] * 3
        motor.despacho.ronda()
        ids = sorted(o["orden_id"] for o in ordenes(motor))
        atrasar_post(motor, despacho_mod.ESPERA_REENVIO_S + 0.5)
        for _ in range(3):
            consultar(motor)
        self.assertEqual(sorted(e["orden_id"] for e in eventos(sim, "orden_recibida")), ids)
        self.assertEqual(eventos(sim, "orden_rechazada"), [])

    def test_un_original_lento_que_aparece_se_adopta(self):
        """El POST llegó (respuesta perdida): aparece en el proveedor antes de los 12 s y se adopta, sin 409."""
        motor, sim, _ = self.preparar()
        sim.guion["enviar_orden"] = ["red_despues"] * 3
        motor.despacho.ronda()
        self.assertTrue(all(o["incierta"] for o in ordenes(motor)))
        consultar(motor)
        self.assertEqual(len(ordenes(motor, "recibida")), 3)
        self.assertEqual(len(eventos(sim, "orden_recibida")), 3)
        self.assertEqual(eventos(sim, "orden_rechazada"), [])


class TestLevantarUnaIncierta(ConPartido):
    def _levantar_todo(self, motor):
        exp = motor.e["expedientes"][0]
        motor.levantar_ubicacion("juez-a", exp["id"], 1, "Prueba: levantar en duda")

    def test_no_se_anula_a_ciegas_y_si_aparece_se_le_manda_el_levantamiento(self):
        motor, sim, _ = self.preparar()
        sim.guion["enviar_orden"] = ["red_despues"] * 3  # llegaron, pero no lo sabemos
        motor.despacho.ronda()
        self.assertTrue(all(o["incierta"] for o in ordenes(motor)))
        sim.guion["orden"] = [(404, {"error": "Orden inexistente"})] * 6  # el proveedor todavía no la muestra
        self._levantar_todo(motor)
        for _ in range(2):
            consultar(motor)
        self.assertFalse([o for o in ordenes(motor) if o.get("anulada")], "no se anula antes de los 12 s")
        self.assertTrue(all(o.get("levantar") for o in ordenes(motor)), "el levantamiento queda pendiente")
        sim.guion["orden"] = []  # ahora el proveedor la muestra
        for _ in range(3):
            consultar(motor)
        self.assertFalse([o for o in ordenes(motor) if o.get("anulada")])
        self.assertEqual(len(ordenes(motor, "levantada")), 3)
        self.assertEqual(len(sim.lev_registro), 3, "a cada proveedor se le mandó el levantamiento")

    def test_si_se_confirma_que_nunca_llego_recien_ahi_se_anula(self):
        motor, sim, _ = self.preparar()
        sim.guion["enviar_orden"] = [(502, None)] * 3  # no llegaron
        motor.despacho.ronda()
        self._levantar_todo(motor)
        consultar(motor)
        self.assertFalse([o for o in ordenes(motor) if o.get("anulada")])
        atrasar_post(motor, despacho_mod.ESPERA_REENVIO_S + 0.5)
        for _ in range(3):
            consultar(motor)
        self.assertEqual(len([o for o in ordenes(motor) if o.get("anulada")]), 3)
        self.assertEqual(eventos(sim, "orden_recibida"), [], "nunca se reenvía algo que se pidió levantar")
