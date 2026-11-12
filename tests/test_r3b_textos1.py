"""Contrato [ESPEC 2b §7 + §1]: una ampliación automática cita UNA sola orden marco en todo el paquete.

La orden marco que nombra decision.texto (bandeja, registro público vía decision_texto, orden) tiene que ser la
misma que decision.orden_marco, la que cita la entrada ampliacion_dinamica de la auditoría, la del expediente .md y
la lista «ampliaciones» de orden-marco/OM-xx del acta. Caso que lo rompe: traspaso de turno, el entrante firma su
OM con seguimiento, ratifica la dinámica y después la filtración se muda.
"""
import json
import re
import tempfile
from pathlib import Path

from marca.exportar import exportar
from tests.simulador_falso import deteccion
from tests.test_contratos_ronda2 import ConPartido, ronda
from tests.test_robustez import entradas

S2 = ("s2.pirata.test", "203.0.113.11", "LP26-PRU-OFI-S0001", "https://pirata.test/vivo", 64600)


def oms(texto):
    return re.findall(r"OM-\d+", texto or "")


class TestUnaSolaOrdenMarco(ConPartido):
    def test_ampliacion_despues_del_traspaso_cita_una_sola_om(self):
        motor, sim, usuarios = self.preparar(alcance="filtracion")
        ronda(motor)
        sim.avanzar(10.5)  # cambio de turno: juez-a -> juez-b
        motor._t_estado = float("-inf")  # «nunca»: en 3.9 el reloj monotónico arranca cerca de 0
        motor.paso()
        usuarios.ingresar("b", "clave-de-prueba-b")
        exp = motor.e["expedientes"][0]
        motor.firmar_marco("juez-b", True)
        motor.ratificar("juez-b", [exp["id"]])
        self.assertEqual(exp["dinamica"]["respaldada_por"], "juez-b")
        # La filtración se muda DESPUÉS del traspaso.
        sim.lista_detecciones.append(deteccion("D-2", 11.0, *S2))
        sim.avanzar(11.1)
        motor._t_estado = float("-inf")  # «nunca»: en 3.9 el reloj monotónico arranca cerca de 0
        motor.paso()
        u2 = exp["ubicaciones"][1]
        self.assertEqual((u2.get("decision") or {}).get("tipo"), "ampliacion_dinamica", u2.get("automatica"))
        dec = u2["decision"]
        om_auditoria_entrada = entradas(motor, "ampliacion_dinamica")[-1]["datos"]["orden_marco"]["entrada"]
        om_por_entrada = {e["n"]: e["datos"]["id"] for e in entradas(motor, "orden_marco")}
        citadas = {
            "decision.texto": oms(dec["texto"]),
            "decision.orden_marco": [dec["orden_marco"]["id"]],
            "auditoria": [om_por_entrada[om_auditoria_entrada]],
        }
        # Registro público (lo que lee transparencia.js: decision_texto).
        ronda(motor)
        sim.avanzar(13.0)  # los proveedores aplican la orden amp-
        motor._t_estado = float("-inf")  # «nunca»: en 3.9 el reloj monotónico arranca cerca de 0
        motor.paso()
        ronda(motor, 3)
        with motor.candado:
            reg = motor.vista_registro()
        textos = {b["decision_texto"] for b in reg["bloqueos"] if b["expediente"] == exp["id"]
                  and b.get("decision_tipo") == "ampliacion_dinamica"}
        self.assertTrue(textos, "el registro público no muestra la ampliación aplicada")
        citadas["registro.decision_texto"] = sorted({x for t in textos for x in oms(t)})
        # Paquete exportado: expediente .md (bloque de la ubicación 2) y acta / OM-xx.json.
        motor.guardar()
        destino = Path(tempfile.mkdtemp(dir=str(self.base))) / "entrega"
        exportar(motor.salida, destino)
        md = next(destino.rglob(exp["id"] + ".md")).read_text(encoding="utf-8")
        bloque = [ln for ln in md.splitlines() if "Ampliación automática" in ln]
        citadas["expediente.md"] = sorted({x for ln in bloque for x in oms(ln)})
        bajo = []
        for f in destino.rglob("OM-*.json"):
            m = json.loads(f.read_text(encoding="utf-8"))
            if any(a.get("exp") == exp["id"] and a.get("ubicacion") == 2 for a in m.get("ampliaciones") or []):
                bajo.append(m["id"])
        citadas["orden-marco/ampliaciones"] = sorted(bajo)
        todas = {x for v in citadas.values() for x in v}
        self.assertEqual(len(todas), 1, f"la misma ampliación cita órdenes marco distintas: {citadas}")
        # Y el texto no se contradice: si la OM citada es del juez que ratificó, no dice «ratificada por» ese mismo
        # juez como si fuera otro.
        # Adaptado a la leyenda única de C7: la OM citada (antes de «, que en el minuto») es la de Dr. B; Dra. A
        # aparece solo como quien otorgó el seguimiento.
        self.assertNotIn("Dra. A", dec["texto"].split(", que en el minuto")[0])
        self.assertIn("otorgado por Dra. A", dec["texto"])


    def test_juez_que_vuelve_a_firmar_su_om_la_ampliacion_cita_la_vigente(self):
        """Vale la última OM del juez: si la re-firma después de otorgar la dinámica, el texto cita la nueva,
        igual que la auditoría (sin traspaso de por medio)."""
        motor, sim, _ = self.preparar(alcance="filtracion")
        motor.firmar_marco("juez-a", True)  # OM-02 reemplaza a OM-01
        sim.lista_detecciones.append(deteccion("D-2", 1.5, *S2))
        sim.avanzar(1.6)
        motor._t_estado = float("-inf")  # «nunca»: en 3.9 el reloj monotónico arranca cerca de 0
        motor.paso()
        dec = motor.e["expedientes"][0]["ubicaciones"][1]["decision"]
        self.assertEqual(dec["tipo"], "ampliacion_dinamica")
        self.assertEqual(oms(dec["texto"]), [dec["orden_marco"]["id"]])


if __name__ == "__main__":
    import unittest
    unittest.main()
