"""Tests de herramientas/escenario_espejo.py.

Contratos que protegen:
  C1  Coherencia escenario <-> verdad (ids, fases, host/IP/minuto, DNS, ASN, reclamos, licenciatario).
  C2  Nada de la practica sobrevive (dominios, IP, ASN, organizaciones, prefijos, sesiones, ids).
  C3  Las organizaciones no delatan el tipo de red (CDN / compartido / dedicado / shared).
  C4  Tiempos: dentro de [0,5 ; fin_min], fases ordenadas sin solaparse, mudanzas antes y despues del 50.
  C5  Determinismo: misma semilla -> mismos bytes; semillas distintas -> distinto resultado.
  C6  --trampas agrega las tres trampas con su verdad correcta.
  C7  El verificador de coherencia FALLA cuando se viola cada contrato (mutaciones).
  C8  La CLI escribe ambos archivos y no escribe nada si algo no cierra.
  C9  Sin --bordes los bytes son los de foto1 (SHA-256 fijados); con --bordes la salida es aditiva,
      determinista e igual en 3.12 y 3.9, cada borde cae en su banda sorteada por semilla, C1-C3 valen
      tambien con bordes y la relajacion de tiempos solo alcanza a los streams de borde.
  C10 Borde "inquilinos de un mismo registrable": verdad 'dominio', solo el host del pirata es pirata.

Solo se LEEN los JSON del repo oficial; no se ejecuta nada desde alli. Ruta: la variable de entorno
DESAFIO_FUTBOL_REPO o, si no esta, ../desafio-futbol (clonado al lado de este repo). Sin el repo, se saltean.
"""
import base64
import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlsplit

RAIZ = Path(__file__).resolve().parent.parent
REPO_DESAFIO = Path(os.environ.get("DESAFIO_FUTBOL_REPO", str(RAIZ.parent / "desafio-futbol")))
SCRIPT = RAIZ / "herramientas" / "escenario_espejo.py"

_spec = importlib.util.spec_from_file_location("escenario_espejo", SCRIPT)
ee = importlib.util.module_from_spec(_spec)
sys.modules["escenario_espejo"] = ee
_spec.loader.exec_module(ee)

PRACTICA = REPO_DESAFIO / "datos" / "escenario_practica.json"
VERDAD = REPO_DESAFIO / "evaluacion" / "verdad_practica.json"
SEMILLAS = (7, 2026)
SEMILLAS_BORDES = (11, 23, 37)
# (semilla, trampas, bordes): las variantes sin bordes de siempre y las de borde que se ensayan.
VARIANTES = ([(s, t, False) for s in SEMILLAS for t in (False, True)]
             + [(s, True, True) for s in SEMILLAS_BORDES])

# SHA-256 de escenario.json y verdad.json escritos por el generador de foto1 (herramientas/
# escenario_espejo.py, antes de --bordes), medidos con Python 3.12 y 3.9: dan lo mismo. Son el
# contrato "sin --bordes, la salida es byte a byte la de antes" contra una referencia EXTERNA al
# codigo nuevo (compararlo consigo mismo no protege nada).
SHA_FOTO1 = {
    (7, False): ("e98655192a7acfd816d25cd0fb6c3ba2c9d8067259460e82e2fb5bbcb4ea30b4",
                 "fa76ec5a17d8a45cb08417f6e74c6d8728b3a84b6e6fc624a7b1a84d1e6b81ac"),
    (7, True): ("5188bb0d6794073b330188c77f98ecf1c7036d5d6df2c0ec7e92c2e48bcccf41",
                "4443df7c838ceb72b6370d3d31bbb80e232ab8ba0ba171f0cff9b759d47d267c"),
    (2026, False): ("c435064376ce492f7f83e8dae6c3d80242a9e7b75552f3ce5579cc6d95f0079f",
                    "ca5a15d0ebf50cbd82d01fe48e2f4e1da96a32ea194cb06e1c2d8eb1c948e584"),
    (2026, True): ("4bd521203bdc3724ffe5c04ec217dc27cd65a72c94ca316cc229c48fc0b28509",
                   "f53eb4d5afd6c5943b0d042295188b5f7e17ca127cb2868fc2ae31dd3ae14bb7"),
}


def cargar(ruta):
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


def sha256(ruta):
    return hashlib.sha256(Path(ruta).read_bytes()).hexdigest()


@unittest.skipUnless(PRACTICA.exists() and VERDAD.exists(), "falta el repo oficial del desafio")
class BaseEspejo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.orig_esc = cargar(PRACTICA)
        cls.orig_ver = cargar(VERDAD)

    def espejo(self, semilla, trampas, bordes=False):
        if bordes:
            return ee.generar(copy.deepcopy(self.orig_esc), copy.deepcopy(self.orig_ver), semilla, trampas, True)
        return ee.generar(copy.deepcopy(self.orig_esc), copy.deepcopy(self.orig_ver), semilla, trampas)


class TestCoherencia(BaseEspejo):
    def test_C1_C2_C3_C4_comprobaciones_pasan_en_todas_las_variantes(self):
        for semilla, trampas, bordes in VARIANTES:
            with self.subTest(semilla=semilla, trampas=trampas, bordes=bordes):
                esc, ver = self.espejo(semilla, trampas, bordes)
                self.assertEqual(ee.verificar_coherencia(esc, ver, self.orig_esc, self.orig_ver, trampas, bordes), [])

    def test_C1_invariantes_independientes_del_verificador(self):
        """Repite a mano lo esencial, sin reutilizar verificar_coherencia (tambien con bordes)."""
        for semilla, trampas, bordes in VARIANTES:
            with self.subTest(semilla=semilla, trampas=trampas, bordes=bordes):
                esc, ver = self.espejo(semilla, trampas, bordes)
                dets = {d["id"]: d for d in esc["detecciones"]}
                en_fase = [i for s in ver["streams"] for f in s["fases"] for i in f["detecciones"]]
                self.assertCountEqual(en_fase, list(dets))  # cada deteccion en exactamente una fase
                for s in ver["streams"]:
                    for f in s["fases"]:
                        self.assertIn(f["host"], esc["dns_pasivo"][f["ip"]])
                        for i in f["detecciones"]:
                            d = dets[i]
                            self.assertEqual((d["host_stream"], d["ip_servidor"]), (f["host"], f["ip"]))
                            self.assertTrue(f["desde_min"] <= d["minuto"] <= f["hasta_min"])
                todos = {x for v in esc["dns_pasivo"].values() for x in v}
                self.assertTrue(set(ver["dominios_piratas"]) <= todos)
                for r in esc["reclamos_automaticos"]:
                    self.assertIn(r["dominio"], todos)
                    self.assertNotIn(r["dominio"], ver["dominios_piratas"])
                for l in esc["partido"]["licenciatarios"]:
                    self.assertTrue(set(l["dominios_autorizados"]) <= todos)
                self.assertEqual(set(esc["ip_asn"]), set(esc["dns_pasivo"]))
                self.assertEqual({str(a) for a in esc["ip_asn"].values()}, set(esc["asn"]))
                self.assertEqual([d["id"] for d in esc["detecciones"]],
                                 ["D-%04d" % n for n in range(1, len(dets) + 1)])

    def test_C2_nada_de_la_practica_sobrevive_ni_siquiera_como_texto(self):
        orig_txt = json.dumps([self.orig_esc, self.orig_ver], ensure_ascii=False)
        for semilla, trampas, bordes in [(7, True, False)] + [(s, True, True) for s in SEMILLAS_BORDES]:
            with self.subTest(semilla=semilla, bordes=bordes):
                esc, ver = self.espejo(semilla, trampas, bordes)
                sin_b64 = json.dumps([esc, ver], ensure_ascii=False)  # los b64 son aleatorios: se quitan
                for d in esc["detecciones"]:
                    sin_b64 = sin_b64.replace(d["captura"]["contenido_b64"], "")
                for ip in self.orig_esc["dns_pasivo"]:
                    self.assertNotIn('"%s"' % ip, sin_b64)
                for dominio in ("pelotaya", "golazo", "verpartido", "tribuna", "resumenes", "canalnorte",
                                "LP26-PRA", "S048211", "S077310", "S010457", "S063002", "S102934", "practica-01",
                                "Canal Norte", "Liga Profesional Ficticia", "Club Ficticio"):
                    self.assertIn(dominio, orig_txt)  # el termino era realmente de la practica
                    self.assertNotIn(dominio, sin_b64)
                for asn in self.orig_esc["asn"]:
                    self.assertNotIn(asn, esc["asn"])

    def test_C3_organizaciones_neutras(self):
        variantes = [(s, True, False) for s in range(1, 15)] + [(s, True, True) for s in SEMILLAS_BORDES]
        for semilla, trampas, bordes in variantes:
            esc, _ = self.espejo(semilla, trampas, bordes)
            for org in esc["asn"].values():
                # "compartid" cubre compartido/compartida (la palabra que mira la plataforma).
                for palabra in ("cdn", "compartid", "dedicado", "shared"):
                    self.assertNotIn(palabra, org.lower(), (semilla, bordes))

    def test_C4_tiempos_y_mudanzas_en_muchas_semillas(self):
        for semilla in range(1, 40):
            esc, ver = self.espejo(semilla, semilla % 2 == 0)
            fin = esc["partido"]["fin_min"]
            for d in esc["detecciones"]:
                for t in [d["minuto"], d["captura"]["capturada_min"]] + [p["minuto"] for p in d["promocion"]]:
                    self.assertTrue(0.5 <= t <= fin, (semilla, d["id"], t))
            mud = []
            for s in ver["streams"]:
                for a, b in zip(s["fases"], s["fases"][1:]):
                    self.assertLess(a["hasta_min"], b["desde_min"], (semilla, s["id"]))
                    if s["clase"] == "pirata":
                        mud.append(b["desde_min"])
                for f in s["fases"]:
                    self.assertTrue(0.5 <= f["desde_min"] <= f["hasta_min"] <= fin)
            self.assertTrue(any(m < 50 for m in mud) and any(m > 50 for m in mud), (semilla, mud))

    def test_C4_con_bordes_la_parte_base_sigue_con_las_reglas_estrictas(self):
        """CONTRATO: --bordes solo relaja piso y solape en los streams que agrega; los de la
        practica y las trampas siguen con fases >= 0,5, sin solaparse y en orden."""
        n_base = len(self.orig_ver["streams"]) + 3
        for semilla in SEMILLAS_BORDES:
            esc, ver = self.espejo(semilla, True, True)
            fin = esc["partido"]["fin_min"]
            for s in ver["streams"][:n_base]:
                for a, b in zip(s["fases"], s["fases"][1:]):
                    self.assertLess(a["hasta_min"], b["desde_min"], (semilla, s["id"]))
                for f in s["fases"]:
                    self.assertTrue(0.5 <= f["desde_min"] <= f["hasta_min"] <= fin, (semilla, s["id"]))
            for d in esc["detecciones"]:
                for t in [d["minuto"], d["captura"]["capturada_min"]] + [p["minuto"] for p in d["promocion"]]:
                    self.assertTrue(0.5 <= t <= fin, (semilla, d["id"], t))

    def test_corrimiento_es_propio_de_cada_stream_y_se_aplica_por_igual(self):
        esc, ver = self.espejo(7, False)
        orig = {d["id"]: d for d in self.orig_esc["detecciones"]}
        nuevo_orden = {d["id"]: d for d in esc["detecciones"]}
        # Mismo stream -> misma diferencia en minuto, captura y promociones; el orden de ids se renumera.
        orig_por_stream = {s["id"]: [i for f in s["fases"] for i in f["detecciones"]] for s in self.orig_ver["streams"]}
        nuevo_por_stream = [[i for f in s["fases"] for i in f["detecciones"]] for s in ver["streams"]]
        corrimientos = []
        for (sid_o, ids_o), ids_n in zip(orig_por_stream.items(), nuevo_por_stream):
            difs = {round(nuevo_orden[n]["minuto"] - orig[o]["minuto"], 3) for o, n in zip(ids_o, ids_n)}
            self.assertEqual(len(difs), 1, sid_o)
            c = difs.pop()
            corrimientos.append(c)
            for o, n in zip(ids_o, ids_n):
                self.assertAlmostEqual(nuevo_orden[n]["captura"]["capturada_min"] - orig[o]["captura"]["capturada_min"], c)
                for po, pn in zip(orig[o]["promocion"], nuevo_orden[n]["promocion"]):
                    self.assertAlmostEqual(pn["minuto"] - po["minuto"], c)
        self.assertGreater(len(set(corrimientos)), 1)  # no es un corrimiento global
        self.assertTrue(all(c != 0 for c in corrimientos))


class TestEstructura(BaseEspejo):
    def test_subdominios_de_un_sitio_comparten_base_y_sitios_distintos_no(self):
        esc, ver = self.espejo(7, False)
        base = lambda h: ".".join(h.split(".")[-2:])
        orig_dns = self.orig_esc["dns_pasivo"]
        # Mapeo posicional: el espejo conserva el orden de IP y de dominios de la practica.
        pares = [(o, n) for ip_o, ip_n in zip(orig_dns, esc["dns_pasivo"])
                 for o, n in zip(orig_dns[ip_o], esc["dns_pasivo"][ip_n])]
        por_base = {}
        for o, n in pares:
            por_base.setdefault(base(o), set()).add(base(n))
        for b_orig, nuevas in por_base.items():
            self.assertEqual(len(nuevas), 1, b_orig)
        self.assertEqual(len({next(iter(v)) for v in por_base.values()}), len(por_base))
        for h in {n for _, n in pares}:
            self.assertTrue(h.endswith(".test") or h.endswith(".example"))

    def test_respaldo_y_espejo_del_pirata_siguen_en_el_mismo_sitio_pirata(self):
        esc, ver = self.espejo(7, False)
        ip_orig = "203.0.113.10"  # s1 + s1-respaldo; "espejo" convive con s3 en 198.51.100.77
        claves = list(self.orig_esc["dns_pasivo"])
        for ip_o in (ip_orig, "198.51.100.77"):
            nuevos = esc["dns_pasivo"][list(esc["dns_pasivo"])[claves.index(ip_o)]]
            self.assertEqual(len({".".join(h.split(".")[-2:]) for h in nuevos}), 1)
            self.assertEqual(len(nuevos), 2)
        todas = {s["id"]: s for s in ver["streams"]}
        self.assertEqual(len(todas), len(self.orig_ver["streams"]))

    def test_marca_ajena_sigue_invalida_y_licenciatario_conserva_su_prefijo(self):
        esc, ver = self.espejo(7, False)
        prefijos = [m["prefijo"] for m in esc["partido"]["marcas_de_agua_validas"]]
        ajenas = [d["marca_de_agua_extraida"] for d in esc["detecciones"]
                  if d["marca_de_agua_extraida"].startswith("LP25-")]
        self.assertTrue(ajenas)
        for m in ajenas:
            self.assertFalse(any(m.startswith(p) for p in prefijos))
        lic = esc["partido"]["licenciatarios"][0]
        self.assertIn(lic["prefijo_marca"], prefijos)
        self.assertNotIn("PRA", "".join(prefijos))

    def test_una_sesion_por_stream_y_sesiones_distintas_entre_streams(self):
        esc, ver = self.espejo(7, True)
        dets = {d["id"]: d for d in esc["detecciones"]}
        sesiones = []
        for s in ver["streams"]:
            marcas = {dets[i]["marca_de_agua_extraida"] for f in s["fases"] for i in f["detecciones"]}
            self.assertEqual(len(marcas), 1, s["id"])
            sesiones.append(marcas.pop())
        con_sesion = [m for m in sesiones if m and m.rsplit("-", 1)[-1].startswith("S")]
        self.assertEqual(len(con_sesion), len(set(con_sesion)))

    def test_capturas_de_64_bytes_con_0x47_y_distintas_entre_si(self):
        esc, _ = self.espejo(7, True)
        vistos = set()
        for d in esc["detecciones"]:
            raw = base64.b64decode(d["captura"]["contenido_b64"], validate=True)
            self.assertEqual(len(raw), 64)
            self.assertEqual(raw[0], 0x47)
            vistos.add(raw)
        self.assertEqual(len(vistos), len(esc["detecciones"]))

    def test_id_nombre_y_limites_del_partido(self):
        esc, ver = self.espejo(7, False)
        self.assertEqual(esc["id"], "espejo-7")
        self.assertEqual(esc["partido"]["id"], "espejo-7")
        self.assertEqual(ver["escenario_id"], "espejo-7")
        self.assertIn("espejo", esc["partido"]["nombre"].lower())
        self.assertEqual((ver["fin_min"], ver["gracia_min"]), (105, 5))
        self.assertEqual(esc["partido"]["fin_min"], 105)

    def test_mismo_formato_de_claves_que_el_original(self):
        esc, ver = self.espejo(7, False)
        self.assertEqual(list(esc), list(self.orig_esc))
        self.assertEqual(list(ver), list(self.orig_ver))
        self.assertEqual(list(esc["detecciones"][0]), list(self.orig_esc["detecciones"][0]))
        self.assertEqual(list(esc["detecciones"][0]["captura"]), list(self.orig_esc["detecciones"][0]["captura"]))
        self.assertEqual(list(ver["streams"][0]["fases"][0]), list(self.orig_ver["streams"][0]["fases"][0]))
        self.assertEqual(len(esc["detecciones"]), len(self.orig_esc["detecciones"]))


class TestDeterminismo(BaseEspejo):
    def test_C5_misma_semilla_mismo_resultado_y_otra_semilla_otro(self):
        a = self.espejo(7, True)
        b = self.espejo(7, True)
        c = self.espejo(8, True)
        self.assertEqual(json.dumps(a, sort_keys=False), json.dumps(b, sort_keys=False))
        self.assertNotEqual(json.dumps(a), json.dumps(c))
        # Con y sin trampas no comparten rotulos por azar: solo el segundo agrega streams.
        sin = self.espejo(7, False)
        self.assertEqual(len(a[1]["streams"]), len(sin[1]["streams"]) + 3)


class TestTrampas(BaseEspejo):
    def test_C6_las_tres_trampas_con_su_verdad(self):
        for semilla in SEMILLAS:
            esc, ver = self.espejo(semilla, True)
            dets = {d["id"]: d for d in esc["detecciones"]}
            nuevos = ver["streams"][len(self.orig_ver["streams"]):]
            self.assertEqual([s["clase"] for s in nuevos], ["falso_positivo", "pirata", "pirata"])
            fp, retrans, compartida = nuevos
            # 1) falso positivo: sin marca, IP propia
            ff = fp["fases"][0]
            self.assertTrue(all(dets[i]["marca_de_agua_extraida"] == "" for i in ff["detecciones"]))
            self.assertEqual(len(esc["dns_pasivo"][ff["ip"]]), 2)  # su host + su apex, nadie mas
            self.assertIsNone(ff["bloqueo_recomendado"])
            self.assertNotIn(ff["host"], ver["dominios_piratas"])
            # 2) retransmision del licenciatario en dominio ajeno
            fr = retrans["fases"][0]
            lic = esc["partido"]["licenciatarios"][0]
            self.assertEqual(len(retrans["fases"]), 1)
            self.assertEqual(len(fr["detecciones"]), 3)
            self.assertEqual(fr["bloqueo_recomendado"], "ip")
            self.assertEqual(esc["dns_pasivo"][fr["ip"]], [fr["host"]])
            self.assertIn(fr["host"], ver["dominios_piratas"])
            self.assertNotIn(fr["host"], lic["dominios_autorizados"])
            self.assertTrue(all(dets[i]["marca_de_agua_extraida"].startswith(lic["prefijo_marca"])
                                for i in fr["detecciones"]))
            # 3) IP compartida con un unico sitio legitimo + reclamo
            fc = compartida["fases"][0]
            otros = [d for d in esc["dns_pasivo"][fc["ip"]] if d != fc["host"]]
            self.assertEqual(len(otros), 1)
            self.assertNotIn(otros[0], ver["dominios_piratas"])
            self.assertEqual(fc["bloqueo_recomendado"], "dominio")
            self.assertEqual(len(compartida["fases"]), 1)
            self.assertTrue(any(r["dominio"] == otros[0] for r in esc["reclamos_automaticos"]))
            # IP exclusivas y distintas entre las tres trampas
            ips = [ff["ip"], fr["ip"], fc["ip"]]
            self.assertEqual(len(set(ips)), 3)

    def test_sin_trampas_no_hay_streams_ni_reclamos_extra(self):
        esc, ver = self.espejo(7, False)
        self.assertEqual(len(ver["streams"]), len(self.orig_ver["streams"]))
        self.assertEqual(len(esc["reclamos_automaticos"]), len(self.orig_esc["reclamos_automaticos"]))


class TestVerificadorDetectaViolaciones(BaseEspejo):
    """C7: cada contrato, roto a proposito, tiene que producir errores."""

    def setUp(self):
        self.esc, self.ver = self.espejo(7, True)

    def errores(self):
        return ee.verificar_coherencia(self.esc, self.ver, self.orig_esc, self.orig_ver, True)

    def test_base_limpia(self):
        self.assertEqual(self.errores(), [])

    def test_detecta_id_inexistente_en_la_verdad(self):
        self.ver["streams"][0]["fases"][0]["detecciones"].append("D-9999")
        self.assertTrue(any("D-9999" in e for e in self.errores()))

    def test_detecta_deteccion_en_dos_fases_o_en_ninguna(self):
        self.ver["streams"][0]["fases"][0]["detecciones"].pop()
        self.assertTrue(any("exactamente 1" in e for e in self.errores()))

    def test_detecta_host_ausente_de_dns_pasivo(self):
        self.ver["streams"][0]["fases"][0]["host"] = "no-existe.test"
        self.assertTrue(any("dns_pasivo" in e for e in self.errores()))

    def test_detecta_minuto_fuera_de_fase(self):
        f = self.ver["streams"][0]["fases"][0]
        f["hasta_min"] = f["desde_min"]
        self.assertTrue(any("fuera de [" in e for e in self.errores()))

    def test_detecta_ip_sin_asn(self):
        self.esc["ip_asn"].pop(next(iter(self.esc["ip_asn"])))
        self.assertTrue(self.errores())

    def test_detecta_asn_sin_organizacion(self):
        self.esc["asn"].pop(next(iter(self.esc["asn"])))
        self.assertTrue(self.errores())

    def test_detecta_dominio_pirata_inexistente_y_reclamo_sobre_pirata(self):
        self.ver["dominios_piratas"].append("fantasma.test")
        self.esc["reclamos_automaticos"].append({"dominio": self.ver["dominios_piratas"][0], "demora_min": 1, "mensaje": "x"})
        e = self.errores()
        self.assertTrue(any("fantasma.test" in x for x in e))
        self.assertTrue(any("es pirata" in x for x in e))

    def test_detecta_licenciatario_con_dominio_inexistente(self):
        self.esc["partido"]["licenciatarios"][0]["dominios_autorizados"].append("nada.test")
        self.assertTrue(any("nada.test" in e for e in self.errores()))

    def test_detecta_ip_de_la_practica(self):
        ip_vieja = "203.0.113.10"
        ip_nueva = next(iter(self.esc["dns_pasivo"]))
        txt = json.dumps([self.esc, self.ver]).replace(ip_nueva, ip_vieja)
        self.esc, self.ver = json.loads(txt)
        self.assertTrue(any("heredada" in e or "sobrevive IP" in e for e in self.errores()))

    def test_detecta_organizacion_que_delata_el_tipo(self):
        asn = next(iter(self.esc["asn"]))
        self.esc["asn"][asn] = "Nube Rapida CDN (ficticia)"
        self.assertTrue(any("delata" in e for e in self.errores()))

    def test_detecta_dominio_de_la_practica_y_prefijo_de_la_practica(self):
        self.esc["detecciones"][0]["pagina"] = "https://pelotaya.test/en-vivo"
        self.assertTrue(any("sobrevive dominio" in e for e in self.errores()))
        self.setUp()
        self.esc["partido"]["marcas_de_agua_validas"][0]["prefijo"] = "LP26-PRA-OFI"
        self.assertTrue(any("sobrevive texto" in e for e in self.errores()))

    def test_detecta_marca_ajena_que_paso_a_ser_valida(self):
        d = next(d for d in self.esc["detecciones"] if d["marca_de_agua_extraida"].startswith("LP25-"))
        d["marca_de_agua_extraida"] = self.esc["partido"]["marcas_de_agua_validas"][0]["prefijo"]
        self.assertTrue(self.errores())

    def test_detecta_sesion_distinta_entre_fases_de_un_mismo_stream(self):
        stream = self.ver["streams"][0]
        ultimo = stream["fases"][-1]["detecciones"][-1]
        next(d for d in self.esc["detecciones"] if d["id"] == ultimo)["marca_de_agua_extraida"] += "X"
        self.assertTrue(any("cambia entre fases" in e for e in self.errores()))

    def test_detecta_tiempos_fuera_de_rango_y_fases_solapadas(self):
        self.esc["detecciones"][0]["promocion"][0]["minuto"] = 0.1
        self.assertTrue(any("fuera de [0.5" in e for e in self.errores()))
        self.setUp()
        fases = self.ver["streams"][0]["fases"]
        fases[1]["desde_min"] = fases[0]["hasta_min"]
        self.assertTrue(any("solapadas" in e for e in self.errores()))

    def test_detecta_falta_de_mudanza_antes_o_despues_del_50(self):
        for s in self.ver["streams"]:
            if s["clase"] == "pirata":
                for f in s["fases"][1:]:
                    f["desde_min"] = 60.0
                    f["hasta_min"] = max(f["hasta_min"], 61.0)
        self.assertTrue(any("mudanza" in e for e in self.errores()))

    def test_detecta_captura_mal_formada(self):
        self.esc["detecciones"][0]["captura"]["contenido_b64"] = base64.b64encode(b"G" + b"\0" * 10).decode()
        self.assertTrue(any("64 bytes" in e for e in self.errores()))
        self.setUp()
        self.esc["detecciones"][0]["captura"]["contenido_b64"] = base64.b64encode(b"H" + b"\0" * 63).decode()
        self.assertTrue(any("0x47" in e for e in self.errores()))

    def test_detecta_trampa_faltante(self):
        self.ver["streams"] = self.ver["streams"][:-1]
        # Las detecciones de la trampa quedan huerfanas Y falta la trampa: ambos errores cuentan.
        self.assertTrue(any("trampa 3" in e or "exactamente 1" in e for e in self.errores()))


TURNO = 50.0
# Orden en que _agregar_bordes suma los streams (es parte del contrato: --bordes es aditivo y fijo).
B_TURNO_ANTES, B_TURNO_DESPUES, B_MUDANZA_TURNO, B_ULTIMOS, B_FIN_EXACTO, B_RAPIDAS, B_VUELVE, \
    B_PARALELO, B_COMPARTIDA, B_INQUILINOS = range(10)
CASI = 1e-9


def registrable(host):
    return ".".join(host.split(".")[-2:])


def regla_nueva_recomienda(host, pagina_host, dominios_en_ip, organizacion):
    """Regla que la plataforma incorpora en esta ronda, escrita aca a mano (independiente del
    generador): un nombre de la IP es propio solo si es el host del stream o el de la pagina, o si
    comparte el registrable R con el host y la pagina vive en R o en www.R; si no, es ajeno."""
    r = registrable(host)
    pagina_en_r = pagina_host in (r, "www." + r)
    propios = [d for d in dominios_en_ip
               if d in (host, pagina_host) or (registrable(d) == r and pagina_en_r)]
    ajenos = [d for d in dominios_en_ip if d not in propios]
    compartida = any(p in organizacion.lower() for p in ("cdn", "compartid", "shared"))
    return "dominio" if (ajenos or compartida) else "ip"


def regla_vieja_recomienda(host, pagina_host, dominios_en_ip):
    """La de foto1/foto2 (el defecto que se corrige): propio = mismo registrable que host o pagina."""
    operacion = {registrable(host), registrable(pagina_host)}
    ajenos = [d for d in dominios_en_ip if registrable(d) not in operacion]
    return "dominio" if ajenos else "ip"


class BaseBordes(BaseEspejo):
    SEMILLAS_B = SEMILLAS_BORDES

    def espejo_b(self, semilla, trampas=True, bordes=True):
        return ee.generar(copy.deepcopy(self.orig_esc), copy.deepcopy(self.orig_ver),
                          semilla, trampas, bordes)

    def fases_de_borde(self, ver, trampas=True):
        n_base = len(self.orig_ver["streams"]) + (3 if trampas else 0)
        return ver["streams"][n_base:]

    def primeras_detecciones(self, esc, fase):
        por = {d["id"]: d for d in esc["detecciones"]}
        mins = [por[i]["minuto"] for i in fase["detecciones"]]
        return min(mins) if mins else fase["desde_min"]

    def en_banda(self, x, lo, hi, msg=None):
        self.assertTrue(lo - CASI <= x <= hi + CASI, msg or (x, lo, hi))


class TestBordesContratos(BaseBordes):
    """Cada contrato que --bordes debe cumplir, nombrado y verificado desde esc/ver."""

    def test_sin_bordes_bytes_iguales_a_los_de_foto1(self):
        """CONTRATO: sin --bordes, escenario.json y verdad.json son byte a byte los que escribia el
        generador de foto1 (SHA-256 fijados arriba), para 7 y 2026, con y sin --trampas.

        Falla si cualquier cambio (un consumo de azar de mas, otro orden de claves, otro formato)
        altera la salida sin bordes."""
        for (semilla, trampas), (sha_esc, sha_ver) in SHA_FOTO1.items():
            with self.subTest(semilla=semilla, trampas=trampas), tempfile.TemporaryDirectory() as tmp:
                esc, ver = self.espejo(semilla, trampas)
                ee.escribir_json(Path(tmp) / "escenario.json", esc)
                ee.escribir_json(Path(tmp) / "verdad.json", ver)
                self.assertEqual(sha256(Path(tmp) / "escenario.json"), sha_esc)
                self.assertEqual(sha256(Path(tmp) / "verdad.json"), sha_ver)

    def test_bordes_no_rompen_las_trampas_ni_el_nucleo(self):
        """CONTRATO: --bordes es aditivo: conserva los 6 streams base + 3 trampas, intactos, y
        agrega 10 streams de borde."""
        for semilla in self.SEMILLAS_B:
            esc, ver = self.espejo_b(semilla)
            sin_esc, sin_ver = self.espejo(semilla, True)
            self.assertEqual(len(self.fases_de_borde(ver)), 10, semilla)
            n_base = len(sin_ver["streams"])
            resumen = lambda streams: [(s["id"], s["clase"], [(f["host"], f["ip"], f["desde_min"], f["hasta_min"],
                                                               f["bloqueo_recomendado"]) for f in s["fases"]])
                                       for s in streams]
            self.assertEqual(resumen(ver["streams"][:n_base]), resumen(sin_ver["streams"]))
            trampas = ver["streams"][len(self.orig_ver["streams"]):n_base]
            self.assertEqual([s["clase"] for s in trampas], ["falso_positivo", "pirata", "pirata"])

    def test_coherencia_cierra_con_bordes(self):
        """CONTRATO: el verificador de coherencia pasa con --trampas --bordes."""
        for semilla in self.SEMILLAS_B:
            esc, ver = self.espejo_b(semilla)
            self.assertEqual(
                ee.verificar_coherencia(esc, ver, self.orig_esc, self.orig_ver, True, True), [], semilla)

    def test_borde_turno_primera_deteccion_a_0_05_a_0_15_del_cambio(self):
        """CONTRATO: dos filtraciones nuevas de una sola fase; la primera deteccion de una cae en
        [49,85 ; 49,95] y la de la otra en [50,05 ; 50,15], sorteadas por semilla."""
        for semilla in self.SEMILLAS_B:
            esc, ver = self.espejo_b(semilla)
            b = self.fases_de_borde(ver)
            antes, despues = b[B_TURNO_ANTES], b[B_TURNO_DESPUES]
            self.assertEqual((len(antes["fases"]), len(despues["fases"])), (1, 1))
            self.en_banda(self.primeras_detecciones(esc, antes["fases"][0]), 49.85, 49.95, semilla)
            self.en_banda(self.primeras_detecciones(esc, despues["fases"][0]), 50.05, 50.15, semilla)

    def test_borde_mudanza_turno_misma_sesion_antes_y_despues_del_cambio(self):
        """CONTRATO (borde mudanza-turno): hay un stream pirata de UNA sola sesion con 3 fases o
        mas, una con desde en [turno - 0,5 ; turno) y la siguiente con desde en (turno ; turno + 0,2]."""
        for semilla in self.SEMILLAS_B:
            esc, ver = self.espejo_b(semilla)
            dets = {d["id"]: d for d in esc["detecciones"]}
            ok = False
            for s in self.fases_de_borde(ver):
                marcas = {dets[i]["marca_de_agua_extraida"] for f in s["fases"] for i in f["detecciones"]}
                if s["clase"] != "pirata" or len(s["fases"]) < 3 or len(marcas) != 1:
                    continue
                for a, b in zip(s["fases"], s["fases"][1:]):
                    if TURNO - 0.5 <= a["desde_min"] < TURNO < b["desde_min"] <= TURNO + 0.2:
                        ok = True
            self.assertTrue(ok, semilla)
            s = self.fases_de_borde(ver)[B_MUDANZA_TURNO]
            self.en_banda(s["fases"][0]["desde_min"], 39.0, 41.0)
            self.en_banda(s["fases"][1]["desde_min"], 49.5, 49.6)
            self.en_banda(s["fases"][2]["desde_min"], 50.1, 50.2)
            # La fase del medio dura 0,5..0,7 min: mas que la demora minima de aurora (0,35) y menos
            # que la de los otros tres proveedores (borde fisico, no imposibilidad total).
            self.en_banda(s["fases"][2]["desde_min"] - s["fases"][1]["desde_min"], 0.5, 0.7)

    def test_borde_fin_fase_de_duracion_cero_en_el_minuto_final(self):
        """CONTRATO: hay una fase pirata de duracion cero exactamente en fin_min (el verificador la
        cuenta 'nunca'); y una filtracion nueva con desde en [fin - 2,8 ; fin - 2,2]."""
        for semilla in self.SEMILLAS_B:
            esc, ver = self.espejo_b(semilla)
            fin = float(esc["partido"]["fin_min"])
            b = self.fases_de_borde(ver)
            cero = b[B_FIN_EXACTO]["fases"][0]
            self.assertEqual((cero["desde_min"], cero["hasta_min"]), (fin, fin), semilla)
            ult = b[B_ULTIMOS]["fases"][0]
            self.en_banda(ult["desde_min"], fin - 2.8, fin - 2.2, semilla)
            self.assertEqual(ult["hasta_min"], fin)
            self.assertTrue(all(self.primeras_detecciones(esc, {"detecciones": [i], "desde_min": 0}) < fin
                                for i in ult["detecciones"]))

    def test_borde_mudanzas_encadenadas_a_menos_de_1_5_min(self):
        """CONTRATO: un stream de 4 fases; cortes en [18;22], [38;42], +[0,8;1,2], +[0,5;0,7]."""
        for semilla in self.SEMILLAS_B:
            esc, ver = self.espejo_b(semilla)
            d = [f["desde_min"] for f in self.fases_de_borde(ver)[B_RAPIDAS]["fases"]]
            self.assertEqual(len(d), 4, semilla)
            self.en_banda(d[0], 18.0, 22.0)
            self.en_banda(d[1], 38.0, 42.0)
            self.en_banda(d[2] - d[1], 0.8, 1.2)
            self.en_banda(d[3] - d[2], 0.5, 0.7)

    def test_borde_vuelve_a_un_servidor_ya_usado(self):
        """CONTRATO: tres fases (desde en [1,5;3], [29;33], [59;63]); la tercera repite el (host, ip)
        de la primera."""
        for semilla in self.SEMILLAS_B:
            esc, ver = self.espejo_b(semilla)
            f = self.fases_de_borde(ver)[B_VUELVE]["fases"]
            self.assertEqual(len(f), 3)
            self.assertEqual((f[2]["host"], f[2]["ip"]), (f[0]["host"], f[0]["ip"]))
            self.assertNotEqual((f[1]["host"], f[1]["ip"]), (f[0]["host"], f[0]["ip"]))
            for fase, (lo, hi) in zip(f, ((1.5, 3.0), (29.0, 33.0), (59.0, 63.0))):
                self.en_banda(fase["desde_min"], lo, hi, semilla)

    def test_borde_paralelo_dos_fases_simultaneas(self):
        """CONTRATO: un stream con dos fases que arrancan en el mismo minuto (en [61,5;64,5]) y
        siguen hasta el final, en servidores distintos."""
        for semilla in self.SEMILLAS_B:
            esc, ver = self.espejo_b(semilla)
            a, b = self.fases_de_borde(ver)[B_PARALELO]["fases"]
            self.assertEqual(a["desde_min"], b["desde_min"])
            self.assertEqual(a["hasta_min"], b["hasta_min"])
            self.assertNotEqual((a["host"], a["ip"]), (b["host"], b["ip"]))
            self.en_banda(a["desde_min"], 61.5, 64.5, semilla)

    def test_borde_ip_compartida_recomienda_dominio_sin_colateral(self):
        """CONTRATO: exclusiva -> compartida -> exclusiva (desde en [45;47], [51,5;52,5], +[0,8;1,2]);
        la del medio aloja 5 a 8 legitimos de otros registrables, recomienda 'dominio' y ninguno de
        esos ajenos figura como pirata (0 colateral)."""
        for semilla in self.SEMILLAS_B:
            esc, ver = self.espejo_b(semilla)
            piratas = set(ver["dominios_piratas"])
            f = self.fases_de_borde(ver)[B_COMPARTIDA]["fases"]
            self.assertEqual([x["bloqueo_recomendado"] for x in f], ["ip", "dominio", "ip"])
            ajenos = [d for d in esc["dns_pasivo"][f[1]["ip"]] if d != f[1]["host"]]
            self.assertTrue(5 <= len(ajenos) <= 8)
            self.assertFalse(set(ajenos) & piratas)
            self.assertFalse({registrable(x) for x in ajenos} & {registrable(f[1]["host"])})
            self.en_banda(f[0]["desde_min"], 45.0, 47.0)
            self.en_banda(f[1]["desde_min"], 51.5, 52.5)
            self.en_banda(f[2]["desde_min"] - f[1]["desde_min"], 0.8, 1.2)

    def test_borde_inquilinos_de_un_mismo_registrable(self):
        """CONTRATO (borde nuevo): la IP del pirata (organizacion neutra) aloja vivo.R, host del
        stream y de la pagina, y 1 a 3 subdominios de OTROS duenos de R. La verdad recomienda
        'dominio', solo vivo.R es pirata, los otros quedan legitimos y uno tiene reclamo automatico.
        La regla nueva (escrita a mano en este test) da 'dominio'; la vieja de foto1/foto2 da 'ip'."""
        for semilla in self.SEMILLAS_B:
            esc, ver = self.espejo_b(semilla)
            s = self.fases_de_borde(ver)[B_INQUILINOS]
            self.assertEqual((s["clase"], len(s["fases"])), ("pirata", 1))
            f = s["fases"][0]
            host, ip = f["host"], f["ip"]
            r = registrable(host)
            self.assertEqual(host, "vivo." + r)
            doms = esc["dns_pasivo"][ip]
            otros = [d for d in doms if d != host]
            self.assertTrue(1 <= len(otros) <= 3, (semilla, doms))
            self.assertTrue(all(registrable(d) == r and d != r and not d.startswith("www.") for d in otros))
            self.assertNotIn(r, doms)
            piratas = set(ver["dominios_piratas"])
            self.assertIn(host, piratas)
            self.assertFalse(set(otros) & piratas)
            # Ningun otro lugar del escenario usa R (no hay un sitio pirata "de arriba").
            todos = {d for ds in esc["dns_pasivo"].values() for d in ds}
            self.assertEqual({d for d in todos if registrable(d) == r}, set(doms))
            org = esc["asn"][str(esc["ip_asn"][ip])]
            for palabra in ("cdn", "compartid", "shared"):
                self.assertNotIn(palabra, org.lower())
            dets = {d["id"]: d for d in esc["detecciones"]}
            self.assertGreaterEqual(len(f["detecciones"]), 3)
            for i in f["detecciones"]:
                pagina_host = urlsplit(dets[i]["pagina"]).hostname
                self.assertEqual(pagina_host, host)
                self.assertEqual(urlsplit(dets[i]["stream_url"]).hostname, host)
                self.assertEqual(regla_nueva_recomienda(host, pagina_host, doms, org), "dominio")
                self.assertEqual(regla_vieja_recomienda(host, pagina_host, doms), "ip")
            self.assertEqual(f["bloqueo_recomendado"], "dominio")
            self.en_banda(f["desde_min"], 24.0, 28.0, semilla)
            self.assertTrue(any(rc["dominio"] in otros for rc in esc["reclamos_automaticos"]), semilla)

    def test_los_minutos_de_borde_cambian_con_la_semilla(self):
        """CONTRATO: cada semilla sortea sus minutos de borde (dentro de las bandas): las tres
        semillas de ensayo no comparten la misma grilla de tiempos."""
        grillas = []
        for semilla in self.SEMILLAS_B:
            esc, ver = self.espejo_b(semilla)
            grillas.append(tuple(f["desde_min"] for s in self.fases_de_borde(ver) for f in s["fases"]))
        self.assertEqual(len(set(grillas)), len(grillas), grillas)
        # Y no solo un minuto: en cada borde con banda hay al menos dos semillas que difieren.
        for pos in (B_TURNO_ANTES, B_TURNO_DESPUES, B_MUDANZA_TURNO, B_ULTIMOS, B_RAPIDAS, B_VUELVE,
                    B_PARALELO, B_COMPARTIDA, B_INQUILINOS):
            por_semilla = set()
            for semilla in self.SEMILLAS_B:
                _, ver = self.espejo_b(semilla)
                por_semilla.add(tuple(f["desde_min"] for f in self.fases_de_borde(ver)[pos]["fases"]))
            self.assertGreater(len(por_semilla), 1, pos)

    def test_recomendacion_coincide_con_la_regla_de_colateral(self):
        """CONTRATO: en cada fase de borde, 'ip' <=> la IP es exclusiva del pirata (sin ajenos);
        'dominio' <=> la IP aloja algun ajeno. Asi la verdad concuerda con la regla pura."""
        for semilla in self.SEMILLAS_B:
            esc, ver = self.espejo_b(semilla)
            piratas = set(ver["dominios_piratas"])
            for s in self.fases_de_borde(ver):
                for f in s["fases"]:
                    ajenos = [d for d in esc["dns_pasivo"][f["ip"]] if d != f["host"] and d not in piratas]
                    esperado = "dominio" if ajenos else "ip"
                    self.assertEqual(f["bloqueo_recomendado"], esperado, (semilla, f["host"]))

    def test_determinismo_con_bordes(self):
        """CONTRATO: misma semilla -> mismos bytes; distinta semilla -> distinto."""
        a = self.espejo_b(11)
        b = self.espejo_b(11)
        c = self.espejo_b(23)
        self.assertEqual(json.dumps(a), json.dumps(b))
        self.assertNotEqual(json.dumps(a), json.dumps(c))

    def test_ids_consecutivos_y_capturas_validas_con_bordes(self):
        """CONTRATO: con bordes, los ids siguen siendo D-0001.. y las capturas 64 bytes/0x47 unicas."""
        esc, ver = self.espejo_b(37)
        dets = esc["detecciones"]
        self.assertEqual([d["id"] for d in dets], ["D-%04d" % n for n in range(1, len(dets) + 1)])
        self.assertEqual([d["minuto"] for d in dets], sorted(d["minuto"] for d in dets))
        vistos = set()
        for d in dets:
            raw = base64.b64decode(d["captura"]["contenido_b64"], validate=True)
            self.assertEqual((len(raw), raw[0]), (64, 0x47))
            vistos.add(raw)
        self.assertEqual(len(vistos), len(dets))

    def test_formato_de_la_verdad_igual_al_oficial(self):
        """CONTRATO (g): con bordes la verdad conserva exactamente las claves de la practica (en
        verdad, en cada stream y en cada fase); no se agregan campos que el verificador no conoce."""
        esc, ver = self.espejo_b(23)
        self.assertEqual(list(ver), list(self.orig_ver))
        claves_s = list(self.orig_ver["streams"][0])
        claves_f = list(self.orig_ver["streams"][0]["fases"][0])
        for s in ver["streams"]:
            self.assertEqual(list(s), claves_s)
            for f in s["fases"]:
                self.assertEqual(list(f), claves_f)
        self.assertEqual(list(esc), list(self.orig_esc))
        for r in esc["reclamos_automaticos"]:
            self.assertEqual(list(r), list(self.orig_esc["reclamos_automaticos"][0]))


class TestVerificadorDetectaVioracionesDeBordes(BaseBordes):
    """El verificador de coherencia FALLA cuando se rompe cada contrato de borde."""

    def setUp(self):
        self.esc, self.ver = self.espejo_b(11)
        self.dets = {d["id"]: d for d in self.esc["detecciones"]}

    def errores(self):
        return ee.verificar_coherencia(self.esc, self.ver, self.orig_esc, self.orig_ver, True, True)

    def mover_fase(self, fase, nuevo_desde):
        """Corre la primera deteccion de la fase (y su desde) a otro minuto, coherente."""
        d0 = min((self.dets[i] for i in fase["detecciones"]), key=lambda x: x["minuto"])
        d0["minuto"] = nuevo_desde
        d0["captura"]["capturada_min"] = nuevo_desde
        fase["desde_min"] = nuevo_desde

    def test_base_limpia(self):
        self.assertEqual(self.errores(), [])

    def test_falta_el_borde_del_turno_antes(self):
        self.mover_fase(self.fases_de_borde(self.ver)[B_TURNO_ANTES]["fases"][0], 48.0)
        self.assertTrue(any("borde turno" in e for e in self.errores()))

    def test_falta_el_borde_del_turno_despues(self):
        # La mudanza-turno tambien tiene un desde en (50 ; 50,2]: el contrato tiene que exigir la
        # filtracion NUEVA de una sola fase, no cualquier fase.
        self.mover_fase(self.fases_de_borde(self.ver)[B_TURNO_DESPUES]["fases"][0], 52.0)
        self.assertTrue(any("borde turno" in e for e in self.errores()))

    def test_mudanza_turno_lejos_del_cambio_de_turno(self):
        # La mutacion del revisor: las mudanzas pasan a 45 y 55, lejos del minuto 50.
        f = self.fases_de_borde(self.ver)[B_MUDANZA_TURNO]["fases"]
        f[0]["hasta_min"] = 45.0
        self.mover_fase(f[1], 45.0)
        f[1]["hasta_min"] = 55.0
        self.mover_fase(f[2], 55.0)
        e = self.errores()
        self.assertTrue(any("mudanza-turno" in x for x in e), e)

    def test_mudanza_turno_con_dos_sesiones(self):
        # Mismo cambio de minutos, pero la fase de despues pasa a OTRA sesion: ya no es "la misma".
        f = self.fases_de_borde(self.ver)[B_MUDANZA_TURNO]["fases"]
        for i in f[2]["detecciones"]:
            self.dets[i]["marca_de_agua_extraida"] = self.dets[i]["marca_de_agua_extraida"][:-6] + "999999"
        e = self.errores()
        self.assertTrue(any("mudanza-turno" in x for x in e), e)

    def test_falta_la_fase_de_duracion_cero(self):
        fin = float(self.esc["partido"]["fin_min"])
        for s in self.fases_de_borde(self.ver):
            for f in s["fases"]:
                if f["desde_min"] == fin and f["hasta_min"] == fin:
                    f["desde_min"] = fin - 0.5  # deja de ser duracion cero
        self.assertTrue(any("duracion cero" in e for e in self.errores()))

    def test_falta_el_paralelo(self):
        self.ver["streams"].remove(self.fases_de_borde(self.ver)[B_PARALELO])
        self.assertTrue(any("paralelo" in e for e in self.errores()))

    def test_un_ajeno_marcado_como_pirata_rompe_la_ip_compartida(self):
        f = self.fases_de_borde(self.ver)[B_COMPARTIDA]["fases"][1]
        self.ver["dominios_piratas"].extend(d for d in self.esc["dns_pasivo"][f["ip"]] if d != f["host"])
        self.assertTrue(any("IP compartida" in e or "sin ser host" in e for e in self.errores()))

    def test_solape_en_un_stream_base_no_se_relaja_con_bordes(self):
        # (c) Un stream de la practica con fases que se tocan: con --bordes tiene que seguir fallando.
        s = next(s for s in self.ver["streams"][:len(self.orig_ver["streams"])] if len(s["fases"]) > 1)
        s["fases"][1]["desde_min"] = s["fases"][0]["hasta_min"]
        self.assertTrue(any("solapadas" in e and s["id"] in e for e in self.errores()))

    def test_piso_de_minuto_en_un_stream_base_no_se_relaja_con_bordes(self):
        s = self.ver["streams"][0]
        s["fases"][0]["desde_min"] = 0.2
        self.assertTrue(any("fuera de rango" in e and s["id"] in e for e in self.errores()))

    def test_el_paralelo_de_borde_sigue_admitido(self):
        # Contracara de (c): el solape del borde paralelo no es un error.
        self.assertFalse(any("solapadas" in e for e in self.errores()))

    def test_inquilino_marcado_como_pirata(self):
        f = self.fases_de_borde(self.ver)[B_INQUILINOS]["fases"][0]
        otro = next(d for d in self.esc["dns_pasivo"][f["ip"]] if d != f["host"])
        self.ver["dominios_piratas"].append(otro)
        self.assertTrue(any("inquilinos" in e for e in self.errores()))

    def test_inquilinos_con_la_pagina_en_el_registrable(self):
        # Si la pagina vive en R (no en el subdominio del pirata), los otros nombres de R serian
        # propios por la regla nueva: el borde deja de ser el que se quiere ensayar.
        f = self.fases_de_borde(self.ver)[B_INQUILINOS]["fases"][0]
        r = registrable(f["host"])
        for i in f["detecciones"]:
            self.dets[i]["pagina"] = "https://%s/en-vivo" % r
        self.assertTrue(any("inquilinos" in e for e in self.errores()))

    def test_inquilinos_recomienda_ip(self):
        f = self.fases_de_borde(self.ver)[B_INQUILINOS]["fases"][0]
        f["bloqueo_recomendado"] = "ip"
        self.assertTrue(any("inquilinos" in e for e in self.errores()))

    def test_inquilino_de_otro_registrable_no_se_admite_como_hermano(self):
        # (c) La excepcion "comparte base con un pirata pero no es pirata" vale solo para los
        # inquilinos del borde: un nombre asi en una IP de la practica sigue siendo un error.
        piratas = set(self.ver["dominios_piratas"])
        fase_base = self.ver["streams"][0]["fases"][0]  # un stream pirata de la practica
        ip_base = fase_base["ip"]
        intruso = "recetas." + registrable(fase_base["host"])
        self.assertNotIn(intruso, piratas)
        self.esc["dns_pasivo"][ip_base].append(intruso)
        self.assertTrue(any(intruso in e and "comparte base" in e for e in self.errores()))

    def test_falta_el_reclamo_del_inquilino(self):
        f = self.fases_de_borde(self.ver)[B_INQUILINOS]["fases"][0]
        otros = set(self.esc["dns_pasivo"][f["ip"]]) - {f["host"]}
        self.esc["reclamos_automaticos"] = [r for r in self.esc["reclamos_automaticos"] if r["dominio"] not in otros]
        self.assertTrue(any("inquilinos" in e and "reclamo" in e for e in self.errores()))


class TestCLI(BaseEspejo):
    def correr(self, *args, cwd=None):
        return subprocess.run([sys.executable, "-I", str(SCRIPT), "--repo-desafio", str(REPO_DESAFIO), *args],
                              capture_output=True, text=True, cwd=cwd)

    def test_C8_la_cli_escribe_ambos_archivos_con_el_mismo_resultado_que_la_funcion(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = self.correr("--semilla", "7", "--salida", os.path.join(tmp, "x", "y"), "--trampas", cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            esc = cargar(Path(tmp) / "x" / "y" / "escenario.json")
            ver = cargar(Path(tmp) / "x" / "y" / "verdad.json")
            esperado = self.espejo(7, True)
            self.assertEqual((esc, ver), esperado)
            texto = (Path(tmp) / "x" / "y" / "escenario.json").read_text(encoding="utf-8")
            self.assertTrue(texto.endswith("}\n"))

    def test_C8_misma_semilla_mismos_bytes_en_dos_corridas(self):
        with tempfile.TemporaryDirectory() as tmp:
            for n in ("a", "b"):
                self.assertEqual(self.correr("--semilla", "2026", "--salida", os.path.join(tmp, n)).returncode, 0)
            for nombre in ("escenario.json", "verdad.json"):
                self.assertEqual((Path(tmp) / "a" / nombre).read_bytes(), (Path(tmp) / "b" / nombre).read_bytes())

    def test_C8_no_escribe_nada_si_las_comprobaciones_fallan(self):
        original = ee.verificar_coherencia
        ee.verificar_coherencia = lambda *a, **k: ["error de prueba"]
        try:
            with tempfile.TemporaryDirectory() as tmp:
                salida = Path(tmp) / "no"
                codigo = ee.main(["--repo-desafio", str(REPO_DESAFIO), "--salida", str(salida)])
                self.assertEqual(codigo, 1)
                self.assertFalse(salida.exists())
        finally:
            ee.verificar_coherencia = original

    def test_cli_bordes_escribe_y_coincide_con_la_funcion(self):
        """CONTRATO (CLI): --trampas --bordes escribe ambos archivos iguales a la funcion."""
        with tempfile.TemporaryDirectory() as tmp:
            r = self.correr("--semilla", "11", "--salida", os.path.join(tmp, "b"), "--trampas", "--bordes")
            self.assertEqual(r.returncode, 0, r.stderr)
            esc = cargar(Path(tmp) / "b" / "escenario.json")
            ver = cargar(Path(tmp) / "b" / "verdad.json")
            esperado = ee.generar(copy.deepcopy(self.orig_esc), copy.deepcopy(self.orig_ver), 11, True, True)
            self.assertEqual((esc, ver), esperado)

    def test_cli_sin_bordes_bytes_iguales_a_los_de_foto1(self):
        """CONTRATO (CLI): la CLI sin --bordes escribe los mismos bytes que el generador de foto1
        (SHA-256 fijados en SHA_FOTO1), para 7 y 2026, con y sin --trampas."""
        with tempfile.TemporaryDirectory() as tmp:
            for (semilla, trampas), (sha_esc, sha_ver) in SHA_FOTO1.items():
                with self.subTest(semilla=semilla, trampas=trampas):
                    salida = os.path.join(tmp, "%d-%s" % (semilla, trampas))
                    args = ["--semilla", str(semilla), "--salida", salida] + (["--trampas"] if trampas else [])
                    r = self.correr(*args)
                    self.assertEqual(r.returncode, 0, r.stderr)
                    self.assertEqual(sha256(Path(salida) / "escenario.json"), sha_esc)
                    self.assertEqual(sha256(Path(salida) / "verdad.json"), sha_ver)

    @unittest.skipUnless(Path("/usr/bin/python3").exists(), "no hay /usr/bin/python3 para comparar")
    def test_cli_bordes_mismos_bytes_en_este_python_y_en_usr_bin_python3(self):
        """CONTRATO (e): con --trampas --bordes la salida es determinista por semilla e igual
        byte a byte en el Python que corre las pruebas y en /usr/bin/python3 (3.9 en macOS)."""
        with tempfile.TemporaryDirectory() as tmp:
            for semilla in SEMILLAS_BORDES:
                with self.subTest(semilla=semilla):
                    salidas = []
                    for n, py in enumerate((sys.executable, "/usr/bin/python3")):
                        salida = Path(tmp) / ("%d-%d" % (semilla, n))
                        r = subprocess.run([py, "-I", str(SCRIPT), "--repo-desafio", str(REPO_DESAFIO),
                                            "--semilla", str(semilla), "--salida", str(salida),
                                            "--trampas", "--bordes"], capture_output=True, text=True)
                        self.assertEqual(r.returncode, 0, (py, r.stderr))
                        salidas.append(salida)
                    for nombre in ("escenario.json", "verdad.json"):
                        self.assertEqual((salidas[0] / nombre).read_bytes(), (salidas[1] / nombre).read_bytes())


if __name__ == "__main__":
    unittest.main()
