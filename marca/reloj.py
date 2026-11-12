"""Reloj del partido: estima el minuto entre consultas al simulador.

Contratos (sección 6 y desvíos 27-28 de la especificación):

- Cada lectura lleva el instante (monotónico) en que se EMITIÓ el pedido y el de la respuesta. Las lecturas se
  ordenan por el pedido, no por la llegada: una respuesta de un pedido anterior al de la última lectura aceptada
  se descarta sin mover nada. Una respuesta que llega tarde nunca se toma como un reinicio del simulador.
- Convención de la base de tiempo: la lectura se ancla en el instante del PEDIDO. El servidor calculó el minuto
  en algún momento entre el pedido y la respuesta; anclarlo al pedido hace que la estimación quede siempre por
  encima del minuto real (nunca por debajo), que es el lado seguro para no firmar tarde.
- Retroceso: solo con una lectura de un pedido posterior que quede por debajo de la última aceptada menos un
  umbral = max(1,0 min; (duración del pedido + 1 s) × acelerar / 60), y confirmada por una segunda lectura
  consecutiva igual de baja. Si después las lecturas vuelven a ser coherentes con la línea de tiempo anterior,
  la bandera se limpia sola.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Optional

# «Nunca» para un instante de time.monotonic(): su origen no está definido (en la Python 3.9 del sistema arranca
# cerca de 0 en cada proceso), así que un 0 por defecto NO significa «hace mucho». Lo persistido guarda None.
NUNCA = float("-inf")


def instante(t) -> float:
    """Un instante monotónico guardado (o None, «nunca») como número comparable."""
    return NUNCA if t is None else float(t)


RETROCESO_MIN = 1.0  # umbral mínimo (min de partido) para sospechar que reiniciaron el simulador
DURACIONES_RECIENTES = 5

# Lo que devuelve `actualizar`:
ACEPTADA = "aceptada"          # la lectura movió (o confirmó) el reloj
IGNORADA = "ignorada"          # pedido anterior al de la última lectura aceptada, o atrasada dentro del umbral
SOSPECHA = "sospecha"          # primera lectura baja: no se mueve nada todavía
RETROCESO = "retroceso"        # segunda lectura baja seguida: retroceso declarado
DESPEJADO = "despejado"        # las lecturas volvieron a la línea de tiempo anterior: la bandera se limpió


class Reloj:
    def __init__(self) -> None:
        self._candado = threading.Lock()
        self.minuto_ultimo: Optional[float] = None
        self.t_ultimo = 0.0               # ancla de la estimación: instante del pedido de la lectura aceptada
        self.t_pedido_ultimo = -1e18      # pedido de la última lectura aceptada (orden de las lecturas)
        self.acelerar = 1.0
        self.fin_min: Optional[float] = None
        self.retrocedio = False
        self._sospecha: Optional[dict] = None
        self._anterior: Optional[dict] = None   # línea de tiempo previa al retroceso declarado
        self._duraciones: deque = deque(maxlen=DURACIONES_RECIENTES)

    # --- lecturas --------------------------------------------------------------------------

    def actualizar(self, minuto: float, acelerar: Optional[float] = None, fin_min: Optional[float] = None,
                   t_pedido: Optional[float] = None, t_respuesta: Optional[float] = None) -> str:
        """Registra una lectura. Devuelve ACEPTADA, IGNORADA, SOSPECHA, RETROCESO o DESPEJADO."""
        ahora_t = time.monotonic()
        t_respuesta = ahora_t if t_respuesta is None else float(t_respuesta)
        t_pedido = t_respuesta if t_pedido is None else float(t_pedido)
        with self._candado:
            if acelerar:
                self.acelerar = float(acelerar)
            if fin_min is not None:
                self.fin_min = float(fin_min)
            minuto = float(minuto)
            if self.minuto_ultimo is None:
                self._aceptar(minuto, t_pedido)
                return ACEPTADA
            if t_pedido < self.t_pedido_ultimo:
                return IGNORADA  # pedida antes que la última aceptada: llegó tarde, no dice nada nuevo
            dur = max(0.0, t_respuesta - t_pedido)
            umbral = max(RETROCESO_MIN, (dur + 1.0) * self.acelerar / 60.0)

            if self.retrocedio and self._anterior is not None:
                # ¿Volvió a la línea de tiempo anterior? (la lectura baja era de otro lado, o el simulador volvió)
                esperado = self._anterior["minuto"] + (t_pedido - self._anterior["t"]) * self.acelerar / 60.0
                if minuto >= self._anterior["minuto"] - umbral and abs(minuto - esperado) <= umbral + \
                        dur * self.acelerar / 60.0:
                    self.retrocedio = False
                    self._anterior = None
                    self._sospecha = None
                    self._aceptar(minuto, t_pedido)
                    return DESPEJADO

            if minuto < self.minuto_ultimo - umbral:
                if self._sospecha is None:
                    self._sospecha = {"minuto": minuto, "t": t_pedido}
                    return SOSPECHA
                # Segunda lectura baja seguida: retroceso confirmado. El reloj sigue a la nueva línea de tiempo.
                self._anterior = {"minuto": self.minuto_ultimo, "t": self.t_ultimo}
                self._sospecha = None
                self.retrocedio = True
                self._aceptar(minuto, t_pedido, forzar=True)
                return RETROCESO

            self._sospecha = None  # una lectura coherente descarta la sospecha
            if minuto < self.minuto_ultimo:
                # Atrasada pero dentro del umbral (redondeo, pedidos casi simultáneos): no atrasa la estimación.
                self.t_pedido_ultimo = t_pedido
                return IGNORADA
            self._aceptar(minuto, t_pedido)
            return ACEPTADA

    def _aceptar(self, minuto: float, t_pedido: float, forzar: bool = False) -> None:
        if forzar or self.minuto_ultimo is None or minuto >= self.minuto_ultimo:
            self.minuto_ultimo = minuto
            self.t_ultimo = t_pedido
        self.t_pedido_ultimo = t_pedido

    # --- latencia ---------------------------------------------------------------------------

    def registrar_duracion(self, segundos: float) -> None:
        """Duración de un GET /estado fresco (pedido → respuesta, en segundos reales)."""
        with self._candado:
            self._duraciones.append(max(0.0, float(segundos)))

    def duracion_reciente(self) -> float:
        """La mayor de las últimas duraciones medidas de /estado (0 si no hay)."""
        with self._candado:
            return max(self._duraciones) if self._duraciones else 0.0

    # --- estimación -------------------------------------------------------------------------

    def _estimar(self) -> float:
        if self.minuto_ultimo is None:
            return 0.0
        return self.minuto_ultimo + (time.monotonic() - self.t_ultimo) * self.acelerar / 60.0

    def ahora(self) -> Optional[float]:
        with self._candado:
            if self.minuto_ultimo is None:
                return None
            return self._estimar()

    @property
    def sospechoso(self) -> bool:
        """Hay una lectura baja sin confirmar (puede ser el comienzo de un reinicio del simulador)."""
        with self._candado:
            return self._sospecha is not None

    def segundos_desde_lectura(self) -> float:
        with self._candado:
            return time.monotonic() - self.t_ultimo if self.minuto_ultimo is not None else 1e9
