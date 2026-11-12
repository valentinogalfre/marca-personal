"""Contratos de la ronda 3 (motor), después de la prueba en navegador contra el motor real (hallazgos N1–N20).

Cada prueba nombra el contrato que protege (C1–C12 de CONTRATO-R3) y falla si se rompe.
"""
import json
import time
import unittest

from marca import canon, dominios, marco
from marca import motor as motor_mod
from marca.motor import Motor

from tests.simulador_falso import deteccion
from tests.test_contratos_ronda2 import CDN, ConPartido, ordenes, ronda
from tests.test_contratos_ronda2b import S2, mudanza
from tests.test_robustez import PIRATA, entradas, motor_con

JUEZ_A = {"usuario": "a", "juez_id": "juez-a", "rol": "juez", "nombre": "Dra. A"}
JUEZ_B = {"usuario": "b", "juez_id": "juez-b", "rol": "juez", "nombre": "Dr. B"}


def avanzar(motor, sim, minuto):
    sim.avanzar(minuto)
    motor._t_estado = float("-inf")
    motor.paso()


def textos_visibles(obj, ruta=""):
    """Todos los textos con espacios (oraciones que lee una persona) de una vista, con su ruta."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from textos_visibles(v, f"{ruta}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from textos_visibles(v, f"{ruta}[{i}]")
    elif isinstance(obj, str) and " " in obj:
        yield ruta, obj


# ======================================================================================================
# C8: un solo redondeo de minutos
# ======================================================================================================

class TestMinTxt(unittest.TestCase):
    def test_valores_del_contrato(self):
        """[C8] 60.25 -> «60,3», 5 -> «5,0», None -> «—»: un decimal, coma, empates lejos del cero."""
        self.assertEqual(canon.min_txt(60.25), "60,3")
        self.assertEqual(canon.min_txt(5), "5,0")
        self.assertEqual(canon.min_txt(None), "—")
        self.assertEqual(canon.min_txt(-60.25), "-60,3")

    def test_nunca_menos_cero(self):
        """[C8] Un negativo que redondea a cero sale «0,0», nunca «-0,0»."""
        for x in (-0.0, -0.04, -0.049):
            self.assertEqual(canon.min_txt(x), "0,0", x)

    def test_igual_que_tofixed_del_navegador(self):
        """[C8] Valor binario exacto del número (como `Number(x).toFixed(1)`): 0.15 es 0.1499… y da «0,1»;
        0.05 es 0.0500…03 y da «0,1»; 2.675 da «2,7»; 1.25 (exacto) da «1,3»."""
        casos = {0.15: "0,1", 0.05: "0,1", 2.675: "2,7", 1.25: "1,3", 1.35: "1,4", 39.75: "39,8", 58.65: "58,6"}
        for x, esperado in casos.items():
            self.assertEqual(canon.min_txt(x), esperado, x)

    def test_lo_que_no_es_numero(self):
        """[C8] Nunca rompe: lo que no es un número finito sale «—»."""
        for x in (float("nan"), float("inf"), "x", True, [], {}):
            self.assertEqual(canon.min_txt(x), "—", x)

    def test_marco_num_saca_la_coma_cero(self):
        """[C8] marco._num pasa por min_txt y además saca el «,0» de los enteros."""
        self.assertEqual(marco._num(50), "50")
        self.assertEqual(marco._num(-60), "-60")
        self.assertEqual(marco._num(60.25), "60,3")
        self.assertEqual(marco._num(104.96), "105")
        self.assertEqual(marco._num(None), marco.NO_INFORMADO)


# ======================================================================================================
# C7: una sola leyenda de la ampliación automática
# ======================================================================================================

LAURA = "Dra. Laura Ficticia"
MARTIN = "Dr. Martín Ejemplo"


class TestTextoAmpliacion(unittest.TestCase):
    def test_sin_traspaso_con_om(self):
        """[C7] Texto exacto sin traspaso: la OM del juez que otorgó y el seguimiento que otorgó."""
        self.assertEqual(
            marco.texto_ampliacion({"id": "OM-02", "nombre": LAURA, "min": 5.8}, {"nombre": LAURA, "min": 39.8}),
            "Ampliación automática del sistema bajo la orden marco OM-02 de Dra. Laura Ficticia (minuto 5,8) y el "
            "seguimiento que otorgó en el minuto 39,8. No se firmó en persona.")

    def test_con_traspaso_con_om(self):
        """[C7] Texto exacto con traspaso: la OM del juez con cuya clave salió, que ratificó lo otorgado por otro."""
        self.assertEqual(
            marco.texto_ampliacion({"id": "OM-03", "nombre": MARTIN, "min": 58.7}, {"nombre": LAURA, "min": 39.8},
                                   {"nombre": MARTIN, "min": 60.25}),
            "Ampliación automática del sistema bajo la orden marco OM-03 de Dr. Martín Ejemplo (minuto 58,7), que en "
            "el minuto 60,3 ratificó el seguimiento otorgado por Dra. Laura Ficticia (minuto 39,8). No se firmó en "
            "persona.")

    def test_sin_om(self):
        """[C7] Dato viejo sin OM: bajo el seguimiento otorgado, con o sin ratificación."""
        self.assertEqual(
            marco.texto_ampliacion(None, {"nombre": LAURA, "min": 39.8}),
            "Ampliación automática del sistema bajo el seguimiento otorgado por Dra. Laura Ficticia en el minuto "
            "39,8. No se firmó en persona.")
        self.assertEqual(
            marco.texto_ampliacion(None, {"nombre": LAURA, "min": 39.8}, {"nombre": MARTIN, "min": 60.25}),
            "Ampliación automática del sistema bajo el seguimiento otorgado por Dra. Laura Ficticia en el minuto "
            "39,8, ratificado por Dr. Martín Ejemplo en el minuto 60,3. No se firmó en persona.")

    def test_hecha_min(self):
        """[C7] Con hecha_min se intercala « Hecha en el minuto {h}.» justo antes de «No se firmó en persona.»"""
        self.assertEqual(
            marco.texto_ampliacion({"id": "OM-02", "nombre": LAURA, "min": 5.8}, {"nombre": LAURA, "min": 39.8},
                                   hecha_min=71.04),
            "Ampliación automática del sistema bajo la orden marco OM-02 de Dra. Laura Ficticia (minuto 5,8) y el "
            "seguimiento que otorgó en el minuto 39,8. Hecha en el minuto 71,0. No se firmó en persona.")
        self.assertTrue(marco.texto_ampliacion(None, {"nombre": LAURA, "min": 1}, None, 2).endswith(
            "en el minuto 1,0. Hecha en el minuto 2,0. No se firmó en persona."))

    def test_datos_faltantes_no_rompen(self):
        """[C7] Datos faltantes: nunca una excepción."""
        texto = marco.texto_ampliacion({}, {})
        self.assertTrue(texto.endswith("No se firmó en persona."))
        self.assertNotIn("orden dinámica", texto)



class TestTextoAmpliacionEnElMotor(ConPartido):
    def test_sin_traspaso_la_leyenda_es_la_de_marco(self):
        """[C7] La leyenda de la ampliación sale de marco.texto_ampliacion con la OM que guarda decision.orden_marco."""
        motor, sim, _ = self.preparar(alcance="filtracion")
        exp = mudanza(motor, sim)
        u1, u2 = exp["ubicaciones"]
        om = motor.marco_vigente("juez-a")
        self.assertEqual(u2["decision"]["orden_marco"]["id"], om["id"])
        esperado = (f"Ampliación automática del sistema bajo la orden marco {om['id']} de Dra. A (minuto "
                    f"{canon.min_txt(om['min'])}) y el seguimiento que otorgó en el minuto "
                    f"{canon.min_txt(u1['decision']['min'])}. No se firmó en persona.")
        self.assertEqual(u2["decision"]["texto"], esperado)

    def test_con_traspaso_la_om_es_la_del_juez_con_cuya_clave_salio(self):
        """[C7][N10] Con traspaso, la leyenda cita la OM del juez entrante (con cuya clave salió la ampliación), que
        ratificó el seguimiento otorgado por el saliente; no la OM de quien lo otorgó."""
        motor, sim, usuarios = self.preparar(alcance="filtracion")
        exp = motor.e["expedientes"][0]
        otorgada_min = exp["ubicaciones"][0]["decision"]["min"]
        ronda(motor)
        avanzar(motor, sim, 10.5)
        usuarios.ingresar("b", "clave-de-prueba-b")
        motor.firmar_marco("juez-b", True)
        motor.ratificar("juez-b")
        sim.lista_detecciones.append(deteccion("D-2", 10.8, *S2))
        avanzar(motor, sim, 10.9)
        u2 = exp["ubicaciones"][1]
        self.assertEqual(u2["decision"]["tipo"], "ampliacion_dinamica")
        self.assertEqual(u2["decision"]["juez_id"], "juez-b")
        om_b = motor.marco_vigente("juez-b")
        self.assertEqual(u2["decision"]["orden_marco"]["id"], om_b["id"])
        rat = exp["dinamica"]["ratificaciones"][-1]
        esperado = (f"Ampliación automática del sistema bajo la orden marco {om_b['id']} de Dr. B (minuto "
                    f"{canon.min_txt(om_b['min'])}), que en el minuto {canon.min_txt(rat['min'])} ratificó el "
                    f"seguimiento otorgado por Dra. A (minuto {canon.min_txt(otorgada_min)}). No se firmó en persona.")
        self.assertEqual(u2["decision"]["texto"], esperado)
        # El mismo texto en todos los lugares que lo muestran.
        oid = next(o["orden_id"] for o in ordenes(motor) if o["n"] == 2)
        self.assertEqual(motor.vista_orden_publica(oid)["decision"]["texto"], esperado)
        sala = motor.vista_sala()
        self.assertEqual(sala["expedientes"][0]["ubicaciones"][1]["decision"]["texto"], esperado)
        b = motor.vista_bandeja(JUEZ_B)
        self.assertEqual(b["historial"][0]["expediente"]["ubicaciones"][1]["decision"]["texto"], esperado)
        ronda(motor)
        avanzar(motor, sim, 12.5)   # Aurora aplica entre 0,35 y 0,65 min después de recibir
        reg = [x for x in motor.vista_registro()["bloqueos"] if x["orden_id"].startswith("amp-")]
        self.assertTrue(reg)
        self.assertTrue(all(x["decision_texto"] == esperado for x in reg))

    def test_el_minuto_del_texto_es_el_publicado(self):
        """[C8] motor._min_txt es canon.min_txt: 60.25 da «60,3», igual que el navegador."""
        self.assertEqual(motor_mod._min_txt(60.25), "60,3")
        self.assertEqual(motor_mod._min_txt(None), "—")


# ======================================================================================================
# C4: ampliación levantada: el servidor vuelve al juez
# ======================================================================================================

class TestAmpliacionLevantadaVuelveAlJuez(ConPartido):
    def frenar_y_levantar(self):
        motor, sim, usuarios = self.preparar(alcance="filtracion")
        ronda(motor)
        exp = mudanza(motor, sim)          # U2 = s2, ampliada sola
        ronda(motor)
        avanzar(motor, sim, 2.0)
        motor.revocar_dinamica("juez-a", exp["id"], "Prueba de freno.", levantar=True)
        ronda(motor)
        avanzar(motor, sim, 2.2)
        return motor, sim, usuarios, exp

    def otra_deteccion(self, motor, sim, did="D-9", minuto=3.0):
        sim.lista_detecciones.append(deteccion(did, minuto, *S2))
        avanzar(motor, sim, minuto + 0.1)

    def test_la_siguiente_deteccion_abre_una_ubicacion_pendiente_con_la_nota(self):
        """[C4] Frenar y levantar una ampliación marca la ubicación; la próxima detección del mismo servidor no se
        suma: abre una ubicación nueva, pendiente, del juez de turno, que no se amplía sola y lleva la nota."""
        motor, sim, _, exp = self.frenar_y_levantar()
        u2 = exp["ubicaciones"][1]
        self.assertEqual(u2["levantada_por_freno"]["juez_id"], "juez-a")
        self.assertTrue(all(o["estado"] == "levantada" for o in ordenes(motor) if o["n"] == 2))
        self.otra_deteccion(motor, sim)
        self.assertEqual(len(exp["ubicaciones"]), 3)
        u3 = exp["ubicaciones"][2]
        self.assertNotIn("D-9", u2["detecciones"])
        self.assertEqual((u3["host"], u3["ip"], u3["estado"], u3["asignada_a"]),
                         (u2["host"], u2["ip"], "pendiente", "juez-a"))
        self.assertEqual(u3["continuidad"], {"de_ubicacion": 2, "criterio": "mismo_servidor"})  # pedido de W (R3B)
        self.assertEqual(u3["reabierta"]["de_ubicacion"], 2)
        self.assertEqual(u2["reabierta_en"], 3)
        motor._paso_dinamicas()
        self.assertEqual(u3["estado"], "pendiente", "nunca se amplía sola")
        self.assertFalse(u3["automatica"]["posible"])
        x = canon.min_txt(u2["decision"]["min"])
        y = canon.min_txt(u2["levantada_por_freno"]["min"])
        b = motor.vista_bandeja(JUEZ_A)
        pend = [p for p in b["pendientes"] if p["n"] == 3]
        self.assertEqual(len(pend), 1)
        self.assertEqual(pend[0]["nota_continuidad"],
                         f"Mismo servidor: la plataforma lo había bloqueado sola en el minuto {x}; usted levantó ese "
                         f"bloqueo en el minuto {y}.")
        sala_u3 = motor.vista_sala()["expedientes"][0]["ubicaciones"][2]
        self.assertEqual(sala_u3["nota_continuidad"],
                         f"Mismo servidor: la plataforma lo había bloqueado sola en el minuto {x}; Dra. A levantó ese "
                         f"bloqueo en el minuto {y}.")
        self.assertEqual(entradas(motor, "ubicacion_armada")[-1]["datos"]["reabre"], 2)
        # La siguiente detección del mismo servidor se suma a la ubicación nueva (no abre otra).
        self.otra_deteccion(motor, sim, "D-10", 3.5)
        self.assertEqual(len(exp["ubicaciones"]), 3)
        self.assertIn("D-10", u3["detecciones"])
        # Firmar en persona vuelve a bloquear ese servidor (el freno no lo deja vetado para el juez).
        motor.aprobar("juez-a", exp["id"], 3, "ubicacion", None, None)
        nuevas = [o for o in ordenes(motor) if o["n"] == 3]
        self.assertTrue(nuevas and all(o["orden_id"].startswith("ord-") for o in nuevas))
        self.assertEqual(u3["decision"]["ya_cubiertos"], [])
        self.assertTrue(entradas(motor, "decision_juez")[-1]["datos"]["levanta_vetos"])
        ronda(motor)
        avanzar(motor, sim, 6.0)
        self.assertTrue(all(o["estado"] == "aplicada" for o in nuevas), [o["estado"] for o in nuevas])

    def test_levantamiento_manual_y_por_reclamo_no_reabren(self):
        """[C4] El levantamiento manual de una firma en persona y el levantamiento por reclamo no reabren: las
        detecciones siguientes se suman como siempre."""
        motor, sim, _ = self.preparar()
        ronda(motor)
        avanzar(motor, sim, 1.5)
        exp = motor.e["expedientes"][0]
        motor.levantar_ubicacion("juez-a", exp["id"], 1, "Prueba de levantamiento manual")
        ronda(motor)
        sim.lista_detecciones.append(deteccion("D-7", 2.0, *PIRATA))
        avanzar(motor, sim, 2.1)
        self.assertEqual(len(exp["ubicaciones"]), 1)
        self.assertIn("D-7", exp["ubicaciones"][0]["detecciones"])
        self.assertNotIn("levantada_por_freno", exp["ubicaciones"][0])

        motor, sim, _ = self.preparar(sub="q", det=[deteccion("D-1", 1.0, *CDN)], aprobar=False)
        exp = motor.e["expedientes"][0]
        motor.aprobar("juez-a", exp["id"], 1, "ubicacion", "ip", "Prueba: forzar IP en una red compartida")
        ronda(motor)
        sim.lista_reclamos = [{"id": "R-1", "minuto": 1.3, "dominio": "panaderia.test", "proveedor": "aurora"}]
        motor._t_reclamos = float("-inf")
        motor._paso_reclamos()
        motor.resolver_reclamo("juez-a", "R-1", "levantar_y_reemplazar", None)
        ronda(motor)
        sim.lista_detecciones.append(deteccion("D-8", 2.0, *CDN))
        avanzar(motor, sim, 2.1)
        self.assertEqual(len(exp["ubicaciones"]), 1)
        self.assertIn("D-8", exp["ubicaciones"][0]["detecciones"])

    def test_frenar_sin_levantar_no_reabre(self):
        """[C4] Frenar sin levantar deja la ampliación vigente: las detecciones siguientes se suman."""
        motor, sim, _ = self.preparar(alcance="filtracion")
        exp = mudanza(motor, sim)
        motor.revocar_dinamica("juez-a", exp["id"], "")
        self.otra_deteccion(motor, sim)
        self.assertEqual(len(exp["ubicaciones"]), 2)
        self.assertIn("D-9", exp["ubicaciones"][1]["detecciones"])

    def test_sobrevive_a_guardar_y_reanudar(self):
        """[C4] La marca se guarda: tras reiniciar la plataforma, la próxima detección abre la ubicación nueva; y
        después de abrirla, un reinicio no la vuelve a abrir."""
        motor, sim, _, exp = self.frenar_y_levantar()
        m2 = self.reanudar(motor, sim)
        exp2 = m2.e["expedientes"][0]
        self.assertTrue(exp2["ubicaciones"][1]["levantada_por_freno"])
        self.otra_deteccion(m2, sim)
        self.assertEqual(len(exp2["ubicaciones"]), 3)
        self.assertEqual(exp2["ubicaciones"][2]["estado"], "pendiente")
        m3 = self.reanudar(m2, sim)
        exp3 = m3.e["expedientes"][0]
        self.otra_deteccion(m3, sim, "D-11", 3.6)
        self.assertEqual(len(exp3["ubicaciones"]), 3, "después de reiniciar no se reabre otra vez")
        self.assertIn("D-11", exp3["ubicaciones"][2]["detecciones"])

    def reanudar(self, motor, sim):
        motor.guardar()
        motor.auditoria.cerrar()
        from marca.usuarios import Usuarios
        from tests.test_robustez import MOTORES
        u = Usuarios(self.base / "p" / "jueces.json")
        u.ingresar("a", "clave-de-prueba-a")
        m2 = Motor("http://falso", motor.salida, u, cliente=sim, tick=0.01, registro=lambda t: None)
        m2.arrancar(nueva=False, hilos=False)
        MOTORES.append(m2)
        return m2


# ======================================================================================================
# C1, C2, C5: registro, estado de la orden marco, horas
# ======================================================================================================

class TestVistas(ConPartido):
    def test_c1_proveedores_en_el_registro_sin_bloqueos(self):
        """[C1] El registro público trae los proveedores del partido desde el primer momento."""
        motor, _, _ = self.preparar(aprobar=False)
        reg = motor.vista_registro()
        self.assertEqual(reg["bloqueos"], [])
        self.assertEqual(reg["proveedores"], [{"id": "aurora", "nombre": "Aurora", "capacidades": ["ip", "dominio"]},
                                              {"id": "valle", "nombre": "Valle", "capacidades": ["dominio"]}])

    def test_c2_estados_de_la_orden_marco(self):
        """[C2] reemplazada (min de la nueva) / turno_terminado (hasta_min) / partido_terminado (fin) / vigente."""
        motor, sim, usuarios = self.preparar(aprobar=False, marco=False)
        m1 = motor.vista_marco(motor.e["marcos"][0]) if motor.e["marcos"] else None
        self.assertIsNone(m1)
        motor.firmar_marco("juez-a", True)
        sim.avanzar(2.0)
        motor.firmar_marco("juez-a", False)
        v1, v2 = [motor.vista_marco(m) for m in motor.e["marcos"]]
        self.assertEqual((v1["estado"], v1["estado_min"]), ("reemplazada", motor.e["marcos"][1]["min"]))
        self.assertEqual((v2["estado"], v2["estado_min"]), ("vigente", None))
        self.assertTrue(v2["vigente"])
        avanzar(motor, sim, 10.5)
        v2 = motor.vista_marco(motor.e["marcos"][1])
        self.assertEqual((v2["estado"], v2["estado_min"]), ("turno_terminado", 10))
        self.assertTrue(v2["vigente"], "vigente queda como está")
        usuarios.ingresar("b", "clave-de-prueba-b")
        motor.firmar_marco("juez-b", True)
        vb = motor.vista_marco(motor.e["marcos"][2])
        self.assertEqual((vb["estado"], vb["estado_min"]), ("vigente", None))
        avanzar(motor, sim, 20.2)
        vb = motor.vista_marco(motor.e["marcos"][2])
        self.assertEqual((vb["estado"], vb["estado_min"]), ("partido_terminado", 20))
        self.assertEqual(motor.vista_marco(motor.e["marcos"][1])["estado"], "turno_terminado")
        self.assertEqual(motor.vista_registro()["marcos"][2]["estado"], "partido_terminado")

    def test_c5_horas_exactas(self):
        """[C5] hora_inicio (HH:MM:SS del minuto 0) y fin_hora (HH:MM de fin_min), también en el registro."""
        motor, _, _ = self.preparar(aprobar=False)
        r = motor.vista_reloj()
        self.assertEqual((r["hora_inicio"], r["fin_hora"]), ("18:00:00", "18:20"))
        reg = motor.vista_registro()["reloj"]
        self.assertEqual((reg["hora_inicio"], reg["fin_hora"]), ("18:00:00", "18:20"))


# ======================================================================================================
# C3: avisos que se cierran solos
# ======================================================================================================

class TestAvisosQueSeCierran(ConPartido):
    def avisos(self, motor, tipo):
        return [a for a in motor.e["avisos"] if a["tipo"] == tipo]

    def test_aviso_nuevo_trae_cierre_null(self):
        """[C3] Cada aviso trae `atendido` y `cierre` (null mientras no se resuelve)."""
        motor, sim, _ = self.preparar(alcance="filtracion")
        mudanza(motor, sim)
        a = motor.vista_bandeja(JUEZ_A)["avisos"][0]
        self.assertEqual((a["tipo"], a["atendido"], a["cierre"]), ("ampliacion_dinamica", False, None))

    def test_ampliacion_frenada_y_levantada(self):
        """[C3] Al frenar y levantar, el aviso de la ampliación queda atendido con el texto de lo que pasó."""
        motor, sim, _ = self.preparar(alcance="filtracion")
        ronda(motor)
        exp = mudanza(motor, sim)
        motor.revocar_dinamica("juez-a", exp["id"], "Ya se cortó la filtración.", levantar=True)
        a = self.avisos(motor, "ampliacion_dinamica")[-1]
        m = canon.min_txt(exp["dinamica"]["revocada"]["min"])
        self.assertTrue(a["atendido"])
        self.assertEqual(a["cierre"], {"min": exp["dinamica"]["revocada"]["min"],
                                       "texto": f"Usted frenó el seguimiento y levantó la ampliación en el minuto {m}."})

    def test_ampliacion_frenada_sin_levantar(self):
        """[C3] Frenar sin levantar: «Usted frenó el seguimiento en el minuto X.»"""
        motor, sim, _ = self.preparar(alcance="filtracion")
        exp = mudanza(motor, sim)
        motor.revocar_dinamica("juez-a", exp["id"], "")
        a = self.avisos(motor, "ampliacion_dinamica")[-1]
        m = canon.min_txt(exp["dinamica"]["revocada"]["min"])
        self.assertTrue(a["atendido"])
        self.assertEqual(a["cierre"]["texto"], f"Usted frenó el seguimiento en el minuto {m}.")

    def test_reclamo_resuelto_cierra_su_aviso(self):
        """[C3] El aviso de reclamo queda atendido al resolver, con lo que pasó de verdad."""
        motor, sim, _ = self.preparar(det=[deteccion("D-1", 1.0, *CDN)], aprobar=False)
        exp = motor.e["expedientes"][0]
        motor.aprobar("juez-a", exp["id"], 1, "ubicacion", "ip", "Prueba: forzar IP en una red compartida")
        motor.despacho.ronda()
        sim.lista_reclamos = [{"id": "R-1", "minuto": 1.3, "dominio": "panaderia.test", "proveedor": "aurora"},
                              {"id": "R-2", "minuto": 1.31, "dominio": "municipio.example", "proveedor": "aurora"}]
        motor._t_reclamos = float("-inf")
        motor._paso_reclamos()
        a = self.avisos(motor, "reclamo")[0]
        self.assertFalse(a["atendido"])
        self.assertIsNone(a["cierre"])
        motor.resolver_reclamo("juez-a", "R-1", "levantar_y_reemplazar", None)
        m = motor.e["reclamos"]["R-1"]["resolucion"]["min"]
        self.assertTrue(a["atendido"])
        self.assertEqual(a["cierre"], {"min": m, "texto": f"Resuelto en el minuto {canon.min_txt(m)}: levantó el "
                                                          "bloqueo y lo reemplazó por dominio."})

    def test_reclamo_desestimado(self):
        """[C3] Desestimar: «Resuelto en el minuto X: desestimó el reclamo.»"""
        motor, sim, _ = self.preparar(det=[deteccion("D-1", 1.0, *CDN)], aprobar=False)
        exp = motor.e["expedientes"][0]
        motor.aprobar("juez-a", exp["id"], 1, "ubicacion", "ip", "Prueba: forzar IP en una red compartida")
        motor.despacho.ronda()
        sim.lista_reclamos = [{"id": "R-1", "minuto": 1.3, "dominio": "panaderia.test", "proveedor": "aurora"}]
        motor._t_reclamos = float("-inf")
        motor._paso_reclamos()
        motor.resolver_reclamo("juez-a", "R-1", "desestimar", "No corresponde")
        a = self.avisos(motor, "reclamo")[0]
        m = motor.e["reclamos"]["R-1"]["resolucion"]["min"]
        self.assertEqual(a["cierre"]["texto"], f"Resuelto en el minuto {canon.min_txt(m)}: desestimó el reclamo.")

    def test_alerta_de_ausencia_se_cierra_y_puede_volver(self):
        """[C3] La alerta de juez ausente se cierra cuando vuelve; si se vuelve a ausentar, sale una nueva."""
        motor, sim, usuarios = self.preparar(aprobar=False)
        usuarios._actividad["juez-a"] = time.monotonic() - 200
        motor._paso_presencia()
        alertas = [a for a in self.avisos(motor, "alerta") if "no tiene la plataforma" in a["texto"]]
        self.assertEqual(len(alertas), 1)
        self.assertIn("hay 1 pedido esperando.", alertas[0]["texto"])
        usuarios.marcar_actividad("juez-a")
        motor._paso_presencia()
        a = alertas[0]
        self.assertTrue(a["atendido"])
        self.assertEqual(a["cierre"]["texto"],
                         f"Dra. A volvió a tener la plataforma abierta en el minuto {canon.min_txt(a['cierre']['min'])}.")
        usuarios._actividad["juez-a"] = time.monotonic() - 200
        motor._paso_presencia()
        alertas = [a for a in self.avisos(motor, "alerta") if "no tiene la plataforma" in a["texto"]]
        self.assertEqual(len(alertas), 2, "una ausencia nueva con pedidos esperando da una alerta nueva")
        self.assertFalse(alertas[-1]["atendido"])

    def test_alerta_de_ausencia_sin_pedidos(self):
        """[C3] Si ya no hay pedidos esperando: «Ya no hay pedidos esperando (minuto X).»"""
        motor, sim, usuarios = self.preparar(aprobar=False)
        usuarios._actividad["juez-a"] = time.monotonic() - 200
        motor._paso_presencia()
        exp = motor.e["expedientes"][0]
        motor.rechazar("juez-a", exp["id"], 1, "La evidencia no alcanza")
        usuarios._actividad["juez-a"] = time.monotonic() - 200
        motor._paso_presencia()
        a = [a for a in self.avisos(motor, "alerta") if "no tiene la plataforma" in a["texto"]][0]
        self.assertTrue(a["atendido"])
        self.assertEqual(a["cierre"]["texto"], f"Ya no hay pedidos esperando (minuto {canon.min_txt(a['cierre']['min'])}).")


# ======================================================================================================
# C8: texto del aviso de traspaso
# ======================================================================================================

class TestAvisoDeTraspaso(ConPartido):
    def recibir(self, alcance, dinamicas=None, marco_b=True):
        motor, sim, usuarios = self.preparar(alcance=alcance)
        ronda(motor)
        avanzar(motor, sim, 10.5)
        usuarios.ingresar("b", "clave-de-prueba-b")
        if marco_b:
            motor.firmar_marco("juez-b", True)
        motor.ratificar("juez-b", dinamicas)
        a = [a for a in motor.e["avisos"] if a["tipo"] == "traspaso" and a["para"] == "juez-b"][-1]
        m = canon.min_txt(motor.e["traspasos"][-1]["ratificado"]["min"])
        return a, m

    def test_ratifico_el_heredado(self):
        """[C8] 1 de 1: «Recibió el turno en el minuto X: ratificó el seguimiento heredado.»"""
        a, m = self.recibir("filtracion")
        self.assertTrue(a["atendido"])
        self.assertEqual(a["texto"], f"Recibió el turno en el minuto {m}: ratificó el seguimiento heredado.")
        self.assertEqual(a["cierre"]["texto"], a["texto"])

    def test_no_ratifico_ninguno(self):
        """[C8] «…: no ratificó ningún seguimiento heredado.»"""
        a, m = self.recibir("filtracion", dinamicas=[])
        self.assertEqual(a["texto"], f"Recibió el turno en el minuto {m}: no ratificó ningún seguimiento heredado.")

    def test_sin_seguimientos_heredados(self):
        """[C8] Sin seguimientos heredados: «Recibió el turno en el minuto X.»"""
        a, m = self.recibir("ubicacion")
        self.assertEqual(a["texto"], f"Recibió el turno en el minuto {m}.")

    def test_n_de_m(self):
        """[C8] «ratificó N de M seguimientos heredados.»"""
        self.assertEqual(Motor.texto_recibio_turno(60.25, 1, 2),
                         "Recibió el turno en el minuto 60,3: ratificó 1 de 2 seguimientos heredados.")


# ======================================================================================================
# C6: por qué no se amplió solo
# ======================================================================================================

class TestMotivosLlanos(ConPartido):
    def motivo(self, exp, n=2):
        return exp["ubicaciones"][n - 1]["automatica"]["motivo"]

    def test_sin_seguimiento_otorgado(self):
        """[C6] El servidor anterior se firmó solo por servidor."""
        motor, sim, _ = self.preparar(alcance="ubicacion")
        exp = mudanza(motor, sim)
        self.assertEqual(self.motivo(exp), "el servidor anterior se firmó “solo este servidor”, sin seguimiento.")

    def test_om_sin_seguimiento(self):
        """[C6] La OM del juez de turno no autoriza el seguimiento."""
        motor, sim, _ = self.preparar(alcance="filtracion")
        motor.firmar_marco("juez-a", False)
        exp = mudanza(motor, sim)
        self.assertEqual(self.motivo(exp), "su orden marco no autoriza el seguimiento.")

    def test_seguimiento_frenado(self):
        """[C6] Seguimiento frenado: con el minuto del freno."""
        motor, sim, _ = self.preparar(alcance="filtracion")
        exp = motor.e["expedientes"][0]
        motor.revocar_dinamica("juez-a", exp["id"], "")
        exp = mudanza(motor, sim)
        m = canon.min_txt(exp["dinamica"]["revocada"]["min"])
        self.assertEqual(self.motivo(exp), f"el seguimiento de esta filtración se frenó en el minuto {m}.")

    def test_espera_ratificacion(self):
        """[C6] Espera ratificación del entrante."""
        motor, sim, usuarios = self.preparar(alcance="filtracion")
        avanzar(motor, sim, 10.5)
        sim.lista_detecciones.append(deteccion("D-2", 10.6, *S2))
        avanzar(motor, sim, 10.7)
        exp = motor.e["expedientes"][0]
        self.assertEqual(self.motivo(exp), "el seguimiento espera que el juez entrante lo ratifique.")

    def test_sin_dinamica(self):
        """[C6] Plataforma con --sin-dinamica."""
        motor, sim, _ = self.preparar(alcance="ubicacion")
        motor.dinamica_habilitada = False
        exp = mudanza(motor, sim)
        self.assertEqual(self.motivo(exp), "la plataforma corre con el seguimiento deshabilitado.")

    def test_ausente(self):
        """[C6] Juez ausente: texto llano y queda para firma en persona aunque vuelva."""
        motor, sim, usuarios = self.preparar(alcance="filtracion")
        usuarios._actividad["juez-a"] = time.monotonic() - 200
        exp = mudanza(motor, sim)
        self.assertRegex(self.motivo(exp), r"^Dra\. A no tenía la plataforma abierta \(sin actividad hace \d+ s\): "
                                           r"queda para firmar en persona\.$")
        self.assertTrue(exp["ubicaciones"][1]["automatica"]["definitivo"])

    def test_ningun_motivo_dice_orden_dinamica(self):
        """[C6][N16] Ningún motivo usa la jerga «orden dinámica»."""
        motor, sim, _ = self.preparar(aprobar=False)
        exp = motor.e["expedientes"][0]
        self.assertNotIn("orden dinámica", self.motivo(exp, 1) or "")
        self.assertTrue(self.motivo(exp, 1))


# ======================================================================================================
# C9, C10, C11, C12
# ======================================================================================================

class TestConsultaPublica(ConPartido):
    def test_url_completa(self):
        """[C9] Se normaliza: esquema, usuario, puerto, ruta, consulta, fragmento, punto final y mayúsculas."""
        motor, _, _ = self.preparar(aprobar=False)
        for texto in ("https://Panaderia-La-Espiga.test/tienda?x=1", "  panaderia-la-espiga.TEST.  ",
                      "http://usuario@panaderia-la-espiga.test:8443#arriba", "panaderia-la-espiga.test?q",
                      "ftp://PANADERIA-LA-ESPIGA.test:21/a/b"):
            r = motor.consulta_publica(texto)
            self.assertEqual((r["dominio"], r["resultado"]), ("panaderia-la-espiga.test", "no_alcanzado"), texto)

    def test_lo_que_no_es_dominio_sigue_invalido(self):
        """[C9] Lo que no queda como nombre de dominio válido sigue dando «invalido»."""
        motor, _, _ = self.preparar(aprobar=False)
        for texto in ("", "   ", "https://", "no es un dominio", "203.0.113.10", "http://[2001:db8::1]/",
                      "localhost", "https://a..b/"):
            self.assertEqual(motor.consulta_publica(texto)["resultado"], "invalido", texto)

    def test_bloqueado_por_url(self):
        """[C9] Una URL del stream bloqueado por dominio da «bloqueado»."""
        motor, _, _ = self.preparar(det=[deteccion("D-1", 1.0, *CDN)])
        ronda(motor)
        r = motor.consulta_publica("https://LIVE.cdn-pirata.test/hls/index.m3u8")
        self.assertEqual((r["dominio"], r["resultado"]), ("live.cdn-pirata.test", "bloqueado"))


class TestOrdenPublicaAmpliacion(ConPartido):
    def test_texto_para_amp(self):
        """[C10] Para una orden amp-, el sello une la orden con la evidencia que evaluó la plataforma y la autorización
        del juez; para una ord-, queda el texto de siempre."""
        motor, sim, _ = self.preparar(alcance="filtracion")
        mudanza(motor, sim)
        amp = next(o for o in ordenes(motor) if o["orden_id"].startswith("amp-"))
        ord_ = next(o for o in ordenes(motor) if o["orden_id"].startswith("ord-"))
        ultimo = motor.vista_orden_publica(amp["orden_id"])["por_que"][-1]
        self.assertTrue(ultimo.endswith(
            f"el sello {amp['sello']} une esta orden con la evidencia exacta que evaluó la plataforma y con la "
            "autorización del juez (su orden marco y el seguimiento que otorgó) en el registro de auditoría."), ultimo)
        ultimo = motor.vista_orden_publica(ord_["orden_id"])["por_que"][-1]
        self.assertTrue(ultimo.endswith("evidencia exacta que vio el juez y con su decisión en el registro de "
                                        "auditoría."), ultimo)


class TestRenglonDosDeLaOM(unittest.TestCase):
    PARTIDO = {"id": "p", "nombre": "P", "titular_derechos": "T", "fin_min": 105}

    def linea(self, desde, hasta, partido=None):
        c = marco.armar(partido or self.PARTIDO, [], {}, {"desde_min": desde, "hasta_min": hasta}, False)
        return c["lineas"][1]

    def test_turno_que_termina_antes(self):
        """[C11] Primer turno: desde antes del inicio hasta el minuto 50."""
        self.assertEqual(self.linea(-60, 50),
                         "Esta orden vale durante mi turno en este partido: desde antes del inicio hasta el minuto 50. "
                         "Todo bloqueo que se ordene bajo ella vence, como máximo, al final del partido (minuto 105).")

    def test_turno_que_llega_al_final(self):
        """[C11] Turno que llega al final: hasta el final del partido (minuto 105)."""
        self.assertEqual(self.linea(50, 240),
                         "Esta orden vale durante mi turno en este partido: desde el minuto 50 hasta el final del "
                         "partido (minuto 105). Todo bloqueo que se ordene bajo ella vence, como máximo, al final del "
                         "partido (minuto 105).")

    def test_datos_faltantes(self):
        """[C11] Datos faltantes: «no informado», nunca rompe."""
        texto = self.linea(None, None, {"id": "p"})
        self.assertIn("no informado", texto)
        self.assertTrue(texto.startswith("Esta orden vale durante mi turno en este partido: desde "))


class TestContadores(ConPartido):
    def test_ubicaciones_levantadas(self):
        """[C12] kpis.ubicaciones_levantadas: aprobadas con todas sus órdenes aplicadas levantadas."""
        motor, sim, _ = self.preparar()
        ronda(motor)
        avanzar(motor, sim, 2.0)
        ronda(motor)
        avanzar(motor, sim, 2.5)
        k = motor.vista_sala()["kpis"]
        self.assertEqual(k["ubicaciones_levantadas"], 0)
        exp = motor.e["expedientes"][0]
        motor.levantar_ubicacion("juez-a", exp["id"], 1, "Prueba de levantamiento")
        ronda(motor)
        avanzar(motor, sim, 3.0)
        self.assertTrue(all(o["estado"] == "levantada" for o in ordenes(motor) if o.get("aplicada_min") is not None))
        k = motor.vista_sala()["kpis"]
        self.assertEqual(k["ubicaciones_levantadas"], 1)
        self.assertIn("ubicaciones_bloqueadas", k)

    def test_pedido_singular_y_plural(self):
        """[C12][N9] «hay 1 pedido esperando» / «hay 2 pedidos esperando»."""
        motor, sim, usuarios = self.preparar(det=[deteccion("D-1", 1.0, *PIRATA), deteccion("D-3", 1.0, *CDN)],
                                             aprobar=False)
        usuarios._actividad["juez-a"] = time.monotonic() - 200
        motor._paso_presencia()
        textos = [a["texto"] for a in motor.e["avisos"] if "no tiene la plataforma" in a["texto"]]
        self.assertEqual(textos, ["Dra. A está de turno y no tiene la plataforma abierta: hay 2 pedidos esperando."])


# ======================================================================================================
# Vocabulario (N16): «seguimiento» y «frenar» en todo texto visible del motor
# ======================================================================================================

class TestVocabulario(ConPartido):
    def test_ni_orden_dinamica_ni_revocar_en_textos_visibles(self):
        """[N16] Ningún texto que arma el motor para una persona dice «orden dinámica» ni «revocar»."""
        motor, sim, usuarios = self.preparar(alcance="filtracion")
        ronda(motor)
        exp = mudanza(motor, sim)
        ronda(motor)
        motor.revocar_dinamica("juez-a", exp["id"], "Ya se cortó la filtración.", levantar=True)
        sim.lista_detecciones.append(deteccion("D-3", 2.5, "s3.pirata.test", "203.0.113.12", "LP26-PRU-OFI-S0001",
                                               "https://pirata.test/vivo", 64600))
        avanzar(motor, sim, 2.6)
        ronda(motor)
        avanzar(motor, sim, 10.5)
        usuarios.ingresar("b", "clave-de-prueba-b")
        vistas = {"bandeja_a": motor.vista_bandeja(JUEZ_A), "bandeja_b": motor.vista_bandeja(JUEZ_B),
                  "sala": dict(motor.vista_sala(), auditoria=[]), "registro": motor.vista_registro()}
        for o in ordenes(motor):
            vistas[o["orden_id"]] = motor.vista_orden_publica(o["orden_id"])
        malos = [(k + ruta, t) for k, v in vistas.items() for ruta, t in textos_visibles(v)
                 if "orden dinámica" in t.lower() or "órdenes dinámicas" in t.lower() or "revoc" in t.lower()]
        self.assertEqual(malos, [])


# ======================================================================================================
# G: objetivos por dominio
# ======================================================================================================

class TestObjetivosDominio(unittest.TestCase):
    HOSTS_PRACTICA = ("s1.pelotaya.test", "s2.pelotaya.test", "s3.pelotaya.test", "live.golazo-libre.test",
                      "tv.verpartido-hd.test", "x9.tribuna-pirata.test", "x10.tribuna-pirata.test")

    def test_hosts_del_escenario_oficial_validos(self):
        """[G] Todos los hosts del escenario de práctica siguen siendo objetivos válidos."""
        for h in self.HOSTS_PRACTICA:
            self.assertTrue(dominios.objetivo_valido("dominio", h), h)

    def test_sufijos_pelados_y_raros_no(self):
        """[G] Al menos dos etiquetas, nunca un sufijo de registro pelado (C16: el guion bajo vale)."""
        for h in ("com", "net", "org", "ar", "com.ar", "gob.ar", "gov.ar", "org.ar", "net.ar", "edu.ar", "test",
                  "example", "invalid", "localhost", "pirata", "co.uk",
                  "com.br", "", "a..b", ".pirata.test", "pirata.test.", "-x.test"):
            self.assertFalse(dominios.objetivo_valido("dominio", h), h)
        self.assertTrue(dominios.objetivo_valido("dominio", "mitienda.com.ar"))
        self.assertTrue(dominios.objetivo_valido("dominio", "pirata.test"))

    def test_ip_valida(self):
        """[G] Sin zona, sin saltos de línea, sin direcciones no ruteables; documentación sí."""
        for ip in ("fe80::1%en0", "203.0.113.10\n", "10.0.0.1", "127.0.0.1", "169.254.1.1", "100.64.0.1",
                   "224.0.0.1", "240.0.0.1", "255.255.255.255", "::1", "fc00::1", "fe80::1", "0.0.0.0", "192.168.1.1",
                   "172.16.0.1", " 203.0.113.10"):
            self.assertFalse(dominios.ip_valida(ip), repr(ip))
        for ip in ("192.0.2.10", "198.51.100.20", "203.0.113.10", "2001:db8::1", "8.8.8.8"):
            self.assertTrue(dominios.ip_valida(ip), ip)


# ======================================================================================================
# C13: un proveedor que falla se sigue reintentando (sin tope), con una sola alerta y a ritmo de 1 por minuto
# ======================================================================================================

TEXTO_SEIS = "falló 6 veces el bloqueo de"


class TestReintentosSinTope(ConPartido):
    def _cadena(self, motor, pid):
        """Las órdenes de un proveedor para el mismo objetivo, en orden de intento."""
        return sorted((o for o in ordenes(motor) if o["proveedor"] == pid), key=lambda o: o["intento"])

    def _alertas_seis(self, motor):
        return [a for a in motor.e["avisos"] if a["tipo"] == "alerta" and TEXTO_SEIS in a["texto"]]

    def test_ocho_fallas_y_aplica_en_el_noveno(self):
        """[C13] Aurora falla 8 veces y aplica en el 9.º intento: la orden queda aplicada (no hay tope) y sale
        exactamente UNA alerta «falló 6 veces … sigue reintentando», nunca «no se reintenta más»."""
        motor, sim, _ = self.preparar(aprobar=False)
        sim.fallas_al_aplicar["aurora"] = 8
        exp = motor.e["expedientes"][0]
        motor.aprobar("juez-a", exp["id"], 1, "ubicacion", None, None)
        m = 1.2
        while m < 9.9:
            ronda(motor)
            m = round(m + 0.1, 2)
            avanzar(motor, sim, m)
        ronda(motor)
        cadena = self._cadena(motor, "aurora")
        self.assertEqual([o["intento"] for o in cadena], list(range(1, 10)), "intento consecutivo, sin elegir números")
        self.assertEqual([o["estado"] for o in cadena], ["fallida"] * 8 + ["aplicada"])
        self.assertEqual(len({(o["tipo"], o["objetivo"], o["sello"]) for o in cadena}), 1, "mismo objetivo y sello")
        alertas = self._alertas_seis(motor)
        self.assertEqual(len(alertas), 1, [a["texto"] for a in alertas])
        self.assertEqual(alertas[0]["texto"],
                         f"Aurora falló 6 veces el bloqueo de {cadena[0]['objetivo']}. La plataforma sigue "
                         "reintentando; conviene avisarle al proveedor.")
        self.assertFalse(any("no se reintenta" in a["texto"] for a in motor.e["avisos"]))
        self.assertFalse(any(r["evento"] == "orden_rechazada" for r in sim.registro))

    def test_desde_el_septimo_un_envio_por_minuto(self):
        """[C13] Del 1.º al 6.º intento el ritmo no cambia (se reintenta en cuanto llega la falla); desde el 7.º,
        como máximo un envío por (proveedor, tipo, objetivo) cada 1 minuto de partido."""
        motor, sim, _ = self.preparar(aprobar=False)
        sim.fallas_al_aplicar["aurora"] = 8
        exp = motor.e["expedientes"][0]
        motor.aprobar("juez-a", exp["id"], 1, "ubicacion", None, None)
        m = 1.2
        while m < 9.9:
            ronda(motor)
            m = round(m + 0.1, 2)
            avanzar(motor, sim, m)
        envios = [r["min"] for r in sim.registro if r["evento"] == "orden_recibida" and r["proveedor"] == "aurora"]
        self.assertEqual(len(envios), 9)
        primeros = [b - a for a, b in zip(envios[:6], envios[1:6])]
        self.assertTrue(all(d < 1.0 for d in primeros), primeros)
        espaciados = [round(envios[i] - envios[i - 1], 3) for i in range(6, 9)]
        self.assertTrue(all(d >= 1.0 for d in espaciados), espaciados)

    def test_el_despacho_respeta_el_no_antes(self):
        """[C13] Un 7.º intento creado al minuto X no sale antes de (envío anterior + 1); sale después."""
        motor, sim, _ = self.preparar()
        ronda(motor)
        o = self._cadena(motor, "aurora")[0]
        o["intento"] = 6
        o["estado"] = "fallida"
        motor._reintentar(o)
        nueva = next(x for x in ordenes(motor) if x.get("reemplaza") == o["orden_id"])
        self.assertEqual(nueva["intento"], 7)
        self.assertAlmostEqual(nueva["no_antes_min"], o["enviada_min"] + 1.0, places=3)
        avanzar(motor, sim, o["enviada_min"] + 0.5)
        ronda(motor)
        self.assertEqual(nueva["estado"], "por_enviar")
        avanzar(motor, sim, o["enviada_min"] + 1.05)
        ronda(motor)
        self.assertEqual(nueva["estado"], "recibida")

    def test_sin_reintento_despues_del_corte(self):
        """[C13] Pasado fin − margen de envío no se crea ningún intento (aunque no haya tope)."""
        motor, sim, _ = self.preparar()
        ronda(motor)
        o = self._cadena(motor, "aurora")[0]
        o["intento"] = 9
        o["estado"] = "fallida"
        avanzar(motor, sim, 16.0)
        motor.margen_envio = lambda *a, **k: 5.0  # corte en el minuto 15
        motor._reintentar(o)
        self.assertFalse([x for x in ordenes(motor) if x.get("reemplaza") == o["orden_id"]])
        motor.margen_envio = lambda *a, **k: 0.0  # control: antes del corte sí se reintenta (intento 10)
        motor._reintentar(o)
        nuevas = [x for x in ordenes(motor) if x.get("reemplaza") == o["orden_id"]]
        self.assertEqual([x["intento"] for x in nuevas], [10])

    def test_un_intento_cuyo_no_antes_cae_pasado_el_corte_no_se_crea(self):
        """[C13] Si el minuto de espera del 7.º intento ya cae pasado el corte, no se crea (nunca sale tarde)."""
        motor, sim, _ = self.preparar()
        ronda(motor)
        o = self._cadena(motor, "aurora")[0]
        o["intento"] = 7
        o["estado"] = "fallida"
        o["enviada_min"] = 14.5
        avanzar(motor, sim, 14.6)
        motor.margen_envio = lambda *a, **k: 5.0  # corte en el minuto 15; el próximo envío no antes de 15,5
        motor._reintentar(o)
        self.assertFalse([x for x in ordenes(motor) if x.get("reemplaza") == o["orden_id"]])

    def test_vetada_o_en_levantamiento_no_se_reintenta(self):
        """[C13] Una orden vetada o con levantamiento pedido no se reintenta (ni en el intento 9)."""
        motor, sim, _ = self.preparar()
        ronda(motor)
        o = self._cadena(motor, "aurora")[0]
        o["intento"] = 9
        o["estado"] = "fallida"
        motor.e["vetados"].append([o["tipo"], o["objetivo"]])
        motor._reintentar(o)
        self.assertFalse([x for x in ordenes(motor) if x.get("reemplaza") == o["orden_id"]])
        motor.e["vetados"].remove([o["tipo"], o["objetivo"]])
        o["levantar"] = {"motivo": "prueba", "juez_id": "juez-a"}
        motor._reintentar(o)
        self.assertFalse([x for x in ordenes(motor) if x.get("reemplaza") == o["orden_id"]])
        self.assertFalse(self._alertas_seis(motor))

    def test_orden_id_pasado_el_99(self):
        """[C13] El contador de la orden pasa de 99 sin romper el formato: «-100-», mismo sello al final."""
        motor, sim, _ = self.preparar()
        ronda(motor)
        o = self._cadena(motor, "aurora")[0]
        o["estado"] = "fallida"
        _, u = motor.ubicacion(o["exp"], o["n"])
        u["contadores"]["aurora"] = 99
        motor._reintentar(o)
        nueva = next(x for x in ordenes(motor) if x.get("reemplaza") == o["orden_id"])
        self.assertIn("-aurora-100-", nueva["orden_id"])
        self.assertEqual(nueva["orden_id"].rsplit("-", 1)[-1], o["sello"])
        self.assertEqual(nueva["k"], 100)


if __name__ == "__main__":
    unittest.main()
