"""Ensayo con personas (herramientas/ensayo.py --personas): el mismo ensayo y el mismo veredicto, pero firman personas.

Contratos:
- P1  Con --personas no arranca ningún juez automático (el acta tiene que poder decir «Firmaron: personas»).
      Sin --personas, uno por cada juez de la configuración (la fiscalía nunca firma).
- P2  La plataforma se abre con el --host pedido (0.0.0.0 para los celulares); por defecto, solo esta máquina.
- P3  Al terminar se imprime la fila «Personas» del README con los números del verificador oficial y del acta:
      casilla destildada en las columnas de la casilla destildada; seguimiento autorizado en las del seguimiento.
      Coma decimal, residual con un decimal, tiempos con dos, «—» si falta un dato.
"""
import sys
import unittest
from argparse import Namespace
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "herramientas"))
import ensayo  # noqa: E402

CFG = {"usuarios": [{"usuario": "laura", "rol": "juez"}, {"usuario": "martin", "rol": "juez"},
                    {"usuario": "fiscalia", "rol": "fiscalia"}]}
OFICIAL = {"resumen": {"fases_piratas_bloqueadas": "7 de 7", "visibilidad_residual_promedio_pct": 5.0}}
PROMEDIOS = {"en_persona": {"ubicaciones": 9, "hasta_firma_min": 0.8234, "hasta_primer_proveedor_min": 1.3,
                            "hasta_todos_min": 7.771},
             "ampliacion": {"ubicaciones": 4, "hasta_firma_min": 0.012, "hasta_primer_proveedor_min": 0.52,
                            "hasta_todos_min": 6.66}}


def args(**kw):
    base = dict(acelerar=6.0, puerto_plataforma_sim=8791, puerto=8792, host="127.0.0.1", config="c.json", tick=0.25,
                sin_dinamica=False)
    base.update(kw)
    return Namespace(**base)


class P1SinJuezAutomatico(unittest.TestCase):
    def test_con_personas_no_corre_ningun_juez_automatico(self):
        self.assertEqual(ensayo.jueces_automaticos(CFG, personas=True), [])

    def test_sin_personas_uno_por_juez_y_nunca_la_fiscalia(self):
        self.assertEqual([u["usuario"] for u in ensayo.jueces_automaticos(CFG, personas=False)], ["laura", "martin"])


class P2Host(unittest.TestCase):
    def test_la_plataforma_se_abre_con_el_host_pedido(self):
        cmd = ensayo.comando_plataforma(args(host="0.0.0.0"), Path("/tmp/x"), nueva=True)
        self.assertEqual(cmd[cmd.index("--host") + 1], "0.0.0.0")
        self.assertIn("--nueva", cmd)

    def test_por_defecto_solo_esta_maquina(self):
        cmd = ensayo.comando_plataforma(Namespace(**{k: v for k, v in vars(args()).items() if k != "host"}),
                                        Path("/tmp/x"), nueva=False)
        self.assertEqual(cmd[cmd.index("--host") + 1], "127.0.0.1")
        self.assertNotIn("--nueva", cmd)


class P3FilaDelReadme(unittest.TestCase):
    def test_casilla_destildada_va_en_sus_columnas(self):
        fila = ensayo.fila_personas(6.0, OFICIAL, PROMEDIOS, seguimiento=False)
        self.assertEqual(fila, "| Personas del equipo, ×6, casilla destildada | 7 de 7 · 5,0 % | 0,82 → 1,30 → 7,77 "
                               "| — | — | — |")

    def test_seguimiento_autorizado_va_en_las_del_seguimiento(self):
        fila = ensayo.fila_personas(20.0, OFICIAL, PROMEDIOS, seguimiento=True)
        self.assertEqual(fila, "| Personas del equipo, ×20, seguimiento autorizado | — | — | 7 de 7 · 5,0 % "
                               "| 0,82 → 1,30 → 7,77 | 0,01 → 0,52 → 6,66 |")

    def test_dato_que_falta_es_raya(self):
        fila = ensayo.fila_personas(6.0, {"resumen": {}}, {"en_persona": {"hasta_firma_min": 1.0}}, seguimiento=False)
        self.assertEqual(fila, "| Personas del equipo, ×6, casilla destildada | — · — | 1,00 → — → — | — | — | — |")

    def test_la_plantilla_comentada_del_readme_tiene_la_misma_forma(self):
        readme = (RAIZ / "README.md").read_text(encoding="utf-8")
        self.assertIn("| Personas del equipo, ×6, casilla destildada | bloqueados · residual |", readme)
        self.assertIn("ensayo.py --personas", readme)


if __name__ == "__main__":
    unittest.main()
