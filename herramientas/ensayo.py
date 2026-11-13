#!/usr/bin/env python3
"""Ensayo automático: corre un partido entero contra el simulador oficial y lo evalúa.

1. Arranca el simulador oficial (python3 -I) con el registro en <salida>/registro.jsonl.
2. Arranca `python3 -m marca servir --nueva` contra ese simulador.
3. Corre un juez automático por cada juez de la configuración (entra por la API web).
4. Con --reiniciar-en <min>, mata la plataforma en ese minuto y la vuelve a arrancar sin --nueva.
5. Espera hasta fin_min + 5,5 (el verificador oficial evalúa los bloqueos activos después del partido en el
   minuto fin_min + 5 solo si el registro llega hasta ahí), para todo, corre el verificador oficial y
   `python3 -m marca verificar`. Si la plataforma terminó antes, igual deja correr el simulador hasta ese minuto.
6. Imprime el informe oficial, un resumen y el veredicto contra la sección 15. Sale con 0 solo si se cumple.

Con --personas no corre ningún juez automático: firman personas desde /juez (con --host 0.0.0.0 y
--config config/jueces_final.json, desde el celular). Mismo veredicto, y al final la fila «Personas» del README.

Con --latencia-ms / --jitter-ms / --falla-cada la plataforma no habla directo con el simulador: pasa por
herramientas/proxy_latencia.py (en --puerto-proxy), que demora cada pedido y, si se pide, responde 502 cada N.
El ensayo y el verificador oficial siguen leyendo el simulador directo.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import List, Optional

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "herramientas"))
from juez_automatico import AVISO, JuezAutomatico  # noqa: E402

PY = sys.executable or "python3"
# Los hijos escriben en UTF-8 aunque la consola sea cp1252 (Windows): sin esto, un «✓» los puede tumbar.
ENV_HIJOS = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
SENAL_FUERTE = getattr(signal, "SIGKILL", signal.SIGTERM)  # Windows no tiene SIGKILL


def ajustar_juez(args) -> None:
    """C25: --demora-juez-s S (segundos REALES por decisión) = --juez-serial --demora-juez S·acelerar/60."""
    if getattr(args, "demora_juez_s", None) is not None:
        args.juez_serial = True
        args.demora_juez = float(args.demora_juez_s) * float(args.acelerar) / 60.0


def opciones_juez(serial: bool, clase=None, avisar=print) -> dict:
    """{"serial": True} solo si se pidió y el juez automático lo acepta (lo agrega E en juez_automatico.py)."""
    if not serial:
        return {}
    import inspect
    try:
        acepta = "serial" in inspect.signature(clase or JuezAutomatico).parameters
    except (TypeError, ValueError):
        acepta = False
    if not acepta:
        avisar("[ensayo] ! este juez automático todavía no tiene modo serial: corre como siempre (en paralelo)")
        return {}
    return {"serial": True}


def abrir_con_reintento(abrir, puerto: int, tope_s: float = 40.0, dormir=time.sleep, ahora=time.monotonic,
                        avisar=print, cada_s: float = 2.0):
    """Abre un servidor local reintentando mientras el puerto siga ocupado (un ensayo anterior lo deja en espera
    unos 30 s). Después de tope_s, SystemExit con un mensaje claro en vez de un traceback."""
    import errno
    limite = ahora() + tope_s
    avisado = False
    while True:
        try:
            return abrir()
        except OSError as err:
            ocupado = err.errno in (errno.EADDRINUSE, getattr(errno, "WSAEADDRINUSE", -1), 10048)
            if not ocupado:
                raise
            if ahora() >= limite:
                raise SystemExit(f"[ensayo] el puerto {puerto} sigue ocupado después de {tope_s:g} s: usar otro "
                                 "(--puerto-proxy) o esperar un poco más.")
            if not avisado:
                avisar(f"[ensayo] el puerto {puerto} sigue ocupado; espero (hasta {tope_s:g} s)…")
                avisado = True
            dormir(cada_s)


def salida_utf8() -> None:
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def correr(cmd: list) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(RAIZ), capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env=ENV_HIJOS)


def pedir_json(url: str, timeout: float = 3.0):
    abridor = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with abridor.open(url, timeout=timeout) as r:
        return json.loads(r.read())


def esperar(url: str, segundos: float) -> dict:
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        try:
            return pedir_json(url)
        except Exception:
            time.sleep(0.2)
    raise SystemExit(f"No respondió {url}")


def esperar_minuto(leer, objetivo: float, tope_s: float, dormir=time.sleep, ahora=time.monotonic,
                   cada_s: float = 0.5) -> Optional[float]:
    """Espera a que el simulador llegue al minuto `objetivo` (leer() devuelve su minuto actual). Devuelve el minuto
    alcanzado, o None si no llegó en `tope_s` segundos reales (o el simulador no responde)."""
    limite = ahora() + tope_s
    while True:
        try:
            m = float(leer())
        except Exception:
            m = None
        if m is not None and m >= objetivo:
            return m
        if ahora() >= limite:
            return None
        dormir(cada_s)


def comando_plataforma(args, salida_marca: Path, nueva: bool) -> list:
    cmd = [PY, "-m", "marca", "servir", "--simulador", f"http://127.0.0.1:{args.puerto_plataforma_sim}",
           "--host", getattr(args, "host", "127.0.0.1"), "--puerto", str(args.puerto), "--salida", str(salida_marca),
           "--config", str(args.config), "--tick", str(args.tick)]
    if nueva:
        cmd.append("--nueva")
    if args.sin_dinamica:
        cmd.append("--sin-dinamica")
    return cmd


def arrancar_plataforma(args, salida_marca: Path, nueva: bool, log) -> subprocess.Popen:
    return subprocess.Popen(comando_plataforma(args, salida_marca, nueva), cwd=str(RAIZ), stdout=log,
                            stderr=subprocess.STDOUT, env=ENV_HIJOS)


def jueces_automaticos(cfg: dict, personas: bool) -> list:
    """Los usuarios que firma un juez automático: ninguno en un ensayo con personas; si no, cada juez."""
    return [] if personas else [u for u in cfg["usuarios"] if u["rol"] == "juez"]


def fila_personas(acelerar: float, oficial: dict, promedios: dict, seguimiento: bool) -> str:
    """La fila «Personas» de la tabla del README, con los números del verificador oficial y del acta."""
    def coma(x, dec):
        return "—" if x is None else f"{x:.{dec}f}".replace(".", ",")

    def tiempos(tipo):
        pr = promedios.get(tipo) or {}
        return " → ".join(coma(pr.get(k), 2) for k in ("hasta_firma_min", "hasta_primer_proveedor_min",
                                                        "hasta_todos_min"))
    r = oficial.get("resumen") or {}
    res = r.get("visibilidad_residual_promedio_pct")
    medido = f"{r.get('fases_piratas_bloqueadas') or '—'} · {coma(res, 1) + ' %' if res is not None else '—'}"
    ritmo = f"×{acelerar:g}"
    if seguimiento:
        return (f"| Personas del equipo, {ritmo}, seguimiento autorizado | — | — | {medido} | {tiempos('en_persona')} "
                f"| {tiempos('ampliacion')} |")
    return f"| Personas del equipo, {ritmo}, casilla destildada | {medido} | {tiempos('en_persona')} | — | — | — |"


def parar(proc: Optional[subprocess.Popen], fuerte: bool = False) -> None:
    if proc is None or proc.poll() is not None:
        return
    if fuerte:
        proc.kill()
    else:
        proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def veredicto(args, oficial: dict, marca_ok: bool, estado: dict, oraculo: Optional[dict] = None,
              cambios_turno: Optional[List[float]] = None) -> List[tuple]:
    """robustez-4: no dice NO CUMPLE por cosas imposibles.

    oraculo: salida de alcanzable.evaluar; solo excusa lo que da por imposible o de suerte, nunca agrega exigencias
    (un DEFECTO del oráculo no se excusa). Una fase de duración cero no cuenta. cambios_turno: minutos en que empieza
    cada turno; sin un cambio posterior a inicio_min no se exige traspaso."""
    r = oficial["resumen"]
    fases = oficial["fases"]
    criterios = []

    def c(ok, texto):
        criterios.append((bool(ok), texto))

    c(r["ordenes_rechazadas"] == 0, f"0 órdenes rechazadas ({r['ordenes_rechazadas']})")
    c(r["ordenes_firmadas_fuera_de_turno"] == 0, f"0 firmadas fuera de turno ({r['ordenes_firmadas_fuera_de_turno']})")
    c(r["bloqueos_falsos_positivos"] == 0, f"0 falsos positivos ({r['bloqueos_falsos_positivos']})")
    post = r["bloqueos_ip_activos_post_partido"]
    c(post == 0, f"0 bloqueos por IP activos después del partido ({post})" if post is not None else
      f"bloqueos por IP activos después del partido: NO EVALUABLE (el registro oficial llega al minuto "
      f"{oficial.get('log_hasta_min')} y el corte es el {oficial.get('corte_post_partido_min')})")
    c(marca_ok, "verificación de integridad en verde, cruzada con el registro oficial")
    evaluables = [f for f in fases if f["hasta_min"] > args.inicio_min and f["hasta_min"] > f["desde_min"]]
    if not args.forzar_ip:
        c(r["bloqueos_con_dano_colateral"] == 0, f"0 órdenes con daño colateral ({r['bloqueos_con_dano_colateral']})")
        c(r["reclamos"] == 0, f"0 reclamos ({r['reclamos']})")
    excusadas = {(fl.get("stream"), fl.get("fase")) for fl in (oraculo or {}).get("fases", [])
                 if fl.get("evaluable") and fl.get("estado") == "lo alcanzable"}

    def nota(n):
        return f"; {n} imposible(s) o de suerte según alcanzable.py" if n else ""
    bloqueadas = [f for f in evaluables if f["primer_bloqueo_min"] is not None]
    sin_b = [f for f in evaluables if f["primer_bloqueo_min"] is None and (f.get("stream"), f.get("fase")) in excusadas]
    c(len(bloqueadas) + len(sin_b) == len(evaluables),
      f"{len(bloqueadas)} de {len(evaluables)} fases evaluables bloqueadas{nota(len(sin_b))}")
    llenas = [f for f in evaluables if f["clientes_cubiertos_pct"] == 100.0]
    sin_l = [f for f in evaluables if f["clientes_cubiertos_pct"] != 100.0
             and (f.get("stream"), f.get("fase")) in excusadas]
    c(len(llenas) + len(sin_l) == len(evaluables),
      f"100 % de clientes cubiertos en {len(llenas)} de {len(evaluables)} fases{nota(len(sin_l))}")
    traspasos = estado.get("traspasos") or []
    hay_cambio = cambios_turno is None or any(float(t) > args.inicio_min for t in cambios_turno)
    if args.inicio_min > 0 and not hay_cambio:
        c(True, f"sin cambio de turno después del min {args.inicio_min:g}: no se exige traspaso")
    if args.inicio_min > 0 and hay_cambio:
        c(traspasos and all(t.get("ratificado") for t in traspasos),
          f"traspaso creado y ratificado ({len(traspasos)} traspaso(s))")
        if not args.sin_dinamica and traspasos:
            rat_min = min((t["ratificado"]["min"] for t in traspasos if t.get("ratificado")), default=None)
            mudanzas = [(exp["id"], u) for exp in estado["expedientes"] for u in exp["ubicaciones"]
                        if u.get("continuidad") and u["continuidad"]["criterio"] == "misma_marca"
                        and rat_min is not None and (u["primera_deteccion_min"] or 0) > rat_min]
            auto = [u for _, u in mudanzas if (u.get("decision") or {}).get("tipo") == "ampliacion_dinamica"]
            c(mudanzas and len(auto) == len(mudanzas),
              f"mudanzas posteriores a la ratificación ampliadas solas: {len(auto)} de {len(mudanzas)}")
    if args.forzar_ip:
        c(r["reclamos"] > 0, f"llegan reclamos ({r['reclamos']})")
        c(r["reclamos_resueltos_por_levantamiento"] == r["reclamos"],
          f"todos resueltos por levantamiento ({r['reclamos_resueltos_por_levantamiento']} de {r['reclamos']})")
        nuestros = list(estado.get("reclamos", {}).values())
        c(all(x["estado"] != "pendiente" for x in nuestros), f"ningún reclamo pendiente en la plataforma "
                                                               f"({sum(1 for x in nuestros if x['estado'] == 'pendiente')})")
        fase = [f for f in fases if f["host"] == args.forzar_ip]
        dominio_vivo = [o for o in estado["ordenes"].values() if o["tipo"] == "dominio" and o["objetivo"] == args.forzar_ip
                        and o.get("aplicada_min") is not None and o["estado"] in ("aplicada", "vencida")]
        provs_dom = [p["id"] for p in estado["proveedores"] if "dominio" in p.get("capacidades", [])]
        c(fase and {o["proveedor"] for o in dominio_vivo} >= set(provs_dom),
          f"el stream sigue bloqueado por dominio en {len({o['proveedor'] for o in dominio_vivo})} de "
          f"{len(provs_dom)} proveedores hasta el vencimiento")
    amp = [o for o in estado["ordenes"].values() if str(o.get("orden_id", "")).startswith("amp-")]
    if args.sin_dinamica or args.alcance == "ubicacion":
        c(not amp, f"ninguna orden amp- sin seguimiento: todo firmado en persona ({len(amp)} amp-)")
    if args.reiniciar_en is not None:
        rec = [o for o in estado["ordenes"].values() if o.get("recibida_min") is not None]
        claves = {}
        dup = 0
        for o in sorted(rec, key=lambda x: x["recibida_min"]):
            k = (o["proveedor"], o["tipo"], o["objetivo"])
            prev = claves.get(k)
            if prev and prev["estado"] not in ("fallida",) and not (prev.get("finalizada_min") is not None
                                                                      and prev["finalizada_min"] <= o["recibida_min"]):
                dup += 1
            claves[k] = o
        c(dup == 0, f"sin órdenes duplicadas ({dup})")
    return criterios


def main() -> int:
    p = argparse.ArgumentParser(description="Ensayo automático de Marca Personal contra el simulador oficial")
    p.add_argument("--repo-desafio", required=True)
    p.add_argument("--acelerar", type=float, default=30)
    p.add_argument("--demora-juez", type=float, default=0.3,
                   help="minutos DE PARTIDO (no segundos reales) que el juez automático espera por decisión")
    p.add_argument("--juez-serial", action="store_true",
                   help="el juez automático atiende de a un pedido y también demora la orden marco (como una persona)")
    p.add_argument("--demora-juez-s", type=float, default=None,
                   help="segundos REALES por decisión: equivale a --juez-serial --demora-juez S·acelerar/60")
    p.add_argument("--alcance", choices=("filtracion", "ubicacion"), default="filtracion")
    p.add_argument("--sin-dinamica", action="store_true")
    p.add_argument("--inicio-min", type=float, default=0.0)
    p.add_argument("--forzar-ip", default=None)
    p.add_argument("--reiniciar-en", type=float, default=None)
    p.add_argument("--puerto-simulador", type=int, default=8791)
    p.add_argument("--puerto", type=int, default=8792)
    p.add_argument("--personas", action="store_true",
                   help="ensayo con personas: no corre ningún juez automático; firman los jueces desde /juez")
    p.add_argument("--host", default="127.0.0.1",
                   help="0.0.0.0 para entrar desde los celulares (necesita --config config/jueces_final.json)")
    p.add_argument("--salida", default="salida-ensayo")
    p.add_argument("--escenario", default=None)
    p.add_argument("--verdad", default=None)
    p.add_argument("--config", default=str(RAIZ / "config" / "jueces_demo.json"))
    p.add_argument("--tick", type=float, default=0.25)
    p.add_argument("--latencia-ms", type=float, default=0.0,
                   help="demora total de ida y vuelta de cada pedido de la plataforma al simulador")
    p.add_argument("--jitter-ms", type=float, default=0.0, help="variación al azar de ± J ms por pedido")
    p.add_argument("--falla-cada", type=int, default=0, help="el proxy responde 502 a uno de cada N pedidos")
    p.add_argument("--semilla", type=int, default=1, help="semilla del jitter (repetible)")
    p.add_argument("--puerto-proxy", type=int, default=None, help="puerto del proxy (por defecto simulador + 2)")
    args = p.parse_args()
    salida_utf8()
    ajustar_juez(args)
    con_proxy = bool(args.latencia_ms or args.jitter_ms or args.falla_cada)
    args.puerto_proxy = args.puerto_proxy or args.puerto_simulador + 2
    args.puerto_plataforma_sim = args.puerto_proxy if con_proxy else args.puerto_simulador

    repo = Path(args.repo_desafio).resolve()
    escenario = Path(args.escenario).resolve() if args.escenario else repo / "datos" / "escenario_practica.json"
    verdad = Path(args.verdad).resolve() if args.verdad else repo / "evaluacion" / "verdad_practica.json"
    salida = Path(args.salida).resolve()
    salida.mkdir(parents=True, exist_ok=True)
    for viejo in ("registro.jsonl", "plataforma.log", "simulador.log", "proxy.jsonl"):
        try:
            (salida / viejo).unlink()
        except OSError:
            pass
    salida_marca = salida / "marca"
    registro = salida / "registro.jsonl"
    print("ENSAYO CON PERSONAS: no corre ningún juez automático; firman los jueces desde /juez." if args.personas
          else AVISO, flush=True)

    sim_log = open(salida / "simulador.log", "w", encoding="utf-8")
    plat_log = open(salida / "plataforma.log", "a", encoding="utf-8")
    sim = subprocess.Popen([PY, "-I", str(repo / "simulador" / "servidor.py"), "--escenario", str(escenario),
                            "--datos", str(repo / "datos"), "--acelerar", str(args.acelerar),
                            "--inicio-min", str(args.inicio_min), "--puerto", str(args.puerto_simulador),
                            "--log", str(registro)], cwd=str(RAIZ), stdout=sim_log, stderr=subprocess.STDOUT,
                           env=ENV_HIJOS)
    plataforma = None
    proxy = None
    jueces: List[JuezAutomatico] = []
    try:
        est = esperar(f"http://127.0.0.1:{args.puerto_simulador}/estado", 15)
        fin = float(est["fin_min"])
        if con_proxy:
            from proxy_latencia import arrancar as arrancar_proxy
            proxy = abrir_con_reintento(
                lambda: arrancar_proxy(args.puerto_proxy, f"http://127.0.0.1:{args.puerto_simulador}", args.latencia_ms,
                                       args.jitter_ms, args.falla_cada, args.semilla, str(salida / "proxy.jsonl")),
                args.puerto_proxy, avisar=lambda t: print(t, flush=True))
            print(f"[ensayo] plataforma → proxy 127.0.0.1:{args.puerto_proxy} ({args.latencia_ms:g} ms ± "
                  f"{args.jitter_ms:g} ms" + (f", 502 cada {args.falla_cada}" if args.falla_cada else "")
                  + ") → simulador", flush=True)
        plataforma = arrancar_plataforma(args, salida_marca, True, plat_log)
        base = f"http://127.0.0.1:{args.puerto}"
        try:
            esperar(base + "/api/salud", 60)
        except SystemExit:
            plat_log.flush()
            print("[ensayo] la plataforma no arrancó. Últimas líneas de plataforma.log:", flush=True)
            print("\n".join((salida / "plataforma.log").read_text(encoding="utf-8").splitlines()[-8:]), flush=True)
            raise
        with open(args.config, encoding="utf-8") as f:
            cfg = json.load(f)
        if args.personas:
            print(f"[ensayo] Jueces: entrar a /juez. Sala: {base}/sala. Registro público: {base}/transparencia",
                  flush=True)
            with open(salida / "plataforma.log", encoding="utf-8") as f:
                for linea in f:
                    if "celular" in linea or "red local" in linea:
                        print("[ensayo]" + linea.rstrip(), flush=True)
        extra_juez = opciones_juez(args.juez_serial, avisar=lambda t: print(t, flush=True))
        for u in jueces_automaticos(cfg, args.personas):
            j = JuezAutomatico(base, u["usuario"], u["clave_demo"], args.demora_juez, args.alcance, args.forzar_ip,
                               registro=lambda t: print(t, flush=True), **extra_juez)
            j.iniciar()
            jueces.append(j)
        reiniciado = False
        t_inicio = time.monotonic()
        while True:
            try:
                m = float(pedir_json(f"http://127.0.0.1:{args.puerto_simulador}/estado")["minuto_actual"])
            except Exception:
                m = None
            if m is not None and args.reiniciar_en is not None and not reiniciado and m >= args.reiniciar_en:
                print(f"[ensayo] min {m:.2f}: se mata la plataforma (SIGKILL) y se reanuda sin --nueva", flush=True)
                parar(plataforma, fuerte=True)
                time.sleep(1.0)
                plataforma = arrancar_plataforma(args, salida_marca, False, plat_log)
                esperar(base + "/api/salud", 60)
                reiniciado = True
            if m is not None and m >= fin + 5.5:
                try:
                    salud = pedir_json(base + "/api/salud")
                except Exception:
                    salud = {}
                if salud.get("exportado") or m >= fin + 8:
                    break
            if plataforma.poll() is not None:
                print("[ensayo] la plataforma terminó sola: ver plataforma.log", flush=True)
                break
            if time.monotonic() - t_inicio > 4 * 3600:
                break
            time.sleep(0.5)
        # El verificador oficial evalúa «bloqueos activos después del partido» en el minuto fin + 5 solo si el
        # simulador llegó hasta ahí: nunca se lo corta antes (aunque la plataforma haya terminado sola).
        cierre = fin + 5.5
        if m is None or m < cierre:
            print(f"[ensayo] se deja correr el simulador hasta el minuto {cierre:g} (el verificador oficial evalúa "
                  f"los bloqueos activos en el minuto {fin + 5:g})", flush=True)
            m = esperar_minuto(lambda: pedir_json(f"http://127.0.0.1:{args.puerto_simulador}/estado")["minuto_actual"],
                               cierre, max(30.0, (cierre - (m or 0.0)) * 60.0 / max(args.acelerar, 0.01) + 30.0))
        print(f"[ensayo] el simulador se corta en el minuto {m if m is not None else 'desconocido'}", flush=True)
    finally:
        for j in jueces:
            j.detener()
        parar(plataforma)
        if proxy is not None:
            proxy.shutdown()
            proxy.server_close()
        parar(sim)
        sim_log.close()
        plat_log.close()

    comun = ["--log", str(registro), "--escenario", str(escenario), "--verdad", str(verdad),
             "--datos", str(repo / "datos")]
    texto = correr([PY, "-I", str(repo / "evaluacion" / "verificar.py")] + comun).stdout
    crudo = correr([PY, "-I", str(repo / "evaluacion" / "verificar.py")] + comun + ["--json"]).stdout
    oficial = json.loads(crudo)
    (salida / "verificador_oficial.json").write_text(crudo, encoding="utf-8")
    print("\n=================== Verificador oficial ===================")
    print(texto)
    entrega = salida_marca / "entrega"
    v = correr([PY, "-m", "marca", "verificar", str(entrega), "--registro-simulador", str(registro),
                "--config", str(args.config)])
    (salida / "verificacion_integridad.txt").write_text(v.stdout + v.stderr, encoding="utf-8")
    print("=================== Verificación de integridad ===================")
    lineas = v.stdout.strip().splitlines()
    malas = [x for x in lineas if x.startswith("✗")]
    print("\n".join(malas[:20] + lineas[-1:]) if malas else "\n".join(
        [x for x in lineas if not x.startswith("✓ EXP")][:40]))
    with open(salida_marca / "estado.json", encoding="utf-8") as f:
        estado = json.load(f)

    print("\n=================== Resumen ===================")
    r = oficial["resumen"]
    print(f"  Registro oficial hasta el minuto {oficial.get('log_hasta_min')}; bloqueos después del partido evaluados en "
          f"el minuto {oficial.get('corte_post_partido_min')}: "
          + ("sí" if oficial.get("post_partido") is not None else "NO (el simulador se cortó antes)"))
    for k, val in r.items():
        print(f"  {k}: {val}")
    print("  Tiempo al primer bloqueo por fase:")
    for f in oficial["fases"]:
        print(f"    {f['stream']} fase {f['fase']} ({f['host']}): "
              f"{f['primer_bloqueo_min'] if f['primer_bloqueo_min'] is not None else 'nunca'} min · "
              f"cobertura {f['clientes_cubiertos_pct']} % · residual {f['visibilidad_residual_pct']} %")
    print(f"  Traspasos: {len(estado.get('traspasos') or [])}, ratificados: "
          f"{sum(1 for t in estado.get('traspasos') or [] if t.get('ratificado'))}")
    ords = list(estado.get("ordenes", {}).values())
    amp = sum(1 for o in ords if str(o.get("orden_id", "")).startswith("amp-"))
    print(f"  Órdenes: {len(ords) - amp} ord- (firmadas en persona) y {amp} amp- (ampliaciones automáticas)")
    try:
        tiempos = json.loads((entrega / "resumen.json").read_text(encoding="utf-8")).get("tiempos") or {}
    except (OSError, ValueError):
        tiempos = {}
    for tipo, titulo in (("en_persona", "firmadas en persona"), ("ampliacion", "ampliaciones automáticas")):
        pr = (tiempos.get("promedios") or {}).get(tipo) or {}

        def mm(x):
            return "—" if x is None else f"{x:.2f}"
        print(f"  Tiempos {titulo} ({pr.get('ubicaciones', 0)}): detección→firma {mm(pr.get('hasta_firma_min'))} min · "
              f"→primer proveedor {mm(pr.get('hasta_primer_proveedor_min'))} min · "
              f"→todos los proveedores {mm(pr.get('hasta_todos_min'))} min"
              + (f" ({pr['sin_todos']} sin llegar a todos)" if pr.get("sin_todos") else ""))
    acciones = [a for j in jueces for a in j.acciones]
    errores = [a for a in acciones if a["http"] != 200 and not a.get("esperado")]
    if args.personas:
        seguimiento = any(m.get("seguimiento") for m in estado.get("marcos") or [])
        print(f"  Firmaron: {tiempos.get('firmaron') or 'personas'} (acta). Seguimiento en la orden marco: "
              f"{'sí' if seguimiento else 'no'}.")
        print("  Fila para el README (tabla del juez simulado, plantilla comentada «Personas»; decir quién firmó):")
        print("  " + fila_personas(args.acelerar, oficial, tiempos.get("promedios") or {}, seguimiento))
    else:
        print(f"  Acciones de los jueces automáticos: {len(acciones)} ({len(errores)} con error)")
    if proxy is not None:
        pedidos = proxy.pedidos
        demoras = [x["demora_ms"] for x in pedidos]
        print(f"  Proxy: {len(pedidos)} pedidos, demora media {sum(demoras) / max(1, len(demoras)):.0f} ms "
              f"(mín {min(demoras, default=0):.0f}, máx {max(demoras, default=0):.0f}), "
              f"{sum(1 for x in pedidos if x['falla_inyectada'])} fallas inyectadas, "
              f"{sum(1 for x in pedidos if x['estado'] >= 500)} respuestas 5xx · detalle en proxy.jsonl")
    for a in errores[:10]:
        print(f"    {a['accion']} → {a['resultado']}")

    import alcanzable
    oraculo = None
    try:
        oraculo = alcanzable.evaluar(alcanzable.cargar_json(verdad, "la verdad"),
                                     alcanzable.cargar_json(repo / "datos" / "proveedores.json", "proveedores"),
                                     oficial, alcanzable.cargar_registro(registro))
    except alcanzable.ErrorDeDatos as e:
        print(f"  (alcanzable.py no pudo evaluar: {e}; el veredicto exige todas las fases)")
    try:  # de juzgados.json solo se leen los turnos, ninguna clave
        with open(repo / "datos" / "juzgados.json", encoding="utf-8") as f:
            cambios_turno = [float(t["desde_min"]) for t in json.load(f).get("turnos", [])]
    except (OSError, ValueError, KeyError, TypeError):
        cambios_turno = None
    criterios = veredicto(args, oficial, v.returncode == 0, estado, oraculo, cambios_turno)
    print("\n=================== Veredicto (sección 15) ===================")
    for ok, t in criterios:
        print(("  ✓ " if ok else "  ✗ ") + t)
    todo = all(ok for ok, _ in criterios)
    print("\nRESULTADO: " + ("CUMPLE" if todo else "NO CUMPLE"))
    return 0 if todo else 1


if __name__ == "__main__":
    sys.exit(main())
