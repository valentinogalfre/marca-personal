"""Contrato del veredicto de herramientas/ensayo.py.

V1  El veredicto es CUMPLE si y solo si no hay nada grave (ceros de seguridad) y no hay ningun defecto
    alcanzable: una fase de duracion cero no cuenta, y lo que herramientas/alcanzable.py da por imposible o
    de suerte no lo hace fallar.
V2  Una fase alcanzable segura que quedo sin bloquear sigue dando NO CUMPLE.
V3  Con --inicio-min posterior al ultimo cambio de turno no se exige traspaso; si hay un cambio despues, si.
"""
import sys
import unittest
from argparse import Namespace
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "herramientas"))
import alcanzable  # noqa: E402
import ensayo  # noqa: E402

CEROS = {"ordenes_rechazadas": 0, "ordenes_firmadas_fuera_de_turno": 0, "bloqueos_falsos_positivos": 0,
         "bloqueos_ip_activos_post_partido": 0, "bloqueos_con_dano_colateral": 0, "reclamos": 0,
         "reclamos_resueltos_por_levantamiento": 0}
PROVEEDORES = {"proveedores": [
    {"id": "rapido", "clientes": 50, "capacidades": ["ip", "dominio"], "comportamiento": {"demora_min": 0.5}},
    {"id": "lento", "clientes": 50, "capacidades": ["dominio"], "comportamiento": {"demora_min": 6}},
]}
FASES = [  # (desde, hasta, host)
    (10, 50, "a.test"),       # larga: alcanzable segura para los dos
    (50, 50.3, "b.test"),     # 0,3 min: imposible para los dos
    (105, 105, "c.test"),     # duracion cero
]
VERDAD = {"escenario_id": "sintetico", "fin_min": 105, "gracia_min": 5, "streams": [
    {"id": "s1", "clase": "pirata", "fases": [{"desde_min": d, "hasta_min": h, "ip": "203.0.113.%d" % n, "host": host}
                                             for n, (d, h, host) in enumerate(FASES, start=1)]}]}


def args(**kw):
    base = dict(inicio_min=0.0, forzar_ip=None, sin_dinamica=False, alcance="filtracion", reiniciar_en=None)
    base.update(kw)
    return Namespace(**base)


def partido(bloquear_a: bool):
    eventos = [{"min": 0.0, "evento": "simulacion_iniciada", "escenario": "sintetico"}]
    if bloquear_a:
        for prov, aplicada in (("rapido", 11.0), ("lento", 17.0)):
            eventos.append({"min": 10.5, "evento": "orden_recibida", "proveedor": prov, "orden_id": "o-" + prov,
                            "tipo": "dominio", "objetivo": "a.test"})
            eventos.append({"min": aplicada, "evento": "orden_aplicada", "proveedor": prov, "orden_id": "o-" + prov})
    eventos.append({"min": 110.0, "evento": "simulacion_terminada"})
    fases = []
    for n, (d, h, host) in enumerate(FASES, start=1):
        bloq = bloquear_a and n == 1
        fases.append({"stream": "s1", "fase": n, "host": host, "desde_min": d, "hasta_min": h,
                      "primer_bloqueo_min": 1.0 if bloq else None,
                      "proveedores_que_bloquearon": ["lento", "rapido"] if bloq else [],
                      "clientes_cubiertos_pct": 100.0 if bloq else 0.0})
    oficial = {"escenario": "sintetico", "log_hasta_min": 110.0, "resumen": dict(CEROS), "fases": fases}
    oraculo = alcanzable.evaluar(VERDAD, PROVEEDORES, oficial, eventos)
    return oficial, oraculo


ESTADO = {"traspasos": [], "ordenes": {}, "expedientes": [], "proveedores": [], "reclamos": {}}


class VeredictoDelEnsayo(unittest.TestCase):
    def test_v1_cero_duracion_e_imposible_no_hacen_fallar(self):
        oficial, oraculo = partido(bloquear_a=True)
        crit = ensayo.veredicto(args(), oficial, True, ESTADO, oraculo=oraculo)
        self.assertTrue(all(ok for ok, _ in crit), [t for ok, t in crit if not ok])

    def test_v1_cero_duracion_no_cuenta_aunque_no_haya_oraculo(self):
        oficial, _ = partido(bloquear_a=True)
        crit = ensayo.veredicto(args(), oficial, True, ESTADO)
        textos = [t for _, t in crit if "fases evaluables" in t]
        self.assertTrue(textos and "de 2 fases evaluables" in textos[0], textos)

    def test_v2_fase_alcanzable_sin_bloquear_es_no_cumple(self):
        oficial, oraculo = partido(bloquear_a=False)
        crit = ensayo.veredicto(args(), oficial, True, ESTADO, oraculo=oraculo)
        self.assertFalse(all(ok for ok, _ in crit))

    def test_v1_lo_grave_sigue_mandando(self):
        oficial, oraculo = partido(bloquear_a=True)
        oficial["resumen"]["ordenes_firmadas_fuera_de_turno"] = 1
        crit = ensayo.veredicto(args(), oficial, True, ESTADO, oraculo=oraculo)
        self.assertFalse(all(ok for ok, _ in crit))

    def test_v3_sin_cambio_de_turno_posterior_no_se_exige_traspaso(self):
        oficial, oraculo = partido(bloquear_a=True)
        crit = ensayo.veredicto(args(inicio_min=60.0), oficial, True, ESTADO, oraculo=oraculo,
                                cambios_turno=[-60.0, 50.0])
        self.assertTrue(all(ok for ok, _ in crit), [t for ok, t in crit if not ok])

    def test_v3_con_cambio_de_turno_posterior_se_exige_traspaso(self):
        oficial, oraculo = partido(bloquear_a=True)
        crit = ensayo.veredicto(args(inicio_min=44.0), oficial, True, ESTADO, oraculo=oraculo,
                                cambios_turno=[-60.0, 50.0])
        self.assertIn((False, "traspaso creado y ratificado (0 traspaso(s))"), crit)


if __name__ == "__main__":
    unittest.main()
