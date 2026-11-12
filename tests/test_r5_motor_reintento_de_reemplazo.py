"""g-despacho-2. Contrato NV1 extendido: la orden que REINTENTA un reemplazo por reclamo (C13: el reemplazo falló al
aplicarse y sale de nuevo con otro orden_id) dice en /orden/<id> y en el registro público la misma decisión que la
sella: la resolución del reclamo (decision_origen «reclamo», su minuto y su entrada), no la firma original."""
from marca.auditoria import leer_entradas
from tests.simulador_falso import deteccion
from tests.test_contratos_ronda2 import CDN, ConPartido, ordenes


class TestReintentoDeReemplazo(ConPartido):
    def test_reintento_de_reemplazo_dice_la_resolucion_del_reclamo(self):
        motor, sim, _ = self.preparar(det=[deteccion("D-1", 1.0, *CDN)], aprobar=False)
        exp = motor.e["expedientes"][0]
        motor.aprobar("juez-a", exp["id"], 1, "ubicacion", "ip", "Prueba: forzar IP en una red compartida")
        motor.despacho.ronda()
        sim.avanzar(3.0)
        sim.lista_reclamos = [{"id": "R-1", "minuto": 2.9, "dominio": "panaderia.test", "proveedor": "aurora"}]
        motor._t_estado = float("-inf"); motor.paso()
        motor._t_reclamos = float("-inf"); motor._paso_reclamos()
        motor.resolver_reclamo("juez-a", "R-1", "levantar_y_reemplazar", "Reclamo fundado")
        res = motor.e["reclamos"]["R-1"]["resolucion"]
        provs = {o["proveedor"] for o in ordenes(motor) if o["origen"] == "reemplazo_reclamo"}
        for p in provs:
            sim.fallas_al_aplicar[p] = 1          # el reemplazo se recibe y falla al aplicarse (C13)
        for m in (4.0, 6.0, 8.0, 10.0):
            motor.despacho.ronda(); sim.avanzar(m); motor._t_estado = float("-inf"); motor.paso(); motor.despacho.ronda()
        reint = [o for o in ordenes(motor) if o["origen"] == "reintento" and o.get("reclamo") == "R-1"]
        self.assertTrue(reint, "premisa: algún reemplazo falló y se reintentó")
        entradas = {e["n"]: e for e in leer_entradas(motor.salida / "auditoria.jsonl")}
        for o in reint:
            self.assertEqual(entradas[o["entrada_sello"]]["tipo"], "reclamo_resuelto")
            v = motor.vista_orden_publica(o["orden_id"])
            self.assertEqual((v["decision_origen"], v["reclamo"], v["decision_min"]), ("reclamo", "R-1", res["min"]),
                             o["orden_id"])
            self.assertEqual(v["decision"]["entrada"], o["entrada_sello"])
