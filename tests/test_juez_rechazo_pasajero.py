"""Contrato de la bandeja del juez: lo que el juez eligió sobrevive a un rechazo pasajero.

El motor contesta «fuera_de_turno» también por causas que se arreglan solas (simulador caído o lento, reloj que
retrocede, «su turno empieza en segundos»). Si la pantalla borra el formulario en ese caso, el segundo toque del mismo
botón firma la recomendación y no el tipo que el juez eligió, sin avisarle. La prueba corre la función `accion()` real
de juez.js en node con el resto de la página simulado.
"""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

JUEZ_JS = Path(__file__).resolve().parent.parent / "marca" / "web" / "static" / "js" / "juez.js"

ARNES = r"""
const vm = require('node:vm');
const fuente = process.argv[1];
const caso = JSON.parse(process.argv[2]);
const avisos = [];
const ctx = {
  est: { ocupado: new Set(), formas: new Map(), bandeja: { v: 1 }, vig: { refrescar() { ctx.refrescos++; }, adoptar() {} } },
  refrescos: 0, pintadas: 0,
  MP: {
    api: async () => { throw { codigo: caso.codigo, texto: caso.texto }; },
    avisar: (t) => avisos.push(t),
  },
  mostrarIngreso: () => {},
};
ctx.pintar = () => { ctx.pintadas++; };
ctx.forma = (k, ini) => { if (!ctx.est.formas.has(k)) ctx.est.formas.set(k, Object.assign({ error: '' }, ini || {})); return ctx.est.formas.get(k); };
vm.createContext(ctx);
vm.runInContext(fuente + '\nthis.accion = accion;', ctx);
const k = 'u:EXP-1/U1';
ctx.forma(k, { forzar: 'dominio', fundamento: 'Comparte IP con sitios legítimos.', rechazando: false, motivo: '', causal: null });
ctx.accion(k, '/api/juez/ubicaciones/EXP-1/1/aprobar', { alcance: 'ubicacion', forzar_tipo: 'dominio' }, 'ok').then(() => {
  const f = ctx.est.formas.get(k) || null;
  console.log(JSON.stringify({ forma: f, ocupado: ctx.est.ocupado.has(k), avisos, refrescos: ctx.refrescos }));
});
"""


def extraer_accion(texto: str) -> str:
    m = re.search(r"\n  async function accion\(k, ruta, cuerpo, exito\) \{\n.*?\n  \}\n", texto, re.S)
    if not m:
        raise AssertionError("no se encontró accion() en juez.js")
    return m.group(0)


@unittest.skipUnless(shutil.which("node"), "hace falta node para correr juez.js")
class RechazoPasajeroConservaElegido(unittest.TestCase):
    def correr(self, codigo: str, texto: str) -> dict:
        fuente = extraer_accion(JUEZ_JS.read_text(encoding="utf-8"))
        r = subprocess.run(["node", "-e", ARNES, fuente, json.dumps({"codigo": codigo, "texto": texto})],
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_fuera_de_turno_pasajero_conserva_tipo_y_fundamento(self):
        """Given: el juez eligió Dominio con fundamento; when: el motor contesta fuera_de_turno por falta de conexión;
        then: el formulario sigue con forzar='dominio' y el fundamento, y el motivo queda visible en la tarjeta."""
        texto = "Sin conexión con el simulador: no se puede confirmar el turno."
        out = self.correr("fuera_de_turno", texto)
        self.assertIsNotNone(out["forma"], "el rechazo pasajero borró lo que el juez eligió")
        self.assertEqual(out["forma"]["forzar"], "dominio")
        self.assertEqual(out["forma"]["fundamento"], "Comparte IP con sitios legítimos.")
        self.assertEqual(out["forma"]["error"], texto, "el motivo del rechazo tiene que quedar en la tarjeta")
        self.assertFalse(out["ocupado"])
        self.assertGreaterEqual(out["refrescos"], 1)

    def test_turno_que_empieza_en_segundos_tambien_conserva(self):
        out = self.correr("fuera_de_turno", "Su turno empieza en segundos: espere un momento y vuelva a intentar.")
        self.assertIsNotNone(out["forma"])
        self.assertEqual(out["forma"]["forzar"], "dominio")

    def test_pedido_que_cambio_si_limpia(self):
        """Cuando el pedido de verdad cambió (ya decidido / no existe), se descarta el formulario viejo."""
        for codigo in ("conflicto", "no_encontrado", "partido_finalizado"):
            with self.subTest(codigo=codigo):
                out = self.correr(codigo, "Esta ubicación ya fue decidida.")
                self.assertIsNone(out["forma"])


if __name__ == "__main__":
    unittest.main()
