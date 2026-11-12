"""Contrato (textos-5): el semáforo de daño colateral describe el bloqueo que se firma, no el de la IP.

`colateral.riesgo` del motor es el riesgo de bloquear la IP. Cuando la recomendación es bloquear solo el nombre
(dominio) por riesgo alto o medio de la IP, la comprobación 3 de la bandeja del juez no puede decir «Riesgo alto»
en rojo a secas, y la orden pública de un bloqueo por nombre no puede decir «Daño colateral: Alto». Donde el
bloqueo sí toca la IP (recomendación «ninguna», o una orden por IP) el rojo se mantiene.

Corre el código real de juez.js y orden.js con node (con un `el` mínimo); sin node, se saltea.
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

JS = Path(__file__).resolve().parent.parent / "marca" / "web" / "static" / "js"
NODE = shutil.which("node")

PROGRAMA = r"""
const fs = require('fs');
const [juez, orden, casos] = process.argv.slice(1);
function el(tag, opts, ...hijos) {
  opts = opts || {};
  const plano = (x) => (Array.isArray(x) ? x.flatMap(plano) : x == null || x === false ? [] : [x]);
  return { clase: plano([opts.class]).filter(Boolean).join(' '), text: opts.text, hijos: plano(hijos) };
}
const texto = (n) => (typeof n === 'string' ? n : (n.text || '') + n.hijos.map(texto).join(''));
const buscar = (n, p) => (typeof n === 'string' ? [] : [...(p(n) ? [n] : []), ...n.hijos.flatMap((h) => buscar(h, p))]);
function bloque(src, desde, hasta) {
  const i = src.indexOf(desde), f = src.indexOf(hasta, i + 1);
  if (i < 0 || f < 0) throw new Error('no encuentro ' + desde);
  return src.slice(i, f);
}
const sj = fs.readFileSync(juez, 'utf8');
const { comprobacionColateral } = new Function('el', bloque(sj, '  const RIESGO = {', '  function tablaBloqueos(') +
  '\nreturn { comprobacionColateral };')(el);
const so = fs.readFileSync(orden, 'utf8');
const { riesgo } = new Function('el', 'MP', bloque(so, '  function riesgo(', '\n  /*') + '\nreturn { riesgo };')(
  el, { capital: (s) => s.charAt(0).toUpperCase() + s.slice(1) });
const salida = JSON.parse(casos).map((c) => {
  const li = comprobacionColateral({ colateral: c.colateral });
  const res = buscar(li, (n) => n.clase === 'comprobacion__resultado')[0];
  const luz = buscar(li, (n) => n.clase.includes('semaforo__luz--encendida'))[0];
  const o = riesgo(c.colateral.riesgo, c.tipo_orden);
  return { clase: li.clase, resultado: texto(res), luz: luz ? luz.clase : '', detalle: texto(li),
           orden_clase: o.clase, orden_texto: texto(o) };
});
console.log(JSON.stringify(salida));
"""


def correr(casos):
    r = subprocess.run([NODE, "-e", PROGRAMA, str(JS / "juez.js"), str(JS / "orden.js"), json.dumps(casos)],
                       capture_output=True, text=True, timeout=30)
    if r.returncode:
        raise AssertionError(r.stderr)
    return json.loads(r.stdout)


def col(rec, riesgo):
    return {"recomendacion": rec, "riesgo": riesgo, "motivo": "…", "ajenos": ["a.test"] if riesgo == "alto" else []}


@unittest.skipUnless(NODE, "sin node: no se puede correr el JS")
class SemaforoDelBloqueoQueSeFirma(unittest.TestCase):
    def test_dominio_con_ip_compartida_no_es_rojo(self):
        for riesgo in ("alto", "medio"):
            with self.subTest(riesgo=riesgo):
                s = correr([{"colateral": col("dominio", riesgo), "tipo_orden": "dominio"}])[0]
                self.assertNotIn("comprobacion--alerta", s["clase"])
                self.assertNotIn("semaforo__luz--roja", s["luz"])
                self.assertIn("si se bloquea la IP", s["resultado"])
                self.assertIn("no afecta a sitios ajenos", s["detalle"])
                self.assertNotIn("alerta", s["orden_clase"])
                self.assertNotEqual(s["orden_texto"], "Alto")

    def test_donde_se_toca_la_ip_el_rojo_se_mantiene(self):
        s = correr([{"colateral": col("ninguna", "alto"), "tipo_orden": "ip"}])[0]
        self.assertIn("comprobacion--alerta", s["clase"])
        self.assertIn("semaforo__luz--roja", s["luz"])
        self.assertEqual(s["resultado"], "Riesgo alto")
        self.assertIn("alerta", s["orden_clase"])  # orden por IP con ajenos: el daño es real

    def test_ip_exclusiva_sigue_verde(self):
        s = correr([{"colateral": col("ip", "nulo"), "tipo_orden": "ip"}])[0]
        self.assertIn("comprobacion--ok", s["clase"])
        self.assertIn("semaforo__luz--verde", s["luz"])
        self.assertEqual(s["resultado"], "Sin daño colateral")


if __name__ == "__main__":
    unittest.main()
