"""Contrato (v-f-integridad-2): con el registro oficial, los minutos de aplicación de cada orden del paquete son los
del simulador. La cola de la auditoría (después del último sello) no lleva clave: quien reescribe un aplicada_min ahí
y recalcula cadena, derivados, .md y manifiesto no puede pasar `verificar --registro-simulador`."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from marca import evidencia, exportar as ex
from marca.auditoria import leer_entradas
from marca.verificar import verificar
from tests.test_motor_verificar import correr_partido
from tests.test_paquete import recalcular_cadena


class TestColaContraRegistro(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        base = Path(cls.dir.name)
        _, cls.sim, cls.entrega, cls.cfg = correr_partido(base)
        cls.reg = base / "registro.jsonl"
        cls.reg.write_text("\n".join(json.dumps(r) for r in cls.sim.registro) + "\n", encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    def test_cola_reescrita_no_verifica_con_registro(self):
        self.assertEqual(verificar(self.entrega, self.reg, self.cfg).fallas, 0)
        e = Path(tempfile.mkdtemp(dir=self.dir.name)) / "e"
        shutil.copytree(self.entrega, e)
        ruta = e / "auditoria.jsonl"
        L = leer_entradas(ruta)
        ultimo_envio = max(x["n"] for x in L if x["tipo"] == "orden_enviada")
        blanco = next(x for x in L if x["n"] > ultimo_envio and x["tipo"] == "orden_aplicada")
        oid = blanco["datos"]["orden_id"]
        envio = next(x for x in L if x["tipo"] == "orden_enviada" and x["datos"].get("orden_id") == oid)
        nuevo = round(float(envio["min"]) + 0.05, 3)
        self.assertNotEqual(nuevo, blanco["datos"]["aplicada_min"])
        blanco["datos"]["aplicada_min"] = blanco["min"] = nuevo
        recalcular_cadena(ruta, L)
        L = leer_entradas(ruta)
        # Todo lo que recalcula verificar, recalculado igual que el exportador.
        res = json.loads((e / "resumen.json").read_text(encoding="utf-8"))
        exps = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((e / "expedientes").glob("*.json"))]
        for x in exps:
            for u in x["ubicaciones"]:
                for o in u.get("ordenes", []):
                    if o.get("orden_id") == oid:
                        o["aplicada_min"] = nuevo
        todas = [o for x in exps for u in x["ubicaciones"] for o in u.get("ordenes", [])]
        todas += list(res.get("ordenes_sin_ubicacion") or [])
        provs = res.get("proveedores") or []
        fin = float(res["partido"]["fin_min"])
        ahora = float(res.get("minuto") or fin)
        for x in exps:
            for u in x["ubicaciones"]:
                d, h = evidencia.ventana(x["ubicaciones"], u, ahora, fin)
                u["ventana"] = [ex.r3(d), ex.r3(h)]
                u["cobertura"] = evidencia.cobertura(d, h, u.get("ip"), u.get("host"), todas, provs)
                u["tiempos"] = ex.tiempos_ubicacion(u, provs)
            (e / "expedientes" / f"{x['id']}.json").write_text(json.dumps(x, ensure_ascii=False), encoding="utf-8")
        res["tiempos"] = ex.armar_tiempos(exps, ex.quien_firmo(L))
        res["cabeza_auditoria"] = {"n": L[-1]["n"], "hash": L[-1]["hash"]}
        (e / "resumen.json").write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
        marcos = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((e / "orden-marco").glob("*.json"))]
        for rel, txt in ex.legibles(res, exps, marcos).items():
            (e / rel).write_text(txt, encoding="utf-8")
        ex.escribir_manifiesto(e)
        # Sin fuente externa, la falsificación de la cola pasa (límite documentado: la ancla la huella).
        self.assertEqual(verificar(e, None, self.cfg).fallas, 0)
        inf = verificar(e, self.reg, self.cfg)
        malas = [x for x in inf.lineas if x.startswith("✗")]
        self.assertTrue(any(oid in x and "registro oficial" in x for x in malas), inf.lineas)


if __name__ == "__main__":
    unittest.main()
