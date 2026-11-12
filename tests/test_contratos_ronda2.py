"""Contratos de la ronda 2: simulador remoto (latencia), despacho, lógica judicial, datos raros y vistas.

Cada prueba nombra el contrato que protege (entre corchetes, el id del hallazgo de la auditoría).
"""
import base64
import json
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from marca import despacho as despacho_mod
from marca import dominios, evidencia, kit, reloj as reloj_mod, turnos
from marca import motor as motor_mod
from marca.simulador import Cliente

from tests.simulador_falso import DNS, SimuladorFalso, deteccion
from tests.test_robustez import PIRATA, Base, entradas, motor_con

CDN = ("live.cdn-pirata.test", "198.51.100.20", "LP26-PRU-OFI-S0002", "https://cdn-pirata.test/p", 64610)


def ordenes(motor, estado=None):
    return [o for o in motor.e["ordenes"].values() if estado is None or o["estado"] == estado]


def sin_espera(motor):
    """Las pruebas no esperan los tiempos reales entre consultas de una orden en duda."""
    for o in motor.e["ordenes"].values():
        o["t_error"] = None
        o["t_post"] = None
        if o.get("levantar"):
            o["levantar"].pop("t_rechazo", None)


def ronda(motor, veces=1):
    for _ in range(veces):
        sin_espera(motor)
        motor.despacho.ronda()


def eventos(sim, evento):
    return [r for r in sim.registro if r["evento"] == evento]


class ConPartido(Base):
    def preparar(self, sub="p", det=None, minuto=1.2, aprobar=True, alcance="ubicacion", usuario="a", sim=None,
                 marco=True):
        motor, sim, usuarios = motor_con(self.base / sub, sim)
        sim.lista_detecciones = det if det is not None else [deteccion("D-1", 1.0, *PIRATA)]
        usuarios.ingresar(usuario, "clave-de-prueba-" + usuario)
        sim.avanzar(minuto)
        motor._t_estado = float("-inf")
        motor.paso()
        if marco:  # ronda 2b: lo dinámico exige la orden marco con seguimiento
            motor.firmar_marco("juez-" + usuario, True)
        if aprobar:
            exp = motor.e["expedientes"][0]
            motor.aprobar("juez-" + usuario, exp["id"], 1, alcance, None, None)
        return motor, sim, usuarios


# ======================================================================================================
# A1 [tiempos-1] Una respuesta tardía de /estado no es un reinicio del simulador
# ======================================================================================================

class TestRelojLecturasTardias(unittest.TestCase):
    def test_respuesta_de_un_pedido_anterior_se_descarta(self):
        r = reloj_mod.Reloj()
        self.assertEqual(r.actualizar(10.0, 20, t_pedido=100.0, t_respuesta=100.1), reloj_mod.ACEPTADA)
        # Pedida ANTES que la aceptada y llegada después, con un minuto muy viejo: no dice nada nuevo.
        self.assertEqual(r.actualizar(4.0, 20, t_pedido=99.0, t_respuesta=101.0), reloj_mod.IGNORADA)
        self.assertFalse(r.retrocedio)
        self.assertEqual(r.minuto_ultimo, 10.0)

    def test_una_sola_lectura_baja_no_declara_retroceso(self):
        r = reloj_mod.Reloj()
        r.actualizar(10.0, 20, t_pedido=100.0, t_respuesta=100.1)
        self.assertEqual(r.actualizar(2.0, 20, t_pedido=101.0, t_respuesta=101.1), reloj_mod.SOSPECHA)
        self.assertFalse(r.retrocedio)
        self.assertTrue(r.sospechoso)
        # Una lectura coherente descarta la sospecha.
        self.assertEqual(r.actualizar(10.8, 20, t_pedido=102.0, t_respuesta=102.1), reloj_mod.ACEPTADA)
        self.assertFalse(r.sospechoso)

    def test_reinicio_real_se_confirma_con_dos_lecturas(self):
        r = reloj_mod.Reloj()
        r.actualizar(10.0, 20, t_pedido=100.0, t_respuesta=100.1)
        r.actualizar(2.0, 20, t_pedido=101.0, t_respuesta=101.1)
        self.assertEqual(r.actualizar(2.3, 20, t_pedido=102.0, t_respuesta=102.1), reloj_mod.RETROCESO)
        self.assertTrue(r.retrocedio)

    def test_umbral_crece_con_la_duracion_y_la_aceleracion(self):
        # x60 y una consulta de 2 s: el umbral es (2 + 1) × 60 / 60 = 3 min; 2 min abajo no es sospecha.
        r = reloj_mod.Reloj()
        r.actualizar(10.0, 60, t_pedido=100.0, t_respuesta=100.1)
        self.assertEqual(r.actualizar(8.0, 60, t_pedido=101.0, t_respuesta=103.0), reloj_mod.IGNORADA)
        self.assertFalse(r.sospechoso)
        # A x1 el mismo salto (umbral 1 min) sí es sospecha.
        r1 = reloj_mod.Reloj()
        r1.actualizar(10.0, 1, t_pedido=100.0, t_respuesta=100.1)
        self.assertEqual(r1.actualizar(8.0, 1, t_pedido=101.0, t_respuesta=101.1), reloj_mod.SOSPECHA)

    def test_bandera_se_limpia_sola_si_vuelve_la_linea_de_tiempo(self):
        r = reloj_mod.Reloj()
        r.actualizar(10.0, 20, t_pedido=100.0, t_respuesta=100.1)
        r.actualizar(2.0, 20, t_pedido=101.0, t_respuesta=101.1)
        r.actualizar(2.3, 20, t_pedido=102.0, t_respuesta=102.1)
        # En t=103 la línea anterior está en 10 + 3 s × 20 / 60 = 11.
        self.assertEqual(r.actualizar(11.0, 20, t_pedido=103.0, t_respuesta=103.1), reloj_mod.DESPEJADO)
        self.assertFalse(r.retrocedio)


class TestRelojEnElMotor(ConPartido):
    def test_alerta_de_retroceso_dice_que_hacer_y_se_limpia(self):
        motor, sim, _ = self.preparar(aprobar=False, minuto=5.0)
        sim.avanzar(1.0)  # dos lecturas bajas seguidas: reinicio
        motor.estado_fresco()
        self.assertFalse(motor.reloj.retrocedio)
        motor.estado_fresco()
        self.assertTrue(motor.reloj.retrocedio)
        textos = [a["datos"]["texto"] for a in entradas(motor, "alerta")]
        self.assertTrue(any("--nueva" in t and "--inicio-min" in t for t in textos), textos)
        ok, _ = motor.puede_firmar_con("juez-a", motor.estado_fresco())
        self.assertFalse(ok, "con el reloj en duda no se firma")
        sim.avanzar(5.0)  # vuelve a la línea anterior
        motor.estado_fresco()
        self.assertFalse(motor.reloj.retrocedio)
        self.assertTrue(any(a["datos"].get("clave") == "retroceso-despejado" for a in entradas(motor, "alerta")))

    def test_respuesta_tardia_no_alerta(self):
        motor, sim, _ = self.preparar(aprobar=False, minuto=5.0)
        t_viejo = time.monotonic() - 5.0
        motor.estado_fresco()
        motor._actualizar_reloj({"minuto_actual": 0.5, "acelerar": sim.acelerar}, t_viejo, time.monotonic())
        motor._actualizar_reloj({"minuto_actual": 0.5, "acelerar": sim.acelerar}, t_viejo, time.monotonic())
        self.assertFalse(motor.reloj.retrocedio)
        self.assertFalse(any("retrocedió" in a["datos"]["texto"] for a in entradas(motor, "alerta")))


# ======================================================================================================
# A2 [tiempos-2, concurrencia-4] Los márgenes incluyen la latencia; con /estado lento no se firma
# ======================================================================================================

class TestMargenesConLatencia(unittest.TestCase):
    def test_formulas(self):
        self.assertAlmostEqual(turnos.margen_fin(20, 0.0), 2 * 20 / 60)
        self.assertAlmostEqual(turnos.margen_fin(20, 1.0), 3.5 * 20 / 60)
        self.assertAlmostEqual(turnos.margen_inicio(20, 1.0), 1.5 * 20 / 60)
        self.assertEqual(turnos.margen_fin(0.0001, 0.0), 0.05)

    def test_inicio_de_turno_con_latencia(self):
        tt = [{"juez_id": "j", "desde_min": 10, "hasta_min": 100}]
        est = {"minuto_actual": 10.2, "acelerar": 20, "jueces_de_turno": ["j"]}
        self.assertTrue(turnos.puede_firmar_con("j", est, tt)[0])                      # margen 0,17 min
        self.assertFalse(turnos.puede_firmar_con("j", dict(est, _dur_s=1.0), tt)[0])   # margen 0,5 min
        self.assertFalse(turnos.puede_firmar_con("j", est, tt, duracion_s=1.0)[0])

    def test_estado_lento_no_firma(self):
        tt = [{"juez_id": "j", "desde_min": 0, "hasta_min": 100}]
        ok, motivo = turnos.puede_firmar_con("j", {"minuto_actual": 50, "acelerar": 1, "jueces_de_turno": ["j"],
                                                   "_dur_s": 3.5}, tt)
        self.assertFalse(ok)
        self.assertIn("lenta", motivo)


class TestDespachoConLatencia(ConPartido):
    def test_estado_de_mas_de_3_s_no_firma_en_esa_ronda(self):
        motor, sim, _ = self.preparar()
        real = motor.estado_fresco
        motor.estado_fresco = lambda: dict(real(), _dur_s=3.5)
        motor.despacho.ronda()
        self.assertEqual(eventos(sim, "orden_recibida"), [])
        self.assertTrue(all(o["estado"] == "por_enviar" and not o.get("en_vuelo") for o in ordenes(motor)))
        motor.estado_fresco = real
        motor.despacho.ronda()
        self.assertEqual(len(eventos(sim, "orden_recibida")), 3)

    def test_cerca_del_final_la_latencia_agranda_el_margen(self):
        # x20, faltan 0,9 min (2,7 s reales). Sin latencia (margen 0,67 min) sale; con D = 1 s (1,17 min) no.
        for dur, sale in ((0.0, True), (1.0, False)):
            with self.subTest(dur=dur):
                motor, sim, _ = self.preparar(sub=f"fin{dur}", det=[deteccion("D-1", 19.0, *PIRATA)], minuto=19.05,
                                              usuario="b")
                sim.acelerar = 20
                sim.avanzar(19.1)
                if dur:
                    motor.reloj.registrar_duracion(dur)
                motor.despacho.ronda()
                self.assertEqual(bool(eventos(sim, "orden_recibida")), sale)
                self.assertEqual(eventos(sim, "orden_rechazada"), [])


# ======================================================================================================
# A3 [tiempos-3, concurrencia-5, protocolo-6] La ronda no espera; en_vuelo se libera siempre
# ======================================================================================================

class TestRondaNoEspera(ConPartido):
    def test_post_lento_no_frena_a_los_demas_ni_a_la_ronda(self):
        motor, sim, _ = self.preparar()
        liberar = threading.Event()
        cuenta = {"n": 0}
        candado = threading.Lock()

        def antes():
            with candado:
                cuenta["n"] += 1
                primero = cuenta["n"] == 1
            if primero:
                liberar.wait(5)
        sim.antes["enviar_orden"] = antes
        t0 = time.monotonic()
        motor.despacho.ronda(esperar=False)
        self.assertLess(time.monotonic() - t0, 1.0, "la ronda no espera a sus envíos")
        limite = time.monotonic() + 3
        while len(eventos(sim, "orden_recibida")) < 2 and time.monotonic() < limite:
            time.sleep(0.02)
        self.assertEqual(len(eventos(sim, "orden_recibida")), 2, "los otros dos POST salieron")
        self.assertEqual(sum(1 for o in ordenes(motor) if o.get("en_vuelo")), 1)
        liberar.set()
        limite = time.monotonic() + 3
        while any(o.get("en_vuelo") for o in ordenes(motor)) and time.monotonic() < limite:
            time.sleep(0.02)
        self.assertFalse(any(o.get("en_vuelo") for o in ordenes(motor)))
        self.assertEqual(len(ordenes(motor, "recibida")), 3)

    def test_error_inesperado_libera_en_vuelo(self):
        motor, sim, usuarios = self.preparar()
        with mock.patch.object(usuarios, "firmar_con", side_effect=RuntimeError("falla de prueba")):
            motor.despacho.ronda()
        self.assertFalse(any(o.get("en_vuelo") for o in ordenes(motor)))
        motor.despacho.ronda()
        self.assertEqual(len(ordenes(motor, "recibida")), 3)

    def test_si_no_se_puede_guardar_no_sale_nada_y_queda_constancia(self):
        motor, sim, _ = self.preparar()
        with mock.patch.object(motor, "guardar", side_effect=OSError("disco lleno")):
            motor.despacho.ronda()
        self.assertEqual(eventos(sim, "orden_recibida"), [])
        self.assertFalse(any(o.get("en_vuelo") for o in ordenes(motor)))
        self.assertTrue(any("No se pudo guardar" in a["datos"]["texto"] for a in entradas(motor, "alerta")))

    def test_tiempos_de_espera_proporcionales_a_la_latencia(self):
        c = Cliente("http://127.0.0.1:9", timeout=5.0)
        self.assertEqual((c.timeout_get(), c.timeout_post()), (1.5, 3.0))
        c._anotar_latencia(0.6)
        self.assertAlmostEqual(c.timeout_get(), 2.8)
        self.assertAlmostEqual(c.timeout_post(), 4.4)
        c._anotar_latencia(5.0)
        self.assertEqual((c.timeout_get(), c.timeout_post()), (5.0, 10.0))


# ======================================================================================================
# A4 [protocolo-1, concurrencia-2, pruebas-y-operacion-3] Respuesta al POST de una orden
# ======================================================================================================

class TestRespuestaAlPost(ConPartido):
    def assert_sin_rechazos(self, sim, motor):
        self.assertEqual(eventos(sim, "orden_rechazada"), [])
        self.assertEqual(ordenes(motor, "rechazada"), [])

    def test_504_de_un_proxy_con_la_orden_aplicada_se_adopta(self):
        motor, sim, _ = self.preparar()
        sim.guion["enviar_orden"] = [("despues", 504, "<html>Gateway Timeout</html>")] * 3
        motor.despacho.ronda()
        self.assertTrue(all(o["incierta"] for o in ordenes(motor)))
        ronda(motor)
        self.assertEqual(len(ordenes(motor, "recibida")), 3)
        self.assertEqual(len(entradas(motor, "orden_reconciliada")), 3)
        self.assertEqual(len(eventos(sim, "orden_recibida")), 3, "ninguna se mandó dos veces")
        self.assert_sin_rechazos(sim, motor)

    def test_409_se_adopta_nunca_rechazada(self):
        motor, sim, _ = self.preparar()
        sim.guion["enviar_orden"] = [("despues", 409, {"error": "Ya existe una orden con ese orden_id"})] * 3
        motor.despacho.ronda()
        self.assertEqual(len(ordenes(motor, "recibida")), 3)
        self.assertTrue(all(e["datos"]["estado"] == "recibida" for e in entradas(motor, "orden_reconciliada")))
        self.assertEqual(ordenes(motor, "rechazada"), [])

    def test_502_sin_efecto_se_reenvia_solo_tras_dos_404(self):
        motor, sim, _ = self.preparar()
        sim.guion["enviar_orden"] = [(502, None)] * 3
        motor.despacho.ronda()
        ids = sorted(o["orden_id"] for o in ordenes(motor))
        self.assertTrue(all(o["incierta"] for o in ordenes(motor)))
        ronda(motor)  # primer GET: 404 → todavía no se reenvía
        self.assertEqual(eventos(sim, "orden_recibida"), [])
        self.assertTrue(all(o["incierta"] and o["n_404"] == 1 for o in ordenes(motor)))
        ronda(motor)  # segundo 404 y pasó el tiempo de espera del POST → mismo orden_id
        self.assertEqual(sorted(e["orden_id"] for e in eventos(sim, "orden_recibida")), ids)
        self.assert_sin_rechazos(sim, motor)

    def test_no_se_reenvia_antes_de_que_venza_el_post(self):
        motor, sim, _ = self.preparar()
        sim.guion["enviar_orden"] = [(502, None)] * 3
        motor.despacho.ronda()
        for _ in range(2):
            for o in ordenes(motor):
                o["t_error"] = None  # el POST se mandó recién: t_post queda
            motor.despacho.ronda()
        self.assertEqual(eventos(sim, "orden_recibida"), [])

    def test_429_y_cuerpo_ajeno_son_inciertos(self):
        for respuesta in ((429, {"error": "demasiados pedidos"}), (403, "<html>Forbidden</html>"),
                          (500, {"error": "interno"}), (408, None)):
            with self.subTest(respuesta=respuesta):
                motor, sim, _ = self.preparar(sub=str(respuesta[0]) + type(respuesta[1]).__name__)
                sim.guion["enviar_orden"] = [respuesta] * 3
                motor.despacho.ronda()
                self.assertTrue(all(o["incierta"] and o["estado"] == "por_enviar" for o in ordenes(motor)))
                self.assertEqual(ordenes(motor, "rechazada"), [])

    def test_rechazo_definitivo_solo_con_el_json_del_simulador(self):
        motor, sim, _ = self.preparar()
        sim.guion["enviar_orden"] = [(422, {"error": "tipo no aceptado"})] * 3
        motor.despacho.ronda()
        self.assertEqual(len(ordenes(motor, "rechazada")), 3)

    def test_espera_creciente_y_alerta_al_tercer_intento(self):
        motor, sim, _ = self.preparar()
        sim.guion["enviar_orden"] = ["red"] * 3
        sim.guion["orden"] = [(503, None)] * 9
        motor.despacho.ronda()
        o = ordenes(motor)[0]
        self.assertEqual(despacho_mod.espera_incierta(o), 1.0)
        ronda(motor, 2)
        self.assertGreaterEqual(o["intentos_inciertos"], 3)
        self.assertGreater(despacho_mod.espera_incierta(o), 1.0)
        claves = [a for a in motor.e["avisos"] if str(a.get("clave", "")).startswith("incierta-enviar-")]
        self.assertEqual(len(claves), 3, "una alerta por orden, al tercer intento")
        self.assertTrue(all(a["para"] is None for a in claves), "las fallas van a la sala")


# ======================================================================================================
# A5 [concurrencia-3, protocolo-4] «levantada» si y solo si hay una entrada orden_levantada
# ======================================================================================================

class TestLevantamientoIncierto(ConPartido):
    def levantar(self):
        motor, sim, _ = self.preparar()
        motor.despacho.ronda()
        sim.avanzar(2.0)
        exp = motor.e["expedientes"][0]
        motor.levantar_ubicacion("juez-a", exp["id"], 1, "Prueba de levantamiento")
        return motor, sim

    def assert_invariante(self, motor):
        lev = {e["datos"]["orden_id"] for e in entradas(motor, "orden_levantada")}
        self.assertEqual({o["orden_id"] for o in ordenes(motor, "levantada")}, lev)

    def test_respuesta_perdida_se_confirma_por_consulta(self):
        motor, sim = self.levantar()
        sim.guion["levantar"] = ["red_despues"] * 3
        motor.despacho.ronda()
        self.assertTrue(all(o.get("lev_incierto") for o in ordenes(motor)))
        self.assertEqual(ordenes(motor, "levantada"), [])
        self.assert_invariante(motor)
        ronda(motor)
        self.assertEqual(len(ordenes(motor, "levantada")), 3)
        lev = entradas(motor, "orden_levantada")
        self.assertTrue(all(e["datos"].get("confirmada_por_consulta") and e["datos"].get("firma") for e in lev))
        self.assertEqual(len(sim.lev_registro), 3, "no se levantó dos veces")
        self.assert_invariante(motor)

    def test_respuesta_ajena_y_sigue_activa_se_reintenta(self):
        motor, sim = self.levantar()
        sim.guion["levantar"] = [(502, None)] * 3
        motor.despacho.ronda()
        ronda(motor)
        self.assertEqual(len(ordenes(motor, "levantada")), 3)
        self.assertTrue(all(e["datos"].get("firma") and not e["datos"].get("confirmada_por_consulta")
                            for e in entradas(motor, "orden_levantada")))
        self.assert_invariante(motor)

    def test_firma_del_levantamiento_es_la_del_juez(self):
        motor, sim = self.levantar()
        motor.despacho.ronda()
        self.assertEqual(len(ordenes(motor, "levantada")), 3, "el simulador falso exige la firma LEVANTAR|orden|juez")
        self.assertTrue(all(x["juez_de_turno"] for x in sim.lev_registro))

    def test_levantamiento_a_medio_hacer_se_confirma_al_reanudar(self):
        motor, sim = self.levantar()
        sim.guion["levantar"] = ["red_despues"] * 3
        motor.despacho.ronda()
        motor.guardar()
        motor.auditoria.cerrar()
        from marca.motor import Motor
        from marca.usuarios import Usuarios
        m2 = Motor("http://falso", motor.salida, Usuarios(self.base / "p" / "jueces.json"), cliente=sim, tick=0.01,
                   registro=lambda t: None)
        m2.arrancar(nueva=False, hilos=False)
        try:
            self.assertTrue(all(o.get("lev_incierto") for o in ordenes(m2) if o["estado"] != "levantada"))
            ronda(m2)
            self.assertEqual(len(ordenes(m2, "levantada")), 3)
            self.assertEqual(len(sim.lev_registro), 3)
            self.assert_invariante(m2)
        finally:
            m2.despacho._pool.shutdown(wait=False)
            m2.auditoria.cerrar()


# ======================================================================================================
# A6 [tiempos-5, protocolo-2] Cierre aunque el simulador no conteste
# ======================================================================================================

class TestCierreSinSimulador(ConPartido):
    def test_testigos_desde_fin_mas_1_y_cierre_sin_conexion(self):
        motor, sim, _ = self.preparar()
        motor.despacho.ronda()
        sim.avanzar(21.2)
        motor.estado_fresco()
        motor._paso_fin()
        motor._paso_fin()
        self.assertTrue(motor.e["hitos"].get("testigos_previos"), "testigos tomados desde fin+1")
        self.assertTrue((motor.salida / "testigos" / "proveedores.json").exists())
        sim.avanzar(25.5)
        motor.estado_fresco()
        sim.caido = True
        with mock.patch.object(motor_mod, "CIERRE_SIN_CONEXION_S", 0.05):
            motor._paso_fin()
            self.assertFalse(motor.e["hitos"].get("cierre"), "espera antes de cerrar sin conexión")
            time.sleep(0.1)
            motor._paso_fin()
        hit = motor.e["hitos"]
        self.assertTrue(hit.get("cierre") and hit.get("exportado"))
        vv = entradas(motor, "vencimiento_verificado")
        self.assertTrue(vv and vv[-1]["datos"].get("sin_conexion"))
        self.assertTrue((motor.salida / "entrega").exists())
        self.assertTrue(hit.get("paquete") and hit["paquete"]["huella"])

    def test_inciertas_se_concilian_al_cierre(self):
        motor, sim, _ = self.preparar()
        sim.guion["enviar_orden"] = ["red_despues", "red", "red"]
        motor.despacho.ronda()
        sim.guion["orden"] = [(503, None)] * 99  # el GET no aclara nada
        sim.avanzar(20.5)
        motor.estado_fresco()
        motor._paso_fin()
        self.assertTrue(all(not o.get("no_enviada") for o in ordenes(motor) if o.get("incierta")),
                        "al fin, las que están en duda no se dan por no enviadas")
        sim.avanzar(25.5)
        motor.estado_fresco()
        motor._paso_fin()
        self.assertFalse(any(o.get("incierta") for o in ordenes(motor)))
        self.assertEqual(sum(1 for o in ordenes(motor) if o.get("aplicada_min") is not None or
                             o["estado"] in ("recibida", "aplicada", "vencida")), 1)
        self.assertEqual(sum(1 for o in ordenes(motor) if o.get("no_enviada")), 2)


# ======================================================================================================
# A7 [tiempos-4] Listas y DNS en paralelo, la red siempre fuera del candado
# ======================================================================================================

class TestRedEnParalelo(ConPartido):
    def test_dns_de_un_lote_en_paralelo_y_fuera_del_candado(self):
        motor, sim, _ = self.preparar(aprobar=False, det=[])
        sim.lista_detecciones = [deteccion("D-1", 1.3, *PIRATA), deteccion("D-2", 1.3, *CDN)]
        libres = []

        def lento(f):
            def g(x):
                ok = motor.candado.acquire(timeout=0.2)
                libres.append(ok)
                if ok:
                    motor.candado.release()
                time.sleep(0.3)
                return f(x)
            return g
        sim.dns_ip, sim.dns_dominio = lento(sim.dns_ip), lento(sim.dns_dominio)
        sim.avanzar(1.4)
        t0 = time.monotonic()
        motor._paso_detecciones()
        self.assertLess(time.monotonic() - t0, 0.9, "cuatro consultas de 0,3 s en paralelo")
        self.assertEqual(len(motor.e["expedientes"]), 2)
        self.assertTrue(libres and all(libres), "ninguna consulta corre con el candado tomado")

    def test_listas_de_seguimiento_en_paralelo(self):
        motor, sim, _ = self.preparar()
        motor.despacho.ronda()
        real = sim.ordenes

        def lenta(pid):
            time.sleep(0.3)
            return real(pid)
        sim.ordenes = lenta
        t0 = time.monotonic()
        motor._paso_seguimiento()
        self.assertLess(time.monotonic() - t0, 0.55)


# ======================================================================================================
# A8 [protocolo-5, pruebas-y-operacion-4] Una orden que desaparece del proveedor se vuelve a emitir
# ======================================================================================================

class TestOrdenPerdida(ConPartido):
    def perder(self):
        motor, sim, _ = self.preparar()
        motor.despacho.ronda()
        sim.avanzar(3.0)
        oid = next(o["orden_id"] for o in ordenes(motor) if o["proveedor"] == "aurora")
        del sim._ords["aurora"][oid]
        for o in ordenes(motor):
            o["t_confirmada"] = None
        motor._t_seg.clear()
        return motor, sim, oid

    def test_perdida_y_reemision_con_mismo_sello(self):
        motor, sim, oid = self.perder()
        motor._paso_seguimiento()
        o = motor.e["ordenes"][oid]
        self.assertEqual(o["estado"], "perdida")
        self.assertEqual([e["datos"] for e in entradas(motor, "orden_perdida")], [{"orden_id": oid,
                                                                                  "proveedor": "aurora"}])
        nueva = [x for x in ordenes(motor) if x.get("reemplaza") == oid]
        self.assertEqual(len(nueva), 1)
        self.assertEqual((nueva[0]["sello"], nueva[0]["k"], nueva[0]["origen"]), (o["sello"], o["k"] + 1,
                                                                                    "reemision_perdida"))
        motor.despacho.ronda()
        self.assertEqual(nueva[0]["estado"], "recibida")
        self.assertTrue(any(a.get("clave") == "perdida-" + oid for a in motor.e["avisos"]))

    def test_con_el_reloj_en_duda_no_hay_perdidas(self):
        motor, sim, oid = self.perder()
        motor.reloj.retrocedio = True
        motor._paso_seguimiento()
        self.assertNotEqual(motor.e["ordenes"][oid]["estado"], "perdida")

    def test_recien_confirmada_no_se_da_por_perdida(self):
        motor, sim, oid = self.perder()
        motor.e["ordenes"][oid]["t_confirmada"] = time.monotonic()
        motor._paso_seguimiento()
        self.assertNotEqual(motor.e["ordenes"][oid]["estado"], "perdida")


# ======================================================================================================
# B. Lógica judicial
# ======================================================================================================

class TestLogicaJudicial(ConPartido):
    def test_b1_dinamica_cubre_solo_la_marca_firmada(self):
        dets = [deteccion("D-1", 1.0, *PIRATA),
                deteccion("D-2", 1.05, "s2.pirata.test", "203.0.113.11", "LP26-PRU-OFI-S0009",
                          "https://pirata.test/vivo", 64600)]
        motor, sim, _ = self.preparar(det=dets, aprobar=False)
        exp = motor.e["expedientes"][0]
        self.assertEqual(len(exp["ubicaciones"]), 2)
        motor.rechazar("juez-a", exp["id"], 2, "No es la misma señal")
        motor.aprobar("juez-a", exp["id"], 1, "filtracion", None, None)
        self.assertEqual(exp["dinamica"]["marcas"], ["LP26-PRU-OFI-S0001"])
        motor.revocar_dinamica("juez-a", exp["id"], "")
        sim.lista_detecciones.append(deteccion("D-3", 1.3, "s3.pirata.test", "203.0.113.11", "LP26-PRU-OFI-S0007",
                                               "https://pirata.test/vivo", 64600))
        sim.avanzar(1.4)
        motor.paso()
        motor.aprobar("juez-a", exp["id"], 3, "filtracion", None, None)
        self.assertEqual(exp["dinamica"]["marcas"], ["LP26-PRU-OFI-S0007"], "volver a otorgar no arrastra las otras")

    def test_b2_orden_en_duda_cuenta_como_causante(self):
        motor, sim, _ = self.preparar(det=[deteccion("D-1", 1.0, *CDN)], aprobar=False)
        exp = motor.e["expedientes"][0]
        motor.aprobar("juez-a", exp["id"], 1, "ubicacion", "ip", "Prueba: forzar IP en una red compartida")
        sim.guion["enviar_orden"] = ["red"] * 3
        motor.despacho.ronda()
        self.assertTrue(any(o["tipo"] == "ip" and o["incierta"] for o in ordenes(motor)))
        sim.lista_reclamos = [{"id": "R-1", "minuto": 1.3, "dominio": "panaderia.test", "proveedor": "aurora",
                               "mensaje": "no anda"}]
        motor._t_reclamos = float("-inf")
        motor._paso_reclamos()
        r = motor.e["reclamos"]["R-1"]
        self.assertEqual(r["estado"], "pendiente", "no se cierra solo mientras haya órdenes en duda")
        self.assertTrue(any(c["incierta"] for c in r["verificacion"]["ordenes_causantes"]))

    def test_b3_levantamiento_heredado_lo_firma_el_entrante_al_ratificar(self):
        motor, sim, usuarios = self.preparar()
        motor.despacho.ronda()
        sim.avanzar(9.5)
        exp = motor.e["expedientes"][0]
        motor.levantar_ubicacion("juez-a", exp["id"], 1, "Prueba de levantamiento heredado")
        sim.avanzar(10.5)
        motor._t_estado = float("-inf")
        motor._paso_estado()
        tr = motor.e["traspasos"][-1]
        pend = tr["resumen"]["levantamientos_pendientes"]
        self.assertEqual(len(pend), 3)
        self.assertEqual(set(pend[0]), {"orden_id", "proveedor", "objetivo", "reclamo"})
        motor.despacho.ronda()
        self.assertEqual(sim.lev_registro, [], "el saliente ya no firma y el entrante no ratificó")
        usuarios.ingresar("b", "clave-de-prueba-b")
        motor.ratificar("juez-b")
        motor.despacho.ronda()
        lev = entradas(motor, "orden_levantada")
        self.assertEqual(len(lev), 3)
        self.assertTrue(all(e["datos"]["juez_id"] == "juez-b" and e["datos"]["heredado_de"] == "juez-a"
                            and e["datos"]["ratificacion"] for e in lev))
        self.assertTrue(all(x["juez_de_turno"] for x in sim.lev_registro))
        aviso = next(a for a in motor.e["avisos"] if a.get("tipo") == "traspaso" and a.get("para") == "juez-b")
        self.assertTrue(aviso["atendido"])
        self.assertIn("Recibió el turno en el minuto", aviso["texto"])  # ronda 3, C8
        rat = entradas(motor, "traspaso_ratificado")[-1]
        self.assertEqual(len(rat["datos"]["levantamientos_pendientes"]), 3)

    def test_b4_revocar_sin_motivo_y_apartarse_exige_fundamento(self):
        motor, sim, _ = self.preparar(aprobar=False)
        exp = motor.e["expedientes"][0]
        with self.assertRaises(motor_mod.ErrorAccion):
            motor.aprobar("juez-a", exp["id"], 1, "ubicacion", "dominio", "corto")
        motor.aprobar("juez-a", exp["id"], 1, "filtracion", None, None)
        motor.revocar_dinamica("juez-a", exp["id"], None)
        self.assertEqual(entradas(motor, "dinamica_revocada")[-1]["datos"]["motivo"], "")


# ======================================================================================================
# C. Datos raros baratos
# ======================================================================================================

class TestDatosRaros(ConPartido):
    def test_asn_no_numerico(self):
        self.assertEqual([evidencia._asn(x) for x in (64600, 64600.0, "64600", "AS64600", "as 64600", "abc", None,
                                                      True, 1.5)],
                         [64600, 64600, 64600, 64600, 64600, None, None, None, None])
        det = deteccion("D-1", 1.0, *PIRATA)
        dns_ip = {"ip": "203.0.113.10", "asn": 64600, "dominios": DNS["203.0.113.10"]}
        for asn, esperado in (("AS64600", True), ("raro", None), (64601, False)):
            a = evidencia.analizar_servidor(dict(det, asn=asn), dns_ip, None, [])
            self.assertEqual(a["coherencia"]["asn_coincide"], esperado)

    def test_host_con_mayusculas_y_punto_final_sale_tal_cual(self):
        det = deteccion("D-1", 1.0, "S1.Pirata.TEST.", "203.0.113.10", "LP26-PRU-OFI-S0001",
                        "https://pirata.test/vivo", 64600)
        motor, sim, _ = self.preparar(det=[det])
        u = motor.e["expedientes"][0]["ubicaciones"][0]
        self.assertEqual(u["host"], "s1.pirata.test")
        self.assertIn("s1.pirata.test", motor.e["dns"]["dominio"])
        objetivos = sorted(o["objetivo"] for o in ordenes(motor) if o["tipo"] == "dominio")
        self.assertIn("S1.Pirata.TEST.", objetivos, "el objetivo es exactamente el host_stream del simulador")
        motor.despacho.ronda()
        self.assertEqual(eventos(sim, "orden_rechazada"), [])
        o = next(o for o in ordenes(motor) if o["objetivo"] == "S1.Pirata.TEST.")
        k = kit.kit("dominio", o["objetivo"], 20, 1.0, "EXP-1", "abc")
        self.assertTrue(k and all("S1.Pirata" not in x["aplicar"] for x in k), "el kit va normalizado")

    def test_captura_con_saltos_de_linea_o_ausente(self):
        crudo = bytes([0x47]) + b"x" * 200
        b64 = base64.b64encode(crudo).decode()
        partido = "\n".join(b64[i:i + 76] for i in range(0, len(b64), 76))
        self.assertEqual(evidencia.decodificar_captura({"contenido_b64": partido}), crudo)
        det = dict(deteccion("D-1", 1.0, *PIRATA))
        del det["captura"]
        motor, sim, _ = self.preparar(det=[det], aprobar=False)
        u = motor.e["expedientes"][0]["ubicaciones"][0]
        self.assertIsNone(u["captura"]["sha256"])
        self.assertFalse(u["colateral"]["limpia"])

    def test_deteccion_de_minuto_negativo(self):
        motor, sim, _ = self.preparar(det=[deteccion("D-1", -3.0, *PIRATA)], aprobar=False)
        self.assertEqual(len(motor.e["expedientes"]), 1)

    def test_dominio_de_licenciatario_con_comodin_o_esquema(self):
        for d in ("*.canalnorte.test", "https://canalnorte.test/vivo", "CanalNorte.TEST.", ".canalnorte.test"):
            with self.subTest(d=d):
                self.assertTrue(dominios.cubre(d, "envivo.canalnorte.test"))
                self.assertFalse(dominios.cubre(d, "canalnorte.test.pirata.test"))
        partido = {"marcas_de_agua_validas": [{"prefijo": "LP26-PRU-LIC-NORTE"}],
                   "licenciatarios": [{"nombre": "Norte", "prefijo_marca": "LP26-PRU-LIC-NORTE",
                                       "dominios_autorizados": ["https://*.canalnorte.test/"]}]}
        s = evidencia.analizar_senal("LP26-PRU-LIC-NORTE", partido, "envivo.canalnorte.test")
        self.assertEqual(s["clase"], "licenciatario")


# ======================================================================================================
# D [concurrencia-6] La foto de testigos deja testigos, estado.json y auditoría coherentes
# ======================================================================================================

class TestFotoDeTestigos(ConPartido):
    def test_foto_a_mitad_de_partido_es_coherente(self):
        motor, sim, _ = self.preparar()
        motor.despacho.ronda()
        sim.avanzar(3.0)  # el simulador ya las aplicó; nosotros todavía no lo sabemos
        motor.pedir_testigos()
        motor._paso_pedido_testigos()
        testigos = json.loads((motor.salida / "testigos" / "proveedores.json").read_text(encoding="utf-8"))
        estado = json.loads((motor.salida / "estado.json").read_text(encoding="utf-8"))
        for pid, lista in testigos["proveedores"].items():
            for s in lista:
                self.assertEqual(estado["ordenes"][s["orden_id"]]["estado"], s["estado"])
        e = entradas(motor, "testigos_guardados")[-1]
        self.assertIn("corte_auditoria", e["datos"])
        self.assertLess(e["datos"]["corte_auditoria"], e["n"])

    def test_durante_la_foto_no_sale_nada(self):
        motor, sim, _ = self.preparar()
        motor._foto = True
        self.assertEqual(motor.despacho._pendientes(), ([], []))
        motor._foto = False
        self.assertEqual(len(motor.despacho._pendientes()[0]), 3)


# ======================================================================================================
# E. Campos de las vistas
# ======================================================================================================

class TestVistas(ConPartido):
    def test_e1_orden_con_levantamiento_y_reclamo(self):
        motor, sim, _ = self.preparar()
        o = ordenes(motor)[0]
        v = motor.vista_orden(o)
        self.assertIsNone(v["levantamiento"])
        self.assertIn("reclamo", v)
        motor.despacho.ronda()
        exp = motor.e["expedientes"][0]
        motor.levantar_ubicacion("juez-a", exp["id"], 1, "Motivo de prueba")
        motor.despacho.ronda()
        v = motor.vista_orden(o)
        self.assertEqual(set(v["levantamiento"]), {"min", "juez", "juez_nombre", "motivo", "reclamo"})
        self.assertEqual((v["levantamiento"]["juez"], v["levantamiento"]["juez_nombre"]), ("juez-a", "Dra. A"))

    def test_e2_e3_bandeja_y_ampliacion(self):
        dets = [deteccion("D-1", 1.0, *PIRATA)]
        motor, sim, usuarios = self.preparar(det=dets, alcance="filtracion")
        motor.despacho.ronda()
        sim.lista_detecciones.append(deteccion("D-2", 9.0, "s2.pirata.test", "203.0.113.11", "LP26-PRU-OFI-S0001",
                                               "https://pirata.test/vivo", 64600))
        sim.avanzar(10.5)
        motor._t_estado = float("-inf")
        motor.paso()
        usuarios.ingresar("b", "clave-de-prueba-b")
        motor.firmar_marco("juez-b", True)  # ronda 2b: ratificar lo dinámico exige la OM con seguimiento
        motor.ratificar("juez-b")
        motor._paso_dinamicas()
        u2 = motor.e["expedientes"][0]["ubicaciones"][1]
        dec = u2["decision"]
        self.assertEqual(dec["tipo"], "ampliacion_dinamica")
        self.assertEqual(dec["otorgada_por"]["juez_id"], "juez-a")
        self.assertEqual(dec["ratificada_por"]["juez_id"], "juez-b")
        # Ronda 2b, sección 7: nunca «ampliación dinámica de Dr. X».
        # Ronda 3, C7 (N10): la OM citada es la del juez con cuya clave salió (el entrante), no la de quien otorgó.
        self.assertIn("Ampliación automática del sistema bajo la orden marco OM-02 de Dr. B (minuto", dec["texto"])
        self.assertIn(", que en el minuto 10,5 ratificó el seguimiento otorgado por Dra. A (minuto", dec["texto"])
        self.assertTrue(dec["texto"].endswith("No se firmó en persona."))
        b = motor.vista_bandeja(usuarios.ficha("b") if hasattr(usuarios, "ficha") else
                                {"usuario": "b", "juez_id": "juez-b", "rol": "juez", "nombre": "Dr. B"})
        din = b["dinamicas"][0]
        self.assertEqual(set(din["otorgada_por"]), {"juez_id", "nombre", "min", "entrada"})
        self.assertEqual(din["ratificada_por"]["juez_id"], "juez-b")
        self.assertEqual(len(b["historial_traspasos"]), 1)
        self.assertLessEqual({"min", "de", "ratificado", "resumen"}, set(b["historial_traspasos"][0]))
        self.assertTrue(all({"clave", "cuenta", "atendido"} <= set(a) for a in b["avisos"]))
        self.assertIn("historial_reclamos", b)

    def test_e2_avisos_agrupados_y_fallas_a_la_sala(self):
        motor, sim, _ = self.preparar()
        for _ in range(3):
            motor.aviso("reclamo", "x", para="juez-a", clave="reclamo:o1|o2")
        agrupados = [a for a in motor.e["avisos"] if a.get("clave") == "reclamo:o1|o2"]
        self.assertEqual(len(agrupados), 1)
        self.assertEqual(agrupados[0]["cuenta"], 3)
        motor.despacho.ronda()
        o = ordenes(motor, "recibida")[0]
        motor._aplicar_estado_sim(o, {"estado": "fallida", "motivo": "falla de prueba"})
        fallas = [a for a in motor.e["avisos"] if a["tipo"] in ("orden_fallida", "reintento")]
        self.assertTrue(fallas and all(a["para"] is None for a in fallas))

    def test_e2_historial_de_reclamos(self):
        motor, sim, _ = self.preparar(det=[deteccion("D-1", 1.0, *CDN)], aprobar=False)
        exp = motor.e["expedientes"][0]
        motor.aprobar("juez-a", exp["id"], 1, "ubicacion", "ip", "Prueba: forzar IP en una red compartida")
        motor.despacho.ronda()
        sim.lista_reclamos = [{"id": "R-1", "minuto": 1.3, "dominio": "panaderia.test", "proveedor": "aurora"},
                              {"id": "R-2", "minuto": 1.31, "dominio": "municipio.example", "proveedor": "aurora"}]
        motor._t_reclamos = float("-inf")
        motor._paso_reclamos()
        avisos = [a for a in motor.e["avisos"] if a["tipo"] == "reclamo"]
        self.assertEqual(len(avisos), 1, "dos reclamos por la misma orden causante: un solo aviso")
        self.assertEqual(avisos[0]["cuenta"], 2)
        motor.resolver_reclamo("juez-a", "R-1", "levantar_y_reemplazar", None)
        h = motor._historial_reclamos("juez-a")
        self.assertEqual([x["id"] for x in h], ["R-1"])
        self.assertEqual(h[0]["cerrados_junto"], ["R-2"])
        self.assertEqual(set(h[0]), {"id", "dominio", "proveedor_nombre", "minuto", "resolucion", "cerrados_junto"})

    def test_e4_e5_e6(self):
        motor, sim, _ = self.preparar()
        motor.despacho.ronda()
        sala = motor.vista_sala()
        self.assertIn("ordenes_con_dano_colateral_vigentes", sala["kpis"])
        self.assertIn("perdidas", sala["kpis"]["ordenes"])
        self.assertIsNone(sala["paquete"])
        self.assertIsNone(motor.vista_registro()["paquete"])
        self.assertEqual(motor.vista_orden_publica(ordenes(motor)[0]["orden_id"])["v"], motor.v)
        motor.exportar_entrega()
        p = motor.vista_sala()["paquete"]
        self.assertEqual(set(p), {"huella", "exportado_min"})
        self.assertEqual(motor.vista_registro()["paquete"], p)


if __name__ == "__main__":
    unittest.main()
