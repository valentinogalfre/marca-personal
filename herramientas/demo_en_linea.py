#!/usr/bin/env python3
"""Demo en línea: partidos de práctica uno detrás de otro, con la plataforma abierta a internet.

Solo para mostrar la plataforma (Railway, ver el Dockerfile). No es el partido final: ahí firman personas.

Cada vuelta:
1. Arranca el simulador oficial (python3 -I) con el escenario de práctica, en un puerto que solo ve esta máquina.
2. Arranca `python3 -m marca servir --nueva --host 0.0.0.0` en el puerto público (variable PORT).
3. Con --demora-juez-s > 0, un juez automático de ensayo por cada juez firma, como una persona, lo que lleva ese
   tiempo esperando. Quien entra como juez desde el celular firma antes y el automático sigue con lo que quede.
4. Cuando el partido termina, deja todo quieto --pausa-final-min minutos para mirar el resultado y empieza otro.

Los usuarios salen de la variable MARCA_USUARIOS_JSON (el contenido del archivo que arma «python3 -m marca
claves») o de --config. Con las contraseñas publicadas en el repo (config/jueces_demo.json) no arranca: cualquiera
que haya leído el repo entraría como el juez. Nunca muestra contraseñas.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import List, Optional

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "herramientas"))
from ensayo import ENV_HIJOS, PY, esperar, opciones_juez, parar, pedir_json  # noqa: E402
from juez_automatico import AVISO, JuezAutomatico  # noqa: E402
from marca.__main__ import usuarios_con_clave_publicada  # noqa: E402

EXIT_CONFIG = 2      # faltan los usuarios, no se pueden leer o tienen contraseñas publicadas
EXIT_PLATAFORMA = 3  # la plataforma no arranca (no tiene sentido reintentar en bucle)


def preparar_usuarios(texto: Optional[str], ruta_config: Optional[str], destino: Path) -> Path:
    """Ruta del archivo de usuarios a usar. Con `texto` (MARCA_USUARIOS_JSON) lo escribe en `destino` con permisos
    600. SystemExit(EXIT_CONFIG) si no hay usuarios, no es JSON, no tiene jueces o alguna contraseña es de las
    publicadas en el repo. Nunca imprime el contenido."""
    if texto and texto.strip():
        try:
            datos = json.loads(texto)
        except ValueError:
            raise SystemExit(_falla("MARCA_USUARIOS_JSON no es un JSON válido."))
        destino.parent.mkdir(parents=True, exist_ok=True)
        temporal = destino.with_name(f".{destino.name}.{os.getpid()}.tmp")
        fd = os.open(str(temporal), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False)
        os.chmod(str(temporal), 0o600)
        os.replace(str(temporal), str(destino))
        ruta = destino
    elif ruta_config:
        ruta = Path(ruta_config)
        try:
            with open(ruta, encoding="utf-8") as f:
                datos = json.load(f)
        except (OSError, ValueError) as err:
            raise SystemExit(_falla(f"No se puede leer {ruta} ({type(err).__name__})."))
    else:
        raise SystemExit(_falla("Faltan los usuarios: pasar MARCA_USUARIOS_JSON (el contenido del archivo que arma "
                                "«python3 -m marca claves») o --config."))
    usuarios = [u for u in (datos.get("usuarios") or []) if isinstance(u, dict)] if isinstance(datos, dict) else []
    if not any(u.get("rol") == "juez" for u in usuarios):
        raise SystemExit(_falla("El archivo de usuarios no tiene ningún juez."))
    expuestos = usuarios_con_clave_publicada(ruta)
    if expuestos:
        raise SystemExit(_falla(f"{len(expuestos)} usuario(s) ({', '.join(expuestos)}) tienen contraseñas publicadas "
                                "en el repo (config/jueces_demo.json). Armar unas nuevas con «python3 -m marca "
                                "claves --salida <archivo>» y pasar ese archivo."))
    return ruta


def _falla(texto: str) -> str:
    print("[demo] ✗ " + texto, flush=True)
    return f"[demo] {texto}"


def limpiar(directorio: Path) -> None:
    """Deja `directorio` listo para un partido nuevo: borra la salida de la plataforma, las carpetas que apartó
    --nueva (`marca.anterior-*`), su candado y el registro del simulador. No toca el archivo de usuarios."""
    directorio.mkdir(parents=True, exist_ok=True)
    for hijo in directorio.iterdir():
        if (hijo.name == "marca" or hijo.name.startswith("marca.anterior-")) and hijo.is_dir():
            shutil.rmtree(hijo, ignore_errors=True)
        elif hijo.name in ("marca.candado", "registro.jsonl", "simulador.log"):
            hijo.unlink()


class Demo:
    def __init__(self, args, usuarios: Path) -> None:
        self.args = args
        self.usuarios = usuarios
        self.directorio = Path(args.dir)
        self.repo = Path(args.repo_desafio).resolve()
        self.parar_todo = threading.Event()
        self.sim: Optional[subprocess.Popen] = None
        self.plataforma: Optional[subprocess.Popen] = None
        self.jueces: List[JuezAutomatico] = []

    def url_sim(self, ruta: str = "") -> str:
        return f"http://127.0.0.1:{self.args.puerto_simulador}{ruta}"

    def minuto(self) -> Optional[float]:
        try:
            return float(pedir_json(self.url_sim("/estado"))["minuto_actual"])
        except Exception:
            return None

    def dormir(self, segundos: float) -> bool:
        """True si hay que parar todo (SIGTERM de Railway)."""
        return self.parar_todo.wait(segundos)

    def vuelta(self, numero: int) -> None:
        a = self.args
        limpiar(self.directorio)
        print(f"[demo] partido {numero}: simulador ×{a.acelerar:g}"
              + (f", juez automático a {a.demora_juez_s:g} s" if a.demora_juez_s > 0 else ", sin juez automático"),
              flush=True)
        sim_log = open(self.directorio / "simulador.log", "w", encoding="utf-8")
        self.sim = subprocess.Popen(
            [PY, "-I", str(self.repo / "simulador" / "servidor.py"),
             "--escenario", str(self.repo / "datos" / "escenario_practica.json"), "--datos", str(self.repo / "datos"),
             "--acelerar", str(a.acelerar), "--inicio-min", "0", "--puerto", str(a.puerto_simulador),
             "--log", str(self.directorio / "registro.jsonl")],
            cwd=str(self.directorio), stdout=sim_log, stderr=subprocess.STDOUT, env=ENV_HIJOS)
        try:
            fin = float(esperar(self.url_sim("/estado"), 30)["fin_min"])
            self.plataforma = subprocess.Popen(
                [PY, "-m", "marca", "servir", "--simulador", self.url_sim(), "--host", a.host,
                 "--puerto", str(a.puerto), "--salida", str(self.directorio / "marca"), "--config", str(self.usuarios),
                 "--nueva"], cwd=str(RAIZ), env=ENV_HIJOS)
            base = f"http://127.0.0.1:{a.puerto}"
            try:
                esperar(base + "/api/salud", 60)
            except SystemExit:
                codigo = self.plataforma.poll()
                raise SystemExit(_falla(f"La plataforma no arrancó (salida {codigo}): ver el registro de arriba."))
            if a.demora_juez_s > 0:
                print(AVISO, flush=True)
                with open(self.usuarios, encoding="utf-8") as f:
                    cfg = json.load(f)
                demora_min = a.demora_juez_s * a.acelerar / 60.0
                for u in cfg["usuarios"]:
                    if u.get("rol") == "juez":
                        j = JuezAutomatico(base, u["usuario"], u["clave_demo"], demora_min,
                                           registro=lambda t: print(t, flush=True), **opciones_juez(True))
                        j.iniciar()
                        self.jueces.append(j)
            tope = time.monotonic() + (fin + 10) * 60.0 / max(a.acelerar, 0.01) + 300
            while not self.parar_todo.is_set():
                m = self.minuto()
                if m is not None and m >= fin + 5.5:
                    break
                if self.plataforma.poll() is not None:
                    print("[demo] la plataforma terminó sola: se empieza otro partido", flush=True)
                    return
                if time.monotonic() > tope:
                    print("[demo] el simulador no llegó al final a tiempo: se empieza otro partido", flush=True)
                    return
                self.dormir(2.0)
            self.detener_jueces()
            if not self.parar_todo.is_set():
                print(f"[demo] partido {numero} terminado: queda a la vista {a.pausa_final_min:g} min", flush=True)
                self.dormir(a.pausa_final_min * 60.0)
        finally:
            self.detener_jueces()
            parar(self.plataforma)
            parar(self.sim)
            sim_log.close()
            self.plataforma = self.sim = None

    def detener_jueces(self) -> None:
        for j in self.jueces:
            j.detener()
        self.jueces = []

    def correr(self) -> int:
        def terminar(*_):
            print("[demo] señal de parada: se apaga todo", flush=True)
            self.parar_todo.set()

        signal.signal(signal.SIGTERM, terminar)
        signal.signal(signal.SIGINT, terminar)
        numero = 0
        while not self.parar_todo.is_set():
            numero += 1
            self.vuelta(numero)
            if self.args.vueltas and numero >= self.args.vueltas:
                break
            self.dormir(2.0)   # que el puerto quede libre antes del próximo partido
        return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Demo en línea de Marca Personal: partidos de práctica en bucle")
    p.add_argument("--repo-desafio", default=os.environ.get("DESAFIO_FUTBOL_REPO"),
                   help="carpeta del repo oficial qualydata-org/desafio-futbol (o DESAFIO_FUTBOL_REPO)")
    p.add_argument("--puerto", type=int, default=int(os.environ.get("PORT") or 8080))
    p.add_argument("--host", default="0.0.0.0", help="0.0.0.0 = abierta a la red (Railway); 127.0.0.1 para probar")
    p.add_argument("--puerto-simulador", type=int, default=8791)
    p.add_argument("--acelerar", type=float, default=float(os.environ.get("DEMO_ACELERAR") or 4))
    p.add_argument("--demora-juez-s", type=float, default=float(os.environ.get("DEMO_DEMORA_JUEZ_S") or 25),
                   help="segundos reales que espera el juez automático antes de firmar; 0 = sin juez automático")
    p.add_argument("--pausa-final-min", type=float, default=float(os.environ.get("DEMO_PAUSA_FINAL_MIN") or 8),
                   help="minutos reales que queda a la vista el resultado antes del próximo partido")
    p.add_argument("--dir", default=os.environ.get("DEMO_DIR") or "/tmp/marca-demo")
    p.add_argument("--config", default=None, help="archivo de usuarios (si no viene MARCA_USUARIOS_JSON)")
    p.add_argument("--vueltas", type=int, default=0, help="cantidad de partidos (0 = sin fin)")
    args = p.parse_args(argv)
    if not args.repo_desafio or not (Path(args.repo_desafio) / "simulador" / "servidor.py").is_file():
        raise SystemExit(_falla("Falta el repo oficial: --repo-desafio <carpeta con simulador/servidor.py>."))
    usuarios = preparar_usuarios(os.environ.get("MARCA_USUARIOS_JSON"), args.config, Path(args.dir) / "usuarios.json")
    return Demo(args, usuarios).correr()


if __name__ == "__main__":
    sys.exit(main())
