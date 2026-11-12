"""Simulador falso en memoria, con la misma semántica que el oficial y reloj manual (solo para pruebas)."""
from __future__ import annotations

import base64
import hashlib
import hmac
from typing import Any, Callable, Dict, List, Optional, Tuple

from marca.simulador import ErrorRed

CAMPOS = ("orden_id", "expediente_id", "tipo", "objetivo", "vence_min", "juzgado_id", "juez_id", "firma")


def _fraccion(*partes: str) -> float:
    return int(hashlib.sha256("|".join(partes).encode()).hexdigest()[:8], 16) / 0x100000000


def captura(semilla: str) -> dict:
    datos = bytes([0x47]) + hashlib.sha256(semilla.encode()).digest() * 2
    datos = datos[:64]
    return {"capturada_min": 0, "formato": "mpegts", "duracion_seg": 6,
            "contenido_b64": base64.b64encode(datos).decode()}


def deteccion(did: str, minuto: float, host: str, ip: str, marca: Optional[str], pagina: str, asn: int) -> dict:
    cap = captura(did)
    cap["capturada_min"] = minuto
    return {"id": did, "minuto": minuto, "pagina": pagina, "stream_url": f"https://{host}/hls/index.m3u8",
            "host_stream": host, "ip_servidor": ip, "asn": asn, "marca_de_agua_extraida": marca, "captura": cap,
            "promocion": [{"red": "x", "url": "https://x.example/1", "minuto": 0.5}]}


PARTIDO = {
    "id": "prueba-01", "nombre": "Partido de prueba", "titular_derechos": "Liga Ficticia",
    "inicio_iso": "2026-11-11T18:00:00-03:00", "fin_min": 20,
    "marcas_de_agua_validas": [{"prefijo": "LP26-PRU-OFI", "origen": "Señal oficial"},
                               {"prefijo": "LP26-PRU-LIC-NORTE", "origen": "Licenciatario Norte"}],
    "licenciatarios": [{"nombre": "Canal Norte", "prefijo_marca": "LP26-PRU-LIC-NORTE",
                        "dominios_autorizados": ["canalnorte.test"]}],
}

DNS = {
    "203.0.113.10": ["s1.pirata.test", "s1-respaldo.pirata.test"],
    "203.0.113.11": ["s2.pirata.test"],
    "198.51.100.20": ["live.cdn-pirata.test", "panaderia.test", "municipio.example"],
    "192.0.2.10": ["envivo.canalnorte.test", "canalnorte.test"],
}
ASN_DE_IP = {"203.0.113.10": 64600, "203.0.113.11": 64600, "198.51.100.20": 64610, "192.0.2.10": 64640}
ASN = {"64600": "Hosting Dedicado", "64610": "NubeRápida CDN", "64640": "Canal Norte"}

DETECCIONES = [
    deteccion("D-0001", 1.0, "s1.pirata.test", "203.0.113.10", "LP26-PRU-OFI-S0001", "https://pirata.test/vivo", 64600),
    deteccion("D-0002", 1.5, "envivo.canalnorte.test", "192.0.2.10", "LP26-PRU-LIC-NORTE",
              "https://canalnorte.test/vivo", 64640),
    deteccion("D-0003", 2.0, "live.cdn-pirata.test", "198.51.100.20", "LP26-PRU-OFI-S0002",
              "https://cdn-pirata.test/p", 64610),
    deteccion("D-0004", 6.0, "s2.pirata.test", "203.0.113.11", "LP26-PRU-OFI-S0001", "https://pirata.test/vivo", 64600),
    deteccion("D-0005", 7.0, "s2.pirata.test", "203.0.113.11", "LP26-PRU-OFI-S0001", "https://pirata.test/vivo", 64600),
]

PROVEEDORES = [
    {"id": "aurora", "nombre": "Aurora", "tamano": "grande", "clientes": 1000, "capacidades": ["ip", "dominio"],
     "comportamiento": {"demora_min": 0.5, "tasa_falla": 0.0}},
    {"id": "valle", "nombre": "Valle", "tamano": "chico", "clientes": 100, "capacidades": ["dominio"],
     "comportamiento": {"demora_min": 1.0, "tasa_falla": 0.0}},
]

JUZGADOS = {
    "juzgados": [{"id": "jg-a", "nombre": "Juzgado A", "jurisdiccion": "X",
                  "jueces": [{"id": "juez-a", "nombre": "Dra. A", "clave_firma_demo": "clave-a"}]},
                 {"id": "jg-b", "nombre": "Juzgado B", "jurisdiccion": "X",
                  "jueces": [{"id": "juez-b", "nombre": "Dr. B", "clave_firma_demo": "clave-b"}]}],
    "turnos": [{"juez_id": "juez-a", "desde_min": -60, "hasta_min": 10},
               {"juez_id": "juez-b", "desde_min": 10, "hasta_min": 240}],
}


class SimuladorFalso:
    """Implementa la interfaz de marca.simulador.Cliente.

    Fallas de red a pedido (para los contratos del despacho), en `guion[metodo]`, una por llamada y en orden:
      "red"          ErrorRed sin efecto (no llegó);
      "red_despues"  la operación se aplica y la respuesta se pierde (ErrorRed);
      (codigo, cuerpo)            respuesta HTTP sin efecto (p. ej. (502, "Bad Gateway"));
      ("despues", codigo, cuerpo) la operación se aplica y responde ese código (p. ej. 504 de un proxy).
    `caido = True` hace que todo devuelva ErrorRed. `antes[metodo]` es una función que corre antes de responder.
    """

    def __init__(self) -> None:
        self.guion: Dict[str, List[Any]] = {}
        self.caido = False
        self.antes: Dict[str, Callable[[], None]] = {}
        self.lev_registro: List[dict] = []
        self.minuto = 0.0
        self.acelerar = 0.0001
        self._ords: Dict[str, Dict[str, dict]] = {p["id"]: {} for p in PROVEEDORES}
        self.registro = []
        self.lista_detecciones = list(DETECCIONES)
        self.lista_reclamos: list = []
        self.llamadas: Dict[str, int] = {}
        self.claves = {j["id"]: (jz["id"], j["clave_firma_demo"]) for jz in JUZGADOS["juzgados"] for j in jz["jueces"]}
        # Ronda 3, C13: `fallas_al_aplicar[pid] = n` hace que las próximas n órdenes aceptadas por ese proveedor
        # terminen «fallida» (en vez de «aplicada») al cumplirse su demora.
        self.fallas_al_aplicar: Dict[str, int] = {}

    def jueces_de_turno(self):
        return [t["juez_id"] for t in JUZGADOS["turnos"] if t["desde_min"] <= self.minuto < t["hasta_min"]]

    def avanzar(self, minuto: float) -> None:
        self.minuto = minuto
        prov = {p["id"]: p for p in PROVEEDORES}
        for pid, ords in self._ords.items():
            for o in ords.values():
                if o["estado"] == "recibida" and minuto >= o["_aplica"] and o.get("_falla"):
                    o["estado"] = "fallida"
                    o["motivo"] = "falla del proveedor (prueba)"
                    o["finalizada_min"] = round(o["_aplica"], 3)
                    self.registro.append({"min": o["finalizada_min"], "evento": "orden_fallida", "proveedor": pid,
                                          "orden_id": o["orden_id"]})
                    continue
                if o["estado"] == "recibida" and minuto >= o["_aplica"]:
                    o["estado"] = "aplicada"
                    o["aplicada_min"] = round(o["_aplica"], 3)
                    self.registro.append({"min": o["aplicada_min"], "evento": "orden_aplicada", "proveedor": pid,
                                          "orden_id": o["orden_id"]})
                if o["estado"] == "aplicada" and minuto >= o["vence_min"]:
                    o["estado"] = "vencida"
                    o["finalizada_min"] = float(max(o["vence_min"], o["aplicada_min"]))
        del prov

    def _vista(self, o):
        return {k: v for k, v in o.items() if not k.startswith("_")}

    # --- interfaz del cliente -------------------------------------------------------
    def estado(self):
        accion = self._falla("estado")
        if accion is not None:
            raise ErrorRed(f"estado: {accion} (prueba)")
        return {"partido": PARTIDO["id"], "minuto_actual": round(self.minuto, 2), "fin_min": float(PARTIDO["fin_min"]),
                "finalizado": self.minuto >= PARTIDO["fin_min"], "acelerar": self.acelerar,
                "jueces_de_turno": self.jueces_de_turno()}

    def partido(self):
        return PARTIDO

    def juzgados(self):
        return {"juzgados": [{"id": jz["id"], "nombre": jz["nombre"], "jurisdiccion": jz["jurisdiccion"],
                              "jueces": [{"id": j["id"], "nombre": j["nombre"]} for j in jz["jueces"]]}
                             for jz in JUZGADOS["juzgados"]],
                "turnos": JUZGADOS["turnos"], "de_turno_ahora": self.jueces_de_turno()}

    def proveedores(self):
        return [dict({k: v for k, v in p.items() if k != "comportamiento"}, ordenes="") for p in PROVEEDORES]

    def _contar(self, nombre: str) -> None:
        self.llamadas[nombre] = self.llamadas.get(nombre, 0) + 1

    def _falla(self, metodo: str):
        """Antes de responder: None (normal) o la falla que toca en esta llamada."""
        self._contar("llamada:" + metodo)
        if metodo in self.antes:
            self.antes[metodo]()
        if self.caido:
            raise ErrorRed("simulador caído (prueba)")
        cola = self.guion.get(metodo)
        if not cola:
            return None
        accion = cola.pop(0)
        if accion == "red":
            raise ErrorRed("corte de red (prueba)")
        return accion

    @staticmethod
    def _despues(accion, resultado):
        """Después de aplicar la operación: la respuesta que llega (o el corte)."""
        if accion == "red_despues":
            raise ErrorRed("respuesta perdida (prueba)")
        if isinstance(accion, tuple) and accion and accion[0] == "despues":
            return accion[1], accion[2]
        return resultado

    def detecciones(self, desde):
        self._contar("detecciones")
        corte = round(self.minuto, 3)

        def entra(d):  # Las inválidas (sin minuto numérico) salen en el primer lote, como si las mandara un tercero.
            m = d.get("minuto") if isinstance(d, dict) else None
            if not isinstance(m, (int, float)) or isinstance(m, bool):
                return desde < 0
            return desde < m <= corte
        return {"minuto_actual": corte, "detecciones": [d for d in self.lista_detecciones if entra(d)]}

    def reclamos(self):
        self._contar("reclamos")
        return {"minuto_actual": round(self.minuto, 2), "reclamos": list(self.lista_reclamos)}

    def dns_ip(self, ip):
        if ip not in DNS:
            return None
        return {"ip": ip, "asn": ASN_DE_IP.get(ip), "organizacion": ASN.get(str(ASN_DE_IP.get(ip))), "dominios": DNS[ip]}

    def dns_dominio(self, dominio):
        ips = [i for i, d in DNS.items() if dominio in d]
        if not ips:
            return None
        return {"dominio": dominio, "ips": [{"ip": i, "asn": ASN_DE_IP.get(i),
                                             "organizacion": ASN.get(str(ASN_DE_IP.get(i)))} for i in ips]}

    def ordenes(self, pid):
        accion = self._falla("ordenes")
        if accion is not None:
            raise ErrorRed(f"ordenes: {accion} (prueba)")
        self._contar("ordenes")
        self._contar("ordenes:" + pid)
        return [self._vista(o) for o in self._ords[pid].values()]

    def orden(self, pid, oid) -> Tuple[int, Any]:
        accion = self._falla("orden")
        if isinstance(accion, tuple) and accion[0] != "despues":
            return accion
        o = self._ords.get(pid, {}).get(oid)
        return (404, {"error": "Orden inexistente"}) if o is None else (200, self._vista(o))

    def enviar_orden(self, pid, cuerpo) -> Tuple[int, Any]:
        accion = self._falla("enviar_orden")
        if isinstance(accion, tuple) and accion[0] != "despues":
            return accion
        return self._despues(accion, self._enviar_orden(pid, cuerpo))

    def _enviar_orden(self, pid, cuerpo) -> Tuple[int, Any]:
        prov = next(p for p in PROVEEDORES if p["id"] == pid)
        err = None
        if any(c not in cuerpo for c in CAMPOS):
            err = (400, "Faltan campos")
        elif cuerpo["orden_id"] in self._ords[pid]:
            err = (409, "Ya existe una orden con ese orden_id en este proveedor")
        elif cuerpo["tipo"] not in prov["capacidades"]:
            err = (422, "tipo no aceptado")
        elif not isinstance(cuerpo["vence_min"], int) or cuerpo["vence_min"] <= self.minuto:
            err = (422, "vence_min")
        else:
            jz, clave = self.claves.get(cuerpo["juez_id"], (None, None))
            msg = f"{cuerpo['orden_id']}|{cuerpo['tipo']}|{cuerpo['objetivo']}|{cuerpo['vence_min']}|{cuerpo['juez_id']}"
            if clave is None or jz != cuerpo["juzgado_id"] or \
                    hmac.new(clave.encode(), msg.encode(), hashlib.sha256).hexdigest() != cuerpo["firma"]:
                err = (403, "Firma inválida")
        if err:
            self.registro.append({"min": self.minuto, "evento": "orden_rechazada", "proveedor": pid,
                                  "orden_id": cuerpo.get("orden_id"), "motivo": err[1]})
            return err[0], {"error": err[1]}
        demora = prov["comportamiento"]["demora_min"] * (0.7 + 0.6 * _fraccion(pid, cuerpo["orden_id"], "demora"))
        o = {c: cuerpo[c] for c in CAMPOS if c != "firma"}
        o.update({"estado": "recibida", "recibida_min": round(self.minuto, 3), "_aplica": self.minuto + demora})
        if self.fallas_al_aplicar.get(pid, 0) > 0:
            self.fallas_al_aplicar[pid] -= 1
            o["_falla"] = True
        self._ords[pid][cuerpo["orden_id"]] = o
        ev = {"min": round(self.minuto, 3), "evento": "orden_recibida", "proveedor": pid,
              "juez_de_turno": cuerpo["juez_id"] in self.jueces_de_turno()}
        ev.update({k: o[k] for k in CAMPOS if k != "firma"})
        self.registro.append(ev)
        return 202, {"orden_id": cuerpo["orden_id"], "estado": "recibida"}

    def levantar(self, pid, oid, cuerpo):
        accion = self._falla("levantar")
        if isinstance(accion, tuple) and accion[0] != "despues":
            return accion
        return self._despues(accion, self._levantar(pid, oid, cuerpo))

    def _levantar(self, pid, oid, cuerpo):
        o = self._ords.get(pid, {}).get(oid)
        if o is None:
            return 404, {"error": "Orden inexistente"}
        # Como el oficial: 403 si el juez no existe o la firma (LEVANTAR|orden_id|juez_id) no verifica.
        jz, clave = self.claves.get(cuerpo.get("juez_id"), (None, None))
        if clave is None or hmac.new(clave.encode(), f"LEVANTAR|{oid}|{cuerpo.get('juez_id')}".encode(),
                                     hashlib.sha256).hexdigest() != cuerpo.get("firma"):
            return 403, {"error": "Firma inválida"}
        if o["estado"] not in ("recibida", "aplicada"):
            return 409, {"error": "no activa"}
        self.lev_registro.append({"orden_id": oid, "juez_id": cuerpo.get("juez_id"), "min": self.minuto,
                                  "juez_de_turno": cuerpo.get("juez_id") in self.jueces_de_turno()})
        o["estado"] = "levantada"
        o["finalizada_min"] = round(self.minuto, 3)
        return 200, self._vista(o)
