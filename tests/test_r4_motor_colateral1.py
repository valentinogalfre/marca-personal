"""Ola C, punto 13 (f-colateral-1). C14 (verificación v-f-colateral-1): el reclamo fundado de un inquilino inferido refuta la inferencia, pero lo que la
plataforma VIO transmitir (y el juez firmó) no se levanta ni se veta: «el reemplazo deja bloqueados solo los
observados».

Caso: misma IP con vivo.h.test (stream visto en U1), vivo3.h.test (inferido en U1, visto transmitir después y firmado
en U2) y panaderia.h.test (inquilino). Reclama panaderia; el juez firma levantar_y_reemplazar.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from marca.motor import Motor
from marca.usuarios import Usuarios

from tests import simulador_falso
from tests.simulador_falso import SimuladorFalso, deteccion
from tests.test_motor_verificar import CONFIG

IP = "203.0.113.71"
PAG = "https://h.test/vivo"


class TestObservadoNoSeLevantaPorReclamoDeInquilino(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        base = Path(self.dir.name)
        for p in (mock.patch.dict(simulador_falso.DNS, {IP: ["vivo.h.test", "vivo3.h.test", "panaderia.h.test"]}),
                  mock.patch.dict(simulador_falso.ASN_DE_IP, {IP: 64600})):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.dir.cleanup)
        ruta = base / "jueces.json"
        ruta.write_text(json.dumps(CONFIG), encoding="utf-8")
        self.sim = SimuladorFalso()
        self.sim.lista_detecciones = [deteccion("D-0701", 1.0, "vivo.h.test", IP, "LP26-PRU-OFI-S0701", PAG, 64600)]
        self.usuarios = Usuarios(ruta)
        self.motor = Motor("http://falso", base / "salida", self.usuarios, cliente=self.sim, tick=0.01,
                           registro=lambda t: None)
        self.motor.arrancar(nueva=True, hilos=False)
        self.paso(1.2)
        self.usuarios.ingresar("a", "clave-de-prueba-a")
        exp = self.motor.e["expedientes"][0]
        self.motor.aprobar("juez-a", exp["id"], 1, "ubicacion", None, None)
        for m in (1.3, 2.0):
            self.paso(m)
        # vivo3.h.test se VE transmitiendo después: segunda ubicación, el juez la firma.
        self.sim.lista_detecciones.append(deteccion("D-0702", 2.2, "vivo3.h.test", IP, "LP26-PRU-OFI-S0701", PAG,
                                                    64600))
        self.paso(2.3)
        self.ub3 = [(e, u) for e in self.motor.e["expedientes"] for u in e["ubicaciones"]
                    if u["host"] == "vivo3.h.test"]
        for e, u in self.ub3:
            if u["estado"] == "pendiente":
                self.motor.aprobar("juez-a", e["id"], u["n"], "ubicacion", None, None)
        for m in (2.5, 3.0):
            self.paso(m)

    def paso(self, minuto):
        self.sim.avanzar(minuto)
        self.motor._t_estado = float("-inf")
        self.motor.paso()
        self.motor.despacho.ronda()
        self.motor.paso()

    def test_premisa(self):
        self.assertTrue(self.ub3, "vivo3.h.test debía quedar como ubicación observada")
        self.assertIn("vivo3.h.test", self.motor.hosts_piratas())

    def test_el_reclamo_del_inquilino_no_libera_un_stream_observado(self):
        self.sim.lista_reclamos.append({"id": "R-001", "minuto": 3.1, "dominio": "panaderia.h.test",
                                        "proveedor": "aurora", "mensaje": "No carga."})
        self.motor._t_reclamos = -1e9  # el reloj monótono de 3.9 en macOS arranca en 0 con el proceso
        self.motor._paso_reclamos()
        r = self.motor.e["reclamos"]["R-001"]
        self.assertEqual(r["propuesta"]["accion"], "levantar_y_reemplazar")
        ords = self.motor.e["ordenes"]
        piratas = {h.lower() for h in self.motor.hosts_piratas()}
        lev = [ords[x["orden_id"]] for x in r["propuesta"]["levantar"]]
        self.assertFalse([o["objetivo"] for o in lev if o["tipo"] == "dominio" and o["objetivo"] in piratas],
                         "la propuesta levanta órdenes sobre nombres observados")
        self.motor.resolver_reclamo("juez-a", "R-001", "levantar_y_reemplazar", None)
        self.paso(3.3)
        self.assertNotIn(["dominio", "vivo3.h.test"], self.motor.e["vetados"])
        for p in self.motor.e["proveedores"]:
            if "dominio" in (p.get("capacidades") or []):
                for h in ("vivo.h.test", "vivo3.h.test"):
                    self.assertTrue(self.motor.objetivo_activo(p["id"], "dominio", h), f"{p['id']} no bloquea {h}")



class TestVistoDespuesDelReclamo(unittest.TestCase):
    def test_resolucion_no_libera_lo_visto_despues_de_la_propuesta(self):
        t = TestObservadoNoSeLevantaPorReclamoDeInquilino("test_premisa")
        # Armado propio: sin la segunda detección hasta después del reclamo.
        t.dir = tempfile.TemporaryDirectory()
        base = Path(t.dir.name)
        for p in (mock.patch.dict(simulador_falso.DNS, {IP: ["vivo.h.test", "vivo3.h.test", "panaderia.h.test"]}),
                  mock.patch.dict(simulador_falso.ASN_DE_IP, {IP: 64600})):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(t.dir.cleanup)
        ruta = base / "jueces.json"
        ruta.write_text(json.dumps(CONFIG), encoding="utf-8")
        t.sim = SimuladorFalso()
        t.sim.lista_detecciones = [deteccion("D-0701", 1.0, "vivo.h.test", IP, "LP26-PRU-OFI-S0701", PAG, 64600)]
        usuarios = Usuarios(ruta)
        t.motor = m = Motor("http://falso", base / "salida", usuarios, cliente=t.sim, tick=0.01, registro=lambda x: None)
        m.arrancar(nueva=True, hilos=False)
        t.paso(1.2)
        usuarios.ingresar("a", "clave-de-prueba-a")
        m.aprobar("juez-a", m.e["expedientes"][0]["id"], 1, "ubicacion", None, None)
        for x in (1.3, 2.0):
            t.paso(x)
        t.sim.lista_reclamos.append({"id": "R-001", "minuto": 2.1, "dominio": "panaderia.h.test",
                                     "proveedor": "aurora", "mensaje": "No carga."})
        m._t_reclamos = -1e9  # el reloj monótono de 3.9 en macOS arranca en 0 con el proceso
        m._paso_reclamos()
        t.sim.lista_detecciones.append(deteccion("D-0702", 2.2, "vivo3.h.test", IP, "LP26-PRU-OFI-S0701", PAG, 64600))
        t.paso(2.3)
        for e in m.e["expedientes"]:
            for u in e["ubicaciones"]:
                if u["host"] == "vivo3.h.test" and u["estado"] == "pendiente":
                    m.aprobar("juez-a", e["id"], u["n"], "ubicacion", None, None)
        t.paso(2.5)
        self.assertIn("vivo3.h.test", m.hosts_piratas())
        m.resolver_reclamo("juez-a", "R-001", "levantar_y_reemplazar", None)
        t.paso(2.8)
        self.assertNotIn(["dominio", "vivo3.h.test"], m.e["vetados"])
        for p in m.e["proveedores"]:
            if "dominio" in (p.get("capacidades") or []):
                self.assertTrue(m.objetivo_activo(p["id"], "dominio", "vivo3.h.test"), f"{p['id']} no bloquea vivo3")


if __name__ == "__main__":
    unittest.main()
