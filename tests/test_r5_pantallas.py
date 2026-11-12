"""Contratos de pantallas, Ola D (W): g-despacho-1 (tres causas de una orden que no bloqueó) y NV7 (la tarjeta
«Recibe el turno» no ofrece ratificar un seguimiento propio; el aviso de recibir sale de lo que se ratificó de verdad).

El JS corre el código real con node (se saltea sin node); la API simulada, con un reloj controlado.
"""
import importlib.util
import json
import shutil
import subprocess
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
JS = RAIZ / "marca" / "web" / "static" / "js"
NODE = shutil.which("node")
LAURA = "jueza-laura-ficticia"
MARTIN = "juez-martin-ejemplo"

spec = importlib.util.spec_from_file_location("api_simulada_r5", RAIZ / "herramientas" / "api_simulada.py")
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)


class Reloj:
    def __init__(self):
        self.m = A.Mundo(6.0, -3.3, False, True)
        self.r = {"m": -3.3}
        self.m.minuto = lambda: self.r["m"]

    def hasta(self, x):
        while self.r["m"] < x:
            self.r["m"] = round(self.r["m"] + 0.05, 4)
            self.m.tick()

    def bandeja(self, juez_id):
        usuario = next(k for k, v in A.USUARIOS.items() if v.get("juez_id") == juez_id)
        with self.m.cond:
            return self.m.bandeja(usuario)


def funcion(fuente, nombre):
    i = fuente.index("function " + nombre + "(")
    j = fuente.index("{", i)
    prof = 0
    for k in range(j, len(fuente)):
        if fuente[k] == "{":
            prof += 1
        elif fuente[k] == "}":
            prof -= 1
            if prof == 0:
                return fuente[i:k + 1]
    raise AssertionError("no cierra " + nombre)


CORRER = r"""
const fs = require('fs'); const vm = require('vm');
const [comun, codigo, nombre, args] = process.argv.slice(1);
const ctx = { window: {}, document: { addEventListener() {}, querySelector() { return null; }, createElement() { return {}; },
  visibilityState: 'visible', title: '', body: { appendChild() {} } }, Node: function () {}, navigator: {}, console,
  setTimeout, clearTimeout, setInterval: () => 0, clearInterval() {}, location: { pathname: '/', search: '' },
  fetch: () => Promise.reject(new Error('sin red')), localStorage: { getItem() { return null; }, setItem() {} },
  sessionStorage: { getItem() { return null; }, setItem() {} }, performance: { now: () => 0 }, Intl, Date, Math, JSON,
  Number, String, AbortController };
ctx.window = ctx; ctx.globalThis = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(comun, 'utf8'), ctx);
const MP = ctx.MP;
const f = codigo ? new Function('MP', codigo + '\nreturn ' + nombre + ';')(MP) : MP[nombre];
console.log(JSON.stringify(f(...JSON.parse(args)) ?? null));
"""


def correr(archivo, nombre, *args):
    codigo = funcion((JS / archivo).read_text(encoding="utf-8"), nombre) if archivo else ""
    r = subprocess.run([NODE, "-e", CORRER, str(JS / "comun.js"), codigo, nombre, json.dumps(args)],
                       capture_output=True, text=True, timeout=30)
    if r.returncode:
        raise AssertionError(r.stderr)
    return json.loads(r.stdout)


@unittest.skipUnless(NODE, "sin node")
class CausasDeUnaOrdenQueNoBloqueo(unittest.TestCase):
    """g-despacho-1: cada causa con su texto (los mismos del acta); sin `no_enviada`, nada cambia."""

    def test_tres_causas(self):
        turno = correr(None, "causaNoEnviada", {"no_enviada": True, "estado": "espera_ratificacion"})
        self.assertEqual((turno["rotulo"], turno["texto"]), ("No enviada", "Sin bloquear: el juez entrante no recibió el turno."))
        conf = correr(None, "causaNoEnviada", {"no_enviada": True, "estado": "por_enviar", "enviada_min": 104.9})
        self.assertEqual((conf["rotulo"], conf["texto"]),
                         ("Sin confirmar", "Sin confirmar: se envió y, al cierre, el proveedor no la tenía."))
        final = correr(None, "causaNoEnviada", {"no_enviada": True, "estado": "por_enviar", "enviada_min": None})
        self.assertEqual((final["rotulo"], final["texto"]),
                         ("No enviada", "Sin bloquear: la firma llegó cuando el partido terminaba."))
        self.assertIsNone(correr(None, "causaNoEnviada", {"estado": "por_enviar"}))

    def test_una_ubicacion_con_varias_causas(self):
        c = correr(None, "causaNuncaSalio", [{"no_enviada": True, "estado": "espera_ratificacion"},
                                             {"no_enviada": True, "estado": "por_enviar", "enviada_min": 104.9}])
        self.assertEqual(c["texto"], "Sin bloquear: ninguna de sus órdenes llegó a aplicarse.")

    def test_lampara_con_el_titulo_de_su_causa(self):
        p = {"estado": "por_enviar", "ref": {"no_enviada": True, "estado": "por_enviar", "enviada_min": 104.9}}
        self.assertEqual(correr("sala.js", "estadoLampara", p), "no_enviada")
        sala = (JS / "sala.js").read_text(encoding="utf-8")
        self.assertIn("if (st === 'no_enviada') { const c = MP.causaNoEnviada(p && p.ref); if (c) return c.texto; }", sala)
        self.assertIn("text: MP.causaNuncaSalio(u.ordenes).texto", sala)
        juez = (JS / "juez.js").read_text(encoding="utf-8")
        self.assertIn("MP.noEnviada(o) ? MP.causaNoEnviada(o).texto : detalleOrden(o)", juez)


class SimuladaMarcaLoQueQuedaEsperandoAlFinal(unittest.TestCase):
    """Paridad con el motor: al final, lo que sigue esperando al juez entrante también queda `no_enviada`."""

    def test_espera_ratificacion_al_final(self):
        w = Reloj()
        w.hasta(1)
        w.m.firmar_marco(LAURA, True)
        w.hasta(3)
        exp = w.m.expedientes[0]
        w.m.decidir(LAURA, exp, exp["ubicaciones"][0], True, "filtracion", None, None)
        w.hasta(52)
        # Una orden de Laura que sale después de su turno queda esperando al juez entrante (el camino de `enviar`).
        u = exp["ubicaciones"][0]
        w.m.crear_orden(exp, u, "cumbre", "ip", u["ip"], LAURA, "f" * 32, "decision", 52.0)
        w.hasta(A.PARTIDO["fin_min"] + 0.5)  # Martín nunca recibe el turno
        esperando = [o for o in w.m.ordenes if o["estado"] == "espera_ratificacion"]
        self.assertTrue(esperando, "el escenario necesita órdenes esperando al juez entrante")
        self.assertTrue(all(A.Mundo.vista_orden(o)["no_enviada"] for o in esperando))


class NV7SeguimientoPropioNoEsHerencia(unittest.TestCase):
    """Martín ratificó el heredado al «Firmar y seguir» y además firmó y siguió una filtración NUEVA: la tarjeta no
    ofrece casillas (nada espera ratificación) y tiene un solo botón."""

    @classmethod
    def setUpClass(cls):
        w = Reloj()
        w.hasta(1)
        w.m.firmar_marco(LAURA, True)
        w.hasta(3)
        cls.heredado = w.m.expedientes[0]
        w.m.decidir(LAURA, cls.heredado, cls.heredado["ubicaciones"][0], True, "filtracion", None, None)
        w.hasta(72)
        w.m.firmar_marco(MARTIN, True)
        pend = [u for u in cls.heredado["ubicaciones"] if u["estado"] == "pendiente"]
        w.m.decidir(MARTIN, cls.heredado, pend[-1], True, "filtracion", None, None)
        cls.propio = next(e for e in w.m.expedientes if e is not cls.heredado and e["filtracion"].get("sesion")
                          and any(u["estado"] == "pendiente" for u in e["ubicaciones"]) and not e["dinamica"])
        u = next(u for u in cls.propio["ubicaciones"] if u["estado"] == "pendiente")
        w.m.decidir(MARTIN, cls.propio, u, True, "filtracion", None, None)
        cls.b = w.bandeja(MARTIN)
        cls.t = dict(cls.b["traspaso"])
        # Como el motor antes del arreglo de E: el resumen lista TODOS los seguimientos activos, también el propio.
        cls.t["resumen"] = dict(cls.t["resumen"], dinamicas=list(cls.t["resumen"]["dinamicas"]) + [
            {"exp": cls.propio["id"], "titulo": cls.propio["titulo"]}])

    @unittest.skipUnless(NODE, "sin node")
    def test_sin_casillas_y_un_solo_boton(self):
        self.assertFalse(any(d.get("requiere_ratificacion") for d in self.b["dinamicas"]))
        r = correr("juez.js", "herenciaTraspaso", self.t, self.b)
        self.assertEqual(r["pendientes"], [])
        self.assertEqual([d["exp"] for d in r["ratificadas"]], [self.heredado["id"]])
        f = funcion((JS / "juez.js").read_text(encoding="utf-8"), "pintarTraspaso")
        self.assertIn("herenciaTraspaso(t, b)", f)
        self.assertIn("} else if (!dins.length) {", f)  # sin casillas: solo «Recibir el turno»

    @unittest.skipUnless(NODE, "sin node")
    def test_aviso_de_recibir_con_la_respuesta(self):
        t = {"resumen": {"dinamicas": [{"exp": "EXP-1", "titulo": "pelotaya.test"}, {"exp": "EXP-2", "titulo": "golazo-libre.test"}]}}
        self.assertEqual(correr("juez.js", "avisoRecibio", {"resultado": {"ratificadas": ["EXP-1"], "sin_ratificar": []}}, t, "x"),
                         "Recibió el turno.")
        self.assertEqual(correr("juez.js", "avisoRecibio", {"resultado": {"ratificadas": [], "sin_ratificar": ["EXP-1", "EXP-2"]}}, t, "x"),
                         "Recibió el turno. Sin ratificar: pelotaya.test y golazo-libre.test; sus mudanzas vuelven a pedir su firma.")
        self.assertEqual(correr("juez.js", "avisoRecibio", {"ok": True}, t, "texto de antes"), "texto de antes")

    def test_la_simulada_responde_lo_ratificado(self):
        fuente = (RAIZ / "herramientas" / "api_simulada.py").read_text(encoding="utf-8")
        self.assertIn('"resultado": res})', fuente)
        w = Reloj()
        w.hasta(1)
        w.m.firmar_marco(LAURA, True)
        w.hasta(3)
        e = w.m.expedientes[0]
        w.m.decidir(LAURA, e, e["ubicaciones"][0], True, "filtracion", None, None)
        w.hasta(55)
        w.m.firmar_marco(MARTIN, True)
        with w.m.cond:
            w.m.ratificar(MARTIN, [])
        self.assertEqual(w.m.ultimo_ratificar, {"ratificadas": [], "sin_ratificar": [e["id"]]})


if __name__ == "__main__":
    unittest.main()
