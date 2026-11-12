"""Revisor colateral (ola C, f-colateral-3). Contrato: el fundamento por defecto de un reclamo resuelto (queda en la
auditoría y es el motivo de cada levantamiento) dice la verdad: solo nombra como «bloqueando» al reclamante las
órdenes que de verdad lo alcanzaban; las que se levantan por refutar la inferencia en OTRO servidor no se presentan
como bloqueos sobre la IP del reclamante."""
import json, tempfile, unittest
from pathlib import Path
from unittest import mock
from marca.motor import Motor
from marca.usuarios import Usuarios
from tests import simulador_falso
from tests.simulador_falso import SimuladorFalso, deteccion
from tests.test_motor_verificar import CONFIG

IPA, IPB = "203.0.113.81", "203.0.113.82"


class FundamentoNoAtribuyeOrdenesDeOtroServidor(unittest.TestCase):
    def test_fundamento(self):
        d = tempfile.TemporaryDirectory(); self.addCleanup(d.cleanup); base = Path(d.name)
        for p in (mock.patch.dict(simulador_falso.DNS, {IPA: ["vivo.h.test", "panaderia.h.test", "ferreteria.h.test"],
                                                        IPB: ["vivo2.h.test", "kiosco.h.test", "mas.h.test"]}),
                  mock.patch.dict(simulador_falso.ASN_DE_IP, {IPA: 64600, IPB: 64600})):
            p.start(); self.addCleanup(p.stop)
        ruta = base / "jueces.json"; ruta.write_text(json.dumps(CONFIG), encoding="utf-8")
        sim = SimuladorFalso()
        sim.lista_detecciones = [deteccion("D-1", 1.0, "vivo.h.test", IPA, "LP26-PRU-OFI-S0901", "https://h.test/", 64600),
                                 deteccion("D-2", 1.0, "vivo2.h.test", IPB, "LP26-PRU-OFI-S0902", "https://h.test/", 64600)]
        us = Usuarios(ruta)
        m = Motor("http://falso", base / "salida", us, cliente=sim, tick=0.01, registro=lambda t: None)
        m.arrancar(nueva=True, hilos=False); us.ingresar("a", "clave-de-prueba-a")

        def paso(x):
            sim.avanzar(x); m._t_estado = float("-inf"); m.paso(); m.despacho.ronda(); m.paso()
        paso(1.2)
        for e in m.e["expedientes"]:
            for u in e["ubicaciones"]:
                if u["estado"] == "pendiente":
                    m.aprobar("juez-a", e["id"], u["n"], "ubicacion", None, None)
        for x in (1.3, 2.0, 2.5):
            paso(x)
        sim.lista_reclamos.append({"id": "R-001", "minuto": 2.6, "dominio": "panaderia.h.test", "proveedor": "aurora",
                                   "mensaje": "No carga."})
        m._t_reclamos = float("-inf"); m._paso_reclamos()
        r = m.e["reclamos"]["R-001"]
        causantes = {c["orden_id"] for c in r["verificacion"]["ordenes_causantes"]}
        m.resolver_reclamo("juez-a", "R-001", r["propuesta"]["accion"], None)
        fund = r["resolucion"]["fundamento"]
        print("\nFUNDAMENTO:", fund)
        ajenas = [o["orden_id"] for o in m.e["ordenes"].values()
                  if (o.get("levantar") or {}).get("reclamo") == "R-001" and o["orden_id"] not in causantes]
        self.assertTrue(ajenas, "premisa: se levantan órdenes de otro servidor por refutar la inferencia")
        bloqueada_por = fund.split("; ")[0]
        for oid in ajenas:
            self.assertNotIn(oid, bloqueada_por,
                             f"el fundamento dice que {oid} bloquea a panaderia.h.test ({IPA}) y no la alcanza")


if __name__ == "__main__":
    unittest.main()
