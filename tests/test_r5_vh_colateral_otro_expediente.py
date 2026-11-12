"""Verificación independiente de h-paquete-1.

Contrato: un paquete legítimo verifica con 0 ✗ en `colateral` aunque el pedido que el motor rehízo por una refutación
(`_recalcular_pendientes`, que usa `hosts_piratas()` = hosts de TODOS los expedientes) marque como «observado» un host
que es de OTRO expediente. `verificar` no puede exigir que lo observado salga solo del mismo expediente.
Variante distinta de la del informante: el host del otro expediente es de OTRO registrable (canal.otro.test) y el
pedido rehecho se firma antes del cierre.
"""
import json, unittest
from pathlib import Path
from marca.verificar import verificar
from tests.test_falsificacion import malas
from tests.test_r4_motor_colateral2 import Base, IPA, IPB

IPC = "198.51.100.74"


def de_colateral(inf):
    return [x for x in malas(inf) if "colateral" in x]


class ObservadoDeOtroExpediente(Base):
    DNS = {IPA: ["tv.club.test", "kiosco.club.test"],
           IPB: ["tv2.club.test", "ferreteria.club.test", "canal.otro.test"],
           IPC: ["canal.otro.test"]}
    DETS = [("D-0301", 1.0, "tv.club.test", IPA, "LP26-PRU-OFI-S0301", "https://club.test/tv", 64601),
            ("D-0302", 2.7, "tv2.club.test", IPB, "LP26-PRU-OFI-S0302", "https://club.test/tv2", 64601),
            ("D-0303", 2.9, "canal.otro.test", IPC, "LP26-PRU-OFI-S0303", "https://otro.test/vivo", 64601)]

    def tearDown(self):
        self.motor.despacho._pool.shutdown(wait=False)
        if self.motor.auditoria:
            self.motor.auditoria.cerrar()

    def test_firmado_tras_rehacer_verifica(self):
        e2, u2 = self.ubic("tv2.club.test")
        e3, _ = self.ubic("canal.otro.test")
        self.assertNotEqual(e2["id"], e3["id"])
        self.assertNotIn("canal.otro.test", u2["sellado"]["colateral"].get("observados") or [])
        self.refutar("kiosco.club.test")
        e2, u2 = self.ubic("tv2.club.test")
        self.assertIn("recalculada", u2)
        self.assertIn("canal.otro.test", u2["colateral"].get("observados") or [])
        self.motor.aprobar("juez-a", e2["id"], u2["n"], "ubicacion", None, None)
        for m in (3.8, 4.4, 5.0, 10.0, 20.0, 25.1, 25.2):
            self.paso(m)
        base = Path(self.dir.name)
        reg = base / "registro.jsonl"
        reg.write_text("".join(json.dumps(r) + "\n" for r in self.sim.registro), encoding="utf-8")
        entrega = base / "salida" / "entrega"
        self.assertEqual(de_colateral(verificar(entrega)), [])
        self.assertEqual(de_colateral(verificar(entrega, reg, base / "jueces.json")), [])


if __name__ == "__main__":
    unittest.main()
