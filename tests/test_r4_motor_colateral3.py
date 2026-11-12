"""Ola C (f-colateral-3). C14 (v-f-colateral-3): un reclamo fundado de un inferido refuta la inferencia ENTERA del registrable.

Contrato: si el pirata tiene dos servidores en el mismo registrable y en cada uno hay un inquilino inferido, al
resolver el reclamo de uno solo no puede quedar vigente ningún bloqueo sobre inquilinos de ese registrable (ni la IP
que los arrastra), porque la sala ya los cuenta como legítimos. Los hosts del stream siguen bloqueados por nombre.
"""
import json, tempfile, unittest
from pathlib import Path
from unittest import mock
from marca.motor import Motor, VIGENTES
from marca.usuarios import Usuarios
from tests import simulador_falso
from tests.simulador_falso import SimuladorFalso, deteccion
from tests.test_motor_verificar import CONFIG

IPA, IPB = "198.51.100.71", "198.51.100.72"


class RefutaRegistrableEntero(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory(); self.addCleanup(d.cleanup)
        base = Path(d.name)
        for p in [mock.patch.dict(simulador_falso.DNS, {IPA: ["tv.q.test", "almacen.q.test"],
                                                         IPB: ["tv2.q.test", "ferreteria.q.test"]}),
                  mock.patch.dict(simulador_falso.ASN_DE_IP, {IPA: 64600, IPB: 64600})]:
            p.start(); self.addCleanup(p.stop)
        ruta = base / "jueces.json"; ruta.write_text(json.dumps(CONFIG), encoding="utf-8")
        self.sim = SimuladorFalso()
        self.sim.lista_detecciones = [
            deteccion("D-0201", 1.0, "tv.q.test", IPA, "LP26-PRU-OFI-S0201", "https://q.test/", 64600),
            deteccion("D-0202", 1.0, "tv2.q.test", IPB, "LP26-PRU-OFI-S0202", "https://q.test/", 64600)]
        self.usuarios = Usuarios(ruta)
        self.motor = Motor("http://falso", base / "salida", self.usuarios, cliente=self.sim, tick=0.01,
                           registro=lambda t: None)
        self.motor.arrancar(nueva=True, hilos=False)
        self.paso(1.2)
        self.usuarios.ingresar("a", "clave-de-prueba-a")
        for exp in self.motor.e["expedientes"]:
            for u in exp["ubicaciones"]:
                if u["estado"] == "pendiente":
                    self.motor.aprobar("juez-a", exp["id"], u["n"], "ubicacion", None, None)
        for m in (1.3, 2.0, 2.5, 3.0):
            self.paso(m)

    def paso(self, minuto):
        self.sim.avanzar(minuto); self.motor._t_estado = float("-inf")
        self.motor.paso(); self.motor.despacho.ronda(); self.motor.paso()

    def vivas(self):
        return {(o["proveedor"], o["tipo"], o["objetivo"]) for o in self.motor.e["ordenes"].values()
                if o["estado"] in VIGENTES}

    def test_reclamo_de_un_inquilino_libera_a_los_del_otro_servidor(self):
        antes = self.vivas()
        # Premisa: los dos servidores quedaron bloqueados por IP y los dos inquilinos por nombre.
        self.assertTrue(any(t == "ip" and x == IPA for _, t, x in antes), antes)
        self.assertTrue(any(t == "ip" and x == IPB for _, t, x in antes), antes)
        self.assertTrue(any(x == "ferreteria.q.test" for _, _, x in antes), antes)
        self.sim.lista_reclamos.append({"id": "R-001", "minuto": 3.1, "dominio": "almacen.q.test",
                                        "proveedor": "aurora", "mensaje": "No carga mi negocio."})
        self.motor._t_reclamos = float("-inf"); self.motor._paso_reclamos()
        r = self.motor.e["reclamos"]["R-001"]
        self.assertEqual(r["propuesta"]["accion"], "levantar_y_reemplazar")
        self.motor.resolver_reclamo("juez-a", "R-001", "levantar_y_reemplazar", None)
        for m in (3.5, 4.0, 4.5, 5.0, 6.0):
            self.paso(m)
        v = self.vivas()
        self.assertIn("q.test", self.motor.e.get("inferencias_refutadas") or [])
        # Ningún inquilino del registrable refutado sigue bloqueado, ni por nombre ni por la IP que comparten.
        for _, t, x in v:
            self.assertNotIn(x, ("almacen.q.test", "ferreteria.q.test", IPA, IPB), sorted(v))
        # La sala no muestra colateral vigente que la plataforma no haya corregido.
        self.assertEqual(self.motor.ordenes_con_colateral(solo_vigentes=True), 0)
        # Los hosts del stream siguen bloqueados por nombre en los proveedores que bloquean por dominio.
        for host in ("tv.q.test", "tv2.q.test"):
            self.assertTrue(any(t == "dominio" and x == host for _, t, x in v), (host, sorted(v)))


if __name__ == "__main__":
    unittest.main()
