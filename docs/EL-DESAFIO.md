# El desafío, explicado

Para quien no leyó la consigna. La fuente es el `README.md` del repo oficial `qualydata-org/desafio-futbol` («la consigna»). Cada dato de la consigna lleva su línea: «(l. 54)». Lo que sale de otros archivos de ese repo (los datos del partido, el simulador, el verificador) dice de qué archivo y de qué línea sale. Los hechos de prensa y de derecho tienen su enlace en `FUENTES.md`. Los números que medimos nosotros salen de corridas con el código congelado; cada uno dice qué ensayo lo midió.

**En una frase.** La organización da el problema, la cancha (un simulador con datos ficticios), las reglas del juego (el formato de la orden, los turnos de los jueces, los proveedores con sus demoras) y la vara (un verificador automático y una rúbrica con puntos). **No da la solución.** Cómo se arma la evidencia, cómo decide el juez, cuándo se bloquea una IP y cuándo un dominio, cómo se entera el proveedor chico, cómo se atienden los reclamos y qué norma hace falta: todo eso lo decide cada equipo. Eso es lo que mira el jurado.

Orden de este documento: 1) el problema; 2) qué deja fijo la organización y qué deja abierto; 3) cómo se evalúa, criterio por criterio; 4) las trampas; 5) cómo responde Marca Personal; 6) lo que sigue en discusión.

---

## 1. El problema

### En criollo

1. Un partido dura dos horas. Un sitio pirata cambia de dominio o de servidor en minutos (l. 9).
2. El bloqueo lo pide el titular de los derechos o una fiscalía (l. 89). En los casos de 2025 y 2026, la fiscalía de ciberdelitos de San Isidro (UFEIC); en 2026, a partir de una presentación de ALIANZA, la alianza contra la piratería audiovisual (l. 13 y 16).
3. Lo ordena un juez. Según la consigna, todo depende de una sola fiscalía y un solo juzgado, el de Garantías N.º 4 de San Isidro (l. 13 y 22).
4. La orden no va directo a los proveedores de internet. Pasa por un intermediario: el ENACOM o las cámaras que agrupan a los proveedores (CABASE y CAPPI), y de ahí a cada uno (l. 15 y 16).
5. No hay un registro al día de todos los proveedores (l. 15). Llegar a los grandes es fácil; llegar a todos, no (l. 9).
6. Cada proveedor aplica la orden con su propio equipo y a su ritmo. Según la consigna, los chicos no pueden reaccionar en tiempo real (l. 18).
7. No hay reglas sobre costos, cuánto dura el bloqueo ni qué se hace después (l. 19). No hay un procedimiento formal ni un canal estándar (l. 22).
8. Por eso llega tarde. Aun con el bloqueo dinámico de 2025, que dejaba al fiscal pedir los bloqueos nuevos (DPL News), cada pedido tenía que bajar por el ENACOM o por las cámaras hasta cada proveedor. Los plazos que se conocen para esa cadena se cuentan en horas: en los oficios por apuestas, al ENACOM le dan 72 horas para informar (iProfesional, 2018), y en la provincia de Buenos Aires el juez de garantías de turno tiene hasta 6 horas para resolver una extrema urgencia (Código Procesal Penal bonaerense, art. 23 bis). (La comparación es lectura nuestra.)
9. Y por eso rompe cosas ajenas: para ir rápido se bloquea una IP, y la IP de una CDN (una red que reparte el contenido de muchos sitios desde las mismas direcciones) o de un hosting compartido aloja también sitios legítimos (l. 20 y 57). Pasó en la Argentina en 2011 (una IP con más de un millón de blogs detrás) y en Italia en 2024 (una IP de Cloudflare).
10. Lo que piden: una plataforma que haga toda esa cadena durante el partido (l. 38), con un juez de turno que firma (l. 73), que llegue a todos los proveedores y no solo a los grandes (l. 9), y sin bloquear sitios legítimos (l. 263).

### En técnico

- **Qué se bloquea.** El servidor que entrega el video (host, IP y red, o ASN), no la página que muestra el reproductor: «Bloquear la página que muestra el reproductor no corta el video» (l. 56).
- **Dos tipos de bloqueo.** Por IP (el proveedor descarta el tráfico hacia esa dirección) o por dominio (el DNS del proveedor deja de resolver ese nombre). La orden dice `tipo` `ip` o `dominio`, y cada proveedor declara cuáles acepta (l. 190).
- **Cómo se sabe que es el partido.** La señal oficial lleva una marca de agua. El detector la extrae y la plataforma la compara con los prefijos válidos de `GET /partido`; además descarta al licenciatario que retransmite legalmente en su propio dominio (l. 55, 144 y 173).
- **Cómo se sabe si una IP es compartida.** Con el DNS pasivo: qué nombres se vieron en esa IP (l. 146 y 147).
- **Cómo se firma.** Un HMAC-SHA256 con la clave de demostración del juez sobre `orden_id|tipo|objetivo|vence_min|juez_id` (l. 195 a 199). En la vida real sería una firma digital (l. 203).
- **Cómo llega al proveedor.** `POST /proveedores/<id>/ordenes`; el proveedor la pasa a `aplicada`, o a `fallida`, o la rechaza al recibirla (l. 150 y 209).
- **Cuándo vence.** `vence_min`, entero, en minutos de partido; al llegar ese minuto el proveedor levanta el bloqueo solo (l. 192).
- **El reloj.** Todo se mide en minutos de partido desde el minuto 0; el partido termina en el 105 (l. 138), y hay 5 minutos de gracia (l. 130).

### Lo que pasó de verdad

La consigna cuenta dos casos (l. 13 a 20). La prensa agrega detalles y en un punto la contradice. Lo separamos.

**Mayo y junio de 2025: el primer bloqueo en vivo**

| | Qué dice la consigna | Qué dice la prensa |
|---|---|---|
| Cuándo | «Mayo de 2025» (l. 13). | Dos partidos: la final de la Champions, el 31 de mayo, y la del Torneo Apertura, el 1 de junio (La Nación, Baires Para Todos, DPL News). |
| Quién | Lo impulsó la UFEIC de San Isidro y lo ordenó el Juzgado de Garantías N.º 4 de San Isidro (l. 13). | Coincide. Baires Para Todos, la nota que cita la consigna, lo llama «prueba piloto»: la fiscalía identificaba durante los partidos los sitios y las IP, y los proveedores tenían que tener técnicos disponibles. |
| Qué tipo de bloqueo | El de IP rigió solo durante los partidos; el de DNS quedó permanente (l. 14). | Solo lo dice Baires Para Todos, y antes de los partidos. No encontramos una segunda fuente. |
| Por dónde viajó | Por las cámaras CABASE y CAPPI, porque el ENACOM no tenía un registro actualizado de proveedores (l. 15). | **DPL News dice otra cosa:** que la orden «fue librada» al ENACOM; La Nación también habla de la «participación activa» del ENACOM. No pudimos aclarar si se usaron las dos vías. |
| Qué tenía de dinámico | No lo dice. | DPL News: la orden tenía «carácter dinámico» y autorizaba **al fiscal** a pedir bloqueos nuevos e inmediatos cuando los sitios migraban a otro dominio. O sea, la actualización no la volvía a firmar el juez. |
| Objeciones | De CABASE: los proveedores chicos no pueden reaccionar en tiempo real; no hay reglas claras sobre costos, duración del bloqueo ni seguimiento (l. 17 a 20). Ese «seguimiento» de CABASE es qué se hace después del bloqueo; no es el nuestro, que se explica en la sección 5. | Baires Para Todos lo dice más amplio: duda de que todos los proveedores, grandes y chicos, puedan reaccionar en tiempo real. Y aclara que eran consideraciones internas de CABASE, sin postura pública todavía. La de la IP compartida se la atribuye a «proveedores consultados». Después, el presidente de CABASE dijo que la Justicia no debería usar a las cámaras como intermediarias de las notificaciones (DPL News, 2/6/2025). |

Cómo circulan estas órdenes en general (casos de apuestas, no de fútbol): la orden llega al ENACOM, que la manda a CABASE, que avisa a cada socio y deja la decisión en manos de cada uno; al ENACOM le dan 72 horas para informar (iProfesional, 2018). En 2024 el ENACOM se describió como «intermediario entre la justicia y los prestadores de internet», con más de mil casos de apuestas ese año (DPL News, 3/9/2024).

**1 de noviembre de 2026: el Superclásico**

| | Qué dice la consigna | Qué dice la prensa |
|---|---|---|
| Qué pasó | A partir de una presentación de ALIANZA, la UFEIC le pidió al ENACOM el bloqueo de 182 dominios (l. 16). | Coincide (Elonce, Infobae y La Capital; DPL News reproduce a Infobae). La UFEIC le pidió el bloqueo al ENACOM y el ENACOM se lo comunicó a los proveedores de todo el país. Infobae habla de una «resolución judicial» y La Capital dice que el bloqueo funcionó, pero ninguna nota publica la orden ni nombra al juzgado. |
| Lo dinámico | «Un mecanismo dinámico que actualiza la restricción cuando los sitios cambian de dominio» (l. 16). | Infobae: «la justicia autorizó la aplicación de mecanismos de bloqueo dinámico». |
| Lo que nadie dice | — | Ninguna de las notas que leímos nombra al juzgado ni al juez, dice cuánto dura el bloqueo, si es por DNS o por IP, ni **quién decide cada actualización**. |

### Otros países

La consigna trae una tabla (l. 26 a 32) y dice que no encontró ningún país donde cada pedido le llegue en el momento a un juez de turno por una plataforma (l. 34). Nosotros tampoco encontramos uno. Lo que hay son tres modelos:

- **Sin juez, decide un organismo administrativo:** Italia (Piracy Shield, del regulador; los proveedores bloquean en 30 minutos), Grecia, Perú y México (l. 28, 31 y 32), y Brasil, donde bloquea la Ancine desde abril de 2026. En Grecia el regulador bloquea sin demora las direcciones nuevas y una comisión decide después; los proveedores de más de 20 000 abonados tienen 30 minutos.
- **El juez firma solo la orden inicial y las actualizaciones las hace otro** (l. 29 y 30): Reino Unido, donde la High Court fijó criterios y el titular de los derechos identifica los servidores a bloquear, con una lista que se renovaba cada semana de partidos; y Francia, donde desde la Ley 2026-725 (agosto de 2026), si la orden judicial lo prevé, los servicios nuevos se bloquean sin demora durante la transmisión, a través de un sistema bajo control del regulador (ARCOM).
- **La recomendación europea** (2023/1018, no obligatoria) habla de «acciones de cesación dinámicas», pide que queden «bajo el control de una autoridad judicial» y que el bloqueo rija solo durante la transmisión en vivo.

Un antecedente regional del «canal estándar»: en Uruguay, el regulador (URSEC) tiene un sistema en línea para comunicarles las órdenes de bloqueo a los proveedores, que confirman y desbloquean al vencer el plazo. No comprobamos si ahí interviene un juez.

---

## 2. Qué deja fijo la organización y qué deja abierto

**La consigna dice con mucho detalle *qué* tiene que pasar y con qué reglas se juega. Casi no dice *cómo*.**

### Lo fijo: el problema, las reglas del juego y la vara

| Qué | Cómo viene | Dónde |
|---|---|---|
| La tesis | No hay ningún país donde cada pedido le llegue en el momento a un juez de turno por una plataforma: «Eso es lo que les proponemos construir». | l. 34 |
| Datos | Todo ficticio: proveedores, juzgados, jueces, partidos, dominios (`.test`, `.example`) e IP de documentación. No se bloquea nada real. | l. 5 y 242 |
| Simulador | Un programa en Python, sin dependencias, que hace de partido, de proveedores, de DNS pasivo y de sitios que reclaman. El partido dura 105 minutos de partido, entretiempo incluido, y se puede acelerar: con `--acelerar 6` dura 17,5 minutos reales. | l. 101, 112, 120 y 138 |
| La detección | **No hay que detectar nada.** El simulador publica las detecciones ya armadas: página, stream, host, IP, ASN, la marca de agua extraída, la captura y dónde se promocionó. El trabajo es decidir qué hacer con cada una. | l. 145 y 158 a 171 |
| La API | Rutas para leer detecciones, DNS pasivo, juzgados y proveedores, y para enviar, consultar y levantar órdenes. | l. 140 a 154 |
| El formato de la orden | `orden_id`, `expediente_id`, `tipo` (`ip` o `dominio`), `objetivo`, `vence_min` (entero, en minutos de partido), juzgado, juez y firma. El `orden_id` es único por proveedor; si una orden falla, se reenvía con otro. | l. 177 a 193 |
| La firma | HMAC-SHA256 con la clave de demostración del juez sobre `orden_id\|tipo\|objetivo\|vence_min\|juez_id`; para levantar, sobre `LEVANTAR\|orden_id\|juez_id`. «Nadie firma en su nombre.» | l. 195 a 203 |
| Los estados de una orden | `recibida` → `aplicada` → `vencida` o `levantada`; o `fallida` (hay que reenviarla); o rechazada al enviarla. | l. 209 |
| Jueces y turnos | En `datos/juzgados.json`. En la práctica: la jueza del primer turno hasta el minuto 50 y el juez del segundo desde el 50. El final usa los mismos jueces y turnos. | l. 205; `datos/juzgados.json` |
| Proveedores con demoras y fallas | Cuatro, con clientes, tipos de bloqueo que aceptan y un comportamiento (demora y tasa de falla) que la API no muestra: se descubre usándola. | `datos/proveedores.json`; `simulador/servidor.py`, l. 123 a 128 |
| Situaciones del partido | Mudanzas de servidor, CDN y hosting compartido, detecciones que no son la señal, un licenciatario, demoras distintas, un proveedor que solo bloquea por dominio, uno inestable, reclamos y un cambio de turno. El final trae **las mismas situaciones**, con otros sitios, IP y tiempos. | l. 213 a 221 |
| El verificador | `evaluacion/verificar.py`: lee el registro del simulador y lo compara con las respuestas correctas del escenario. El día 3 se corre el mismo script contra el escenario final. | l. 225 a 234 |
| La rúbrica | Cinco criterios con puntos: circuito completo 25, evidencia 25, daño colateral 20, velocidad 15, claridad y propuesta normativa 15. «Propuesta sujeta a las bases y condiciones del hackathon.» | l. 257 a 265 |
| Entregables y cierre | Repo público con README, video de hasta 3 minutos, `entrega/` con el expediente y la auditoría **del partido final**, la propuesta normativa de una página y el pitch. «Lo que se evalúa es lo que está en el repo a la hora de cierre.» | l. 245 a 253 |
| Requisitos excluyentes | Trabajo original del evento, el circuito completo corriendo en el partido final, nada ofensivo ni contra sistemas reales, sin datos personales ni claves reales (las de demostración sí). | l. 238 a 243 |
| Tecnología | Cualquier lenguaje, framework o base de datos. La interfaz del juez puede ser web, móvil o de línea de comandos, pero tiene que poder mostrarse. | l. 95 |

Los cuatro proveedores de la práctica (`datos/proveedores.json`; la demora real es la declarada por un factor entre 0,7 y 1,3, según `simulador/servidor.py`, l. 192):

| Proveedor | Tamaño | Clientes | Acepta | Tarda en aplicar | Falla |
|---|---|---|---|---|---|
| Aurora | grande | 3 800 000 (73 % del total) | IP y dominio | 0,35 a 0,65 min | nunca |
| Andina | mediano | 1 200 000 | IP y dominio | 1,4 a 2,6 min | nunca |
| Valle | chico | 140 000 | **solo dominio** | **4,2 a 7,8 min** | nunca |
| Cumbre | chico | 60 000 | IP y dominio | 2,1 a 3,9 min | **35 % de las órdenes** |

Que el final use estos mismos números no está prometido: la consigna solo promete las mismas situaciones (l. 213).

### Lo fijo también: el *qué* de cada pieza

El circuito (l. 38 a 50): detección → expediente con evidencia → juez de turno que aprueba y firma (o rechaza y se archiva) → cada proveedor del registro → cada uno confirma → vencimiento al terminar el partido. Y, aparte, reclamo de un sitio afectado → juez.

| # | Pieza | Qué dice la consigna | ¿Núcleo o extra? |
|---|---|---|---|
| 1 | Expediente: que es la señal oficial | La marca de agua coincide con el partido y no es de un licenciatario autorizado en su propio dominio (l. 55). «Que algo aparezca en el feed no quiere decir que haya que bloquearlo» (l. 173). | Núcleo (l. 72) |
| 2 | Expediente: el servidor | Host, IP y red (ASN) del servidor que entrega el video (l. 56). | Núcleo (l. 72) |
| 3 | Expediente: riesgo colateral | Qué otros sitios comparten la IP. Si es una CDN o un hosting compartido, recomendar dominio en vez de IP (l. 57). | Núcleo: «si la IP es compartida, se pide bloqueo por dominio» (l. 72) |
| 4 | Expediente: integridad | Hashes de la captura y sellos de tiempo, «para que cualquier alteración posterior se detecte» (l. 58). | Núcleo (l. 72) |
| 5 | Expediente: dónde se promocionó | X, Discord, Telegram (l. 59). | Extra (l. 82) |
| 6 | Expediente: vencimiento propuesto | (l. 60). | — |
| 7 | Juez | Notificarlo, mostrarle el expediente «de forma clara» y registrar su decisión con firma. Entra con su propio usuario y firma solo mientras está de turno. Al cambio de turno, lo pendiente pasa al entrante (l. 61). | Núcleo, con usuario y contraseña, y «el saliente ya no puede firmar» (l. 73 y 74) |
| 8 | Envío | A cada proveedor del registro, en el tipo de bloqueo que acepta; seguir su confirmación; si falla, reintentar (l. 62). | Núcleo (l. 75) |
| 9 | Vencimiento | Los bloqueos **por IP** vencen cuando termina el partido (l. 63). | Núcleo (l. 76) |
| 10 | Auditoría | Registro de auditoría «inalterable» de cada paso (l. 64). | Núcleo (l. 77) |
| 11 | Transparencia | Registro público: qué se bloqueó, cuándo, por orden de quién y hasta cuándo (l. 64). | Extra (l. 81) |
| 12 | Reclamos | Verificar el reclamo, levantar la orden con firma judicial y, si corresponde, reemplazarla por un bloqueo más preciso (l. 65). | Extra (l. 80) |
| 13 | Interfaz del juez cuidada | Por ejemplo en el celular y con notificaciones (l. 83). | Extra |
| 14 | Propuesta normativa | Una página: qué tendría que establecer una ley o una resolución (orden marco, registro de proveedores, plazos, control de daño colateral, reclamos, transparencia), sin lenguaje jurídico (l. 250). | Entregable |

La regla de oro: «Primero tiene que funcionar el núcleo de punta a punta durante el partido final. Los extras suman puntos, pero no compensan un núcleo que no corre» (l. 69).

Los roles (l. 87 a 93): el titular o la fiscalía carga y pide; el juez de turno revisa y firma; los proveedores reciben por API, aplican y confirman (en el desafío, los simula el servidor); el sitio afectado reclama (los reclamos los genera el simulador); el público consulta.

### Lo abierto: el «cómo», que decide cada equipo

| Pregunta | Lo que dice la consigna | Lo que no dice |
|---|---|---|
| ¿Qué prueba que es la señal oficial? | Comparar la marca con los prefijos válidos de `GET /partido` y descartar al licenciatario en su dominio (l. 55, 144 y 173). | Qué hacer con un prefijo parecido, con el código de sesión que trae la marca, o con la señal de un licenciatario que aparece en un dominio ajeno. |
| ¿Qué evidencia alcanza? | La lista de las piezas 1 a 6 (l. 54 a 60). | Cómo se sella, cómo se demuestra después que nadie la tocó, cómo la lee un juez y cómo la comprueba un tercero. |
| ¿Cuándo IP y cuándo dominio? | Si la IP es compartida, dominio; CDN u hosting compartido, dominio (l. 57 y 72). | Qué cuenta como «compartida» (¿y si el otro nombre es el respaldo del propio pirata?), qué se le manda al proveedor que solo acepta dominio, y qué hacer si no hay datos. |
| ¿Cómo decide el juez? | Se le muestra el expediente «de forma clara» y su decisión queda firmada (l. 61). | La pantalla, qué ve primero, cómo se lo avisa, qué pasa si no está mirando, y cómo se le **impide** firmar fuera de turno: el simulador no lo impide, solo lo anota (`simulador/servidor.py`, l. 201 y 202). |
| ¿Qué se hace cuando el pirata se muda? | Avisa que va a pasar (l. 215). | Si el juez tiene que firmar cada servidor nuevo o si alcanza una decisión previa. La consigna exige que detrás de cada firma haya un juez con su sesión iniciada que aprobó la orden (l. 203) y propone que cada pedido le llegue al juez de turno (l. 34). La «orden marco» aparece solo como tema de la propuesta normativa (l. 250) y el «mecanismo dinámico», como antecedente (l. 16). Si una orden marco firmada cuenta como esa aprobación, no lo dice (sección 6). |
| ¿Cómo se entera el proveedor chico? | En el desafío, por API (l. 91). | Cómo sería en la vida real para el que no tiene API, qué le llega a su técnico, qué pasa si su equipo no vence el bloqueo solo. |
| ¿Cómo se atienden los reclamos? | Verificar, levantar con firma y reemplazar (l. 65). | Cómo se verifica ni qué orden lo causó: el reclamo trae el sitio y el proveedor, pero no la orden (`simulador/servidor.py`, l. 296 a 299). |
| ¿Qué norma hace falta? | Una página, con temas sugeridos (l. 250). | El contenido. «No hace falta lenguaje jurídico: alcanza con que diga qué debería establecerse y por qué» (l. 250). |
| ¿Qué es «rápido»? | «Minutos desde la detección hasta el bloqueo confirmado, con cobertura de todos los proveedores» (l. 264). | Ningún umbral. El verificador da números por servidor; cuánto vale cada uno lo decide el jurado. |

En resumen: **dan el problema, las reglas del juego y la vara. No dan la solución.** Hasta lo que suena a instrucción («recomendar dominio», «reintentar», «verificar el reclamo») dice qué tiene que lograrse, no cómo.

---

## 3. Cómo se evalúa, criterio por criterio

Hay dos capas. El **verificador** corre sobre el registro del simulador del partido final y da números (l. 225 a 234). El **jurado** pone el puntaje con la rúbrica (l. 259 a 265). El partido final es un escenario que nadie vio, con una instancia del simulador por equipo, «posiblemente acelerada» (l. 273 y 275).

**Qué cuenta el verificador de verdad** (leído en `evaluacion/verificar.py`, sin ejecutarlo desde su carpeta):

- Por cada servidor de cada stream pirata (cada «fase»): el **primer bloqueo confirmado**, en minutos desde que empieza esa fase, de **cualquier** proveedor (`verificar.py`, l. 95); el **porcentaje de clientes cubiertos**, que suma a cada proveedor que bloqueó en algún momento de la fase, aunque haya sido tarde (`verificar.py`, l. 98); y la **visibilidad residual**, que pesa los clientes de cada proveedor por los minutos que estuvo bloqueado (`verificar.py`, l. 89 a 99). El resumen da la residual promedio de todas las fases (`verificar.py`, l. 159).
- **Daño colateral:** cada orden aplicada, por proveedor, cuyo objetivo tenía sitios legítimos detrás, y cuántos minutos estuvo activa (`verificar.py`, l. 102 a 111). Una IP compartida mandada a tres proveedores son tres bloqueos con daño colateral.
- **Falsos positivos:** cada orden aplicada contra el licenciatario o contra un stream que no es el partido (`verificar.py`, l. 113 a 122).
- **Bloqueos activos después del partido:** solo si el registro llega al minuto 110 (fin + gracia); si no, dice «no evaluable» (`verificar.py`, l. 125 a 133, 211 y 212). Los de IP «deberían haber vencido»; los de dominio son «informativo» (`verificar.py`, l. 216).
- **Reclamos:** si la orden del reclamo terminó después del reclamo, «levantada» o «venció sola», y en cuánto (`verificar.py`, l. 135 a 146).
- **Órdenes rechazadas** (por motivo), **fallidas** y **firmadas fuera de turno** (`verificar.py`, l. 148 a 151).

Lo que el verificador **no** mide: cuánto tarda el juez, cuánto tarda el último proveedor, la evidencia, la auditoría, la pantalla del juez, la transparencia ni la propuesta. Eso lo mira el jurado.

| Criterio | Peso | Qué dice la rúbrica | Quién lo mide | Qué mide en realidad |
|---|---|---|---|---|
| Circuito completo | 25 | Carga → juez → proveedores → confirmación → vencimiento, funcionando durante el partido final (l. 261). | Jurado, con el video, el pitch y `entrega/`; el verificador muestra si hubo órdenes aplicadas y vencidas. | Que corra entero **en el final**, que además es requisito excluyente (l. 241). Si la plataforma se cae, lo demás no se ve: hay que poder reanudar sin duplicar órdenes. |
| Validez e integridad de la evidencia | 25 | El expediente prueba que es la señal oficial, identifica el servidor y detecta cualquier alteración posterior (l. 262). | Solo el jurado. El verificador no mira la evidencia. | El expediente y la auditoría exportados del partido final, en `entrega/` (l. 249). Que se puedan comprobar sin la plataforma y sin confiar en el equipo. |
| Control de daño colateral | 20 | No bloquear sitios legítimos ni al licenciatario, y elegir bien entre IP y dominio. Atender bien los reclamos suma (l. 263). | Verificador (colateral, falsos positivos, reclamos) y jurado. | Cero bloqueos con daño colateral y cero falsos positivos. Si igual hay un reclamo, que termine «levantada» y rápido. Elegir dominio de más no se castiga como colateral, pero un servidor que se podía bloquear por IP queda menos cubierto. |
| Velocidad | 15 | «Minutos desde la detección hasta el bloqueo confirmado, con cobertura de todos los proveedores» (l. 264). | Verificador (primer bloqueo, clientes cubiertos, residual) y jurado. | El primer bloqueo lo gana Aurora, con el 73 % de los clientes: eso es lo que más baja la residual. «Todos los proveedores» lo dominan el más lento (Valle, de 4,2 a 7,8 min) y el que falla (Cumbre): física del simulador. Lo que maneja el equipo: cuánto tarda el juez, si hay seguimiento, que ninguna orden se rechace y reintentar al instante. |
| Claridad y propuesta normativa | 15 | «Un juez y un proveedor entienden qué se pide y por qué. La propuesta normativa es concreta y viable» (l. 265). | Solo el jurado. | La pantalla del juez y la página de cada orden se entienden sin explicación. La propuesta, en una página (l. 250). |

---

## 4. Las trampas

Lo que el simulador deja pasar y el verificador cobra. Las comprobamos leyendo la consigna, los datos de la práctica, el simulador y el verificador.

1. **Firmar fuera de turno.** El simulador acepta la orden igual: solo anota si el juez estaba de turno (`simulador/servidor.py`, l. 201 y 202). El verificador la cuenta (l. 232; `evaluacion/verificar.py`, l. 150 y 151). Impedirlo es trabajo de la plataforma (l. 74).
2. **El cambio de turno.** En la práctica es en el minuto 50 (`datos/juzgados.json`). Lo pendiente pasa al entrante y el saliente ya no puede firmar (l. 74 y 221). Los reintentos y reenvíos de después del cambio también tienen que salir con un juez de turno.
3. **Bloquear la IP compartida.** En la práctica, la CDN tiene 11 sitios legítimos detrás de la IP y el hosting compartido, 4 (`datos/escenario_practica.json`). Bloquear esa IP es daño colateral y dispara reclamos (l. 216 y 220), y cuenta una vez por cada proveedor que la aplicó (`evaluacion/verificar.py`, l. 104 a 111).
4. **La IP «compartida» con el respaldo del propio pirata.** Dos servidores pirata de la práctica comparten la IP solo con otro nombre del mismo pirata (`s1.pelotaya.test` con `s1-respaldo.pelotaya.test`, y `s3.pelotaya.test` con `espejo.pelotaya.test`). La verdad oficial recomienda IP para los dos (`evaluacion/verdad_practica.json`). La regla ingenua («hay otro nombre, entonces dominio») deja vivo el respaldo.
5. **Bloquear al licenciatario.** Retransmite legalmente, con una marca válida, en sus dominios (l. 55 y 218). Tocarlo es un falso positivo (l. 229).
6. **Falsos positivos.** Detecciones con la marca de otro partido o sin marca (l. 217). Aparecer en el feed no obliga a bloquear (l. 173).
7. **IP activas después del partido.** Los bloqueos por IP tienen que vencer al final (l. 63 y 76); el verificador los mira cuando pasan los 5 minutos de gracia (l. 130 y 230). `vence_min` es un entero (l. 192). El verificador lista también los de dominio que siguen activos, como informativo (`evaluacion/verificar.py`, l. 124 a 133 y 216), aunque la consigna solo exige vencer los de IP.
8. **Cortar antes del minuto 110.** Si el simulador se corta antes de fin + gracia, el verificador no evalúa los bloqueos activos después del partido: dice «no evaluable» (`evaluacion/verificar.py`, l. 126 y 211 y 212). La consigna pide evaluar «cuando el partido termine (y pasen los 5 minutos de gracia)» (l. 130).
9. **El proveedor que solo bloquea por dominio** (l. 219). Mandarle una IP es una orden rechazada (`simulador/servidor.py`, l. 163 y 164), y toda orden rechazada cuenta (l. 232).
10. **El proveedor que falla.** Cumbre falla el 35 % de las órdenes y lo avisa recién cuando le tocaba aplicarla, entre 2,1 y 3,9 minutos después (`datos/proveedores.json`; `simulador/servidor.py`, l. 192 y 256 a 264). Hay que reenviar con un `orden_id` nuevo (l. 193 y 209). Reenviar el mismo `orden_id`, por ejemplo después de un corte de red, también es una orden rechazada (`simulador/servidor.py`, l. 159 y 160).
11. **El pirata que se muda** (l. 215). Las detecciones repetidas del mismo servidor no son casos nuevos; la misma filtración en otro servidor, sí, y el reloj corre desde que aparece.
12. **El cursor de los reclamos.** `GET /reclamos` devuelve el `minuto_actual` redondeado a dos decimales (`simulador/servidor.py`, l. 146), y los reclamos llevan tres (l. 297 del mismo archivo). Usado tal cual como el próximo `desde`, puede repetir o saltear un reclamo. En las detecciones el simulador ya lo evita (l. 101 a 104 del mismo archivo).
13. **«Clientes cubiertos» engaña.** Cuenta a un proveedor que bloqueó aunque haya sido al final de la fase (`evaluacion/verificar.py`, l. 98). El número que castiga la demora es la visibilidad residual.
14. **«Nadie firma en su nombre»** (l. 203). Toda orden que salga con la clave de un juez tiene que tener detrás una aprobación de ese juez, con su sesión iniciada. Es la frase que pone en discusión cualquier ampliación automática (sección 6).

---

## 5. Cómo responde Marca Personal

Lo que sigue describe el producto tal como queda en el repo al cierre. Una palabra antes: el **seguimiento** (la prensa habló de «bloqueo dinámico») es que, si el juez lo autoriza, la plataforma siga sola a la misma filtración cuando se muda de servidor. Viene apagado.

| Pieza | Qué hace Marca Personal | Lo que la hace distinta |
|---|---|---|
| Señal oficial (l. 55, 173) | Compara la marca que informa el detector con los prefijos de `GET /partido`; gana el prefijo más largo. El dominio de un licenciatario no se bloquea nunca. La señal de un licenciatario en un dominio ajeno es pirata. | Un expediente **por filtración**, no por sitio: el código de sesión de la marca identifica la cuenta que filtra, y el expediente la sigue de servidor en servidor. |
| Servidor e IP o dominio (l. 56, 57, 72) | Si la IP aloja sitios ajenos, dominio. Si solo aloja nombres del propio pirata, IP. Ante cualquier duda, dominio. Al proveedor que solo acepta dominio le van los nombres del servidor. Apartarse de la recomendación («Apartarme de la recomendación») exige el fundamento escrito del juez. | Una regla de «propios» que separa lo que la plataforma **vio** (el nombre del stream, y el de su página si es del mismo dominio) de lo que **infirió** (otros nombres de ese dominio en el mismo servidor). Un reclamo fundado de un nombre inferido corrige la inferencia: lo inferido de ese dominio se levanta en todos los servidores del pirata, en ese dominio no se vuelve a inferir y los pedidos que esperaban firma se rehacen corregidos («La propuesta cambió…»). Lo que se vio transmitir sigue bloqueado por nombre: ese reclamo no prospera. |
| Integridad (l. 58, 64) | La captura con su hash, la auditoría encadenada y un sello de la evidencia **dentro del número de orden**. El juez firma ese número y cada proveedor lo guarda. `herramientas/falsificar.py` arma un expediente falso completo con nuestras propias claves: nuestra verificación sola no puede notarlo y lo dice («Resultado: coherente consigo mismo (sin cotejar con el registro oficial del simulador).»); el cruce con lo que guardan los proveedores (en el simulador, su registro) lo delata, incluidos el minuto de aplicación, el vencimiento y el estado final de cada orden. | «Ni nosotros podemos falsificarlo»: los proveedores quedan de testigos. |
| Juez (l. 61, 73, 74) | Usuario y contraseña. La plataforma consulta el turno justo antes de firmar. Al empezar su turno, el juez firma una **orden marco** con los límites por escrito («Firmar orden marco»). Su segundo renglón dice hasta cuándo vale («… desde antes del inicio hasta el minuto 50.» o «… hasta el final del partido (minuto 105).») y que todo bloqueo vence, como máximo, al final del partido. Trae la casilla «Autorizo el seguimiento de la misma filtración», **destildada**. Sin ella, cada pedido muestra un solo botón, «Firmar solo este servidor», y la línea «Para seguir a la filtración, autorícelo en la orden marco.». Con ella, dos botones del mismo peso: «Firmar solo este servidor» y «Firmar y seguir a esta filtración». Rechazar pide un motivo, con causales para tocar. Para cambiar la casilla: «Cambiar» y firmar de nuevo; la anterior queda «Reemplazada en el min …». | Nada viene preseleccionado: el juez elige en cada firma. |
| Mudanzas (l. 215) | **Seguimiento**, solo si el juez lo autorizó y lo eligió: cuando la misma sesión de la marca aparece en otro servidor, la plataforma emite la orden sola, como **ampliación automática**. Corre solo si la evidencia nueva está completa y sellada, el bloqueo nuevo no alcanza a sitios ajenos (si el servidor nuevo comparte la IP, se bloquea solo el nombre del stream) y el juez está de turno y con su bandeja abierta (vista en los últimos 90 segundos; el registro público no cuenta). Si no, la mudanza le queda como pedido para firmar en persona, con «Mismo stream que ya bloqueó: ubicación 1 → 2» (si la anterior está aprobada) y una línea «No se amplió solo: …» que dice por qué (por ejemplo, «su orden marco no autoriza el seguimiento.»). Nunca alcanza a otra filtración. Si un pedido queda viejo porque la filtración se mudó, dice «Este servidor no se ve desde el min X. La misma filtración apareció después en otro servidor (ubicación N), que está más arriba.». Un rechazo tampoco es definitivo si el servidor se sigue viendo: vuelve como pedido con «Mismo servidor: usted rechazó este pedido en el minuto X; la plataforma lo volvió a ver transmitiendo en el minuto Y.», y nunca se amplía solo, tampoco si reaparece con otro nombre en la misma IP o con el mismo nombre en otra IP, ni si lo trae la mudanza de otra filtración con seguimiento. Si el juez no vuelve a entrar después de un reinicio, la plataforma lo espera hasta 90 segundos reales; después, la mudanza queda como pedido. Si un servidor se dio por caído y después se lo ve transmitiendo, vuelve al juez. Se le avisa en el momento («Ampliación automática: …»). Con `--sin-dinamica` no hay seguimiento. | El número lo dice: las firmadas en persona empiezan con `ord-` y las ampliaciones con `amp-`. La página de la orden dice «Firmada en persona» o «Ampliación automática» y explica de qué orden marco cuelga. |
| Frenar | El juez frena el seguimiento de una filtración con «Frenar el seguimiento», y elige: «Frenar las próximas mudanzas» o «Frenar y levantar la ampliación» (o «las N ampliaciones»). Queda escrito en la auditoría. Si levantó una ampliación y ese servidor vuelve a aparecer, le llega como pedido con la nota «Mismo servidor: la plataforma lo había bloqueado sola en el minuto …; usted levantó ese bloqueo en el minuto ….». | Lo que el juez levantó no vuelve solo. |
| Cambio de turno (l. 61, 74) | Lo que el saliente dejó esperando pasa al entrante. El orden es: si hay un pedido esperando, primero lo firma (la pantalla dice «Tiene N pedidos esperando. Su orden marco está más abajo.»); después la orden marco y lo heredado. Sin seguimientos heredados, toca «Recibir el turno» y firma su orden marco. Con seguimientos heredados, firma su orden marco con la casilla tildada y en la tarjeta «Recibe el turno» elige cuáles sigue: «Ratificar las marcadas» o «Recibir sin seguimiento». «Firmar y seguir» sobre un seguimiento heredado también lo ratifica, pero no recibe el turno: la tarjeta lo muestra aparte («Ya ratificado al firmar y seguir (min X).») y, si no queda nada por decidir, hay un solo botón, «Recibir el turno». Queda el aviso, por ejemplo, «Recibió el turno en el minuto X: ratificó N de M seguimientos heredados.». El saliente ve «Su turno terminó» y en la sala figura «Fuera de turno desde el min 50». Nadie firma en los últimos 2 segundos reales de un turno ni en el primer medio segundo del siguiente, a propósito: a ×6 son unos 0,25 minutos de partido; a ×20, unos 0,8. | Lo heredado no sigue ampliándose solo hasta que el entrante lo ratifica. |
| Envío y confirmación (l. 62, 75) | Antes de mandar, la plataforma revisa lo que el simulador rechaza: el tipo que el proveedor acepta, un `vence_min` entero y posterior al minuto actual, un juez de turno con su firma y un número de orden que no se repite. Si una orden falla, se reenvía al instante con otro número. Ante un corte de red, se consulta antes de reenviar, y una orden sin respuesta no se reenvía con el mismo número antes de 12 segundos reales (también contados desde un reinicio); una firma en los últimos segundos del partido queda registrada pero no sale, se le avisa al juez; el acta y el expediente separan «no enviada (el partido terminaba)», «no enviada (el juez entrante no recibió el turno)» o «sin confirmar (se envió y, al cierre, el proveedor no la tenía)»; si se levanta mientras está incierta, el levantamiento espera a saber si llegó. | El acta muestra tres tiempos por servidor: detección → firma, → primer proveedor, → todos los proveedores, separados para firmadas en persona y ampliaciones automáticas. |
| Proveedor chico (l. 18, 91) | Cada orden tiene una página con las líneas para MikroTik, nftables, Unbound y BIND y el vencimiento con hora (con el partido acelerado, la hora real va con segundos, redondeada hacia arriba, y la página rotula las dos horas). Cada proveedor tiene una lista que su equipo lee solo: `/proveedor/<id>/vigentes.json`, `dominios.txt`, `ips.txt`, `unbound.conf` y `rpz.zone`; y un cliente de referencia, `herramientas/cliente_proveedor.py`, que muestra «+ BLOQUEAR» y «− QUITAR», escribe los archivos y corre la recarga. Para los sitios ajenos que cuelgan de un nombre bloqueado, `unbound.conf` lleva líneas `transparent`; la página de una orden sola no las trae (límite conocido: el proveedor que usa solo esa página no las tiene). Los nombres con «_» valen. El cliente de referencia es más estricto que la plataforma con las direcciones IPv6 de transición (límite conocido). Ningún bloqueo dura más de 6 horas desde la última lista buena, y una orden levantada nunca vuelve. En `/transparencia` está la «Lista de cada proveedor». | Las líneas se revisaron contra la documentación oficial de cada equipo; **no se probaron en equipos reales**. |
| Vencimiento (l. 63, 76) | Todo bloqueo vence con el partido, también los de dominio. Al terminar, la pantalla del juez dice «Partido terminado» y la sala, en cada filtración, «Venció con el partido» o «Levantado». | — |
| Auditoría y transparencia (l. 64) | Auditoría encadenada de cada paso. Registro público en `/transparencia`, con las órdenes marco firmadas y la consulta «¿Tu sitio quedó bloqueado?», que acepta la dirección completa. Las páginas públicas no muestran el código de sesión. | Privacidad: el código de sesión lo ven el juez y el expediente, no el público. |
| Reclamos (l. 65) | Verifica el reclamo contra el DNS pasivo, deduce qué órdenes lo causaron en todos los proveedores y le deja al juez el levantamiento y el reemplazo listos para firmar («Levantar y reemplazar»). El aviso se cierra con lo que pasó, por ejemplo «Resuelto en el minuto …: levantó el bloqueo y lo reemplazó por dominio.». La propuesta dice cuántos bloqueos son por IP y cuántos por nombre, y la orden de reemplazo dice «Decidida … al resolver el reclamo R-00x», con el minuto de esa resolución. El acta y el expediente cuentan cada reclamo en castellano llano: quién lo resolvió, en qué minuto, qué se levantó y qué lo reemplazó (la columna «Firma» dice «Reemplazo por reclamo R-…»). | La explicación verificada queda escrita en el levantamiento. |
| Dónde se promocionó (l. 59) | Figura en el expediente y en el acta. | — |
| Corte en origen | La plataforma deja constancia del código de sesión para que el titular dé de baja esa cuenta. **En el simulador es solo una constancia**: no hay a quién avisarle. | Apunta a la cuenta que filtra, no solo al servidor. |
| Propuesta normativa (l. 250) | `entrega/propuesta-normativa.md`, una página, y su PDF. | — |

**Lo medido** (se mide con el código congelado; cada número dice quién firmó):

- Práctica oficial a ×20, jueces automáticos de ensayo que firman cada pedido a los 0,3 minutos de partido (no son personas), verificador oficial. Con el seguimiento autorizado: 7 de 7 servidores pirata bloqueados; 100 % de clientes cubiertos; residual promedio 3,3 %; 33 órdenes recibidas y 0 rechazadas; 0 falsos positivos, 0 firmas fuera de turno, 0 bloqueos con daño colateral; primer bloqueo confirmado entre 0,40 y 1,05 minutos.
- Los tres tiempos, mismo ensayo: firmadas en persona por el juez automático, detección → firma 0,39, → primer proveedor 0,93, → todos 6,56; ampliaciones automáticas 0,04 / 0,48 / 7,35.
- Con la casilla destildada (todo firmado en persona), mismo juez automático: 7 de 7, residual 5,1 %, 0 rechazadas; tiempos 0,72 / 1,35 / 9,01.
- Con un juez simulado a ritmo humano (un programa que tarda 20 s reales en cada decisión, no una persona), a ×20: con la casilla destildada, residual 31,2 % y firmadas una por una 11,50 / 11,97 / 18,71; con el seguimiento autorizado, residual 21,2 %. Las otras combinaciones (8 y 20 s, ×6 y ×20) están en el README.
- Partido espejo con trampas (otro partido con la misma estructura), ×20, juez automático, seguimiento autorizado: 9 de 9, residual 3,2 %, 41 órdenes.
- Error forzado (el juez bloquea a propósito una IP compartida): 3 bloqueos con daño colateral, 1 reclamo, resuelto por levantamiento.

---

## 6. Lo que sigue en discusión

1. **El seguimiento contra «nadie firma en su nombre».** La consigna dice: «la plataforma firma con la clave de un juez solo después de que ese juez inició sesión y aprobó la orden. Nadie firma en su nombre» (l. 203). La misma consigna pide que la propuesta normativa hable de una «orden marco» (l. 250) y cuenta como antecedente «un mecanismo dinámico que actualiza la restricción cuando los sitios cambian de dominio» (l. 16). Nuestro seguimiento es una ampliación automática bajo una orden marco que el juez firmó. **Es defendible, pero discutible al pie de la letra:** el juez no vio el servidor nuevo antes de que saliera la orden, y esa orden sale con su clave. **Postura del equipo:** el seguimiento está apagado por defecto y lo decide quien firma; se les pregunta a los mentores el jueves 12; si no hay respuesta, el partido final se corre con la casilla destildada (cada orden firmada en persona) y el seguimiento se muestra medido sobre un partido de práctica.
   - A favor: el antecedente real de 2025 era más amplio (la actualización la pedía el fiscal, según DPL News); la recomendación europea pide que las «acciones de cesación dinámicas» queden «bajo el control de una autoridad judicial», que es lo que busca la orden marco; y en Francia, desde la Ley 2026-725, si la orden judicial lo prevé, los servicios nuevos se bloquean sin demora durante la transmisión.
   - En contra: la letra de la línea 203, y la tesis de la consigna: que cada pedido le llegue en el momento a un juez de turno, «eso es lo que les proponemos construir» (l. 34). Con el seguimiento, el servidor nuevo no pasa por el juez antes de bloquearse, y eso se acerca al modelo de Francia y del Reino Unido de su tabla, donde el juez firma la orden inicial (l. 29 y 30).
2. **La velocidad a ritmo humano.** Todos los tiempos medidos son de programas: el juez automático firma en 0,3 minutos de partido y el juez simulado tarda 8 o 20 segundos reales por decisión (a ×6, 0,8 o 2 minutos de partido; a ×20, 2,67 o 6,67). Con un juez de verdad manda el tiempo que tarda en decidir, y ahí es donde más ayuda el seguimiento. Cada vez que se muestre un tiempo, se dice quién o qué firmó.
3. **«Presente» quiere decir la bandeja abierta en los últimos 90 segundos reales.** Con el simulador acelerado, son muchos minutos de partido: a ×6, nueve; a ×20, treinta. Si el final va muy acelerado, conviene decirlo al explicar la presencia del juez. Y las sesiones viven en memoria: si la plataforma se reinicia, cada juez vuelve a entrar; la plataforma lo espera hasta 90 segundos reales antes de dar por perdida una ampliación, y después la mudanza le queda como pedido. Es una decisión, no una falla. Si un juez de turno no tiene la plataforma abierta y hay pedidos, la sala recibe un solo aviso por ausencia («… está de turno y no tiene la plataforma abierta: hay N pedidos esperando»).
4. **El kit no se probó en equipos reales.** Además, el bloqueo por DNS solo alcanza a los abonados que usan el DNS de su proveedor; quien use otro, o DNS cifrado en el navegador, lo saltea.
5. **Que el proveedor lea su lista no lo garantiza la plataforma.** En el simulador los proveedores reciben por API (l. 91). En la vida real haría falta un registro de proveedores al día y la obligación de leer el canal: eso es materia de la propuesta normativa.
6. **La firma es de demostración.** La consigna lo permite (l. 203 y 243). Con firma digital real cambia quién guarda la clave, y eso pesa en el punto 1. Las contraseñas de ingreso de demostración están publicadas en el repo: para abrir la plataforma a la red se arman otras con `python3 -m marca claves`, y con las publicadas `servir` no arranca fuera de la propia máquina.
7. **El corte en origen es solo una constancia** en el simulador.
8. **Los hechos que no pudimos cerrar.** En 2025, si la orden viajó por las cámaras (consigna, l. 15) o por el ENACOM (DPL News; La Nación habla de su «participación activa»), o por los dos. En 2026, qué juzgado intervino y quién decide cada actualización.
9. **El tiempo hasta «todos los proveedores» no depende de nosotros.** Lo fija el proveedor más lento del simulador (de 4,2 a 7,8 minutos) y el que falla. Hay que explicarlo así para que no se lea como lentitud de la plataforma.
10. **Del final, ¿qué números habrá?** El verificador compara con las respuestas correctas del escenario final (l. 225 y 234), que no tenemos. Si la organización no da el registro o la salida oficial, del final solo podemos publicar los números de nuestra acta, y hay que decirlo así.
