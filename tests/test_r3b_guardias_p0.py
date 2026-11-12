"""R3B · prioridad B, c1-pruebas-y-operacion-7: guardias para los mutantes que sobrevivían (parte del motor).

Contratos (uno por prueba):
- M1e: una orden firmada por un juez que ya no está de turno no sale con su firma: queda en espera de ratificación
  y el proveedor no recibe nada.
- M4: al reanudar, una orden que pudo haber salido (tenía `enviada_min`) queda incierta y se consulta antes de
  reenviarla: si el proveedor ya la tenía se adopta, sin 409 «orden_rechazada» en el registro oficial.
- M9: levantar por reclamo veta el objetivo levantado (no se vuelve a bloquear solo).
- M11: al reanudar se concilia con los proveedores en el acto: una orden que el proveedor tiene y el estado no,
  da la alerta sin esperar una ronda.
"""
import json
import unittest

from marca.motor import Motor
from marca.usuarios import Usuarios
from tests.simulador_falso import deteccion
from tests.test_contratos_ronda2 import CDN, ConPartido, eventos, ordenes
from tests.test_robustez import MOTORES, entradas


class TestGuardiasP0(ConPartido):
    def reanudar(self, motor, sim):
        otro = Motor("http://falso", motor.salida, Usuarios(self.base / "p" / "jueces.json"), cliente=sim, tick=0.01,
                     registro=lambda t: None)
        otro.arrancar(nueva=False, hilos=False)
        MOTORES.append(otro)
        return otro

    def test_m1e_firma_fuera_de_turno_no_sale(self):
        motor, sim, _ = self.preparar()
        sim.avanzar(10.5)  # juez-a dejó el turno en el 10 y juez-b todavía no ratificó nada
        motor.despacho.ronda()
        self.assertEqual(eventos(sim, "orden_recibida"), [])
        self.assertTrue(ordenes(motor) and all(o["estado"] == "espera_ratificacion" for o in ordenes(motor)),
                        [o["estado"] for o in ordenes(motor)])

    def test_m4_al_reanudar_lo_que_pudo_salir_se_consulta_y_se_adopta(self):
        motor, sim, _ = self.preparar()
        motor.despacho.ronda()
        ids = sorted(o["orden_id"] for o in ordenes(motor))
        self.assertEqual(sorted(e["orden_id"] for e in eventos(sim, "orden_recibida")), ids)
        motor.detener()
        ruta = motor.salida / "estado.json"
        guardado = json.loads(ruta.read_text(encoding="utf-8"))
        for o in guardado["ordenes"].values():  # se cayó antes de anotar las respuestas
            o["estado"], o["recibida_min"] = "por_enviar", None
        ruta.write_text(json.dumps(guardado, ensure_ascii=False), encoding="utf-8")
        sim.guion["ordenes"] = ["red"] * 10  # al reanudar no se pudo conciliar con las listas de los proveedores
        otro = self.reanudar(motor, sim)
        sim.guion["ordenes"] = []
        for o in ordenes(otro):
            self.assertTrue(o.get("incierta"), o["orden_id"])
            o["t_error"] = None
        otro.despacho.ronda()
        self.assertEqual(eventos(sim, "orden_rechazada"), [])
        self.assertEqual(sorted(e["orden_id"] for e in eventos(sim, "orden_recibida")), ids, "ningún reenvío")
        self.assertTrue(all(o["estado"] in ("recibida", "aplicada") for o in ordenes(otro)))

    def test_m9_levantar_por_reclamo_veta_el_objetivo(self):
        motor, sim, _ = self.preparar(det=[deteccion("D-1", 1.0, *CDN)], aprobar=False)
        exp = motor.e["expedientes"][0]
        motor.aprobar("juez-a", exp["id"], 1, "ubicacion", "ip", "Prueba: forzar IP en una red compartida")
        motor.despacho.ronda()
        sim.lista_reclamos = [{"id": "R-1", "minuto": 1.3, "dominio": "panaderia.test", "proveedor": "aurora"}]
        motor._t_reclamos = float("-inf")
        motor._paso_reclamos()
        r = motor.e["reclamos"]["R-1"]
        self.assertNotEqual(r["propuesta"]["accion"], "desestimar", "premisa: el reclamo es fundado")
        motor.resolver_reclamo("juez-a", "R-1", r["propuesta"]["accion"], "Reclamo fundado")
        levantadas = [o for o in ordenes(motor) if o.get("levantar") or o["estado"] == "levantada"]
        self.assertTrue(levantadas)
        for o in levantadas:
            self.assertIn([o["tipo"], o["objetivo"]], motor.e["vetados"])

    def test_m11_al_reanudar_se_concilia_en_el_acto(self):
        motor, sim, _ = self.preparar()
        motor.despacho.ronda()
        motor.detener()
        ruta = motor.salida / "estado.json"
        guardado = json.loads(ruta.read_text(encoding="utf-8"))
        perdida = sorted(guardado["ordenes"])[0]
        del guardado["ordenes"][perdida]
        ruta.write_text(json.dumps(guardado, ensure_ascii=False), encoding="utf-8")
        otro = self.reanudar(motor, sim)
        alertas = [e["datos"]["texto"] for e in entradas(otro, "alerta")]
        self.assertTrue(any(perdida in t and "no figura en el estado guardado" in t for t in alertas), alertas)


if __name__ == "__main__":
    unittest.main()
