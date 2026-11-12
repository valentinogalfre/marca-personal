"""Revisión ola D (motor, g-colateral-1). Contrato: el fundamento por defecto de un reclamo dice la verdad. La cola
«además se levanta(n) N bloqueo(s) sobre lo que la plataforma había inferido del mismo dominio X y nunca vio
transmitir» cuenta SOLO bloqueos sobre objetivos que la plataforma nunca vio transmitir; un bloqueo por IP de un
servidor pirata que la plataforma SÍ vio transmitir (y que se reemplaza por bloqueo por nombre) no entra en esa cuenta."""
import re
import unittest

from tests import test_r5_motor_fundamento_reclamo as base
from marca import motor as M

CAPTURA = {}


class FundamentoNoCuentaComoInferidoLoQueSeVio(unittest.TestCase):
    def test_ademas_cuenta_solo_lo_nunca_visto(self):
        real = M.Motor.resolver_reclamo

        def espia(self_m, juez, rid, accion, fundamento):
            real(self_m, juez, rid, accion, fundamento)
            vistos_ip = {u["ip"] for e in self_m.e["expedientes"] for u in e["ubicaciones"] if u.get("detecciones")}
            vistos_host = {u["host"] for e in self_m.e["expedientes"] for u in e["ubicaciones"] if u.get("detecciones")}
            r = self_m.e["reclamos"][rid]
            causantes = {c["orden_id"] for c in r["verificacion"]["ordenes_causantes"]}
            ajenas = [o for o in self_m.e["ordenes"].values()
                      if (o.get("levantar") or {}).get("reclamo") == rid and o["orden_id"] not in causantes]
            CAPTURA["fund"] = r["resolucion"]["fundamento"]
            CAPTURA["nunca_vistas"] = [o for o in ajenas if o["objetivo"] not in vistos_ip | vistos_host]
            CAPTURA["ajenas"] = ajenas

        orig = M.Motor.resolver_reclamo
        M.Motor.resolver_reclamo = espia
        try:
            res = unittest.TextTestRunner(verbosity=0).run(
                unittest.defaultTestLoader.loadTestsFromTestCase(base.FundamentoNoAtribuyeOrdenesDeOtroServidor))
        finally:
            M.Motor.resolver_reclamo = orig
        self.assertTrue(res.wasSuccessful())
        fund = CAPTURA["fund"]
        m = re.search(r"además se levantan? (\d+) bloqueos?", fund)
        self.assertIsNotNone(m, fund)
        dicho = int(m.group(1))
        print("\nAJENAS:", [(o["tipo"], o["objetivo"]) for o in CAPTURA["ajenas"]])
        print("DICHO:", dicho, "| NUNCA VISTAS DE VERDAD:", len(CAPTURA["nunca_vistas"]))
        self.assertEqual(dicho, len(CAPTURA["nunca_vistas"]),
                         f"el fundamento dice que {dicho} bloqueos eran sobre lo nunca visto; de verdad son "
                         f"{len(CAPTURA['nunca_vistas'])}: {fund}")


if __name__ == "__main__":
    unittest.main()
