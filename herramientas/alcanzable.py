#!/usr/bin/env python3
"""Oraculo de lo alcanzable: en un ensayo (sobre todo uno con bordes), separa lo que era fisicamente
imposible de bloquear de lo que es un defecto real de la plataforma.

Uso:
    python3 herramientas/alcanzable.py --verdad V.json --proveedores proveedores.json \\
        --verificador RESULTADO_DEL_VERIFICADOR.json --registro REGISTRO_DEL_SIMULADOR.jsonl \\
        [--margen-min 1.0] [--json]

Para cada fase pirata de la verdad y cada proveedor:
  - La fase no es evaluable si hasta_min <= desde_min (duracion cero) o si el registro termino antes
    de que empezara (el verificador oficial tampoco la puntua).
  - Que cuenta como bloqueo de la fase es lo que cuenta el verificador oficial (evaluacion/verificar.py,
    funcion afecta): una orden aplicada de tipo "ip" sobre la IP de la fase o de tipo "dominio" sobre
    su host, activa un intervalo > 0 dentro de [desde, min(hasta, fin del registro)]. La recomendacion
    de la verdad NO cambia eso; lo que limita a cada proveedor son sus capacidades (valle solo dominio,
    que igual alcanza: el host de la fase siempre se puede bloquear por dominio).
  - Demora del simulador: demora_min x (0,7 + 0,6 x fraccion), o sea entre 0,7 y 1,3 x demora_min.
    fallas = ordenes de ese proveedor que afectan la fase (por su IP o su host) y que fallaron dentro
    de la fase antes de la que la cubrio (o antes del final de la fase si nadie la cubrio).
      imposible       si desde + 0,7 x demora >= hasta
      alcanzable seguro si desde + margen + 1,3 x demora x (1 + fallas) < hasta
      depende de la suerte en otro caso (no cuenta ni a favor ni en contra)
  - Cada par (fase, proveedor) queda: cubierto / no cubierto y era imposible / no cubierto y dependia de
    la suerte / NO cubierto y era alcanzable seguro (DEFECTO).
Veredicto: "sin defectos" si no hay ningun par DEFECTO y toda fase evaluable con algun proveedor
alcanzable seguro quedo bloqueada; si no, "defectos" con la lista.

Codigo de salida: 0 sin defectos, 1 con defectos, 2 por error de uso o de datos.
Solo biblioteca estandar, Python 3.9+. No importa el paquete `marca` ni ejecuta nada del repo oficial.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

TIPOS_QUE_CUENTAN = ("ip", "dominio")  # los dos tipos que verificar.afecta reconoce
FACTOR_MIN, FACTOR_MAX = 0.7, 1.3      # demora real = demora_min x [0,7 ; 1,3)

SEGURIDAD = ("bloqueos_con_dano_colateral", "bloqueos_falsos_positivos", "ordenes_firmadas_fuera_de_turno",
             "bloqueos_ip_activos_post_partido", "ordenes_rechazadas")
CLASES = ("cubierto", "no_cubierto_imposible", "no_cubierto_suerte", "defecto")
TEXTO_ALCANCE = {"seguro": "alcanzable seguro", "suerte": "dependia de la suerte", "imposible": "imposible"}


class ErrorDeDatos(Exception):
    """Archivos ilegibles, mal formados o que no corresponden entre si (codigo de salida 2)."""


# --------------------------------------------------------------------------------------------
# Lectura y validacion
# --------------------------------------------------------------------------------------------
def cargar_json(ruta: Path, que: str) -> Any:
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except OSError as e:
        raise ErrorDeDatos(f"no se pudo leer {que} ({ruta}): {e.strerror or e}")
    except json.JSONDecodeError as e:
        raise ErrorDeDatos(f"{que} ({ruta}) no es JSON valido: {e}")


def cargar_registro(ruta: Path) -> List[dict]:
    try:
        with open(ruta, encoding="utf-8") as f:
            lineas = f.readlines()
    except OSError as e:
        raise ErrorDeDatos(f"no se pudo leer el registro ({ruta}): {e.strerror or e}")
    eventos = []
    for n, linea in enumerate(lineas, start=1):
        if not linea.strip():
            continue
        try:
            e = json.loads(linea)
        except json.JSONDecodeError as err:
            raise ErrorDeDatos(f"registro, linea {n}: no es JSON valido ({err})")
        if not isinstance(e, dict) or not isinstance(e.get("evento"), str) or not _es_numero(e.get("min")):
            raise ErrorDeDatos(f"registro, linea {n}: cada evento necesita 'min' (numero) y 'evento' (texto)")
        eventos.append(e)
    if not eventos:
        raise ErrorDeDatos("el registro esta vacio")
    return sorted(eventos, key=lambda e: e["min"])  # igual que verificar.cargar_log (orden estable)


def _es_numero(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _exigir(cond: bool, msg: str) -> None:
    if not cond:
        raise ErrorDeDatos(msg)


def leer_proveedores(datos: Any) -> List[dict]:
    lista = datos.get("proveedores") if isinstance(datos, dict) else datos
    _exigir(isinstance(lista, list) and lista, "proveedores: falta la lista 'proveedores'")
    out = []
    for p in lista:
        _exigir(isinstance(p, dict) and isinstance(p.get("id"), str), "proveedores: cada proveedor necesita 'id'")
        comp = p.get("comportamiento")
        _exigir(isinstance(comp, dict) and _es_numero(comp.get("demora_min")) and comp["demora_min"] >= 0,
                f"proveedores: {p['id']} necesita comportamiento.demora_min (numero >= 0)")
        caps = p.get("capacidades")
        _exigir(isinstance(caps, list) and all(isinstance(c, str) for c in caps),
                f"proveedores: {p['id']} necesita 'capacidades' (lista)")
        out.append({"id": p["id"], "demora_min": float(comp["demora_min"]),
                    "tipos": [t for t in TIPOS_QUE_CUENTAN if t in caps]})
    _exigir(len({p["id"] for p in out}) == len(out), "proveedores: hay ids repetidos")
    return out


def leer_fases_piratas(verdad: Any) -> List[Tuple[str, int, dict]]:
    _exigir(isinstance(verdad, dict) and isinstance(verdad.get("streams"), list), "verdad: falta 'streams'")
    _exigir(isinstance(verdad.get("escenario_id"), str), "verdad: falta 'escenario_id'")
    fases = []
    for s in verdad["streams"]:
        _exigir(isinstance(s, dict) and isinstance(s.get("id"), str) and isinstance(s.get("fases"), list),
                "verdad: cada stream necesita 'id' y 'fases'")
        if s.get("clase") != "pirata":
            continue
        for n, f in enumerate(s["fases"], start=1):
            _exigir(isinstance(f, dict) and _es_numero(f.get("desde_min")) and _es_numero(f.get("hasta_min"))
                    and isinstance(f.get("ip"), str) and isinstance(f.get("host"), str),
                    f"verdad: la fase {n} de {s['id']} necesita desde_min, hasta_min, ip y host")
            fases.append((s["id"], n, f))
    return fases


def leer_verificador(res: Any) -> Tuple[str, float, Dict[Tuple[str, int], dict]]:
    _exigir(isinstance(res, dict) and isinstance(res.get("fases"), list) and _es_numero(res.get("log_hasta_min")),
            "verificador: se espera el JSON de evaluacion/verificar.py --json (faltan 'fases' o 'log_hasta_min')")
    por_fase = {}
    for f in res["fases"]:
        _exigir(isinstance(f, dict) and isinstance(f.get("stream"), str) and isinstance(f.get("fase"), int)
                and isinstance(f.get("proveedores_que_bloquearon"), list) and "primer_bloqueo_min" in f,
                "verificador: cada fase necesita stream, fase, primer_bloqueo_min y proveedores_que_bloquearon")
        por_fase[(f["stream"], f["fase"])] = f
    return str(res.get("escenario", "")), float(res["log_hasta_min"]), por_fase


# --------------------------------------------------------------------------------------------
# Ordenes del registro (misma semantica que verificar.reconstruir_ordenes, mas el minuto de falla)
# --------------------------------------------------------------------------------------------
def reconstruir_ordenes(eventos: List[dict]) -> List[dict]:
    ordenes: Dict[Tuple[Any, Any], dict] = {}
    for e in eventos:
        clave = (e.get("proveedor"), e.get("orden_id"))
        if e["evento"] == "orden_recibida":
            ordenes[clave] = {"proveedor": e.get("proveedor"), "orden_id": e.get("orden_id"), "tipo": e.get("tipo"),
                              "objetivo": e.get("objetivo"), "recibida": e["min"], "aplicada": None,
                              "fallida": None, "fin": None}
        elif clave in ordenes:
            o = ordenes[clave]
            if e["evento"] == "orden_aplicada":
                o["aplicada"] = e["min"]
            elif e["evento"] == "orden_fallida":
                o["fallida"] = e["min"]
            elif e["evento"] in ("orden_vencida", "orden_levantada"):
                o["fin"] = e["min"]
    return list(ordenes.values())


def afecta(o: dict, ip: str, host: str) -> bool:
    return (o["tipo"] == "ip" and o["objetivo"] == ip) or (o["tipo"] == "dominio" and o["objetivo"] == host)


def intervalo(o: dict, desde: float, hasta: float) -> float:
    if o["aplicada"] is None:
        return 0.0
    fin = min(o["fin"] if o["fin"] is not None else hasta, hasta)
    return max(0.0, fin - max(o["aplicada"], desde))


# --------------------------------------------------------------------------------------------
# Oraculo
# --------------------------------------------------------------------------------------------
def evaluar(verdad: Any, proveedores: Any, verificador: Any, eventos: List[dict], margen_min: float = 1.0) -> dict:
    _exigir(_es_numero(margen_min) and margen_min >= 0, "--margen-min tiene que ser un numero >= 0")
    provs = leer_proveedores(proveedores)
    fases = leer_fases_piratas(verdad)
    escenario_v, log_fin, por_fase = leer_verificador(verificador)
    escenario = verdad["escenario_id"]
    _exigir(escenario_v in ("", escenario),
            f"el resultado del verificador es del escenario {escenario_v!r} y la verdad de {escenario!r}")
    inicio = next((e for e in eventos if e["evento"] == "simulacion_iniciada"), None)
    if inicio is not None and inicio.get("escenario") not in (None, escenario):
        raise ErrorDeDatos(f"el registro es del escenario {inicio.get('escenario')!r} y la verdad de {escenario!r}")
    claves_verdad = {(sid, n) for sid, n, _ in fases}
    sobran = sorted(set(por_fase) - claves_verdad)
    _exigir(not sobran, f"el verificador puntua fases que la verdad no tiene: {sobran[:3]}")
    ordenes = reconstruir_ordenes(eventos)
    nombres = [p["id"] for p in provs]

    filas, defectos = [], []
    for sid, n, f in fases:
        desde, hasta = float(f["desde_min"]), float(f["hasta_min"])
        hasta_eval = min(hasta, log_fin)
        fila = {"stream": sid, "fase": n, "host": f["host"], "ip": f["ip"], "desde_min": desde, "hasta_min": hasta,
                "hasta_evaluada_min": hasta_eval, "bloqueo_recomendado": f.get("bloqueo_recomendado"),
                "evaluable": False, "motivo": None, "bloqueada": None, "estado": "no evaluable", "proveedores": []}
        filas.append(fila)
        res = por_fase.get((sid, n))
        if hasta <= desde:
            fila["motivo"] = "duracion cero: el verificador no la puede puntuar"
            continue
        if res is None:
            _exigir(desde >= log_fin, f"el verificador no trae la fase {n} de {sid}, que empieza antes del fin del "
                                      f"registro (min {log_fin:g}): ¿es el resultado de este ensayo?")
            fila["motivo"] = f"el registro termino (min {log_fin:g}) antes de que empezara la fase"
            continue
        _exigir(set(res["proveedores_que_bloquearon"]) <= set(nombres),
                f"el verificador nombra proveedores que no estan en proveedores.json: {res['proveedores_que_bloquearon']}")
        fila["evaluable"] = True
        fila["bloqueada"] = res["primer_bloqueo_min"] is not None
        cubiertos = set(res["proveedores_que_bloquearon"])
        hay_seguro = False
        for p in provs:
            mias = [o for o in ordenes if o["proveedor"] == p["id"] and o["tipo"] in p["tipos"]
                    and afecta(o, f["ip"], f["host"])]
            cubren = [o for o in mias if intervalo(o, desde, hasta_eval) > 0]
            _exigir(bool(cubren) == (p["id"] in cubiertos),
                    f"fase {n} de {sid}, {p['id']}: el registro y el resultado del verificador no coinciden "
                    "(¿son del mismo ensayo?)")
            corte = min(max(o["aplicada"], desde) for o in cubren) if cubren else hasta_eval
            fallas = sum(1 for o in mias if o["fallida"] is not None and desde <= o["fallida"] < corte)
            if not p["tipos"]:
                lim_imp, lim_seg, alcance = None, None, "imposible"
            else:
                d = p["demora_min"]
                lim_imp = desde + FACTOR_MIN * d
                lim_seg = desde + margen_min + FACTOR_MAX * d * (1 + fallas)
                alcance = "imposible" if lim_imp >= hasta_eval else "seguro" if lim_seg < hasta_eval else "suerte"
            hay_seguro |= alcance == "seguro"
            cubierto = p["id"] in cubiertos
            clase = ("cubierto" if cubierto else "defecto" if alcance == "seguro"
                     else "no_cubierto_imposible" if alcance == "imposible" else "no_cubierto_suerte")
            fila["proveedores"].append({
                "proveedor": p["id"], "demora_min": p["demora_min"], "tipos": p["tipos"], "fallas_observadas": fallas,
                "limite_imposible_min": None if lim_imp is None else round(lim_imp, 3),
                "limite_seguro_min": None if lim_seg is None else round(lim_seg, 3),
                "alcance": alcance, "cubierto": cubierto, "clase": clase})
            if clase == "defecto":
                defectos.append({"stream": sid, "fase": n, "desde_min": desde, "hasta_min": hasta, "proveedor": p["id"],
                                 "motivo": f"{p['id']} no la cubrio y llegaba seguro: orden a mas tardar en el min "
                                           f"{desde + margen_min:g}, aplicada antes del min {lim_seg:.2f} "
                                           f"({fallas} falla(s) observada(s)); la fase sigue hasta el {hasta_eval:g}"})
        if hay_seguro and not fila["bloqueada"]:
            defectos.append({"stream": sid, "fase": n, "desde_min": desde, "hasta_min": hasta, "proveedor": None,
                             "motivo": "la fase quedo sin ningun bloqueo y al menos un proveedor llegaba seguro"})
        clases = [x["clase"] for x in fila["proveedores"]]
        fila["estado"] = ("DEFECTO" if "defecto" in clases or (hay_seguro and not fila["bloqueada"])
                          else "completa" if all(c == "cubierto" for c in clases) else "lo alcanzable")

    pares = {c: sum(1 for fl in filas for x in fl["proveedores"] if x["clase"] == c) for c in CLASES}
    # Informativo (no entra en el veredicto): los contadores de seguridad del propio verificador.
    resumen_v = verificador.get("resumen") if isinstance(verificador.get("resumen"), dict) else {}
    seguridad = {k: resumen_v.get(k) for k in SEGURIDAD if k in resumen_v}
    evaluables = [fl for fl in filas if fl["evaluable"]]
    return {
        "escenario": escenario, "log_hasta_min": log_fin, "margen_min": margen_min,
        "veredicto": "defectos" if defectos else "sin defectos",
        "resumen": {"fases": len(filas), "evaluables": len(evaluables), "no_evaluables": len(filas) - len(evaluables),
                    "bloqueadas": sum(1 for fl in evaluables if fl["bloqueada"]), "pares": pares},
        "proveedores": [{"proveedor": p["id"], "demora_min": p["demora_min"], "tipos": p["tipos"]} for p in provs],
        "fases": filas, "defectos": defectos, "seguridad_informativa": seguridad,
    }


# --------------------------------------------------------------------------------------------
# Salida
# --------------------------------------------------------------------------------------------
def _lista(nombres: List[str]) -> str:
    return ", ".join(nombres) if nombres else "nadie"


def texto(r: dict) -> str:
    out = [f"Oraculo de lo alcanzable — escenario {r['escenario']} (registro hasta el min {r['log_hasta_min']:g}; "
           f"margen de la plataforma {r['margen_min']:g} min)"]
    out.append("Proveedores: " + " · ".join(
        f"{p['proveedor']} {p['demora_min']:g} min" + ("" if p["tipos"] == list(TIPOS_QUE_CUENTAN)
                                                    else f" (solo {', '.join(p['tipos']) or 'nada'})")
        for p in r["proveedores"]))
    out.append("")
    ancho = max([len(f"{f['stream']} fase {f['fase']}") for f in r["fases"]] + [10])
    for f in r["fases"]:
        nombre = f"{f['stream']} fase {f['fase']}".ljust(ancho)
        minutos = f"(min {f['desde_min']:g}–{f['hasta_min']:g})"
        if not f["evaluable"]:
            out.append(f"NO EVALUABLE   {nombre} {minutos}: {f['motivo']}")
            continue
        por = {c: [x["proveedor"] for x in f["proveedores"] if x["clase"] == c] for c in CLASES}
        partes = [("bloqueada" if f["bloqueada"] else "SIN BLOQUEO") + f"; la cubrieron: {_lista(por['cubierto'])}"]
        if por["no_cubierto_suerte"]:
            partes.append(f"dependia de la suerte: {_lista(por['no_cubierto_suerte'])}")
        if por["no_cubierto_imposible"]:
            partes.append(f"imposible: {_lista(por['no_cubierto_imposible'])}")
        for x in f["proveedores"]:
            if x["clase"] == "defecto":
                partes.append(f"DEFECTO {x['proveedor']}: llegaba seguro antes del min {x['limite_seguro_min']:g} "
                              f"({x['fallas_observadas']} falla(s))")
        etiqueta = {"completa": "COMPLETA", "lo alcanzable": "LO ALCANZABLE", "DEFECTO": "DEFECTO"}[f["estado"]]
        out.append(f"{etiqueta:<14} {nombre} {minutos}: " + "; ".join(partes))
    res, pares = r["resumen"], r["resumen"]["pares"]
    out.append("")
    out.append(f"Fases: {res['evaluables']} evaluables ({res['bloqueadas']} bloqueadas), {res['no_evaluables']} no evaluables. "
               f"Pares fase-proveedor: {pares['cubierto']} cubiertos, {pares['no_cubierto_imposible']} imposibles, "
               f"{pares['no_cubierto_suerte']} de suerte, {pares['defecto']} defectos.")
    if r["seguridad_informativa"]:
        out.append("Seguridad segun el verificador (informativo, no entra en el veredicto): " + ", ".join(
            f"{k.replace('_', ' ')} {v if v is not None else 'no evaluable'}" for k, v in r["seguridad_informativa"].items()))
    if r["defectos"]:
        out.append(f"Resultado: DEFECTOS ({len(r['defectos'])})")
        for d in r["defectos"]:
            out.append(f"  - {d['stream']} fase {d['fase']} (min {d['desde_min']:g}–{d['hasta_min']:g}): {d['motivo']}")
    else:
        out.append("Resultado: SIN DEFECTOS (todo lo que no se cubrio era imposible o dependia de la suerte)")
    return "\n".join(out)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # codigo 2, como manda el contrato (argparse ya usa 2)
        self.print_usage(sys.stderr)
        print(f"error: {message}", file=sys.stderr)
        sys.exit(2)


def main(argv: Optional[List[str]] = None) -> int:
    ap = _Parser(description="Dice, fase por fase, que bloqueo era fisicamente alcanzable y que es un defecto.")
    ap.add_argument("--verdad", type=Path, required=True, help="verdad.json del escenario")
    ap.add_argument("--proveedores", type=Path, required=True, help="datos/proveedores.json usado en el ensayo")
    ap.add_argument("--verificador", type=Path, required=True, help="salida de evaluacion/verificar.py --json")
    ap.add_argument("--registro", type=Path, required=True, help="registro.jsonl del simulador")
    ap.add_argument("--margen-min", type=float, default=1.0,
                    help="minutos que se le dan a la plataforma entre la deteccion y la orden (defecto 1,0)")
    ap.add_argument("--json", action="store_true", help="imprime el resultado completo en JSON")
    a = ap.parse_args(argv)
    try:
        r = evaluar(cargar_json(a.verdad, "la verdad"), cargar_json(a.proveedores, "proveedores"),
                    cargar_json(a.verificador, "el resultado del verificador"), cargar_registro(a.registro),
                    a.margen_min)
    except ErrorDeDatos as e:
        print(f"error de datos: {e}", file=sys.stderr)
        return 2
    print(json.dumps(r, ensure_ascii=False, indent=2) if a.json else texto(r))
    return 1 if r["defectos"] else 0


if __name__ == "__main__":
    sys.exit(main())
