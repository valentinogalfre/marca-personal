import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "herramientas"))
import propuesta_pdf as p  # noqa: E402


class TestMarkdown(unittest.TestCase):
    def test_negrita_y_cursiva(self):
        """Contrato: **x** -> <strong> y *x* -> <em>, sin mezclarse."""
        h = p.markdown_a_html("Hola **fuerte** y *suave*.")
        self.assertIn("<strong>fuerte</strong>", h)
        self.assertIn("<em>suave</em>", h)
        self.assertNotIn("*", h)

    def test_escape_html(self):
        """Contrato: el texto del usuario nunca inyecta HTML (< > &)."""
        h = p.markdown_a_html("a < b & c > d <script>")
        self.assertIn("a &lt; b &amp; c &gt; d &lt;script&gt;", h)
        self.assertNotIn("<script>", h)

    def test_codigo_no_interpreta_markdown(self):
        """Contrato: dentro de `código` no se aplica negrita y se escapa."""
        h = p.markdown_a_html("usar `a**b** <x>` ya")
        self.assertIn("<code>a**b** &lt;x&gt;</code>", h)

    def test_titulos_y_parrafos(self):
        """Contrato: # -> h1, ## -> h2; líneas contiguas forman un párrafo y la línea en blanco separa."""
        h = p.markdown_a_html("# T\n\n## S\n\nuno\ndos\n\ntres")
        self.assertIn("<h1>T</h1>", h)
        self.assertIn("<h2>S</h2>", h)
        self.assertIn("<p>uno dos</p>", h)
        self.assertIn("<p>tres</p>", h)

    def test_tabla(self):
        """Contrato: tabla con encabezado y 2 filas -> 3 <tr>, 1 fila de <th> y 4 <td>."""
        md = "| A | B |\n|---|---|\n| 1 | **2** |\n| 3 | 4 |\n"
        h = p.markdown_a_html(md)
        self.assertEqual(h.count("<tr>"), 3)
        self.assertEqual(h.count("<th>"), 2)
        self.assertEqual(h.count("<td>"), 4)
        self.assertIn("<td><strong>2</strong></td>", h)

    def test_comentario_ignorado(self):
        """Contrato: los comentarios HTML (también multilínea) no llegan a la salida."""
        h = p.markdown_a_html("antes\n<!-- secreto\nmultilínea -->\ndespués")
        self.assertNotIn("secreto", h)
        self.assertNotIn("&lt;!--", h)
        self.assertIn("antes", h)
        self.assertIn("después", h)

    def test_barra_sin_separador_es_parrafo(self):
        """Contrato: algo que no se entiende (barras sin fila separadora) queda como párrafo."""
        h = p.markdown_a_html("| solo | una |")
        self.assertNotIn("<table>", h)
        self.assertIn("<p>", h)

    def test_css_a4_y_letra(self):
        """Contrato: el HTML fija A4 con márgenes 11mm 12mm y el tamaño de letra pedido."""
        h = p.armar_html("<p>x</p>", 8.5)
        self.assertIn("size: A4; margin: 11mm 12mm;", h)
        self.assertIn("font-size: 8.5pt", h)


class TestPaginas(unittest.TestCase):
    def test_cuenta_page_sin_pages(self):
        """Contrato: se cuentan /Type /Page y no /Type /Pages."""
        b = (b"1 0 obj<</Type /Pages /Count 2>>endobj "
             b"2 0 obj<</Type /Page>>endobj 3 0 obj<</Type/Page/Parent 1 0 R>>endobj")
        self.assertEqual(p.contar_paginas(b), 2)

    def test_fallback_count(self):
        """Contrato: sin objetos /Page visibles (comprimidos), se usa /Count del árbol."""
        self.assertEqual(p.contar_paginas(b"<</Type /Pages /Count 1>>"), 1)

    def test_vacio(self):
        """Contrato: bytes sin páginas dan 0 (nunca se confunde con 1)."""
        self.assertEqual(p.contar_paginas(b"nada"), 0)

    def test_tamanos(self):
        """Contrato: se prueba de 10pt a 7.5pt en pasos de 0,25pt."""
        t = p.tamanos()
        self.assertEqual(t[0], 10.0)
        self.assertEqual(t[-1], 7.5)
        self.assertEqual(len(t), 11)


if __name__ == "__main__":
    unittest.main()
