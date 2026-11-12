"""Motor de la plataforma: estado, ciclo, decisiones, reclamos, traspaso y fin del partido.

Regla de oro: la red va FUERA del candado del estado. Se consulta, y después se aplica con el
candado tomado.
"""
from __future__ import annotations

import datetime
import json
import secrets
import shutil
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import VERSION, dominios, evidencia, kit as kit_mod, marco as marco_mod, reloj as reloj_mod, sello, turnos
from .auditoria import Auditoria, verificar_cadena
from .canon import (canonico, guardar_json_atomico, hora_de_partido, huella, min_txt, nombre_captura, r3, sha256_hex,
                    utc_ahora)
from .reloj import NUNCA, Reloj, instante
from .simulador import Cliente, ErrorRed
from .usuarios import Usuarios

ACTIVAS = ("por_enviar", "recibida", "aplicada", "espera_ratificacion")
VIGENTES = ("recibida", "aplicada")
FINALES = ("vencida", "levantada", "fallida", "rechazada", "perdida")
AVISO_INTENTOS = 6             # C13: al 6.º intento fallido, UNA alerta a la sala (y se sigue reintentando)
ESPACIO_REINTENTO_MIN = 1.0    # C13: desde el 7.º intento, un envío por (proveedor, tipo, objetivo) por minuto
ESPERA_TRAS_ERROR_S = 3.0
INTERVALO_RECLAMOS_S = 1.0     # /reclamos: una vez por segundo real
INTERVALO_APLICADAS_S = 2.0    # proveedores que solo tienen órdenes ya aplicadas
ARCHIVO_PEDIR_TESTIGOS = "pedir-testigos"
GRACIA_PERDIDA_S = 2.0         # una orden recién confirmada puede no figurar todavía en la lista del proveedor
CIERRE_SIN_CONEXION_S = 10.0   # en fin+5: si los GET fallan más que esto, se cierra con lo último que se obtuvo
ESPERA_FOTO_S = 12.0           # foto de testigos: espera máxima a que terminen los POST en camino
DESDE_INICIAL = -1e9           # /detecciones sirve desde < minuto: así entran también las de minuto negativo
CAMPOS_MONOTONICOS = ("t_error", "t_post", "t_confirmada")  # no valen entre procesos: se borran al reanudar
PRESENCIA_S = 90.0             # «con la plataforma abierta»: actividad del juez en los últimos 90 s reales
TEXTO_SIN_MARCO = "Para seguir a la filtración, firme antes la orden marco con el seguimiento autorizado."
MOTIVO_RECHAZO_MIN = 10


TEXTO_FIRMA_TARDE = ("Faltan segundos para el final del partido: la firma queda registrada, pero la orden ya no llega a "
                     "los proveedores y no bloquea.")  # Ola C (f-desconocido-1, texto del verificador)


def _cant(n: int, singular: str, plural: str) -> str:
    """Ola C (NV3): «1 orden», «2 órdenes»: singular y plural de verdad, nunca «orden(es)»."""
    return f"{n} {singular if n == 1 else plural}"


def _min_txt(minuto: Optional[float]) -> str:
    """El único redondeo de minutos para leer (canon.min_txt, ronda 3 C8)."""
    return min_txt(minuto)


def _pedidos(n: int) -> str:
    return f"{n} pedido" if n == 1 else f"{n} pedidos"


class ErrorAccion(Exception):
    """Error de una acción pedida por la API: lleva código y texto para mostrar."""

    def __init__(self, codigo: str, texto: str) -> None:
        super().__init__(texto)
        self.codigo = codigo
        self.texto = texto


def _estado_inicial() -> dict:
    return {
        "formato": 1, "partido": None, "partido_huella": None, "proveedores": [], "juzgados": None,
        "turnos": [], "jueces": {}, "desde": DESDE_INICIAL, "detecciones_vistas": [], "sha_vistos": {},
        "expedientes": [], "num_exp": 0, "ordenes": {}, "reclamos": {}, "traspasos": [], "avisos": [],
        "num_aviso": 0, "descartes": {}, "de_turno": None, "ratificados": [], "vetados": [],
        "hitos": {}, "minuto": None, "simulador": None, "dns": {"ip": {}, "dominio": {}},
        "marcos": [], "cortes_avisados": [],
    }


class Motor:
    def __init__(self, simulador_url: str, salida, usuarios: Usuarios, dinamica: bool = True,
                 tick: float = 0.25, cliente: Optional[Cliente] = None, registro=None) -> None:
        self.simulador_url = simulador_url.rstrip("/")
        self.cliente = cliente or Cliente(self.simulador_url)
        self.salida = Path(salida)
        self.usuarios = usuarios
        self.dinamica_habilitada = dinamica
        self.tick = tick
        self.candado = threading.RLock()
        self.cond = threading.Condition(self.candado)
        self.reloj = Reloj()
        self.auditoria: Optional[Auditoria] = None
        self.e = _estado_inicial()
        self.v = 1
        self.conexion = "sin_conexion"
        self._sucio = False
        self._parar = threading.Event()
        self._hilos: List[threading.Thread] = []
        self._t_estado = NUNCA
        self._t_juzgados = NUNCA
        self._t_reclamos = NUNCA
        self._t_seg: Dict[str, float] = {}
        self.intervalo_reclamos_s = INTERVALO_RECLAMOS_S
        self.intervalo_aplicadas_s = INTERVALO_APLICADAS_S
        self.instancia = secrets.token_hex(8)
        self._alertas_dadas: Dict[str, float] = {}
        self._registro = registro or (lambda texto: print(texto, file=sys.stderr, flush=True))
        self.idx_exp: Dict[str, dict] = {}
        self.idx_ubic: Dict[Tuple[str, str], Tuple[str, int]] = {}
        self.idx_marca: Dict[str, str] = {}
        self.idx_sitio: Dict[str, str] = {}
        self._pool_red = ThreadPoolExecutor(max_workers=6, thread_name_prefix="red")
        self._ultimas_listas: Dict[str, dict] = {}   # última lista de cada proveedor obtenida desde fin+1
        self._t_cierre_falla: Optional[float] = None
        self._foto = False                           # foto de testigos en curso: no sale ningún POST nuevo
        self._posts_en_curso = 0
        self._t_lista: Dict[str, float] = {}         # instante en que se pidió la última lista de cada proveedor
        self._t_fin_listas = NUNCA
        self._huella_testigos: Optional[str] = None
        from .despacho import Despacho
        self.despacho = Despacho(self)

    # ======================================================================================
    # Arranque, reanudación y persistencia
    # ======================================================================================

    def log(self, texto: str) -> None:
        self._registro(texto)

    def _conectar(self, espera_max_s: float = 60.0) -> Tuple[dict, list, dict, dict]:
        limite = time.monotonic() + espera_max_s
        ultimo = None
        while time.monotonic() < limite:
            try:
                return (self.cliente.partido(), self.cliente.proveedores(), self.cliente.juzgados(),
                        self.cliente.estado())
            except ErrorRed as err:
                ultimo = err
                time.sleep(0.5)
        raise SystemExit(f"No se pudo conectar con el simulador en {self.simulador_url}: {ultimo}")

    def arrancar(self, nueva: bool = False, hilos: bool = True) -> None:
        ruta_estado = self.salida / "estado.json"
        if nueva and self.salida.exists() and any(self.salida.iterdir()):
            fecha = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            destino = self.salida.with_name(f"{self.salida.name}.anterior-{fecha}")
            self.salida.rename(destino)
            self.log(f"La salida anterior se guardó en {destino}")
        self.salida.mkdir(parents=True, exist_ok=True)
        (self.salida / "capturas").mkdir(exist_ok=True)
        partido, proveedores, juzgados, estado = self._conectar()
        if ruta_estado.exists():
            self._reanudar(ruta_estado, partido, estado)
        else:
            self._iniciar(partido, proveedores, juzgados, estado)
        # robustez-2: la actividad de los jueces vive en memoria; se cuenta desde acá (ya conectado y reanudado).
        self._t_arranque = time.monotonic()
        self.conexion = "ok"
        if hilos:
            self._iniciar_hilos()

    def _jueces_info(self, juzgados: dict) -> Dict[str, dict]:
        info = {}
        for jz in juzgados.get("juzgados") or []:
            for j in jz.get("jueces") or []:
                info[j["id"]] = {"nombre": j.get("nombre"), "juzgado_id": jz["id"], "juzgado": jz.get("nombre")}
        return info

    def _iniciar(self, partido: dict, proveedores: list, juzgados: dict, estado: dict) -> None:
        self.auditoria = Auditoria(self.salida / "auditoria.jsonl")
        with self.candado:
            e = self.e
            e["partido"] = partido
            e["partido_huella"] = huella(partido)
            e["proveedores"] = proveedores
            e["juzgados"] = juzgados
            e["turnos"] = juzgados.get("turnos") or []
            e["jueces"] = self._jueces_info(juzgados)
            e["simulador"] = self.simulador_url
            self._actualizar_reloj(estado)
            e["de_turno"] = list(estado.get("jueces_de_turno") or [])
            self.auditar("inicio", "sistema", datos={
                "version": VERSION, "simulador": self.simulador_url, "partido": partido.get("id"),
                "nombre": partido.get("nombre"), "fin_min": partido.get("fin_min"),
                "huellas": {"partido": e["partido_huella"], "proveedores": huella(proveedores),
                            "juzgados": huella(juzgados)},
                "dinamica_habilitada": self.dinamica_habilitada, "de_turno": e["de_turno"],
                "minuto_simulador": estado.get("minuto_actual"), "acelerar": estado.get("acelerar"),
            })
            if not e["de_turno"]:
                self.alerta("Nadie está de turno al iniciar: los pedidos quedan sin asignar.", clave="nadie")
            self._marcar()
            self.guardar()

    def _reanudar(self, ruta_estado: Path, partido: dict, estado: dict) -> None:
        with open(ruta_estado, encoding="utf-8") as f:
            guardado = json.load(f)
        if (guardado.get("partido") or {}).get("id") != partido.get("id"):
            raise SystemExit(f"La carpeta {self.salida} es de otro partido "
                             f"({(guardado.get('partido') or {}).get('id')}). Use --nueva o otra --salida.")
        if guardado.get("minuto") is not None and float(estado["minuto_actual"]) < float(guardado["minuto"]) - 0.01:
            raise SystemExit(f"El simulador está en el minuto {estado['minuto_actual']}, antes que lo guardado "
                             f"({guardado['minuto']}): parece reiniciado. Use --nueva para empezar de cero.")
        from .auditoria import apartar_cola_danada, recortar_linea_incompleta
        ruta_aud = self.salida / "auditoria.jsonl"
        recortado = recortar_linea_incompleta(ruta_aud)
        ok, cantidad, errores = verificar_cadena(ruta_aud)
        reparada = None
        if not ok:
            # En la mitad de un partido la plataforma no puede negarse a arrancar: la cola dañada se aparta
            # (no se borra), la cadena sigue desde la última entrada buena y queda constancia.
            reparada = apartar_cola_danada(ruta_aud, datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
            if reparada is not None:
                reparada["errores"] = errores[:5]
            ok, cantidad, errores = verificar_cadena(ruta_aud) if ruta_aud.exists() else (True, 0, [])
            if not ok:
                raise SystemExit("La auditoría guardada no verifica ni apartando la cola dañada: " + "; ".join(errores[:3]))
        self.auditoria = Auditoria(ruta_aud)
        self.auditoria.recortado = recortado
        with self.candado:
            base = _estado_inicial()
            base.update(guardado)
            self.e = base
            v_guardada = guardado.get("v")
            if isinstance(v_guardada, int) and not isinstance(v_guardada, bool) and v_guardada >= self.v:
                self.v = v_guardada + 1  # kit-4: el serial de la zona sigue subiendo después de un reinicio
            anterior_url = self.e.get("simulador")
            self.e["simulador"] = self.simulador_url
            self._reconstruir_indices()
            self._actualizar_reloj(estado)
            # Las órdenes que estaban en el aire o por enviar se consultan antes de volver a mandarlas.
            for o in self.e["ordenes"].values():
                en_vuelo = o.pop("en_vuelo", None)
                for campo in CAMPOS_MONOTONICOS:
                    if campo in o:
                        o[campo] = None  # «nunca» en este proceso: un instante de otro proceso no se compara
                if o["estado"] in ("por_enviar", "espera_ratificacion") and (en_vuelo or o.get("enviada_min") is not None):
                    o["incierta"] = True
                    o["t_error"] = None
                    # f-despacho-1: el instante del POST de otro proceso se perdió; los 12 s de C19 cuentan desde
                    # acá, así un original lento alcanza a aparecer antes de reenviar el mismo orden_id.
                    o["t_post"] = time.monotonic()
                # Un levantamiento a medio hacer (firmado y quizá enviado) se confirma con GET antes de repetirlo.
                if o.get("levantar") and (o["levantar"].get("enviado") or en_vuelo) and o["estado"] in VIGENTES:
                    o["lev_incierto"] = True
                    o["t_error"] = None
            self.auditar("reanudacion", "sistema", datos={
                "linea_incompleta_descartada": self.auditoria.recortado,
                "version": VERSION, "minuto_guardado": guardado.get("minuto"),
                "minuto_simulador": estado.get("minuto_actual"), "entradas_previas": cantidad,
                "estado_hasta_entrada": guardado.get("aud_n"),
                "dinamica_habilitada": self.dinamica_habilitada, "simulador": self.simulador_url,
                "simulador_anterior": anterior_url})
            if anterior_url and anterior_url != self.simulador_url:
                self.alerta(f"Se reanudó contra otro simulador ({self.simulador_url}; antes {anterior_url}): se "
                            "comparan las órdenes con lo que tiene cada proveedor.", clave="otro-simulador")
            if reparada is not None:
                self.auditar("auditoria_reparada", "sistema", datos=reparada)
                self.alerta(f"La auditoría guardada estaba dañada desde la línea {reparada['desde_linea']}: se apartaron "
                            f"{_cant(reparada['lineas'], 'línea', 'líneas')} a {reparada['archivo']} (sha256 {reparada['sha256'][:16]}…) y "
                            "la cadena sigue desde la última entrada buena.", clave="auditoria-reparada")
        self._reconciliar()
        with self.candado:
            self._marcar()
            self.guardar()

    def _reconciliar(self) -> None:
        """Compara las órdenes guardadas con las de cada proveedor del simulador."""
        listas = self._listas_proveedores([p["id"] for p in self.e["proveedores"]], marcar_red=False)
        with self.candado:
            nuestras = self.e["ordenes"]
            for pid, lista in listas.items():
                if lista is None:
                    continue
                vistas = set()
                for s in lista:
                    if not isinstance(s, dict):
                        continue
                    vistas.add(s.get("orden_id"))
                    o = nuestras.get(s.get("orden_id"))
                    if o is None:
                        self.alerta(f"El proveedor {pid} tiene la orden {s.get('orden_id')} que no figura en el estado "
                                    "guardado.", clave=f"desconocida-{s.get('orden_id')}")
                        continue
                    if o.get("incierta") or o["estado"] in ("por_enviar", "espera_ratificacion"):
                        self._adoptar(o, s, "reanudación: el proveedor ya la tenía")
                    else:
                        self._aplicar_estado_sim(o, s)
                for o in nuestras.values():
                    if o["proveedor"] == pid and o.get("incierta") and o["orden_id"] not in vistas:
                        # El proveedor no la lista: cuenta como un primer 404. Se reenvía (con el mismo orden_id)
                        # recién cuando un GET lo confirme.
                        o["n_404"] = max(1, int(o.get("n_404") or 0))
                self._detectar_perdidas(pid, vistas)

    def _reconstruir_indices(self) -> None:
        self.idx_exp, self.idx_ubic, self.idx_marca, self.idx_sitio = {}, {}, {}, {}
        for exp in self.e["expedientes"]:
            self.idx_exp[exp["id"]] = exp
            self.idx_sitio.setdefault(exp["sitio"], exp["id"])
            if exp["filtracion"].get("sesion"):
                for m in exp["filtracion"]["marcas"]:
                    self.idx_marca[m] = exp["id"]
            for u in exp["ubicaciones"]:
                self.idx_ubic[(u["host"], u["ip"])] = (exp["id"], u["n"])
                if "detecciones_min" not in u:  # estado de una versión anterior
                    u["detecciones_min"] = [m for m in dict.fromkeys(
                        (u.get("primera_deteccion_min"), u.get("ultima_deteccion_min"))) if m is not None]

    def guardar(self) -> None:
        with self.candado:
            self.e["minuto"] = r3(self.reloj.ahora())
            # robustez-3: hasta qué entrada de la auditoría refleja este estado (lo cruza el verificador al reanudar).
            self.e["aud_n"] = self.auditoria.n if self.auditoria else None
            # kit-4: la versión de las vistas (serial de rpz.zone) no retrocede al reiniciar.
            self.e["v"] = self.v
            guardar_json_atomico(self.salida / "estado.json", self.e)
            self._sucio = False

    def _iniciar_hilos(self) -> None:
        h = threading.Thread(target=self._bucle, name="motor", daemon=True)
        h.start()
        self._hilos.append(h)
        self._hilos.append(self.despacho.iniciar())

    def detener(self) -> None:
        self._parar.set()
        self.despacho.detener()
        self._pool_red.shutdown(wait=True)
        for h in self._hilos:
            h.join(timeout=5)
        with self.candado:
            self.guardar()
        if self.auditoria:
            self.auditoria.cerrar()

    # ======================================================================================
    # Utilidades de estado
    # ======================================================================================

    def ahora(self) -> float:
        m = self.reloj.ahora()
        return m if m is not None else 0.0

    def fin_min(self) -> float:
        return float(self.e["partido"]["fin_min"])

    def margen_envio(self, acelerar: Optional[float] = None, duracion_s: Optional[float] = None) -> float:
        """Margen antes del final (y antes del vencimiento) para mandar una orden: (2 s + 1,5 × D) reales."""
        dur = self.latencia_para() if duracion_s is None else duracion_s
        return turnos.margen_fin(acelerar if acelerar else self.reloj.acelerar, dur)

    def latencia_para(self, est: Optional[dict] = None) -> float:
        """La latencia que se toma en cuenta: la del /estado de esta decisión o la reciente, la mayor."""
        return max(float((est or {}).get("_dur_s") or 0.0), self.reloj.duracion_reciente(), self._latencia_post())

    def _latencia_post(self) -> float:
        """turnos-1: una orden llega al simulador una latencia de POST después del chequeo de turno."""
        f = getattr(self.cliente, "latencia_post", None)
        try:
            return max(0.0, float(f())) if callable(f) else 0.0
        except (TypeError, ValueError):
            return 0.0

    def _marcar(self) -> None:
        """Algo cambió: sube la versión y despierta a quienes esperan."""
        with self.cond:
            self.v += 1
            self._sucio = True
            self.cond.notify_all()

    def auditar(self, tipo: str, actor: str, exp: Optional[str] = None, datos: Optional[dict] = None,
                minuto: Optional[float] = None) -> dict:
        assert self.auditoria is not None
        return self.auditoria.agregar(tipo, actor, self.ahora() if minuto is None else minuto, exp, datos)

    def aviso(self, tipo: str, texto: str, exp: Optional[str] = None, para: Optional[str] = None,
              clave: Optional[str] = None) -> dict:
        """Aviso para un juez (o para la sala, con para=None). Los repetidos por la misma causa (misma clave y mismo
        destinatario, sin atender) se agrupan en uno solo que actualiza su contador, su minuto y su texto."""
        if clave:
            for a in reversed(self.e["avisos"]):
                if a.get("clave") == clave and a.get("para") == para and not a.get("atendido"):
                    a["cuenta"] = int(a.get("cuenta") or 1) + 1
                    a["min"] = r3(self.ahora())
                    a["texto"] = texto
                    return a
        self.e["num_aviso"] += 1
        a = {"n": self.e["num_aviso"], "min": r3(self.ahora()), "tipo": tipo, "texto": texto, "exp": exp,
             "para": para, "clave": clave or f"{tipo}-{self.e['num_aviso']}", "cuenta": 1, "atendido": False,
             "cierre": None}
        self.e["avisos"].append(a)
        if len(self.e["avisos"]) > 300:
            self.e["avisos"] = self.e["avisos"][-200:]
        return a

    def cerrar_aviso(self, a: dict, texto: str, minuto: Optional[float] = None) -> None:
        """Con el candado: el aviso queda atendido, con lo que pasó (ronda 3, C3). Uno ya cerrado no se toca."""
        if a.get("atendido") and a.get("cierre"):
            return
        a["atendido"] = True
        a["cierre"] = {"min": r3(self.ahora() if minuto is None else minuto), "texto": texto}
        if a.get("juez_ausente"):
            # Pedido de W (C21): el cierre de una alerta de ausencia dice de qué juez era.
            a["cierre"]["juez_ausente"] = a["juez_ausente"]
        self._marcar()

    def _quien(self, juez_id: Optional[str], para: Optional[str]) -> str:
        """«Usted» si el aviso es para ese mismo juez; si no, su nombre."""
        return "Usted" if juez_id and juez_id == para else (self.nombre_juez(juez_id) or "El juez")

    def alerta(self, texto: str, clave: Optional[str] = None, exp: Optional[str] = None) -> None:
        clave = clave or texto
        if clave in self._alertas_dadas:
            return
        self._alertas_dadas[clave] = time.monotonic()
        with self.candado:
            self.auditar("alerta", "sistema", exp=exp, datos={"texto": texto})
            self.aviso("alerta", texto, exp=exp, para=None, clave=clave)
            self._marcar()
        self.log("ALERTA: " + texto)

    def nombre_juez(self, juez_id: Optional[str]) -> Optional[str]:
        if not juez_id:
            return None
        return (self.e["jueces"].get(juez_id) or {}).get("nombre") or juez_id

    def info_juez(self, juez_id: str) -> dict:
        info = self.e["jueces"].get(juez_id) or {}
        return {"juez_id": juez_id, "nombre": info.get("nombre") or juez_id}

    def proveedor(self, pid: str) -> dict:
        for p in self.e["proveedores"]:
            if p["id"] == pid:
                return p
        return {"id": pid, "nombre": pid, "clientes": 0, "capacidades": []}

    def _actualizar_reloj(self, estado: dict, t_pedido: Optional[float] = None,
                          t_respuesta: Optional[float] = None) -> None:
        res = self.reloj.actualizar(float(estado["minuto_actual"]), estado.get("acelerar"), estado.get("fin_min"),
                                    t_pedido=t_pedido, t_respuesta=t_respuesta)
        if res == reloj_mod.SOSPECHA:
            self.log(f"Lectura del reloj más baja que la anterior (min {estado['minuto_actual']}): se espera una "
                     "segunda lectura antes de concluir nada.")
        elif res == reloj_mod.RETROCESO:
            self.alerta("El minuto del simulador retrocedió en dos lecturas seguidas: parece que lo reiniciaron. No se "
                        "firma nada hasta que el reloj vuelva a ser coherente. Si de verdad reiniciaron el simulador, "
                        "pida a la organización que lo vuelva al minuto en que estaba (--inicio-min) o, si es un "
                        "partido nuevo, detenga la plataforma y arránquela con --nueva.", clave="retroceso")
        elif res == reloj_mod.DESPEJADO:
            self._alertas_dadas.pop("retroceso", None)
            with self.candado:
                self.auditar("alerta", "sistema", datos={
                    "texto": "El reloj del simulador volvió a ser coherente con el anterior: se vuelve a firmar.",
                    "clave": "retroceso-despejado"})
                self.aviso("alerta", "El reloj del simulador volvió a ser coherente: se vuelve a firmar.")
                self._marcar()

    def _leer_estado(self, red: bool = False) -> dict:
        """GET /estado con la duración medida: deja `_t_pedido`, `_t_respuesta` y `_dur_s` en la respuesta."""
        t0 = time.monotonic()
        est = self._red(self.cliente.estado) if red else self.cliente.estado()
        t1 = time.monotonic()
        if not isinstance(est, dict):
            raise ErrorRed(f"GET /estado devolvió algo que no es un objeto: {str(est)[:80]}")
        est = dict(est, _t_pedido=t0, _t_respuesta=t1, _dur_s=round(t1 - t0, 4))
        self.reloj.registrar_duracion(t1 - t0)
        self._actualizar_reloj(est, t0, t1)
        return est

    def estado_fresco(self) -> dict:
        """Consulta fresca de GET /estado (fuera del candado)."""
        return self._leer_estado()

    def puede_firmar_con(self, juez_id: str, est: dict) -> Tuple[bool, Optional[str]]:
        if self.reloj.retrocedio:
            return False, "El reloj del simulador retrocedió: la plataforma no firma hasta que vuelva a ser coherente."
        return turnos.puede_firmar_con(juez_id, est, self.e["turnos"], self.latencia_para())

    def puede_firmar(self, juez_id: str) -> Tuple[bool, Optional[str], Optional[dict]]:
        """Consulta fresca a /estado y márgenes de la sección 6. Llamar SIN el candado tomado."""
        try:
            est = self.estado_fresco()
        except ErrorRed:
            return False, "Sin conexión con el simulador: no se puede confirmar el turno.", None
        ok, motivo = self.puede_firmar_con(juez_id, est)
        return ok, motivo, est

    def de_turno(self) -> List[str]:
        return list(self.e.get("de_turno") or [])

    def primero_de_turno(self) -> Optional[str]:
        return turnos.primero_de_turno(self.e["turnos"], self.de_turno())

    def objetivo_activo(self, pid: str, tipo: str, objetivo: str) -> Optional[str]:
        for o in self.e["ordenes"].values():
            mismo = o["objetivo"] == objetivo if tipo == "ip" else \
                dominios.normalizar(o["objetivo"]) == dominios.normalizar(objetivo)
            if (o["proveedor"] == pid and o["tipo"] == tipo and mismo
                    and o["estado"] in ACTIVAS and not o.get("levantar")):
                return o["orden_id"]
        return None

    def ubicacion(self, exp_id: str, n: int) -> Tuple[dict, dict]:
        exp = self.idx_exp.get(exp_id)
        if exp is None:
            raise ErrorAccion("no_encontrado", f"No existe el expediente {exp_id}.")
        for u in exp["ubicaciones"]:
            if u["n"] == n:
                return exp, u
        raise ErrorAccion("no_encontrado", f"No existe la ubicación {n} del expediente {exp_id}.")

    def hosts_piratas(self) -> set:
        hosts = set()
        for exp in self.e["expedientes"]:
            for u in exp["ubicaciones"]:
                hosts.add(u["host"])
        return hosts

    def _donde_se_vio(self, dominio: str) -> Optional[Tuple[str, Any]]:
        """C14: ("transmitiendo" | "publicando", minuto) si la plataforma vio ese nombre como host de un stream o como
        nombre observado de una ubicación (la página en el mismo registrable); None si nunca lo vio."""
        mejor = None
        for exp in self.e["expedientes"]:
            for u in exp["ubicaciones"]:
                m = u.get("primera_deteccion_min")
                if u["host"] == dominio:
                    cand = ("transmitiendo", m)
                elif dominio in [dominios.normalizar(x) for x in (u.get("colateral") or {}).get("observados") or []]:
                    cand = ("publicando", m)
                else:
                    continue
                if mejor is None or (cand[0] == "transmitiendo" and mejor[0] != "transmitiendo"):
                    mejor = cand
        return mejor

    def _inferido_en(self, dominio: str, causantes: List[dict]) -> Optional[str]:
        """C14: el registrable por el que la plataforma infirió que `dominio` era del pirata (en alguna ubicación
        causante), o None."""
        for c in causantes:
            try:
                _, u = self.ubicacion(c["exp"], c["n"])
            except ErrorAccion:
                continue
            if dominio in [dominios.normalizar(x) for x in (u.get("colateral") or {}).get("inferidos") or []]:
                return dominios.registrable(dominio)
        return None

    # ======================================================================================
    # Ciclo
    # ======================================================================================

    def _bucle(self) -> None:
        while not self._parar.is_set():
            t0 = time.monotonic()
            try:
                self.paso()
            except Exception:  # El ciclo no se cae por un error: se anota y sigue.
                self.log("Error en el ciclo del motor:\n" + traceback.format_exc())
                try:
                    self.alerta("Error interno en el ciclo del motor (ver consola).", clave="error-ciclo")
                except Exception:
                    pass
            self._parar.wait(max(0.0, self.tick - (time.monotonic() - t0)))

    def _red(self, funcion, *args):
        """Ejecuta una consulta de red; marca la conexión según resulte."""
        try:
            resultado = funcion(*args)
        except ErrorRed:
            if self.conexion != "sin_conexion":
                self.conexion = "sin_conexion"
                self.alerta("Sin conexión con el simulador: se reintenta en cada ciclo.", clave="sin-conexion")
            raise
        if self.conexion != "ok":
            self.conexion = "ok"
            self._alertas_dadas.pop("sin-conexion", None)
            with self.candado:
                self.auditar("alerta", "sistema", datos={"texto": "Conexión con el simulador restablecida."})
                self._marcar()
        return resultado

    def paso(self) -> None:
        """Un ciclo. Cada etapa corre aunque la anterior haya fallado: un dato raro no traba el partido."""
        for nombre, etapa in (("detecciones", self._paso_detecciones), ("estado", self._paso_estado),
                              ("dinamicas", self._paso_dinamicas), ("presencia", self._paso_presencia),
                              ("seguimiento", self._paso_seguimiento),
                              ("reclamos", self._paso_reclamos), ("fin", self._paso_fin),
                              ("testigos", self._paso_pedido_testigos)):
            try:
                etapa()
            except ErrorRed:
                continue
            except Exception:
                self._error_etapa(nombre)
        try:
            if self.despacho.hay_trabajo():
                self.despacho.despertar()
        except Exception:
            self._error_etapa("despacho")
        with self.candado:
            if self._sucio:
                self.guardar()

    def _error_etapa(self, nombre: str) -> None:
        self.log(f"Error en la etapa «{nombre}» del ciclo del motor:\n" + traceback.format_exc())
        try:
            self.alerta(f"Error interno en la etapa «{nombre}» del ciclo (ver la consola); las demás etapas siguen.",
                        clave="error-" + nombre)
        except Exception:
            pass

    # --- 1. detecciones ------------------------------------------------------------------

    def _dns_ip(self, ip: str) -> Optional[dict]:
        cache = self.e["dns"]["ip"]
        if ip not in cache:
            resp = self._red(self.cliente.dns_ip, ip)
            with self.candado:
                cache[ip] = {"resp": resp, "min": r3(self.ahora())}
        return cache[ip]

    def _consulta_dns_dominio(self, dominio: str) -> Optional[dict]:
        """GET /dns-pasivo?dominio= con el nombre tal cual llegó; si no lo conoce, con el nombre normalizado."""
        crudo = str(dominio or "").strip()
        resp = self._red(self.cliente.dns_dominio, crudo)
        normal = dominios.normalizar(crudo)
        if resp is None and normal and normal != crudo:
            resp = self._red(self.cliente.dns_dominio, normal)
        return resp

    def _dns_dominio(self, dominio: str) -> Optional[dict]:
        cache = self.e["dns"]["dominio"]
        clave = dominios.normalizar(dominio)
        if clave not in cache:
            resp = self._consulta_dns_dominio(dominio)
            with self.candado:
                cache[clave] = {"resp": resp, "min": r3(self.ahora())}
        return cache[clave]

    def _consultar_dns(self, ips: List[str], nombres: List[str]) -> None:
        """Consultas de DNS pasivo de un lote, en paralelo y fuera del candado. Se guardan las que salieron; si
        alguna falló se levanta ErrorRed (el lote se vuelve a pedir en el próximo ciclo)."""
        if not ips and not nombres:
            return
        futuros = [("ip", ip, self._pool_red.submit(self._red, self.cliente.dns_ip, ip)) for ip in ips]
        futuros += [("dominio", n, self._pool_red.submit(self._consulta_dns_dominio, n)) for n in nombres]
        fallo = None
        resultados = []
        for clase, clave, f in futuros:
            try:
                resultados.append((clase, clave, f.result()))
            except ErrorRed as err:
                fallo = err
        with self.candado:
            minuto = r3(self.ahora())
            for clase, clave, resp in resultados:
                k = clave if clase == "ip" else dominios.normalizar(clave)
                self.e["dns"][clase].setdefault(k, {"resp": resp, "min": minuto})
        if fallo is not None:
            raise fallo

    def _listas_proveedores(self, pids: List[str], marcar_red: bool = True) -> Dict[str, Optional[list]]:
        """GET /proveedores/<id>/ordenes de varios proveedores en paralelo (fuera del candado). Una lista que no
        se pudo obtener queda en None. Anota en `_t_lista` el instante en que se pidió cada una."""
        def una(pid: str) -> Optional[list]:
            t0 = time.monotonic()
            try:
                lista = self._red(self.cliente.ordenes, pid) if marcar_red else self.cliente.ordenes(pid)
            except ErrorRed:
                return None
            if not isinstance(lista, list):
                return None
            self._t_lista[pid] = t0
            return lista
        futuros = {pid: self._pool_red.submit(una, pid) for pid in pids}
        return {pid: f.result() for pid, f in futuros.items()}

    def _paso_detecciones(self) -> None:
        t0 = time.monotonic()
        lote = self._red(self.cliente.detecciones, self.e["desde"])
        t1 = time.monotonic()
        if not isinstance(lote, dict):
            raise ValueError(f"GET /detecciones devolvió algo que no es un objeto: {str(lote)[:80]}")
        m_lote = lote.get("minuto_actual")
        m_lote = float(m_lote) if evidencia._numero(m_lote) else None
        if m_lote is not None:
            self._actualizar_reloj({"minuto_actual": m_lote, "acelerar": self.reloj.acelerar}, t0, t1)
        crudas = lote.get("detecciones")
        crudas = crudas if isinstance(crudas, list) else []
        vistas = set(self.e["detecciones_vistas"])
        candidatas: List[dict] = []
        invalidas: List[Tuple[Any, str]] = []
        for d in crudas:
            d = evidencia.normalizar_deteccion(d)
            motivo = evidencia.validar_deteccion(d)
            if motivo is not None:
                did = d.get("id") if isinstance(d, dict) else None
                if not (isinstance(did, str) and did in vistas):
                    invalidas.append((d, motivo))
                continue
            if d["id"] in vistas or any(c["id"] == d["id"] for c in candidatas):
                continue
            candidatas.append(d)
        candidatas.sort(key=lambda d: (float(d["minuto"]), d["id"]))
        partido = self.e["partido"]
        senales: Dict[str, dict] = {}
        pedir_ip: List[str] = []
        pedir_nombre: List[str] = []
        for d in list(candidatas):
            try:
                host = dominios.normalizar(d["host_stream"])
                senal = evidencia.analizar_senal(d.get("marca_de_agua_extraida"), partido, host,
                                                 dominios.host_de(d.get("pagina")))
            except Exception as err:  # Un dato raro en una detección no frena a las demás.
                self.log("Detección que no se pudo analizar:\n" + traceback.format_exc())
                invalidas.append((d, f"no se pudo analizar la señal: {type(err).__name__}: {err}"))
                candidatas.remove(d)
                continue
            senales[d["id"]] = senal
            if senal["clase"] == "pirata" and (host, str(d["ip_servidor"])) not in self.idx_ubic:
                ip = str(d["ip_servidor"])
                if ip not in self.e["dns"]["ip"] and ip not in pedir_ip:
                    pedir_ip.append(ip)
                if not dominios.es_ip(host) and host not in self.e["dns"]["dominio"] and \
                        host not in [dominios.normalizar(n) for n in pedir_nombre]:
                    pedir_nombre.append(str(d["host_stream"]))
        self._consultar_dns(pedir_ip, pedir_nombre)
        with self.candado:
            for d, motivo in invalidas:
                self._deteccion_invalida(d, motivo)
            for d in candidatas:
                try:
                    self._procesar_deteccion(d, senales[d["id"]])
                except Exception as err:
                    self.log(f"Falló el procesamiento de la detección {d['id']}:\n" + traceback.format_exc())
                    self._deteccion_invalida(d, f"falló el procesamiento: {type(err).__name__}: {err}")
            if m_lote is not None:
                self.e["desde"] = m_lote
            else:
                self.e["desde"] = max([float(self.e["desde"])] + [float(d["minuto"]) for d in candidatas])
            if candidatas or invalidas:
                self._marcar()

    def _deteccion_invalida(self, d: Any, motivo: str) -> None:
        """Con el candado: la detección queda vista, auditada y avisada; no se pide ningún bloqueo."""
        did = d.get("id") if isinstance(d, dict) else None
        did = did if isinstance(did, str) and did.strip() else None
        if did and did not in self.e["detecciones_vistas"]:
            self.e["detecciones_vistas"].append(did)
        minuto = d.get("minuto") if isinstance(d, dict) and evidencia._numero(d.get("minuto")) else None
        linea = " ".join(str(motivo).split())[:300]
        self.e["detecciones_invalidas"] = int(self.e.get("detecciones_invalidas") or 0) + 1
        self.auditar("deteccion_invalida", "sistema", datos={"deteccion": did, "minuto": minuto, "motivo": linea})
        self.alerta(f"Detección {did or '(sin id)'} descartada por inválida: {linea}",
                    clave=f"det-invalida-{did or self.e['detecciones_invalidas']}")

    def _guardar_captura(self, d: dict) -> None:
        datos = evidencia.decodificar_captura(d.get("captura"))
        if datos is None:
            return
        ruta = self.salida / "capturas" / nombre_captura(d["id"])
        if not ruta.exists():
            ruta.write_bytes(datos)

    def _procesar_deteccion(self, d: dict, senal: dict) -> None:
        e = self.e
        e["detecciones_vistas"].append(d["id"])
        host = dominios.normalizar(d.get("host_stream"))
        ip = str(d.get("ip_servidor") or "")
        self._guardar_captura(d)
        cap = evidencia.analizar_captura(d.get("captura"),
                                         {s for s, did in e["sha_vistos"].items() if did != d["id"]})
        if cap["sha256"] and cap["sha256"] not in e["sha_vistos"]:
            e["sha_vistos"][cap["sha256"]] = d["id"]
        self.auditar("deteccion_recibida", "titular", datos={
            "deteccion": d["id"], "minuto": d.get("minuto"), "host": host, "ip": ip,
            "marca": d.get("marca_de_agua_extraida"), "clase": senal["clase"], "captura_sha256": cap["sha256"]})

        if senal["clase"] != "pirata":
            clave = f"{host}|{senal['clase']}"
            desc = e["descartes"].get(clave)
            if desc is None:
                desc = {"deteccion_id": d["id"], "minuto": d.get("minuto"), "host": host, "ip": ip,
                        "pagina": d.get("pagina"), "marca": d.get("marca_de_agua_extraida"), "clase": senal["clase"],
                        "motivo": senal["motivo"], "veces": 0, "ultima_min": d.get("minuto")}
                e["descartes"][clave] = desc
            desc["veces"] += 1
            desc["ultima_min"] = d.get("minuto")
            self.auditar("deteccion_descartada", "sistema", datos={
                "deteccion": d["id"], "host": host, "clase": senal["clase"], "motivo": senal["motivo"],
                "veces": desc["veces"]})
            return

        clave_u = (host, ip)
        if clave_u in self.idx_ubic:
            exp_id, n = self.idx_ubic[clave_u]
            exp, u = self.ubicacion(exp_id, n)
            if u.get("levantada_por_freno") and not u.get("reabierta_en") and not self.e["hitos"].get("fin"):
                # C4: el juez frenó el seguimiento y levantó la ampliación de este servidor, que sigue transmitiendo.
                # No se suma en silencio: abre una ubicación nueva, pendiente, que vuelve a la bandeja del juez.
                self._reabrir_ubicacion(exp, u, d, senal, cap)
                return
            if self._vuelve_tras_rechazo(u, d):
                # C22: un juez rechazó este servidor y la plataforma lo sigue viendo después: no se suma en silencio a
                # la rechazada; vuelve a la bandeja como pedido nuevo, nunca ampliable solo.
                self._pedido_tras_rechazo(exp, u, d, senal, cap)
                return
            if d["id"] not in u["detecciones"]:
                u["detecciones"].append(d["id"])
                u.setdefault("detecciones_min", []).append(d.get("minuto"))
                u["ultima_deteccion_min"] = d.get("minuto")
            return

        pagina_host = dominios.host_de(d.get("pagina"))
        sitio = dominios.registrable(pagina_host or host)
        marca = (d.get("marca_de_agua_extraida") or "").strip()
        exp, criterio = None, None
        if senal.get("sesion") and marca in self.idx_marca:
            exp, criterio = self.idx_exp[self.idx_marca[marca]], "misma_marca"
        elif sitio in self.idx_sitio:
            exp, criterio = self.idx_exp[self.idx_sitio[sitio]], "mismo_sitio"
        nuevo = exp is None
        if nuevo:
            exp = self._abrir_expediente(senal, sitio, marca)
        try:
            self._armar_ubicacion(exp, d, senal, cap, criterio)
        except Exception as err:
            if nuevo and not exp["ubicaciones"]:
                self._anular_expediente(exp, f"no se pudo armar la primera ubicación: {type(err).__name__}: {err}")
            raise
        self._aviso_corte_en_origen(exp, senal)
        if not nuevo and senal.get("sesion") and marca not in exp["filtracion"]["marcas"]:
            exp["filtracion"]["marcas"].append(marca)
            self.idx_marca[marca] = exp["id"]

    def _reabrir_ubicacion(self, exp: dict, u: dict, d: dict, senal: dict, cap: dict) -> dict:
        """Con el candado (C4): la ubicación nueva del mismo servidor, con su propia evidencia sellada, encadenada al
        expediente como cualquier ubicación, pendiente y nunca ampliable sola (`reabierta`)."""
        # Pedido de W (C21): es el mismo servidor (host e IP) que se levantó, no una mudanza: su criterio lo dice. Así
        # tampoco cuenta como «mudanza de la misma marca» que el seguimiento debería haber ampliado solo.
        criterio = "mismo_servidor"
        lev = u["levantada_por_freno"]
        reab = {"de_ubicacion": u["n"], "ampliada_min": lev.get("ampliada_min"), "levantada_min": lev.get("min"),
                "juez_id": lev.get("juez_id"), "juez": lev.get("juez"), "vetados": list(lev.get("vetados") or [])}
        nueva = self._armar_ubicacion(exp, d, senal, cap, criterio, reabre=u["n"])
        nueva["reabierta"] = reab
        nueva["automatica"] = {"posible": False, "motivo": self._motivo_no_ampliar(exp, nueva, False)}
        u["reabierta_en"] = nueva["n"]
        return nueva

    def _vuelve_tras_rechazo(self, u: dict, d: dict) -> bool:
        """C22: la detección es del mismo servidor de una ubicación rechazada y su minuto es posterior al rechazo."""
        dec = u.get("decision") or {}
        m = d.get("minuto")
        return (u.get("estado") == "rechazada" and not self.e["hitos"].get("fin") and dec.get("min") is not None
                and isinstance(m, (int, float)) and not isinstance(m, bool) and float(m) > float(dec["min"]))

    def _pedido_tras_rechazo(self, exp: dict, u: dict, d: dict, senal: dict, cap: dict) -> dict:
        """Con el candado (C22): ubicación nueva del mismo servidor, con su evidencia sellada, pendiente y con
        `rechazo_previo`. La ubicación más nueva de ese servidor pasa a ser la del índice (también al reanudar)."""
        dec = u.get("decision") or {}
        previo = {"ref": u["ref"], "min": dec.get("min"), "juez_id": dec.get("juez_id"),
                  "juez": dec.get("juez") or self.nombre_juez(dec.get("juez_id")), "motivo": dec.get("motivo_rechazo")}
        nueva = self._armar_ubicacion(exp, d, senal, cap, "mismo_servidor", reabre=u["n"], rechazo_previo=previo)
        nueva["automatica"] = {"posible": False, "motivo": self._motivo_no_ampliar(exp, nueva, False)}
        return nueva

    def _rechazada_que_cruza(self, exp: dict, u: dict) -> Optional[dict]:
        """f-turnos-1 (criterio del verificador): la ubicación RECHAZADA de CUALQUIER expediente (Ola D,
        g-seguimiento-1), de otro servidor, que
        comparte la IP o el nombre normalizado del stream con `u`, salvo que ese mismo servidor se haya firmado
        después (el rechazo quedó atrás). None = ninguna. El mismo servidor lo cubre rechazo_previo (C22)."""
        host, ip = dominios.normalizar(u.get("host") or ""), str(u.get("ip") or "")
        todas = [x for e in self.e["expedientes"] for x in e["ubicaciones"]]
        for r in todas:
            if r is u or r.get("estado") != "rechazada":
                continue
            rh, rip = dominios.normalizar(r.get("host") or ""), str(r.get("ip") or "")
            if (rh, rip) == (host, ip):
                continue
            ent_r = (r.get("decision") or {}).get("entrada")  # «después» por la entrada de auditoría (global)
            if any(x.get("estado") == "aprobada" and ent_r is not None
                   and ((x.get("decision") or {}).get("entrada") or -1) > ent_r
                   and (dominios.normalizar(x.get("host") or ""), str(x.get("ip") or "")) == (rh, rip)
                   for x in todas):
                continue
            if (ip and ip == rip) or (host and host == rh):
                return r
        return None

    def nota_reapertura(self, u: dict, para: Optional[str] = None) -> Optional[str]:
        """C4: la nota de continuidad de una ubicación reabierta, para el juez `para` («usted») o en tercera
        persona. C22: también la de un servidor rechazado que se volvió a ver."""
        rp = u.get("rechazo_previo")
        if rp:
            quien = "usted" if rp.get("juez_id") and rp.get("juez_id") == para else (
                rp.get("juez") or self.nombre_juez(rp.get("juez_id")) or "un juez")
            return (f"Mismo servidor: {quien} rechazó este pedido en el minuto {_min_txt(rp.get('min'))}; la "
                    f"plataforma lo volvió a ver transmitiendo en el minuto {_min_txt(u.get('primera_deteccion_min'))}.")
        r = u.get("reabierta")
        if not r:
            return None
        quien = "usted" if r.get("juez_id") and r.get("juez_id") == para else (
            r.get("juez") or self.nombre_juez(r.get("juez_id")) or "el juez")
        return (f"Mismo servidor: la plataforma lo había bloqueado sola en el minuto {_min_txt(r.get('ampliada_min'))}; "
                f"{quien} levantó ese bloqueo en el minuto {_min_txt(r.get('levantada_min'))}.")

    def _anular_expediente(self, exp: dict, motivo: str) -> None:
        """Con el candado: un expediente nunca queda con cero ubicaciones."""
        self.e["expedientes"] = [x for x in self.e["expedientes"] if x["id"] != exp["id"]]
        self.idx_exp.pop(exp["id"], None)
        for indice in (self.idx_sitio, self.idx_marca):
            for clave in [k for k, v in indice.items() if v == exp["id"]]:
                del indice[clave]
        self.auditar("expediente_anulado", "sistema", exp=exp["id"], datos={"motivo": " ".join(motivo.split())[:300]})

    def _abrir_expediente(self, senal: dict, sitio: str, marca: str) -> dict:
        e = self.e
        e["num_exp"] += 1
        anio = str((e["partido"].get("inicio_iso") or "")[:4]) or time.strftime("%Y")
        exp_id = f"EXP-{anio}-{e['num_exp']:06d}"
        clave = marca if senal.get("sesion") else f"{senal.get('prefijo')}@{sitio}"
        exp = {"id": exp_id, "num": e["num_exp"], "titulo": sitio, "sitio": sitio, "creado_min": r3(self.ahora()),
               "estado": "pendiente",
               "filtracion": {"clave": clave, "sesion": senal.get("sesion"),
                              "marcas": [marca] if senal.get("sesion") else [],
                              "prefijo": senal.get("prefijo"), "origen": senal.get("origen")},
               "dinamica": None, "corte_en_origen": None, "ubicaciones": []}
        e["expedientes"].append(exp)
        self.idx_exp[exp_id] = exp
        self.idx_sitio.setdefault(sitio, exp_id)
        if senal.get("sesion"):
            self.idx_marca[marca] = exp_id
        self.auditar("expediente_abierto", "sistema", exp=exp_id, datos={
            "sitio": sitio, "filtracion": exp["filtracion"]["clave"]})
        return exp

    def _armar_ubicacion(self, exp: dict, d: dict, senal: dict, cap: dict, criterio: Optional[str],
                         reabre: Optional[int] = None, rechazo_previo: Optional[dict] = None) -> dict:
        e = self.e
        host = dominios.normalizar(d.get("host_stream"))
        ip = str(d.get("ip_servidor") or "")
        dns_ip = (e["dns"]["ip"].get(ip) or {"resp": None, "min": None})
        dns_host = (e["dns"]["dominio"].get(host) or {"resp": None, "min": None}) if not dominios.es_ip(host) \
            else {"resp": None, "min": None}
        analisis = evidencia.analizar_servidor(d, dns_ip["resp"], dns_host["resp"], self.hosts_piratas(),
                                               self.e.get("inferencias_refutadas") or [])
        colateral = dict(analisis["colateral"])
        colateral["limpia"] = evidencia.es_limpia(senal, analisis["coherencia"], cap, colateral)
        propuesta = evidencia.proponer(analisis, e["proveedores"], self.fin_min())
        n = len(exp["ubicaciones"]) + 1
        anterior = exp["ubicaciones"][-1] if exp["ubicaciones"] else None
        ahora = self.ahora()
        utc = utc_ahora()
        senal_sellada = {k: senal[k] for k in ("marca", "prefijo", "origen", "sesion", "clase", "motivo")}
        consultado = max([m for m in (dns_ip["min"], dns_host["min"]) if m is not None] or [r3(ahora)])
        sellado = {
            "version": 1, "expediente": exp["id"], "ubicacion": n,
            "partido": {"id": e["partido"].get("id"), "nombre": e["partido"].get("nombre"),
                        "titular": e["partido"].get("titular_derechos"), "fin_min": e["partido"].get("fin_min"),
                        "huella": e["partido_huella"]},
            "deteccion": d,
            "captura": cap,
            "senal": senal_sellada,
            "servidor": analisis["servidor"],
            "dns_pasivo": {"por_ip": {ip: dns_ip["resp"]},
                           "por_host": {host: dns_host["resp"]} if not dominios.es_ip(host) else {},
                           "consultado_min": r3(consultado)},
            "coherencia": analisis["coherencia"],
            "colateral": colateral,
            "promocion": d.get("promocion") or [],
            "propuesta": propuesta,
            "antecedente": {"ubicacion": anterior["n"], "huella": anterior["huella"]} if anterior else None,
            "armado": {"min": r3(ahora), "utc": utc},
        }
        h = huella(sellado)
        asignado = self.primero_de_turno()
        u = {
            "n": n, "ref": f"{exp['id']}/U{n}", "estado": "pendiente", "host": host, "ip": ip,
            "host_stream": str(d.get("host_stream") or "").strip(),
            "asn": analisis["servidor"]["asn"], "organizacion": analisis["servidor"]["organizacion"],
            "pagina": d.get("pagina"), "stream_url": d.get("stream_url"),
            "primera_deteccion_min": d.get("minuto"), "ultima_deteccion_min": d.get("minuto"),
            "detecciones": [d["id"]], "detecciones_min": [d.get("minuto")],
            # f-turnos-2: el pedido del mismo servidor apunta a ESE servidor (el rechazado o el levantado); el
            # «antecedente» del sellado sigue siendo la última ubicación (cadena de huellas).
            "continuidad": {"de_ubicacion": reabre if reabre is not None else anterior["n"], "criterio": criterio}
            if anterior and criterio else None,
            "senal": dict(senal), "captura": cap, "coherencia": analisis["coherencia"], "colateral": colateral,
            "promocion": d.get("promocion") or [], "propuesta": propuesta, "huella": h,
            "armado_min": r3(ahora), "armado_utc": utc, "asignada_a": asignado,
            "notificada_min": r3(ahora) if asignado else None, "vista_min": None, "decision": None,
            "automatica": {"posible": False, "motivo": None}, "contadores": {}, "operacion": analisis["operacion"],
            "sellado": sellado,
        }
        if rechazo_previo:
            u["rechazo_previo"] = rechazo_previo
        exp["ubicaciones"].append(u)
        exp["estado"] = "pendiente"
        self.idx_ubic[(host, ip)] = (exp["id"], n)
        self.auditar("ubicacion_armada", "sistema", exp=exp["id"], datos={
            "ubicacion": n, "huella": h, "host": host, "ip": ip, "deteccion": d["id"],
            "continuidad": u["continuidad"], "recomendacion": colateral["recomendacion"],
            "riesgo": colateral["riesgo"], "limpia": colateral["limpia"],
            **({"reabre": reabre} if reabre is not None else {}),
            **({"rechazo_previo": rechazo_previo} if rechazo_previo else {})})
        if asignado:
            self.auditar("notificacion_juez", "sistema", exp=exp["id"], datos={"ubicacion": n, "juez_id": asignado})
        else:
            self.alerta("Llegó un pedido y no hay ningún juez de turno para asignarlo.", clave=f"sin-juez-{u['ref']}",
                        exp=exp["id"])
        return u

    # --- 2 y 3. estado del simulador y traspaso -----------------------------------------

    def _paso_estado(self) -> None:
        ahora = self.ahora()
        esperado = turnos.de_turno(self.e["turnos"], ahora)
        cambio_posible = set(esperado) != set(self.de_turno())
        if time.monotonic() - self._t_estado < 5.0 and not cambio_posible:
            return
        est = self._leer_estado(red=True)
        self._t_estado = time.monotonic()
        if time.monotonic() - self._t_juzgados > 30.0:
            try:
                jz = self._red(self.cliente.juzgados)
                with self.candado:
                    if jz.get("turnos") and jz["turnos"] != self.e["turnos"]:
                        self.e["turnos"] = jz["turnos"]
                        self.e["jueces"] = self._jueces_info(jz)
                        self._marcar()
                self._t_juzgados = time.monotonic()
            except ErrorRed:
                pass
        nuevos = list(est.get("jueces_de_turno") or [])
        with self.candado:
            viejos = self.de_turno()
            if set(nuevos) == set(viejos):
                return
            self.e["de_turno"] = nuevos
            entrantes = [j for j in nuevos if j not in viejos]
            if not nuevos:
                self.alerta("No queda ningún juez de turno: los pedidos esperan al próximo turno.",
                            clave=f"nadie-{r3(ahora)}")
            if entrantes:
                self._crear_traspaso(viejos, nuevos)
            else:
                self._reasignar()
            self._marcar()

    def _reasignar(self) -> None:
        nuevo = self.primero_de_turno()
        for exp in self.e["expedientes"]:
            for u in exp["ubicaciones"]:
                if u["estado"] == "pendiente" and u.get("asignada_a") != nuevo:
                    u["asignada_a"] = nuevo
                    u["notificada_min"] = r3(self.ahora()) if nuevo else None
                    u["vista_min"] = None
                    if nuevo:
                        self.auditar("notificacion_juez", "sistema", exp=exp["id"],
                                     datos={"ubicacion": u["n"], "juez_id": nuevo, "por": "traspaso"})
        for r in self.e["reclamos"].values():
            if r["estado"] == "pendiente":
                r["asignado_a"] = nuevo

    def _resumen_traspaso(self) -> dict:
        pend = sum(1 for exp in self.e["expedientes"] for u in exp["ubicaciones"] if u["estado"] == "pendiente")
        recl = sum(1 for r in self.e["reclamos"].values() if r["estado"] == "pendiente")
        vig = sum(1 for o in self.e["ordenes"].values() if o["estado"] in VIGENTES)
        din = [{"exp": exp["id"], "titulo": exp["titulo"], "sesion": exp["filtracion"].get("sesion")}
               for exp in self.e["expedientes"] if exp.get("dinamica") and exp["dinamica"].get("activa")]
        esp = sum(1 for o in self.e["ordenes"].values() if o["estado"] == "espera_ratificacion")
        return {"ubicaciones_pendientes": pend, "reclamos_pendientes": recl, "bloqueos_vigentes": vig,
                "dinamicas": din, "ordenes_en_espera": esp,
                "levantamientos_pendientes": self._levantamientos_pendientes()}

    def _levantamientos_pendientes(self) -> List[dict]:
        """Levantamientos decididos que todavía no se firmaron ante el proveedor."""
        return [{"orden_id": o["orden_id"], "proveedor": o["proveedor"], "objetivo": o["objetivo"],
                 "reclamo": (o.get("levantar") or {}).get("reclamo")}
                for o in self.e["ordenes"].values()
                if o.get("levantar") and (o["estado"] in VIGENTES or o.get("incierta"))]

    def _crear_traspaso(self, viejos: List[str], nuevos: List[str]) -> None:
        self._reasignar()
        for exp in self.e["expedientes"]:
            din = exp.get("dinamica")
            if din and din.get("activa") and not din.get("revocada"):
                din["requiere_ratificacion"] = True
        self.e["ratificados"] = []
        tr = {"min": r3(self.ahora()), "de": [self.info_juez(j) for j in viejos],
              "a": [self.info_juez(j) for j in nuevos], "requiere_ratificacion": True, "ratificado": None,
              "resumen": self._resumen_traspaso()}
        self.e["traspasos"].append(tr)
        entrada = self.auditar("traspaso_de_turno", "sistema", datos={
            "de": viejos, "a": nuevos, "resumen": tr["resumen"]})
        tr["entrada"] = entrada["n"]
        for j in nuevos:
            self.aviso("traspaso", "Empieza su turno: ratifique lo heredado (bloqueos vigentes y seguimientos).",
                       para=j, clave=f"traspaso-{tr['min']}")
        self.despacho.despertar()

    # --- orden marco (ronda 2b, sección 1) --------------------------------------------------

    def marco_vigente(self, juez_id: Optional[str]) -> Optional[dict]:
        """La última orden marco que firmó ese juez (vale la última suya), o None."""
        for m in reversed(self.e.get("marcos") or []):
            if m.get("juez_id") == juez_id:
                return m
        return None

    def _ref_marco(self, juez_id: Optional[str]) -> Optional[dict]:
        """Lo que citan las entradas decision_juez y ampliacion_dinamica: {entrada, huella} o None."""
        m = self.marco_vigente(juez_id)
        return {"entrada": m["entrada"], "huella": m["huella"]} if m else None

    def seguimiento_autorizado(self, juez_id: Optional[str]) -> bool:
        m = self.marco_vigente(juez_id)
        return bool(self.dinamica_habilitada and m and m.get("seguimiento"))

    def _juez_marco(self, juez: str) -> dict:
        info = self.e["jueces"].get(juez) or {}
        return {"juez_id": juez, "nombre": info.get("nombre"), "juzgado_id": info.get("juzgado_id"),
                "juzgado": info.get("juzgado")}

    def contenido_marco(self, juez: str, seguimiento: bool) -> dict:
        """El contenido canónico de la OM que firmaría ahora este juez (lo arma marco.py, nadie lo redacta acá)."""
        m = self.ahora()
        t = turnos.turno_de(juez, self.e["turnos"], m) or turnos.proximo_turno(juez, self.e["turnos"], m) or {}
        turno = {"desde_min": t.get("desde_min"), "hasta_min": t.get("hasta_min")}
        return marco_mod.armar(self.e["partido"], self.e["proveedores"], self._juez_marco(juez), turno, bool(seguimiento))

    def _validar_marco(self, juez: str) -> None:
        if self.e["hitos"].get("fin"):
            raise ErrorAccion("partido_finalizado", "El partido terminó: ya no se firman órdenes.")
        if juez not in self.de_turno():
            raise ErrorAccion("fuera_de_turno", "No está de turno: no puede firmar la orden marco.")
        if not self.usuarios.tiene_clave(juez):
            raise ErrorAccion("sin_permiso", "No hay una clave de firma para este juez.")

    def firmar_marco(self, juez: str, seguimiento: bool) -> dict:
        """El juez de turno firma su orden marco (mismas reglas de turno que una decisión). Vale la última suya."""
        seguimiento = bool(seguimiento)
        if seguimiento and not self.dinamica_habilitada:
            raise ErrorAccion("invalido", "La plataforma corre sin seguimiento de la filtración: la orden marco se "
                                          "firma sin esa casilla.")
        with self.candado:
            self._validar_marco(juez)
        ok, texto, _ = self.puede_firmar(juez)
        if not ok:
            raise ErrorAccion("fuera_de_turno", texto or "No puede firmar ahora.")
        with self.candado:
            self._validar_marco(juez)
            c = self.contenido_marco(juez, seguimiento)
            h = marco_mod.huella(c)
            pid = str(self.e["partido"].get("id"))
            firma = self.usuarios.firmar_con(juez, sello.firma_marco, pid, h, juez, seguimiento)
            anterior = self.marco_vigente(juez)
            mid = f"OM-{len(self.e['marcos']) + 1:02d}"
            info = self._juez_marco(juez)
            entrada = self.auditar("orden_marco", "juez:" + juez, datos={
                "id": mid, "juez_id": juez, "juzgado_id": info.get("juzgado_id"), "huella": h,
                "seguimiento": seguimiento, "contenido": c, "firma": firma,
                "reemplaza": anterior["entrada"] if anterior else None})
            m = {"id": mid, "juez_id": juez, "nombre": info.get("nombre"), "juzgado_id": info.get("juzgado_id"),
                 "juzgado": info.get("juzgado"), "min": entrada["min"], "utc": entrada["utc"], "entrada": entrada["n"],
                 "huella": h, "seguimiento": seguimiento, "turno": dict(c.get("turno") or {}),
                 "reemplaza": anterior["id"] if anterior else None}
            self.e["marcos"].append(m)
            self._marcar()
            self.guardar()
            vista = self.vista_marco(m)
        return vista

    def vista_marco(self, m: dict) -> dict:
        """Vista pública de una OM (sala y registro)."""
        vigente = self.marco_vigente(m["juez_id"])
        estado, estado_min = self._estado_marco(m)
        return {"id": m["id"], "juez_id": m["juez_id"], "juez": m.get("nombre"), "juzgado": m.get("juzgado"),
                "min": m.get("min"), "hora": hora_de_partido(self.e["partido"].get("inicio_iso"), m.get("min")),
                "huella": m.get("huella"), "seguimiento": bool(m.get("seguimiento")),
                "turno": {"desde_min": (m.get("turno") or {}).get("desde_min"),
                          "hasta_min": (m.get("turno") or {}).get("hasta_min")},
                "entrada": m.get("entrada"), "vigente": bool(vigente is not None and vigente["id"] == m["id"]),
                "estado": estado, "estado_min": estado_min}

    def _estado_marco(self, m: dict) -> Tuple[str, Optional[float]]:
        """Ronda 3, C2: reemplazada (el mismo juez firmó otra después) > turno_terminado (su turno terminó antes del
        final y ya pasó ese minuto) > partido_terminado > vigente."""
        marcos = self.e.get("marcos") or []
        try:
            i = next(k for k, x in enumerate(marcos) if x.get("id") == m.get("id"))
        except StopIteration:
            i = len(marcos)
        for x in marcos[i + 1:]:
            if x.get("juez_id") == m.get("juez_id"):
                return "reemplazada", x.get("min")
        ahora, fin = self.ahora(), self.fin_min()
        hasta = (m.get("turno") or {}).get("hasta_min")
        if evidencia._numero(hasta) and float(hasta) < fin and ahora >= float(hasta):
            return "turno_terminado", hasta
        if ahora >= fin or self.e["hitos"].get("fin"):
            return "partido_terminado", self.e["partido"].get("fin_min")
        return "vigente", None

    def _vista_marco_bandeja(self, juez: str, turno: dict) -> dict:
        m = self.marco_vigente(juez)
        firmada = None
        if m:
            firmada = {"id": m["id"], "min": m.get("min"),
                       "hora": hora_de_partido(self.e["partido"].get("inicio_iso"), m.get("min")),
                       "entrada": m.get("entrada"), "huella": m.get("huella"), "seguimiento": bool(m.get("seguimiento"))}
        try:
            prop = self.contenido_marco(juez, False)
            propuesta = {"lineas": list(prop.get("lineas") or []),
                         "condiciones_seguimiento": list(prop.get("condiciones_seguimiento") or []),
                         "titulo_casilla": marco_mod.TITULO_CASILLA}
        except Exception:  # la propuesta es texto de pantalla: un dato raro no tira la bandeja
            self.log("No se pudo armar la propuesta de orden marco:\n" + traceback.format_exc())
            propuesta = {"lineas": [], "condiciones_seguimiento": [], "titulo_casilla": marco_mod.TITULO_CASILLA}
        puede = bool(turno.get("puede_firmar")) and not self.e["hitos"].get("fin")
        motivo = None if puede else (turno.get("motivo") or "No puede firmar ahora.")
        return {"firmada": firmada, "propuesta": propuesta, "puede_firmar": puede, "motivo_no": motivo,
                "seguimiento_disponible": bool(self.dinamica_habilitada)}

    def vista_jueces(self) -> List[dict]:
        """Estado de cada juez para la sala: de turno, presencia real y orden marco."""
        ids = list(self.e["jueces"].keys())
        for t in self.e["turnos"]:
            if t.get("juez_id") and t["juez_id"] not in ids:
                ids.append(t["juez_id"])
        de = self.de_turno()
        ahora = self.ahora()
        salida = []
        for j in ids:
            hace = self.usuarios.hace_s(j)
            m = self.marco_vigente(j)
            # Pedido de W (C21): el turno en curso o, si no está de turno, el próximo; None si ya no tiene más.
            t = turnos.turno_de(j, self.e["turnos"], ahora) or turnos.proximo_turno(j, self.e["turnos"], ahora)
            salida.append({"juez_id": j, "nombre": self.nombre_juez(j), "de_turno": j in de,
                           "turno": {"desde_min": t.get("desde_min"), "hasta_min": t.get("hasta_min")} if t else None,
                           "activo": self.usuarios.activo(j, PRESENCIA_S),
                           "hace_s": None if hace is None else int(hace),
                           "marco": {"id": m["id"], "seguimiento": bool(m.get("seguimiento"))} if m else None})
        return salida

    # --- presencia real del juez (ronda 2b, sección 2) ---------------------------------------

    def _pedidos_esperando(self, j: str) -> int:
        n = sum(1 for exp in self.e["expedientes"] for u in exp["ubicaciones"]
                if u["estado"] == "pendiente" and u.get("asignada_a") == j)
        return n + sum(1 for r in self.e["reclamos"].values() if r["estado"] == "pendiente" and r.get("asignado_a") == j)

    def _paso_presencia(self) -> None:
        """Alerta a la sala si el juez de turno no tiene la plataforma abierta y hay pedidos. La alerta se cierra sola
        cuando el juez vuelve o ya no hay pedidos esperando; si después se vuelve a ausentar, sale otra (C3)."""
        with self.candado:
            m = self.ahora()
            for a in self.e["avisos"]:
                j = a.get("juez_ausente")
                if not j or a.get("atendido"):
                    continue
                if self.usuarios.activo(j, PRESENCIA_S):
                    self.cerrar_aviso(a, f"{self.nombre_juez(j)} volvió a tener la plataforma abierta en el minuto "
                                         f"{_min_txt(r3(m))}.", r3(m))
                elif not self._pedidos_esperando(j) or j not in self.de_turno():
                    self.cerrar_aviso(a, f"Ya no hay pedidos esperando (minuto {_min_txt(r3(m))}).", r3(m))
                else:
                    continue
                self._alertas_dadas.pop(a.get("clave"), None)
            if self.e["hitos"].get("fin"):
                return
            for j in self.de_turno():
                if self.usuarios.activo(j, PRESENCIA_S):
                    continue
                n = self._pedidos_esperando(j)
                if not n:
                    continue
                t = turnos.turno_de(j, self.e["turnos"], m) or {}
                clave = f"ausente-{j}-{t.get('desde_min')}"
                texto = (f"{self.nombre_juez(j)} está de turno y no tiene la plataforma abierta: hay {_pedidos(n)} "
                         "esperando.")
                abierta = next((a for a in reversed(self.e["avisos"])
                                if a.get("clave") == clave and not a.get("atendido")), None)
                if abierta is not None:
                    # C23: la misma ausencia no repite la alerta, pero el aviso dice cuántos pedidos esperan ahora.
                    if abierta.get("texto") != texto:
                        abierta["texto"] = texto
                        self._marcar()
                    continue
                self._alertas_dadas.pop(clave, None)
                self.alerta(texto, clave=clave)
                for a in reversed(self.e["avisos"]):
                    if a.get("clave") == clave and not a.get("atendido"):
                        a["juez_ausente"] = j
                        break

    # --- 4. ampliaciones dinámicas ---------------------------------------------------------

    def _vetos_del_host(self, u: dict) -> List[list]:
        host = dominios.normalizar(u.get("host") or "")
        if not host or dominios.es_ip(host):
            return []
        return [x for x in self.e["vetados"] if x[0] == "dominio" and dominios.normalizar(x[1]) == host]

    def _veto_del_host(self, u: dict) -> Optional[str]:
        """C14: si el host del stream de esta ubicación estaba vetado, la frase de por qué lo decide el juez."""
        if not self._vetos_del_host(u):
            return None
        host = dominios.normalizar(u["host"])
        for r in self.e["reclamos"].values():
            res = r.get("resolucion") or {}
            if r["estado"] != "resuelto" or not res.get("juez_id"):
                continue
            lev = [self.e["ordenes"].get(oid) for oid in
                   ([x["orden_id"] for x in (r.get("propuesta") or {}).get("levantar") or []])]
            if r["dominio"] == host or any(o and dominios.normalizar(o["objetivo"]) == host for o in lev):
                return (f"{host} se había levantado por el reclamo {r['id']} en el minuto {_min_txt(res.get('min'))}, "
                        "y ahora la plataforma lo vio transmitiendo el partido: lo decide el juez.")
        return f"{host} se había levantado por decisión del juez, y ahora la plataforma lo vio transmitiendo: lo decide el juez."

    def _motivo_no_ampliar(self, exp: dict, u: dict, fin: bool) -> Optional[str]:
        """Por qué esta ubicación no se amplía sola, en una frase llana que la pantalla muestra como «No se amplió
        solo: {texto}» (ronda 3, C6). None = se puede ampliar."""
        din = exp.get("dinamica")
        if (u.get("automatica") or {}).get("definitivo"):
            # No se amplió por ausencia del juez: queda como pedido para firma en persona, aunque vuelva.
            return u["automatica"].get("motivo")
        if u.get("reabierta"):
            # C4: el juez levantó la ampliación de este mismo servidor; ahora decide él.
            return "este mismo servidor ya se había bloqueado solo y ese bloqueo se levantó: lo decide el juez."
        if u.get("rechazo_previo"):
            # C22: lo que un juez rechazó nunca entra solo por el seguimiento.
            return (f"este servidor ya fue rechazado en el minuto {_min_txt(u['rechazo_previo'].get('min'))}; queda "
                    "para decidir en persona.")
        rechazada = self._rechazada_que_cruza(exp, u)
        if rechazada is not None:
            # f-turnos-1: lo que un juez rechazó no se bloquea solo aunque vuelva con otro nombre o en otra IP.
            return (f"un servidor con esta misma IP o este mismo nombre ya fue rechazado en el minuto "
                    f"{_min_txt((rechazada.get('decision') or {}).get('min'))}; queda para decidir en persona.")
        vetado = self._veto_del_host(u)
        if vetado:
            # C14: un nombre levantado (por reclamo o por el juez) que la plataforma ahora VE transmitiendo vuelve
            # al juez como pedido en persona; nunca se amplía solo.
            return vetado
        if not self.dinamica_habilitada:
            return "la plataforma corre con el seguimiento deshabilitado."
        if fin:
            return "el partido terminó."
        if not u.get("continuidad"):
            return "es el primer servidor de esta filtración: lo decide el juez."
        if not din:
            firmadas = [x for x in exp["ubicaciones"] if x["n"] < u["n"] and x["estado"] == "aprobada"]
            if firmadas:
                return "el servidor anterior se firmó “solo este servidor”, sin seguimiento."
            return "ningún servidor anterior de esta filtración se firmó con seguimiento."
        if not din.get("activa") or din.get("revocada"):
            rev = din.get("revocada") or {}
            return f"el seguimiento de esta filtración se frenó en el minuto {_min_txt(rev.get('min'))}."
        if din.get("requiere_ratificacion"):
            return "el seguimiento espera que el juez entrante lo ratifique."
        if u["continuidad"].get("criterio") != "misma_marca":
            return "esta ubicación lleva otra marca de agua: la decide el juez."
        if (u["senal"].get("marca") or "") not in din.get("marcas", []):
            return "la marca de agua de este servidor no está alcanzada por el seguimiento: la decide el juez."
        if not u["colateral"].get("limpia"):
            return self._motivo_no_limpia(u)
        if not self.seguimiento_autorizado(din["respaldada_por"]):
            if din["respaldada_por"] == u.get("asignada_a"):
                return "su orden marco no autoriza el seguimiento."
            return f"la orden marco de {self.nombre_juez(din['respaldada_por'])} no autoriza el seguimiento."
        if not self.usuarios.activo(din["respaldada_por"], PRESENCIA_S):
            juez = din["respaldada_por"]
            arranque = getattr(self, "_t_arranque", None)
            if self.usuarios.hace_s(juez) is None and arranque is not None \
                    and time.monotonic() - arranque < PRESENCIA_S:
                # robustez-2: tras un arranque las sesiones se pierden; no es ausencia (no se marca «definitivo»).
                return (f"la plataforma acaba de arrancar: se espera hasta {int(PRESENCIA_S)} s a que "
                        f"{self.nombre_juez(juez)} vuelva a entrar.")
            return self._texto_ausente(juez)
        return None

    @staticmethod
    def _motivo_no_limpia(u: dict) -> str:
        cap = u.get("captura") or {}
        col = u.get("colateral") or {}
        if not cap.get("valida"):
            return "la captura de este servidor no es válida o está repetida: la decide el juez."
        if col.get("recomendacion") == "ninguna":
            # C15: la causa es que no hay un nombre que bloquear sin tocar la IP, no un «riesgo» abstracto.
            return ("el stream sale directo de una IP, sin nombre, y no se puede asegurar que esa IP sea solo del "
                    "pirata: la decide el juez.")
        return "no se pudo comprobar del todo que el servidor sea el de la detección: la decide el juez."

    def _texto_ausente(self, juez: str) -> str:
        hace = self.usuarios.hace_s(juez)
        cuanto = f"sin actividad hace {int(hace)} s" if hace is not None else "sin actividad desde que arrancó la plataforma"
        return f"{self.nombre_juez(juez)} no tenía la plataforma abierta ({cuanto}): queda para firmar en persona."

    def _es_ausencia(self, exp: dict, motivo: Optional[str]) -> bool:
        din = exp.get("dinamica") or {}
        return bool(motivo) and bool(din.get("respaldada_por")) and \
            motivo.startswith(f"{self.nombre_juez(din['respaldada_por'])} no tenía la plataforma abierta")

    def _paso_dinamicas(self) -> None:
        candidatos = []
        with self.candado:
            fin = self.ahora() >= self.fin_min() - self.margen_envio()
            for exp in self.e["expedientes"]:
                for u in exp["ubicaciones"]:
                    if u["estado"] != "pendiente":
                        continue
                    motivo = self._motivo_no_ampliar(exp, u, fin)
                    if motivo is not None:
                        if u["automatica"].get("motivo") != motivo:
                            u["automatica"] = {"posible": False, "motivo": motivo}
                            if self._es_ausencia(exp, motivo):
                                u["automatica"]["definitivo"] = True
                            self._marcar()
                        continue
                    candidatos.append((exp["id"], u["n"], exp["dinamica"]["respaldada_por"]))
        if not candidatos:
            return
        cache: Dict[str, Tuple[bool, Optional[str], Optional[dict]]] = {}
        for _, _, juez in candidatos:
            if juez not in cache:
                cache[juez] = self.puede_firmar(juez)
        with self.candado:
            for exp_id, n, juez in candidatos:
                exp, u = self.ubicacion(exp_id, n)
                ok, motivo, _ = cache[juez]
                if u["estado"] != "pendiente":
                    continue
                if self._motivo_no_ampliar(exp, u, False) is not None:
                    continue
                if not ok:
                    motivo_txt = f"{self.nombre_juez(juez)} no puede firmar ahora: {motivo}"
                    motivo_txt = motivo_txt if motivo_txt.endswith(".") else motivo_txt + "."
                    if u["automatica"].get("motivo") != motivo_txt:
                        u["automatica"] = {"posible": False, "motivo": motivo_txt}
                        self._marcar()
                    continue
                self._ampliar(exp, u, juez)
        self.despacho.despertar()

    def _habilitante(self, din: dict) -> dict:
        """La entrada que respalda la orden dinámica hoy: la ratificación más reciente o la firma original."""
        if din.get("ratificaciones"):
            r = din["ratificaciones"][-1]
            return {"juez_id": r["juez_id"], "nombre": r.get("nombre") or self.nombre_juez(r["juez_id"]),
                    "entrada": r["entrada"], "min": r["min"], "por": "ratificacion"}
        o = din.get("otorgada_por") or {}
        return {"juez_id": o.get("juez_id") or din.get("respaldada_por"),
                "nombre": o.get("nombre") or self.nombre_juez(din.get("respaldada_por")),
                "entrada": din["entrada"], "min": din.get("otorgada_min"), "por": "firma"}

    def _otorgada_ratificada(self, din: dict) -> Tuple[dict, Optional[dict]]:
        o = din.get("otorgada_por") or {}
        otorgada = {"juez_id": o.get("juez_id") or din.get("respaldada_por"),
                    "nombre": o.get("nombre") or self.nombre_juez(din.get("respaldada_por")),
                    "min": din.get("otorgada_min"), "entrada": din.get("entrada")}
        ratificada = None
        if din.get("ratificaciones"):
            r = din["ratificaciones"][-1]
            ratificada = {"juez_id": r["juez_id"], "nombre": r.get("nombre") or self.nombre_juez(r["juez_id"]),
                          "min": r.get("min"), "entrada": r.get("entrada")}
        return otorgada, ratificada

    @staticmethod
    def texto_ampliacion(otorgada: dict, ratificada: Optional[dict], om: Optional[dict] = None) -> str:
        """La leyenda de la ampliación: una sola fuente, `marco.texto_ampliacion` (ronda 3, C7). `om` es la orden
        marco del juez con cuya clave salió la ampliación (la de `decision.orden_marco`)."""
        return marco_mod.texto_ampliacion(om, otorgada, ratificada)

    @staticmethod
    def texto_bajo_orden(b: dict) -> str:
        m = _min_txt(b.get("min"))
        return (f"Ampliación automática bajo el seguimiento otorgado por {b['nombre']} en el minuto {m} "
                f"(entrada {b['entrada']})")

    def _ampliar(self, exp: dict, u: dict, juez: str) -> None:
        """La ampliación la hace el sistema, bajo la orden dinámica del juez: no es una firma en persona."""
        din = exp["dinamica"]
        hab = self._habilitante(din)
        firma = self.usuarios.firmar_con(juez, sello.firma_ampliacion, exp["id"], u["n"], u["huella"], juez,
                                         hab["entrada"])
        entrada = self.auditar("ampliacion_dinamica", "sistema", exp=exp["id"], datos={
            "ubicacion": u["n"], "huella": u["huella"], "aprobar": True, "alcance": "filtracion",
            "bajo_orden_dinamica_de": juez, "entrada_habilitante": hab["entrada"],
            "entrada_decision": din["entrada"], "firma_ampliacion": firma, "marca": u["senal"].get("marca"),
            "tipo": u["propuesta"]["tipo"], "orden_marco": self._ref_marco(juez)})
        self._aprobar_interno(exp, u, juez, entrada, "ampliacion_dinamica", "filtracion", None, None)
        otorgada, ratificada = self._otorgada_ratificada(din)
        # Las pantallas leen quién la otorgó y quién la ratificó desde bajo_orden_de (contrato de interfaz 2b).
        bajo = {"juez_id": juez, "nombre": self.nombre_juez(juez), "entrada": hab["entrada"], "min": hab["min"],
                "otorgada_por": otorgada, "ratificada_por": ratificada}
        u["decision"]["bajo_orden_de"] = bajo
        u["decision"]["otorgada_por"] = otorgada
        u["decision"]["ratificada_por"] = ratificada
        om = self.marco_vigente(juez)  # la que cita la auditoría: la del juez con cuya clave sale la ampliación
        u["decision"]["orden_marco"] = {"id": om["id"], "entrada": om["entrada"], "huella": om["huella"]} if om else None
        # C7 (N10): la leyenda cita esa misma OM (no la de quien otorgó) y, si hubo traspaso, la ratificación con la
        # que el juez entrante respalda el seguimiento.
        rat_txt = {"nombre": hab["nombre"], "min": hab["min"]} if hab.get("por") == "ratificacion" else None
        u["decision"]["texto"] = marco_mod.texto_ampliacion(
            {"id": om["id"], "nombre": om.get("nombre"), "min": om.get("min")} if om else None,
            {"nombre": otorgada.get("nombre"), "min": otorgada.get("min")}, rat_txt)
        u["automatica"] = {"posible": True, "motivo": None}
        a = self.aviso("ampliacion_dinamica",
                       f"La filtración de {exp['titulo']} se mudó a {u['host']} ({u['ip']}). Se bloqueó sola bajo el "
                       "seguimiento que usted autorizó; puede frenarlo.", exp=exp["id"], para=juez)
        a["ubicacion"] = u["n"]
        self._marcar()

    # --- decisiones ------------------------------------------------------------------------

    def _aprobar_interno(self, exp: dict, u: dict, juez: str, entrada: dict, tipo_decision: str, alcance: str,
                         forzar: Optional[str], fundamento: Optional[str]) -> None:
        """Con el candado tomado: registra la decisión y crea las órdenes (por_enviar)."""
        propuesta = u["propuesta"]
        if forzar and forzar != propuesta["tipo"]:
            analisis = {"servidor": u["sellado"]["servidor"], "colateral": u["colateral"]}
            propuesta = evidencia.proponer(analisis, self.e["proveedores"], self.fin_min(), forzar, fundamento)
        s = sello.calcular_sello(u["huella"], entrada["hash"])
        ya_cubiertos = []
        info = self.e["jueces"].get(juez) or {}
        for pid, objetivos in propuesta["objetivos_por_proveedor"].items():
            for obj in objetivos:
                existente = self.objetivo_activo(pid, obj["tipo"], obj["objetivo"])
                if existente or (obj["tipo"], obj["objetivo"]) in [tuple(x) for x in self.e["vetados"]]:
                    ya_cubiertos.append({"proveedor": pid, "tipo": obj["tipo"], "objetivo": obj["objetivo"],
                                         "orden_id": existente})
                    continue
                self.crear_orden(exp, u, pid, obj["tipo"], obj["objetivo"], juez, s, entrada["n"], "decision",
                                 prefijo="amp" if tipo_decision == "ampliacion_dinamica" else "ord")
        u["estado"] = "aprobada"
        u["decision"] = {
            "tipo": "firma" if tipo_decision == "decision_juez" else "ampliacion_dinamica",
            "aprobada": True, "juez_id": juez, "juez": info.get("nombre"), "juzgado_id": info.get("juzgado_id"),
            "juzgado": info.get("juzgado"), "min": entrada["min"], "utc": entrada["utc"], "alcance": alcance,
            "forzado": {"tipo": forzar, "fundamento": fundamento} if forzar and forzar != u["propuesta"]["tipo"]
            else None,
            "motivo_rechazo": None, "sello": s, "entrada": entrada["n"], "ya_cubiertos": ya_cubiertos,
            "propuesta_aplicada": propuesta, "bajo_orden_de": None,
            "texto": f"Firmada por {info.get('nombre') or juez} en el minuto "
                     f"{_min_txt(entrada['min'])} (entrada {entrada['n']})"}
        self._estado_expediente(exp)

    def _aviso_corte_en_origen(self, exp: dict, senal: dict) -> None:
        """Con el candado: constancia de aviso al titular para que corte la sesión filtrada en su plataforma. Sale al
        armar el expediente con una marca válida de la señal oficial (una vez por sesión), no al firmar el juez."""
        sesion = senal.get("sesion")
        if senal.get("clase") != "pirata" or not sesion:
            return
        de_lic = {l.get("prefijo_marca") for l in self.e["partido"].get("licenciatarios") or []}
        if not senal.get("prefijo") or senal.get("prefijo") in de_lic:
            return  # marca de un licenciatario fuera de sus dominios: el aviso va por otro camino
        if sesion in self.e["cortes_avisados"]:
            return
        self.e["cortes_avisados"].append(sesion)
        texto = (f"Constancia de aviso al titular ({self.e['partido'].get('titular_derechos')}): la sesión {sesion} "
                 "de su plataforma es la que se está filtrando; cortarla le corresponde al titular. La plataforma no "
                 "corta nada: deja constancia del aviso. (Simulado: el simulador no tiene esa API.)")
        ent = self.auditar("aviso_corte_en_origen", "sistema", exp=exp["id"], datos={
            "sesion": sesion, "texto": texto, "simulado": True})
        if exp.get("corte_en_origen") is None:
            exp["corte_en_origen"] = {"min": ent["min"], "sesion": sesion, "texto": texto}

    def _estado_expediente(self, exp: dict) -> None:
        estados = [u["estado"] for u in exp["ubicaciones"]]
        if "pendiente" in estados:
            exp["estado"] = "pendiente"
        elif "aprobada" in estados:
            exp["estado"] = "activo"
            if self.e["hitos"].get("cierre"):
                exp["estado"] = "cerrado"
        elif "sin_decidir" in estados:
            exp["estado"] = "cerrado"  # terminó el partido con un pedido sin firmar: cerrado, sin órdenes
        else:
            exp["estado"] = "rechazado"

    def crear_orden(self, exp: dict, u: dict, pid: str, tipo: str, objetivo: str, juez: str, s: str,
                    entrada_n: int, origen: str, reemplaza: Optional[str] = None, intento: int = 1,
                    reclamo: Optional[str] = None, prefijo: str = "ord") -> dict:
        k = int(u["contadores"].get(pid, 0)) + 1
        u["contadores"][pid] = k
        oid = sello.orden_id(exp["num"], u["n"], pid, k, s, prefijo=prefijo)
        info = self.e["jueces"].get(juez) or {}
        o = {"orden_id": oid, "proveedor": pid, "tipo": tipo, "objetivo": objetivo,
             "vence_min": int(u["propuesta"]["vence_min"]), "juez_id": juez, "juzgado_id": info.get("juzgado_id"),
             "estado": "por_enviar", "intento": intento, "origen": origen, "reemplaza": reemplaza,
             "enviada_min": None, "recibida_min": None, "aplicada_min": None, "finalizada_min": None, "motivo": None,
             "exp": exp["id"], "n": u["n"], "k": k, "sello": s, "entrada_sello": entrada_n, "juez_decision": juez,
             "reclamo": reclamo, "incierta": False, "t_error": None, "levantar": None, "levantamiento": None,
             "creada_min": r3(self.ahora())}
        self.e["ordenes"][oid] = o
        return o

    @staticmethod
    def prefijo_de(oid: str) -> str:
        """Un reenvío conserva el prefijo de la orden que reemplaza: una ampliación sigue siendo una ampliación."""
        pre = str(oid).split("-", 1)[0]
        return pre if pre in sello.PREFIJOS_ORDEN else "ord"

    def _validar_juez_ubicacion(self, juez: str, exp_id: str, n: int, asignado: bool = True) -> Tuple[dict, dict]:
        exp, u = self.ubicacion(exp_id, n)
        if self.e["hitos"].get("fin"):
            raise ErrorAccion("partido_finalizado", "El partido terminó: ya no se firman órdenes.")
        if juez not in self.de_turno():
            raise ErrorAccion("fuera_de_turno", "No está de turno: no puede firmar.")
        if asignado:
            if u["estado"] != "pendiente":
                raise ErrorAccion("conflicto", "Esta ubicación ya fue decidida.")
            if u.get("asignada_a") != juez:
                raise ErrorAccion("sin_permiso", "Este pedido está asignado a otro juez.")
        return exp, u

    def aprobar(self, juez: str, exp_id: str, n: int, alcance: str, forzar_tipo: Optional[str],
                fundamento: Optional[str]) -> dict:
        if alcance not in ("ubicacion", "filtracion"):
            raise ErrorAccion("invalido", "El alcance debe ser 'ubicacion' o 'filtracion'.")
        if alcance == "filtracion" and not self.dinamica_habilitada:
            raise ErrorAccion("invalido", "El seguimiento está deshabilitado en esta plataforma.")
        if forzar_tipo not in (None, "", "ip", "dominio"):
            raise ErrorAccion("invalido", "forzar_tipo debe ser 'ip' o 'dominio'.")
        forzar_tipo = forzar_tipo or None
        with self.candado:
            exp, u = self._validar_juez_ubicacion(juez, exp_id, n)
            recomendado = u["propuesta"]["tipo"]
            if recomendado == "ninguna" and not forzar_tipo:
                raise ErrorAccion("invalido", "No hay un bloqueo recomendado: elija IP o dominio y fundamente.")
            if forzar_tipo and forzar_tipo != recomendado and len((fundamento or "").strip()) < 10:
                raise ErrorAccion("invalido", "Apartarse de la recomendación exige un fundamento de al menos "
                                              "10 caracteres.")
            if alcance == "filtracion" and not self.seguimiento_autorizado(juez):
                raise ErrorAccion("invalido", TEXTO_SIN_MARCO)
        ok, motivo, est = self.puede_firmar(juez)
        if not ok:
            raise ErrorAccion("fuera_de_turno", motivo or "No puede firmar ahora.")
        # Ola C (f-desconocido-1): pasado el corte de envío (fin − margen_envio, que no cambia) la firma queda pero el
        # despacho ya no manda la orden: el juez lo sabe en la respuesta.
        est = est or {}
        minuto_firma = float(est.get("minuto_actual", self.ahora()))
        tarde = minuto_firma >= self.fin_min() - self.margen_envio(est.get("acelerar"), self.latencia_para(est))
        with self.candado:
            exp, u = self._validar_juez_ubicacion(juez, exp_id, n)
            efectivo, aviso = alcance, None
            if alcance == "filtracion" and not (u["senal"].get("sesion") and (u["senal"].get("marca") or "").strip()):
                efectivo = "ubicacion"
                aviso = ("La marca de agua de esta filtración no trae sesión: no se puede seguir a la filtración, así "
                         "que se firmó solo esta ubicación (alcance «ubicación»). Si se muda, llega un pedido nuevo.")
            firma = self.usuarios.firmar_con(juez, sello.firma_decision, exp["id"], n, u["huella"], True, efectivo,
                                             juez)
            datos = {"ubicacion": n, "huella": u["huella"], "aprobar": True, "alcance": efectivo,
                     "alcance_pedido": alcance, "juez_id": juez, "forzar_tipo": forzar_tipo, "fundamento": fundamento,
                     "firma_decision": firma, "orden_marco": self._ref_marco(juez)}
            # C4: firmar en persona el servidor reabierto vuelve a permitir los objetivos que vetó el freno.
            reabiertos = [x for x in (u.get("reabierta") or {}).get("vetados") or [] if x in self.e["vetados"]]
            # C14: firmar en persona el servidor que ahora se VIO transmitir desde un nombre vetado lo vuelve a bloquear.
            reabiertos += [x for x in self._vetos_del_host(u) if x not in reabiertos]
            if reabiertos:
                datos["levanta_vetos"] = reabiertos
                self.e["vetados"] = [x for x in self.e["vetados"] if x not in reabiertos]
            entrada = self.auditar("decision_juez", "juez:" + juez, exp=exp["id"], datos=datos)
            self._aprobar_interno(exp, u, juez, entrada, "decision_juez", efectivo, forzar_tipo, fundamento)
            if efectivo == "filtracion":
                self._otorgar_dinamica(exp, u, juez, entrada)
            if aviso:
                u["decision"]["aviso_alcance"] = aviso
            if tarde:
                aviso = ((aviso + " ") if aviso else "") + TEXTO_FIRMA_TARDE
            self._marcar()
            self.guardar()
        self.despacho.despertar()
        return {"alcance_pedido": alcance, "alcance_efectivo": efectivo, "aviso": aviso}

    def _otorgar_dinamica(self, exp: dict, u: dict, juez: str, entrada: dict) -> None:
        din = exp.get("dinamica")
        marca = (u["senal"].get("marca") or "").strip() if u["senal"].get("sesion") else ""
        if not marca:
            return  # sin marca con sesión no hay filtración que seguir
        if din and din.get("activa") and not din.get("revocada"):
            nueva = marca not in din["marcas"]
            if nueva:
                din["marcas"].append(marca)
            # textos-3 / marco-4: «Firmar y seguir» sobre un seguimiento heredado sin ratificar lo ratifica (aprobar
            # ya exigió turno y orden marco con seguimiento); antes lo dejaba esperando en silencio.
            ratifica = bool(din.get("requiere_ratificacion"))
            if ratifica:
                info = self.info_juez(juez)
                din["respaldada_por"] = juez
                din["requiere_ratificacion"] = False
                din["ratificaciones"].append({"juez_id": juez, "nombre": info["nombre"], "min": entrada["min"],
                                              "entrada": entrada["n"], "por": "firma_y_seguir"})
                if self.e["traspasos"]:
                    ult = self.e["traspasos"][-1]
                    ult["dinamicas_ratificadas"] = list(ult.get("dinamicas_ratificadas") or []) + [exp["id"]]
                    ult["dinamicas_sin_ratificar"] = [x for x in (ult.get("dinamicas_sin_ratificar") or [])
                                                      if x != exp["id"]]
                    # Ola C, NV4: queda dicho en el traspaso (la tarjeta y el acta lo muestran); el turno se sigue
                    # recibiendo con su propio acto.
                    ult.setdefault("ratificadas_al_firmar", []).append(
                        {"id": exp["id"], "min": entrada["min"], "juez_id": juez, "nombre": info["nombre"]})
            if nueva or ratifica:
                self.auditar("orden_dinamica_otorgada", "juez:" + juez, exp=exp["id"], datos={
                    "marcas": [marca], "entrada_decision": entrada["n"], "juez_id": juez, "agrega": True,
                    "ratifica": ratifica})
            return
        # Solo la marca de la ubicación que el juez firmó: las demás (rechazadas o de antes de una revocación)
        # quedan afuera.
        om = self.marco_vigente(juez)
        exp["dinamica"] = {"activa": True, "marcas": [marca],
                           "orden_marco": {k: om.get(k) for k in ("id", "entrada", "huella", "nombre", "min")}
                           if om else None,
                           "otorgada_por": self.info_juez(juez), "otorgada_min": entrada["min"],
                           "entrada": entrada["n"], "respaldada_por": juez, "requiere_ratificacion": False,
                           "ratificaciones": [], "revocada": None}
        self.auditar("orden_dinamica_otorgada", "juez:" + juez, exp=exp["id"], datos={
            "marcas": exp["dinamica"]["marcas"], "entrada_decision": entrada["n"], "juez_id": juez})

    def rechazar(self, juez: str, exp_id: str, n: int, motivo: str) -> None:
        if len((motivo or "").strip()) < MOTIVO_RECHAZO_MIN:
            raise ErrorAccion("invalido", f"El rechazo exige un motivo de al menos {MOTIVO_RECHAZO_MIN} caracteres.")
        with self.candado:
            self._validar_juez_ubicacion(juez, exp_id, n)
        ok, texto, _ = self.puede_firmar(juez)
        if not ok:
            raise ErrorAccion("fuera_de_turno", texto or "No puede firmar ahora.")
        with self.candado:
            exp, u = self._validar_juez_ubicacion(juez, exp_id, n)
            firma = self.usuarios.firmar_con(juez, sello.firma_decision, exp["id"], n, u["huella"], False,
                                             "ubicacion", juez)
            entrada = self.auditar("decision_juez", "juez:" + juez, exp=exp["id"], datos={
                "ubicacion": n, "huella": u["huella"], "aprobar": False, "alcance": "ubicacion", "juez_id": juez,
                "motivo_rechazo": motivo, "firma_decision": firma, "orden_marco": self._ref_marco(juez)})
            info = self.e["jueces"].get(juez) or {}
            u["estado"] = "rechazada"
            u["decision"] = {"tipo": "firma", "aprobada": False, "juez_id": juez, "juez": info.get("nombre"),
                             "juzgado_id": info.get("juzgado_id"), "juzgado": info.get("juzgado"),
                             "min": entrada["min"], "utc": entrada["utc"], "alcance": "ubicacion", "forzado": None,
                             "motivo_rechazo": motivo, "sello": sello.calcular_sello(u["huella"], entrada["hash"]),
                             "entrada": entrada["n"], "ya_cubiertos": []}
            self._estado_expediente(exp)
            self._marcar()
            self.guardar()

    def levantar_ubicacion(self, juez: str, exp_id: str, n: int, motivo: str) -> dict:
        """Devuelve {"aviso": texto} si algún bloqueo se mantuvo porque otra ubicación firmada lo necesita, o {}."""
        if len((motivo or "").strip()) < 3:
            raise ErrorAccion("invalido", "Levantar exige un motivo.")
        with self.candado:
            self._validar_juez_ubicacion(juez, exp_id, n, asignado=False)
        ok, texto, _ = self.puede_firmar(juez)
        if not ok:
            raise ErrorAccion("fuera_de_turno", texto or "No puede firmar ahora.")
        with self.candado:
            exp, u = self.ubicacion(exp_id, n)
            mantenidas: List[str] = []
            if not self._levantar_ubicacion_interno(juez, exp, u, motivo, mantenidas=mantenidas):
                if mantenidas:
                    raise ErrorAccion("conflicto", " ".join(mantenidas))
                raise ErrorAccion("conflicto", "Esta ubicación no tiene bloqueos activos.")
            self._marcar()
            self.guardar()
        self.despacho.despertar()
        return {"aviso": " ".join(mantenidas)} if mantenidas else {}

    def _dependientes(self, o: dict, excluir: set) -> List[Tuple[dict, dict]]:
        """turnos-2: ubicaciones aprobadas (fuera de `excluir`) sin orden propia para el objetivo de `o` porque ya
        estaba cubierto (`ya_cubiertos`). Si `o` se levanta, esas ubicaciones quedan sin bloqueo."""
        mismo = lambda y: self._cubre(y, o)  # noqa: E731
        res = []
        for exp in self.e["expedientes"]:
            for v in exp["ubicaciones"]:
                if v["estado"] != "aprobada" or (exp["id"], v["n"]) in excluir or v.get("levantada_por_freno"):
                    continue
                if any(mismo(y) for y in (v.get("decision") or {}).get("ya_cubiertos") or []):
                    res.append((exp, v))
        return res

    @staticmethod
    def _cubre(y: dict, o: dict) -> bool:
        """Una entrada de `ya_cubiertos` habla del mismo (proveedor, tipo, objetivo) que la orden `o`."""
        if y.get("proveedor") != o["proveedor"] or y.get("tipo") != o["tipo"]:
            return False
        if o["tipo"] == "ip":
            return y.get("objetivo") == o["objetivo"]
        return dominios.normalizar(y.get("objetivo") or "") == dominios.normalizar(o["objetivo"])

    def _texto_mantenido(self, o: dict, dep: List[Tuple[dict, dict]]) -> str:
        quienes = "; ".join(
            f"la ubicación {v['n']} de {exp['id']}, firmada por "
            f"{(v.get('decision') or {}).get('juez') or self.nombre_juez((v.get('decision') or {}).get('juez_id')) or 'el juez'}"
            for exp, v in dep)
        nombre = self.proveedor(o["proveedor"]).get("nombre") or o["proveedor"]
        return f"Se mantiene el bloqueo de {o['objetivo']} en {nombre} porque también cubre {quienes}."

    def _levantar_ubicacion_interno(self, juez: str, exp: dict, u: dict, motivo: str,
                                    excluir: Optional[set] = None, mantenidas: Optional[List[str]] = None) -> int:
        """Con el candado: decide levantar los bloqueos activos de la ubicación (los firma el despacho). turnos-2:
        no levanta (ni veta) un objetivo del que depende otra ubicación aprobada que no se está levantando."""
        excluir = set(excluir or ()) | {(exp["id"], u["n"])}
        activas = []
        for o in self.e["ordenes"].values():
            if o["exp"] != exp["id"] or o["n"] != u["n"] or o["estado"] not in ACTIVAS or o.get("levantar"):
                continue
            dep = self._dependientes(o, excluir)
            if dep:
                if mantenidas is not None:
                    mantenidas.append(self._texto_mantenido(o, dep))
                # Ola C, punto 4: el juez quiso levantarla; se levanta cuando la suelte la última que la necesita.
                o["levantar_al_liberar"] = {"juez_id": juez, "min": r3(self.ahora())}
                continue
            activas.append(o)
        # Ola C, punto 4: los bloqueos «prestados» a esta ubicación (sus `ya_cubiertos`) que el juez ya había querido
        # levantar y que se mantuvieron solo por ella: al levantarla, se levantan también, si nadie más los necesita.
        for y in (u.get("decision") or {}).get("ya_cubiertos") or []:
            for o in self.e["ordenes"].values():
                if (o.get("levantar_al_liberar") and o["estado"] in ACTIVAS and not o.get("levantar")
                        and o not in activas and self._cubre(y, o) and not self._dependientes(o, excluir)):
                    activas.append(o)
        if not activas:
            return 0
        entrada = self.auditar("decision_juez", "juez:" + juez, exp=exp["id"], datos={
            "accion": "levantar_ubicacion", "ubicacion": u["n"], "huella": u["huella"], "juez_id": juez,
            "motivo": motivo, "ordenes": [o["orden_id"] for o in activas], "orden_marco": self._ref_marco(juez)})
        for o in activas:
            o["levantar"] = {"juez_id": juez, "motivo": motivo, "reclamo": None, "entrada": entrada["n"]}
            self._vetar(o["tipo"], o["objetivo"])
        return len(activas)

    def _recalcular_pendientes(self, refuta: str, rid: str) -> None:
        """Ola C (f-colateral-2): la refutación alcanza también a los pedidos que esperan firma, armados con la
        inferencia vieja. Se rehace el análisis con la misma evidencia sellada y los refutados de ahora; la tarjeta
        muestra la propuesta nueva y lo firmado es eso (la evidencia sellada y la huella no cambian)."""
        reg = dominios.normalizar(refuta)
        for exp in self.e["expedientes"]:
            for u in exp["ubicaciones"]:
                if u["estado"] != "pendiente" or not any(
                        dominios.registrable(x) == reg for x in (u.get("colateral") or {}).get("inferidos") or []):
                    continue
                sel = u["sellado"]
                analisis = evidencia.analizar_servidor(
                    sel["deteccion"], (sel["dns_pasivo"].get("por_ip") or {}).get(u["ip"]),
                    (sel["dns_pasivo"].get("por_host") or {}).get(u["host"]), self.hosts_piratas(),
                    self.e.get("inferencias_refutadas") or [])
                colateral = dict(analisis["colateral"])
                colateral["limpia"] = evidencia.es_limpia(u["senal"], analisis["coherencia"], u["captura"], colateral)
                antes = u["propuesta"]["tipo"]
                u["colateral"] = colateral
                u["propuesta"] = evidencia.proponer(analisis, self.e["proveedores"], self.fin_min())
                u["recalculada"] = {"reclamo": rid, "registrable": refuta, "min": r3(self.ahora()),
                                    "tipo_antes": antes, "tipo": u["propuesta"]["tipo"]}

    def _vetar(self, tipo: str, objetivo: str) -> None:
        if [tipo, objetivo] not in self.e["vetados"]:
            self.e["vetados"].append([tipo, objetivo])

    def _dinamicas_heredadas(self) -> List[dict]:
        """Órdenes dinámicas activas que esperan la ratificación del juez entrante."""
        return [exp for exp in self.e["expedientes"]
                if exp.get("dinamica") and exp["dinamica"].get("activa") and not exp["dinamica"].get("revocada")
                and exp["dinamica"].get("requiere_ratificacion")]

    def ratificar(self, juez: str, dinamicas: Optional[List[str]] = None) -> dict:
        """Recibe el turno: siempre libera lo que quedó en espera del saliente (órdenes y levantamientos). De las
        órdenes dinámicas heredadas ratifica solo las de `dinamicas` (None = todas), y solo si el entrante tiene orden
        marco con seguimiento; si no, ratifica lo demás y devuelve un aviso. Las no ratificadas siguen esperando."""
        def validar() -> Tuple[Optional[dict], List[dict]]:
            tr = self.traspaso_pendiente(juez)
            heredadas = self._dinamicas_heredadas() if juez in self.de_turno() else []
            if tr is None and not heredadas:
                raise ErrorAccion("conflicto", "No hay nada heredado para ratificar.")
            if dinamicas is not None:
                ids = {x["id"] for x in heredadas}
                # Ola C, NV4: lo que ya se ratificó al «Firmar y seguir» se ignora en silencio (idempotente).
                ref = tr or (self.e["traspasos"][-1] if self.e["traspasos"] else {})
                ya = set(ref.get("dinamicas_ratificadas") or [])
                ajenas = [d for d in dinamicas if d not in ids and d not in ya]
                if ajenas:
                    raise ErrorAccion("invalido", f"{ajenas[0]} no tiene un seguimiento heredado para ratificar.")
            return tr, heredadas
        with self.candado:
            validar()
        ok, texto, _ = self.puede_firmar(juez)
        if not ok:
            raise ErrorAccion("fuera_de_turno", texto or "No puede firmar ahora.")
        with self.candado:
            tr, heredadas = validar()
            elegidas = [x for x in heredadas if dinamicas is None or x["id"] in dinamicas]
            aviso = None
            if elegidas and not self.seguimiento_autorizado(juez):
                aviso = ("Recibió el turno, pero los seguimientos heredados siguen esperando: para ratificarlos, firme "
                         "antes la orden marco con el seguimiento autorizado.")
                elegidas = []
            sin_ratificar = [x["id"] for x in heredadas if x not in elegidas]
            espera = [o for o in self.e["ordenes"].values() if o["estado"] == "espera_ratificacion"] if tr else []
            levs = self._levantamientos_pendientes()
            entrada = self.auditar("traspaso_ratificado", "juez:" + juez, datos={
                "traspaso_min": tr["min"] if tr else None, "juez_id": juez, "dinamicas": [x["id"] for x in elegidas],
                "dinamicas_sin_ratificar": sin_ratificar,
                "ordenes_en_espera": [o["orden_id"] for o in espera], "levantamientos_pendientes": levs,
                "orden_marco": self._ref_marco(juez)})
            info = self.info_juez(juez)
            if tr is not None:
                tr["ratificado"] = {"juez_id": juez, "nombre": info["nombre"], "min": entrada["min"],
                                    "entrada": entrada["n"]}
                tr["resumen"]["levantamientos_pendientes"] = levs
                previas = [x for x in (tr.get("dinamicas_ratificadas") or []) if x not in [y["id"] for y in elegidas]]
                tr["dinamicas_ratificadas"] = previas + [x["id"] for x in elegidas]  # textos-3: no pisa lo de «seguir»
                tr["dinamicas_sin_ratificar"] = sin_ratificar
                texto_rec = self.texto_recibio_turno(entrada["min"], len(elegidas), len(heredadas))
                for a in self.e["avisos"]:
                    if a.get("para") == juez and a.get("tipo") == "traspaso" and not a.get("atendido"):
                        a["texto"] = texto_rec
                        self.cerrar_aviso(a, texto_rec, entrada["min"])
                for o in self.e["ordenes"].values():
                    if o.get("levantar") and o["levantar"].get("en_espera"):
                        o["levantar"]["heredado_por"] = juez
                tr["requiere_ratificacion"] = False
                tr["resumen"]["ordenes_en_espera"] = len(espera)
                if juez not in self.e["ratificados"]:
                    self.e["ratificados"].append(juez)
                for o in espera:
                    o["estado"] = "por_enviar"
                    o["motivo"] = None
            elif self.e["traspasos"]:
                ult = self.e["traspasos"][-1]
                ult["dinamicas_ratificadas"] = list(ult.get("dinamicas_ratificadas") or []) + [x["id"] for x in elegidas]
                ult["dinamicas_sin_ratificar"] = sin_ratificar
            for exp in elegidas:
                din = exp["dinamica"]
                din["respaldada_por"] = juez
                din["requiere_ratificacion"] = False
                din["ratificaciones"].append({"juez_id": juez, "nombre": info["nombre"], "min": entrada["min"],
                                              "entrada": entrada["n"]})
            self._marcar()
            self.guardar()
        self.despacho.despertar()
        return {"ratificadas": [x["id"] for x in elegidas], "sin_ratificar": sin_ratificar, "aviso": aviso}

    @staticmethod
    def texto_recibio_turno(minuto: Any, ratificados: int, heredados: int) -> str:
        """Texto del aviso de traspaso ya atendido (ronda 3, C8)."""
        base = f"Recibió el turno en el minuto {_min_txt(minuto)}"
        if not heredados:
            return base + "."
        if not ratificados:
            return base + ": no ratificó ningún seguimiento heredado."
        if heredados == 1:
            return base + ": ratificó el seguimiento heredado."
        return base + f": ratificó {ratificados} de {heredados} seguimientos heredados."

    def traspaso_pendiente(self, juez: str) -> Optional[dict]:
        if not self.e["traspasos"]:
            return None
        tr = self.e["traspasos"][-1]
        if tr.get("ratificado") is None and juez in [x["juez_id"] for x in tr["a"]] and juez in self.de_turno():
            return tr
        return None

    def ampliadas_vigentes(self, exp: dict) -> List[dict]:
        """Ubicaciones del expediente que se ampliaron solas y todavía tienen algún bloqueo activo sin levantar."""
        return [u for u in exp["ubicaciones"] if (u.get("decision") or {}).get("tipo") == "ampliacion_dinamica"
                and any(o["estado"] in ACTIVAS and not o.get("levantar") for o in self.ordenes_de(exp["id"], u["n"]))]

    def _puede_frenar(self, exp: dict, levantar: bool) -> bool:
        """Frenar exige el seguimiento activo; levantar lo ampliado se puede también después de frenarlo
        (turnos-3), mientras quede alguna ampliación vigente."""
        din = exp.get("dinamica") or {}
        return bool(din.get("activa") or (levantar and din.get("revocada") and self.ampliadas_vigentes(exp)))

    def revocar_dinamica(self, juez: str, exp_id: str, motivo: Optional[str] = None, levantar: bool = False) -> dict:
        """Frena las próximas mudanzas. Con `levantar`, además levanta con la firma del juez los bloqueos de las
        ubicaciones que se ampliaron solas bajo esa orden (mismo camino que levantar_ubicacion)."""
        motivo = (motivo or "").strip()  # revocar no exige motivo: queda "" si no se da
        levantar = bool(levantar)
        with self.candado:
            exp = self.idx_exp.get(exp_id)
            if exp is None or not exp.get("dinamica") or not self._puede_frenar(exp, levantar):
                raise ErrorAccion("no_encontrado", "Ese expediente no tiene un seguimiento activo.")
            if juez not in self.de_turno():
                raise ErrorAccion("fuera_de_turno", "No está de turno.")
        ok, texto, _ = self.puede_firmar(juez)
        if not ok:
            raise ErrorAccion("fuera_de_turno", texto or "No puede firmar ahora.")
        with self.candado:
            exp = self.idx_exp[exp_id]
            din = exp["dinamica"]
            if not self._puede_frenar(exp, levantar):
                raise ErrorAccion("no_encontrado", "Ese expediente no tiene un seguimiento activo.")
            if din.get("activa"):
                entrada = self.auditar("dinamica_revocada", "juez:" + juez, exp=exp_id, datos={
                    "juez_id": juez, "motivo": motivo, "levantar": levantar})
                din["activa"] = False
                din["revocada"] = {"juez_id": juez, "nombre": self.nombre_juez(juez), "min": entrada["min"],
                                   "motivo": motivo, "entrada": entrada["n"], "levantar": levantar}
            else:
                # turnos-3: ya frenado; solo se levanta lo ampliado (cada levantamiento queda auditado aparte).
                entrada = {"min": r3(self.ahora()), "n": (din.get("revocada") or {}).get("entrada")}
            levantadas, mantenidas = [], []
            if levantar:
                texto_lev = "Se frenó el seguimiento" + (f": {motivo}" if motivo else ".")
                ampliadas = {(exp["id"], v["n"]) for v in exp["ubicaciones"]
                             if (v.get("decision") or {}).get("tipo") == "ampliacion_dinamica"}
                for u in self.ampliadas_vigentes(exp):
                    vetos_previos = [list(x) for x in self.e["vetados"]]
                    if not self._levantar_ubicacion_interno(juez, exp, u, texto_lev, excluir=ampliadas,
                                                            mantenidas=mantenidas):
                        continue  # turnos-2: todo lo de esta ubicación lo necesita otra firmada: se mantiene
                    levantadas.append(u["n"])
                    # C4: este servidor ya no queda bajo ninguna decisión; la próxima detección vuelve al juez.
                    u["levantada_por_freno"] = {
                        "min": entrada["min"], "juez_id": juez, "juez": self.nombre_juez(juez),
                        "entrada": entrada["n"], "ampliada_min": (u.get("decision") or {}).get("min"),
                        "vetados": [x for x in self.e["vetados"] if x not in vetos_previos]}
            for a in self.e["avisos"]:
                if a.get("tipo") == "ampliacion_dinamica" and a.get("exp") == exp_id and not a.get("atendido"):
                    quien = self._quien(juez, a.get("para"))
                    hizo = "frenó el seguimiento y levantó la ampliación" if (
                        levantar and (a.get("ubicacion") is None or a.get("ubicacion") in levantadas)) \
                        else "frenó el seguimiento"
                    self.cerrar_aviso(a, f"{quien} {hizo} en el minuto {_min_txt(entrada['min'])}.", entrada["min"])
            self._marcar()
            self.guardar()
        self.despacho.despertar()
        res: dict = {"levantadas": levantadas}
        if mantenidas:
            res["aviso"] = " ".join(mantenidas)
        return res

    # --- 5. seguimiento de órdenes y reintentos ---------------------------------------------

    def _aplicar_estado_sim(self, o: dict, s: dict) -> None:
        """Con el candado: lleva nuestra orden al estado que informa el simulador."""
        est = s.get("estado")
        if o["estado"] in ("por_enviar", "espera_ratificacion") and est:
            o["estado"] = "recibida"
            o["recibida_min"] = s.get("recibida_min")
            if o.get("enviada_min") is None:
                o["enviada_min"] = s.get("recibida_min")
            self.auditar("orden_recibida", "proveedor:" + o["proveedor"], exp=o["exp"], datos={
                "orden_id": o["orden_id"], "recibida_min": s.get("recibida_min"), "por": "reconciliacion"})
        if o.get("recibida_min") is None and s.get("recibida_min") is not None:
            o["recibida_min"] = s.get("recibida_min")
        if est in ("aplicada", "vencida") and o.get("aplicada_min") is None and s.get("aplicada_min") is not None:
            o["aplicada_min"] = s["aplicada_min"]
            if o["estado"] == "recibida":
                o["estado"] = "aplicada"
            self.auditar("orden_aplicada", "proveedor:" + o["proveedor"], exp=o["exp"], datos={
                "orden_id": o["orden_id"], "aplicada_min": s["aplicada_min"], "tipo": o["tipo"],
                "objetivo": o["objetivo"]})
            self._marcar()
        if est == "fallida" and o["estado"] != "fallida":
            o["estado"] = "fallida"
            o["motivo"] = s.get("motivo")
            o["finalizada_min"] = r3(self.ahora())
            self.auditar("orden_fallida", "proveedor:" + o["proveedor"], exp=o["exp"], datos={
                "orden_id": o["orden_id"], "motivo": s.get("motivo"), "intento": o["intento"]})
            # Las fallas de los proveedores y sus reintentos van a la sala, no a la bandeja del juez.
            self.aviso("orden_fallida", f"{self.proveedor(o['proveedor'])['nombre']} informó una falla al aplicar "
                       f"el bloqueo de {o['objetivo']} (intento {o['intento']}).", exp=o["exp"], para=None,
                       clave=f"fallida-{o['proveedor']}-{o['tipo']}-{o['objetivo']}")
            self._reintentar(o)
            self._marcar()
        if est == "vencida" and o["estado"] != "vencida":
            o["estado"] = "vencida"
            o["finalizada_min"] = s.get("finalizada_min")
            o["levantar"] = None
            self.auditar("orden_vencida", "proveedor:" + o["proveedor"], exp=o["exp"], datos={
                "orden_id": o["orden_id"], "finalizada_min": s.get("finalizada_min")})
            self._marcar()
        if est == "levantada" and o["estado"] != "levantada":
            self._registrar_levantamiento(o, s.get("finalizada_min"), por_consulta=True)

    def _adoptar(self, o: dict, datos: dict, motivo: str) -> None:
        """Con el candado: el proveedor ya tiene la orden (409, consulta o lista): se adopta su estado."""
        o["incierta"] = False
        o.pop("n_404", None)
        o["intentos_inciertos"] = 0
        o["t_confirmada"] = time.monotonic()
        self._aplicar_estado_sim(o, datos)
        self.auditar("orden_reconciliada", "sistema", exp=o.get("exp"), datos={
            "orden_id": o["orden_id"], "estado": datos.get("estado"), "motivo": motivo})
        self._marcar()

    def _ratificacion_de(self, juez: str) -> Optional[int]:
        for tr in reversed(self.e["traspasos"]):
            rat = tr.get("ratificado") or {}
            if rat.get("juez_id") == juez and rat.get("entrada") is not None:
                return rat["entrada"]
        return None

    def _registrar_levantamiento(self, o: dict, finalizada_min: Any, por_consulta: bool) -> None:
        """Con el candado. Invariante: una orden queda «levantada» si y solo si hay una entrada orden_levantada."""
        pedido = o.get("levantar") or {}
        enviado = pedido.get("enviado")
        if not enviado and o.get("lev_enviado"):
            # El pedido ya no está, pero sí salió un POST firmado: el levantamiento es ese (con su firma y su juez).
            previo = o["lev_enviado"]
            enviado = {"juez_id": previo["juez_id"], "firma": previo["firma"]}
            pedido = {"motivo": previo.get("motivo"), "reclamo": previo.get("reclamo"),
                      "entrada": previo.get("entrada"), "juez_id": previo.get("pedido_por")}
        datos: Dict[str, Any] = {"orden_id": o["orden_id"], "proveedor": o["proveedor"],
                                 "finalizada_min": finalizada_min}
        if enviado:
            juez = enviado["juez_id"]
            actor = "juez:" + juez
            datos.update({"juez_id": juez, "firma": enviado["firma"], "motivo": pedido.get("motivo"),
                          "reclamo": pedido.get("reclamo"), "entrada": pedido.get("entrada")})
            heredado = pedido.get("juez_id") if pedido.get("juez_id") and pedido.get("juez_id") != juez else None
            if heredado:
                datos["heredado_de"] = heredado
                datos["ratificacion"] = self._ratificacion_de(juez)
            o["levantamiento"] = {"min": finalizada_min, "juez_id": juez, "juez": self.nombre_juez(juez),
                                  "motivo": pedido.get("motivo"), "reclamo": pedido.get("reclamo"),
                                  "heredado_de": heredado}
        else:
            actor = "proveedor:" + o["proveedor"]
            datos["sin_pedido"] = True
            o["levantamiento"] = {"min": finalizada_min, "juez_id": None, "juez": None,
                                  "motivo": "El proveedor la informa levantada sin un pedido firmado de la plataforma.",
                                  "reclamo": None, "heredado_de": None}
            self.alerta(f"{self.proveedor(o['proveedor']).get('nombre')} informa levantada la orden {o['orden_id']} "
                        "sin que la plataforma lo haya pedido.", clave="lev-sin-pedido-" + o["orden_id"],
                        exp=o.get("exp"))
        if por_consulta:
            datos["confirmada_por_consulta"] = True
        self.auditar("orden_levantada", actor, exp=o.get("exp"), datos=datos)
        o["estado"] = "levantada"
        o["finalizada_min"] = finalizada_min
        o["levantar"] = None
        o.pop("lev_incierto", None)
        o["intentos_inciertos"] = 0
        self._marcar()

    def _detectar_perdidas(self, pid: str, vistas: set) -> None:
        """Con el candado. Una orden recibida o aplicada que ya no figura en la lista de su proveedor antes de
        vencer queda «perdida» y se vuelve a emitir (próximo k, mismo sello). Si el reloj retrocedió (o hay una
        lectura baja sin confirmar), es un reinicio del simulador y no se toca nada."""
        if self.reloj.retrocedio or self.reloj.sospechoso:
            return
        if self._t_lista.get(pid) is None:
            return  # sin el instante del pedido de la lista no se puede descartar una carrera: no se toca nada
        t_lista = float(self._t_lista[pid])
        ahora = self.ahora()
        for o in list(self.e["ordenes"].values()):
            if o["proveedor"] != pid or o["estado"] not in VIGENTES or o["orden_id"] in vistas:
                continue
            if o.get("en_vuelo") or o.get("incierta") or o.get("lev_incierto"):
                continue
            if instante(o.get("t_confirmada")) > t_lista - GRACIA_PERDIDA_S:
                continue  # confirmada casi a la vez que se pidió la lista: puede no figurar todavía
            if float(o.get("vence_min") or 0) <= ahora:
                continue
            o["estado"] = "perdida"
            o["finalizada_min"] = r3(ahora)
            o["motivo"] = "Desapareció de la lista del proveedor antes de vencer."
            self.auditar("orden_perdida", "sistema", exp=o["exp"], datos={"orden_id": o["orden_id"],
                                                                         "proveedor": pid})
            self.alerta(f"{self.proveedor(pid).get('nombre')} ya no lista la orden {o['orden_id']} ({o['tipo']} "
                        f"{o['objetivo']}) y no venció: se vuelve a emitir.", clave="perdida-" + o["orden_id"],
                        exp=o["exp"])
            if o.get("levantar"):
                o["levantar"] = None  # se estaba levantando: no se reemite (y el objetivo está vetado)
            else:
                self._reintentar(o, origen="reemision_perdida")
            self._marcar()

    def _reintentar(self, o: dict, origen: str = "reintento") -> None:
        if o.get("levantar") or [o["tipo"], o["objetivo"]] in self.e["vetados"]:
            return
        corte = self.fin_min() - self.margen_envio()
        if self.ahora() >= corte:
            return
        if self.objetivo_activo(o["proveedor"], o["tipo"], o["objetivo"]):
            return
        # C13: sin tope de intentos. Desde el 7.º, no antes de 1 minuto de partido después del envío anterior.
        intento = int(o["intento"]) + 1
        no_antes = None
        if intento > AVISO_INTENTOS:
            previo = o.get("enviada_min")
            if previo is None:
                previo = o.get("recibida_min")
            if previo is None:
                previo = self.ahora()
            no_antes = r3(float(previo) + ESPACIO_REINTENTO_MIN)
            if no_antes >= corte:
                return  # saldría pasado el corte: no se crea
        if int(o["intento"]) == AVISO_INTENTOS:
            nombre = self.proveedor(o["proveedor"]).get("nombre") or o["proveedor"]
            self.alerta(f"{nombre} falló {AVISO_INTENTOS} veces el bloqueo de {o['objetivo']}. La plataforma sigue "
                        "reintentando; conviene avisarle al proveedor.",
                        clave=f"seis-fallas-{o['proveedor']}-{o['tipo']}-{o['objetivo']}", exp=o["exp"])
        exp, u = self.ubicacion(o["exp"], o["n"])
        nueva = self.crear_orden(exp, u, o["proveedor"], o["tipo"], o["objetivo"], o["juez_id"], o["sello"],
                                 o["entrada_sello"], origen, reemplaza=o["orden_id"], intento=intento,
                                 reclamo=o.get("reclamo"), prefijo=self.prefijo_de(o["orden_id"]))
        nueva["juez_decision"] = o.get("juez_decision")
        if no_antes is not None:
            nueva["no_antes_min"] = no_antes
        datos_r = {"orden_id": nueva["orden_id"], "reemplaza": o["orden_id"], "intento": nueva["intento"],
                   "proveedor": o["proveedor"], "origen": origen}
        if no_antes is not None:
            datos_r["no_antes_min"] = no_antes
        self.auditar("orden_reintentada", "sistema", exp=o["exp"], datos=datos_r)
        self.aviso("reintento", f"Se reintenta el bloqueo de {o['objetivo']} en "
                   f"{self.proveedor(o['proveedor'])['nombre']} (intento {nueva['intento']}).", exp=o["exp"],
                   para=None, clave=f"reintento-{o['proveedor']}-{o['tipo']}-{o['objetivo']}")

    def _paso_seguimiento(self) -> None:
        """Proveedores con órdenes en tránsito (recibidas): en cada ciclo. Con solo aplicadas: cada 2 s reales."""
        ahora_t = time.monotonic()
        with self.candado:
            estados: Dict[str, set] = {}
            for o in self.e["ordenes"].values():
                if o["estado"] in VIGENTES and not o.get("en_vuelo"):
                    estados.setdefault(o["proveedor"], set()).add(o["estado"])
        pids = [pid for pid, est in sorted(estados.items())
                if "recibida" in est or ahora_t - self._t_seg.get(pid, NUNCA) >= self.intervalo_aplicadas_s]
        if not pids:
            return
        listas = self._listas_proveedores(pids)
        with self.candado:
            nuestras = self.e["ordenes"]
            for pid, lista in listas.items():
                if lista is None:
                    continue
                self._t_seg[pid] = time.monotonic()
                vistas = set()
                for s in lista:
                    if not isinstance(s, dict):
                        continue
                    vistas.add(s.get("orden_id"))
                    o = nuestras.get(s.get("orden_id"))
                    if o is None or o["proveedor"] != pid or o.get("en_vuelo"):
                        continue
                    if o["estado"] in VIGENTES:
                        self._aplicar_estado_sim(o, s)
                    elif o.get("incierta") and o["estado"] in ("por_enviar", "espera_ratificacion"):
                        self._adoptar(o, s, "seguimiento: el proveedor ya la lista")
                self._detectar_perdidas(pid, vistas)

    # --- 6. reclamos ---------------------------------------------------------------------------

    @staticmethod
    def _clave_reclamo(r: Any) -> str:
        rid = r.get("id") if isinstance(r, dict) else None
        if isinstance(rid, str) and rid.strip():
            return rid
        return "sin-id:" + sha256_hex(canonico(r))[:16]

    def _paso_reclamos(self) -> None:
        """GET /reclamos?desde=-1 una vez por segundo real; cada reclamo se valida y se procesa por separado."""
        if time.monotonic() - self._t_reclamos < self.intervalo_reclamos_s:
            return
        datos = self._red(self.cliente.reclamos)
        self._t_reclamos = time.monotonic()
        lista = datos.get("reclamos") if isinstance(datos, dict) else None
        lista = lista if isinstance(lista, list) else []
        malos_vistos = set(self.e.get("reclamos_invalidos") or [])
        nuevos: List[dict] = []
        invalidos: List[Tuple[Any, str, str]] = []
        for r in lista:
            clave = self._clave_reclamo(r)
            if clave in self.e["reclamos"] or clave in malos_vistos:
                continue
            motivo = evidencia.validar_reclamo(r)
            if motivo is not None:
                invalidos.append((r, motivo, clave))
                malos_vistos.add(clave)
                continue
            if any(x["id"] == r["id"] for x in nuevos):
                continue
            nuevos.append(r)
        if not nuevos and not invalidos:
            return
        for r in nuevos:
            self._dns_dominio(r["dominio"])
        with self.candado:
            for r, motivo, clave in invalidos:
                self._reclamo_invalido(r, motivo, clave)
            for r in sorted(nuevos, key=lambda x: (float(x["minuto"]), x["id"])):
                if r["id"] in self.e["reclamos"]:
                    continue
                try:
                    self._procesar_reclamo(r)
                except Exception as err:
                    self.log(f"Falló el procesamiento del reclamo {r['id']}:\n" + traceback.format_exc())
                    if r["id"] not in self.e["reclamos"]:
                        self._reclamo_invalido(r, f"falló el procesamiento: {type(err).__name__}: {err}", r["id"])
            self._marcar()

    def _reclamo_invalido(self, r: Any, motivo: str, clave: str) -> None:
        """Con el candado: el reclamo inválido queda visto, auditado y avisado en la sala."""
        lista = self.e.setdefault("reclamos_invalidos", [])
        if clave not in lista:
            lista.append(clave)
        linea = " ".join(str(motivo).split())[:300]
        rid = r.get("id") if isinstance(r, dict) and isinstance(r.get("id"), str) else None
        self.auditar("reclamo_invalido", "sistema", datos={"reclamo": rid, "clave": clave, "motivo": linea})
        self.alerta(f"Reclamo {rid or '(sin id)'} inválido, no se procesa: {linea}", clave="recl-invalido-" + clave)

    @staticmethod
    def _puede_estar_en_el_proveedor(o: dict) -> bool:
        """Vigente, o enviada/en camino/en duda: puede estar bloqueando aunque no la tengamos confirmada."""
        if o["estado"] in VIGENTES:
            return True
        return o["estado"] in ("por_enviar", "espera_ratificacion") and not o.get("no_enviada") and bool(
            o.get("en_vuelo") or o.get("incierta") or o.get("enviada_min") is not None)

    @staticmethod
    def _afecta(o: dict, dominio: str, ips: List[str]) -> bool:
        if o["tipo"] == "ip":
            return o["objetivo"] in ips
        return dominios.normalizar(o["objetivo"]) == dominios.normalizar(dominio)

    def _causantes(self, dominio: str, ips: List[str]) -> List[dict]:
        causantes = []
        for o in self.e["ordenes"].values():
            if not self._puede_estar_en_el_proveedor(o):
                continue
            if self._afecta(o, dominio, ips):
                causantes.append({"orden_id": o["orden_id"], "proveedor": o["proveedor"], "tipo": o["tipo"],
                                  "objetivo": o["objetivo"], "exp": o["exp"], "n": o["n"],
                                  "incierta": o["estado"] not in VIGENTES})
        return causantes

    def _procesar_reclamo(self, r: dict) -> None:
        dominio = dominios.normalizar(r.get("dominio"))
        dns = (self.e["dns"]["dominio"].get(dominio) or {}).get("resp")
        ips = [x.get("ip") for x in (dns or {}).get("ips") or [] if x.get("ip")]
        prov = self.proveedor(r.get("proveedor"))
        self.auditar("reclamo_recibido", "proveedor:" + str(r.get("proveedor")), datos={
            "reclamo": r["id"], "minuto": r.get("minuto"), "dominio": dominio, "proveedor": r.get("proveedor"),
            "mensaje": r.get("mensaje")})
        causantes = self._causantes(dominio, ips)
        lic = any(dominios.cubre(d, dominio) for l in self.e["partido"].get("licenciatarios") or []
                  for d in l.get("dominios_autorizados") or [])
        # C14: pirata es solo lo OBSERVADO; lo inferido (comparte servidor y registrable) el reclamo lo corrige.
        visto = self._donde_se_vio(dominio)
        inferido_por = None if visto else self._inferido_en(dominio, causantes)
        if not causantes:
            clase = "sin_bloqueo"
            explicacion = (f"Se verificó {dominio} contra el DNS pasivo ({', '.join(ips) or 'sin IP conocida'}) y "
                           "no hay ningún bloqueo activo que lo afecte: se cierra solo.")
        elif lic:
            clase = "licenciatario"
            explicacion = f"{dominio} es un dominio autorizado de un licenciatario: nunca debe quedar bloqueado."
        elif visto:
            clase = "operacion_pirata"
            explicacion = (f"Es el mismo nombre que la plataforma vio {visto[0]} el partido en el minuto "
                           f"{_min_txt(visto[1])}: el reclamo no es fundado.")
        elif inferido_por:
            clase = "legitimo"
            explicacion = (f"La plataforma lo había tomado como parte del sitio pirata porque comparte el servidor y "
                           f"el dominio {inferido_por}, pero nunca lo vio transmitir ni publicar el partido. El reclamo "
                           "corrige esa inferencia.")
        else:
            clase = "legitimo"
            explicacion = (f"{dominio} resuelve a {', '.join(ips)}, que está bloqueada por "
                           f"{_cant(len(causantes), 'orden', 'órdenes')}. Es un sitio ajeno al pirata: el reclamo es fundado.")
        propuesta = self._propuesta_reclamo(dominio, clase, causantes, inferido_por)
        reclamo = {"id": r["id"], "minuto": r.get("minuto"), "dominio": dominio, "proveedor": r.get("proveedor"),
                   "proveedor_nombre": prov.get("nombre"), "mensaje": r.get("mensaje"), "estado": "pendiente",
                   "asignado_a": self.primero_de_turno(),
                   "verificacion": {"ips": ips, "clase_reclamante": clase, "ordenes_causantes": causantes,
                                    "explicacion": explicacion,
                                    **({"inferido": True, "registrable": inferido_por}
                                       if inferido_por and clase == "legitimo" else {})},
                   "propuesta": propuesta, "resolucion": None, "recibido_min": r3(self.ahora())}
        self.e["reclamos"][r["id"]] = reclamo
        self.auditar("reclamo_verificado", "sistema", datos={
            "reclamo": r["id"], "clase": clase, "ips": ips, "causantes": [c["orden_id"] for c in causantes],
            "propuesta": propuesta["accion"]})
        if clase == "sin_bloqueo":
            self._cerrar_reclamo(reclamo, None)
        else:
            # Repetidos por la misma causa (el mismo conjunto de órdenes causantes) se agrupan en un solo aviso.
            a = self.aviso("reclamo", f"Reclamo de {dominio}: {explicacion}", para=reclamo["asignado_a"],
                           clave="reclamo:" + "|".join(sorted(c["orden_id"] for c in causantes)))
            a.setdefault("reclamos", [])
            if r["id"] not in a["reclamos"]:
                a["reclamos"].append(r["id"])

    def _cerrar_avisos_reclamo(self) -> None:
        """Con el candado: el aviso de un reclamo queda atendido cuando ninguno de sus reclamos sigue pendiente, con
        lo que pasó de verdad (ronda 3, C3)."""
        for a in self.e["avisos"]:
            if a.get("tipo") != "reclamo" or a.get("atendido") or not a.get("reclamos"):
                continue
            rs = [self.e["reclamos"].get(rid) for rid in a["reclamos"]]
            if any(r is None or r["estado"] == "pendiente" for r in rs):
                continue
            # La resolución de un juez manda sobre los cierres automáticos que arrastró.
            rs.sort(key=lambda r: (bool((r.get("resolucion") or {}).get("juez_id")),
                                   (r.get("resolucion") or {}).get("min") or 0))
            res = rs[-1].get("resolucion") or {}
            m = res.get("min")
            juez = res.get("juez_id")
            quien = "" if not juez or juez == a.get("para") else f"{self.nombre_juez(juez)} "
            accion = res.get("accion")
            if accion == "desestimar":
                hizo = "desestimó el reclamo"
            elif accion == "levantar_y_reemplazar" and res.get("ordenes_reemplazo"):
                hizo = "levantó el bloqueo y lo reemplazó por dominio"
            elif accion in ("levantar", "levantar_y_reemplazar"):
                hizo = "levantó el bloqueo"
            elif res.get("por_reclamo"):
                hizo = f"quedó resuelto junto con el reclamo {res['por_reclamo']}"
            else:
                hizo = "se cerró solo: ya no había bloqueos que lo afecten"
            self.cerrar_aviso(a, f"Resuelto en el minuto {_min_txt(m)}: {quien}{hizo}.", m)

    def _otros_inferidos(self, dominio: str, causantes: List[dict], registrable: str) -> List[dict]:
        """C14: un reclamo fundado de un inferido refuta la inferencia entera del registrable, en TODOS los servidores
        del pirata (Ola C, f-colateral-3): órdenes activas por nombre sobre los DEMÁS inferidos de ese registrable y,
        en las ubicaciones que tenían inferidos de ese registrable, sus órdenes por IP (que los arrastran).
        Ola C (f-colateral-1): lo que después se vio transmitir (o publicar) ya no es inferido: no se levanta ni se
        veta."""
        nombres, ubics = set(), set()
        for exp in self.e["expedientes"]:
            for u in exp["ubicaciones"]:
                for x in (u.get("colateral") or {}).get("inferidos") or []:
                    x = dominios.normalizar(x)
                    if x != dominio and dominios.registrable(x) == registrable and self._donde_se_vio(x) is None:
                        nombres.add(x)
                        ubics.add((exp["id"], u["n"]))
        ya = {c["orden_id"] for c in causantes}
        return [o for o in self.e["ordenes"].values()
                if ((o["tipo"] == "dominio" and dominios.normalizar(o["objetivo"]) in nombres)
                    or (o["tipo"] == "ip" and (o["exp"], o["n"]) in ubics))
                and o["estado"] in ACTIVAS and not o.get("levantar") and o["orden_id"] not in ya]

    def _propuesta_reclamo(self, dominio: str, clase: str, causantes: List[dict],
                           inferido_por: Optional[str] = None) -> dict:
        if clase == "operacion_pirata":
            return {"accion": "desestimar", "levantar": [], "reemplazo": [],
                    "explicacion": "El reclamante es parte de la operación pirata: se mantiene el bloqueo."}
        if clase == "sin_bloqueo":
            return {"accion": "cerrar", "levantar": [], "reemplazo": [], "explicacion": "No hay bloqueos que levantar."}
        levantar = [{"orden_id": c["orden_id"], "proveedor": c["proveedor"]} for c in causantes]
        otros = self._otros_inferidos(dominio, causantes, inferido_por) if inferido_por and clase == "legitimo" else []
        levantar += [{"orden_id": o["orden_id"], "proveedor": o["proveedor"]} for o in otros]
        reemplazo = self._reemplazos(causantes + [o for o in otros if o["tipo"] == "ip"], dominio)
        # Ola C (NV3 + f-colateral-1): cuántos son por IP y cuántos por nombre, en singular o plural de verdad.
        n_ip = sum(1 for c in causantes if c["tipo"] == "ip")
        n_nombre = len(causantes) - n_ip
        if n_ip:
            accion = "levantar_y_reemplazar"
            hosts = sorted({x["objetivo"] for x in reemplazo})
            cuales = _cant(n_ip, "bloqueo por IP", "bloqueos por IP") + (
                f" y {_cant(n_nombre, 'bloqueo por nombre', 'bloqueos por nombre')}" if n_nombre else "")
            alcanza = "alcanza" if n_ip + n_nombre == 1 else "alcanzan"
            explicacion = (f"Levantar {cuales} que {alcanza} a {dominio}"
                           + (f" y reemplazar{'lo' if n_ip == 1 else 'los'} por "
                              f"{'un bloqueo' if len(reemplazo) == 1 else 'bloqueos'} por dominio de "
                              f"{', '.join(hosts)}, que cortan el stream sin afectar a nadie más." if hosts else "."))
        else:
            accion = "levantar"
            explicacion = (f"Levantar {_cant(len(causantes), 'bloqueo por nombre', 'bloqueos por nombre')} "
                           f"contra {dominio}, sin reemplazo.")
        if any(o["tipo"] == "ip" for o in otros):
            explicacion += (f" También se levantan los bloqueos por IP de "
                            f"{evidencia.lista_corta(sorted({o['objetivo'] for o in otros if o['tipo'] == 'ip'}))}, "
                            f"otros servidores donde la plataforma había inferido sitios del mismo dominio "
                            f"{inferido_por}, y se reemplazan por bloqueos por dominio del stream.")
        if any(o["tipo"] == "dominio" for o in otros):
            nombres_otros = sorted({o["objetivo"] for o in otros if o["tipo"] == "dominio"})
            explicacion += (f" También se levantan los bloqueos por nombre de "
                            f"{evidencia.lista_corta(nombres_otros)}, que la plataforma "
                            f"había inferido del mismo dominio {inferido_por} y nunca vio transmitir: queda bloqueado "
                            "solo lo que se vio.")
        res = {"accion": accion, "levantar": levantar, "reemplazo": reemplazo, "explicacion": explicacion}
        if inferido_por and clase == "legitimo":
            res["refuta"] = inferido_por
        return res

    def _reemplazos(self, causantes: List[dict], dominio: str) -> List[dict]:
        reemplazo, vistos = [], set()
        for c in causantes:
            if c["tipo"] != "ip":
                continue
            _, u0 = self.ubicacion(c["exp"], c["n"])
            # Ola C (f-colateral-1): al levantar la IP se reemplaza el stream de CADA ubicación firmada en esa IP, no
            # solo la dueña de la orden.
            # Ola D (g-colateral-2): si el juez ya había pedido levantar esta orden («Frenar y levantar») y se mantuvo
            # solo por otras ubicaciones, su propio stream no se reemplaza: se reemplazan solo las que la sostenían.
            propia = [] if (self.e["ordenes"].get(c.get("orden_id")) or {}).get("levantar_al_liberar") \
                else [(c["exp"], c["n"], u0)]
            ubics = propia + [(e["id"], x["n"], x) for e in self.e["expedientes"]
                                                for x in e["ubicaciones"]
                                                if x["estado"] == "aprobada" and x["ip"] == u0["ip"] and x is not u0]
            for exp_id, n, u in ubics:
                host = u.get("host_stream") or u["host"]  # tal como lo escribe el simulador
                if dominios.es_ip(host) or dominios.normalizar(host) == dominios.normalizar(dominio):
                    continue
                for p in self.e["proveedores"]:
                    if "dominio" not in (p.get("capacidades") or []):
                        continue
                    clave = (p["id"], host)
                    if clave in vistos or self.objetivo_activo(p["id"], "dominio", host):
                        continue
                    vistos.add(clave)
                    reemplazo.append({"proveedor": p["id"], "tipo": "dominio", "objetivo": host,
                                      "exp": exp_id, "n": n})
        return reemplazo

    @staticmethod
    def fundamento_reclamo(r: dict, ordenes: List[dict]) -> str:
        """Fundamento por defecto de un levantamiento por reclamo: la explicación ya verificada (sección 7)."""
        ips = ", ".join(r.get("verificacion", {}).get("ips") or []) or "una IP sin dato"
        ids = [o["orden_id"] for o in ordenes] or [c["orden_id"] for c in
                                                  r.get("verificacion", {}).get("ordenes_causantes") or []]
        cual = f"la orden {ids[0]}" if len(ids) == 1 else ("las órdenes " + ", ".join(ids) if ids else "una orden")
        bloqueada = "bloqueada" if len(ips.split(", ")) == 1 else "bloqueadas"
        return f"{r.get('dominio')} resuelve a {ips}, {bloqueada} por {cual}; no es un sitio pirata"

    def _cerrar_reclamo(self, reclamo: dict, por: Optional[str]) -> None:
        reclamo["estado"] = "cerrado"
        reclamo["resolucion"] = {"accion": "cerrar", "juez_id": None, "juez": None, "min": r3(self.ahora()),
                                 "fundamento": "Sin bloqueos activos que lo afecten." if por is None
                                 else f"Quedó resuelto por el reclamo {por}.",
                                 "minutos_hasta_resolver": r3(self.ahora() - float(reclamo.get("minuto") or 0)),
                                 "por_reclamo": por}
        self.auditar("reclamo_resuelto", "sistema", datos={"reclamo": reclamo["id"], "accion": "cerrar",
                                                           "por_reclamo": por})

    def resolver_reclamo(self, juez: str, rid: str, accion: str, fundamento: Optional[str]) -> None:
        if accion not in ("levantar_y_reemplazar", "levantar", "desestimar"):
            raise ErrorAccion("invalido", "Acción inválida.")
        if accion == "desestimar" and len((fundamento or "").strip()) < 3:
            raise ErrorAccion("invalido", "Desestimar exige un fundamento.")

        def validar() -> dict:
            r = self.e["reclamos"].get(rid)
            if r is None:
                raise ErrorAccion("no_encontrado", "No existe ese reclamo.")
            if r["estado"] != "pendiente":
                raise ErrorAccion("conflicto", "Ese reclamo ya fue resuelto.")
            if juez not in self.de_turno():
                raise ErrorAccion("fuera_de_turno", "No está de turno.")
            return r

        with self.candado:
            validar()
        ok, texto, _ = self.puede_firmar(juez)
        if not ok:
            raise ErrorAccion("fuera_de_turno", texto or "No puede firmar ahora.")
        with self.candado:
            r = validar()
            causantes_vivos = self._causantes(r["dominio"], r["verificacion"]["ips"])
            # Ola C (f-colateral-1): lo que se vio transmitir entre la propuesta y la firma ya no se levanta.
            ids_vivos = {c["orden_id"] for c in causantes_vivos} | {
                x["orden_id"] for x in r["propuesta"]["levantar"]
                if not ((self.e["ordenes"].get(x["orden_id"]) or {}).get("tipo") == "dominio"
                        and self._donde_se_vio(dominios.normalizar(self.e["ordenes"][x["orden_id"]]["objetivo"])))}
            levantar_ordenes = []
            if accion != "desestimar":
                for o in self.e["ordenes"].values():
                    afecta = self._afecta(o, r["dominio"], r["verificacion"]["ips"])
                    if afecta and o["estado"] in ACTIVAS and not o.get("levantar"):
                        levantar_ordenes.append(o)
                    elif o["orden_id"] in ids_vivos and o["estado"] in ACTIVAS and not o.get("levantar"):
                        levantar_ordenes.append(o)
            reemplazo = self._reemplazos((causantes_vivos or r["verificacion"]["ordenes_causantes"])
                                         + [o for o in levantar_ordenes if o["tipo"] == "ip"
                                            and o["orden_id"] in ids_vivos], r["dominio"]) \
                if accion == "levantar_y_reemplazar" else []
            if accion != "desestimar" and not (fundamento or "").strip():
                # Ola D (g-colateral-1): «bloqueada por» nombra solo lo que alcanzaba al reclamante; lo inferido que
                # se levanta por refutar el dominio va aparte.
                cids = {c["orden_id"] for c in (causantes_vivos or r["verificacion"]["ordenes_causantes"])}
                propias = [o for o in levantar_ordenes if o["orden_id"] in cids]
                fundamento = self.fundamento_reclamo(r, propias)
                refuta = (r.get("propuesta") or {}).get("refuta")
                resto = [o for o in levantar_ordenes if o["orden_id"] not in cids]
                nombres = sum(1 for o in resto if o["tipo"] != "ip")
                ips = sorted({o["objetivo"] for o in resto if o["tipo"] == "ip"})
                if refuta and nombres:
                    fundamento += (f"; además se {'levanta' if nombres == 1 else 'levantan'} "
                                   f"{_cant(nombres, 'bloqueo', 'bloqueos')} sobre lo que la plataforma había inferido "
                                   f"del mismo dominio {refuta} y nunca vio transmitir")
                if refuta and ips:
                    fundamento += (f"; también se levanta el bloqueo por IP de {', '.join(ips)}, que alojaba nombres "
                                   f"de ese dominio" + ("; lo que la plataforma vio transmitir ahí queda bloqueado "
                                                        "por nombre" if accion == "levantar_y_reemplazar" else ""))
            entrada = self.auditar("reclamo_resuelto", "juez:" + juez, datos={
                "reclamo": rid, "accion": accion, "fundamento": fundamento, "juez_id": juez,
                "levantar": [o["orden_id"] for o in levantar_ordenes],
                "reemplazo": [{k: x[k] for k in ("proveedor", "tipo", "objetivo", "exp", "n")} for x in reemplazo]})
            for o in levantar_ordenes:
                o["levantar"] = {"juez_id": juez, "motivo": f"Reclamo {rid} de {r['dominio']}: "
                                 + (fundamento or r["propuesta"]["explicacion"]), "reclamo": rid,
                                 "entrada": entrada["n"]}
                self._vetar(o["tipo"], o["objetivo"])
            creadas = []
            for x in reemplazo:
                exp, u = self.ubicacion(x["exp"], x["n"])
                if self.objetivo_activo(x["proveedor"], "dominio", x["objetivo"]):
                    continue
                s = sello.calcular_sello(u["huella"], entrada["hash"])
                creadas.append(self.crear_orden(exp, u, x["proveedor"], "dominio", x["objetivo"], juez, s,
                                                entrada["n"], "reemplazo_reclamo", reclamo=rid)["orden_id"])
            refuta = (r.get("propuesta") or {}).get("refuta")
            if accion != "desestimar" and refuta:
                # C14: un reclamo fundado de un inferido refuta la inferencia entera de ese registrable.
                refutadas = self.e.setdefault("inferencias_refutadas", [])
                if refuta not in refutadas:
                    refutadas.append(refuta)
                    ubics = sorted({f"{c['exp']}/U{c['n']}" for c in r["verificacion"]["ordenes_causantes"]})
                    self.auditar("inferencia_refutada", "juez:" + juez, datos={
                        "registrable": refuta, "reclamo": rid, "ubicaciones": ubics})
                    self._recalcular_pendientes(refuta, rid)
            info = self.info_juez(juez)
            r["estado"] = "desestimado" if accion == "desestimar" else "resuelto"
            r["resolucion"] = {"accion": accion, "juez_id": juez, "juez": info["nombre"], "min": entrada["min"],
                               "fundamento": fundamento,
                               "minutos_hasta_resolver": r3(entrada["min"] - float(r.get("minuto") or 0)),
                               "por_reclamo": None, "ordenes_reemplazo": creadas, "entrada": entrada["n"]}
            if accion != "desestimar":
                for otro in self.e["reclamos"].values():
                    if otro["estado"] != "pendiente":
                        continue
                    vivos = [c for c in self._causantes(otro["dominio"], otro["verificacion"]["ips"])
                             if not self.e["ordenes"][c["orden_id"]].get("levantar")]
                    if not vivos:
                        self._cerrar_reclamo(otro, rid)
            self._cerrar_avisos_reclamo()
            self._marcar()
            self.guardar()
        self.despacho.despertar()

    # --- 7. fin del partido ----------------------------------------------------------------------

    def _aplicar_listas(self, listas: Dict[str, Optional[list]], cierre: bool = False) -> None:
        """Con el candado: lleva nuestras órdenes al estado de las listas de los proveedores. En el cierre, las
        órdenes en duda que el proveedor lista se adoptan y las que no lista quedan como no enviadas."""
        nuestras = self.e["ordenes"]
        for pid, lista in listas.items():
            if lista is None:
                continue
            vistas = set()
            for s in lista:
                if not isinstance(s, dict):
                    continue
                vistas.add(s.get("orden_id"))
                o = nuestras.get(s.get("orden_id"))
                if o is None or o["proveedor"] != pid:
                    continue
                if o["estado"] in VIGENTES:
                    self._aplicar_estado_sim(o, s)
                elif o.get("incierta") and o["estado"] in ("por_enviar", "espera_ratificacion"):
                    self._adoptar(o, s, "cierre: el proveedor la lista" if cierre else "el proveedor ya la lista")
            if cierre:
                for o in nuestras.values():
                    if o["proveedor"] == pid and o.get("incierta") and o["orden_id"] not in vistas and \
                            o["estado"] in ("por_enviar", "espera_ratificacion"):
                        o["incierta"] = False
                        o["no_enviada"] = True
                        o["motivo"] = "No salió: al cierre el proveedor no la tiene."
                        self.auditar("orden_reconciliada", "sistema", exp=o["exp"], datos={
                            "orden_id": o["orden_id"], "estado": "no_enviada",
                            "motivo": "cierre: el proveedor no la lista"})

    def _testigos_si_cambiaron(self, listas: Dict[str, list], hito: str) -> None:
        """Escribe los testigos (y su entrada) solo si el contenido cambió desde la última vez."""
        h = sha256_hex(canonico(listas))
        if self._huella_testigos == h:
            return
        self.guardar_testigos(listas)
        self._huella_testigos = h
        with self.candado:
            self.e["hitos"][hito] = r3(self.ahora())

    def _paso_fin(self) -> None:
        ahora = self.ahora()
        fin = self.fin_min()
        hit = self.e["hitos"]
        if ahora >= fin and not hit.get("fin"):
            with self.candado:
                hit["fin"] = r3(ahora)
                self.auditar("partido_finalizado", "sistema", datos={"fin_min": fin}, minuto=max(ahora, fin))
                for o in self.e["ordenes"].values():
                    # Las que están en duda NO: se siguen consultando y se concilian al cierre.
                    if o["estado"] in ("por_enviar", "espera_ratificacion") and not o.get("en_vuelo") \
                            and not o.get("incierta"):
                        o["no_enviada"] = True
                        o["motivo"] = "No salió: terminó el partido."
                self._marcar()
        if hit.get("fin"):
            with self.candado:
                self._pasar_a_sin_decidir()
        if hit.get("cierre"):
            self._cerrar_y_exportar(None)
            return
        if not hit.get("fin") or ahora < fin + 1:
            return
        cierre = ahora >= fin + 5
        if not cierre and time.monotonic() - self._t_fin_listas < self.intervalo_aplicadas_s:
            return
        pids = [p["id"] for p in self.e["proveedores"]]
        listas = self._listas_proveedores(pids)
        self._t_fin_listas = time.monotonic()
        completas = all(listas.get(pid) is not None for pid in pids)
        with self.candado:
            for pid, lista in listas.items():
                if lista is not None:
                    self._ultimas_listas[pid] = {"lista": lista, "min": r3(ahora)}
            self._aplicar_listas(listas)
        if completas:
            self._t_cierre_falla = None
            # Testigos desde fin+1: se refrescan en cada intento, si cambió lo que tiene cada proveedor.
            try:
                self._testigos_si_cambiaron(listas, "testigos_previos")
            except Exception:
                self.log("No se pudieron guardar los testigos tempranos:\n" + traceback.format_exc())
        elif self._t_cierre_falla is None:
            self._t_cierre_falla = time.monotonic()
        if not cierre:
            return
        sin_conexion = False
        if not completas:
            if time.monotonic() - (time.monotonic() if self._t_cierre_falla is None else self._t_cierre_falla) <= CIERRE_SIN_CONEXION_S:
                return
            # Más de 10 s sin poder consultar: se cierra con lo último que se obtuvo de cada proveedor.
            sin_conexion = True
            listas = {pid: (listas.get(pid) if listas.get(pid) is not None
                            else (self._ultimas_listas.get(pid) or {}).get("lista")) for pid in pids}
        with self.candado:
            self._aplicar_listas(listas, cierre=True)
            activas_ip = [{"proveedor": pid, "orden_id": s.get("orden_id"), "objetivo": s.get("objetivo")}
                          for pid, lista in listas.items() for s in lista or []
                          if isinstance(s, dict) and s.get("tipo") == "ip" and s.get("estado") == "aplicada"]
            datos = {"bloqueos_ip_activos": activas_ip, "ok": not activas_ip}
            if sin_conexion:
                datos["sin_conexion"] = True
                datos["listas_de_min"] = {pid: (self._ultimas_listas.get(pid) or {}).get("min") for pid in pids}
            self.auditar("vencimiento_verificado", "sistema", datos=datos)
            if activas_ip:
                self.alerta(f"Quedan {len(activas_ip)} bloqueos por IP activos después del partido.",
                            clave="ip-post")
            if sin_conexion:
                self.alerta("Cierre sin conexión con el simulador: se usó la última lista de cada proveedor y los "
                            "testigos tomados desde el minuto fin+1.", clave="cierre-sin-conexion")
            hit["cierre"] = r3(ahora)
            if sin_conexion:
                hit["cierre_sin_conexion"] = True
            for exp in self.e["expedientes"]:
                self._estado_expediente(exp)
            self._marcar()
            self.guardar()
        self._cerrar_y_exportar(None if sin_conexion else listas)

    def _pasar_a_sin_decidir(self) -> None:
        """Con el candado, desde el final: una ubicación pendiente ya no se puede firmar. Pasa a «sin_decidir»
        (terminal, sin ninguna orden), con el motivo y una entrada de auditoría por ubicación (adenda 3, B)."""
        fin = self.fin_min()
        hubo = False
        for exp in self.e["expedientes"]:
            for u in exp["ubicaciones"]:
                if u["estado"] != "pendiente":
                    continue
                primera = float(u.get("primera_deteccion_min") or 0)
                x = max(0.0, fin - primera)
                motivo = (f"El partido terminó a los {_min_txt(x)} min de la detección: ya no se pueden firmar "
                          "órdenes.")
                # Desde que el pedido existe (no desde la última notificación: un traspaso la renueva).
                armado = u.get("armado_min")
                if armado is not None and fin - float(armado) > 1.0:
                    motivo += f" El pedido estuvo esperando la firma {_min_txt(fin - float(armado))} min."
                u["estado"] = "sin_decidir"
                u["motivo_sin_decidir"] = motivo
                u["sin_decidir_min"] = r3(self.ahora())
                u["automatica"] = {"posible": False, "motivo": motivo}
                self.auditar("ubicacion_sin_decidir", "sistema", exp=exp["id"], datos={
                    "expediente": exp["id"], "ubicacion": u["n"], "motivo": "partido_terminado",
                    "primera_deteccion_min": u.get("primera_deteccion_min")})
                hubo = True
            if hubo:
                self._estado_expediente(exp)
        if hubo:
            self._marcar()

    def _cerrar_y_exportar(self, listas: Optional[Dict[str, list]]) -> None:
        """Testigos y exportación del cierre. Si algo falla se reintenta en los ciclos siguientes.

        Los testigos se reintentan hasta que salgan. Se exporta en cuanto hay testigos o, si el simulador no
        responde, después de 3 intentos fallidos (sin testigos); cuando lleguen, se vuelve a exportar.
        """
        hit = self.e["hitos"]
        if not hit.get("testigos") and hit.get("cierre_sin_conexion") and hit.get("testigos_previos"):
            with self.candado:
                hit["testigos"] = hit["testigos_previos"]  # los últimos que se pudieron tomar
        if not hit.get("testigos"):
            try:
                self.guardar_testigos(listas)
                with self.candado:
                    hit["testigos"] = r3(self.ahora())
            except Exception:
                with self.candado:
                    hit["testigos_fallos"] = int(hit.get("testigos_fallos") or 0) + 1
                self.log("No se pudieron guardar los testigos del cierre:\n" + traceback.format_exc())
                self.alerta("No se pudieron guardar los testigos de los proveedores: se reintenta.",
                            clave="error-testigos-cierre")
        hay_testigos = bool(hit.get("testigos"))
        if hit.get("exportado") and (hit.get("exportado_con_testigos") or not hay_testigos):
            return
        if not hay_testigos and int(hit.get("testigos_fallos") or 0) < 3:
            return
        self.exportar_entrega()
        with self.candado:
            hit["exportado"] = r3(self.ahora())
            hit["exportado_con_testigos"] = hay_testigos
            self._marcar()
            self.guardar()

    # --- testigos: lo que guardó cada proveedor ----------------------------------------------

    def pedir_testigos(self) -> None:
        """Pedido externo de refrescar los testigos en el próximo ciclo (lo usa `exportar`)."""
        try:
            (self.salida / ARCHIVO_PEDIR_TESTIGOS).touch()
        except OSError:
            self._pedido_testigos = True

    def _paso_pedido_testigos(self) -> None:
        """`exportar` deja el archivo <salida>/pedir-testigos: se consume, se consultan los proveedores y se anota."""
        ruta = self.salida / ARCHIVO_PEDIR_TESTIGOS
        pedido = getattr(self, "_pedido_testigos", False) or ruta.exists()
        if not pedido:
            return
        self._pedido_testigos = False
        try:
            ruta.unlink()
        except OSError:
            pass
        try:
            self.foto_testigos()
        except ErrorRed:
            self.log("No se pudieron refrescar los testigos: sin conexión con el simulador.")
            return
        if self.e["hitos"].get("exportado"):
            # C20: con el partido cerrado, el paquete de la plataforma se rearma con los testigos nuevos, así la
            # huella que muestra /transparencia es la del paquete que copia `exportar`.
            self.exportar_entrega()

    def foto_testigos(self) -> Optional[dict]:
        """Testigos coherentes con el estado y la auditoría: mientras dura la foto no sale ningún POST nuevo, se
        espera a que terminen los que están en camino, se consultan los proveedores y, en una sola pasada con el
        candado, se llevan las órdenes al estado de las listas, se escriben los testigos y se guarda estado.json."""
        with self.candado:
            self._foto = True
        try:
            limite = time.monotonic() + ESPERA_FOTO_S
            while time.monotonic() < limite:
                with self.candado:
                    if self._posts_en_curso <= 0:
                        break
                time.sleep(0.05)
            pids = [p["id"] for p in self.e["proveedores"]]
            listas = self._listas_proveedores(pids)
            if any(listas.get(pid) is None for pid in pids):
                raise ErrorRed("no se pudieron consultar todos los proveedores")
            with self.candado:
                self._aplicar_listas(listas)
                entrada = self.guardar_testigos(listas)
                self.guardar()
                return entrada
        finally:
            with self.candado:
                self._foto = False
            self.despacho.despertar()

    def guardar_testigos(self, listas: Optional[Dict[str, list]] = None) -> Optional[dict]:
        """Consulta GET /proveedores/<id>/ordenes de todos los proveedores y lo guarda con su sha256. La entrada
        `testigos_guardados` lleva `corte_auditoria`: el número de la última entrada anterior a la foto."""
        from .exportar import escribir_testigos
        if listas is None:
            listas = {}
            for p in self.e["proveedores"]:
                listas[p["id"]] = self._red(self.cliente.ordenes, p["id"])
        with self.candado:
            corte = self.auditoria.n
            entrada = escribir_testigos(self.salida, self.simulador_url, self.ahora(), listas,
                                        lambda tipo, datos: self.auditar(tipo, "sistema",
                                                                         datos=dict(datos, corte_auditoria=corte)))
            self._marcar()
            return entrada

    def exportar_entrega(self) -> Path:
        from .exportar import exportar, huella_paquete
        destino = self.salida / "entrega"
        with self.candado:
            self.auditar("exportacion", "sistema", datos={"destino": str(destino), "motivo": "cierre del partido"})
            self.guardar()
            exportar(self.salida, destino)
            self._marcar()
        h = huella_paquete(destino)
        with self.candado:
            self.e["hitos"]["paquete"] = {"huella": h, "exportado_min": r3(self.ahora())}
            self._marcar()
        self.log(f"Exportado a {destino}. Huella del paquete: {h}")
        return destino

    # ======================================================================================
    # Vistas para la API (llamar con el candado tomado)
    # ======================================================================================

    def vista_reloj(self) -> dict:
        m = self.ahora()
        fin = self.fin_min()
        partido = self.e["partido"]
        de_turno = []
        for j in self.de_turno():
            info = self.e["jueces"].get(j) or {}
            t = turnos.turno_de(j, self.e["turnos"], m) or {}
            de_turno.append({"juez_id": j, "nombre": info.get("nombre"), "juzgado_id": info.get("juzgado_id"),
                             "juzgado": info.get("juzgado"), "desde_min": t.get("desde_min"),
                             "hasta_min": t.get("hasta_min")})
        ini = partido.get("inicio_iso")
        return {"minuto": round(m, 2), "hora": hora_de_partido(ini, m), "fin_min": fin,
                "hora_inicio": hora_de_partido(ini, 0), "fin_hora": (hora_de_partido(ini, fin) or "")[:5] or None,
                "finalizado": m >= fin, "cerrado": m >= fin + 5, "acelerar": self.reloj.acelerar,
                "conexion": self.conexion,
                "partido": {"id": partido.get("id"), "nombre": partido.get("nombre"),
                            "titular": partido.get("titular_derechos")},
                "de_turno": de_turno}

    def vista_yo(self, usuario: dict) -> dict:
        juez_id = usuario.get("juez_id")
        info = self.e["jueces"].get(juez_id) or {} if juez_id else {}
        return {"usuario": usuario["usuario"], "rol": usuario["rol"],
                "nombre": info.get("nombre") or usuario.get("nombre") or usuario["usuario"],
                "juez_id": juez_id, "juzgado_id": info.get("juzgado_id") if juez_id else None,
                "juzgado": info.get("juzgado") if juez_id else None,
                "dinamica_habilitada": self.dinamica_habilitada, "v": self.v, "reloj": self.vista_reloj()}

    def vista_orden(self, o: dict) -> dict:
        p = self.proveedor(o["proveedor"])
        return {"orden_id": o["orden_id"], "proveedor": o["proveedor"], "proveedor_nombre": p.get("nombre"),
                "tipo": o["tipo"], "objetivo": o["objetivo"], "vence_min": o["vence_min"], "juez_id": o["juez_id"],
                "juzgado_id": o["juzgado_id"], "estado": o["estado"], "intento": o["intento"], "origen": o["origen"],
                "reemplaza": o["reemplaza"], "enviada_min": o["enviada_min"], "recibida_min": o["recibida_min"],
                "aplicada_min": o["aplicada_min"], "finalizada_min": o["finalizada_min"], "motivo": o["motivo"],
                "levantamiento": self._vista_levantamiento(o), "reclamo": o.get("reclamo"),
                # Ola C (f-desconocido-1): no salió por el corte de envío (el motivo lo dice); no es «por enviar».
                "no_enviada": bool(o.get("no_enviada"))}

    def _vista_levantamiento(self, o: dict) -> Optional[dict]:
        L = o.get("levantamiento")
        if not L:
            return None
        return {"min": L.get("min"), "juez": L.get("juez_id"), "juez_nombre": L.get("juez"),
                "motivo": L.get("motivo"), "reclamo": L.get("reclamo")}

    def ordenes_de(self, exp_id: str, n: int) -> List[dict]:
        return [o for o in self.e["ordenes"].values() if o["exp"] == exp_id and o["n"] == n]

    def cobertura(self, exp: dict, u: dict) -> dict:
        """Misma cuenta que el verificador oficial, sobre nuestras órdenes."""
        desde, hasta = evidencia.ventana(exp["ubicaciones"], u, self.ahora(), self.fin_min())
        return evidencia.cobertura(desde, hasta, u["ip"], u["host"], self.e["ordenes"].values(),
                                   self.e["proveedores"])

    def vista_ubicacion(self, exp: dict, u: dict) -> dict:
        claves = ("n", "ref", "estado", "host", "ip", "asn", "organizacion", "pagina", "stream_url",
                  "primera_deteccion_min", "ultima_deteccion_min", "detecciones", "detecciones_min", "continuidad",
                  "senal", "captura", "motivo_sin_decidir", "sin_decidir_min",
                  "coherencia", "colateral", "promocion", "propuesta", "huella", "armado_min", "armado_utc",
                  "asignada_a", "notificada_min", "vista_min", "decision")
        v = {k: u.get(k) for k in claves}
        if isinstance(v.get("propuesta"), dict):
            # C26: la hora de vencimiento la calcula el motor, igual que en la orden (la propuesta sellada no cambia).
            v["propuesta"] = dict(v["propuesta"], vence_hora=hora_de_partido(
                self.e["partido"].get("inicio_iso"), v["propuesta"].get("vence_min")))
        v["n_detecciones"] = len(u["detecciones"])
        # C4: marca del freno con levantamiento y, en la ubicación nueva, de dónde viene (con su nota).
        v["levantada_por_freno"] = {k: (u.get("levantada_por_freno") or {}).get(k) for k in ("min", "juez_id", "juez")} \
            if u.get("levantada_por_freno") else None
        v["reabierta_en"] = u.get("reabierta_en")
        r = u.get("reabierta")
        v["reabierta"] = {k: r.get(k) for k in ("de_ubicacion", "ampliada_min", "levantada_min", "juez_id", "juez")} \
            if r else None
        v["rechazo_previo"] = dict(u["rechazo_previo"]) if u.get("rechazo_previo") else None
        # Ola C (f-colateral-2): la propuesta se rehízo porque un reclamo refutó la inferencia de un registrable.
        v["recalculada"] = dict(u["recalculada"]) if u.get("recalculada") else None
        v["nota_continuidad"] = self.nota_reapertura(u)
        if v["continuidad"] and v["nota_continuidad"]:
            v["continuidad"] = {**v["continuidad"], "nota": v["nota_continuidad"]}
        v["ordenes"] = [self.vista_orden(o) for o in self.ordenes_de(exp["id"], u["n"])]
        v["cobertura"] = self.cobertura(exp, u)
        return v

    def vista_expediente(self, exp: dict) -> dict:
        claves = ("id", "num", "titulo", "sitio", "creado_min", "estado", "filtracion", "dinamica", "corte_en_origen")
        v = {k: exp.get(k) for k in claves}
        v["ubicaciones"] = [self.vista_ubicacion(exp, u) for u in exp["ubicaciones"]]
        return v

    def vista_reclamo(self, r: dict) -> dict:
        return {k: r.get(k) for k in ("id", "minuto", "dominio", "proveedor", "proveedor_nombre", "mensaje", "estado",
                                       "asignado_a", "verificacion", "propuesta", "resolucion")}

    def vista_traspaso(self, tr: dict) -> dict:
        v = {k: tr.get(k) for k in ("min", "de", "a", "requiere_ratificacion", "ratificado", "resumen",
                                     "dinamicas_ratificadas", "dinamicas_sin_ratificar")}
        v["ratificadas_al_firmar"] = list(tr.get("ratificadas_al_firmar") or [])
        if tr.get("ratificado") is None:
            v["resumen"] = dict(tr.get("resumen") or {}, **self._resumen_traspaso())
            # Ola D (NV7): en vivo, «dinamicas» lista solo lo HEREDADO (lo que espera ratificación, más lo ya
            # ratificado en este traspaso); un seguimiento que el entrante firmó él mismo no se ofrece para ratificar.
            # Lo guardado en tr["resumen"] y la auditoría no cambian.
            heredadas = {exp["id"] for exp in self._dinamicas_heredadas()}
            heredadas |= set(tr.get("dinamicas_ratificadas") or [])
            heredadas |= {x.get("id") for x in tr.get("ratificadas_al_firmar") or []}
            v["resumen"]["dinamicas"] = [d for d in v["resumen"].get("dinamicas") or [] if d.get("exp") in heredadas]
        return v

    def vista_turno(self, juez_id: str) -> dict:
        m = self.ahora()
        t = turnos.turno_de(juez_id, self.e["turnos"], m)
        de = juez_id in self.de_turno() and t is not None
        prox = turnos.proximo_turno(juez_id, self.e["turnos"], m)
        puede, motivo = False, None
        if de:
            est = {"minuto_actual": m, "acelerar": self.reloj.acelerar, "jueces_de_turno": self.de_turno(),
                   "finalizado": m >= self.fin_min()}
            puede, motivo = self.puede_firmar_con(juez_id, est)
        elif prox:
            motivo = f"Su turno empieza en el min {prox['desde_min']:g}."
        else:
            motivo = "Su turno terminó."
        return {"de_turno": de, "desde_min": t["desde_min"] if t else None, "hasta_min": t["hasta_min"] if t else None,
                "faltan_min": round(t["hasta_min"] - m, 1) if t else None, "puede_firmar": puede, "motivo": motivo,
                "proximo": {"desde_min": prox["desde_min"], "faltan_min": round(prox["desde_min"] - m, 1)}
                if (prox and not de) else None}

    def vista_bandeja(self, usuario: dict) -> dict:
        juez = usuario["juez_id"]
        turno = self.vista_turno(juez)
        de = turno["de_turno"]
        pendientes, dinamicas, historial, reclamos = [], [], [], []
        cambio = False
        if de:
            for exp in self.e["expedientes"]:
                for u in exp["ubicaciones"]:
                    if u["estado"] == "pendiente" and u.get("asignada_a") == juez:
                        if u.get("vista_min") is None:
                            u["vista_min"] = r3(self.ahora())
                            self.auditar("expediente_visto", "juez:" + juez, exp=exp["id"], datos={"ubicacion": u["n"]})
                            cambio = True
                        vexp = self.vista_expediente(exp)
                        for vu in vexp["ubicaciones"]:
                            if vu.get("nota_continuidad"):
                                _, uu = self.ubicacion(exp["id"], vu["n"])
                                vu["nota_continuidad"] = self.nota_reapertura(uu, juez)
                                if vu.get("continuidad"):
                                    vu["continuidad"]["nota"] = vu["nota_continuidad"]
                        # C24: la filtración se mudó si otra ubicación empezó a verse después de la última detección
                        # de esta (si las dos se ven a la vez, no; si la vieja vuelve a verse, la marca se va sola).
                        ult = u.get("ultima_deteccion_min")
                        sup = [x["n"] for x in exp["ubicaciones"] if x["n"] != u["n"] and ult is not None
                               and x.get("primera_deteccion_min") is not None
                               and float(x["primera_deteccion_min"]) > float(ult)]
                        pendientes.append({"expediente": vexp, "n": u["n"], "superada_por": max(sup) if sup else None,
                                           "automatica": dict(u.get("automatica") or {"posible": False, "motivo": None}),
                                           "nota_continuidad": self.nota_reapertura(u, juez)})
                din = exp.get("dinamica")
                if din and din.get("activa") and not din.get("revocada"):
                    otorgada, ratificada = self._otorgada_ratificada(din)
                    dinamicas.append({"exp": exp["id"], "titulo": exp["titulo"], "sesion": exp["filtracion"].get("sesion"),
                                      "otorgada_min": din.get("otorgada_min"),
                                      "ubicaciones": sum(1 for x in exp["ubicaciones"] if x["estado"] == "aprobada"),
                                      "requiere_ratificacion": din.get("requiere_ratificacion"),
                                      "otorgada_por": otorgada, "ratificada_por": ratificada,
                                      "ampliaciones": len(self.ampliadas_vigentes(exp))})
            pendientes.sort(key=lambda x: x["superada_por"] is not None)  # C24, estable: lo que se ve primero
            reclamos = [self.vista_reclamo(r) for r in sorted(self.e["reclamos"].values(), key=lambda x: x["minuto"] or 0)
                        if r["estado"] == "pendiente" and r.get("asignado_a") == juez]
        for exp in self.e["expedientes"]:
            amp = {x["n"] for x in self.ampliadas_vigentes(exp)} if de else set()
            for u in exp["ubicaciones"]:
                if u.get("decision") and u["decision"].get("juez_id") == juez:
                    historial.append((u["decision"].get("min") or 0, exp, u["n"]))
                elif u["n"] in amp:
                    # turnos-3: ampliación automática vigente bajo la orden de otro juez: el de turno puede levantarla.
                    historial.append((u["decision"].get("min") or 0, exp, u["n"]))
                elif u["estado"] == "sin_decidir" and u.get("asignada_a") == juez:
                    historial.append((u.get("sin_decidir_min") or self.fin_min(), exp, u["n"]))
        historial.sort(key=lambda x: x[0], reverse=True)
        avisos = [self._vista_aviso(a) for a in self.e["avisos"] if a.get("para") == juez][-30:][::-1] if de else []
        tr = self.traspaso_pendiente(juez) if de else None
        if cambio:
            self._marcar()
        return {"v": self.v, "reloj": self.vista_reloj(), "yo": self.vista_yo(usuario), "turno": turno,
                "traspaso": self.vista_traspaso(tr) if tr else None, "reclamos": reclamos, "pendientes": pendientes,
                "dinamicas": dinamicas, "avisos": avisos,
                "historial": [{"expediente": self.vista_expediente(exp), "n": n} for _, exp, n in historial[:30]],
                "historial_reclamos": self._historial_reclamos(juez),
                "historial_traspasos": self._historial_traspasos(juez),
                "marco": self._vista_marco_bandeja(juez, turno),
                "proveedores": [{"id": p.get("id"), "nombre": p.get("nombre"), "capacidades": p.get("capacidades")}
                                for p in self.e["proveedores"]]}

    @staticmethod
    def _vista_aviso(a: dict) -> dict:
        v = dict(a)
        v.setdefault("clave", f"{a.get('tipo')}-{a.get('n')}")
        v.setdefault("cuenta", 1)
        v.setdefault("atendido", False)
        return v

    def _historial_reclamos(self, juez: str) -> List[dict]:
        """Reclamos que resolvió este juez, del más nuevo al más viejo, con los que se cerraron junto con cada uno."""
        todos = list(self.e["reclamos"].values())
        mios = [r for r in todos if (r.get("resolucion") or {}).get("juez_id") == juez]
        mios.sort(key=lambda r: ((r.get("resolucion") or {}).get("min") or 0, r["id"]), reverse=True)
        return [{"id": r["id"], "dominio": r.get("dominio"), "proveedor_nombre": r.get("proveedor_nombre"),
                 "minuto": r.get("minuto"), "resolucion": r.get("resolucion"),
                 "cerrados_junto": sorted(x["id"] for x in todos
                                          if (x.get("resolucion") or {}).get("por_reclamo") == r["id"])}
                for r in mios]

    def _historial_traspasos(self, juez: str) -> List[dict]:
        salida = []
        for tr in reversed(self.e["traspasos"]):
            rat = tr.get("ratificado") or {}
            if rat.get("juez_id") != juez:
                continue
            salida.append({"min": tr.get("min"),
                           "de": [{"juez_id": x.get("juez_id"), "nombre": x.get("nombre")} for x in tr.get("de") or []],
                           "ratificado": {"min": rat.get("min"), "entrada": rat.get("entrada")},
                           "resumen": tr.get("resumen"),
                           "dinamicas_ratificadas": tr.get("dinamicas_ratificadas"),
                           "dinamicas_sin_ratificar": tr.get("dinamicas_sin_ratificar")})
        return salida

    def ordenes_con_colateral(self, solo_vigentes: bool = False) -> int:
        """C14: pirata = observados + inferidos no refutados. Un reclamante que salió «legítimo» y los inferidos
        de un registrable refutado cuentan como legítimos (la sala cuenta lo mismo que hizo)."""
        refutados = {dominios.normalizar(x) for x in self.e.get("inferencias_refutadas") or []}
        legitimos = {dominios.normalizar(r["dominio"]) for r in self.e["reclamos"].values()
                     if (r.get("verificacion") or {}).get("clase_reclamante") == "legitimo"}
        piratas = set(self.hosts_piratas())
        for exp in self.e["expedientes"]:
            for u in exp["ubicaciones"]:
                col = u.get("colateral") or {}
                obs = col.get("observados")
                inf = col.get("inferidos")
                if obs is None and inf is None:  # estado anterior a C14
                    obs, inf = col.get("propios") or [], []
                piratas |= {dominios.normalizar(p) for p in obs or []}
                piratas |= {dominios.normalizar(p) for p in inf or []
                            if dominios.registrable(dominios.normalizar(p)) not in refutados}
        piratas -= legitimos
        cuenta = 0
        for o in self.e["ordenes"].values():
            if o.get("aplicada_min") is None:
                continue
            if solo_vigentes and o["estado"] not in VIGENTES:
                continue
            if o["tipo"] == "ip":
                dns = (self.e["dns"]["ip"].get(o["objetivo"]) or {}).get("resp")
                doms = [dominios.normalizar(d) for d in (dns or {}).get("dominios") or []]
                if dns is None or any(d not in piratas for d in doms):
                    cuenta += 1
            elif dominios.normalizar(o["objetivo"]) not in piratas:
                cuenta += 1
        return cuenta

    def vista_sala(self) -> dict:
        exps = [self.vista_expediente(exp) for exp in self.e["expedientes"]]
        ubics = [u for exp in exps for u in exp["ubicaciones"]]
        aprobadas = [u for u in ubics if u["estado"] == "aprobada"]
        primeros = [u["cobertura"]["primer_bloqueo_min"] for u in aprobadas
                    if u["cobertura"]["primer_bloqueo_min"] is not None]
        residuales = [u["cobertura"]["visibilidad_residual_pct"] for u in ubics if u["estado"] != "rechazada"
                      and u["cobertura"]["visibilidad_residual_pct"] is not None]
        cubiertos = [u["cobertura"]["clientes_cubiertos_pct"] for u in aprobadas]
        ords = list(self.e["ordenes"].values())
        cuenta = lambda est: sum(1 for o in ords if o["estado"] == est)  # noqa: E731
        reclamos = list(self.e["reclamos"].values())
        descartes = list(self.e["descartes"].values())
        proveedores = []
        for p in self.e["proveedores"]:
            mias = [o for o in ords if o["proveedor"] == p["id"]]
            demoras = [o["aplicada_min"] - o["recibida_min"] for o in mias
                       if o.get("aplicada_min") is not None and o.get("recibida_min") is not None]
            proveedores.append({"id": p["id"], "nombre": p.get("nombre"), "tamano": p.get("tamano"),
                                "clientes": p.get("clientes"), "capacidades": p.get("capacidades"),
                                "activas": sum(1 for o in mias if o["estado"] in VIGENTES),
                                "fallidas": sum(1 for o in mias if o["estado"] == "fallida"),
                                "demora_promedio_min": round(sum(demoras) / len(demoras), 2) if demoras else None})
        prom = lambda xs: round(sum(xs) / len(xs), 2) if xs else None  # noqa: E731
        kpis = {"expedientes": len(exps),
                "ubicaciones_bloqueadas": sum(1 for u in aprobadas if u["cobertura"]["proveedores_aplicados"] > 0),
                "ubicaciones_levantadas": sum(1 for u in aprobadas if self._todo_levantado(u["ordenes"])),
                "ubicaciones_pendientes": sum(1 for u in ubics if u["estado"] == "pendiente"),
                "clientes_total": sum(p.get("clientes", 0) for p in self.e["proveedores"]),
                "clientes_cubiertos_pct": prom(cubiertos),
                "primer_bloqueo_promedio_min": prom(primeros),
                "visibilidad_residual_promedio_pct": prom(residuales),
                "ordenes_con_dano_colateral": self.ordenes_con_colateral(),
                "ordenes_con_dano_colateral_vigentes": self.ordenes_con_colateral(solo_vigentes=True),
                "reclamos_pendientes": sum(1 for r in reclamos if r["estado"] == "pendiente"),
                "reclamos_resueltos": sum(1 for r in reclamos if r["estado"] in ("resuelto", "desestimado", "cerrado")),
                "ordenes": {"enviadas": sum(1 for o in ords if o.get("enviada_min") is not None),
                            "recibidas": cuenta("recibida"), "aplicadas": cuenta("aplicada"),
                            "fallidas": cuenta("fallida"), "rechazadas": cuenta("rechazada"),
                            "vencidas": cuenta("vencida"), "levantadas": cuenta("levantada"),
                            "en_espera": cuenta("espera_ratificacion"), "perdidas": cuenta("perdida")},
                "descartes": {c: sum(1 for d in descartes if d["clase"] == c)
                              for c in ("licenciatario", "otra_senal", "sin_marca")}}
        audit = list(self.auditoria.ultimas[-80:])[::-1] if self.auditoria else []
        return {"v": self.v, "reloj": self.vista_reloj(), "cabeza_auditoria": self.auditoria.cabeza_info(),
                "kpis": kpis, "proveedores": proveedores, "expedientes": exps,
                "descartes": sorted(descartes, key=lambda d: d["minuto"] or 0),
                "reclamos": [self.vista_reclamo(r) for r in sorted(reclamos, key=lambda x: x["minuto"] or 0)],
                "traspasos": [self.vista_traspaso(t) for t in self.e["traspasos"]],
                "avisos": [self._vista_aviso(a) for a in self.e["avisos"][-50:][::-1]], "auditoria": audit,
                "paquete": self.e["hitos"].get("paquete"),
                "marcos": [self.vista_marco(m) for m in self.e["marcos"]], "jueces": self.vista_jueces()}

    @staticmethod
    def _todo_levantado(ordenes: List[dict]) -> bool:
        """C12: hubo órdenes aplicadas y todas terminaron levantadas (ninguna vigente ni vencida con el partido)."""
        aplicadas = [o for o in ordenes if o.get("aplicada_min") is not None]
        return bool(aplicadas) and all(o["estado"] == "levantada" for o in aplicadas)

    def _motivo_publico(self, exp: dict) -> str:
        return (f"Retransmisión no autorizada del partido «{self.e['partido'].get('nombre')}» "
                f"(expediente {exp['id']}, sitio {exp['titulo']}).")

    def _decision_publica(self, o: dict, dec: dict) -> dict:
        """Ola C, NV1: la decisión que ORDENÓ esta orden (la entrada que la sella). Para un reemplazo por reclamo es la
        resolución del reclamo, no la firma original de la ubicación."""
        rid = o.get("reclamo")
        res = (self.e["reclamos"].get(rid) or {}).get("resolucion") if rid else None
        if rid and res:  # Ola D (g-despacho-2): también el reintento C13 de un reemplazo (conserva `reclamo`)
            quien = res.get("juez") or self.nombre_juez(o.get("juez_id")) or "el juez"
            return {"origen": "reclamo", "reclamo": rid, "min": res.get("min"),
                    "entrada": o.get("entrada_sello") or res.get("entrada"), "tipo": "resolucion_reclamo",
                    "texto": f"Decidida por {quien} al resolver el reclamo {rid}, en el minuto {_min_txt(res.get('min'))} "
                             f"(entrada {o.get('entrada_sello') or res.get('entrada')})"}
        return {"origen": "ubicacion", "reclamo": None, "min": dec.get("min"), "entrada": dec.get("entrada"),
                "tipo": dec.get("tipo"), "texto": dec.get("texto")}

    def vista_registro(self) -> dict:
        bloqueos = []
        for o in self.e["ordenes"].values():
            if o.get("aplicada_min") is None:
                continue
            exp, u = self.ubicacion(o["exp"], o["n"])
            dec = u.get("decision") or {}
            dp = self._decision_publica(o, dec)
            lev = None
            if o.get("levantamiento"):
                L = o["levantamiento"]
                lev = {"min": L.get("min"), "juez": L.get("juez"), "motivo": L.get("motivo"), "reclamo": L.get("reclamo")}
            bloqueos.append({"orden_id": o["orden_id"], "expediente": exp["id"], "filtracion": exp["id"],
                             "sello": o["sello"], "tipo": o["tipo"],
                             "objetivo": o["objetivo"], "proveedor": o["proveedor"],
                             "proveedor_nombre": self.proveedor(o["proveedor"]).get("nombre"), "estado": o["estado"],
                             "desde_min": o["aplicada_min"], "hasta_min": o.get("finalizada_min"),
                             "vence_min": o["vence_min"], "juez": self.nombre_juez(o["juez_id"]),
                             "juzgado": (self.e["jueces"].get(o["juez_id"]) or {}).get("juzgado"),
                             "decision_min": dp["min"], "motivo": self._motivo_publico(exp), "levantamiento": lev,
                             "decision_tipo": dp["tipo"], "bajo_orden_de": dec.get("bajo_orden_de"),
                             "decision_texto": dp["texto"], "decision_origen": dp["origen"],
                             "reclamo": dp["reclamo"]})
        bloqueos.sort(key=lambda b: (b["desde_min"] or 0, b["orden_id"]))
        reclamos = list(self.e["reclamos"].values())
        r = self.vista_reloj()
        return {"v": self.v, "reloj": {k: r[k] for k in ("minuto", "hora", "fin_min", "finalizado", "partido",
                                                          "hora_inicio", "fin_hora")},
                "cabeza_auditoria": self.auditoria.cabeza_info(),
                "resumen": {"bloqueos_vigentes": sum(1 for b in bloqueos if b["estado"] == "aplicada"),
                            "bloqueos_vencidos": sum(1 for b in bloqueos if b["estado"] == "vencida"),
                            "bloqueos_levantados": sum(1 for b in bloqueos if b["estado"] == "levantada"),
                            "sitios_bloqueados": len({(b["expediente"]) for b in bloqueos}),
                            "reclamos_recibidos": len(reclamos),
                            "reclamos_resueltos": sum(1 for x in reclamos if x["estado"] != "pendiente")},
                "bloqueos": bloqueos, "paquete": self.e["hitos"].get("paquete"),
                "marcos": [self.vista_marco(m) for m in self.e["marcos"]],
                "proveedores": [{"id": p.get("id"), "nombre": p.get("nombre"), "capacidades": p.get("capacidades")}
                                for p in self.e["proveedores"]]}

    NO_RIGE = ("levantada", "vencida", "fallida", "rechazada", "perdida")

    def texto_llano_orden(self, o: dict) -> str:
        """El texto llano depende del estado: una orden que ya no rige no dice «con las líneas de abajo se quita»."""
        p = self.proveedor(o["proveedor"])
        partido = self.e["partido"]
        hora_vence = hora_de_partido(partido.get("inicio_iso"), o["vence_min"])
        que = "la IP" if o["tipo"] == "ip" else "el nombre de dominio"
        cuando = f"hasta el minuto {o['vence_min']} del partido" + (f" (hora {hora_vence})" if hora_vence else "")
        if o["estado"] in self.NO_RIGE or self.ahora() >= float(o["vence_min"]):
            texto = f"Esta orden ya no rige. Ordenaba a {p.get('nombre')} bloquear {que} {o['objetivo']} {cuando}. "
            L = o.get("levantamiento") or {}
            fin_txt = _min_txt(o.get("finalizada_min")) if o.get("finalizada_min") is not None else None
            if o["estado"] == "levantada":
                quien = L.get("juez") or self.nombre_juez(L.get("juez_id")) or "el juez"
                texto += f"La levantó {quien} en el minuto {_min_txt(L.get('min') or o.get('finalizada_min'))}"
                texto += f" (reclamo {L.get('reclamo')})." if L.get("reclamo") else "."
            elif o["estado"] == "vencida" or self.ahora() >= float(o["vence_min"]):
                texto += f"Venció en el minuto {fin_txt or o['vence_min']}."
            elif o["estado"] == "fallida":
                texto += "El proveedor no pudo aplicarla."
            elif o["estado"] == "rechazada":
                texto += "El proveedor la rechazó."
            else:
                texto += "El proveedor ya no la tiene."
            texto += " Si la aplicaste, quitala."
        else:
            texto = f"Se ordena a {p.get('nombre')} bloquear {que} {o['objetivo']} {cuando}. "
            texto += ("El bloqueo vence en ese minuto: con las líneas de abajo se quita solo." if o["tipo"] == "ip" else
                      "Vence en ese minuto. El DNS no lo quita solo: usá la lista del proveedor o la línea de "
                      "vencimiento.")
        if o.get("reclamo"):  # Ola D (g-despacho-2): el reintento de un reemplazo también lo dice
            texto += f" Reemplaza un bloqueo por IP que afectaba a un sitio legítimo (reclamo {o.get('reclamo')})."
        return texto

    def _kit_orden(self, o: dict, exp: dict) -> List[dict]:
        partido = self.e["partido"]
        ahora = self.ahora()
        acelerar = float(self.reloj.acelerar or 1.0)
        if acelerar != 1.0:
            # kit-1: con el partido acelerado, la hora del partido no es la del router: el vencimiento va en la hora
            # real de esta máquina (lo que falta de partido, en minutos reales).
            real = datetime.datetime.now() + datetime.timedelta(minutes=max(0.0, float(o["vence_min"]) - ahora) / acelerar)
            # Ola C (f-kit-1): con segundos y redondeado hacia arriba: truncar a HH:MM adelantaba el borrado hasta 1
            # minuto real y la filtración volvía a verse antes de que venciera la orden.
            if real.microsecond:
                real = real.replace(microsecond=0) + datetime.timedelta(seconds=1)
            hora, fecha = real.strftime("%H:%M:%S"), real.strftime("%Y-%m-%d")
        else:
            hora = (hora_de_partido(partido.get("inicio_iso"), o["vence_min"]) or "")[:5]  # a x1: HH:MM (verificador)
            fecha = None
            try:
                inicio = datetime.datetime.fromisoformat(str(partido.get("inicio_iso")).replace("Z", "+00:00"))
                fecha = (inicio + datetime.timedelta(minutes=float(o["vence_min"]))).strftime("%Y-%m-%d")
            except (TypeError, ValueError):
                fecha = None
        vigente = o["estado"] not in self.NO_RIGE and ahora < float(o["vence_min"])
        return kit_mod.kit(o["tipo"], o["objetivo"], o["vence_min"], ahora, exp["id"], o["sello"],
                           vigente=vigente, hora_vence=hora or None, fecha_vence=fecha, acelerar=acelerar)

    def vista_orden_publica(self, oid: str) -> dict:
        o = self.e["ordenes"].get(oid)
        if o is None:
            raise ErrorAccion("no_encontrado", "No existe esa orden.")
        exp, u = self.ubicacion(o["exp"], o["n"])
        dec = u.get("decision") or {}
        dp = self._decision_publica(o, dec)
        partido = self.e["partido"]
        prefijo = u["senal"].get("prefijo") or ""
        # Sección 4: la sesión de la marca identifica a un abonado; lo público muestra solo el prefijo.
        por_que = [evidencia.texto_senal_publico(u["senal"]),
                   f"El video sale del servidor {u['host']} (IP {u['ip']}, ASN {u.get('asn')}, {u.get('organizacion')}).",
                   u["colateral"].get("motivo"),
                   f"La evidencia quedó sellada (huella {u['huella'][:16]}…); el sello {o['sello']} une esta orden con la "
                   + ("evidencia exacta que evaluó la plataforma y con la autorización del juez (su orden marco y el "
                      "seguimiento que otorgó) en el registro de auditoría."
                      if self.prefijo_de(o["orden_id"]) == "amp" else
                      "evidencia exacta que vio el juez y con su decisión en el registro de auditoría.")]
        lev = o.get("levantamiento")
        if lev:
            lev = dict(lev, juez_nombre=lev.get("juez"))
        return {"v": self.v, "orden": self.vista_orden(o), "expediente": exp["id"], "filtracion": exp["id"],
                "ubicacion": u["n"], "sello": o["sello"],
                "huella": u["huella"], "juez": self.nombre_juez(o["juez_id"]),
                "juzgado": (self.e["jueces"].get(o["juez_id"]) or {}).get("juzgado"),
                "decision_min": dp["min"], "decision_hora": hora_de_partido(partido.get("inicio_iso"), dp["min"]),
                "decision_origen": dp["origen"], "reclamo": dp["reclamo"],
                "texto_llano": self.texto_llano_orden(o), "por_que": [x for x in por_que if x],
                "evidencia": {"marca": prefijo or None, "host": u["host"], "ip": u["ip"], "asn": u.get("asn"),
                              "organizacion": u.get("organizacion"), "captura_sha256": u["captura"].get("sha256"),
                              "riesgo": u["colateral"].get("riesgo"), "motivo_colateral": u["colateral"].get("motivo")},
                "levantamiento": lev,
                "decision": {"tipo": dp["tipo"], "bajo_orden_de": dec.get("bajo_orden_de"),
                             "texto": dp["texto"], "entrada": dp["entrada"]},
                "kit": self._kit_orden(o, exp),
                "como_objetar": ("Si este bloqueo afecta a tu sitio, avisale a tu proveedor de internet o al juzgado que "
                                 "figura arriba, con el número de orden. La plataforma comprueba qué sitios comparten el "
                                 "servidor bloqueado y el juez de turno decide si lo levanta. La decisión queda firmada y "
                                 "publicada en este registro.")}

    def _no_cortar(self, o: dict, u: dict) -> dict:
        """kit-2: en una orden por dominio, los nombres ajenos conocidos que cuelgan de ese dominio (Unbound los
        cortaría con la zona entera); el kit los deja resolver. Ola C (P3 de a-kit): el ajeno puede conocerse por
        OTRA ubicación (otra IP): se miran los ajenos de todas, empezando por la de la orden."""
        if o.get("tipo") != "dominio":
            return {}
        obj = dominios.normalizar(o.get("objetivo") or "")
        todas = [u] + [x for exp in self.e["expedientes"] for x in exp["ubicaciones"] if x is not u]
        colgados = sorted({dominios.normalizar(n) for x in todas for n in (x.get("colateral") or {}).get("ajenos") or []
                           if dominios.normalizar(n).endswith("." + obj)})
        return {"no_cortar": colgados} if obj and colgados else {}

    def vista_proveedor(self, pid: str) -> dict:
        """La lista que el equipo del proveedor lee solo (sección 5.2). Con el candado tomado."""
        if not any(p.get("id") == pid for p in self.e["proveedores"]):
            raise ErrorAccion("no_encontrado", "No existe ese proveedor.")
        p = self.proveedor(pid)
        partido = self.e["partido"]
        ini = partido.get("inicio_iso")
        m = self.ahora()
        hora = lambda x: (hora_de_partido(ini, x) or "")[:5] or None  # noqa: E731
        mias = [o for o in self.e["ordenes"].values() if o["proveedor"] == pid and o.get("recibida_min") is not None]
        vigentes, retiradas = [], []
        for o in sorted(mias, key=lambda x: (x.get("recibida_min") or 0, x["orden_id"])):
            exp, u = self.ubicacion(o["exp"], o["n"])
            dec = u.get("decision") or {}
            if o["estado"] in VIGENTES and not o.get("levantar") and m < float(o["vence_min"]):
                vigentes.append({"orden_id": o["orden_id"], "tipo": o["tipo"], "objetivo": o["objetivo"],
                                 "vence_min": o["vence_min"], "vence_hora": hora(o["vence_min"]),
                                 "juzgado": (self.e["jueces"].get(o["juez_id"]) or {}).get("juzgado"),
                                 "juez": self.nombre_juez(o["juez_id"]),
                                 "firma": "ampliacion" if dec.get("tipo") == "ampliacion_dinamica" else "en_persona",
                                 "desde_min": o.get("recibida_min"), "url": "/orden/" + o["orden_id"],
                                 **self._no_cortar(o, u)})
            elif o["estado"] in ("levantada", "vencida") or (o["estado"] in VIGENTES and m >= float(o["vence_min"])):
                motivo = "levantada" if o["estado"] == "levantada" else "vencida"
                retiradas.append({"orden_id": o["orden_id"], "tipo": o["tipo"], "objetivo": o["objetivo"],
                                  "motivo": motivo, "min": o.get("finalizada_min")
                                  if o.get("finalizada_min") is not None else o["vence_min"]})
        retiradas.sort(key=lambda x: (x["min"] or 0, x["orden_id"]))
        return {"acelerar": float(self.reloj.acelerar or 1.0),
                "v": self.v, "proveedor": {"id": pid, "nombre": p.get("nombre"), "capacidades": p.get("capacidades")},
                "minuto": round(m, 2), "hora": hora(m), "generado_utc": utc_ahora(),
                "partido": {"nombre": partido.get("nombre"), "fin_min": self.fin_min(), "fin_hora": hora(self.fin_min())},
                "vigentes": vigentes, "retiradas": retiradas[-50:]}

    @staticmethod
    def normalizar_consulta(texto: Any) -> str:
        """C9: lo que pegó la persona queda como nombre de dominio: sin espacios alrededor, esquema (`algo://`), usuario
        (`…@`), ruta, consulta y fragmento (desde el primer `/`, `?` o `#`), puerto final (`:dígitos`) ni punto
        final, y en minúsculas. Un espacio en el medio no se borra: «con espacio.test» sigue siendo inválido."""
        t = str(texto or "").strip()
        if "://" in t:
            t = t.split("://", 1)[1]
        for corte in "/?#":
            t = t.split(corte, 1)[0]
        if "@" in t:
            t = t.rsplit("@", 1)[1]
        cabeza, dos_puntos, cola = t.rpartition(":")
        if dos_puntos and cola.isdigit() and ":" not in cabeza:
            t = cabeza
        return t.rstrip(".").lower()

    def consulta_publica(self, dominio: str) -> dict:
        """«¿Tu sitio quedó bloqueado?» (sección 5.4): sin red y sin cambiar estado."""
        crudo = str(dominio or "").strip()
        d = self.normalizar_consulta(crudo)
        if not d or dominios.es_ip(d) or not dominios.es_hostname(d) or "." not in d or \
                any(not r for r in d.split(".")):  # Ola C (f-kit-2): «_» es válido (C16)
            return {"dominio": d or crudo, "resultado": "invalido", "ordenes": [],
                    "texto": "Escriba un nombre de dominio, por ejemplo: mitienda.com.ar."}
        m = self.ahora()
        vig = [o for o in self.e["ordenes"].values()
               if o["estado"] in VIGENTES and not o.get("levantar") and m < float(o["vence_min"])]

        def item(o: dict) -> dict:
            return {"orden_id": o["orden_id"], "tipo": o["tipo"], "objetivo": o["objetivo"],
                    "juzgado": (self.e["jueces"].get(o["juez_id"]) or {}).get("juzgado"), "vence_min": o["vence_min"],
                    "url": "/orden/" + o["orden_id"]}
        directas = [item(o) for o in vig if o["tipo"] == "dominio" and dominios.normalizar(o["objetivo"]) == d]
        if directas:
            return {"dominio": d, "resultado": "bloqueado", "ordenes": directas,
                    "texto": f"{d} está bloqueado por orden judicial hasta el minuto {directas[0]['vence_min']}."}
        compartidas = []
        for o in vig:
            if o["tipo"] != "ip":
                continue
            resp = (self.e["dns"]["ip"].get(o["objetivo"]) or {}).get("resp") or {}
            if d in [dominios.normalizar(x) for x in resp.get("dominios") or []]:
                compartidas.append(item(o))
        if compartidas:
            ips = ", ".join(sorted({x["objetivo"] for x in compartidas}))
            return {"dominio": d, "resultado": "comparte_servidor", "ordenes": compartidas,
                    "texto": f"{d} comparte el servidor {ips} con un sitio bloqueado por IP. Si su sitio no tiene "
                             "relación con la retransmisión, avise a su proveedor o al juzgado con el número de orden."}
        return {"dominio": d, "resultado": "no_alcanzado", "ordenes": [],
                "texto": f"Ninguna orden vigente alcanza a {d}."}
