"""Contratos de la ronda 2b (motor): orden marco, presencia, prefijo amp-, privacidad, lista del proveedor,
traspaso y revocación, textos, «propios», corte en origen y adenda 3 (ventana, sin decidir, juez automático).

Cada prueba nombra el contrato que protege; la sección de ESPEC/ADENDA va entre corchetes.
"""
import json
import time
import unittest

from marca import dominios, evidencia, marco, sello
from marca import motor as motor_mod
from marca.motor import ErrorAccion, Motor

from tests.simulador_falso import deteccion
from tests import test_contratos_ronda2 as t2
from tests.test_contratos_ronda2 import CDN, ConPartido, eventos, ordenes, ronda
from tests.test_robustez import PIRATA, entradas

S2 = ("s2.pirata.test", "203.0.113.11", "LP26-PRU-OFI-S0001", "https://pirata.test/vivo", 64600)


def mudanza(motor, sim, minuto=1.5):
    """La misma sesión aparece en otro servidor."""
    sim.lista_detecciones.append(deteccion("D-2", minuto, *S2))
    sim.avanzar(minuto + 0.1)
    motor._t_estado = float("-inf")
    motor.paso()
    return motor.e["expedientes"][0]


# ======================================================================================================
# Sección 1: orden marco
# ======================================================================================================

class TestOrdenMarco(ConPartido):
    def test_firma_auditoria_huella_y_firma_verificables(self):
        """[1] La OM queda en la auditoría con su contenido; la huella y la firma se recalculan desde ahí."""
        motor, _, _ = self.preparar(aprobar=False, marco=False)
        vista = motor.firmar_marco("juez-a", True)
        e = entradas(motor, "orden_marco")[-1]
        d = e["datos"]
        self.assertEqual((e["actor"], e.get("exp")), ("juez:juez-a", None))
        self.assertEqual(set(d), {"id", "juez_id", "juzgado_id", "huella", "seguimiento", "contenido", "firma",
                                  "reemplaza"})
        self.assertEqual((d["id"], d["seguimiento"], d["reemplaza"]), ("OM-01", True, None))
        self.assertEqual(marco.huella(d["contenido"]), d["huella"])
        self.assertEqual(sello.firma_marco("clave-a", "prueba-01", d["huella"], "juez-a", True), d["firma"])
        self.assertEqual(d["contenido"]["juez"]["juez_id"], "juez-a")
        self.assertEqual(len(d["contenido"]["lineas"]), 6)
        self.assertEqual(set(vista), {"id", "juez_id", "juez", "juzgado", "min", "hora", "huella", "seguimiento",
                                      "turno", "entrada", "vigente", "estado", "estado_min"})  # + ronda 3, C2
        self.assertTrue(vista["vigente"])

    def test_mensaje_de_firma_una_sola_fuente(self):
        """[1] sello.mensaje_marco y marco.mensaje_firma dan el mismo texto, con el formato fijado."""
        for seg in (True, False):
            self.assertEqual(sello.mensaje_marco("p1", "ab" * 32, "juez-a", seg),
                             marco.mensaje_firma("p1", "ab" * 32, "juez-a", seg))
        self.assertEqual(sello.mensaje_marco("p1", "h", "juez-a", True), "MARCO|p1|h|juez-a|S1")
        self.assertEqual(sello.firma_marco("k", "p1", "h", "juez-a", False),
                         sello.firmar("k", "MARCO|p1|h|juez-a|S0"))

    def test_vale_la_ultima_y_reemplaza(self):
        """[1] Un juez puede volver a firmarla: vale la última suya, que cita la entrada que reemplaza."""
        motor, _, _ = self.preparar(aprobar=False, marco=False)
        motor.firmar_marco("juez-a", True)
        primera = entradas(motor, "orden_marco")[-1]
        motor.firmar_marco("juez-a", False)
        segunda = entradas(motor, "orden_marco")[-1]
        self.assertEqual(segunda["datos"]["reemplaza"], primera["n"])
        self.assertEqual(motor.marco_vigente("juez-a")["id"], "OM-02")
        self.assertFalse(motor.seguimiento_autorizado("juez-a"))
        sala = motor.vista_sala()
        self.assertEqual([m["vigente"] for m in sala["marcos"]], [False, True])

    def test_seguir_a_la_filtracion_exige_om_con_seguimiento(self):
        """[1] Sin OM con seguimiento del juez, alcance «filtracion» es inválido; por servidor, no hace falta."""
        motor, _, _ = self.preparar(aprobar=False, marco=False)
        exp = motor.e["expedientes"][0]
        with self.assertRaises(ErrorAccion) as ctx:
            motor.aprobar("juez-a", exp["id"], 1, "filtracion", None, None)
        self.assertEqual(ctx.exception.texto, motor_mod.TEXTO_SIN_MARCO)
        motor.firmar_marco("juez-a", False)
        with self.assertRaises(ErrorAccion):
            motor.aprobar("juez-a", exp["id"], 1, "filtracion", None, None)
        motor.aprobar("juez-a", exp["id"], 1, "ubicacion", None, None)
        dec = entradas(motor, "decision_juez")[-1]["datos"]
        om = entradas(motor, "orden_marco")[-1]
        self.assertEqual(dec["orden_marco"], {"entrada": om["n"], "huella": om["datos"]["huella"]})

    def test_decision_sin_om_cita_null(self):
        """[1] Toda decision_juez lleva orden_marco: null si el juez no tiene OM."""
        motor, _, _ = self.preparar(aprobar=False, marco=False)
        exp = motor.e["expedientes"][0]
        motor.aprobar("juez-a", exp["id"], 1, "ubicacion", None, None)
        self.assertIn("orden_marco", entradas(motor, "decision_juez")[-1]["datos"])
        self.assertIsNone(entradas(motor, "decision_juez")[-1]["datos"]["orden_marco"])

    def test_ampliacion_cita_la_om_del_juez_que_respalda(self):
        """[1][3] La ampliación cita la OM vigente con seguimiento del juez que la respalda y sale con amp-."""
        motor, sim, _ = self.preparar(alcance="filtracion")
        exp = mudanza(motor, sim)
        u2 = exp["ubicaciones"][1]
        self.assertEqual(u2["decision"]["tipo"], "ampliacion_dinamica")
        amp = entradas(motor, "ampliacion_dinamica")[-1]["datos"]
        om = entradas(motor, "orden_marco")[-1]
        self.assertEqual(amp["orden_marco"], {"entrada": om["n"], "huella": om["datos"]["huella"]})
        mias = [o for o in ordenes(motor) if o["n"] == 2]
        self.assertTrue(mias and all(o["orden_id"].startswith("amp-") for o in mias), [o["orden_id"] for o in mias])
        self.assertTrue(all(o["orden_id"].startswith("ord-") for o in ordenes(motor) if o["n"] == 1))
        self.assertTrue(u2["decision"]["texto"].startswith(
            "Ampliación automática del sistema bajo la orden marco OM-01 de Dra. A (minuto"))
        self.assertTrue(u2["decision"]["texto"].endswith("No se firmó en persona."))

    def test_sin_seguimiento_en_la_om_no_amplia(self):
        """[1] Si el juez apaga el seguimiento en su OM, la mudanza vuelve a él con el motivo escrito."""
        motor, sim, _ = self.preparar(alcance="filtracion")
        motor.firmar_marco("juez-a", False)
        exp = mudanza(motor, sim)
        u2 = exp["ubicaciones"][1]
        self.assertEqual(u2["estado"], "pendiente")
        self.assertEqual(u2["automatica"]["motivo"], "su orden marco no autoriza el seguimiento.")  # ronda 3, C6

    def test_sin_dinamica_la_om_se_firma_sin_casilla(self):
        """[1] Con --sin-dinamica la OM se firma igual, sin seguimiento (seguimiento_disponible: false)."""
        motor, _, _ = self.preparar(aprobar=False, marco=False)
        motor.dinamica_habilitada = False
        with self.assertRaises(ErrorAccion):
            motor.firmar_marco("juez-a", True)
        motor.firmar_marco("juez-a", False)
        b = motor.vista_bandeja({"usuario": "a", "juez_id": "juez-a", "rol": "juez", "nombre": "Dra. A"})
        self.assertFalse(b["marco"]["seguimiento_disponible"])

    def test_vistas_de_la_om(self):
        """[1] vista_bandeja.marco, vista_sala.marcos/.jueces y vista_registro.marcos con los campos del contrato."""
        motor, _, _ = self.preparar(aprobar=False, marco=False)
        b = motor.vista_bandeja({"usuario": "a", "juez_id": "juez-a", "rol": "juez", "nombre": "Dra. A"})
        self.assertEqual(set(b["marco"]), {"firmada", "propuesta", "puede_firmar", "motivo_no",
                                           "seguimiento_disponible"})
        self.assertIsNone(b["marco"]["firmada"])
        self.assertEqual(set(b["marco"]["propuesta"]), {"lineas", "condiciones_seguimiento", "titulo_casilla"})
        self.assertEqual(b["marco"]["propuesta"]["titulo_casilla"], marco.TITULO_CASILLA)
        self.assertTrue(b["marco"]["puede_firmar"])
        self.assertEqual({p["id"] for p in b["proveedores"]}, {"aurora", "valle"})
        motor.firmar_marco("juez-a", True)
        b = motor.vista_bandeja({"usuario": "a", "juez_id": "juez-a", "rol": "juez", "nombre": "Dra. A"})
        self.assertEqual(set(b["marco"]["firmada"]), {"id", "min", "hora", "entrada", "huella", "seguimiento"})
        sala = motor.vista_sala()
        self.assertEqual(len(sala["marcos"]), 1)
        jueces = {j["juez_id"]: j for j in sala["jueces"]}
        self.assertEqual(set(jueces["juez-a"]), {"juez_id", "nombre", "de_turno", "turno", "activo", "hace_s", "marco"})
        self.assertEqual(jueces["juez-a"]["marco"], {"id": "OM-01", "seguimiento": True})
        self.assertTrue(jueces["juez-a"]["activo"])
        self.assertIsNone(jueces["juez-b"]["marco"])
        self.assertEqual(len(motor.vista_registro()["marcos"]), 1)

    def test_fuera_de_turno_no_firma(self):
        """[1] Mismas reglas de turno que una decisión."""
        motor, _, _ = self.preparar(aprobar=False, marco=False)
        with self.assertRaises(ErrorAccion) as ctx:
            motor.firmar_marco("juez-b", True)
        self.assertEqual(ctx.exception.codigo, "fuera_de_turno")
        self.assertEqual(entradas(motor, "orden_marco"), [])


# ======================================================================================================
# Sección 2: presencia real del juez
# ======================================================================================================

class TestPresencia(ConPartido):
    def test_ausente_no_amplia_y_queda_para_firma_en_persona(self):
        """[2] Sin actividad en 90 s no se amplía; aunque el juez vuelva, esa mudanza queda para firma en persona."""
        motor, sim, usuarios = self.preparar(alcance="filtracion")
        usuarios._actividad["juez-a"] = time.monotonic() - 200
        exp = mudanza(motor, sim)
        u2 = exp["ubicaciones"][1]
        self.assertEqual(u2["estado"], "pendiente")
        self.assertRegex(u2["automatica"]["motivo"],
                         r"^Dra\. A no tenía la plataforma abierta \(sin actividad hace \d+ s\): queda para firmar en "
                         r"persona\.$")  # ronda 3, C6
        usuarios.marcar_actividad("juez-a")
        motor.paso()
        self.assertEqual(u2["estado"], "pendiente", "una mudanza no ampliada por ausencia no se amplía al volver")

    def test_alerta_a_la_sala_una_sola_vez(self):
        """[2] Juez de turno sin actividad y pedidos esperando: una alerta a la sala, por clave."""
        motor, sim, usuarios = self.preparar(aprobar=False)
        usuarios._actividad["juez-a"] = time.monotonic() - 200
        motor._paso_presencia()
        motor._paso_presencia()
        textos = [e["datos"]["texto"] for e in entradas(motor, "alerta") if "no tiene la plataforma" in e["datos"]["texto"]]
        self.assertEqual(textos, ["Dra. A está de turno y no tiene la plataforma abierta: hay 1 pedido esperando."])

    def test_usuarios_actividad(self):
        """[2] marcar_actividad / hace_s / activo con reloj monotónico."""
        motor, _, usuarios = self.preparar(aprobar=False)
        self.assertIsNone(usuarios.hace_s("juez-b"))
        self.assertFalse(usuarios.activo("juez-b", 90))
        usuarios.marcar_actividad("juez-b")
        self.assertTrue(usuarios.activo("juez-b", 90))
        self.assertLess(usuarios.hace_s("juez-b"), 5)


# ======================================================================================================
# Sección 3: prefijo amp-
# ======================================================================================================

class TestPrefijo(ConPartido):
    def test_orden_id_con_prefijo(self):
        """[3] El formato de orden_id solo cambia el prefijo; un prefijo desconocido no se acepta."""
        self.assertTrue(sello.orden_id(1, 2, "aurora", 1, "ab" * 16, prefijo="amp").startswith("amp-0001-u2-aurora-01-"))
        self.assertEqual(sello.orden_id(1, 2, "aurora", 1, "ab" * 16),
                         sello.orden_id(1, 2, "aurora", 1, "ab" * 16, prefijo="ord"))
        with self.assertRaises(ValueError):
            sello.orden_id(1, 2, "aurora", 1, "ab" * 16, prefijo="xyz")

    def test_reenvio_de_una_ampliacion_sigue_siendo_amp(self):
        """[3] Un reintento conserva el prefijo: una ampliación reenviada no pasa a parecer firmada en persona."""
        motor, sim, _ = self.preparar(alcance="filtracion")
        mudanza(motor, sim)
        o = next(o for o in ordenes(motor) if o["n"] == 2)
        o["estado"] = "fallida"
        motor._reintentar(o)
        nueva = [x for x in ordenes(motor) if x.get("reemplaza") == o["orden_id"]]
        self.assertEqual(len(nueva), 1)
        self.assertTrue(nueva[0]["orden_id"].startswith("amp-"))


# ======================================================================================================
# Sección 4: privacidad
# ======================================================================================================

class TestPrivacidad(ConPartido):
    def test_lo_publico_no_muestra_la_sesion(self):
        """[4] vista_orden_publica y vista_registro: marca = prefijo, filtracion = expediente, nunca la sesión."""
        motor, sim, _ = self.preparar()
        ronda(motor)
        sim.avanzar(3.0)
        motor._t_estado = float("-inf")
        motor.paso()
        exp = motor.e["expedientes"][0]
        oid = ordenes(motor)[0]["orden_id"]
        pub = motor.vista_orden_publica(oid)
        self.assertEqual(pub["evidencia"]["marca"], "LP26-PRU-OFI")
        self.assertEqual(pub["filtracion"], exp["id"])
        self.assertNotIn("S0001", json.dumps(pub, ensure_ascii=False))
        reg = motor.vista_registro()
        self.assertTrue(reg["bloqueos"])
        self.assertTrue(all(b["filtracion"] == b["expediente"] for b in reg["bloqueos"]))
        self.assertNotIn("S0001", json.dumps(reg, ensure_ascii=False))
        # El registro judicial (sala) sigue llevando la marca entera.
        self.assertIn("S0001", json.dumps(motor.vista_sala()["expedientes"], ensure_ascii=False))


# ======================================================================================================
# Sección 5: kit por estado, lista del proveedor y consulta pública
# ======================================================================================================

class TestProveedor(ConPartido):
    def test_orden_que_ya_no_rige(self):
        """[5.1] Una orden levantada no dice «se quita solo» ni ofrece aplicar: dice que ya no rige y por qué."""
        motor, _, _ = self.preparar()
        ronda(motor)
        o = next(o for o in ordenes(motor) if o["tipo"] == "ip")
        vigente = motor.vista_orden_publica(o["orden_id"])
        self.assertIn("con las líneas de abajo se quita solo", vigente["texto_llano"])
        self.assertTrue(any(e.get("aplicar") for e in vigente["kit"]))
        o["estado"] = "levantada"
        o["finalizada_min"] = 1.4
        o["levantamiento"] = {"min": 1.4, "juez_id": "juez-a", "juez": "Dra. A", "motivo": "x", "reclamo": None}
        pub = motor.vista_orden_publica(o["orden_id"])
        self.assertTrue(pub["texto_llano"].startswith("Esta orden ya no rige."))
        self.assertIn("La levantó Dra. A en el minuto 1,4", pub["texto_llano"])
        self.assertNotIn("se quita solo", pub["texto_llano"])
        self.assertFalse(any(e.get("aplicar") for e in pub["kit"]))
        self.assertTrue(all(e.get("quitar") for e in pub["kit"]))
        self.assertTrue(pub["como_objetar"].startswith("Si este bloqueo afecta a tu sitio, avisale a tu proveedor"))

    def test_vista_proveedor(self):
        """[5.2] Forma del contrato; firma en persona vs ampliación; levantadas a retiradas."""
        motor, sim, _ = self.preparar(alcance="filtracion")
        ronda(motor)
        mudanza(motor, sim)
        ronda(motor)
        v = motor.vista_proveedor("aurora")
        self.assertEqual(set(v), {"acelerar", "v", "proveedor", "minuto", "hora", "generado_utc", "partido",
                                  "vigentes", "retiradas"})
        self.assertIsInstance(v["acelerar"], float)
        self.assertEqual(set(v["partido"]), {"nombre", "fin_min", "fin_hora"})
        self.assertEqual(set(v["vigentes"][0]), {"orden_id", "tipo", "objetivo", "vence_min", "vence_hora", "juzgado",
                                                 "juez", "firma", "desde_min", "url"})
        firmas = {x["orden_id"][:4]: x["firma"] for x in v["vigentes"]}
        self.assertEqual(firmas, {"ord-": "en_persona", "amp-": "ampliacion"})
        o = next(o for o in ordenes(motor) if o["proveedor"] == "aurora" and o["n"] == 1)
        o["estado"], o["finalizada_min"] = "levantada", 1.7
        v = motor.vista_proveedor("aurora")
        self.assertEqual([(x["orden_id"], x["motivo"]) for x in v["retiradas"]], [(o["orden_id"], "levantada")])
        self.assertNotIn(o["orden_id"], [x["orden_id"] for x in v["vigentes"]])
        with self.assertRaises(ErrorAccion):
            motor.vista_proveedor("no-existe")

    def test_levantamiento_en_curso_ya_no_esta_en_la_lista(self):
        """[5.2] Una orden que el juez mandó levantar sale de la lista apenas se firma, antes de que el proveedor
        confirme: la lista es lo que el equipo tiene que tener aplicado ahora."""
        motor, _, _ = self.preparar()
        ronda(motor)
        sim_oids = {x["orden_id"] for x in motor.vista_proveedor("aurora")["vigentes"]}
        self.assertTrue(sim_oids)
        exp = motor.e["expedientes"][0]
        motor.levantar_ubicacion("juez-a", exp["id"], 1, "Prueba de levantamiento")
        o = next(o for o in ordenes(motor) if o["proveedor"] == "aurora")
        self.assertIsNotNone(o.get("levantar"))
        self.assertIn(o["estado"], ("recibida", "aplicada"))
        self.assertNotIn(o["orden_id"], {x["orden_id"] for x in motor.vista_proveedor("aurora")["vigentes"]})

    def test_las_listas_del_kit_leen_la_vista_del_proveedor(self):
        """[5.2] kit.lista_ips / lista_dominios / unbound_conf / zona_rpz se arman con lo que da vista_proveedor."""
        from marca import kit
        motor, _, _ = self.preparar(det=[deteccion("D-1", 1.0, *PIRATA), deteccion("D-3", 1.0, *CDN)])
        cdn = next(x for x in motor.e["expedientes"] if x["ubicaciones"][0]["host"] == CDN[0])
        motor.aprobar("juez-a", cdn["id"], 1, "ubicacion", None, None)
        ronda(motor)
        v = motor.vista_proveedor("aurora")
        objetivos = {(x["tipo"], x["objetivo"]) for x in v["vigentes"]}
        self.assertIn(("ip", "203.0.113.10"), objetivos)
        self.assertIn(("dominio", CDN[0]), objetivos)
        self.assertIn("203.0.113.10", kit.lista_ips(v))
        self.assertNotIn(CDN[0], kit.lista_ips(v))
        self.assertIn(CDN[0], kit.lista_dominios(v))
        self.assertNotIn("203.0.113.10", kit.lista_dominios(v))
        self.assertIn(CDN[0], kit.unbound_conf(v))
        self.assertIn(CDN[0], kit.zona_rpz(v))

    def test_consulta_publica(self):
        """[5.4] bloqueado / comparte_servidor / no_alcanzado / invalido, sin red."""
        motor, _, _ = self.preparar(det=[deteccion("D-1", 1.0, *PIRATA), deteccion("D-3", 1.0, *CDN)],
                                    aprobar=False)
        cdn = next(x for x in motor.e["expedientes"] if x["titulo"] == "cdn-pirata.test")
        motor.aprobar("juez-a", motor.e["expedientes"][0]["id"], 1, "ubicacion", None, None)
        motor.aprobar("juez-a", cdn["id"], 1, "ubicacion", "ip", "Ensayo: se fuerza la IP del CDN.")
        ronda(motor)
        self.assertEqual(motor.consulta_publica("s1-respaldo.pirata.test")["resultado"], "bloqueado")
        r = motor.consulta_publica("PANADERIA.test")
        self.assertEqual((r["resultado"], r["dominio"]), ("comparte_servidor", "panaderia.test"))
        self.assertEqual(motor.consulta_publica("otro.test")["resultado"], "no_alcanzado")
        self.assertEqual(motor.consulta_publica("con espacio.test")["resultado"], "invalido")
        self.assertEqual(motor.consulta_publica("203.0.113.10")["resultado"], "invalido")
        self.assertEqual(set(r["ordenes"][0]), {"orden_id", "tipo", "objetivo", "juzgado", "vence_min", "url"})


# ======================================================================================================
# Sección 6: traspaso y revocación
# ======================================================================================================

class TestTraspasoYRevocacion(ConPartido):
    def traspaso(self, motor, sim, usuarios):
        ronda(motor)
        sim.avanzar(10.5)
        motor._t_estado = float("-inf")
        motor.paso()
        usuarios.ingresar("b", "clave-de-prueba-b")
        return motor.e["expedientes"][0]

    def test_sin_om_con_seguimiento_recibe_el_turno_sin_ratificar_lo_dinamico(self):
        """[6] Sin OM con seguimiento: se ratifica lo demás, devuelve un aviso y la dinámica sigue esperando."""
        motor, sim, usuarios = self.preparar(alcance="filtracion")
        exp = self.traspaso(motor, sim, usuarios)
        r = motor.ratificar("juez-b")
        self.assertIn("firme antes la orden marco con el seguimiento autorizado", r["aviso"])
        self.assertEqual((r["ratificadas"], r["sin_ratificar"]), ([], [exp["id"]]))
        self.assertTrue(exp["dinamica"]["requiere_ratificacion"])
        self.assertEqual(entradas(motor, "traspaso_ratificado")[-1]["datos"]["dinamicas"], [])
        tr = motor.vista_traspaso(motor.e["traspasos"][-1])
        self.assertEqual(tr["dinamicas_sin_ratificar"], [exp["id"]])
        # Después firma la OM y ratifica la que quedó esperando.
        motor.firmar_marco("juez-b", True)
        r = motor.ratificar("juez-b", [exp["id"]])
        self.assertEqual(r["ratificadas"], [exp["id"]])
        self.assertFalse(exp["dinamica"]["requiere_ratificacion"])
        self.assertEqual(exp["dinamica"]["respaldada_por"], "juez-b")

    def test_ratifica_solo_las_elegidas(self):
        """[6] dinamicas=[] no ratifica ninguna dinámica, aunque haya OM con seguimiento."""
        motor, sim, usuarios = self.preparar(alcance="filtracion")
        exp = self.traspaso(motor, sim, usuarios)
        motor.firmar_marco("juez-b", True)
        r = motor.ratificar("juez-b", [])
        self.assertEqual(r["sin_ratificar"], [exp["id"]])
        self.assertIsNone(r["aviso"])
        self.assertTrue(exp["dinamica"]["requiere_ratificacion"])

    def test_revocar_y_levantar_las_ampliaciones(self):
        """[6] levantar=true levanta con la firma del juez solo lo que se amplió solo; la vista cuenta ampliaciones."""
        motor, sim, _ = self.preparar(alcance="filtracion")
        ronda(motor)
        exp = mudanza(motor, sim)
        ronda(motor)
        b = motor.vista_bandeja({"usuario": "a", "juez_id": "juez-a", "rol": "juez", "nombre": "Dra. A"})
        self.assertEqual(b["dinamicas"][0]["ampliaciones"], 1)
        r = motor.revocar_dinamica("juez-a", exp["id"], "La filtración ya se cortó.", levantar=True)
        self.assertEqual(r["levantadas"], [2])
        self.assertTrue(all(o.get("levantar") for o in ordenes(motor) if o["n"] == 2))
        self.assertFalse(any(o.get("levantar") for o in ordenes(motor) if o["n"] == 1))
        rev = entradas(motor, "dinamica_revocada")[-1]["datos"]
        self.assertTrue(rev["levantar"])
        lev = [e for e in entradas(motor, "decision_juez") if e["datos"].get("accion") == "levantar_ubicacion"]
        self.assertEqual([e["datos"]["ubicacion"] for e in lev], [2])

    def test_revocar_sin_levantar_no_toca_las_ordenes(self):
        motor, sim, _ = self.preparar(alcance="filtracion")
        exp = mudanza(motor, sim)
        r = motor.revocar_dinamica("juez-a", exp["id"], "")
        self.assertEqual(r["levantadas"], [])
        self.assertFalse(any(o.get("levantar") for o in ordenes(motor)))


# ======================================================================================================
# Sección 7: textos del expediente
# ======================================================================================================

class TestTextos(ConPartido):
    def test_texto_de_la_marca_y_del_hash(self):
        """[7] La plataforma compara la marca que informa el detector; el hash prueba que la captura no cambió."""
        motor, _, _ = self.preparar(aprobar=False)
        u = motor.e["expedientes"][0]["ubicaciones"][0]
        self.assertEqual(u["senal"]["motivo"],
                         "El detector informó la marca LP26-PRU-OFI (sesión S0001). La plataforma comprobó que ese "
                         "prefijo es de la señal oficial del partido y que no es de un licenciatario en su dominio.")
        self.assertEqual(u["captura"]["texto"], "El hash prueba que la captura no cambió desde que llegó a la plataforma.")

    def test_apartarse_de_la_recomendacion_no_se_contradice(self):
        """[7] El fundamento dice lo que el juez ordenó, el riesgo informado y su texto."""
        motor, _, _ = self.preparar(det=[deteccion("D-3", 1.0, *CDN)], aprobar=False)
        exp = motor.e["expedientes"][0]
        motor.aprobar("juez-a", exp["id"], 1, "ubicacion", "ip", "Lo pide la fiscalía por escrito.")
        f = exp["ubicaciones"][0]["decision"]["propuesta_aplicada"]["fundamento"]
        self.assertEqual(f, "El juez se apartó de la recomendación (dominio) y ordenó bloquear la IP 198.51.100.20 "
                            "hasta el minuto 20. Riesgo informado: la IP aloja otros 2 sitios (panaderia.test y "
                            "municipio.example). Fundamento del juez: «Lo pide la fiscalía por escrito.».")
        self.assertNotIn("se bloquea solo el nombre del stream", f)

    def test_rechazo_exige_diez_caracteres(self):
        """[7] Rechazar exige un motivo de al menos 10 caracteres."""
        motor, _, _ = self.preparar(aprobar=False)
        exp = motor.e["expedientes"][0]
        with self.assertRaises(ErrorAccion):
            motor.rechazar("juez-a", exp["id"], 1, "No va.")
        motor.rechazar("juez-a", exp["id"], 1, "La evidencia no alcanza")
        self.assertEqual(exp["ubicaciones"][0]["estado"], "rechazada")

    def test_fundamento_por_defecto_del_levantamiento_por_reclamo(self):
        """[7] Sin fundamento escrito, queda la explicación verificada."""
        r = {"dominio": "panaderia.test", "verificacion": {"ips": ["198.51.100.20"], "ordenes_causantes": []}}
        self.assertEqual(Motor.fundamento_reclamo(r, [{"orden_id": "ord-0002-u1-aurora-01-x"}]),
                         "panaderia.test resuelve a 198.51.100.20, bloqueada por la orden ord-0002-u1-aurora-01-x; "
                         "no es un sitio pirata")


# ======================================================================================================
# Agregado 10: regla de «propios» (hosting por subdominios)
# ======================================================================================================

def det_servidor(host, ip, pagina):
    return {"host_stream": host, "ip_servidor": ip, "pagina": pagina, "stream_url": f"https://{host}/x.m3u8",
            "asn": 64600}


def dns(ip, nombres):
    return {"ip": ip, "asn": 64600, "organizacion": "Hosting", "dominios": nombres}


class TestPropios(unittest.TestCase):
    def analizar(self, host, pagina, nombres, ip="203.0.113.50"):
        return evidencia.analizar_servidor(det_servidor(host, ip, pagina), dns(ip, nombres),
                                           {"ips": [{"ip": ip}]}, [])

    def test_caso_practica_respaldo_hermano(self):
        """[10] s1 y su respaldo en el dominio del pirata (página en R): IP exclusiva."""
        a = self.analizar("s1.pelotaya.test", "https://pelotaya.test/en-vivo",
                          ["s1.pelotaya.test", "s1-respaldo.pelotaya.test"])
        self.assertEqual(a["colateral"]["recomendacion"], "ip")
        self.assertEqual(a["colateral"]["ajenos"], [])

    def test_trampa_hosting_gratis(self):
        """[10] pirata.hosting-gratis.test junto a panaderia.hosting-gratis.test: dominio."""
        a = self.analizar("pirata.hosting-gratis.test", "https://pirata.hosting-gratis.test/vivo",
                          ["pirata.hosting-gratis.test", "panaderia.hosting-gratis.test"])
        self.assertEqual(a["colateral"]["recomendacion"], "dominio")
        self.assertEqual(a["colateral"]["ajenos"], ["panaderia.hosting-gratis.test"])
        self.assertIn("comparte la IP con otros subdominios de hosting-gratis.test que no podemos atribuir al pirata",
                      a["colateral"]["motivo"])
        self.assertEqual(a["operacion"], [])

    def test_pagina_en_www_cuenta_como_la_raiz(self):
        """[10] La página en www.R prueba que el pirata controla R."""
        a = self.analizar("s1.pelotaya.test", "https://www.pelotaya.test/vivo",
                          ["s1.pelotaya.test", "espejo.pelotaya.test"])
        self.assertEqual(a["colateral"]["recomendacion"], "ip")

    def test_pagina_en_otro_dominio(self):
        """[10] Si la página vive en otro dominio, los hermanos del host no se le atribuyen al pirata."""
        a = self.analizar("s1.pelotaya.test", "https://otro-sitio.test/vivo",
                          ["s1.pelotaya.test", "espejo.pelotaya.test"])
        self.assertEqual(a["colateral"]["recomendacion"], "dominio")
        self.assertEqual(a["colateral"]["ajenos"], ["espejo.pelotaya.test"])

    def test_el_host_de_la_pagina_es_propio(self):
        """[10] (a) el host de la página es propio aunque esté en otro registrable."""
        a = self.analizar("tv.verpartido-hd.test", "https://verpartido-hd.test/vivo",
                          ["tv.verpartido-hd.test", "verpartido-hd.test"])
        self.assertEqual(a["colateral"]["recomendacion"], "ip")


# ======================================================================================================
# Agregado 11: corte en origen
# ======================================================================================================

class TestCorteEnOrigen(ConPartido):
    def test_constancia_al_armar_una_vez_por_sesion(self):
        """[11] Sale al armar el expediente con una marca oficial válida, una vez por sesión, sin firma del juez."""
        motor, sim, _ = self.preparar(aprobar=False)
        avisos = entradas(motor, "aviso_corte_en_origen")
        self.assertEqual(len(avisos), 1)
        texto = avisos[0]["datos"]["texto"]
        self.assertIn("Constancia de aviso al titular", texto)
        self.assertIn("La plataforma no corta nada", texto)
        mudanza(motor, sim)
        self.assertEqual(len(entradas(motor, "aviso_corte_en_origen")), 1)
        exp = motor.e["expedientes"][0]
        motor.aprobar("juez-a", exp["id"], 1, "ubicacion", None, None)
        self.assertEqual(len(entradas(motor, "aviso_corte_en_origen")), 1, "firmar no repite la constancia")

    def test_marca_de_licenciatario_fuera_de_su_dominio_no(self):
        motor, _, _ = self.preparar(det=[deteccion("D-9", 1.0, "s9.pirata.test", "203.0.113.11",
                                                   "LP26-PRU-LIC-NORTE-S77", "https://pirata.test/x", 64600)],
                                    aprobar=False)
        self.assertEqual(len(motor.e["expedientes"]), 1)
        self.assertEqual(entradas(motor, "aviso_corte_en_origen"), [])


# ======================================================================================================
# Adenda 3: A (ventana), B (sin decidir), C (juez automático), dominios envenenados
# ======================================================================================================

def ub(n, minutos):
    return {"n": n, "primera_deteccion_min": minutos[0], "ultima_deteccion_min": minutos[-1],
            "detecciones_min": list(minutos)}


class TestVentana(unittest.TestCase):
    def test_mudanza_simple(self):
        a, b = ub(1, [2, 12, 22]), ub(2, [31, 41])
        self.assertEqual(evidencia.ventana([a, b], a, 50, 90), (2, 31))
        self.assertEqual(evidencia.ventana([a, b], b, 50, 90), (31, 50))

    def test_dos_servidores_a_la_vez(self):
        """[A] Misma sesión en dos servidores desde el mismo minuto: las dos siguen vivas."""
        a, b = ub(1, [63, 73, 83]), ub(2, [63, 73, 83])
        self.assertEqual(evidencia.ventana([a, b], a, 100, 90), (63, 90))
        self.assertEqual(evidencia.ventana([a, b], b, 100, 90), (63, 90))

    def test_vuelve(self):
        """[A] El pirata vuelve al servidor viejo: A sigue viva hasta el final; B termina en la vuelta."""
        a, b = ub(1, [2, 12, 22, 61, 71, 81, 91, 101]), ub(2, [31, 41, 51])
        self.assertEqual(evidencia.ventana([a, b], a, 120, 105), (2, 105))
        self.assertEqual(evidencia.ventana([a, b], b, 120, 105), (31, 61))

    def test_mudanzas_rapidas(self):
        a, b, c = ub(1, [40]), ub(2, [41]), ub(3, [41.6])
        self.assertEqual(evidencia.ventana([a, b, c], a, 50, 90), (40, 41))
        self.assertEqual(evidencia.ventana([a, b, c], b, 50, 90), (41, 41.6))

    def test_ventana_cero_sin_numeros(self):
        """[A] Ventana de duración cero: None en los tres tiempos y sin_ventana true."""
        orden = {"tipo": "ip", "objetivo": "203.0.113.10", "aplicada_min": 5.0, "finalizada_min": None,
                 "proveedor": "aurora"}
        c = evidencia.cobertura(10, 10, "203.0.113.10", "s1.pirata.test", [orden],
                                [{"id": "aurora", "clientes": 10}])
        self.assertEqual((c["primer_bloqueo_min"], c["completo_min"], c["visibilidad_residual_pct"], c["sin_ventana"]),
                         (None, None, None, True))
        c = evidencia.cobertura(10, 12, "203.0.113.10", "s1.pirata.test", [orden], [{"id": "aurora", "clientes": 10}])
        self.assertFalse(c["sin_ventana"])
        self.assertEqual(c["visibilidad_residual_pct"], 0.0)


class TestVentanaEnElMotor(ConPartido):
    def test_dos_ubicaciones_al_mismo_tiempo_las_dos_cubiertas(self):
        """[A] motor.cobertura usa evidencia.ventana: dos servidores de la misma sesión con órdenes aplicadas."""
        dets = [deteccion("D-1", 1.0, *PIRATA), deteccion("D-2", 1.0, *S2)]
        motor, sim, _ = self.preparar(det=dets, aprobar=False)
        exp = motor.e["expedientes"][0]
        self.assertEqual(len(exp["ubicaciones"]), 2)
        self.assertEqual(exp["ubicaciones"][0]["detecciones_min"], [1.0])
        for n in (1, 2):
            motor.aprobar("juez-a", exp["id"], n, "ubicacion", None, None)
        ronda(motor)
        for o in ordenes(motor):
            o["estado"], o["aplicada_min"] = "aplicada", 1.0
        sim.avanzar(5.0)
        motor._t_estado = float("-inf")
        for u in exp["ubicaciones"]:
            c = motor.cobertura(exp, u)
            self.assertFalse(c["sin_ventana"])
            self.assertEqual(c["visibilidad_residual_pct"], 0.0, u["n"])


class TestSinDecidir(ConPartido):
    def test_pendiente_al_terminar_pasa_a_sin_decidir(self):
        """[B] Al cruzar el final: sin_decidir (terminal), motivo, auditoría por ubicación, expediente cerrado."""
        motor, sim, _ = self.preparar(aprobar=False, marco=False)
        sim.avanzar(20.5)
        motor._t_estado = float("-inf")
        motor.paso()
        exp = motor.e["expedientes"][0]
        u = exp["ubicaciones"][0]
        self.assertEqual(u["estado"], "sin_decidir")
        self.assertTrue(u["motivo_sin_decidir"].startswith(
            "El partido terminó a los 19,0 min de la detección: ya no se pueden firmar órdenes."))
        self.assertIn("estuvo esperando la firma", u["motivo_sin_decidir"])
        self.assertIsNotNone(u["sin_decidir_min"])
        e = entradas(motor, "ubicacion_sin_decidir")
        self.assertEqual(len(e), 1)
        self.assertEqual((e[0]["actor"], e[0]["datos"]),
                         ("sistema", {"expediente": exp["id"], "ubicacion": 1, "motivo": "partido_terminado",
                                      "primera_deteccion_min": 1.0}))
        self.assertEqual(exp["estado"], "cerrado")
        self.assertEqual(ordenes(motor), [])
        motor.paso()
        self.assertEqual(len(entradas(motor, "ubicacion_sin_decidir")), 1, "una sola vez")


class TestJuezAutomatico(unittest.TestCase):
    def test_409_ya_decidida_es_esperado(self):
        """[C] El 409 «ya fue decidida» se anota como «la amplió el sistema» y no cuenta como error."""
        from herramientas.juez_automatico import JuezAutomatico
        j = JuezAutomatico("http://127.0.0.1:1", "a", "x", registro=lambda t: None)
        j._pedir = lambda *a, **k: (409, {"codigo": "conflicto", "error": "Esta ubicación ya fue decidida."})
        j._accion("/api/juez/ubicaciones/EXP/2/aprobar", {}, "firma")
        self.assertEqual((j.acciones[-1]["resultado"], j.acciones[-1]["esperado"]), ("la amplió el sistema", True))
        j._pedir = lambda *a, **k: (403, {"codigo": "fuera_de_turno", "error": "No está de turno."})
        j._accion("/api/juez/ubicaciones/EXP/2/aprobar", {}, "firma")
        self.assertFalse(j.acciones[-1]["esperado"])

    def test_firma_la_om_antes_de_decidir(self):
        """[1] Al entrar de turno, el juez automático firma la OM (con seguimiento) antes de cualquier firma."""
        from herramientas.juez_automatico import JuezAutomatico
        j = JuezAutomatico("http://127.0.0.1:1", "a", "x", registro=lambda t: None)
        pedidos = []
        j._pedir = lambda metodo, ruta, cuerpo=None: (pedidos.append((ruta, cuerpo)) or (200, {"ok": True}))
        b = {"reloj": {"minuto": 1.0}, "turno": {"de_turno": True, "puede_firmar": True}, "yo": {"dinamica_habilitada": True},
             "marco": {"firmada": None, "puede_firmar": True, "seguimiento_disponible": True},
             "traspaso": None, "reclamos": [], "pendientes": []}
        j._atender(b)
        self.assertEqual(pedidos, [("/api/juez/marco", {"seguimiento": True})])
        j2 = JuezAutomatico("http://127.0.0.1:1", "a", "x", alcance="ubicacion", registro=lambda t: None)
        pedidos.clear()
        j2._pedir = j._pedir
        j2._atender(b)
        self.assertEqual(pedidos, [("/api/juez/marco", {"seguimiento": False})])


class TestDominiosEnvenenados(unittest.TestCase):
    def test_venenos_invalidos(self):
        """IPv6 con zona y texto libre, saltos de línea finales y direcciones no enrutables: inválidas."""
        for x in ("2001:db8::1%\n0.0.0.0-255.255.255.255", "2001:db8::1%;flush ruleset", "2001:db8::1%eth0",
                  "203.0.113.10\n", "127.0.0.1", "10.1.2.3", "172.16.0.1", "192.168.1.1", "100.64.0.1", "169.254.1.1",
                  "224.0.0.1", "255.255.255.255", "240.0.0.1", "0.0.0.0", "::", "::1", "fe80::1", "fd00::1", "ff02::1",
                  "::ffff:10.0.0.1"):
            self.assertFalse(dominios.ip_valida(x), repr(x))
            self.assertFalse(dominios.objetivo_valido("ip", x), repr(x))
        for x in ("s1.pirata.test\n", "s1.pirata.test\n0.0.0.0", "a..b"):
            self.assertFalse(dominios.es_hostname(x), repr(x))

    def test_ips_del_escenario_oficial_validas(self):
        """Los rangos de documentación que usa el escenario oficial siguen siendo válidos."""
        for x in ("203.0.113.10", "203.0.113.11", "198.51.100.77", "198.51.100.20", "192.0.2.50", "203.0.113.40",
                  "203.0.113.41", "198.51.100.90", "192.0.2.10", "2001:db8::10"):
            self.assertTrue(dominios.ip_valida(x), x)

    def test_deteccion_con_ip_envenenada_no_arma_orden(self):
        d = deteccion("D-X", 1.0, "s1.pirata.test", "2001:db8::1%;flush ruleset", "LP26-PRU-OFI-S1",
                      "https://pirata.test/x", 64600)
        self.assertIsNotNone(evidencia.validar_deteccion(d))


if __name__ == "__main__":
    unittest.main()


# ======================================================================================================
# Reloj monotónico que arranca cerca de 0 (Python 3.9 del sistema): «nunca» no es 0
# ======================================================================================================

class TestMonotonicoCercaDeCero(ConPartido):
    """El origen de time.monotonic() no está definido. Un instante «nunca» por defecto en 0 hacía esperar de más
    recién arrancada la plataforma. Contrato: con el reloj en 0,01 s, nada espera por un instante que no existe."""

    def setUp(self):
        super().setUp()
        from unittest import mock
        self.reloj_t = [0.01]
        p = mock.patch("time.monotonic", lambda: self.reloj_t[0])
        p.start()
        self.addCleanup(p.stop)

    def test_nunca_es_menos_infinito(self):
        from marca import reloj
        self.assertEqual(reloj.instante(None), float("-inf"))
        self.assertEqual(reloj.instante(0.0), 0.0)
        from tests.simulador_falso import SimuladorFalso
        m = Motor("http://falso", self.base / "nunca", None, cliente=SimuladorFalso(), tick=0.01,
                  registro=lambda t: None)
        for campo in ("_t_estado", "_t_juzgados", "_t_reclamos", "_t_fin_listas"):
            self.assertEqual(getattr(m, campo), float("-inf"), campo)
        m._pool_red.shutdown(wait=False)

    def test_primer_reintento_sin_espera_extra(self):
        """Un 502 al POST deja la orden incierta: el GET de confirmación sale apenas pasa la espera propia
        (no la espera más el origen del reloj), y tras dos 404 se reenvía con el mismo orden_id."""
        motor, sim, _ = self.preparar()
        sim.guion["enviar_orden"] = [(502, None)] * 3
        motor.despacho.ronda()
        ids = sorted(o["orden_id"] for o in ordenes(motor))
        self.assertTrue(ids and all(o["incierta"] for o in ordenes(motor)))
        for o in ordenes(motor):  # la orden quedó en duda en este instante (0,01 s)
            self.assertAlmostEqual(o["t_error"], 0.01)
        antes = sim.llamadas.get("llamada:orden", 0)
        self.reloj_t[0] = 0.01 + 30.0  # pasó la espera de una incierta y la del POST, nada más
        motor.despacho.ronda()
        self.assertGreater(sim.llamadas.get("llamada:orden", 0), antes, "el GET de confirmación salió")
        self.reloj_t[0] += 30.0
        motor.despacho.ronda()
        self.assertEqual(sorted(e["orden_id"] for e in eventos(sim, "orden_recibida")), ids)

    def test_409_se_consulta_ya(self):
        """Un 409 al POST: la orden es nuestra y se confirma con GET en la misma ronda siguiente, con el reloj en 0,01."""
        motor, sim, _ = self.preparar()
        motor.despacho.ronda()
        o = ordenes(motor)[0]
        o["estado"], o["incierta"], o["t_error"] = "por_enviar", True, None
        antes = sim.llamadas.get("llamada:orden", 0)
        motor.despacho.ronda()
        self.assertGreater(sim.llamadas.get("llamada:orden", 0), antes)


class TestLevantamientoConfirmadoPorConsulta(ConPartido):
    levantar = t2.TestLevantamientoIncierto.levantar

    def test_confirmado_por_la_lista_lleva_firma_y_juez(self):
        """[ronda 2] Un levantamiento que salió firmado y se confirma después por consulta (aunque el pedido ya se
        haya descartado) deja orden_levantada con firma, juez_id y confirmada_por_consulta."""
        motor, sim = self.levantar()
        sim.guion["levantar"] = ["red_despues"] * 3
        motor.despacho.ronda()
        for o in ordenes(motor):
            self.assertTrue(o.get("lev_incierto"))
            o["levantar"], o["lev_incierto"] = None, False  # p. ej. un 404 descartó el pedido
            motor._aplicar_estado_sim(o, {"estado": "levantada", "finalizada_min": 2.1})
        lev = entradas(motor, "orden_levantada")
        self.assertEqual(len(lev), 3)
        for e in lev:
            d = e["datos"]
            self.assertTrue(d.get("confirmada_por_consulta"))
            self.assertEqual(d.get("juez_id"), "juez-a")
            self.assertEqual(d.get("firma"), sello.firma_levantamiento("clave-a", d["orden_id"], "juez-a"))
            self.assertEqual(e["actor"], "juez:juez-a")
            self.assertNotIn("sin_pedido", d)
