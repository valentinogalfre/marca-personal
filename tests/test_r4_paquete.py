"""Ola C (R4) — contratos del paquete y de verificar.

- f-integridad-1: sin una fuente externa (registro oficial), `verificar` nunca presenta un paquete como probado:
  dice que es coherente consigo mismo y avisa que, sin el registro, quien maneja la plataforma pudo recalcularlo
  todo. Con un registro coherente, sí dice «todo verifica». El código de salida no cambia (0 si no hay ✗).
- f-integridad-3 (C20): con la plataforma apagada y sin entradas nuevas en la auditoría desde el cierre, `exportar`
  entrega el paquete del cierre: la huella es la publicada, aunque estado.json haya seguido avanzando el minuto.
  Con entradas nuevas, se vuelve a armar.
- paquete-3 / c1-concurrencia-6: con la plataforma viva, `exportar` no arma el paquete hasta que estado.json refleja
  la entrada testigos_guardados nueva (aud_n): estado y testigos son de la misma foto.
"""
import contextlib
import io
import json
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from marca import __main__ as principal
from marca.exportar import huella_paquete
from marca.verificar import AVISO_SIN_REGISTRO, RESULTADO_COHERENTE, RESULTADO_OK, main_verificar
from tests.test_motor_verificar import correr_partido
from tests.test_paquete import cerrar

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "herramientas"))
import falsificar  # noqa: E402


def _salida_de(fn, *args, **kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        codigo = fn(*args, **kw)
    return codigo, buf.getvalue()


class _Partido(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        cls.base = Path(cls.dir.name)
        cls.motor, cls.sim, cls.entrega, cls.cfg = correr_partido(cls.base)
        cerrar(cls.motor)
        cls.registro = cls.base / "registro.jsonl"
        cls.registro.write_text("".join(json.dumps(r) + "\n" for r in cls.sim.registro), encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()


class TestSinRegistroNoSePresentaComoProbado(_Partido):
    def test_falsificado_sin_registro_dice_coherente_y_avisa(self):
        falsa = self.base / "falsa"
        falsificar.falsificar(self.entrega, falsa, str(self.cfg))
        codigo, texto = _salida_de(main_verificar, falsa)
        self.assertEqual(codigo, 0)
        self.assertIn(AVISO_SIN_REGISTRO, texto)
        self.assertIn(RESULTADO_COHERENTE, texto)
        self.assertNotIn(RESULTADO_OK, texto)
        self.assertTrue(texto.rstrip().endswith(RESULTADO_COHERENTE))

    def test_con_registro_coherente_dice_todo_verifica(self):
        codigo, texto = _salida_de(main_verificar, self.entrega, self.registro, self.cfg)
        self.assertEqual(codigo, 0, texto)
        self.assertIn(RESULTADO_OK, texto)
        self.assertNotIn(AVISO_SIN_REGISTRO, texto)

    def test_el_leeme_dice_que_los_testigos_no_reemplazan_al_registro(self):
        leeme = (self.entrega / "LEEME.md").read_text(encoding="utf-8")
        self.assertIn("lo guarda la plataforma", leeme)
        self.assertIn("No reemplaza al registro oficial del simulador", leeme)


class TestExportarApagadaEntregaElPaqueteDelCierre(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        base = Path(self.dir.name)
        motor, _, self.entrega, _ = correr_partido(base)
        cerrar(motor)
        self.salida = motor.salida
        self.assertTrue(json.loads((self.entrega / "resumen.json").read_text(encoding="utf-8"))["cerrado"])
        # La plataforma siguió corriendo un rato después del cierre: estado.json tiene un minuto posterior.
        est = json.loads((self.salida / "estado.json").read_text(encoding="utf-8"))
        est["minuto"] = float(est["minuto"]) + 1.06
        (self.salida / "estado.json").write_text(json.dumps(est), encoding="utf-8")
        self.base = base

    def tearDown(self):
        self.dir.cleanup()

    def caido(self):
        c = mock.MagicMock()
        from marca.simulador import ErrorRed
        c.ordenes.side_effect = ErrorRed("sin conexión")
        c.estado.side_effect = ErrorRed("sin conexión")
        return c

    def test_misma_huella_que_la_publicada(self):
        publicada = huella_paquete(self.entrega)
        codigo, _ = _salida_de(principal.exportar_paquete, self.salida, self.base / "pendrive", cliente=self.caido(),
                               imprimir=print)
        self.assertEqual(codigo, 0)
        self.assertEqual(huella_paquete(self.base / "pendrive"), publicada)
        _, texto = _salida_de(main_verificar, self.base / "pendrive", None, None, publicada)
        self.assertIn("igual a la publicada", texto)

    def test_entradas_posteriores_al_cierre_no_cambian_la_huella(self):
        """f-operacion-1: después del cierre (sesiones, consultas) la huella sigue siendo la publicada."""
        from marca.auditoria import Auditoria
        publicada = huella_paquete(self.entrega)
        aud = Auditoria(self.salida / "auditoria.jsonl")
        try:
            aud.agregar("nota_operador", "sistema", 111.0, None, {"texto": "prueba"})
        finally:
            aud.cerrar()
        antes = (self.salida / "auditoria.jsonl").read_bytes()
        codigo, texto = _salida_de(principal.exportar_paquete, self.salida, self.base / "pendrive",
                                   cliente=self.caido(), imprimir=print)
        self.assertEqual(codigo, 0)
        self.assertEqual(huella_paquete(self.base / "pendrive"), publicada)
        self.assertIn("1 entrada(s) posteriores al cierre", texto)
        self.assertEqual((self.salida / "auditoria.jsonl").read_bytes(), antes)


class TestExportarConLaPlataformaVivaDespuesDelCierre(unittest.TestCase):
    """f-operacion-1 + C20: con el partido cerrado y la plataforma viva, exportar a dest1, a dest2 y otra vez a dest1
    da tres veces la huella de salida/entrega (la publicada), y la auditoría no gana testigos_guardados."""

    def test_tres_exportaciones_misma_huella_y_sin_testigos_nuevos(self):
        from marca import api
        from marca.__main__ import escribir_info_plataforma
        from tests.test_integridad_r3b import arrancar, parar
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            motor, _, entrega, _ = correr_partido(base)
            salida = motor.salida
            servidor = api.servir(motor, "127.0.0.1", 0)
            arrancar(servidor)
            try:
                escribir_info_plataforma(salida, "127.0.0.1", servidor.server_address[1], motor.instancia)
                self.assertTrue(principal.plataforma_viva(salida))
                with motor.candado:
                    publicada = (motor.e["hitos"].get("paquete") or {}).get("huella")
                self.assertEqual(huella_paquete(entrega), publicada)
                testigos = principal._contar_testigos(salida / "auditoria.jsonl")
                huellas = []
                for dest in ("dest1", "dest2", "dest1"):
                    textos = []
                    rc = {}
                    t = threading.Thread(target=lambda: rc.setdefault("rc", principal.exportar_paquete(
                        salida, base / dest, espera_s=3, imprimir=textos.append)))
                    t.start()
                    while t.is_alive():  # la plataforma sigue su ciclo mientras se exporta
                        motor.paso()
                        time.sleep(0.05)
                    self.assertEqual(rc["rc"], 0, textos)
                    huellas.append(huella_paquete(base / dest))
                for _ in range(3):
                    motor.paso()
                self.assertEqual(huellas, [publicada] * 3)
                self.assertEqual(huella_paquete(entrega), publicada)
                self.assertEqual(principal._contar_testigos(salida / "auditoria.jsonl"), testigos)
                self.assertFalse((salida / "pedir-testigos").exists())
            finally:
                parar(servidor)
                cerrar(motor)


class TestExportarEsperaQueElEstadoRefleteLaFoto(unittest.TestCase):
    """Plataforma viva simulada: anota testigos_guardados y recién 0,5 s después guarda estado.json con aud_n."""

    def test_no_arma_con_un_estado_anterior_a_la_foto(self):
        with tempfile.TemporaryDirectory() as d:
            salida = Path(d) / "salida"
            salida.mkdir()
            aud = salida / "auditoria.jsonl"
            aud.write_text(json.dumps({"n": 1, "tipo": "partido_iniciado"}) + "\n", encoding="utf-8")
            (salida / "estado.json").write_text(json.dumps({"aud_n": 1, "minuto": 50.0}), encoding="utf-8")

            def plataforma():
                pedido = salida / "pedir-testigos"
                while not pedido.exists():
                    time.sleep(0.01)
                with open(aud, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"n": 2, "tipo": "testigos_guardados"}) + "\n")
                time.sleep(0.5)
                (salida / "estado.json").write_text(json.dumps({"aud_n": 2, "minuto": 51.0}), encoding="utf-8")
            hilo = threading.Thread(target=plataforma, daemon=True)
            hilo.start()
            visto = {}

            def exportar_falso(sal, dest):
                visto["aud_n"] = json.loads((Path(sal) / "estado.json").read_text(encoding="utf-8"))["aud_n"]
                Path(dest).mkdir(parents=True, exist_ok=True)
                return Path(dest)
            with mock.patch.object(principal, "plataforma_viva", return_value=True), \
                    mock.patch("marca.exportar.exportar", side_effect=exportar_falso), \
                    mock.patch("marca.exportar.huella_paquete", return_value=None):
                codigo, _ = _salida_de(principal.exportar_paquete, salida, Path(d) / "destino", espera_s=5.0,
                                       imprimir=print)
            hilo.join(2)
            self.assertEqual(codigo, 0)
            self.assertEqual(visto.get("aud_n"), 2, "se armó el paquete con un estado anterior a la foto de testigos")


class TestTiemposContraElRegistroOficial(_Partido):
    """f-integridad-2: con el registro oficial, el minuto de aplicación y el estado final de cada orden del paquete
    son los del simulador, también los de la cola posterior al último sello. Lo que el paquete todavía no sabe
    (aplicada después de exportar) no es falla."""

    def ordenes(self):
        import glob
        out = {}
        for f in sorted((self.entrega / "expedientes").glob("*.json")):
            x = json.loads(f.read_text(encoding="utf-8"))
            for u in x["ubicaciones"]:
                for o in u.get("ordenes") or []:
                    out[o["orden_id"]] = o
        return out

    def test_legitimo_da_tilde(self):
        from marca.verificar import Informe, cotejar_tiempos_con_registro
        inf = Informe()
        cotejar_tiempos_con_registro(inf, list(self.sim.registro), self.ordenes())
        self.assertEqual(inf.fallas, 0, inf.lineas)

    def test_aplicada_adelantada_da_cruz_con_su_orden(self):
        from marca.verificar import Informe, cotejar_tiempos_con_registro
        ords = self.ordenes()
        oid = next(k for k, o in ords.items() if o.get("aplicada_min") is not None)
        ords[oid] = dict(ords[oid], aplicada_min=float(ords[oid]["aplicada_min"]) - 0.5)
        inf = Informe()
        cotejar_tiempos_con_registro(inf, list(self.sim.registro), ords)
        malas = [x for x in inf.lineas if x.startswith("✗")]
        self.assertTrue(any(oid in x and "tiempos o estado distintos del registro oficial" in x for x in malas), malas)

    def test_aplicada_sin_evento_en_el_registro_da_cruz(self):
        from marca.verificar import Informe, cotejar_tiempos_con_registro
        ords = self.ordenes()
        oid = next(k for k, o in ords.items() if o.get("aplicada_min") is not None)
        eventos = [e for e in self.sim.registro if not (e.get("orden_id") == oid and e["evento"] == "orden_aplicada")]
        inf = Informe()
        cotejar_tiempos_con_registro(inf, eventos, ords)
        self.assertTrue(any(oid in x for x in inf.lineas if x.startswith("✗")), inf.lineas)

    def test_lo_que_el_paquete_todavia_no_sabe_no_es_falla(self):
        from marca.verificar import Informe, cotejar_tiempos_con_registro
        ords = self.ordenes()
        oid = next(k for k, o in ords.items() if o.get("aplicada_min") is not None)
        ords[oid] = dict(ords[oid], aplicada_min=None, estado="recibida", finalizada_min=None)
        inf = Informe()
        cotejar_tiempos_con_registro(inf, list(self.sim.registro), ords)
        self.assertEqual(inf.fallas, 0, inf.lineas)

    def test_verificar_lo_usa_con_registro(self):
        from marca import verificar as v
        with mock.patch.object(v, "cotejar_tiempos_con_registro", wraps=v.cotejar_tiempos_con_registro) as c:
            v.verificar(self.entrega, self.registro)
        self.assertEqual(c.call_count, 1)


class TestTextosDelActa(_Partido):
    """f-humano-1, NV4 y f-desconocido-1: el acta no afirma lo que no se puede medir ni deja «por_enviar» colgado."""

    def resumen(self, **extra):
        r = {"partido": {}, "minuto": 110.0, "ordenes": [], "descartes": [], "reclamos": [], "traspasos": []}
        r.update(extra)
        return r

    def test_no_dice_expediente_abierto(self):
        textos = {p.name: p.read_text(encoding="utf-8") for p in self.entrega.rglob("*.md")}
        self.assertIn("Pedido en la bandeja antes de firmar", textos["acta-del-partido.md"])
        for nombre, t in textos.items():
            self.assertNotIn("expediente abierto", t.lower(), nombre)

    def test_traspaso_sin_recibir_pero_ratificado_al_firmar(self):
        from marca.exportar import acta_md
        exps = [{"id": "EXP-2026-000001", "titulo": "pelotaya", "ubicaciones": []}]
        t = {"min": 50.0, "de": [{"nombre": "Laura"}], "a": [{"nombre": "Martín"}], "ratificado": None,
             "ratificadas_al_firmar": [{"id": "EXP-2026-000001", "min": 51.2, "juez_id": "juez-b",
                                        "nombre": "Martín"}]}
        acta = acta_md(self.resumen(traspasos=[t]), exps, [])
        self.assertNotIn("sin ratificar", acta)
        self.assertIn("el juez entrante no confirmó la recepción del turno; el seguimiento de pelotaya lo ratificó "
                      "Martín al firmar y seguir en el minuto 51,2.", acta)
        t2 = {"min": 50.0, "de": [{"nombre": "Laura"}], "a": [{"nombre": "Martín"}], "ratificado": None}
        self.assertIn("el juez entrante no confirmó la recepción del turno.", acta_md(self.resumen(traspasos=[t2]),
                                                                                       exps, []))

    def test_no_enviada_al_final_no_es_por_enviar(self):
        from marca.exportar import acta_md, estado_legible
        o = {"orden_id": "ord-0009-u1-valle-01-x", "estado": "por_enviar", "no_enviada": True}
        self.assertEqual(estado_legible(o), "no enviada (el partido terminaba)")
        self.assertEqual(estado_legible({"estado": "por_enviar"}), "por_enviar")
        self.assertEqual(estado_legible({"estado": "aplicada", "no_enviada": True}), "aplicada")
        acta = acta_md(self.resumen(ordenes_sin_ubicacion=[o]), [], [])
        self.assertIn("no enviada (el partido terminaba): 1", acta)
        self.assertNotIn("por_enviar", acta)


class TestChequearAvisaElConfigDeDemo(unittest.TestCase):
    """OPERACION 8(d): aun escuchando solo en esta máquina (un túnel la publica igual), `chequear` avisa si el archivo
    de usuarios es el de demostración. No es ✗ (los ensayos lo usan); con contraseñas propias no avisa."""

    def correr(self, config):
        from argparse import Namespace
        args = Namespace(host="127.0.0.1", config=str(config), simulador="http://127.0.0.1:9", salida=None)
        with mock.patch.object(principal, "revision_previa", return_value=[]):
            return _salida_de(principal.cmd_chequear, args)

    def test_demo_avisa_y_propio_no(self):
        codigo, texto = self.correr(principal.CONFIG)
        self.assertEqual(codigo, 0)
        self.assertIn(principal.AVISO_CONFIG_DEMO, texto)
        with tempfile.TemporaryDirectory() as d:
            final = Path(d) / "jueces_final.json"
            self.assertEqual(principal.armar_claves(final, imprimir=lambda t: None), 0)
            codigo, texto = self.correr(final)
        self.assertEqual(codigo, 0)
        self.assertNotIn(principal.AVISO_CONFIG_DEMO, texto)


class TestServirSinTraceback(unittest.TestCase):
    """Revisor de operación (P3): una carpeta de salida sin permiso o un archivo de usuarios mal escrito terminan con
    un ✗ claro y código 1, sin traceback."""

    def args(self, salida, config, puerto=0):
        from argparse import Namespace
        return Namespace(simulador="http://127.0.0.1:9", puerto=puerto, host="127.0.0.1", salida=str(salida),
                         nueva=False, descartar_anteriores=False, config=str(config), sin_dinamica=False, tick=0.25)

    def test_carpeta_sin_permiso(self):
        import os
        with tempfile.TemporaryDirectory() as d:
            ro = Path(d) / "ro"
            ro.mkdir()
            os.chmod(ro, 0o500)
            try:
                if os.access(ro, os.W_OK):
                    self.skipTest("el usuario puede escribir igual (root)")
                codigo, texto = _salida_de(principal.cmd_servir, self.args(ro / "salida", principal.CONFIG))
            finally:
                os.chmod(ro, 0o700)
        self.assertEqual(codigo, 1)
        self.assertIn("No se puede escribir junto a la carpeta de salida", texto)

    def test_usuarios_mal_escritos(self):
        with tempfile.TemporaryDirectory() as d:
            malo = Path(d) / "malo.json"
            malo.write_text('{"usuarios": [', encoding="utf-8")
            with mock.patch.object(principal, "revision_previa", return_value=[]), \
                    mock.patch.object(principal, "revisar_sin_estado", return_value=0), \
                    mock.patch.object(principal, "plataforma_viva", return_value=False):
                codigo, texto = _salida_de(principal.cmd_servir, self.args(Path(d) / "salida", malo))
        self.assertEqual(codigo, 1)
        self.assertIn("No se puede leer el archivo de usuarios", texto)


if __name__ == "__main__":
    unittest.main()
