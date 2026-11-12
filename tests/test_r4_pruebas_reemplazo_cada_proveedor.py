"""Contrato (f-colateral-1 + f-colateral-3, reemplazo al resolver): cuando un reclamo fundado levanta el bloqueo por IP
de OTRO servidor del pirata (inferencia refutada en todos sus servidores), el stream de ese servidor queda bloqueado
por nombre en CADA proveedor que bloquea por dominio, no solo en alguno. Si no, ese proveedor deja de cortar una
filtración que la plataforma vio transmitir.

La prueba de test_r4_motor_colateral3 mira «algún proveedor»: pasa aunque `resolver_reclamo` no reemplace las IP de
los otros servidores, porque otro proveedor (solo dominio) ya tenía el nombre bloqueado desde la firma."""
import unittest

from tests import test_r4_motor_colateral3 as _c3


class ReemplazoEnCadaProveedor(_c3.RefutaRegistrableEntero):
    def test_reclamo_de_un_inquilino_libera_a_los_del_otro_servidor(self):  # ya cubierta en la base
        pass

    def test_cada_proveedor_que_bloquea_por_dominio_corta_cada_stream(self):
        self.sim.lista_reclamos.append({"id": "R-001", "minuto": 3.1, "dominio": "almacen.q.test",
                                        "proveedor": "aurora", "mensaje": "No carga mi negocio."})
        self.motor._t_reclamos = float("-inf"); self.motor._paso_reclamos()
        # Lo que el juez lee antes de firmar ya nombra el reemplazo del stream del otro servidor.
        prop = self.motor.e["reclamos"]["R-001"]["propuesta"]
        self.assertIn(("aurora", "tv2.q.test"), {(x["proveedor"], x["objetivo"]) for x in prop["reemplazo"]}, prop)
        self.motor.resolver_reclamo("juez-a", "R-001", "levantar_y_reemplazar", None)
        for m in (3.5, 4.0, 4.5, 5.0, 6.0):
            self.paso(m)
        v = self.vivas()
        por_dominio = [p["id"] for p in self.motor.e["proveedores"] if "dominio" in (p.get("capacidades") or [])]
        self.assertGreaterEqual(len(por_dominio), 2, "premisa: dos proveedores que bloquean por dominio")
        for pid in por_dominio:
            for host in ("tv.q.test", "tv2.q.test"):
                self.assertIn((pid, "dominio", host), v, (pid, host, sorted(v)))


if __name__ == "__main__":
    unittest.main()
