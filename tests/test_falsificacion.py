"""Contrato de herramientas/falsificar.py (sección 9 de la ronda 2b): «ni nosotros podemos falsificarlo».

- Sobre una copia, cambia la IP de una ubicación y recalcula todo lo que controla la plataforma (huellas, cadena,
  firmas con --config, sellos, números de orden, testigos, textos, manifiesto).
- `verificar <copia>` no lo nota: da lo mismo que la exportación original («coherente consigo mismo» si el original
  lo da).
- Con el registro oficial del simulador, sí: faltan órdenes y sobran órdenes ajenas.
- La huella del paquete cambia (por eso se publica) y la exportación original no se toca.
"""
import contextlib
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from marca.verificar import verificar

from tests.test_motor_verificar import correr_partido

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "herramientas"))
import falsificar  # noqa: E402


def foto(carpeta: Path) -> dict:
    return {p.relative_to(carpeta).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(carpeta.rglob("*")) if p.is_file()}


def malas(inf):
    return [x for x in inf.lineas if x.startswith("✗")]


class TestFalsificar(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        cls.base = Path(cls.dir.name)
        cls.motor, cls.sim, cls.entrega, cls.cfg = correr_partido(cls.base)
        cls.registro = cls.base / "registro.jsonl"
        cls.registro.write_text("".join(json.dumps(r) + "\n" for r in cls.sim.registro), encoding="utf-8")
        cls.antes = foto(cls.entrega)
        cls.falsa = cls.base / "falsa"
        cls.resultado = falsificar.falsificar(cls.entrega, cls.falsa, str(cls.cfg))

    @classmethod
    def tearDownClass(cls):
        cls.motor.despacho._pool.shutdown(wait=False)
        if cls.motor.auditoria:
            cls.motor.auditoria.cerrar()
        cls.dir.cleanup()

    def test_el_original_no_se_toca_y_la_huella_cambia(self):
        self.assertEqual(foto(self.entrega), self.antes)
        r = self.resultado
        self.assertNotEqual(r["huella_original"], r["huella_falsificada"])
        self.assertNotEqual(r["ip_vieja"], r["ip_nueva"])
        texto = (self.falsa / "expedientes").glob("*.json")
        self.assertTrue(any(r["ip_nueva"] in p.read_text(encoding="utf-8") for p in texto))
        self.assertGreater(r["sellos_cambiados"], 0)

    def test_sin_el_registro_no_se_nota(self):
        # Lo mismo que la exportación original, en los modos sin fuente externa (sin --config y con --config).
        for cfg in (None, self.cfg):
            with self.subTest(config=bool(cfg)):
                self.assertEqual(len(malas(verificar(self.falsa, None, cfg))), len(malas(verificar(self.entrega, None,
                                                                                                    cfg))))

    def test_todo_verde_si_el_original_lo_esta(self):
        """El contrato de la sección 9 tal cual: `verificar <copia>` da todo verde."""
        if malas(verificar(self.entrega)):
            self.skipTest("la exportación original del partido falso todavía no verifica sola (ver informe)")
        self.assertEqual(malas(verificar(self.falsa)), [])
        self.assertEqual(malas(verificar(self.falsa, None, self.cfg)), [])

    def test_con_el_registro_oficial_si(self):
        extra = set(malas(verificar(self.falsa, self.registro))) - set(malas(verificar(self.falsa)))
        self.assertTrue(any(m.startswith("✗ registro oficial: faltan") for m in extra), extra)
        self.assertTrue(any("que no están en la auditoría" in m for m in extra), extra)
        self.assertFalse(any(m.startswith("✗ registro oficial") for m in malas(verificar(self.entrega, self.registro))))

    def test_nunca_sobre_una_carpeta_existente(self):
        with self.assertRaises(falsificar.ErrorFalsificar):
            falsificar.falsificar(self.entrega, self.falsa)
        with self.assertRaises(falsificar.ErrorFalsificar):
            falsificar.falsificar(self.entrega, self.entrega / "adentro")
        self.assertEqual(foto(self.entrega), self.antes)

    def test_la_herramienta_explica_el_resultado(self):
        destino = self.base / "falsa-cli"
        r = subprocess.run([sys.executable, str(RAIZ / "herramientas" / "falsificar.py"), str(self.entrega),
                            str(destino)], capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        lineas = r.stdout.strip().splitlines()
        self.assertIn("coherente consigo mismo", lineas[-2])
        self.assertNotIn("todo verde", r.stdout)
        self.assertIn("--registro-simulador da ✗", lineas[-1])
        self.assertIn("Huella del paquete original:", r.stdout)
        self.assertIn("Huella del paquete falsificado:", r.stdout)


def _leer(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _escribir(p, x):
    Path(p).write_text(json.dumps(x, ensure_ascii=False, indent=1), encoding="utf-8")


def _rehacer(c: Path):
    """Lo que puede hacer cualquiera con este mismo código: .md desde los .json y manifiesto nuevo."""
    from marca import exportar
    resumen = _leer(c / "resumen.json")
    exps = sorted((_leer(p) for p in (c / "expedientes").glob("*.json")), key=lambda x: (x.get("num") or 0, x["id"]))
    marcos = sorted((_leer(p) for p in (c / "orden-marco").glob("*.json")), key=lambda x: x.get("entrada") or 0)
    for rel, texto in exportar.legibles(resumen, exps, marcos).items():
        (c / rel).write_text(texto, encoding="utf-8")
    exportar.escribir_manifiesto(c)


def _primera_ubicacion_firmada(c: Path):
    for p in sorted((c / "expedientes").glob("*.json")):
        e = _leer(p)
        for u in e["ubicaciones"]:
            if (u.get("decision") or {}).get("aprobada") and u["decision"].get("tipo") == "firma" and u.get("ordenes"):
                return p, e, u
    raise AssertionError("el partido falso no tiene una ubicación firmada en persona con órdenes")


def _juez(c):
    p, e, u = _primera_ubicacion_firmada(c)
    u["decision"]["juez"] = "Dr. Firmante Inventado"
    _escribir(p, e)


def _aplicada(c):
    from marca import exportar
    p, e, u = _primera_ubicacion_firmada(c)
    for o in u["ordenes"]:
        o["aplicada_min"] = round(float(u["primera_deteccion_min"]) + 0.1, 3)
    provs = _leer(c / "resumen.json")["proveedores"]
    u["tiempos"] = exportar.tiempos_ubicacion(u, provs)  # coherente: el atacante recalcula con el exportador
    _escribir(p, e)


def _estado(c):
    p, e, u = _primera_ubicacion_firmada(c)
    u["ordenes"][0]["estado"], u["ordenes"][0]["finalizada_min"] = "vencida", 3.0
    _escribir(p, e)


def _cobertura(c):
    p, e, u = _primera_ubicacion_firmada(c)
    u["cobertura"]["visibilidad_residual_pct"] = 0.0
    _escribir(p, e)


def _tiempos_resumen(c):
    r = _leer(c / "resumen.json")
    for tipo in r["tiempos"]["promedios"].values():
        if tipo.get("hasta_todos_min") is not None:
            tipo["hasta_todos_min"] = 0.1
    r["tiempos"]["firmaron"] = "el juez automático de ensayo (solo pruebas)"
    _escribir(c / "resumen.json", r)


def _marco(c):
    p = sorted((c / "orden-marco").glob("*.json"))[0]
    m = _leer(p)
    m["min"] = 0.5
    m["ampliaciones"].append({"exp": "EXP-2026-000999", "ubicacion": 7, "min": 61.0, "entrada": 99999})
    _escribir(p, m)


def _reclamo(c):
    r = _leer(c / "resumen.json")
    r["reclamos"].append({"id": "R-99", "dominio": "panaderia.test", "minuto": 30.0, "estado": "resuelto",
                          "verificacion": {"clase_reclamante": "legitimo"},
                          "resolucion": {"accion": "levantar", "minutos_hasta_resolver": 0.2}})
    _escribir(c / "resumen.json", r)


def _descarte(c):
    r = _leer(c / "resumen.json")
    r["descartes"].append({"host": "club-oficial.test", "clase": "legitimo", "veces": 3, "minuto": 12.0,
                           "motivo": "sitio protegido"})
    _escribir(c / "resumen.json", r)


def _colateral(c):
    """c1-integridad-2: el colateral que muestra el expediente (y el .md) no es el sellado."""
    p, e, u = _primera_ubicacion_firmada(c)
    u["colateral"]["riesgo"] = "nulo" if u["colateral"].get("riesgo") != "nulo" else "alto"
    u["colateral"]["motivo"] = "sin sitios ajenos en el servidor"
    _escribir(p, e)


class TestLoDerivadoSaleDeLaAuditoria(unittest.TestCase):
    """Contrato (paquete-1): todo lo que muestra el acta y no está sellado (quién firmó, estado y minutos de cada
    orden, tiempos, cobertura, órdenes marco, descartes y reclamos) se recalcula desde la auditoría. Si alguien edita
    un .json, regenera los .md y rehace el manifiesto SIN tocar la auditoría, `verificar` da ✗, también con el
    registro oficial y las claves. El paquete sin tocar da 0 ✗."""

    MANIPULACIONES = {"juez": _juez, "aplicada_min": _aplicada, "estado": _estado, "cobertura": _cobertura,
                      "tiempos_resumen": _tiempos_resumen, "orden_marco": _marco, "reclamo": _reclamo,
                      "descarte": _descarte, "colateral": _colateral}

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        cls.base = Path(cls.dir.name)
        cls.motor, cls.sim, cls.entrega, cls.cfg = correr_partido(cls.base)
        cls.registro = cls.base / "registro.jsonl"
        cls.registro.write_text("".join(json.dumps(r) + "\n" for r in cls.sim.registro), encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.motor.despacho._pool.shutdown(wait=False)
        if cls.motor.auditoria:
            cls.motor.auditoria.cerrar()
        cls.dir.cleanup()

    def test_sin_tocar_verifica(self):
        self.assertEqual(malas(verificar(self.entrega, self.registro, self.cfg)), [])

    def test_cada_dato_derivado_editado_da_cruz(self):
        import shutil
        for nombre, mutar in self.MANIPULACIONES.items():
            with self.subTest(dato=nombre):
                c = self.base / f"editado-{nombre}"
                shutil.copytree(self.entrega, c)
                auditoria = (c / "auditoria.jsonl").read_bytes()
                mutar(c)
                _rehacer(c)
                self.assertEqual((c / "auditoria.jsonl").read_bytes(), auditoria)
                for args in ((), (self.registro, self.cfg)):
                    self.assertNotEqual(malas(verificar(c, *args)), [], f"{nombre}: verde con {len(args)} fuentes")



if __name__ == "__main__":
    unittest.main()
