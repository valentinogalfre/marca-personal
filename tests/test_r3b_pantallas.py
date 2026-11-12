"""Contratos de pantallas, ronda 3 tanda B (W): C15/textos-2, C17, turnos-2 y C14.

- C15: la API simulada copia, palabra por palabra, los renglones 3 y 4 de la orden marco y las condiciones [0] y [1].
- textos-2: con los dos botones de firma a la vista, la tarjeta dice qué alcanza cada uno.
- C17: solo la bandeja del juez manda `de=juez` en la espera larga; las páginas públicas nunca.
- turnos-2: levantar o frenar no deja sin bloqueo a otra ubicación firmada que lo necesita, y la pantalla lo avisa.
- C14: el reclamo de un nombre solo inferido es legítimo (`verificacion.inferido`); el de un nombre observado, no.

Las pruebas de JS corren el código real con node (se saltean sin node). La API simulada se conduce con un reloj
controlado, sin servidor.
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


def cargar_simulada():
    spec = importlib.util.spec_from_file_location("api_simulada_r3b", RAIZ / "herramientas" / "api_simulada.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


A = cargar_simulada()
LAURA = "jueza-laura-ficticia"


def mundo_hasta(minuto):
    m = A.Mundo(6.0, -3.3, True, True)
    reloj = {"m": -3.3}
    m.minuto = lambda: reloj["m"]
    while reloj["m"] < minuto:
        reloj["m"] = round(reloj["m"] + 0.05, 4)
        m.tick()
    return m


class C15TextosDeLaOrdenMarco(unittest.TestCase):
    def test_renglones_y_condiciones_como_el_contrato(self):
        m = A.Mundo(6.0, 0.0, False, True)
        c = m.contenido_marco(LAURA, True)
        self.assertTrue(c["lineas"][2].startswith(
            "Solo se protege la señal del partido: la oficial (LP26-PRA-OFI) y la de cada licenciatario cuando se "
            "transmite fuera de sus dominios (LP26-PRA-LIC-NORTE). Nunca se bloquea a un licenciatario en sus dominios: "))
        self.assertEqual(c["lineas"][3],
                         "Cada bloqueo necesita un expediente con evidencia sellada (la captura con su hash, la marca "
                         "verificada y el servidor con host, IP y red) y mi firma, servidor por servidor, salvo que en "
                         "esta orden autorice el seguimiento de la misma filtración.")
        # Renglón 4: texto fijo, no depende de la casilla.
        self.assertEqual(m.contenido_marco(LAURA, False)["lineas"][3], c["lineas"][3])
        self.assertEqual(A.CONDICIONES_SEGUIMIENTO[0],
                         "Si firmo un bloqueo con «Firmar y seguir a esta filtración» y esa misma filtración (la misma "
                         "sesión de la marca de agua) aparece en otro servidor, la plataforma amplía el bloqueo sin "
                         "esperar una firma nueva, solo si se cumple todo esto:")
        self.assertEqual(A.CONDICIONES_SEGUIMIENTO[1],
                         "La evidencia nueva está completa y sellada, y el bloqueo nuevo no alcanza a sitios ajenos: si "
                         "el servidor nuevo comparte la IP con sitios ajenos, se bloquea solo el nombre del stream.")


class Textos2LineaDeLosDosBotones(unittest.TestCase):
    def test_la_tarjeta_explica_los_dos_botones(self):
        js = (JS / "juez.js").read_text(encoding="utf-8")
        i = js.index("const seguir = puedeSeguir && seguimientoAutorizado(b)")
        bloque = js[i:js.index("const error = ", i)]
        m = re.search(r"else\s+nota\s*=\s*(.+?);\n", bloque, re.S)
        self.assertIsNotNone(m, "Con los dos botones a la vista no hay ninguna línea que explique la diferencia.")
        texto = m.group(1)
        for parte in ("“Firmar y seguir”", "exp.filtracion.sesion", "sin pedirle otra firma",
                      "hasta el final del partido", "puede frenarlo", "“Solo este servidor”", "llega un pedido nuevo"):
            self.assertIn(parte, texto)
        self.assertIn("nota ? el('p', { class: 'ayuda acciones__nota', text: nota }) : null", js)

    def test_textos3_nota_de_ratificacion_con_seguimiento_heredado(self):
        js = (JS / "juez.js").read_text(encoding="utf-8")
        i = js.index("const seguir = puedeSeguir && seguimientoAutorizado(b)")
        bloque = js[i:js.index("const error = ", i)]
        self.assertIn("d.exp === exp.id && d.requiere_ratificacion", bloque)
        self.assertIn("Firmar y seguir también ratifica el seguimiento heredado.", bloque)


VIGILAR = r"""
const fs = require('fs'); const vm = require('vm');
const ctx = { window: {}, document: { addEventListener() {}, querySelector() { return null; }, createElement() { return {}; },
  visibilityState: 'visible', title: '', body: { appendChild() {} } }, Node: function () {}, navigator: {}, console,
  setTimeout, clearTimeout, setInterval: () => 0, clearInterval() {}, location: { pathname: '/', search: '' },
  fetch: () => Promise.reject(new Error('sin red')), localStorage: { getItem() { return null; }, setItem() {} },
  sessionStorage: { getItem() { return null; }, setItem() {} }, performance: { now: () => 0 }, Intl, Date, Math, JSON,
  Number, String, AbortController };
ctx.window = ctx; ctx.globalThis = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), ctx);
const MP = ctx.MP;
const rutas = [];
MP.api = (metodo, ruta) => { rutas.push(ruta); return new Promise(() => {}); };  // la espera larga nunca vuelve
MP.conexion = () => {}; MP.ajustarMinuto = () => {};
const opc = JSON.parse(process.argv[2]);
MP.vigilar(Object.assign({ cargar: async () => ({ v: 7 }) }, opc));
setTimeout(() => console.log(JSON.stringify(rutas)), 50);
"""


@unittest.skipUnless(NODE, "sin node: no se puede correr el JS")
class C17PresenciaSoloDesdeLaBandeja(unittest.TestCase):
    def espera(self, opc):
        r = subprocess.run([NODE, "-e", VIGILAR, str(JS / "comun.js"), json.dumps(opc)],
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_vigilar_con_de_lo_agrega_y_sin_de_no(self):
        self.assertEqual(self.espera({"de": "juez"}), ["/api/cambios?v=7&de=juez"])
        self.assertEqual(self.espera({}), ["/api/cambios?v=7"])

    def test_solo_juez_js_pasa_de_juez(self):
        def llamada(nombre):
            js = (JS / nombre).read_text(encoding="utf-8")
            i = js.index("MP.vigilar({")
            return js[i:js.index("});", i)]
        self.assertIn("de: 'juez'", llamada("juez.js"))
        for publica in ("sala.js", "transparencia.js", "orden.js"):
            with self.subTest(pagina=publica):
                self.assertNotRegex(llamada(publica), r"\bde\s*:")


class Pantallas3RiesgoEnLaOrdenPublica(unittest.TestCase):
    def test_cada_riesgo_del_motor_tiene_color_propio(self):
        js = (JS / "orden.js").read_text(encoding="utf-8")
        i = js.index("  function riesgo(")
        bloque = js[i:js.index("\n  }\n", i)]
        self.assertIn("nulo: ['ok',", bloque)
        self.assertIn("desconocido: ['neutro', 'Sin datos']", bloque)


class Turnos2NoSeLevantaLoQueOtraUbicacionNecesita(unittest.TestCase):
    def armar(self):
        m = A.Mundo(6.0, 10.0, False, True)
        m.minuto = lambda: 10.0
        juez = LAURA
        cubierto = {"proveedor": "aurora", "tipo": "ip", "objetivo": "203.0.113.10"}
        m.expedientes = [{"id": "EXP-1", "ubicaciones": [
            {"n": 1, "estado": "aprobada", "decision": {"juez": "Dra. A", "ya_cubiertos": []}},
            {"n": 2, "estado": "aprobada", "decision": {"juez": "Dra. B", "ya_cubiertos": [cubierto]}}]}]
        base = {"proveedor_nombre": "Aurora", "estado": "aplicada", "_exp": "EXP-1", "_n": 1, "orden_id": "o-1"}
        compartida = dict(base, **cubierto)
        propia = dict(base, proveedor="andina", tipo="dominio", objetivo="s1.pelotaya.test", orden_id="o-2")
        m.ordenes = [compartida, propia]
        return m, juez, compartida, propia

    def test_levantar_mantiene_la_que_cubre_a_otra_y_avisa(self):
        m, juez, compartida, propia = self.armar()
        hechas, avisos = m.levantar_salvo_necesarias([compartida, propia], {("EXP-1", 1)}, juez, "prueba", 10.0)
        self.assertEqual(hechas, 1)
        self.assertEqual(compartida["estado"], "aplicada", "la ubicación 2 quedaría sin bloqueo")
        self.assertEqual(propia["estado"], "levantada")
        self.assertEqual(len(avisos), 1)
        self.assertTrue(avisos[0].startswith("Se mantiene el bloqueo por IP 203.0.113.10 en Aurora"), avisos[0])
        self.assertIn("EXP-1 ubicación 2 (Dra. B)", avisos[0])

    def test_si_las_dos_se_levantan_juntas_no_hay_aviso(self):
        m, juez, compartida, propia = self.armar()
        hechas, avisos = m.levantar_salvo_necesarias([compartida], {("EXP-1", 1), ("EXP-1", 2)}, juez, "x", 10.0)
        self.assertEqual((hechas, avisos), (1, []))


ACCION = r"""
const vm = require('node:vm');
const fuente = process.argv[1];
const avisos = [];
const ctx = {
  est: { ocupado: new Set(), formas: new Map(), bandeja: null, vig: { refrescar() {}, adoptar() {} } },
  MP: { api: async () => JSON.parse(process.argv[2]), avisar: (t, tipo) => avisos.push([t, tipo]) },
  mostrarIngreso: () => {}, pintar: () => {},
};
ctx.forma = (k, ini) => { if (!ctx.est.formas.has(k)) ctx.est.formas.set(k, Object.assign({ error: '' }, ini || {})); return ctx.est.formas.get(k); };
vm.createContext(ctx);
vm.runInContext(fuente + '\nthis.accion = accion;', ctx);
ctx.accion('l:EXP-1/U1', '/api/juez/ubicaciones/EXP-1/1/levantar', { motivo: 'ya no transmite' }, 'Bloqueo levantado.')
  .then(() => console.log(JSON.stringify(avisos)));
"""


@unittest.skipUnless(NODE, "sin node: no se puede correr el JS")
class Turnos2LaBandejaMuestraElAviso(unittest.TestCase):
    def correr(self, respuesta):
        js = (JS / "juez.js").read_text(encoding="utf-8")
        fuente = re.search(r"\n  async function accion\(k, ruta, cuerpo, exito\) \{\n.*?\n  \}\n", js, re.S).group(0)
        r = subprocess.run([NODE, "-e", ACCION, fuente, json.dumps(respuesta)], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_con_aviso_se_muestra_como_alerta(self):
        aviso = "Se mantiene el bloqueo por IP 203.0.113.10 en Aurora porque también cubre EXP-1 ubicación 2 (Dra. B)."
        self.assertEqual(self.correr({"ok": True, "aviso": aviso}), [[aviso, "alerta"]])

    def test_sin_aviso_dice_lo_que_se_hizo(self):
        self.assertEqual(self.correr({"ok": True}), [["Bloqueo levantado.", "ok"]])


class C14ReclamoDeUnNombreInferido(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = mundo_hasta(30)

    def reclamo(self, dominio):
        r = next((x for x in self.m.reclamos if x["dominio"] == dominio), None)
        self.assertIsNotNone(r, "la API simulada no generó el reclamo de " + dominio)
        return r

    def test_inferido_es_legitimo_y_lo_dice(self):
        r = self.reclamo("tienda.pelotaya.test")
        v = r["verificacion"]
        self.assertEqual(v["clase_reclamante"], "legitimo")
        self.assertIs(v.get("inferido"), True)
        self.assertEqual(v["explicacion"],
                         "La plataforma lo había tomado como parte del sitio pirata porque comparte el servidor y el "
                         "dominio pelotaya.test, pero nunca lo vio transmitir ni publicar el partido. El reclamo "
                         "corrige esa inferencia.")
        self.assertEqual(r["propuesta"]["accion"], "levantar_y_reemplazar")

    def test_observado_se_desestima(self):
        r = self.reclamo("verpartido-hd.test")
        v = r["verificacion"]
        self.assertEqual(v["clase_reclamante"], "operacion_pirata")
        self.assertNotIn("inferido", v)
        self.assertRegex(v["explicacion"], r"^Es el mismo nombre que la plataforma vio (transmitiendo|publicando) el "
                                           r"partido en el minuto [0-9,]+: el reclamo no es fundado\.$")
        self.assertEqual(r["propuesta"]["accion"], "desestimar")

    def test_la_tarjeta_muestra_la_explicacion_tal_cual_y_no_dice_sin_relacion(self):
        js = (JS / "juez.js").read_text(encoding="utf-8")
        i = js.index("  function construirReclamo(")
        bloque = js[i:js.index("\n  }\n", i)]
        self.assertIn("el('p', { text: v.explicacion || '' })", bloque)
        self.assertIn("v.inferido", bloque)


TARJETA = r"""
const fs = require('fs');
const js = fs.readFileSync(process.argv[1], 'utf8');
const corte = (desde, hasta) => { const i = js.indexOf(desde), f = js.indexOf(hasta, i + 1); if (i < 0 || f < 0) throw new Error(desde); return js.slice(i, f); };
const MP = { min: (x) => 'min ' + String(x).replace('.', ',') };
const pendientesDe = (b) => b.pendientes || [];
const f = new Function('MP', 'pendientesDe', corte('  function lineaMismoStream(', '  function construirPedido(') +
  corte('  function pedidosPrimero(', '  function ordenarSecciones(') +
  '\nreturn { lineaMismoStream, textoSuperada, pedidosPrimero, lineaPedidosArriba };')(MP, pendientesDe);
const b = (n, firmada, deTurno) => ({ turno: { de_turno: deTurno }, reloj: {}, marco: { firmada }, pendientes: Array(n).fill({}) });
console.log(JSON.stringify({
  aprobada: f.lineaMismoStream({ estado: 'aprobada' }, 1, 2),
  pendiente: f.lineaMismoStream({ estado: 'pendiente' }, 1, 2),
  rechazada: f.lineaMismoStream({ estado: 'rechazada' }, 1, 2),
  superada: f.textoSuperada({ ultima_deteccion_min: 21.5 }, 3),
  arriba: [f.pedidosPrimero(b(2, null, true)), f.pedidosPrimero(b(0, null, true)), f.pedidosPrimero(b(2, { min: 1 }, true)),
           f.pedidosPrimero(b(2, null, false))],
  linea1: f.lineaPedidosArriba(1), linea3: f.lineaPedidosArriba(3),
}));
"""


@unittest.skipUnless(NODE, "sin node: no se puede correr el JS")
class Humano34TarjetasDelJuez(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run([NODE, "-e", TARJETA, str(JS / "juez.js")], capture_output=True, text=True, timeout=30)
        if r.returncode:
            raise AssertionError(r.stderr)
        cls.o = json.loads(r.stdout.strip().splitlines()[-1])

    def test_c24_ya_bloqueo_solo_si_la_anterior_esta_aprobada(self):
        self.assertEqual(self.o["aprobada"], "Mismo stream que ya bloqueó: ubicación 1 → 2")
        self.assertEqual(self.o["pendiente"], "Mismo stream que la ubicación 1 (todavía sin decidir)")
        self.assertEqual(self.o["rechazada"], "Mismo stream que la ubicación 1 (rechazada)")

    def test_c24_superada(self):
        self.assertEqual(self.o["superada"], "Este servidor no se ve desde el min 21,5. La misma filtración apareció "
                                             "después en otro servidor (ubicación 3), que está más arriba.")

    def test_humano4_pedidos_arriba_solo_sin_orden_marco_y_con_pedidos(self):
        self.assertEqual(self.o["arriba"], [2, 0, 0, 0])
        self.assertEqual(self.o["linea1"], "Tiene 1 pedido esperando. Su orden marco está más abajo.")
        self.assertEqual(self.o["linea3"], "Tiene 3 pedidos esperando. Su orden marco está más abajo.")

    def test_c22_el_rechazo_previo_no_se_toma_como_seguimiento_frenado(self):
        js = (JS / "juez.js").read_text(encoding="utf-8")
        self.assertIn("const porRechazo = mismoServidor && (!!u.rechazo_previo", js)
        self.assertIn("const seguir = puedeSeguir && seguimientoAutorizado(b) && !frenado;", js)

    def test_c26_la_hora_del_vencimiento_la_da_el_motor(self):
        js = (JS / "juez.js").read_text(encoding="utf-8")
        self.assertIn("const hora = prop.vence_hora ? String(prop.vence_hora).slice(0, 5) : MP.horaCorta(vence);", js)


class Humano13EnLaApiSimulada(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        m = A.Mundo(6.0, -3.3, False, True)
        reloj = {"m": -3.3}
        m.minuto = lambda: reloj["m"]

        def hasta(x):
            while reloj["m"] < x:
                reloj["m"] = round(reloj["m"] + 0.05, 4)
                m.tick()
        hasta(5)
        cls.exp = m.expedientes[0]
        m.decidir(LAURA, cls.exp, cls.exp["ubicaciones"][0], False, "ubicacion", None, "La evidencia no alcanza.")
        hasta(13)
        cls.u2 = cls.exp["ubicaciones"][1]
        hasta(40)
        with m.cond:
            cls.b = m.bandeja("laura")
        cls.m = m

    def test_c22_lo_visto_despues_del_rechazo_vuelve_como_pedido_con_la_nota(self):
        u2 = self.u2
        self.assertEqual((u2["host"], u2["estado"]), (self.exp["ubicaciones"][0]["host"], "pendiente"))
        self.assertEqual(u2["continuidad"]["criterio"], "mismo_servidor")
        self.assertEqual(u2["continuidad"]["nota"], "Mismo servidor: usted rechazó este pedido en el minuto 5,0; la "
                                                    "plataforma lo volvió a ver transmitiendo en el minuto 12,0.")
        self.assertEqual(u2["rechazo_previo"]["ref"], self.exp["ubicaciones"][0]["ref"])
        self.assertFalse(u2["_automatica"]["posible"])

    def test_c24_superada_por_y_al_final(self):
        sup = [(p["expediente"]["id"], p["n"], p["superada_por"]) for p in self.b["pendientes"]]
        self.assertIn((self.exp["id"], 2, 3), sup)
        vistos = [x[2] is not None for x in sup]
        self.assertEqual(vistos, sorted(vistos), "los superados van después de los demás")

    def test_c26_vence_hora_en_la_propuesta(self):
        self.assertEqual(self.u2["propuesta"]["vence_hora"], self.m.hora(self.u2["propuesta"]["vence_min"]))


if __name__ == "__main__":
    unittest.main()
