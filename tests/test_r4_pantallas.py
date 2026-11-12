"""Contratos de pantallas, Ola C (W): NV4, NV5, NV6, la hora del kit en /orden y la propuesta recalculada.

- NV4: lo que el juez entrante ya ratificó al «Firmar y seguir» no vuelve a pedirse en «Recibe el turno»; se muestra
  aparte. La sala dice que el seguimiento ya se ratificó aunque el turno no se haya recibido.
- NV5: fuera de turno no se pide dejar la pantalla abierta.
- NV6: con el partido terminado, «Recibe el turno» no tiene botones y su aviso no queda como pendiente.
- Kit: si la hora del partido (texto de la orden) y la hora real del kit no coinciden, la página rotula cada una.
- Recalculada (Ola C, 6): si la propuesta de un pedido se rehízo al resolverse un reclamo, la tarjeta lo dice.

El JS corre el código real con node (se saltea sin node). La API simulada se conduce con un reloj controlado.
"""
import importlib.util
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
JS = RAIZ / "marca" / "web" / "static" / "js"
NODE = shutil.which("node")
LAURA = "jueza-laura-ficticia"
MARTIN = "juez-martin-ejemplo"


def cargar_simulada():
    spec = importlib.util.spec_from_file_location("api_simulada_r4", RAIZ / "herramientas" / "api_simulada.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


A = cargar_simulada()


class Reloj:
    def __init__(self, auto=False):
        self.m = A.Mundo(6.0, -3.3, auto, True)
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
    """El texto de `function nombre(...) {...}` tal como está en el archivo (llaves balanceadas)."""
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
    raise AssertionError("no cierra la función " + nombre)


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
const f = new Function('MP', codigo + '\nreturn ' + nombre + ';')(ctx.MP);
console.log(JSON.stringify(f(...JSON.parse(args))));
"""


def correr(archivo, nombre, *args):
    codigo = funcion((JS / archivo).read_text(encoding="utf-8"), nombre)
    r = subprocess.run([NODE, "-e", CORRER, str(JS / "comun.js"), codigo, nombre, json.dumps(args)], capture_output=True, text=True, timeout=30)
    if r.returncode:
        raise AssertionError(r.stderr)
    return json.loads(r.stdout)


class NV4SimuladaRegistraLoRatificadoAlFirmar(unittest.TestCase):
    """Martín recibe el seguimiento heredado de Laura y firma una mudanza con «Firmar y seguir»: eso lo ratifica, y
    el traspaso lo anota sin darlo por recibido."""

    @classmethod
    def setUpClass(cls):
        cls.w = Reloj()
        w = cls.w
        w.hasta(1)
        w.m.firmar_marco(LAURA, True)
        w.hasta(3)
        cls.exp = w.m.expedientes[0]
        w.m.decidir(LAURA, cls.exp, cls.exp["ubicaciones"][0], True, "filtracion", None, None)
        w.hasta(72)
        w.m.firmar_marco(MARTIN, True)
        cls.requeria = cls.exp["dinamica"]["requiere_ratificacion"]
        pend = [u for u in cls.exp["ubicaciones"] if u["estado"] == "pendiente"]
        w.m.decidir(MARTIN, cls.exp, pend[-1], True, "filtracion", None, None)
        cls.t = w.bandeja(MARTIN)["traspaso"]

    def test_el_traspaso_anota_lo_ratificado_al_firmar(self):
        self.assertTrue(self.requeria, "el escenario necesita un seguimiento heredado sin ratificar")
        self.assertIsNotNone(self.t, "el traspaso no recibido tiene que seguir en la bandeja del entrante")
        self.assertFalse(self.t.get("ratificado"))
        al = self.t.get("ratificadas_al_firmar") or []
        self.assertEqual([x["id"] for x in al], [self.exp["id"]])
        self.assertEqual(al[0]["juez_id"], MARTIN)
        self.assertIsInstance(al[0]["min"], float)
        self.assertIn(self.exp["id"], self.t.get("dinamicas_ratificadas") or [])

    @unittest.skipUnless(NODE, "sin node")
    def test_la_tarjeta_no_vuelve_a_pedir_lo_ya_ratificado(self):
        r = correr("juez.js", "herenciaTraspaso", self.t)
        self.assertEqual([d["exp"] for d in r["pendientes"]], [])
        self.assertEqual([d["exp"] for d in r["ratificadas"]], [self.exp["id"]])
        self.assertEqual(r["ratificadas"][0]["ratificada_min"], self.t["ratificadas_al_firmar"][0]["min"])

    def test_recibir_el_turno_despues_no_pisa_lo_ratificado_al_firmar(self):
        with self.w.m.cond:
            self.w.m.ratificar(MARTIN, [])
            t = self.w.m.traspasos[-1]
        self.assertTrue(t.get("ratificado"))
        self.assertIn(self.exp["id"], t.get("dinamicas_ratificadas") or [])
        self.assertEqual([x["id"] for x in t.get("ratificadas_al_firmar") or []], [self.exp["id"]])


@unittest.skipUnless(NODE, "sin node")
class NV4PantallasSinElCampo(unittest.TestCase):
    RESUMEN = {"dinamicas": [{"exp": "EXP-1", "titulo": "pelotaya.test"}, {"exp": "EXP-2", "titulo": "golazo-libre.test"}]}

    def test_sin_ratificadas_al_firmar_usa_dinamicas_ratificadas(self):
        r = correr("juez.js", "herenciaTraspaso", {"resumen": self.RESUMEN, "dinamicas_ratificadas": ["EXP-2"]})
        self.assertEqual([d["exp"] for d in r["pendientes"]], ["EXP-1"])
        self.assertEqual([d["exp"] for d in r["ratificadas"]], ["EXP-2"])
        self.assertIsNone(r["ratificadas"][0]["ratificada_min"])

    def test_sin_ningun_campo_todo_queda_pendiente(self):
        r = correr("juez.js", "herenciaTraspaso", {"resumen": self.RESUMEN})
        self.assertEqual([d["exp"] for d in r["pendientes"]], ["EXP-1", "EXP-2"])
        self.assertEqual(r["ratificadas"], [])

    def test_sala_dice_que_ya_se_ratifico_al_firmar(self):
        s = {"expedientes": [{"id": "EXP-1", "titulo": "pelotaya.test"}]}
        texto = correr("sala.js", "textoTraspaso", {"ratificadas_al_firmar": [{"id": "EXP-1", "min": 72.0}]}, s)
        self.assertEqual(texto, "El juez entrante todavía no confirmó la recepción del turno; el seguimiento de "
                                "pelotaya.test ya lo ratificó al firmar y seguir.")
        self.assertEqual(correr("sala.js", "textoTraspaso", {}, s), "Espera la ratificación del juez entrante.")
        self.assertEqual(correr("sala.js", "textoTraspaso", {"ratificado": {"min": 80}}, s), "Ratificado en el min 80.")


class NV4NV5NV6TextosDeLaBandeja(unittest.TestCase):
    js = (JS / "juez.js").read_text(encoding="utf-8")

    def test_nv4_lo_ratificado_se_muestra_aparte_sin_casilla(self):
        f = funcion(self.js, "pintarTraspaso")
        self.assertIn("herenciaTraspaso(t, b)", f)  # Ola D (NV7): con la bandeja
        self.assertIn("Ya ratificado al firmar y seguir", f)
        self.assertIn("Recibir el turno", f)

    def test_nv5_fuera_de_turno_no_pide_dejar_la_pantalla_abierta(self):
        self.assertIn("zonas.avisosBarra.hidden = !!b.reloj.finalizado || !(b.turno && b.turno.de_turno);", self.js)

    def test_nv6_partido_terminado_sin_botones_ni_aviso_pendiente(self):
        f = funcion(self.js, "pintarTraspaso")
        self.assertIn("'El partido terminó sin que se confirmara la recepción del turno.'", f)
        self.assertRegex(f, r"if \(fin\) \{\s*//[^\n]*\n\s*acciones = el\('p'")
        aviso = funcion(self.js, "construirAviso")
        self.assertIn("a.tipo === 'traspaso' && !a.atendido && !!b.reloj.finalizado", aviso)
        self.assertIn("MP.pideAccion(a) && !finSinRecibir", aviso)


class KitHoraRealConSegundos(unittest.TestCase):
    def test_la_simulada_da_la_hora_real_con_segundos(self):
        fuente = (RAIZ / "herramientas" / "api_simulada.py").read_text(encoding="utf-8")
        self.assertIn('hora_vence=self.hora(o["vence_min"]) if self.acelerar == 1 else (', fuente)

    @unittest.skipUnless(NODE, "sin node")
    def test_la_pagina_reconoce_las_dos_horas(self):
        d = {"texto_llano": "Se ordena a X bloquear la IP 203.0.113.10 hasta el minuto 105 del partido (hora 18:20:00). Vence.",
             "kit": [{"aplicar": 'comment="EXP-1 abcd1234 vence 04:56:12"', "nota": "vence a las 04:56:12."}]}
        self.assertEqual(correr("orden.js", "horasDeLaOrden", d), {"partido": "18:20:00", "real": "04:56:12"})
        # Sin kit o sin hora en el texto, no inventa nada.
        self.assertEqual(correr("orden.js", "horasDeLaOrden", {"texto_llano": "", "kit": []}), {"partido": None, "real": None})

    def test_la_nota_rotula_cada_hora(self):
        js = (JS / "orden.js").read_text(encoding="utf-8")
        f = funcion(js, "notaHoras")
        self.assertIn("h.partido.slice(0, 5) === h.real.slice(0, 5)", f)  # si coinciden, no hay nada que aclarar
        self.assertIn("es la hora del partido", f)
        self.assertIn("esa es la hora real, la del reloj de su equipo", f)
        self.assertIn("rige ? notaHoras(d) : null,", js)


class PropuestaRecalculadaAlResolverUnReclamo(unittest.TestCase):
    """Laura firma s1 por IP; s2 llega como pedido por IP; el reclamo de tienda.pelotaya.test (nombre solo inferido)
    se resuelve levantando y reemplazando: el pedido de s2 pasa a proponerse por dominio y lo dice."""

    @classmethod
    def setUpClass(cls):
        w = Reloj()
        w.hasta(1)
        w.m.firmar_marco(LAURA, False)
        w.hasta(3)
        cls.exp = w.m.expedientes[0]
        w.m.decidir(LAURA, cls.exp, cls.exp["ubicaciones"][0], True, "servidor", None, None)
        w.hasta(40)
        cls.antes = [(u["n"], u["estado"], u["propuesta"]["tipo"]) for u in cls.exp["ubicaciones"]]
        cls.r = next(x for x in w.m.reclamos if x["dominio"] == "tienda.pelotaya.test")
        w.m.resolver_reclamo(LAURA, cls.r, "levantar_y_reemplazar", None)
        cls.b = w.bandeja(LAURA)

    def test_el_pedido_pasa_de_ip_a_dominio_y_queda_anotado(self):
        self.assertIn((2, "pendiente", "ip"), self.antes)
        u = next(x for p in self.b["pendientes"] for x in p["expediente"]["ubicaciones"] if x["n"] == 2)
        self.assertEqual(u["propuesta"]["tipo"], "dominio")
        rc = u.get("recalculada")
        self.assertEqual(rc, {"reclamo": self.r["id"], "registrable": "pelotaya.test", "min": 40.0,
                              "tipo_antes": "ip", "tipo": "dominio"})
        self.assertNotIn("Bloqueo por IP", u["propuesta"]["fundamento"])
        aprobada = next(x for x in self.exp["ubicaciones"] if x["n"] == 1)
        self.assertNotIn("recalculada", aprobada, "solo cambia lo que espera firma")

    @unittest.skipUnless(NODE, "sin node")
    def test_la_tarjeta_lo_dice(self):
        u = next(x for x in self.exp["ubicaciones"] if x["n"] == 2)
        self.assertEqual(correr("juez.js", "textoRecalculada", u["recalculada"]),
                         "La propuesta cambió en el minuto 40 al resolverse el reclamo %s: antes proponía bloquear "
                         "por IP; ahora, por dominio." % self.r["id"])
        self.assertIsNone(correr("juez.js", "textoRecalculada", None))  # tolera que el campo no venga

    def test_la_tarjeta_del_pedido_lo_muestra(self):
        f = funcion((JS / "juez.js").read_text(encoding="utf-8"), "construirPedido")
        self.assertIn("textoRecalculada(u.recalculada)", f)


class SalaEnEsperaNoEsEnviado(unittest.TestCase):
    """Ola C (7): la orden que espera al juez entrante todavía no salió; la sala no dice «enviado»."""

    @unittest.skipUnless(NODE, "sin node")
    def test_lampara_y_texto(self):
        js = (JS / "sala.js").read_text(encoding="utf-8")
        self.assertEqual(correr("sala.js", "estadoLampara", {"estado": "espera_ratificacion"}), "espera")
        self.assertEqual(correr("sala.js", "estadoLampara", {"estado": "recibida"}), "recibida")
        self.assertIn("espera: 'En espera: sale cuando el juez entrante reciba el turno.'", js)
        self.assertIn(".lampara--espera", (RAIZ / "marca" / "web" / "static" / "css" / "pizarra.css").read_text(encoding="utf-8"))


@unittest.skipUnless(NODE, "sin node")
class CartelDelTurnoConUnidad(unittest.TestCase):
    """Ola C (8): «faltan N min»; en el último minuto, «falta menos de 1 min» (nunca «faltan 0»)."""

    def test_textos(self):
        self.assertEqual(correr("juez.js", "faltanTxt", 0), "falta menos de 1 min")
        self.assertEqual(correr("juez.js", "faltanTxt", 1), "falta 1 min")
        self.assertEqual(correr("juez.js", "faltanTxt", 12), "faltan 12 min")
        js = (JS / "juez.js").read_text(encoding="utf-8")
        self.assertNotIn("' (faltan ' + faltan + ')'", js)
        self.assertEqual(js.count("' (' + faltanTxt(faltan) + ')'"), 2)


class FirmaEnLosUltimosSegundos(unittest.TestCase):
    """Ola C (9, simplificado): solo la respuesta de aprobar trae el aviso; la bandeja ya lo muestra (r.aviso)."""

    def test_la_simulada_avisa_al_aprobar_en_los_ultimos_segundos(self):
        self.assertEqual(A.TEXTO_FUERA_DE_PLAZO, "Faltan segundos para el final del partido: la firma queda registrada, "
                                                 "pero la orden ya no llega a los proveedores y no bloquea.")
        fuente = (RAIZ / "herramientas" / "api_simulada.py").read_text(encoding="utf-8")
        self.assertIn('if PARTIDO["fin_min"] - ahora < FUERA_DE_PLAZO_MIN:\n                    aviso_r = TEXTO_FUERA_DE_PLAZO', fuente)
        w = Reloj()
        w.hasta(1)
        w.m.firmar_marco(LAURA, False)
        w.hasta(10)
        exp = w.m.expedientes[0]
        u = next(x for x in exp["ubicaciones"] if x["estado"] == "pendiente")
        self.assertNotIn("fuera_de_plazo", w.m.vista_ubicacion(exp, u, A.PARTIDO["fin_min"] - 0.2))

    def test_la_bandeja_muestra_el_aviso_de_la_respuesta(self):
        js = (JS / "juez.js").read_text(encoding="utf-8")
        self.assertIn("if (r && r.aviso) MP.avisar(r.aviso, 'alerta', 15);", js)
        self.assertNotIn("fuera_de_plazo", js)

class NV1ReemplazoDecididoAlResolverElReclamo(unittest.TestCase):
    """La orden de reemplazo la ordenó la resolución del reclamo: minuto, origen y reclamo son los de esa resolución
    (como `_decision_publica` del motor), no los de la firma original de la ubicación."""

    @classmethod
    def setUpClass(cls):
        w = Reloj()
        w.hasta(1)
        w.m.firmar_marco(LAURA, False)
        w.hasta(3)
        exp = w.m.expedientes[0]
        w.m.decidir(LAURA, exp, exp["ubicaciones"][0], True, "servidor", None, None)
        cls.firma_min = exp["ubicaciones"][0]["decision"]["min"]
        w.hasta(40)
        cls.r = next(x for x in w.m.reclamos if x["dominio"] == "tienda.pelotaya.test")
        w.m.resolver_reclamo(LAURA, cls.r, "levantar_y_reemplazar", None)
        cls.w = w
        cls.reemplazo = next(o for o in w.m.ordenes if o["origen"] == "reemplazo_reclamo")
        cls.comun = next(o for o in w.m.ordenes if o["origen"] != "reemplazo_reclamo")

    def test_la_orden_publica_del_reemplazo(self):
        with self.w.m.cond:
            d = self.w.m.orden_publica(self.reemplazo["orden_id"])
        self.assertEqual(d["decision_origen"], "reclamo")
        self.assertEqual(d["reclamo"], self.r["id"])
        self.assertEqual(d["decision_min"], self.r["resolucion"]["min"])
        self.assertNotEqual(d["decision_min"], self.firma_min)
        self.assertEqual(d["decision"]["tipo"], "resolucion_reclamo")
        self.assertTrue(d["decision"]["texto"].startswith("Decidida por Dra. Laura Ficticia al resolver el reclamo %s, en el minuto "
                                                          % self.r["id"]))
        self.assertEqual(d["decision"]["entrada"], self.r["resolucion"]["entrada"])

    def test_una_orden_comun_sigue_como_antes(self):
        with self.w.m.cond:
            d = self.w.m.orden_publica(self.comun["orden_id"])
        self.assertEqual(d["decision_origen"], "ubicacion")
        self.assertIsNone(d["reclamo"])
        self.assertEqual(d["decision_min"], self.firma_min)

    def test_el_registro_publico(self):
        with self.w.m.cond:
            b = self.w.m.bloqueo_publico(self.reemplazo)
        self.assertEqual((b["decision_origen"], b["reclamo"], b["decision_tipo"], b["decision_min"]),
                         ("reclamo", self.r["id"], "resolucion_reclamo", self.r["resolucion"]["min"]))
        self.assertIn("al resolver el reclamo", b["decision_texto"])

    @unittest.skipUnless(NODE, "sin node")
    def test_transparencia_dice_decidida_al_resolver_el_reclamo(self):
        self.assertEqual(correr("transparencia.js", "textoDecision",
                                {"decision_origen": "reclamo", "reclamo": "R-001", "decision_min": 16.7}),
                         "decidida al resolver el reclamo R-001 en el min 16,7")
        # Sin el campo (motor anterior), como hoy.
        self.assertEqual(correr("transparencia.js", "textoDecision", {"decision_min": 10.3}), "firmó en el min 10,3")

    def test_orden_rotula_la_decision_y_el_sello(self):
        js = (JS / "orden.js").read_text(encoding="utf-8")
        self.assertIn("const porReclamo = !ampl && d.decision_origen === 'reclamo' && !!d.reclamo;", js)
        self.assertIn("porReclamo ? 'Decidida al resolver el reclamo ' + d.reclamo + ' · ' : null", js)
        self.assertIn("pie: (porReclamo ? 'Reclamo ' + d.reclamo + ' · ' : '') + MP.min(d.decision_min)", js)


class OrdenNoEnviadaAlFinal(unittest.TestCase):
    """Ola C (parte 6): firmada en los últimos segundos, la orden nunca sale; ninguna pantalla dice «enviado» ni
    «Bloqueado» ni «Venció con el partido» de algo que nunca bloqueó."""

    @classmethod
    def setUpClass(cls):
        w = Reloj()
        w.hasta(1)
        w.m.firmar_marco(LAURA, False)
        w.hasta(10)
        cls.exp = w.m.expedientes[0]
        cls.u = next(x for x in cls.exp["ubicaciones"] if x["estado"] == "pendiente")
        w.r["m"] = A.PARTIDO["fin_min"] - 0.2  # salto del reloj: firma en los últimos segundos, ya de turno Martín
        w.m.firmar_marco(MARTIN, False)
        w.m.decidir(MARTIN, cls.exp, cls.u, True, "servidor", None, None)
        cls.w = w
        cls.ordenes = [A.Mundo.vista_orden(o) for o in w.m.ordenes_de(cls.exp["id"], cls.u["n"])]

    def test_la_simulada_la_marca_no_enviada(self):
        self.assertTrue(self.ordenes)
        self.assertTrue(all(o["no_enviada"] and o["estado"] == "por_enviar" for o in self.ordenes))
        self.assertIs(A.Mundo.vista_orden({"estado": "recibida"})["no_enviada"], False)  # las que salieron, como antes

    @unittest.skipUnless(NODE, "sin node")
    def test_lampara_y_rotulos(self):
        p = {"estado": "por_enviar", "ref": self.ordenes[0], "ordenes": self.ordenes[:1]}
        self.assertEqual(correr("sala.js", "estadoLampara", p), "no_enviada")
        sin = dict(self.ordenes[0]); sin.pop("no_enviada")
        self.assertEqual(correr("sala.js", "estadoLampara", {"estado": "por_enviar", "ref": sin, "ordenes": [sin]}), "recibida")
        js = (JS / "sala.js").read_text(encoding="utf-8")
        self.assertIn("no_enviada: 'No enviada'", js)  # Ola D: el título lo da la causa (test_r5_pantallas)
        self.assertIn("item('no_enviada', 'No enviada o sin confirmar')", js)
        comun = (JS / "comun.js").read_text(encoding="utf-8")
        self.assertIn("final: { rotulo: 'No enviada', texto: 'Sin bloquear: la firma llegó cuando el partido terminaba.' }", comun)
        self.assertIn("no_enviada: { texto: 'No enviada'", comun)
        self.assertIn("MP.estadoOrden(MP.noEnviada(o) ? (MP.causaNoEnviada(o).clave === 'confirmar' ? 'sin_confirmar' : 'no_enviada') : o.estado)", (JS / "juez.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
