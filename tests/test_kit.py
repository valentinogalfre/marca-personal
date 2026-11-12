"""Contratos del kit del proveedor (`marca/kit.py`, ESPEC 5.1 y 5.2, ADENDA-3 punto D).

Estas líneas se pegan en un router. Cada prueba nombra el contrato que protege:

- K1  Firma: seis parámetros posicionales (las llamadas viejas siguen andando) y `vigente`, `hora_vence`,
      `fecha_vence` solo por nombre.
- K2  Forma de cada entrada: `equipo`, `quitar` y `nota` siempre; `aplicar` si y solo si la orden rige.
- K3  Una orden que ya no rige no trae `aplicar`, `preparar` ni `vencer`, y la nota lo dice.
- K4  El comentario lleva la hora absoluta del vencimiento; la nota avisa que el timeout cuenta desde que se pega.
- K5  MikroTik por IP: regla antes de fasttrack (place-before=0), corte de conexiones abiertas, aviso de reinicio.
- K6  IPv6 va por `/ipv6 firewall` y por un set `ipv6_addr` con `ip6 daddr`; IPv4 nunca usa los de IPv6.
- K7  nftables con tabla propia (`inet bloqueo_judicial`), comandos exactos de la especificación.
- K8  Dominio en MikroTik: NXDOMAIN + vaciado de caché, línea de vencimiento que no depende del formato de fecha,
      la nota da las dos formas de fecha, y quitar borra también la tarea programada.
- K9  Unbound dice la verdad sobre el alcance (corta el nombre y sus subdominios); MikroTik y BIND, solo el exacto.
- K10 Ningún texto promete que un bloqueo por DNS se quita solo.
- K11 BIND (RPZ) por nsupdate, con la zona y response-policy para preparar.
- K12 La leyenda nueva va en cada equipo de una orden que rige.
- K13 Defensa: con un objetivo (o tipo) inválido, una sola entrada que lo dice y ninguna línea de comando (sin
      repetir el objetivo); con expediente, sello, hora, fecha o minutos fuera de lo esperado → lista vacía.
      Los rangos de documentación (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24, 2001:db8::/32) siguen saliendo.
- K14 Nada de la entrada llega a un comando sin validar: los comandos son ASCII imprimible y el objetivo sale
      en forma canónica (minúsculas, sin punto final, IP canónica).
- K15 Timeout = lo que falta hasta el vencimiento, redondeado para arriba, como mínimo 1 minuto.
- L1  Las cuatro listas del proveedor empiezan con los dos comentarios pedidos (`#`, o `;` en la zona RPZ).
- L2  Cada lista trae solo los objetivos válidos de su tipo, sin repetir y en orden fijo.
- L3  `unbound_conf` produce exactamente la línea que escribe el cliente de referencia.
- L4  `zona_rpz`: $TTL 30, SOA con serial = v, NS localhost. y `<host> CNAME .`.
- L5  Listas vacías (o vista incompleta) dan un texto válido solo con la cabecera.
- L6  La cabecera no se puede usar para colar líneas (nombre del proveedor con saltos de línea).
- L7  Venenos en los objetivos (salto de línea, «;flush ruleset», comillas, zona «%eth0», espacio): ninguna
      línea de las cuatro salidas se sale de la forma esperada, y un comentario de cabecera adicional dice
      cuántos se descartaron («# N objetivo(s) descartado(s) por formato inválido.», solo si N > 0).
"""
from __future__ import annotations

import importlib.util
import inspect
import ipaddress
import re
import unittest
from pathlib import Path

from marca import kit as K

RAIZ = Path(__file__).resolve().parent.parent
EXP, SELLO = "EXP-2026-000001", "a1b2c3d4e5f6a7b8"
LEYENDA = ("Probá estas líneas en tu equipo antes del partido. Lo que obliga es la orden (objetivo y "
           "vencimiento); las líneas son una ayuda.")
NO_RIGE = "Esta orden ya no rige. Si la aplicaste, quitala."
NOTA_UNBOUND = ("Corta ese nombre y los que cuelgan de él (sus subdominios). No toca el dominio de arriba ni a sus "
                "nombres hermanos. Vive en memoria: un reload o un reinicio lo borra; no vence solo: usá la lista "
                "del proveedor o corré la línea de quitar al final.")
CAMPOS = {"equipo", "preparar", "aplicar", "quitar", "vencer", "nota"}
COMANDOS = ("preparar", "aplicar", "quitar", "vencer")


def ip(objetivo="203.0.113.10", **kw):
    kw.setdefault("hora_vence", "19:45")
    return K.kit("ip", objetivo, 105, 20.4, EXP, SELLO, **kw)


def dom(objetivo="s1.pirata.test", **kw):
    kw.setdefault("hora_vence", "19:45")
    kw.setdefault("fecha_vence", "2026-11-12")
    return K.kit("dominio", objetivo, 105, 20.4, EXP, SELLO, **kw)


def equipo(entradas, prefijo):
    hallados = [e for e in entradas if e["equipo"].startswith(prefijo)]
    assert len(hallados) == 1, (prefijo, [e["equipo"] for e in entradas])
    return hallados[0]


def cargar_cliente():
    ruta = RAIZ / "herramientas" / "cliente_proveedor.py"
    spec = importlib.util.spec_from_file_location("cliente_proveedor_ref", str(ruta))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Firma(unittest.TestCase):
    def test_k1_seis_posicionales_y_tres_por_nombre(self):
        p = inspect.signature(K.kit).parameters
        self.assertEqual(list(p)[:6], ["tipo", "objetivo", "vence_min", "minuto_actual", "expediente", "sello"])
        for n in ("tipo", "objetivo", "vence_min", "minuto_actual", "expediente", "sello"):
            self.assertEqual(p[n].kind, inspect.Parameter.POSITIONAL_OR_KEYWORD, n)
        for n, defecto in (("vigente", True), ("hora_vence", None), ("fecha_vence", None), ("acelerar", 1.0)):
            self.assertEqual(p[n].kind, inspect.Parameter.KEYWORD_ONLY, n)
            self.assertEqual(p[n].default, defecto, n)
        # Llamada vieja, seis posicionales: sigue generando las líneas.
        self.assertTrue(K.kit("ip", "203.0.113.10", 105, 10, "EXP-2026-000001", "ab12"))


class FormaYEstado(unittest.TestCase):
    def todas(self, vigente):
        return (ip(vigente=vigente) + ip("2001:db8::10", vigente=vigente) + dom(vigente=vigente))

    def test_k2_campos_de_cada_entrada(self):
        for e in self.todas(True):
            with self.subTest(equipo=e["equipo"]):
                self.assertLessEqual(set(e), CAMPOS)
                for c in ("equipo", "aplicar", "quitar", "nota"):
                    self.assertIsInstance(e.get(c), str, c)
                    self.assertTrue(e[c].strip(), c)

    def test_k2_equipos_esperados(self):
        self.assertEqual([e["equipo"] for e in ip()], ["MikroTik RouterOS 6 y 7", "nftables"])
        self.assertEqual([e["equipo"] for e in dom()], ["MikroTik RouterOS 6 y 7", "Unbound", "BIND (RPZ)"])

    def test_k3_orden_que_no_rige_solo_trae_quitar(self):
        for e in self.todas(False):
            with self.subTest(equipo=e["equipo"]):
                self.assertNotIn("aplicar", e)
                self.assertNotIn("preparar", e)
                self.assertNotIn("vencer", e)
                self.assertTrue(e["quitar"].strip())
                self.assertIn(NO_RIGE, e["nota"])

    def test_k3_quitar_es_el_mismo_rija_o_no(self):
        for a, b in ((ip(), ip(vigente=False)), (dom(), dom(vigente=False))):
            self.assertEqual([x["quitar"] for x in a], [x["quitar"] for x in b])


class Vencimiento(unittest.TestCase):
    def test_k4_comentario_con_hora_absoluta(self):
        mk = equipo(ip(), "MikroTik")
        self.assertIn(f'comment="{EXP} a1b2c3d4 vence 19:45"', mk["aplicar"])
        mk = equipo(dom(), "MikroTik")
        self.assertIn(f'comment="{EXP} a1b2c3d4 vence 19:45"', mk["aplicar"])

    def test_k4_hora_con_segundos(self):
        self.assertIn('vence 19:45"', equipo(ip(hora_vence="19:45:00"), "MikroTik")["aplicar"])
        self.assertIn('vence 19:45:30"', equipo(ip(hora_vence="19:45:30"), "MikroTik")["aplicar"])

    def test_k4_sin_hora_el_comentario_dice_el_minuto(self):
        mk = equipo(K.kit("ip", "203.0.113.10", 105, 20.4, EXP, SELLO), "MikroTik")
        self.assertIn(f'comment="{EXP} a1b2c3d4 vence min 105"', mk["aplicar"])

    def test_k4_la_nota_dice_que_el_timeout_cuenta_desde_que_se_pega(self):
        for e in ip():
            with self.subTest(equipo=e["equipo"]):
                self.assertIn("desde que pegás la línea", e["nota"])
                self.assertIn("19:45", e["nota"])

    def test_k15_timeout(self):
        mk, nft = ip()
        self.assertIn("timeout=1h25m ", mk["aplicar"])
        self.assertIn("timeout 85m }", nft["aplicar"])
        mk, nft = K.kit("ip", "203.0.113.10", 30, 29.5, EXP, SELLO)
        self.assertIn("timeout=1m ", mk["aplicar"])
        mk, nft = K.kit("ip", "203.0.113.10", 30, 40, EXP, SELLO)  # ya pasado: nunca 0 ni negativo
        self.assertIn("timeout=1m ", mk["aplicar"])
        self.assertIn("timeout 1m }", nft["aplicar"])
        mk, _ = K.kit("ip", "203.0.113.10", 105, None, EXP, SELLO)
        self.assertIn("timeout=1h45m ", mk["aplicar"])


class MikroTikIP(unittest.TestCase):
    def test_k5_regla_antes_de_fasttrack(self):
        mk = equipo(ip(), "MikroTik")
        self.assertEqual(mk["preparar"], '/ip firewall filter add chain=forward dst-address-list=bloqueo-judicial '
                                         'action=drop comment="bloqueo judicial" place-before=0')
        self.assertIn("antes de la regla fasttrack-connection", mk["nota"])
        self.assertIn("las conexiones ya abiertas siguen", mk["nota"])

    def test_k5_aplicar_y_quitar(self):
        mk = equipo(ip(), "MikroTik")
        self.assertEqual(mk["aplicar"], '/ip firewall address-list add list=bloqueo-judicial address=203.0.113.10 '
                                        f'timeout=1h25m comment="{EXP} a1b2c3d4 vence 19:45"')
        self.assertEqual(mk["quitar"], "/ip firewall address-list remove [find list=bloqueo-judicial "
                                       "address=203.0.113.10]")

    def test_k5_corte_de_conexiones_abiertas_y_reinicio(self):
        mk = equipo(ip(), "MikroTik")
        self.assertIn('/ip firewall connection remove [find where dst-address~"^203.0.113.10(:|$)"]', mk["nota"])
        self.assertIn("probalo antes en tu equipo", mk["nota"])
        self.assertIn("se borra si el router se reinicia", mk["nota"])


class IPv6(unittest.TestCase):
    def test_k6_mikrotik_ipv6(self):
        mk = equipo(ip("2001:db8::10"), "MikroTik")
        self.assertTrue(mk["preparar"].startswith("/ipv6 firewall filter add chain=forward "))
        self.assertTrue(mk["aplicar"].startswith("/ipv6 firewall address-list add list=bloqueo-judicial "
                                                 "address=2001:db8::10 "))
        self.assertEqual(mk["quitar"], "/ipv6 firewall address-list remove [find list=bloqueo-judicial "
                                       "address=2001:db8::10]")
        for c in COMANDOS:
            self.assertNotIn("/ip firewall", mk.get(c, ""), c)
        # La búsqueda por texto de IPv4 cortaría otras conexiones en IPv6: no se ofrece.
        self.assertNotIn("dst-address~", mk["nota"])

    def test_k6_nftables_ipv6(self):
        nft = equipo(ip("2001:db8::10"), "nftables")
        self.assertIn("type ipv6_addr; flags timeout;", nft["preparar"])
        self.assertIn("ip6 daddr @objetivos6 drop", nft["preparar"])
        self.assertNotIn("ipv4_addr", nft["preparar"])
        self.assertEqual(nft["aplicar"], "nft add element inet bloqueo_judicial objetivos6 '{ 2001:db8::10 timeout 85m }'")
        self.assertEqual(nft["quitar"], "nft delete element inet bloqueo_judicial objetivos6 '{ 2001:db8::10 }'")

    def test_k6_ipv4_no_usa_lo_de_ipv6(self):
        mk, nft = ip()
        for c in COMANDOS:
            self.assertNotIn("/ipv6", mk.get(c, ""))
            self.assertNotIn("ipv6_addr", nft.get(c, ""))
            self.assertNotIn("ip6 ", nft.get(c, ""))

    def test_k14_ipv6_sale_canonica(self):
        mk = equipo(ip("2001:DB8:0:0::10"), "MikroTik")
        self.assertIn("address=2001:db8::10 ", mk["aplicar"])


class Nftables(unittest.TestCase):
    def test_k7_tabla_propia(self):
        nft = equipo(ip(), "nftables")
        self.assertEqual(nft["preparar"].split("\n"), [
            "nft add table inet bloqueo_judicial",
            "nft add set inet bloqueo_judicial objetivos '{ type ipv4_addr; flags timeout; }'",
            "nft add chain inet bloqueo_judicial forward '{ type filter hook forward priority -10; policy accept; }'",
            "nft add rule inet bloqueo_judicial forward ip daddr @objetivos drop"])
        self.assertEqual(nft["aplicar"], "nft add element inet bloqueo_judicial objetivos '{ 203.0.113.10 timeout 85m }'")
        self.assertEqual(nft["quitar"], "nft delete element inet bloqueo_judicial objetivos '{ 203.0.113.10 }'")
        self.assertIn("si usás flowtable, esta tabla tiene que cortar antes del flow add", nft["nota"].lower())
        for c in COMANDOS:
            self.assertNotIn("inet filter", nft.get(c, ""))


class MikroTikDominio(unittest.TestCase):
    def test_k8_aplicar_con_vaciado_de_cache(self):
        mk = equipo(dom(), "MikroTik")
        self.assertEqual(mk["aplicar"].split("\n"), [
            f'/ip dns static add name=s1.pirata.test type=NXDOMAIN comment="{EXP} a1b2c3d4 vence 19:45"',
            "/ip dns cache flush"])

    def test_k8_vencer_con_el_programador_sin_depender_del_formato_de_fecha(self):
        mk = equipo(dom(), "MikroTik")
        self.assertEqual(mk["vencer"], f"/system scheduler add name=vence-{EXP}-a1b2c3d4 start-time=19:45:00 "
                                       'interval=0s on-event="/ip dns static remove [find name=s1.pirata.test]"')
        self.assertNotIn("start-date", mk["vencer"])
        # La nota da las dos formas de escribir la fecha, por si el vencimiento cae otro día.
        self.assertIn("start-date=2026-11-12", mk["nota"])
        self.assertIn("start-date=nov/12/2026", mk["nota"])
        self.assertIn("RouterOS 6.47 o posterior y el reloj en hora", mk["nota"])
        self.assertIn("solo alcanza a los abonados que usan este router como DNS", mk["nota"])

    def test_k8_sin_hora_no_hay_linea_de_vencer(self):
        mk = equipo(K.kit("dominio", "s1.pirata.test", 105, 20.4, EXP, SELLO), "MikroTik")
        self.assertNotIn("vencer", mk)
        self.assertIn("minuto 105", mk["nota"])

    def test_k8_quitar_borra_tambien_la_tarea(self):
        mk = equipo(dom(), "MikroTik")
        self.assertEqual(mk["quitar"].split("\n"), [
            "/ip dns static remove [find name=s1.pirata.test]",
            f"/system scheduler remove [find name=vence-{EXP}-a1b2c3d4]"])


class Alcance(unittest.TestCase):
    def test_k9_unbound_corta_nombre_y_subdominios(self):
        ub = equipo(dom(), "Unbound")
        self.assertEqual(ub["aplicar"], "unbound-control local_zone s1.pirata.test. always_nxdomain")
        self.assertEqual(ub["quitar"], "unbound-control local_zone_remove s1.pirata.test.")
        self.assertIn(NOTA_UNBOUND, ub["nota"])
        self.assertNotIn("nombre exacto", ub["nota"])

    def test_k9_mikrotik_y_bind_solo_el_nombre_exacto(self):
        for nombre in ("MikroTik", "BIND"):
            with self.subTest(equipo=nombre):
                self.assertIn("solo el nombre exacto", equipo(dom(), nombre)["nota"])

    def test_k10_ningun_texto_promete_que_el_dns_se_quita_solo(self):
        for vig in (True, False):
            for e in dom(vigente=vig) + K.kit("dominio", "s1.pirata.test", 105, 20.4, EXP, SELLO, vigente=vig):
                texto = " ".join(str(v) for v in e.values()).lower()
                with self.subTest(equipo=e["equipo"], vigente=vig):
                    self.assertNotIn("se quita solo", texto)
                    self.assertNotIn("se quita sola", texto)
                    for m in re.finditer(r"vence solo", texto):
                        self.assertEqual(texto[max(0, m.start() - 3):m.start()], "no ", texto)


class Bind(unittest.TestCase):
    def test_k11_nsupdate(self):
        b = equipo(dom(), "BIND")
        self.assertEqual(b["aplicar"], "printf 'zone rpz.local\\nupdate add s1.pirata.test.rpz.local. 60 CNAME .\\n"
                                       "send\\n' | nsupdate -l")
        self.assertEqual(b["quitar"], "printf 'zone rpz.local\\nupdate delete s1.pirata.test.rpz.local. CNAME\\n"
                                      "send\\n' | nsupdate -l")
        self.assertIn('zone "rpz.local" { type primary; file "rpz.local"; update-policy local; };', b["preparar"])
        self.assertIn('response-policy { zone "rpz.local"; } min-update-interval 5;', b["preparar"])


class Leyenda(unittest.TestCase):
    def test_k12_leyenda_en_cada_equipo_que_rige(self):
        for e in ip() + ip("2001:db8::10") + dom():
            with self.subTest(equipo=e["equipo"]):
                self.assertIn(LEYENDA, e["nota"])
                self.assertNotIn("Ejemplos de referencia", e["nota"])


def objetivo_rechazado(test, r, objetivo):
    test.assertEqual(len(r), 1, r)
    test.assertEqual(r[0]["equipo"], "Objetivo no válido")
    test.assertFalse(set(r[0]) & set(COMANDOS), r)
    test.assertIn("no es una IP ni un nombre de host válido", r[0]["nota"])
    if isinstance(objetivo, str) and objetivo:
        test.assertNotIn(objetivo, r[0]["nota"])


class Defensa(unittest.TestCase):
    MALOS_DOMINIO = ["s1.pirata.test\n", "s1.pirata.test ", "s1.pirata.test;flush ruleset", 's1.pirata.test" ; /system reboot', "s1.pirata.test\n/system reboot", "s1 pirata.test",
                     "s1.pirata.test;reboot", "$(reboot).test", "a..b", "-a.test", "com", "com.ar", "localhost",
                     "203.0.113.10", "1.2.3.999", "ejemplo.123", "", None, 5, "a" * 64 + ".test",
                     "ñandú.test", "s1.pirata.test'", "s1.pirata.test`id`"]
    MALAS_IP = ["203.0.113.10; rm -rf /", "203.0.113.10 ", " 203.0.113.10", "203.0.113.300", "[::1]",
                "s1.pirata.test", "2001:db8::10%eth0", "2001:db8::1%$(reboot)", "0.0.0.0", "127.0.0.1", "::1",
                "224.0.0.1", "fe80::1", "", None, 3, "203.0.113.0/24", "2001:db8::1%\n0.0.0.0-255.255.255.255",
                "203.0.113.10\n"]

    def test_k13_objetivo_invalido(self):
        for malo in self.MALOS_DOMINIO:
            with self.subTest(dominio=malo):
                objetivo_rechazado(self, K.kit("dominio", malo, 105, 10, EXP, SELLO, hora_vence="19:45"), malo)
        for mala in self.MALAS_IP:
            with self.subTest(ip=mala):
                objetivo_rechazado(self, K.kit("ip", mala, 105, 10, EXP, SELLO, hora_vence="19:45"), mala)
        for vig in (True, False):
            objetivo_rechazado(self, K.kit("ip", "s1.pirata.test", 105, 10, EXP, SELLO, vigente=vig), "s1")

    def test_k13_tipo_desconocido(self):
        for tipo in ("IP", "url", None, "", "dominio "):
            objetivo_rechazado(self, K.kit(tipo, "203.0.113.10", 105, 10, EXP, SELLO), "203.0.113.10")

    def test_k13_rangos_de_documentacion_siguen_saliendo(self):
        for d in ("192.0.2.50", "198.51.100.77", "203.0.113.41", "2001:db8::10", "2001:DB8::1:2"):
            with self.subTest(ip=d):
                r = K.kit("ip", d, 105, 10, EXP, SELLO)
                self.assertEqual([e["equipo"] for e in r], ["MikroTik RouterOS 6 y 7", "nftables"])
                self.assertIn(str(ipaddress.ip_address(d)), r[0]["aplicar"])

    def test_k13_expediente_y_sello(self):
        for exp in ('EXP"x', "EXP x", "EXP\n", "EXP;reboot", "EXP$x", "", None, "EXPñ", "x" * 65):
            self.assertEqual(K.kit("dominio", "s1.pirata.test", 105, 10, exp, SELLO), [], repr(exp))
        for s in ('ab"c', "ab c", "ab\n", "abc\n", "", None, "ab;c", "ab]c", "²³"):
            self.assertEqual(K.kit("dominio", "s1.pirata.test", 105, 10, EXP, s), [], repr(s))

    def test_k13_hora_y_fecha(self):
        for h in ("19:45 ; reboot", "25:00", "19:60", "1945", "19:45:00:00", '19:45"', 1945, "", "7:45", "19:45\n"):
            self.assertEqual(dom(hora_vence=h), [], repr(h))
        for f in ("2026-13-01", "2026-02-30", "12/11/2026", "2026-11-12; reboot", "", 20261112, "2026-11-1",
                  "2026-11-12\n"):
            self.assertEqual(dom(fecha_vence=f), [], repr(f))

    def test_k13_minutos(self):
        for v in (None, "105", True, float("nan"), float("inf")):
            self.assertEqual(K.kit("ip", "203.0.113.10", v, 10, EXP, SELLO), [], repr(v))
        for m in ("10", True, float("nan")):
            self.assertEqual(K.kit("ip", "203.0.113.10", 105, m, EXP, SELLO), [], repr(m))

    def test_k14_comandos_ascii_imprimible(self):
        for e in ip() + ip("2001:db8::10") + dom() + dom("S1.Pirata.TEST.") + ip(vigente=False):
            for c in COMANDOS:
                if c in e:
                    with self.subTest(equipo=e["equipo"], campo=c):
                        self.assertTrue(all(ch == "\n" or (" " <= ch <= "~") for ch in e[c]), e[c])

    def test_k14_dominio_normalizado(self):
        for e in dom("S1.Pirata.TEST."):
            for c in COMANDOS:
                if c in e:
                    self.assertNotIn("Pirata", e[c])
                    self.assertNotIn("TEST.", e[c])
        self.assertIn("name=s1.pirata.test ", equipo(dom("S1.Pirata.TEST."), "MikroTik")["aplicar"])


# --- lista del proveedor (5.2) -----------------------------------------------------------------------

def orden(oid, tipo, objetivo, vence=105, **kw):
    o = {"orden_id": oid, "tipo": tipo, "objetivo": objetivo, "vence_min": vence, "vence_hora": "19:45",
         "juzgado": "Juzgado 1", "juez": "Dra. A", "firma": "en_persona", "desde_min": 5, "url": "/orden/" + oid}
    o.update(kw)
    return o


def vista(vigentes=(), **kw):
    v = {"v": 7, "proveedor": {"id": "valle", "nombre": "FibraValle (ficticio)", "capacidades": ["dominio"]},
         "minuto": 20.4, "hora": "18:20", "generado_utc": "2026-11-12T21:20:24.000Z",
         "partido": {"nombre": "Partido de práctica", "fin_min": 105, "fin_hora": "19:45"},
         "vigentes": list(vigentes), "retiradas": []}
    v.update(kw)
    return v


VIGENTES = [
    orden("ord-0001-u1-valle-01-aa", "dominio", "s1.pirata.test"),
    orden("ord-0001-u2-valle-01-bb", "dominio", "S2.Pirata.TEST."),
    orden("amp-0001-u3-valle-01-cc", "dominio", "s1.pirata.test"),           # repetido
    orden("ord-0002-u1-valle-01-dd", "ip", "203.0.113.10"),
    orden("ord-0002-u2-valle-01-ee", "ip", "2001:DB8::10"),
    orden("ord-0003-u1-valle-01-ff", "dominio", '203.0.113.11'),             # IP como dominio: no
    orden("ord-0003-u2-valle-01-gg", "ip", "s9.pirata.test"),                # dominio como IP: no
    orden("ord-0003-u3-valle-01-hh", "dominio", 'x.test." always_nxdomain\nlocal-zone: "com'),
    orden("ord-0003-u4-valle-01-ii", "dominio", "s8.pirata.test\n@ NS evil."),
    orden("ord-0003-u5-valle-01-jj", "ip", "203.0.113.12\n0.0.0.0"),
    orden("ord-0003-u6-valle-01-kk", "dominio", "com"),
    orden("ord-0003-u7-valle-01-ll", "dominio", "vencida.pirata.test", vence=20),  # ya venció según la lista
    "no es una orden",
]
SEGUNDO = "Son datos, no comandos: su equipo decide cómo aplicarlos."


def cuerpo(texto, marca="#"):
    return [l for l in texto.split("\n") if l and not l.startswith(marca)]


class ListaProveedor(unittest.TestCase):
    def test_l1_cabecera(self):
        for f, marca, segunda in ((K.lista_dominios, "#", SEGUNDO), (K.lista_ips, "#", SEGUNDO),
                                  (K.unbound_conf, "#", SEGUNDO + " Cada línea corta el nombre y sus subdominios."),
                                  (K.zona_rpz, ";", SEGUNDO)):
            with self.subTest(f=f.__name__):
                lineas = f(vista(VIGENTES)).split("\n")
                self.assertTrue(lineas[0].startswith(marca + " "), lineas[0])
                for dato in ("FibraValle (ficticio)", "minuto 20,4", "18:20", "105", "19:45"):
                    self.assertIn(dato, lineas[0])
                self.assertEqual(lineas[1], f"{marca} {segunda}")
                n = 2 if f is K.lista_ips else 4  # los de su tipo con formato inválido (no los vencidos)
                self.assertEqual(lineas[2], f"{marca} {n} objetivo(s) descartado(s) por formato inválido.")
                self.assertFalse(lineas[3].startswith(marca))

    def test_l1_cabecera_cuenta_lo_vigente_de_la_lista(self):
        self.assertIn("2 vigentes", K.lista_dominios(vista(VIGENTES)).split("\n")[0])
        self.assertIn("2 vigentes", K.lista_ips(vista(VIGENTES)).split("\n")[0])
        self.assertIn("0 vigentes", K.lista_ips(vista()).split("\n")[0])

    def test_l2_dominios(self):
        self.assertEqual(cuerpo(K.lista_dominios(vista(VIGENTES))), ["s1.pirata.test", "s2.pirata.test"])

    def test_l2_ips(self):
        self.assertEqual(cuerpo(K.lista_ips(vista(VIGENTES))), ["203.0.113.10", "2001:db8::10"])

    def test_l2_terminan_en_salto_de_linea(self):
        for f in (K.lista_dominios, K.lista_ips, K.unbound_conf, K.zona_rpz):
            self.assertTrue(f(vista(VIGENTES)).endswith("\n"), f.__name__)

    def test_l3_unbound_igual_al_cliente_de_referencia(self):
        cli = cargar_cliente()
        mio = cuerpo(K.unbound_conf(vista(VIGENTES)))
        self.assertEqual(mio, ['local-zone: "s1.pirata.test." always_nxdomain',
                               'local-zone: "s2.pirata.test." always_nxdomain'])
        aplicadas = {o["orden_id"]: {"tipo": "dominio", "objetivo": h}
                     for o, h in zip(VIGENTES, ("s1.pirata.test", "s2.pirata.test"))}
        self.assertEqual(mio, cuerpo(cli.texto_unbound("valle", aplicadas)))
        patron = re.compile(r'^local-zone: "[a-z0-9.-]+\." always_nxdomain$')
        self.assertTrue(all(patron.match(l) for l in mio))

    def test_l4_zona_rpz(self):
        lineas = cuerpo(K.zona_rpz(vista(VIGENTES)), ";")
        self.assertEqual(lineas[0], "$TTL 30")
        soa = lineas[1].split()
        self.assertEqual(soa[:4], ["@", "SOA", "localhost.", "root.localhost."])
        self.assertEqual(soa[4], "7")
        self.assertEqual(lineas[2], "@ NS localhost.")
        self.assertEqual(lineas[3:], ["s1.pirata.test CNAME .", "s2.pirata.test CNAME ."])

    def test_l4_serial_invalido_no_llega_al_texto(self):
        for v in ("7\n@ NS evil.", -1, True, 2 ** 40, None, 3.5):
            with self.subTest(v=v):
                texto = K.zona_rpz(vista(VIGENTES, v=v))
                self.assertNotIn("evil", texto)
                serial = cuerpo(texto, ";")[1].split()[4]
                self.assertTrue(serial.isdigit() and int(serial) < 2 ** 32, serial)

    def test_l5_listas_vacias(self):
        for f in (K.lista_dominios, K.lista_ips, K.unbound_conf):
            with self.subTest(f=f.__name__):
                t = f(vista())
                self.assertEqual(len(t.rstrip("\n").split("\n")), 2)
                self.assertEqual(cuerpo(t), [])
        self.assertEqual(cuerpo(K.zona_rpz(vista()), ";")[0], "$TTL 30")
        self.assertEqual(len(cuerpo(K.zona_rpz(vista()), ";")), 3)

    def test_l5_vista_incompleta_no_rompe(self):
        for v in ({}, {"vigentes": None}, {"proveedor": None, "partido": None, "minuto": "x"},
                  {"v": 3, "proveedor": {"id": "p1", "nombre": "Proveedor Uno", "capacidades": ["ip"]},
                   "minuto": 10.0, "hora": "21:10", "vigentes": [], "retiradas": []}):
            for f in (K.lista_dominios, K.lista_ips, K.unbound_conf, K.zona_rpz):
                with self.subTest(v=v, f=f.__name__):
                    t = f(v)
                    self.assertTrue(t.startswith("# ") or t.startswith("; "))

    def test_l6_cabecera_sin_inyeccion(self):
        malo = vista(VIGENTES, proveedor={"id": "valle", "nombre": "X\nlocal-zone: \"com.\" always_nxdomain"},
                     hora="18:20\nmal", partido={"fin_min": "105\nmal", "fin_hora": "x"})
        for f in (K.lista_dominios, K.lista_ips, K.unbound_conf, K.zona_rpz):
            with self.subTest(f=f.__name__):
                t = f(malo)
                self.assertNotIn('"com."', t)
                self.assertNotIn("mal", t)
                comentarios = [i for i, l in enumerate(t.split("\n")) if l.startswith(("#", ";"))]
                self.assertEqual(comentarios, [0, 1, 2])  # dos de cabecera + el de descartados, y nada más

    VENENOS = [
        orden("ord-9-u1-v-01-a", "dominio", "s1.pirata.test\n@ NS evil."),
        orden("ord-9-u2-v-01-b", "dominio", "s2.pirata.test;flush ruleset"),
        orden("ord-9-u3-v-01-c", "dominio", 's3.pirata.test" always_nxdomain'),
        orden("ord-9-u4-v-01-d", "dominio", "s4 pirata.test"),
        orden("ord-9-u5-v-01-e", "dominio", "s5.pirata.test\n"),
        orden("ord-9-u6-v-01-f", "ip", "2001:db8::1%eth0"),
        orden("ord-9-u7-v-01-g", "ip", "2001:db8::1%\n0.0.0.0-255.255.255.255"),
        orden("ord-9-u8-v-01-h", "ip", "203.0.113.9;flush ruleset"),
        orden("ord-9-u9-v-01-i", "ip", '"203.0.113.8"'),
        orden("ord-9-u10-v-01-j", "ip", "203.0.113.7\n"),
        # Lo bueno sigue saliendo (rangos de documentación que usa el escenario oficial).
        orden("ord-9-u11-v-01-k", "dominio", "tv.verpartido-hd.test"),
        orden("ord-9-u16-v-01-p", "dominio", "b12_hd.pizarronhd.test"),  # «_» es un nombre válido (C16)
        orden("ord-9-u12-v-01-l", "ip", "192.0.2.50"),
        orden("ord-9-u13-v-01-m", "ip", "198.51.100.77"),
        orden("ord-9-u14-v-01-n", "ip", "203.0.113.41"),
        orden("ord-9-u15-v-01-o", "ip", "2001:db8::10"),
    ]

    def test_l7_venenos_no_llegan_a_ninguna_salida(self):
        v = vista(self.VENENOS)
        host = r"[a-z0-9_-]+(?:\.[a-z0-9_-]+)+"
        formas = {
            K.lista_dominios: ("#", re.compile(host), 5, ["tv.verpartido-hd.test", "b12_hd.pizarronhd.test"]),
            K.lista_ips: ("#", re.compile(r"[0-9a-f:.]+"), 5,
                          ["192.0.2.50", "198.51.100.77", "203.0.113.41", "2001:db8::10"]),
            K.unbound_conf: ("#", re.compile(r'local-zone: "' + host + r'\." always_nxdomain'), 5,
                             ['local-zone: "tv.verpartido-hd.test." always_nxdomain',
                              'local-zone: "b12_hd.pizarronhd.test." always_nxdomain']),
            K.zona_rpz: (";", re.compile(r"\$TTL 30|@ SOA localhost\. root\.localhost\. 7 3600 600 86400 30|"
                                         r"@ NS localhost\.|" + host + r" CNAME \."), 5,
                         ["tv.verpartido-hd.test CNAME .", "b12_hd.pizarronhd.test CNAME ."]),
        }
        for f, (marca, forma, n, esperadas) in formas.items():
            with self.subTest(f=f.__name__):
                t = f(v)
                self.assertTrue(t.endswith("\n"))
                lineas = t[:-1].split("\n")
                self.assertEqual(lineas[2], f"{marca} {n} objetivo(s) descartado(s) por formato inválido.")
                datos = lineas[3:]
                for l in datos:
                    self.assertTrue(forma.fullmatch(l), repr(l))
                for e in esperadas:
                    self.assertIn(e, datos)
                for veneno in ("evil", "flush", "%", "s4", "0.0.0.0", '"s3', "203.0.113.9", "203.0.113.8",
                               "203.0.113.7", "s5.pirata"):
                    self.assertNotIn(veneno, "\n".join(datos))


class TiempoReal(unittest.TestCase):
    """K16 (kit-1): el router cuenta minutos reales. Con el partido acelerado (xN), el timeout no supera
    ⌈lo que falta / N⌉ minutos y la nota lo dice; con acelerar=1 el kit queda igual que antes."""

    def test_k16_timeout_en_minutos_reales(self):
        import math
        e = K.kit("ip", "203.0.113.10", 105, 12.5, EXP, SELLO, acelerar=20.0)
        tope = math.ceil(92.5 / 20)  # 5
        self.assertIn(f"timeout={tope}m ", equipo(e, "MikroTik")["aplicar"])
        self.assertIn(f"timeout {tope}m ", equipo(e, "nftables")["aplicar"])
        for x in e:
            self.assertIn("El partido corre acelerado (x20): el timeout ya está pasado a minutos reales.", x["nota"])
        d = K.kit("dominio", "s1.pirata.test", 105, 12.5, EXP, SELLO, hora_vence="03:07:02", acelerar=20.0)
        for x in d:
            self.assertIn("acelerado (x20)", x["nota"])
            self.assertIn("la hora es la del reloj real", x["nota"])
        self.assertIn("start-time=03:07:02", equipo(d, "MikroTik")["vencer"])
        self.assertIn("timeout=1m ", equipo(K.kit("ip", "203.0.113.10", 105, 104.9, EXP, SELLO, acelerar=20.0),
                                            "MikroTik")["aplicar"])  # nunca menos de 1 minuto

    def test_k16_sin_acelerar_queda_igual(self):
        for args in (("ip", "203.0.113.10", 105, 12.5, EXP, SELLO), ("dominio", "s1.pirata.test", 105, 12.5, EXP, SELLO)):
            self.assertEqual(K.kit(*args), K.kit(*args, acelerar=1.0))
            self.assertEqual(K.kit(*args, hora_vence="19:45"), K.kit(*args, hora_vence="19:45", acelerar=1))
        self.assertIn("timeout=1h33m ", equipo(K.kit("ip", "203.0.113.10", 105, 12.5, EXP, SELLO), "MikroTik")["aplicar"])
        for x in K.kit("ip", "203.0.113.10", 105, 12.5, EXP, SELLO):
            self.assertNotIn("acelerado", x["nota"])

    def test_k16_acelerar_invalido_no_arma_lineas(self):
        for malo in (0, -5, float("nan"), float("inf"), "20", True, None):
            with self.subTest(acelerar=malo):
                self.assertEqual(K.kit("ip", "203.0.113.10", 105, 12.5, EXP, SELLO, acelerar=malo), [])

    def test_k16_orden_que_ya_no_rige_no_cambia(self):
        """Lo que ya no rige solo trae quitar y la nota de «ya no rige», con o sin partido acelerado."""
        self.assertEqual(K.kit("ip", "203.0.113.10", 105, 12.5, EXP, SELLO, vigente=False),
                         K.kit("ip", "203.0.113.10", 105, 12.5, EXP, SELLO, vigente=False, acelerar=20.0))


if __name__ == "__main__":
    unittest.main()
