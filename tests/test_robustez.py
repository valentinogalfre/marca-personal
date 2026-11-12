"""Contratos de robustez para el partido final (escenario no visto, simulador remoto y acelerado).

- Un dato mal formado (detección o reclamo) no frena el ciclo: se audita, se avisa y el resto sigue.
- Nunca un expediente con cero ubicaciones.
- No se manda una orden si faltan 2 s reales (o menos) para el final o su vencimiento, a cualquier aceleración.
- La carga sobre el simulador está acotada (seguimiento y reclamos).
- La ampliación dinámica la hace el sistema, bajo la orden del juez, y se ve así en la auditoría y las vistas.
- Firmar «filtración» sin sesión registra el alcance efectivo («ubicación») y lo explica.
- El cierre se reintenta hasta quedar exportado.
- Una auditoría dañada no impide reanudar: la cola se aparta y queda constancia.
"""
import json
import tempfile
import unittest
from pathlib import Path

from marca.auditoria import leer_entradas, verificar_cadena
from marca.motor import Motor
from marca.usuarios import Usuarios

from tests.simulador_falso import SimuladorFalso, deteccion
from tests.test_motor_verificar import CONFIG

PIRATA = ("s1.pirata.test", "203.0.113.10", "LP26-PRU-OFI-S0001", "https://pirata.test/vivo", 64600)


MOTORES = []


def cerrar_motores():
    while MOTORES:
        m = MOTORES.pop()
        try:
            m.despacho._pool.shutdown(wait=False)
            if m.auditoria:
                m.auditoria.cerrar()
        except Exception:
            pass


def motor_con(base: Path, sim=None):
    base.mkdir(parents=True, exist_ok=True)
    ruta_cfg = base / "jueces.json"
    ruta_cfg.write_text(json.dumps(CONFIG), encoding="utf-8")
    sim = sim or SimuladorFalso()
    usuarios = Usuarios(ruta_cfg)
    motor = Motor("http://falso", base / "salida", usuarios, cliente=sim, tick=0.01, registro=lambda t: None)
    motor.arrancar(nueva=True, hilos=False)
    MOTORES.append(motor)
    return motor, sim, usuarios


def entradas(motor, tipo):
    return [e for e in leer_entradas(motor.salida / "auditoria.jsonl") if e["tipo"] == tipo]


class Base(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.base = Path(self._dir.name)

    def tearDown(self):
        cerrar_motores()
        self._dir.cleanup()


class TestDatosMalFormados(Base):
    def lote(self):
        v1 = deteccion("V-1", 1.0, *PIRATA)
        sin_id = deteccion("X-0", 1.0, "otro.pirata.test", "203.0.113.11", "LP26-PRU-OFI-S0009",
                           "https://otro.test/", 64600)
        del sin_id["id"]
        host_malo = deteccion("X-1", 1.0, 's1.pirata.test" ; /system reboot', "203.0.113.10", "LP26-PRU-OFI-S0001",
                              "https://pirata.test/vivo", 64600)
        minuto_nulo = dict(deteccion("X-2", 1.0, *PIRATA), minuto=None)
        v2 = deteccion("V-2", 1.1, "live.cdn-pirata.test", "198.51.100.20", "LP26-PRU-OFI-S0002",
                       "https://cdn-pirata.test/p", 64610)
        return [v1, sin_id, host_malo, minuto_nulo, v2]

    def test_lote_con_detecciones_invalidas_no_frena_el_ciclo(self):
        motor, sim, _ = motor_con(self.base)
        sim.lista_detecciones = self.lote()
        sim.avanzar(1.2)
        motor.paso()
        exps = motor.e["expedientes"]
        self.assertEqual(sorted(u["host"] for x in exps for u in x["ubicaciones"]),
                         ["live.cdn-pirata.test", "s1.pirata.test"])
        malas = entradas(motor, "deteccion_invalida")
        self.assertEqual(len(malas), 3, malas)
        self.assertEqual({m["datos"]["deteccion"] for m in malas}, {None, "X-1", "X-2"})
        self.assertTrue(all("\n" not in m["datos"]["motivo"] for m in malas))
        # Las etapas siguientes corrieron en el mismo ciclo y `desde` avanzó.
        self.assertEqual(sim.llamadas.get("reclamos"), 1)
        self.assertEqual(motor.e["desde"], 1.2)
        self.assertTrue(any("inválida" in a["texto"] for a in motor.e["avisos"]))
        # No se vuelven a auditar en el ciclo siguiente.
        sim.avanzar(1.3)
        motor.paso()
        self.assertEqual(len(entradas(motor, "deteccion_invalida")), 3)

    def test_falla_al_armar_no_deja_expediente_vacio(self):
        motor, sim, _ = motor_con(self.base)
        sim.lista_detecciones = self.lote()[:1] + self.lote()[4:]
        original = motor._armar_ubicacion

        def armar(exp, d, *args):
            if d["id"] == "V-1":
                raise RuntimeError("dato imposible")
            return original(exp, d, *args)
        motor._armar_ubicacion = armar
        sim.avanzar(1.2)
        motor.paso()
        self.assertTrue(motor.e["expedientes"])
        self.assertTrue(all(x["ubicaciones"] for x in motor.e["expedientes"]))
        self.assertEqual(len(entradas(motor, "expediente_anulado")), 1)
        self.assertEqual([m["datos"]["deteccion"] for m in entradas(motor, "deteccion_invalida")], ["V-1"])
        motor.vista_sala()  # las vistas no fallan

    def test_una_etapa_que_falla_no_saltea_las_demas(self):
        motor, sim, _ = motor_con(self.base)

        def rota():
            raise KeyError("campo inesperado")
        motor._paso_estado = rota
        sim.avanzar(1.2)
        motor.paso()
        self.assertEqual(sim.llamadas.get("reclamos"), 1)
        self.assertTrue(motor.e["expedientes"])
        self.assertTrue(any("«estado»" in a["texto"] for a in motor.e["avisos"]))

    def test_reclamos_invalidos_se_auditan_una_vez(self):
        motor, sim, _ = motor_con(self.base)
        sim.lista_reclamos = [
            {"id": "R-1", "minuto": 1.0, "dominio": "panaderia.test", "proveedor": "aurora", "mensaje": "x"},
            {"minuto": 1.0, "dominio": "x.test", "proveedor": "aurora"},
            {"id": "R-3", "minuto": 1.0, "dominio": "pana deria.test", "proveedor": "aurora"},
            {"id": "R-4", "minuto": None, "dominio": "a.test", "proveedor": "aurora"},
        ]
        sim.avanzar(1.2)
        motor.paso()
        self.assertIn("R-1", motor.e["reclamos"])
        self.assertEqual(len(entradas(motor, "reclamo_invalido")), 3)
        motor._t_reclamos = float("-inf")
        motor.paso()
        self.assertEqual(len(entradas(motor, "reclamo_invalido")), 3)


class TestMargenFinal(Base):
    def caso(self, acelerar, minuto_envio, vence=None):
        motor, sim, usuarios = motor_con(self.base / str(acelerar) / str(minuto_envio))
        sim.acelerar = acelerar
        sim.lista_detecciones = [deteccion("F-1", minuto_envio - 0.1, *PIRATA)]
        usuarios.ingresar("b", "clave-de-prueba-b")
        sim.avanzar(minuto_envio - 0.05)
        motor._t_estado = float("-inf")
        motor.paso()
        exp = motor.e["expedientes"][0]
        motor.aprobar("juez-b", exp["id"], 1, "ubicacion", None, None)
        if vence is not None:
            for o in motor.e["ordenes"].values():
                o["vence_min"] = vence
        sim.avanzar(minuto_envio)
        motor.despacho.ronda()
        rechazadas = [r for r in sim.registro if r["evento"] == "orden_rechazada"]
        self.assertEqual(rechazadas, [])
        return [r for r in sim.registro if r["evento"] == "orden_recibida"]

    def test_cerca_del_final_x30_no_sale_y_x6_si(self):
        # Faltan 0,5 min: a x30 son 1 s real (margen 1 min); a x6 son 5 s reales (margen 0,2 min).
        self.assertEqual(self.caso(30, 19.5), [])
        self.assertTrue(self.caso(6, 19.5))

    def test_cerca_del_vencimiento_x30_no_sale_y_x6_si(self):
        self.assertEqual(self.caso(30, 12.5, vence=13), [])
        self.assertTrue(self.caso(6, 12.5, vence=13))


class TestCargaSobreElSimulador(Base):
    def test_seguimiento_y_reclamos_acotados(self):
        motor, sim, _ = motor_con(self.base)
        motor.e["ordenes"]["x"] = {"orden_id": "x", "proveedor": "aurora", "estado": "aplicada"}
        motor._paso_seguimiento()
        motor._paso_seguimiento()
        self.assertEqual(sim.llamadas.get("ordenes:aurora"), 1, "solo aplicadas: cada 2 s reales")
        motor.e["ordenes"]["x"]["estado"] = "recibida"
        motor._paso_seguimiento()
        motor._paso_seguimiento()
        self.assertEqual(sim.llamadas.get("ordenes:aurora"), 3, "en tránsito: en cada ciclo")
        motor._paso_reclamos()
        motor._paso_reclamos()
        self.assertEqual(sim.llamadas.get("reclamos"), 1, "reclamos: una vez por segundo real")


class TestAlcanceEfectivo(Base):
    def test_filtracion_sin_sesion_queda_como_ubicacion(self):
        motor, sim, usuarios = motor_con(self.base)
        sim.lista_detecciones = [deteccion("S-1", 1.0, "s1.pirata.test", "203.0.113.10", "LP26-PRU-OFI",
                                           "https://pirata.test/vivo", 64600)]
        usuarios.ingresar("a", "clave-de-prueba-a")
        sim.avanzar(1.2)
        motor.paso()
        exp = motor.e["expedientes"][0]
        motor.firmar_marco("juez-a", True)
        res = motor.aprobar("juez-a", exp["id"], 1, "filtracion", None, None)
        self.assertEqual(res["alcance_efectivo"], "ubicacion")
        self.assertIn("sesión", res["aviso"])
        dec = entradas(motor, "decision_juez")[-1]["datos"]
        self.assertEqual((dec["alcance"], dec["alcance_pedido"]), ("ubicacion", "filtracion"))
        self.assertIsNone(exp["dinamica"])
        self.assertEqual(exp["ubicaciones"][0]["decision"]["alcance"], "ubicacion")


class TestCierreReintentado(Base):
    def test_si_exportar_falla_se_reintenta(self):
        motor, sim, _ = motor_con(self.base)
        original = motor.exportar_entrega
        fallas = {"n": 0}

        def exportar():
            if fallas["n"] == 0:
                fallas["n"] += 1
                raise OSError("disco lleno")
            return original()
        motor.exportar_entrega = exportar
        sim.avanzar(25.1)
        motor.paso()
        self.assertTrue(motor.e["hitos"].get("cierre"))
        self.assertFalse(motor.e["hitos"].get("exportado"))
        motor.paso()
        self.assertTrue(motor.e["hitos"].get("exportado"))
        self.assertTrue((motor.salida / "entrega" / "MANIFIESTO.json").exists())


class TestAuditoriaDanada(Base):
    def test_reanuda_apartando_la_cola_danada(self):
        motor, sim, _ = motor_con(self.base)
        sim.avanzar(1.2)
        motor.paso()
        motor.detener()
        ruta = motor.salida / "auditoria.jsonl"
        lineas = ruta.read_text(encoding="utf-8").splitlines(keepends=True)
        total = len(lineas)
        e = json.loads(lineas[3])
        e["datos"]["x"] = "alterada"
        lineas[3] = json.dumps(e, ensure_ascii=False) + "\n"
        ruta.write_text("".join(lineas), encoding="utf-8")
        self.assertFalse(verificar_cadena(ruta)[0])

        usuarios = Usuarios(self.base / "jueces.json")
        otro = Motor("http://falso", motor.salida, usuarios, cliente=sim, tick=0.01, registro=lambda t: None)
        otro.arrancar(nueva=False, hilos=False)
        MOTORES.append(otro)
        ok, _, errores = verificar_cadena(ruta)
        self.assertTrue(ok, errores)
        rep = entradas(otro, "auditoria_reparada")
        self.assertEqual(len(rep), 1)
        d = rep[0]["datos"]
        self.assertEqual((d["desde_linea"], d["lineas"]), (4, total - 3))
        apartado = motor.salida / d["archivo"]
        import hashlib
        self.assertEqual(hashlib.sha256(apartado.read_bytes()).hexdigest(), d["sha256"])
        self.assertTrue(any("dañada" in a["texto"] for a in otro.e["avisos"]))
        otro.paso()  # sigue funcionando
        self.assertTrue(verificar_cadena(ruta)[0])
        from marca.exportar import exportar
        destino = exportar(otro.salida, self.base / "paquete")
        self.assertEqual((destino / "auditoria-apartada" / d["archivo"]).read_bytes(), apartado.read_bytes())


class TestValidadores(unittest.TestCase):
    def test_hostnames_e_ips(self):
        from marca import dominios
        self.assertTrue(dominios.es_hostname("s1.pirata.test"))
        self.assertTrue(dominios.ip_valida("203.0.113.10"))
        for malo in ("s1 pirata.test", 's1.pirata.test"', "", None, 5, "a..b", "-a.test", "a" * 64 + ".test"):
            self.assertFalse(dominios.es_hostname(malo), malo)
        for mala in (" 203.0.113.10", "203.0.113.300", "[::1]", None, 3):
            self.assertFalse(dominios.ip_valida(mala), mala)

    def test_kit_no_genera_comandos_con_objetivos_raros(self):
        from marca.kit import kit
        self.assertTrue(kit("ip", "203.0.113.10", 105, 10, "EXP-2026-000001", "ab12"))
        self.assertTrue(kit("dominio", "s1.pirata.test", 105, 10, "EXP-2026-000001", "ab12"))
        # Contrato: con un objetivo raro no sale ninguna línea para pegar (a lo sumo, una nota que lo explica).
        def sin_comandos(entradas):
            return all(not any(e.get(c) for c in ("preparar", "aplicar", "quitar", "vencer")) for e in entradas)
        self.assertTrue(sin_comandos(kit("dominio", 's1.pirata.test" ; /system reboot', 105, 10, "EXP-2026-000001",
                                         "ab12")))
        self.assertTrue(sin_comandos(kit("ip", "203.0.113.10; rm -rf /", 105, 10, "EXP-2026-000001", "ab12")))
        self.assertTrue(sin_comandos(kit("ip", "s1.pirata.test", 105, 10, "EXP-2026-000001", "ab12")))
        self.assertTrue(sin_comandos(kit("dominio", "s1.pirata.test", 105, 10, 'EXP"x', "ab12")))

    def test_nombre_de_captura(self):
        from marca.canon import nombre_captura
        self.assertEqual(nombre_captura("D-0001"), "D-0001.ts")
        raros = ["../../etc/passwd", "D/1", "D1/", "D 1"]
        nombres = [nombre_captura(x) for x in raros]
        self.assertEqual(len(set(nombres)), len(raros))
        for n in nombres:
            self.assertNotIn("/", n)
            self.assertFalse(n.startswith("."))


if __name__ == "__main__":
    unittest.main()
