"""Orden marco (OM): contenido y texto de la resolución que el juez firma al empezar su turno (ESPEC sección 1).

Funciones puras: sin red, sin estado, sin reloj. La OM fija los límites del partido y, solo si el juez tilda la
casilla, autoriza el seguimiento de la misma filtración (las ampliaciones automáticas). El texto se arma acá una
sola vez: la pantalla, la auditoría y la exportación lo usan tal cual, nadie lo vuelve a redactar.

Datos que se leen (tal como el motor los guarda, sin transformar):
- `partido` = `e["partido"]`, la respuesta de `GET /partido`: `id`, `nombre`, `titular_derechos` (o `titular`),
  `fin_min`, `marcas_de_agua_validas[].prefijo` y `licenciatarios[]` con `nombre`, `prefijo_marca` y
  `dominios_autorizados` (o `dominios`).
- `proveedores` = `e["proveedores"]`, la respuesta de `GET /proveedores`: de cada uno `id`, `nombre`,
  `capacidades` (lo demás, como `clientes` o `tamano`, no entra en la OM).
- `juez` = `{"juez_id", "nombre", "juzgado_id", "juzgado"}` (lo arma el motor con `e["jueces"]`).
- `turno` = `{"desde_min", "hasta_min"}` (el turno del juez en `GET /juzgados`).
Un dato que falta queda `None` en el contenido y «no informado» en el texto: nunca rompe.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from .canon import huella as _huella_canonica
from .canon import min_txt

VERSION_MARCO = 1
TITULO_CASILLA = "Autorizo el seguimiento de la misma filtración"
CONDICIONES_SEGUIMIENTO = [
    "Si firmo un bloqueo con «Firmar y seguir a esta filtración» y esa misma filtración (la misma sesión de la marca "
    "de agua) aparece en otro servidor, la plataforma amplía el bloqueo sin esperar una firma nueva, solo si se "
    "cumple todo esto:",
    "La evidencia nueva está completa y sellada, y el bloqueo nuevo no alcanza a sitios ajenos: si el servidor nuevo "
    "comparte la IP con sitios ajenos, se bloquea solo el nombre del stream.",
    "Estoy de turno y con la plataforma abierta.",
    "Cada ampliación se me avisa en el momento, sale identificada como ampliación (su número empieza con amp-) y "
    "puedo frenarla o levantarla.",
    "Vence al final del partido. Fuera de estas condiciones, el pedido vuelve a mí.",
]
NO_INFORMADO = "no informado"


def _dic(x: Any) -> dict:
    return x if isinstance(x, dict) else {}


def _lista(x: Any) -> list:
    return x if isinstance(x, list) else []


def _texto(x: Any) -> Optional[str]:
    if x is None or isinstance(x, (dict, list)):
        return None
    t = str(x).strip()
    return t or None


def _minuto(x: Any) -> Optional[float]:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return x if math.isfinite(float(x)) else None


def _num(x: Any) -> str:
    """Minuto para leer: sin decimales si es entero; si no, un decimal con coma."""
    m = _minuto(x)
    if m is None:
        return NO_INFORMADO
    texto = min_txt(m)
    return texto[:-2] if texto.endswith(",0") else texto


def _enumerar(cosas: List[str], conector: str = " y ") -> str:
    if len(cosas) <= 1:
        return "".join(cosas)
    return ", ".join(cosas[:-1]) + conector + cosas[-1]


def _prefijos_oficiales(partido: dict) -> List[str]:
    """Prefijos de la señal oficial: las marcas válidas que no son de un licenciatario."""
    de_lic = {_texto(_dic(l).get("prefijo_marca")) for l in _lista(partido.get("licenciatarios"))}
    salida = []
    for m in _lista(partido.get("marcas_de_agua_validas") or partido.get("marcas_validas")):
        p = _texto(_dic(m).get("prefijo") if isinstance(m, dict) else m)
        if p and p not in de_lic and p not in salida:
            salida.append(p)
    return salida


def _vigencia(turno: dict, p: dict) -> str:
    """Renglón 2 (ronda 3, C11): desde cuándo y hasta cuándo vale la OM, y el tope de todo bloqueo."""
    desde, hasta, fin = _minuto(turno.get("desde_min")), _minuto(turno.get("hasta_min")), _minuto(p.get("fin_min"))
    if desde is None:
        inicio = f"el minuto {NO_INFORMADO}"
    elif desde <= 0:
        inicio = "antes del inicio"
    else:
        inicio = f"el minuto {_num(desde)}"
    if hasta is not None and (fin is None or hasta < fin):
        hasta_txt = f"hasta el minuto {_num(hasta)}"
    elif hasta is not None:
        hasta_txt = f"hasta el final del partido (minuto {_num(fin)})"
    else:
        hasta_txt = f"hasta el minuto {NO_INFORMADO}"
    return (f"Esta orden vale durante mi turno en este partido: desde {inicio} {hasta_txt}. Todo bloqueo que se "
            f"ordene bajo ella vence, como máximo, al final del partido (minuto {_num(fin)}).")


def _renglon_senal(marcas: str, lic: List[dict], lic_txt: List[str]) -> str:
    """C15, renglón 3: qué señal se protege (la oficial y la de cada licenciatario fuera de sus dominios)."""
    if not lic:
        return f"Solo se protege la señal oficial del partido ({marcas})."
    pre = [t for t in (_texto(l.get("prefijo_marca")) for l in lic) if t]
    marcas_lic = f"marcas {', '.join(pre)}" if pre else "marcas no informadas"
    return (f"Solo se protege la señal del partido: la oficial ({marcas}) y la de cada licenciatario cuando se "
            f"transmite fuera de sus dominios ({marcas_lic}). Nunca se bloquea a un licenciatario en sus dominios: "
            f"{'; '.join(lic_txt)}.")


def _lineas(p: dict, turno: dict, prefijos: List[str], lic: List[dict]) -> List[str]:
    marcas = f"marcas {', '.join(prefijos)}" if prefijos else "marcas no informadas"
    lic_txt = []
    for l in lic:
        doms = [d for d in (_texto(x) for x in l["dominios"]) if d]
        lic_txt.append(f"{_texto(l['nombre']) or 'licenciatario sin nombre informado'} en "
                       + (_enumerar(doms) if doms else "dominios no informados"))
    return [
        f"Partido: {_texto(p['nombre']) or NO_INFORMADO}. Titular de los derechos: {_texto(p['titular']) or NO_INFORMADO}.",
        _vigencia(turno, p),
        _renglon_senal(marcas, lic, lic_txt),
        "Cada bloqueo necesita un expediente con evidencia sellada (la captura con su hash, la marca verificada y el "
        "servidor con host, IP y red) y mi firma, servidor por servidor, salvo que en esta orden autorice el "
        "seguimiento de la misma filtración.",
        "Si la IP es compartida o hay dudas, solo se bloquea el nombre del stream. Apartarse de esa regla exige mi "
        "fundamento escrito.",
        "Los reclamos se verifican y todo levantamiento lleva mi firma.",
    ]


def _dato(x: Any) -> Any:
    """Un valor escalar apto para JSON canónico (los números y textos pasan; lo demás, como texto o None)."""
    if x is None or isinstance(x, (str, bool, int)):
        return x
    if isinstance(x, float):
        return x if math.isfinite(x) else None
    return str(x)


def armar(partido: dict, proveedores: List[dict], juez: dict, turno: dict, seguimiento: bool) -> Dict[str, Any]:
    """El contenido canónico de la OM (lo que se firma, por su huella), con las claves de ESPEC sección 1."""
    partido, juez, turno = _dic(partido), _dic(juez), _dic(turno)
    titular = partido.get("titular_derechos")
    if titular is None:
        titular = partido.get("titular")
    p = {"id": _dato(partido.get("id")), "nombre": _dato(partido.get("nombre")), "titular": _dato(titular),
         "fin_min": _dato(partido.get("fin_min"))}
    lic = []
    for l in _lista(partido.get("licenciatarios")):
        l = _dic(l)
        doms = l.get("dominios_autorizados")
        if doms is None:
            doms = l.get("dominios")
        lic.append({"nombre": _dato(l.get("nombre")), "prefijo_marca": _dato(l.get("prefijo_marca")),
                    "dominios": [_dato(d) for d in _lista(doms)]})
    prefijos = _prefijos_oficiales(partido)
    t = {"desde_min": _dato(turno.get("desde_min")), "hasta_min": _dato(turno.get("hasta_min"))}
    provs = [{"id": _dato(_dic(x).get("id")), "nombre": _dato(_dic(x).get("nombre")),
              "capacidades": [_dato(c) for c in _lista(_dic(x).get("capacidades"))]}
             for x in _lista(proveedores)]
    j = {k: _dato(juez.get(k)) for k in ("juez_id", "nombre", "juzgado_id", "juzgado")}
    return {
        "version": VERSION_MARCO, "partido": p, "marcas_validas": prefijos, "licenciatarios": lic,
        "proveedores": provs, "juez": j, "turno": t, "seguimiento": bool(seguimiento),
        "lineas": _lineas(p, t, prefijos, lic),
        "condiciones_seguimiento": list(CONDICIONES_SEGUIMIENTO),
    }


def huella(contenido: dict) -> str:
    """sha256 (hex) del JSON canónico del contenido (marca/canon.py)."""
    return _huella_canonica(contenido)


def mensaje_firma(partido_id: str, huella: str, juez_id: str, seguimiento: bool) -> str:
    """Lo que firma el juez con su clave: `MARCO|{partido_id}|{huella}|{juez_id}|S1` (o `S0`)."""
    return f"MARCO|{partido_id}|{huella}|{juez_id}|S{1 if seguimiento else 0}"


def texto_ampliacion(om: Optional[dict], otorgada: Optional[dict], ratificada: Optional[dict] = None,
                     hecha_min: Any = None) -> str:
    """La leyenda de una ampliación automática (ronda 3, C7): una sola fuente para la tarjeta del juez, la sala, la
    orden pública, el registro, el kit y el acta.

    - `om`: la orden marco que respalda la ampliación, la del juez con cuya clave salió (`decision.orden_marco`):
      `{"id", "nombre", "min"}` o `None` (dato viejo).
    - `otorgada`: quién otorgó el seguimiento, `{"nombre", "min"}`.
    - `ratificada`: `None` o `{"nombre", "min"}`, el juez entrante que lo ratificó.
    - `hecha_min`: el minuto de la ampliación, o `None`.
    Los minutos van con `canon.min_txt`."""
    om, otorgada = _dic(om), _dic(otorgada)
    rat = _dic(ratificada) if ratificada else None
    quien = _texto(otorgada.get("nombre")) or NO_INFORMADO
    if om:
        texto = (f"Ampliación automática del sistema bajo la orden marco {_texto(om.get('id')) or NO_INFORMADO} de "
                 f"{_texto(om.get('nombre')) or NO_INFORMADO} (minuto {min_txt(om.get('min'))})")
        if rat:
            texto += (f", que en el minuto {min_txt(rat.get('min'))} ratificó el seguimiento otorgado por {quien} "
                      f"(minuto {min_txt(otorgada.get('min'))}).")
        else:
            texto += f" y el seguimiento que otorgó en el minuto {min_txt(otorgada.get('min'))}."
    else:
        texto = (f"Ampliación automática del sistema bajo el seguimiento otorgado por {quien} en el minuto "
                 f"{min_txt(otorgada.get('min'))}")
        if rat:
            texto += (f", ratificado por {_texto(rat.get('nombre')) or NO_INFORMADO} en el minuto "
                      f"{min_txt(rat.get('min'))}")
        texto += "."
    if hecha_min is not None:
        texto += f" Hecha en el minuto {min_txt(hecha_min)}."
    return texto + " No se firmó en persona."


def a_texto(contenido: dict) -> List[str]:
    """Renglones para mostrar o exportar: `lineas` y, solo si `seguimiento` es true, el título de la casilla y
    las `condiciones_seguimiento`."""
    c = _dic(contenido)
    renglones = [str(x) for x in _lista(c.get("lineas"))]
    if c.get("seguimiento") is True:
        renglones += [TITULO_CASILLA] + [str(x) for x in _lista(c.get("condiciones_seguimiento"))]
    return renglones
