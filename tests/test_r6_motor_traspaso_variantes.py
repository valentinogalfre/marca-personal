"""Revisión ola D (motor, NV7, variantes). Contrato: mientras el turno no se recibió, `resumen.dinamicas` lista solo lo
HEREDADO, también después de reiniciar el motor; `ratificar` con exactamente esa lista funciona y su respuesta dice la
verdad; el seguimiento propio del entrante sigue activo sin pedir ratificación."""
import unittest

from marca.motor import Motor
from marca.usuarios import Usuarios
from tests.test_robustez import MOTORES
from tests.test_r5_motor_traspaso_solo_heredados import JUEZ_B, OTRA, TestTraspasoSoloHeredados as Base
from tests import test_contratos_ronda2b as r2b


class Variantes(Base):
    def reanudar(self, motor, sim):
        motor.guardar()
        motor.auditoria.cerrar()
        otro = Motor("http://falso", motor.salida, Usuarios(self.base / "p" / "jueces.json"), cliente=sim, tick=0.01,
                     registro=lambda t: None)
        otro.arrancar(nueva=False, hilos=False)
        MOTORES.append(otro)
        return otro

    def _armar(self):
        motor, sim, usuarios = self.preparar(alcance="filtracion")
        heredada = r2b.TestTraspasoYRevocacion.traspaso(self, motor, sim, usuarios)
        motor.firmar_marco("juez-b", True)
        self.detectar(motor, sim, "D-77", 11.0, OTRA)
        nueva = next(e for e in motor.e["expedientes"] if e is not heredada)
        u = nueva["ubicaciones"][-1]
        motor.aprobar("juez-b", nueva["id"], u["n"], "filtracion", None, None)
        return motor, sim, usuarios, heredada, nueva

    def test_e_tras_reiniciar_sigue_listando_solo_lo_heredado(self):
        motor, sim, usuarios, heredada, nueva = self._armar()
        m2 = self.reanudar(motor, sim)
        tr = m2.e["traspasos"][-1]
        self.assertIsNone(tr.get("ratificado"))
        v = m2.vista_sala()["traspasos"][-1]
        lista = [d["exp"] for d in v["resumen"]["dinamicas"]]
        print("TRAS REINICIO dinamicas:", lista)
        self.assertEqual(lista, [heredada["id"]])
        res = m2.ratificar("juez-b", lista)
        print("RATIFICAR:", res)
        n2 = next(e for e in m2.e["expedientes"] if e["id"] == nueva["id"])
        self.assertTrue(n2["dinamica"]["activa"])
        self.assertFalse(n2["dinamica"].get("requiere_ratificacion"))

    def test_a_ratificar_lista_vacia_deja_sin_ratificar_solo_lo_heredado(self):
        motor, sim, usuarios, heredada, nueva = self._armar()
        res = motor.ratificar("juez-b", [])
        print("RATIFICAR []:", res)
        self.assertTrue(nueva["dinamica"]["activa"], "el seguimiento propio no debe caer por no ratificarlo")
        sin = res.get("sin_ratificar") if isinstance(res, dict) else None
        if sin is not None:
            self.assertNotIn(nueva["id"], [x if isinstance(x, str) else x.get("id") or x.get("exp") for x in sin])
        tr = motor.e["traspasos"][-1]
        v = motor.vista_sala()["traspasos"][-1]
        print("DESPUES DE RECIBIR:", [d["exp"] for d in v["resumen"]["dinamicas"]])


if __name__ == "__main__":
    unittest.main()
