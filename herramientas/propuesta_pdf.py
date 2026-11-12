#!/usr/bin/env python3
"""Genera el PDF de la propuesta normativa a partir del Markdown y garantiza,
por ejecución, que entre en exactamente una página A4.

Uso:
    python3 herramientas/propuesta_pdf.py [--entrada entrega/propuesta-normativa.md]
        [--salida entrega/propuesta-normativa.pdf] [--chrome RUTA]

Solo biblioteca estándar. Las funciones de conversión son puras (sin E/S).
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
MAC_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
BINARIOS_PATH = ["google-chrome", "chromium", "chromium-browser", "chrome"]
LETRA_MAX, LETRA_MIN, PASO = 10.0, 7.5, 0.25


# ---------------------------------------------------------------- Markdown

def escapar(texto):
    """Escapa &, < y > para HTML."""
    return texto.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def quitar_comentarios(md):
    """Saca los comentarios HTML (<!-- ... -->), también los multilínea."""
    return re.sub(r"<!--.*?-->", "", md, flags=re.S)


def inline(texto):
    """Convierte `código`, **negrita** y *cursiva* a HTML, escapando todo."""
    partes = re.split(r"(`[^`\n]+`)", texto)
    salida = []
    for parte in partes:
        if len(parte) > 1 and parte.startswith("`") and parte.endswith("`"):
            salida.append("<code>%s</code>" % escapar(parte[1:-1]))
            continue
        h = escapar(parte)
        h = re.sub(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", r"<strong>\1</strong>", h)
        h = re.sub(r"(?<![\*\w])\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?!\*)", r"<em>\1</em>", h)
        salida.append(h)
    return "".join(salida)


def _celdas(linea):
    s = linea.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _es_separador(linea):
    if "|" not in linea:
        return False
    celdas = _celdas(linea)
    return bool(celdas) and all(re.fullmatch(r":?-{1,}:?", c) for c in celdas)


def _tabla(filas):
    """filas[0] encabezado, filas[1] separador, el resto datos."""
    enc = _celdas(filas[0])
    html = ["<table>", "<thead><tr>%s</tr></thead>" % "".join(
        "<th>%s</th>" % inline(c) for c in enc), "<tbody>"]
    for f in filas[2:]:
        html.append("<tr>%s</tr>" % "".join("<td>%s</td>" % inline(c) for c in _celdas(f)))
    html += ["</tbody>", "</table>"]
    return "\n".join(html)


def markdown_a_html(md):
    """Markdown mínimo -> fragmento HTML (cuerpo)."""
    lineas = quitar_comentarios(md).splitlines()
    out, parrafo, i = [], [], 0

    def cerrar():
        if parrafo:
            out.append("<p>%s</p>" % inline(" ".join(p.strip() for p in parrafo)))
            parrafo.clear()

    while i < len(lineas):
        l = lineas[i]
        if not l.strip():
            cerrar()
        elif re.match(r"^#{1,2}\s+\S", l):
            cerrar()
            nivel = 1 if l.startswith("# ") or re.match(r"^#\s", l) else 2
            out.append("<h%d>%s</h%d>" % (nivel, inline(l.lstrip("#").strip()), nivel))
        elif l.lstrip().startswith("|") and i + 1 < len(lineas) and _es_separador(lineas[i + 1]):
            cerrar()
            j = i + 2
            while j < len(lineas) and lineas[j].lstrip().startswith("|"):
                j += 1
            out.append(_tabla(lineas[i:j]))
            i = j
            continue
        else:
            parrafo.append(l)
        i += 1
    cerrar()
    return "\n".join(out)


def armar_html(cuerpo, letra_pt):
    """Documento HTML completo, con CSS de impresión inline."""
    css = """
@page { size: A4; margin: 11mm 12mm; }
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: #fff; }
body { font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
  font-size: %(pt)spt; line-height: 1.28; color: #1f2328; }
h1 { font-size: 1.55em; line-height: 1.2; margin: 0 0 .45em; padding-bottom: .3em;
  border-bottom: 1.5px solid #1f2328; font-weight: 700; letter-spacing: -.01em; }
h2 { font-size: 1.15em; margin: .8em 0 .3em; }
p { margin: 0 0 .55em; }
table { width: 100%%; border-collapse: collapse; table-layout: fixed; margin: .5em 0 .6em; }
th, td { border: .5pt solid #b8bcc2; padding: .3em .5em; vertical-align: top; text-align: left; }
th { background: #f3f4f6; font-weight: 700; }
th:nth-child(1), td:nth-child(1) { width: 58%%; }
th:nth-child(2), td:nth-child(2) { width: 42%%; }
tr { page-break-inside: avoid; }
code { font-family: Menlo, Consolas, monospace; font-size: .92em; background: #f3f4f6; padding: 0 .2em; }
strong { font-weight: 700; }
""" % {"pt": ("%g" % letra_pt)}
    return ('<!doctype html>\n<html lang="es"><head><meta charset="utf-8">'
            "<title>Propuesta normativa</title><style>%s</style></head>"
            "<body>\n%s\n</body></html>\n" % (css, cuerpo))


# ---------------------------------------------------------------- PDF

def contar_paginas(datos):
    """Cuenta páginas de un PDF (bytes): objetos /Type /Page (sin /Pages).
    Si no encuentra ninguno (objetos comprimidos), usa el mayor /Count."""
    n = len(re.findall(rb"/Type\s*/Page(?![A-Za-z])", datos))
    if n:
        return n
    counts = [int(c) for c in re.findall(rb"/Count\s+(\d+)", datos)]
    return max(counts) if counts else 0


def buscar_chrome(explicito=None, entorno=None):
    """Ruta del ejecutable de Chrome/Chromium o None."""
    entorno = os.environ if entorno is None else entorno
    for c in (explicito, entorno.get("CHROME")):
        if c:
            return c if Path(c).exists() else (shutil.which(c) or None)
    if Path(MAC_CHROME).exists():
        return MAC_CHROME
    for b in BINARIOS_PATH:
        r = shutil.which(b)
        if r:
            return r
    return None


def imprimir_pdf(chrome, html_path, pdf_path):
    """Imprime con Chrome sin interfaz; prueba --headless=new y luego --headless."""
    ultimo = ""
    for modo in ("--headless=new", "--headless"):
        if pdf_path.exists():
            pdf_path.unlink()
        cmd = [chrome, modo, "--disable-gpu", "--no-pdf-header-footer",
               "--print-to-pdf=%s" % pdf_path, "file://%s" % html_path]
        try:
            r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               timeout=120)
        except (OSError, subprocess.TimeoutExpired) as e:
            ultimo = str(e)
            continue
        if pdf_path.exists() and pdf_path.stat().st_size > 0:
            return True, ""
        ultimo = r.stderr.decode("utf-8", "replace")[-400:]
    return False, ultimo


def tamanos():
    n = int(round((LETRA_MAX - LETRA_MIN) / PASO))
    return [LETRA_MAX - k * PASO for k in range(n + 1)]


def main(argv=None):
    ap = argparse.ArgumentParser(description="PDF de una página A4 desde el Markdown de la propuesta.")
    ap.add_argument("--entrada", default=str(RAIZ / "entrega" / "propuesta-normativa.md"))
    ap.add_argument("--salida", default=str(RAIZ / "entrega" / "propuesta-normativa.pdf"))
    ap.add_argument("--chrome", default=None, help="ruta al ejecutable de Chrome/Chromium")
    a = ap.parse_args(argv)

    entrada, salida = Path(a.entrada), Path(a.salida).resolve()
    if not entrada.is_file():
        print("ERROR: no existe el Markdown de entrada: %s" % entrada, file=sys.stderr)
        return 1
    chrome = buscar_chrome(a.chrome)
    if not chrome:
        print("ERROR: no encontré Chrome ni Chromium. Instalá Google Chrome, o pasá "
              "--chrome RUTA, o definí la variable de entorno CHROME.", file=sys.stderr)
        return 1

    cuerpo = markdown_a_html(entrada.read_text(encoding="utf-8"))
    salida.parent.mkdir(parents=True, exist_ok=True)
    elegido = None
    with tempfile.TemporaryDirectory(prefix="propuesta_pdf_") as tmp:
        tmp = Path(tmp)
        html_path, prueba = tmp / "propuesta.html", tmp / "prueba.pdf"
        for pt in tamanos():
            html_path.write_text(armar_html(cuerpo, pt), encoding="utf-8")
            ok, err = imprimir_pdf(chrome, html_path, prueba)
            if not ok:
                print("ERROR: Chrome no pudo generar el PDF. Detalle: %s" % err, file=sys.stderr)
                return 1
            paginas = contar_paginas(prueba.read_bytes())
            if paginas == 1:
                shutil.copyfile(prueba, salida)
                elegido = (pt, paginas)
                break
    if not elegido:
        print("ERROR: el texto no entra en 1 página ni a %gpt. Acortá el Markdown "
              "(entrega/propuesta-normativa.md) y volvé a correr." % LETRA_MIN, file=sys.stderr)
        return 1
    print("PDF: %s" % salida)
    print("Tamaño de letra: %gpt" % elegido[0])
    print("Páginas: %d" % elegido[1])
    return 0


if __name__ == "__main__":
    sys.exit(main())
