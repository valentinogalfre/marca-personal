"""Kit del proveedor: líneas de ejemplo para MikroTik, nftables, Unbound y BIND (RPZ), y la lista que su equipo
lee solo (ESPEC 5.1 y 5.2; ADENDA-3, punto D). Funciones puras: sin red, sin estado, sin reloj.

Estas líneas se pegan en un router. Por eso todo dato de entrada pasa por una validación estricta antes de
aparecer en la salida: si algo no valida, `kit()` no genera ningún comando y las listas omiten esa entrada.

Fuentes de cada línea: la investigación del kit contrastada con la documentación oficial (manual de RouterOS
7.25 y ayuda heredada de v6, man de nft y wiki de nftables, manual de unbound-control, referencia de BIND 9.20).
Nada de esto se probó en un equipo real: de ahí la leyenda.
"""
from __future__ import annotations

import datetime
import ipaddress
import math
import re
from typing import Any, Dict, List, Optional, Tuple

from .canon import min_txt
from .dominios import SUFIJOS_SEGUNDO_NIVEL, objetivo_valido

LEYENDA = ("Probá estas líneas en tu equipo antes del partido. Lo que obliga es la orden (objetivo y "
           "vencimiento); las líneas son una ayuda.")
NO_RIGE = "Esta orden ya no rige. Si la aplicaste, quitala."
ALCANCE_UNBOUND = ("Corta ese nombre y los que cuelgan de él (sus subdominios). No toca el dominio de arriba ni a "
                   "sus nombres hermanos. Vive en memoria: un reload o un reinicio lo borra; no vence solo: usá la "
                   "lista del proveedor o corré la línea de quitar al final.")
DATOS_NO_COMANDOS = "Son datos, no comandos: su equipo decide cómo aplicarlos."
CADA_LINEA_UNBOUND = "Cada línea corta el nombre y sus subdominios."
LINEAS_TRANSPARENT = ("Las líneas transparent son sitios ajenos que cuelgan de un nombre bloqueado: siguen "
                      "resolviendo.")
MAX_NO_CORTAR = 100  # nombres ajenos por orden (kit-2): un tope para que una vista rara no infle el archivo

EQUIPO_MIKROTIK = "MikroTik RouterOS 6 y 7"
LISTA_MIKROTIK = "bloqueo-judicial"
TABLA_NFT = "inet bloqueo_judicial"
ZONA_RPZ = "rpz.local"
MESES = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_SELLO = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_HORA = re.compile(r"^([01][0-9]|2[0-3]):([0-5][0-9])(?::([0-5][0-9]))?$")
_FECHA = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_NOMBRE_OK = set(" .,()-_/'&")
# Última barrera antes del equipo del proveedor: TODO el valor tiene que cumplir (fullmatch), sin espacios,
# saltos de línea, comillas, «;» ni zona IPv6 («%eth0»).
_IP_CHARS = re.compile(r"[0-9A-Fa-f:.]+")
_HOST_CHARS = re.compile(r"[a-z0-9_-]+(?:\.[a-z0-9_-]+)*")  # «_» vale, como en dominios.es_hostname (C16, kit-5)
OBJETIVO_NO_VALIDO = ("El objetivo de esta orden no es una IP ni un nombre de host válido: no se arma ninguna "
                      "línea para el router. No pegues nada y avisale al juzgado que figura en la orden.")


# --- validación ---------------------------------------------------------------------------------------

def _numero(x: Any) -> Optional[float]:
    """Un número finito (nunca un bool ni un texto), o None."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    x = float(x)
    return x if math.isfinite(x) else None


def _ip(texto: Any) -> Optional[ipaddress._BaseAddress]:
    """IP que se puede bloquear, o None. Sin zona IPv6 (`%eth0`), ni loopback, multicast, enlace local o 0.0.0.0."""
    if not isinstance(texto, str) or not _IP_CHARS.fullmatch(texto) or not objetivo_valido("ip", texto):
        return None
    try:
        dir_ = ipaddress.ip_address(texto)
    except ValueError:
        return None
    if dir_.is_unspecified or dir_.is_loopback or dir_.is_multicast or dir_.is_link_local:
        return None
    return dir_


def _host(texto: Any) -> Optional[str]:
    """Nombre de host normalizado, o None. Además de `dominios.objetivo_valido` (que ya descarta los disparadores
    de RPZ, kit-3): al menos dos rótulos, nunca un sufijo de registro (com.ar) ni un rótulo final numérico. En
    Unbound la línea corta también los subdominios: un «com» colado cortaría medio internet."""
    if not isinstance(texto, str) or not texto.isascii():
        return None  # antes de lower(): el signo Kelvin se volvería una «k»
    h = texto.lower()
    if h.endswith("."):
        h = h[:-1]  # el punto final y las mayúsculas no cambian el nombre; nada más se corrige
    if len(h) > 253 or not _HOST_CHARS.fullmatch(h) or not objetivo_valido("dominio", h):
        return None
    rotulos = h.split(".")
    if len(rotulos) < 2 or h in SUFIJOS_SEGUNDO_NIVEL or rotulos[-1].isdigit():
        return None
    return h


def objetivo_seguro(tipo: Any, objetivo: Any) -> Optional[str]:
    """El objetivo en forma canónica (lo único que llega a una línea de router), o None si no valida."""
    if tipo == "ip":
        dir_ = _ip(objetivo)
        return str(dir_) if dir_ is not None else None
    if tipo == "dominio":
        return _host(objetivo)
    return None


def _hora(x: Any) -> Optional[str]:
    """"HH:MM" o "HH:MM:SS" → "HH:MM:SS"; otra cosa → None."""
    if not isinstance(x, str):
        return None
    m = _HORA.fullmatch(x)
    if not m:
        return None
    return f"{m.group(1)}:{m.group(2)}:{m.group(3) or '00'}"


def _fecha(x: Any) -> Optional[datetime.date]:
    if not isinstance(x, str) or not _FECHA.fullmatch(x):
        return None
    try:
        return datetime.date(int(x[:4]), int(x[5:7]), int(x[8:10]))
    except ValueError:
        return None


def _hora_corta(hms: str) -> str:
    return hms[:5] if hms.endswith(":00") else hms


def _num(x: float) -> str:
    """Minutos para leer: sin decimales si es entero; si no, un decimal con coma. Ronda 3 (C8): el mismo
    redondeo que todo lo demás (canon.min_txt), sin el «,0» de los enteros."""
    t = min_txt(x)
    return t[:-2] if t.endswith(",0") else t


def duracion_mikrotik(minutos: float) -> str:
    total = max(1, int(math.ceil(minutos)))
    h, m = divmod(total, 60)
    return f"{h}h{m}m" if h else f"{m}m"


# --- kit por orden (5.1) ------------------------------------------------------------------------------

def kit(tipo: str, objetivo: str, vence_min: float, minuto_actual: Optional[float], expediente: str, sello: str, *,
        vigente: bool = True, hora_vence: Optional[str] = None, fecha_vence: Optional[str] = None,
        acelerar: float = 1.0) -> List[dict]:
    """Líneas de ejemplo para aplicar (o quitar) una orden.

    Cada entrada: `{equipo, preparar (una sola vez, puede faltar), aplicar (falta si la orden ya no rige), quitar,
    vencer (puede faltar), nota}`. `hora_vence` es la hora del vencimiento ("HH:MM" o "HH:MM:SS", hora del
    partido); `fecha_vence`, su fecha ("AAAA-MM-DD"). `acelerar` (kit-1) es la velocidad del reloj del partido
    (1 en la vida real): el router cuenta minutos reales, así que el timeout sale en minutos reales; con el partido
    acelerado, quien llama pasa en `hora_vence` y `fecha_vence` la hora real del vencimiento.

    Si el objetivo (o el tipo) no valida, devuelve una sola entrada que lo dice, sin ninguna línea de comando.
    Si no valida otro dato (expediente, sello, minutos, hora, fecha o `acelerar`, que tiene que ser un número
    finito mayor que 0), devuelve [].
    """
    obj = objetivo_seguro(tipo, objetivo)
    if obj is None:
        return [{"equipo": "Objetivo no válido", "nota": OBJETIVO_NO_VALIDO}]
    vence = _numero(vence_min)
    minuto = 0.0 if minuto_actual is None else _numero(minuto_actual)
    acel = _numero(acelerar)
    hms = None if hora_vence is None else _hora(hora_vence)
    fecha = None if fecha_vence is None else _fecha(fecha_vence)
    if (vence is None or minuto is None or acel is None or acel <= 0
            or not isinstance(expediente, str) or not _ID.fullmatch(expediente)
            or not isinstance(sello, str) or not _SELLO.fullmatch(sello)
            or (hora_vence is not None and hms is None) or (fecha_vence is not None and fecha is None)):
        return []
    # El router cuenta minutos reales: con el partido acelerado, un minuto de partido dura 1/acelerar minutos.
    faltan = max(1.0, (vence - minuto) / acel)
    corto = sello[:8]
    cuando = f"vence {_hora_corta(hms)}" if hms else f"vence min {_num(vence)}"
    comentario = f"{expediente} {corto} {cuando}"
    a_las = f"a las {_hora_corta(hms)}" if hms else f"en el minuto {_num(vence)} del partido"
    if tipo == "ip":
        entradas = _kit_ip(obj, faltan, comentario, a_las)
    else:
        entradas = _kit_dominio(obj, comentario, a_las, f"vence-{expediente}-{corto}", hms, fecha, vence)
    if acel != 1.0:
        aviso = (f" El partido corre acelerado (x{_num(acel)}): el timeout ya está pasado a minutos reales"
                 + (" y la hora es la del reloj real." if hms else "."))
        for e in entradas:
            e["nota"] = e["nota"] + aviso
    if not vigente:
        return [{"equipo": e["equipo"], "quitar": e["quitar"], "nota": _nota_no_rige(e)} for e in entradas]
    return entradas


def _nota_no_rige(e: dict) -> str:
    if "\n" in e["quitar"] and "scheduler" in e["quitar"]:
        return NO_RIGE + " La segunda línea borra la tarea programada del vencimiento, si la cargaste."
    return NO_RIGE


def _kit_ip(obj: str, faltan: float, comentario: str, a_las: str) -> List[dict]:
    v6 = ":" in obj
    fam = "/ipv6" if v6 else "/ip"
    def pegar(aclaracion: str = "") -> str:
        return (f"El timeout cuenta desde que pegás la línea, no desde que se generó: la orden vence {a_las}"
                f"{aclaracion}. Si la pegaste tarde, quitala a esa hora. ")
    if v6:
        cortar = ("En IPv6 no damos la línea para cortar las conexiones ya abiertas: la dirección de la conexión "
                  "también lleva «:» y una búsqueda por texto podría cortar otras. Buscalas con /ipv6 firewall "
                  "connection print y borralas a mano. ")
    else:
        cortar = (f'Para cortar a quien ya está mirando: /ip firewall connection remove [find where '
                  f'dst-address~"^{obj}(:|$)"] (probalo antes en tu equipo). ')
    mikrotik = {
        "equipo": EQUIPO_MIKROTIK,
        "preparar": f'{fam} firewall filter add chain=forward dst-address-list={LISTA_MIKROTIK} action=drop '
                    'comment="bloqueo judicial" place-before=0',
        "aplicar": f'{fam} firewall address-list add list={LISTA_MIKROTIK} address={obj} '
                   f'timeout={duracion_mikrotik(faltan)} comment="{comentario}"',
        "quitar": f"{fam} firewall address-list remove [find list={LISTA_MIKROTIK} address={obj}]",
        "nota": ("La línea de preparar se pega una sola vez y tiene que quedar antes de la regla "
                 "fasttrack-connection; si no, las conexiones ya abiertas siguen. Si el router no acepta "
                 f"place-before=0, corré antes {fam} firewall filter print y volvé a pegarla. " + cortar
                 + pegar(" (está en el comentario)") + "La entrada con timeout se borra si el router se reinicia: si reinicia durante el partido, "
                   "volvé a pegarla. " + LEYENDA),
    }
    conjunto, tipo_set, campo = ("objetivos6", "ipv6_addr", "ip6") if v6 else ("objetivos", "ipv4_addr", "ip")
    nft = {
        "equipo": "nftables",
        "preparar": "\n".join([
            f"nft add table {TABLA_NFT}",
            f"nft add set {TABLA_NFT} {conjunto} '{{ type {tipo_set}; flags timeout; }}'",
            f"nft add chain {TABLA_NFT} forward '{{ type filter hook forward priority -10; policy accept; }}'",
            f"nft add rule {TABLA_NFT} forward {campo} daddr @{conjunto} drop"]),
        "aplicar": f"nft add element {TABLA_NFT} {conjunto} '{{ {obj} timeout {int(math.ceil(faltan))}m }}'",
        "quitar": f"nft delete element {TABLA_NFT} {conjunto} '{{ {obj} }}'",
        "nota": ("La línea de preparar se pega una sola vez: crea una tabla propia (bloqueo_judicial) que corta el "
                 "tráfico que atraviesa este equipo sin tocar tu firewall. Si usás flowtable, esta tabla tiene que "
                 "cortar antes del flow add; si no, los flujos ya abiertos siguen. "
                 + pegar() + "Si el elemento ya venció, la línea de quitar puede avisar que no existe. " + LEYENDA),
    }
    return [mikrotik, nft]


def _kit_dominio(obj: str, comentario: str, a_las: str, tarea: str, hms: Optional[str],
                 fecha: Optional[datetime.date], vence: float) -> List[dict]:
    borrar = f"/ip dns static remove [find name={obj}]"
    mikrotik = {
        "equipo": EQUIPO_MIKROTIK,
        "aplicar": f'/ip dns static add name={obj} type=NXDOMAIN comment="{comentario}"\n/ip dns cache flush',
        "quitar": f"{borrar}\n/system scheduler remove [find name={tarea}]",
    }
    alcance_exacto = ("Corta solo el nombre exacto: no toca sus subdominios, ni el dominio de arriba, ni sus nombres "
                      "hermanos. ")
    nota = (alcance_exacto + "RouterOS 6.47 o posterior y el reloj en hora; solo alcanza a los abonados que usan "
            "este router como DNS. El bloqueo por DNS no vence solo. ")
    if hms:
        mikrotik["vencer"] = (f'/system scheduler add name={tarea} start-time={hms} interval=0s '
                              f'on-event="{borrar}"')
        if fecha:
            iso = fecha.isoformat()
            viejo = f"{MESES[fecha.month - 1]}/{fecha.day:02d}/{fecha.year:04d}"
        else:
            iso, viejo = "AAAA-MM-DD", "mmm/dd/aaaa"
        nota += (f"La línea de vencer programa el borrado {a_las} (hora del router). No lleva fecha porque RouterOS "
                 "6 y 7 la escriben distinto: corre a esa hora del mismo día en que la pegás. Si el vencimiento cae "
                 f"otro día, agregale la fecha como la muestra /system clock print: start-date={iso} en RouterOS 7 "
                 f"o start-date={viejo} en RouterOS 6. Si no cargás la tarea, corré la línea de quitar a esa hora. ")
    else:
        nota += (f"Sin la hora del vencimiento no se arma la línea de vencer: corré la línea de quitar en el minuto "
                 f"{_num(vence)} del partido. ")
    mikrotik["nota"] = nota + LEYENDA
    unbound = {
        "equipo": "Unbound",
        "aplicar": f"unbound-control local_zone {obj}. always_nxdomain",
        "quitar": f"unbound-control local_zone_remove {obj}.",
        "nota": (ALCANCE_UNBOUND + f" La orden vence {a_las}. Solo alcanza a quienes usan este servidor como DNS. "
                 + LEYENDA),
    }
    nombre_rpz = f"{obj}.{ZONA_RPZ}."
    bind = {
        "equipo": "BIND (RPZ)",
        "preparar": "\n".join([
            "# en named.conf, una sola vez:",
            f'zone "{ZONA_RPZ}" {{ type primary; file "{ZONA_RPZ}"; update-policy local; }};',
            "# y dentro de options:",
            f'response-policy {{ zone "{ZONA_RPZ}"; }} min-update-interval 5;']),
        "aplicar": f"printf 'zone {ZONA_RPZ}\\nupdate add {nombre_rpz} 60 CNAME .\\nsend\\n' | nsupdate -l",
        "quitar": f"printf 'zone {ZONA_RPZ}\\nupdate delete {nombre_rpz} CNAME\\nsend\\n' | nsupdate -l",
        "nota": ("Corta solo el nombre exacto: no toca sus subdominios, ni el dominio de arriba, ni sus nombres "
                 "hermanos. El archivo rpz.local tiene que existir con su SOA y su NS (podés partir del rpz.zone de "
                 "la lista del proveedor). BIND aplica los cambios de una zona RPZ como mucho una vez cada "
                 "min-update-interval (60 s si no lo cambiás): por eso preparar lo baja a 5 s. En versiones viejas "
                 "de BIND se escribe type master en lugar de type primary. Solo alcanza a quienes usan este "
                 f"servidor como DNS. El bloqueo por DNS no vence solo: corré la línea de quitar {a_las}. "
                 + LEYENDA),
    }
    return [mikrotik, unbound, bind]


# --- lista del proveedor (5.2) ------------------------------------------------------------------------

def _dic(x: Any) -> dict:
    return x if isinstance(x, dict) else {}


def _texto_cabecera(x: Any, largo: int = 80) -> Optional[str]:
    """Un nombre para un comentario: solo letras, dígitos y . , ( ) - _ / ' &; sin saltos de línea."""
    if not isinstance(x, str):
        return None
    limpio = "".join(c for c in x if c.isalnum() or c in _NOMBRE_OK)
    limpio = " ".join(limpio.split())[:largo]
    return limpio or None


def _hora_vista(x: Any) -> Optional[str]:
    hms = _hora(x)
    return _hora_corta(hms) if hms else None


def _objetivos(vista: dict, tipo: str) -> Tuple[List[str], int]:
    """Los objetivos vigentes de un tipo, validados, sin repetir y en orden fijo; y cuántos se descartaron por
    formato inválido (los que no son de este tipo o ya vencieron no cuentan)."""
    minuto = _numero(vista.get("minuto"))
    vigentes = vista.get("vigentes")
    hallados = set()
    descartados = 0
    for o in vigentes if isinstance(vigentes, list) else []:
        if not isinstance(o, dict) or o.get("tipo") != tipo:
            continue
        vence = _numero(o.get("vence_min"))
        if vence is None or (minuto is not None and vence <= minuto):
            continue  # sin vencimiento, o ya vencida según la misma lista: no rige
        obj = objetivo_seguro(tipo, o.get("objetivo"))
        if obj is None:
            descartados += 1
        else:
            hallados.add(obj)
    if tipo == "ip":
        return sorted(hallados, key=lambda s: (ipaddress.ip_address(s).version, ipaddress.ip_address(s))), descartados
    return sorted(hallados), descartados


def _no_cortar(valor: Any, objetivo: str) -> List[str]:
    """Los nombres ajenos conocidos que cuelgan de `objetivo` (campo opcional `no_cortar` de una vigente por dominio,
    kit-2), validados como cualquier objetivo, sin repetir y en orden. Lo que no valida o no cuelga de `objetivo`
    se ignora."""
    if not isinstance(valor, list):
        return []
    nombres = set()
    for n in valor[:MAX_NO_CORTAR]:
        h = objetivo_seguro("dominio", n)
        if h is not None and h.endswith("." + objetivo):
            nombres.add(h)
    return sorted(nombres)


def _excepciones(vista: dict, hosts: List[str]) -> List[str]:
    """Nombres que Unbound tiene que dejar resolver: los `no_cortar` de las vigentes por dominio que cuelgan de un
    nombre bloqueado en esta misma lista y que no están bloqueados ellos mismos."""
    minuto = _numero(vista.get("minuto"))
    bloqueados = set(hosts)
    vigentes = vista.get("vigentes")
    salida = set()
    for o in vigentes if isinstance(vigentes, list) else []:
        if not isinstance(o, dict) or o.get("tipo") != "dominio":
            continue
        vence = _numero(o.get("vence_min"))
        obj = objetivo_seguro("dominio", o.get("objetivo"))
        if obj is None or obj not in bloqueados or vence is None or (minuto is not None and vence <= minuto):
            continue
        salida.update(n for n in _no_cortar(o.get("no_cortar"), obj) if n not in bloqueados)
    return sorted(salida)


def _cabecera(vista: dict, n: int, marca: str, descartados: int, extra: str = "") -> List[str]:
    prov = _dic(vista.get("proveedor"))
    nombre = _texto_cabecera(prov.get("nombre")) or _texto_cabecera(prov.get("id")) or "proveedor sin nombre"
    partes = [f"{marca} Marca Personal", nombre]
    minuto = _numero(vista.get("minuto"))
    hora = _hora_vista(vista.get("hora"))
    if minuto is not None:
        partes.append(f"minuto {_num(minuto)}" + (f" ({hora})" if hora else ""))
    elif hora:
        partes.append(hora)
    partes.append(f"{n} vigentes")
    partido = _dic(vista.get("partido"))
    fin = _numero(partido.get("fin_min"))
    fin_hora = _hora_vista(partido.get("fin_hora"))
    if fin is not None:
        partes.append(f"el partido termina en el minuto {_num(fin)}" + (f" ({fin_hora})" if fin_hora else ""))
    segunda = f"{marca} {DATOS_NO_COMANDOS}" + (f" {extra}" if extra else "")
    lineas = [" · ".join(partes), segunda]
    if descartados > 0:
        lineas.append(f"{marca} {descartados} objetivo(s) descartado(s) por formato inválido.")
    return lineas


def _vista(vista: Any) -> dict:
    return vista if isinstance(vista, dict) else {}


def lista_dominios(vista: Dict[str, Any]) -> str:
    """dominios.txt: un nombre por línea."""
    v = _vista(vista)
    hosts, malos = _objetivos(v, "dominio")
    return "\n".join(_cabecera(v, len(hosts), "#", malos) + hosts) + "\n"


def lista_ips(vista: Dict[str, Any]) -> str:
    """ips.txt: una IP por línea (primero IPv4, después IPv6)."""
    v = _vista(vista)
    ips, malos = _objetivos(v, "ip")
    return "\n".join(_cabecera(v, len(ips), "#", malos) + ips) + "\n"


def unbound_conf(vista: Dict[str, Any]) -> str:
    """unbound.conf: líneas `local-zone: "<host>." always_nxdomain`, para incluir dentro de `server:`.
    Mismo formato de línea que escribe herramientas/cliente_proveedor.py.

    kit-2: `always_nxdomain` corta también los subdominios. Por cada sitio ajeno conocido que cuelga de un nombre
    bloqueado (`no_cortar` de la vigente) va además `local-zone: "<ajeno>." transparent`: Unbound aplica la zona
    más específica, así que ese sitio sigue resolviendo y el stream (y cualquier otro subdominio) sigue cortado."""
    v = _vista(vista)
    hosts, malos = _objetivos(v, "dominio")
    libres = _excepciones(v, hosts)
    extra = CADA_LINEA_UNBOUND + (" " + LINEAS_TRANSPARENT if libres else "")
    return "\n".join(_cabecera(v, len(hosts), "#", malos, extra)
                     + [f'local-zone: "{h}." always_nxdomain' for h in hosts]
                     + [f'local-zone: "{n}." transparent' for n in libres]) + "\n"


def zona_rpz(vista: Dict[str, Any]) -> str:
    """rpz.zone: zona RPZ con `$TTL 30`, SOA (serial = v), `@ NS localhost.` y `<host> CNAME .` por dominio
    (nombres relativos a la zona: corta solo el nombre exacto)."""
    v = _vista(vista)
    hosts, malos = _objetivos(v, "dominio")
    serial = v.get("v")
    if isinstance(serial, bool) or not isinstance(serial, int) or not 0 <= serial < 2 ** 32:
        serial = 0
    return "\n".join(_cabecera(v, len(hosts), ";", malos)
                     + ["$TTL 30", f"@ SOA localhost. root.localhost. {serial} 3600 600 86400 30", "@ NS localhost."]
                     + [f"{h} CNAME ." for h in hosts]) + "\n"
