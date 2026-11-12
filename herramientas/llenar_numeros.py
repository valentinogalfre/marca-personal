#!/usr/bin/env python3
"""Carga los números medidos en los documentos: reemplaza cada ‹FAMILIA-campo› por VALORES[FAMILIA][campo].

    python3 -I herramientas/llenar_numeros.py --valores VALORES.json --docs DIR [--simular]

- Recorre todos los .md de DIR (recursivo).
- Una marca es ‹FAMILIA-campo›: FAMILIA es una clave de VALORES (A, U, H8x6U, A60…) y campo, una clave de esa familia.
  Gana la familia más larga que calce (así ‹A60-bloqueados› es A60 y no A).
- No toca las marcas duras (‹equipo›, ‹enlace al video en Hacki›) ni nada que no tenga la forma de arriba.
- Una marca sin valor, o con valor nulo, queda como está y se informa (nunca escribe «None»).
- Las claves que empiezan con «_» son notas y se ignoran.
- Con --simular no escribe nada: solo informa.
Sale con 0 si todas las marcas de número tuvieron valor, con 1 si quedó alguna, con 2 si el JSON o DIR no sirven.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DURAS = {"equipo", "enlace al video en Hacki"}
MARCA = re.compile(r"‹([^‹›\s]+)›")


def texto(v) -> str:
    if isinstance(v, bool):
        return "sí" if v else "no"
    if isinstance(v, float):
        s = f"{v:.2f}".rstrip("0").rstrip(".")
        return s.replace(".", ",")
    return str(v)


def partir(marca: str, familias):
    """('A60', 'bloqueados') para «A60-bloqueados»; None si no calza ninguna familia."""
    for fam in sorted(familias, key=len, reverse=True):
        if marca.startswith(fam + "-") and len(marca) > len(fam) + 1:
            return fam, marca[len(fam) + 1:]
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--valores", required=True)
    ap.add_argument("--docs", required=True)
    ap.add_argument("--simular", action="store_true", help="no escribe: solo informa")
    a = ap.parse_args(argv)
    try:
        crudo = json.loads(Path(a.valores).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"✗ No pude leer {a.valores}: {e}")
        return 2
    valores = {f: {k: v for k, v in d.items() if not k.startswith("_")}
               for f, d in crudo.items() if not f.startswith("_") and isinstance(d, dict)}
    raiz = Path(a.docs)
    if not raiz.is_dir():
        print(f"✗ No existe la carpeta {raiz}")
        return 2

    puestos, sin_valor, nulos, ajenas = 0, {}, {}, {}
    for md in sorted(raiz.rglob("*.md")):
        original = md.read_text(encoding="utf-8")

        def cambiar(m, md=md):
            nonlocal puestos
            nombre = m.group(1)
            if nombre in DURAS:
                return m.group(0)
            p = partir(nombre, valores)
            if not p:
                ajenas.setdefault(nombre, set()).add(str(md.relative_to(raiz)))
                return m.group(0)
            fam, campo = p
            if campo not in valores[fam]:
                sin_valor.setdefault(nombre, set()).add(str(md.relative_to(raiz)))
                return m.group(0)
            v = valores[fam][campo]
            if v is None:
                nulos.setdefault(nombre, set()).add(str(md.relative_to(raiz)))
                return m.group(0)
            puestos += 1
            return texto(v)

        nuevo = MARCA.sub(cambiar, original)
        if nuevo != original and not a.simular:
            md.write_text(nuevo, encoding="utf-8")

    print(f"{'(simulado) ' if a.simular else ''}Marcas reemplazadas: {puestos}.")
    for titulo, d in (("Sin valor en VALORES", sin_valor), ("Con valor nulo (quedan como marca)", nulos),
                      ("Con forma de marca pero de una familia que no está en VALORES", ajenas)):
        if d:
            print(f"\n{titulo}: {len(d)}")
            for k in sorted(d):
                print(f"  ‹{k}›  en {', '.join(sorted(d[k]))}")
    restantes = len(sin_valor) + len(nulos) + len(ajenas)
    return 1 if restantes else 0


if __name__ == "__main__":
    sys.exit(main())
