"""Contratos de herramientas/ensayo.py de la tanda R3B (C25 y el puerto del proxy).

- C25: `--demora-juez-s S` son segundos REALES por decisión: equivale a `--juez-serial --demora-juez S·acelerar/60`.
  El modo serial se le pasa al juez automático solo si lo acepta (si no, se avisa y corre como siempre).
- Un puerto ocupado por un ensayo anterior (queda en espera unos 30 s) se reintenta con un mensaje claro, hasta un
  tope, y después sale con un mensaje, no con un traceback. Otro error del sistema no se tapa.
"""
import errno
import socket
import sys
import unittest
from argparse import Namespace
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "herramientas"))
import ensayo  # noqa: E402
import proxy_latencia  # noqa: E402


class TestJuezDeEnsayo(unittest.TestCase):
    def test_demora_en_segundos_reales(self):
        a = Namespace(acelerar=20.0, demora_juez=0.3, juez_serial=False, demora_juez_s=30.0)
        ensayo.ajustar_juez(a)
        self.assertTrue(a.juez_serial)
        self.assertAlmostEqual(a.demora_juez, 10.0)  # 30 s reales a x20 = 10 min de partido
        b = Namespace(acelerar=20.0, demora_juez=0.3, juez_serial=False, demora_juez_s=None)
        ensayo.ajustar_juez(b)
        self.assertEqual((b.juez_serial, b.demora_juez), (False, 0.3))

    def test_serial_solo_si_el_juez_lo_acepta(self):
        class ConSerial:
            def __init__(self, base, usuario, clave, demora, serial=False):
                pass

        class SinSerial:
            def __init__(self, base, usuario, clave, demora):
                pass
        avisos = []
        self.assertEqual(ensayo.opciones_juez(True, ConSerial, avisos.append), {"serial": True})
        self.assertEqual(avisos, [])
        self.assertEqual(ensayo.opciones_juez(True, SinSerial, avisos.append), {})
        self.assertTrue(avisos and "serial" in avisos[0])
        self.assertEqual(ensayo.opciones_juez(False, ConSerial, avisos.append), {})

    def test_ayuda_dice_minutos_de_partido(self):
        texto = (RAIZ / "herramientas" / "ensayo.py").read_text(encoding="utf-8")
        self.assertIn("minutos DE PARTIDO (no segundos reales)", texto)


class TestPuertoOcupado(unittest.TestCase):
    def reloj(self):
        t = [0.0]
        return (lambda s: t.__setitem__(0, t[0] + s)), (lambda: t[0])

    def test_reintenta_mientras_esta_ocupado(self):
        dormir, ahora = self.reloj()
        intentos, avisos = [], []

        def abrir():
            intentos.append(1)
            if len(intentos) < 4:
                raise OSError(errno.EADDRINUSE, "Address already in use")
            return "abierto"
        self.assertEqual(ensayo.abrir_con_reintento(abrir, 8832, 40, dormir, ahora, avisos.append), "abierto")
        self.assertEqual(len(intentos), 4)
        self.assertEqual(len(avisos), 1)
        self.assertIn("puerto 8832 sigue ocupado; espero", avisos[0])

    def test_despues_del_tope_sale_con_mensaje(self):
        dormir, ahora = self.reloj()

        def abrir():
            raise OSError(errno.EADDRINUSE, "Address already in use")
        with self.assertRaises(SystemExit) as ctx:
            ensayo.abrir_con_reintento(abrir, 8832, 40, dormir, ahora, lambda t: None)
        self.assertIn("8832", str(ctx.exception.code))

    def test_otro_error_no_se_tapa(self):
        def abrir():
            raise OSError(errno.EACCES, "Permission denied")
        with self.assertRaises(OSError):
            ensayo.abrir_con_reintento(abrir, 80, 40, lambda s: None, lambda: 0.0, lambda t: None)

    def test_el_proxy_real_da_eaddrinuse_en_un_puerto_tomado(self):
        """El error que se reintenta es el que da el proxy de verdad sobre un puerto tomado."""
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        try:
            puerto = s.getsockname()[1]
            dormir, ahora = self.reloj()
            with self.assertRaises(SystemExit):
                ensayo.abrir_con_reintento(lambda: proxy_latencia.Proxy(puerto, "http://127.0.0.1:9"), puerto, 4,
                                           dormir, ahora, lambda t: None)
        finally:
            s.close()


if __name__ == "__main__":
    unittest.main()
