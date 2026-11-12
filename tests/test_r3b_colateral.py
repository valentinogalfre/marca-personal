"""Ronda 3, C14 (colateral-1, -2 y -3): una sola regla de daño colateral.

Contrato (colateral-1): el reclamo de un inquilino que la plataforma solo INFIRIÓ como propio (comparte el registrable con el host
del stream, pero nunca se lo observó como stream ni como página) nunca se propone desestimar. Lo observado (el host del
stream) sigue siendo operación pirata.

Caso: hosting por subdominios con la página del pirata en el apex (https://h.test/vivo) y un vecino panaderia.h.test en
la misma IP: la regla de «propios» lo toma como del pirata y recomienda IP; su reclamo es la señal que lo corrige.
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
from tests.test_contratos_ronda2 import ConPartido, ordenes
from marca import evidencia
from tests.test_robustez import entradas

IP = "203.0.113.60"


class TestReclamoDeInquilinoInferido(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        base = Path(self.dir.name)
        parches = [mock.patch.dict(simulador_falso.DNS, {IP: ["vivo.h.test", "panaderia.h.test"]}),
                   mock.patch.dict(simulador_falso.ASN_DE_IP, {IP: 64600})]
        for p in parches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.dir.cleanup)
        ruta = base / "jueces.json"
        ruta.write_text(json.dumps(CONFIG), encoding="utf-8")
        self.sim = SimuladorFalso()
        self.sim.lista_detecciones = [deteccion("D-0101", 1.0, "vivo.h.test", IP, "LP26-PRU-OFI-S0101",
                                                "https://h.test/vivo", 64600)]
        usuarios = Usuarios(ruta)
        self.motor = Motor("http://falso", base / "salida", usuarios, cliente=self.sim, tick=0.01,
                           registro=lambda t: None)
        self.motor.arrancar(nueva=True, hilos=False)
        self.paso(1.2)
        exp = self.motor.e["expedientes"][0]
        usuarios.ingresar("a", "clave-de-prueba-a")
        self.motor.aprobar("juez-a", exp["id"], 1, "ubicacion", None, None)
        for m in (1.3, 2.0, 2.5, 3.0):
            self.paso(m)

    def paso(self, minuto):
        self.sim.avanzar(minuto)
        self.motor._t_estado = float("-inf")  # «nunca»: en 3.9 el reloj monotónico arranca cerca de 0
        self.motor.paso()
        self.motor.despacho.ronda()
        self.motor.paso()

    def reclamo(self, rid, dominio):
        self.sim.lista_reclamos.append({"id": rid, "minuto": 3.1, "dominio": dominio, "proveedor": "aurora",
                                        "mensaje": "No carga."})
        self.motor._t_reclamos = float("-inf")  # «nunca»: en 3.9 el reloj monotónico arranca cerca de 0
        self.motor._paso_reclamos()
        return self.motor.e["reclamos"][rid]

    def test_premisa_la_ip_quedo_bloqueada(self):
        self.assertTrue(any(o["tipo"] == "ip" and o["objetivo"] == IP and o.get("aplicada_min") is not None
                            for o in self.motor.e["ordenes"].values()))

    def test_reclamo_del_inquilino_inferido_no_se_desestima(self):
        r = self.reclamo("R-001", "panaderia.h.test")
        self.assertTrue(r["verificacion"]["ordenes_causantes"])
        self.assertNotEqual(r["verificacion"]["clase_reclamante"], "operacion_pirata")
        self.assertNotEqual(r["propuesta"]["accion"], "desestimar")

    def test_la_sala_cuenta_el_colateral_del_inquilino(self):
        self.assertEqual(self.motor.ordenes_con_colateral(), 0)  # antes del reclamo, la inferencia manda
        self.reclamo("R-003", "panaderia.h.test")
        self.assertGreaterEqual(self.motor.ordenes_con_colateral(), 1)

    def test_reclamo_del_host_observado_sigue_siendo_pirata(self):
        r = self.reclamo("R-002", "vivo.h.test")
        self.assertEqual(r["verificacion"]["clase_reclamante"], "operacion_pirata")
        self.assertEqual(r["propuesta"]["accion"], "desestimar")


PAGINA_SUB = ("s1.pirata.test", "203.0.113.10", "LP26-PRU-OFI-S0001", "https://ver.pirata.test/vivo", 64600)


class TestReclamoDeUnNombrePropio(ConPartido):
    def test_la_pagina_del_pirata_en_un_subdominio_no_es_legitima(self):
        """[C14, colateral-3 caso 1] La página del pirata en ver.R (misma IP) es un nombre OBSERVADO: su reclamo
        sale «operacion_pirata» y se propone desestimar."""
        with mock.patch.dict(simulador_falso.DNS, {"203.0.113.10": ["s1.pirata.test", "ver.pirata.test"]}):
            motor, sim, _ = self.preparar(det=[deteccion("D-1", 1.0, *PAGINA_SUB)])
            u = motor.e["expedientes"][0]["ubicaciones"][0]
            self.assertEqual(u["colateral"]["recomendacion"], "ip")
            self.assertIn("ver.pirata.test", u["colateral"]["observados"])
            motor.despacho.ronda()
            self.assertTrue(any(o["tipo"] == "ip" for o in ordenes(motor)))
            sim.lista_reclamos = [{"id": "R-1", "minuto": 1.3, "dominio": "ver.pirata.test", "proveedor": "aurora",
                                   "mensaje": "Somos un sitio legítimo"}]
            motor._t_reclamos = float("-inf")  # «nunca»: en 3.9 el reloj monotónico arranca cerca de 0
            motor._paso_reclamos()
            r = motor.e["reclamos"]["R-1"]
            self.assertTrue(r["verificacion"]["ordenes_causantes"])
            self.assertEqual(r["verificacion"]["clase_reclamante"], "operacion_pirata")
            self.assertEqual(r["propuesta"]["accion"], "desestimar")
            self.assertIn("vio publicando el partido en el minuto", r["verificacion"]["explicacion"])

    def test_la_pagina_en_otro_registrable_ya_no_hace_exclusiva_la_ip(self):
        """[C14, colateral-3 caso 2, premisa nueva] Con la página en otro registrable no hay bloqueo por IP: ese
        sitio es ajeno y su reclamo no tiene órdenes causantes."""
        det = ("s1.pirata.test", "203.0.113.10", "LP26-PRU-OFI-S0001", "https://otra-marca.test/vivo", 64600)
        with mock.patch.dict(simulador_falso.DNS, {"203.0.113.10": ["s1.pirata.test", "otra-marca.test"]}):
            motor, sim, _ = self.preparar(det=[deteccion("D-1", 1.0, *det)])
            u = motor.e["expedientes"][0]["ubicaciones"][0]
            self.assertEqual(u["colateral"]["recomendacion"], "dominio")
            self.assertIn("otra-marca.test", u["colateral"]["ajenos"])
            motor.despacho.ronda()
            self.assertFalse(any(o["tipo"] == "ip" for o in ordenes(motor)))
            self.assertFalse(any(o["objetivo"] == "otra-marca.test" for o in ordenes(motor)))
            sim.lista_reclamos = [{"id": "R-1", "minuto": 1.3, "dominio": "otra-marca.test", "proveedor": "aurora",
                                   "mensaje": "Somos un sitio legítimo"}]
            motor._t_reclamos = float("-inf")  # «nunca»: en 3.9 el reloj monotónico arranca cerca de 0
            motor._paso_reclamos()
            r = motor.e["reclamos"]["R-1"]
            self.assertEqual(r["verificacion"]["ordenes_causantes"], [])
            self.assertEqual(r["verificacion"]["clase_reclamante"], "sin_bloqueo")


IP3 = "203.0.113.62"


class TestInferenciaRefutada(unittest.TestCase):
    """[C14] Un reclamo fundado de un inferido refuta la inferencia entera del registrable."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        base = Path(self.dir.name)
        parches = [mock.patch.dict(simulador_falso.DNS, {
                       IP3: ["vivo.h.test", "panaderia.h.test", "turnos.h.test"],
                       "203.0.113.63": ["otro.h.test", "agenda.h.test"]}),
                   mock.patch.dict(simulador_falso.ASN_DE_IP, {IP3: 64600, "203.0.113.63": 64600})]
        for p in parches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.dir.cleanup)
        ruta = base / "jueces.json"
        ruta.write_text(json.dumps(CONFIG), encoding="utf-8")
        self.sim = SimuladorFalso()
        self.sim.lista_detecciones = [deteccion("D-0201", 1.0, "vivo.h.test", IP3, "LP26-PRU-OFI-S0201",
                                                "https://h.test/vivo", 64600)]
        usuarios = Usuarios(ruta)
        self.motor = Motor("http://falso", base / "salida", usuarios, cliente=self.sim, tick=0.01,
                           registro=lambda t: None)
        self.motor.arrancar(nueva=True, hilos=False)
        TestReclamoDeInquilinoInferido.paso(self, 1.2)
        exp = self.motor.e["expedientes"][0]
        usuarios.ingresar("a", "clave-de-prueba-a")
        self.motor.aprobar("juez-a", exp["id"], 1, "ubicacion", None, None)
        for m in (1.3, 2.0, 2.5, 3.0):
            TestReclamoDeInquilinoInferido.paso(self, m)

    def test_el_motivo_dice_que_se_vio_y_que_se_infirio(self):
        u = self.motor.e["expedientes"][0]["ubicaciones"][0]
        self.assertEqual(u["colateral"]["recomendacion"], "ip")
        self.assertEqual(u["colateral"]["observados"], ["vivo.h.test"])
        self.assertEqual(sorted(u["colateral"]["inferidos"]), ["panaderia.h.test", "turnos.h.test"])
        self.assertIn("vio vivo.h.test", u["colateral"]["motivo"])
        self.assertIn("los 3 nombres", u["colateral"]["motivo"])
        self.assertNotIn("los dos", u["colateral"]["motivo"])

    def test_el_reclamo_de_un_inferido_levanta_la_ip_y_los_demas_inferidos(self):
        r = TestReclamoDeInquilinoInferido.reclamo(self, "R-001", "panaderia.h.test")
        self.assertEqual(r["verificacion"]["clase_reclamante"], "legitimo")
        self.assertTrue(r["verificacion"]["inferido"])
        self.assertIn("corrige esa inferencia", r["verificacion"]["explicacion"])
        self.assertEqual(r["propuesta"]["accion"], "levantar_y_reemplazar")
        ords = self.motor.e["ordenes"]
        lev = {(ords[x["orden_id"]]["tipo"], ords[x["orden_id"]]["objetivo"]) for x in r["propuesta"]["levantar"]}
        self.assertIn(("ip", IP3), lev)
        self.assertIn(("dominio", "turnos.h.test"), lev)
        self.assertNotIn(("dominio", "vivo.h.test"), lev)
        self.motor.resolver_reclamo("juez-a", "R-001", "levantar_y_reemplazar", None)
        self.assertIn("h.test", self.motor.e["inferencias_refutadas"])
        self.assertIn(["dominio", "turnos.h.test"], self.motor.e["vetados"])
        ref = entradas(self.motor, "inferencia_refutada")
        self.assertEqual(len(ref), 1)
        self.assertEqual(ref[0]["datos"]["registrable"], "h.test")
        self.assertEqual(ref[0]["datos"]["reclamo"], "R-001")
        # Lo observado sigue bloqueado: el stream por nombre en todos los que bloquean por dominio.
        self.assertTrue(self.motor.objetivo_activo("valle", "dominio", "vivo.h.test"))
        # Una ubicación posterior del mismo registrable ya no infiere: sale por dominio con los hermanos ajenos.
        self.sim.lista_detecciones.append(deteccion("D-0202", 3.5, "otro.h.test", "203.0.113.63",
                                                    "LP26-PRU-OFI-S0202", "https://h.test/vivo", 64600))
        TestReclamoDeInquilinoInferido.paso(self, 3.6)
        u = next(u for exp in self.motor.e["expedientes"] for u in exp["ubicaciones"] if u["host"] == "otro.h.test")
        self.assertEqual(u["colateral"]["recomendacion"], "dominio")
        self.assertIn("agenda.h.test", u["colateral"]["ajenos"])
        self.assertEqual(u["colateral"]["inferidos"], [])

    def test_un_nombre_vetado_que_despues_se_ve_transmitir_vuelve_al_juez(self):
        """[C14] Si después la plataforma VE el partido saliendo de un nombre vetado, llega al juez como pedido en
        persona con la nota del reclamo (nunca se amplía solo); si lo firma, se vuelve a bloquear."""
        TestReclamoDeInquilinoInferido.reclamo(self, "R-001", "panaderia.h.test")
        self.motor.resolver_reclamo("juez-a", "R-001", "levantar_y_reemplazar", None)
        self.assertIn(["dominio", "turnos.h.test"], self.motor.e["vetados"])
        self.sim.lista_detecciones.append(deteccion("D-0203", 3.5, "turnos.h.test", IP3, "LP26-PRU-OFI-S0201",
                                                    "https://h.test/vivo", 64600))
        TestReclamoDeInquilinoInferido.paso(self, 3.6)
        exp, u = next((exp, u) for exp in self.motor.e["expedientes"] for u in exp["ubicaciones"]
                      if u["host"] == "turnos.h.test")
        self.assertEqual(u["estado"], "pendiente")
        motivo = self.motor._motivo_no_ampliar(exp, u, False)
        self.assertIn("reclamo R-001", motivo)
        self.assertIn("lo decide el juez", motivo)
        self.motor.aprobar("juez-a", exp["id"], u["n"], "ubicacion", None, None)
        self.assertNotIn(["dominio", "turnos.h.test"], self.motor.e["vetados"])
        self.assertTrue(self.motor.objetivo_activo("valle", "dominio", "turnos.h.test"))

    def test_la_sala_cuenta_los_inferidos_refutados_como_legitimos(self):
        self.assertEqual(self.motor.ordenes_con_colateral(), 0)
        TestReclamoDeInquilinoInferido.reclamo(self, "R-001", "panaderia.h.test")
        self.motor.resolver_reclamo("juez-a", "R-001", "levantar_y_reemplazar", None)
        # La orden por nombre de turnos.h.test (aplicada antes) ya cuenta como colateral.
        self.assertGreaterEqual(self.motor.ordenes_con_colateral(), 2)


if __name__ == "__main__":
    unittest.main()
