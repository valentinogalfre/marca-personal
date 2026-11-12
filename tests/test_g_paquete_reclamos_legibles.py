"""g-paquete-6/7. Contrato: el acta y los expedientes cuentan los reclamos en castellano llano, que es lo que lee el
jurado. El expediente de una ubicación con reemplazo por reclamo nombra el reclamo, quién lo resolvió y en qué minuto;
las órdenes de reemplazo dicen en la columna Firma que nacen de ese reclamo; el acta no muestra valores internos
(levantar_y_reemplazar, legitimo, cerrar, resuelto). Y el paquete sigue verificando con el registro oficial: `verificar`
regenera estos textos con el mismo código."""
import json
import re
import unittest
from pathlib import Path

from marca import canon
from marca.verificar import verificar
from tests.test_falsificacion import malas
from tests.test_r4_motor_colateral2 import OtraIP

INTERNOS = ("levantar_y_reemplazar", "legitimo", "operacion_pirata", "sin_bloqueo", "cerrar", "→")


class ReclamosLegibles(OtraIP):
    test_firmar_el_pendiente_no_bloquea_al_hermano_ya_refutado = None
    test_la_vista_dice_que_la_propuesta_se_rehizo = None

    def tearDown(self):
        self.motor.despacho._pool.shutdown(wait=False)
        if self.motor.auditoria:
            self.motor.auditoria.cerrar()

    def test_reemplazo_por_reclamo_en_el_expediente_y_el_acta(self):
        # Dos proveedores reclaman por el mismo sitio; la jueza resuelve el primero y el segundo se cierra solo.
        self.sim.lista_reclamos += [
            {"id": "R-077", "minuto": 3.1, "dominio": "kiosco.club.test", "proveedor": "aurora", "mensaje": "comercio"},
            {"id": "R-078", "minuto": 3.2, "dominio": "kiosco.club.test", "proveedor": "andina", "mensaje": "comercio"}]
        self.motor._t_reclamos = float("-inf")
        self.motor._paso_reclamos()
        self.motor.resolver_reclamo("juez-a", "R-077", "levantar_y_reemplazar", None)
        res = self.motor.e["reclamos"]["R-077"]["resolucion"]
        self.assertTrue(res["ordenes_reemplazo"], "premisa: hubo reemplazo")
        self.assertEqual(self.motor.e["reclamos"]["R-078"]["resolucion"]["por_reclamo"], "R-077")
        for m in (3.4, 5.0, 10.0, 20.0, 25.1, 25.2):
            self.paso(m)
        base = Path(self.dir.name)
        entrega = base / "salida" / "entrega"
        exp, u = self.ubic("tv.club.test")

        md = (entrega / "expedientes" / f"{exp['id']}.md").read_text(encoding="utf-8")
        juez, minuto = res["juez"], canon.min_txt(res["min"])
        linea = next((x for x in md.splitlines() if x.startswith("- Reclamo R-077 ")), None)
        self.assertIsNotNone(linea, md)
        self.assertIn("de kiosco.club.test (minuto 3,1): fundado", linea)
        self.assertIn(f"{juez} lo resolvió en el minuto {minuto} (entrada {res['entrada']})", linea)
        self.assertIn("se reemplazaron por bloqueos por dominio (sello `", linea)
        self.assertIn("También cerró R-078, del mismo bloqueo.", linea)
        filas = [x for x in md.splitlines() if x.startswith("| `")]
        for oid in res["ordenes_reemplazo"]:
            fila = next(x for x in filas if oid in x)
            self.assertIn("| Reemplazo por reclamo R-077 |", fila)
        self.assertFalse(any("levantar_y_reemplazar" in x for x in md.splitlines()))

        acta = (entrega / "acta-del-partido.md").read_text(encoding="utf-8")
        seccion = acta[acta.index("## Reclamos"):acta.index("## Traspasos de turno")]
        for interno in INTERNOS:
            self.assertNotRegex(seccion, rf"(?<![\w-]){re.escape(interno)}(?![\w-])", interno)
        self.assertIn(f"{juez} lo resolvió en el minuto {minuto} (", seccion)
        self.assertIn("- R-078 kiosco.club.test (minuto 3,2), vía ", seccion)
        self.assertIn(": cerrado por la resolución de R-077 (", seccion)

        reg = base / "registro.jsonl"
        # El simulador oficial anota cada levantamiento en el registro (servidor.py: registrar("orden_levantada", …));
        # el falso lo guarda aparte, en lev_registro: se suma con la misma forma.
        levs = [{"min": x["min"], "evento": "orden_levantada", "orden_id": x["orden_id"], "juez_id": x["juez_id"]}
                for x in self.sim.lev_registro]
        reg.write_text("".join(json.dumps(r) + "\n" for r in sorted(self.sim.registro + levs, key=lambda r: r["min"])),
                       encoding="utf-8")
        self.assertEqual(malas(verificar(entrega)), [])
        self.assertEqual(malas(verificar(entrega, reg, base / "jueces.json")), [])


if __name__ == "__main__":
    unittest.main()
