"""Demo en línea (herramientas/demo_en_linea.py y Dockerfile).

Contratos:
- La demo abierta a internet nunca arranca con las contraseñas publicadas en el repo (config/jueces_demo.json),
  ni sin usuarios, ni sin jueces.
- El archivo de usuarios que arma desde MARCA_USUARIOS_JSON queda con permisos 600 y su contenido no se imprime.
- Entre un partido y el siguiente se borra la salida anterior, pero no el archivo de usuarios.
- La imagen lleva config/jueces_demo.json (sin él, el control de contraseñas publicadas no ve ninguna y deja pasar
  todo), no lleva contraseñas propias ni equipo/, y fija el repo oficial a un commit.
"""
import contextlib
import io
import json
import os
import re
import stat
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "herramientas"))
import demo_en_linea  # noqa: E402

DEMO = json.loads((RAIZ / "config" / "jueces_demo.json").read_text(encoding="utf-8"))


def propios() -> dict:
    datos = json.loads(json.dumps(DEMO))
    for i, u in enumerate(datos["usuarios"]):
        u["clave_demo"] = f"clave-propia-de-prueba-{i}-xq7"
    return datos


class PrepararUsuarios(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.destino = Path(self.tmp.name) / "usuarios.json"

    def tearDown(self):
        self.tmp.cleanup()

    def preparar(self, texto=None, config=None):
        salida = io.StringIO()
        with contextlib.redirect_stdout(salida):
            ruta = demo_en_linea.preparar_usuarios(texto, config, self.destino)
        return ruta, salida.getvalue()

    def test_no_arranca_con_las_contrasenas_publicadas(self):
        with self.assertRaises(SystemExit) as e:
            self.preparar(json.dumps(DEMO))
        self.assertIn("publicadas", str(e.exception))
        for u in DEMO["usuarios"]:
            self.assertNotIn(str(u["clave_demo"]), str(e.exception))

    def test_no_arranca_con_el_archivo_de_demo_por_config(self):
        with self.assertRaises(SystemExit):
            self.preparar(config=str(RAIZ / "config" / "jueces_demo.json"))

    def test_no_arranca_sin_usuarios(self):
        with self.assertRaises(SystemExit):
            self.preparar()

    def test_no_arranca_con_json_roto(self):
        with self.assertRaises(SystemExit):
            self.preparar("{no es json")

    def test_no_arranca_sin_jueces(self):
        datos = propios()
        datos["usuarios"] = [u for u in datos["usuarios"] if u["rol"] != "juez"]
        with self.assertRaises(SystemExit):
            self.preparar(json.dumps(datos))

    def test_escribe_con_permisos_600_y_no_muestra_contrasenas(self):
        datos = propios()
        ruta, salida = self.preparar(json.dumps(datos))
        self.assertEqual(ruta, self.destino)
        self.assertEqual(json.loads(ruta.read_text(encoding="utf-8")), datos)
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(ruta.stat().st_mode), 0o600)
        for u in datos["usuarios"]:
            self.assertNotIn(u["clave_demo"], salida)


class Limpiar(unittest.TestCase):
    def test_borra_el_partido_anterior_y_deja_los_usuarios(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "marca").mkdir()
            (d / "marca" / "estado.json").write_text("{}")
            (d / "marca.anterior-20261112-2200").mkdir()
            for nombre in ("marca.candado", "registro.jsonl", "simulador.log", "usuarios.json"):
                (d / nombre).write_text("x")
            demo_en_linea.limpiar(d)
            self.assertEqual(sorted(p.name for p in d.iterdir()), ["usuarios.json"])


class Imagen(unittest.TestCase):
    def setUp(self):
        self.texto = (RAIZ / "Dockerfile").read_text(encoding="utf-8")
        self.copias = [linea.split()[1] for linea in self.texto.splitlines()
                       if linea.strip().startswith(("COPY", "ADD")) and not linea.split()[1].startswith("http")]

    def test_lleva_el_archivo_de_demo_para_el_control_de_contrasenas(self):
        self.assertIn("config/jueces_demo.json", self.copias)

    def test_no_lleva_contrasenas_propias_ni_equipo(self):
        for origen in self.copias:
            self.assertNotIn(origen, (".", "./", "config", "config/"))
            self.assertFalse(origen.startswith("equipo"), origen)
            self.assertNotIn("jueces_final", origen)
            self.assertNotIn("jueces_en_linea", origen)

    def test_fija_el_repo_oficial_a_un_commit(self):
        self.assertRegex(self.texto, r"ARG DESAFIO_COMMIT=[0-9a-f]{40}\b")
        self.assertIn("qualydata-org/desafio-futbol/archive/${DESAFIO_COMMIT}", self.texto)

    def test_el_simulador_corre_aislado(self):
        fuente = (RAIZ / "herramientas" / "demo_en_linea.py").read_text(encoding="utf-8")
        self.assertTrue(re.search(r'\[PY, "-I", str\(self\.repo / "simulador" / "servidor\.py"\)', fuente))


if __name__ == "__main__":
    unittest.main()
