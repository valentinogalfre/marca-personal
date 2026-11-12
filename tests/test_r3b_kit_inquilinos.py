"""Contrato kit-2 (lado del kit y del cliente): ningún sitio que la plataforma clasificó como ajeno y que cuelga de un
nombre bloqueado (`vigentes[].no_cortar`) queda cortado por una línea de Unbound que publica la plataforma o que
escribe el cliente del proveedor; el nombre del stream y cualquier otro subdominio suyo siguen cortados. Sin
`no_cortar`, unbound.conf es el de siempre. El kit y el cliente escriben las mismas líneas."""
from __future__ import annotations

import importlib.util
import re
import unittest
from pathlib import Path

from marca import kit as K

RAIZ = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("cliente_proveedor_r3b_inq", RAIZ / "herramientas" / "cliente_proveedor.py")
cp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cp)

HOST = "cdn.hostingbarato.test"
INQ = ["panaderia-sol.cdn.hostingbarato.test", "tienda-lucia.cdn.hostingbarato.test"]
RAROS = ["otro.sitio.test", HOST, "mal\n.cdn.hostingbarato.test", "x.rpz-ip", 5, None,
         'a" always_nxdomain\nlocal-zone: "com.cdn.hostingbarato.test']


def zona_que_rige(texto, nombre):
    """Regla de Unbound: manda la local-zone más específica que cubre al nombre."""
    zonas = {}
    for l in texto.splitlines():
        m = re.fullmatch(r'local-zone: "(.+)\." (always_nxdomain|transparent)', l)
        if m:
            zonas[m.group(1)] = m.group(2)
    partes = nombre.split(".")
    for i in range(len(partes)):
        if ".".join(partes[i:]) in zonas:
            return zonas[".".join(partes[i:])]
    return None


def vista(vigentes, minuto=10):
    return {"v": 4, "minuto": minuto, "proveedor": {"id": "valle", "nombre": "FibraValle"}, "vigentes": vigentes}


def vig(objetivo, no_cortar=None, vence=105):
    o = {"orden_id": "ord-" + objetivo.split(".")[0], "tipo": "dominio", "objetivo": objetivo, "vence_min": vence}
    if no_cortar is not None:
        o["no_cortar"] = no_cortar
    return o


class InquilinosEnElKit(unittest.TestCase):
    def test_kit2_unbound_conf_no_corta_a_los_ajenos_conocidos(self):
        """El stream y un subdominio desconocido quedan en always_nxdomain; los inquilinos conocidos, transparent."""
        t = K.unbound_conf(vista([vig(HOST, INQ + RAROS + ["TIENDA-LUCIA.cdn.hostingbarato.test."])]))
        self.assertEqual(zona_que_rige(t, HOST), "always_nxdomain")
        self.assertEqual(zona_que_rige(t, "www." + HOST), "always_nxdomain")
        for n in INQ:
            self.assertEqual(zona_que_rige(t, n), "transparent", n)
        datos = [l for l in t.splitlines() if not l.startswith("#")]
        self.assertEqual(datos, [f'local-zone: "{HOST}." always_nxdomain']
                         + [f'local-zone: "{n}." transparent' for n in INQ])
        self.assertIn(K.LINEAS_TRANSPARENT, t.splitlines()[1])
        self.assertNotIn("descartado", t)  # los nombres raros de no_cortar se ignoran: no son órdenes

    def test_kit2_una_orden_le_gana_a_la_excepcion(self):
        t = K.unbound_conf(vista([vig(HOST, INQ), vig(INQ[0])]))
        self.assertEqual(zona_que_rige(t, INQ[0]), "always_nxdomain")
        self.assertEqual(zona_que_rige(t, INQ[1]), "transparent")

    def test_kit2_orden_vencida_no_deja_excepciones(self):
        t = K.unbound_conf(vista([vig(HOST, INQ, vence=8)]))
        self.assertNotIn("local-zone", t)

    def test_kit2_la_excepcion_de_una_orden_vencida_no_vale_aunque_otra_siga(self):
        """Solo cuentan los no_cortar de vigentes que rigen: otra orden vencida sobre el mismo nombre no libera nada."""
        t = K.unbound_conf(vista([vig(HOST), dict(vig(HOST, INQ, vence=8), orden_id="ord-vieja")]))
        self.assertEqual(zona_que_rige(t, INQ[0]), "always_nxdomain")
        self.assertNotIn("transparent", t)

    def test_kit2_tope_de_nombres_por_orden(self):
        """Una vista con miles de «inquilinos» no infla el archivo: a lo sumo MAX_NO_CORTAR por orden, en el kit y
        en el cliente (los primeros que trae la lista)."""
        muchos = [f"i{n:04d}.{HOST}" for n in range(K.MAX_NO_CORTAR + 50)]
        t = K.unbound_conf(vista([vig(HOST, muchos)]))
        self.assertEqual(sum(l.endswith(" transparent") for l in t.splitlines()), K.MAX_NO_CORTAR)
        self.assertEqual(cp.MAX_NO_CORTAR, K.MAX_NO_CORTAR)
        self.assertEqual(cp.no_cortar(muchos, HOST), muchos[:cp.MAX_NO_CORTAR])

    def test_kit2_sin_no_cortar_queda_igual(self):
        sin = K.unbound_conf(vista([vig(HOST)]))
        self.assertEqual(sin, K.unbound_conf(vista([vig(HOST, [])])))
        self.assertNotIn("transparent", sin)
        self.assertEqual(sin.splitlines()[1], "# " + K.DATOS_NO_COMANDOS + " " + K.CADA_LINEA_UNBOUND)

    def test_kit2_las_otras_listas_no_cambian(self):
        """dominios.txt, rpz.zone (corta solo el nombre exacto) e ips.txt no llevan los inquilinos."""
        con, sin = vista([vig(HOST, INQ)]), vista([vig(HOST)])
        for f in (K.lista_dominios, K.zona_rpz, K.lista_ips):
            self.assertEqual(f(con), f(sin), f.__name__)


class MismasLineasKitYCliente(unittest.TestCase):
    def test_kit2_kit_y_cliente_escriben_lo_mismo(self):
        """Para la misma lista, las líneas de datos del unbound.conf del kit y del archivo del cliente coinciden."""
        vigentes = [vig(HOST, INQ + RAROS), vig(INQ[0]), vig("s1.pelotaya.test", ["www.s1.pelotaya.test"]),
                    vig("b12_hd.pizarronhd.test")]
        v = vista(vigentes)
        aplicadas = {}
        for o in vigentes:
            obj = cp.objetivo_valido("dominio", o["objetivo"])
            aplicadas[o["orden_id"]] = {"tipo": "dominio", "objetivo": obj}
            libres = cp.no_cortar(o.get("no_cortar"), obj)
            if libres:
                aplicadas[o["orden_id"]]["no_cortar"] = libres
        del_kit = [l for l in K.unbound_conf(v).splitlines() if not l.startswith("#")]
        del_cliente = [l for l in cp.texto_unbound("valle", aplicadas).splitlines() if not l.startswith("#")]
        self.assertEqual(del_kit, del_cliente)
        self.assertIn('local-zone: "www.s1.pelotaya.test." transparent', del_kit)


if __name__ == "__main__":
    unittest.main()
