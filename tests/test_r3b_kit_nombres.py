"""Contratos de los nombres que llegan al equipo del proveedor (ronda 3, tanda B: C16, kit-5 y kit-3).

- N1 (C16, kit-5) Un nombre con «_» en un rótulo es un objetivo válido en todos lados: `dominios.objetivo_valido`,
     `dominios.es_hostname`, el kit y el cliente del proveedor. Toda orden por dominio que el motor puede mandar
     tiene su línea en las listas del proveedor y su kit en la página pública.
- N2 (C16) Las demás defensas siguen: al menos dos rótulos, sin punto final en la orden, sin comodines, espacios ni
     caracteres de control, largo máximo, ni un sufijo de registro pelado.
- N3 (kit-3) Lo que se publica para BIND (rpz.zone y la línea de nsupdate) corta solo nombres: un último rótulo
     «rpz-…» (rpz-ip, rpz-client-ip, rpz-nsip, rpz-nsdname, rpz-passthru…) es un disparador de RPZ por IP del
     cliente, IP de respuesta o servidor de nombres, y nunca es objetivo, ni en el kit ni en el cliente.
- N4 El cliente del proveedor valida los nombres con las mismas reglas que el kit: para cualquier texto, el
     cliente acepta exactamente lo que el kit acepta y en la misma forma canónica (ni más estricto ni más laxo).
"""
from __future__ import annotations

import importlib.util
import random
import unittest
from pathlib import Path

from marca import dominios
from marca import kit as K

RAIZ = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("cliente_proveedor_r3b", RAIZ / "herramientas" / "cliente_proveedor.py")
cp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cp)

CON_GUION_BAJO = ["b12_hd.pizarronhd.test", "live_hd.pirata.test", "_cdn.pirata.test", "s1_pirata.test",
                  "a_.pirata.test", "x.pi_rata.test"]
COMUNES = ["s1.pelotaya.test", "a-b.c-d.example", "x9.tribuna-pirata.test", "mitienda.com.ar", "pirata.test",
           "xn--pelota-9za.example", "rpz-tv.example", "tv.rpz-ip.example"]
DISPARADORES_RPZ = ["10.0.0.64.100.rpz-client-ip", "1.0.0.0.0.rpz-client-ip", "1.0.0.0.0.rpz-ip",
                    "1.0.0.0.0.rpz-nsip", "ns1.proveedor.example.rpz-nsdname", "8.0.0.0.10.RPZ-CLIENT-IP",
                    "s1.pirata.rpz-passthru", "s1.pirata.rpz-drop", "s1.pirata.rpz-tcp-only"]
MALOS = ["s1 pirata.test", "s1.pirata.test\n", "s1.pirata.test;flush ruleset", "*.pirata.test", "pirata.",
         "pirata", "com", "com.ar", "co.uk", "test", "a..b", ".pirata.test", "-x.test", "x-.test",
         "a" * 64 + ".test", ("a" * 63 + ".") * 4 + "test", "ejemplo.123", "203.0.113.10", "K.pirata.test",
         "ñandú.test", "s1.pirata.test\x00", "s1\t.pirata.test", "", None, 5, "int.ar", "mil.ar", "tur.ar",
         "in-addr.arpa"] + DISPARADORES_RPZ


def vista(*hosts):
    return {"v": 3, "minuto": 10, "proveedor": {"id": "valle", "nombre": "FibraValle"},
            "vigentes": [{"tipo": "dominio", "objetivo": h, "vence_min": 105} for h in hosts]}


class GuionBajo(unittest.TestCase):
    def test_n1_lo_que_el_motor_manda_tiene_su_linea(self):
        """N1: dominios acepta el nombre con «_» y el kit lo publica en las cuatro salidas y en su kit."""
        for h in CON_GUION_BAJO + COMUNES:
            with self.subTest(h=h):
                self.assertTrue(dominios.es_hostname(h))
                self.assertTrue(dominios.objetivo_valido("dominio", h))
                self.assertEqual(K.objetivo_seguro("dominio", h), h)
                entradas = K.kit("dominio", h, 105, 10, "EXP-0001", "abcdef0123456789")
                self.assertNotEqual(entradas[0].get("equipo"), "Objetivo no válido")
                v = vista(h)
                self.assertIn(h + "\n", K.lista_dominios(v))
                self.assertIn(f'local-zone: "{h}." always_nxdomain', K.unbound_conf(v))
                self.assertIn(f"\n{h} CNAME .\n", K.zona_rpz(v))
                self.assertNotIn("descartado", K.lista_dominios(v))

    def test_n1_el_cliente_aplica_el_nombre_con_guion_bajo(self):
        """N1: el cliente del proveedor también lo acepta y lo escribe tal cual."""
        for h in CON_GUION_BAJO:
            with self.subTest(h=h):
                self.assertEqual(cp.objetivo_valido("dominio", h), h)
                self.assertIn(f'local-zone: "{h}." always_nxdomain', cp.texto_unbound("valle", {"ord-1": {"tipo": "dominio", "objetivo": h}}))

    def test_n2_las_demas_defensas_siguen(self):
        """N2: lo que no es un nombre de host concreto no es objetivo ni sale en ninguna lista."""
        self.assertFalse(dominios.objetivo_valido("dominio", "pirata.test."))  # la orden va sin punto final
        self.assertEqual(K.objetivo_seguro("dominio", "pirata.test."), "pirata.test")  # el kit lo normaliza (K14)
        for h in MALOS:
            with self.subTest(h=h):
                self.assertFalse(dominios.objetivo_valido("dominio", h))
                self.assertIsNone(K.objetivo_seguro("dominio", h))
                self.assertIsNone(cp.objetivo_valido("dominio", h))


class DisparadoresRpz(unittest.TestCase):
    def test_n3_no_son_objetivo(self):
        """N3: un último rótulo «rpz-…» no es objetivo en dominios, en el kit ni en el cliente."""
        for h in DISPARADORES_RPZ:
            with self.subTest(h=h):
                self.assertFalse(dominios.objetivo_valido("dominio", h))
                self.assertIsNone(K.objetivo_seguro("dominio", h))
                self.assertEqual(K.kit("dominio", h, 105, 10, "EXP-0001", "abcdef0123456789")[0]["equipo"],
                                 "Objetivo no válido")
                self.assertIsNone(cp.objetivo_valido("dominio", h))

    def test_n3_zona_rpz_y_nsupdate_no_publican_disparadores(self):
        """N3: rpz.zone solo trae nombres que se cortan; la línea de nsupdate, también."""
        zona = K.zona_rpz(vista(*DISPARADORES_RPZ, "b12.pizarronhd.test")).lower()
        for linea in zona.splitlines():
            if not linea.startswith(";"):
                self.assertNotIn("rpz-", linea)
        self.assertIn("\nb12.pizarronhd.test cname .\n", zona)
        self.assertIn(f"; {len(DISPARADORES_RPZ)} objetivo(s) descartado(s)", zona)
        bind = [e for e in K.kit("dominio", "b12.pizarronhd.test", 105, 10, "EXP-0001", "abcdef0123456789")
                if e["equipo"] == "BIND (RPZ)"][0]
        self.assertIn("update add b12.pizarronhd.test.rpz.local. 60 CNAME .", bind["aplicar"])


class MismasReglasKitYCliente(unittest.TestCase):
    def test_n4_mismas_listas_de_sufijos(self):
        """N4: el cliente (que no importa la plataforma) lleva la misma lista de sufijos pelados que dominios."""
        self.assertEqual(set(cp._SUFIJOS), set(dominios.SUFIJOS_PELADOS))

    def test_n4_mismo_veredicto_para_cualquier_texto(self):
        """N4: para una muestra fija y miles de textos al azar (semilla fija), cliente == kit, con la misma forma
        canónica."""
        muestra = CON_GUION_BAJO + COMUNES + MALOS + [
            "S1.Pelotaya.TEST", "s1.pelotaya.test.", "B12_HD.pizarronhd.test.", "x." + "a" * 63 + ".test",
            ("a" * 61 + ".") * 4 + "test", "_._", "a._", "1a.test", "a.1test", "a.b-", "a.-b", "a.b_", "x.rpz-",
            "x.rpz", "x.Rpz-Ip", "203.0.113.10.test", "localhost.localdomain", "x.in-addr.arpa", "in-addr.arpa."]
        alfabeto = "ab1_-.xZrpz-." + "K\n ;*%"
        azar = random.Random(20261112)
        for _ in range(4000):
            muestra.append("".join(azar.choice(alfabeto) for _ in range(azar.randint(1, 14))))
        diferencias = []
        for h in muestra:
            del_kit = K.objetivo_seguro("dominio", h)
            del_cliente = cp.objetivo_valido("dominio", h)
            if del_kit != del_cliente:
                diferencias.append((h, del_kit, del_cliente))
        self.assertEqual(diferencias, [])


if __name__ == "__main__":
    unittest.main()
