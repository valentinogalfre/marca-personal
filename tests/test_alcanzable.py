"""Tests de herramientas/alcanzable.py (oraculo de lo alcanzable).

Contratos que protegen (cada prueba nombra el suyo):
  A1  Una fase de duracion cero no es evaluable: no cuenta ni como bloqueada ni como defecto.
  A2  Una fase mas corta que la demora minima de un proveedor es "imposible" para el, nunca defecto.
  A3  Una fase larga que un proveedor sin fallas no cubrio es un DEFECTO (codigo 1).
  A4  Las fallas observadas de ESE proveedor sobre ESA fase corren el limite (y las de otro objetivo,
      o anteriores a la fase, no).
  A5  Un proveedor que solo bloquea por dominio igual alcanza (el host de la fase cuenta para el
      verificador), y sus ordenes por IP no cuentan como fallas suyas; sin ninguna capacidad util es
      imposible.
  A6  Limites exactos: imposible si desde + 0,7 x demora >= hasta; seguro solo si
      desde + margen + 1,3 x demora x (1 + fallas) < hasta (estricto); --margen-min se respeta.
  A7  Datos mal formados o que no corresponden entre si -> codigo 2, sin veredicto.
  A8  --json es un objeto legible por otro programa con el veredicto, las fases y los defectos.
Deterministas, sin red y sin esperas: los archivos se arman en carpetas temporales.
"""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SCRIPT = RAIZ / "herramientas" / "alcanzable.py"

_spec = importlib.util.spec_from_file_location("alcanzable", SCRIPT)
al = importlib.util.module_from_spec(_spec)
sys.modules["alcanzable"] = al
_spec.loader.exec_module(al)

# Los cuatro proveedores del desafio (datos/proveedores.json) y uno "lento" con demora 5,0, cuyos
# limites (0,7 x 5 = 3,5 y 1,3 x 5 = 6,5) son exactos en binario para probar los bordes de la regla.
PROVEEDORES = {"proveedores": [
    {"id": "aurora", "clientes": 3800000, "capacidades": ["ip", "dominio"], "comportamiento": {"demora_min": 0.5, "tasa_falla": 0.0}},
    {"id": "andina", "clientes": 1200000, "capacidades": ["ip", "dominio"], "comportamiento": {"demora_min": 2.0, "tasa_falla": 0.0}},
    {"id": "valle", "clientes": 140000, "capacidades": ["dominio"], "comportamiento": {"demora_min": 6.0, "tasa_falla": 0.0}},
    {"id": "cumbre", "clientes": 60000, "capacidades": ["ip", "dominio"], "comportamiento": {"demora_min": 3.0, "tasa_falla": 0.35}},
]}
LENTO = {"proveedores": [
    {"id": "lento", "clientes": 1, "capacidades": ["ip", "dominio"], "comportamiento": {"demora_min": 5.0, "tasa_falla": 0.0}}]}
IP, HOST = "203.0.113.5", "b1.pirata.test"


class Ensayo:
    """Arma verdad + registro + resultado del verificador coherentes entre si.

    fases: lista de (desde, hasta, cubren) donde cubren = {proveedor: (tipo, minuto_aplicada)}.
    extra: ordenes que fallaron, (proveedor, tipo, objetivo, recibida, minuto_falla).
    """

    def __init__(self, fases, extra=(), log_fin=110.0, escenario="t-1", rec="ip"):
        # Cada fase en su propio servidor (la fase 1 en IP / HOST), como una mudanza.
        srv = [(IP, HOST) if k == 1 else ("203.0.113.%d" % (100 + k), "b%d.pirata.test" % k)
               for k in range(1, len(fases) + 1)]
        self.verdad = {"escenario_id": escenario, "fin_min": 105, "gracia_min": 5,
                       "dominios_piratas": [h for _, h in srv],
                       "streams": [{"id": "s", "clase": "pirata", "fases": [
                           {"host": host, "ip": ip, "desde_min": d, "hasta_min": h, "bloqueo_recomendado": rec,
                            "detecciones": []} for (d, h, _), (ip, host) in zip(fases, srv)]},
                           {"id": "fp", "clase": "falso_positivo", "fases": [
                               {"host": "vod.otro.test", "ip": "192.0.2.9", "desde_min": 5.0, "hasta_min": 9.0,
                                "bloqueo_recomendado": None, "detecciones": []}]}]}
        ev = [{"min": 0.0, "evento": "simulacion_iniciada", "escenario": escenario}]
        fases_v = []
        n = 0
        for k, (d, h, cubren) in enumerate(fases, start=1):
            ip, host = srv[k - 1]
            for prov, (tipo, aplicada) in sorted(cubren.items()):
                n += 1
                obj = ip if tipo == "ip" else host
                ev.append({"min": min(d, aplicada), "evento": "orden_recibida", "proveedor": prov, "orden_id": f"o{n}",
                           "tipo": tipo, "objetivo": obj, "juez_id": "j", "juez_de_turno": True})
                ev.append({"min": aplicada, "evento": "orden_aplicada", "proveedor": prov, "orden_id": f"o{n}",
                           "tipo": tipo, "objetivo": obj})
                ev.append({"min": 109.0, "evento": "orden_vencida", "proveedor": prov, "orden_id": f"o{n}"})
            if d >= log_fin:
                continue
            fases_v.append({"stream": "s", "fase": k, "ip": ip, "host": host, "desde_min": d, "hasta_min": h,
                            "bloqueo_recomendado": rec,
                            "primer_bloqueo_min": round(min(a for _, a in cubren.values()) - d, 2) if cubren else None,
                            "proveedores_que_bloquearon": sorted(cubren), "clientes_cubiertos_pct": 0.0,
                            "visibilidad_residual_pct": 0.0})
        for prov, tipo, obj, recibida, falla in extra:
            n += 1
            ev.append({"min": recibida, "evento": "orden_recibida", "proveedor": prov, "orden_id": f"o{n}",
                       "tipo": tipo, "objetivo": obj, "juez_id": "j", "juez_de_turno": True})
            ev.append({"min": falla, "evento": "orden_fallida", "proveedor": prov, "orden_id": f"o{n}", "motivo": "x"})
        ev.append({"min": log_fin, "evento": "ventana_cerrada"})
        self.registro = ev
        self.verificador = {"escenario": escenario, "log_hasta_min": log_fin, "fases": fases_v,
                            "resumen": {"bloqueos_con_dano_colateral": 0, "bloqueos_falsos_positivos": 0,
                                        "ordenes_firmadas_fuera_de_turno": 0}}

    def evaluar(self, proveedores=PROVEEDORES, margen=1.0):
        return al.evaluar(self.verdad, proveedores, self.verificador, sorted(self.registro, key=lambda e: e["min"]),
                          margen)

    def escribir(self, carpeta, proveedores=PROVEEDORES):
        c = Path(carpeta)
        (c / "verdad.json").write_text(json.dumps(self.verdad), encoding="utf-8")
        (c / "proveedores.json").write_text(json.dumps(proveedores), encoding="utf-8")
        (c / "verificador.json").write_text(json.dumps(self.verificador), encoding="utf-8")
        (c / "registro.jsonl").write_text("".join(json.dumps(e) + "\n" for e in self.registro), encoding="utf-8")
        return c


def todos(t0):
    """Los cuatro proveedores cubren, por dominio valle y por IP el resto, con demoras realistas."""
    return {"aurora": ("ip", t0 + 0.8), "andina": ("ip", t0 + 2.5), "valle": ("dominio", t0 + 6.5),
            "cumbre": ("ip", t0 + 3.5)}


def clase(r, fase, proveedor):
    f = next(x for x in r["fases"] if x["fase"] == fase)
    return next(p for p in f["proveedores"] if p["proveedor"] == proveedor)


def correr_cli(carpeta, *extra):
    c = Path(carpeta)
    return subprocess.run([sys.executable, "-I", str(SCRIPT), "--verdad", str(c / "verdad.json"),
                           "--proveedores", str(c / "proveedores.json"), "--verificador", str(c / "verificador.json"),
                           "--registro", str(c / "registro.jsonl"), *extra], capture_output=True, text=True)


class TestFisica(unittest.TestCase):
    def test_A1_fase_de_duracion_cero_no_es_evaluable(self):
        """CONTRATO A1: hasta <= desde -> no evaluable; ni bloqueada ni defecto; el veredicto no cambia."""
        e = Ensayo([(10.0, 60.0, todos(10.0)), (105.0, 105.0, {})])
        r = e.evaluar()
        cero = r["fases"][1]
        self.assertFalse(cero["evaluable"])
        self.assertIn("duracion cero", cero["motivo"])
        self.assertEqual(cero["proveedores"], [])
        self.assertEqual(r["veredicto"], "sin defectos")
        self.assertEqual(r["resumen"]["no_evaluables"], 1)

    def test_A2_fase_mas_corta_que_la_demora_minima_es_imposible_no_defecto(self):
        """CONTRATO A2: fase de 1 min (40-41): andina (>= 1,4), cumbre (>= 2,1) y valle (>= 4,2) no
        pueden; si solo aurora la cubre, no hay defecto. Y una de 0,3 min sin nadie tampoco lo es."""
        e = Ensayo([(40.0, 41.0, {"aurora": ("ip", 40.6)}), (52.0, 52.3, {})])
        r = e.evaluar()
        for p in ("andina", "valle", "cumbre"):
            self.assertEqual(clase(r, 1, p)["clase"], "no_cubierto_imposible", p)
        self.assertEqual(clase(r, 1, "aurora")["clase"], "cubierto")
        for p in ("aurora", "andina", "valle", "cumbre"):
            self.assertEqual(clase(r, 2, p)["clase"], "no_cubierto_imposible", p)
        self.assertEqual(r["veredicto"], "sin defectos")
        self.assertEqual(r["defectos"], [])

    def test_A3_fase_larga_sin_cubrir_por_proveedor_sin_fallas_es_defecto(self):
        """CONTRATO A3: fase 10-60, andina sin fallas no la cubrio (10 + 1 + 2,6 < 60) -> DEFECTO."""
        cubren = todos(10.0)
        del cubren["andina"]
        r = Ensayo([(10.0, 60.0, cubren)]).evaluar()
        self.assertEqual(clase(r, 1, "andina")["clase"], "defecto")
        self.assertEqual(clase(r, 1, "andina")["alcance"], "seguro")
        self.assertEqual(r["veredicto"], "defectos")
        self.assertEqual([(d["fase"], d["proveedor"]) for d in r["defectos"]], [(1, "andina")])

    def test_A3_fase_sin_ningun_bloqueo_y_alcanzable_es_defecto_de_fase(self):
        """CONTRATO A3 (veredicto): una fase evaluable alcanzable seguro que quedo sin bloquear figura
        tambien como defecto de la fase entera."""
        r = Ensayo([(10.0, 60.0, {})]).evaluar()
        self.assertEqual(r["veredicto"], "defectos")
        self.assertIn((1, None), [(d["fase"], d["proveedor"]) for d in r["defectos"]])
        self.assertEqual(r["fases"][0]["estado"], "DEFECTO")

    def test_A4_fallas_observadas_corren_el_limite(self):
        """CONTRATO A4: fase 10-20 sin cumbre. Sin fallas: 10+1+3,9 = 14,9 < 20 -> defecto. Con 1 falla:
        10+1+7,8 = 18,8 < 20 -> sigue defecto. Con 2: 10+1+11,7 = 22,7 >= 20 -> dependia de la suerte."""
        cubren = todos(10.0)
        del cubren["cumbre"]
        cubren["valle"] = ("dominio", 14.5)
        sin = Ensayo([(10.0, 20.0, cubren)]).evaluar()
        self.assertEqual(clase(sin, 1, "cumbre")["clase"], "defecto")
        una = Ensayo([(10.0, 20.0, cubren)], extra=[("cumbre", "ip", IP, 10.5, 12.6)]).evaluar()
        self.assertEqual(clase(una, 1, "cumbre")["fallas_observadas"], 1)
        self.assertEqual(clase(una, 1, "cumbre")["clase"], "defecto")
        dos = Ensayo([(10.0, 20.0, cubren)],
                     extra=[("cumbre", "ip", IP, 10.5, 12.6), ("cumbre", "dominio", HOST, 12.7, 15.9)]).evaluar()
        self.assertEqual(clase(dos, 1, "cumbre")["fallas_observadas"], 2)
        self.assertEqual(clase(dos, 1, "cumbre")["clase"], "no_cubierto_suerte")
        self.assertEqual(dos["veredicto"], "sin defectos")

    def test_A4_solo_cuentan_fallas_de_ese_proveedor_sobre_esa_fase(self):
        """CONTRATO A4: fallas sobre otra IP/host, de otro proveedor o anteriores a la fase no excusan."""
        cubren = todos(10.0)
        del cubren["cumbre"]
        cubren["valle"] = ("dominio", 14.5)
        ajenas = [("cumbre", "ip", "198.51.100.77", 10.5, 12.6),      # otra IP
                  ("cumbre", "dominio", "otro.pirata.test", 11.0, 13.0),  # otro host
                  ("andina", "ip", IP, 10.2, 12.0),                   # otro proveedor
                  ("cumbre", "ip", IP, 5.0, 8.0)]                     # antes de la fase
        r = Ensayo([(10.0, 20.0, cubren)], extra=ajenas).evaluar()
        self.assertEqual(clase(r, 1, "cumbre")["fallas_observadas"], 0)
        self.assertEqual(clase(r, 1, "cumbre")["clase"], "defecto")

    def test_A4_las_fallas_despues_de_la_orden_que_cubrio_no_cuentan(self):
        """CONTRATO A4: "fallaron ANTES de la que se aplico": una falla posterior no se cuenta."""
        cubren = todos(10.0)
        r = Ensayo([(10.0, 60.0, cubren)], extra=[("cumbre", "ip", IP, 20.0, 22.0)]).evaluar()
        self.assertEqual(clase(r, 1, "cumbre")["fallas_observadas"], 0)
        r = Ensayo([(10.0, 60.0, cubren)], extra=[("cumbre", "ip", IP, 10.1, 12.0)]).evaluar()
        self.assertEqual(clase(r, 1, "cumbre")["fallas_observadas"], 1)

    def test_A5_proveedor_que_solo_bloquea_por_dominio(self):
        """CONTRATO A5: valle (solo dominio) cubre una fase que recomienda 'ip' con un bloqueo por
        dominio del host; si no la cubre en una fase larga es defecto aunque la verdad diga 'ip'; una
        orden por IP a valle en el registro no cuenta como falla suya."""
        r = Ensayo([(10.0, 60.0, todos(10.0))], rec="ip").evaluar()
        self.assertEqual(clase(r, 1, "valle")["clase"], "cubierto")
        self.assertEqual(clase(r, 1, "valle")["tipos"], ["dominio"])
        cubren = todos(10.0)
        del cubren["valle"]
        r = Ensayo([(10.0, 60.0, cubren)], rec="ip",
                   extra=[("valle", "ip", IP, 10.2, 14.0), ("valle", "ip", IP, 14.1, 18.0)]).evaluar()
        self.assertEqual(clase(r, 1, "valle")["fallas_observadas"], 0)
        self.assertEqual(clase(r, 1, "valle")["clase"], "defecto")

    def test_A5_proveedor_sin_capacidades_utiles_es_imposible(self):
        """CONTRATO A5: un proveedor que no aplica ni 'ip' ni 'dominio' no puede bloquear nada que el
        verificador cuente: es imposible, nunca defecto."""
        provs = {"proveedores": PROVEEDORES["proveedores"] + [
            {"id": "mudo", "capacidades": ["url"], "comportamiento": {"demora_min": 0.1}}]}
        r = Ensayo([(10.0, 60.0, todos(10.0))]).evaluar(provs)
        self.assertEqual(clase(r, 1, "mudo")["clase"], "no_cubierto_imposible")
        self.assertEqual(r["veredicto"], "sin defectos")

    def test_A6_limites_exactos_de_imposible_y_seguro(self):
        """CONTRATO A6, con demora 5 (0,7 x 5 = 3,5 y 1,3 x 5 = 6,5, exactos):
        10-13,5 imposible (>=); 10-13,75 suerte; 10-17,5 suerte (el seguro es estricto); 10-17,75 seguro."""
        casos = [(13.5, "imposible"), (13.75, "suerte"), (17.5, "suerte"), (17.75, "seguro")]
        for hasta, esperado in casos:
            with self.subTest(hasta=hasta):
                r = Ensayo([(10.0, hasta, {})]).evaluar(LENTO, margen=1.0)
                self.assertEqual(clase(r, 1, "lento")["alcance"], esperado)

    def test_A6_el_margen_se_respeta(self):
        """CONTRATO A6: andina en 10-60 es defecto con margen 1 y deja de serlo con margen 50
        (10 + 50 + 2,6 >= 60)."""
        cubren = todos(10.0)
        del cubren["andina"]
        e = Ensayo([(10.0, 60.0, cubren)])
        self.assertEqual(e.evaluar(margen=1.0)["veredicto"], "defectos")
        self.assertEqual(e.evaluar(margen=50.0)["veredicto"], "sin defectos")

    def test_fase_posterior_al_fin_del_registro_no_es_evaluable(self):
        """Si el registro termina antes de que empiece la fase, el verificador no la puntua y el oraculo
        tampoco (no es un defecto)."""
        r = Ensayo([(10.0, 40.0, todos(10.0)), (60.0, 105.0, {})], log_fin=50.0).evaluar()
        self.assertFalse(r["fases"][1]["evaluable"])
        self.assertIn("registro termino", r["fases"][1]["motivo"])
        self.assertEqual(r["veredicto"], "sin defectos")


class TestCLI(unittest.TestCase):
    def test_A3_A8_codigo_1_y_json_legible(self):
        """CONTRATO A3 + A8: con un defecto la CLI sale con 1 y --json trae veredicto, fases y defectos."""
        cubren = todos(10.0)
        del cubren["andina"]
        with tempfile.TemporaryDirectory() as tmp:
            Ensayo([(10.0, 60.0, cubren), (105.0, 105.0, {})]).escribir(tmp)
            r = correr_cli(tmp, "--json")
            self.assertEqual(r.returncode, 1, r.stderr)
            datos = json.loads(r.stdout)
            self.assertEqual(datos["veredicto"], "defectos")
            self.assertEqual(datos["defectos"][0]["proveedor"], "andina")
            self.assertEqual([f["evaluable"] for f in datos["fases"]], [True, False])
            texto = correr_cli(tmp)
            self.assertEqual(texto.returncode, 1)
            self.assertIn("DEFECTO", texto.stdout)
            self.assertIn("(min 10–60)", texto.stdout)
            self.assertIn("NO EVALUABLE", texto.stdout)

    def test_codigo_0_sin_defectos(self):
        with tempfile.TemporaryDirectory() as tmp:
            Ensayo([(10.0, 60.0, todos(10.0)), (40.0, 41.0, {"aurora": ("ip", 40.6)})]).escribir(tmp)
            r = correr_cli(tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("SIN DEFECTOS", r.stdout)

    def test_A7_datos_mal_formados_codigo_2(self):
        """CONTRATO A7: cada forma de dato roto termina con codigo 2 y un mensaje en stderr."""
        def roto(cambiar):
            with tempfile.TemporaryDirectory() as tmp:
                c = Ensayo([(10.0, 60.0, todos(10.0))]).escribir(tmp)
                extra = cambiar(c) or []
                return correr_cli(tmp, *extra)

        casos = {
            "verdad no es JSON": lambda c: (c / "verdad.json").write_text("{nope", encoding="utf-8") and None,
            "verdad sin streams": lambda c: (c / "verdad.json").write_text('{"escenario_id": "t-1"}') and None,
            "fase sin desde_min": lambda c: (c / "verdad.json").write_text(json.dumps(
                {"escenario_id": "t-1", "streams": [{"id": "s", "clase": "pirata", "fases": [{"ip": IP, "host": HOST,
                                                                                               "hasta_min": 3}]}]})) and None,
            "proveedores sin demora": lambda c: (c / "proveedores.json").write_text(json.dumps(
                {"proveedores": [{"id": "aurora", "capacidades": ["ip"]}]})) and None,
            "registro con linea rota": lambda c: (c / "registro.jsonl").write_text(
                (c / "registro.jsonl").read_text() + "{rota\n") and None,
            "registro vacio": lambda c: (c / "registro.jsonl").write_text("\n") and None,
            "verificador de otro escenario": lambda c: (c / "verificador.json").write_text(json.dumps(
                dict(json.loads((c / "verificador.json").read_text()), escenario="otro"))) and None,
            "verificador sin fases": lambda c: (c / "verificador.json").write_text('{"log_hasta_min": 110}') and None,
            "registro de otro ensayo": lambda c: (c / "registro.jsonl").write_text(
                '{"min": 0, "evento": "simulacion_iniciada", "escenario": "t-1"}\n') and None,
            "archivo inexistente": lambda c: (c / "verdad.json").unlink(),
            "margen negativo": lambda c: ["--margen-min", "-1"],
        }
        for nombre, cambiar in casos.items():
            with self.subTest(caso=nombre):
                r = roto(cambiar)
                self.assertEqual(r.returncode, 2, (nombre, r.stdout, r.stderr))
                self.assertTrue(r.stderr.strip(), nombre)
                self.assertNotIn("Traceback", r.stderr, nombre)

    def test_A7_uso_incorrecto_codigo_2(self):
        r = subprocess.run([sys.executable, "-I", str(SCRIPT), "--verdad", "x.json"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        r = subprocess.run([sys.executable, "-I", str(SCRIPT), "--verdad", "a", "--proveedores", "b",
                            "--verificador", "c", "--registro", "d", "--margen-min", "uno"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)

    def test_no_importa_el_paquete_marca(self):
        """El oraculo es independiente de la plataforma: no importa `marca`."""
        texto = SCRIPT.read_text(encoding="utf-8")
        self.assertNotRegex(texto, r"(?m)^\s*(import|from)\s+(marca|verificar|evaluacion)\b")


if __name__ == "__main__":
    unittest.main()
