"""Contratos del cliente de referencia del proveedor chico (`herramientas/cliente_proveedor.py`, sección 5.3).

Cada prueba levanta su propia plataforma falsa (`http.server` en 127.0.0.1, puerto elegido por el sistema) que
sirve `GET /proveedor/<id>/vigentes.json` con la forma de la sección 5.2. El reloj se inyecta: nada depende de la
hora real ni espera, salvo las pruebas del pedido que gotea (C10), donde el tiempo real es el contrato.

Contratos:
- C1 Una orden nueva produce «+ BLOQUEAR» y su objetivo aparece en los archivos.
- C2 Una orden que deja de figurar, o que figura en `retiradas`, produce «− QUITAR» con el motivo y sale de los archivos.
- C3 Un objetivo malicioso o mal formado nunca llega a ningún archivo (y se avisa). Solo entran IP que una orden real
     puede apuntar (nada de zonas `%`, privadas, CGNAT, loopback, etc.) y nombres de host válidos; al armar cada
     archivo se vuelve a revisar cada línea y, si una falla, no se escribe nada.
- C4 Si la plataforma no responde o responde algo fuera del contrato (o supera los topes), lo aplicado no cambia y
     `--una-vez` sale con 1, con una línea de aviso y sin traceback. Ningún error al leer tira el proceso.
- C5 Si nada cambió, los archivos no se reescriben; cuando cambian, el reemplazo es atómico (temporal en la misma
     carpeta), conserva permisos, dueño y grupo, y si falla se reintenta sin dar el cambio por hecho.
- C6 `--al-cambiar` corre sin shell, con tope de tiempo y sin stdin: al arrancar, cada vez que cambió un archivo y,
     si falla, en cada vuelta hasta que salga bien (también con la plataforma caída).
- C7 Lo vencido se quita aunque la plataforma no responda, a la hora estimada: nunca antes de que venza de verdad,
     con tope de 6 horas, medido con reloj monotónico, y también tras un reinicio sin `--estado` explícito.
- C8 El estado guardado: un reinicio no repite «+ BLOQUEAR» ni pierde lo retirado; un estado roto se aparta y se
     avisa; nada que el programa no pueda justificar queda bloqueado.
- C9 La salida no se rompe por los símbolos aunque la terminal no sea UTF-8; Ctrl-C termina limpio.
- C10 Red: ningún pedido dura más que el tope total aunque el servidor mande de a gotas; no se siguen redirecciones.
- C11 Una lista vieja o repetida nunca agrega bloqueos ni revive una orden levantada.
- C12 `--una-vez` sale con 0 solo si quedó todo aplicado: 1 sin lista, 3 si no pudo escribir, 4 si la recarga falló.
- C13 Los avisos tienen tope (memoria y líneas por vuelta) y nunca muestran caracteres de control crudos.
"""
from __future__ import annotations

import contextlib
import errno
import hashlib
import http.client
import importlib.util
import io
import json
import os
import re
import shlex
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parents[1]
SCRIPT = RAIZ / "herramientas" / "cliente_proveedor.py"

_spec = importlib.util.spec_from_file_location("cliente_proveedor", SCRIPT)
cp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cp)

PID = "isp-chico"
LINEA_UNBOUND = re.compile(r'local-zone: "[a-z0-9_.-]+\." always_nxdomain')
LINEA_IP = re.compile(r"[0-9a-f:.]+")
CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def orden(oid, tipo, objetivo, vence_min=80, vence_hora="21:45"):
    return {"orden_id": oid, "tipo": tipo, "objetivo": objetivo, "vence_min": vence_min, "vence_hora": vence_hora,
            "juzgado": "Juzgado de prueba", "juez": "Jueza de prueba", "firma": "en_persona", "desde_min": 5,
            "url": f"/orden/{oid}"}


def lista(vigentes=(), retiradas=(), minuto=10.0, pid=PID, **extra):
    d = {"v": 1, "proveedor": {"id": pid, "nombre": "ISP chico", "capacidades": ["dns", "ip"]},
         "minuto": minuto, "hora": "21:00", "generado_utc": "2026-11-13T00:00:00+00:00",
         "partido": {"nombre": "Prueba", "fin_min": 95, "fin_hora": "22:35"},
         "vigentes": list(vigentes), "retiradas": list(retiradas)}
    d.update(extra)
    return d


def levantada(o):
    return {"orden_id": o["orden_id"], "tipo": o["tipo"], "objetivo": o["objetivo"], "motivo": "levantada", "min": 30}


DOM = orden("ord-0001-u1-isp-chico-01-a1b2c3d4", "dominio", "s2.ejemplo.test")
IP = orden("ord-0001-u1-isp-chico-02-e5f6a7b8", "ip", "203.0.113.10", vence_hora="21:50")


class Plataforma:
    """Plataforma falsa: sirve lo que la prueba le diga en `estado`/`cuerpo`. `al_pedir` (si está) corre al llegar
    cada pedido, antes de responder: sirve para armar el cuerpo con el reloj inyectado o para simular demora."""

    def __init__(self):
        self.estado = 200
        self.cuerpo = b"{}"
        self.cabeceras = {}
        self.pedidos = 0
        self.al_pedir = None
        plataforma = self

        class Manejador(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                plataforma.pedidos += 1
                if self.path != f"/proveedor/{PID}/vigentes.json":
                    self.send_response(404)
                    self.end_headers()
                    return
                if plataforma.al_pedir:
                    plataforma.al_pedir()
                self.send_response(plataforma.estado)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(plataforma.cuerpo)))
                for k, v in plataforma.cabeceras.items():
                    self.send_header(k, v)
                self.end_headers()
                try:
                    self.wfile.write(plataforma.cuerpo)
                except OSError:
                    pass  # el cliente cortó antes (respuesta de más): es lo esperado

            def log_message(self, *a):
                pass

        class Servidor(ThreadingHTTPServer):
            def handle_error(self, request, client_address):
                pass

        self.servidor = Servidor(("127.0.0.1", 0), Manejador)
        self.url = f"http://127.0.0.1:{self.servidor.server_address[1]}"
        self.hilo = threading.Thread(target=self.servidor.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self.hilo.start()
        self.cerrada = False

    def poner(self, datos, estado=200):
        self.estado = estado
        self.cuerpo = datos if isinstance(datos, bytes) else json.dumps(datos).encode("utf-8")

    def cerrar(self):
        if not self.cerrada:
            self.servidor.shutdown()
            self.servidor.server_close()
            self.cerrada = True


class Reloj:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


class SimPartido:
    """Partido simulado sobre la plataforma falsa. El minuto se calcula con el reloj inyectado cuando llega el pedido
    (el peor caso para el cliente) y la respuesta llega `demora` segundos después. Cada respuesta es distinta
    (`generado_utc`), como en la plataforma real."""

    def __init__(self, plat, reloj, ordenes, minuto0=40.0, acel=1.0):
        self.plat, self.reloj, self.ordenes = plat, reloj, ordenes
        self.t_base, self.m_base, self.acel = reloj.t, minuto0, acel
        self.demora = 0.0
        self.forzar_minuto = None
        self.n = 0
        plat.al_pedir = self.servir

    def minuto(self):
        return self.m_base + (self.reloj.t - self.t_base) * self.acel / 60.0

    def cambiar(self, acel=None, salto=0.0):
        self.m_base, self.t_base = self.minuto() + salto, self.reloj.t
        if acel is not None:
            self.acel = acel

    def t_real(self, vence_min):
        return self.t_base + (vence_min - self.m_base) * 60.0 / self.acel

    def servir(self):
        self.n += 1
        m = self.forzar_minuto if self.forzar_minuto is not None else round(self.minuto(), 2)
        self.forzar_minuto = None
        d = lista(self.ordenes, minuto=m, generado_utc=f"2026-11-13T00:00:{self.n:06d}Z")
        self.plat.cuerpo = json.dumps(d).encode("utf-8")
        self.reloj.t += self.demora
        self.demora = 0.0


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.dir.name)
        self.unbound = self.tmp / "bloqueo.conf"
        self.ips = self.tmp / "ips.txt"
        self.estado = self.tmp / "estado.json"
        self.plat = Plataforma()
        self.reloj = Reloj()
        self.dichos, self.avisos = [], []

    def tearDown(self):
        self.plat.cerrar()
        self.dir.cleanup()

    def cliente(self, **kw):
        kw.setdefault("salida_unbound", str(self.unbound))
        kw.setdefault("salida_ips", str(self.ips))
        kw.setdefault("estado", str(self.estado))
        kw.setdefault("reloj", self.reloj)
        return cp.Cliente(self.plat.url, PID, decir=self.dichos.append, avisar=self.avisos.append, **kw)

    def lineas(self, ruta):
        return [x for x in Path(ruta).read_text(encoding="utf-8").splitlines() if x and not x.startswith("#")]

    def cli(self, *extra, env=None, estado=True, salidas=True):
        args = [sys.executable, str(SCRIPT), "--plataforma", self.plat.url, "--proveedor", PID]
        if salidas:
            args += ["--salida-unbound", str(self.unbound), "--salida-ips", str(self.ips)]
        if estado:
            args += ["--estado", str(self.estado)]
        args += ["--una-vez", *extra]
        entorno = dict(os.environ, **(env or {}))
        return subprocess.run(args, capture_output=True, timeout=60, env=entorno, cwd=str(self.tmp))

    def main_en_proceso(self, *argv):
        err, out = io.StringIO(), io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
            codigo = cp.main(["--plataforma", self.plat.url, "--proveedor", PID, *argv], reloj=self.reloj)
        return codigo, out.getvalue(), err.getvalue()


# --- C1 / C2 ---------------------------------------------------------------------------------------------------

class TestAplicarYQuitar(Base):
    def test_c1_orden_nueva_bloquea_y_aparece_en_archivos(self):
        """C1: «+ BLOQUEAR» con orden y vencimiento, y el objetivo en el archivo que corresponde."""
        self.plat.poner(lista([DOM, IP]))
        self.assertTrue(self.cliente().pasada())
        self.assertIn(f"+ BLOQUEAR dominio s2.ejemplo.test · orden {DOM['orden_id']} · vence 21:45", self.dichos)
        self.assertIn(f"+ BLOQUEAR ip 203.0.113.10 · orden {IP['orden_id']} · vence 21:50", self.dichos)
        self.assertEqual(self.lineas(self.unbound), ['local-zone: "s2.ejemplo.test." always_nxdomain'])
        self.assertEqual(self.lineas(self.ips), ["203.0.113.10"])

    def test_c2_orden_que_deja_de_figurar_se_quita(self):
        """C2: si la orden ya no figura, «− QUITAR … · ya no figura» y sale del archivo."""
        c = self.cliente()
        self.plat.poner(lista([DOM, IP]))
        c.pasada()
        self.dichos.clear()
        self.plat.poner(lista([IP]))
        self.assertTrue(c.pasada())
        self.assertEqual(self.dichos, [f"− QUITAR dominio s2.ejemplo.test · orden {DOM['orden_id']} · ya no figura"])
        self.assertEqual(self.lineas(self.unbound), [])
        self.assertEqual(self.lineas(self.ips), ["203.0.113.10"])

    def test_c2_orden_en_retiradas_se_quita_con_su_motivo(self):
        """C2: si figura en `retiradas`, el motivo es el que dice la plataforma (levantada, vencida)."""
        c = self.cliente()
        self.plat.poner(lista([DOM, IP]))
        c.pasada()
        self.dichos.clear()
        self.plat.poner(lista([], retiradas=[
            {"orden_id": DOM["orden_id"], "tipo": "dominio", "objetivo": DOM["objetivo"], "motivo": "levantada", "min": 30},
            {"orden_id": IP["orden_id"], "tipo": "ip", "objetivo": IP["objetivo"], "motivo": "vencida", "min": 80}]))
        c.pasada()
        self.assertIn(f"− QUITAR dominio s2.ejemplo.test · orden {DOM['orden_id']} · levantada", self.dichos)
        self.assertIn(f"− QUITAR ip 203.0.113.10 · orden {IP['orden_id']} · vencida", self.dichos)
        self.assertEqual(self.lineas(self.unbound), [])
        self.assertEqual(self.lineas(self.ips), [])

    def test_c2_vigente_y_retirada_a_la_vez_no_se_aplica(self):
        """C2: una orden que la lista da por retirada no se bloquea aunque también figure como vigente."""
        self.plat.poner(lista([DOM], retiradas=[{"orden_id": DOM["orden_id"], "motivo": "levantada"}]))
        self.cliente().pasada()
        self.assertEqual(self.lineas(self.unbound), [])
        self.assertFalse(any(d.startswith("+") for d in self.dichos))


# --- C3 --------------------------------------------------------------------------------------------------------

class TestValidacion(Base):
    MALOS = [
        orden("ord-m-01", "dominio", 'malo".test'),
        orden("ord-m-02", "dominio", 'a.test." always_nxdomain\nlocal-zone: "com'),
        orden("ord-m-03", "dominio", 'x.test"; rm -rf /'),
        orden("ord-m-04", "dominio", ".".join(["a" * 60] * 5)),          # 304 caracteres, rótulos válidos
        orden("ord-m-05", "dominio", "con espacio.test"),
        orden("ord-m-06", "dominio", "test"),                            # un solo rótulo: tiraría todo el TLD
        orden("ord-m-07", "dominio", "com.ar"),                          # sufijo de registro
        orden("ord-m-08", "dominio", "-guion.test"),
        orden("ord-m-09", "dominio", "203.0.113.99"),                    # IP disfrazada de dominio
        orden("ord-m-10", "ip", "203.0.113.11\n10.0.0.1"),
        orden("ord-m-11", "ip", "203.0.113.12; rm -rf /"),
        orden("ord-m-12", "ip", "0.0.0.0"),
        orden("ord-m-13", "ip", "127.0.0.1"),
        orden("ord-m-14", "comando", "reboot"),
        orden('ord-m-15"\n', "dominio", "bien.test"),                    # número de orden con salto de línea
        orden("ord-m-16", "dominio", ["lista.test"]),
        orden("ord-m-17", "dominio", "ñandu.test"),
        orden("ord-m-18", "dominio", "bien.test\n"),                     # salto de línea al final ($ lo deja pasar)
        orden("ord-m-19", "dominio", "a\n.b\n.test"),
        orden("ord-m-20", "dominio", "\u212aejemplo.test"),              # signo Kelvin: lower() lo vuelve «k»
        orden("ord-m-21\n", "dominio", "bien.test"),
    ]

    def test_c3_objetivo_malicioso_nunca_llega_a_un_archivo(self):
        """C3: solo lo que valida se escribe; cada línea del archivo tiene la forma exacta; se avisa lo descartado."""
        bueno_dom = orden("ord-b-01", "dominio", "S3.Ejemplo.TEST")
        bueno_ip = orden("ord-b-02", "ip", "2001:db8::1")
        self.plat.poner(lista(self.MALOS + [bueno_dom, bueno_ip]))
        self.assertTrue(self.cliente().pasada())
        unbound = self.lineas(self.unbound)
        ips = self.lineas(self.ips)
        self.assertEqual(unbound, ['local-zone: "s3.ejemplo.test." always_nxdomain'])
        self.assertEqual(ips, ["2001:db8::1"])
        for linea in unbound:
            self.assertRegex(linea, LINEA_UNBOUND)
        crudo = self.unbound.read_text(encoding="utf-8") + self.ips.read_text(encoding="utf-8")
        for veneno in ("rm -rf", "malo", "com\"", "10.0.0.1", "0.0.0.0", "127.0.0.1", "reboot", "aaaa", "kejemplo"):
            self.assertNotIn(veneno, crudo)
        self.assertEqual(len(self.avisos), len(self.MALOS), self.avisos)
        self.assertTrue(all(not CONTROL.search(a) for a in self.avisos), self.avisos)
        self.assertEqual(len([d for d in self.dichos if d.startswith("+ BLOQUEAR")]), 2)
        estado = self.estado.read_text(encoding="utf-8")
        self.assertNotIn("rm -rf", estado)

    def test_c3_validadores(self):
        """C3: reglas del nombre de host y de la IP, una por una (con fullmatch: un «\\n» al final no pasa)."""
        self.assertEqual(cp.host_valido("a-b.c1.test"), "a-b.c1.test")
        self.assertEqual(cp.host_valido("x." * 126 + "ab"), None)               # 254 caracteres
        self.assertIsNotNone(cp.host_valido(("a" * 63 + ".") * 3 + "a" * 61))     # 253 justos
        self.assertEqual(cp.host_valido("a_b.test"), "a_b.test")                # «_» vale, como en el kit (C16)
        self.assertEqual(cp.host_valido("A.Test."), "a.test")                   # forma canónica, como el kit
        for malo in ('a"b.test', "a\nb.test", "a b.test", "a..test", "a.test..", "x.rpz-ip", "", None, 5,
                     "bien.test\n", "a\n.test", "pirata\n.com", "com.ar\n", "a\n.pirata\n.com\n", "\u212aejemplo.test",
                     "a.b\t", "10.0.0.1", "1.2.3.4"):
            self.assertIsNone(cp.host_valido(malo), repr(malo))
        self.assertEqual(cp.ip_valida("2001:0db8::0001"), "2001:db8::1")
        for malo in (" 1.2.3.4", "1.2.3.4 ", "1.2.3", "::", "::1", "224.0.0.1", "169.254.1.1", "[2001:db8::1]",
                     "203.0.113.5\n", "\u0663.1.1.1"):
            self.assertIsNone(cp.ip_valida(malo), repr(malo))
        self.assertTrue(cp.orden_id_valido("ord-1"))
        for malo in ("ord-1\n", "", "-ord", "ord 1", None, 7, "x" * 129):
            self.assertFalse(cp.orden_id_valido(malo), repr(malo))
        self.assertTrue(cp.hora_valida("21:45"))
        self.assertFalse(cp.hora_valida("21:45\n"))

    def test_c3_ip_con_zona_nunca_mete_lineas_en_la_lista_de_ip(self):
        """C3 (zona IPv6): ninguna IP con «%…» llega al archivo de IP ni al estado; cada línea es una IP sola."""
        zonas = ["2001:db8::1%\n0.0.0.0-255.255.255.255", "2001:db8::2%\n127.0.0.1\n10.0.0.1",
                 "2001:db8::3%;flush ruleset", "2001:db8::4%eth0", "2001:db8::5%\x00", "2001:db8::6%é",
                 "2001:db8::7%", "2001:db8::1%\n192.168.88.1", "2001:db8::8%1"]
        for z in zonas:
            self.assertIsNone(cp.ip_valida(z), repr(z))
        malos = [orden(f"ord-z-{i:02d}", "ip", z) for i, z in enumerate(zonas)]
        self.plat.poner(lista(malos + [IP]))
        self.assertTrue(self.cliente().pasada())
        crudo = self.ips.read_text(encoding="utf-8")
        self.assertEqual(self.lineas(self.ips), ["203.0.113.10"])
        for linea in self.lineas(self.ips):
            self.assertTrue(LINEA_IP.fullmatch(linea), linea)
        for veneno in ("%", "0.0.0.0", "127.0.0.1", "10.0.0.1", "flush", "\x00", "eth0", "192.168.88.1"):
            self.assertNotIn(veneno, crudo)
        estado = self.estado.read_text(encoding="utf-8")
        self.assertNotIn("%", estado)
        self.assertNotIn("192.168.88.1", estado)
        self.assertEqual(len(self.avisos), len(zonas), self.avisos)
        self.assertTrue(all("\n" not in d for d in self.dichos + self.avisos))

    INFRA = ["10.0.0.1", "172.16.0.1", "172.31.255.254", "192.168.88.1", "100.64.0.1", "100.127.255.254", "0.1.2.3",
             "240.0.0.1", "255.255.255.255", "fc00::1", "fd12:3456::1", "::ffff:127.0.0.1", "::ffff:10.0.0.1",
             "::ffff:0.0.0.0", "2002:7f00:1::1", "2002:a00:1::1", "64:ff9b::a00:1", "64:ff9b:1::1", "fe80::1",
             "fec0::1", "ff02::1", "198.18.0.1", "192.0.0.8", "2001::1", "::1.2.3.4",
             "2001:2::1", "2001:10::1", "4000::1", "fe00::1"]  # pruebas, ORCHID y reservadas de IPv6

    def test_c3_ip_de_la_red_del_proveedor_nunca_se_bloquea(self):
        """C3: privadas, CGNAT, reservadas, broadcast, ULA, link-local, IPv4 metidas en IPv6: nunca son objetivo.
        Las de documentación (las del simulador) y las públicas sí."""
        for ip in self.INFRA:
            self.assertIsNone(cp.ip_valida(ip), ip)
        for ip in ("203.0.113.10", "198.51.100.7", "192.0.2.5", "2001:db8::1", "8.8.8.8", "2800:3f0:4002::1"):
            self.assertEqual(cp.ip_valida(ip), ip)
        malos = [orden(f"ord-i-{i:02d}", "ip", x) for i, x in enumerate(self.INFRA)]
        self.plat.poner(lista(malos + [IP]))
        self.assertTrue(self.cliente().pasada())
        self.assertEqual(self.lineas(self.ips), ["203.0.113.10"])
        self.assertEqual(len(self.avisos), len(self.INFRA), self.avisos)

    def test_c3_segunda_barrera_no_escribe_una_linea_invalida(self):
        """C3 (segunda barrera): si algo inválido llegara a lo aplicado por otro camino, al armar el archivo se
        detecta, no se escribe ningún archivo y se avisa."""
        self.plat.poner(lista([DOM, IP]))
        c = self.cliente()
        c.pasada()
        antes = (self.unbound.read_bytes(), self.ips.read_bytes())
        self.plat.cerrar()
        malas = {"dominio": 'x.test." always_nxdomain\nlocal-zone: "com', "ip": "10.0.0.1"}
        for tipo, objetivo in malas.items():
            with self.subTest(tipo=tipo):
                c.aplicadas["ord-mala"] = {"orden_id": "ord-mala", "tipo": tipo, "vence_min": 80.0,
                                           "vence_hora": None, "objetivo": objetivo, "vence_local": self.reloj.t + 9e3}
                c.archivos_pendientes = True
                self.avisos.clear()
                c.pasada()
                self.assertEqual((self.unbound.read_bytes(), self.ips.read_bytes()), antes)
                self.assertTrue(any("no escribo" in a for a in self.avisos), self.avisos)
                self.assertTrue(all(not CONTROL.search(a) for a in self.avisos), self.avisos)
                del c.aplicadas["ord-mala"]

    def test_c3_orden_ya_vencida_en_la_misma_lista_no_se_aplica(self):
        """C3: una entrada con `vence_min` <= `minuto` no rige: no se bloquea."""
        self.plat.poner(lista([orden("ord-v-01", "ip", "203.0.113.20", vence_min=10)], minuto=10))
        self.cliente().pasada()
        self.assertEqual(self.lineas(self.ips), [])


# --- C4 --------------------------------------------------------------------------------------------------------

ENTERO_GIGANTE = int("9" * 400)
ANIDADO = b'{"minuto": ' + b"[" * 100000 + b"]" * 100000 + b"}"


class TestPlataformaCaida(Base):
    def _base_buena(self):
        self.plat.poner(lista([DOM, IP]))
        r = self.cli()
        self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace"))
        foto = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (self.unbound, self.ips)}
        self.assertIn(b"s2.ejemplo.test", foto[self.unbound][0])
        return foto

    def _sin_cambios(self, foto, r):
        err = r.stderr.decode("utf-8")
        self.assertEqual(r.returncode, 1, err)
        self.assertNotIn("Traceback", err)
        self.assertEqual(len(err.strip().splitlines()), 1, err)
        self.assertIn("Sigo con lo último que apliqué", err)
        for p, (datos, mtime) in foto.items():
            self.assertEqual(p.read_bytes(), datos)
            self.assertEqual(p.stat().st_mtime_ns, mtime)

    def test_c4_respuestas_fuera_de_contrato_no_cambian_nada(self):
        """C4: 500, no-JSON, JSON fuera de forma, otro proveedor, NaN, entero gigante, anidado sin fin, más de 2 MB o
        de 5000 órdenes -> nada cambia, sale 1, una línea sin traceback."""
        foto = self._base_buena()
        casos = [
            (b"error", 500),
            (b"<html>no es json</html>", 200),
            (json.dumps([1, 2, 3]).encode(), 200),
            (json.dumps({"vigentes": []}).encode(), 200),
            (json.dumps(lista([], pid="otro-isp")).encode(), 200),
            (json.dumps(dict(lista([]), vigentes="no-lista")).encode(), 200),
            (json.dumps(lista([])).replace('"minuto": 10.0', '"minuto": NaN').encode(), 200),
            (json.dumps(lista([], minuto=ENTERO_GIGANTE)).encode(), 200),
            (ANIDADO, 200),
            (b" " * (cp.MAX_BYTES + 10), 200),
            (json.dumps(lista([orden(f"ord-x-{i}", "ip", "203.0.113.30") for i in range(cp.MAX_ENTRADAS + 1)])).encode(), 200),
        ]
        for cuerpo, estado in casos:
            with self.subTest(cuerpo=cuerpo[:40], estado=estado):
                self.plat.poner(cuerpo, estado)
                self._sin_cambios(foto, self.cli())

    def test_c4_interpretar_solo_levanta_lista_invalida(self):
        """C4: `interpretar` rechaza toda respuesta fuera de contrato con ListaInvalida (su contrato), sin dejar
        escapar errores internos de Python (recursión, desborde), aunque el bucle tenga su propia red."""
        for cuerpo in (ANIDADO, json.dumps(lista([], minuto=ENTERO_GIGANTE)).encode(), b"\xff\xfe", b"[]"):
            with self.subTest(cuerpo=cuerpo[:20]):
                with self.assertRaises(cp.ListaInvalida):
                    cp.interpretar(cuerpo, PID)

    def test_c4_plataforma_apagada_no_cambia_nada(self):
        """C4: conexión rechazada -> nada cambia, sale 1, una línea sin traceback."""
        foto = self._base_buena()
        self.plat.cerrar()
        self._sin_cambios(foto, self.cli())

    def test_c4_tope_en_proceso_no_cambia_lo_aplicado(self):
        """C4: superar el tope de órdenes no borra lo aplicado (el cliente sigue con la lista anterior)."""
        c = self.cliente()
        self.plat.poner(lista([DOM]))
        c.pasada()
        self.plat.poner(lista([orden(f"ord-x-{i}", "ip", "203.0.113.30") for i in range(cp.MAX_ENTRADAS + 1)]))
        self.assertFalse(c.pasada())
        self.assertEqual(self.lineas(self.unbound), ['local-zone: "s2.ejemplo.test." always_nxdomain'])
        self.assertIn(DOM["orden_id"], c.aplicadas)

    def test_c4_tope_de_retiradas(self):
        """C4: más de MAX_ENTRADAS retiradas también es fuera de tope: lo aplicado no cambia."""
        c = self.cliente()
        self.plat.poner(lista([DOM]))
        c.pasada()
        self.plat.poner(lista([], retiradas=[{"orden_id": f"ord-r-{i}", "motivo": "vencida"}
                                             for i in range(cp.MAX_ENTRADAS + 1)]))
        self.assertFalse(c.pasada())
        self.assertEqual(self.lineas(self.unbound), ['local-zone: "s2.ejemplo.test." always_nxdomain'])

    def test_c4_lista_sin_minuto_no_cambia_nada(self):
        """C4: una lista del proveedor correcto sin `minuto` se rechaza (no se toma como minuto 0)."""
        c = self.cliente()
        self.plat.poner(lista([IP], minuto=10.0))
        c.pasada()
        antes = dict(c.aplicadas[IP["orden_id"]])
        sin_minuto = lista([IP])
        del sin_minuto["minuto"]
        self.plat.poner(sin_minuto)
        self.avisos.clear()
        self.assertFalse(c.pasada())
        self.assertEqual(c.aplicadas[IP["orden_id"]], antes)
        self.assertTrue(any("minuto" in a for a in self.avisos), self.avisos)
        # Sin una lista anterior (no puede pasar por «lista vieja»): tampoco se aplica nada.
        nuevo = self.cliente(estado=str(self.tmp / "otro-estado.json"))
        self.avisos.clear()
        self.assertFalse(nuevo.pasada())
        self.assertNotIn(IP["orden_id"], nuevo.aplicadas)
        self.assertTrue(any("no trae el minuto" in a for a in self.avisos), self.avisos)

    def test_c4_respuesta_enorme_no_se_lee_entera(self):
        """C4: con una respuesta de 3 × MAX_BYTES el cliente deja de leer apenas pasa el tope (no la junta entera)."""
        leidos = []
        original = http.client.HTTPResponse.read

        def contar(yo, *a, **kw):
            datos = original(yo, *a, **kw)
            leidos.append(len(datos))
            return datos

        c = self.cliente()
        self.plat.poner(lista([DOM]))
        c.pasada()
        self.plat.poner(b" " * (3 * cp.MAX_BYTES))
        with mock.patch.object(http.client.HTTPResponse, "read", contar):
            self.assertFalse(c.pasada())
        self.assertLessEqual(sum(leidos), cp.MAX_BYTES + 64 * 1024)
        self.assertIn(DOM["orden_id"], c.aplicadas)

    def test_c4_campo_raro_en_una_entrada_no_tira_el_cliente(self):
        """C4: un `motivo` que no es texto, un `vence_min` que no entra en un float o un `acelerar` raro se
        descartan sin traceback; lo bueno se aplica."""
        bueno = orden("ord-ok-01", "dominio", "bien.ejemplo.test")
        gigante = orden("ord-g-01", "ip", "203.0.113.77", vence_min=ENTERO_GIGANTE)
        self.plat.poner(lista([bueno, gigante], retiradas=[{"orden_id": "ord-r-01", "motivo": []},
                                                         {"orden_id": "ord-r-02", "motivo": {"a": 1}}],
                              acelerar={"x": 1}))
        r = self.cli()
        err = r.stderr.decode("utf-8")
        self.assertEqual(r.returncode, 0, err)
        self.assertNotIn("Traceback", err)
        self.assertEqual(self.lineas(self.unbound), ['local-zone: "bien.ejemplo.test." always_nxdomain'])
        self.assertEqual(self.lineas(self.ips), [])

    def test_c4_cualquier_error_al_leer_cae_en_quitar_lo_vencido(self):
        """C4+C7: si interpretar la lista falla por cualquier motivo no previsto, la vuelta sigue por la rama
        «sigo con lo último que apliqué» y lo vencido se quita igual."""
        c = self.cliente()
        self.plat.poner(lista([orden("ord-t-09", "ip", "203.0.113.42", vence_min=11)], minuto=10.0))
        c.pasada()
        self.reloj.t += 61
        self.avisos.clear()
        with mock.patch.object(cp, "interpretar", side_effect=TypeError("campo fuera de contrato")):
            self.assertFalse(c.pasada())
        self.assertEqual(self.lineas(self.ips), [])
        self.assertTrue(any("Sigo con lo último" in a for a in self.avisos), self.avisos)

    def test_c4_una_vuelta_que_falla_no_corta_el_bucle(self):
        """C4: aunque una vuelta entera falle por algo no previsto, el bucle de main sigue y Ctrl-C termina con 0."""
        vueltas = []

        def dormir(s):
            vueltas.append(s)
            if len(vueltas) == 3:
                raise KeyboardInterrupt

        err = io.StringIO()
        with mock.patch.object(cp.Cliente, "pasada", side_effect=RuntimeError("roto")), \
                contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            codigo = cp.main(["--plataforma", self.plat.url, "--proveedor", PID, "--salida-ips", str(self.ips)],
                             reloj=self.reloj, dormir=dormir)
        self.assertEqual(codigo, 0)
        self.assertEqual(len(vueltas), 3)
        self.assertNotIn("Traceback", err.getvalue())
        self.assertEqual(err.getvalue().count("falló una vuelta"), 3, err.getvalue())


# --- C5 --------------------------------------------------------------------------------------------------------

class TestEscritura(Base):
    def test_c5_si_nada_cambio_no_se_reescribe(self):
        """C5: segunda pasada con la misma lista -> misma fecha de modificación y mismo inodo en los dos archivos."""
        c = self.cliente()
        self.plat.poner(lista([DOM, IP]))
        c.pasada()
        viejo = 1_000_000_000
        for p in (self.unbound, self.ips):
            os.utime(p, (viejo, viejo))
        inodos = {p: p.stat().st_ino for p in (self.unbound, self.ips)}
        self.plat.poner(lista([DOM, IP], minuto=11.0))
        self.assertTrue(c.pasada())
        for p in (self.unbound, self.ips):
            self.assertEqual(p.stat().st_mtime_ns, viejo * 10**9, p)
            self.assertEqual(p.stat().st_ino, inodos[p], p)
        self.assertEqual([x for x in os.listdir(self.tmp) if x.endswith(".tmp")], [])

    def test_c5_escritura_atomica_reemplaza_y_conserva_permisos(self):
        """C5: cuando cambia, el archivo se reemplaza entero (inodo nuevo), legible por el servidor DNS (0644)."""
        c = self.cliente()
        self.plat.poner(lista([DOM]))
        c.pasada()
        self.assertEqual(self.unbound.stat().st_mode & 0o777, 0o644)
        ino = self.unbound.stat().st_ino
        self.plat.poner(lista([]))
        c.pasada()
        self.assertNotEqual(self.unbound.stat().st_ino, ino)
        self.assertEqual(self.unbound.stat().st_mode & 0o777, 0o644)

    def test_c5_conserva_el_modo_de_un_archivo_existente(self):
        """C5: un archivo que el operador dejó en 0640 sigue en 0640 después del reemplazo (inodo nuevo)."""
        self.unbound.write_text("# viejo\n")
        os.chmod(self.unbound, 0o640)
        ino = self.unbound.stat().st_ino
        self.plat.poner(lista([DOM]))
        self.cliente().pasada()
        self.assertEqual(self.unbound.stat().st_mode & 0o777, 0o640)
        self.assertNotEqual(self.unbound.stat().st_ino, ino)

    def test_c5_temporal_en_la_carpeta_del_destino(self):
        """C5: el temporal se crea en la carpeta del destino (si no, os.replace entre sistemas de archivos falla)."""
        original = os.replace

        def replace_mismo_fs(a, b):
            if os.path.dirname(os.path.abspath(a)) != os.path.dirname(os.path.abspath(b)):
                raise OSError(errno.EXDEV, "otro sistema de archivos")
            return original(a, b)

        self.plat.poner(lista([DOM, IP]))
        with mock.patch.object(cp.os, "replace", replace_mismo_fs):
            self.cliente().pasada()
        self.assertEqual(self.lineas(self.ips), ["203.0.113.10"])
        self.assertFalse(any("no pude escribir" in a for a in self.avisos), self.avisos)

    def _grupo_ajeno(self):
        for g in os.getgroups():
            if g not in (os.getegid(), os.stat(self.tmp).st_gid):
                return g
        self.skipTest("el usuario no tiene otro grupo para probar")

    def test_c5_conserva_dueno_y_grupo(self):
        """C5: el reemplazo atómico conserva el dueño y el grupo del archivo que ya existía (0640 root:unbound)."""
        g = self._grupo_ajeno()
        self.unbound.write_text("# viejo\n")
        os.chown(self.unbound, -1, g)
        os.chmod(self.unbound, 0o640)
        self.plat.poner(lista([DOM]))
        self.cliente().pasada()
        st = self.unbound.stat()
        self.assertEqual((st.st_uid, st.st_gid, st.st_mode & 0o777), (os.geteuid(), g, 0o640))
        self.assertIn("s2.ejemplo.test", self.unbound.read_text())

    def test_c5_si_no_puede_conservar_el_grupo_avisa_una_vez_y_escribe(self):
        """C5: si chown falla, el archivo se escribe igual (nunca queda el viejo) y se avisa una sola vez."""
        g = self._grupo_ajeno()
        self.unbound.write_text("# viejo\n")
        os.chown(self.unbound, -1, g)
        c = self.cliente()
        with mock.patch.object(cp.os, "chown", side_effect=PermissionError(errno.EPERM, "no")):
            self.plat.poner(lista([DOM]))
            c.pasada()
            self.plat.poner(lista([]))
            c.pasada()
        self.assertEqual(self.lineas(self.unbound), [])
        self.assertEqual(len([a for a in self.avisos if "grupo" in a and str(self.unbound) in a]), 1, self.avisos)
        self.assertEqual([x for x in os.listdir(self.tmp) if x.endswith(".tmp")], [])

    def test_c5_escritura_fallida_se_reintenta_y_no_dice_quitar_como_hecho(self):
        """C5+C7: con la plataforma caída, si falla la escritura que quita lo vencido, la pantalla dice que quedó
        pendiente, se reintenta en la vuelta siguiente y recién ahí sale del archivo."""
        c = self.cliente()
        self.plat.poner(lista([orden("ord-t-21", "dominio", "corta.ejemplo.test", vence_min=12)], minuto=10.0))
        c.pasada()
        self.plat.cerrar()
        self.reloj.t += 121
        original = os.replace
        fallas = []

        def falla_una_vez(a, b):
            if str(b) == str(self.unbound) and not fallas:
                fallas.append(1)
                raise OSError(errno.ENOSPC, "disco lleno")
            return original(a, b)

        self.dichos.clear()
        with mock.patch.object(cp.os, "replace", falla_una_vez):
            c.pasada()
            self.assertEqual(self.lineas(self.unbound), ['local-zone: "corta.ejemplo.test." always_nxdomain'])
            self.assertEqual(len(self.dichos), 1, self.dichos)
            self.assertIn("− QUITAR dominio corta.ejemplo.test", self.dichos[0])
            self.assertIn("PENDIENTE", self.dichos[0])
            self.assertTrue(any("no pude escribir" in a for a in self.avisos), self.avisos)
            self.reloj.t += 5
            c.pasada()
        self.assertEqual(self.lineas(self.unbound), [])
        self.assertTrue(any("Ya pude escribir" in d for d in self.dichos), self.dichos)


# --- C6 --------------------------------------------------------------------------------------------------------

class Correr:
    """`correr` falso: devuelve los códigos (o levanta lo) que se le pida, en orden; después, 0."""

    def __init__(self, *resultados):
        self.resultados = list(resultados)
        self.llamadas = []

    def __call__(self, args, **kw):
        self.llamadas.append((args, kw))
        r = self.resultados.pop(0) if self.resultados else 0
        if isinstance(r, BaseException):
            raise r
        return subprocess.CompletedProcess(args, r)


class TestAlCambiar(Base):
    COMANDO = ["/usr/sbin/unbound-control", "reload"]

    def test_c6_corre_solo_cuando_hubo_cambios_y_sin_shell(self):
        """C6: el comando fijo se corre una vez por cambio, como lista de argumentos y con shell=False."""
        correr = Correr()
        c = self.cliente(al_cambiar=self.COMANDO, correr=correr)
        self.plat.poner(lista([DOM]))
        c.pasada()
        self.assertEqual(len(correr.llamadas), 1)
        self.assertEqual(correr.llamadas[0][0], self.COMANDO)
        self.assertIs(correr.llamadas[0][1].get("shell"), False)
        c.pasada()
        self.plat.poner(b"caida", 500)
        c.pasada()
        self.assertEqual(len(correr.llamadas), 1, "sin cambios no se corre")
        self.plat.poner(lista([]))
        c.pasada()
        self.assertEqual(len(correr.llamadas), 2)

    def test_c6_por_linea_de_comandos_no_pasa_por_un_shell(self):
        """C6: un «;» en el comando llega como argumento, no separa comandos; y nada de la lista entra al comando.
        Cada proceso recarga una vez al arrancar (no sabe qué tiene cargado el DNS) y no más si nada cambia."""
        registro = self.tmp / "registro.txt"
        trampa = self.tmp / "trampa"
        codigo = ("import sys, pathlib; p = pathlib.Path(sys.argv[1]); "
                  "p.write_text(p.read_text() + repr(sys.argv[2:]) + '\\n' if p.exists() else repr(sys.argv[2:]) + '\\n')")
        comando = " ".join(shlex.quote(x) for x in (sys.executable, "-c", codigo, str(registro))) + \
            f" ';' touch {shlex.quote(str(trampa))}"
        self.plat.poner(lista([orden("ord-s-01", "dominio", "s9.ejemplo.test")]))
        r = self.cli("--al-cambiar", comando)
        self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace"))
        r = self.cli("--al-cambiar", comando)          # misma lista: no hay cambio, pero es otro proceso
        self.assertEqual(r.returncode, 0)
        self.assertFalse(trampa.exists(), "el «;» se interpretó: pasó por un shell")
        corridas = registro.read_text().splitlines()
        self.assertEqual(corridas, [repr([";", "touch", str(trampa)])] * 2)
        self.assertNotIn("s9.ejemplo.test", registro.read_text())

    def test_c6_recarga_fallida_se_reintenta_hasta_salir_bien_tambien_caida(self):
        """C6: si la recarga falla (código, tope de tiempo o programa que no está), se reintenta en cada vuelta,
        aunque la lista no cambie o la plataforma esté caída; cuando sale bien, no se repite sin cambios."""
        fallas = {"codigo": 1, "tope": subprocess.TimeoutExpired("x", 60), "no existe": FileNotFoundError("x")}
        for nombre, falla in fallas.items():
            with self.subTest(falla=nombre):
                with tempfile.TemporaryDirectory() as d:
                    correr = Correr(0, falla, falla)
                    c = self.cliente(al_cambiar=self.COMANDO, correr=correr, salida_unbound=f"{d}/u.conf",
                                     salida_ips=f"{d}/i.txt", estado=f"{d}/e.json")
                    plat = Plataforma()
                    c.url = plat.url + f"/proveedor/{PID}/vigentes.json"
                    plat.poner(lista([DOM]))
                    c.pasada()                                   # 1: arranque + cambio, sale bien
                    plat.poner(lista([], retiradas=[levantada(DOM)]))
                    c.pasada()                                   # 2: falla
                    self.assertEqual(self.lineas(f"{d}/u.conf"), [])
                    plat.cerrar()
                    c.pasada()                                   # 3: caída, reintenta y falla
                    c.pasada()                                   # 4: caída, reintenta y sale bien
                    c.pasada()
                    c.pasada()
                    self.assertEqual(len(correr.llamadas), 4)
                    self.assertTrue(any("--al-cambiar" in a and "reintento" in a for a in self.avisos), self.avisos)

    def test_c6_arranque_recarga_una_vez_aunque_los_archivos_no_cambien(self):
        """C6: al arrancar no se sabe qué tiene cargado el DNS: la primera vuelta recarga aunque los archivos ya
        estén al día (reinicio de la máquina, o corte entre escribir y recargar), también con la plataforma caída."""
        self.plat.poner(lista([IP]))
        self.cliente().pasada()
        correr = Correr()
        c = self.cliente(al_cambiar=self.COMANDO, correr=correr)
        foto = self.ips.read_bytes()
        c.pasada()
        c.pasada()
        self.assertEqual(len(correr.llamadas), 1)
        self.plat.cerrar()
        correr2 = Correr()
        c2 = self.cliente(al_cambiar=self.COMANDO, correr=correr2)
        c2.pasada()
        c2.pasada()
        self.assertEqual(len(correr2.llamadas), 1)
        self.assertEqual(self.ips.read_bytes(), foto)

    def test_c6_corte_durante_la_recarga_de_un_levantamiento_se_recarga_al_rearrancar(self):
        """C6: si el proceso se corta entre escribir el archivo sin la orden levantada y recargar, el próximo
        arranque recarga (si no, el DNS seguiría bloqueando una orden levantada)."""
        correr = Correr(0, KeyboardInterrupt())
        c = self.cliente(al_cambiar=self.COMANDO, correr=correr)
        self.plat.poner(lista([IP]))
        c.pasada()
        self.plat.poner(lista([], retiradas=[levantada(IP)]))
        with self.assertRaises(KeyboardInterrupt):
            c.pasada()
        self.assertEqual(self.lineas(self.ips), [])
        correr2 = Correr()
        self.cliente(al_cambiar=self.COMANDO, correr=correr2).pasada()
        self.assertEqual(len(correr2.llamadas), 1)

    def test_c6_al_cambiar_con_tope_de_tiempo_y_sin_stdin(self):
        """C6: el comando tiene un tope de tiempo finito y no hereda stdin; un comando colgado no impide quitar
        lo vencido."""
        correr = Correr(subprocess.TimeoutExpired("x", 60))
        c = self.cliente(al_cambiar=self.COMANDO, correr=correr)
        self.plat.poner(lista([orden("ord-t-31", "ip", "203.0.113.43", vence_min=11)], minuto=10.0))
        c.pasada()
        kw = correr.llamadas[0][1]
        self.assertTrue(0 < kw.get("timeout", 0) <= 300, kw)
        self.assertIs(kw.get("stdin"), subprocess.DEVNULL)
        self.plat.cerrar()
        self.reloj.t += 61
        c.pasada()
        self.assertEqual(self.lineas(self.ips), [])

    def test_c6_windows_conserva_las_barras_de_la_ruta(self):
        """C6 (Windows, leído): la ruta de --al-cambiar llega entera, con y sin comillas; en POSIX no cambia nada."""
        self.assertEqual(cp.partir_comando(r"C:\scripts\recargar-dns.bat", windows=True),
                         [r"C:\scripts\recargar-dns.bat"])
        self.assertEqual(cp.partir_comando(r'"C:\Program Files\Unbound\unbound-control.exe" reload', windows=True),
                         [r"C:\Program Files\Unbound\unbound-control.exe", "reload"])
        self.assertEqual(cp.partir_comando("/usr/sbin/unbound-control reload", windows=False),
                         ["/usr/sbin/unbound-control", "reload"])
        self.assertEqual(cp.partir_comando("'/opt/mi dns/recargar' --ya", windows=False),
                         ["/opt/mi dns/recargar", "--ya"])


# --- C7 --------------------------------------------------------------------------------------------------------

class TestVencimientoLocal(Base):
    def test_c7_lo_vencido_se_quita_aunque_la_plataforma_no_responda(self):
        """C7: con la plataforma caída, se quita cada orden al llegar su hora local estimada (y no antes)."""
        c = self.cliente()
        corta = orden("ord-t-01", "dominio", "corta.ejemplo.test", vence_min=12)
        larga = orden("ord-t-02", "ip", "203.0.113.40", vence_min=30)
        self.plat.poner(lista([corta, larga], minuto=10.0))
        t0 = self.reloj.t
        c.pasada()
        self.assertEqual(c.aplicadas[corta["orden_id"]]["vence_local"], t0 + 120)
        self.plat.cerrar()
        self.dichos.clear()
        self.reloj.t = t0 + 119
        self.assertFalse(c.pasada())
        self.assertEqual(self.dichos, [])
        self.assertEqual(self.lineas(self.unbound), ['local-zone: "corta.ejemplo.test." always_nxdomain'])
        self.reloj.t = t0 + 121
        self.assertFalse(c.pasada())
        self.assertEqual(self.dichos, [
            "− QUITAR dominio corta.ejemplo.test · orden ord-t-01 · vencida (según la última lista)"])
        self.assertEqual(self.lineas(self.unbound), [])
        self.assertEqual(self.lineas(self.ips), ["203.0.113.40"])

    def test_c7_se_quita_justo_en_la_hora_local(self):
        """C7: con la plataforma caída, en t == hora estimada la orden ya sale (sin demora extra)."""
        c = self.cliente()
        self.plat.poner(lista([orden("ord-t-05", "ip", "203.0.113.44", vence_min=12)], minuto=10.0))
        t0 = self.reloj.t
        c.pasada()
        self.plat.cerrar()
        self.reloj.t = t0 + 120
        c.pasada()
        self.assertEqual(self.lineas(self.ips), [])

    def test_c7_con_ritmo_acelerado_vence_antes_en_hora_local(self):
        """C7: si el partido corre acelerado (ensayo), la hora local de vencimiento usa la velocidad medida: nunca
        antes de la hora real, y apenas después (la medición descuenta lo que redondea la plataforma)."""
        c = self.cliente()
        o = orden("ord-t-03", "ip", "203.0.113.41", vence_min=30)
        t0 = self.reloj.t
        self.plat.poner(lista([o], minuto=10.0))
        c.pasada()
        self.reloj.t = t0 + 12                          # 12 s reales = 12 min de partido: x60
        self.plat.poner(lista([o], minuto=22.0))
        c.pasada()
        vence = c.aplicadas["ord-t-03"]["vence_local"]
        self.assertGreaterEqual(vence, t0 + 20)
        self.assertLess(vence, t0 + 20.1)
        self.plat.cerrar()
        self.reloj.t = t0 + 21
        c.pasada()
        self.assertEqual(self.lineas(self.ips), [])

    def _dos_lecturas(self, m0, dt, m1, vence_min):
        c = self.cliente()
        o = orden("ord-r-01", "ip", "203.0.113.45", vence_min=vence_min)
        self.plat.poner(lista([o], minuto=m0))
        c.pasada()
        self.reloj.t += dt
        self.plat.poner(lista([o], minuto=m1))
        c.pasada()
        return c.aplicadas["ord-r-01"]["vence_local"] - self.reloj.t

    def test_c7_velocidad_medida_menor_que_uno_usa_uno(self):
        """C7: si el reloj del partido parece ir más lento que el real (pausa, ruido), se usa 1: una pausa nunca
        estira un bloqueo con la plataforma caída."""
        self.assertAlmostEqual(self._dos_lecturas(10, 120, 11, 30), 19 * 60, places=6)

    def test_c7_velocidad_medida_tiene_tope(self):
        """C7: la velocidad medida no pasa de RITMO_MAX."""
        self.assertAlmostEqual(self._dos_lecturas(10, 60, 100000, 200000), 100000 * 60 / cp.RITMO_MAX, places=6)

    def test_c7_velocidad_medida_descuenta_redondeo_y_duracion_del_pedido(self):
        """C7: la cota de velocidad resta lo que redondea la plataforma (0,01 min) y suma la duración del pedido
        anterior: nunca sobreestima. 10→15 min en 5 s con un primer pedido de 1 s da (5 − 0,01)·60/6."""
        c = self.cliente()
        o = orden("ord-r-02", "ip", "203.0.113.46", vence_min=100)
        demoras = [1.0]

        def demorar():
            if demoras:
                self.reloj.t += demoras.pop()

        self.plat.al_pedir = demorar
        self.plat.poner(lista([o], minuto=10.0))
        c.pasada()
        self.reloj.t += 5
        self.plat.poner(lista([o], minuto=15.0))
        c.pasada()
        ritmo = (5 - 0.01) * 60 / 6
        self.assertAlmostEqual(c.aplicadas["ord-r-02"]["vence_local"] - self.reloj.t, 85 * 60 / ritmo, places=6)

    def test_c7_ritmo_nunca_adelanta_el_vencimiento(self):
        """C7: con la plataforma caída, ningún bloqueo se quita antes de su vencimiento real (salvo lo que redondea
        la plataforma), y sí se quita poco después: pedido lento, reinicio de la plataforma, salto del minuto,
        cambio de velocidad y ensayo acelerado estable."""
        def caso(nombre, guion):
            with self.subTest(caso=nombre), tempfile.TemporaryDirectory() as d:
                reloj = Reloj()
                plat = Plataforma()
                o = orden("ord-n-01", "ip", "203.0.113.50", vence_min=71)
                sim = SimPartido(plat, reloj, [o])
                c = cp.Cliente(plat.url, PID, salida_ips=f"{d}/i.txt", estado=f"{d}/e.json", reloj=reloj,
                               decir=lambda t: None, avisar=lambda t: None)
                guion(sim, c, reloj)
                plat.cerrar()
                real = sim.t_real(71)
                margen = 0.01 * 60 / sim.acel
                vence = c.aplicadas["ord-n-01"]["vence_local"]
                self.assertGreaterEqual(vence, real - margen, f"quita {real - vence:.1f} s antes")
                falta = real - reloj.t
                self.assertLessEqual(vence, real + 0.05 * falta + 2, f"quita {vence - real:.1f} s tarde")
                reloj.t = real - margen - 0.01
                c.pasada()
                self.assertEqual(self.lineas(f"{d}/i.txt"), ["203.0.113.50"])
                reloj.t = vence + 0.01
                c.pasada()
                self.assertEqual(self.lineas(f"{d}/i.txt"), [])

        def pedido_lento(sim, c, reloj):
            sim.demora = cp.TIMEOUT_S - 0.1
            c.pasada()
            for _ in range(2):
                reloj.t += 10
                c.pasada()

        def reinicio_de_la_plataforma(sim, c, reloj):
            for _ in range(3):
                c.pasada()
                reloj.t += 5
            sim.forzar_minuto = 0.5                    # recién reiniciada, antes de leer el simulador
            c.pasada()
            reloj.t += 5
            c.pasada()
            reloj.t += 20

        def salto_del_minuto(sim, c, reloj):
            for _ in range(3):
                c.pasada()
                reloj.t += 5
            sim.cambiar(salto=25)
            c.pasada()
            reloj.t += 5

        def de_x20_a_x1(sim, c, reloj):
            sim.cambiar(acel=20)
            for _ in range(10):
                c.pasada()
                reloj.t += 5
            sim.cambiar(acel=1)
            c.pasada()
            reloj.t += 5
            c.pasada()

        def x20_estable(sim, c, reloj):
            sim.cambiar(acel=20)
            for _ in range(12):
                c.pasada()
                reloj.t += 5

        for nombre, guion in (("pedido lento", pedido_lento), ("reinicio", reinicio_de_la_plataforma),
                              ("salto", salto_del_minuto), ("x20 a x1", de_x20_a_x1), ("x20", x20_estable)):
            caso(nombre, guion)

    def test_c7_velocidad_declarada_vale_desde_la_primera_lectura(self):
        """C7: si la lista trae `acelerar`, con una sola lectura alcanza: la orden sale a su hora real."""
        c = self.cliente()
        self.plat.poner(lista([orden("ord-a-01", "dominio", "acel.ejemplo.test", vence_min=15)], minuto=10.0,
                              acelerar=6))
        t0 = self.reloj.t
        c.pasada()
        self.plat.cerrar()
        self.reloj.t = t0 + 49
        c.pasada()
        self.assertEqual(self.lineas(self.unbound), ['local-zone: "acel.ejemplo.test." always_nxdomain'])
        self.reloj.t = t0 + 51
        c.pasada()
        self.assertEqual(self.lineas(self.unbound), [])

    def test_c7_velocidad_declarada_fuera_de_rango_se_ignora(self):
        """C7: un `acelerar` inválido (menor que 1, no numérico, enorme) se ignora con aviso: se mide."""
        for valor in (0, 0.5, -6, "6", True, None, 10**9, float(cp.RITMO_MAX) * 2):
            with self.subTest(acelerar=valor):
                self.reloj.t += 10_000
                c = self.cliente(estado=None)
                self.plat.poner(lista([orden(f"ord-a-{abs(hash(str(valor)))}", "ip", "203.0.113.47", vence_min=11)],
                                      minuto=10.0, acelerar=valor))
                c.pasada()
                o = next(iter(c.aplicadas.values()))
                self.assertAlmostEqual(o["vence_local"], self.reloj.t + 60, places=6)

    def test_c7_tope_de_seis_horas_desde_la_ultima_lista(self):
        """C7: con la plataforma caída, ninguna orden queda aplicada más de 6 horas desde la última lista buena,
        sea cual sea `vence_min`; el estado es JSON estricto y sobrevive al reinicio."""
        casos = {"lejano": (1e12, 10.0), "desborde": (1.7e308, -1.7e308), "minuto negativo": (105, -1e6)}
        for nombre, (vence_min, minuto) in casos.items():
            with self.subTest(caso=nombre), tempfile.TemporaryDirectory() as d:
                reloj = Reloj()
                plat = Plataforma()
                plat.poner(lista([orden("ord-6-01", "ip", "203.0.113.48", vence_min=vence_min)], minuto=minuto))
                kw = dict(salida_ips=f"{d}/i.txt", estado=f"{d}/e.json", reloj=reloj, decir=lambda t: None,
                          avisar=lambda t: None)
                t0 = reloj.t
                cp.Cliente(plat.url, PID, **kw).pasada()
                plat.cerrar()
                texto = Path(f"{d}/e.json").read_text(encoding="utf-8")
                json.loads(texto, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
                reloj.t = t0 + cp.TOPE_VENCE_LOCAL_S - 1
                c = cp.Cliente(plat.url, PID, **kw)
                c.pasada()
                self.assertEqual(self.lineas(f"{d}/i.txt"), ["203.0.113.48"])
                reloj.t = t0 + cp.TOPE_VENCE_LOCAL_S + 1
                c.pasada()
                self.assertEqual(self.lineas(f"{d}/i.txt"), [])

    def test_c7_tope_tambien_para_un_estado_guardado(self):
        """C7: un estado guardado con una hora de vencimiento lejísima se acota al cargarlo (6 h desde ahora)."""
        self.estado.write_text(json.dumps({"v": cp.VERSION_ESTADO, "proveedor": PID, "aplicadas": {
            "ord-6-02": {"orden_id": "ord-6-02", "tipo": "ip", "objetivo": "203.0.113.49", "vence_min": 90,
                         "vence_local": 9e15}}}))
        self.ips.write_text("203.0.113.49\n")
        self.plat.cerrar()
        c = self.cliente()
        c.pasada()
        self.assertEqual(self.lineas(self.ips), ["203.0.113.49"])
        self.reloj.t += cp.TOPE_VENCE_LOCAL_S + 1
        c.pasada()
        self.assertEqual(self.lineas(self.ips), [])

    def test_c7_salto_del_reloj_del_sistema_no_cambia_cuanto_falta(self):
        """C7: dentro del proceso, «cuánto falta» se mide con reloj monotónico: si el reloj del sistema salta una
        hora (adelante o atrás) con la plataforma caída, el bloqueo sale a su hora, ni antes ni mucho después."""
        for salto in (3600, -3600):
            with self.subTest(salto=salto):
                sist, mono = Reloj(2_000_000.0), Reloj(50.0)
                c = self.cliente(reloj=sist, monotonico=mono, estado=None)
                plat = Plataforma()
                c.url = plat.url + f"/proveedor/{PID}/vigentes.json"
                plat.poner(lista([orden("ord-j-01", "ip", "203.0.113.51", vence_min=12)], minuto=10.0))
                c.pasada()
                plat.cerrar()
                sist.t += salto
                mono.t += 30
                sist.t += 30
                c.pasada()
                self.assertEqual(self.lineas(self.ips), ["203.0.113.51"])
                mono.t += 91
                c.pasada()
                self.assertEqual(self.lineas(self.ips), [])

    def test_c7_reinicio_usa_el_reloj_del_sistema_y_descarta_lecturas_del_futuro(self):
        """C7: entre un arranque y el siguiente vale el reloj del sistema (el monotónico arranca de otro valor);
        lecturas guardadas «del futuro» (el reloj se atrasó) se descartan."""
        sist = Reloj(3_000_000.0)
        self.plat.poner(lista([orden("ord-j-02", "ip", "203.0.113.52", vence_min=12)], minuto=10.0))
        self.cliente(reloj=sist, monotonico=Reloj(10.0)).pasada()
        datos = json.loads(self.estado.read_text(encoding="utf-8"))
        datos["lecturas"].append([sist.t + 1000, 30.0, 0.0])
        self.estado.write_text(json.dumps(datos))
        self.plat.cerrar()
        sist.t += 60
        c = self.cliente(reloj=sist, monotonico=Reloj(99_999.0))
        self.assertTrue(all(x[0] <= 99_999.0 + 5 for x in c.lecturas), c.lecturas)
        c.pasada()
        self.assertEqual(self.lineas(self.ips), ["203.0.113.52"])
        sist.t += 61
        c2 = self.cliente(reloj=sist, monotonico=Reloj(7.0))
        c2.pasada()
        self.assertEqual(self.lineas(self.ips), [])

    def test_c7_el_vencimiento_local_sobrevive_al_reinicio(self):
        """C7+C8: tras reiniciar con la plataforma caída, lo vencido se quita con la hora guardada en el estado."""
        self.plat.poner(lista([orden("ord-t-04", "ip", "203.0.113.42", vence_min=11)], minuto=10.0))
        t0 = self.reloj.t
        self.cliente().pasada()
        self.plat.cerrar()
        self.reloj.t = t0 + 61
        self.assertFalse(self.cliente().pasada())
        self.assertEqual(self.lineas(self.ips), [])

    def test_c7_sin_estado_explicito_el_reinicio_quita_lo_vencido(self):
        """C7: con la línea de comandos de la 5.3 (sin --estado), un proceso nuevo con la plataforma caída quita lo
        vencido, y no antes. El estado va oculto al lado de la primera salida."""
        self.plat.poner(lista([orden("ord-e-01", "ip", "203.0.113.60", vence_min=11)], minuto=10.0))
        t0 = self.reloj.t
        codigo, _, err = self.main_en_proceso("--salida-ips", str(self.ips), "--una-vez")
        self.assertEqual(codigo, 0, err)
        self.assertEqual(self.lineas(self.ips), ["203.0.113.60"])
        self.assertTrue((self.tmp / ".ips.txt.estado.json").exists())
        self.assertFalse(self.estado.exists())
        self.plat.cerrar()
        self.reloj.t = t0 + 59
        codigo, _, _ = self.main_en_proceso("--salida-ips", str(self.ips), "--una-vez")
        self.assertEqual(codigo, 1)
        self.assertEqual(self.lineas(self.ips), ["203.0.113.60"])
        self.reloj.t = t0 + 61
        codigo, _, _ = self.main_en_proceso("--salida-ips", str(self.ips), "--una-vez")
        self.assertEqual(codigo, 1)
        self.assertEqual(self.lineas(self.ips), [])


# --- C8 --------------------------------------------------------------------------------------------------------

class TestEstado(Base):
    def test_c8_el_estado_es_json_estricto(self):
        """C8: el estado nunca lleva Infinity ni NaN (JSON inválido para otro lector): si un valor no es finito, no
        se guarda, se avisa y queda el estado anterior."""
        self.plat.poner(lista([DOM]))
        c = self.cliente()
        c.pasada()
        antes = self.estado.read_text()
        c.aplicadas[DOM["orden_id"]]["vence_local"] = float("inf")
        self.avisos.clear()
        c._guardar_estado()

        def no_finito(x):
            raise AssertionError(f"el estado tiene {x}")

        json.loads(self.estado.read_text(), parse_constant=no_finito)
        self.assertEqual(self.estado.read_text(), antes)
        self.assertTrue(any("no pude guardar el estado" in a for a in self.avisos), self.avisos)

    def test_c8_reinicio_no_repite_ni_pierde(self):
        """C8: tras reiniciar, lo ya aplicado no se anuncia de nuevo y lo levantado mientras tanto se quita."""
        self.plat.poner(lista([DOM, IP]))
        self.cliente().pasada()
        self.dichos.clear()
        self.plat.poner(lista([IP], retiradas=[{"orden_id": DOM["orden_id"], "motivo": "levantada"}]))
        self.cliente().pasada()                        # cliente nuevo = reinicio
        self.assertEqual(self.dichos, [f"− QUITAR dominio s2.ejemplo.test · orden {DOM['orden_id']} · levantada"])

    def test_c8_estado_de_otro_proveedor_no_se_usa_ni_se_toca(self):
        """C8: un estado ajeno (otro proveedor) se ignora con aviso, no se aplica nada de él y no se pisa."""
        ajeno = json.dumps({"v": 1, "proveedor": "otro", "aplicadas": {
            "ord-z-01": {"tipo": "ip", "objetivo": "203.0.113.50", "vence_min": 90, "vence_local": 9e12}}})
        self.estado.write_text(ajeno)
        self.plat.poner(lista([DOM]))
        c = self.cliente()
        self.assertEqual(c.aplicadas, {})
        self.assertTrue(any("otro proveedor" in a for a in self.avisos), self.avisos)
        c.pasada()
        self.assertEqual(self.estado.read_text(), ajeno)
        self.assertFalse(Path(str(self.estado) + ".danado").exists())

    def test_c8_estado_de_otra_version_se_aparta(self):
        """C8: un estado de otra versión no se usa: se mueve a .danado y se avisa."""
        otro = json.dumps({"v": cp.VERSION_ESTADO + 1, "proveedor": PID, "aplicadas": {
            "ord-z-02": {"orden_id": "ord-z-02", "tipo": "ip", "objetivo": "203.0.113.53", "vence_min": 90,
                         "vence_local": 9e12}}})
        self.estado.write_text(otro)
        c = self.cliente()
        self.assertEqual(c.aplicadas, {})
        self.assertEqual(Path(str(self.estado) + ".danado").read_text(), otro)
        self.assertTrue(any(".danado" in a for a in self.avisos), self.avisos)

    def test_c8_estado_ilegible_se_aparta_y_lo_que_no_se_puede_justificar_se_quita(self):
        """C8: con un estado roto y la plataforma caída, el estado se conserva como .danado, se avisa, y los
        bloqueos que quedaron en los archivos sin saber de qué orden son ni cuándo vencen se quitan (con aviso
        y «− QUITAR»): un bloqueo no puede durar más que su orden."""
        self.plat.poner(lista([DOM, IP]))
        self.cliente().pasada()
        self.estado.write_text("{roto")
        self.plat.cerrar()
        self.dichos.clear()
        self.cliente().pasada()
        self.assertEqual(Path(str(self.estado) + ".danado").read_text(), "{roto")
        self.assertEqual(self.lineas(self.unbound), [])
        self.assertEqual(self.lineas(self.ips), [])
        self.assertTrue(any("no sé de qué orden son" in a for a in self.avisos), self.avisos)
        self.assertIn("− QUITAR dominio s2.ejemplo.test · no sé de qué orden es ni cuándo vence", self.dichos)
        self.assertIn("− QUITAR ip 203.0.113.10 · no sé de qué orden es ni cuándo vence", self.dichos)

    def test_c8_sin_estado_la_plataforma_confirma_lo_vigente(self):
        """C8: sin estado y con la plataforma arriba, lo que la lista confirma queda y lo demás se quita."""
        self.unbound.write_text('# viejo\nlocal-zone: "s2.ejemplo.test." always_nxdomain\n'
                                'local-zone: "viejo.ejemplo.test." always_nxdomain\n')
        self.plat.poner(lista([DOM]))
        self.cliente().pasada()
        self.assertEqual(self.lineas(self.unbound), ['local-zone: "s2.ejemplo.test." always_nxdomain'])
        self.assertIn("− QUITAR dominio viejo.ejemplo.test · no sé de qué orden es ni cuándo vence", self.dichos)

    def test_c8_estado_con_objetivo_malicioso_no_llega_a_un_archivo(self):
        """C8+C3: un estado guardado con un objetivo mal formado no se carga ni llega a un archivo."""
        self.estado.write_text(json.dumps({"v": cp.VERSION_ESTADO, "proveedor": PID, "aplicadas": {
            "ord-y-01": {"orden_id": "ord-y-01", "tipo": "dominio", "objetivo": 'a.test." always_nxdomain\nx',
                         "vence_min": 90, "vence_local": 9e12},
            "ord-y-02": {"orden_id": "ord-y-02", "tipo": "ip", "objetivo": "203.0.113.54", "vence_min": 11,
                         "vence_local": self.reloj.t + 1}}}))
        c = self.cliente()
        self.assertNotIn("ord-y-01", c.aplicadas)
        self.plat.cerrar()
        self.reloj.t += 5
        c.pasada()
        self.assertNotIn("always_nxdomain\nx", self.unbound.read_text())
        self.assertEqual(self.lineas(self.unbound), [])

    def test_c8_reinicio_alinea_los_archivos_con_el_estado(self):
        """C8+C5: tras un fallo de escritura y un reinicio con la plataforma caída, el archivo coincide con el
        estado: no queda un bloqueo que el estado ya no tiene."""
        c = self.cliente()
        self.plat.poner(lista([DOM, IP]))
        c.pasada()
        self.plat.poner(lista([IP], retiradas=[levantada(DOM)]))
        original = os.replace

        def falla_unbound(a, b):
            if str(b) == str(self.unbound):
                raise OSError(errno.ENOSPC, "disco lleno")
            return original(a, b)

        with mock.patch.object(cp.os, "replace", falla_unbound):
            c.pasada()
        self.assertIn("s2.ejemplo.test", self.unbound.read_text())
        self.plat.cerrar()
        self.cliente().pasada()
        self.assertEqual(self.lineas(self.unbound), [])
        self.assertEqual(self.lineas(self.ips), ["203.0.113.10"])

    def test_c8_reinicio_reescribe_lo_que_falta_en_el_archivo(self):
        """C8: si al archivo le falta algo que el estado tiene vigente (la escritura que lo agregaba no llegó), el
        reinicio con la plataforma caída lo reescribe igual: archivo y estado quedan iguales."""
        self.plat.poner(lista([DOM, IP]))
        self.cliente().pasada()
        self.ips.write_text("")
        self.plat.cerrar()
        self.cliente().pasada()
        self.assertEqual(self.lineas(self.ips), ["203.0.113.10"])
        self.assertEqual(self.lineas(self.unbound), ['local-zone: "s2.ejemplo.test." always_nxdomain'])


# --- C9 --------------------------------------------------------------------------------------------------------

class TestSalida(Base):
    def test_c9_salida_utf8_aunque_la_terminal_sea_ascii(self):
        """C9: con la salida redirigida y una codificación que no tiene «·» ni «−», no se rompe ni pierde líneas."""
        self.plat.poner(lista([DOM]))
        r = self.cli(env={"PYTHONIOENCODING": "ascii"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("+ BLOQUEAR dominio s2.ejemplo.test · orden", r.stdout.decode("utf-8"))
        self.plat.poner(lista([]))
        r = self.cli(env={"PYTHONIOENCODING": "ascii"})
        self.assertIn("− QUITAR dominio s2.ejemplo.test", r.stdout.decode("utf-8"))
        self.plat.cerrar()
        r = self.cli(env={"PYTHONIOENCODING": "ascii"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("último", r.stderr.decode("utf-8"))
        self.assertNotIn(b"Traceback", r.stderr)

    def test_c9_ctrl_c_termina_limpio(self):
        """C9: sin --una-vez repite; Ctrl-C (KeyboardInterrupt) termina con 0 y sin traceback."""
        self.plat.poner(lista([DOM]))
        vueltas = []

        def dormir(s):
            vueltas.append(s)
            if len(vueltas) == 2:
                raise KeyboardInterrupt

        salida = io.StringIO()
        with contextlib.redirect_stdout(salida):
            codigo = cp.main(["--plataforma", self.plat.url, "--proveedor", PID, "--cada", "5",
                              "--salida-unbound", str(self.unbound)], reloj=self.reloj, dormir=dormir)
        self.assertIn("Listo, corté", salida.getvalue())
        self.assertEqual(codigo, 0)
        self.assertEqual(vueltas, [5.0, 5.0])
        self.assertEqual(self.plat.pedidos, 2)

    def test_c9_sin_proxy(self):
        """C9: las variables de proxy del sistema no desvían el pedido (va directo a la plataforma)."""
        self.plat.poner(lista([DOM]))
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            muerto = s.getsockname()[1]
        r = self.cli(env={"http_proxy": f"http://127.0.0.1:{muerto}", "HTTP_PROXY": f"http://127.0.0.1:{muerto}",
                          "no_proxy": "", "NO_PROXY": ""})
        self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace"))


# --- C10 -------------------------------------------------------------------------------------------------------

class TestRed(Base):
    def setUp(self):
        super().setUp()
        self.parar = threading.Event()
        self.addCleanup(self.parar.set)

    def _servidor_de_gotas(self, inicio: bytes, gota: bytes, conexiones=1) -> str:
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(8)
        self.addCleanup(srv.close)

        def atender_uno(cn):
            with cn:
                try:
                    cn.recv(65536)
                    cn.sendall(inicio)
                    while not self.parar.wait(0.1):
                        cn.sendall(gota)
                except OSError:
                    pass

        def atender():
            for _ in range(conexiones):
                try:
                    cn, _ = srv.accept()
                except OSError:
                    return
                threading.Thread(target=atender_uno, args=(cn,), daemon=True).start()

        threading.Thread(target=atender, daemon=True).start()
        return f"http://127.0.0.1:{srv.getsockname()[1]}"

    def _pasada_acotada(self, url, vueltas=1):
        c = self.cliente()
        self.plat.poner(lista([orden("ord-g-01", "ip", "203.0.113.55", vence_min=80)], minuto=10.0))
        c.pasada()
        self.reloj.t += (80 - 10) * 60 + 1
        c.url = url + f"/proveedor/{PID}/vigentes.json"
        with mock.patch.object(cp, "TIMEOUT_S", 0.3):
            for _ in range(vueltas):
                t = time.monotonic()
                self.assertFalse(c.pasada())
                self.assertLess(time.monotonic() - t, 3 * 0.3 + 1.0)
        self.assertEqual(self.lineas(self.ips), [])
        self.assertTrue(any("vencida" in d for d in self.dichos), self.dichos)
        self.assertTrue(any("tarda demasiado" in a or "siguen sin terminar" in a for a in self.avisos), self.avisos)
        return c

    def test_c10_cabeceras_de_a_gotas(self):
        """C10: un servidor que manda las cabeceras de a un byte (más rápido que el timeout por operación) no
        frena la vuelta más allá del tope total; lo vencido se quita en esa misma vuelta."""
        self._pasada_acotada(self._servidor_de_gotas(b"HTTP/1.1 200 OK\r\nX-Gota: ", b"a"))

    def test_c10_cuerpo_de_a_gotas(self):
        """C10: lo mismo si las gotas son del cuerpo (Content-Length grande, un byte cada 0,1 s)."""
        self._pasada_acotada(self._servidor_de_gotas(
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 1000000\r\n\r\n", b" "))

    def test_c10_goteo_sin_fin_no_acumula_pedidos(self):
        """C10: varias vueltas seguidas contra un servidor que gotea siempre: cada una respeta el tope, y al vencer
        el tope la conexión se corta de verdad (con http no queda ningún pedido colgado ocupando un descriptor)."""
        c = self._pasada_acotada(self._servidor_de_gotas(b"HTTP/1.1 200 OK\r\nX-Gota: ", b"a", conexiones=6),
                                 vueltas=4)
        self.assertEqual([h for h in c._colgados if h.is_alive()], [])
        self.assertFalse(any("siguen sin terminar" in a for a in self.avisos), self.avisos)

    def test_c10_redireccion_no_se_sigue(self):
        """C10: un 3xx hacia otro esquema, equipo, puerto o ruta no se sigue: no sale ninguna conexión al destino,
        se avisa el código y no se bloquea nada."""
        for esquema in ("http", "ftp"):
            with self.subTest(esquema=esquema):
                destino = socket.socket()
                destino.bind(("127.0.0.1", 0))
                destino.listen(1)
                destino.settimeout(0.3)
                self.addCleanup(destino.close)
                self.plat.poner(b"", 302)
                self.plat.cabeceras = {"Location": f"{esquema}://127.0.0.1:{destino.getsockname()[1]}/admin/x"}
                self.avisos.clear()
                self.assertFalse(self.cliente().pasada())
                with self.assertRaises(socket.timeout):
                    destino.accept()
                self.assertTrue(any("302" in a for a in self.avisos), self.avisos)
                self.assertFalse(self.ips.exists() and self.lineas(self.ips))

    def test_c10_solo_http_o_https(self):
        """C10: el cliente rechaza una plataforma que no sea http:// o https://."""
        for url in ("ftp://127.0.0.1:1", "file:///etc", "data:,x"):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    cp.Cliente(url, PID)


# --- C11 -------------------------------------------------------------------------------------------------------

class TestListaViejaORepetida(Base):
    def test_c11_repetir_una_lista_vieja_no_revive_lo_levantado(self):
        """C11: una lista anterior a la última aceptada (minuto menor) no vuelve a bloquear lo levantado; se avisa."""
        c = self.cliente()
        self.plat.poner(lista([DOM], minuto=10))
        c.pasada()
        self.plat.poner(lista([], retiradas=[levantada(DOM)], minuto=20))
        c.pasada()
        self.dichos.clear()
        self.plat.poner(lista([DOM], minuto=10))
        self.assertFalse(c.pasada())
        self.assertEqual(self.dichos, [])
        self.assertEqual(self.lineas(self.unbound), [])
        self.assertTrue(any("ya había recibido" in a for a in self.avisos), self.avisos)

    def test_c11_lista_vieja_nunca_agrega_y_avisa_una_vez(self):
        """C11: una lista vieja no agrega órdenes nuevas, y el aviso sale una sola vez."""
        c = self.cliente()
        self.plat.poner(lista([], minuto=30))
        c.pasada()
        for m in (10, 11, 12):
            self.plat.poner(lista([IP], minuto=m))
            c.pasada()
        self.assertEqual(self.lineas(self.ips), [])
        self.assertEqual(len([a for a in self.avisos if "ya había recibido" in a]), 1, self.avisos)

    def test_c11_lista_vieja_si_quita(self):
        """C11: una lista vieja sí puede quitar: lo que no figura sale."""
        c = self.cliente()
        self.plat.poner(lista([DOM, IP], minuto=20))
        c.pasada()
        self.plat.poner(lista([IP], minuto=10))
        c.pasada()
        self.assertEqual(self.lineas(self.unbound), [])
        self.assertEqual(self.lineas(self.ips), ["203.0.113.10"])

    def test_c11_levantada_no_vuelve_aunque_la_lista_sea_nueva(self):
        """C11: una orden que alguna lista trajo como levantada no se vuelve a bloquear, ni tras reiniciar."""
        c = self.cliente()
        self.plat.poner(lista([DOM], minuto=10))
        c.pasada()
        self.plat.poner(lista([], retiradas=[levantada(DOM)], minuto=20))
        c.pasada()
        self.plat.poner(lista([DOM], minuto=21))
        c.pasada()
        self.assertEqual(self.lineas(self.unbound), [])
        self.plat.poner(lista([DOM], minuto=22))
        self.cliente().pasada()
        self.assertEqual(self.lineas(self.unbound), [])

    def test_c11_el_minuto_mas_alto_vence_a_las_seis_horas(self):
        """C11: el minuto más alto recordado deja de valer pasadas 6 horas (otro partido, otro día): una lista con
        minuto bajo vuelve a aplicarse."""
        for reinicia in (False, True):
            with self.subTest(reinicia=reinicia):
                estado = str(self.tmp / f"estado-{reinicia}.json")
                c = self.cliente(estado=estado)
                self.plat.poner(lista([], minuto=90))
                c.pasada()
                self.assertEqual(self.lineas(self.ips), [])
                self.reloj.t += cp.TOPE_VENCE_LOCAL_S + 1
                self.plat.poner(lista([IP], minuto=5))
                self.assertTrue((self.cliente(estado=estado) if reinicia else c).pasada())
                self.assertEqual(self.lineas(self.ips), ["203.0.113.10"])

    def test_c11_lista_identica_no_renueva_el_vencimiento(self):
        """C11: si la plataforma devuelve exactamente el mismo cuerpo (caché, espejo) durante más de 60 s reales,
        no se toma como lista nueva: se avisa una vez y cada bloqueo sale a su hora estimada."""
        c = self.cliente()
        self.plat.poner(lista([orden("ord-c-01", "dominio", "pirata.ejemplo.test", vence_min=20)], minuto=10.0))
        t0 = self.reloj.t
        resultados = []
        while self.reloj.t < t0 + 3600:
            resultados.append(c.pasada())
            if not self.lineas(self.unbound):
                break
            self.reloj.t += 5
        self.assertLessEqual(self.reloj.t, t0 + 600 + 5)
        self.assertTrue(any("− QUITAR dominio pirata.ejemplo.test" in d for d in self.dichos), self.dichos)
        self.assertEqual(len([a for a in self.avisos if "misma lista" in a]), 1, self.avisos)
        self.assertFalse(resultados[-1])

    def test_c11_pausa_real_del_partido_manda_la_plataforma(self):
        """C11: con el partido en pausa (minuto quieto, pero cada respuesta nueva), manda la plataforma: el bloqueo
        sigue toda la pausa y no hay aviso de lista repetida."""
        c = self.cliente()
        n = [0]

        def nueva():
            n[0] += 1
            self.plat.poner(lista([orden("ord-c-02", "dominio", "pausa.ejemplo.test", vence_min=20)], minuto=10.0,
                                  generado_utc=f"2026-11-13T00:00:{n[0]:06d}Z"))

        self.plat.al_pedir = nueva
        t0 = self.reloj.t
        while self.reloj.t < t0 + 3600:
            self.assertTrue(c.pasada())
            self.reloj.t += 5
        self.assertEqual(self.lineas(self.unbound), ['local-zone: "pausa.ejemplo.test." always_nxdomain'])
        self.assertFalse(any("misma lista" in a for a in self.avisos), self.avisos)

    def test_c11_lista_repetida_entre_procesos(self):
        """C11: lo mismo con `--una-vez` desde cron: la huella de la última lista se guarda en el estado."""
        self.plat.poner(lista([orden("ord-c-03", "ip", "203.0.113.56", vence_min=20)], minuto=10.0))
        t0 = self.reloj.t
        self.cliente().pasada()
        self.reloj.t = t0 + 601
        self.assertFalse(self.cliente().pasada())
        self.assertEqual(self.lineas(self.ips), [])


# --- C12 -------------------------------------------------------------------------------------------------------

class TestCodigosDeSalida(Base):
    def test_c12_codigos_de_salida_de_una_vez(self):
        """C12: 0 si quedó todo aplicado; 1 si no pudo leer la lista; 3 si no pudo escribir un archivo; 4 si la
        recarga falló o el programa no existe. Están en --help."""
        self.plat.poner(lista([DOM]))
        self.assertEqual(self.cli().returncode, 0)
        self.assertEqual(self.cli("--al-cambiar", "/usr/bin/false").returncode, 4)
        self.assertEqual(self.cli("--al-cambiar", str(self.tmp / "no-existe")).returncode, 4)
        self.assertEqual(self.cli("--al-cambiar", "/usr/bin/true").returncode, 0)
        cerrada = self.tmp / "cerrada"
        cerrada.mkdir()
        os.chmod(cerrada, 0o555)
        try:
            r = subprocess.run([sys.executable, str(SCRIPT), "--plataforma", self.plat.url, "--proveedor", PID,
                                "--salida-ips", str(cerrada / "ips.txt"), "--una-vez"], capture_output=True,
                               timeout=60)
        finally:
            os.chmod(cerrada, 0o755)
        self.assertEqual(r.returncode, 3, r.stderr.decode("utf-8", "replace"))
        self.assertFalse((cerrada / "ips.txt").exists())
        self.plat.poner(b"caida", 500)
        self.assertEqual(self.cli().returncode, 1)
        ayuda = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, timeout=30)
        texto = ayuda.stdout.decode("utf-8")
        self.assertEqual(ayuda.returncode, 0)
        for codigo in ("0", "1", "2", "3", "4"):
            self.assertRegex(texto, rf"(?m)^\s*{codigo}\s")
        self.assertNotIn("ritmo", texto)
        self.assertNotIn("vence_local", texto)

    def test_c12_recarga_pendiente_entre_procesos(self):
        """C12+C6: si la recarga falla en un `--una-vez`, el siguiente la vuelve a correr y sale 0 si anda."""
        marca = self.tmp / "marca"
        self.plat.poner(lista([DOM]))
        self.assertEqual(self.cli("--al-cambiar", "/usr/bin/false").returncode, 4)
        comando = " ".join(shlex.quote(x) for x in (sys.executable, "-c",
                                                     "import pathlib,sys; pathlib.Path(sys.argv[1]).touch()",
                                                     str(marca)))
        self.assertEqual(self.cli("--al-cambiar", comando).returncode, 0)
        self.assertTrue(marca.exists())


# --- C13 -------------------------------------------------------------------------------------------------------

class TestAvisos(Base):
    def test_c13_avisos_con_tope_de_memoria_y_de_lineas(self):
        """C13: una lista con muchas entradas inválidas distintas en cada vuelta no hace crecer la memoria sin tope
        ni inunda el registro, y no frena lo válido; un aviso estable sale una sola vez."""
        c = self.cliente()
        with mock.patch.object(cp, "MAX_AVISOS_RECORDADOS", 120):
            for vuelta in range(6):
                malos = [orden(f"ord-q-{vuelta}-{i}", "ip", f"10.9.{vuelta}.{i % 250}") for i in range(300)]
                self.plat.poner(lista(malos + [DOM], minuto=10 + vuelta))
                self.avisos.clear()
                c.pasada()
                self.assertLessEqual(len(self.avisos), cp.MAX_AVISOS_POR_PASADA + 1)
                self.assertTrue(any("que no detallo" in a for a in self.avisos), self.avisos[-1:])
                self.assertLessEqual(len(c.avisados), 120)
        self.assertEqual(self.lineas(self.unbound), ['local-zone: "s2.ejemplo.test." always_nxdomain'])
        self.avisos.clear()
        for m in (20, 21):
            self.plat.poner(lista([orden("ord-q-fija", "ip", "10.0.0.1"), DOM], minuto=m))
            c.pasada()
        self.assertEqual(len(self.avisos), 1, self.avisos)

    def test_c13_lo_que_viene_de_la_lista_se_muestra_escapado(self):
        """C13: ningún aviso ni línea de pantalla lleva saltos de línea o caracteres de control crudos."""
        self.plat.poner(lista([orden("ord-k-01", "dominio", "x\x1b[2Jy.test\n"), orden("ord-k\x07", "ip", "1.2.3.4"),
                               orden("ord-k-03", "co\nmando", "a.test")],
                              retiradas=[{"orden_id": "ord\n-r", "motivo": "levantada"}], acelerar="x\ny"))
        c = self.cliente()
        c.pasada()
        for texto in self.avisos + self.dichos:
            self.assertFalse(CONTROL.search(texto), repr(texto))

    def test_c13_ultima_barrera_tambien_para_lo_que_no_viene_de_la_lista(self):
        """C13: un texto que no pasó por el escapado de la lista (un error del sistema con una ruta rara) tampoco
        llega crudo a la pantalla."""
        rara = self.tmp / "sal\x1b[31m\nida"
        rara.mkdir()
        os.chmod(rara, 0o555)
        try:
            self.plat.poner(lista([IP]))
            c = self.cliente(salida_unbound=None, salida_ips=str(rara / "ips.txt"))
            c.pasada()
        finally:
            os.chmod(rara, 0o755)
        self.assertTrue(self.avisos, "se esperaba un aviso por la escritura fallida")
        for texto in self.avisos + self.dichos:
            self.assertFalse(CONTROL.search(texto), repr(texto))


# --- C14: sitios ajenos colgados de un nombre bloqueado (kit-2) ----------------------------------------------------

HOSTING = "cdn.hostingbarato.test"
INQUILINOS = ["panaderia-sol.cdn.hostingbarato.test", "tienda-lucia.cdn.hostingbarato.test"]


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


class TestNoCortar(Base):
    def _orden_hosting(self, **kw):
        o = orden("ord-0002-u1-isp-chico-01-c0ffee00", "dominio", HOSTING, **kw)
        o["no_cortar"] = INQUILINOS + ["otro.sitio.test", HOSTING, "mal\n.cdn.hostingbarato.test",
                                       "x.rpz-ip", 5, "TIENDA-LUCIA.cdn.hostingbarato.test"]
        return o

    def test_c14_los_inquilinos_conocidos_siguen_resolviendo(self):
        """C14 (kit-2): ningún sitio ajeno que la plataforma manda en `no_cortar` queda cortado por el archivo de
        Unbound; el stream y cualquier otro subdominio del nombre bloqueado, sí. Lo que no valida o no cuelga del
        nombre bloqueado no llega al archivo."""
        self.plat.poner(lista([self._orden_hosting(), DOM]))
        self.assertTrue(self.cliente().pasada())
        texto = self.unbound.read_text(encoding="utf-8")
        self.assertEqual(zona_que_rige(texto, HOSTING), "always_nxdomain")
        self.assertEqual(zona_que_rige(texto, "www." + HOSTING), "always_nxdomain")
        for n in INQUILINOS:
            self.assertEqual(zona_que_rige(texto, n), "transparent", n)
        datos = [l for l in texto.splitlines() if not l.startswith("#")]
        self.assertEqual(datos, [f'local-zone: "{HOSTING}." always_nxdomain', f'local-zone: "{DOM["objetivo"]}." always_nxdomain']
                         + [f'local-zone: "{n}." transparent' for n in INQUILINOS])
        self.assertIn("# Las líneas transparent son sitios ajenos", texto)

    def test_c14_sobrevive_al_reinicio_sin_huerfanos(self):
        """C14: tras reiniciar con la plataforma caída, las excepciones siguen (vienen del estado) y no se toman
        como bloqueos sin orden."""
        self.plat.poner(lista([self._orden_hosting()]))
        self.cliente().pasada()
        antes = self.unbound.read_text(encoding="utf-8")
        self.plat.cerrar()
        self.avisos.clear()
        c = self.cliente()
        self.assertEqual(c.huerfanos, [])
        c.pasada()
        self.assertEqual(self.unbound.read_text(encoding="utf-8"), antes)
        self.assertFalse(any("no figuran en lo que tengo guardado" in a for a in self.avisos), self.avisos)

    def test_c14_inquilino_bloqueado_por_otra_orden_sigue_cortado(self):
        """C14: si el inquilino tiene su propia orden, se corta: la excepción nunca le gana a una orden."""
        propia = orden("ord-0003-u2-isp-chico-01-deadbeef", "dominio", INQUILINOS[0])
        self.plat.poner(lista([self._orden_hosting(), propia]))
        self.cliente().pasada()
        texto = self.unbound.read_text(encoding="utf-8")
        self.assertEqual(zona_que_rige(texto, INQUILINOS[0]), "always_nxdomain")
        self.assertEqual(zona_que_rige(texto, INQUILINOS[1]), "transparent")

    def test_c14_no_cortar_y_segunda_barrera(self):
        """C14: `no_cortar` solo deja nombres válidos que cuelgan del objetivo de su orden; y al armar el archivo,
        una excepción que no cuelga de ningún nombre bloqueado (o que no valida) no se escribe o no se escribe nada."""
        self.assertEqual(cp.no_cortar(INQUILINOS[::-1] + ["otro.sitio.test", HOSTING, "x\n.cdn.hostingbarato.test"],
                                      HOSTING), INQUILINOS)
        self.assertEqual(cp.no_cortar("tienda.cdn.hostingbarato.test", HOSTING), [])
        aplicadas = {"a": {"tipo": "dominio", "objetivo": HOSTING, "no_cortar": ["otro.sitio.test"] + INQUILINOS}}
        datos = [l for l in cp.texto_unbound(PID, aplicadas).splitlines() if not l.startswith("#")]
        self.assertEqual(datos, [f'local-zone: "{HOSTING}." always_nxdomain']
                         + [f'local-zone: "{n}." transparent' for n in INQUILINOS])
        aplicadas["a"]["no_cortar"] = ['com." always_nxdomain\nlocal-zone: "x.cdn.hostingbarato.test']
        with self.assertRaises(ValueError):
            cp.texto_unbound(PID, aplicadas)

    def test_c14_sin_no_cortar_el_archivo_no_cambia(self):
        """C14: sin `no_cortar`, el archivo es el de siempre (tres renglones de cabecera)."""
        self.plat.poner(lista([DOM]))
        self.cliente().pasada()
        self.assertEqual(self.lineas(self.unbound), [f'local-zone: "{DOM["objetivo"]}." always_nxdomain'])
        self.assertNotIn("transparent", self.unbound.read_text(encoding="utf-8"))

    def test_c14_al_levantar_la_orden_se_van_tambien_las_excepciones(self):
        """C14: levantada la orden del hosting, no queda ninguna línea suya (ni el bloqueo ni las excepciones)."""
        o = self._orden_hosting()
        self.plat.poner(lista([o]))
        c = self.cliente()
        c.pasada()
        self.plat.poner(lista([], retiradas=[levantada(o)]))
        c.pasada()
        self.assertEqual(self.lineas(self.unbound), [])
        self.assertNotIn("transparent", self.unbound.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
