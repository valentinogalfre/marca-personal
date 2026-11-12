"""Contratos de la evidencia: qué es pirata, qué se bloquea y cómo, sin dañar a terceros.

Los datos replican las situaciones del partido de práctica oficial.
"""
import base64
import unittest

from marca import evidencia

PARTIDO = {
    "marcas_de_agua_validas": [
        {"prefijo": "LP26-PRA-OFI", "origen": "Señal oficial del titular (plataforma propia)"},
        {"prefijo": "LP26-PRA-LIC-NORTE", "origen": "Licenciatario autorizado: Canal Norte TV (ficticio)"}],
    "licenciatarios": [{"nombre": "Canal Norte TV (ficticio)", "prefijo_marca": "LP26-PRA-LIC-NORTE",
                        "dominios_autorizados": ["canalnorte.test", "envivo.canalnorte.test"]}],
}
PROVEEDORES = [
    {"id": "aurora", "capacidades": ["ip", "dominio"], "clientes": 3800000},
    {"id": "andina", "capacidades": ["ip", "dominio"], "clientes": 1200000},
    {"id": "valle", "capacidades": ["dominio"], "clientes": 140000},
    {"id": "cumbre", "capacidades": ["ip", "dominio"], "clientes": 60000},
]
CDN_DOMINIOS = ["live.golazo-libre.test", "tienda-mate-y-yerba.test", "noticias-del-valle.test",
                "turismo-cafayate.example", "radio-comunitaria-fm.test", "municipio-ejemplo.example",
                "biblioteca-popular-norte.test", "delivery-salta-ejemplo.test", "clinica-veterinaria-sol.test",
                "inmobiliaria-ejemplo.test", "academia-de-ingles.test", "feria-artesanal.example"]


def det(host, ip, asn, pagina, marca="LP26-PRA-OFI-S048211"):
    return {"id": "D-1", "minuto": 2.0, "pagina": pagina, "stream_url": f"https://{host}/hls/index.m3u8",
            "host_stream": host, "ip_servidor": ip, "asn": asn, "marca_de_agua_extraida": marca}


def dns_ip(ip, asn, org, dominios):
    return {"ip": ip, "asn": asn, "organizacion": org, "dominios": dominios}


def dns_host(host, *pares):
    return {"dominio": host, "ips": [{"ip": ip, "asn": asn, "organizacion": "x"} for ip, asn in pares]}


class TestSenal(unittest.TestCase):
    def test_oficial_fuera_de_plataforma_es_pirata(self):
        s = evidencia.analizar_senal("LP26-PRA-OFI-S048211", PARTIDO, "s1.pelotaya.test")
        self.assertEqual(s["clase"], "pirata")
        self.assertEqual(s["prefijo"], "LP26-PRA-OFI")
        self.assertEqual(s["sesion"], "S048211")

    def test_licenciatario_en_su_dominio_nunca(self):
        s = evidencia.analizar_senal("LP26-PRA-LIC-NORTE", PARTIDO, "envivo.canalnorte.test")
        self.assertEqual(s["clase"], "licenciatario")

    def test_subdominio_de_dominio_autorizado_es_licenciatario(self):
        s = evidencia.analizar_senal("LP26-PRA-LIC-NORTE-S1", PARTIDO, "cdn2.envivo.canalnorte.test")
        self.assertEqual(s["clase"], "licenciatario")

    def test_senal_del_licenciatario_en_dominio_ajeno_es_pirata(self):
        s = evidencia.analizar_senal("LP26-PRA-LIC-NORTE-S9", PARTIDO, "tv.pirata.test")
        self.assertEqual(s["clase"], "pirata")
        self.assertIn("licenciatario", s["motivo"])

    def test_marca_de_otro_partido_es_descarte(self):
        s = evidencia.analizar_senal("LP25-F03-OFI-S102934", PARTIDO, "vod.resumenes-deportivos.test")
        self.assertEqual(s["clase"], "otra_senal")

    def test_sin_marca(self):
        self.assertEqual(evidencia.analizar_senal(None, PARTIDO, "x.test")["clase"], "sin_marca")
        self.assertEqual(evidencia.analizar_senal("", PARTIDO, "x.test")["clase"], "sin_marca")

    def test_prefijo_parecido_no_es_valido(self):
        self.assertEqual(evidencia.analizar_senal("LP26-PRA-OFIX-S1", PARTIDO, "x.test")["clase"], "otra_senal")
        self.assertEqual(evidencia.analizar_senal("LP26-PRA-OF", PARTIDO, "x.test")["clase"], "otra_senal")

    def test_prefijo_mas_largo_gana(self):
        s = evidencia.analizar_senal("LP26-PRA-LIC-NORTE-S5", {
            "marcas_de_agua_validas": [{"prefijo": "LP26-PRA", "origen": "corto"},
                                       {"prefijo": "LP26-PRA-LIC-NORTE", "origen": "largo"}],
            "licenciatarios": []}, "x.test")
        self.assertEqual(s["prefijo"], "LP26-PRA-LIC-NORTE")
        self.assertEqual(s["sesion"], "S5")

    def test_pagina_del_licenciatario_nunca_se_bloquea(self):
        s = evidencia.analizar_senal("LP26-PRA-LIC-NORTE", PARTIDO, "cdn.otro.test", "canalnorte.test")
        self.assertEqual(s["clase"], "licenciatario")


class TestServidor(unittest.TestCase):
    def test_servidor_exclusivo_con_respaldo_ip_y_dominios_para_valle(self):
        d = det("s1.pelotaya.test", "203.0.113.10", 64600, "https://pelotaya.test/en-vivo")
        a = evidencia.analizar_servidor(d, dns_ip("203.0.113.10", 64600, "Bruma Hosting Dedicado (ficticio)",
                                                  ["s1.pelotaya.test", "s1-respaldo.pelotaya.test"]),
                                        dns_host("s1.pelotaya.test", ("203.0.113.10", 64600)), set())
        self.assertEqual(a["colateral"]["recomendacion"], "ip")
        self.assertEqual(a["colateral"]["riesgo"], "nulo")
        self.assertTrue(a["coherencia"]["completa"])
        p = evidencia.proponer(a, PROVEEDORES, 105)
        self.assertEqual(p["objetivos_por_proveedor"]["aurora"], [{"tipo": "ip", "objetivo": "203.0.113.10"}])
        self.assertEqual(p["objetivos_por_proveedor"]["valle"],
                         [{"tipo": "dominio", "objetivo": "s1.pelotaya.test"},
                          {"tipo": "dominio", "objetivo": "s1-respaldo.pelotaya.test"}])
        self.assertEqual(p["vence_min"], 105)
        self.assertIsInstance(p["vence_min"], int)

    def test_cdn_con_11_ajenos_dominio(self):
        d = det("live.golazo-libre.test", "198.51.100.20", 64610, "https://golazo-libre.test/partido")
        a = evidencia.analizar_servidor(d, dns_ip("198.51.100.20", 64610, "NubeRápida CDN (ficticia)", CDN_DOMINIOS),
                                        dns_host("live.golazo-libre.test", ("198.51.100.20", 64610)), set())
        self.assertEqual(a["colateral"]["recomendacion"], "dominio")
        self.assertEqual(a["colateral"]["riesgo"], "alto")
        self.assertEqual(len(a["colateral"]["ajenos"]), 11)
        self.assertIn("11", a["colateral"]["motivo"])
        p = evidencia.proponer(a, PROVEEDORES, 105)
        for pid in ("aurora", "andina", "valle", "cumbre"):
            self.assertEqual(p["objetivos_por_proveedor"][pid], [{"tipo": "dominio", "objetivo": "live.golazo-libre.test"}])

    def test_hosting_compartido_dominio(self):
        d = det("tv.verpartido-hd.test", "192.0.2.50", 64620, "https://verpartido-hd.test/vivo")
        a = evidencia.analizar_servidor(
            d, dns_ip("192.0.2.50", 64620, "Pampa Web Hosting Compartido (ficticio)",
                      ["tv.verpartido-hd.test", "verpartido-hd.test", "panaderia-la-espiga.test"]),
            dns_host("tv.verpartido-hd.test", ("192.0.2.50", 64620)), set())
        self.assertEqual(a["colateral"]["recomendacion"], "dominio")
        self.assertIn("verpartido-hd.test", a["colateral"]["propios"])
        self.assertEqual(a["colateral"]["ajenos"], ["panaderia-la-espiga.test"])

    def test_pagina_de_otro_registrable_no_hace_exclusiva_la_ip(self):
        """[C14, colateral-2] La página de la detección solo cuenta como propia (observada) si comparte el
        registrable del stream. Un foro legítimo de otro registrable alojado en la misma IP es ajeno: no se
        recomienda la IP ni se le manda una orden por nombre a ningún proveedor."""
        d = det("s9.pirata-foro.test", "203.0.113.61", 64661, "https://foro-hinchas.test/hilo/77")
        a = evidencia.analizar_servidor(
            d, dns_ip("203.0.113.61", 64661, "Servidor dedicado", ["s9.pirata-foro.test", "foro-hinchas.test"]),
            dns_host("s9.pirata-foro.test", ("203.0.113.61", 64661)), set())
        self.assertEqual(a["colateral"]["recomendacion"], "dominio")
        self.assertIn("foro-hinchas.test", a["colateral"]["ajenos"])
        self.assertNotIn("foro-hinchas.test", a["colateral"]["propios"])
        p = evidencia.proponer(a, PROVEEDORES, 105)
        objetivos = {o["objetivo"] for lista in p["objetivos_por_proveedor"].values() for o in lista}
        self.assertEqual(objetivos, {"s9.pirata-foro.test"})

    def test_registrable_refutado_ya_no_infiere(self):
        """[C14] Con el registrable refutado por un reclamo, los hermanos del stream son ajenos (no se infiere)."""
        d = det("s1.pirata.test", "203.0.113.10", 64600, "https://pirata.test/vivo")
        dip = dns_ip("203.0.113.10", 64600, "Dedicado", ["s1.pirata.test", "s1-respaldo.pirata.test"])
        dh = dns_host("s1.pirata.test", ("203.0.113.10", 64600))
        a = evidencia.analizar_servidor(d, dip, dh, set())
        self.assertEqual(a["colateral"]["inferidos"], ["s1-respaldo.pirata.test"])
        self.assertEqual(a["colateral"]["recomendacion"], "ip")
        b = evidencia.analizar_servidor(d, dip, dh, set(), refutados={"pirata.test"})
        self.assertEqual(b["colateral"]["inferidos"], [])
        self.assertIn("s1-respaldo.pirata.test", b["colateral"]["ajenos"])
        self.assertEqual(b["colateral"]["recomendacion"], "dominio")

    def test_red_compartida_por_nombre_del_asn(self):
        d = det("s9.pirata.test", "203.0.113.99", 64999, "https://pirata.test/")
        a = evidencia.analizar_servidor(d, dns_ip("203.0.113.99", 64999, "Shared Hosting SA", ["s9.pirata.test"]),
                                        dns_host("s9.pirata.test", ("203.0.113.99", 64999)), set())
        self.assertEqual((a["colateral"]["recomendacion"], a["colateral"]["riesgo"]), ("dominio", "medio"))

    def test_sin_datos_de_dns_dominio(self):
        d = det("s9.pirata.test", "203.0.113.99", 64999, "https://pirata.test/")
        a = evidencia.analizar_servidor(d, None, None, set())
        self.assertEqual((a["colateral"]["recomendacion"], a["colateral"]["riesgo"]), ("dominio", "desconocido"))
        self.assertFalse(a["coherencia"]["completa"])

    def test_host_en_varias_ip_dominio(self):
        d = det("s9.pirata.test", "203.0.113.99", 64999, "https://pirata.test/")
        a = evidencia.analizar_servidor(d, dns_ip("203.0.113.99", 64999, "Dedicado", ["s9.pirata.test"]),
                                        dns_host("s9.pirata.test", ("203.0.113.99", 64999), ("203.0.113.98", 64999)),
                                        set())
        self.assertEqual((a["colateral"]["recomendacion"], a["colateral"]["riesgo"]), ("dominio", "nulo"))

    def test_host_ip_literal_sin_garantias_ninguna(self):
        d = det("203.0.113.99", "203.0.113.99", 64999, "https://pirata.test/")
        a = evidencia.analizar_servidor(d, dns_ip("203.0.113.99", 64999, "NubeX CDN", ["otro.test"]), None, set())
        self.assertEqual((a["colateral"]["recomendacion"], a["colateral"]["riesgo"]), ("ninguna", "alto"))
        p = evidencia.proponer(a, PROVEEDORES, 105)
        self.assertEqual(p["objetivos_por_proveedor"], {})

    def test_host_ip_literal_exclusiva_ip_y_valle_sin_cobertura(self):
        d = det("203.0.113.99", "203.0.113.99", 64999, "https://pirata.test/")
        a = evidencia.analizar_servidor(d, dns_ip("203.0.113.99", 64999, "Dedicado", ["pirata.test"]), None, set())
        self.assertEqual(a["colateral"]["recomendacion"], "ip")
        p = evidencia.proponer(a, PROVEEDORES, 105)
        self.assertIn("valle", p["sin_cobertura"])

    def test_incoherencia_detecta_y_pide_dominio(self):
        d = det("s9.pirata.test", "203.0.113.99", 64999, "https://pirata.test/")
        a = evidencia.analizar_servidor(d, dns_ip("203.0.113.99", 64001, "Dedicado", ["s9.pirata.test"]),
                                        dns_host("s9.pirata.test", ("203.0.113.99", 64001)), set())
        self.assertFalse(a["coherencia"]["asn_coincide"])
        self.assertEqual((a["colateral"]["recomendacion"], a["colateral"]["riesgo"]), ("dominio", "desconocido"))

    def test_host_que_no_esta_en_la_url(self):
        d = det("s9.pirata.test", "203.0.113.99", 64999, "https://pirata.test/")
        d["stream_url"] = "https://otro.test/x.m3u8"
        a = evidencia.analizar_servidor(d, dns_ip("203.0.113.99", 64999, "Dedicado", ["s9.pirata.test"]),
                                        dns_host("s9.pirata.test", ("203.0.113.99", 64999)), set())
        self.assertFalse(a["coherencia"]["host_en_url"])
        self.assertEqual(a["colateral"]["recomendacion"], "dominio")

    def test_forzar_ip_en_compartido_se_respeta(self):
        d = det("tv.verpartido-hd.test", "192.0.2.50", 64620, "https://verpartido-hd.test/vivo")
        a = evidencia.analizar_servidor(
            d, dns_ip("192.0.2.50", 64620, "Pampa Web Hosting Compartido", ["tv.verpartido-hd.test", "panaderia.test"]),
            dns_host("tv.verpartido-hd.test", ("192.0.2.50", 64620)), set())
        p = evidencia.proponer(a, PROVEEDORES, 104.5, forzar_tipo="ip")
        self.assertEqual(p["tipo"], "ip")
        self.assertEqual(p["vence_min"], 105)
        self.assertEqual(p["objetivos_por_proveedor"]["valle"], [{"tipo": "dominio", "objetivo": "tv.verpartido-hd.test"}])


class TestCaptura(unittest.TestCase):
    def test_captura_valida_y_repetida(self):
        datos = bytes([0x47]) + b"\x00" * 63
        cap = {"formato": "mpegts", "contenido_b64": base64.b64encode(datos).decode(), "capturada_min": 2.0}
        a = evidencia.analizar_captura(cap, set())
        self.assertTrue(a["valida"])
        self.assertEqual(a["bytes"], 64)
        b = evidencia.analizar_captura(cap, {a["sha256"]})
        self.assertTrue(b["repetida"])
        self.assertFalse(b["valida"])

    def test_captura_sin_sincronia(self):
        cap = {"formato": "mpegts", "contenido_b64": base64.b64encode(b"\x00" * 64).decode()}
        self.assertFalse(evidencia.analizar_captura(cap, set())["valida"])

    def test_captura_no_base64(self):
        self.assertFalse(evidencia.analizar_captura({"formato": "mpegts", "contenido_b64": "@@@"}, set())["valida"])


class TestCobertura(unittest.TestCase):
    def test_misma_cuenta_que_el_verificador(self):
        ordenes = [{"proveedor": "aurora", "tipo": "ip", "objetivo": "1.1.1.1", "aplicada_min": 3.0, "finalizada_min": None},
                   {"proveedor": "valle", "tipo": "dominio", "objetivo": "h.test", "aplicada_min": 8.0,
                    "finalizada_min": None},
                   {"proveedor": "andina", "tipo": "dominio", "objetivo": "otro.test", "aplicada_min": 3.0,
                    "finalizada_min": None}]
        provs = [{"id": "aurora", "clientes": 100}, {"id": "valle", "clientes": 100}, {"id": "andina", "clientes": 200}]
        c = evidencia.cobertura(2.0, 12.0, "1.1.1.1", "h.test", ordenes, provs)
        self.assertEqual(c["primer_bloqueo_min"], 1.0)
        self.assertEqual(c["clientes_cubiertos_pct"], 50.0)
        # cubiertos = 100*9 + 100*4 = 1300 de 400*10 → residual 67.5 %
        self.assertEqual(c["visibilidad_residual_pct"], 67.5)


if __name__ == "__main__":
    unittest.main()
