"""Contratos de la orden marco (`marca/marco.py`, ESPEC sección 1).

- M1 Interfaz: `TITULO_CASILLA`, `armar`, `huella`, `mensaje_firma`, `a_texto` con las firmas acordadas.
- M2 `armar` devuelve exactamente las claves de la especificación, con los datos tal como el motor los guarda
     (partido de `GET /partido`, proveedores de `GET /proveedores`).
- M3 Los seis renglones (`lineas`) son el texto de la especificación, ya con los datos.
- M4 `condiciones_seguimiento` son los renglones de la especificación, sin el título de la casilla.
- M5 Un dato que falta se dice de forma neutra («no informado») y no rompe.
- M6 Minutos sin decimales cuando son enteros (y con coma si no).
- M7 La señal oficial excluye las marcas de los licenciatarios.
- M8 `huella` = sha256 del JSON canónico (marca/canon.py); cambia si cambia el seguimiento o cualquier renglón.
- M9 `mensaje_firma` = `MARCO|partido|huella|juez|S1` o `S0`, igual que `sello.mensaje_marco`.
- M10 `a_texto`: `lineas` y, solo con seguimiento, el título de la casilla y las condiciones.
- M11 Pureza: no toca la entrada, mismo resultado con la misma entrada, contenido serializable.
"""
from __future__ import annotations

import copy
import hashlib
import inspect
import json
import unittest

from marca import canon, marco, sello

PARTIDO = {
    "id": "practica-01", "nombre": "Partido de práctica — Club Ficticio del Norte vs. Deportivo Ejemplo",
    "titular_derechos": "Liga Profesional Ficticia", "inicio_iso": "2026-11-11T18:00:00-03:00", "fin_min": 105,
    "marcas_de_agua_validas": [
        {"prefijo": "LP26-PRA-OFI", "origen": "Señal oficial del titular (plataforma propia)"},
        {"prefijo": "LP26-PRA-LIC-NORTE", "origen": "Licenciatario autorizado: Canal Norte TV (ficticio)"}],
    "licenciatarios": [{"nombre": "Canal Norte TV (ficticio)", "prefijo_marca": "LP26-PRA-LIC-NORTE",
                        "dominios_autorizados": ["canalnorte.test", "envivo.canalnorte.test"]}],
}
PROVEEDORES = [
    {"id": "aurora", "nombre": "Conectividad Aurora (ficticio)", "tamano": "grande", "clientes": 3800000,
     "capacidades": ["ip", "dominio"], "ordenes": "/proveedores/aurora/ordenes"},
    {"id": "valle", "nombre": "FibraValle (ficticio)", "tamano": "chico", "clientes": 140000,
     "capacidades": ["dominio"], "ordenes": "/proveedores/valle/ordenes"},
]
JUEZ = {"juez_id": "jueza-laura-ficticia", "nombre": "Dra. Laura Ficticia", "juzgado_id": "jg-centro-3",
        "juzgado": "Juzgado de Garantías N.º 3 (ficticio) — Distrito Judicial Centro"}
TURNO = {"desde_min": -60, "hasta_min": 50}

LINEAS = [
    "Partido: Partido de práctica — Club Ficticio del Norte vs. Deportivo Ejemplo. Titular de los derechos: "
    "Liga Profesional Ficticia.",
    # Ronda 3, C11 (N3): renglón 2 reescrito.
    "Esta orden vale durante mi turno en este partido: desde antes del inicio hasta el minuto 50. Todo bloqueo que se "
    "ordene bajo ella vence, como máximo, al final del partido (minuto 105).",
    # Ronda 3b, C15: renglones 3 y 4 en su versión única.
    "Solo se protege la señal del partido: la oficial (marcas LP26-PRA-OFI) y la de cada licenciatario cuando se "
    "transmite fuera de sus dominios (marcas LP26-PRA-LIC-NORTE). Nunca se bloquea a un licenciatario en sus "
    "dominios: Canal Norte TV (ficticio) en canalnorte.test y envivo.canalnorte.test.",
    "Cada bloqueo necesita un expediente con evidencia sellada (la captura con su hash, la marca verificada y el "
    "servidor con host, IP y red) y mi firma, servidor por servidor, salvo que en esta orden autorice el "
    "seguimiento de la misma filtración.",
    "Si la IP es compartida o hay dudas, solo se bloquea el nombre del stream. Apartarse de esa regla exige mi "
    "fundamento escrito.",
    "Los reclamos se verifican y todo levantamiento lleva mi firma.",
]
CONDICIONES = [
    # Ronda 3b, C15: condiciones [0] y [1] en su versión única.
    "Si firmo un bloqueo con «Firmar y seguir a esta filtración» y esa misma filtración (la misma sesión de la marca "
    "de agua) aparece en otro servidor, la plataforma amplía el bloqueo sin esperar una firma nueva, solo si se "
    "cumple todo esto:",
    "La evidencia nueva está completa y sellada, y el bloqueo nuevo no alcanza a sitios ajenos: si el servidor nuevo "
    "comparte la IP con sitios ajenos, se bloquea solo el nombre del stream.",
    "Estoy de turno y con la plataforma abierta.",
    "Cada ampliación se me avisa en el momento, sale identificada como ampliación (su número empieza con amp-) y "
    "puedo frenarla o levantarla.",
    "Vence al final del partido. Fuera de estas condiciones, el pedido vuelve a mí.",
]


def armar(seguimiento=True, **cambios):
    datos = {"partido": PARTIDO, "proveedores": PROVEEDORES, "juez": JUEZ, "turno": TURNO}
    datos.update(cambios)
    return marco.armar(datos["partido"], datos["proveedores"], datos["juez"], datos["turno"], seguimiento)


class Interfaz(unittest.TestCase):
    def test_m1_firmas(self):
        self.assertEqual(marco.TITULO_CASILLA, "Autorizo el seguimiento de la misma filtración")
        self.assertEqual(list(inspect.signature(marco.armar).parameters),
                         ["partido", "proveedores", "juez", "turno", "seguimiento"])
        self.assertEqual(list(inspect.signature(marco.huella).parameters), ["contenido"])
        self.assertEqual(list(inspect.signature(marco.mensaje_firma).parameters),
                         ["partido_id", "huella", "juez_id", "seguimiento"])
        self.assertEqual(list(inspect.signature(marco.a_texto).parameters), ["contenido"])


class Contenido(unittest.TestCase):
    def test_m2_claves_exactas(self):
        c = armar()
        self.assertEqual(set(c), {"version", "partido", "marcas_validas", "licenciatarios", "proveedores", "juez",
                                  "turno", "seguimiento", "lineas", "condiciones_seguimiento"})
        self.assertEqual(c["version"], 1)
        self.assertEqual(c["partido"], {"id": "practica-01", "nombre": PARTIDO["nombre"],
                                        "titular": "Liga Profesional Ficticia", "fin_min": 105})
        self.assertEqual(c["licenciatarios"], [{"nombre": "Canal Norte TV (ficticio)",
                                                "prefijo_marca": "LP26-PRA-LIC-NORTE",
                                                "dominios": ["canalnorte.test", "envivo.canalnorte.test"]}])
        self.assertEqual(c["proveedores"], [
            {"id": "aurora", "nombre": "Conectividad Aurora (ficticio)", "capacidades": ["ip", "dominio"]},
            {"id": "valle", "nombre": "FibraValle (ficticio)", "capacidades": ["dominio"]}])
        self.assertEqual(c["juez"], JUEZ)
        self.assertEqual(c["turno"], {"desde_min": -60, "hasta_min": 50})
        self.assertIs(c["seguimiento"], True)
        self.assertIs(armar(False)["seguimiento"], False)

    def test_m3_lineas(self):
        self.assertEqual(armar()["lineas"], LINEAS)
        self.assertEqual(armar(False)["lineas"], LINEAS)

    def test_m4_condiciones(self):
        c = armar()["condiciones_seguimiento"]
        self.assertEqual(c, CONDICIONES)
        self.assertNotIn(marco.TITULO_CASILLA, c)
        self.assertEqual(marco.CONDICIONES_SEGUIMIENTO, CONDICIONES)

    def test_m5_faltan_datos(self):
        c = marco.armar({}, [], {}, {}, False)
        self.assertEqual(c["lineas"][0], "Partido: no informado. Titular de los derechos: no informado.")
        self.assertEqual(c["lineas"][1], "Esta orden vale durante mi turno en este partido: desde el minuto no "
                                         "informado hasta el minuto no informado. Todo bloqueo que se ordene bajo "
                                         "ella vence, como máximo, al final del partido (minuto no informado).")
        # C15: sin licenciatarios, el renglón 3 nombra solo la señal oficial.
        self.assertEqual(c["lineas"][2], "Solo se protege la señal oficial del partido (marcas no informadas).")
        self.assertEqual(c["lineas"][3:], LINEAS[3:])
        self.assertEqual(c["partido"], {"id": None, "nombre": None, "titular": None, "fin_min": None})
        self.assertEqual(c["marcas_validas"], [])
        self.assertEqual(c["licenciatarios"], [])
        # None en lugar de dict/lista tampoco rompe.
        self.assertEqual(marco.armar(None, None, None, None, True)["lineas"][0], c["lineas"][0])

    def test_m5_licenciatario_incompleto(self):
        p = dict(PARTIDO, titular_derechos=None, licenciatarios=[{"prefijo_marca": "X-LIC"},
                                                                {"nombre": "Canal Sur", "dominios_autorizados": []}])
        lineas = armar(partido=p)["lineas"]
        self.assertTrue(lineas[0].endswith("Titular de los derechos: no informado."))
        self.assertTrue(lineas[2].endswith("en sus dominios: licenciatario sin nombre informado en dominios no "
                                           "informados; Canal Sur en dominios no informados."), lineas[2])

    def test_m6_minutos(self):
        l2 = armar(turno={"desde_min": 50.0, "hasta_min": 240.0}, partido=dict(PARTIDO, fin_min=105.0))["lineas"][1]
        self.assertIn("desde el minuto 50 hasta el final del partido (minuto 105)", l2)
        self.assertIn("(minuto 105)", l2)
        l2 = armar(turno={"desde_min": 49.5, "hasta_min": 50})["lineas"][1]
        self.assertIn("desde el minuto 49,5 hasta el minuto 50.", l2)
        l2 = armar(turno={"desde_min": True, "hasta_min": "x"})["lineas"][1]
        self.assertIn("desde el minuto no informado hasta el minuto no informado.", l2)

    def test_m7_senal_oficial(self):
        p = dict(PARTIDO, marcas_de_agua_validas=PARTIDO["marcas_de_agua_validas"] + [{"prefijo": "LP26-PRA-OFI2"}])
        c = armar(partido=p)
        self.assertEqual(c["marcas_validas"], ["LP26-PRA-OFI", "LP26-PRA-OFI2"])
        self.assertIn("(marcas LP26-PRA-OFI, LP26-PRA-OFI2)", c["lineas"][2])
        self.assertNotIn("LIC", c["lineas"][2].split(" y la de cada licenciatario")[0])


class HuellaYFirma(unittest.TestCase):
    def test_m8_huella_es_sha256_del_canonico(self):
        c = armar()
        esperado = hashlib.sha256(json.dumps(c, sort_keys=True, ensure_ascii=False,
                                             separators=(",", ":")).encode("utf-8")).hexdigest()
        self.assertEqual(marco.huella(c), esperado)
        self.assertEqual(marco.huella(c), canon.huella(c))

    def test_m8_huella_cambia_con_el_seguimiento_y_con_el_texto(self):
        self.assertNotEqual(marco.huella(armar(True)), marco.huella(armar(False)))
        c = armar()
        c2 = copy.deepcopy(c)
        c2["lineas"][4] = c2["lineas"][4].replace("solo", "también")
        self.assertNotEqual(marco.huella(c), marco.huella(c2))
        self.assertEqual(marco.huella(armar()), marco.huella(armar()))

    def test_m9_mensaje_de_firma(self):
        h = marco.huella(armar())
        self.assertEqual(marco.mensaje_firma("practica-01", h, "jueza-laura-ficticia", True),
                         f"MARCO|practica-01|{h}|jueza-laura-ficticia|S1")
        self.assertEqual(marco.mensaje_firma("practica-01", h, "jueza-laura-ficticia", False),
                         f"MARCO|practica-01|{h}|jueza-laura-ficticia|S0")
        for seg in (True, False):
            self.assertEqual(marco.mensaje_firma("p", h, "j", seg), sello.mensaje_marco("p", h, "j", seg))


class Texto(unittest.TestCase):
    def test_m10_con_seguimiento(self):
        self.assertEqual(marco.a_texto(armar(True)), LINEAS + [marco.TITULO_CASILLA] + CONDICIONES)

    def test_m10_sin_seguimiento(self):
        self.assertEqual(marco.a_texto(armar(False)), LINEAS)

    def test_m10_usa_el_contenido_tal_cual(self):
        c = armar(True)
        c["lineas"] = ["uno", "dos"]
        c["condiciones_seguimiento"] = ["tres"]
        self.assertEqual(marco.a_texto(c), ["uno", "dos", marco.TITULO_CASILLA, "tres"])
        c["seguimiento"] = "sí"  # solo true cuenta como seguimiento
        self.assertEqual(marco.a_texto(c), ["uno", "dos"])


class Pureza(unittest.TestCase):
    def test_m11_no_toca_la_entrada_y_es_determinista(self):
        entradas = [copy.deepcopy(x) for x in (PARTIDO, PROVEEDORES, JUEZ, TURNO)]
        c = marco.armar(*entradas, True)
        self.assertEqual(entradas, [PARTIDO, PROVEEDORES, JUEZ, TURNO])
        c["licenciatarios"][0]["dominios"].append("otro.test")
        c["proveedores"][0]["capacidades"].append("x")
        self.assertEqual(entradas, [PARTIDO, PROVEEDORES, JUEZ, TURNO])
        self.assertEqual(armar(), marco.armar(PARTIDO, PROVEEDORES, JUEZ, TURNO, True))
        canon.canonico(armar())  # serializable

    def test_m11_a_texto_devuelve_una_copia(self):
        c = armar()
        t = marco.a_texto(c)
        t.append("x")
        self.assertEqual(c["lineas"], LINEAS)


if __name__ == "__main__":
    unittest.main()
