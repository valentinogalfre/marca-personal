"""Línea de comandos: servir | chequear | claves | exportar | verificar."""
from __future__ import annotations

import argparse
import hmac
import ipaddress
import json
import os
import secrets
import signal
import socket
import ssl
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

from . import VERSION

RAIZ = Path(__file__).resolve().parent.parent
CONFIG = RAIZ / "config" / "jueces_demo.json"          # va al repo público: contraseñas de demostración
CONFIG_FINAL = RAIZ / "config" / "jueces_final.json"   # contraseñas propias, fuera del repo (.gitignore)
WEB = Path(__file__).resolve().parent / "web"
PANTALLAS = ("index.html", "juez.html", "sala.html", "transparencia.html", "orden.html")


def _imprimir(texto: str = "") -> None:
    print(texto, flush=True)


def salida_utf8() -> None:
    """En Windows, con la salida redirigida, ✓ y ✗ no existen en la página de códigos: se fuerza UTF-8."""
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


# --- candado de la carpeta de salida -----------------------------------------------------------

EXIT_OCUPADA = 3       # otra plataforma tiene la carpeta
EXIT_PUERTO = 4        # el puerto no se puede abrir
EXIT_NUEVA = 5         # --nueva rechazado (el simulador ya tiene órdenes, o no se pudo comprobar)
EXIT_CLAVES = 6        # abierta a la red con contraseñas publicadas en el repo


# --- contraseñas publicadas y red (C18) ---------------------------------------------------------


def es_loopback(host) -> bool:
    """Solo esta máquina: «localhost» o una IP de loopback. 0.0.0.0, «::», «» y cualquier otro nombre son la red."""
    host = str(host or "").strip()
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def _leer_usuarios(ruta) -> list:
    try:
        with open(ruta, encoding="utf-8") as f:
            datos = json.load(f)
        return [u for u in (datos.get("usuarios") or []) if isinstance(u, dict)]
    except (OSError, ValueError, AttributeError):
        return []


def usuarios_con_clave_publicada(config, publicado=None) -> list:
    """Nombres de los usuarios de `config` cuya contraseña es alguna de las publicadas en config/jueces_demo.json.

    Compara en tiempo constante y nunca devuelve ni muestra contraseñas. Detecta también una copia del archivo
    de demostración en otra ruta.
    """
    publicadas = [str(u.get("clave_demo")).encode("utf-8") for u in _leer_usuarios(publicado or CONFIG)
                  if u.get("clave_demo") is not None]
    expuestos = []
    for u in _leer_usuarios(config):
        clave = str(u.get("clave_demo") if u.get("clave_demo") is not None else "").encode("utf-8")
        if clave and any(hmac.compare_digest(clave, p) for p in publicadas):
            expuestos.append(str(u.get("usuario")))
    return expuestos


def aviso_red(host, config, publicado=None):
    """(ok, texto) para `chequear`/`servir`, o None si la plataforma queda solo en esta máquina."""
    if es_loopback(host):
        return None
    expuestos = usuarios_con_clave_publicada(config, publicado)
    if not expuestos:
        return (True, f"Abierta a la red (--host {host}) con contraseñas propias ({config})")
    return (False, f"Abierta a la red (--host {host}) y {len(expuestos)} usuario(s) ({', '.join(expuestos)}) tienen "
                   f"contraseñas publicadas en el repo (config/jueces_demo.json): cualquiera que lo haya leído "
                   "entraría como el juez y firmaría en su nombre. Armar contraseñas nuevas con "
                   "«python3 -m marca claves --salida config/jueces_final.json» y pasar "
                   "«--config config/jueces_final.json».")


def armar_claves(salida, reemplazar: bool = False, origen=None, imprimir=_imprimir) -> int:
    """`claves`: el archivo de usuarios del partido final, con contraseñas de ingreso nuevas al azar.

    Mismo contenido que el de demostración (usuarios, roles, jueces y claves de firma, que tienen que ser las del
    simulador). Permisos 600. No pisa un archivo existente sin `reemplazar`. Nunca imprime contraseñas.
    """
    origen = Path(origen or CONFIG)
    salida = Path(salida)
    if salida.exists() and not reemplazar:
        imprimir(f"✗ {salida} ya existe: no se pisó. Para generar contraseñas nuevas, agregar --reemplazar "
                 "(las anteriores dejan de valer).")
        return 1
    try:
        with open(origen, encoding="utf-8") as f:
            datos = json.load(f)
    except (OSError, ValueError) as err:
        imprimir(f"✗ No se pudo leer {origen}: {err}")
        return 1
    usuarios = [dict(u) for u in datos.get("usuarios") or [] if isinstance(u, dict)]
    if not usuarios:
        imprimir(f"✗ {origen} no tiene usuarios.")
        return 1
    for u in usuarios:
        u["clave_demo"] = secrets.token_urlsafe(12)
    datos["usuarios"] = usuarios
    datos["aviso"] = ("Usuarios del partido final: contraseñas propias, NO publicar (está en .gitignore). Las "
                      "claves de firma son las del simulador. Generado con «python3 -m marca claves».")
    temporal = salida.with_name(f".{salida.name}.{os.getpid()}.tmp")
    no_se_pudo = (f"✗ No se pudo escribir {salida}: {{}}. Elegir con --salida una ruta en una carpeta donde se "
                  "pueda escribir.")
    try:
        salida.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(temporal), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError as err:
        imprimir(no_se_pudo.format(err.strerror or err))
        return 1
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.chmod(str(temporal), 0o600)
        os.replace(str(temporal), str(salida))
    except BaseException as err:
        try:
            os.unlink(str(temporal))
        except OSError:
            pass
        if isinstance(err, OSError):
            imprimir(no_se_pudo.format(err.strerror or err))
            return 1
        raise
    imprimir(f"✓ Usuarios del partido final en {salida} (permisos 600; no va al repo).")
    imprimir("  Usuarios: " + ", ".join(f"{u.get('usuario')} ({u.get('rol')})" for u in usuarios))
    imprimir("  Las contraseñas están solo en ese archivo: abrirlo en esta computadora y pasárselas a cada juez "
             "en persona. No se muestran acá.")
    imprimir(f"  Servir con: python3 -m marca servir … --host 0.0.0.0 --config {salida}")
    return 0


def cmd_claves(args) -> int:
    return armar_claves(args.salida, args.reemplazar)


def ruta_candado(salida) -> Path:
    """`<salida>.candado`, al lado de la carpeta: no se mueve cuando --nueva aparta la carpeta."""
    salida = Path(salida).resolve()
    return salida.with_name(salida.name + ".candado")


class CandadoSalida:
    """Candado exclusivo de una carpeta de salida, del sistema operativo (fcntl o msvcrt).

    Lo suelta el sistema cuando el proceso termina, aunque sea por un SIGKILL o un corte de luz: no
    quedan candados viejos. Se toma antes de leer, mover o escribir nada en la carpeta.
    """

    def __init__(self, salida) -> None:
        self.ruta = ruta_candado(salida)
        self._f = None

    def tomar(self) -> bool:
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self.ruta), os.O_RDWR | os.O_CREAT, 0o644)
        f = os.fdopen(fd, "r+", encoding="utf-8")
        try:
            if os.name == "nt":
                import msvcrt
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            f.close()
            return False
        self._f = f
        self.anotar()
        return True

    def anotar(self, **datos) -> None:
        if self._f is None:
            return
        try:
            self._f.seek(0)
            self._f.truncate()
            self._f.write(json.dumps(dict({"pid": os.getpid()}, **datos), ensure_ascii=False))
            self._f.flush()
        except OSError:
            pass

    def info_ajena(self) -> dict:
        try:
            with open(self.ruta, encoding="utf-8") as f:
                datos = json.loads(f.read() or "{}")
            return datos if isinstance(datos, dict) else {}
        except (OSError, ValueError):
            return {}

    def soltar(self) -> None:
        if self._f is not None:
            try:
                self._f.close()  # cerrar suelta el candado
            except OSError:
                pass
            self._f = None


def ordenes_en_simulador(cliente, espera_s: float = 20.0):
    """{proveedor: cantidad de órdenes} del simulador, o None si no responde en espera_s."""
    from .simulador import ErrorRed
    limite = time.monotonic() + espera_s
    while True:
        try:
            return {p["id"]: len(cliente.ordenes(p["id"]) or []) for p in cliente.proveedores()}
        except (ErrorRed, KeyError, TypeError, ValueError):
            if time.monotonic() >= limite:
                return None
            time.sleep(0.5)


def apartar_salida(salida):
    """Mueve la carpeta con estado a `<salida>.anterior-<fecha>`. Nunca borra. Devuelve el destino o None."""
    import datetime
    salida = Path(salida)
    if not salida.exists() or (salida.is_dir() and not any(salida.iterdir())):
        return None
    fecha = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    destino = salida.with_name(f"{salida.name}.anterior-{fecha}")
    i = 2
    while destino.exists():
        destino = salida.with_name(f"{salida.name}.anterior-{fecha}-{i}")
        i += 1
    salida.rename(destino)
    return destino


def preparar_nueva(salida, cliente, descartar: bool, imprimir=_imprimir, espera_s: float = 20.0) -> int:
    """--nueva: se niega si el simulador ya tiene órdenes (salvo descartar); si sigue, aparta la carpeta."""
    cuentas = ordenes_en_simulador(cliente, espera_s)
    if cuentas is None:
        imprimir("✗ --nueva: no se pudo consultar al simulador si ya tiene órdenes. No se tocó la carpeta "
                 f"{salida}. Revisar la conexión y volver a intentar.")
        return EXIT_NUEVA
    total = sum(cuentas.values())
    if total and not descartar:
        detalle = ", ".join(f"{pid}: {n}" for pid, n in cuentas.items() if n)
        imprimir(f"✗ --nueva: el simulador ya tiene {total} órdenes en los proveedores ({detalle}): hay un partido "
                 "en curso.")
        imprimir("  Lo normal es reanudar: el mismo comando SIN --nueva (sigue desde lo guardado).")
        imprimir("  Solo si de verdad hay que empezar de cero sabiendo que esas órdenes quedan fuera de esta "
                 "auditoría, agregar --descartar-anteriores.")
        imprimir(f"  No se tocó la carpeta {salida}.")
        return EXIT_NUEVA
    if total:
        imprimir(f"! --nueva --descartar-anteriores: el simulador tiene {total} órdenes que no van a figurar en la "
                 "auditoría nueva.")
    destino = apartar_salida(salida)
    if destino is not None:
        imprimir(f"La salida anterior se apartó a {destino} (no se borró nada).")
    return 0


def revisar_sin_estado(salida, cliente, imprimir=_imprimir, espera_s: float = 20.0) -> int:
    """Sin --nueva y sin estado.json en la salida (robustez-1): si el simulador ya tiene órdenes, esto no es el
    arranque del partido sino una --salida equivocada. Se niega con 5 en vez de empezar de cero en silencio."""
    cuentas = ordenes_en_simulador(cliente, espera_s)
    if cuentas is None:
        imprimir(f"✗ No hay estado guardado en {salida} y no se pudo consultar al simulador si ya tiene órdenes. "
                 "No se tocó nada. Revisar la conexión y volver a intentar.")
        return EXIT_NUEVA
    total = sum(cuentas.values())
    if total:
        detalle = ", ".join(f"{pid}: {n}" for pid, n in cuentas.items() if n)
        imprimir(f"✗ No hay estado guardado en {salida} (falta estado.json) y el simulador ya tiene {total} órdenes "
                 f"({detalle}): hay un partido en curso. ¿Es la --salida correcta?")
        imprimir("  Para reanudar hace falta la carpeta del partido, la que tiene estado.json: el mismo comando con "
                 "esa --salida.")
        imprimir("  Solo si de verdad hay que empezar de cero sabiendo que esas órdenes quedan fuera de esta "
                 "auditoría: --nueva --descartar-anteriores.")
        imprimir(f"  No se tocó la carpeta {salida}.")
        return EXIT_NUEVA
    return 0


# --- chequear --------------------------------------------------------------------------------


AVISO_CERTIFICADO = ("Este Python no confía en el certificado de esa dirección. Probá con /usr/bin/python3 (usa los "
                     "certificados del sistema) o pedile a la organización una dirección http.")


def es_error_de_certificado(err: BaseException) -> bool:
    """¿El error de red es porque este Python no reconoce el certificado https? Mira la cadena de causas (y el
    `reason` de urllib) y, si no hay causa, el texto. No saltea nada: solo sirve para explicar el ✗."""
    vistos = set()
    e: object = err
    while e is not None and id(e) not in vistos:
        vistos.add(id(e))
        if isinstance(e, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in str(e):
            return True
        e = getattr(e, "reason", None) if isinstance(getattr(e, "reason", None), BaseException) \
            else (e.__cause__ or e.__context__) if isinstance(e, BaseException) else None
    return False


def revision_previa(simulador: str, config, salida=None) -> list:
    """Devuelve una lista de (ok, texto). No manda ninguna orden."""
    from .canon import min_txt
    from .simulador import Cliente, ErrorRed
    res = []
    cliente = Cliente(simulador, timeout=5)
    try:
        t0 = time.monotonic()
        est = cliente.estado()
        ms = (time.monotonic() - t0) * 1000
        res.append((True, f"Conexión con el simulador {simulador} ({ms:.0f} ms)"))
        res.append((True, f"Reloj: minuto {min_txt(est['minuto_actual'])}, fin {min_txt(est['fin_min'])}, "
                          f"x{est['acelerar']:g}"
                          + (" — el partido ya terminó" if est.get("finalizado") else "")))
    except ErrorRed as err:
        res.append((False, f"No hay conexión con el simulador {simulador}: {err}"))
        if es_error_de_certificado(err):
            res.append((False, AVISO_CERTIFICADO))
        return res
    try:
        partido = cliente.partido()
        res.append((bool(partido.get("marcas_de_agua_validas")),
                    f"Partido {partido.get('id')}: {partido.get('nombre')} "
                    f"({len(partido.get('marcas_de_agua_validas') or [])} marcas válidas, "
                    f"{len(partido.get('licenciatarios') or [])} licenciatarios)"))
        provs = cliente.proveedores()
        res.append((bool(provs), f"{len(provs)} proveedores: " + ", ".join(
            f"{p['id']} ({'+'.join(p.get('capacidades') or [])})" for p in provs)))
        sin_tipo = [p["id"] for p in provs if not p.get("capacidades")]
        if sin_tipo:
            res.append((False, f"Proveedores sin capacidades: {', '.join(sin_tipo)}"))
        jz = cliente.juzgados()
    except ErrorRed as err:
        res.append((False, f"Error leyendo el simulador: {err}"))
        return res
    try:
        with open(config, encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError) as err:
        res.append((False, f"No se pudo leer la configuración {config}: {err}"))
        return res
    usuarios = {u.get("juez_id") for u in cfg.get("usuarios") or [] if u.get("rol") == "juez"}
    claves = cfg.get("claves_firma_demo") or {}
    for t in jz.get("turnos") or []:
        j = t["juez_id"]
        res.append((j in usuarios and j in claves,
                    f"Turno {j} (min {min_txt(t['desde_min'])} a {min_txt(t['hasta_min'])}): "
                    + ("usuario y clave de firma configurados" if j in usuarios and j in claves
                       else "FALTA usuario o clave de firma en la configuración")))
    if not any(u.get("rol") == "fiscalia" for u in cfg.get("usuarios") or []):
        res.append((False, "No hay usuario de fiscalía para la sala"))
    if salida is not None:
        try:
            Path(salida).mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=salida, delete=True):
                pass
            res.append((True, f"La carpeta de salida {salida} se puede escribir"))
        except OSError as err:
            res.append((False, f"No se puede escribir en {salida}: {err}"))
    faltan = [p for p in PANTALLAS if not (WEB / p).exists()]
    res.append((not faltan, "Pantallas presentes en marca/web/" if not faltan
                else f"Faltan pantallas en marca/web/: {', '.join(faltan)}"))
    return res


AVISO_CONFIG_DEMO = ("! El archivo de usuarios tiene contraseñas publicadas en el repo (config/jueces_demo.json): "
                     "sirve para ensayos en esta máquina. Para el partido final, y siempre que se entre por un túnel "
                     "(publica la plataforma aunque escuche en 127.0.0.1), usar --config config/jueces_final.json "
                     "(se arma con «python3 -m marca claves»).")


def cmd_chequear(args) -> int:
    red = aviso_red(args.host, args.config)
    res = ([red] if red else []) + revision_previa(args.simulador, args.config, args.salida)
    for ok, texto in res:
        _imprimir(("✓ " if ok else "✗ ") + texto)
    if red is None and usuarios_con_clave_publicada(args.config):
        _imprimir(AVISO_CONFIG_DEMO)  # solo esta máquina: no es ✗ (los ensayos lo usan), pero se avisa
    malos = sum(1 for ok, _ in res if not ok)
    _imprimir("\nTodo listo." if not malos else f"\n{malos} problema(s) para resolver antes del partido.")
    return 0 if not malos else 1


# --- servir ---------------------------------------------------------------------------------


def _texto_ajena(info: dict) -> str:
    partes = []
    if info.get("pid"):
        partes.append(f"pid {info['pid']}")
    if info.get("puerto"):
        partes.append(f"puerto {info['puerto']}")
    return ", ".join(partes) or "sin datos"


def cmd_servir(args) -> int:
    from .api import abrir_servidor, instalar_motor
    from .motor import Motor
    from .simulador import Cliente
    from .usuarios import Usuarios

    salida = Path(args.salida)
    _imprimir(f"Marca Personal {VERSION}")
    # 0. Abierta a la red con contraseñas publicadas: no arranca y no toca nada (C18).
    red = aviso_red(args.host, args.config)
    if red and not red[0]:
        _imprimir("✗ " + red[1])
        _imprimir(f"  No se tocó nada (ni la carpeta {salida} ni el puerto).")
        return EXIT_CLAVES
    # 1. Antes de leer, mover o escribir nada en la carpeta: su candado, que no haya otra plataforma viva
    #    sobre ella y que el puerto se pueda abrir.
    candado = CandadoSalida(salida)
    try:
        tomado = candado.tomar()
    except OSError as err:
        _imprimir(f"✗ No se puede escribir junto a la carpeta de salida {salida} ({err.strerror or err}): revisar los "
                  "permisos o elegir otra --salida. No se tocó nada.")
        return 1
    if not tomado:
        _imprimir(f"✗ Ya hay una plataforma corriendo sobre la salida {salida} ({_texto_ajena(candado.info_ajena())}). "
                  "No se tocó nada.")
        _imprimir("  Si responde, no hace falta relanzarla: los jueces siguen entrando a la misma dirección.")
        _imprimir(f"  Candado: {candado.ruta} (lo suelta el sistema cuando esa plataforma termina).")
        return EXIT_OCUPADA
    if plataforma_viva(salida):
        _imprimir(f"✗ La plataforma de {salida} ya responde en /api/salud ({_texto_ajena(leer_info_plataforma(salida))}). "
                  "No se tocó nada.")
        candado.soltar()
        return EXIT_OCUPADA
    try:
        servidor = abrir_servidor(args.host, args.puerto)
    except OSError as err:
        _imprimir(f"✗ No se pudo abrir el puerto {args.puerto} en {args.host}: {err}. No se tocó la carpeta {salida}.")
        _imprimir("  ¿Hay otra plataforma u otro programa en ese puerto? Probar con otro --puerto.")
        candado.soltar()
        return EXIT_PUERTO
    try:
        return _servir(args, salida, candado, servidor, Motor, Cliente, Usuarios, instalar_motor)
    finally:
        servidor.server_close()
        candado.soltar()


def _servir(args, salida, candado, servidor, Motor, Cliente, Usuarios, instalar_motor) -> int:
    res = revision_previa(args.simulador, args.config, None)
    for ok, texto in res:
        _imprimir(("  ✓ " if ok else "  ✗ ") + texto)
    if args.nueva:
        codigo = preparar_nueva(salida, Cliente(args.simulador, timeout=5), args.descartar_anteriores)
        if codigo:
            return codigo
    elif not (salida / "estado.json").exists():
        codigo = revisar_sin_estado(salida, Cliente(args.simulador, timeout=5))
        if codigo:
            return codigo
    try:
        usuarios = Usuarios(args.config)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as err:
        _imprimir(f"✗ No se puede leer el archivo de usuarios {args.config} ({type(err).__name__}: {str(err)[:120]}). "
                  "Revisarlo (o volver a armarlo con «python3 -m marca claves») y arrancar de nuevo.")
        return 1
    motor = Motor(args.simulador, salida, usuarios, dinamica=not args.sin_dinamica, tick=args.tick)
    motor.arrancar(nueva=args.nueva)
    instalar_motor(servidor, motor)
    puerto = servidor.server_address[1]
    candado.anotar(host=args.host, puerto=puerto, instancia=motor.instancia)
    escribir_info_plataforma(salida, args.host, puerto, motor.instancia)
    base = f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '', '::') else args.host}:{puerto}"
    _imprimir(f"\nPlataforma en {base}  (seguimiento {'habilitado' if not args.sin_dinamica else 'deshabilitado'})")
    for nombre, ruta in (("Portada", "/"), ("Juez", "/juez"), ("Sala de situación", "/sala"),
                         ("Registro público", "/transparencia")):
        _imprimir(f"  {nombre:<18} {base}{ruta}")
    if args.host in ("0.0.0.0", "", "::"):
        ip = ip_red_local()
        if ip:
            _imprimir(f"  Desde el celular del juez (misma red): http://{ip}:{puerto}/juez")
        else:
            _imprimir("  Abierta a la red local, pero no se pudo averiguar la IP de esta computadora. Averiguarla con "
                      "«ipconfig getifaddr en0» (macOS), «hostname -I» (Linux) o «ipconfig» (Windows) y entrar a "
                      f"http://<esa IP>:{puerto}/juez")
    _imprimir(f"Salida: {salida}   Usuarios: ver {args.config}")

    parar = threading.Event()

    def terminar(*_):
        parar.set()

    signal.signal(signal.SIGTERM, terminar)
    signal.signal(signal.SIGINT, terminar)
    hilo = threading.Thread(target=servidor.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True)
    hilo.start()
    try:
        while not parar.is_set():
            parar.wait(0.5)
    finally:
        _imprimir("\nDeteniendo la plataforma…")
        servidor.shutdown()
        motor.detener()
        try:
            (salida / ARCHIVO_INFO).unlink()
        except OSError:
            pass
    return 0


# --- exportar -------------------------------------------------------------------------------

ARCHIVO_INFO = "plataforma.json"


def ip_red_local():
    """IP de esta computadora en la red local, sin mandar paquetes (un socket UDP «conectado» no transmite)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("192.0.2.1", 9))
            ip = s.getsockname()[0]
        finally:
            s.close()
        if ip and not ip.startswith("127.") and ip != "0.0.0.0":
            return ip
    except OSError:
        pass
    try:
        ip = socket.gethostbyname(socket.gethostname())
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass
    return None


def escribir_info_plataforma(salida: Path, host: str, puerto: int, instancia: str) -> None:
    from .canon import guardar_json_atomico
    guardar_json_atomico(Path(salida) / ARCHIVO_INFO, {"pid": os.getpid(), "host": host, "puerto": puerto,
                                                       "instancia": instancia})


def leer_info_plataforma(salida) -> dict:
    try:
        with open(Path(salida) / ARCHIVO_INFO, encoding="utf-8") as f:
            info = json.load(f)
        return info if isinstance(info, dict) else {}
    except (OSError, ValueError):
        return {}


def plataforma_viva(salida: Path, espera_s: float = 2.0) -> bool:
    """La plataforma de ESTA salida responde en /api/salud (misma instancia). Funciona igual en cualquier sistema."""
    import urllib.request
    try:
        with open(Path(salida) / ARCHIVO_INFO, encoding="utf-8") as f:
            info = json.load(f)
        host = info.get("host") or "127.0.0.1"
        if host in ("0.0.0.0", "", "::"):
            host = "127.0.0.1"
        abridor = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with abridor.open(f"http://{host}:{int(info['puerto'])}/api/salud", timeout=espera_s) as r:
            datos = json.loads(r.read().decode("utf-8"))
        return bool(datos.get("ok")) and datos.get("instancia") == info.get("instancia")
    except Exception:
        return False


def _contar_testigos(ruta) -> int:
    n = 0
    try:
        with open(ruta, encoding="utf-8") as f:
            for linea in f:
                if '"testigos_guardados"' in linea:
                    n += 1
    except OSError:
        pass
    return n


def _testigos_sin_plataforma(salida, ruta_aud, cliente, imprimir, escribir_testigos) -> None:
    from .auditoria import Auditoria
    from .simulador import Cliente, ErrorRed
    with open(salida / "estado.json", encoding="utf-8") as f:
        estado = json.load(f)
    try:
        cliente = cliente or Cliente(estado.get("simulador") or "", timeout=5)
        listas = {p["id"]: cliente.ordenes(p["id"]) for p in estado.get("proveedores") or []}
        minuto = cliente.estado()["minuto_actual"]
        aud = Auditoria(ruta_aud)
        try:
            escribir_testigos(salida, estado.get("simulador"), minuto, listas,
                              lambda tipo, datos: aud.agregar(tipo, "sistema", minuto, None, datos))
        finally:
            aud.cerrar()
        imprimir("La plataforma no está corriendo: este comando consultó y guardó los testigos de los proveedores.")
    except (ErrorRed, ValueError, KeyError, TypeError):
        imprimir("Sin conexión con el simulador: se usan los testigos guardados (si los hay).")


def _ultimo_n(ruta) -> int:
    """n de la última entrada testigos_guardados (0 si no hay)."""
    n = 0
    try:
        with open(ruta, encoding="utf-8") as f:
            for linea in f:
                if '"testigos_guardados"' in linea:
                    try:
                        n = int(json.loads(linea).get("n") or 0)
                    except (ValueError, TypeError, AttributeError):
                        pass
    except OSError:
        pass
    return n


def _cabeza_auditoria(ruta) -> Optional[dict]:
    """{n, hash} de la última línea completa de la auditoría (como la anota exportar en resumen.cabeza_auditoria)."""
    try:
        crudo = Path(ruta).read_bytes()
    except OSError:
        return None
    for linea in reversed(crudo[:crudo.rfind(b"\n") + 1].splitlines()):
        if linea.strip():
            try:
                e = json.loads(linea.decode("utf-8"))
                return {"n": e["n"], "hash": e["hash"]}
            except (ValueError, KeyError, TypeError, UnicodeDecodeError):
                return None
    return {"n": 0, "hash": None}


def paquete_del_cierre(salida) -> Optional[dict]:
    """El resumen de <salida>/entrega si es el paquete que la plataforma exportó y publicó al cerrar; si no, None."""
    entrega = Path(salida) / "entrega"
    if not (entrega / "MANIFIESTO.json").is_file():
        return None
    try:
        resumen = json.loads((entrega / "resumen.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(resumen, dict):
        return None
    if resumen.get("cerrado"):
        return resumen
    # Lo que la plataforma publicó (hitos.paquete.huella, la de /transparencia) es la prueba más firme.
    try:
        estado = json.loads((Path(salida) / "estado.json").read_text(encoding="utf-8"))
        publicada = ((estado.get("hitos") or {}).get("paquete") or {}).get("huella")
    except (OSError, ValueError, AttributeError):
        publicada = None
    from .exportar import huella_paquete
    return resumen if publicada and publicada == huella_paquete(entrega) else None


def exportar_paquete(salida, destino, espera_s: float = 10.0, cliente=None, imprimir=_imprimir) -> int:
    """Refresca los testigos y exporta. Si la plataforma responde, este comando NUNCA escribe la auditoría."""
    from .exportar import ErrorDestino, comprobar_destino, copiar_paquete, escribir_testigos, exportar, huella_paquete
    salida = Path(salida)
    if not (salida / "estado.json").exists():
        imprimir(f"No hay estado en {salida}.")
        return 1
    try:
        comprobar_destino(destino)  # antes de pedir testigos: si el destino no sirve, no se toca nada
    except ErrorDestino as err:
        imprimir(f"✗ {err}")
        return 1
    ruta_aud = salida / "auditoria.jsonl"
    cierre = paquete_del_cierre(salida)
    if cierre is not None:
        # C20 (f-integridad-3, f-operacion-1): con el partido cerrado, la huella que vale es la del paquete que la
        # plataforma exportó y publicó al cerrar (/transparencia, la sala). Se copia tal cual, con la plataforma viva o
        # apagada y cuantas veces sea: no se piden testigos nuevos ni se escribe la auditoría (la foto final de los
        # testigos ya la tomó el cierre).
        entrega = salida / "entrega"
        try:
            destino = copiar_paquete(entrega, destino)
        except (ErrorDestino, OSError) as err:
            imprimir(f"✗ No se pudo copiar el paquete del cierre ({entrega}): {err}")
            return 1
        imprimir(f"El partido ya cerró: se copió el paquete del cierre ({entrega}) a {destino}")
        cabeza = _cabeza_auditoria(ruta_aud)
        en_paquete = (cierre.get("cabeza_auditoria") or {}).get("n")
        if cabeza and isinstance(en_paquete, int) and cabeza["n"] > en_paquete:
            imprimir(f"  La auditoría tiene {cabeza['n'] - en_paquete} entrada(s) posteriores al cierre (sesiones, "
                     "consultas): no van en el paquete; el paquete que vale es el del cierre.")
        imprimir(f"Huella del paquete: {huella_paquete(destino)}")
        imprimir("Es la huella que publicó la plataforma al cerrar (/transparencia y la sala). Se compara con: "
                 "python3 -m marca verificar <carpeta> --huella <huella>")
        return 0
    if plataforma_viva(salida):
        antes = _contar_testigos(ruta_aud)
        entrega = salida / "entrega"
        h_antes = huella_paquete(entrega)  # existe si el partido ya cerró (la plataforma exportó sola)
        (salida / "pedir-testigos").touch()
        limite = time.monotonic() + espera_s
        while time.monotonic() < limite and _contar_testigos(ruta_aud) == antes:
            time.sleep(0.2)
        imprimir("Testigos refrescados por la plataforma." if _contar_testigos(ruta_aud) > antes
                 else "La plataforma no refrescó los testigos a tiempo: se usa lo último guardado.")
        # paquete-3 / c1-concurrencia-6: la plataforma anota testigos_guardados ANTES de guardar estado.json;
        # se espera a que el estado la refleje (aud_n), así estado y testigos son de la misma foto.
        n_aud = _ultimo_n(ruta_aud)
        while time.monotonic() < limite:
            try:
                if int(json.loads((salida / "estado.json").read_text(encoding="utf-8")).get("aud_n") or 0) >= n_aud:
                    break
            except (OSError, ValueError, TypeError, AttributeError):
                pass
            time.sleep(0.05)
        if h_antes is not None:
            # C20: con el partido cerrado la plataforma vuelve a exportar <salida>/entrega con los testigos nuevos y
            # publica su huella en /transparencia. Se entrega ESE paquete, copiado tal cual: misma huella.
            while time.monotonic() < limite and huella_paquete(entrega) == h_antes:
                time.sleep(0.2)
            try:
                destino = copiar_paquete(entrega, destino)
            except (ErrorDestino, OSError) as err:
                imprimir(f"✗ No se pudo copiar el paquete de la plataforma ({entrega}): {err}")
                return 1
            imprimir(f"Copiado el paquete que publicó la plataforma ({entrega}) a {destino}")
            imprimir(f"Huella del paquete: {huella_paquete(destino)}")
            imprimir("Es la misma huella que muestran /transparencia y la sala. Publicarla (README, video, chat con "
                     "la organización). Se compara con: python3 -m marca verificar <carpeta> --huella <huella>")
            return 0
    else:
        candado = CandadoSalida(salida)
        if not candado.tomar():
            # Hay una plataforma arrancando o trabada sobre esta salida: la auditoría es de ella.
            imprimir("Otra plataforma tiene tomada la carpeta y no responde todavía: no se escribe la auditoría; "
                     "se usan los testigos guardados.")
        else:
            try:
                _testigos_sin_plataforma(salida, ruta_aud, cliente, imprimir, escribir_testigos)
            finally:
                candado.soltar()
    try:
        destino = exportar(salida, destino)
    except ErrorDestino as err:
        imprimir(f"✗ {err}")
        return 1
    imprimir(f"Exportado a {destino}")
    imprimir(f"Huella del paquete: {huella_paquete(destino)}")
    imprimir("Publicar esta huella (README, video, chat con la organización): es lo que ancla la cola de la "
             "auditoría posterior al último sello. Se compara con: python3 -m marca verificar <carpeta> --huella <huella>")
    return 0


def cmd_exportar(args) -> int:
    return exportar_paquete(args.salida, args.destino)


def cmd_verificar(args) -> int:
    from .verificar import main_verificar
    return main_verificar(args.carpeta, args.registro_simulador, args.config, args.huella)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python3 -m marca", description="Marca Personal — órdenes de bloqueo en vivo")
    sub = p.add_subparsers(dest="comando", required=True)

    s = sub.add_parser("servir", help="corre la plataforma contra el simulador")
    s.add_argument("--simulador", required=True)
    s.add_argument("--puerto", type=int, default=8700)
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--salida", default="salida")
    s.add_argument("--nueva", action="store_true",
                   help="empezar de cero: aparta la carpeta a <salida>.anterior-<fecha>; se niega si el simulador "
                        "ya tiene órdenes")
    s.add_argument("--descartar-anteriores", action="store_true",
                   help="con --nueva: arrancar aunque el simulador ya tenga órdenes (quedan fuera de la auditoría)")
    s.add_argument("--config", default=str(CONFIG))
    s.add_argument("--sin-dinamica", action="store_true",
                   help="deshabilita el seguimiento (ampliaciones automáticas): cada servidor nuevo espera la firma "
                        "del juez")
    s.add_argument("--tick", type=float, default=0.25)
    s.set_defaults(f=cmd_servir)

    c = sub.add_parser("chequear", help="revisión previa al partido (no manda órdenes)")
    c.add_argument("--simulador", required=True)
    c.add_argument("--config", default=str(CONFIG))
    c.add_argument("--salida", default="salida")
    c.add_argument("--host", default="127.0.0.1",
                   help="el --host con el que se va a servir: avisa si queda abierta a la red con contraseñas "
                        "publicadas")
    c.set_defaults(f=cmd_chequear)

    k = sub.add_parser("claves", help="arma el archivo de usuarios del partido final con contraseñas nuevas")
    k.add_argument("--salida", default=str(CONFIG_FINAL))
    k.add_argument("--reemplazar", action="store_true", help="pisa el archivo si ya existe")
    k.set_defaults(f=cmd_claves)

    e = sub.add_parser("exportar", help="exporta expedientes, auditoría, testigos y acta")
    e.add_argument("--salida", default="salida")
    e.add_argument("--destino", default="entrega")
    e.set_defaults(f=cmd_exportar)

    v = sub.add_parser("verificar", help="verifica una exportación sin conexión")
    v.add_argument("carpeta")
    v.add_argument("--registro-simulador", default=None)
    v.add_argument("--config", default=None)
    v.add_argument("--huella", default=None, help="huella del paquete publicada al exportar: se compara")
    v.set_defaults(f=cmd_verificar)

    salida_utf8()
    args = p.parse_args(argv)
    if getattr(args, "descartar_anteriores", False) and not args.nueva:
        p.error("--descartar-anteriores va solo junto con --nueva")
    sim = getattr(args, "simulador", None)
    if sim is not None and not sim.strip().lower().startswith(("http://", "https://")):
        # g-operacion-1: sin esquema, la conexión fallaba recién a los 20 s y con un error críptico.
        p.error(f"--simulador {sim}: la dirección tiene que empezar con http:// o https:// "
                f"(por ejemplo http://192.168.0.10:8791)")
    return int(args.f(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
