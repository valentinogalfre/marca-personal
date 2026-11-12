"""Ola D, zona paquete (g-despacho-1). Contrato: los paquetes de cierre con una orden «sin confirmar» (502 en cada envío)
o «no enviada (el juez entrante no recibió el turno)» verifican con 0 ✗ (sin registro), y el acta y el expediente
muestran la frase de su causa y nunca «el partido terminaba» para esas órdenes."""
from pathlib import Path
from marca.verificar import verificar
from tests.test_falsificacion import malas
from tests.test_contratos_ronda2 import ConPartido, ordenes
from tests.test_g_despacho_no_enviada_motivo import _cerrar


class TresCausasVerifica(ConPartido):
    def _entrega(self, motor):
        return Path(motor.salida) / "entrega"

    def _chequear(self, motor, frase):
        ent = self._entrega(motor)
        self.assertEqual(malas(verificar(ent)), [])
        texto = (ent / "acta-del-partido.md").read_text(encoding="utf-8") + "".join(
            p.read_text(encoding="utf-8") for p in (ent / "expedientes").glob("*.md"))
        self.assertIn(frase, texto)
        self.assertNotIn("el partido terminaba", texto)

    def test_sin_confirmar(self):
        motor, sim, _ = self.preparar(aprobar=False)
        sim.guion["enviar_orden"] = [(502, None)] * 500
        motor.aprobar("juez-a", motor.e["expedientes"][0]["id"], 1, "ubicacion", None, None)
        motor.despacho.ronda()
        _cerrar(motor, sim)
        self._chequear(motor, "sin confirmar (se envió y, al cierre, el proveedor no la tenía)")

    def test_espera_ratificacion(self):
        motor, sim, _ = self.preparar(aprobar=False, minuto=9.6)
        motor.aprobar("juez-a", motor.e["expedientes"][0]["id"], 1, "ubicacion", None, None)
        sim.avanzar(10.4); motor._t_estado = float("-inf"); motor.paso(); motor.despacho.ronda()
        _cerrar(motor, sim)
        self._chequear(motor, "no enviada (el juez entrante no recibió el turno)")
