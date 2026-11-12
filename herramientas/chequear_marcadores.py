#!/usr/bin/env python3
"""Chequeo antes de entregar: ningún marcador ‹…› sin completar en lo que se publica.

    python3 -I herramientas/chequear_marcadores.py            # README.md, docs/, entrega/ (md y pdf)
    python3 -I herramientas/chequear_marcadores.py --equipo   # además equipo/ (no va al repo)
    python3 -I herramientas/chequear_marcadores.py --raiz /ruta/al/proyecto

Contrato que protege: lo que lee el jurado no tiene nada para completar.
- Falla (sale con 1) con cualquier ‹…›, también dentro de comentarios HTML y en el PDF de la propuesta.
- Sale con 2 si falta README.md o entrega/propuesta-normativa.md.
- Avisa, sin fallar, si siguen las frases por defecto que hay que actualizar con lo que pasó
  (respuesta de los mentores, partido final): ver equipo/ANTES-DE-ENTREGAR.md.
No escribe nada y no ejecuta nada del proyecto: solo lee archivos (y llama a pdftotext, si existe).
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

MARCA = re.compile(r"‹[^›\n]*›|‹")

# Frases por defecto: están bien si nada cambió, pero hay que mirarlas antes de entregar.
POR_DEFECTO = [
    ("se les pregunta a los mentores el jueves 12", "postura: ¿ya respondieron los mentores?"),
    ("Los números de arriba son del partido de práctica", "README: ¿ya se corrió el partido final?"),
    ("el juez de turno firmó su orden marco con la casilla destildada", "guion: ¿con qué casilla se corrió el final?"),
    ("Si los mentores ya respondieron", "preguntas: ¿ya respondieron los mentores?"),
]


def texto_de(ruta: Path):
    if ruta.suffix.lower() != ".pdf":
        return ruta.read_text(encoding="utf-8"), None
    exe = shutil.which("pdftotext")
    if not exe:
        return None, f"{ruta}: sin pdftotext no se lee el PDF; regenerarlo desde el .md ya revisado"
    return subprocess.run([exe, str(ruta), "-"], capture_output=True, text=True, check=True).stdout, None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--raiz", default=".", help="carpeta del proyecto (por defecto, la actual)")
    ap.add_argument("--equipo", action="store_true", help="revisar también equipo/")
    a = ap.parse_args(argv)
    raiz = Path(a.raiz)

    obligatorios = [raiz / "README.md", raiz / "entrega" / "propuesta-normativa.md"]
    faltan = [str(p) for p in obligatorios if not p.is_file()]
    if faltan:
        print("✗ Falta: " + ", ".join(faltan))
        return 2

    rutas = [raiz / "README.md"]
    for sub in ("docs", "entrega") + (("equipo",) if a.equipo else ()):
        d = raiz / sub
        if d.is_dir():
            rutas += sorted(p for p in d.rglob("*") if p.suffix.lower() in (".md", ".pdf"))

    problemas, avisos, notas = [], [], []
    for ruta in rutas:
        texto, nota = texto_de(ruta)
        if nota:
            notas.append(nota)
            continue
        rel = ruta.relative_to(raiz)
        for n, renglon in enumerate(texto.split("\n"), 1):
            for m in MARCA.finditer(renglon):
                problemas.append(f"{rel}:{n}: {m.group(0)}")
            for frase, que in POR_DEFECTO:
                if frase in renglon and ruta.name != "ANTES-DE-ENTREGAR.md":
                    avisos.append(f"{rel}:{n}: {que}")

    for t in notas:
        print("· " + t)
    for t in avisos:
        print("! frase por defecto, revisar: " + t)
    if problemas:
        print(f"✗ {len(problemas)} marcador(es) sin completar:")
        for t in problemas:
            print("  " + t)
        return 1
    print(f"✓ Sin marcadores en {len(rutas)} archivo(s)" + (" (con equipo/)" if a.equipo else "") + ".")
    return 0


if __name__ == "__main__":
    sys.exit(main())
