"""R3B · prioridad B, parte del motor de kit-1, kit-2, kit-4 y robustez-3.

Contratos:
- kit-1: con el partido acelerado, el kit de /orden recibe `acelerar` y la hora REAL de vencimiento (la del router),
  no la hora del partido; a x1 sigue la hora del partido.
- kit-2: una vigente por dominio de la lista del proveedor trae `no_cortar` con los nombres ajenos conocidos que
  cuelgan de ese dominio (y no lo trae si no hay).
- kit-4: la versión `v` (serial de rpz.zone) no retrocede al reanudar después de un reinicio.
- robustez-3: estado.json guarda `aud_n` (la última entrada de auditoría que refleja) y la entrada `reanudacion`
  lleva `estado_hasta_entrada` con ese número.
"""
import datetime
import json
import unittest
from unittest import mock

from marca import motor as motor_mod
from marca.motor import Motor
from marca.usuarios import Usuarios
from tests.test_contratos_ronda2 import ConPartido, ordenes
from tests.test_robustez import MOTORES, entradas


class TestKitDelMotor(ConPartido):
    def test_kit1_acelerado_pasa_acelerar_y_la_hora_real(self):
        motor, sim, _ = self.preparar()
        o = ordenes(motor)[0]
        exp, _ = motor.ubicacion(o["exp"], o["n"])
        motor.reloj.acelerar = 20.0
        with mock.patch.object(motor_mod.kit_mod, "kit", return_value=[]) as k:
            antes = datetime.datetime.now()
            motor._kit_orden(o, exp)
            despues = datetime.datetime.now()
        kw = k.call_args.kwargs
        self.assertEqual(kw["acelerar"], 20.0)
        falta = datetime.timedelta(minutes=(float(o["vence_min"]) - motor.ahora()) / 20.0)
        # Ola C (v-f-kit-1): con segundos y redondeada hacia arriba (nunca antes del vencimiento real).
        hora = datetime.datetime.combine((antes + falta).date(),
                                         datetime.datetime.strptime(kw["hora_vence"], "%H:%M:%S").time())
        self.assertGreaterEqual(hora, (antes + falta).replace(microsecond=0))
        self.assertLessEqual(hora, despues + falta + datetime.timedelta(seconds=1))
        self.assertEqual(kw["fecha_vence"], (antes + falta).strftime("%Y-%m-%d"))

    def test_kit1_a_velocidad_real_sigue_la_hora_del_partido(self):
        motor, sim, _ = self.preparar()
        o = ordenes(motor)[0]
        exp, _ = motor.ubicacion(o["exp"], o["n"])
        motor.reloj.acelerar = 1.0
        with mock.patch.object(motor_mod.kit_mod, "kit", return_value=[]) as k:
            motor._kit_orden(o, exp)
        kw = k.call_args.kwargs
        self.assertEqual(kw["acelerar"], 1.0)
        hora = motor_mod.hora_de_partido(motor.e["partido"].get("inicio_iso"), o["vence_min"])
        self.assertEqual(kw["hora_vence"], (hora or "")[:5] or None)

    def test_kit2_vigente_por_dominio_trae_los_ajenos_colgados(self):
        motor, sim, _ = self.preparar()
        motor.despacho.ronda()
        sim.avanzar(3.0)
        motor.despacho.ronda()
        por_dominio = [o for o in ordenes(motor) if o["tipo"] == "dominio" and o.get("recibida_min") is not None]
        self.assertTrue(por_dominio, "premisa: hay una orden por dominio recibida")
        o = por_dominio[0]
        _, u = motor.ubicacion(o["exp"], o["n"])
        u["colateral"]["ajenos"] = ["tienda." + o["objetivo"], "otro-sitio.test"]
        vig = [v for v in motor.vista_proveedor(o["proveedor"])["vigentes"] if v["orden_id"] == o["orden_id"]][0]
        self.assertEqual(vig["no_cortar"], ["tienda." + o["objetivo"]])
        u["colateral"]["ajenos"] = ["otro-sitio.test"]
        vig = [v for v in motor.vista_proveedor(o["proveedor"])["vigentes"] if v["orden_id"] == o["orden_id"]][0]
        self.assertNotIn("no_cortar", vig)


class TestReanudarSinRetroceder(ConPartido):
    def reanudar(self, motor, sim):
        usuarios = Usuarios(self.base / "p" / "jueces.json")
        otro = Motor("http://falso", motor.salida, usuarios, cliente=sim, tick=0.01, registro=lambda t: None)
        otro.arrancar(nueva=False, hilos=False)
        MOTORES.append(otro)
        return otro

    def test_kit4_el_serial_no_retrocede_y_robustez3_aud_n(self):
        motor, sim, _ = self.preparar()
        for _ in range(5):
            motor._marcar()
        motor.guardar()
        v_antes = motor.v
        guardado = json.loads((motor.salida / "estado.json").read_text(encoding="utf-8"))
        self.assertEqual(guardado["aud_n"], motor.auditoria.n)
        self.assertEqual(guardado["v"], v_antes)
        motor.detener()
        guardado = json.loads((motor.salida / "estado.json").read_text(encoding="utf-8"))
        otro = self.reanudar(motor, sim)
        self.assertGreater(otro.v, v_antes)
        rean = entradas(otro, "reanudacion")[-1]
        self.assertEqual(rean["datos"]["estado_hasta_entrada"], guardado["aud_n"])


if __name__ == "__main__":
    unittest.main()
