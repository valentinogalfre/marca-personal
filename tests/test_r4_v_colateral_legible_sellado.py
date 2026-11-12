"""Contrato (c1-integridad-2): el colateral que lee el juez y el jurado en el expediente (u.colateral: riesgo,
motivo, recomendación, sitios ajenos) es el sellado (sellado.colateral). Si alguien edita el .json, regenera los .md y
rehace el manifiesto SIN tocar la auditoría, `verificar` da ✗, solo y con registro oficial + claves. Sin tocar: 0 ✗."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from marca.verificar import verificar

from tests.test_falsificacion import _escribir, _leer, _rehacer, malas
from tests.test_motor_verificar import correr_partido


def _ubicaciones_con_colateral_sellado(c: Path):
    for p in sorted((c / "expedientes").glob("*.json")):
        e = _leer(p)
        for u in e["ubicaciones"]:
            if isinstance((u.get("sellado") or {}).get("colateral"), dict):
                yield p, e, u


class TestColateralLegibleEsElSellado(unittest.TestCase):
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

    def test_en_la_exportacion_sana_el_colateral_legible_es_el_sellado(self):
        vistas = list(_ubicaciones_con_colateral_sellado(self.entrega))
        self.assertTrue(vistas, "el partido falso no tiene ubicaciones con colateral sellado")
        for _, e, u in vistas:
            self.assertEqual(u.get("colateral"), u["sellado"]["colateral"], f"{e['id']} U{u.get('n')}")
        self.assertEqual(malas(verificar(self.entrega, self.registro, self.cfg)), [])

    def test_colateral_editado_da_cruz(self):
        c = self.base / "editado-colateral"
        shutil.copytree(self.entrega, c)
        auditoria = (c / "auditoria.jsonl").read_bytes()
        p, e, u = next(_ubicaciones_con_colateral_sellado(c))
        n = u["n"]
        u = next(x for x in e["ubicaciones"] if x["n"] == n)
        u["colateral"]["riesgo"] = "alto" if u["colateral"].get("riesgo") != "alto" else "nulo"
        _escribir(p, e)
        _rehacer(c)
        self.assertEqual((c / "auditoria.jsonl").read_bytes(), auditoria)
        for args in ((), (self.registro, self.cfg)):
            self.assertNotEqual(malas(verificar(c, *args)), [], f"colateral: verde con {len(args)} fuentes")


if __name__ == "__main__":
    unittest.main()
