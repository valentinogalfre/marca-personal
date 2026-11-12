"""R3B · C25 (humano-5). Contrato: el juez automático en modo serial se parece a una persona.

Con demora D (minutos de partido) y N pedidos que aparecen juntos, atiende de a uno: la orden marco espera D desde
que la ve, y cada firma queda a >= D de la acción anterior; el último pedido se firma a >= (N+1)·D del primero visto.
Sin serial, el comportamiento de siempre (OM inmediata, pedidos en paralelo) no cambia.
"""
import unittest

from herramientas.juez_automatico import JuezAutomatico


def correr(serial, demora=1.0, n=3, paso=0.05, traspaso=False):
    kw = {"serial": True} if serial else {}
    j = JuezAutomatico("http://127.0.0.1:1", "a", "x", demora, registro=lambda t: None, **kw)
    est = {"min": 10.0, "marco": None, "pend": set(range(1, n + 1))}
    firmas = []

    def pedir(metodo, ruta, cuerpo=None):
        firmas.append((est["min"], ruta))
        if ruta == "/api/juez/marco":
            est["marco"] = {"seguimiento": cuerpo["seguimiento"]}
        elif ruta == "/api/juez/traspaso/ratificar":
            est["ratificado"] = True
        else:
            est["pend"].discard(int(ruta.rsplit("/", 2)[1]))
        return 200, {}

    j._pedir = pedir
    j._puede_intentar = lambda clave, cada_s=2.0: True
    while est["pend"] and est["min"] < 100:
        ubs = [{"n": k, "ref": "E/%d" % k, "host": "h%d" % k, "propuesta": {"tipo": "ip"}} for k in range(1, n + 1)]
        j._atender({"reloj": {"minuto": est["min"]}, "turno": {"de_turno": True, "puede_firmar": True},
                    "yo": {"dinamica_habilitada": True},
                    "marco": {"puede_firmar": True, "firmada": est["marco"], "seguimiento_disponible": True},
                    "traspaso": {"min": 9.0} if traspaso and not est.get("ratificado") else None, "reclamos": [],
                    "pendientes": [{"expediente": {"id": "E", "ubicaciones": ubs}, "n": k} for k in sorted(est["pend"])]})
        est["min"] = round(est["min"] + paso, 6)
    return firmas


class TestJuezSerial(unittest.TestCase):
    def test_serial_atiende_de_a_uno_y_demora_la_om(self):
        f = correr(serial=True, demora=1.0, n=3)
        self.assertEqual([r for _, r in f][0], "/api/juez/marco")
        self.assertEqual(len(f), 4)
        self.assertGreaterEqual(f[0][0] - 10.0, 1.0, "la orden marco también espera la demora")
        for (a, _), (b, _) in zip(f, f[1:]):
            self.assertGreaterEqual(b - a, 1.0 - 1e-9, "dos decisiones seguidas quedan a >= D")
        self.assertGreaterEqual(f[-1][0] - 10.0, 4.0 - 1e-9)

    def test_serial_la_ratificacion_tambien_espera(self):
        f = correr(serial=True, demora=1.0, n=1, traspaso=True)
        self.assertEqual([r for _, r in f][:2], ["/api/juez/marco", "/api/juez/traspaso/ratificar"])
        for (a, _), (b, _) in zip(f, f[1:]):
            self.assertGreaterEqual(b - a, 1.0 - 1e-9)

    def test_sin_serial_no_cambia(self):
        f = correr(serial=False, demora=1.0, n=3)
        self.assertEqual(f[0], (10.0, "/api/juez/marco"))
        self.assertLess(f[-1][0] - f[1][0], 0.2, "sin serial, los pedidos maduran juntos (comportamiento previo)")


if __name__ == "__main__":
    unittest.main()
