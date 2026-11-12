"""Contrato: lo que docs/ESPECIFICACION.md (lo que lee el jurado técnico) dice del corte de envío del final y de
`exportar` con el partido cerrado es lo que hace el código. Cada prueba ejecuta el comportamiento y exige que el
documento lo cuente; falla si el documento vuelve a afirmar la regla vieja."""
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from tests.simulador_falso import deteccion
from tests.test_contratos_ronda2 import ConPartido, ronda
from tests.test_robustez import PIRATA, motor_con

ESPEC = (Path(__file__).resolve().parent.parent / "docs" / "ESPECIFICACION.md").read_text(encoding="utf-8")


def seccion(titulo_inicio: str, siguiente: str) -> str:
    i = ESPEC.index(titulo_inicio)
    return ESPEC[i:ESPEC.index(siguiente, i + 1)]


class TestCorteDeEnvioDocumentado(unittest.TestCase):
    def test_a_x20_con_medio_minuto_de_margen_no_sale_y_la_especificacion_lo_dice(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        motor, sim, usuarios = motor_con(Path(d.name) / "p")
        sim.acelerar = 20.0
        sim.lista_detecciones = [deteccion("D-1", 18.9, *PIRATA)]
        usuarios.ingresar("b", "clave-de-prueba-b")
        sim.avanzar(19.5)  # fin 20: faltan 0,5 min de partido (> 0,05, < margen a ×20)
        motor._t_estado = float("-inf")
        motor.paso()
        exp = motor.e["expedientes"][0]
        motor.aprobar("juez-b", exp["id"], 1, "ubicacion", None, None)
        for _ in range(3):
            motor.despacho.ronda()
        self.assertEqual(sum(1 for x in sim.registro if x["evento"] == "orden_recibida"), 0)  # premisa: el código
        s55 = seccion("### 5.5 Órdenes", "### 5.6")
        self.assertNotIn("`fin_min − 0,05`", s55, "§5.5 sigue diciendo que el corte es fin_min − 0,05")
        self.assertIn("1,5 × D", s55)
        self.assertIn("no_enviada", s55)
        s16 = seccion("16. **Margen de envío", "17. ")
        self.assertIn("1,5 × D", s16, "§16.16 omite la latencia medida en el margen")


class TestExportarTrasElCierreDocumentado(ConPartido):
    def test_exportar_tras_el_cierre_no_refresca_y_la_especificacion_lo_dice(self):
        from marca.__main__ import exportar_paquete
        motor, sim, _ = self.preparar()
        ronda(motor, 2)
        for m in (5.0, 10.0, 15.0, 20.5, 25.5, 26.0):
            sim.avanzar(m)
            motor._t_estado = float("-inf")
            motor.paso()
            motor.despacho.ronda()
        aud = motor.salida / "auditoria.jsonl"
        antes = aud.read_bytes()
        with redirect_stdout(io.StringIO()):
            self.assertEqual(exportar_paquete(motor.salida, self.base / "dest", espera_s=1.0, cliente=sim,
                                              imprimir=print), 0)
        self.assertEqual(aud.read_bytes(), antes)  # premisa: el código no pidió testigos ni escribió la auditoría
        s13 = seccion("## 13. Exportación y verificación", "## 14.")
        self.assertNotIn("\n- `python3 -m marca exportar` también los refresca.", s13,
                         "§13 afirma sin condición que exportar refresca los testigos")
        self.assertIn("partido **cerrado**", s13)
        self.assertIn("copia ese paquete tal cual", s13)


if __name__ == "__main__":
    unittest.main()
