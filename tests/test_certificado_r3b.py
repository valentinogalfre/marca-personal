"""Contrato (pedido del coordinador, R3B): si el simulador está en https con un certificado que este Python no
reconoce, `chequear` y el arranque de `servir` (los dos usan revision_previa) siguen dando ✗, y además dicen en criollo
qué hacer. No hay ninguna opción para saltear la verificación. Un error de red común no trae ese aviso."""
import shutil
import ssl
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from marca import __main__ as principal
from marca.simulador import ErrorRed


class TestDeteccion(unittest.TestCase):
    def test_cadena_de_causas(self):
        try:
            try:
                raise ssl.SSLCertVerificationError(1, "verificación")
            except ssl.SSLCertVerificationError as causa:
                raise ErrorRed("<urlopen error algo>") from causa
        except ErrorRed as err:
            self.assertTrue(principal.es_error_de_certificado(err))

    def test_solo_el_texto(self):
        self.assertTrue(principal.es_error_de_certificado(
            ErrorRed("<urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed>")))

    def test_un_error_de_red_comun_no(self):
        try:
            try:
                raise ConnectionRefusedError(61, "Connection refused")
            except ConnectionRefusedError as causa:
                raise ErrorRed("<urlopen error [Errno 61] Connection refused>") from causa
        except ErrorRed as err:
            self.assertFalse(principal.es_error_de_certificado(err))

    def test_sin_opcion_para_saltear(self):
        texto = (Path(principal.__file__)).read_text(encoding="utf-8")
        for prohibido in ("CERT_NONE", "_create_unverified_context", "check_hostname = False", "--inseguro"):
            self.assertNotIn(prohibido, texto)


class _Cualquiera(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")


@unittest.skipUnless(shutil.which("openssl"), "sin openssl para armar un certificado propio")
class TestSimuladorHttpsDeVerdad(unittest.TestCase):
    def test_chequear_explica_el_certificado(self):
        with tempfile.TemporaryDirectory() as d:
            cert, clave = Path(d) / "c.pem", Path(d) / "k.pem"
            subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj",
                            "/CN=127.0.0.1", "-keyout", str(clave), "-out", str(cert)],
                           check=True, capture_output=True)
            srv = HTTPServer(("127.0.0.1", 0), _Cualquiera)
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(str(cert), str(clave))
            srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            try:
                res = principal.revision_previa(f"https://127.0.0.1:{srv.server_address[1]}", Path(d) / "no.json")
            finally:
                srv.shutdown()
                srv.server_close()
        self.assertFalse(res[0][0])
        self.assertIn("No hay conexión con el simulador", res[0][1])
        self.assertEqual(res[-1], (False, principal.AVISO_CERTIFICADO))


if __name__ == "__main__":
    unittest.main()
