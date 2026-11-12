"""Envío, levantamiento y seguimiento de órdenes hacia los proveedores.

Un solo hilo despachador decide qué sale en cada ronda (así una orden nunca se manda dos veces en
paralelo) y reparte los envíos entre varios hilos, fuera del candado del estado. La ronda NO espera a sus
envíos: cada envío libera su marca `en_vuelo` al terminar (pase lo que pase) y despierta al despachador.

Reglas que protegen el registro oficial:
- antes de CADA POST se consulta GET /estado fresco y se comprueba que el juez firmante puede firmar, con el
  margen que suma la latencia medida; si la consulta tardó más de 3 s, no se firma en esa ronda;
- respuesta al POST de una orden:
  202 → recibida; 409 → la orden ya existe: GET y se adopta su estado (`orden_reconciliada`), nunca rechazada;
  400/401/403/404/422 con el JSON de error del simulador → rechazada (con alerta);
  cualquier otra cosa (5xx, 429, 408, cuerpo ajeno, tiempo agotado, corte) → incierta;
- una orden incierta se consulta con GET; si existe se adopta; si da 404 solo se reenvía (con el mismo
  orden_id) cuando ya pasó el tiempo de espera del POST y un segundo GET repite el 404. Las consultas se
  espacian cada vez más y al tercer intento se avisa en la sala;
- un levantamiento con respuesta incierta se confirma con GET: si el proveedor ya lo levantó se registra
  `orden_levantada` con `confirmada_por_consulta`; si sigue activa, se reintenta;
- nunca se manda una orden si falta el margen de fin (con la latencia) o menos para el final o su vencimiento.
"""
from __future__ import annotations

import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, wait
from typing import TYPE_CHECKING, Any, List, Optional, Tuple

from . import sello, turnos
from .reloj import instante
from .canon import r3
from .simulador import ErrorRed

if TYPE_CHECKING:  # pragma: no cover
    from .motor import Motor

ESPERAS_INCIERTA_S = (1.0, 2.0, 4.0, 8.0)   # espera creciente entre consultas de una orden en duda
ALERTA_INCIERTA_EN = 3                      # al tercer intento en duda se avisa en la sala
ESPERA_LEV_RECHAZADO_S = 5.0
# C19: un POST sin respuesta no se reenvía con el mismo orden_id antes de 12 s reales desde que salió (además de los
# dos 404), así un original lento alcanza a aparecer en el proveedor y se adopta en vez de dejar un 409 «rechazada».
ESPERA_REENVIO_S = 12.0
CODIGOS_RECHAZO = (400, 401, 403, 404, 422)


def es_rechazo_del_simulador(estado: int, datos: Any) -> bool:
    """Un rechazo definitivo: código de validación del simulador y su cuerpo JSON de error."""
    return estado in CODIGOS_RECHAZO and isinstance(datos, dict) and isinstance(datos.get("error"), str)


def espera_incierta(o: dict) -> float:
    k = max(1, int(o.get("intentos_inciertos") or 1))
    return ESPERAS_INCIERTA_S[min(k, len(ESPERAS_INCIERTA_S)) - 1]


class Despacho:
    def __init__(self, motor: "Motor") -> None:
        self.m = motor
        self._evento = threading.Event()
        self._parar = threading.Event()
        self._pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="envio")

    def iniciar(self) -> threading.Thread:
        h = threading.Thread(target=self._bucle, name="despacho", daemon=True)
        h.start()
        return h

    def detener(self) -> None:
        self._parar.set()
        self._evento.set()
        self._pool.shutdown(wait=True)

    def despertar(self) -> None:
        self._evento.set()

    # --------------------------------------------------------------------------------------

    def _pendientes(self) -> Tuple[List[dict], List[dict]]:
        """Con el candado: órdenes para enviar y órdenes para levantar en esta ronda."""
        m = self.m
        envios, levantes = [], []
        if m._foto:
            return envios, levantes  # foto de testigos en curso: no sale nada nuevo hasta que termine
        ahora_t = time.monotonic()
        candidatos_firma = set(m.de_turno())
        minuto = m.ahora()
        for o in m.e["ordenes"].values():
            if o.get("en_vuelo") or o.get("no_enviada"):
                continue
            if o.get("no_antes_min") is not None and o["estado"] in ("por_enviar", "espera_ratificacion") \
                    and not o.get("levantar") and minuto < float(o["no_antes_min"]):
                continue  # C13: reintento desde el 7.º, todavía no se cumplió el minuto de espera
            if (o.get("incierta") or o.get("lev_incierto")) and \
                    ahora_t - instante(o.get("t_error")) < espera_incierta(o):
                continue
            pedido = o.get("levantar")
            if pedido and o["estado"] in ("por_enviar", "recibida", "aplicada", "espera_ratificacion"):
                if ahora_t - instante(pedido.get("t_rechazo")) < ESPERA_LEV_RECHAZADO_S:
                    continue
                if pedido.get("en_espera") and not ({pedido["juez_id"]} | set(m.e["ratificados"])) & candidatos_firma:
                    continue  # nadie de turno puede firmarlo todavía: espera la ratificación
                levantes.append(o)
            elif o["estado"] == "por_enviar":
                envios.append(o)
            elif o["estado"] == "espera_ratificacion":
                firmantes = {o["juez_id"]} | set(m.e["ratificados"])
                if firmantes & candidatos_firma:
                    envios.append(o)
        return envios, levantes

    def hay_trabajo(self) -> bool:
        with self.m.candado:
            envios, levantes = self._pendientes()
            return bool(envios or levantes)

    def _bucle(self) -> None:
        while not self._parar.is_set():
            self._evento.wait(0.5)
            self._evento.clear()
            if self._parar.is_set():
                break
            try:
                self.ronda(esperar=False)
            except Exception:
                self.m.log("Error en el despacho:\n" + traceback.format_exc())

    def ronda(self, esperar: bool = True) -> None:
        """Una ronda. El bucle la corre sin esperar a los envíos; `esperar=True` (pruebas, herramientas) espera."""
        m = self.m
        with m.candado:
            envios, levantes = self._pendientes()
            if not envios and not levantes:
                return
            for o in envios + levantes:
                o["en_vuelo"] = True
            # La instantánea se guarda ANTES de mandar: si la plataforma se cae, al reanudar sabe qué pudo salir.
            try:
                m.guardar()
            except Exception:
                for o in envios + levantes:
                    o.pop("en_vuelo", None)
                m.log("No se pudo guardar el estado antes de enviar:\n" + traceback.format_exc())
                m.auditar("alerta", "sistema", datos={
                    "texto": "No se pudo guardar el estado antes de enviar: no salió nada y se reintenta."})
                return
        trabajos = [self._pool.submit(self._trabajo, o, self._enviar) for o in envios]
        trabajos += [self._pool.submit(self._trabajo, o, self._levantar) for o in levantes]
        if esperar:
            wait(trabajos)

    def _trabajo(self, o: dict, funcion) -> None:
        """Un envío o levantamiento. Pase lo que pase, la orden deja de estar en vuelo y el despachador despierta."""
        m = self.m
        try:
            funcion(o)
        except Exception:
            m.log("Error enviando una orden:\n" + traceback.format_exc())
        finally:
            with m.candado:
                o.pop("en_vuelo", None)
                m._marcar()
                try:
                    m.guardar()
                except Exception:
                    m.log("No se pudo guardar el estado después de un envío:\n" + traceback.format_exc())
            self.despertar()

    # --------------------------------------------------------------------------------------

    def _elegir_firmante(self, o: dict, juez_preferido: str) -> Tuple[Optional[str], Optional[dict], Optional[str]]:
        """Consulta fresca a /estado. Devuelve (juez, estado, motivo). Sin estado = no se decide nada ahora."""
        m = self.m
        try:
            est = m.estado_fresco()
        except ErrorRed:
            return None, None, "Sin conexión con el simulador."
        if float(est.get("_dur_s") or 0.0) > turnos.DURACION_MAXIMA_S:
            return None, None, turnos.TEXTO_LENTO.format(float(est["_dur_s"]))
        with m.candado:
            candidatos = [juez_preferido] + [j for j in m.e["ratificados"] if j != juez_preferido]
        motivo = None
        for j in candidatos:
            if not m.usuarios.tiene_clave(j):
                continue
            ok, mot = m.puede_firmar_con(j, est)
            if ok:
                return j, est, None
            motivo = motivo or mot
        return None, est, motivo

    def _minuto_ahora(self, est: dict) -> float:
        """Cota superior del minuto del simulador ahora: el de la consulta más lo que pasó desde que se pidió."""
        minuto = float(est["minuto_actual"])
        t_pedido = est.get("_t_pedido")
        if t_pedido is None:
            return minuto
        return minuto + max(0.0, time.monotonic() - float(t_pedido)) * float(est.get("acelerar") or 1.0) / 60.0

    def _marcar_incierta(self, o: dict, motivo: str, campo: str = "incierta") -> None:
        """Con el candado: la respuesta no permite saber qué pasó; se consulta con GET antes de decidir."""
        m = self.m
        o[campo] = True
        o["motivo_incierta"] = motivo
        accion = "enviar" if campo == "incierta" else "levantar"
        m.auditar("alerta", "sistema", exp=o.get("exp"), datos={
            "texto": f"Respuesta incierta al {accion} {o['orden_id']} ({motivo}): se consulta antes de reintentar.",
            "orden_id": o["orden_id"], "error": str(motivo)[:200]})
        self._otro_intento(o, accion, motivo)

    def _otro_intento(self, o: dict, accion: str, motivo: str) -> None:
        """Con el candado: un intento más en duda; la espera crece y al tercero se avisa en la sala."""
        m = self.m
        o["t_error"] = time.monotonic()
        o["intentos_inciertos"] = int(o.get("intentos_inciertos") or 0) + 1
        if o["intentos_inciertos"] == ALERTA_INCIERTA_EN:
            m.alerta(f"{m.proveedor(o['proveedor']).get('nombre')}: tercer intento en duda al {accion} la orden "
                     f"{o['orden_id']} ({motivo}). Se sigue consultando antes de reintentar.",
                     clave=f"incierta-{accion}-{o['orden_id']}", exp=o.get("exp"))

    def _resolver_incierta(self, o: dict) -> str:
        """GET de una orden cuyo envío quedó en duda. Devuelve 'existe', 'reenviar' o 'esperar'."""
        m = self.m
        try:
            estado, datos = m.cliente.orden(o["proveedor"], o["orden_id"])
        except ErrorRed as err:
            with m.candado:
                self._otro_intento(o, "enviar", f"consulta sin respuesta: {err}")
            return "esperar"
        with m.candado:
            if estado == 200 and isinstance(datos, dict):
                m._adoptar(o, datos, o.get("motivo_incierta") or "envío incierto")
                return "existe"
            if estado == 404 and isinstance(datos, dict):
                o["n_404"] = int(o.get("n_404") or 0) + 1
                vencio_post = time.monotonic() >= instante(o.get("t_post")) + max(
                    ESPERA_REENVIO_S, float(o.get("post_timeout") or 0.0))
                if o["n_404"] >= 2 and vencio_post:
                    o["incierta"] = False
                    o["n_404"] = 0
                    return "reenviar"
                o["t_error"] = time.monotonic()  # un 404: se espera el segundo
                return "esperar"
            self._otro_intento(o, "enviar", f"consulta con HTTP {estado}")
            return "esperar"

    def _enviar(self, o: dict) -> None:
        m = self.m
        if o.get("incierta"):
            if self._resolver_incierta(o) != "reenviar":
                return
        juez, est, motivo = self._elegir_firmante(o, o["juez_id"])
        if est is None:
            return
        fin = m.fin_min()
        with m.candado:
            if o["estado"] not in ("por_enviar", "espera_ratificacion") or o.get("levantar") or o.get("incierta"):
                return
            if m._foto:
                return  # se manda en la próxima ronda, después de la foto de testigos
            minuto = self._minuto_ahora(est)  # cuenta lo que se esperó por el candado
            if o.get("no_antes_min") is not None and minuto < float(o["no_antes_min"]):
                return  # C13: con el minuto fresco del simulador, todavía no toca; sale en una ronda siguiente
            margen = m.margen_envio(est.get("acelerar"), m.latencia_para(est))
            if minuto >= fin - margen or int(o["vence_min"]) - minuto <= margen:
                o["no_enviada"] = True
                o["motivo"] = "No salió: el partido termina o la orden vence en segundos."
                m.auditar("alerta", "sistema", exp=o["exp"], datos={
                    "texto": f"La orden {o['orden_id']} no se envió: faltaban {max(0.0, min(fin, int(o['vence_min'])) - minuto):.2f} "
                             f"min para el final o el vencimiento (margen {margen:.2f} min).",
                    "orden_id": o["orden_id"]})
                return
            if juez is not None:
                ok, mot = m.puede_firmar_con(juez, dict(est, minuto_actual=minuto))
                if not ok:
                    juez, motivo = None, mot
            if juez is None:
                if o["estado"] != "espera_ratificacion":
                    o["estado"] = "espera_ratificacion"
                    o["motivo"] = motivo or "El juez firmante ya no está de turno."
                    m.auditar("orden_en_espera", "sistema", exp=o["exp"], datos={
                        "orden_id": o["orden_id"], "juez_id": o["juez_id"], "motivo": o["motivo"]})
                return
            info = m.e["jueces"].get(juez) or {}
            o["juez_id"] = juez
            o["juzgado_id"] = info.get("juzgado_id")
            o["estado"] = "por_enviar"
            o["motivo"] = None
            firma = m.usuarios.firmar_con(juez, sello.firma_orden, o["orden_id"], o["tipo"], o["objetivo"],
                                          int(o["vence_min"]), juez)
            cuerpo = {"orden_id": o["orden_id"], "expediente_id": o["exp"], "tipo": o["tipo"],
                      "objetivo": o["objetivo"], "vence_min": int(o["vence_min"]), "juzgado_id": o["juzgado_id"],
                      "juez_id": juez, "firma": firma}
            m.auditar("orden_enviada", "sistema", exp=o["exp"], datos={
                "orden_id": o["orden_id"], "proveedor": o["proveedor"], "tipo": o["tipo"], "objetivo": o["objetivo"],
                "vence_min": int(o["vence_min"]), "juez_id": juez, "juzgado_id": o["juzgado_id"],
                "intento": o["intento"], "origen": o["origen"], "reemplaza": o["reemplaza"]},
                minuto=float(est["minuto_actual"]))
            o["enviada_min"] = r3(float(est["minuto_actual"]))
            o["t_post"] = time.monotonic()
            o["post_timeout"] = float(m.cliente.timeout_post()) if hasattr(m.cliente, "timeout_post") else 10.0
            m._posts_en_curso += 1
        try:
            estado, datos = m.cliente.enviar_orden(o["proveedor"], cuerpo)
        except ErrorRed as err:
            with m.candado:
                m._posts_en_curso -= 1
                self._marcar_incierta(o, f"error de red: {err}")
            return
        except BaseException:
            with m.candado:
                m._posts_en_curso -= 1
            raise
        adoptar_409 = False
        with m.candado:
            m._posts_en_curso -= 1
            if estado == 202:
                o["estado"] = "recibida"
                o["recibida_min"] = r3(m.ahora())
                o["t_confirmada"] = time.monotonic()
                o["intentos_inciertos"] = 0
                m.auditar("orden_recibida", "proveedor:" + o["proveedor"], exp=o["exp"], datos={
                    "orden_id": o["orden_id"], "respuesta": 202})
            elif estado == 409:
                # Ya existe una orden con ese orden_id: es la nuestra (un envío anterior llegó). Se adopta.
                o["incierta"] = True
                o["t_error"] = None  # se consulta ya
                o["motivo_incierta"] = "409: el proveedor ya tenía la orden"
                adoptar_409 = True
            elif es_rechazo_del_simulador(estado, datos):
                o["estado"] = "rechazada"
                o["motivo"] = datos["error"]
                m.auditar("orden_rechazada", "proveedor:" + o["proveedor"], exp=o["exp"], datos={
                    "orden_id": o["orden_id"], "http": estado, "motivo": o["motivo"]})
                m.alerta(f"{o['proveedor']} rechazó la orden {o['orden_id']}: {o['motivo']}",
                         clave="rechazo-" + o["orden_id"], exp=o["exp"])
            else:
                self._marcar_incierta(o, f"HTTP {estado}" + ("" if isinstance(datos, dict) else ", respuesta ajena"))
        if adoptar_409:
            self._resolver_incierta(o)

    # --- levantamientos --------------------------------------------------------------------

    def _consultar_levantamiento(self, o: dict) -> str:
        """GET de una orden cuyo levantamiento quedó en duda: 'levantada', 'activa', 'final' o 'esperar'."""
        m = self.m
        try:
            estado, datos = m.cliente.orden(o["proveedor"], o["orden_id"])
        except ErrorRed as err:
            with m.candado:
                self._otro_intento(o, "levantar", f"consulta sin respuesta: {err}")
            return "esperar"
        with m.candado:
            if estado == 200 and isinstance(datos, dict):
                est_sim = datos.get("estado")
                if est_sim == "levantada":
                    m._registrar_levantamiento(o, datos.get("finalizada_min"), por_consulta=True)
                    return "levantada"
                o["lev_incierto"] = False
                if est_sim in ("recibida", "aplicada"):
                    if o["estado"] not in ("recibida", "aplicada"):
                        m._aplicar_estado_sim(o, datos)
                    return "activa"
                m._aplicar_estado_sim(o, datos)
                o["levantar"] = None
                return "final"
            if estado == 404 and isinstance(datos, dict):
                o["lev_incierto"] = False
                o["levantar"] = None  # El proveedor no la tiene: el seguimiento la da por perdida (y está vetada).
                return "final"
            self._otro_intento(o, "levantar", f"consulta con HTTP {estado}")
            return "esperar"

    def _levantar(self, o: dict) -> None:
        m = self.m
        pedido = o["levantar"]
        if o.get("incierta"):
            if self._resolver_incierta(o) == "esperar":
                return
        if o.get("lev_incierto"):
            if self._consultar_levantamiento(o) != "activa":
                return
        with m.candado:
            if o.get("levantar") is None:
                return
            if o["estado"] in ("por_enviar", "espera_ratificacion") and not o.get("incierta"):
                # Nunca salió: se anula sin tocar al proveedor.
                o["estado"] = "levantada"
                o["anulada"] = True
                o["finalizada_min"] = r3(m.ahora())
                o["levantamiento"] = {"min": o["finalizada_min"], "juez_id": pedido["juez_id"],
                                      "juez": m.nombre_juez(pedido["juez_id"]), "motivo": pedido["motivo"],
                                      "reclamo": pedido.get("reclamo")}
                m.auditar("orden_levantada", "sistema", exp=o["exp"], datos={
                    "orden_id": o["orden_id"], "anulada": True, "motivo": pedido["motivo"],
                    "reclamo": pedido.get("reclamo"), "entrada": pedido.get("entrada")})
                o["levantar"] = None
                return
            if o["estado"] not in ("recibida", "aplicada"):
                o["levantar"] = None
                return
        juez, est, motivo = self._elegir_firmante(o, pedido["juez_id"])
        if est is None:
            return
        with m.candado:
            if juez is not None:
                ok, mot = m.puede_firmar_con(juez, dict(est, minuto_actual=self._minuto_ahora(est)))
                if not ok:
                    juez, motivo = None, mot
            if juez is None:
                if not pedido.get("en_espera"):
                    # Lo decidió un juez que ya no puede firmar: queda constancia y lo firma el entrante al ratificar.
                    pedido["en_espera"] = True
                    m.auditar("orden_en_espera", "sistema", exp=o["exp"], datos={
                        "orden_id": o["orden_id"], "accion": "levantar", "juez_id": pedido["juez_id"],
                        "entrada": pedido.get("entrada"), "reclamo": pedido.get("reclamo"),
                        "motivo": motivo or "El juez que decidió el levantamiento ya no está de turno."})
                    m._marcar()
                return
            if m._foto:
                return
            firma = m.usuarios.firmar_con(juez, sello.firma_levantamiento, o["orden_id"], juez)
            pedido["enviado"] = {"juez_id": juez, "firma": firma}
            # Queda también en la orden: si el pedido se descarta (p. ej. un 404) y después el proveedor la muestra
            # levantada, la entrada orden_levantada lleva igual la firma y el juez del POST que se mandó.
            o["lev_enviado"] = dict(pedido["enviado"], motivo=pedido.get("motivo"), reclamo=pedido.get("reclamo"),
                                    entrada=pedido.get("entrada"), pedido_por=pedido.get("juez_id"))
            pedido.pop("en_espera", None)
            m.guardar()  # si la plataforma muere con el POST en camino, al reanudar sabe quién firmó
            m._posts_en_curso += 1
        try:
            estado, datos = m.cliente.levantar(o["proveedor"], o["orden_id"],
                                               {"juez_id": juez, "firma": firma, "motivo": pedido["motivo"]})
        except ErrorRed as err:
            with m.candado:
                m._posts_en_curso -= 1
                self._marcar_incierta(o, f"error de red: {err}", campo="lev_incierto")
            return
        except BaseException:
            with m.candado:
                m._posts_en_curso -= 1
            raise
        with m.candado:
            m._posts_en_curso -= 1
            if estado == 200 and isinstance(datos, dict):
                if datos.get("aplicada_min") is not None and o.get("aplicada_min") is None:
                    o["aplicada_min"] = datos["aplicada_min"]
                m._registrar_levantamiento(o, datos.get("finalizada_min"), por_consulta=False)
            elif estado == 404 and isinstance(datos, dict):
                o["levantar"] = None  # El proveedor no la tiene: el seguimiento la da por perdida.
            elif estado in (400, 401, 403, 422) and isinstance(datos, dict) and isinstance(datos.get("error"), str):
                pedido["t_rechazo"] = time.monotonic()
                m.alerta(f"{o['proveedor']} no aceptó el levantamiento de {o['orden_id']}: HTTP {estado} "
                         f"({datos['error']}). Se reintenta.", clave=f"lev-rechazo-{o['orden_id']}", exp=o["exp"])
            else:
                # 409 (ya no está activa) o una respuesta ajena: se consulta antes de decidir.
                self._marcar_incierta(o, f"HTTP {estado}", campo="lev_incierto")
                if estado == 409:
                    o["t_error"] = None  # se consulta ya
