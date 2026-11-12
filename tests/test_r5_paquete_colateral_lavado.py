"""Ola D, zona paquete: `_colateral_esperado` (g-paquete-1) no puede lavar una mentira ni marcar ✗ un paquete legítimo.

Contratos:
- L1: un campo `recalculada` agregado a mano a una ubicación que el motor NO rehízo (citando un reclamo y un
  registrable reales) no vuelve aceptable un colateral distinto del sellado: `verificar` da ✗.
- L4: borrar `recalculada` de una ubicación rehecha deja un colateral distinto del sellado: ✗.
- L5: un paquete legítimo en el que el host que vuelve «observado» al pedido rehecho es de OTRO expediente verifica
  con 0 ✗ (el motor usa todos los hosts piratas de la plataforma, no solo los del expediente).
"""
import json, shutil, unittest
from pathlib import Path
from marca import verificar as V
from marca.verificar import verificar
from tests.test_falsificacion import malas, _leer, _escribir, _rehacer
from tests.test_r4_motor_colateral2 import Base, IPA, IPB

IPC = "198.51.100.73"


def de_colateral(inf):
    return [x for x in malas(inf) if "campo colateral" in x or "colateral." in x]


class _Cierre(Base):
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


class OtroExpediente(_Cierre):
    """tv3.club.test transmite (otra sesión, otro expediente) DESPUÉS de sellado el pedido de tv2 y comparte con él el
    DNS pasivo de IPB. Al refutar club.test, el motor rehace tv2 con tv3 como observado."""
    DNS = {IPA: ["tv.club.test", "kiosco.club.test"],
           IPB: ["tv2.club.test", "ferreteria.club.test", "tv3.club.test"],
           IPC: ["tv3.club.test"]}
    DETS = [("D-0201", 1.0, "tv.club.test", IPA, "LP26-PRU-OFI-S0201", "https://club.test/tv", 64601),
            ("D-0202", 2.7, "tv2.club.test", IPB, "LP26-PRU-OFI-S0202", "https://club.test/tv2", 64601),
            ("D-0203", 2.9, "tv3.club.test", IPC, "LP26-PRU-OFI-S0203", "https://otrapagina.test/tv3", 64601)]

    def test_legitimo_con_observado_de_otro_expediente_verifica(self):
        e2, u2 = self.ubic("tv2.club.test")
        e3, _ = self.ubic("tv3.club.test")
        self.assertNotEqual(e2["id"], e3["id"])  # premisa: expedientes distintos
        self.assertNotIn("tv3.club.test", u2["sellado"]["colateral"].get("observados") or [])  # premisa
        self.refutar("kiosco.club.test")
        e2, u2 = self.ubic("tv2.club.test")
        self.assertIn("recalculada", u2)
        self.assertIn("tv3.club.test", u2["colateral"].get("observados") or [])  # premisa: el motor lo ve pirata
        entrega, reg, cfg = self.cerrar()
        self.assertEqual(de_colateral(verificar(entrega)), [])
        self.assertEqual(de_colateral(verificar(entrega, reg, cfg)), [])


class Lavado(_Cierre):
    DNS = {IPA: ["tv.club.test", "kiosco.club.test"], IPB: ["tv2.club.test", "ferreteria.club.test"]}
    DETS = [("D-0201", 1.0, "tv.club.test", IPA, "LP26-PRU-OFI-S0201", "https://club.test/tv", 64601),
            ("D-0202", 2.7, "tv2.club.test", IPB, "LP26-PRU-OFI-S0202", "https://club.test/tv2", 64601)]

    def _copia(self, entrega, nombre):
        c = Path(self.dir.name) / nombre
        shutil.copytree(entrega, c)
        return c

    def test_recalculada_inventada_en_ubicacion_firmada_da_cruz(self):
        self.refutar("kiosco.club.test")
        entrega, reg, cfg = self.cerrar()
        c = self._copia(entrega, "L1")
        orden = [json.loads(x) for x in (c / "auditoria.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
        hecho = False
        for p in (c / "expedientes").glob("*.json"):
            e = _leer(p)
            ubics = e["ubicaciones"]
            for u in ubics:
                if u.get("recalculada"):
                    continue
                u["recalculada"] = {"reclamo": "R-077", "registrable": "club.test"}
                nuevo = V._colateral_esperado(u, orden, ubics)
                if nuevo != u["colateral"]:
                    u["colateral"] = nuevo
                    hecho = True
                else:
                    del u["recalculada"]
            _escribir(p, e)
        self.assertTrue(hecho, "premisa: el recálculo cambia el colateral de alguna ubicación no rehecha")
        _rehacer(c)
        self.assertNotEqual(malas(verificar(c)), [], "sin registro")
        self.assertNotEqual(malas(verificar(c, reg, cfg)), [], "con registro")

    def test_borrar_recalculada_da_cruz(self):
        self.refutar("kiosco.club.test")
        entrega, reg, cfg = self.cerrar()
        c = self._copia(entrega, "L4")
        hecho = False
        for p in (c / "expedientes").glob("*.json"):
            e = _leer(p)
            for u in e["ubicaciones"]:
                if u.get("recalculada"):
                    del u["recalculada"]; hecho = True
            _escribir(p, e)
        self.assertTrue(hecho)
        _rehacer(c)
        self.assertNotEqual(de_colateral(verificar(c)), [])


if __name__ == "__main__":
    unittest.main()
