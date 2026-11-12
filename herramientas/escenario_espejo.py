#!/usr/bin/env python3
"""Generador de "partidos espejo" para el Desafio Futbol (Hackathon Argentina Space 2026).

Toma el escenario de practica y su verdad (solo los LEE como JSON, no ejecuta nada del repo del
desafio) y produce una variante con otros sitios, IP, ASN, marcas, sesiones, tiempos y capturas,
coherente entre `escenario.json` y `verdad.json`, para ensayar que la plataforma no quedo atada
a los nombres de la practica.

Uso:
    python3 herramientas/escenario_espejo.py --repo-desafio "<ruta>" --semilla 7 --salida <carpeta> [--trampas]

Solo biblioteca estandar, Python 3.9+. Determinista: misma semilla, mismo resultado (con la misma
version de Python, porque se apoya en random.Random).
"""
from __future__ import annotations

import argparse
import base64
import copy
import json
import random
import re
import string
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

# "compartid" cubre compartido/compartida, la raiz que mira la plataforma. Ningun nombre de ORG_A/ORG_B
# la contiene, asi que el cambio no altera la salida (el filtro nunca descarta nada).
PALABRAS_PROHIBIDAS_EN_ORGANIZACION = ("cdn", "compartid", "dedicado", "shared")
RANGOS_IP = ("192.0.2.", "198.51.100.", "203.0.113.")
ASN_MIN, ASN_MAX = 64512, 65534
MINUTO_MIN = 0.5
CAMBIO_DE_TURNO_MIN = 50.0

# --------------------------------------------------------------------------------------------
# Vocabulario inventado (ningun nombre coincide con los de la practica; se verifica igual).
# --------------------------------------------------------------------------------------------
PIRATA_A = ["arco", "cancha", "tablon", "gambeta", "chilena", "hinchada", "vestuario", "palco", "remate",
            "cabezazo", "pizarron", "banderin", "lateral", "medialuna", "vaiven", "orsai", "cabecera", "alargue"]
PIRATA_B = ["directo", "tv", "hd", "play", "gol", "stream", "total", "vivo", "max", "premium", "zona", "online"]
FALSO_A = ["goles", "resultados", "tabla", "fechas", "cronica", "repasos", "analisis", "jugadas"]
FALSO_B = ["del-dia", "semanales", "y-mas", "al-instante", "de-la-fecha", "en-resumen"]
LEGIT_RUBRO = ["ferreteria", "libreria", "optica", "gomeria", "kiosco", "heladeria", "taller", "farmacia",
               "vivero", "jugueteria", "zapateria", "imprenta", "dietetica", "rotiseria", "lavadero", "mueblerias"]
LEGIT_LUGAR = ["los-cardos", "del-sur", "san-expedito", "el-molino", "la-estancia", "norte-grande", "santa-clara",
               "el-trebol", "paso-largo", "la-merced", "villa-alta", "el-ceibo"]
LICENCIATARIO = ["canal-meridiano", "telecumbre", "videosur", "canal-altiplano", "redvision-oeste", "telelitoral-vision"]
SUBDOMINIOS = ["n1", "n2", "c3", "edge", "play", "hd1", "stream", "vivo2", "m4", "tx", "dir", "rt", "emisor",
               "senal", "b7", "k2", "z5", "relay", "flujo", "w3", "q8", "lt1", "directo", "tv2", "cast"]
ORG_A = ["Meridiano", "Altamar", "Cuenca", "Sendero", "Faro", "Quebrada", "Vertiente", "Cordillera", "Pampero",
         "Mirador", "Ribera", "Cumbrera", "Alameda", "Costanera"]
ORG_B = ["Redes", "Datos", "Servidores", "Telematica", "Conexiones", "Sistemas", "Infraestructura"]
CLUBES = ["Atletico Cumbres", "Deportivo Riberas", "Union del Valle Alto", "Sportivo Quebrada", "Juventud Austral",
          "Racing del Oeste", "Defensores del Faro", "Club Sierras Verdes", "Estudiantes del Sur", "Central Pampero"]
LIGAS = ["Liga Federal Ficticia", "Federacion Austral de Futbol (ficticia)", "Asociacion Regional Ficticia"]
REDES_NOMBRES = {"x": ["tuit", "pio-red", "mx-red"], "discord": ["sala-voz", "charlas-hoy"],
                 "telegram": ["canal-t", "mensajeo"]}
MENSAJES = [
    "{n}: nuestros clientes no pueden entrar a la tienda online desde hace unos minutos.",
    "{n}: la pagina de inscripciones dejo de cargar.",
    "{n}: el sitio no carga para visitantes de varios proveedores.",
    "{n}: el portal de tramites esta caido para parte de los vecinos.",
    "{n}: los turnos online no abren desde hace un rato.",
]
MENSAJE_LICENCIATARIO = "{n}: somos licenciatarios autorizados y nuestra transmision fue bloqueada."
# Borde "inquilinos": plataforma que reparte subdominios de un mismo registrable entre duenos distintos.
PLATAFORMA_A = ["barrio", "vecinal", "plaza", "rincon", "patio", "comarca", "portal", "mural"]
PLATAFORMA_B = ["web", "sitios", "paginas", "digital", "hosting", "red"]
INQUILINOS = ["recetas", "turnos", "clima", "noticias", "foro", "tienda", "agenda", "fotos", "clases", "talleres"]
MENSAJE_INQUILINO = "{n}: nuestra pagina dejo de cargar y no tenemos nada que ver con el futbol."


# --------------------------------------------------------------------------------------------
# Utilidades de dominios
# --------------------------------------------------------------------------------------------
def partir_host(host: str) -> Tuple[str, str]:
    """('s1', 'pelotaya.test') o ('', 'pelotaya.test') para el apex."""
    etiquetas = host.split(".")
    if len(etiquetas) < 2:
        raise ValueError(f"host invalido: {host!r}")
    return ".".join(etiquetas[:-2]), ".".join(etiquetas[-2:])


def etiqueta_base(base: str) -> str:
    return base.rsplit(".", 1)[0]


def nombre_visible(etiqueta: str) -> str:
    return " ".join(p.capitalize() for p in etiqueta.split("-"))


def reemplazar_host_en_url(url: str, nuevo_host: str) -> str:
    partes = urlsplit(url)
    return urlunsplit((partes.scheme, nuevo_host, partes.path, partes.query, partes.fragment))


class Generador:
    """Estado del mapeo original -> espejo. Todo el azar sale de un unico random.Random(semilla)."""

    def __init__(self, escenario: dict, verdad: dict, semilla: int) -> None:
        self.rng = random.Random(semilla)
        self.semilla = semilla
        self.orig_esc = escenario
        self.orig_ver = verdad
        self.fin_min = float(verdad["fin_min"])

        # Tokens originales que no pueden reaparecer en etiquetas inventadas.
        self.hosts_orig = self._hosts_originales()
        self.bases_orig = list(dict.fromkeys(partir_host(h)[1] for h in self.hosts_orig))
        self.prohibidos = {etiqueta_base(b) for b in self.bases_orig} | {s["id"] for s in verdad["streams"]}
        self.etiquetas_usadas: set = set()

        self.mapa_base: Dict[str, str] = {}
        self.mapa_sub: Dict[Tuple[str, str], str] = {}
        self.mapa_host: Dict[str, str] = {}
        self.mapa_ip: Dict[str, str] = {}
        self.mapa_asn: Dict[int, int] = {}
        self.mapa_marca: Dict[str, str] = {}
        self.mapa_promo: Dict[Tuple[str, str], str] = {}
        self.hosts_promo: Dict[str, str] = {}
        self.sesiones_usadas: set = set()
        self.subs_libres = list(SUBDOMINIOS)
        self.rng.shuffle(self.subs_libres)
        self.ips_libres = [f"{r}{n}" for r in RANGOS_IP for n in range(1, 255)]
        self.ips_libres = [ip for ip in self.ips_libres if ip not in escenario["ip_asn"] and ip not in escenario["dns_pasivo"]]
        self.rng.shuffle(self.ips_libres)
        self.asn_libres = [a for a in range(ASN_MIN, ASN_MAX + 1) if str(a) not in escenario["asn"]]
        self.rng.shuffle(self.asn_libres)
        self.orgs_usadas: set = set()

    # ---- recoleccion de hosts originales -------------------------------------------------
    def _hosts_originales(self) -> List[str]:
        e, v = self.orig_esc, self.orig_ver
        hosts: List[str] = []
        for doms in e["dns_pasivo"].values():
            hosts.extend(doms)
        hosts.extend(r["dominio"] for r in e.get("reclamos_automaticos", []))
        hosts.extend(v["dominios_piratas"])
        for lic in e["partido"]["licenciatarios"]:
            hosts.extend(lic["dominios_autorizados"])
        for d in e["detecciones"]:
            hosts.append(d["host_stream"])
            hosts.append(urlsplit(d["pagina"]).hostname or "")
            hosts.append(urlsplit(d["stream_url"]).hostname or "")
        for s in v["streams"]:
            hosts.extend(f["host"] for f in s["fases"])
        return list(dict.fromkeys(h for h in hosts if h))

    # ---- nombres -------------------------------------------------------------------------
    def _etiqueta_libre(self, generar) -> str:
        for _ in range(500):
            cand = generar()
            if cand in self.etiquetas_usadas or any(p in cand for p in self.prohibidos):
                continue
            self.etiquetas_usadas.add(cand)
            return cand
        raise RuntimeError("no se pudo inventar un nombre libre")

    def _tld(self) -> str:
        return self.rng.choice([".test", ".test", ".example"])

    def nueva_base(self, tipo: str) -> str:
        rng = self.rng
        if tipo == "pirata":
            g = lambda: rng.choice(PIRATA_A) + rng.choice(["", "-"]) + rng.choice(PIRATA_B)
        elif tipo == "falso":
            g = lambda: rng.choice(FALSO_A) + "-" + rng.choice(FALSO_B)
        elif tipo == "licenciatario":
            g = lambda: rng.choice(LICENCIATARIO)
        elif tipo == "plataforma":
            g = lambda: rng.choice(PLATAFORMA_A) + rng.choice(["", "-"]) + rng.choice(PLATAFORMA_B)
        else:
            g = lambda: rng.choice(LEGIT_RUBRO) + "-" + rng.choice(LEGIT_LUGAR)
        return self._etiqueta_libre(g) + self._tld()

    def nuevo_sub(self) -> str:
        if not self.subs_libres:
            raise RuntimeError("se acabaron los subdominios inventados")
        return self.subs_libres.pop()

    def nueva_ip(self) -> str:
        return self.ips_libres.pop()

    def nueva_asn(self) -> int:
        return self.asn_libres.pop()

    def nueva_organizacion(self) -> str:
        for _ in range(500):
            n = f"{self.rng.choice(ORG_A)} {self.rng.choice(ORG_B)} (ficticio)"
            if n not in self.orgs_usadas and not any(p in n.lower() for p in PALABRAS_PROHIBIDAS_EN_ORGANIZACION):
                self.orgs_usadas.add(n)
                return n
        raise RuntimeError("no se pudo inventar una organizacion")

    # ---- mapeo de hosts ------------------------------------------------------------------
    def preparar_hosts(self) -> None:
        e, v = self.orig_esc, self.orig_ver
        bases_lic = {partir_host(d)[1] for l in e["partido"]["licenciatarios"] for d in l["dominios_autorizados"]}
        bases_pir = {partir_host(h)[1] for h in v["dominios_piratas"]}
        bases_fp = {partir_host(f["host"])[1] for s in v["streams"] if s["clase"] == "falso_positivo" for f in s["fases"]}
        for base in self.bases_orig:
            tipo = ("licenciatario" if base in bases_lic else "pirata" if base in bases_pir
                    else "falso" if base in bases_fp else "legitimo")
            self.mapa_base[base] = self.nueva_base(tipo)
        subs = [partir_host(h) for h in self.hosts_orig]
        dependientes = []
        for sub, base in subs:
            if not sub or (base, sub) in self.mapa_sub:
                continue
            prefijo = sub.split("-")[0]
            if prefijo != sub and any(s == prefijo and b == base for s, b in subs):
                dependientes.append((sub, base))
            else:
                self.mapa_sub[(base, sub)] = self.nuevo_sub()
        for sub, base in dependientes:  # p. ej. "s1-respaldo" cuelga del nuevo nombre de "s1"
            prefijo, resto = sub.split("-", 1)
            self.mapa_sub[(base, sub)] = self.mapa_sub[(base, prefijo)] + "-reserva"
        for h in self.hosts_orig:
            self.mapa_host[h] = self._componer(*partir_host(h))

    def _componer(self, sub: str, base: str) -> str:
        nueva = self.mapa_base[base]
        return f"{self.mapa_sub[(base, sub)]}.{nueva}" if sub else nueva

    def host(self, h: str) -> str:
        return self.mapa_host[h]

    # ---- marcas de agua ------------------------------------------------------------------
    def preparar_marcas(self) -> None:
        partido = self.orig_esc["partido"]
        prefijos_lic = {l["prefijo_marca"] for l in partido["licenciatarios"]}
        letras = string.ascii_uppercase
        while True:
            codigo = "".join(self.rng.choice(letras) for _ in range(3))
            if codigo != "PRA":
                break
        self.prefijos: List[Tuple[str, str]] = []
        for m in partido["marcas_de_agua_validas"]:
            if m["prefijo"] in prefijos_lic:
                while True:
                    algo = "".join(self.rng.choice(letras) for _ in range(5))
                    if algo != "NORTE":
                        break
                nuevo = f"LP26-{codigo}-LIC-{algo}"
            else:
                nuevo = f"LP26-{codigo}-OFI"
            self.prefijos.append((m["prefijo"], nuevo))
        self.mapa_prefijo = dict(self.prefijos)

    def _sesion_nueva(self, prohibida: str = "") -> str:
        while True:
            s = f"S{self.rng.randint(0, 999999):06d}"
            if s not in self.sesiones_usadas and s != prohibida:
                self.sesiones_usadas.add(s)
                return s

    def marca(self, orig: str) -> str:
        if orig == "":
            return ""
        if orig in self.mapa_marca:
            return self.mapa_marca[orig]
        nueva: Optional[str] = None
        for pref, nuevo_pref in self.prefijos:
            if orig == pref:
                nueva = nuevo_pref
            elif orig.startswith(pref + "-"):
                m = re.fullmatch(r"-(S\d{6})", orig[len(pref):])
                if not m:
                    raise ValueError(f"marca con sufijo desconocido: {orig!r}")
                nueva = f"{nuevo_pref}-{self._sesion_nueva(m.group(1))}"
            if nueva is not None:
                break
        if nueva is None:
            m = re.fullmatch(r"LP25-F(\d\d)-OFI-(S\d{6})", orig)
            if not m:
                raise ValueError(f"marca ajena con formato desconocido: {orig!r}")
            while True:
                fecha = self.rng.randint(1, 38)
                if f"{fecha:02d}" != m.group(1):
                    break
            nueva = f"LP25-F{fecha:02d}-OFI-{self._sesion_nueva(m.group(2))}"
        self.mapa_marca[orig] = nueva
        return nueva

    def marca_licenciatario(self) -> str:
        lic = {l["prefijo_marca"] for l in self.orig_esc["partido"]["licenciatarios"]}
        return self.mapa_prefijo[sorted(lic)[0]]

    def marca_oficial_nueva(self) -> str:
        """Prefijo oficial + sesion nueva (para los streams agregados por --trampas)."""
        lic = {l["prefijo_marca"] for l in self.orig_esc["partido"]["licenciatarios"]}
        oficial = next(n for o, n in self.prefijos if o not in lic)
        return f"{oficial}-{self._sesion_nueva()}"

    # ---- promociones ---------------------------------------------------------------------
    def host_red(self, red: str) -> str:
        if red not in self.hosts_promo:
            usados = set(self.hosts_promo.values())
            opciones = [f"{n}.example" for n in REDES_NOMBRES.get(red, [f"red-{red}"]) if f"{n}.example" not in usados]
            self.hosts_promo[red] = self.rng.choice(opciones) if opciones else f"red-{red}-{len(usados)}.example"
        return self.hosts_promo[red]

    def promo(self, red: str, url: str, slug: str) -> str:
        clave = (red, url)
        if clave not in self.mapa_promo:
            partes = urlsplit(url)
            segs = []
            for s in partes.path.split("/"):
                if s in ("", "status", "invite"):
                    segs.append(s)
                elif s.isdigit():
                    segs.append(str(self.rng.randint(1000, 9999)))
                else:
                    segs.append(slug)
            self.mapa_promo[clave] = urlunsplit((partes.scheme, self.host_red(red), "/".join(segs), "", ""))
        return self.mapa_promo[clave]

    def promo_nueva(self, red: str, slug: str, minuto: float) -> dict:
        ruta = {"x": f"/{slug}/status/{self.rng.randint(1000, 9999)}", "discord": f"/invite/{slug}"}.get(red, f"/{slug}")
        return {"red": red, "url": f"https://{self.host_red(red)}{ruta}", "minuto": minuto}

    # ---- capturas ------------------------------------------------------------------------
    def captura_b64(self) -> str:
        contenido = bytes([0x47]) + bytes(self.rng.getrandbits(8) for _ in range(63))
        return base64.b64encode(contenido).decode("ascii")


# --------------------------------------------------------------------------------------------
# Correr tiempos
# --------------------------------------------------------------------------------------------
def tiempos_de_stream(dets: List[dict], fases: List[dict]) -> List[float]:
    t: List[float] = []
    for d in dets:
        t.append(d["minuto"])
        t.append(d["captura"]["capturada_min"])
        t.extend(p["minuto"] for p in d.get("promocion", []))
    t.extend(f["desde_min"] for f in fases)
    return t


def elegir_corrimientos(gen: Generador, streams_dets: Dict[str, Tuple[List[dict], List[dict]]]) -> Dict[str, float]:
    """Un corrimiento por stream; reintenta hasta que quede una mudanza antes y otra despues del minuto 50."""
    fin = gen.fin_min
    for _ in range(300):
        corr: Dict[str, float] = {}
        for sid, (dets, fases) in streams_dets.items():
            t = tiempos_de_stream(dets, fases)
            ok = lambda c: min(t) + c >= MINUTO_MIN and max(t) + c <= fin
            cands = [x / 2 for x in range(-8, 9) if abs(x) >= 2 and ok(x / 2)]
            if not cands:
                cands = [x / 2 for x in range(-8, 9) if x != 0 and ok(x / 2)]
            corr[sid] = gen.rng.choice(cands) if cands else 0.0
        mudanzas = []
        for sid, (dets, fases) in streams_dets.items():
            if gen.orig_ver_clase[sid] == "pirata":
                mudanzas.extend(f["desde_min"] + corr[sid] for f in fases[1:])
        if any(m < CAMBIO_DE_TURNO_MIN for m in mudanzas) and any(m > CAMBIO_DE_TURNO_MIN for m in mudanzas):
            return corr
    raise RuntimeError("no se pudo dejar una mudanza de servidor antes y otra despues del minuto 50")


# --------------------------------------------------------------------------------------------
# Generacion
# --------------------------------------------------------------------------------------------
def generar(escenario: dict, verdad: dict, semilla: int, trampas: bool = False,
            bordes: bool = False) -> Tuple[dict, dict]:
    gen = Generador(escenario, verdad, semilla)
    gen.orig_ver_clase = {s["id"]: s["clase"] for s in verdad["streams"]}
    rng = gen.rng
    esc = copy.deepcopy(escenario)
    ver = copy.deepcopy(verdad)
    fin = gen.fin_min

    gen.preparar_hosts()
    gen.preparar_marcas()

    # --- IP y ASN --------------------------------------------------------------------------
    for ip in escenario["dns_pasivo"]:
        gen.mapa_ip[ip] = gen.nueva_ip()
    for asn in escenario["asn"]:
        gen.mapa_asn[int(asn)] = gen.nueva_asn()

    # --- partido ---------------------------------------------------------------------------
    p = esc["partido"]
    clubes = rng.sample(CLUBES, 2)
    p["nombre"] = f"Partido espejo {semilla} — {clubes[0]} vs. {clubes[1]}"
    p["id"] = f"espejo-{semilla}"
    p["titular_derechos"] = rng.choice(LIGAS)
    esc["id"] = f"espejo-{semilla}"
    ver["escenario_id"] = f"espejo-{semilla}"

    nombres_lic: Dict[str, str] = {}
    for lic in p["licenciatarios"]:
        base_nueva = gen.mapa_base[partir_host(lic["dominios_autorizados"][0])[1]]
        nombres_lic[lic["nombre"]] = f"{nombre_visible(etiqueta_base(base_nueva))} TV (ficticio)"
    for m in p["marcas_de_agua_validas"]:
        for viejo, nuevo in nombres_lic.items():
            m["origen"] = m["origen"].replace(viejo, nuevo)
        m["prefijo"] = gen.mapa_prefijo[m["prefijo"]]
    for lic in p["licenciatarios"]:
        lic["prefijo_marca"] = gen.mapa_prefijo[lic["prefijo_marca"]]
        lic["dominios_autorizados"] = [gen.host(d) for d in lic["dominios_autorizados"]]
        lic["nombre"] = nombres_lic[lic["nombre"]]

    # --- asn / ip_asn / dns_pasivo ---------------------------------------------------------
    esc["asn"] = {}
    for asn, org in escenario["asn"].items():
        esc["asn"][str(gen.mapa_asn[int(asn)])] = nombres_lic.get(org) or gen.nueva_organizacion()
    esc["ip_asn"] = {gen.mapa_ip[ip]: gen.mapa_asn[a] for ip, a in escenario["ip_asn"].items()}
    esc["dns_pasivo"] = {gen.mapa_ip[ip]: [gen.host(d) for d in doms] for ip, doms in escenario["dns_pasivo"].items()}

    # --- detecciones por stream -> corrimientos ---------------------------------------------
    por_id = {d["id"]: d for d in esc["detecciones"]}
    streams_dets: Dict[str, Tuple[List[dict], List[dict]]] = {}
    stream_de_det: Dict[str, str] = {}
    for s in ver["streams"]:
        dets: List[dict] = []
        for f in s["fases"]:
            for did in f["detecciones"]:
                dets.append(por_id[did])
                stream_de_det[did] = s["id"]
        streams_dets[s["id"]] = (dets, s["fases"])
    if set(stream_de_det) != set(por_id):
        raise ValueError("la verdad de la practica no cubre todas las detecciones")
    corr = elegir_corrimientos(gen, streams_dets)

    # --- transformar detecciones -------------------------------------------------------------
    for d in esc["detecciones"]:
        c = corr[stream_de_det[d["id"]]]
        host_orig = d["host_stream"]
        slug = etiqueta_base(gen.mapa_base[partir_host(host_orig)[1]]).replace("-", "_")
        ip_orig = d["ip_servidor"]
        d["minuto"] = round(d["minuto"] + c, 3)
        d["pagina"] = reemplazar_host_en_url(d["pagina"], gen.host(urlsplit(d["pagina"]).hostname))
        d["stream_url"] = reemplazar_host_en_url(d["stream_url"], gen.host(urlsplit(d["stream_url"]).hostname))
        d["host_stream"] = gen.host(host_orig)
        d["ip_servidor"] = gen.mapa_ip[ip_orig]
        d["asn"] = gen.mapa_asn[d["asn"]]
        d["marca_de_agua_extraida"] = gen.marca(d["marca_de_agua_extraida"])
        d["captura"]["capturada_min"] = round(d["captura"]["capturada_min"] + c, 3)
        d["captura"]["contenido_b64"] = gen.captura_b64()
        for pr in d["promocion"]:
            pr["url"] = gen.promo(pr["red"], pr["url"], slug)
            pr["minuto"] = round(pr["minuto"] + c, 3)

    # --- transformar verdad ------------------------------------------------------------------
    nuevo_id_stream: Dict[str, str] = {}
    for s in ver["streams"]:
        c = corr[s["id"]]
        nuevo_id_stream[s["id"]] = etiqueta_base(gen.mapa_base[partir_host(s["fases"][0]["host"])[1]])
        for f in s["fases"]:
            f["host"] = gen.host(f["host"])
            f["ip"] = gen.mapa_ip[f["ip"]]
            f["desde_min"] = round(f["desde_min"] + c, 3)
            f["hasta_min"] = round(min(f["hasta_min"] + c, fin), 3)
    for s in ver["streams"]:
        s["id"] = nuevo_id_stream[s["id"]]
    if len(set(nuevo_id_stream.values())) != len(nuevo_id_stream):
        raise ValueError("dos streams de la practica comparten sitio: no se pueden renombrar por separado")
    ver["dominios_piratas"] = [gen.host(h) for h in ver["dominios_piratas"]]

    # --- reclamos automaticos ----------------------------------------------------------------
    dominios_lic = {d for l in escenario["partido"]["licenciatarios"] for d in l["dominios_autorizados"]}
    reclamos = []
    for r in escenario.get("reclamos_automaticos", []):
        nuevo_dom = gen.host(r["dominio"])
        n = nombre_visible(etiqueta_base(partir_host(nuevo_dom)[1]))
        if r["dominio"] in dominios_lic:
            lic_nombre = next(nombres_lic[l["nombre"]] for l in escenario["partido"]["licenciatarios"]
                              if r["dominio"] in l["dominios_autorizados"])
            msg = MENSAJE_LICENCIATARIO.format(n=lic_nombre)
        else:
            msg = rng.choice(MENSAJES).format(n=n)
        reclamos.append({"dominio": nuevo_dom, "demora_min": max(1, r["demora_min"] + rng.randint(-1, 1)), "mensaje": msg})
    esc["reclamos_automaticos"] = reclamos

    # --- trampas -----------------------------------------------------------------------------
    if trampas:
        _agregar_trampas(gen, esc, ver)

    # --- bordes ------------------------------------------------------------------------------
    # Se agregan DESPUES de las trampas, de modo que `--trampas --bordes` conserva byte a byte
    # la parte de trampas y solo suma los bordes al final. Sin --bordes no se toca el azar.
    if bordes:
        _agregar_bordes(gen, esc, ver)

    # --- renumerar detecciones por minuto ----------------------------------------------------
    orden = sorted(range(len(esc["detecciones"])), key=lambda i: (esc["detecciones"][i]["minuto"], i))
    viejo_a_nuevo: Dict[str, str] = {}
    nuevas = []
    for pos, i in enumerate(orden, start=1):
        d = esc["detecciones"][i]
        nuevo = f"D-{pos:04d}"
        viejo_a_nuevo[d["id"]] = nuevo
        d["id"] = nuevo
        nuevas.append(d)
    esc["detecciones"] = nuevas
    for s in ver["streams"]:
        for f in s["fases"]:
            f["detecciones"] = sorted(viejo_a_nuevo[x] for x in f["detecciones"])
    return esc, ver


def _agregar_trampas(gen: Generador, esc: dict, ver: dict) -> None:
    rng = gen.rng
    fin = gen.fin_min

    def sitio(tipo: str, sub: Optional[str] = None) -> Tuple[str, str]:
        base = gen.nueva_base(tipo)
        host = f"{sub or gen.nuevo_sub()}.{base}"
        return base, host

    def ip_con_asn() -> Tuple[str, int]:
        ip, asn = gen.nueva_ip(), gen.nueva_asn()
        esc["asn"][str(asn)] = gen.nueva_organizacion()
        esc["ip_asn"][ip] = asn
        return ip, asn

    def detecciones(host: str, base: str, ip: str, asn: int, marca: str, minutos: List[float], promos: List[Tuple[str, float]]) -> List[str]:
        slug = etiqueta_base(base).replace("-", "_")
        ids = []
        for m in minutos:
            did = f"T-{len(esc['detecciones']) + 1}"
            esc["detecciones"].append({
                "id": did, "minuto": m,
                "pagina": f"https://{base}/en-vivo",
                "stream_url": f"https://{host}/hls/en-vivo/index.m3u8",
                "host_stream": host, "ip_servidor": ip, "asn": asn,
                "marca_de_agua_extraida": marca,
                "captura": {"capturada_min": m, "formato": "mpegts", "duracion_seg": 6, "contenido_b64": gen.captura_b64()},
                "promocion": [gen.promo_nueva(red, slug, pm) for red, pm in promos],
            })
            ids.append(did)
        return ids

    def serie(inicio_min: int, inicio_max: int, n: int, paso_min: int, paso_max: int) -> List[float]:
        t = float(rng.randint(inicio_min, inicio_max))
        out = [t]
        for _ in range(n - 1):
            t += rng.randint(paso_min, paso_max)
            out.append(t)
        return out

    # 1) Falso positivo sin marca de agua, en un sitio nuevo con IP propia.
    base, host = sitio("falso", "vod")
    ip, asn = ip_con_asn()
    esc["dns_pasivo"][ip] = [host, base]
    ts = serie(10, 30, 2, 12, 20)
    ids = detecciones(host, base, ip, asn, "", ts, [("x", round(ts[0] - 2, 1))])
    ver["streams"].append({"id": etiqueta_base(base), "clase": "falso_positivo", "fases": [
        {"host": host, "ip": ip, "desde_min": ts[0], "hasta_min": ts[-1] + 5.0, "bloqueo_recomendado": None, "detecciones": ids}]})

    # 2) Pirata que retransmite la senal del licenciatario en un dominio que no es suyo.
    base, host = sitio("pirata")
    ip, asn = ip_con_asn()
    esc["dns_pasivo"][ip] = [host]
    ts = serie(12, 35, 3, 15, 25)
    ids = detecciones(host, base, ip, asn, gen.marca_licenciatario(), ts, [("telegram", round(ts[0] - 3, 1))])
    ver["streams"].append({"id": etiqueta_base(base), "clase": "pirata", "fases": [
        {"host": host, "ip": ip, "desde_min": ts[0], "hasta_min": fin_float(fin), "bloqueo_recomendado": "ip", "detecciones": ids}]})
    ver["dominios_piratas"].append(host)

    # 3) Pirata en una IP que comparte con un unico sitio legitimo (ni CDN ni hosting grande).
    base, host = sitio("pirata")
    base_legit, _ = sitio("legitimo", "www")
    legit = base_legit  # el sitio legitimo vive en su dominio base
    ip, asn = ip_con_asn()
    esc["dns_pasivo"][ip] = [host, legit]
    ts = serie(18, 40, 3, 15, 25)
    ids = detecciones(host, base, ip, asn, gen.marca_oficial_nueva(), ts,
                      [("discord", round(ts[0] - 4, 1)), ("x", round(ts[0] - 2, 1))])
    ver["streams"].append({"id": etiqueta_base(base), "clase": "pirata", "fases": [
        {"host": host, "ip": ip, "desde_min": ts[0], "hasta_min": fin_float(fin), "bloqueo_recomendado": "dominio", "detecciones": ids}]})
    ver["dominios_piratas"].append(host)
    esc["reclamos_automaticos"].append({
        "dominio": legit, "demora_min": rng.randint(3, 6),
        "mensaje": rng.choice(MENSAJES).format(n=nombre_visible(etiqueta_base(legit)))})


def fin_float(fin: float) -> float:
    return float(fin)


# --------------------------------------------------------------------------------------------
# Bordes: tiempos y combinaciones incomodas que el simulador oficial admite (--bordes).
#
# Todo lo que se agrega aca es coherente con la verdad y lo acepta el verificador oficial:
# son situaciones de las mismas familias que ya trae el partido (mudanzas, IP compartida,
# senal propia) llevadas a los BORDES que el espejo base nunca toca: el cambio de turno (minuto
# 50), los ultimos minutos, mudanzas muy juntas, servidores en paralelo y reusados, y una IP con
# inquilinos de un mismo dominio registrable.
#
# Cada minuto de borde se sortea por semilla dentro de una banda chica y segura (BANDAS_BORDE),
# para que tres semillas no ensayen la misma grilla de tiempos; el minuto del final (fase de
# duracion cero) es fijo porque ese borde ES el minuto. Sitios, IP, ASN, sesiones y capturas
# vienen del mismo azar por semilla. Todo el azar de los bordes se consume DESPUES del espejo
# base y de las trampas, asi que sin --bordes la salida no cambia ni un byte.
#
# Las recomendaciones de la verdad son las de la regla de colateral: IP si el servidor es
# exclusivo del pirata, dominio si comparte con ajenos. En el borde "inquilinos" esa regla es la
# NUEVA (un nombre que comparte la IP es propio del pirata solo si es el host del stream o el de la
# pagina, o si comparte el registrable R con el host y la pagina vive en R o en www.R): las reglas
# de foto1/foto2 todavia recomiendan "ip" ahi, y un chequeo de reglas contra esas copias marca esa
# fase. Es el defecto que se esta corrigiendo, no un error del escenario.
#
# Se descartan a proposito, por ser DUDOSOS o por no sumar un resultado nuevo que el verificador
# puntue:
#   - Evidencia que no cierra (sin DNS, host fuera del DNS, ASN distinto, captura repetida): la
#     recomendacion depende de un dato incoherente; el verificador no lo puntua distinto y el
#     chequeo de reglas lo marcaria como "NO limpia". Es mejor ensayarlo como sonda suelta.
#   - Host con mayusculas o punto final: la verdad tendria el host sin normalizar y el bloqueo
#     por dominio no contaria; no sabemos cual es el resultado "correcto" esperado -> dudoso.
#   - Otra lista de proveedores y --acelerar: no van en escenario.json (uno en --datos, el otro
#     en la linea del simulador); no los produce este generador.
# --------------------------------------------------------------------------------------------
# Bandas (minimo, maximo) de cada minuto de borde, relativas a turno=50 y fin=105. Las anchuras
# ("+") son la distancia al corte anterior del mismo stream.
BANDAS_BORDE = {
    "turno_antes": (49.85, 49.95),        # filtracion nueva a 0,05..0,15 min ANTES del cambio
    "turno_despues": (50.05, 50.15),      # y otra a 0,05..0,15 min DESPUES
    "mudanza_inicio": (39.0, 41.0),       # la sesion que se muda en el cambio de turno arranca aca
    "mudanza_antes": (49.5, 49.6),        # se muda en [turno-0,5 ; turno)
    "mudanza_despues": (50.1, 50.2),      # y otra vez en (turno ; turno+0,2]: la fase del medio dura
                                          # 0,5..0,7 min (aurora, 0,35..0,65, puede llegar; nadie mas)
    "ultimos": (-2.8, -2.2),              # relativo al fin: filtracion nueva en los ultimos minutos
    "rapidas_inicio": (18.0, 22.0),
    "rapidas_primera": (38.0, 42.0),
    "rapidas_fase2": (0.8, 1.2),          # +: duracion de la 2a fase (mas corta que andina/cumbre/valle)
    "rapidas_fase3": (0.5, 0.7),          # +: duracion de la 3a fase
    "vuelve_a": (1.5, 3.0),
    "vuelve_b": (29.0, 33.0),
    "vuelve_c": (59.0, 63.0),             # vuelve al servidor de vuelve_a
    "paralelo": (61.5, 64.5),             # dos servidores a la vez, desde el mismo minuto
    "compartida_antes": (45.0, 47.0),
    "compartida": (51.5, 52.5),
    "compartida_dura": (0.8, 1.2),        # +: duracion de la fase en la IP compartida
    "inquilinos": (24.0, 28.0),
}


def _agregar_bordes(gen: Generador, esc: dict, ver: dict) -> None:
    rng = gen.rng
    fin = gen.fin_min
    turno = CAMBIO_DE_TURNO_MIN

    def banda(nombre: str, base: float = 0.0) -> float:
        lo, hi = BANDAS_BORDE[nombre]
        return round(base + round(rng.uniform(lo, hi), 2), 3)

    estado = {"sub": 0}

    def sub() -> str:
        # Etiqueta de subdominio propia de los bordes: no consume el pool barajado (que fija el
        # azar del espejo base) y no colisiona, porque cada base es nueva.
        estado["sub"] += 1
        return f"b{estado['sub']}"

    def ip_asn() -> Tuple[str, int]:
        ip, asn = gen.nueva_ip(), gen.nueva_asn()
        esc["asn"][str(asn)] = gen.nueva_organizacion()
        esc["ip_asn"][ip] = asn
        return ip, asn

    def servidor_nuevo(legitimos: int = 0) -> Tuple[str, str, str]:
        """(host, base, ip). Con legitimos>0, la IP ademas aloja sitios ajenos (IP compartida)."""
        base = gen.nueva_base("pirata")
        host = f"{sub()}.{base}"
        ip, _ = ip_asn()
        doms = [host]
        for _ in range(legitimos):
            doms.append(gen.nueva_base("legitimo"))  # sitio legitimo, registrable propio, apex
        esc["dns_pasivo"][ip] = doms
        return host, base, ip

    def det(host: str, base: str, ip: str, asn: int, marca: str, minuto: float, pagina_host: str = "") -> str:
        did = f"B-{len(esc['detecciones']) + 1}"
        esc["detecciones"].append({
            "id": did, "minuto": round(minuto, 3),
            "pagina": f"https://{pagina_host or base}/en-vivo",
            "stream_url": f"https://{host}/hls/en-vivo/index.m3u8",
            "host_stream": host, "ip_servidor": ip, "asn": asn,
            "marca_de_agua_extraida": marca,
            "captura": {"capturada_min": round(minuto, 3), "formato": "mpegts",
                        "duracion_seg": 6, "contenido_b64": gen.captura_b64()},
            "promocion": [],
        })
        return did

    def asn_de(ip: str) -> int:
        return esc["ip_asn"][ip]

    def stream(sid_base: str, clase: str, fases: List[dict]) -> None:
        ver["streams"].append({"id": etiqueta_base(sid_base), "clase": clase, "fases": fases})

    def fase(host: str, ip: str, desde: float, hasta: float, rec: Optional[str], ids: List[str]) -> dict:
        return {"host": host, "ip": ip, "desde_min": round(desde, 3),
                "hasta_min": round(hasta, 3), "bloqueo_recomendado": rec, "detecciones": ids}

    def pirata(host: str) -> None:
        ver["dominios_piratas"].append(host)

    # -- Borde 1: filtracion nueva a 0,05..0,15 min del cambio de turno (justo antes y justo despues).
    #    Dos filtraciones nuevas de una sola fase, IP exclusiva.
    for nombre in ("turno_antes", "turno_despues"):
        t0 = banda(nombre)
        host, base, ip = servidor_nuevo()
        marca = gen.marca_oficial_nueva()
        ids = [det(host, base, ip, asn_de(ip), marca, m) for m in (t0, t0 + 10, t0 + 20)]
        stream(base, "pirata", [fase(host, ip, t0, fin, "ip", ids)])
        pirata(host)

    # -- Borde 2 (mudanza-turno): la MISMA sesion se muda en [turno-0,5 ; turno) y otra vez en
    #    (turno ; turno+0,2]. Tres fases IP; la del medio es corta y cae en la zona del traspaso.
    t0, t1, t2 = banda("mudanza_inicio"), banda("mudanza_antes"), banda("mudanza_despues")
    marca = gen.marca_oficial_nueva()
    h1, b1, ip1 = servidor_nuevo()
    h2, b2, ip2 = servidor_nuevo()
    h3, b3, ip3 = servidor_nuevo()
    f1 = fase(h1, ip1, t0, t1, "ip", [det(h1, b1, ip1, asn_de(ip1), marca, m) for m in (t0, t0 + 5)])
    f2 = fase(h2, ip2, t1, t2, "ip", [det(h2, b2, ip2, asn_de(ip2), marca, t1)])
    f3 = fase(h3, ip3, t2, fin, "ip", [det(h3, b3, ip3, asn_de(ip3), marca, m) for m in (t2, t2 + 10, t2 + 30)])
    stream(b1, "pirata", [f1, f2, f3])
    for h in (h1, h2, h3):
        pirata(h)

    # -- Borde 3: filtracion nueva en los ultimos minutos, y una deteccion en el minuto exacto
    #    del final (fase de duracion cero, que el verificador marca "nunca": es lo correcto).
    t0 = banda("ultimos", fin)
    host, base, ip = servidor_nuevo()
    marca = gen.marca_oficial_nueva()
    ids = [det(host, base, ip, asn_de(ip), marca, m) for m in (t0, t0 + 1.0, t0 + 2.0)]
    stream(base, "pirata", [fase(host, ip, t0, fin, "ip", ids)])
    pirata(host)
    host, base, ip = servidor_nuevo()
    marca = gen.marca_oficial_nueva()
    idf = det(host, base, ip, asn_de(ip), marca, fin)
    stream(base, "pirata", [fase(host, ip, fin, fin, "ip", [idf])])
    pirata(host)

    # -- Borde 4: dos mudanzas de la misma filtracion separadas por menos de 1,5 min
    #    (IP1 -> IP2 -> IP3 -> IP4, fases de 0,8..1,2 y 0,5..0,7 min). Misma sesion, todo por IP.
    c0, c1 = banda("rapidas_inicio"), banda("rapidas_primera")
    c2 = banda("rapidas_fase2", c1)
    c3 = banda("rapidas_fase3", c2)
    cortes = [c0, c1, c2, c3, fin]
    marca = gen.marca_oficial_nueva()
    hs = [servidor_nuevo() for _ in range(4)]
    fases = []
    for k, (h, b, ip) in enumerate(hs):
        desde, hasta = cortes[k], cortes[k + 1]
        mins = [desde] if k in (1, 2) else [desde, round((desde + hasta) / 2, 3)]
        fases.append(fase(h, ip, desde, hasta, "ip", [det(h, b, ip, asn_de(ip), marca, m) for m in mins]))
        pirata(h)
    stream(hs[0][1], "pirata", fases)

    # -- Borde 5: el pirata vuelve a un servidor que ya uso (misma (host, IP) que una fase previa).
    a, b, c = banda("vuelve_a"), banda("vuelve_b"), banda("vuelve_c")
    marca = gen.marca_oficial_nueva()
    hA, bA, ipA = servidor_nuevo()
    hB, bB, ipB = servidor_nuevo()
    fvuelve = [
        fase(hA, ipA, a, b - 1.0, "ip", [det(hA, bA, ipA, asn_de(ipA), marca, m) for m in (a, a + 13.0)]),
        fase(hB, ipB, b, c - 1.0, "ip", [det(hB, bB, ipB, asn_de(ipB), marca, m) for m in (b, b + 14.0)]),
        fase(hA, ipA, c, fin, "ip", [det(hA, bA, ipA, asn_de(ipA), marca, m) for m in (c, c + 14.0)]),
    ]
    stream(bA, "pirata", fvuelve)
    for h in (hA, hB):
        pirata(h)

    # -- Borde 6: la misma sesion en dos servidores a la vez (dos fases superpuestas en el tiempo).
    t0 = banda("paralelo")
    marca = gen.marca_oficial_nueva()
    hP, bP, ipP = servidor_nuevo()
    hQ, bQ, ipQ = servidor_nuevo()
    fpar = [
        fase(hP, ipP, t0, fin, "ip", [det(hP, bP, ipP, asn_de(ipP), marca, m) for m in (t0, t0 + 7.0, t0 + 17.0)]),
        fase(hQ, ipQ, t0, fin, "ip", [det(hQ, bQ, ipQ, asn_de(ipQ), marca, m) for m in (t0, t0 + 8.0, t0 + 18.0)]),
    ]
    stream(bP, "pirata", fpar)
    for h in (hP, hQ):
        pirata(h)

    # -- Borde 7: IP exclusiva -> IP compartida con legitimos -> IP exclusiva (misma sesion).
    #    La fase del medio recomienda "dominio" (hay sitios ajenos en la IP): nada por IP ahi.
    a, b = banda("compartida_antes"), banda("compartida")
    c = banda("compartida_dura", b)
    marca = gen.marca_oficial_nueva()
    hx, bx, ipx = servidor_nuevo()
    hy, by, ipy = servidor_nuevo(legitimos=rng.randint(5, 8))
    hz, bz, ipz = servidor_nuevo()
    fcomp = [
        fase(hx, ipx, a, b, "ip", [det(hx, bx, ipx, asn_de(ipx), marca, m) for m in (a, a + 4.0)]),
        fase(hy, ipy, b, c, "dominio", [det(hy, by, ipy, asn_de(ipy), marca, b)]),
        fase(hz, ipz, c, fin, "ip", [det(hz, bz, ipz, asn_de(ipz), marca, m) for m in (c, c + 7.0, c + 17.0)]),
    ]
    stream(bx, "pirata", fcomp)
    for h in (hx, hy, hz):
        pirata(h)

    # -- Borde 8 (inquilinos): la IP del pirata, de una organizacion neutra, aloja vivo.R (host del
    #    stream Y de la pagina) y 1 a 3 subdominios de OTROS duenos del mismo registrable R
    #    (recetas.R, ...). Como la pagina vive en vivo.R y no en R ni en www.R, esos nombres son
    #    ajenos: la IP se trata como compartida y la verdad recomienda "dominio". Solo vivo.R es
    #    pirata; uno de los inquilinos reclama si alguien bloquea la IP.
    t0 = banda("inquilinos")
    r = gen.nueva_base("plataforma")
    host = f"vivo.{r}"
    inquilinos = [f"{n}.{r}" for n in rng.sample(INQUILINOS, rng.randint(1, 3))]
    ip, _ = ip_asn()
    esc["dns_pasivo"][ip] = [host] + inquilinos
    marca = gen.marca_oficial_nueva()
    ids = [det(host, r, ip, asn_de(ip), marca, m, pagina_host=host) for m in (t0, t0 + 10.0, t0 + 25.0)]
    stream(r, "pirata", [fase(host, ip, t0, fin, "dominio", ids)])
    pirata(host)
    reclama = rng.choice(inquilinos)
    esc["reclamos_automaticos"].append({
        "dominio": reclama, "demora_min": rng.randint(3, 6),
        "mensaje": MENSAJE_INQUILINO.format(n=nombre_visible(reclama.split(".", 1)[0]) + " de "
                                            + nombre_visible(etiqueta_base(r)))})


# --------------------------------------------------------------------------------------------
# Comprobaciones de coherencia (las usa main antes de escribir y el test las repite)
# --------------------------------------------------------------------------------------------
def _recorrer(obj: Any, sin_capturas: bool = True) -> Iterator[Tuple[str, Any]]:
    """Genera ('cadena', texto) para claves y valores de texto, y ('entero', n) para enteros."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield "cadena", str(k)
            if sin_capturas and k == "contenido_b64":
                continue
            yield from _recorrer(v, sin_capturas)
    elif isinstance(obj, list):
        for v in obj:
            yield from _recorrer(v, sin_capturas)
    elif isinstance(obj, str):
        yield "cadena", obj
    elif isinstance(obj, int) and not isinstance(obj, bool):
        yield "entero", obj


def verificar_coherencia(esc: dict, ver: dict, orig_esc: dict, orig_ver: dict, trampas: bool = False,
                         bordes: bool = False) -> List[str]:
    err: List[str] = []
    dns = esc["dns_pasivo"]
    todos_dominios = {d for doms in dns.values() for d in doms}
    dets = {d["id"]: d for d in esc["detecciones"]}
    partido = esc["partido"]
    fin = float(partido["fin_min"])

    if len(dets) != len(esc["detecciones"]):
        err.append("ids de deteccion repetidos")
    if [d["id"] for d in esc["detecciones"]] != [f"D-{i:04d}" for i in range(1, len(dets) + 1)]:
        err.append("los id de deteccion no son D-0001.. consecutivos")
    if [d["minuto"] for d in esc["detecciones"]] != sorted(d["minuto"] for d in esc["detecciones"]):
        err.append("las detecciones no estan en orden de minuto")
    if esc["partido"]["fin_min"] != orig_esc["partido"]["fin_min"] or ver["fin_min"] != orig_ver["fin_min"] \
            or ver["gracia_min"] != orig_ver["gracia_min"]:
        err.append("se modifico fin_min o gracia_min")
    if ver["escenario_id"] != esc["id"] or esc["id"] != partido["id"]:
        err.append("id de escenario, partido y verdad no coinciden")

    # Verdad vs escenario: cada deteccion en exactamente una fase.
    vistas: Dict[str, int] = {}
    for s in ver["streams"]:
        for f in s["fases"]:
            host, ip = f["host"], f["ip"]
            if host not in dns.get(ip, []):
                err.append(f"stream {s['id']}: host {host} no figura en dns_pasivo[{ip}]")
            for did in f["detecciones"]:
                vistas[did] = vistas.get(did, 0) + 1
                d = dets.get(did)
                if d is None:
                    err.append(f"la verdad cita {did}, que no existe en el escenario")
                    continue
                if d["host_stream"] != host or d["ip_servidor"] != ip:
                    err.append(f"{did}: host/ip de la deteccion no coinciden con su fase")
                if not (f["desde_min"] <= d["minuto"] <= f["hasta_min"]):
                    err.append(f"{did}: minuto {d['minuto']} fuera de [{f['desde_min']}, {f['hasta_min']}]")
    for did in dets:
        if vistas.get(did, 0) != 1:
            err.append(f"{did} aparece en {vistas.get(did, 0)} fases (debe ser exactamente 1)")

    # Tiempos. Los streams de la practica y de las trampas (los primeros n_base) siguen SIEMPRE las
    # reglas estrictas; con --bordes solo se relajan para los streams que agrega _agregar_bordes.
    n_base = len(orig_ver["streams"]) + (3 if trampas else 0)
    for k, s in enumerate(ver["streams"]):
        de_borde = bordes and k >= n_base
        minimo = 0.0 if de_borde else MINUTO_MIN  # un borde admite una fase que arranque en 0..0,5
        previa = None
        for f in s["fases"]:
            if f["desde_min"] < minimo or f["hasta_min"] > fin or f["desde_min"] > f["hasta_min"]:
                err.append(f"stream {s['id']}: fase fuera de rango [{f['desde_min']}, {f['hasta_min']}]")
            if previa is not None:
                # Fases estrictamente separadas. En un stream de borde el verificador oficial
                # admite fases superpuestas (misma sesion en paralelo), asi que solo se exige que
                # no vengan DESORDENADAS: cada desde >= el desde de la fase anterior.
                desordenada = (f["desde_min"] < previa["desde_min"] if de_borde
                               else f["desde_min"] <= previa["hasta_min"])
                if desordenada:
                    err.append(f"stream {s['id']}: fases solapadas o desordenadas")
            previa = f
    for d in esc["detecciones"]:
        tiempos = [d["minuto"], d["captura"]["capturada_min"]] + [p["minuto"] for p in d["promocion"]]
        if min(tiempos) < MINUTO_MIN or max(tiempos) > fin:
            err.append(f"{d['id']}: tiempo fuera de [{MINUTO_MIN}, {fin}]")
    mud = [f["desde_min"] for s in ver["streams"] if s["clase"] == "pirata" for f in s["fases"][1:]]
    if not any(m < CAMBIO_DE_TURNO_MIN for m in mud) or not any(m > CAMBIO_DE_TURNO_MIN for m in mud):
        err.append("falta una mudanza de servidor antes del minuto 50 y otra despues")

    # DNS / ASN / IP.
    if set(esc["ip_asn"]) != set(dns):
        err.append("ip_asn no cubre exactamente las IP de dns_pasivo")
    asn_usados = {str(a) for a in esc["ip_asn"].values()}
    if asn_usados - set(esc["asn"]) or set(esc["asn"]) - asn_usados:
        err.append("asn no coincide con los ASN usados en ip_asn")
    for d in esc["detecciones"]:
        if esc["ip_asn"].get(d["ip_servidor"]) != d["asn"]:
            err.append(f"{d['id']}: asn distinto del de ip_asn")
    todas_ip = list(dns)
    if len(set(todas_ip)) != len(todas_ip):
        err.append("IP repetidas")
    for ip in todas_ip:
        if not ip.startswith(RANGOS_IP) or ip in orig_esc["dns_pasivo"]:
            err.append(f"IP fuera de los rangos de documentacion o heredada de la practica: {ip}")
    for a, org in esc["asn"].items():
        if not (ASN_MIN <= int(a) <= ASN_MAX) or a in orig_esc["asn"]:
            err.append(f"ASN fuera de rango o heredado: {a}")
        if any(w in org.lower() for w in PALABRAS_PROHIBIDAS_EN_ORGANIZACION):
            err.append(f"el nombre de organizacion {org!r} delata el tipo de red")
    if len(set(esc["asn"].values())) != len(esc["asn"]):
        err.append("nombres de organizacion repetidos")

    # Dominios.
    for h in todos_dominios:
        if not (h.endswith(".test") or h.endswith(".example")):
            err.append(f"dominio fuera de .test/.example: {h}")
    for h in ver["dominios_piratas"]:
        if h not in todos_dominios:
            err.append(f"dominio pirata {h} no existe en dns_pasivo")
    for r in esc["reclamos_automaticos"]:
        if r["dominio"] not in todos_dominios:
            err.append(f"reclamo sobre {r['dominio']}, que no existe en dns_pasivo")
        if r["dominio"] in ver["dominios_piratas"]:
            err.append(f"reclamo sobre {r['dominio']}, que es pirata")
    for lic in partido["licenciatarios"]:
        for d in lic["dominios_autorizados"]:
            if d not in todos_dominios:
                err.append(f"dominio autorizado {d} no existe en dns_pasivo")
    # Estructura: cada base de la practica sigue siendo una sola base nueva, y bases distintas siguen distintas.
    bases_nuevas = {partir_host(h)[1] for h in todos_dominios}
    bases_pir = {partir_host(h)[1] for h in ver["dominios_piratas"]}
    for s in ver["streams"]:
        if s["clase"] == "pirata":
            if not {partir_host(f["host"])[1] for f in s["fases"]} <= bases_pir:
                err.append(f"stream {s['id']}: un host pirata no es subdominio de un sitio pirata")
    # Excepcion acotada al borde "inquilinos": en la IP de una fase de BORDE que recomienda
    # "dominio", los otros subdominios del mismo registrable del host son de otros duenos.
    inquilinos_de_borde: set = set()
    if bordes:
        for s in ver["streams"][n_base:]:
            for f in s["fases"]:
                if s["clase"] == "pirata" and f["bloqueo_recomendado"] == "dominio":
                    r = partir_host(f["host"])[1]
                    inquilinos_de_borde |= {d for d in dns.get(f["ip"], []) if d != f["host"] and partir_host(d)[1] == r}
    for h in todos_dominios:
        if partir_host(h)[1] in bases_pir and h not in ver["dominios_piratas"] and h not in inquilinos_de_borde \
                and not any(s["clase"] == "falso_positivo" for s in ver["streams"] if any(f["host"] == h for f in s["fases"])):
            err.append(f"{h} comparte base con un sitio pirata pero no figura como pirata")
    if len(bases_nuevas) < 5:
        err.append("pocas bases de dominio: se perdio la estructura")

    # Marcas / sesiones.
    prefijos = [m["prefijo"] for m in partido["marcas_de_agua_validas"]]
    prefijos_lic = [l["prefijo_marca"] for l in partido["licenciatarios"]]
    for pl in prefijos_lic:
        if pl not in prefijos:
            err.append("el prefijo del licenciatario no figura en marcas_de_agua_validas")
    sesion_de_stream: Dict[str, set] = {}
    stream_de = {did: s["id"] for s in ver["streams"] for f in s["fases"] for did in f["detecciones"]}
    for d in esc["detecciones"]:
        m = d["marca_de_agua_extraida"]
        if m.startswith("LP25-"):
            if any(m.startswith(p) for p in prefijos):
                err.append(f"{d['id']}: la marca ajena {m} paso a ser valida")
        elif m and not any(m.startswith(p) for p in prefijos):
            err.append(f"{d['id']}: marca {m!r} sin prefijo valido ni forma de partido ajeno")
        sesion_de_stream.setdefault(stream_de.get(d["id"], "?"), set()).add(m)
    for sid, marcas in sesion_de_stream.items():
        if len(marcas) != 1:
            err.append(f"stream {sid}: la marca/sesion cambia entre fases: {sorted(marcas)}")
    con_sesion = [next(iter(m)) for m in sesion_de_stream.values() if re.search(r"-S\d{6}$", next(iter(m)))]
    if len(set(con_sesion)) != len(con_sesion):
        err.append("dos streams comparten sesion")

    # Capturas.
    for d in esc["detecciones"]:
        try:
            raw = base64.b64decode(d["captura"]["contenido_b64"], validate=True)
        except Exception:
            err.append(f"{d['id']}: captura no es base64 valido")
            continue
        if len(raw) != 64 or raw[0] != 0x47:
            err.append(f"{d['id']}: la captura debe tener 64 bytes y empezar con 0x47")

    # Nada de la practica sobrevive.
    err.extend(_buscar_restos_de_la_practica(esc, ver, orig_esc, orig_ver))

    if trampas:
        err.extend(_verificar_trampas(esc, ver))
    if bordes:
        err.extend(_verificar_bordes(esc, ver, orig_ver, trampas))
    return err


def _tokens_originales(orig_esc: dict, orig_ver: dict) -> Tuple[List[str], List[str], List[str], set]:
    """(frases, dominios, ips, asn) de la practica que no pueden reaparecer."""
    p = orig_esc["partido"]
    frases = [orig_esc["id"], orig_ver["escenario_id"], p["titular_derechos"], p["id"]]
    resto = p["nombre"].split("—", 1)[-1].strip()
    frases += [c.strip() for c in resto.split(" vs. ")]
    frases += [l["nombre"] for l in p["licenciatarios"]]
    frases += list(orig_esc["asn"].values())
    frases += [s["id"] for s in orig_ver["streams"]]
    prefijos = [m["prefijo"] for m in p["marcas_de_agua_validas"]]
    frases += prefijos
    for d in orig_esc["detecciones"]:
        m = d["marca_de_agua_extraida"]
        if m and m not in prefijos:
            frases.append(m)
            frases.append(m.rsplit("-", 1)[-1])  # sesion
    dominios: List[str] = []
    for doms in orig_esc["dns_pasivo"].values():
        dominios.extend(doms)
    for d in orig_esc["detecciones"]:
        dominios.extend(urlsplit(u).hostname or "" for u in (d["pagina"], d["stream_url"]))
    etiquetas = [etiqueta_base(partir_host(h)[1]) for h in dict.fromkeys(dominios) if h]
    for d in orig_esc["detecciones"]:  # redes sociales: el host es un dominio a renombrar, pero no su etiqueta ("discord" es la red)
        dominios.extend(urlsplit(pr["url"]).hostname or "" for pr in d["promocion"])
        frases.extend(pr["url"] for pr in d["promocion"])
    frases += [r["mensaje"] for r in orig_esc["reclamos_automaticos"]]
    dominios = list(dict.fromkeys(x for x in dominios if x))
    frases += [e for e in etiquetas if len(e) >= 6]
    ips = list(orig_esc["dns_pasivo"]) + list(orig_esc["ip_asn"])
    return frases, dominios, list(dict.fromkeys(ips)), {int(a) for a in orig_esc["asn"]}


def _buscar_restos_de_la_practica(esc: dict, ver: dict, orig_esc: dict, orig_ver: dict) -> List[str]:
    frases, dominios, ips, asns = _tokens_originales(orig_esc, orig_ver)
    err: List[str] = []
    cadenas: List[str] = []
    enteros: set = set()
    for doc in (esc, ver):
        for tipo, v in _recorrer(doc):
            if tipo == "cadena":
                cadenas.append(v)
            else:
                enteros.add(v)
    texto = "\n".join(cadenas)
    for fr in frases:
        if fr and fr in texto:
            err.append(f"sobrevive texto de la practica: {fr!r}")
    for dom in dominios:
        if re.search(r"(?<![\w-])" + re.escape(dom), texto):
            err.append(f"sobrevive dominio de la practica: {dom}")
    for ip in ips:
        if re.search(r"(?<![\d.])" + re.escape(ip) + r"(?![\d])", texto):
            err.append(f"sobrevive IP de la practica: {ip}")
    for a in asns:
        if a in enteros or str(a) in {c for c in cadenas if c.isdigit()}:
            err.append(f"sobrevive ASN de la practica: {a}")
    return err


def _verificar_trampas(esc: dict, ver: dict) -> List[str]:
    err: List[str] = []
    dets = {d["id"]: d for d in esc["detecciones"]}
    prefijos_lic = [l["prefijo_marca"] for l in esc["partido"]["licenciatarios"]]
    dominios_lic = {d for l in esc["partido"]["licenciatarios"] for d in l["dominios_autorizados"]}
    bases_lic = {partir_host(d)[1] for d in dominios_lic}
    sin_marca = [s for s in ver["streams"] if s["clase"] == "falso_positivo"
                 and all(dets[i]["marca_de_agua_extraida"] == "" for f in s["fases"] for i in f["detecciones"])]
    if not sin_marca:
        err.append("trampa 1: falta el falso positivo sin marca de agua")
    for s in sin_marca:
        for f in s["fases"]:
            if len(esc["dns_pasivo"][f["ip"]]) > 2 or f["bloqueo_recomendado"] is not None:
                err.append("trampa 1: el falso positivo debe tener IP propia y sin bloqueo recomendado")
    retrans = [s for s in ver["streams"] if s["clase"] == "pirata" and len(s["fases"]) == 1
               and any(dets[i]["marca_de_agua_extraida"] in prefijos_lic for i in s["fases"][0]["detecciones"])]
    if not retrans:
        err.append("trampa 2: falta el pirata que retransmite la senal del licenciatario")
    for s in retrans:
        f = s["fases"][0]
        if partir_host(f["host"])[1] in bases_lic or f["host"] in dominios_lic:
            err.append("trampa 2: el host debe ser ajeno al licenciatario")
        if f["bloqueo_recomendado"] != "ip" or len(f["detecciones"]) != 3 or esc["dns_pasivo"][f["ip"]] != [f["host"]]:
            err.append("trampa 2: debe recomendar ip, tener 3 detecciones y una IP exclusiva")
        if f["host"] not in ver["dominios_piratas"]:
            err.append("trampa 2: el host no esta en dominios_piratas")
    compartida = [s for s in ver["streams"] if s["clase"] == "pirata" and len(s["fases"]) == 1
                  and len(esc["dns_pasivo"][s["fases"][0]["ip"]]) == 2 and s["fases"][0]["bloqueo_recomendado"] == "dominio"
                  and s["fases"][0]["host"] not in dominios_lic]
    # Debe haber una distinta de los pirata de la practica: la que tiene un unico legitimo y su reclamo.
    ok3 = False
    for s in compartida:
        f = s["fases"][0]
        otros = [d for d in esc["dns_pasivo"][f["ip"]] if d != f["host"]]
        if len(otros) == 1 and otros[0] not in ver["dominios_piratas"] \
                and any(r["dominio"] == otros[0] for r in esc["reclamos_automaticos"]):
            ok3 = True
    if not ok3:
        err.append("trampa 3: falta el pirata que comparte IP con un unico sitio legitimo (con reclamo asociado)")
    return err


def _verificar_bordes(esc: dict, ver: dict, orig_ver: dict, trampas: bool) -> List[str]:
    """Contratos de los bordes, comprobados solo desde esc/ver (sin estado del generador).

    Mira los streams agregados despues de los de la practica (y, si estan, de las 3 trampas).
    """
    err: List[str] = []
    dns = esc["dns_pasivo"]
    piratas = set(ver["dominios_piratas"])
    n_base = len(orig_ver["streams"]) + (3 if trampas else 0)
    nuevos = ver["streams"][n_base:]
    if len(nuevos) < 10:
        err.append(f"bordes: se esperaban al menos 10 streams de borde, hay {len(nuevos)}")
    pir = [s for s in nuevos if s["clase"] == "pirata"]
    if len(pir) != len(nuevos):
        err.append("bordes: todos los streams de borde deben ser clase pirata")
    dets = {d["id"]: d for d in esc["detecciones"]}
    turno = CAMBIO_DE_TURNO_MIN

    def sesiones(s) -> set:
        return {dets[i]["marca_de_agua_extraida"] for f in s["fases"] for i in f["detecciones"] if i in dets}

    # B1: una filtracion NUEVA (stream de una sola fase) con primera deteccion justo antes del
    # minuto 50 y otra justo despues. Solo cuentan streams de una fase: la mudanza-turno (B2) tambien
    # tiene un desde en (50 ; 50,2] y no puede tapar la falta de este borde.
    primeras = []
    for s in pir:
        if len(s["fases"]) == 1:
            f = s["fases"][0]
            mins = [dets[i]["minuto"] for i in f["detecciones"] if i in dets]
            primeras.append(min(mins) if mins else f["desde_min"])
    if not any(turno - 0.2 <= x < turno for x in primeras):
        err.append("borde turno: falta una filtracion nueva con primera deteccion en [49,8 ; 50,0)")
    if not any(turno < x <= turno + 0.2 for x in primeras):
        err.append("borde turno: falta una filtracion nueva con primera deteccion en (50,0 ; 50,2]")

    # B2 (mudanza-turno): un stream de UNA sola sesion, con 3 fases o mas, que se muda en
    # [turno - 0,5 ; turno) y en la fase siguiente en (turno ; turno + 0,2].
    def muda_en_el_turno(s) -> bool:
        if len(s["fases"]) < 3 or len(sesiones(s)) != 1 or not re.search(r"-S\d{6}$", next(iter(sesiones(s)))):
            return False
        return any(turno - 0.5 <= a["desde_min"] < turno < b["desde_min"] <= turno + 0.2
                   for a, b in zip(s["fases"], s["fases"][1:]))
    if not any(muda_en_el_turno(s) for s in pir):
        err.append("borde mudanza-turno: falta un stream de una sola sesion (3+ fases) que se mude en "
                   "[49,5 ; 50) y otra vez en (50 ; 50,2]")

    # B3: una fase de duracion cero en el minuto exacto del final.
    fin = float(esc["partido"]["fin_min"])
    if not any(f["desde_min"] == fin and f["hasta_min"] == fin for s in pir for f in s["fases"]):
        err.append("borde final: falta una fase de duracion cero en el minuto del final")
    # B3: una filtracion que empieza en los ultimos ~3 minutos.
    if not any(fin - 3.0 <= f["desde_min"] <= fin - 2.0 for s in pir for f in s["fases"]):
        err.append("borde final: falta una filtracion nueva en los ultimos minutos")

    # B4: un stream con 4+ fases encadenadas y algun salto < 1,5 min.
    def saltos(s):
        d = [f["desde_min"] for f in s["fases"]]
        return [b - a for a, b in zip(d, d[1:])]
    if not any(len(s["fases"]) >= 4 and any(0 < x < 1.5 for x in saltos(s)) for s in pir):
        err.append("borde mudanzas rapidas: falta un stream con 4+ fases y saltos < 1,5 min")

    # B5: un stream donde una fase posterior repite (host, ip) de una fase anterior.
    def hay_vuelta(s):
        vistos = set()
        for f in s["fases"]:
            par = (f["host"], f["ip"])
            if par in vistos:
                return True
            vistos.add(par)
        return False
    if not any(hay_vuelta(s) for s in pir):
        err.append("borde vuelve: ningun stream reutiliza un (host, ip) anterior")

    # B6: un stream con dos fases superpuestas en el tiempo y distinto (host, ip).
    def hay_paralelo(s):
        for a, b in [(a, b) for i, a in enumerate(s["fases"]) for b in s["fases"][i + 1:]]:
            solapan = a["desde_min"] < b["hasta_min"] and b["desde_min"] < a["hasta_min"]
            if solapan and (a["host"], a["ip"]) != (b["host"], b["ip"]):
                return True
        return False
    if not any(hay_paralelo(s) for s in pir):
        err.append("borde paralelo: falta un stream con dos fases simultaneas")

    # B7: un stream con una fase 'dominio' cuya IP aloja sitios ajenos (legitimos, no piratas).
    ok_comp = False
    for s in pir:
        for f in s["fases"]:
            if f["bloqueo_recomendado"] == "dominio":
                ajenos = [d for d in dns.get(f["ip"], []) if d not in piratas]
                if ajenos:
                    ok_comp = True
    if not ok_comp:
        err.append("borde IP compartida: falta una fase 'dominio' con legitimos ajenos en su IP")

    # B8 (inquilinos): una fase pirata cuyo host es un subdominio h de un registrable R, en una IP
    # de organizacion neutra que aloja h y de 1 a 3 subdominios de OTROS duenos de R (no piratas, ni
    # R ni www.R); toda pagina y stream_url de la fase vive en h (no en R ni en www.R), la verdad
    # recomienda "dominio" y alguno de los inquilinos tiene un reclamo automatico.
    def problemas_inquilinos(f) -> List[str]:
        host = f["host"]
        sub, r = partir_host(host)
        doms = dns.get(f["ip"], [])
        otros = [d for d in doms if d != host]
        p: List[str] = []
        if not sub or sub == "www":
            p.append("el host no es un subdominio propio del registrable")
        if not (1 <= len(otros) <= 3) or any(partir_host(d)[1] != r or d in (r, "www." + r) for d in otros):
            p.append("la IP debe alojar de 1 a 3 subdominios de otros duenos del mismo registrable")
        if any(d in piratas for d in otros):
            p.append("un inquilino figura como pirata")
        org = esc["asn"].get(str(esc["ip_asn"].get(f["ip"])), "")
        if any(w in org.lower() for w in ("cdn", "compartid", "shared")):
            p.append("la organizacion delata una red compartida")
        for i in f["detecciones"]:
            d = dets.get(i, {})
            if urlsplit(d.get("pagina", "")).hostname != host or urlsplit(d.get("stream_url", "")).hostname != host:
                p.append("la pagina y el stream tienen que vivir en el subdominio del pirata")
                break
        if f["bloqueo_recomendado"] != "dominio":
            p.append("con inquilinos ajenos la verdad tiene que recomendar 'dominio'")
        if not any(rc["dominio"] in otros for rc in esc["reclamos_automaticos"]):
            p.append("falta el reclamo automatico de un inquilino")
        return p
    candidatas = [f for s in pir if len(s["fases"]) == 1 for f in s["fases"]
                  if any(d != f["host"] and partir_host(d)[1] == partir_host(f["host"])[1]
                         for d in dns.get(f["ip"], []))]
    if not candidatas:
        err.append("borde inquilinos: falta una fase cuya IP aloje otros subdominios del mismo registrable")
    elif all(problemas_inquilinos(f) for f in candidatas):
        for f in candidatas:
            for p in problemas_inquilinos(f):
                err.append(f"borde inquilinos ({f['host']}): {p}")

    # Todos los hosts pirata de los bordes estan en dominios_piratas y los ajenos NO.
    for s in pir:
        for f in s["fases"]:
            if f["host"] not in piratas:
                err.append(f"borde: el host pirata {f['host']} no figura en dominios_piratas")
            for d in dns.get(f["ip"], []):
                if d != f["host"] and d in piratas and not any(
                        ff["host"] == d for ss in pir for ff in ss["fases"]):
                    err.append(f"borde: el dominio {d} figura como pirata sin ser host de ninguna fase")
    return err


# --------------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------------
def cargar_json(ruta: Path) -> Any:
    with ruta.open(encoding="utf-8") as f:
        return json.load(f)


def escribir_json(ruta: Path, datos: Any) -> None:
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Genera un partido espejo del Desafio Futbol (escenario.json + verdad.json)")
    ap.add_argument("--repo-desafio", type=Path, required=True, help="carpeta del repo oficial (solo lectura)")
    ap.add_argument("--semilla", type=int, default=7)
    ap.add_argument("--salida", type=Path, required=True, help="carpeta donde escribir escenario.json y verdad.json")
    ap.add_argument("--trampas", action="store_true", help="agrega falso positivo sin marca, pirata con senal del licenciatario y pirata en IP con un solo legitimo")
    ap.add_argument("--bordes", action="store_true", help="agrega bordes de tiempo y combinacion que el simulador admite (cambio de turno, ultimos minutos, mudanzas muy juntas, servidores en paralelo y reusados, IP compartida); combinable con --trampas")
    a = ap.parse_args(argv)

    orig_esc = cargar_json(a.repo_desafio / "datos" / "escenario_practica.json")
    orig_ver = cargar_json(a.repo_desafio / "evaluacion" / "verdad_practica.json")
    esc, ver = generar(orig_esc, orig_ver, a.semilla, a.trampas, a.bordes)
    errores = verificar_coherencia(esc, ver, orig_esc, orig_ver, a.trampas, a.bordes)
    if errores:
        print("El espejo generado no paso las comprobaciones; no se escribio nada:", file=sys.stderr)
        for e in errores:
            print(f"  - {e}", file=sys.stderr)
        return 1
    a.salida.mkdir(parents=True, exist_ok=True)
    escribir_json(a.salida / "escenario.json", esc)
    escribir_json(a.salida / "verdad.json", ver)
    extras = "".join(x for x in (", con trampas" if a.trampas else "", ", con bordes" if a.bordes else ""))
    print(f"Espejo {esc['id']} escrito en {a.salida} ({len(esc['detecciones'])} detecciones, "
          f"{len(ver['streams'])} streams{extras}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
