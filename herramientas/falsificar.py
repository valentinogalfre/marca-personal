#!/usr/bin/env python3
"""«Ni nosotros podemos falsificarlo»: falsifica una COPIA de una exportación con todo lo que controla la plataforma.

    python3 herramientas/falsificar.py <exportación> <destino> [--config config/jueces_demo.json] [--ip 198.51.100.250]

Cambia un dato de la evidencia (por defecto, la IP de la primera ubicación del primer expediente, y todo lo que la
nombra) y después recalcula lo que un falsificador con acceso a la plataforma podría recalcular:

- la huella de cada ubicación (y el antecedente de las siguientes);
- la cadena de auditoría desde la primera entrada cambiada, con sus decisiones y, con --config, sus firmas;
- los sellos y los números de orden en la auditoría, los expedientes, el resumen y los testigos;
- el sha256 de testigos_guardados, los .md (desde los .json) y el manifiesto.

`python3 -m marca verificar <destino>` dice «coherente consigo mismo»: sin nada de afuera, la falsificación no se
nota. Con
`--registro-simulador <registro.jsonl>` da ✗: el registro oficial del simulador, que la plataforma no puede
reescribir, tiene órdenes que la auditoría falsificada no tiene, y al revés. Por eso la huella se publica.

Nunca escribe sobre la exportación original: trabaja sobre una copia en <destino>, que no puede existir.
Solo biblioteca estándar.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from marca import sello as sello_mod  # noqa: E402
from marca.auditoria import hash_entrada  # noqa: E402
from marca.canon import CEROS, huella, sha256_hex  # noqa: E402
from marca.exportar import escribir_manifiesto, huella_paquete, legibles  # noqa: E402

TIPOS_SELLO = ("decision_juez", "ampliacion_dinamica", "reclamo_resuelto")


class ErrorFalsificar(Exception):
    pass


def _reemplazar(obj: Any, mapa: Dict[str, str]) -> Any:
    """Reemplaza, en todo texto dentro de obj, cada valor viejo (huella, sello) por el nuevo."""
    if isinstance(obj, str):
        for viejo, nuevo in mapa.items():
            if viejo in obj:
                obj = obj.replace(viejo, nuevo)
        return obj
    if isinstance(obj, list):
        return [_reemplazar(x, mapa) for x in obj]
    if isinstance(obj, dict):
        return {k: _reemplazar(v, mapa) for k, v in obj.items()}
    return obj


def _cambiar_ip(texto: str, vieja: str, nueva: str) -> str:
    return re.sub(r"(?<![\d.])" + re.escape(vieja) + r"(?![\d])", nueva, texto)


def falsificar(origen, destino, config: Optional[str] = None, ip_nueva: str = "198.51.100.250") -> dict:
    origen, destino = Path(origen).resolve(), Path(destino).resolve()
    if not (origen / "auditoria.jsonl").is_file() or not (origen / "expedientes").is_dir():
        raise ErrorFalsificar(f"{origen} no es una exportación (falta auditoria.jsonl o expedientes/).")
    if destino.exists():
        raise ErrorFalsificar(f"{destino} ya existe: el falsificado va siempre a una carpeta nueva.")
    if destino == origen or origen in destino.parents:
        raise ErrorFalsificar("El destino no puede estar dentro de la exportación original.")
    claves = None
    if config:
        claves = {str(k): str(v) for k, v in (json.loads(Path(config).read_text(encoding="utf-8"))
                                               .get("claves_firma_demo") or {}).items()}
    huella_original = huella_paquete(origen)
    shutil.copytree(origen, destino)

    # 1. El dato que se cambia: la IP de la primera ubicación del primer expediente (y todo lo que la nombra).
    archivos = sorted((destino / "expedientes").glob("*.json"))
    originales = [json.loads(p.read_text(encoding="utf-8")) for p in archivos]
    con_ubic = [x for x in originales if x.get("ubicaciones")]
    if not con_ubic:
        raise ErrorFalsificar("La exportación no tiene ubicaciones: no hay evidencia que cambiar.")
    victima = con_ubic[0]["ubicaciones"][0]
    ip_vieja = victima["ip"]
    if ip_nueva == ip_vieja:
        ip_nueva = "198.51.100.251"

    def ip(texto: str) -> str:
        return _cambiar_ip(texto, ip_vieja, ip_nueva)

    # 2. Huellas nuevas, ubicación por ubicación (el antecedente de la siguiente cambia con la anterior).
    mapa: Dict[str, str] = {}
    expedientes: List[dict] = []
    for arch, orig in zip(archivos, originales):
        exp = json.loads(ip(json.dumps(orig, ensure_ascii=False)))
        for u, uo in zip(exp["ubicaciones"], orig["ubicaciones"]):
            u["sellado"] = _reemplazar(u["sellado"], mapa)
            nueva = huella(u["sellado"])
            if nueva != uo["huella"]:
                mapa[uo["huella"]] = nueva
            u["huella"] = nueva
        expedientes.append(exp)

    # Qué sellos nacen de cada entrada: (sello viejo, huella nueva de la ubicación) por entrada_sello.
    por_entrada: Dict[int, List[tuple]] = {}
    for exp, orig in zip(expedientes, originales):
        for u, uo in zip(exp["ubicaciones"], orig["ubicaciones"]):
            for o in uo.get("ordenes") or []:
                if isinstance(o.get("entrada_sello"), int) and o.get("sello"):
                    por_entrada.setdefault(o["entrada_sello"], []).append((o["sello"], u["huella"]))
            dec = uo.get("decision") or {}
            if isinstance(dec.get("entrada"), int) and dec.get("sello"):
                por_entrada.setdefault(dec["entrada"], []).append((dec["sello"], u["huella"]))

    ruta_t = destino / "testigos" / "proveedores.json"
    testigos_viejos = ruta_t.read_bytes() if ruta_t.exists() else None
    sha_testigos_viejo = sha256_hex(testigos_viejos) if testigos_viejos is not None else None
    testigos_nuevos = None

    # 3. La auditoría, entrada por entrada: textos, firmas, cadena y sellos.
    lineas = [l for l in (destino / "auditoria.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    entradas, prev, cambiadas = [], CEROS, 0
    for linea in lineas:
        vieja = json.loads(linea)
        x = json.loads(ip(linea))
        x = {k: (v if k in ("prev", "hash") else _reemplazar(v, mapa)) for k, v in x.items()}
        d = x.get("datos") if isinstance(x.get("datos"), dict) else {}
        if claves is not None:
            _refirmar(x, d, claves)
        if x.get("tipo") == "testigos_guardados" and d.get("sha256") == sha_testigos_viejo:
            testigos_nuevos = _reemplazar(ip(testigos_viejos.decode("utf-8")), mapa).encode("utf-8")
            d["sha256"] = sha256_hex(testigos_nuevos)
        x["prev"] = prev
        x["hash"] = hash_entrada(x)
        prev = x["hash"]
        if x["hash"] != vieja.get("hash"):
            cambiadas += 1
        for sello_viejo, huella_nueva in por_entrada.get(x.get("n"), []):
            nuevo = sello_mod.calcular_sello(huella_nueva, x["hash"])
            if nuevo != sello_viejo:
                mapa[sello_viejo] = nuevo
        entradas.append(x)
    (destino / "auditoria.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in entradas),
                                            encoding="utf-8")

    # 4. Expedientes, testigos, órdenes marco y resumen con los sellos y números de orden nuevos.
    expedientes = [_reemplazar(e, mapa) for e in expedientes]
    for arch, exp in zip(archivos, expedientes):
        arch.write_text(json.dumps(exp, ensure_ascii=False, indent=1), encoding="utf-8")
    if testigos_viejos is not None:
        ruta_t.write_bytes(testigos_nuevos if testigos_nuevos is not None
                           else _reemplazar(ip(testigos_viejos.decode("utf-8")), mapa).encode("utf-8"))
    marcos = []
    for arch in sorted((destino / "orden-marco").glob("*.json")) if (destino / "orden-marco").is_dir() else []:
        m = _reemplazar(json.loads(ip(arch.read_text(encoding="utf-8"))), mapa)
        arch.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
        marcos.append(m)
    marcos.sort(key=lambda m: m.get("entrada") or 0)
    ruta_r = destino / "resumen.json"
    resumen = _reemplazar(json.loads(ip(ruta_r.read_text(encoding="utf-8"))), mapa)
    resumen["cabeza_auditoria"] = {"n": entradas[-1]["n"], "hash": entradas[-1]["hash"]} if entradas else \
        {"n": 0, "hash": None}
    ruta_r.write_text(json.dumps(resumen, ensure_ascii=False, indent=1), encoding="utf-8")

    # 5. Los .md salen de los .json (igual que al exportar) y el manifiesto se rehace.
    expedientes.sort(key=lambda x: (x.get("num") or 0, str(x.get("id"))))
    for rel, texto in legibles(resumen, expedientes, marcos).items():
        (destino / rel).write_text(texto, encoding="utf-8")
    huella_falsa = escribir_manifiesto(destino)
    return {"ip_vieja": ip_vieja, "ip_nueva": ip_nueva, "expediente": con_ubic[0]["id"],
            "entradas_reescritas": cambiadas, "sellos_cambiados": sum(1 for k in mapa if len(k) == 32),
            "huella_original": huella_original, "huella_falsificada": huella_falsa}


def _refirmar(x: dict, d: dict, claves: Dict[str, str]) -> None:
    """Con las claves de demostración, el falsificador vuelve a firmar lo que cambió."""
    tipo = x.get("tipo")
    if tipo == "decision_juez" and "accion" not in d and d.get("firma_decision") and claves.get(d.get("juez_id")):
        d["firma_decision"] = sello_mod.firma_decision(claves[d["juez_id"]], x.get("exp"), d.get("ubicacion"),
                                                       d.get("huella"), bool(d.get("aprobar")), d.get("alcance"),
                                                       d["juez_id"])
    elif tipo == "ampliacion_dinamica" and d.get("firma_ampliacion"):
        juez = d.get("bajo_orden_dinamica_de")
        if claves.get(juez):
            d["firma_ampliacion"] = sello_mod.firma_ampliacion(claves[juez], x.get("exp"), d.get("ubicacion"),
                                                               d.get("huella"), juez, d.get("entrada_habilitante"))
    elif tipo == "orden_levantada" and d.get("firma") and claves.get(d.get("juez_id")):
        d["firma"] = sello_mod.firma_levantamiento(claves[d["juez_id"]], d.get("orden_id"), d["juez_id"])


def main() -> int:
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(description="Falsifica una copia de una exportación (demostración)")
    p.add_argument("exportacion")
    p.add_argument("destino")
    p.add_argument("--config", default=None, help="claves de demostración: también vuelve a firmar")
    p.add_argument("--ip", default="198.51.100.250", help="IP falsa para la ubicación")
    a = p.parse_args()
    try:
        r = falsificar(a.exportacion, a.destino, a.config, a.ip)
    except ErrorFalsificar as err:
        print(f"✗ {err}", file=sys.stderr)
        return 2
    print(f"Copia falsificada en {a.destino}: la IP {r['ip_vieja']} de {r['expediente']} U1 pasó a ser "
          f"{r['ip_nueva']}.")
    print(f"Se reescribieron {r['entradas_reescritas']} entradas de la auditoría y {r['sellos_cambiados']} sellos, "
          "con huellas, números de orden, testigos, textos y manifiesto recalculados"
          + (" y las firmas rehechas con las claves de demostración." if a.config else "."))
    print(f"Huella del paquete original:    {r['huella_original']}")
    print(f"Huella del paquete falsificado: {r['huella_falsificada']}")
    print()
    print(f"«python3 -m marca verificar {a.destino}» dice «coherente consigo mismo»: con lo que controla la "
          "plataforma, no se nota.")
    print("Con --registro-simulador da ✗: el registro oficial y la huella publicada no se pueden recalcular.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
