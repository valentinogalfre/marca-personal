"""Ola C, punto 14 (f-colateral-2). C14 (refutación) también vale para los pedidos que ya estaban esperando firma.

Contrato: «los análisis siguientes reciben refutados: en ese registrable ya no se infiere». Un pedido armado ANTES de
que el juez refute el registrable no puede firmarse con la inferencia vieja: lo que se firma no bloquea a un inquilino
ya reconocido legítimo, ni por nombre ni por una IP que comparte con él; y si el objetivo IP quedó vetado, el proveedor
igual recibe un bloqueo sobre el host del stream (nada de «ya cubierto» sin orden)."""
import json, tempfile, unittest
from pathlib import Path
from unittest import mock
from marca.motor import Motor, VIGENTES
from marca.usuarios import Usuarios
from tests import simulador_falso
from tests.simulador_falso import SimuladorFalso, deteccion
from tests.test_motor_verificar import CONFIG

IPA, IPB = "198.51.100.71", "198.51.100.72"


class Base(unittest.TestCase):
    DNS = {}
    DETS = []

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(); self.addCleanup(self.dir.cleanup)
        base = Path(self.dir.name)
        for p in [mock.patch.dict(simulador_falso.DNS, self.DNS),
                  mock.patch.dict(simulador_falso.ASN_DE_IP, {ip: 64601 for ip in self.DNS})]:
            p.start(); self.addCleanup(p.stop)
        ruta = base / "jueces.json"; ruta.write_text(json.dumps(CONFIG), encoding="utf-8")
        self.sim = SimuladorFalso()
        self.sim.lista_detecciones = [deteccion(*d) for d in self.DETS]
        us = Usuarios(ruta)
        self.motor = Motor("http://falso", base / "salida", us, cliente=self.sim, tick=0.01, registro=lambda t: None)
        self.motor.arrancar(nueva=True, hilos=False)
        self.paso(1.2)
        us.ingresar("a", "clave-de-prueba-a")
        self.motor.aprobar("juez-a", self.motor.e["expedientes"][0]["id"], 1, "ubicacion", None, None)
        for m in (1.4, 2.1, 2.6, 3.0):
            self.paso(m)

    def paso(self, m):
        self.sim.avanzar(m); self.motor._t_estado = float("-inf"); self.motor.paso(); self.motor.despacho.ronda(); self.motor.paso()

    def ubic(self, host):
        return next((x, u) for x in self.motor.e["expedientes"] for u in x["ubicaciones"] if u["host"] == host)

    def refutar(self, dominio):
        self.sim.lista_reclamos.append({"id": "R-077", "minuto": 3.1, "dominio": dominio, "proveedor": "aurora",
                                        "mensaje": "somos un comercio"})
        self.motor._t_reclamos = float("-inf"); self.motor._paso_reclamos()
        self.motor.resolver_reclamo("juez-a", "R-077", "levantar_y_reemplazar", None)
        self.paso(3.4)

    def vivas(self):
        return {(o["proveedor"], o["tipo"], o["objetivo"]) for o in self.motor.e["ordenes"].values()
                if o["estado"] in VIGENTES}


class OtraIP(Base):
    DNS = {IPA: ["tv.club.test", "kiosco.club.test"], IPB: ["tv2.club.test", "ferreteria.club.test"]}
    DETS = [("D-0201", 1.0, "tv.club.test", IPA, "LP26-PRU-OFI-S0201", "https://club.test/tv", 64601),
            ("D-0202", 2.7, "tv2.club.test", IPB, "LP26-PRU-OFI-S0202", "https://club.test/tv2", 64601)]

    def test_firmar_el_pendiente_no_bloquea_al_hermano_ya_refutado(self):
        _, u2 = self.ubic("tv2.club.test")
        self.assertEqual(u2["estado"], "pendiente")
        self.assertIn("ferreteria.club.test", u2["colateral"]["inferidos"])  # premisa: armado antes de refutar
        self.refutar("kiosco.club.test")
        self.assertIn("club.test", self.motor.e["inferencias_refutadas"])
        exp, u2 = self.ubic("tv2.club.test")
        self.motor.aprobar("juez-a", exp["id"], u2["n"], "ubicacion", None, None)
        for m in (3.8, 4.4, 5.0):
            self.paso(m)
        v = self.vivas()
        self.assertFalse([x for x in v if x[2] == "ferreteria.club.test"], v)
        self.assertNotIn(("aurora", "ip", IPB), v)
        self.assertTrue(any(x[2] == "tv2.club.test" for x in v), v)  # el stream sí queda bloqueado
        self.assertEqual(self.motor.ordenes_con_colateral(solo_vigentes=True), 0)

    def test_la_vista_dice_que_la_propuesta_se_rehizo(self):
        """Ola C: la tarjeta dice por qué cambió la propuesta (campo «recalculada» de la vista de la ubicación); la
        evidencia sellada y la huella no cambian."""
        exp, u2 = self.ubic("tv2.club.test")
        huella, sellada = u2["huella"], u2["sellado"]["propuesta"]
        self.refutar("kiosco.club.test")
        exp, u2 = self.ubic("tv2.club.test")
        v = self.motor.vista_ubicacion(exp, u2)
        self.assertEqual({k: v["recalculada"][k] for k in ("reclamo", "registrable")},
                         {"reclamo": "R-077", "registrable": "club.test"}, v["recalculada"])
        self.assertIn("tipo_antes", v["recalculada"])
        self.assertEqual(u2["huella"], huella)
        self.assertEqual(u2["sellado"]["propuesta"], sellada)
        self.assertNotIn("ferreteria.club.test", u2["colateral"].get("inferidos") or [])


class MismaIPVetada(Base):
    DNS = {IPA: ["tv.club.test", "tv3.club.test", "kiosco.club.test"]}
    DETS = [("D-0201", 1.0, "tv.club.test", IPA, "LP26-PRU-OFI-S0201", "https://club.test/tv", 64601),
            ("D-0203", 2.7, "tv3.club.test", IPA, "LP26-PRU-OFI-S0203", "https://club.test/tv3", 64601)]

    def test_la_ip_vetada_no_deja_al_proveedor_sin_bloqueo(self):
        _, u3 = self.ubic("tv3.club.test")
        self.assertEqual(u3["estado"], "pendiente")
        self.refutar("kiosco.club.test")
        self.assertIn(["ip", IPA], self.motor.e["vetados"])
        exp, u3 = self.ubic("tv3.club.test")
        self.motor.aprobar("juez-a", exp["id"], u3["n"], "ubicacion", None, None)
        for m in (3.8, 4.4, 5.0):
            self.paso(m)
        v = self.vivas()
        ids_ip = {p["id"] for p in simulador_falso.PROVEEDORES if "dominio" in p["capacidades"]}
        for pid in ids_ip:
            self.assertIn((pid, "dominio", "tv3.club.test"), v, f"{pid} no bloquea tv3.club.test: {sorted(v)}")
        _, u3 = self.ubic("tv3.club.test")
        self.assertFalse([c for c in u3["decision"]["ya_cubiertos"] if not c.get("orden_id")],
                         u3["decision"]["ya_cubiertos"])


if __name__ == "__main__":
    unittest.main()
