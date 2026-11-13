"""Antes de firmar (pantalla del juez): las tres comprobaciones y qué se bloquea, pegadas a los botones de firma.

Contratos:
- El resumen dice lo mismo que las tres comprobaciones de arriba (señal, servidor, daño colateral).
- Si el juez se aparta para bloquear por IP una IP compartida, el resumen muestra el riesgo de esa IP, nunca el
  verde de la recomendación por nombre.
- «Se bloquea» junta a los proveedores que reciben lo mismo y nombra cada objetivo; sin nada que bloquear, null.
- El resumen va dentro de la decisión, antes de los botones, y se rehace cuando el juez cambia el tipo de bloqueo.
- Un pedido nuevo se trae a la vista solo si es el único pendiente y el juez no está tocando ni escribiendo.

El JS corre el código real con node (se saltea sin node).
"""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
JS = RAIZ / "marca" / "web" / "static" / "js"
NODE = shutil.which("node")
FUENTE = (JS / "juez.js").read_text(encoding="utf-8")


def funcion(nombre):
    i = FUENTE.index("function " + nombre + "(")
    j = FUENTE.index("{", i)
    prof = 0
    for k in range(j, len(FUENTE)):
        if FUENTE[k] == "{":
            prof += 1
        elif FUENTE[k] == "}":
            prof -= 1
            if prof == 0:
                return FUENTE[i:k + 1]
    raise AssertionError("no cierra " + nombre)


def constante(nombre):
    m = re.search(r"const " + nombre + r" = \{.*?\n  \};", FUENTE, re.S)
    if not m:
        raise AssertionError("no está " + nombre)
    return m.group(0)


CORRER = r"""
const [codigo, nombre, args] = process.argv.slice(1);
const f = new Function(codigo + '\nreturn ' + nombre + ';')();
console.log(JSON.stringify(f(...JSON.parse(args)) ?? null));
"""


def correr(nombre, *args):
    codigo = "\n".join([constante("RIESGO"), funcion("riesgoDelBloqueo"), funcion("resumenComprobaciones"),
                        funcion("lineaBloqueo")])
    r = subprocess.run([NODE, "-e", CORRER, codigo, nombre, json.dumps(args)], capture_output=True, text=True, timeout=30)
    if r.returncode:
        raise AssertionError(r.stderr)
    return json.loads(r.stdout)


UBIC_LIMPIA = {"senal": {"clase": "pirata"}, "coherencia": {"completa": True, "ok": True},
               "colateral": {"riesgo": "nulo", "recomendacion": "ip"}}
UBIC_COMPARTIDA = {"senal": {"clase": "pirata"}, "coherencia": {"completa": True, "ok": True},
                   "colateral": {"riesgo": "alto", "recomendacion": "dominio", "ajenos": ["panaderia-la-espiga.test"]}}


@unittest.skipUnless(NODE, "sin node")
class ResumenDeComprobaciones(unittest.TestCase):
    def test_dice_lo_mismo_que_las_tres_comprobaciones(self):
        r = correr("resumenComprobaciones", UBIC_LIMPIA, None)
        self.assertEqual([(x["clase"], x["texto"]) for x in r],
                         [("ok", "Señal del partido"), ("ok", "Servidor coherente"), ("ok", "Sin daño colateral")])

    def test_senal_ajena_y_servidor_que_no_coincide_no_salen_en_verde(self):
        u = {"senal": {"clase": "otra"}, "coherencia": {"completa": False, "ok": False}, "colateral": {}}
        r = correr("resumenComprobaciones", u, None)
        self.assertEqual([x["clase"] for x in r[:2]], ["alerta", "alerta"])
        self.assertEqual(r[2]["clase"], "neutro")

    def test_bloquear_por_ip_una_ip_compartida_muestra_su_riesgo(self):
        recomendado = correr("resumenComprobaciones", UBIC_COMPARTIDA, None)
        self.assertEqual(recomendado[2]["clase"], "espera")  # por nombre no toca a nadie; avisa el riesgo de la IP
        forzado = correr("resumenComprobaciones", UBIC_COMPARTIDA, "ip")
        self.assertEqual((forzado[2]["clase"], forzado[2]["texto"]), ("alerta", "Riesgo alto"))


@unittest.skipUnless(NODE, "sin node")
class QueSeBloquea(unittest.TestCase):
    NOMBRES = {"aurora": "Conectividad Aurora", "andina": "Red Andina Telecom", "cumbre": "Cooperativa Cumbre Conecta",
               "valle": "FibraValle"}

    def test_junta_a_los_proveedores_que_reciben_lo_mismo(self):
        ip = [{"tipo": "ip", "objetivo": "203.0.113.10"}]
        plan = {"objetivos_por_proveedor": {
            "aurora": ip, "andina": ip, "cumbre": ip,
            "valle": [{"tipo": "dominio", "objetivo": "s1.pelotaya.test"},
                      {"tipo": "dominio", "objetivo": "s1-respaldo.pelotaya.test"}]}}
        self.assertEqual(correr("lineaBloqueo", plan, self.NOMBRES),
                         "IP 203.0.113.10 en Conectividad Aurora, Red Andina Telecom y Cooperativa Cumbre Conecta; "
                         "s1.pelotaya.test y s1-respaldo.pelotaya.test en FibraValle.")

    def test_un_solo_proveedor(self):
        plan = {"objetivos_por_proveedor": {"valle": [{"tipo": "dominio", "objetivo": "tv.verpartido-hd.test"}]}}
        self.assertEqual(correr("lineaBloqueo", plan, self.NOMBRES), "tv.verpartido-hd.test en FibraValle.")

    def test_sin_nada_que_bloquear(self):
        self.assertIsNone(correr("lineaBloqueo", {"objetivos_por_proveedor": {}}, self.NOMBRES))
        self.assertIsNone(correr("lineaBloqueo", {}, self.NOMBRES))


class Ubicacion(unittest.TestCase):
    def test_el_resumen_va_antes_de_los_botones(self):
        self.assertIn("el('div', { class: 'decision' }, antesDeFirmar(u, prop, f, rec), botones,", FUENTE)

    def test_se_rehace_al_cambiar_el_tipo_de_bloqueo(self):
        actualizar = funcion("apartarse")
        self.assertIn("resumen.replaceWith(antesDeFirmar(u, prop || {}, f, rec))", actualizar)

    def test_solo_trae_a_la_vista_el_unico_pedido_con_el_juez_quieto(self):
        alertar = funcion("alertar")
        self.assertIn("if (pedido && quieto && !escribiendo && pendientesDe(b).length === 1)", alertar)


if __name__ == "__main__":
    unittest.main()
