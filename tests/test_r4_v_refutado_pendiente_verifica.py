"""Contrato (cruce f-colateral-2 / c1-integridad-2): un partido legítimo en el que el juez refuta una inferencia mientras
otro pedido del mismo registrable espera firma (y su propuesta se rehace) se exporta y `verificar` no da ✗ por el
colateral, firmado o no, con y sin registro oficial. La guarda de c1-integridad-2 sigue: si alguien edita el colateral
de ese pedido rehecho (y regenera actas y manifiesto sin tocar la auditoría), `verificar` da ✗."""
import json, shutil, unittest
from pathlib import Path
from marca.verificar import verificar
from tests.test_falsificacion import malas, _leer, _escribir, _rehacer
from tests.test_r4_motor_colateral2 import OtraIP


def de_colateral(inf):
    return [x for x in malas(inf) if "campo colateral" in x or "colateral." in x]


class RefutadoConPendiente(OtraIP):
    test_firmar_el_pendiente_no_bloquea_al_hermano_ya_refutado = None
    test_la_vista_dice_que_la_propuesta_se_rehizo = None

    def tearDown(self):
        self.motor.despacho._pool.shutdown(wait=False)
        if self.motor.auditoria:
            self.motor.auditoria.cerrar()

    def cerrar(self):
        for m in (5.0, 10.0, 20.0, 25.1, 25.2):
            self.paso(m)
        base = Path(self.dir.name)
        reg = base / "registro.jsonl"
        reg.write_text("".join(json.dumps(r) + "\n" for r in self.sim.registro), encoding="utf-8")
        return base / "salida" / "entrega", reg, base / "jueces.json"

    def chequear_sin_cruz(self, entrega, reg, cfg):
        self.assertEqual(malas(verificar(entrega)), [])
        self.assertEqual(de_colateral(verificar(entrega, reg, cfg)), [])

    def test_firmado_despues_de_refutar_verifica(self):
        self.refutar("kiosco.club.test")
        exp, u2 = self.ubic("tv2.club.test")
        self.assertIn("recalculada", u2)  # premisa: la propuesta se rehizo
        self.motor.aprobar("juez-a", exp["id"], u2["n"], "ubicacion", None, None)
        self.chequear_sin_cruz(*self.cerrar())

    def test_sin_firmar_verifica(self):
        self.refutar("kiosco.club.test")
        self.chequear_sin_cruz(*self.cerrar())

    def test_colateral_rehecho_editado_da_cruz(self):
        self.refutar("kiosco.club.test")
        exp, u2 = self.ubic("tv2.club.test")
        self.motor.aprobar("juez-a", exp["id"], u2["n"], "ubicacion", None, None)
        entrega, reg, cfg = self.cerrar()
        for cambio in ("riesgo", "observados", "ajenos"):
            c = Path(self.dir.name) / ("editado-" + cambio)
            shutil.copytree(entrega, c)
            p = c / "expedientes" / f"{exp['id']}.json"
            e = _leer(p)
            u = next(x for x in e["ubicaciones"] if x.get("recalculada"))
            if cambio == "riesgo":
                u["colateral"]["riesgo"] = "nulo"
            elif cambio == "observados":  # dice que la plataforma vio al inquilino
                u["colateral"]["observados"].append("ferreteria.club.test")
            else:
                u["colateral"]["ajenos"] = []
            _escribir(p, e)
            _rehacer(c)
            self.assertNotEqual(de_colateral(verificar(c)), [], cambio)


if __name__ == "__main__":
    unittest.main()
