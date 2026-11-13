# Marca Personal

**Bloqueo en vivo con juez, en minutos, cuidando a los sitios ajenos.**

Marca Personal es un prototipo de plataforma federal de órdenes de bloqueo en vivo, hecho para el «Desafío Fútbol» de QualyData (Hackathon Argentina Space 2026, Salta).
Mientras se juega, arma un expediente con evidencia sellada por cada stream pirata y se lo pone adelante al juez de turno.
Con su firma, manda la orden a cada proveedor de internet en el tipo de bloqueo que acepta, sigue la confirmación y reintenta si falla.
Al terminar el partido, los bloqueos vencen. Atiende reclamos, publica un registro de transparencia y exporta todo en un paquete que se verifica sin conexión.
Corre contra el simulador oficial: los datos son ficticios y no se bloquea nada real. No es asesoramiento legal.

‹equipo›

## Qué lo distingue

- **Marcamos a la filtración, no perseguimos servidores.** En el fútbol, la marca personal sigue al jugador, no a la zona. La marca de agua trae el código de sesión de la cuenta que filtra, y ese código no cambia cuando el pirata se muda. Hay un expediente por filtración y cada servidor nuevo es una ubicación más. Si el juez lo autoriza en su orden marco, la plataforma sigue a esa filtración sola: es el **seguimiento** (la prensa habló de «bloqueo dinámico»). La casilla viene destildada.
- **El sello de la evidencia va dentro del número de orden que firma el juez.** Cada proveedor guarda la orden, así que guarda la prueba. «Ni nosotros podemos falsificarlo»: `herramientas/falsificar.py` arma un expediente falso con nuestras propias claves; nuestra verificación sola no puede notarlo, y lo avisa; el cruce con el registro del simulador lo delata.
- **Cada proveedor tiene una lista que su equipo lee solo** y un cliente de referencia que la aplica. El proveedor chico no depende de que alguien mire una pantalla.
- **El daño colateral tiene una regla escrita.** Por IP solo si el servidor es del pirata y de nadie más; ante la duda, por dominio. La plataforma separa lo que **vio** (el nombre del stream y el de su página) de lo que **infirió** (otros nombres del mismo dominio en ese servidor). Si un nombre inferido reclama con fundamento, el reclamo corrige la inferencia y se levanta todo lo que dependía de ella, con firma del juez y durante el partido. Si reclama un nombre que la plataforma vio transmitiendo, el reclamo no prospera. Cualquiera puede consultar «¿Tu sitio quedó bloqueado?».

## Resultados medidos

Partido de práctica oficial a ×20, verificador oficial (`evaluacion/verificar.py`). Firman **jueces automáticos de ensayo**, programas que firman 0,3 minutos después de cada pedido: no son personas. Minutos de partido.

| Medida | Seguimiento autorizado | Casilla destildada (todo firmado una por una) |
|---|---|---|
| Servidores pirata bloqueados | 7 de 7 | 7 de 7 |
| Clientes cubiertos en cada servidor | 100 % | 100 % |
| Visibilidad residual promedio (clientes por minuto que igual vieron el stream) | 3,3 % | 5,1 % |
| Órdenes recibidas / rechazadas | 33 / 0 | 39 / 0 |
| Daño colateral · falsos positivos · firmas fuera de turno | 0 · 0 · 0 | 0 · 0 · 0 |
| Bloqueos por IP activos después del partido | 0 | 0 |
| Detección → firma → primer proveedor → todos, firmadas una por una (`ord-`) | 0,39 → 0,93 → 6,56 | 0,72 → 1,35 → 9,01 |
| Ídem, ampliaciones automáticas (`amp-`) | 0,04 → 0,48 → 7,35 | no hay |

**Con un juez simulado a ritmo humano.** Es un programa, no una persona: atiende de a un pedido y tarda 8 o 20 segundos reales por decisión, también para firmar la orden marco y ratificar lo heredado (`herramientas/ensayo.py --demora-juez-s 8`). Sirve para ver cuánto pesa el tiempo de decisión del juez cuando el partido va acelerado, y cuánto ayuda el seguimiento. Mismo partido de práctica; bloqueados y residual del verificador oficial; tiempos en minutos de partido.

| Ritmo | Casilla destildada: bloqueados · residual | Firmadas una por una | Seguimiento autorizado: bloqueados · residual | Firmadas una por una | Ampliaciones automáticas |
|---|---|---|---|---|---|
| ×6 · 8 s (0,8 min de partido) | 7 de 7 · 5,2 % | 0,82 → 1,31 → 7,77 | 7 de 7 · 4,0 % | 0,82 → 1,30 → 8,94 | 0,01 → 0,52 → 6,66 |
| ×6 · 20 s (2 min de partido) | 7 de 7 · 8,5 % | 2,03 → 2,56 → 9,33 | 7 de 7 · 5,6 % | 2,03 → 2,49 → 8,83 | 0,01 → 0,52 → 5,44 |
| ×20 · 8 s (2,67 min de partido) | 7 de 7 · 11,2 % | 3,02 → 3,50 → 8,82 | 7 de 7 · 7,3 % | 3,22 → 3,75 → 10,38 | 0,02 → 0,45 → 5,50 |
| ×20 · 20 s (6,67 min de partido) | 7 de 7 · 31,2 % | 11,50 → 11,97 → 18,71 | 7 de 7 · 21,2 % | 15,08 → 15,64 → 25,06 | 0,07 → 0,66 → 6,72 |

<!-- Si el equipo ensaya con personas, sumar acá su fila con los números del acta y del verificador oficial de esa corrida (ver equipo/PLAN-DEL-EQUIPO.md, «Ensayos con personas»):
| Personas del equipo, ×6, casilla destildada | bloqueados · residual | firma → primer proveedor → todos | — | — | — |
-->

El tiempo hasta «todos» (línea 264) lo fija el simulador: FibraValle tarda de 4,2 a 7,8 minutos en aplicar y Cumbre falla el 35 % de las órdenes (`datos/proveedores.json` y `simulador/servidor.py`, línea 192, del repo del desafío). La plataforma reintenta al instante.

Otros ensayos automáticos: partido espejo con trampas, 9 de 9 bloqueados y residual 3,2 %; IP compartida bloqueada a propósito, 3 bloqueos con daño colateral y 1 de 1 reclamos resueltos por levantamiento; plataforma reiniciada en el minuto 30, 7 de 7 y 0 órdenes duplicadas; a ×60, 7 de 7; con demora de red y fallas, 7 de 7.

**El partido final.** Lo que exporta la plataforma queda en [`entrega/partido-final/`](entrega/partido-final/) y se verifica con los comandos de «Cómo verificar la entrega». Mientras tanto, [`entrega/partido-practica/`](entrega/partido-practica/) trae el mismo paquete generado en un partido de práctica (jueces automáticos, ×20, con seguimiento), y se verifica con los mismos comandos. Los números de arriba son del partido de práctica.

<!-- Si el final se corre antes del cierre, una línea acá con su acta: quién firmó (persona del equipo o de la organización), con qué casilla, servidores bloqueados, órdenes ord- y amp-, rechazadas, fuera de turno; y, si la organización da su salida, los números del verificador oficial. -->

## Cómo correrlo

Python 3.9 o más nuevo, sin dependencias. Cuando decimos «línea N», es la del README oficial del desafío (la consigna).

```bash
# 1. Simulador oficial, desde la carpeta del repo del desafío (otra terminal)
python3 simulador/servidor.py --escenario datos/escenario_practica.json --acelerar 6

# 2. Desde esta carpeta: revisión previa (no manda órdenes) y la plataforma
python3 -m marca chequear --simulador http://127.0.0.1:8080
python3 -m marca servir --simulador http://127.0.0.1:8080
```

A ×6 el partido dura 17,5 minutos de reloj (línea 120). Pantallas: `http://127.0.0.1:8700/juez` (cada juez), `/sala` (fiscalía), `/transparencia` (cualquiera) y `/orden/<número>` (el proveedor). Usuarios de demostración: [`config/jueces_demo.json`](config/jueces_demo.json); los dos jueces en una computadora, con una ventana normal y una de incógnito. `--sin-dinamica` apaga el seguimiento en toda la plataforma: ninguna orden marco lo puede autorizar.

**Para abrir la plataforma a la red** (el celular del juez, otra computadora). Las contraseñas de demostración están publicadas en este repo: sirven solo en la propia máquina. Con un `--host` que no sea local y esas contraseñas, `servir` no arranca. Primero se arman contraseñas nuevas:

```bash
python3 -m marca claves --salida config/jueces_final.json
python3 -m marca chequear --simulador http://127.0.0.1:8080 --host 0.0.0.0 --config config/jueces_final.json
python3 -m marca servir --simulador http://127.0.0.1:8080 --host 0.0.0.0 --config config/jueces_final.json
```

`claves` copia usuarios, roles y claves de firma de la demostración y pone contraseñas de ingreso nuevas, al azar. El archivo queda legible solo por su dueño y fuera de git. No pisa uno que ya existe. No imprime las contraseñas: el operador las lee del archivo y se las da a cada juez en persona. La página va por `http`: conviene una red propia con clave.

**Dejá correr el simulador y la plataforma hasta el minuto 110 o más** (fin + 5 de gracia, línea 130). La plataforma exporta sola a `salida/entrega/`. Si se corta antes, el verificador oficial no evalúa los bloqueos activos después del partido (`evaluacion/verificar.py`, línea 126). Después:

```bash
python3 -m marca exportar --destino salida-prueba/entrega
python3 -m marca verificar salida-prueba/entrega --config config/jueces_demo.json --registro-simulador "<repo del desafío>/salida/registro.jsonl"
```

Y el verificador oficial, desde el repo del desafío: `python3 evaluacion/verificar.py --log salida/registro.jsonl` (línea 133).

**Sin personas:** `python3 herramientas/ensayo.py --repo-desafio "<repo del desafío>" --acelerar 20` levanta todo, firma con jueces automáticos (solo ensayos) y corre los dos verificadores; con `--alcance ubicacion`, firma una por una. **Pruebas:** `DESAFIO_FUTBOL_REPO="<repo del desafío>" python3 -m unittest discover -s tests` (sin la variable, las del partido espejo buscan el repo en `../desafio-futbol` y, si no está, se saltean). Operación del final: [`docs/OPERACION.md`](docs/OPERACION.md); diseño: [`docs/ESPECIFICACION.md`](docs/ESPECIFICACION.md); el desafío explicado: [`docs/EL-DESAFIO.md`](docs/EL-DESAFIO.md). **En línea:** https://demo-production-642eae5b.up.railway.app: partidos de práctica uno detrás de otro; si nadie firma en 25 segundos, firma un juez automático de ensayo (cómo se arma: [`docs/OPERACION.md`](docs/OPERACION.md), «Demo en línea»).

### Para un proveedor

Lo que obliga es la orden: objetivo y vencimiento. `/orden/<número>` la muestra en castellano, con las líneas para MikroTik, nftables, Unbound y BIND. Tu equipo lee solo su lista (`/proveedor/<id>/vigentes.json`, `dominios.txt`, `ips.txt`, `unbound.conf`, `rpz.zone`) con el cliente de referencia:

```bash
python3 herramientas/cliente_proveedor.py --plataforma http://127.0.0.1:8700 --proveedor cumbre --una-vez
```

Muestra «+ BLOQUEAR …» y «− QUITAR …»; con `--salida-unbound` o `--salida-ips` escribe los archivos y con `--al-cambiar` corre tu comando de recarga (al arrancar, cuando cambia un archivo y, si falla, hasta que ande). `--estado` guarda lo aplicado (por defecto, `.<nombre>.estado.json` al lado de la primera salida). Si la plataforma se cae, quita cada bloqueo a su hora: ninguno dura más de 6 horas desde la última lista buena, y una orden levantada nunca vuelve. `--una-vez` sale con 0 (todo aplicado), 1 (no hubo lista válida), 2 (argumentos inválidos), 3 (no pudo escribir) o 4 (falló la recarga). En el simulador, la confirmación va por la API de cada proveedor (líneas 91 y 150 a 152).

## La decisión abierta

La consigna dice: «la plataforma firma con la clave de un juez solo después de que ese juez inició sesión y aprobó la orden. Nadie firma en su nombre» (línea 203). También pide que la propuesta normativa hable de una «orden marco» (línea 250) y cuenta como antecedente «un mecanismo dinámico que actualiza la restricción cuando los sitios cambian de dominio» (línea 16).

Cómo funciona. Al empezar su turno, el juez firma una **orden marco** con los límites por escrito. Trae la casilla «Autorizo el seguimiento de la misma filtración», destildada. Si la tilda, en cada pedido elige entre «Firmar solo este servidor» y «Firmar y seguir a esta filtración». Si eligió seguir y la misma sesión aparece en otro servidor, la plataforma emite sola una **ampliación automática** (número `amp-`; las firmadas en persona son `ord-`). Solo si el juez está de turno y tiene su bandeja abierta, la evidencia está completa y sellada, y el bloqueo nuevo no alcanza a sitios ajenos: si el servidor nuevo comparte la IP con otros, se bloquea solo el nombre del stream. Si falta algo, le llega como pedido. Se le avisa y puede frenarlo («Frenar el seguimiento»): «Frenar las próximas mudanzas» o «Frenar y levantar la ampliación».

Es defendible: en Francia y el Reino Unido el juez interviene en la orden inicial y la lista se actualiza después (líneas 29 y 30), y la Recomendación (UE) 2023/1018 pone las «acciones de cesación dinámicas» «bajo el control de una autoridad judicial» (punto 13). Es discutible al pie de la letra: la orden `amp-` sale con la clave de demostración del juez sin que él apruebe ese servidor.

**Postura del equipo:** el seguimiento está apagado por defecto y lo decide quien firma; se les pregunta a los mentores el jueves 12; si no hay respuesta, el partido final se corre con la casilla destildada (cada orden firmada en persona) y el seguimiento se muestra medido sobre un partido de práctica.

<!-- Si los mentores respondieron, o el final se corrió con otra casilla, cambiar la postura de arriba por lo que pasó (equipo/ANTES-DE-ENTREGAR.md). -->

## Cómo verificar la entrega

```bash
python3 -m marca verificar entrega/partido-final --huella <la huella publicada>
```

Los mismos comandos sirven para el ejemplo del partido de práctica, que trae al lado el registro del simulador de esa corrida y la salida del verificador oficial:

```bash
python3 -m marca verificar entrega/partido-practica --huella 6286add95f44b912a056207b34c2285430161d6d23cec0bb2ebc598345b0ea1c \
  --config config/jueces_demo.json --registro-simulador entrega/partido-practica-registro-simulador.jsonl
```

`exportar` imprime la «Huella del paquete» (el sha256 de `MANIFIESTO.json`), y se publica apenas se exporta. Es la que quedó publicada en `/transparencia` al cerrar el partido: con el partido cerrado, `exportar` entrega siempre ese paquete y esa huella, con la plataforma prendida o apagada, las veces que se exporte y a cualquier destino. `verificar --huella` la compara. Con `--config config/jueces_demo.json` comprueba también cada firma; con `--registro-simulador <registro.jsonl>` cruza todo con el registro del simulador, que en el final tiene la organización (línea 275), incluidos el minuto de aplicación, el vencimiento y el estado final de cada orden. Sin el registro, si no hay fallas, termina en «Resultado: coherente consigo mismo (sin cotejar con el registro oficial del simulador).» y avisa que eso no prueba que el paquete sea verdadero; con el registro, «Resultado: todo verifica.». Recalcula la cadena de auditoría, el hash de cada captura, el sello de cada número de orden y que cada `amp-` cuelgue de una orden marco con seguimiento. Si cambia un byte, dice en qué archivo y en qué campo.

**«Ni nosotros podemos falsificarlo», en cuatro comandos** (a ×20, unos 6 minutos):

```bash
python3 herramientas/ensayo.py --repo-desafio "<repo del desafío>" --acelerar 20 --salida salida-ensayo/A
python3 herramientas/falsificar.py salida-ensayo/A/marca/entrega salida-ensayo/falsificada --config config/jueces_demo.json
python3 -m marca verificar salida-ensayo/falsificada --config config/jueces_demo.json
python3 -m marca verificar salida-ensayo/falsificada --config config/jueces_demo.json --registro-simulador salida-ensayo/A/registro.jsonl
```

`falsificar.py` cambia la IP de una ubicación en una copia y recalcula todo, firmas incluidas. El tercer comando no encuentra fallas, pero termina en «Resultado: coherente consigo mismo (sin cotejar con el registro oficial del simulador).» y avisa que eso no prueba que sea verdadero: la verificación propia sola no alcanza, y lo dice. El cuarto da ✗: los proveedores guardaron las órdenes con el sello verdadero. Y las huellas del original y del falso son distintas.

## Supuestos y límites

- **La filtración es la marca de agua completa**, con su código de sesión. La plataforma comprueba el prefijo contra `GET /partido` y sella la captura tal como llega.
- **Una IP es exclusiva del pirata** si todos los nombres que el DNS pasivo ve en ella son suyos. Ante la duda, dominio. Al licenciatario en su dominio, nunca.
- **Todo bloqueo vence con el partido**, también los de dominio.
- **«Presente» es la bandeja del juez abierta** (la plataforma la vio en los últimos 90 segundos de reloj): prueba que la pantalla está abierta, no que el juez la mire. Tener abierto el registro público no cuenta, y cerrar sesión corta la presencia en el acto.
- **Cambio de turno:** nadie firma en los últimos 2 segundos de reloj de un turno ni en el primer medio segundo del siguiente.
- **La clave de demostración del juez.** El simulador solo acepta órdenes firmadas con ella (líneas 195 a 203): la plataforma la guarda y firma con ella, también las ampliaciones. No está en la API, ni en la auditoría, ni en lo exportado.
- **La lista del proveedor no va firmada** y se lee por `http`. El kit se revisó con la documentación oficial, no en equipos reales.
- **El bloqueo por dominio no alcanza** a quien usa DNS cifrado, otro DNS o una VPN.
- **El residual por ubicación de la sala es una estimación**; vale el del verificador oficial.
- **El corte en origen es una constancia**: en el simulador no hay a quién avisarle.
- **El estado se guarda en archivos**: alcanza para un partido, no para producción.

### Límites conocidos

- **La inferencia puede fallar** en un hosting que reparte subdominios entre clientes distintos. Si el pirata transmite desde `vivo.hosting.test`, publica en `hosting.test/vivo` y en el mismo servidor está `panaderia.hosting.test`, la plataforma toma a la panadería como parte del sitio pirata. El reclamo de la panadería lo corrige: lo inferido de ese dominio se levanta en todos los servidores del pirata y en ese dominio no se vuelve a inferir; lo que la plataforma vio transmitir sigue bloqueado por nombre, y los pedidos que esperaban firma se rehacen con la inferencia corregida (la tarjeta dice «La propuesta cambió…»).
- **Las sesiones viven en memoria.** Si la plataforma se reinicia, cada juez vuelve a ingresar. La plataforma lo espera hasta 90 segundos reales antes de dar por perdida una ampliación; si tarda más, la mudanza le llega como pedido para firmar en persona. Una orden que quedó sin respuesta no se reenvía con el mismo número antes de 12 segundos reales desde el reinicio.
- **Unbound corta también los subdominios** del nombre bloqueado: `vivo.pirata.test` se lleva a `a.vivo.pirata.test`. Los sitios ajenos conocidos que cuelgan de ese nombre van en `unbound.conf` como `local-zone: "<ajeno>." transparent` y siguen resolviendo. La página `/orden/<número>` sola no trae esas líneas: el proveedor que usa Unbound tiene que tomar su lista.
- **El cliente de referencia es más estricto que la plataforma con IPv6 de transición** (6to4, Teredo, `64:ff9b::/96`): no aplica esos objetivos.
- **Un rechazo no es definitivo si el servidor se sigue viendo:** una detección posterior vuelve al juez como pedido nuevo. Un servidor rechazado nunca se bloquea solo, tampoco si vuelve con otro nombre en la misma IP o con el mismo nombre en otra IP, ni si lo trae la mudanza de otra filtración con seguimiento: llega como pedido para decidir en persona.
- **Órdenes que no bloquearon:** una firma en los últimos segundos del partido queda registrada, pero la orden ya no sale, y el juez recibe el aviso. El acta y el expediente separan tres causas: «no enviada (el partido terminaba)», «no enviada (el juez entrante no recibió el turno)» o «sin confirmar (se envió y, al cierre, el proveedor no la tenía)»; la sala y la bandeja lo dicen con «Sin bloquear: …» o «Sin confirmar: …».
- **Un paquete se verifica con la misma versión del código que lo exportó:** `verificar` vuelve a generar el LEEME y las actas y los compara. Después del partido final no se toca el código.
- **Las contraseñas de demostración** (`config/jueces_demo.json`) están publicadas: sirven solo en la propia máquina. Para la red, `marca claves`.

## Qué existía antes del evento

Nada de código. Todo se escribió durante el evento, con asistencia de herramientas de inteligencia artificial. Usa solo la biblioteca estándar de Python y HTML, CSS y JavaScript sin bibliotecas externas. El simulador y el verificador oficiales se usan sin copiarlos.

## Qué hay en el repositorio

```
marca/          la plataforma: evidencia, sello, auditoría, turnos, orden marco, kit, API y pantallas
config/         usuarios y claves de demostración
herramientas/   ensayo, juez automático, partido espejo, falsificar.py, cliente_proveedor.py, demo en línea
tests/          pruebas
Dockerfile      la demo en línea (partidos de práctica en bucle; ver docs/OPERACION.md)
entrega/        propuesta normativa, lo exportado del partido final (acta, expedientes, auditoría, MANIFIESTO.json) y el ejemplo de práctica
docs/           el desafío explicado, las fuentes, la especificación y la operación
```

## Entregables

La consigna pide cinco (líneas 245 a 251), y «lo que se evalúa es lo que está en el repo a la hora de cierre» (línea 253).

| Entregable | Dónde |
|---|---|
| Repositorio público y este README | Este repo |
| Video de hasta 3 minutos | ‹enlace al video en Hacki› |
| Expediente y auditoría del partido final | [`entrega/partido-final/`](entrega/partido-final/) |
| Ejemplo de expediente y auditoría (partido de práctica) | [`entrega/partido-practica/`](entrega/partido-practica/), con el registro del simulador ([`entrega/partido-practica-registro-simulador.jsonl`](entrega/partido-practica-registro-simulador.jsonl)) y la salida del verificador oficial ([`entrega/partido-practica-verificador-oficial.json`](entrega/partido-practica-verificador-oficial.json)) |
| Propuesta normativa de una página | [`entrega/propuesta-normativa.md`](entrega/propuesta-normativa.md) y [`.pdf`](entrega/propuesta-normativa.pdf) |
| Pitch | En vivo, el viernes |
