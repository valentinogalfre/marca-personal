"""R3B · C21, última fila: los tres pedidos de W tras la tanda A.

Contratos:
- La ubicación reabierta (C4) dice en `continuidad` que es el mismo servidor (`criterio: "mismo_servidor"`), trae la
  nota (`continuidad.nota`, en «usted» para el juez que levantó) y `reabierta`.
- `vista_sala()["jueces"][]` trae `turno {desde_min, hasta_min}`: el turno en curso o el próximo.
- El cierre de una alerta de juez ausente dice de qué juez era (`cierre.juez_ausente`, además de `juez_ausente`).
"""
import time
import unittest

from tests.test_contratos_ronda2 import ConPartido
from tests import test_contratos_ronda3 as r3
from tests.test_contratos_ronda3 import JUEZ_A


class TestUbicacionReabiertaParaW(ConPartido):
    frenar_y_levantar = r3.TestAmpliacionLevantadaVuelveAlJuez.frenar_y_levantar
    otra_deteccion = r3.TestAmpliacionLevantadaVuelveAlJuez.otra_deteccion

    def test_continuidad_mismo_servidor_con_nota_y_reabierta(self):
        motor, sim, _, exp = self.frenar_y_levantar()
        self.otra_deteccion(motor, sim)
        u3 = exp["ubicaciones"][2]
        self.assertEqual(u3["continuidad"]["criterio"], "mismo_servidor")
        sala_u3 = motor.vista_sala()["expedientes"][0]["ubicaciones"][2]
        self.assertEqual(sala_u3["continuidad"]["criterio"], "mismo_servidor")
        self.assertEqual(sala_u3["continuidad"]["nota"], sala_u3["nota_continuidad"])
        self.assertIn("Dra. A levantó", sala_u3["continuidad"]["nota"])
        self.assertEqual(sala_u3["reabierta"]["de_ubicacion"], 2)
        pend = [p for p in motor.vista_bandeja(JUEZ_A)["pendientes"] if p["n"] == 3][0]
        vu3 = [x for x in pend["expediente"]["ubicaciones"] if x["n"] == 3][0]
        self.assertIn("usted levantó", vu3["continuidad"]["nota"])
        self.assertNotIn("nota", u3["continuidad"], "la nota es de la vista: el estado sellado no cambia")


class TestSalaYAvisosParaW(ConPartido):
    avisos = r3.TestAvisosQueSeCierran.avisos

    def test_jueces_de_la_sala_traen_su_turno(self):
        motor, sim, _ = self.preparar(aprobar=False)
        jueces = {j["juez_id"]: j for j in motor.vista_sala()["jueces"]}
        ahora = motor.ahora()
        for t in motor.e["turnos"]:
            j = jueces[t["juez_id"]]
            self.assertIn("turno", j)
            if t["desde_min"] <= ahora < t["hasta_min"]:
                self.assertEqual(j["turno"], {"desde_min": t["desde_min"], "hasta_min": t["hasta_min"]})
        for j in jueces.values():
            if j["turno"] is not None:
                self.assertEqual(set(j["turno"]), {"desde_min", "hasta_min"})
                self.assertGreater(j["turno"]["hasta_min"], ahora)

    def test_el_cierre_de_la_alerta_de_ausencia_dice_de_que_juez_era(self):
        motor, sim, usuarios = self.preparar(aprobar=False)
        usuarios._actividad["juez-a"] = time.monotonic() - 200
        motor._paso_presencia()
        a = [a for a in self.avisos(motor, "alerta") if "no tiene la plataforma" in a["texto"]][0]
        self.assertEqual(a["juez_ausente"], "juez-a")
        usuarios.marcar_actividad("juez-a")
        motor._paso_presencia()
        self.assertEqual(a["cierre"]["juez_ausente"], "juez-a")
        vista = [v for v in motor.vista_sala()["avisos"] if v["n"] == a["n"]][0]
        self.assertEqual((vista["juez_ausente"], vista["cierre"]["juez_ausente"]), ("juez-a", "juez-a"))


if __name__ == "__main__":
    unittest.main()
