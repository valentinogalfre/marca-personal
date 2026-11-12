#!/usr/bin/env python3
"""Proxy HTTP local que agrega demora (y, si se pide, fallas) entre la plataforma y el simulador.

Sirve para ensayar con una red parecida a la del evento: la plataforma habla con el proxy y el proxy con el
simulador oficial. Solo biblioteca estándar; escucha en 127.0.0.1.

    python3 herramientas/proxy_latencia.py --destino http://127.0.0.1:8781 --puerto 8783 --latencia-ms 400

- `--latencia-ms N`: demora total de ida y vuelta de cada pedido, en milisegundos. La mitad se espera antes de
  reenviar el pedido al simulador y la otra mitad antes de devolver la respuesta.
- `--jitter-ms J`: a cada pedido se le suma un valor al azar entre -J y +J (la demora nunca baja de 0).
- `--falla-cada N`: el pedido número N, 2N, 3N… no llega al simulador: el proxy responde 502 (como un
  intermediario caído). Así se prueba que la plataforma reintenta sin duplicar.
- `--semilla S`: fija el azar del jitter para repetir un ensayo igual.
- `--registro archivo.jsonl`: anota cada pedido (método, ruta, demora aplicada, estado devuelto).

También se usa como módulo: `arrancar(puerto, destino, latencia_ms, jitter_ms, falla_cada, semilla)` devuelve el
servidor ya escuchando en un hilo; `Proxy.pedidos` tiene lo que pasó por él.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

MAX_CUERPO = 1_000_000


class Proxy(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, puerto: int, destino: str, latencia_ms: float = 0.0, jitter_ms: float = 0.0,
                 falla_cada: int = 0, semilla: Optional[int] = None, registro: Optional[str] = None,
                 host: str = "127.0.0.1") -> None:
        self._registro = None  # antes del bind: si el puerto está ocupado, server_close() corre igual
        super().__init__((host, puerto), _Manejador)
        self.destino = destino.rstrip("/")
        self.latencia_ms = max(0.0, float(latencia_ms))
        self.jitter_ms = max(0.0, float(jitter_ms))
        self.falla_cada = max(0, int(falla_cada or 0))
        self._azar = random.Random(semilla)
        self._candado = threading.Lock()
        self._cuenta = 0
        self.pedidos: list = []
        self._registro = open(registro, "a", encoding="utf-8") if registro else None
        self._abridor = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def turno(self) -> tuple:
        """Número de pedido, demora total en segundos y si este pedido falla."""
        with self._candado:
            self._cuenta += 1
            n = self._cuenta
            extra = self._azar.uniform(-self.jitter_ms, self.jitter_ms) if self.jitter_ms else 0.0
        demora = max(0.0, self.latencia_ms + extra) / 1000.0
        falla = bool(self.falla_cada) and n % self.falla_cada == 0
        return n, demora, falla

    def anotar(self, fila: dict) -> None:
        with self._candado:
            self.pedidos.append(fila)
            if self._registro:
                self._registro.write(json.dumps(fila, ensure_ascii=False) + "\n")
                self._registro.flush()

    def server_close(self) -> None:
        super().server_close()
        if getattr(self, "_registro", None):
            self._registro.close()
            self._registro = None


class _Manejador(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    timeout = 30

    def log_message(self, *a) -> None:  # el registro va a --registro, no a la consola
        pass

    def _responder(self, estado: int, cuerpo: bytes, tipo: str = "application/json") -> None:
        self.send_response(estado)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(cuerpo)

    def _reenviar(self, metodo: str) -> None:
        srv: Proxy = self.server  # type: ignore[assignment]
        t0 = time.monotonic()
        crudo = (self.headers.get("Content-Length") or "0").strip()
        largo = int(crudo) if crudo.isdigit() else -1
        if largo < 0 or largo > MAX_CUERPO:
            self.close_connection = True
            self._responder(400, b'{"error": "Content-Length invalido"}')
            return
        cuerpo = self.rfile.read(largo) if largo else None
        n, demora, falla = srv.turno()
        time.sleep(demora / 2)
        if falla:
            estado, datos, tipo = 502, b'{"error": "proxy_latencia: falla inyectada"}', "application/json"
        else:
            req = urllib.request.Request(srv.destino + self.path, data=cuerpo, method=metodo,
                                         headers={"Content-Type": self.headers.get("Content-Type",
                                                                                   "application/json"),
                                                  "Accept": "application/json"})
            try:
                with srv._abridor.open(req, timeout=30) as r:
                    estado, datos = r.status, r.read()
                    tipo = r.headers.get("Content-Type", "application/json")
            except urllib.error.HTTPError as e:
                estado, datos = e.code, e.read()
                tipo = e.headers.get("Content-Type", "application/json") if e.headers else "application/json"
            except Exception as e:  # simulador caído o colgado: el proxy contesta 502, como un intermediario real
                estado, datos, tipo = 502, json.dumps({"error": f"proxy_latencia: {e}"}).encode(), "application/json"
        time.sleep(demora / 2)
        srv.anotar({"n": n, "metodo": metodo, "ruta": self.path, "demora_ms": round(demora * 1000, 1),
                    "falla_inyectada": falla, "estado": estado, "total_ms": round((time.monotonic() - t0) * 1000, 1)})
        self._responder(estado, datos, tipo)

    def do_GET(self) -> None:
        self._reenviar("GET")

    def do_POST(self) -> None:
        self._reenviar("POST")


def arrancar(puerto: int, destino: str, latencia_ms: float = 0.0, jitter_ms: float = 0.0, falla_cada: int = 0,
             semilla: Optional[int] = None, registro: Optional[str] = None) -> Proxy:
    srv = Proxy(puerto, destino, latencia_ms, jitter_ms, falla_cada, semilla, registro)
    threading.Thread(target=srv.serve_forever, name="proxy-latencia", daemon=True).start()
    return srv


def main() -> int:
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(description="Proxy local con demora entre la plataforma y el simulador")
    p.add_argument("--destino", required=True, help="URL del simulador, p. ej. http://127.0.0.1:8781")
    p.add_argument("--puerto", type=int, required=True, help="puerto donde escucha el proxy (127.0.0.1)")
    p.add_argument("--latencia-ms", type=float, default=0.0)
    p.add_argument("--jitter-ms", type=float, default=0.0)
    p.add_argument("--falla-cada", type=int, default=0)
    p.add_argument("--semilla", type=int, default=None)
    p.add_argument("--registro", default=None)
    a = p.parse_args()
    try:
        srv = Proxy(a.puerto, a.destino, a.latencia_ms, a.jitter_ms, a.falla_cada, a.semilla, a.registro)
    except OSError as e:
        print(f"No se pudo abrir el puerto {a.puerto}: {e}", file=sys.stderr)
        return 4
    print(f"Proxy en http://127.0.0.1:{a.puerto} → {a.destino} · demora {a.latencia_ms:g} ms ± {a.jitter_ms:g} ms"
          + (f" · 502 cada {a.falla_cada} pedidos" if a.falla_cada else ""), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
