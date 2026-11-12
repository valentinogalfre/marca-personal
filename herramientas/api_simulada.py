#!/usr/bin/env python3
"""API simulada de Marca Personal (solo para desarrollar y mostrar las pantallas).

Sirve las pantallas de `marca/web/` con las mismas rutas que el motor y responde
todas las rutas de la sección 10 de `docs/ESPECIFICACION.md` con datos coherentes.
Sigue un guion que avanza solo, tomado del partido de práctica del desafío:

  min 2     pedido nuevo: pelotaya.test en s1 (IP exclusiva: se propone IP)
  min 4     descarte: el licenciatario Canal Norte en su dominio
  min 6     pedido nuevo: golazo-libre.test en una CDN con 11 sitios ajenos (dominio)
  min 9     pedido nuevo: verpartido-hd.test en hosting compartido (dominio)
  ...       los proveedores aplican; Cumbre falla en algunos y se reintenta
  min 37,5  pelotaya.test se muda a s2: si el juez otorgó el seguimiento, se amplía sola
  min 50    traspaso de turno: Dra. Laura Ficticia -> Dr. Martín Ejemplo
  min 55    pedido nuevo: tribuna-pirata.test (x9)
  min 71    pelotaya.test se muda a s3 (se amplía sola si el traspaso está ratificado)
  min 82    tribuna-pirata.test se muda a x10
  min 105   final del partido: los bloqueos vencen
  min 110   cierre: verificación de vencimientos

Los reclamos aparecen si alguien bloquea por IP un servidor que comparte la IP
con sitios ajenos (por ejemplo, firmando verpartido-hd.test «apartándose de la
recomendación» por IP). Con --auto, un juez automático de ensayo firma la orden
marco, firma todo, fuerza IP en verpartido-hd.test para provocar el reclamo,
ratifica y resuelve.

Ronda 2b: orden marco (POST /api/juez/marco), presencia real del juez (90 s),
órdenes amp-, lista pública de cada proveedor (/proveedor/<id>/…) y consulta
«¿Tu sitio quedó bloqueado?» (/api/publico/consulta).

Uso:
  python3 herramientas/api_simulada.py [--puerto 8790] [--host 127.0.0.1]
         [--acelerar 6] [--inicio-min -0.5] [--auto] [--sin-dinamica]

Solo biblioteca estándar. Python 3.9 o superior. Todo vive en memoria.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import math
import secrets
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

RAIZ = Path(__file__).resolve().parent.parent
WEB = (RAIZ / "marca" / "web").resolve()
VERSION = "0.1.0-simulada"

# ---------------------------------------------------------------------------
# Usuarios de mentira (solo para esta API simulada; el motor usa config/).
# ---------------------------------------------------------------------------
USUARIOS = {
    "laura": {"clave": "toga-centro-2026", "rol": "juez", "juez_id": "jueza-laura-ficticia"},
    "martin": {"clave": "toga-norte-2026", "rol": "juez", "juez_id": "juez-martin-ejemplo"},
    "fiscalia": {"clave": "sala-fiscal-2026", "rol": "fiscalia", "nombre": "Fiscalía (demostración)"},
}

# ---------------------------------------------------------------------------
# Datos del partido de práctica (ficticios, del repositorio del desafío).
# ---------------------------------------------------------------------------
PARTIDO = {
    "id": "practica-01",
    "nombre": "Partido de práctica — Club Ficticio del Norte vs. Deportivo Ejemplo",
    "titular": "Liga Profesional Ficticia",
    "inicio_iso": "2026-11-11T18:00:00-03:00",
    "fin_min": 105,
}
MARCAS_VALIDAS = [
    {"prefijo": "LP26-PRA-OFI", "origen": "Señal oficial del titular (plataforma propia)"},
    {"prefijo": "LP26-PRA-LIC-NORTE", "origen": "Licenciatario autorizado: Canal Norte TV (ficticio)"},
]
LICENCIATARIOS = [
    {"nombre": "Canal Norte TV (ficticio)", "prefijo_marca": "LP26-PRA-LIC-NORTE",
     "dominios_autorizados": ["canalnorte.test", "envivo.canalnorte.test"]},
]
JUZGADOS = {
    "jg-centro-3": "Juzgado de Garantías N.º 3 (ficticio) — Distrito Judicial Centro",
    "jg-norte-1": "Juzgado de Garantías N.º 1 (ficticio) — Distrito Judicial Norte",
}
JUECES = {
    "jueza-laura-ficticia": {"nombre": "Dra. Laura Ficticia", "juzgado_id": "jg-centro-3"},
    "juez-martin-ejemplo": {"nombre": "Dr. Martín Ejemplo", "juzgado_id": "jg-norte-1"},
}
TURNOS = [
    {"juez_id": "jueza-laura-ficticia", "desde_min": -60, "hasta_min": 50},
    {"juez_id": "juez-martin-ejemplo", "desde_min": 50, "hasta_min": 240},
]
PROVEEDORES = [
    {"id": "aurora", "nombre": "Conectividad Aurora (ficticio)", "tamano": "grande", "clientes": 3800000,
     "capacidades": ["ip", "dominio"], "demora": 0.5},
    {"id": "andina", "nombre": "Red Andina Telecom (ficticio)", "tamano": "mediano", "clientes": 1200000,
     "capacidades": ["ip", "dominio"], "demora": 2.0},
    {"id": "valle", "nombre": "FibraValle (ficticio)", "tamano": "chico", "clientes": 140000,
     "capacidades": ["dominio"], "demora": 6.0},
    {"id": "cumbre", "nombre": "Cooperativa Cumbre Conecta (ficticio)", "tamano": "chico", "clientes": 60000,
     "capacidades": ["ip", "dominio"], "demora": 3.0},
]
PROV = {p["id"]: p for p in PROVEEDORES}
CLIENTES_TOTAL = sum(p["clientes"] for p in PROVEEDORES)

ASN = {
    64600: "Bruma Hosting Dedicado (ficticio)",
    64610: "NubeRápida CDN (ficticia)",
    64620: "Pampa Web Hosting Compartido (ficticio)",
    64630: "Servidores Litoral (ficticio)",
    64640: "Canal Norte TV (ficticio)",
}
DNS_IP = {
    "203.0.113.10": ["s1.pelotaya.test", "s1-respaldo.pelotaya.test", "tienda.pelotaya.test"],
    "203.0.113.11": ["s2.pelotaya.test"],
    "198.51.100.77": ["s3.pelotaya.test", "espejo.pelotaya.test"],
    "198.51.100.20": ["live.golazo-libre.test", "tienda-mate-y-yerba.test", "noticias-del-valle.test",
                      "turismo-cafayate.example", "radio-comunitaria-fm.test", "municipio-ejemplo.example",
                      "biblioteca-popular-norte.test", "delivery-salta-ejemplo.test", "clinica-veterinaria-sol.test",
                      "inmobiliaria-ejemplo.test", "academia-de-ingles.test", "feria-artesanal.example"],
    "192.0.2.50": ["tv.verpartido-hd.test", "verpartido-hd.test", "panaderia-la-espiga.test",
                   "club-atletico-barrio-norte.test", "escuela-tecnica-12.test", "estudio-contable-ruiz.test"],
    "203.0.113.40": ["x9.tribuna-pirata.test"],
    "203.0.113.41": ["x10.tribuna-pirata.test"],
    "198.51.100.90": ["vod.resumenes-deportivos.test", "resumenes-deportivos.test"],
    "192.0.2.10": ["envivo.canalnorte.test", "canalnorte.test"],
    "203.0.113.60": ["live.canchaabierta.test"],
    "203.0.113.70": ["hd.ultimo-minuto.test"],
}
IP_ASN = {"203.0.113.10": 64600, "203.0.113.11": 64600, "198.51.100.77": 64630, "198.51.100.20": 64610,
          "192.0.2.50": 64620, "203.0.113.40": 64600, "203.0.113.41": 64600, "198.51.100.90": 64630,
          "192.0.2.10": 64640, "203.0.113.60": 64600, "203.0.113.70": 64600}
DNS_DOMINIO: Dict[str, List[str]] = {}
for _ip, _doms in DNS_IP.items():
    for _d in _doms:
        DNS_DOMINIO.setdefault(_d, []).append(_ip)

# Ola C (9): en los últimos segundos la firma queda registrada, pero la orden ya no llega a los proveedores. Como el
# motor, solo lo dice el aviso de la respuesta de aprobar (no hay campo en la ubicación); el umbral es del simulador.
FUERA_DE_PLAZO_MIN = 0.5
TEXTO_FUERA_DE_PLAZO = ("Faltan segundos para el final del partido: la firma queda registrada, pero la orden ya no "
                        "llega a los proveedores y no bloquea.")

REPETICIONES_RECLAMO = {"panaderia-la-espiga.test": 6, "club-atletico-barrio-norte.test": 2}
RECLAMOS_AUTO = {
    "panaderia-la-espiga.test": (4, "Panadería La Espiga: nuestros clientes no pueden entrar a la tienda online desde hace unos minutos."),
    "club-atletico-barrio-norte.test": (6, "Club Atlético Barrio Norte: la página de inscripciones dejó de cargar."),
    "noticias-del-valle.test": (3, "Noticias del Valle: el diario no carga para lectores de varios proveedores."),
    "municipio-ejemplo.example": (5, "Municipio Ejemplo: el portal de trámites está caído para parte de los vecinos."),
    # C14: un nombre del registrable del pirata que la plataforma solo infirió (nunca lo vio transmitir ni publicar).
    "tienda.pelotaya.test": (7, "Tienda Pelotaya: vendemos camisetas, no transmitimos nada, y la tienda dejó de cargar."),
    # C14: el pirata reclama por el nombre de su propia página (observado): se desestima.
    "verpartido-hd.test": (8, "VerPartido HD: somos un sitio de resúmenes, no transmitimos; levanten el bloqueo."),
    "canalnorte.test": (2, "Canal Norte TV: somos licenciatarios autorizados y nuestra transmisión fue bloqueada."),
}

# (id, minuto, página, host del stream, ip, asn, marca)
DETECCIONES = [
    ("D-0001", 2.0, "https://pelotaya.test/en-vivo", "s1.pelotaya.test", "203.0.113.10", 64600, "LP26-PRA-OFI-S048211"),
    ("D-0002", 4.0, "https://canalnorte.test/en-vivo", "envivo.canalnorte.test", "192.0.2.10", 64640, "LP26-PRA-LIC-NORTE"),
    ("D-0003", 6.0, "https://golazo-libre.test/partido", "live.golazo-libre.test", "198.51.100.20", 64610, "LP26-PRA-OFI-S077310"),
    ("D-0004", 9.0, "https://verpartido-hd.test/vivo", "tv.verpartido-hd.test", "192.0.2.50", 64620, "LP26-PRA-OFI-S010457"),
    ("D-0005", 12.0, "https://pelotaya.test/en-vivo", "s1.pelotaya.test", "203.0.113.10", 64600, "LP26-PRA-OFI-S048211"),
    ("D-0006", 16.0, "https://golazo-libre.test/partido", "live.golazo-libre.test", "198.51.100.20", 64610, "LP26-PRA-OFI-S077310"),
    ("D-0007", 19.0, "https://verpartido-hd.test/vivo", "tv.verpartido-hd.test", "192.0.2.50", 64620, "LP26-PRA-OFI-S010457"),
    ("D-0008", 20.0, "https://resumenes-deportivos.test/fecha-3", "vod.resumenes-deportivos.test", "198.51.100.90", 64630, "LP25-F03-OFI-S102934"),
    ("D-0009", 22.0, "https://pelotaya.test/en-vivo", "s1.pelotaya.test", "203.0.113.10", 64600, "LP26-PRA-OFI-S048211"),
    ("D-0010", 26.0, "https://golazo-libre.test/partido", "live.golazo-libre.test", "198.51.100.20", 64610, "LP26-PRA-OFI-S077310"),
    ("D-0011", 29.0, "https://verpartido-hd.test/vivo", "tv.verpartido-hd.test", "192.0.2.50", 64620, "LP26-PRA-OFI-S010457"),
    ("D-0044", 30.5, "https://futbol-gratis.test/ahora", "cdn7.futbol-gratis.test", "198.51.100.99", 64630, ""),
    # Inventada (no está en la práctica): la señal del licenciatario fuera de sus dominios. Esa marca no trae
    # código de sesión, así que no admite seguimiento.
    ("D-0045", 31.5, "https://canchaabierta.test/vivo", "live.canchaabierta.test", "203.0.113.60", 64600, "LP26-PRA-LIC-NORTE"),
    ("D-0012", 32.0, "https://pelotaya.test/en-vivo", "s1.pelotaya.test", "203.0.113.10", 64600, "LP26-PRA-OFI-S048211"),
    ("D-0013", 36.0, "https://golazo-libre.test/partido", "live.golazo-libre.test", "198.51.100.20", 64610, "LP26-PRA-OFI-S077310"),
    ("D-0014", 37.5, "https://pelotaya.test/en-vivo", "s2.pelotaya.test", "203.0.113.11", 64600, "LP26-PRA-OFI-S048211"),
    ("D-0015", 39.0, "https://verpartido-hd.test/vivo", "tv.verpartido-hd.test", "192.0.2.50", 64620, "LP26-PRA-OFI-S010457"),
    ("D-0016", 44.0, "https://canalnorte.test/en-vivo", "envivo.canalnorte.test", "192.0.2.10", 64640, "LP26-PRA-LIC-NORTE"),
    ("D-0017", 46.0, "https://golazo-libre.test/partido", "live.golazo-libre.test", "198.51.100.20", 64610, "LP26-PRA-OFI-S077310"),
    ("D-0018", 47.5, "https://pelotaya.test/en-vivo", "s2.pelotaya.test", "203.0.113.11", 64600, "LP26-PRA-OFI-S048211"),
    ("D-0019", 49.0, "https://verpartido-hd.test/vivo", "tv.verpartido-hd.test", "192.0.2.50", 64620, "LP26-PRA-OFI-S010457"),
    ("D-0020", 50.0, "https://resumenes-deportivos.test/fecha-3", "vod.resumenes-deportivos.test", "198.51.100.90", 64630, "LP25-F03-OFI-S102934"),
    ("D-0021", 55.0, "https://tribuna-pirata.test/ver", "x9.tribuna-pirata.test", "203.0.113.40", 64600, "LP26-PRA-OFI-S063002"),
    ("D-0022", 56.0, "https://golazo-libre.test/partido", "live.golazo-libre.test", "198.51.100.20", 64610, "LP26-PRA-OFI-S077310"),
    ("D-0023", 57.5, "https://pelotaya.test/en-vivo", "s2.pelotaya.test", "203.0.113.11", 64600, "LP26-PRA-OFI-S048211"),
    ("D-0024", 59.0, "https://verpartido-hd.test/vivo", "tv.verpartido-hd.test", "192.0.2.50", 64620, "LP26-PRA-OFI-S010457"),
    ("D-0025", 65.0, "https://tribuna-pirata.test/ver", "x9.tribuna-pirata.test", "203.0.113.40", 64600, "LP26-PRA-OFI-S063002"),
    ("D-0026", 66.0, "https://golazo-libre.test/partido", "live.golazo-libre.test", "198.51.100.20", 64610, "LP26-PRA-OFI-S077310"),
    ("D-0027", 67.5, "https://pelotaya.test/en-vivo", "s2.pelotaya.test", "203.0.113.11", 64600, "LP26-PRA-OFI-S048211"),
    ("D-0028", 69.0, "https://verpartido-hd.test/vivo", "tv.verpartido-hd.test", "192.0.2.50", 64620, "LP26-PRA-OFI-S010457"),
    ("D-0029", 71.0, "https://pelotaya.test/en-vivo", "s3.pelotaya.test", "198.51.100.77", 64630, "LP26-PRA-OFI-S048211"),
    ("D-0030", 75.0, "https://tribuna-pirata.test/ver", "x9.tribuna-pirata.test", "203.0.113.40", 64600, "LP26-PRA-OFI-S063002"),
    ("D-0031", 76.0, "https://golazo-libre.test/partido", "live.golazo-libre.test", "198.51.100.20", 64610, "LP26-PRA-OFI-S077310"),
    ("D-0032", 79.0, "https://verpartido-hd.test/vivo", "tv.verpartido-hd.test", "192.0.2.50", 64620, "LP26-PRA-OFI-S010457"),
    ("D-0033", 81.0, "https://pelotaya.test/en-vivo", "s3.pelotaya.test", "198.51.100.77", 64630, "LP26-PRA-OFI-S048211"),
    ("D-0034", 82.0, "https://tribuna-pirata.test/ver", "x10.tribuna-pirata.test", "203.0.113.41", 64600, "LP26-PRA-OFI-S063002"),
    ("D-0035", 84.0, "https://canalnorte.test/en-vivo", "envivo.canalnorte.test", "192.0.2.10", 64640, "LP26-PRA-LIC-NORTE"),
    ("D-0036", 86.0, "https://golazo-libre.test/partido", "live.golazo-libre.test", "198.51.100.20", 64610, "LP26-PRA-OFI-S077310"),
    ("D-0037", 89.0, "https://verpartido-hd.test/vivo", "tv.verpartido-hd.test", "192.0.2.50", 64620, "LP26-PRA-OFI-S010457"),
    ("D-0038", 91.0, "https://pelotaya.test/en-vivo", "s3.pelotaya.test", "198.51.100.77", 64630, "LP26-PRA-OFI-S048211"),
    ("D-0039", 92.0, "https://tribuna-pirata.test/ver", "x10.tribuna-pirata.test", "203.0.113.41", 64600, "LP26-PRA-OFI-S063002"),
    ("D-0040", 96.0, "https://golazo-libre.test/partido", "live.golazo-libre.test", "198.51.100.20", 64610, "LP26-PRA-OFI-S077310"),
    ("D-0041", 99.0, "https://verpartido-hd.test/vivo", "tv.verpartido-hd.test", "192.0.2.50", 64620, "LP26-PRA-OFI-S010457"),
    ("D-0042", 101.0, "https://pelotaya.test/en-vivo", "s3.pelotaya.test", "198.51.100.77", 64630, "LP26-PRA-OFI-S048211"),
    ("D-0043", 102.0, "https://tribuna-pirata.test/ver", "x10.tribuna-pirata.test", "203.0.113.41", 64600, "LP26-PRA-OFI-S063002"),
    # Inventada (adenda 3, B): una detección en el minuto exacto del final. Queda «sin decidir» y su ventana
    # dura cero (cobertura con sin_ventana).
    ("D-0046", 105.0, "https://ultimo-minuto.test/vivo", "hd.ultimo-minuto.test", "203.0.113.70", 64600, "LP26-PRA-OFI-S090105"),
]

ACTIVAS = ("por_enviar", "recibida", "aplicada")
PRESENCIA_S = 90  # ronda 2b: «plataforma abierta» = actividad en los últimos 90 s reales
TITULO_CASILLA = "Autorizo el seguimiento de la misma filtración"
CONDICIONES_SEGUIMIENTO = [
    # C15 (CONTRATO-R3B): texto único de la orden marco, copiado palabra por palabra del contrato.
    "Si firmo un bloqueo con «Firmar y seguir a esta filtración» y esa misma filtración (la misma sesión de la marca "
    "de agua) aparece en otro servidor, la plataforma amplía el bloqueo sin esperar una firma nueva, solo si se cumple "
    "todo esto:",
    "La evidencia nueva está completa y sellada, y el bloqueo nuevo no alcanza a sitios ajenos: si el servidor nuevo "
    "comparte la IP con sitios ajenos, se bloquea solo el nombre del stream.",
    "Estoy de turno y con la plataforma abierta.",
    "Cada ampliación se me avisa en el momento, sale identificada como ampliación (su número empieza con amp-) "
    "y puedo frenarla o levantarla.",
    "Vence al final del partido. Fuera de estas condiciones, el pedido vuelve a mí.",
]
NO_RIGE = ("levantada", "vencida", "fallida", "rechazada", "perdida")
SUFIJOS_2N = {"com.ar", "gob.ar", "gov.ar", "org.ar", "net.ar", "edu.ar", "com.br", "com.mx", "com.uy",
              "com.py", "com.bo", "com.pe", "com.co", "com.cl", "co.uk"}


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def canonico(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def sha(texto: Any) -> str:
    if isinstance(texto, (dict, list)):
        texto = canonico(texto)
    if isinstance(texto, str):
        texto = texto.encode("utf-8")
    return hashlib.sha256(texto).hexdigest()


def utc_ahora() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def registrable(host: Optional[str]) -> Optional[str]:
    if not host:
        return None
    partes = host.lower().strip(".").split(".")
    if len(partes) >= 3 and ".".join(partes[-2:]) in SUFIJOS_2N:
        return ".".join(partes[-3:])
    return ".".join(partes[-2:])


def host_de(url: str) -> Optional[str]:
    try:
        return urlparse(url).hostname
    except ValueError:
        return None


def cubre(dominio: str, host: str) -> bool:
    return host == dominio or host.endswith("." + dominio)


def r3(x: Optional[float]) -> Optional[float]:
    return None if x is None else round(x, 3)


def r2(x: Optional[float]) -> Optional[float]:
    return None if x is None else round(x, 2)


def min_txt(x: Optional[float]) -> str:
    """C8: un solo redondeo de minutos, igual que el motor y que `Number(x).toFixed(1)` en el navegador:
    valor binario exacto, un decimal, empates lejos del cero, coma decimal. Nunca «-0,0»."""
    if x is None:
        return "no informado"
    d = Decimal(float(x)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    if d == 0:
        d = Decimal("0.0")
    return str(d).replace(".", ",")


def fmin(x: float) -> str:
    """Minuto para textos: 37.5 -> '37,5'; 105 -> '105' (como `marco._num`: mismo redondeo que min_txt)."""
    s = min_txt(x)
    return s[:-2] if s.endswith(",0") else s


def lista_corta(items: List[str], n: int = 2) -> str:
    if len(items) <= n:
        return " y ".join(items) if len(items) == 2 else ", ".join(items)
    return ", ".join(items[:n]) + " y %d más" % (len(items) - n)


class ErrorApi(Exception):
    def __init__(self, estado: int, codigo: str, texto: str):
        super().__init__(texto)
        self.estado, self.codigo, self.texto = estado, codigo, texto


# ---------------------------------------------------------------------------
# El mundo simulado
# ---------------------------------------------------------------------------
class Mundo:
    def __init__(self, acelerar: float, inicio_min: float, auto: bool, dinamica: bool):
        self.cond = threading.Condition(threading.RLock())
        self.v = 1
        self.acelerar = acelerar
        self.t0 = time.monotonic()
        self.min0 = inicio_min
        self.auto = auto
        self.dinamica_habilitada = dinamica
        self.inicio = datetime.fromisoformat(PARTIDO["inicio_iso"])
        self.auditoria: List[Dict[str, Any]] = []
        self.expedientes: List[Dict[str, Any]] = []
        self.descartes: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self.ordenes: List[Dict[str, Any]] = []
        self.contador_k: Dict[Tuple[int, int, str], int] = {}
        self.reclamos: List[Dict[str, Any]] = []
        self.reclamos_programados: List[Dict[str, Any]] = []
        self.reclamos_hechos: set = set()
        self.traspasos: List[Dict[str, Any]] = []
        self.avisos: List[Dict[str, Any]] = []
        self.sesiones: Dict[str, Dict[str, Any]] = {}
        self.fallos: Dict[str, Dict[str, float]] = {}
        self.i_det = 0
        self.turno_anterior: Optional[Tuple[str, ...]] = None
        self.finalizado_anotado = False
        self.cerrado_anotado = False
        self.paquete: Optional[Dict[str, Any]] = None
        # Ronda 2b: órdenes marco firmadas (la última de cada juez es la vigente) y actividad real de cada juez.
        self.marcos: List[Dict[str, Any]] = []
        self.actividad: Dict[str, float] = {}
        self.alertas_ausencia: Dict[str, Dict[str, Any]] = {}  # juez -> alerta abierta (C3)
        self.ultimo_aviso: Optional[str] = None  # turnos-2: aviso del último freno con levantamiento
        self.fallos_pasajeros = 0  # --fallo-pasajero: próximos «aprobar» que fallan como sin simulador
        self.auditar("inicio", "sistema", None, {"version": VERSION, "simulador": "api simulada (sin simulador)",
                                                  "partido": PARTIDO["id"], "dinamica": dinamica})

    # -- reloj --------------------------------------------------------------
    def minuto(self) -> float:
        return self.min0 + (time.monotonic() - self.t0) * self.acelerar / 60.0

    def hora(self, m: float) -> str:
        return (self.inicio + timedelta(minutes=m)).strftime("%H:%M:%S")

    def de_turno(self, m: float) -> List[str]:
        return [t["juez_id"] for t in TURNOS if t["desde_min"] <= m < t["hasta_min"]]

    def turno_de(self, juez_id: str) -> Dict[str, Any]:
        return next(t for t in TURNOS if t["juez_id"] == juez_id)

    def puede_firmar(self, juez_id: str, m: float) -> Tuple[bool, Optional[str]]:
        t = self.turno_de(juez_id)
        if m >= PARTIDO["fin_min"]:
            return False, "El partido terminó: ya no se firman órdenes."
        if m < t["desde_min"]:
            return False, "Su turno empieza en el min %s." % fmin(t["desde_min"])
        if m >= t["hasta_min"]:
            return False, "Su turno terminó."
        if t["hasta_min"] - m <= max(0.05, 2 * self.acelerar / 60):
            return False, "Su turno termina en segundos: este pedido pasa al juez entrante."
        if m - t["desde_min"] <= max(0.02, 0.5 * self.acelerar / 60):
            return False, "Su turno acaba de empezar: espere unos segundos y vuelva a intentar."
        return True, None

    def cambio(self) -> None:
        self.v += 1
        self.cond.notify_all()

    # -- presencia (ronda 2b, sección 2) ------------------------------------
    def marcar_actividad(self, juez_id: str) -> None:
        self.actividad[juez_id] = time.monotonic()

    def hace_s(self, juez_id: str) -> Optional[float]:
        t = self.actividad.get(juez_id)
        return None if t is None else time.monotonic() - t

    def activo(self, juez_id: str) -> bool:
        if self.auto:
            return True
        h = self.hace_s(juez_id)
        return h is not None and h <= PRESENCIA_S

    # -- orden marco (ronda 2b, sección 1) ----------------------------------
    def contenido_marco(self, juez_id: str, seguimiento: bool) -> Dict[str, Any]:
        t = self.turno_de(juez_id)
        fin = PARTIDO["fin_min"]
        oficiales = [x["prefijo"] for x in MARCAS_VALIDAS if "LIC" not in x["prefijo"]]
        lic = ", ".join("%s (%s)" % (", ".join(x["dominios_autorizados"]), x["nombre"]) for x in LICENCIATARIOS)
        lineas = [
            "Partido: %s. Titular de los derechos: %s." % (PARTIDO["nombre"], PARTIDO["titular"]),
            # C11: el renglón 2 dice hasta cuándo vale de verdad (turno que termina antes o que llega al final).
            "Esta orden vale durante mi turno en este partido: desde %s hasta %s. Todo bloqueo que se ordene bajo ella "
            "vence, como máximo, al final del partido (minuto %s)." % (
                "antes del inicio" if t["desde_min"] <= 0 else "el minuto %s" % fmin(t["desde_min"]),
                "el minuto %s" % fmin(t["hasta_min"]) if t["hasta_min"] < fin
                else "el final del partido (minuto %s)" % fmin(fin), fmin(fin)),
            # C15: renglones 3 y 4, como el contrato (el 4 no depende de la casilla).
            ("Solo se protege la señal del partido: la oficial (%s) y la de cada licenciatario cuando se transmite "
             "fuera de sus dominios (%s). Nunca se bloquea a un licenciatario en sus dominios: %s." % (
                 ", ".join(oficiales), ", ".join(x["prefijo_marca"] for x in LICENCIATARIOS), lic))
            if LICENCIATARIOS else "Solo se protege la señal oficial del partido (%s)." % ", ".join(oficiales),
            "Cada bloqueo necesita un expediente con evidencia sellada (la captura con su hash, la marca verificada y el "
            "servidor con host, IP y red) y mi firma, servidor por servidor, salvo que en esta orden autorice el "
            "seguimiento de la misma filtración.",
            "Si la IP es compartida o hay dudas, solo se bloquea el nombre del stream. Apartarse de esa regla exige mi "
            "fundamento escrito.",
            "Los reclamos se verifican y todo levantamiento lleva mi firma.",
        ]
        return {"version": 1,
                "partido": {"id": PARTIDO["id"], "nombre": PARTIDO["nombre"], "titular": PARTIDO["titular"], "fin_min": fin},
                "marcas_validas": oficiales,
                "licenciatarios": [{"nombre": x["nombre"], "prefijo_marca": x["prefijo_marca"],
                                    "dominios": x["dominios_autorizados"]} for x in LICENCIATARIOS],
                "proveedores": [{"id": p["id"], "nombre": p["nombre"], "capacidades": p["capacidades"]} for p in PROVEEDORES],
                "juez": {"juez_id": juez_id, "nombre": JUECES[juez_id]["nombre"],
                         "juzgado_id": JUECES[juez_id]["juzgado_id"], "juzgado": JUECES_JUZGADO(juez_id)},
                "turno": {"desde_min": t["desde_min"], "hasta_min": t["hasta_min"]},
                "seguimiento": bool(seguimiento), "lineas": lineas, "condiciones_seguimiento": CONDICIONES_SEGUIMIENTO}

    def marco_vigente(self, juez_id: Optional[str]) -> Optional[Dict[str, Any]]:
        return next((x for x in reversed(self.marcos) if x["juez_id"] == juez_id), None)

    def con_seguimiento(self, juez_id: Optional[str]) -> bool:
        om = self.marco_vigente(juez_id)
        return bool(om and om["seguimiento"])

    def firmar_marco(self, juez_id: str, seguimiento: bool) -> Dict[str, Any]:
        if not self.dinamica_habilitada:
            seguimiento = False
        m = self.minuto()
        contenido = self.contenido_marco(juez_id, seguimiento)
        huella = sha(contenido)
        anterior = self.marco_vigente(juez_id)
        om_id = "OM-%02d" % (len(self.marcos) + 1)
        e = self.auditar("orden_marco", "juez:" + juez_id, None, {
            "id": om_id, "juez_id": juez_id, "juzgado_id": JUECES[juez_id]["juzgado_id"], "huella": huella,
            "seguimiento": bool(seguimiento), "contenido": contenido,
            "firma": "(simulada) MARCO|%s|%s|%s|S%d" % (PARTIDO["id"], huella, juez_id, 1 if seguimiento else 0),
            "reemplaza": anterior["entrada"] if anterior else None})
        om = {"id": om_id, "juez_id": juez_id, "seguimiento": bool(seguimiento), "min": r2(m), "hora": self.hora(m),
              "entrada": e["n"], "huella": huella, "contenido": contenido}
        self.marcos.append(om)
        return om

    def estado_marco(self, om: Dict[str, Any]) -> Tuple[str, Optional[float]]:
        """C2: reemplazada / turno_terminado / partido_terminado / vigente, con el minuto en que dejó de valer."""
        fin = PARTIDO["fin_min"]
        m = self.minuto()
        t = self.turno_de(om["juez_id"])
        despues = [x for x in self.marcos if x["juez_id"] == om["juez_id"] and x["entrada"] > om["entrada"]]
        if despues:
            return "reemplazada", despues[0]["min"]
        if t["hasta_min"] < fin and m >= t["hasta_min"]:
            return "turno_terminado", float(t["hasta_min"])
        if m >= fin:
            return "partido_terminado", float(fin)
        return "vigente", None

    def vista_marco_publica(self, om: Dict[str, Any]) -> Dict[str, Any]:
        t = self.turno_de(om["juez_id"])
        estado, estado_min = self.estado_marco(om)
        return {"id": om["id"], "juez_id": om["juez_id"], "juez": JUECES[om["juez_id"]]["nombre"],
                "juzgado": JUECES_JUZGADO(om["juez_id"]),
                "min": om["min"], "hora": om["hora"], "huella": om["huella"], "seguimiento": om["seguimiento"],
                "turno": {"desde_min": t["desde_min"], "hasta_min": t["hasta_min"]}, "entrada": om["entrada"],
                "vigente": self.marco_vigente(om["juez_id"]) is om, "estado": estado, "estado_min": estado_min}

    def ref_marco(self, juez_id: Optional[str]) -> Optional[Dict[str, Any]]:
        om = self.marco_vigente(juez_id)
        return {"id": om["id"], "entrada": om["entrada"], "huella": om["huella"]} if om else None

    # -- auditoría ----------------------------------------------------------
    def auditar(self, tipo: str, actor: str, exp: Optional[str], datos: Dict[str, Any]) -> Dict[str, Any]:
        prev = self.auditoria[-1]["hash"] if self.auditoria else "0" * 64
        e = {"n": len(self.auditoria) + 1, "utc": utc_ahora(), "min": r3(self.minuto()), "tipo": tipo,
             "actor": actor, "exp": exp, "datos": datos, "prev": prev}
        e["hash"] = sha(e)
        self.auditoria.append(e)
        return e

    def avisar(self, tipo: str, texto: str, exp: Optional[str], para: Optional[str],
               clave: Optional[str] = None) -> Dict[str, Any]:
        a = {"n": len(self.avisos) + 1, "min": r2(self.minuto()), "tipo": tipo, "texto": texto,
             "exp": exp, "para": para, "clave": clave or (tipo + ":" + texto), "atendido": False, "cierre": None}
        self.avisos.append(a)
        return a

    def cerrar_aviso(self, a: Dict[str, Any], texto: str, m: float) -> None:
        """C3: el aviso queda atendido y guarda por qué se cerró (la pantalla lo muestra apagado, sin botones)."""
        if a.get("atendido"):
            return
        a["atendido"] = True
        a["cierre"] = {"min": r2(m), "texto": texto}

    def cerrar_avisos(self, pred, texto: str, m: float) -> None:
        for a in self.avisos:
            if not a.get("atendido") and pred(a):
                self.cerrar_aviso(a, texto, m)

    def atendido(self, a: Dict[str, Any]) -> bool:
        """Contrato: un aviso que pedía algo queda atendido cuando eso se resolvió."""
        if a.get("atendido"):
            return True
        clave = a.get("clave") or ""
        if a["tipo"] == "reclamo":
            dominio = clave.split(":", 1)[1] if ":" in clave else ""
            return not any(r["estado"] == "pendiente" and r["dominio"] == dominio for r in self.reclamos)
        if a["tipo"] == "traspaso" and clave.startswith("traspaso:"):
            t = next((x for x in self.traspasos if "traspaso:%s" % x["min"] == clave), None)
            return bool(t is None or t["ratificado"])  # «ratificó lo heredado» no pide nada
        return False

    def vista_avisos(self, crudos: List[Dict[str, Any]], tope: int) -> List[Dict[str, Any]]:
        """Contrato: los avisos repetidos se agrupan por `clave` (el último manda) con `cuenta` y `atendido`."""
        grupos: Dict[str, Dict[str, Any]] = {}
        for a in crudos:  # del más viejo al más nuevo
            g = grupos.get(a["clave"])
            cuenta = (g["cuenta"] + 1) if g else 1
            grupos.pop(a["clave"], None)
            grupos[a["clave"]] = dict(a, cuenta=cuenta)
        lista = list(grupos.values())[::-1][:tope]
        for a in lista:
            a["atendido"] = self.atendido(a)
            a.setdefault("cierre", None)
        return lista

    # -- búsqueda -----------------------------------------------------------
    def expediente(self, exp_id: str) -> Dict[str, Any]:
        for e in self.expedientes:
            if e["id"] == exp_id:
                return e
        raise ErrorApi(404, "no_encontrado", "No existe el expediente %s." % exp_id)

    def ubicacion(self, exp: Dict[str, Any], n: int) -> Dict[str, Any]:
        for u in exp["ubicaciones"]:
            if u["n"] == n:
                return u
        raise ErrorApi(404, "no_encontrado", "No existe la ubicación %s/U%d." % (exp["id"], n))

    def ordenes_de(self, exp_id: str, n: int) -> List[Dict[str, Any]]:
        return [o for o in self.ordenes if o["_exp"] == exp_id and o["_n"] == n]

    # -- análisis de evidencia (simplificado y coherente con la sección 4) ---
    def analizar_senal(self, marca: str, host: str) -> Dict[str, Any]:
        base = {"marca": marca or None, "prefijo": None, "origen": None, "sesion": None, "observaciones": []}
        if not marca:
            return dict(base, clase="sin_marca",
                        motivo="La detección no trae marca de agua: sin ella no se puede atribuir la filtración a este partido.")
        validos = [p for p in MARCAS_VALIDAS if marca == p["prefijo"] or marca.startswith(p["prefijo"] + "-")]
        if not validos:
            return dict(base, clase="otra_senal",
                        motivo="La marca de agua %s no corresponde a este partido: es otra señal." % marca)
        p = max(validos, key=lambda x: len(x["prefijo"]))
        sesion = marca[len(p["prefijo"]) + 1:] or None if marca != p["prefijo"] else None
        base.update(prefijo=p["prefijo"], origen=p["origen"], sesion=sesion)
        for lic in LICENCIATARIOS:
            if any(cubre(d, host) for d in lic["dominios_autorizados"]):
                return dict(base, clase="licenciatario",
                            motivo="%s transmite en su dominio autorizado (%s). No se bloquea." % (lic["nombre"], host))
        if p["prefijo"] == "LP26-PRA-OFI":
            motivo = "Lleva la marca de agua de la señal oficial del titular, fuera de su plataforma."
        else:
            motivo = "Lleva la señal del licenciatario fuera de sus dominios autorizados."
        return dict(base, clase="pirata", motivo=motivo)

    def analizar_servidor(self, host: str, ip: str, pagina: str, asn: int) -> Dict[str, Any]:
        dominios = list(DNS_IP.get(ip, []))
        operacion = {registrable(host), registrable(host_de(pagina))}
        piratas = {u["host"] for e in self.expedientes for u in e["ubicaciones"]}
        propios = [d for d in dominios if registrable(d) in operacion or d in piratas]
        if host in propios:
            propios.remove(host)
            propios.insert(0, host)
        ajenos = [d for d in dominios if d not in propios]
        org = ASN.get(asn, "Desconocida")
        red_compartida = any(x in org.lower() for x in ("cdn", "compartid", "shared"))
        varias_ip = len(DNS_DOMINIO.get(host, [])) > 1
        if not dominios:
            rec, riesgo = "dominio", "desconocido"
            motivo = "No hay datos de DNS pasivo de la IP %s: no se puede saber qué más aloja. Se bloquea solo el nombre del stream." % ip
        elif ajenos:
            rec, riesgo = "dominio", "alto"
            motivo = ("La IP aloja otros %d sitios que no tienen que ver con el pirata (%s). Bloquearla los dejaría "
                      "sin servicio: se bloquea solo el nombre del stream." % (len(ajenos), lista_corta(ajenos)))
        elif red_compartida:
            rec, riesgo = "dominio", "medio"
            motivo = "La IP pertenece a una red compartida (%s). Bloquearla podría afectar a otros clientes: se bloquea solo el nombre del stream." % org
        elif varias_ip:
            rec, riesgo = "dominio", "nulo"
            motivo = "El nombre %s aparece en más de una IP: se bloquea el nombre para cubrirlas todas." % host
        else:
            rec, riesgo = "ip", "nulo"
            if len(propios) > 1:
                motivo = "La IP es exclusiva del sitio pirata (%s y su respaldo %s). Bloquear la IP corta los dos." % (
                    propios[0], lista_corta(propios[1:]))
            else:
                motivo = "La IP es exclusiva del sitio pirata (%s). Bloquear la IP lo corta en el servidor." % host
        coherencia = {"host_en_url": True, "ip_en_dns_del_host": ip in DNS_DOMINIO.get(host, []),
                      "host_en_dns_de_la_ip": host in dominios, "asn_coincide": IP_ASN.get(ip) == asn}
        valores = list(coherencia.values())
        coherencia.update(ok=all(v is not False for v in valores), completa=all(v is True for v in valores),
                          observaciones=[] if all(valores) else ["El DNS pasivo no confirma todos los datos de la detección."])
        return {"dominios_en_ip": dominios, "propios": propios, "ajenos": ajenos, "red_compartida": red_compartida,
                "riesgo": riesgo, "recomendacion": rec, "motivo": motivo, "organizacion": org, "coherencia": coherencia}

    def proponer(self, tipo: str, host: str, ip: str, propios: List[str], fundamento: str) -> Dict[str, Any]:
        objetivos: Dict[str, List[Dict[str, str]]] = {}
        sin_cobertura: List[str] = []
        for p in PROVEEDORES:
            if tipo == "ip":
                if "ip" in p["capacidades"]:
                    objetivos[p["id"]] = [{"tipo": "ip", "objetivo": ip}]
                else:
                    objetivos[p["id"]] = [{"tipo": "dominio", "objetivo": d} for d in (propios or [host])]
            elif tipo == "dominio":
                if "dominio" in p["capacidades"]:
                    objetivos[p["id"]] = [{"tipo": "dominio", "objetivo": host}]
                else:
                    sin_cobertura.append(p["id"])
        vence = int(math.ceil(PARTIDO["fin_min"]))
        # C26 (textos-7): la hora del vencimiento sale del servidor, igual que en la orden que recibe el proveedor.
        return {"tipo": tipo, "vence_min": vence, "vence_hora": self.hora(vence), "fundamento": fundamento,
                "objetivos_por_proveedor": objetivos, "sin_cobertura": sin_cobertura}

    @staticmethod
    def captura(det_id: str, m: float) -> Dict[str, Any]:
        datos = b"\x47" + hashlib.sha256(det_id.encode()).digest() * 2
        datos = datos[:64]
        return {"sha256": hashlib.sha256(datos).hexdigest(), "bytes": len(datos), "formato": "mpegts",
                "duracion_seg": 6, "capturada_min": m, "sync_mpegts": True, "repetida": False, "valida": True}

    # -- ciclo --------------------------------------------------------------
    def tick(self) -> None:
        with self.cond:
            m = self.minuto()
            hubo = False
            while self.i_det < len(DETECCIONES) and DETECCIONES[self.i_det][1] <= m:
                self.procesar_deteccion(DETECCIONES[self.i_det])
                self.i_det += 1
                hubo = True
            hubo |= self.revisar_turno(m)
            hubo |= self.revisar_ampliaciones(m)
            hubo |= self.avanzar_ordenes(m)
            hubo |= self.revisar_reclamos(m)
            hubo |= self.revisar_final(m)
            hubo |= self.revisar_presencia(m)
            if self.auto:
                hubo |= self.juez_automatico(m)
            if hubo:
                self.cambio()

    def revisar_presencia(self, m: float) -> bool:
        """Ronda 2b: la sala ve quién está activo; alerta (una por clave) si el juez de turno no está y hay pedidos."""
        activos = tuple(j for j in JUECES if self.activo(j))
        hubo = activos != getattr(self, "_activos", None)
        self._activos = activos
        for j in JUECES:
            esperando = sum(1 for e in self.expedientes for u in e["ubicaciones"]
                            if u["estado"] == "pendiente" and u["asignada_a"] == j)
            abierta = self.alertas_ausencia.get(j)
            if abierta is not None:
                # C3: la alerta se cierra sola cuando el juez vuelve o ya no hay pedidos esperando.
                if self.activo(j):
                    self.cerrar_aviso(abierta, "%s volvió a tener la plataforma abierta en el minuto %s." % (
                        JUECES[j]["nombre"], min_txt(r2(m))), m)
                elif not esperando:
                    self.cerrar_aviso(abierta, "Ya no hay pedidos esperando (minuto %s)." % min_txt(r2(m)), m)
                if abierta["atendido"]:
                    del self.alertas_ausencia[j]
                    hubo = True
                continue
            if m < PARTIDO["fin_min"] and j in self.de_turno(m) and esperando and not self.activo(j):
                # Una alerta nueva por cada ausencia (no queda muda por haber alertado antes en el mismo turno).
                a = self.avisar("alerta", "%s está de turno y no tiene la plataforma abierta: hay %d %s esperando." % (
                    JUECES[j]["nombre"], esperando, "pedido" if esperando == 1 else "pedidos"), None, None,
                    clave="ausente-%s-%s" % (j, r2(m)))
                a["juez_ausente"] = j
                self.alertas_ausencia[j] = a
                hubo = True
        return hubo

    def procesar_deteccion(self, d: Tuple) -> None:
        det_id, minuto, pagina, host, ip, asn, marca = d
        self.auditar("deteccion_recibida", "titular", None, {"deteccion": det_id, "host": host, "ip": ip})
        senal = self.analizar_senal(marca, host)
        if senal["clase"] != "pirata":
            clave = (host, senal["clase"])
            if clave in self.descartes:
                self.descartes[clave]["veces"] += 1
                self.descartes[clave]["ultima_min"] = minuto
            else:
                self.descartes[clave] = {"deteccion_id": det_id, "minuto": minuto, "host": host, "ip": ip,
                                         "pagina": pagina, "marca": marca or None, "clase": senal["clase"],
                                         "motivo": senal["motivo"], "veces": 1, "ultima_min": minuto}
            self.auditar("deteccion_descartada", "sistema", None, {"deteccion": det_id, "clase": senal["clase"]})
            return
        sitio = registrable(host_de(pagina))
        exp, criterio = None, None
        for e in self.expedientes:
            if marca in e["filtracion"]["marcas"]:
                exp, criterio = e, "misma_marca"
                break
        if exp is None:
            for e in self.expedientes:
                if e["sitio"] == sitio:
                    exp, criterio = e, "mismo_sitio"
                    break
        if exp is None:
            num = len(self.expedientes) + 1
            exp = {"id": "EXP-2026-%06d" % num, "num": num, "titulo": sitio, "sitio": sitio, "creado_min": r3(minuto),
                   "filtracion": {"clave": marca, "sesion": senal["sesion"], "marcas": [marca],
                                  "prefijo": senal["prefijo"], "origen": senal["origen"]},
                   "dinamica": None, "corte_en_origen": None, "ubicaciones": []}
            self.expedientes.append(exp)
            self.auditar("expediente_abierto", "sistema", exp["id"], {"sitio": sitio, "clave": marca})
        elif marca not in exp["filtracion"]["marcas"]:
            exp["filtracion"]["marcas"].append(marca)
        previa = next((u for u in reversed(exp["ubicaciones"]) if u["host"] == host and u["ip"] == ip), None)
        rechazo = (previa or {}).get("decision") or {}
        if previa is not None and previa["estado"] == "rechazada" and minuto > (rechazo.get("min") or 0) \
                and minuto < PARTIDO["fin_min"]:
            # C22: el servidor rechazado se vuelve a ver después del rechazo: pedido nuevo, nunca se amplía solo.
            self.armar_ubicacion(exp, det_id, minuto, pagina, host, ip, asn, marca, senal, "mismo_servidor",
                                 rechazada=previa)
            return
        if previa is not None and not previa.get("levantada_por_freno"):
            previa["detecciones"].append(det_id)
            previa["n_detecciones"] += 1
            previa["ultima_deteccion_min"] = minuto
            return
        if previa is not None:
            # C4: el juez frenó el seguimiento y levantó esta ampliación; el servidor sigue transmitiendo, así que
            # vuelve a la bandeja del juez de turno como un pedido nuevo (nunca se amplía solo).
            self.armar_ubicacion(exp, det_id, minuto, pagina, host, ip, asn, marca, senal, "mismo_servidor",
                                 reabre=previa)
            return
        self.armar_ubicacion(exp, det_id, minuto, pagina, host, ip, asn, marca, senal, criterio)

    def armar_ubicacion(self, exp, det_id, minuto, pagina, host, ip, asn, marca, senal, criterio, reabre=None,
                        rechazada=None) -> None:
        m = self.minuto()
        n = len(exp["ubicaciones"]) + 1
        reabre = reabre or rechazada
        srv = self.analizar_servidor(host, ip, pagina, asn)
        cap = self.captura(det_id, minuto)
        limpia = srv["coherencia"]["completa"] and cap["valida"] and srv["recomendacion"] != "ninguna"
        colateral = {k: srv[k] for k in ("dominios_en_ip", "propios", "ajenos", "red_compartida", "riesgo",
                                          "recomendacion", "motivo")}
        colateral["limpia"] = limpia
        fundamento = ("Retransmisión no autorizada de «%s» con %s (sesión %s). %s" % (
            PARTIDO["nombre"], "la señal oficial del titular" if senal["prefijo"] == "LP26-PRA-OFI" else "la señal del licenciatario",
            senal["sesion"] or "sin sesión", "Bloqueo por IP: el servidor es exclusivo del sitio pirata."
            if srv["recomendacion"] == "ip" else "Bloqueo por nombre: la IP no es exclusiva del pirata."))
        propuesta = self.proponer(srv["recomendacion"], host, ip, srv["propios"], fundamento)
        slug = (registrable(host) or "x").split(".")[0]
        promocion = [{"red": "x", "url": "https://x.example/%s/status/%d" % (slug, 1000 + int(det_id[2:])),
                      "minuto": max(0.0, minuto - 1)}]
        detec = {"id": det_id, "minuto": minuto, "pagina": pagina, "stream_url": "https://%s/hls/en-vivo/index.m3u8" % host,
                 "host_stream": host, "ip_servidor": ip, "asn": asn, "marca_de_agua_extraida": marca}
        anterior = reabre or (exp["ubicaciones"][-1] if exp["ubicaciones"] else None)
        sellado = {"version": 1, "expediente": exp["id"], "ubicacion": n,
                   "partido": {"id": PARTIDO["id"], "nombre": PARTIDO["nombre"], "titular": PARTIDO["titular"],
                               "fin_min": PARTIDO["fin_min"], "huella": sha(PARTIDO)},
                   "deteccion": detec, "captura": cap, "senal": senal,
                   "servidor": {"pagina": pagina, "stream_url": detec["stream_url"], "host": host, "ip": ip, "asn": asn,
                                "organizacion": srv["organizacion"]},
                   "coherencia": srv["coherencia"], "colateral": colateral, "promocion": promocion,
                   "propuesta": propuesta,
                   "antecedente": {"ubicacion": anterior["n"], "huella": anterior["huella"]} if anterior else None,
                   "armado": {"min": r3(m), "utc": utc_ahora()}}
        huella = sha(sellado)
        asignada = (self.de_turno(m) or [None])[0]
        u = {"n": n, "ref": "%s/U%d" % (exp["id"], n), "estado": "pendiente", "host": host, "ip": ip, "asn": asn,
             "organizacion": srv["organizacion"], "pagina": pagina, "stream_url": detec["stream_url"],
             "primera_deteccion_min": minuto, "ultima_deteccion_min": minuto, "detecciones": [det_id], "n_detecciones": 1,
             "continuidad": {"de_ubicacion": anterior["n"], "criterio": criterio} if anterior else None,
             "senal": senal, "captura": cap, "coherencia": srv["coherencia"], "colateral": colateral,
             "promocion": promocion, "propuesta": propuesta, "huella": huella, "armado_min": r3(m),
             "armado_utc": sellado["armado"]["utc"], "asignada_a": asignada, "notificada_min": r3(m), "vista_min": None,
             "decision": None, "_marca": marca, "_automatica": {"posible": False, "motivo": None}}
        if rechazada is not None:
            dr = rechazada["decision"]
            quien = "usted" if dr["juez_id"] == asignada else dr["juez"]
            nota = ("Mismo servidor: %s rechazó este pedido en el minuto %s; la plataforma lo volvió a ver transmitiendo "
                    "en el minuto %s." % (quien, min_txt(dr["min"]), min_txt(minuto)))
            u["continuidad"]["nota"] = nota
            u["rechazo_previo"] = {"ref": rechazada["ref"], "min": dr["min"], "juez_id": dr["juez_id"],
                                   "juez": dr["juez"], "motivo": dr.get("motivo_rechazo")}
            # Paridad con el motor (motor.py, C22): el mismo texto.
            u["_automatica"] = {"posible": False, "motivo": "este servidor ya fue rechazado en el minuto %s; queda para "
                                                            "decidir en persona." % min_txt(dr["min"])}
        elif reabre is not None:
            lf = reabre["levantada_por_freno"]
            quien = "usted" if lf["juez_id"] == asignada else lf["juez"]
            nota = ("Mismo servidor: la plataforma lo había bloqueado sola en el minuto %s; %s levantó ese bloqueo "
                    "en el minuto %s." % (min_txt(lf.get("ampliada_min")), quien, min_txt(lf["min"])))
            u["continuidad"]["nota"] = nota
            u["reabierta"] = {"de_ubicacion": reabre["n"], "nota": nota, "levantada_min": lf["min"],
                              "juez_id": lf["juez_id"], "juez": lf["juez"]}
        exp["ubicaciones"].append(u)
        self.auditar("ubicacion_armada", "sistema", exp["id"], {"ubicacion": n, "huella": huella, "host": host, "ip": ip})
        if asignada:
            self.auditar("notificacion_juez", "sistema", exp["id"], {"ubicacion": n, "juez_id": asignada})
        else:
            self.auditar("alerta", "sistema", exp["id"], {"texto": "No hay juez de turno para asignar el pedido."})

    # -- turnos -------------------------------------------------------------
    def revisar_turno(self, m: float) -> bool:
        actual = tuple(self.de_turno(m))
        if self.turno_anterior is None:
            self.turno_anterior = actual
            return False
        if actual == self.turno_anterior:
            return False
        saliente, self.turno_anterior = self.turno_anterior, actual
        if not actual:
            return True
        entrante = actual[0]
        for e in self.expedientes:
            for u in e["ubicaciones"]:
                if u["estado"] == "pendiente":
                    u["asignada_a"] = entrante
            if e["dinamica"] and e["dinamica"]["activa"]:
                e["dinamica"]["requiere_ratificacion"] = True
        for r in self.reclamos:
            if r["estado"] == "pendiente":
                r["asignado_a"] = entrante
        t = {"min": r2(m), "de": [{"juez_id": j, "nombre": JUECES[j]["nombre"]} for j in saliente],
             "a": [{"juez_id": j, "nombre": JUECES[j]["nombre"]} for j in actual],
             "requiere_ratificacion": True, "ratificado": None, "resumen": None}
        t["resumen"] = self.resumen_traspaso()
        self.traspasos.append(t)
        e = self.auditar("traspaso_de_turno", "sistema", None, {"de": list(saliente), "a": list(actual)})
        t["_entrada"] = e["n"]
        texto = "Cambio de turno en el min %s: %s entrega a %s." % (
            fmin(m), ", ".join(JUECES[j]["nombre"] for j in saliente), JUECES[entrante]["nombre"])
        self.avisar("traspaso", texto + " Hay que ratificar lo heredado.", None, entrante, clave="traspaso:%s" % t["min"])
        return True

    def resumen_traspaso(self) -> Dict[str, Any]:
        return {"ubicaciones_pendientes": sum(1 for e in self.expedientes for u in e["ubicaciones"] if u["estado"] == "pendiente"),
                "reclamos_pendientes": sum(1 for r in self.reclamos if r["estado"] == "pendiente"),
                "bloqueos_vigentes": sum(1 for o in self.ordenes if o["estado"] == "aplicada"),
                "dinamicas": [{"exp": e["id"], "titulo": e["titulo"], "sesion": e["filtracion"]["sesion"]}
                              for e in self.expedientes if e["dinamica"] and e["dinamica"]["activa"]],
                "ordenes_en_espera": sum(1 for o in self.ordenes if o["estado"] == "espera_ratificacion"),
                # Contrato: levantamientos firmados que todavía no salieron (en la API simulada salen en el acto).
                "levantamientos_pendientes": []}

    def traspaso_pendiente(self) -> Optional[Dict[str, Any]]:
        for t in reversed(self.traspasos):
            if t["ratificado"] is None:
                return t
            break
        return None

    # -- órdenes ------------------------------------------------------------
    def crear_orden(self, exp, u, prov_id, tipo, objetivo, juez_id, sello, origen, m, reemplaza=None, intento=1,
                    reclamo=None, prefijo="ord"):
        clave = (exp["num"], u["n"], prov_id)
        k = self.contador_k.get(clave, 0) + 1
        self.contador_k[clave] = k
        # Ronda 2b, sección 3: las órdenes de una ampliación automática empiezan con amp-.
        oid = "%s-%04d-u%d-%s-%02d-%s" % (prefijo, exp["num"], u["n"], prov_id, k, sello)
        frac = int(hashlib.sha256(oid.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
        demora = PROV[prov_id]["demora"] * (0.7 + 0.6 * frac)
        falla = prov_id == "cumbre" and intento == 1 and (exp["num"] + u["n"]) % 2 == 0 and origen == "decision"
        o = {"orden_id": oid, "proveedor": prov_id, "proveedor_nombre": PROV[prov_id]["nombre"], "tipo": tipo,
             "objetivo": objetivo, "vence_min": int(math.ceil(PARTIDO["fin_min"])), "juez_id": juez_id,
             "juzgado_id": JUECES[juez_id]["juzgado_id"], "estado": "por_enviar", "intento": intento,
             "origen": origen, "reemplaza": reemplaza, "enviada_min": None, "recibida_min": None,
             "aplicada_min": None, "finalizada_min": None, "motivo": None,
             "_exp": exp["id"], "_n": u["n"], "_sello": sello, "_demora": demora, "_falla": falla,
             "_aplicar_en": None,
             # Contrato: el levantamiento firmado (o null) y el reclamo que originó un reemplazo (o null).
             "levantamiento": None, "reclamo": reclamo}
        self.ordenes.append(o)
        self.enviar(o, m)
        return o

    def enviar(self, o: Dict[str, Any], m: float) -> None:
        ok, _ = self.puede_firmar(o["juez_id"], m)
        if not ok:
            o["estado"] = "espera_ratificacion"
            self.auditar("orden_en_espera", "sistema", o["_exp"], {"orden_id": o["orden_id"]})
            return
        if PARTIDO["fin_min"] - m < FUERA_DE_PLAZO_MIN:
            # Ola C (parte 6), como el motor al cierre: firmada en los últimos segundos, ya no sale. Queda por_enviar
            # con `no_enviada` para que las pantallas no digan «enviado» de algo que nunca llegó al proveedor.
            o["no_enviada"] = True
            o["motivo"] = "No salió: al cierre el proveedor no la tiene."
            return
        o["estado"] = "recibida"
        o["enviada_min"] = o["recibida_min"] = r2(m)
        o["_aplicar_en"] = m + o["_demora"]
        self.auditar("orden_enviada", "juez:" + o["juez_id"], o["_exp"],
                     {"orden_id": o["orden_id"], "proveedor": o["proveedor"], "tipo": o["tipo"], "objetivo": o["objetivo"]})

    def objetivo_activo(self, prov_id: str, tipo: str, objetivo: str) -> bool:
        return any(o["proveedor"] == prov_id and o["tipo"] == tipo and o["objetivo"] == objetivo
                   and o["estado"] in ACTIVAS for o in self.ordenes)

    def avanzar_ordenes(self, m: float) -> bool:
        hubo = False
        if m >= PARTIDO["fin_min"]:
            # g-despacho-1, como el motor al finalizar: lo que nunca salió (por enviar o esperando al juez entrante)
            # queda `no_enviada`; las pantallas distinguen la causa por el estado y `enviada_min`.
            for o in self.ordenes:
                if o["estado"] in ("por_enviar", "espera_ratificacion") and not o.get("no_enviada"):
                    o["no_enviada"] = True
                    o["motivo"] = "No salió: terminó el partido."
                    hubo = True
        for o in list(self.ordenes):
            if o["estado"] == "recibida" and o["_aplicar_en"] is not None and m >= o["_aplicar_en"]:
                hubo = True
                exp = self.expediente(o["_exp"])
                u = self.ubicacion(exp, o["_n"])
                para = (u["decision"] or {}).get("juez_id")
                if o["_falla"]:
                    o["estado"] = "fallida"
                    o["finalizada_min"] = r2(m)
                    o["motivo"] = "El proveedor informó una falla al aplicar el bloqueo."
                    self.auditar("orden_fallida", "proveedor:" + o["proveedor"], o["_exp"], {"orden_id": o["orden_id"]})
                    nueva = self.reintentar(o, m)
                    texto = "%s informó una falla en el bloqueo de %s. " % (PROV[o["proveedor"]]["nombre"], o["objetivo"])
                    if nueva["estado"] == "espera_ratificacion":
                        texto += "El reintento espera la ratificación del juez entrante."
                    else:
                        texto += "Se reintentó solo (intento %d)." % nueva["intento"]
                    self.avisar("orden_fallida", texto, o["_exp"], para, clave="falla:" + o["proveedor"])
                else:
                    o["estado"] = "aplicada"
                    o["aplicada_min"] = r2(m)
                    self.auditar("orden_aplicada", "proveedor:" + o["proveedor"], o["_exp"], {"orden_id": o["orden_id"]})
                    if o["origen"] == "reintento":
                        texto = "El reintento en %s quedó aplicado: %s." % (PROV[o["proveedor"]]["nombre"], o["objetivo"])
                        self.avisar("reintento", texto, o["_exp"], para, clave="reintento:" + o["proveedor"])
                    if o["tipo"] == "ip":
                        self.programar_reclamos(o, m)
            elif o["estado"] == "aplicada" and m >= o["vence_min"]:
                o["estado"] = "vencida"
                o["finalizada_min"] = float(o["vence_min"])
                self.auditar("orden_vencida", "sistema", o["_exp"], {"orden_id": o["orden_id"]})
                hubo = True
        return hubo

    def reintentar(self, o: Dict[str, Any], m: float) -> Dict[str, Any]:
        exp = self.expediente(o["_exp"])
        u = self.ubicacion(exp, o["_n"])
        firmante = o["juez_id"]
        if not self.puede_firmar(firmante, m)[0]:
            t = self.traspasos[-1] if self.traspasos else None
            if t and t["ratificado"]:
                firmante = t["ratificado"]["juez_id"]
        nueva = self.crear_orden(exp, u, o["proveedor"], o["tipo"], o["objetivo"], firmante, o["_sello"],
                                 "reintento", m, reemplaza=o["orden_id"], intento=o["intento"] + 1)
        self.auditar("orden_reintentada", "sistema", o["_exp"], {"orden_id": nueva["orden_id"], "reemplaza": o["orden_id"]})
        return nueva

    # -- decisiones ---------------------------------------------------------
    def decidir(self, juez_id: str, exp: Dict[str, Any], u: Dict[str, Any], aprobar: bool, alcance: Optional[str],
                forzar: Optional[Dict[str, str]], motivo_rechazo: Optional[str], tipo: str = "firma",
                entrada_habilita: Optional[int] = None) -> None:
        m = self.minuto()
        actor = "juez:" + juez_id  # como el motor: la ampliación también la firma el juez que respalda la dinámica
        datos = {"ubicacion": u["n"], "huella": u["huella"], "decision": "APROBAR" if aprobar else "RECHAZAR",
                 "alcance": alcance, "forzado": forzar, "motivo_rechazo": motivo_rechazo, "juez_id": juez_id}
        if entrada_habilita:
            datos["habilita"] = entrada_habilita
        datos["orden_marco"] = self.ref_marco(juez_id)
        entrada = self.auditar("decision_juez" if tipo == "firma" else "ampliacion_dinamica", actor, exp["id"], datos)
        sello = sha("MARCA-PERSONAL-SELLO-v1|" + u["huella"] + "|" + entrada["hash"])[:32]
        ya_cubiertos: List[Dict[str, str]] = []
        aplicada = None
        if aprobar:
            tipo_bloqueo = forzar["tipo"] if forzar else u["propuesta"]["tipo"]
            aplicada = u["propuesta"]
            if forzar:
                aplicada = self.proponer(tipo_bloqueo, u["host"], u["ip"], u["colateral"]["propios"],
                                         u["propuesta"]["fundamento"])
            objetivos = aplicada["objetivos_por_proveedor"]
            for prov_id, lista in objetivos.items():
                for ob in lista:
                    if self.objetivo_activo(prov_id, ob["tipo"], ob["objetivo"]):
                        ya_cubiertos.append({"proveedor": prov_id, "tipo": ob["tipo"], "objetivo": ob["objetivo"]})
                        continue
                    self.crear_orden(exp, u, prov_id, ob["tipo"], ob["objetivo"], juez_id, sello, "decision", m,
                                     prefijo="amp" if tipo == "ampliacion_dinamica" else "ord")
            u["estado"] = "aprobada"
            if alcance == "filtracion" and tipo == "firma" and exp["filtracion"].get("sesion"):
                d = exp["dinamica"]
                if d and d["activa"]:
                    if u["_marca"] not in d["marcas"]:
                        d["marcas"].append(u["_marca"])
                    d["respaldada_por"] = juez_id
                    if d["requiere_ratificacion"]:  # textos-3: «Firmar y seguir» ratifica el seguimiento heredado
                        d["ratificaciones"].append({"juez_id": juez_id, "nombre": JUECES[juez_id]["nombre"],
                                                    "min": r2(m), "entrada": entrada["n"]})
                        # NV4: el traspaso pendiente lo registra; la tarjeta «Recibe el turno» ya no lo ofrece.
                        tp = self.traspaso_pendiente()
                        if tp is not None:
                            tp.setdefault("ratificadas_al_firmar", []).append(
                                {"id": exp["id"], "min": r2(m), "juez_id": juez_id, "nombre": JUECES[juez_id]["nombre"]})
                            tp["dinamicas_ratificadas"] = list(tp.get("dinamicas_ratificadas") or []) + [exp["id"]]
                    d["requiere_ratificacion"] = False
                else:
                    exp["dinamica"] = {"activa": True, "marcas": [u["_marca"]],
                                       "otorgada_por": {"juez_id": juez_id, "nombre": JUECES[juez_id]["nombre"]},
                                       "otorgada_min": r2(m), "entrada": entrada["n"], "respaldada_por": juez_id,
                                       "requiere_ratificacion": False, "ratificaciones": [], "revocada": None}
                self.auditar("orden_dinamica_otorgada", actor, exp["id"], {"marcas": exp["dinamica"]["marcas"],
                                                                           "entrada": entrada["n"]})
            if exp["corte_en_origen"] is None and u["senal"]["sesion"]:
                exp["corte_en_origen"] = {"min": r2(m), "sesion": u["senal"]["sesion"],
                                          "texto": "Se avisó al titular para que corte la sesión %s en su plataforma "
                                                   "(simulado: el simulador no tiene esa API)." % u["senal"]["sesion"]}
                self.auditar("aviso_corte_en_origen", "sistema", exp["id"], {"sesion": u["senal"]["sesion"]})
        else:
            u["estado"] = "rechazada"
        u["decision"] = {"tipo": tipo, "aprobada": aprobar, "juez_id": juez_id, "juez": JUECES[juez_id]["nombre"],
                         "juzgado_id": JUECES[juez_id]["juzgado_id"], "juzgado": JUECES_JUZGADO(juez_id),
                         "min": r2(m), "utc": entrada["utc"], "alcance": alcance, "forzado": forzar,
                         "motivo_rechazo": motivo_rechazo, "sello": sello, "entrada": entrada["n"],
                         "ya_cubiertos": ya_cubiertos, "orden_marco": datos["orden_marco"]}
        if aprobar:
            u["decision"]["propuesta_aplicada"] = aplicada
        if tipo == "ampliacion_dinamica":
            # Campo que el motor agrega: el seguimiento (otorgado o ratificado) que habilita esta ampliación.
            d = exp["dinamica"]
            otorgada = dict(d["otorgada_por"], min=d["otorgada_min"], entrada=d["entrada"])
            ratificada = dict(d["ratificaciones"][-1]) if d["ratificaciones"] else None
            hab = ratificada or otorgada
            u["decision"]["bajo_orden_de"] = {"juez_id": hab["juez_id"], "nombre": hab["nombre"],
                                              "entrada": hab["entrada"], "min": hab["min"],
                                              "otorgada_por": otorgada, "ratificada_por": ratificada}
            u["decision"]["otorgada_por"] = otorgada
            u["decision"]["ratificada_por"] = ratificada
            # C7: una sola leyenda (como `marco.texto_ampliacion`); cita la orden marco del juez con cuya clave salió
            # la ampliación (la de `decision.orden_marco`), no la de quien otorgó el seguimiento.
            om = self.marco_vigente(juez_id)
            if om:
                texto = "Ampliación automática del sistema bajo la orden marco %s de %s (minuto %s)" % (
                    om["id"], JUECES[om["juez_id"]]["nombre"], min_txt(om["min"]))
                if ratificada and ratificada["juez_id"] == juez_id:
                    texto += ", que en el minuto %s ratificó el seguimiento otorgado por %s (minuto %s)." % (
                        min_txt(ratificada["min"]), otorgada["nombre"], min_txt(otorgada["min"]))
                else:
                    texto += " y el seguimiento que otorgó en el minuto %s." % min_txt(otorgada["min"])
            else:
                texto = "Ampliación automática del sistema bajo el seguimiento otorgado por %s en el minuto %s" % (
                    otorgada["nombre"], min_txt(otorgada["min"]))
                if ratificada:
                    texto += ", ratificado por %s en el minuto %s" % (ratificada["nombre"], min_txt(ratificada["min"]))
                texto += "."
            u["decision"]["texto"] = texto + " No se firmó en persona."
        u["_automatica"] = {"posible": tipo == "ampliacion_dinamica", "motivo": None}

    def revisar_ampliaciones(self, m: float) -> bool:
        hubo = False
        for exp in self.expedientes:
            for u in exp["ubicaciones"]:
                if u["estado"] != "pendiente":
                    continue
                if not u["continuidad"]:
                    # Como el motor: la primera ubicación también trae el motivo (la pantalla decide si lo muestra).
                    if exp["dinamica"] is None and u["_automatica"].get("motivo") is None:
                        u["_automatica"] = {"posible": False,
                                            "motivo": "es el primer servidor de esta filtración: lo decide el juez."}
                        hubo = True
                    continue
                if u.get("_por_ausencia") or u.get("rechazo_previo"):  # C22: lo rechazado no entra solo
                    continue  # ya quedó para firma en persona (el motivo no se reescribe)
                motivo = self.motivo_no_ampliar(exp, u, m)
                if motivo is None:
                    d = exp["dinamica"]
                    juez = d["respaldada_por"]
                    habilita = d["ratificaciones"][-1]["entrada"] if d["ratificaciones"] else d["entrada"]
                    self.decidir(juez, exp, u, True, "filtracion", None, None, tipo="ampliacion_dinamica",
                                 entrada_habilita=habilita)
                    texto = ("La filtración de %s se mudó a %s (%s). Se bloqueó sola bajo el seguimiento que usted "
                             "autorizó; puede frenarlo." % (exp["titulo"], u["host"], u["ip"]))
                    a = self.avisar("ampliacion_dinamica", texto, exp["id"], juez,
                                    clave="ampliacion:%s:%d" % (exp["id"], u["n"]))
                    a["ubicacion"] = u["n"]
                    hubo = True
                elif u["_automatica"].get("motivo") != motivo:
                    u["_automatica"] = {"posible": False, "motivo": motivo}
                    hubo = True
        return hubo

    def motivo_no_ampliar(self, exp, u, m) -> Optional[str]:
        """C6: textos llanos, en minúscula; la pantalla les antepone solo «No se amplió solo: »."""
        d = exp["dinamica"]
        if not self.dinamica_habilitada:
            return "la plataforma corre con el seguimiento deshabilitado."
        if m >= PARTIDO["fin_min"]:
            return "el partido terminó."
        if u.get("reabierta"):
            return "este mismo servidor ya se había bloqueado solo y ese bloqueo se levantó: lo decide el juez."
        if d is None:
            return "el servidor anterior se firmó “solo este servidor”, sin seguimiento."
        if not d["activa"]:
            return "el seguimiento de esta filtración se frenó en el minuto %s." % min_txt((d["revocada"] or {}).get("min"))
        if d["requiere_ratificacion"]:
            return "el seguimiento espera que el juez entrante lo ratifique."
        if u["continuidad"]["criterio"] != "misma_marca" or u["_marca"] not in d["marcas"]:
            return "esta ubicación lleva otra marca de agua: la decide el juez."
        if not u["colateral"]["limpia"]:
            return "la evidencia nueva no está completa: la decide el juez."
        quien = d["respaldada_por"]
        if not self.con_seguimiento(quien):
            return "su orden marco no autoriza el seguimiento."
        ok, motivo = self.puede_firmar(quien, m)
        if not ok:
            return "quien respalda el seguimiento no puede firmar ahora: " + (motivo or "").lower()
        if not self.activo(quien):
            h = self.hace_s(quien)
            # Una mudanza que no se amplió por ausencia queda para firma en persona, aunque el juez vuelva.
            u["_por_ausencia"] = True
            return "%s no tenía la plataforma abierta (sin actividad hace %s s)." % (
                JUECES[quien]["nombre"], "más de %d" % PRESENCIA_S if h is None else "%d" % int(h))
        return None

    # -- reclamos -----------------------------------------------------------
    def programar_reclamos(self, o: Dict[str, Any], m: float) -> None:
        for dominio in DNS_IP.get(o["objetivo"], []):
            if dominio in RECLAMOS_AUTO and dominio not in self.reclamos_hechos:
                self.reclamos_hechos.add(dominio)
                demora, mensaje = RECLAMOS_AUTO[dominio]
                # El mismo sitio reclama varias veces y por varios proveedores (como en el simulador oficial).
                for i in range(REPETICIONES_RECLAMO.get(dominio, 1)):
                    prov = PROVEEDORES[(PROVEEDORES.index(PROV[o["proveedor"]]) + i) % len(PROVEEDORES)]["id"]
                    self.reclamos_programados.append({"min": m + demora + 0.5 * i, "dominio": dominio,
                                                      "proveedor": prov, "mensaje": mensaje})

    def causantes(self, dominio: str) -> List[Dict[str, Any]]:
        ips = DNS_DOMINIO.get(dominio, [])
        return [o for o in self.ordenes if o["estado"] in ("recibida", "aplicada")
                and ((o["tipo"] == "ip" and o["objetivo"] in ips) or (o["tipo"] == "dominio" and o["objetivo"] == dominio))]

    def revisar_reclamos(self, m: float) -> bool:
        hubo = False
        for p in list(self.reclamos_programados):
            if m < p["min"]:
                continue
            self.reclamos_programados.remove(p)
            hubo = True
            rid = "R-%03d" % (len(self.reclamos) + 1)
            dominio = p["dominio"]
            ips = DNS_DOMINIO.get(dominio, [])
            causas = self.causantes(dominio)
            if not causas:  # mismo orden que el motor: sin bloqueo que lo afecte, se cierra solo
                clase = "sin_bloqueo"
            elif any(cubre(d, dominio) for lic in LICENCIATARIOS for d in lic["dominios_autorizados"]):
                clase = "licenciatario"
            elif self.visto_pirata(dominio):
                clase = "operacion_pirata"  # C14: un nombre observado
            else:
                clase = "legitimo"  # C14: también el que solo se infirió (verificacion.inferido)
            r = {"id": rid, "minuto": r3(p["min"]), "dominio": dominio, "proveedor": p["proveedor"],
                 "proveedor_nombre": PROV[p["proveedor"]]["nombre"], "mensaje": p["mensaje"],
                 "estado": "pendiente", "asignado_a": (self.de_turno(m) or [None])[0],
                 "verificacion": None, "propuesta": None, "resolucion": None}
            self.auditar("reclamo_recibido", "proveedor:" + p["proveedor"], None, {"reclamo": rid, "dominio": dominio})
            r["verificacion"], r["propuesta"] = self.verificar_reclamo(dominio, ips, causas, clase)
            self.auditar("reclamo_verificado", "sistema", None, {"reclamo": rid, "clase": clase,
                                                                 "causantes": [o["orden_id"] for o in causas]})
            if clase == "sin_bloqueo":
                r["estado"] = "cerrado"
                r["resolucion"] = {"accion": "cerrar", "juez_id": None, "juez": None, "min": r2(m),
                                   "fundamento": "No hay bloqueos activos que afecten a este dominio.",
                                   "minutos_hasta_resolver": 0.0, "por_reclamo": None}
            self.reclamos.append(r)
            if r["estado"] == "pendiente":
                texto = "Reclamo de %s: %s" % (dominio, r["verificacion"]["explicacion"])
                self.avisar("reclamo", texto, None, r["asignado_a"], clave="reclamo:" + dominio)
        return hubo

    def visto_pirata(self, dominio: str) -> Optional[Tuple[str, float]]:
        """C14: ("transmitiendo"|"publicando", minuto) si la plataforma vio ese nombre como stream o como página
        (la página solo si comparte el registrable con el stream)."""
        for e in self.expedientes:
            for u in e["ubicaciones"]:
                if u["host"] == dominio:
                    return "transmitiendo", u["primera_deteccion_min"]
                pagina = host_de(u.get("pagina") or e.get("pagina") or "")
                if pagina == dominio and registrable(pagina) == registrable(u["host"]):
                    return "publicando", u["primera_deteccion_min"]
        return None

    def inferido(self, dominio: str, causas) -> Optional[str]:
        """C14: el registrable del stream si el nombre se tomó como propio sin verlo (mismo registrable que el stream
        de una ubicación causante cuya página está en ese registrable)."""
        for o in causas:
            e = self.expediente(o["_exp"])
            u = self.ubicacion(e, o["_n"])
            r = registrable(u["host"])
            pagina = host_de(u.get("pagina") or e.get("pagina") or "")
            if registrable(dominio) == r and pagina and registrable(pagina) == r:
                return r
        return None

    def verificar_reclamo(self, dominio, ips, causas, clase):
        ordenes = []
        for o in causas:
            ordenes.append({"orden_id": o["orden_id"], "proveedor": o["proveedor"], "tipo": o["tipo"],
                            "objetivo": o["objetivo"], "exp": o["_exp"], "n": o["_n"]})
        exps = sorted({o["_exp"] for o in causas})
        hosts = sorted({self.ubicacion(self.expediente(o["_exp"]), o["_n"])["host"] for o in causas})
        inferido = self.inferido(dominio, causas) if clase == "legitimo" else None
        visto = self.visto_pirata(dominio) if clase == "operacion_pirata" else None
        if inferido:
            expl = ("La plataforma lo había tomado como parte del sitio pirata porque comparte el servidor y el dominio "
                    "%s, pero nunca lo vio transmitir ni publicar el partido. El reclamo corrige esa inferencia." % inferido)
        elif visto:
            expl = ("Es el mismo nombre que la plataforma vio %s el partido en el minuto %s: el reclamo no es fundado."
                    % (visto[0], min_txt(visto[1])))
        elif clase == "legitimo":
            expl = ("%s resuelve a %s, la misma IP que se bloqueó en %s (%s). No tiene relación con el pirata: "
                    "el reclamo es legítimo." % (dominio, ", ".join(ips), ", ".join(exps), ", ".join(hosts)))
        elif clase == "licenciatario":
            expl = "%s es un dominio autorizado del licenciatario: no debe quedar bloqueado." % dominio
        elif clase == "operacion_pirata":
            expl = "%s forma parte de la operación pirata del mismo sitio: el bloqueo es correcto." % dominio
        else:
            expl = "No hay bloqueos activos que afecten a %s." % dominio
        verificacion = {"ips": ips, "clase_reclamante": clase, "ordenes_causantes": ordenes, "explicacion": expl}
        if inferido:
            verificacion["inferido"] = True
        if clase in ("legitimo", "licenciatario") and causas:
            levantar = [{"orden_id": o["orden_id"], "proveedor": o["proveedor"]} for o in causas]
            reemplazo = []
            if any(o["tipo"] == "ip" for o in causas):
                for o in causas:
                    if o["tipo"] != "ip":
                        continue
                    host = self.ubicacion(self.expediente(o["_exp"]), o["_n"])["host"]
                    for p in PROVEEDORES:
                        item = {"proveedor": p["id"], "tipo": "dominio", "objetivo": host, "exp": o["_exp"], "n": o["_n"]}
                        if "dominio" in p["capacidades"] and item not in reemplazo \
                                and not self.objetivo_activo(p["id"], "dominio", host):
                            reemplazo.append(item)
                accion = "levantar_y_reemplazar"
                provs = ", ".join(PROV[x["proveedor"]]["nombre"].split(" (")[0] for x in reemplazo) or "ningún proveedor nuevo"
                n_ip = sum(1 for o in causas if o["tipo"] == "ip")
                n_nom = len(causas) - n_ip  # C14: con un inferido, también la orden por su nombre
                cuantos = ("los %d bloqueos por IP" % n_ip if n_ip > 1 else "el bloqueo por IP") + (
                    (" y los %d por nombre" % n_nom if n_nom > 1 else " y el bloqueo por nombre") if n_nom else "")
                expl = ("Levantar %s y bloquear solo el nombre del stream (%s) en %s. "
                        "El stream sigue bloqueado y %s vuelve a funcionar." % (
                            cuantos, ", ".join(hosts), provs, dominio))
            else:
                accion = "levantar"
                reemplazo = []
                expl = "Levantar el bloqueo por nombre de %s, sin reemplazo." % dominio
            return verificacion, {"accion": accion, "levantar": levantar, "reemplazo": reemplazo, "explicacion": expl}
        if clase == "operacion_pirata":
            return verificacion, {"accion": "desestimar", "levantar": [], "reemplazo": [],
                                  "explicacion": "Desestimar el reclamo: el dominio es parte de la operación pirata."}
        return verificacion, {"accion": "cerrar", "levantar": [], "reemplazo": [],
                              "explicacion": "No hay bloqueos que levantar."}

    def resolver_reclamo(self, juez_id: str, r: Dict[str, Any], accion: str, fundamento: Optional[str]) -> None:
        m = self.minuto()
        entrada = self.auditar("reclamo_resuelto", "juez:" + juez_id, None,
                               {"reclamo": r["id"], "accion": accion, "fundamento": fundamento})
        sello = sha("MARCA-PERSONAL-SELLO-v1|" + sha(r["id"]) + "|" + entrada["hash"])[:32]
        creadas: List[str] = []
        if accion in ("levantar_y_reemplazar", "levantar"):
            motivo = "Reclamo %s de %s: %s" % (r["id"], r["dominio"], fundamento or "levantamiento por daño colateral.")
            for item in r["propuesta"]["levantar"]:
                o = next((x for x in self.ordenes if x["orden_id"] == item["orden_id"]), None)
                if o and o["estado"] in ACTIVAS + ("espera_ratificacion",):
                    self.levantar_orden(o, juez_id, motivo, m, r["id"])
            if accion == "levantar_y_reemplazar":
                for item in r["propuesta"]["reemplazo"]:
                    causa = r["verificacion"]["ordenes_causantes"][0]
                    exp = self.expediente(causa["exp"])
                    u = next((x for x in exp["ubicaciones"] if x["host"] == item["objetivo"]), None) \
                        or self.ubicacion(exp, causa["n"])
                    if not self.objetivo_activo(item["proveedor"], "dominio", item["objetivo"]):
                        creadas.append(self.crear_orden(exp, u, item["proveedor"], "dominio", item["objetivo"], juez_id,
                                                        sello, "reemplazo_reclamo", m, reclamo=r["id"])["orden_id"])
            r["estado"] = "resuelto"
            if (r.get("verificacion") or {}).get("inferido"):
                self.recalcular_pendientes(r, m)
        else:
            r["estado"] = "desestimado"
        r["resolucion"] = {"accion": accion, "juez_id": juez_id, "juez": JUECES[juez_id]["nombre"], "min": r2(m),
                           "fundamento": fundamento, "minutos_hasta_resolver": r2(m - r["minuto"]), "por_reclamo": None,
                           "ordenes_reemplazo": creadas, "entrada": entrada["n"]}
        for otro in self.reclamos:
            if otro["estado"] == "pendiente" and not self.causantes(otro["dominio"]):
                otro["estado"] = "cerrado"
                otro["resolucion"] = {"accion": "cerrar", "juez_id": None, "juez": None, "min": r2(m),
                                      "fundamento": "Quedó sin bloqueos activos al resolverse %s." % r["id"],
                                      "minutos_hasta_resolver": r2(m - otro["minuto"]), "por_reclamo": r["id"]}
        # C3: los avisos de reclamo se cierran solos, con lo que pasó de verdad.
        hecho = {"levantar_y_reemplazar": "levantó el bloqueo y lo reemplazó por dominio.",
                 "levantar": "levantó el bloqueo.", "desestimar": "desestimó el reclamo."}[accion]
        for a in self.avisos:
            if a["tipo"] != "reclamo" or a.get("atendido"):
                continue
            dominio = (a.get("clave") or "").split(":", 1)[-1]
            if any(x["estado"] == "pendiente" and x["dominio"] == dominio for x in self.reclamos):
                continue
            if dominio == r["dominio"]:
                quien = "" if a.get("para") in (None, juez_id) else JUECES[juez_id]["nombre"] + " "
                texto = "Resuelto en el minuto %s: %s%s" % (min_txt(r2(m)), quien, hecho)
            else:
                texto = "Resuelto en el minuto %s: quedó sin bloqueos activos al resolverse %s." % (min_txt(r2(m)), r["id"])
            self.cerrar_aviso(a, texto, m)

    def recalcular_pendientes(self, r: Dict[str, Any], m: float) -> None:
        """Ola C (6): refutada la inferencia, los pedidos del mismo registrable que esperan firma ya no se proponen
        por IP sino por nombre; la ubicación guarda `recalculada` para que la tarjeta lo diga."""
        reg = registrable(r["dominio"])
        for exp in self.expedientes:
            for u in exp["ubicaciones"]:
                prop = u.get("propuesta") or {}
                if u["estado"] != "pendiente" or prop.get("tipo") != "ip" or registrable(u["host"]) != reg:
                    continue
                fund = (prop.get("fundamento") or "").replace(
                    "Bloqueo por IP: el servidor es exclusivo del sitio pirata.",
                    "Bloqueo por nombre: el reclamo %s mostró que no todo %s es del sitio pirata." % (r["id"], reg))
                u["propuesta"] = self.proponer("dominio", u["host"], u["ip"], u["colateral"]["propios"], fund)
                u["recalculada"] = {"reclamo": r["id"], "registrable": reg, "min": r2(m), "tipo_antes": "ip",
                                    "tipo": "dominio"}

    def levantar_orden(self, o, juez_id, motivo, m, reclamo=None) -> None:
        o["estado"] = "levantada"
        o["finalizada_min"] = r2(m)
        o["motivo"] = motivo
        o["levantamiento"] = {"min": r2(m), "juez": juez_id, "juez_nombre": JUECES[juez_id]["nombre"], "motivo": motivo,
                              "reclamo": reclamo}
        self.auditar("orden_levantada", "juez:" + juez_id, o["_exp"], {"orden_id": o["orden_id"], "motivo": motivo})

    def quien_necesita(self, o: Dict[str, Any], levantando: set) -> Optional[str]:
        """turnos-2: otra ubicación aprobada que no se está levantando y se apoya en esta orden (la tenía en sus
        `ya_cubiertos` al firmarse). Si existe, la orden no se levanta: esa ubicación quedaría sin bloqueo."""
        for exp in self.expedientes:
            for v in exp["ubicaciones"]:
                if (exp["id"], v["n"]) in levantando or v["estado"] != "aprobada":
                    continue
                d = v.get("decision") or {}
                if any(x["proveedor"] == o["proveedor"] and x["tipo"] == o["tipo"] and x["objetivo"] == o["objetivo"]
                       for x in d.get("ya_cubiertos") or []):
                    return "%s ubicación %d (%s)" % (exp["id"], v["n"], d.get("juez") or "")
        return None

    def levantar_salvo_necesarias(self, ordenes, levantando: set, juez_id: str, motivo: str, m: float):
        """turnos-2: levanta las órdenes que nadie más necesita; devuelve (levantadas, avisos de las que se mantienen)."""
        hechas, mantenidas = 0, []
        for o in ordenes:
            quien = self.quien_necesita(o, levantando)
            if quien:
                mantenidas.append("Se mantiene el bloqueo %s %s en %s porque también cubre %s." % (
                    "por IP" if o["tipo"] == "ip" else "por dominio", o["objetivo"], o["proveedor_nombre"], quien))
                continue
            self.levantar_orden(o, juez_id, motivo, m)
            hechas += 1
        return hechas, mantenidas

    # -- final --------------------------------------------------------------
    def revisar_final(self, m: float) -> bool:
        hubo = False
        if m >= PARTIDO["fin_min"] and not self.finalizado_anotado:
            self.finalizado_anotado = True
            self.auditar("partido_finalizado", "sistema", None, {"min": PARTIDO["fin_min"]})
            self.avisar("alerta", "Terminó el partido. No sale ninguna orden más; los bloqueos vencen ahora.", None, None)
            hubo = True
        if m >= PARTIDO["fin_min"]:
            # Adenda 3, B: lo que quedó pendiente pasa a «sin_decidir» (terminal), sin ninguna orden.
            for exp in self.expedientes:
                for u in exp["ubicaciones"]:
                    if u["estado"] != "pendiente":
                        continue
                    x = PARTIDO["fin_min"] - u["primera_deteccion_min"]
                    u["estado"] = "sin_decidir"
                    u["motivo_sin_decidir"] = ("El partido terminó a los %s min de la detección: ya no se pueden firmar órdenes."
                                               % ("%.1f" % x).replace(".", ","))
                    u["sin_decidir_min"] = r3(m)
                    self.auditar("ubicacion_sin_decidir", "sistema", exp["id"],
                                 {"expediente": exp["id"], "ubicacion": u["n"], "motivo": "partido_terminado",
                                  "primera_deteccion_min": u["primera_deteccion_min"]})
                    hubo = True
        if m >= PARTIDO["fin_min"] + 5 and not self.cerrado_anotado:
            self.cerrado_anotado = True
            ip_activas = [o["orden_id"] for o in self.ordenes if o["tipo"] == "ip" and o["estado"] in ACTIVAS]
            self.auditar("vencimiento_verificado", "sistema", None, {"bloqueos_ip_activos": ip_activas})
            ent = self.auditar("exportacion", "sistema", None, {"destino": "(simulado)"})
            # Contrato: la huella del paquete exportado (lo que se publica para que la entrega no cambie después).
            self.paquete = {"huella": sha({"auditoria": ent["hash"], "partido": PARTIDO["id"]}), "exportado_min": r2(m)}
            self.avisar("alerta", "Cierre verificado: no queda ningún bloqueo por IP activo." if not ip_activas
                        else "Atención: quedan bloqueos por IP activos después del partido.", None, None)
            hubo = True
        return hubo

    # -- juez automático (solo con --auto) ----------------------------------
    def juez_automatico(self, m: float) -> bool:
        hubo = False
        de_turno = self.de_turno(m)
        if not de_turno:
            return False
        juez = de_turno[0]
        if not self.puede_firmar(juez, m)[0]:
            return False
        if self.marco_vigente(juez) is None:
            self.firmar_marco(juez, self.dinamica_habilitada)  # como el juez automático del motor (ronda 2b)
            return True
        t = self.traspaso_pendiente()
        if t and m >= t["min"] + 0.6:
            self.ratificar(juez)
            return True
        for exp in self.expedientes:
            for u in exp["ubicaciones"]:
                if u["estado"] == "pendiente" and u["asignada_a"] == juez and m - u["armado_min"] >= 0.8:
                    if t and u["_automatica"].get("motivo"):
                        continue
                    forzar = None
                    if u["host"] == "tv.verpartido-hd.test":
                        forzar = {"tipo": "ip", "fundamento": "Ensayo: bloqueo por IP forzado para provocar un reclamo."}
                    if u["vista_min"] is None:
                        u["vista_min"] = r3(m)
                    # C4: el servidor que volvió después de «frenar y levantar» se firma solo para él.
                    alcance = "filtracion" if self.dinamica_habilitada and not u.get("reabierta") else "ubicacion"
                    self.decidir(juez, exp, u, True, alcance, forzar, None)
                    hubo = True
        for r in self.reclamos:
            if r["estado"] == "pendiente" and m - r["minuto"] >= 1.2 and r["propuesta"]:
                fund = "Ensayo: desestimado." if r["propuesta"]["accion"] == "desestimar" else None
                self.resolver_reclamo(juez, r, r["propuesta"]["accion"], fund)
                hubo = True
        return hubo

    def ratificar(self, juez_id: str, dinamicas: Optional[List[str]] = None) -> Optional[str]:
        """Ronda 2b, sección 6: siempre libera lo que quedó en espera; de las dinámicas heredadas ratifica solo las
        de `dinamicas` (None = todas) y solo con orden marco con seguimiento. Devuelve un aviso o None."""
        m = self.minuto()
        t = self.traspaso_pendiente()
        esperan = [exp for exp in self.expedientes
                   if exp["dinamica"] and exp["dinamica"]["activa"] and exp["dinamica"]["requiere_ratificacion"]]
        if t is None and not esperan:
            raise ErrorApi(409, "conflicto", "No hay nada heredado para ratificar.")
        pedidas = [x for x in esperan if dinamicas is None or x["id"] in dinamicas]
        aviso = None
        if pedidas and not self.con_seguimiento(juez_id):
            aviso = ("Recibió el turno, pero los seguimientos siguen esperando: para ratificarlos, firme antes la "
                     "orden marco con el seguimiento autorizado.")
            pedidas = []
        e = self.auditar("traspaso_ratificado", "juez:" + juez_id, None, {
            "traspaso_min": t["min"] if t else None, "dinamicas": [x["id"] for x in pedidas]})
        for exp in pedidas:
            d = exp["dinamica"]
            d["requiere_ratificacion"] = False
            d["respaldada_por"] = juez_id
            d["ratificaciones"].append({"juez_id": juez_id, "nombre": JUECES[juez_id]["nombre"], "min": r2(m),
                                        "entrada": e["n"]})
        if t is not None:
            t["resumen"] = self.resumen_traspaso()
            t["ratificado"] = {"juez_id": juez_id, "nombre": JUECES[juez_id]["nombre"], "min": r2(m), "entrada": e["n"]}
            # Propuesta (no está en el contrato): qué dinámicas ratificó y cuáles quedaron esperando.
            t["dinamicas_ratificadas"] = list(t.get("dinamicas_ratificadas") or []) + [x["id"] for x in pedidas]
            t["dinamicas_sin_ratificar"] = [x["id"] for x in esperan if x not in pedidas]
            # NV7, como el motor: la respuesta dice qué se ratificó y qué quedó esperando.
            self.ultimo_ratificar = {"ratificadas": [x["id"] for x in pedidas],
                                     "sin_ratificar": [x["id"] for x in esperan if x not in pedidas]}
            for o in self.ordenes:
                if o["estado"] == "espera_ratificacion":
                    o["juez_id"] = juez_id
                    o["juzgado_id"] = JUECES[juez_id]["juzgado_id"]
                    self.enviar(o, m)
            # C8: «Recibió el turno en el minuto X: ratificó N de M seguimientos heredados.»
            total = len(esperan)
            if total == 0:
                texto = "Recibió el turno en el minuto %s." % min_txt(r2(m))
            elif not pedidas:
                texto = "Recibió el turno en el minuto %s: no ratificó ningún seguimiento heredado." % min_txt(r2(m))
            elif total == 1:
                texto = "Recibió el turno en el minuto %s: ratificó el seguimiento heredado." % min_txt(r2(m))
            else:
                texto = "Recibió el turno en el minuto %s: ratificó %d de %d seguimientos heredados." % (
                    min_txt(r2(m)), len(pedidas), total)
            self.cerrar_avisos(lambda a: a["tipo"] == "traspaso" and a.get("clave") == "traspaso:%s" % t["min"],
                               texto, m)
            self.avisar("traspaso", "%s: %s" % (JUECES[juez_id]["nombre"], texto[0].lower() + texto[1:]), None, None,
                        clave="traspaso:recibido:%s" % t["min"])
        elif pedidas:
            self.avisar("traspaso", "%s ratificó %s en el minuto %s." % (
                JUECES[juez_id]["nombre"], "el seguimiento heredado" if len(pedidas) == 1
                else "%d seguimientos heredados" % len(pedidas), min_txt(r2(m))), None, None)
        return aviso

    def revocar(self, juez_id: str, exp: Dict[str, Any], motivo: str, levantar: bool) -> int:
        """Ronda 2b, sección 6: frena las próximas mudanzas; con `levantar`, levanta lo que se amplió solo."""
        m = self.minuto()
        d = exp["dinamica"]
        if not d or not d["activa"]:
            raise ErrorApi(404, "no_encontrado", "Esa filtración no tiene un seguimiento activo.")
        ent = self.auditar("dinamica_revocada", "juez:" + juez_id, exp["id"],
                           {"juez_id": juez_id, "motivo": motivo, "levantar": bool(levantar)})
        d["activa"] = False
        d["revocada"] = {"juez_id": juez_id, "nombre": JUECES[juez_id]["nombre"], "min": r2(m), "motivo": motivo,
                         "entrada": ent["n"], "levantar": bool(levantar)}
        n = 0
        mantenidas: List[str] = []
        if levantar:
            texto = "Se frenó el seguimiento%s" % (": " + motivo if motivo else ".")
            ampliadas = self.ampliadas_vigentes(exp)
            levantando = {(exp["id"], x["n"]) for x in ampliadas}
            for u in ampliadas:
                activas = [o for o in self.ordenes_de(exp["id"], u["n"]) if o["estado"] in ACTIVAS + ("espera_ratificacion",)]
                _, mant = self.levantar_salvo_necesarias(activas, levantando, juez_id, texto, m)
                mantenidas.extend(mant)
                # C4: la próxima detección de este servidor vuelve al juez como un pedido nuevo.
                u["levantada_por_freno"] = {"min": r2(m), "juez_id": juez_id, "juez": JUECES[juez_id]["nombre"],
                                            "entrada": ent["n"], "ampliada_min": (u["decision"] or {}).get("min")}
                n += 1
        # C3: los avisos de ampliación de esta filtración quedan atendidos.
        for a in self.avisos:
            if a["tipo"] != "ampliacion_dinamica" or a["exp"] != exp["id"] or a.get("atendido"):
                continue
            quien = "Usted" if a.get("para") == juez_id else JUECES[juez_id]["nombre"]
            levanto = levantar and any(u["n"] == a.get("ubicacion") and u.get("levantada_por_freno")
                                       for u in exp["ubicaciones"])
            self.cerrar_aviso(a, "%s frenó el seguimiento%s en el minuto %s." % (
                quien, " y levantó la ampliación" if levanto else "", min_txt(r2(m))), m)
        self.ultimo_aviso = " ".join(mantenidas) or None  # turnos-2: la API lo devuelve como `aviso`
        return n

    @staticmethod
    def levantada_entera(u: Dict[str, Any]) -> bool:
        """Una ubicación (vista, con sus `ordenes`) cuyo bloqueo aplicado se levantó entero (C12): ninguna orden
        activa y todas las aplicadas, levantadas."""
        ords = u.get("ordenes") or []
        aplicadas = [o for o in ords if o["aplicada_min"] is not None]
        return bool(aplicadas) and all(o["estado"] == "levantada" for o in aplicadas) \
            and not any(o["estado"] in ACTIVAS + ("espera_ratificacion",) for o in ords)

    def ampliadas_vigentes(self, exp: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [u for u in exp["ubicaciones"] if (u["decision"] or {}).get("tipo") == "ampliacion_dinamica"
                and any(o["estado"] in ACTIVAS + ("espera_ratificacion",) for o in self.ordenes_de(exp["id"], u["n"]))]

    # -- vistas -------------------------------------------------------------
    def reloj(self) -> Dict[str, Any]:
        m = self.minuto()
        return {"minuto": r2(m), "hora": self.hora(m), "fin_min": float(PARTIDO["fin_min"]),
                # C5: la hora de pared del minuto 0 y la del final (las pantallas calculan las horas desde acá).
                "hora_inicio": self.hora(0), "fin_hora": self.hora(PARTIDO["fin_min"])[:5],
                "finalizado": m >= PARTIDO["fin_min"], "cerrado": m >= PARTIDO["fin_min"] + 5,
                "acelerar": self.acelerar, "conexion": "ok",
                "partido": {"id": PARTIDO["id"], "nombre": PARTIDO["nombre"], "titular": PARTIDO["titular"]},
                "de_turno": [dict(juez_id=j, nombre=JUECES[j]["nombre"], juzgado_id=JUECES[j]["juzgado_id"],
                                  juzgado=JUECES_JUZGADO(j), desde_min=self.turno_de(j)["desde_min"],
                                  hasta_min=self.turno_de(j)["hasta_min"]) for j in self.de_turno(m)]}

    def yo(self, usuario: str) -> Dict[str, Any]:
        u = USUARIOS[usuario]
        if u["rol"] == "juez":
            j = u["juez_id"]
            base = {"usuario": usuario, "rol": "juez", "nombre": JUECES[j]["nombre"], "juez_id": j,
                    "juzgado_id": JUECES[j]["juzgado_id"], "juzgado": JUECES_JUZGADO(j)}
        else:
            base = {"usuario": usuario, "rol": u["rol"], "nombre": u["nombre"], "juez_id": None, "juzgado_id": None,
                    "juzgado": None}
        base.update(dinamica_habilitada=self.dinamica_habilitada, v=self.v, reloj=self.reloj())
        return base

    @staticmethod
    def vista_orden(o: Dict[str, Any]) -> Dict[str, Any]:
        v = {k: val for k, val in o.items() if not k.startswith("_")}
        v["no_enviada"] = bool(o.get("no_enviada"))  # como el motor; la simulada no reconcilia, siempre False
        return v

    def cobertura(self, exp, u, m) -> Dict[str, Any]:
        ords = self.ordenes_de(exp["id"], u["n"])
        ahora_aplicados = {o["proveedor"] for o in ords if o["estado"] == "aplicada"}
        primeras: Dict[str, float] = {}
        tramos: Dict[str, List[Tuple[float, float]]] = {}
        for o in ords:
            if o["aplicada_min"] is not None:
                p = o["proveedor"]
                primeras[p] = min(primeras.get(p, 1e9), o["aplicada_min"])
                tramos.setdefault(p, []).append((o["aplicada_min"], o["finalizada_min"] if o["finalizada_min"] is not None else 1e9))
        pd = u["primera_deteccion_min"]
        sig = [x["primera_deteccion_min"] for x in exp["ubicaciones"] if x["n"] == u["n"] + 1]
        fin = sig[0] if sig else min(m, PARTIDO["fin_min"])
        dur = fin - pd
        if dur > 0:
            visible = 0.0
            for p in PROVEEDORES:
                bloqueado = 0.0
                for a, b in sorted(tramos.get(p["id"], [])):
                    bloqueado += max(0.0, min(b, fin) - max(a, pd))
                visible += p["clientes"] * max(0.0, dur - min(bloqueado, dur))
            residual = round(visible / (CLIENTES_TOTAL * dur) * 100, 1)
        else:
            residual = None  # adenda 3, A: sin ventana no hay nada que medir
        return {"clientes_cubiertos_pct": round(sum(PROV[p]["clientes"] for p in ahora_aplicados) / CLIENTES_TOTAL * 100, 1),
                "proveedores_aplicados": len(ahora_aplicados), "proveedores_total": len(PROVEEDORES),
                "primer_bloqueo_min": r2(min(primeras.values()) - pd) if primeras else None,
                "completo_min": r2(max(primeras.values()) - pd) if len(primeras) == len(PROVEEDORES) else None,
                "visibilidad_residual_pct": residual, "sin_ventana": dur <= 0} if dur > 0 else {
                "clientes_cubiertos_pct": round(sum(PROV[p]["clientes"] for p in ahora_aplicados) / CLIENTES_TOTAL * 100, 1),
                "proveedores_aplicados": len(ahora_aplicados), "proveedores_total": len(PROVEEDORES),
                "primer_bloqueo_min": None, "completo_min": None, "visibilidad_residual_pct": None, "sin_ventana": True}

    def vista_ubicacion(self, exp, u, m) -> Dict[str, Any]:
        v = {k: val for k, val in u.items() if not k.startswith("_")}
        v["ordenes"] = [self.vista_orden(o) for o in self.ordenes_de(exp["id"], u["n"])]
        v["cobertura"] = self.cobertura(exp, u, m)
        v.setdefault("recalculada", None)  # como el motor: null si la propuesta no se rehízo
        return v

    def estado_expediente(self, exp, m) -> str:
        estados = [u["estado"] for u in exp["ubicaciones"]]
        if "pendiente" in estados:
            return "pendiente"
        if estados and all(s == "rechazada" for s in estados):
            return "rechazado"
        activas = any(o["estado"] in ACTIVAS + ("espera_ratificacion",) for o in self.ordenes if o["_exp"] == exp["id"])
        if m >= PARTIDO["fin_min"] or not activas:
            return "cerrado"
        return "activo"

    def vista_expediente(self, exp, m) -> Dict[str, Any]:
        v = {k: val for k, val in exp.items() if k != "ubicaciones"}
        v["estado"] = self.estado_expediente(exp, m)
        v["ubicaciones"] = [self.vista_ubicacion(exp, u, m) for u in exp["ubicaciones"]]
        return v

    def bandeja(self, usuario: str) -> Dict[str, Any]:
        m = self.minuto()
        yo = self.yo(usuario)
        j = yo["juez_id"]
        t = self.turno_de(j)
        de_turno = j in self.de_turno(m)
        puede, motivo = self.puede_firmar(j, m)
        turno = {"de_turno": de_turno, "desde_min": t["desde_min"], "hasta_min": t["hasta_min"],
                 "faltan_min": r2(t["hasta_min"] - m) if de_turno else None, "puede_firmar": puede,
                 "motivo": motivo, "proximo": {"desde_min": t["desde_min"], "faltan_min": r2(t["desde_min"] - m)}
                 if m < t["desde_min"] else None}
        historial = []
        for exp in self.expedientes:
            for u in exp["ubicaciones"]:
                if u["decision"] and u["decision"]["juez_id"] == j:
                    historial.append((u["decision"]["min"], exp, u))
                elif u["estado"] == "sin_decidir" and u.get("asignada_a") == j:
                    historial.append((u.get("sin_decidir_min") or PARTIDO["fin_min"], exp, u))
        historial.sort(key=lambda x: x[0], reverse=True)
        b = {"v": self.v, "reloj": yo["reloj"], "yo": yo, "turno": turno, "traspaso": None, "reclamos": [],
             "pendientes": [], "dinamicas": [], "avisos": [],
             "historial": [{"expediente": self.vista_expediente(e, m), "n": u["n"]} for _, e, u in historial[:30]],
             # Contrato: reclamos que este juez resolvió y traspasos que ratificó.
             "historial_reclamos": [{"id": r["id"], "dominio": r["dominio"], "proveedor_nombre": r["proveedor_nombre"],
                                     "minuto": r["minuto"], "resolucion": r["resolucion"],
                                     "cerrados_junto": [x["id"] for x in self.reclamos
                                                        if (x["resolucion"] or {}).get("por_reclamo") == r["id"]]}
                                    for r in reversed(self.reclamos) if (r["resolucion"] or {}).get("juez_id") == j],
             "historial_traspasos": [{"min": t["min"], "de": t["de"],
                                      "ratificado": {"min": t["ratificado"]["min"], "entrada": t["ratificado"]["entrada"]},
                                      "resumen": t["resumen"],
                                      "dinamicas_ratificadas": t.get("dinamicas_ratificadas"),
                                      "dinamicas_sin_ratificar": t.get("dinamicas_sin_ratificar")}
                                     for t in reversed(self.traspasos) if (t["ratificado"] or {}).get("juez_id") == j],
             # Contrato (ronda 2b, sección 1): la orden marco de este juez.
             "marco": self.vista_marco_juez(j, m),
             # Propuesta (no está en el contrato): nombres de los proveedores, para no mostrar ids en los pedidos.
             "proveedores": [{"id": p["id"], "nombre": p["nombre"], "capacidades": p["capacidades"]} for p in PROVEEDORES]}
        if not de_turno:
            return b
        tp = self.traspaso_pendiente()
        if tp and any(x["juez_id"] == j for x in tp["a"]):
            tv = {k: val for k, val in tp.items() if not k.startswith("_")}
            tv.setdefault("ratificadas_al_firmar", [])  # como el motor: lista vacía si no hubo
            tv["resumen"] = self.resumen_traspaso()
            b["traspaso"] = tv
        b["reclamos"] = [r for r in self.reclamos if r["estado"] == "pendiente" and r["asignado_a"] == j]
        cambios = False
        for exp in self.expedientes:
            for u in exp["ubicaciones"]:
                if u["estado"] == "pendiente" and u["asignada_a"] == j:
                    if u["vista_min"] is None:
                        u["vista_min"] = r3(m)
                        self.auditar("expediente_visto", "juez:" + j, exp["id"], {"ubicacion": u["n"]})
                        cambios = True
                    # C24: la ubicación más nueva del mismo expediente vista después de la última detección de esta.
                    nuevas = [v["n"] for v in exp["ubicaciones"]
                              if v["n"] != u["n"] and v["primera_deteccion_min"] > u["ultima_deteccion_min"]]
                    b["pendientes"].append({"expediente": self.vista_expediente(exp, m), "n": u["n"],
                                            "automatica": dict(u["_automatica"]),
                                            "superada_por": max(nuevas) if nuevas else None})
            d = exp["dinamica"]
            if d and d["activa"]:  # como el motor: todas las vigentes
                rat = d["ratificaciones"][-1] if d["ratificaciones"] else None
                b["dinamicas"].append({"exp": exp["id"], "titulo": exp["titulo"], "sesion": exp["filtracion"]["sesion"],
                                       "otorgada_min": d["otorgada_min"],
                                       "ubicaciones": sum(1 for u in exp["ubicaciones"] if u["estado"] == "aprobada"),
                                       "requiere_ratificacion": d["requiere_ratificacion"],
                                       "otorgada_por": dict(d["otorgada_por"], min=d["otorgada_min"], entrada=d["entrada"]),
                                       "ratificada_por": dict(rat) if rat else None,
                                       # Contrato (ronda 2b, sección 6): ubicaciones ampliadas solas todavía vigentes.
                                       "ampliaciones": len(self.ampliadas_vigentes(exp))})
        b["pendientes"].sort(key=lambda x: x["superada_por"] is not None)  # C24: los superados, al final (estable)
        b["avisos"] = self.vista_avisos([a for a in self.avisos if a["para"] == j], 30)
        if cambios:
            self.cambio()
            b["v"] = self.v
        return b

    def vista_marco_juez(self, j: str, m: float) -> Dict[str, Any]:
        om = self.marco_vigente(j)
        puede, motivo = self.puede_firmar(j, m)
        if j not in self.de_turno(m):
            puede, motivo = False, motivo or "No está de turno."
        c = self.contenido_marco(j, False)
        return {"firmada": {k: om[k] for k in ("id", "min", "hora", "entrada", "huella", "seguimiento")} if om else None,
                "propuesta": {"lineas": c["lineas"], "condiciones_seguimiento": c["condiciones_seguimiento"],
                              "titulo_casilla": TITULO_CASILLA},
                "puede_firmar": puede, "motivo_no": None if puede else motivo,
                "seguimiento_disponible": self.dinamica_habilitada}

    def sala(self) -> Dict[str, Any]:
        m = self.minuto()
        exps = [self.vista_expediente(e, m) for e in self.expedientes]
        ubs = [u for e in exps for u in e["ubicaciones"]]
        aprobadas = [u for u in ubs if u["estado"] == "aprobada"]
        primeros = [u["cobertura"]["primer_bloqueo_min"] for u in aprobadas if u["cobertura"]["primer_bloqueo_min"] is not None]
        conteo = {k: 0 for k in ("enviadas", "recibidas", "aplicadas", "fallidas", "rechazadas", "vencidas",
                                 "levantadas", "en_espera")}
        mapa = {"recibida": "recibidas", "aplicada": "aplicadas", "fallida": "fallidas", "rechazada": "rechazadas",
                "vencida": "vencidas", "levantada": "levantadas", "espera_ratificacion": "en_espera"}
        dano = dano_vigentes = 0
        for o in self.ordenes:
            if o["enviada_min"] is not None:
                conteo["enviadas"] += 1
            if o["estado"] in mapa:
                conteo[mapa[o["estado"]]] += 1
            if o["tipo"] == "ip" and o["aplicada_min"] is not None:
                if any(d for d in DNS_IP.get(o["objetivo"], []) if registrable(d) != registrable(
                        self.ubicacion(self.expediente(o["_exp"]), o["_n"])["host"])):
                    dano += 1
                    if o["estado"] in ("recibida", "aplicada"):
                        dano_vigentes += 1
        desc = {"licenciatario": 0, "otra_senal": 0, "sin_marca": 0}
        for d in self.descartes.values():
            desc[d["clase"]] += 1
        provs = []
        for p in PROVEEDORES:
            mias = [o for o in self.ordenes if o["proveedor"] == p["id"]]
            demoras = [o["aplicada_min"] - o["recibida_min"] for o in mias if o["aplicada_min"] is not None]
            provs.append({"id": p["id"], "nombre": p["nombre"], "tamano": p["tamano"], "clientes": p["clientes"],
                          "capacidades": p["capacidades"], "activas": sum(1 for o in mias if o["estado"] in ("recibida", "aplicada")),
                          "fallidas": sum(1 for o in mias if o["estado"] == "fallida"),
                          "demora_promedio_min": r2(sum(demoras) / len(demoras)) if demoras else None})

        def prom(xs):
            return round(sum(xs) / len(xs), 2) if xs else None

        kpis = {"expedientes": len(exps),
                "ubicaciones_bloqueadas": sum(1 for u in aprobadas if u["cobertura"]["proveedores_aplicados"] > 0),
                "ubicaciones_pendientes": sum(1 for u in ubs if u["estado"] == "pendiente"),
                "clientes_total": CLIENTES_TOTAL,
                "clientes_cubiertos_pct": prom([u["cobertura"]["clientes_cubiertos_pct"] for u in aprobadas]),
                "primer_bloqueo_promedio_min": prom(primeros),
                "visibilidad_residual_promedio_pct": prom([u["cobertura"]["visibilidad_residual_pct"] for u in ubs
                                                           if u["estado"] != "rechazada"
                                                           and u["cobertura"]["visibilidad_residual_pct"] is not None]),
                "ordenes_con_dano_colateral": dano,
                "ordenes_con_dano_colateral_vigentes": dano_vigentes,
                "reclamos_pendientes": sum(1 for r in self.reclamos if r["estado"] == "pendiente"),
                "reclamos_resueltos": sum(1 for r in self.reclamos if r["estado"] in ("resuelto", "desestimado", "cerrado")),
                # C12: ubicaciones cuyo bloqueo aplicado se levantó entero («6 de 7 · 1 levantada»).
                "ubicaciones_levantadas": sum(1 for u in aprobadas if self.levantada_entera(u)),
                "ordenes": conteo, "descartes": desc}
        cabeza = self.auditoria[-1]
        return {"v": self.v, "reloj": self.reloj(), "cabeza_auditoria": {"n": cabeza["n"], "hash": cabeza["hash"]},
                "kpis": kpis, "proveedores": provs, "expedientes": exps,
                "descartes": sorted(self.descartes.values(), key=lambda d: d["minuto"]),
                "reclamos": sorted(self.reclamos, key=lambda x: x["minuto"] or 0),
                "traspasos": [{k: val for k, val in t.items() if not k.startswith("_")} for t in self.traspasos],
                "avisos": self.vista_avisos(self.avisos, 50), "paquete": self.paquete,
                # Contrato (ronda 2b, secciones 1 y 2): órdenes marco firmadas y estado de cada juez.
                "marcos": [self.vista_marco_publica(x) for x in self.marcos],
                "jueces": [{"juez_id": j, "nombre": JUECES[j]["nombre"], "de_turno": j in self.de_turno(m),
                            "activo": self.activo(j),
                            # Propuesta para E (N8): el turno, así la sala dice «Fuera de turno desde el min X».
                            "turno": {"desde_min": self.turno_de(j)["desde_min"],
                                      "hasta_min": self.turno_de(j)["hasta_min"]},
                            "hace_s": None if self.hace_s(j) is None else int(self.hace_s(j)),
                            "marco": ({"id": self.marco_vigente(j)["id"], "seguimiento": self.marco_vigente(j)["seguimiento"]}
                                      if self.marco_vigente(j) else None)} for j in JUECES],
                "auditoria": list(reversed(self.auditoria[-80:]))}

    def decision_publica(self, o: Dict[str, Any], dec: Dict[str, Any]) -> Dict[str, Any]:
        """Ola C, NV1 (como `_decision_publica` del motor): la decisión que ORDENÓ esta orden. Para un reemplazo por
        reclamo es la resolución del reclamo, no la firma original de la ubicación."""
        rid = o.get("reclamo")
        res = next((x.get("resolucion") for x in self.reclamos if x["id"] == rid), None) if rid else None
        if o.get("origen") == "reemplazo_reclamo" and res:
            quien = res.get("juez") or JUECES[o["juez_id"]]["nombre"]
            return {"origen": "reclamo", "reclamo": rid, "min": res.get("min"), "entrada": res.get("entrada"),
                    "tipo": "resolucion_reclamo",
                    "texto": "Decidida por %s al resolver el reclamo %s, en el minuto %s (entrada %s)" % (
                        quien, rid, min_txt(res.get("min")), res.get("entrada"))}
        return {"origen": "ubicacion", "reclamo": None, "min": dec.get("min"), "entrada": dec.get("entrada"),
                "tipo": dec.get("tipo"), "texto": dec.get("texto")}

    def bloqueo_publico(self, o: Dict[str, Any]) -> Dict[str, Any]:
        exp = self.expediente(o["_exp"])
        u = self.ubicacion(exp, o["_n"])
        dec = u["decision"] or {}
        dp = self.decision_publica(o, dec)
        return {"orden_id": o["orden_id"], "expediente": exp["id"], "filtracion": exp["id"], "sello": o["_sello"],
                "tipo": o["tipo"],
                "objetivo": o["objetivo"], "proveedor": o["proveedor"], "proveedor_nombre": o["proveedor_nombre"],
                "estado": o["estado"], "desde_min": o["aplicada_min"], "hasta_min": o["finalizada_min"],
                "vence_min": o["vence_min"], "juez": JUECES[o["juez_id"]]["nombre"], "juzgado": JUECES_JUZGADO(o["juez_id"]),
                "decision_min": dp["min"],
                # Como el motor: el registro distingue una ampliación de una firma (y, NV1, de una resolución de reclamo).
                "decision_tipo": dp["tipo"], "bajo_orden_de": dec.get("bajo_orden_de"),
                "decision_texto": dp["texto"], "decision_origen": dp["origen"], "reclamo": dp["reclamo"],
                "motivo": "Retransmisión no autorizada del partido «%s» (expediente %s, sitio %s)." % (
                    PARTIDO["nombre"], exp["id"], exp["titulo"]), "levantamiento": ({"min": o["levantamiento"]["min"], "juez": o["levantamiento"]["juez_nombre"],
                                                     "motivo": o["levantamiento"]["motivo"],
                                                     "reclamo": o["levantamiento"]["reclamo"]}
                                                    if o["levantamiento"] else None)}

    def registro(self) -> Dict[str, Any]:
        r = self.reloj()
        bloqueos = [self.bloqueo_publico(o) for o in self.ordenes if o["aplicada_min"] is not None]
        bloqueos.sort(key=lambda b: (b["desde_min"] or 0, b["orden_id"]))
        cabeza = self.auditoria[-1]
        return {"v": self.v,
                "reloj": {k: r[k] for k in ("minuto", "hora", "fin_min", "finalizado", "partido", "hora_inicio",
                                            "fin_hora")},
                # C1: los proveedores del partido desde el minuto cero (aunque todavía no haya bloqueos).
                "proveedores": [{"id": p["id"], "nombre": p["nombre"], "capacidades": p["capacidades"]}
                                for p in PROVEEDORES],
                "cabeza_auditoria": {"n": cabeza["n"], "hash": cabeza["hash"]},
                "resumen": {"bloqueos_vigentes": sum(1 for b in bloqueos if b["estado"] == "aplicada"),
                            "bloqueos_vencidos": sum(1 for b in bloqueos if b["estado"] == "vencida"),
                            "bloqueos_levantados": sum(1 for b in bloqueos if b["estado"] == "levantada"),
                            "sitios_bloqueados": len({b["expediente"] for b in bloqueos}),
                            "reclamos_recibidos": len(self.reclamos),
                            "reclamos_resueltos": sum(1 for x in self.reclamos if x["estado"] != "pendiente")},
                "bloqueos": bloqueos, "paquete": self.paquete,
                "marcos": [self.vista_marco_publica(x) for x in self.marcos]}

    def orden_publica(self, orden_id: str) -> Dict[str, Any]:
        o = next((x for x in self.ordenes if x["orden_id"] == orden_id), None)
        if o is None:
            raise ErrorApi(404, "no_encontrado", "No existe una orden con ese identificador.")
        exp = self.expediente(o["_exp"])
        u = self.ubicacion(exp, o["_n"])
        dec = u["decision"] or {}
        dp = self.decision_publica(o, dec)
        m = self.minuto()
        juez = JUECES[o["juez_id"]]["nombre"]
        juzgado = JUECES_JUZGADO(o["juez_id"])
        que = "la IP" if o["tipo"] == "ip" else "el nombre de dominio"
        texto = "Se ordena a %s bloquear %s %s hasta el minuto %d del partido (hora %s). %s" % (
            o["proveedor_nombre"], que, o["objetivo"], o["vence_min"], self.hora(o["vence_min"]),
            "El bloqueo vence en ese minuto: con las líneas de abajo se quita solo." if o["tipo"] == "ip" else
            "Vence en ese minuto. El DNS no lo quita solo: usá la lista del proveedor o la línea de vencimiento.")
        if o["origen"] == "reemplazo_reclamo":
            texto += " Reemplaza un bloqueo por IP que afectaba a un sitio legítimo (reclamo %s)." % o["reclamo"]
        prefijo = u["senal"].get("prefijo") or u["senal"]["marca"]  # ronda 2b, sección 4: sin la sesión del abonado
        por_que = [u["senal"]["motivo"] + " Marca de agua %s: %s." % (prefijo, u["senal"]["origen"]),
                   "El stream sale del servidor %s (%s, AS%d %s), comprobado contra el DNS pasivo." % (
                       u["host"], u["ip"], u["asn"], u["organizacion"]),
                   u["colateral"]["motivo"],
                   # C10: la misma oración del motor; una ampliación no la «vio» el juez.
                   "La evidencia quedó sellada (huella %s…); el sello %s une esta orden con la " % (u["huella"][:16], o["_sello"])
                   + ("evidencia exacta que evaluó la plataforma y con la autorización del juez (su orden marco y el "
                      "seguimiento que otorgó) en el registro de auditoría." if o["orden_id"].startswith("amp-") else
                      "evidencia exacta que vio el juez y con su decisión en el registro de auditoría.")]
        if o["origen"] == "reemplazo_reclamo":
            por_que.insert(0, "Reemplaza un bloqueo por IP que afectaba a un sitio ajeno, después de un reclamo verificado.")
        kit = kit_proveedor(o["tipo"], o["objetivo"], o["vence_min"], m, exp["id"], o["_sello"],
                            vigente=o["estado"] not in NO_RIGE and m < o["vence_min"],
                            # Ola C (kit): como el motor, la hora real del reloj del equipo, con segundos; con el
                            # partido acelerado no coincide con la hora del partido del texto.
                            hora_vence=self.hora(o["vence_min"]) if self.acelerar == 1 else (
                                datetime.now() + timedelta(minutes=max(0.0, o["vence_min"] - m) / self.acelerar)
                            ).strftime("%H:%M:%S"),
                            fecha_vence=(self.inicio + timedelta(minutes=o["vence_min"])).strftime("%Y-%m-%d"))
        return {"orden": self.vista_orden(o), "expediente": exp["id"], "filtracion": exp["id"], "ubicacion": u["n"],
                "sello": o["_sello"],
                "huella": u["huella"], "juez": juez, "juzgado": juzgado, "decision_min": dp["min"],
                "decision_hora": self.hora(dp["min"]) if dp["min"] is not None else None,
                "decision_origen": dp["origen"], "reclamo": dp["reclamo"],
                "texto_llano": texto, "por_que": por_que, "levantamiento": o["levantamiento"],
                "v": self.v,  # contrato: la vista de la orden trae su versión
                "decision": {"tipo": dp["tipo"], "bajo_orden_de": dec.get("bajo_orden_de"),
                             "texto": dp["texto"], "entrada": dp["entrada"]},
                "evidencia": {"marca": prefijo, "host": u["host"], "ip": u["ip"], "asn": u["asn"],
                              "organizacion": u["organizacion"], "captura_sha256": u["captura"]["sha256"],
                              "riesgo": u["colateral"]["riesgo"], "motivo_colateral": u["colateral"]["motivo"]},
                "kit": kit,
                "como_objetar": ("Si este bloqueo afecta a tu sitio, avisale a tu proveedor de internet o al juzgado que "
                                 "figura arriba, con el número de orden. La plataforma comprueba qué sitios comparten el "
                                 "servidor bloqueado y el juez de turno decide si lo levanta. La decisión queda firmada y "
                                 "publicada en este registro.")}

    # -- ronda 2b, sección 5.2: la lista que el equipo del proveedor lee solo ---------------------------
    def vista_proveedor(self, pid: str) -> Dict[str, Any]:
        if pid not in PROV:
            raise ErrorApi(404, "no_encontrado", "No existe ese proveedor.")
        m = self.minuto()
        mias = [o for o in self.ordenes if o["proveedor"] == pid and o["recibida_min"] is not None]
        vig, ret = [], []
        for o in mias:
            dec = self.ubicacion(self.expediente(o["_exp"]), o["_n"])["decision"] or {}
            if o["estado"] in ("recibida", "aplicada") and not o["levantamiento"] and m < o["vence_min"]:
                vig.append({"orden_id": o["orden_id"], "tipo": o["tipo"], "objetivo": o["objetivo"],
                            "vence_min": o["vence_min"], "vence_hora": self.hora(o["vence_min"])[:5],
                            "juzgado": JUECES_JUZGADO(o["juez_id"]), "juez": JUECES[o["juez_id"]]["nombre"],
                            "firma": "ampliacion" if dec.get("tipo") == "ampliacion_dinamica" else "en_persona",
                            "desde_min": o["recibida_min"], "url": "/orden/" + o["orden_id"]})
            elif o["estado"] in ("levantada", "vencida"):
                ret.append({"orden_id": o["orden_id"], "tipo": o["tipo"], "objetivo": o["objetivo"],
                            "motivo": o["estado"], "min": o["finalizada_min"]})
        p = PROV[pid]
        return {"v": self.v, "proveedor": {"id": pid, "nombre": p["nombre"], "capacidades": p["capacidades"]},
                "minuto": r2(m), "hora": self.hora(m)[:5], "generado_utc": utc_ahora(),
                "partido": {"nombre": PARTIDO["nombre"], "fin_min": PARTIDO["fin_min"],
                            "fin_hora": self.hora(PARTIDO["fin_min"])[:5]},
                "vigentes": vig, "retiradas": ret[-50:]}

    # -- ronda 2b, sección 5.4: «¿Tu sitio quedó bloqueado?» --------------------------------------------
    @staticmethod
    def normalizar_consulta(texto: Any) -> str:
        """C9 (como el motor): sin espacios alrededor, esquema, usuario, ruta, consulta, fragmento, puerto ni punto
        final, y en minúsculas."""
        t = str(texto or "").strip()
        if "://" in t:
            t = t.split("://", 1)[1]
        for corte in "/?#":
            t = t.split(corte, 1)[0]
        if "@" in t:
            t = t.rsplit("@", 1)[1]
        cabeza, dos_puntos, cola = t.rpartition(":")
        if dos_puntos and cola.isdigit() and ":" not in cabeza:
            t = cabeza
        return t.rstrip(".").lower()

    def consulta_publica(self, dominio: str) -> Dict[str, Any]:
        crudo = str(dominio or "").strip()
        d = self.normalizar_consulta(crudo)
        if not d or len(d) > 253 or "." not in d or any(not r for r in d.split(".")) \
                or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789.-" for c in d):
            return {"dominio": d or crudo, "resultado": "invalido", "ordenes": [],
                    "texto": "Escriba un nombre de dominio, por ejemplo: mitienda.com.ar."}
        m = self.minuto()
        vig = [o for o in self.ordenes if o["estado"] in ("recibida", "aplicada") and m < o["vence_min"]]

        def item(o):
            return {"orden_id": o["orden_id"], "tipo": o["tipo"], "objetivo": o["objetivo"],
                    "juzgado": JUECES_JUZGADO(o["juez_id"]), "vence_min": o["vence_min"], "url": "/orden/" + o["orden_id"]}
        directas = [item(o) for o in vig if o["tipo"] == "dominio" and o["objetivo"] == d]
        if directas:
            return {"dominio": d, "resultado": "bloqueado", "ordenes": directas,
                    "texto": "%s está bloqueado por orden judicial hasta el final del partido." % d}
        ips = DNS_DOMINIO.get(d, [])
        compartidas = [item(o) for o in vig if o["tipo"] == "ip" and o["objetivo"] in ips]
        if compartidas:
            return {"dominio": d, "resultado": "comparte_servidor", "ordenes": compartidas,
                    "texto": "%s comparte el servidor %s con un sitio bloqueado por IP. Si su sitio no tiene relación "
                             "con la retransmisión, avise a su proveedor o al juzgado con el número de orden." % (
                                 d, ", ".join(sorted({o["objetivo"] for o in compartidas})))}
        return {"dominio": d, "resultado": "no_alcanzado", "ordenes": [],
                "texto": "Ninguna orden vigente alcanza a %s." % d}


LEYENDA_KIT = ("Probá estas líneas en tu equipo antes del partido. Lo que obliga es la orden (objetivo y "
               "vencimiento); las líneas son una ayuda.")


def kit_proveedor(tipo: str, objetivo: str, vence_min: int, minuto_actual: float, expediente: str, sello: str, *,
                  vigente: bool = True, hora_vence: Optional[str] = None, fecha_vence: Optional[str] = None):
    """Como marca/kit.py del motor (ronda 2b, sección 5.1): preparar, aplicar, quitar y vencer."""
    faltan = max(1.0, float(vence_min) - float(minuto_actual or 0))
    total = max(1, int(math.ceil(faltan)))
    h, mm = divmod(total, 60)
    dur = "%dh%dm" % (h, mm) if h else "%dm" % mm
    comentario = "%s %s%s" % (expediente, (sello or "")[:8], " vence " + hora_vence if hora_vence else "")
    v6 = ":" in objetivo
    if tipo == "ip":
        fam = "/ipv6" if v6 else "/ip"
        kit = [{"equipo": "MikroTik RouterOS 6 y 7",
                "preparar": '%s firewall filter add chain=forward dst-address-list=bloqueo-judicial action=drop '
                            'comment="bloqueo judicial" place-before=0' % fam,
                "aplicar": '%s firewall address-list add list=bloqueo-judicial address=%s timeout=%s comment="%s"' % (
                    fam, objetivo, dur, comentario),
                "quitar": "%s firewall address-list remove [find list=bloqueo-judicial address=%s]" % (fam, objetivo),
                "nota": "La regla de preparar tiene que quedar antes de la regla fasttrack-connection; si no, las "
                        "conexiones ya abiertas siguen. Para cortar a quien ya está mirando: /ip firewall connection "
                        "remove [find where dst-address~\"^%s(:|$)\"] (probalo antes en tu equipo). La entrada con "
                        "timeout se borra si el router se reinicia: si reinicia durante el partido, volvé a pegarla. "
                        "El timeout cuenta desde que pegás la línea: vence a las %s. %s" % (
                            objetivo, hora_vence or "la hora del vencimiento", LEYENDA_KIT)},
               {"equipo": "nftables",
                "preparar": "nft add table inet bloqueo_judicial ; nft add set inet bloqueo_judicial objetivos "
                            "'{ type %s; flags timeout; }' ; nft add chain inet bloqueo_judicial forward "
                            "'{ type filter hook forward priority -10; policy accept; }' ; nft add rule inet "
                            "bloqueo_judicial forward %s daddr @objetivos drop" % (
                                "ipv6_addr" if v6 else "ipv4_addr", "ip6" if v6 else "ip"),
                "aplicar": "nft add element inet bloqueo_judicial objetivos '{ %s timeout %dm }'" % (objetivo, total),
                "quitar": "nft delete element inet bloqueo_judicial objetivos '{ %s }'" % objetivo,
                "nota": "Si usás flowtable, esta tabla tiene que cortar antes del flow add. " + LEYENDA_KIT}]
    else:
        kit = [{"equipo": "MikroTik RouterOS 6 y 7",
                "aplicar": '/ip dns static add name=%s type=NXDOMAIN comment="%s" ; /ip dns cache flush' % (
                    objetivo, comentario),
                "quitar": "/ip dns static remove [find name=%s]" % objetivo,
                "vencer": '/system scheduler add name=vence-%s-%s start-date=%s start-time=%s:00 interval=0s '
                          'on-event="/ip dns static remove [find name=%s]"' % (
                              expediente, (sello or "")[:8], fecha_vence or "AAAA-MM-DD", hora_vence or "HH:MM", objetivo),
                "nota": "RouterOS 6.47 o posterior y el reloj en hora; solo alcanza a los abonados que usan este router "
                        "como DNS. Solo el nombre exacto (ni subdominios ni el dominio padre). " + LEYENDA_KIT},
               {"equipo": "Unbound", "aplicar": "unbound-control local_zone %s. always_nxdomain" % objetivo,
                "quitar": "unbound-control local_zone_remove %s." % objetivo,
                "nota": "Corta ese nombre y los que cuelgan de él (sus subdominios). No toca el dominio de arriba ni a sus "
                        "nombres hermanos. Vive en memoria: un reload o un reinicio lo borra; no vence solo: usá la lista "
                        "del proveedor o corré la línea de quitar al final. " + LEYENDA_KIT},
               {"equipo": "BIND (RPZ)",
                "preparar": 'zone "rpz.local" { type primary; file "rpz.local"; update-policy local; }; y en options: '
                            'response-policy { zone "rpz.local"; } min-update-interval 5;',
                "aplicar": "printf 'zone rpz.local\\nupdate add %s.rpz.local. 60 CNAME .\\nsend\\n' | nsupdate -l" % objetivo,
                "quitar": "printf 'zone rpz.local\\nupdate delete %s.rpz.local. CNAME\\nsend\\n' | nsupdate -l" % objetivo,
                "nota": LEYENDA_KIT}]
    if not vigente:  # la orden ya no rige: sin aplicar ni preparar, solo quitar
        kit = [{"equipo": k["equipo"], "quitar": k["quitar"],
                "nota": "Esta orden ya no rige. Si la aplicaste, quitala."} for k in kit]
    return kit


def JUECES_JUZGADO(juez_id: str) -> str:
    return JUZGADOS[JUECES[juez_id]["juzgado_id"]]


# ---------------------------------------------------------------------------
# Servidor HTTP
# ---------------------------------------------------------------------------
PAGINAS = {"/": "index.html", "/juez": "juez.html", "/sala": "sala.html", "/transparencia": "transparencia.html"}
TIPOS = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
         ".ico": "image/x-icon", ".json": "application/json; charset=utf-8", ".txt": "text/plain; charset=utf-8"}
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
       "font-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")

MUNDO: Optional[Mundo] = None


class Manejador(BaseHTTPRequestHandler):
    server_version = "MarcaPersonalSimulada/" + VERSION
    protocol_version = "HTTP/1.1"

    def log_message(self, formato: str, *args: Any) -> None:  # silencio: la espera larga ensucia la consola
        return

    # -- respuestas ----------------------------------------------------------
    def responder(self, estado: int, cuerpo: bytes, tipo: str, extra: Optional[Dict[str, str]] = None) -> None:
        self.send_response(estado)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", (extra or {}).pop("Cache-Control", None) or "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if tipo.startswith("text/html"):
            self.send_header("Content-Security-Policy", CSP)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(cuerpo)

    def json(self, estado: int, obj: Any, extra: Optional[Dict[str, str]] = None) -> None:
        self.responder(estado, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", extra)

    def error(self, e: ErrorApi) -> None:
        self.json(e.estado, {"error": e.texto, "codigo": e.codigo})

    # -- sesión -------------------------------------------------------------
    def ficha(self) -> Optional[str]:
        for parte in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = parte.strip().partition("=")
            if k == "mp_sesion":
                return v
        return None

    def usuario(self) -> str:
        f = self.ficha()
        s = MUNDO.sesiones.get(f) if f else None
        if not s or s["vence"] < time.time():
            raise ErrorApi(401, "no_autenticado", "Inicie sesión para continuar.")
        if s.get("juez_id"):
            MUNDO.marcar_actividad(s["juez_id"])  # ronda 2b, sección 2: cada pedido autenticado de un juez
        return s["usuario"]

    def rol(self, rol: str) -> str:
        usuario = self.usuario()
        if USUARIOS[usuario]["rol"] != rol:
            raise ErrorApi(403, "sin_permiso", "Su usuario no tiene permiso para esta pantalla.")
        return usuario

    def cuerpo(self) -> Dict[str, Any]:
        tipo = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        largo = int(self.headers.get("Content-Length") or 0)
        datos = self.rfile.read(largo) if largo else b""
        if tipo != "application/json":
            raise ErrorApi(422, "invalido", "La solicitud tiene que enviarse como JSON.")
        try:
            obj = json.loads(datos.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            raise ErrorApi(422, "invalido", "El cuerpo de la solicitud no es JSON válido.")
        if not isinstance(obj, dict):
            raise ErrorApi(422, "invalido", "El cuerpo de la solicitud tiene que ser un objeto.")
        return obj

    # -- GET ----------------------------------------------------------------
    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        url = urlparse(self.path)
        ruta = url.path
        try:
            if ruta.startswith("/api/"):
                return self.api_get(ruta, parse_qs(url.query))
            if ruta in PAGINAS:
                return self.archivo(WEB / PAGINAS[ruta])
            if ruta.startswith("/orden/"):
                return self.archivo(WEB / "orden.html")
            if ruta.startswith("/proveedor/"):
                return self.lista_proveedor(ruta)
            if ruta.startswith("/static/"):
                destino = (WEB / "static" / unquote(ruta[len("/static/"):])).resolve()
                if WEB not in destino.parents:
                    raise ErrorApi(404, "no_encontrado", "No existe.")
                return self.archivo(destino)
            raise ErrorApi(404, "no_encontrado", "No existe esa página.")
        except ErrorApi as e:
            self.error(e)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def lista_proveedor(self, ruta: str) -> None:
        """Ronda 2b, sección 5.2: /proveedor/<id>/{vigentes.json,dominios.txt,ips.txt,unbound.conf,rpz.zone}."""
        partes = ruta.strip("/").split("/")
        if len(partes) != 3:
            raise ErrorApi(404, "no_encontrado", "No existe esa lista.")
        with MUNDO.cond:
            v = MUNDO.vista_proveedor(unquote(partes[1]))
        sin_cache = {"Cache-Control": "no-store"}
        if partes[2] == "vigentes.json":
            return self.json(200, v, sin_cache)
        cab = ["# %s · min %s (%s) · %d vigentes · el partido termina en el min %s (%s)" % (
            v["proveedor"]["nombre"], fmin(v["minuto"]), v["hora"], len(v["vigentes"]), fmin(v["partido"]["fin_min"]),
            v["partido"]["fin_hora"]), "# Son datos, no comandos: su equipo decide cómo aplicarlos."]
        doms = sorted({x["objetivo"] for x in v["vigentes"] if x["tipo"] == "dominio"})
        ips = sorted({x["objetivo"] for x in v["vigentes"] if x["tipo"] == "ip"})
        if partes[2] == "dominios.txt":
            cuerpo = cab + doms
        elif partes[2] == "ips.txt":
            cuerpo = cab + ips
        elif partes[2] == "unbound.conf":
            cuerpo = [cab[0], cab[1] + " Cada línea corta el nombre y sus subdominios."] + [
                'local-zone: "%s." always_nxdomain' % d for d in doms]
        elif partes[2] == "rpz.zone":
            cuerpo = [";" + c[1:] for c in cab] + ["$TTL 30", "@ SOA localhost. root.localhost. %d 60 60 600 30" % v["v"],
                                                  "@ NS localhost."] + ["%s CNAME ." % d for d in doms]
        else:
            raise ErrorApi(404, "no_encontrado", "No existe esa lista.")
        return self.responder(200, ("\n".join(cuerpo) + "\n").encode("utf-8"), "text/plain; charset=utf-8", sin_cache)

    def archivo(self, ruta: Path) -> None:
        if not ruta.is_file():
            raise ErrorApi(404, "no_encontrado", "No existe ese archivo.")
        self.responder(200, ruta.read_bytes(), TIPOS.get(ruta.suffix.lower(), "application/octet-stream"))

    def api_get(self, ruta: str, q: Dict[str, List[str]]) -> None:
        m = MUNDO
        if ruta == "/api/salud":
            with m.cond:
                r = m.reloj()
            return self.json(200, {"ok": True, "version": VERSION, "conexion": "ok", "minuto": r["minuto"],
                                   "partido": r["partido"]})
        if ruta == "/api/cambios":
            try:
                v = int((q.get("v") or ["0"])[0])
            except ValueError:
                v = 0
            limite = time.monotonic() + 20
            with m.cond:
                while m.v <= v:
                    resta = limite - time.monotonic()
                    if resta <= 0:
                        break
                    m.cond.wait(min(resta, 1.0))
                s = m.sesiones.get(self.ficha() or "")
                if s and s.get("juez_id") and s["vence"] > time.time():
                    m.marcar_actividad(s["juez_id"])  # también al terminar la espera larga
                return self.json(200, {"v": m.v, "minuto": r2(m.minuto())})
        if ruta == "/api/publico/consulta":
            with m.cond:
                return self.json(200, m.consulta_publica((q.get("dominio") or [""])[0]))
        if ruta == "/api/yo":
            with m.cond:
                return self.json(200, m.yo(self.usuario()))
        if ruta == "/api/juez/bandeja":
            with m.cond:
                return self.json(200, m.bandeja(self.rol("juez")))
        if ruta == "/api/sala":
            with m.cond:
                self.rol("fiscalia")
                return self.json(200, m.sala())
        if ruta == "/api/publico/registro":
            with m.cond:
                return self.json(200, m.registro())
        if ruta.startswith("/api/publico/ordenes/"):
            with m.cond:
                return self.json(200, m.orden_publica(unquote(ruta[len("/api/publico/ordenes/"):])))
        raise ErrorApi(404, "no_encontrado", "No existe esa ruta de la API.")

    # -- POST ---------------------------------------------------------------
    def do_POST(self) -> None:
        ruta = urlparse(self.path).path
        try:
            cuerpo = self.cuerpo()
            with MUNDO.cond:
                self.api_post(ruta, cuerpo)
        except ErrorApi as e:
            self.error(e)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def api_post(self, ruta: str, c: Dict[str, Any]) -> None:
        m = MUNDO
        if ruta == "/api/login":
            usuario = str(c.get("usuario") or "").strip().lower()
            clave = str(c.get("clave") or "")
            f = m.fallos.get(usuario, {"n": 0, "hasta": 0.0})
            if f["hasta"] > time.time():
                raise ErrorApi(429, "trabado", "Demasiados intentos fallidos. Espere %d segundos y vuelva a intentar."
                               % math.ceil(f["hasta"] - time.time()))
            u = USUARIOS.get(usuario)
            ok = u is not None and hmac.compare_digest(u["clave"].encode(), clave.encode())
            if not ok:
                f["n"] += 1
                if f["n"] >= 5:
                    f = {"n": 0, "hasta": time.time() + 30}
                m.fallos[usuario] = f
                m.auditar("login_fallido", "sistema", None, {"usuario": usuario[:40]})
                raise ErrorApi(401, "no_autenticado", "Usuario o contraseña incorrectos.")
            m.fallos.pop(usuario, None)
            ficha = secrets.token_urlsafe(32)
            m.sesiones[ficha] = {"usuario": usuario, "juez_id": u.get("juez_id"), "vence": time.time() + 12 * 3600}
            m.auditar("sesion_iniciada", "juez:" + u["juez_id"] if u.get("juez_id") else "fiscalia:" + usuario, None, {})
            m.cambio()
            return self.json(200, m.yo(usuario), {
                "Set-Cookie": "mp_sesion=%s; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200" % ficha})
        if ruta == "/api/logout":
            usuario = self.usuario()
            m.sesiones.pop(self.ficha(), None)
            m.auditar("sesion_cerrada", "sistema", None, {"usuario": usuario})
            m.cambio()
            return self.json(200, {"ok": True}, {"Set-Cookie": "mp_sesion=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"})
        if not ruta.startswith("/api/juez/"):
            raise ErrorApi(404, "no_encontrado", "No existe esa ruta de la API.")
        usuario = self.rol("juez")
        juez = USUARIOS[usuario]["juez_id"]
        ahora = m.minuto()
        if ahora >= PARTIDO["fin_min"]:
            raise ErrorApi(409, "partido_finalizado", "El partido terminó: ya no se firman órdenes.")
        puede, motivo = m.puede_firmar(juez, ahora)
        if not puede:
            raise ErrorApi(403, "fuera_de_turno", motivo or "No está de turno.")
        partes = ruta.strip("/").split("/")  # api juez ...
        aviso_r: Optional[str] = None  # turnos-2: lo que no se levantó porque otra ubicación lo necesita
        if m.fallos_pasajeros > 0 and partes[-1] == "aprobar":
            # --fallo-pasajero: como el motor sin conexión con el simulador (pantallas-1). La pantalla no puede
            # perder lo que el juez eligió ni firmar otra cosa al segundo toque.
            m.fallos_pasajeros -= 1
            raise ErrorApi(403, "fuera_de_turno", "Sin conexión con el simulador: no se puede confirmar el turno.")
        if len(partes) == 6 and partes[2] == "ubicaciones":
            exp = m.expediente(unquote(partes[3]))
            try:
                n = int(partes[4])
            except ValueError:
                raise ErrorApi(404, "no_encontrado", "Ubicación inválida.")
            u = m.ubicacion(exp, n)
            accion = partes[5]
            if accion in ("aprobar", "rechazar"):
                if u["estado"] != "pendiente":
                    raise ErrorApi(409, "conflicto", "Este pedido ya fue decidido.")
                if u["asignada_a"] != juez:
                    raise ErrorApi(403, "sin_permiso", "Este pedido está asignado a otro juez.")
            if accion == "aprobar":
                alcance = str(c.get("alcance") or "ubicacion")  # como el motor: sin alcance, solo esta ubicación
                if alcance not in ("ubicacion", "filtracion"):
                    raise ErrorApi(422, "invalido", "El alcance debe ser 'ubicacion' o 'filtracion'.")
                if alcance == "filtracion" and not m.dinamica_habilitada:
                    raise ErrorApi(422, "invalido", "El seguimiento está deshabilitado en esta plataforma.")
                if alcance == "filtracion" and not m.con_seguimiento(juez):
                    raise ErrorApi(422, "invalido", "Para seguir a la filtración, firme antes la orden marco con el "
                                                    "seguimiento autorizado.")
                forzar_tipo = c.get("forzar_tipo")
                fundamento = str(c.get("fundamento") or "").strip()
                if forzar_tipo not in (None, "", "ip", "dominio"):
                    raise ErrorApi(422, "invalido", "Tipo de bloqueo inválido.")
                rec = u["colateral"]["recomendacion"]
                forzar = None
                if forzar_tipo and forzar_tipo != rec:
                    if len(fundamento) < 10:
                        raise ErrorApi(422, "invalido", "Para apartarse de la recomendación escriba un fundamento de al menos 10 caracteres.")
                    forzar = {"tipo": forzar_tipo, "fundamento": fundamento}
                elif rec == "ninguna":
                    raise ErrorApi(422, "invalido", "La plataforma no recomienda bloquear: elija el tipo y fundamente.")
                m.decidir(juez, exp, u, True, alcance, forzar, None)
                if PARTIDO["fin_min"] - ahora < FUERA_DE_PLAZO_MIN:
                    aviso_r = TEXTO_FUERA_DE_PLAZO
            elif accion == "rechazar":
                motivo_r = str(c.get("motivo") or "").strip()
                if len(motivo_r) < 10:  # ronda 2b, sección 7
                    raise ErrorApi(422, "invalido", "Escriba el motivo del rechazo (al menos 10 caracteres).")
                m.decidir(juez, exp, u, False, "ubicacion", None, motivo_r)
            elif accion == "levantar":
                motivo_l = str(c.get("motivo") or "").strip()
                if len(motivo_l) < 3:
                    raise ErrorApi(422, "invalido", "Escriba el motivo del levantamiento.")
                activas = [o for o in m.ordenes_de(exp["id"], n) if o["estado"] in ACTIVAS + ("espera_ratificacion",)]
                if not activas:
                    raise ErrorApi(409, "conflicto", "Esta ubicación no tiene bloqueos activos.")
                # turnos-2: lo que otra ubicación firmada necesita no se levanta; se avisa.
                hechas, mant = m.levantar_salvo_necesarias(activas, {(exp["id"], n)}, juez, motivo_l, ahora)
                if not hechas:
                    raise ErrorApi(409, "conflicto", " ".join(mant))
                aviso_r = " ".join(mant) or None
            else:
                raise ErrorApi(404, "no_encontrado", "Acción desconocida.")
        elif partes[2:] == ["marco"]:
            m.firmar_marco(juez, bool(c.get("seguimiento")))  # ronda 2b, sección 1
        elif partes[2:] == ["traspaso", "ratificar"]:
            dins = c.get("dinamicas")
            if dins is not None and not (isinstance(dins, list) and all(isinstance(x, str) for x in dins)):
                raise ErrorApi(422, "invalido", "«dinamicas» tiene que ser una lista de expedientes o null.")
            m.ultimo_ratificar = None
            aviso = m.ratificar(juez, dins)
            m.cambio()
            res = dict(getattr(m, "ultimo_ratificar", None) or {}, aviso=aviso)  # como el motor: `resultado`
            return self.json(200, {"ok": True, "aviso": aviso, "bandeja": m.bandeja(usuario), "resultado": res})
        elif len(partes) == 5 and partes[2] == "dinamicas" and partes[4] == "revocar":
            exp = m.expediente(unquote(partes[3]))
            motivo_d = str(c.get("motivo") or "").strip()  # contrato: el motivo es opcional
            m.revocar(juez, exp, motivo_d, bool(c.get("levantar")))
            aviso_r = m.ultimo_aviso
        elif len(partes) == 5 and partes[2] == "reclamos" and partes[4] == "resolver":
            rid = unquote(partes[3])
            r = next((x for x in m.reclamos if x["id"] == rid), None)
            if r is None:
                raise ErrorApi(404, "no_encontrado", "No existe ese reclamo.")
            if r["estado"] != "pendiente":
                raise ErrorApi(409, "conflicto", "Este reclamo ya fue resuelto.")
            accion = c.get("accion")
            if accion not in ("levantar_y_reemplazar", "levantar", "desestimar"):
                raise ErrorApi(422, "invalido", "Acción inválida para el reclamo.")
            fundamento = str(c.get("fundamento") or "").strip() or None
            if accion == "desestimar" and (not fundamento or len(fundamento) < 3):
                raise ErrorApi(422, "invalido", "Para desestimar el reclamo escriba un fundamento.")
            m.resolver_reclamo(juez, r, accion, fundamento)
        else:
            raise ErrorApi(404, "no_encontrado", "No existe esa ruta de la API.")
        m.cambio()
        r_ok = {"ok": True, "bandeja": m.bandeja(usuario)}
        if aviso_r:
            r_ok["aviso"] = aviso_r
        return self.json(200, r_ok)


def ciclo(mundo: Mundo, parar: threading.Event) -> None:
    while not parar.is_set():
        try:
            mundo.tick()
        except Exception as e:  # el guion nunca tiene que tirar el servidor
            print("Error en el guion:", repr(e), file=sys.stderr)
        parar.wait(0.2)


def main() -> None:
    global MUNDO
    ap = argparse.ArgumentParser(description="API simulada de Marca Personal (solo para desarrollar las pantallas).")
    ap.add_argument("--puerto", type=int, default=8790)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--acelerar", type=float, default=6.0, help="minutos de partido por minuto real (6: 1 min = 10 s)")
    ap.add_argument("--inicio-min", type=float, default=-0.5, help="minuto de partido en el que arranca el guion")
    ap.add_argument("--auto", action="store_true", help="juez automático de ensayo: firma, ratifica y resuelve solo")
    ap.add_argument("--sin-dinamica", action="store_true", help="deshabilita el seguimiento de la filtración")
    ap.add_argument("--fallo-pasajero", type=int, default=0,
                    help="las próximas N firmas fallan con «fuera_de_turno» pasajero (sin conexión con el simulador)")
    a = ap.parse_args()
    if not WEB.is_dir():
        sys.exit("No encuentro las pantallas en %s" % WEB)
    MUNDO = Mundo(a.acelerar, a.inicio_min, a.auto, not a.sin_dinamica)
    MUNDO.fallos_pasajeros = max(0, a.fallo_pasajero)
    parar = threading.Event()
    hilo = threading.Thread(target=ciclo, args=(MUNDO, parar), daemon=True)
    hilo.start()
    srv = ThreadingHTTPServer((a.host, a.puerto), Manejador)
    srv.daemon_threads = True
    base = "http://%s:%d" % ("127.0.0.1" if a.host in ("0.0.0.0", "") else a.host, a.puerto)
    print("API simulada de Marca Personal — SOLO PARA DESARROLLO, sin simulador.")
    print("  Portada:        %s/" % base)
    print("  Juez:           %s/juez" % base)
    print("  Sala:           %s/sala" % base)
    print("  Transparencia:  %s/transparencia" % base)
    print("  Usuarios y claves de prueba: ver USUARIOS al principio de este archivo.")
    print("  Partido: min %s, x%s%s%s" % (fmin(a.inicio_min), a.acelerar, ", juez automático" if a.auto else "",
                                         ", sin seguimiento" if a.sin_dinamica else ""))
    sys.stdout.flush()
    try:
        srv.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        parar.set()
        srv.server_close()


if __name__ == "__main__":
    main()
