# Marca Personal — especificación v1

Plataforma federal de órdenes de bloqueo en vivo para el **Desafío Fútbol** (Hackathon Argentina Space 2026, track Datos y Streaming, QualyData). Corre contra el simulador oficial del desafío.

Este documento es el contrato entre el motor (Python), las pantallas (web estática) y las herramientas de ensayo. Si algo de acá choca con el simulador real, **manda el simulador**: se corrige el código y se anota la diferencia al final de este archivo, en «Desvíos».

---

## 1. La idea en una página

En el fútbol hay dos maneras de marcar: en zona (cuidás un lugar) o **marca personal** (seguís a un jugador adonde vaya). Las plataformas de bloqueo marcan en zona: bloquean direcciones, y el pirata se muda. Nosotros hacemos marca personal: seguimos a **la filtración**.

Cada stream pirata lleva la marca de agua de la señal oficial, y esa marca termina en un código de sesión (`LP26-PRA-OFI-S048211`). El pirata cambia de servidor y de IP, pero la sesión filtrada es la misma. De ahí salen las seis decisiones de diseño que nos distinguen:

1. **Un expediente por filtración, no por dirección.** Cada servidor nuevo del mismo stream es una *ubicación* más del mismo expediente, con su propia evidencia sellada.
2. **Orden dinámica.** Al firmar, el juez elige el alcance: solo este servidor, o esta filtración adonde se mude hasta el final del partido. Con alcance dinámico, la mudanza se bloquea en segundos, se le avisa al juez y él puede revocarla. Solo se amplía sola si la marca de agua es la misma y la evidencia nueva está limpia.
3. **El sello viaja en la orden.** Cada `orden_id` lleva un sello: el hash de la evidencia más el hash de la entrada de auditoría donde quedó la decisión. La firma del juez cubre el `orden_id`, así que cubre la evidencia exacta que vio. Cada proveedor guarda el sello; el registro del simulador (que es de la organización) queda como testigo independiente.
4. **Regla de daño colateral bien hecha.** IP solo si el servidor es exclusivo del pirata (ahí cae también su respaldo); dominio si la IP es compartida; al proveedor que solo bloquea por dominio se le mandan todos los nombres del servidor pirata. Nunca al licenciatario.
5. **Traspaso de turno con ratificación.** El simulador acepta firmas fuera de turno y el verificador las castiga: la plataforma lo impide sola. El juez entrante ratifica lo heredado con un toque.
6. **Reclamos que se verifican solos.** La plataforma comprueba el reclamo contra el DNS pasivo y le deja al juez el levantamiento y el reemplazo por un bloqueo más preciso, listos para firmar.

---

## 2. Reglas del repositorio

- **Python 3.9 o superior, solo biblioteca estándar.** Sin dependencias, sin `pip`. Nada de `match`, ni `X | Y` en anotaciones evaluadas en tiempo de ejecución (usar `from __future__ import annotations` y `Optional`).
- **Web sin compilación.** HTML, CSS y JavaScript a mano, sin frameworks, sin CDN, sin fuentes externas: tiene que andar sin internet.
- Nombres de módulos, funciones y variables **en español, sin tildes ni ñ**. Comentarios y textos de interfaz en español neutro y formal (es una herramienta judicial).
- **El repo del desafío no se toca.** Se clona aparte (las pruebas del partido espejo lo buscan en `DESAFIO_FUTBOL_REPO` o al lado de este repo, en `../desafio-futbol`). Solo se lee. El simulador y el verificador se ejecutan con `python3 -I <ruta absoluta>` y con todas las rutas por argumento, desde una carpeta de trabajo que no sea la del repo del desafío. Nunca se escribe ahí dentro.
- **No hacer trampa con el simulador.** La demora y la falla de cada proveedor salen de un hash del `orden_id`. Está prohibido elegir `orden_id` para esquivar fallas o acortar demoras. Nuestro `orden_id` lleva un sello que es un hash, así que no se puede elegir.
- Las claves de firma nunca salen del servidor: no van en respuestas de la API, ni en el registro de auditoría, ni en lo exportado.
- Todo dato que viene del simulador es **no confiable**: en la web se muestra con `textContent`, nunca con `innerHTML`.
- No se hacen commits ni push: eso lo decide el equipo.

### Estructura

```
marca-personal/
├── marca/                     paquete Python
│   ├── __init__.py            VERSION
│   ├── __main__.py            línea de comandos: servir | chequear | exportar | verificar
│   ├── canon.py               JSON canónico y sha256
│   ├── dominios.py            dominio registrable, cobertura de dominios, ¿es IP?
│   ├── evidencia.py           análisis puro: señal, servidor, colateral, propuesta
│   ├── sello.py               huella, sello, firmas (orden, levantamiento, decisión)
│   ├── auditoria.py           registro encadenado por hash
│   ├── turnos.py              quién está de turno y si puede firmar
│   ├── simulador.py           cliente HTTP del simulador
│   ├── reloj.py               reloj del partido (estimación entre consultas)
│   ├── motor.py               estado, ciclo, decisiones, reclamos, traspaso
│   ├── despacho.py            envío, seguimiento y reintento de órdenes
│   ├── usuarios.py            usuarios, contraseñas (PBKDF2) y sesiones
│   ├── api.py                 servidor HTTP: API JSON, espera larga, archivos estáticos
│   ├── kit.py                 instrucciones listas para el proveedor (MikroTik, Unbound, BIND, nftables)
│   ├── exportar.py            exporta expedientes, auditoría y acta
│   ├── verificar.py           verificador de integridad, sin conexión
│   └── web/                   pantallas (ver sección 11)
├── config/jueces_demo.json    usuarios y claves de demostración
├── herramientas/
│   ├── ensayo.py              corre un partido entero y lo evalúa
│   ├── juez_automatico.py     juez de ensayo (solo para pruebas)
│   └── api_simulada.py        API de mentira para desarrollar las pantallas
├── tests/                     unittest
├── entrega/                   propuesta normativa y lo exportado del partido final
└── docs/
```

---

## 3. El simulador: hechos comprobados leyendo `simulador/servidor.py`

El tiempo se mide en **minutos de partido**. `--acelerar N` hace que un minuto de partido dure `60/N` segundos reales.

| Ruta | Respuesta |
|---|---|
| `GET /estado` | `{partido, minuto_actual (2 decimales), fin_min, finalizado, acelerar, jueces_de_turno: [juez_id]}` |
| `GET /partido` | `{id, nombre, titular_derechos, inicio_iso, fin_min, marcas_de_agua_validas: [{prefijo, origen}], licenciatarios: [{nombre, prefijo_marca, dominios_autorizados}]}` |
| `GET /detecciones?desde=M` | `{minuto_actual (3 decimales), detecciones: [...]}`: las que cumplen `desde < minuto <= minuto_actual`. Usar el `minuto_actual` devuelto como próximo `desde`. Primera vez: `desde=-1`. |
| `GET /dns-pasivo?ip=X` | `200 {ip, asn, organizacion, dominios: [...]}` o `404 {error}` |
| `GET /dns-pasivo?dominio=D` | `200 {dominio, ips: [{ip, asn, organizacion}]}` o `404`. Coincidencia exacta. |
| `GET /juzgados` | `{juzgados: [{id, nombre, jurisdiccion, jueces: [{id, nombre}]}], turnos: [{juez_id, desde_min, hasta_min}], de_turno_ahora}` (sin claves) |
| `GET /proveedores` | `[{id, nombre, tamano, clientes, capacidades: ["ip","dominio"], ordenes}]` |
| `POST /proveedores/<id>/ordenes` | `202 {orden_id, estado: "recibida", consultar}` o error |
| `GET /proveedores/<id>/ordenes` | lista de todas las órdenes de ese proveedor |
| `GET /proveedores/<id>/ordenes/<orden_id>` | una orden |
| `POST /proveedores/<id>/ordenes/<orden_id>/levantar` | cuerpo `{juez_id, firma, motivo}`; `200` con la orden, `409` si ya no está activa |
| `GET /reclamos?desde=M` | `{minuto_actual (2 decimales), reclamos: [{id, minuto, dominio, proveedor, mensaje}]}` |

Detección:

```json
{"id": "D-0001", "minuto": 2.0, "pagina": "https://pelotaya.test/en-vivo",
 "stream_url": "https://s1.pelotaya.test/hls/en-vivo/index.m3u8", "host_stream": "s1.pelotaya.test",
 "ip_servidor": "203.0.113.10", "asn": 64600, "marca_de_agua_extraida": "LP26-PRA-OFI-S048211",
 "captura": {"capturada_min": 2.0, "formato": "mpegts", "duracion_seg": 6, "contenido_b64": "R78w..."},
 "promocion": [{"red": "x", "url": "https://x.example/...", "minuto": 1.0}]}
```

La captura decodificada mide 64 bytes y empieza con `0x47` (byte de sincronía de MPEG-TS). La marca puede venir vacía o nula en el partido final.

Orden (todos los campos son obligatorios):

```json
{"orden_id": "...", "expediente_id": "...", "tipo": "ip|dominio", "objetivo": "...", "vence_min": 105,
 "juzgado_id": "jg-centro-3", "juez_id": "jueza-laura-ficticia", "firma": "<hex>"}
```

- `firma` = HMAC-SHA256 en hexadecimal, con la `clave_firma_demo` del juez, sobre `orden_id|tipo|objetivo|vence_min|juez_id`.
- Levantar: firma sobre `LEVANTAR|orden_id|juez_id`.
- `vence_min` tiene que ser `int` y mayor que el minuto actual.
- Estados: `recibida` → `aplicada` o `fallida`; `aplicada` → `vencida` (al llegar a `vence_min`) o `levantada`.

**Trampas del simulador que el código tiene que respetar:**

1. **Todo error al enviar una orden queda como `orden_rechazada` en el registro oficial y el verificador lo cuenta.** Incluye el `409` por `orden_id` repetido. Regla: si un `POST` falla por red o por tiempo, primero `GET` de esa orden; solo si da `404` se reenvía. Nunca se manda algo que el simulador vaya a rechazar.
2. **El simulador no rechaza una orden firmada por un juez fuera de turno.** La anota con `juez_de_turno: false` y el verificador la castiga. Lo evalúa en el momento en que recibe la orden, no cuando se firmó.
3. **`GET /reclamos` redondea `minuto_actual` a 2 decimales** y los reclamos tienen 3: usar ese valor como `desde` puede saltear un reclamo. Regla: pedir siempre `desde=-1` y descartar repetidos por `id`.
4. La falla de un proveedor se informa recién cuando hubiera aplicado la orden (para Cumbre, entre 2,1 y 3,9 minutos después de recibirla).
5. El reclamo que devuelve la API no dice qué orden lo causó: hay que deducirlo.
6. El DNS pasivo es fijo durante todo el partido.
7. El verificador mide cada fase pirata desde que empieza (coincide con la primera detección de ese servidor): tiempo al primer bloqueo aplicado, porcentaje de clientes cuyos proveedores bloquearon y visibilidad residual (clientes por minuto que lo pudieron ver). Un bloqueo cuenta para una fase si es por IP con la IP de la fase, o por dominio con **exactamente** el host del stream.
8. Daño colateral: cualquier orden aplicada que deje detrás un dominio que no sea pirata. Los bloqueos por IP que sigan activos 5 minutos después del final cuentan en contra; los de dominio, no.

Datos de práctica (el partido final trae las mismas situaciones con otros nombres, IP y tiempos; los jueces y los turnos son los mismos):

- Proveedores: Aurora (3,8 M de clientes, IP y dominio, ~0,5 min), Andina (1,2 M, IP y dominio, ~2 min), FibraValle (140 k, **solo dominio**, ~6 min), Cumbre (60 k, IP y dominio, ~3 min, **falla el 35 %**). La demora real va del 70 % al 130 %.
- Turnos: `jueza-laura-ficticia` (juzgado `jg-centro-3`) del minuto −60 al 50; `juez-martin-ejemplo` (`jg-norte-1`) del 50 al 240.
- Partido: termina en el minuto 105. Prefijos válidos: `LP26-PRA-OFI` (señal oficial) y `LP26-PRA-LIC-NORTE` (licenciatario Canal Norte, dominios `canalnorte.test` y `envivo.canalnorte.test`).

---

## 4. Reglas de evidencia (`dominios.py`, `evidencia.py`): funciones puras

Nada en estos módulos hace entrada/salida. Reciben datos y devuelven diccionarios. Son la parte más probada.

### 4.1 Dominios

- `normalizar(host)`: minúsculas, sin espacios, sin punto final.
- `es_ip(host)`: verdadero si es una IPv4 o IPv6 literal (`ipaddress`).
- `registrable(host)`: los dos últimos rótulos (`s1.pelotaya.test` → `pelotaya.test`). Tres rótulos si termina en un sufijo de segundo nivel conocido (`com.ar`, `gob.ar`, `gov.ar`, `org.ar`, `net.ar`, `edu.ar`, `com.br`, `com.mx`, `com.uy`, `com.py`, `com.bo`, `com.pe`, `com.co`, `com.cl`, `co.uk`). Una IP literal se devuelve tal cual.
- `cubre(dominio, host)`: `host == dominio` o `host` termina en `"." + dominio`.
- `host_de(url)`: el host de una URL, o `None`.

### 4.2 La señal

`analizar_senal(marca, partido, host) -> dict` con `{marca, prefijo, origen, sesion, clase, motivo, observaciones}`.

1. Marca vacía o nula → `clase = "sin_marca"`.
2. Prefijo válido: el **más largo** de `partido.marcas_de_agua_validas` tal que `marca == prefijo` o `marca` empieza con `prefijo + "-"`. Sin prefijo válido → `clase = "otra_senal"`.
3. Si `host` está cubierto por algún `dominios_autorizados` de algún licenciatario → `clase = "licenciatario"`. **Nunca se bloquea**, cualquiera sea la marca. Si el prefijo no es el de ese licenciatario, va una observación.
4. Si no → `clase = "pirata"`. Motivo según el prefijo: señal oficial del titular fuera de su plataforma, o señal del licenciatario fuera de sus dominios autorizados.
5. `sesion`: lo que sigue al prefijo y al guion (`S048211`), o `None`.

### 4.3 El servidor y el daño colateral

`analizar_servidor(det, dns_ip, dns_host, hosts_piratas, refutados=frozenset()) -> dict`, donde `dns_ip` y `dns_host` son las respuestas crudas del DNS pasivo (o `None` si dio 404), `hosts_piratas` es el conjunto de hosts ya confirmados como piratas en otros expedientes y `refutados` los registrables cuya inferencia corrigió un reclamo (ronda 3b, C14).

- **Regla de «propios» (ronda 3b, C14; reemplaza la de la ronda 2b).** Los nombres de la IP se separan en:
  `observados` = lo que la plataforma **vio**: el host del stream, el host de la página **solo si comparte el
  registrable con el del stream** (o si el stream sale de una IP literal) y los `hosts_piratas`; `inferidos` = los
  otros nombres de la IP que cuelgan del registrable `R` del stream, solo si la página vive en `R` o en `www.R`
  (`controla_registrable`) **y** `R` no está en `refutados`. `propios` = observados + inferidos; el resto es
  `ajenos` y la recomendación pasa a `dominio`. Una página de **otro** registrable ya no es propia. El motivo de
  «IP exclusiva» dice qué se vio y qué se infirió, y concuerda en número («corta los dos nombres» / «los N
  nombres»). En un hosting por subdominios (`pirata.hosting-gratis.test` junto a
  `panaderia.hosting-gratis.test`) el motivo dice «… comparte la IP con otros subdominios de hosting-gratis.test
  que no podemos atribuir al pirata (…)».
- `operacion` = `{R}` solo si la página controla `R`; si no, vacío.
- `red_compartida` = la organización del ASN contiene `cdn`, `compartid` o `shared` (sin distinguir mayúsculas).
- `coherencia` = `{host_en_url, ip_en_dns_del_host, host_en_dns_de_la_ip, asn_coincide}`; cada uno es `true`, `false` o `null` (no se pudo comprobar). `ok` = ninguno es `false`. `completa` = todos son `true`.

Recomendación, en este orden (la primera que se cumple):

| # | Condición | `recomendacion` | `riesgo` |
|---|---|---|---|
| 1 | El host es una IP literal y la IP tiene ajenos, es red compartida o no hay datos | `ninguna` | `alto` |
| 2 | No hay datos de DNS pasivo de la IP | `dominio` | `desconocido` |
| 3 | La IP tiene dominios ajenos | `dominio` | `alto` |
| 4 | Red compartida por el nombre del ASN | `dominio` | `medio` |
| 5 | El host aparece en más de una IP | `dominio` | `nulo` |
| 6 | Alguna comprobación de coherencia dio `false` | `dominio` | `desconocido` |
| 7 | Ninguna de las anteriores | `ip` | `nulo` |

`motivo` es una oración en español llano que cualquiera entiende, por ejemplo: «La IP aloja otros 11 sitios que no tienen que ver con el pirata (municipio-ejemplo.example, noticias-del-valle.test y 9 más). Bloquearla los dejaría sin servicio: se bloquea solo el nombre del stream.» o «La IP es exclusiva del sitio pirata (s1.pelotaya.test y su respaldo s1-respaldo.pelotaya.test). Bloquear la IP corta los dos.»

`limpia` (apta para ampliarse sola bajo una orden dinámica) = clase pirata **y** coherencia `completa` **y** captura válida **y** `recomendacion` distinta de `ninguna`.

### 4.4 La captura

`analizar_captura(captura, vistas) -> {sha256, bytes, formato, duracion_seg, capturada_min, sync_mpegts, repetida, valida}`: decodifica base64, calcula el sha256 de los bytes, comprueba que empiece con `0x47` si el formato es `mpegts`, y marca `repetida` si ese sha256 ya apareció en otra detección. `valida` = decodificó, no está vacía, `sync_mpegts` y no repetida.

### 4.5 La propuesta de bloqueo

`proponer(analisis, proveedores, fin_min, forzar_tipo=None) -> {tipo, vence_min, fundamento, objetivos_por_proveedor, sin_cobertura}`.

- `vence_min = ceil(fin_min)`, siempre entero. Todo bloqueo vence con el partido.
- `tipo` = `forzar_tipo` si viene; si no, la recomendación.
- Tipo `ip`: a cada proveedor que acepta `ip`, la IP. Al que solo acepta `dominio`, **un bloqueo por dominio por cada nombre de `propios`** (el host del stream primero).
- Tipo `dominio`: a cada proveedor que acepta `dominio`, el host del stream. El que solo acepta `ip` va a `sin_cobertura` (salvo que el tipo esté forzado a `ip`).
- Recomendación `ninguna` y sin forzar: `objetivos_por_proveedor` vacío; decide el juez.

Un solo tipo por proveedor: no se manda IP y dominio a la vez al mismo proveedor.

---

## 5. Modelo

### 5.1 Expediente y ubicación

- **Expediente** = un stream pirata. `id` = `EXP-<año>-<num de 6 cifras>` (año de `partido.inicio_iso`).
- **Clave de filtración**: si hay sesión, la marca completa; si no, `prefijo + "@" + registrable(host de la página, o del stream)`.
- Una detección pirata entra a un expediente existente si (a) su marca ya está en las marcas del expediente → criterio `misma_marca`; o (b) el registrable de su página es el `sitio` del expediente → criterio `mismo_sitio`. Si no, abre un expediente nuevo.
- **Ubicación** = un servidor del stream: el par `(host, ip)`. Una detección de un par que ya existe es una **redetección**: se agrega a la lista y no genera nada más, salvo dos casos que vuelven al juez como ubicación nueva del mismo servidor: la ampliación que el juez frenó y levantó (C4, §18.5) y el servidor que un juez **rechazó** y se sigue viendo después del rechazo (C22, §19.8).
- Una ubicación nueva arma su evidencia, la sella y queda `pendiente`.
- Las detecciones que no son piratas (`licenciatario`, `otra_senal`, `sin_marca`) van a **descartes** con su motivo y no llegan al juez. Las repetidas del mismo `(host, clase)` suman en `veces`.

### 5.2 La evidencia sellada

Al armar la ubicación se construye el bloque `sellado`, que no cambia nunca más:

```json
{
  "version": 1,
  "expediente": "EXP-2026-000001", "ubicacion": 1,
  "partido": {"id": "...", "nombre": "...", "titular": "...", "fin_min": 105, "huella": "<sha256 de la respuesta de /partido>"},
  "deteccion": { "...": "la detección tal como llegó, completa" },
  "captura": {"sha256": "...", "bytes": 64, "formato": "mpegts", "duracion_seg": 6, "capturada_min": 2.0, "sync_mpegts": true, "repetida": false, "valida": true},
  "senal": {"marca": "...", "prefijo": "...", "origen": "...", "sesion": "S048211", "clase": "pirata", "motivo": "..."},
  "servidor": {"pagina": "...", "stream_url": "...", "host": "...", "ip": "...", "asn": 64600, "organizacion": "..."},
  "dns_pasivo": {"por_ip": {"...": "respuesta cruda o null"}, "por_host": {"...": "respuesta cruda o null"}, "consultado_min": 2.031},
  "coherencia": {"host_en_url": true, "ip_en_dns_del_host": true, "host_en_dns_de_la_ip": true, "asn_coincide": true, "ok": true, "completa": true, "observaciones": []},
  "colateral": {"dominios_en_ip": [], "propios": [], "ajenos": [], "red_compartida": false, "riesgo": "nulo", "recomendacion": "ip", "motivo": "...", "limpia": true},
  "promocion": [],
  "propuesta": {"tipo": "ip", "vence_min": 105, "fundamento": "...", "objetivos_por_proveedor": {"aurora": [{"tipo": "ip", "objetivo": "203.0.113.10"}]}, "sin_cobertura": []},
  "antecedente": null,
  "armado": {"min": 2.031, "utc": "2026-11-12T01:23:45.678Z"}
}
```

- `antecedente` es `null` en la primera ubicación; en las siguientes, `{"ubicacion": n, "huella": "..."}` de la anterior: las ubicaciones quedan encadenadas.
- `huella = sha256(canonico(sellado))`.
- `canonico(obj)` = `json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))` en UTF-8. Los minutos se guardan redondeados a 3 decimales.
- La captura decodificada se guarda en `<salida>/capturas/<id de detección>.ts`.

### 5.3 Decisión y sello

Toda decisión queda primero en la auditoría; de esa entrada sale el sello.

- `firma_decision` = HMAC con la clave del juez sobre `DECISION|<exp>|U<n>|<huella>|<APROBAR o RECHAZAR>|<alcance>|<juez_id>`.
- `sello = sha256("MARCA-PERSONAL-SELLO-v1|" + huella + "|" + hash_de_la_entrada_de_auditoria).hexdigest()[:32]`.
- `orden_id = "<prefijo>-<num de expediente, 4 cifras>-u<n>-<proveedor>-<k, 2 cifras>-<sello>"`, con prefijo `ord` (firma en persona) o `amp` (ampliación automática bajo la orden marco; los reintentos y reenvíos conservan el prefijo), con `k` = contador por ubicación y proveedor desde 1 (los reintentos y los reemplazos usan el siguiente). Ejemplo: `ord-0001-u1-aurora-01-9f3a2b1c4d5e6f708192a3b4c5d6e7f8`. El proveedor se sanea a `[a-z0-9_-]`.
- `expediente_id` de la orden = el `id` del expediente.

### 5.4 Orden dinámica

`expediente.dinamica`: `null` o

```json
{"activa": true, "marcas": ["LP26-PRA-OFI-S048211"],
 "otorgada_por": {"juez_id": "...", "nombre": "..."}, "otorgada_min": 2.4, "entrada": 17,
 "respaldada_por": "jueza-laura-ficticia", "requiere_ratificacion": false,
 "ratificaciones": [{"juez_id": "...", "nombre": "...", "min": 50.2, "entrada": 131}],
 "revocada": null}
```

Una ubicación pendiente se **amplía sola** si se cumple todo esto:

1. La plataforma corre con la orden dinámica habilitada (por defecto sí; `--sin-dinamica` la apaga).
2. `dinamica.activa`, sin `requiere_ratificacion` y sin revocar.
3. La ubicación entró por `misma_marca` y su marca está en `dinamica.marcas`.
4. La evidencia es `limpia`.
5. El juez que respalda puede firmar ahora (sección 6), **firmó su orden marco con el seguimiento autorizado**
   (sección 17.1) y **está presente**: hubo actividad suya en la plataforma en los últimos 90 s (`PRESENCIA_S`,
   `usuarios.activo`). Una mudanza que no se amplió por ausencia queda para firma en persona aunque el juez
   vuelva (`automatica.definitivo`).
6. El partido no terminó.

Si se cumple: entrada `ampliacion_dinamica` en la auditoría (con la entrada de la decisión que la habilita), órdenes firmadas con la clave del juez que respalda, y un aviso para ese juez. Si no se cumple, la ubicación sigue pendiente en la bandeja del juez de turno con `automatica.motivo` explicando por qué. El motor lo vuelve a intentar en cada ciclo.

### 5.5 Órdenes

Estados nuestros: `por_enviar` → `recibida` → `aplicada` → `vencida` | `levantada`; también `fallida`, `rechazada` y `espera_ratificacion`.

- **Sin duplicar objetivos.** Antes de crear una orden para `(proveedor, tipo, objetivo)` se mira si ya hay una en `por_enviar`, `recibida` o `aplicada` (de cualquier expediente). Si la hay, no se crea y queda anotado en la decisión como `ya_cubiertos`.
- **Envío** en paralelo a todos los proveedores (`ThreadPoolExecutor`), fuera del candado del estado.
- **Seguimiento**: en cada ciclo, `GET /proveedores/<id>/ordenes` de los proveedores que tengan órdenes sin terminar.
- **Reintento** al ver `fallida`: orden nueva, mismo objetivo, mismo sello, `k` siguiente, `origen: "reintento"`, `reemplaza` = la fallida. La firma el juez de la decisión si todavía puede firmar. Si ya cambió el turno: la firma el juez entrante si ya ratificó el traspaso; si todavía no, queda en `espera_ratificacion`. Sin tope de intentos (C13): al 6.º intento fallido sale UNA alerta a la sala y se sigue reintentando; desde el 7.º, no antes de 1 minuto de partido después del envío anterior.
- Antes de **cada** `POST` se vuelve a comprobar que el juez firmante sigue de turno. Si no, la orden no sale y pasa a `espera_ratificacion`.
- No se envía nada si faltan `max(0,05; (2 s + 1,5 × D) × acelerar / 60)` minutos de partido o menos para el final o para el `vence_min` de la orden (`margen_envio`, D = la latencia medida; la misma forma que el margen de fin de turno del §6; a ×20 son al menos 0,67 min). Una firma que llega dentro de ese margen queda registrada, recibe el aviso «Faltan segundos para el final del partido: …» y sus órdenes quedan `no_enviada` (§20, f-desconocido-1).

### 5.6 Reclamos

1. Cada ciclo: `GET /reclamos?desde=-1`; los nuevos (por `id`) se procesan.
2. **Verificación**: `GET /dns-pasivo?dominio=<reclamante>` → IP. Órdenes causantes = las activas (`recibida` o `aplicada`), de **cualquier proveedor**, por IP con una de esas IP, o por dominio con ese mismo dominio.
3. Clase del reclamante: `licenciatario` (dominio autorizado), `operacion_pirata` (es un host pirata o comparte registrable con algún expediente), `sin_bloqueo` (no hay órdenes causantes: se cierra solo) o `legitimo`.
4. Propuesta: para `legitimo` y `licenciatario`, `levantar_y_reemplazar`: levantar todas las órdenes causantes en todos los proveedores y, si eran por IP, reemplazarlas por bloqueos por dominio del host del stream de esa ubicación en todos los proveedores que aceptan dominio. Si la orden causante era por dominio contra el propio reclamante: `levantar`, sin reemplazo. Para `operacion_pirata`: `desestimar`. Excepción (§20, f-colateral-1): lo que la plataforma **vio** transmitir o publicar el partido no se levanta ni se veta aunque fuera inferido del mismo registrable, tampoco si se vio entre la propuesta y la firma.
5. Queda pendiente para el juez de turno, arriba de todo en su bandeja.
6. Al resolver: entrada `reclamo_resuelto`; levantamientos firmados (`LEVANTAR|orden_id|juez_id`); reemplazos con sello nuevo (el de esa entrada) y `origen: "reemplazo_reclamo"`.
7. Si otro reclamo pendiente se queda sin órdenes causantes activas, se cierra solo con referencia al que lo resolvió.

### 5.7 Traspaso de turno

Cuando cambia quién está de turno:

- Las ubicaciones y los reclamos pendientes pasan al juez entrante.
- Las órdenes dinámicas quedan con `requiere_ratificacion: true`.
- Se crea el `traspaso` (sección 10) y la entrada `traspaso_de_turno`.
- El juez saliente sigue pudiendo entrar, pero ve «Su turno terminó» y no puede firmar nada.
- El juez entrante ratifica con una acción: las órdenes dinámicas pasan a respaldarse con él, las órdenes en `espera_ratificacion` se firman y salen, y desde ahí los reintentos de bloqueos heredados los firma él.

### 5.8 Fin del partido

- Al llegar a `fin_min`: entrada `partido_finalizado`. No sale ninguna orden más. Cada ubicación todavía
  `pendiente` pasa a `sin_decidir` (terminal, sin órdenes), con `motivo_sin_decidir` («El partido terminó a los
  X min de la detección: ya no se pueden firmar órdenes.» y, si esperó más de 1 min desde que se armó, «El pedido
  estuvo esperando la firma W min.»), `sin_decidir_min` y una entrada `ubicacion_sin_decidir` por ubicación. Un
  expediente cuyas ubicaciones son todas `sin_decidir` queda `cerrado`.
- Al llegar a `fin_min + 5`: se comprueba que no quede ningún bloqueo por IP activo (entrada `vencimiento_verificado`, con alerta si queda alguno), se genera el acta y se exporta todo a `<salida>/entrega/`.

---

## 6. Turnos y permiso para firmar (`turnos.py`)

Los turnos salen de `GET /juzgados` (al arrancar y cada 30 segundos reales). El minuto sale del simulador.

`puede_firmar(juez_id)` hace **una consulta fresca a `GET /estado`** y devuelve `(bool, motivo)`. Verdadero solo si:

- el juez figura en `jueces_de_turno` de esa respuesta;
- le queda margen hasta el final de su turno: `hasta_min − minuto > max(0,05; (2 s + 1,5 × D) × acelerar / 60)`;
- ya empezó su turno con margen: `minuto − desde_min > max(0,02; (0,5 s + D) × acelerar / 60)`.

`D` es la duración real medida de esa consulta fresca (base de tiempo: segundos reales, convertidos a minutos de
partido con el `acelerar` del simulador). Si la consulta tardó más de 3 s, no se firma con ella.

Si falta menos que el margen para el cambio de turno, la firma se rechaza con «Su turno termina en segundos: este pedido pasa al juez entrante».

La ubicación se asigna al primer juez de turno según el orden de `turnos`. Si no hay nadie de turno, queda sin asignar y hay una alerta.

---

## 7. Auditoría (`auditoria.py`)

Archivo `<salida>/auditoria.jsonl`, una entrada por línea, solo se agrega:

```json
{"n": 17, "utc": "2026-11-12T01:23:45.678Z", "min": 2.412, "tipo": "decision_juez",
 "actor": "juez:jueza-laura-ficticia", "exp": "EXP-2026-000001", "datos": {}, "prev": "<hash de la entrada 16>", "hash": "<sha256>"}
```

- `hash = sha256(canonico(entrada sin el campo hash))`. La primera entrada lleva `prev` = 64 ceros.
- Escritura con candado, `flush` y `fsync` por entrada.
- `verificar_cadena(ruta) -> (ok, cantidad, errores)`.
- Al reanudar, se verifica la cadena existente y se sigue desde su cabeza.

Tipos de entrada: `inicio`, `reanudacion`, `deteccion_recibida`, `deteccion_descartada`, `expediente_abierto`, `ubicacion_armada`, `notificacion_juez`, `expediente_visto`, `decision_juez`, `orden_dinamica_otorgada`, `orden_marco`, `ampliacion_dinamica`, `ubicacion_sin_decidir`, `dinamica_revocada`, `aviso_corte_en_origen`, `orden_enviada`, `orden_recibida`, `orden_aplicada`, `orden_fallida`, `orden_reintentada`, `orden_rechazada`, `orden_vencida`, `orden_levantada`, `orden_en_espera`, `traspaso_de_turno`, `traspaso_ratificado`, `reclamo_recibido`, `reclamo_verificado`, `reclamo_resuelto`, `sesion_iniciada`, `sesion_cerrada`, `login_fallido`, `partido_finalizado`, `vencimiento_verificado`, `exportacion`, `alerta`.

Actores: `sistema`, `titular` (el detector del titular de derechos), `fiscalia`, `juez:<id>`, `fiscalia:<usuario>`, `proveedor:<id>`.

`inicio` guarda la versión, la dirección del simulador, el partido y las huellas de las respuestas de `/partido`, `/proveedores` y `/juzgados`.

`aviso_corte_en_origen`: al armar el expediente con una marca oficial válida (prefijo que no es de un licenciatario) y con sesión, una vez por sesión y sin esperar la firma del juez, se deja constancia del aviso al titular para que corte esa sesión en su plataforma. La plataforma no corta nada («simulado: el simulador no tiene esa API»).

---

## 8. Ciclo del motor (`motor.py`)

Un hilo, cada `--tick` segundos reales (por defecto 0,25):

1. Detecciones nuevas → análisis → expedientes, ubicaciones, descartes.
2. Cada 5 segundos reales, o si pasó un posible cambio de turno: `GET /estado` (reloj, aceleración, turno).
3. Traspaso, si cambió el juez de turno.
4. Ampliaciones dinámicas pendientes.
5. Seguimiento de órdenes; reintentos.
6. Reclamos.
7. Fin del partido.
8. Si algo cambió: sube la versión del estado, despierta a los que esperan en `/api/cambios` y guarda la instantánea.

Reglas:

- La red va **fuera** del candado del estado. Se consulta, y después se aplica con el candado tomado.
- Un error de red no tira el ciclo: marca `conexion: "sin_conexion"`, lo anota una vez y sigue.
- `reloj.ahora()` estima el minuto entre consultas: `minuto_ultimo + (monotonic − t_ultimo) × acelerar / 60`.
- Si el minuto del simulador retrocede, es que lo reiniciaron: alerta y no se sigue firmando.

### Persistencia y reanudación

- `<salida>/estado.json`: instantánea completa, escrita a un temporal y renombrada.
- Al arrancar: si existe `estado.json` y **no** viene `--nueva`: se reanuda si el partido es el mismo y el minuto del simulador no es menor que el guardado; si no, se sale con un mensaje claro. Con `--nueva`, la carpeta anterior se renombra a `<salida>.anterior-<fecha>` (nunca se borra) y se empieza de cero.
- Al reanudar: se reconcilian las órdenes con `GET /proveedores/<id>/ordenes`; las que estaban `por_enviar` se consultan antes de mandarlas. Las sesiones web no se guardan: los jueces vuelven a entrar.

---

## 9. Usuarios y seguridad (`usuarios.py`, `api.py`)

`config/jueces_demo.json`:

```json
{
  "aviso": "Usuarios y claves de DEMOSTRACIÓN para el simulador del hackathon. No usar en producción.",
  "usuarios": [
    {"usuario": "laura", "clave_demo": "<a elección>", "rol": "juez", "juez_id": "jueza-laura-ficticia"},
    {"usuario": "martin", "clave_demo": "<a elección>", "rol": "juez", "juez_id": "juez-martin-ejemplo"},
    {"usuario": "fiscalia", "clave_demo": "<a elección>", "rol": "fiscalia", "nombre": "Fiscalía (demostración)"}
  ],
  "claves_firma_demo": {"jueza-laura-ficticia": "demo-clave-laura-0b7e", "juez-martin-ejemplo": "demo-clave-martin-4c21"}
}
```

- Las contraseñas de demostración se eligen al crear el archivo y **solo se escriben ahí** (no en el README, no en la salida de los comandos, no en los informes). El README remite al archivo.
- Al cargar, cada contraseña se deriva con PBKDF2-HMAC-SHA256 (sal aleatoria por usuario, 200 000 vueltas) y se compara con `hmac.compare_digest`.
- Sesión: ficha de `secrets.token_urlsafe(32)` en una cookie `mp_sesion` con `HttpOnly; SameSite=Strict; Path=/`. Guardada del lado del servidor; vence a las 12 horas.
- Tope de intentos: 5 fallos seguidos del mismo usuario lo traban 30 segundos (`429`).
- Todo `POST` exige `Content-Type: application/json`. No se habilita CORS.
- Cada ruta comprueba el rol del lado del servidor. Un juez solo recibe lo que tiene asignado y solo mientras está de turno.
- Archivos estáticos: la ruta se resuelve y se comprueba que quede dentro de `marca/web/`.
- Por defecto escucha en `127.0.0.1`. Con `--host 0.0.0.0` se abre a la red local (para el celular del juez).
- Dos jueces a la vez en la misma computadora: una ventana normal y una de incógnito, o dos dispositivos.

---

## 10. API de la plataforma

Base: `http://<host>:<puerto>`. Todo es JSON en UTF-8. Errores: `{"error": "texto para mostrar", "codigo": "..."}` con códigos `no_autenticado` (401), `sin_permiso` (403), `fuera_de_turno` (403), `no_encontrado` (404), `conflicto` (409), `invalido` (422), `partido_finalizado` (409), `trabado` (429), `sin_conexion` (503).

### Rutas

| Método y ruta | Quién | Qué hace |
|---|---|---|
| `GET /api/salud` | cualquiera | `{ok, version, conexion, minuto, partido}` |
| `POST /api/login` | cualquiera | cuerpo `{usuario, clave}` → `Yo` + cookie |
| `POST /api/logout` | con sesión | cierra la sesión |
| `GET /api/yo` | con sesión | `Yo` |
| `GET /api/cambios?v=N` | cualquiera | espera hasta 20 s a que la versión supere `N`; responde `{v, minuto}` |
| `GET /api/juez/bandeja` | juez | `Bandeja` |
| `POST /api/juez/ubicaciones/<exp>/<n>/aprobar` | juez de turno, asignado | cuerpo `{alcance: "ubicacion"\|"filtracion", forzar_tipo?: "ip"\|"dominio", fundamento?: str}` |
| `POST /api/juez/ubicaciones/<exp>/<n>/rechazar` | juez de turno, asignado | cuerpo `{motivo}` (obligatorio) |
| `POST /api/juez/ubicaciones/<exp>/<n>/levantar` | juez de turno | cuerpo `{motivo}`; levanta todos los bloqueos activos de esa ubicación |
| `POST /api/juez/traspaso/ratificar` | juez de turno | ratifica lo heredado |
| `POST /api/juez/dinamicas/<exp>/revocar` | juez de turno | cuerpo `{motivo}` |
| `POST /api/juez/reclamos/<id>/resolver` | juez de turno | cuerpo `{accion: "levantar_y_reemplazar"\|"levantar"\|"desestimar", fundamento?: str}` (`fundamento` obligatorio al desestimar) |
| `GET /api/sala` | fiscalía | `Sala` |
| `GET /api/publico/registro` | cualquiera | `RegistroPublico` |
| `GET /api/publico/ordenes/<orden_id>` | cualquiera | `OrdenPublica` |

Las acciones del juez devuelven `{ok: true, bandeja: Bandeja}`.

`forzar_tipo` distinto de la recomendación exige `fundamento` de al menos 10 caracteres. Con alcance `filtracion` y la orden dinámica deshabilitada: `422`.

Páginas: `GET /` → `web/index.html`; `/juez`, `/sala`, `/transparencia` → el `.html` del mismo nombre; `/orden/<orden_id>` → `web/orden.html`; `/static/<ruta>` → `web/static/<ruta>`. Todo con `Cache-Control: no-cache`.

### Objetos

```jsonc
// Reloj
{"minuto": 37.62, "hora": "18:37:37", "fin_min": 105, "finalizado": false, "cerrado": false,
 "acelerar": 6.0, "conexion": "ok",
 "partido": {"id": "practica-01", "nombre": "...", "titular": "Liga Profesional Ficticia"},
 "de_turno": [{"juez_id": "jueza-laura-ficticia", "nombre": "Dra. Laura Ficticia",
               "juzgado_id": "jg-centro-3", "juzgado": "Juzgado de Garantías N.º 3 ...",
               "desde_min": -60, "hasta_min": 50}]}
// "hora" = hora de partido (inicio_iso + minuto), o null. "cerrado" = minuto >= fin_min + 5.
// La web estima el minuto entre respuestas: minuto + segundos_transcurridos × acelerar / 60.

// Yo
{"usuario": "laura", "rol": "juez", "nombre": "Dra. Laura Ficticia",
 "juez_id": "jueza-laura-ficticia", "juzgado_id": "jg-centro-3", "juzgado": "...",
 "dinamica_habilitada": true, "v": 412, "reloj": Reloj}
// Para rol "fiscalia": juez_id, juzgado_id y juzgado van en null.

// Orden
{"orden_id": "ord-0001-u1-aurora-01-9f3a...", "proveedor": "aurora", "proveedor_nombre": "Conectividad Aurora (ficticio)",
 "tipo": "ip", "objetivo": "203.0.113.10", "vence_min": 105,
 "juez_id": "jueza-laura-ficticia", "juzgado_id": "jg-centro-3",
 "estado": "aplicada", "intento": 1, "origen": "decision", "reemplaza": null,
 "enviada_min": 2.41, "recibida_min": 2.41, "aplicada_min": 2.93, "finalizada_min": null, "motivo": null}
// estado: por_enviar | recibida | aplicada | fallida | vencida | levantada | rechazada | espera_ratificacion
// origen: decision | reintento | reemplazo_reclamo

// Ubicacion
{"n": 1, "ref": "EXP-2026-000001/U1", "estado": "aprobada",   // pendiente | aprobada | rechazada
 "host": "s1.pelotaya.test", "ip": "203.0.113.10", "asn": 64600, "organizacion": "Bruma Hosting Dedicado (ficticio)",
 "pagina": "https://pelotaya.test/en-vivo", "stream_url": "https://s1.pelotaya.test/hls/en-vivo/index.m3u8",
 "primera_deteccion_min": 2.0, "ultima_deteccion_min": 32.0, "detecciones": ["D-0001", "D-0005"], "n_detecciones": 2,
 "continuidad": null,            // o {"de_ubicacion": 1, "criterio": "misma_marca" | "mismo_sitio"}
 "senal": {"marca": "LP26-PRA-OFI-S048211", "prefijo": "LP26-PRA-OFI", "origen": "Señal oficial del titular (plataforma propia)",
           "sesion": "S048211", "clase": "pirata", "motivo": "...", "observaciones": []},
 "captura": {"sha256": "77b14e...", "bytes": 64, "formato": "mpegts", "duracion_seg": 6, "capturada_min": 2.0,
             "sync_mpegts": true, "repetida": false, "valida": true},
 "coherencia": {"host_en_url": true, "ip_en_dns_del_host": true, "host_en_dns_de_la_ip": true, "asn_coincide": true,
                "ok": true, "completa": true, "observaciones": []},
 "colateral": {"dominios_en_ip": ["s1.pelotaya.test", "s1-respaldo.pelotaya.test"], "propios": ["s1.pelotaya.test", "s1-respaldo.pelotaya.test"],
               "ajenos": [], "red_compartida": false, "riesgo": "nulo",   // nulo | medio | alto | desconocido
               "recomendacion": "ip",                                     // ip | dominio | ninguna
               "motivo": "...", "limpia": true},
 "promocion": [{"red": "x", "url": "https://x.example/...", "minuto": 1.0}],
 "propuesta": {"tipo": "ip", "vence_min": 105, "fundamento": "...",
               "objetivos_por_proveedor": {"aurora": [{"tipo": "ip", "objetivo": "203.0.113.10"}],
                                           "valle": [{"tipo": "dominio", "objetivo": "s1.pelotaya.test"},
                                                     {"tipo": "dominio", "objetivo": "s1-respaldo.pelotaya.test"}]},
               "sin_cobertura": []},
 "huella": "<sha256, 64 hex>", "armado_min": 2.031, "armado_utc": "...",
 "asignada_a": "jueza-laura-ficticia", "notificada_min": 2.031, "vista_min": 2.2,
 "decision": {"tipo": "firma",                 // firma | ampliacion_dinamica
              "aprobada": true, "juez_id": "jueza-laura-ficticia", "juez": "Dra. Laura Ficticia",
              "juzgado_id": "jg-centro-3", "juzgado": "...", "min": 2.41, "utc": "...",
              "alcance": "filtracion",          // ubicacion | filtracion
              "forzado": null,                  // o {"tipo": "ip", "fundamento": "..."}
              "motivo_rechazo": null, "sello": "<32 hex>", "entrada": 17, "ya_cubiertos": []},   // null si está pendiente
 "ordenes": [Orden],
 "cobertura": {"clientes_cubiertos_pct": 100.0, "proveedores_aplicados": 4, "proveedores_total": 4,
               "primer_bloqueo_min": 0.93,      // minutos desde la primera detección; null si todavía no hay
               "completo_min": 7.1,             // minutos hasta que aplicaron todos; null si falta alguno
               "visibilidad_residual_pct": 3.4}}
// cobertura.visibilidad_residual_pct: misma cuenta que el verificador, desde la primera detección hasta
// la primera detección de la ubicación siguiente del expediente (o hasta ahora, o hasta fin_min).

// Expediente
{"id": "EXP-2026-000001", "num": 1, "titulo": "pelotaya.test", "sitio": "pelotaya.test", "creado_min": 2.031,
 "estado": "activo",             // pendiente (hay una ubicación pendiente) | activo | rechazado | cerrado
 "filtracion": {"clave": "LP26-PRA-OFI-S048211", "sesion": "S048211", "marcas": ["LP26-PRA-OFI-S048211"],
                "prefijo": "LP26-PRA-OFI", "origen": "Señal oficial del titular (plataforma propia)"},
 "dinamica": null,               // u objeto de la sección 5.4
 "corte_en_origen": null,        // o {"min": 2.41, "sesion": "S048211", "texto": "..."}
 "ubicaciones": [Ubicacion]}

// Descarte
{"deteccion_id": "D-0002", "minuto": 4.0, "host": "envivo.canalnorte.test", "ip": "192.0.2.10",
 "pagina": "...", "marca": "LP26-PRA-LIC-NORTE", "clase": "licenciatario",   // licenciatario | otra_senal | sin_marca
 "motivo": "...", "veces": 3, "ultima_min": 84.0}

// Reclamo
{"id": "R-001", "minuto": 13.4, "dominio": "panaderia-la-espiga.test", "proveedor": "aurora",
 "proveedor_nombre": "...", "mensaje": "...",
 "estado": "pendiente",          // pendiente | resuelto | desestimado | cerrado
 "asignado_a": "jueza-laura-ficticia",
 "verificacion": {"ips": ["192.0.2.50"], "clase_reclamante": "legitimo",   // legitimo | licenciatario | operacion_pirata | sin_bloqueo
                  "ordenes_causantes": [{"orden_id": "...", "proveedor": "aurora", "tipo": "ip", "objetivo": "192.0.2.50",
                                         "exp": "EXP-2026-000003", "n": 1}],
                  "explicacion": "..."},
 "propuesta": {"accion": "levantar_y_reemplazar",
               "levantar": [{"orden_id": "...", "proveedor": "aurora"}],
               "reemplazo": [{"proveedor": "aurora", "tipo": "dominio", "objetivo": "tv.verpartido-hd.test"}],
               "explicacion": "..."},
 "resolucion": null}             // o {"accion", "juez_id", "juez", "min", "fundamento", "minutos_hasta_resolver", "por_reclamo": null | "R-001"}

// Traspaso
{"min": 50.0, "de": [{"juez_id": "...", "nombre": "..."}], "a": [{"juez_id": "...", "nombre": "..."}],
 "requiere_ratificacion": true, "ratificado": null,   // o {"juez_id", "nombre", "min"}
 "resumen": {"ubicaciones_pendientes": 0, "reclamos_pendientes": 0, "bloqueos_vigentes": 11,
             "dinamicas": [{"exp": "EXP-2026-000001", "titulo": "pelotaya.test", "sesion": "S048211"}],
             "ordenes_en_espera": 0}}

// Aviso
{"n": 9, "min": 37.6, "tipo": "ampliacion_dinamica",   // ampliacion_dinamica | orden_fallida | reintento | reclamo | traspaso | alerta
 "texto": "...", "exp": "EXP-2026-000001", "para": "jueza-laura-ficticia"}   // "para" en null = para la sala

// Bandeja (GET /api/juez/bandeja)
{"v": 412, "reloj": Reloj, "yo": Yo,
 "turno": {"de_turno": true, "desde_min": -60, "hasta_min": 50, "faltan_min": 12.4,
           "puede_firmar": true, "motivo": null,
           "proximo": null},     // si no está de turno y le toca después: {"desde_min": 50, "faltan_min": 12.4}
 "traspaso": null,               // Traspaso que le toca ratificar, o null
 "reclamos": [Reclamo],          // pendientes, asignados a él
 "pendientes": [{"expediente": Expediente, "n": 2,
                 "automatica": {"posible": false, "motivo": "La orden dinámica espera la ratificación del juez entrante."}}],
 "dinamicas": [{"exp": "EXP-2026-000001", "titulo": "pelotaya.test", "sesion": "S048211",
                "otorgada_min": 2.41, "ubicaciones": 2, "requiere_ratificacion": false}],
 "avisos": [Aviso],              // los últimos 30 para él, del más nuevo al más viejo
 "historial": [{"expediente": Expediente, "n": 1}]}   // ubicaciones que decidió él, últimas 30
// Fuera de turno: de_turno false; traspaso null; reclamos, pendientes, dinamicas y avisos vacíos; historial sí.

// Sala (GET /api/sala)
{"v": 412, "reloj": Reloj, "cabeza_auditoria": {"n": 240, "hash": "..."},
 "kpis": {"expedientes": 4, "ubicaciones_bloqueadas": 5, "ubicaciones_pendientes": 0,
          "clientes_total": 5200000, "clientes_cubiertos_pct": 100.0,
          "primer_bloqueo_promedio_min": 0.9, "visibilidad_residual_promedio_pct": 3.8,
          "ordenes_con_dano_colateral": 0, "reclamos_pendientes": 0, "reclamos_resueltos": 0,
          "ordenes": {"enviadas": 22, "recibidas": 0, "aplicadas": 20, "fallidas": 2, "rechazadas": 0,
                      "vencidas": 0, "levantadas": 0, "en_espera": 0},
          "descartes": {"licenciatario": 1, "otra_senal": 1, "sin_marca": 0}},
 "proveedores": [{"id": "aurora", "nombre": "...", "tamano": "grande", "clientes": 3800000,
                  "capacidades": ["ip", "dominio"], "activas": 5, "fallidas": 0, "demora_promedio_min": 0.5}],
 "expedientes": [Expediente], "descartes": [Descarte], "reclamos": [Reclamo],
 "traspasos": [Traspaso], "avisos": [Aviso],          // últimos 50
 "auditoria": [EntradaDeAuditoria]}                    // últimas 80, de la más nueva a la más vieja

// RegistroPublico (GET /api/publico/registro)
{"v": 412, "reloj": {"minuto": 37.62, "hora": "18:37:37", "fin_min": 105, "finalizado": false,
                      "partido": {"id": "...", "nombre": "...", "titular": "..."}},
 "cabeza_auditoria": {"n": 240, "hash": "..."},
 "resumen": {"bloqueos_vigentes": 11, "bloqueos_vencidos": 0, "bloqueos_levantados": 0,
             "sitios_bloqueados": 4, "reclamos_recibidos": 0, "reclamos_resueltos": 0},
 "bloqueos": [{"orden_id": "...", "expediente": "EXP-2026-000001", "sello": "<32 hex>",
               "tipo": "ip", "objetivo": "203.0.113.10", "proveedor": "aurora", "proveedor_nombre": "...",
               "estado": "aplicada", "desde_min": 2.93, "hasta_min": null, "vence_min": 105,
               "juez": "Dra. Laura Ficticia", "juzgado": "...", "decision_min": 2.41,
               "motivo": "Retransmisión no autorizada del partido ...", "levantamiento": null}]}
// Solo órdenes que llegaron a aplicarse. "levantamiento": {"min", "juez", "motivo", "reclamo"} o null.

// OrdenPublica (GET /api/publico/ordenes/<orden_id>)
{"orden": Orden, "expediente": "EXP-2026-000001", "ubicacion": 1, "sello": "...", "huella": "...",
 "juez": "...", "juzgado": "...", "decision_min": 2.41, "decision_hora": "18:02:24",
 "texto_llano": "Se ordena a Conectividad Aurora bloquear la IP 203.0.113.10 hasta ...",
 "por_que": ["Lleva la marca de agua de la señal oficial del partido ...", "..."],
 "evidencia": {"marca": "...", "host": "...", "ip": "...", "asn": 64600, "organizacion": "...",
               "captura_sha256": "...", "riesgo": "nulo", "motivo_colateral": "..."},
 "kit": [{"equipo": "MikroTik RouterOS 7", "aplicar": "...", "quitar": "..."},
         {"equipo": "Unbound", "aplicar": "...", "quitar": "..."}],
 "como_objetar": "..."}
```

### El kit del proveedor (`kit.py`)

Responde a la objeción de los proveedores chicos: la orden llega con las líneas para copiar y pegar. Cada elemento trae `equipo`, `aplicar` y `quitar`. El tiempo de vida se calcula con los minutos que faltan hasta `vence_min`.

- Bloqueo por **IP**:
  - MikroTik RouterOS 7: `/ip firewall address-list add list=bloqueo-judicial address=<ip> timeout=<XhYm> comment="<expediente> <sello corto>"` (la regla `chain=forward dst-address-list=bloqueo-judicial action=drop` se carga una sola vez; mostrarla como nota).
  - nftables: `nft add element inet filter bloqueo_judicial { <ip> timeout <N>m }`.
- Bloqueo por **dominio**:
  - MikroTik RouterOS 7: `/ip dns static add name=<host> type=NXDOMAIN comment="<expediente> <sello corto>"`.
  - Unbound: `unbound-control local_zone <host>. always_nxdomain` y, para quitar, `unbound-control local_zone_remove <host>.`.
  - BIND (zona RPZ): `<host> CNAME .`.

Cada kit lleva la leyenda «Ejemplos de referencia: adaptarlos a la red de cada proveedor».

### El cliente del proveedor (`herramientas/cliente_proveedor.py`)

Notas de uso del cliente (tal cual las dejó el agente que lo escribió):

- estado por defecto `.<nombre>.estado.json` al lado de la primera salida;
- campo opcional de primer nivel `"acelerar"` (1 a 1000) en la lista del proveedor;
- el estado suma los campos opcionales `max_minuto`, `levantadas` y `huella`, y `lecturas` pasa a tener 3 elementos (VERSION_ESTADO sigue en 1);
- ningún bloqueo dura más de 6 horas desde la última lista buena;
- una lista con minuto más bajo que el máximo recibido (0,5 de tolerancia) solo quita;
- una orden levantada nunca vuelve.

---

## 11. Pantallas (`marca/web/`)

Archivos: `index.html`, `juez.html`, `sala.html`, `transparencia.html`, `orden.html`, y `static/` con `css/` y `js/`. Sin compilación, sin dependencias, sin recursos externos.

Reglas comunes:

- Cada pantalla pide su dato (`/api/juez/bandeja`, `/api/sala`, `/api/publico/registro`) y después se queda en `GET /api/cambios?v=<v>`; cuando cambia la versión, vuelve a pedir. Si la conexión falla, reintenta cada 2 segundos y muestra «Sin conexión con la plataforma».
- El reloj del partido corre solo entre respuestas, con `acelerar`.
- Todo texto que venga de la API se pone con `textContent`.
- Tiene que verse bien en un celular de 360 px de ancho y en un proyector de 1920 px. Un solo tema oscuro («Estadio de noche»).
- Los minutos se muestran como «min 37,5» y, si hay `hora`, también como hora de partido.

### `/juez` — la bandeja del juez (primero el celular)

1. **Ingreso** con usuario y contraseña. Errores claros (`trabado`, credenciales).
2. **Cabecera**: nombre y juzgado, reloj del partido, y el turno: «De turno hasta el min 50 (faltan 12)» o «Su turno terminó» o «Su turno empieza en el min 50».
3. **Traspaso** (si hay): qué hereda (bloqueos vigentes, órdenes dinámicas, órdenes en espera) y un botón «Ratificar lo heredado».
4. **Reclamos** pendientes: quién reclama, qué comprobó la plataforma, qué propone, y los botones «Levantar y reemplazar» / «Levantar» / «Desestimar» (este último pide fundamento).
5. **Pedidos pendientes**. Cada uno entra en una pantalla de celular sin perder nada esencial:
   - Qué se pide bloquear y de qué sitio. Si es una mudanza, una franja «Mismo stream que ya bloqueó: ubicación 1 → 2» con el criterio.
   - Tres comprobaciones con su resultado: **es la señal del partido** (marca, origen, sesión), **servidor identificado** (host, IP, ASN y organización; coherencia), **daño colateral** (semáforo según `riesgo`, la oración de `motivo` y la lista de ajenos).
   - **Qué se bloquea en cada proveedor** (`objetivos_por_proveedor`) y hasta cuándo.
   - La huella y el sha256 de la captura, plegados en «Ver evidencia completa», junto con las promociones y las detecciones.
   - Alcance, si `dinamica_habilitada`: «Solo este servidor» o «Este stream, adonde se mude, hasta el final del partido».
   - Botón principal «Firmar bloqueo». Botón secundario «Rechazar» (pide motivo).
   - Plegado, «Apartarme de la recomendación»: elegir IP o dominio, con fundamento obligatorio y una advertencia en rojo si deja sitios ajenos bloqueados (con la cuenta).
   - Si `automatica.posible` es falso y hay motivo, se muestra por qué no se amplió sola.
6. **Avisos**: ampliaciones automáticas (con «Revocar la orden dinámica»), órdenes fallidas y reintentos.
7. **Historial** de lo que firmó, con el estado de cada proveedor y «Levantar bloqueo» (pide motivo).
8. **Aviso de pedido nuevo**: sonido corto (Web Audio), vibración si el dispositivo la tiene, título de la pestaña con la cantidad pendiente y, si el navegador lo permite, una notificación del sistema. Un botón «Activar avisos» al entrar, porque el sonido necesita un gesto del usuario.
9. Fuera de turno no hay botones de firma. Un error `fuera_de_turno` se muestra con su texto y la bandeja se recarga.

### `/sala` — la sala de situación (fiscalía; pensada para proyector)

- Ingreso (rol fiscalía).
- Arriba: partido, reloj grande, juez de turno, estado de la conexión con el simulador.
- Indicadores: clientes cubiertos, tiempo promedio al primer bloqueo, visibilidad residual, órdenes con daño colateral (tiene que leerse el 0), reclamos.
- **Una pista por expediente**: la filtración (sitio y sesión), sus ubicaciones encadenadas de izquierda a derecha (s1 → s2 → s3) y, en cada ubicación, un punto por proveedor con su estado y su demora. Si el expediente tiene orden dinámica, se ve. Esta pista es la imagen de la «marca personal» y es lo que se muestra en el video.
- Proveedores: clientes, capacidades, órdenes activas y fallidas.
- Descartes con su motivo (licenciatario, otra señal, sin marca).
- Reclamos y traspasos.
- La cola de la auditoría en vivo, con el hash de la cabeza.

### `/transparencia` — registro público (sin ingreso)

Qué se bloqueó, cuándo, por orden de quién y hasta cuándo. Filtro por estado. Cada fila enlaza a `/orden/<orden_id>`. Muestra la cabeza de la auditoría y explica en dos oraciones cómo se verifica.

### `/orden/<orden_id>` — la orden en lenguaje llano (sin ingreso)

Lo que lee un proveedor: qué se le pide, hasta cuándo, por qué (`por_que`), quién lo ordenó, el sello, el estado y el **kit** con botones de copiar. Y cómo objetar.

### `/` — portada

Qué es, y tres entradas: Juez, Sala, Registro público.

### API simulada para desarrollar las pantallas (`herramientas/api_simulada.py`)

Servidor de biblioteca estándar que sirve `marca/web/` y responde todas las rutas de la sección 10 con datos de ejemplo coherentes, con un guion que avanza solo (pedido nuevo, firma, mudanza con ampliación automática, traspaso, reclamo, final). Acepta las acciones y cambia su estado en memoria. Sirve para diseñar sin el motor y para mostrar las pantallas sin simulador.

---

## 12. Línea de comandos

```
python3 -m marca servir   --simulador http://HOST:8080 [--puerto 8700] [--host 127.0.0.1]
                          [--salida salida] [--nueva] [--config config/jueces_demo.json]
                          [--sin-dinamica] [--tick 0.25]
python3 -m marca chequear --simulador http://HOST:8080 [--config ...]
python3 -m marca exportar --salida salida --destino entrega
python3 -m marca verificar <carpeta> [--registro-simulador ruta/registro.jsonl] [--config ...]
```

- `chequear`: revisión previa al partido. Comprueba conexión, reloj y aceleración, partido, proveedores y capacidades, que cada juez de los turnos tenga usuario y clave de firma en la configuración, que la carpeta de salida se pueda escribir y que estén las pantallas. No manda ninguna orden. Sale con código distinto de 0 si algo falta.
- `servir` imprime al arrancar las direcciones de las pantallas y el estado de la revisión previa.

---

## 13. Exportación y verificación

`exportar` escribe en la carpeta de destino:

```
expedientes/EXP-2026-000001.json     expediente completo: cada ubicación con su bloque "sellado", huella, decisión, órdenes y redetecciones
expedientes/EXP-2026-000001.md       el mismo expediente, para leer
capturas/D-0001.ts                   capturas de las ubicaciones exportadas
auditoria.jsonl                      el registro encadenado completo
testigos/proveedores.json            copia de lo que guardó cada proveedor (qué prueba y qué no: ver abajo)
acta-del-partido.md                  resumen: filtraciones, tiempos, cobertura, descartes, reclamos, traspasos
resumen.json                         partido, proveedores, descartes, reclamos y traspasos (para máquinas)
LEEME.md                             cómo verificar, en pocas líneas
MANIFIESTO.json                      ruta, tamaño y sha256 de cada archivo del paquete (se escribe al final)
```

La **huella del paquete** es el sha256 de `MANIFIESTO.json`. `exportar` y `verificar` la imprimen (`Huella del paquete: …`) para publicarla en el README y en el video. El export del partido final va a `entrega/partido-final/`.

**Testigos de los proveedores.** En el partido final no tenemos el registro oficial del simulador (lo corre la organización), pero sí podemos pedir por la API pública lo que guardó cada proveedor. Esa copia la escribimos nosotros y su sha256 queda en la auditoría: atrapa un cambio torpe del paquete, pero **no es un testigo independiente**. Quien reescriba a la vez la auditoría, los testigos y su sha256 pasa este paso (límite aceptado: `herramientas/falsificar.py` lo demuestra y el LEEME lo dice). Lo independiente es `--registro-simulador` (el registro oficial), `--config` (las firmas HMAC) o la huella del paquete publicada de antemano. No existe `verificar --simulador URL`: `verificar` no consulta la red.

- El motor, justo antes de exportar al llegar a `fin_min + 5`, consulta `GET /proveedores/<id>/ordenes` de **todos** los proveedores y escribe `<salida>/testigos/proveedores.json`: `{"consultado_min", "consultado_utc", "simulador", "proveedores": {"<id>": [órdenes tal como las devuelve el simulador]}}`. Deja en la auditoría la entrada `testigos_guardados` con el sha256 de los bytes exactos escritos.
- Con el partido **en curso**, `python3 -m marca exportar` también los refresca. Con el partido **cerrado** (ya está en `<salida>/entrega` el paquete que la plataforma exportó y publicó al cierre), no pide testigos ni escribe la auditoría: copia ese paquete tal cual, con la plataforma viva o apagada y cuantas veces sea, y la huella es la que se publicó al cerrar; si la auditoría tiene entradas posteriores al cierre, avisa que no van en el paquete. La plataforma deja `<salida>/plataforma.json` con `{pid, host, puerto, instancia}`, y está viva si `GET /api/salud` responde en 2 s con esa misma `instancia`.
  - Si está viva, el comando deja el archivo `<salida>/pedir-testigos`. La plataforma lo consume en su ciclo, consulta a los proveedores y anota ella: la auditoría tiene un solo escritor, y el comando nunca la escribe.
  - Si no responde y hay conexión con el simulador, los consulta y los anota el propio comando.
  - Sin conexión, usa lo último guardado.
  - Funciona igual en cualquier sistema operativo: no usa señales ni pids.
- `exportar` copia `testigos/proveedores.json` al destino.

`verificar` no necesita conexión ni la plataforma. Comprueba y lista con ✓ o ✗:

0. El paquete contra `MANIFIESTO.json`: un archivo cambiado, faltante o sobrante da ✗ con su nombre. Los que crea el sistema operativo al abrir la carpeta (`.DS_Store`, `Thumbs.db`, `desktop.ini`) no cuentan. Sin manifiesto, se informa «sin manifiesto».
1. La cadena de auditoría completa.
2. Por ubicación: sha256 de la captura contra el archivo; huella recalculada desde `sellado`; encadenamiento con el antecedente.
3. Por decisión: que la entrada de auditoría exista, sea de esa ubicación y lleve esa huella; sello recalculado.
4. Por orden: que el `orden_id` termine en el sello; que el levantamiento, si lo hay, esté en la auditoría.
5. Con `--config`: las firmas de decisión y de levantamiento (HMAC). Cada `ampliacion_dinamica` debe cumplir lo siguiente; la firma se comprueba con `--config`:
   - la escribe el actor `sistema`;
   - nombra a `bajo_orden_dinamica_de` y a una `entrada_habilitante`, que existe, es anterior y es de ese expediente: la firma del juez con alcance «filtración», o la ratificación del entrante que lo incluye;
   - su firma usa el mensaje `AMPLIACION|exp|U<n>|huella|filtracion|juez|E<entrada habilitante>`.
6. Con `--registro-simulador`: que cada orden nuestra figure en el registro oficial con el mismo tipo, objetivo, vencimiento y juez; que el registro oficial no tenga órdenes que no estén en nuestra auditoría; que ninguna figure con `juez_de_turno: false`; que no haya ninguna `orden_rechazada`; y que el minuto de aplicación y el estado final de cada orden del paquete sean los del registro (con tolerancia; lo que el registro sabe después de exportar no es falla). Sin `--registro-simulador` el resultado es «coherente consigo mismo (sin cotejar con el registro oficial del simulador)», no «todo verifica».
7. Testigos, si está `testigos/proveedores.json`: (a) su sha256 coincide con el de la última entrada `testigos_guardados`; (b) cada orden nuestra que llegó a enviarse figura en el proveedor con el mismo `tipo`, `objetivo`, `vence_min` y `juez_id`; (c) el proveedor no tiene ninguna orden que no esté en nuestra auditoría; (d) el `orden_id` que guarda el proveedor termina en el sello recalculado. Si el archivo no está y la auditoría no tiene ninguna entrada `testigos_guardados`, el paso se informa como «no disponible», sin error; si falta y la auditoría dice que se guardaron, es ✗ («falta, y la auditoría dice que se guardaron»).

Si algo no cierra, dice qué archivo y qué campo, y sale con código 1.

---

## 14. Ensayo automático (`herramientas/ensayo.py`)

```
python3 herramientas/ensayo.py --repo-desafio "<ruta al repo del desafío>" [--acelerar 30]
        [--demora-juez 0.3] [--alcance filtracion|ubicacion] [--sin-dinamica]
        [--inicio-min 0] [--forzar-ip <host>] [--reiniciar-en <min>]
        [--puerto-simulador 8791] [--puerto 8792] [--salida salida-ensayo] [--escenario ...] [--verdad ...]
```

1. Arranca el simulador oficial como subproceso con `python3 -I`, con el registro en `<salida>/registro.jsonl`.
2. Arranca `python3 -m marca servir --nueva` contra ese simulador.
3. Corre un **juez automático** por cada juez de la configuración. Entra por la API web igual que una persona (`/api/login`, `/api/juez/bandeja` y las acciones), espera `--demora-juez` minutos de partido desde que ve cada pedido, y firma. Ratifica los traspasos y resuelve los reclamos con la acción propuesta. Con `--forzar-ip <host>`, firma por IP la ubicación de ese host (con fundamento), para provocar reclamos.
4. Con `--reiniciar-en <min>`: mata la plataforma en ese minuto y la vuelve a arrancar sin `--nueva`.
5. Espera hasta `fin_min + 5,5`, para todo, corre el verificador oficial (`--json`) y `python3 -m marca verificar <salida>/marca/entrega --registro-simulador ...`.
6. Imprime el informe oficial, un resumen y el veredicto contra los criterios de la sección 15. Código de salida 0 solo si se cumplen.

El juez automático es solo para ensayos y lo dice en pantalla al arrancar: en el partido final firman personas.

---

## 15. Criterios de aceptación (se comprueban ejecutando)

Pruebas unitarias (`python3 -m unittest discover -s tests`), como mínimo:

- `evidencia`: las situaciones del partido de práctica (servidor exclusivo con respaldo → IP y, para el proveedor que solo acepta dominio, los dos nombres; CDN con 11 ajenos → dominio; hosting compartido → dominio; licenciatario en su dominio → nunca; marca de otro partido → descarte; sin marca → descarte) y los bordes: prefijo parecido que no es válido, prefijo más largo gana, señal del licenciatario en dominio ajeno → pirata, subdominio de un dominio autorizado → licenciatario, sin datos de DNS → dominio, host en varias IP → dominio, host que es una IP literal, incoherencia entre la detección y el DNS.
- `sello`: la firma de una orden coincide con la que calcula el simulador (mismo algoritmo, valores fijos); el sello cambia si cambia un byte de la evidencia o de la entrada.
- `auditoria`: cambiar, borrar o reordenar una entrada rompe la verificación y se informa dónde.
- `turnos`: márgenes al principio y al final del turno; nadie de turno.
- `dominios`: registrable y cobertura.
- `verificar`: una exportación sana pasa; con un byte cambiado en la captura, en el sellado o en la auditoría, falla.

Ensayos contra el simulador oficial:

| # | Ensayo | Tiene que dar |
|---|---|---|
| A | Partido de práctica completo, alcance `filtracion`, demora del juez 0,3 min | 7 de 7 fases bloqueadas; 100 % de clientes cubiertos en cada fase; 0 órdenes con daño colateral; 0 falsos positivos; 0 bloqueos por IP activos después del partido; 0 reclamos; 0 órdenes rechazadas; 0 firmadas fuera de turno; verificación de integridad en verde, cruzada con el registro oficial |
| B | Igual, con `--sin-dinamica` | Los mismos ceros |
| C | `--inicio-min 44` | Traspaso creado y ratificado; 0 fuera de turno; las mudanzas posteriores se amplían solas después de ratificar |
| D | `--forzar-ip tv.verpartido-hd.test` | Llegan reclamos; todos quedan resueltos por levantamiento; el stream sigue bloqueado por dominio; no quedan órdenes rechazadas |
| E | `--reiniciar-en 30` | Sin órdenes duplicadas ni rechazadas; cadena de auditoría íntegra; el resto como A |

En cada ensayo se informa la visibilidad residual promedio y el tiempo al primer bloqueo de cada fase.

---

## 16. Desvíos

*(Anotar acá cualquier diferencia entre esta especificación y lo que se terminó implementando, con el motivo.)*

Contra el simulador oficial no hizo falta ningún desvío: los cinco ensayos cumplen la tabla de la sección 15 tal como está. Lo que sigue son defectos o huecos de diseño que aparecieron al implementar, y cómo se cerraron.

**Evidencia (sección 5)**

1. **Licenciatario también por la página.** La señal del licenciatario se trata como licenciatario si el host del stream **o** el host de la página están cubiertos por un dominio autorizado, no solo el del stream. Motivo: un licenciatario que sirve desde un CDN propio con nombre ajeno no puede terminar bloqueado. Es el error que no tiene vuelta atrás, así que ante la duda no se bloquea.
2. **`misma_marca` solo con sesión.** La regla de «misma marca → mismo expediente» se aplica solo cuando la marca trae sesión. Sin sesión no se juntan sitios distintos en un expediente. Motivo: sin sesión, la marca identifica al partido y no a la filtración, y juntar sitios distintos haría que una firma alcance a un tercero.
3. **Host que es una IP literal.** `ip_en_dns_del_host` es verdadero si el host es esa misma IP, y `host_en_dns_de_la_ip` queda sin dato. La regla 1 («ninguna») se aplica también cuando la detección y el DNS no coinciden. Motivo: la especificación no decía cómo coherenciar un host sin nombre, y bloquear por IP con datos incoherentes es justamente el riesgo de colateral.
4. **Orden de las clases de reclamo.** Se evalúa primero `sin_bloqueo` (el reclamante no está bloqueado por nada nuestro), después `licenciatario`, `operacion_pirata` y `legitimo`. Motivo: un reclamo sobre algo que ya no bloqueamos no debe disparar levantamientos.

**Órdenes (secciones 6 a 8)**

5. **Deduplicación más amplia.** Antes de crear una orden se descartan también las que están en `espera_ratificacion` y los pares (tipo, objetivo) **vetados** porque un juez los levantó. Motivo: sin eso, después de un levantamiento por reclamo la ampliación o los reintentos volvían a mandar el mismo bloqueo.
6. **Levantar una orden que nunca salió.** Queda `levantada` con `anulada: true` y no se manda nada al proveedor. Las que se cancelan antes de salir (fin del partido, vencimiento) quedan `no_enviada`. Motivo: un `POST /levantar` sobre una orden que el proveedor no tiene da 404, y no hace falta.
7. **Después de un error de red al enviar**, la orden queda `incierta`. A los 3 s se hace `GET` y solo con 404 se reenvía, con el mismo `orden_id`. Motivo: es la regla dura 2. Los 3 s evitan preguntar antes de que el proveedor termine de registrar.
8. **Antes de cada ronda de despacho se guarda el estado** con las órdenes marcadas `en_vuelo`, y la entrada `orden_enviada` se escribe **antes** del `POST`. Motivo: si la plataforma muere a mitad de envío, al reanudar sabe qué pudo haber salido. Todo lo `en_vuelo` o `enviada` pasa a `incierta`, y nunca hay dos envíos del mismo `orden_id` sin un `GET` en el medio.

**Reloj y turnos (sección 6)**

9. **Retroceso del reloj** se mide contra la **última lectura** del simulador, no contra la estimación local, con un umbral de 1 min. Las respuestas viejas que llegan fuera de orden se ignoran. Motivo: con la estimación, una respuesta lenta se tomaba como retroceso.
10. **Frecuencia de `/estado`.** El minuto se toma de `/detecciones` en cada paso. `/estado` se pide cada 5 s, o en cada paso cuando falta poco para un cambio de turno. Antes de firmar y antes de cada `POST` se pide siempre uno fresco, como dice la sección 6. Motivo: no saturar al simulador sin perder el borde del turno.

**Persistencia y auditoría (secciones 9 y 13)**

11. **Línea de auditoría incompleta.** Al reanudar, si la última línea quedó sin salto de línea (la plataforma murió escribiéndola), se descarta y su contenido queda en `reanudacion.datos.linea_incompleta_descartada`. Las líneas completas no se tocan nunca. Motivo: sin eso, un `SIGKILL` en mal momento dejaba una cadena que no verificaba y la plataforma no podía reanudar. El ensayo E lo ejercita.
12. **Testigos de los proveedores.** Es una entrada nueva de auditoría, `testigos_guardados`. Están el archivo `testigos/proveedores.json` y el paso 7 de `verificar` (sección 13). Motivo: en el partido final no tenemos el registro oficial, y los testigos prueban el sello con lo que guardó cada proveedor.
13. **`exportar` con la plataforma viva** le pide los testigos a la plataforma con el archivo `<salida>/pedir-testigos`, en vez de escribir él en la auditoría. Sabe si la plataforma está viva por `plataforma.json` más `GET /api/salud` con la misma `instancia`. Primero se hizo con `SIGUSR1` y `plataforma.pid`, y se reemplazó por los motivos siguientes:
    - en Windows, `os.kill(pid, 0)` termina el proceso;
    - en Windows `SIGUSR1` no existe, y entonces el comando escribía la auditoría con la plataforma viva;
    - un pid viejo puede ser de otro programa.

    Motivo: la auditoría tiene un solo escritor por vez.
14. **Extras en la exportación y en la API.**
    - La exportación incluye `resumen.json` y `MANIFIESTO.json`.
    - `/api/salud` devuelve además `v`, `cerrado`, `exportado` (verdadero recién cuando la exportación terminó, manifiesto incluido) e `instancia`.
    - La respuesta de aprobar trae `resultado` (`alcance_pedido`, `alcance_efectivo`) y `aviso` si corresponde.
    - Las vistas suman campos y no renombran ni quitan ninguno:
      - en la decisión, `bajo_orden_de` y `texto`;
      - en el registro público, `decision_tipo`, `bajo_orden_de` y `decision_texto`;
      - en la página de la orden, `decision`;
      - en el reloj, `exportado`.

**Robustez para el partido final (revisión del motor)**

15. **Un dato mal formado no frena el partido.**
    - Cada etapa del ciclo atrapa cualquier excepción: va con traceback a la consola, avisa en la sala con la clave `error-<etapa>`, y las etapas siguientes corren en el mismo ciclo. Antes, solo se atrapaban los errores de red: una detección rara trababa el ciclo hasta el final, porque `desde` no avanzaba.
    - Cada detección se valida antes de analizarla y se procesa por separado. Tiene que traer un `id` de texto, un `minuto` numérico, un `host_stream` que sea nombre de host válido o IP literal, y una `ip_servidor` válida.
    - Una detección inválida, o que falla al procesarse, queda vista y se audita como `deteccion_invalida`, con el motivo en una línea. Se avisa en la sala y no se pide bloqueo, y `desde` avanza siempre.
    - Lo mismo vale para cada reclamo (`reclamo_invalido`, una sola vez por reclamo).
    - Si falla el armado de la primera ubicación, el expediente recién abierto se anula (`expediente_anulado`): nunca queda un expediente con cero ubicaciones.
16. **Margen de envío proporcional a la aceleración.** No se manda una orden si faltan `max(0,05 min, (2 s + 1,5 × D) reales × acelerar / 60)` o menos (D: la latencia medida) para el final o para su `vence_min`. Es la misma forma que el margen de fin de turno. Antes eran 0,05 min fijos: 0,1 s reales a x30. Con la latencia de un simulador remoto, el `POST` podía llegar vencido (`422`, que el verificador oficial cuenta como rechazada). La orden que no sale queda `no_enviada`, con alerta.
17. **Menos carga sobre el simulador de la organización.**
    - Detecciones: en cada ciclo.
    - Proveedores con alguna orden en tránsito (`recibida`): en cada ciclo, porque de eso dependen los tiempos de bloqueo y los reintentos.
    - Proveedores que solo tienen órdenes `aplicada`: cada 2 s reales.
    - `/reclamos`: cada 1 s real.

    Antes se consultaba todo en cada ciclo de 0,25 s: unas 16 consultas por segundo solo de seguimiento.
18. **Ampliación dinámica transparente.**
    - La entrada `ampliacion_dinamica` la escribe el actor `sistema`, ya no `juez:<id>`. Lleva `bajo_orden_dinamica_de` (el juez que la respalda) y `entrada_habilitante`: la firma con alcance «filtración», o la ratificación del entrante.
    - Su firma usa un mensaje propio (`AMPLIACION|…|E<entrada habilitante>`), distinto del de una firma en persona. `verificar` la recalcula y comprueba que la entrada habilitante exista, sea anterior y sea de ese expediente.
    - Las vistas muestran «Ampliación automática del sistema bajo la orden marco {OM} de {A} (minuto a)[, ratificada por {B} en el minuto b]. No se firmó en persona.» (ronda 2b), y la orden sale con prefijo `amp-`.
    - La orden que va al proveedor no cambia: juez y firma del juez que respalda.
    - Motivo: nadie firma en nombre de un juez, y antes la auditoría lo hacía parecer.
19. **Alcance efectivo.** Si el juez firma con alcance «filtración» y la marca no trae sesión, no hay orden dinámica posible. Por eso se registra y se firma el alcance efectivo (`ubicacion`, con `alcance_pedido: filtracion`), y la respuesta trae el motivo para que la pantalla lo diga. Antes quedaba registrado «filtración» sin que se otorgara nada.
20. **Manifiesto del paquete.** `MANIFIESTO.json` se escribe al final de `exportar`, y `verificar` lo revisa primero (paso 0). Motivo: un cambio fuera de `sellado` (en un `.md`, el acta o `resumen.json`) pasaba la verificación, y la consigna pide detectar cualquier alteración posterior. Los archivos del sistema operativo (`.DS_Store`, `Thumbs.db`, `desktop.ini`) se ignoran: abrir la carpeta en el Finder no puede «alterar» el paquete.
21. **API: cuerpo no leído.** Si un `POST` se rechaza antes de leer el cuerpo (tipo de contenido, largo, tamaño, `Transfer-Encoding`), se cierra la conexión. Motivo: con keep-alive, esos bytes se interpretaban como el pedido siguiente.
22. **Kit de comandos.** Si el objetivo no es una IP o un nombre de host válidos, `kit` devuelve una sola entrada `{"equipo": "Objetivo no válido", "nota": …}` sin comandos; si el expediente o el sello traen caracteres raros, no devuelve nada: las líneas se pegan en un router. El nombre de archivo de cada captura sale de una sola función (`canon.nombre_captura`), la misma en el motor, la exportación y `verificar`. Los ids raros se sanean y llevan un trozo de su sha256, así dos ids nunca comparten archivo.
23. **El cierre se reintenta.**
    - Si fallan los testigos o la exportación del minuto `fin_min + 5`, se reintenta en cada ciclo hasta que quede exportado.
    - Sin conexión con el simulador, se exporta sin testigos después de 3 intentos, y se vuelve a exportar cuando lleguen.
    - `exportado` queda en `hitos` y en `/api/salud`.
24. **`servir --host 0.0.0.0`** imprime la dirección de red local para el celular del juez. La averigua con un socket UDP «conectado», que no manda paquetes. Si no se puede, dice cómo averiguarla.
25. **Auditoría dañada al reanudar.** Antes, si la cadena guardada no verificaba, la plataforma no arrancaba. En la mitad de un partido eso deja el resto sin bloqueos. Ahora pasa esto:
    - la cola dañada (desde la primera línea que no verifica) se aparta, sin borrarla, a `auditoria.danada-<fecha>.jsonl`;
    - se deja la entrada `auditoria_reparada` con el sha256 y la cantidad de líneas apartadas;
    - se avisa en la sala y se sigue desde la última entrada buena;
    - `exportar` copia lo apartado a `auditoria-apartada/`.

    Las decisiones que estaban en la parte apartada no van a verificar en la exportación, y está bien que así sea: queda a la vista.
26. **Comando `jueces --datos` (P2-e): no se hizo.** El README oficial dice que el partido final usa los mismos jueces y turnos.

---

## 17. Ronda 2b (motor)

Las vistas solo suman campos; el formato del sello, los mensajes de firma ya existentes y los tipos y campos de
auditoría anteriores no cambian.

### 17.1 Orden marco (OM)

- Al entrar de turno, el juez firma una vez la **orden marco**: el contenido sale de
  `marco.armar(partido, proveedores, {juez_id, nombre, juzgado_id, juzgado}, {desde_min, hasta_min}, seguimiento)`;
  `huella = marco.huella(contenido)` (sha256 del JSON canónico).
- Firma: HMAC con la clave del juez sobre `MARCO|<partido_id>|<huella>|<juez_id>|S1` (o `S0`). Una sola fuente:
  `sello.mensaje_marco` llama a `marco.mensaje_firma`.
- Mismas reglas de turno que una decisión. Con `--sin-dinamica` se firma igual, solo con `seguimiento: false`.
- **Vale la última suya.** Cada nueva cita en `reemplaza` la entrada anterior.
- Auditoría `orden_marco` (actor `juez:<id>`), datos `{id: "OM-NN", juez_id, juzgado_id, huella, seguimiento,
  contenido, firma, reemplaza}`.
- Toda `decision_juez` (aprobar, rechazar, levantar ubicación) y toda `ampliacion_dinamica` lleva
  `orden_marco: {entrada, huella}` de la OM vigente del juez (`null` si no tiene). `traspaso_ratificado` también.
- Aprobar con alcance `filtracion` exige una OM vigente con seguimiento: si no, `invalido` con «Para seguir a la
  filtración, firme antes la orden marco con el seguimiento autorizado.»
- Vistas:
  - `bandeja.marco = {firmada, propuesta: {lineas, condiciones_seguimiento, titulo_casilla}, puede_firmar,
    motivo_no, seguimiento_disponible}`;
  - `sala.marcos`, `sala.jueces[] = {juez_id, nombre, de_turno, activo, hace_s, marco}`;
  - `registro.marcos`.

### 17.2 Presencia

`usuarios.marcar_actividad(juez)` en cada pedido autenticado; `activo(juez, 90 s)`. Sin presencia no se amplía
(sección 5.4). Un juez de turno sin actividad con pedidos esperando genera una alerta a la sala, una sola vez por
turno.

### 17.3 Privacidad

La sesión de la marca identifica a un abonado. Lo público (orden pública y registro) muestra solo el prefijo
(`evidencia.marca`) y `filtracion: <expediente>`; la sala y el paquete conservan la marca entera.

### 17.4 Proveedor

- `vista_orden_publica`: el kit se arma con `vigente`, `hora_vence` (HH:MM) y `fecha_vence` (AAAA-MM-DD,
  inicio + `vence_min`). El texto llano depende del estado: una orden levantada o vencida dice «Esta orden ya no
  rige. … La levantó X en el minuto Y / Venció en el minuto Z. Si la aplicaste, quitala.». Por dominio no se dice
  que se quite solo.
- `vista_proveedor(pid)` (`/proveedor/<id>/…`): `{acelerar, v, proveedor, minuto, hora, generado_utc,
  partido: {nombre, fin_min, fin_hora}, vigentes[], retiradas[]}`. `vigentes` = recibidas o aplicadas, sin
  levantamiento en curso y antes de `vence_min`, con `firma: en_persona | ampliacion`. `retiradas` = levantadas o
  vencidas (las últimas 50). Las listas de `kit.lista_ips/lista_dominios/unbound_conf/zona_rpz` leen esta vista.
- `consulta_publica(dominio)`: `bloqueado` (orden por dominio que lo cubre), `comparte_servidor` (comparte la IP de
  una orden por IP vigente, según el DNS pasivo guardado), `no_alcanzado` o `invalido`. Sin red.

### 17.5 Traspaso y revocación

- `ratificar(juez, dinamicas=None) -> {ratificadas, sin_ratificar, aviso}`. Sin OM con seguimiento, el turno se
  recibe igual pero las dinámicas siguen esperando, con el aviso. `dinamicas` elige cuáles.
- `traspaso_ratificado` suma `dinamicas_sin_ratificar`. Se puede volver a llamar sin traspaso pendiente para
  ratificar las que quedaron.
- `revocar_dinamica(juez, exp, motivo, levantar=False)`: con `levantar`, levanta con la firma del juez las
  ubicaciones que se ampliaron solas (mismo camino que levantar ubicación). `dinamica_revocada` suma `levantar`.
- Cada dinámica de la bandeja suma `ampliaciones`: ubicaciones ampliadas solas todavía vigentes.

### 17.6 Textos

- Señal: «El detector informó la marca {prefijo} (sesión {s}). La plataforma comprobó que ese prefijo es de la señal
  oficial del partido y que no es de un licenciatario en su dominio.»
- Captura: «El hash prueba que la captura no cambió desde que llegó a la plataforma.»
- Apartarse: «El juez se apartó de la recomendación (dominio) y ordenó bloquear la IP {ip} hasta el minuto {m}.
  Riesgo informado: la IP aloja otros {n} sitios ({lista}). Fundamento del juez: «{texto}».»
- Reclamo sin fundamento escrito: «{sitio} resuelve a {ip}, bloqueada por la orden {id}; no es un sitio pirata».
- Rechazar exige un motivo de al menos 10 caracteres.

### 17.7 Ventana de cobertura (adenda 3, A)

`evidencia.ventana(ubicaciones, u, ahora, fin)` es el único lugar donde se calcula. Va desde la primera detección
de la ubicación hasta la primera detección de **otra** ubicación del expediente posterior a la última detección
propia; si no hay, hasta `min(ahora, fin)`. Así, dos servidores a la vez siguen vivos los dos y un pirata que vuelve
al servidor viejo lo mantiene vivo. Cada ubicación guarda `detecciones_min`. Una ventana de duración cero da
`sin_ventana: true` y `null` en los tres tiempos.

### 17.8 Validación de objetivos

`dominios.ip_valida`: el texto entero tiene que ser `[0-9A-Fa-f:.]+` (sin zona IPv6 `%…` ni saltos de línea) y la
dirección no puede ser de loopback, privada, CGNAT 100.64/10, link-local, multicast, broadcast, reservada, ULA ni
no especificada. Los rangos de documentación (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24, 2001:db8::/32) son
válidos: los usa el escenario oficial. Los nombres de host se validan con `fullmatch`. Una detección con objetivo
inválido no arma ninguna orden.

### 17.9 Juez automático (`herramientas/juez_automatico.py`)

Firma la OM antes de cualquier decisión (con seguimiento si el alcance es `filtracion` y la dinámica está
habilitada). Un 409 «ya fue decidida» (el sistema la amplió antes) se anota como «la amplió el sistema» con
`esperado: true` y no es un error.

### 17.10 Tipos y campos nuevos

- Tipos de auditoría: `orden_marco`, `ubicacion_sin_decidir`.
- Campos: `orden_marco` en `decision_juez`, `ampliacion_dinamica` y `traspaso_ratificado`;
  `dinamicas_sin_ratificar` en `traspaso_ratificado`; `levantar` en `dinamica_revocada`.
- Estado: `marcos`, `cortes_avisados`; por ubicación `detecciones_min`, `motivo_sin_decidir`, `sin_decidir_min`,
  `automatica.definitivo`, `decision.orden_marco`; `decision.bajo_orden_de.{otorgada_por, ratificada_por}`;
  `dinamica.orden_marco`; en el traspaso `dinamicas_ratificadas` y `dinamicas_sin_ratificar`.

### 17.11 Reloj monotónico: «nunca» no es 0

El origen de `time.monotonic()` no está definido: en la Python 3.9 del sistema (macOS) arranca cerca de 0 en
cada proceso. Un instante «anterior» que por defecto valía 0 hacía esperar de más recién arrancada la plataforma
(reintentos, consultas de una orden en duda, `/estado`, `/reclamos`, detección de perdidas). Regla: «nunca» es
`reloj.NUNCA = -inf` en memoria y `None` en lo persistido (`reloj.instante(None) == -inf`); al reanudar, los
instantes monotónicos guardados (`t_error`, `t_post`, `t_confirmada`) pasan a `None`, porque los de otro proceso
no se comparan. Sin el instante del pedido de la lista de un proveedor no se declara ninguna orden perdida.

### 17.12 Levantamiento confirmado por consulta

Al mandar un levantamiento firmado, la orden guarda `lev_enviado` (juez, firma, motivo, reclamo, entrada). Si el
proveedor la muestra levantada después (por consulta o en su lista), la entrada `orden_levantada` lleva
`confirmada_por_consulta`, `juez_id` y `firma` de ese POST, aunque el pedido ya se haya descartado. Solo una orden
que el proveedor levantó sin ningún pedido nuestro queda con `sin_pedido` y actor `proveedor:<id>`.

---

## 18. Ronda 3 (motor)

Arreglos después de la prueba en navegador contra el motor real (hallazgos N1–N20). Contratos C1–C13; pruebas en
`tests/test_contratos_ronda3.py` (cada una nombra su contrato). Las vistas solo **suman** campos.

### 18.1 Vocabulario (N16)

En todo texto que lee una persona: «seguimiento» (no «orden dinámica») y «frenar» (no «revocar»). Las claves,
los tipos de auditoría (`orden_dinamica_otorgada`, `dinamica_revocada`, `ampliacion_dinamica`…), los nombres de
funciones y las opciones (`--sin-dinamica`) no cambian. Una prueba recorre los textos visibles de las vistas.

### 18.2 Funciones compartidas (C7, C8)

- `canon.min_txt(minuto)`: el único redondeo de minutos para leer. Un decimal, coma, empates lejos del cero sobre
  el valor binario exacto (igual que `Number(x).toFixed(1)`); nunca «-0,0»; lo que no es un número finito sale «—».
  `marco._num` y `kit._num` pasan por ella y sacan el «,0» de los enteros.
- `marco.texto_ampliacion(om, otorgada, ratificada=None, hecha_min=None)`: la única leyenda de la ampliación
  automática. Cita la orden marco del juez **con cuya clave salió** la ampliación (no la de quien otorgó el
  seguimiento):
  - con traspaso: «Ampliación automática del sistema bajo la orden marco OM-03 de Dr. X (minuto 58,7), que en el
    minuto 60,2 ratificó el seguimiento otorgado por Dra. Y (minuto 39,8). No se firmó en persona.»
  - sin traspaso: «… bajo la orden marco OM-02 de Dra. Y (minuto 5,8) y el seguimiento que otorgó en el minuto
    39,8. No se firmó en persona.»
  - sin orden marco: «… bajo el seguimiento otorgado por X en el minuto O[, ratificado por Z en el minuto R].»
  `Motor.texto_ampliacion` delega en ella; `exportar.texto_ampliacion` (agente I) debe llamar a la misma.
- `Motor.texto_recibio_turno(minuto, ratificados, heredados)` (C8, N15): «Recibió el turno en el minuto X: ratificó
  N de M seguimientos heredados.» (y las variantes de ninguno / el único).

### 18.3 Campos nuevos

- **C1** `vista_registro().proveedores`: `[{id, nombre, capacidades}]`, también sin ningún bloqueo.
- **C2** cada orden marco de `vista_marco` suma `estado` ∈ `vigente` | `reemplazada` | `turno_terminado` |
  `partido_terminado` y `estado_min` (minuto en que dejó de valer; `None` si está vigente). Prioridad: reemplazada
  (el mismo juez firmó otra después) > turno_terminado (su turno termina antes del final y ya pasó) >
  partido_terminado > vigente.
- **C3** cada aviso suma `cierre`: `None` o `{min, texto}` (qué pasó). Los avisos de reclamo guardan `reclamos`
  (ids); la alerta de ausencia guarda `juez_ausente`.
- **C5** `vista_reloj` (y el reloj del registro) suma `hora_inicio` (hora del minuto 0) y `fin_hora` («HH:MM» del
  final, calculada con `hora_de_partido`, la misma que usa el motor en todos lados).
- **C12** `kpis.ubicaciones_levantadas`: ubicaciones con órdenes aplicadas cuyas órdenes quedaron todas levantadas.
- **C4** por ubicación: `levantada_por_freno` (`{min, juez_id, juez}`), `reabierta_en` (n de la ubicación que la
  continúa), `reabierta` (`{de_ubicacion, ampliada_min, levantada_min, juez_id, juez}`) y `nota_continuidad`.
  Auditoría: `ubicacion_armada.reabre` y `decision_juez.levanta_vetos`.
- **C13** orden: `no_antes_min` (solo desde el 7.º intento); auditoría: `orden_reintentada.no_antes_min`.

### 18.4 Avisos que se cierran solos (C3, N7)

Cuando se resuelve la causa, el aviso queda `atendido` con su `cierre`:
- reclamo: «Resuelto en el minuto X: Nombre levantó el bloqueo y lo reemplazó por dominio.» / «… levantó el
  bloqueo.» / «… desestimó el reclamo.» / «… quedó resuelto junto con el reclamo R-…»;
- ampliación automática: «Usted / Nombre frenó el seguimiento [y levantó la ampliación] en el minuto X.»;
- ausencia del juez: «Nombre volvió a tener la plataforma abierta en el minuto X.» o «Ya no hay pedidos esperando
  (minuto X).» (también si el juez quedó fuera de turno). Si después se vuelve a ausentar, sale una alerta nueva.
- traspaso: el texto pasa a ser el de `texto_recibio_turno`.
Singular y plural: «hay 1 pedido esperando», «hay 2 pedidos esperando».

### 18.5 Ampliación levantada: el servidor vuelve al juez (C4, N14)

«Frenar y levantar la ampliación» marca cada ubicación levantada con `levantada_por_freno` y veta sus objetivos.
La detección siguiente del **mismo servidor** (misma marca o mismo sitio) ya no se suma a esa ubicación: abre una
ubicación nueva **pendiente** (`reabierta`), con el mismo sello de evidencia encadenado y la nota «Mismo
servidor: la plataforma lo había bloqueado sola en el minuto X; usted levantó ese bloqueo en el minuto Y.». Nunca
se amplía sola (motivo: «este mismo servidor ya se había bloqueado solo y ese bloqueo se levantó: lo decide el
juez.»). Si el juez la firma en persona, los vetos de ese freno se quitan (`decision_juez.levanta_vetos`); si la
rechaza, siguen. Sobrevive a guardar y reanudar. Un levantamiento manual o por reclamo, o un freno sin levantar,
no reabre.

### 18.6 Otros textos y vistas

- **C6** «No se amplió solo: …» con motivos llanos, en este orden: definitivo, reabierta, seguimiento
  deshabilitado, partido terminado, primer servidor, servidor anterior «solo este servidor», seguimiento frenado,
  espera ratificación, otra marca de agua, marca no alcanzada, evidencia no limpia, orden marco sin seguimiento,
  juez sin la plataforma abierta.
- **C9** `consulta_publica` normaliza antes de validar: saca espacios de los bordes (no los de adentro: «con
  espacio.test» sigue inválido), esquema, ruta/consulta/fragmento, usuario, puerto y punto final; pasa a
  minúsculas. Devuelve el `dominio` normalizado.
- **C10** `/orden` de una ampliación (`amp-`): «… une esta orden con la evidencia exacta que evaluó la plataforma
  y con la autorización del juez (su orden marco y el seguimiento que otorgó) en el registro de auditoría.»
- **C11** renglón 2 de la orden marco: «Esta orden vale durante mi turno en este partido: desde antes del inicio
  / el minuto D hasta el minuto H / hasta el final del partido (minuto F). Todo bloqueo que se ordene bajo ella
  vence, como máximo, al final del partido (minuto F).»

### 18.7 Objetivos válidos (G)

`ip_valida` no acepta zona (`%…`), espacios ni saltos de línea, ni direcciones no ruteables (privadas, loopback,
link-local, CGNAT, multicast, reservadas); las de documentación sí. Un objetivo por dominio necesita al menos dos
etiquetas `[a-z0-9-]` (sin guion bajo, sin punto final), la última no numérica, y nunca es un sufijo de registro
pelado (`com`, `com.ar`, `gob.ar`, `test`, `example`, `localhost`…). Los hosts del escenario de práctica oficial
siguen valiendo (probado).

### 18.8 Reintentos sin tope (C13)

Antes: al 6.º intento fallido se dejaba de reintentar (`MAX_INTENTOS`) y el bloqueo quedaba sin efecto el resto
del partido (ensayo base ×20: Cumbre falló 6 veces x10.tribuna-pirata.test, cobertura 98,8 %, NO CUMPLE).
Ahora:
- mientras `ahora < fin_min − margen_envio()` y la orden no esté vetada ni en levantamiento, una falla del
  proveedor (o una orden perdida) siempre genera el intento siguiente: número consecutivo, mismo sello, mismo
  objetivo. No hay tope ni se eligen números;
- al 6.º intento fallido sale **una** alerta a la sala: «{Proveedor} falló 6 veces el bloqueo de {objetivo}. La
  plataforma sigue reintentando; conviene avisarle al proveedor.»;
- desde el 7.º intento, como máximo un envío por (proveedor, tipo, objetivo) cada 1 minuto de partido: la orden
  nueva lleva `no_antes_min = envío anterior + 1` y el despacho no la manda antes (se comprueba con el minuto
  fresco del simulador). Si ese minuto cae pasado el corte, el intento no se crea;
- el contador de `orden_id` pasa de 99 sin romper el formato (`-100-`).
Nada más cambia en el despacho.

## 19. Ronda 3b (motor)

Cada punto tiene su prueba en `tests/test_r3b_*.py` (nombre del archivo entre paréntesis).

### 19.1 Daño colateral: observado e inferido (C14, `test_r3b_colateral`)

Regla en §4.3. El reclamo corrige la inferencia (`_procesar_reclamo`), en este orden: licenciatario →
`licenciatario`; nombre **observado** (en `hosts_piratas()` o en `observados` de alguna ubicación) →
`operacion_pirata`, propuesta `desestimar` («Es el mismo nombre que la plataforma vio transmitiendo|publicando el
partido en el minuto X: el reclamo no es fundado.»); solo **inferido** → `legitimo` con `verificacion.inferido =
true` y `registrable` («La plataforma lo había tomado como parte del sitio pirata porque comparte el servidor y el
dominio R, pero nunca lo vio transmitir ni publicar el partido. El reclamo corrige esa inferencia.»), propuesta
`levantar_y_reemplazar`; cualquier otro → `legitimo`.
Resolver a favor un reclamo de un inferido refuta el registrable: entra en `e["inferencias_refutadas"]` (auditado
`inferencia_refutada {registrable, reclamo, ubicaciones}`), la propuesta levanta también las órdenes por nombre
sobre los otros inferidos de esas ubicaciones (quedan vetados) y los análisis siguientes ya no infieren en ese
registrable. Si la plataforma después **ve** el partido saliendo de un nombre vetado, el pedido va al juez («{host}
se había levantado por el reclamo R en el minuto X, y ahora la plataforma lo vio transmitiendo el partido: lo decide
el juez.»); nunca se amplía solo, y firmarlo en persona quita ese veto. `ordenes_con_colateral` cuenta como pirata
observados + inferidos no refutados, menos los reclamantes que salieron `legitimo`.

### 19.2 Orden marco (C15, `test_marco`)

Renglón 3: «Solo se protege la señal del partido: la oficial (…) y la de cada licenciatario cuando se transmite
fuera de sus dominios (…). Nunca se bloquea a un licenciatario en sus dominios: …» (sin licenciatarios: «Solo se
protege la señal oficial del partido (…).»). Renglón 4 termina «…, salvo que en esta orden autorice el seguimiento
de la misma filtración.». `CONDICIONES_SEGUIMIENTO[0]` y `[1]` con el texto del contrato. Cambia la huella de las
órdenes marco nuevas; las claves y el mensaje de firma no. El motivo «no limpia» por recomendación `ninguna` dice
«el stream sale directo de una IP, sin nombre, y no se puede asegurar que esa IP sea solo del pirata: la decide el
juez.»

### 19.3 Órdenes inciertas (C19, `test_r3b_inciertas`)

Un POST sin respuesta no se reenvía con el mismo `orden_id` antes de `ESPERA_REENVIO_S = 12` s reales desde que
salió (o del `post_timeout`, el mayor), además de la regla de los dos 404. Levantar una orden incierta no la anula
a ciegas: queda con el levantamiento pendiente; si aparece en el proveedor se le manda, y recién si se confirma
que nunca llegó se anula.

### 19.4 Paquete repetible (C20, `test_r3b_reexporta_testigos`)

Con `hitos.exportado` marcado, un pedido de testigos (`_paso_pedido_testigos`) de la plataforma viva rearma el paquete
(`exportar_entrega()`): `entrega/` y `hitos.paquete.huella` quedan con los testigos nuevos. El comando `exportar` con
el partido cerrado no lo pide: copia el paquete del cierre tal cual (§13). Antes del cierre no
exporta. Si la foto de testigos falla por red, no exporta.

### 19.5 Turnos

- **turnos-1** (`test_r3b_latencia_post_turno`): el margen de envío y `puede_firmar_con` usan
  `latencia_para()` = máx(duración estimada, duración reciente, latencia de POST). El cliente del simulador
  anota la latencia de los POST (`latencia_post()`: la mayor de los últimos 120 s, con techo de 5 s).
- **turnos-2** (`test_r3b_turnos2`): levantar una ubicación (o frenar y levantar el seguimiento) no levanta una
  orden de la que depende otra ubicación firmada (la que la tiene en `ya_cubiertos`): se mantiene y no se veta.
  `levantar_ubicacion` y `revocar_dinamica` devuelven `{"aviso": "Se mantiene el bloqueo de {objetivo} en
  {Proveedor} porque también cubre la ubicación {n} de {EXP}, firmada por {juez}."}` o `{}`
  (`revocar_dinamica` además `levantadas`). Si no se pudo levantar nada, `levantar_ubicacion` da conflicto con
  ese texto.
- **turnos-3** (`test_r3b_turnos3`): después de un freno sin levantar, se puede volver a frenar con levantar
  mientras queden ampliadas (sin repetir `dinamica_revocada`); el historial de la bandeja incluye las ampliadas
  vigentes de otros jueces.

### 19.6 Textos y datos

- **textos-3** (`test_r3b_seguir_sin_ratificar`): «Firmar y seguir» sobre un seguimiento que espera ratificación
  lo ratifica (`ratificaciones[].por = "firma_y_seguir"`, el último traspaso lo anota en
  `dinamicas_ratificadas`); `ratificar` suma a lo ya ratificado, no lo pisa.
- **datos-raros** (`test_r3b_datos_raros`): cada detección pasa por `evidencia.normalizar_deteccion` antes de
  validarse: `id` entero → texto; `host_stream` vacío o ausente → el host de `stream_url`. Queda anotado en
  `normalizada: [campos]`.

### 19.7 Pedidos de las pantallas (C21, `test_r3b_pedidos_w`)

- La ubicación reabierta (§18.5) lleva `continuidad.criterio = "mismo_servidor"` (antes `misma_marca` o
  `mismo_sitio`: es el mismo host e IP, no una mudanza) y, en las vistas, `continuidad.nota` (= `nota_continuidad`,
  en «usted» para el juez que levantó) y `reabierta`.
- `vista_sala().jueces[].turno = {desde_min, hasta_min}`: el turno en curso o el próximo; `None` si no le queda.
- El cierre de una alerta de juez ausente lleva `cierre.juez_ausente` (además de `juez_ausente` en el aviso).

### 19.8 Un rechazo no absorbe en silencio (C22, `test_r3b_rechazo_vuelve`)

Una detección del mismo (host, IP) de una ubicación **rechazada** cuyo minuto es posterior al minuto del rechazo arma
una ubicación nueva del mismo expediente (evidencia nueva sellada, pendiente, del juez de turno) con
`rechazo_previo = {ref, min, juez_id, juez, motivo}` y `continuidad = {de_ubicacion, criterio: "mismo_servidor"}`.
Las de minuto anterior o igual se siguen sumando a la rechazada; después del final del partido no se arma nada.
Nunca se amplía sola, aunque la filtración tenga seguimiento: «No se amplió solo: este servidor ya fue rechazado en
el minuto X; queda para decidir en persona.». Tampoco se amplía sola una ubicación de **otro** servidor que comparte
la IP o el nombre normalizado del stream con una ubicación rechazada del mismo expediente, salvo que ese servidor
rechazado se haya firmado después (el rechazo quedó atrás) (f-turnos-1, `test_r4_motor_rechazo_cruza_ip`): «No se
amplió solo: un servidor con esta misma IP o este mismo nombre ya fue rechazado en el minuto X; queda para decidir en
persona.». La nota de continuidad (`continuidad.nota` / `nota_continuidad`): «Mismo
servidor: usted|{nombre} rechazó este pedido en el minuto X; la plataforma lo volvió a ver transmitiendo en el minuto
Y.». Mientras esté pendiente, las detecciones siguientes se suman a ella; si se la vuelve a rechazar, vale la misma
regla. La ubicación más nueva de ese servidor es la del índice, también al reanudar. `ubicacion_armada` lleva
`reabre` y `rechazo_previo`.

### 19.9 Aviso de juez ausente por episodio (C23, `test_r3b_ausencia`)

Cada ausencia nueva del juez de turno con pedidos esperando da un aviso nuevo (arriba en la sala); durante la misma
ausencia no se repite la alerta, pero el texto del aviso abierto lleva el número al día («hay 1 pedido esperando» /
«hay N pedidos esperando»). Cuando vuelve, el aviso de ese episodio queda atendido (C3).

### 19.10 Pedido superado por la mudanza (C24, `test_r3b_bandeja_superada`)

En `vista_bandeja`, cada pendiente lleva `superada_por`: el número de la ubicación más nueva del mismo expediente
cuya primera detección es posterior a la última detección de esta (o `null`). Orden estable: primero los no
superados. Dos servidores que se ven a la vez no se marcan; si el viejo vuelve a verse, la marca se va.

### 19.11 Hora de vencimiento en la vista (C26, `test_r3b_vence_hora`)

`vista_ubicacion().propuesta.vence_hora = hora_de_partido(inicio_iso, propuesta.vence_min)` (HH:MM:SS, la misma que
dice la orden pública). Solo en la vista: la propuesta guardada y sellada no cambia.

### 19.12 Prioridad B del motor

- **kit-1** (`test_r3b_kit_motor`): con el partido acelerado, `_kit_orden` pasa `acelerar` y la hora y fecha
  **reales** del vencimiento (reloj de esta máquina + lo que falta de partido / acelerar); a x1, la del partido.
- **kit-2**: cada vigente por dominio de `vista_proveedor` lleva `no_cortar` (opcional) con los `ajenos` de su
  ubicación que cuelgan de ese dominio.
- **kit-4**: `guardar()` anota `e["v"]`; al reanudar, `v` sigue desde ahí (el serial de rpz.zone no retrocede).
- **robustez-3**: `guardar()` anota `e["aud_n"]` (última entrada de auditoría que refleja el estado) y la entrada
  `reanudacion` lleva `estado_hasta_entrada`.
- **c1-pruebas-y-operacion-7** (`test_r3b_guardias_p0`): guardias para los mutantes M1e, M4, M9 y M11.

## 20. Ola C del motor (12-nov, antes del congelamiento)

Cada punto tiene su prueba de contrato (`tests/test_r4_motor*.py`), roja antes del arreglo y verde después.

- **f-colateral-1** (`test_r4_motor_colateral1`): el reclamo fundado de un inquilino inferido refuta la inferencia,
  pero lo que la plataforma **vio** transmitir no se levanta ni se veta: `_otros_inferidos` salta lo que reconoce
  `_donde_se_vio`, y `resolver_reclamo` saca de la lista a levantar las órdenes por nombre cuyo objetivo se vio entre
  la propuesta y la firma. `_reemplazos` arma el reemplazo por nombre para el host de **cada** ubicación aprobada en
  esa IP (no solo la dueña de la orden).
- **f-colateral-2** (`test_r4_motor_colateral2`): al refutar un registrable, `_recalcular_pendientes` rehace el
  análisis y la propuesta de las ubicaciones **pendientes** que tenían inferidos de ese registrable, con la misma
  evidencia sellada (el bloque `sellado` y la huella no cambian). La ubicación lleva
  `recalculada = {reclamo, registrable, min, tipo_antes, tipo}`, que `vista_ubicacion` expone.
- **f-colateral-3** (`test_r4_motor_colateral3`): la refutación alcanza a **todos** los servidores del pirata: se
  levantan también las órdenes por nombre sobre los demás inferidos de ese registrable y las órdenes por IP de las
  ubicaciones que los tenían, con sus reemplazos por nombre del stream. Convive con f-colateral-1.
- **f-turnos-1**: ver §19.8.
- **f-turnos-2**: `continuidad.de_ubicacion` apunta a la ubicación que se reabre (C22 rechazada o C4 levantada), no a
  la última del expediente.
- **f-despacho-1** (`test_r4_motor_reinicio_incierta`): al reanudar, una orden que quedó en vuelo se marca incierta
  con `t_post` = ahora, así la espera de la consulta corre desde el reinicio.
- **robustez-2** (`test_r4_motor_reanudar_presencia`): durante `PRESENCIA_S` desde el arranque, un juez sin
  presencia registrada no cuenta como ausente: «la plataforma acaba de arrancar: se espera hasta 90 s a que {nombre}
  vuelva a entrar.».
- **Bloqueo trabado tras «Frenar y levantar»** (`test_r4_motor_levantar_trabado`): una orden que el juez quiso
  levantar pero se mantuvo porque cubría otra ubicación queda con `levantar_al_liberar`; al levantar esa otra
  ubicación, se levanta también si nadie más la necesita.
- **NV1** (`test_r4_motor_decision_y_traspaso`): la orden pública y el registro dicen qué decisión la ordenó:
  `decision_origen` (`"reclamo"` o `"ubicacion"`) y `reclamo`; para un `reemplazo_reclamo`, `decision_min`,
  `decision_hora`, `decision.tipo = "resolucion_reclamo"`, `decision.texto` y `decision.entrada` son los de la
  resolución del reclamo.
- **NV4**: `ratificar()` ignora en silencio los ids que ya están en `dinamicas_ratificadas`; «Firmar y seguir» sobre
  un seguimiento heredado anota `ratificadas_al_firmar = [{id, min, juez_id, nombre}]` en el traspaso, que
  `vista_traspaso` expone. El traspaso no se cierra solo.
- **Guarda de vetados en aprobar** (`test_r4_motor`, mutante M9c).
- **NV2/NV3** (`test_r4_motor_textos_plural`): singular y plural de verdad; la propuesta de un reclamo dice cuántos
  bloqueos son por IP y cuántos por nombre («Levantar 2 bloqueos por IP y 1 bloqueo por nombre que alcanzan a …»).
- **f-kit-1** (`test_r3b_kit_motor`, `test_vfkit1_hora_real` del verificador): con el partido acelerado, la hora real
  de vencimiento del kit va en HH:MM:SS redondeada hacia arriba al segundo (nunca borra antes del vencimiento real);
  a x1 sigue la hora del partido en HH:MM.
- **f-kit-2** (`test_r4_motor_consulta_guion`): la consulta pública acepta nombres con «_» (válidos por C16).
- **f-desconocido-1** (`test_r4_motor_fuera_de_plazo`): si el minuto fresco de la firma (el de `puede_firmar`) es
  `>= fin_min − margen_envio(acelerar, latencia)` (el margen no cambia), `aprobar()` suma al aviso
  `TEXTO_FIRMA_TARDE`: «Faltan segundos para el final del partido: la firma queda registrada, pero la orden ya no
  llega a los proveedores y no bloquea.». `vista_orden` trae `no_enviada` (con su `motivo`).
- **P3 de a-kit**: `_no_cortar` mira los ajenos de todas las ubicaciones (`test_r4_motor_no_cortar_cruzado`); un id de
  detección float entero (101.0) pasa a texto «101» (`test_r4_motor_ids_raros`; un 1.5, un bool o un NaN se siguen
  descartando). Límite conocido: con un SIGKILL entre un cambio servido y el guardado, el serial de la zona puede
  repetirse (al reanudar se suma +1).

## 21. Ola D (12-nov)

Del motor (cada uno con su prueba, roja antes del arreglo):

- **g-seguimiento-1** (`test_r5_motor_rechazo_otro_expediente`): `_rechazada_que_cruza` busca la ubicación rechazada
  en **todos** los expedientes; la excepción «se firmó después» compara la entrada de auditoría de la decisión
  (global), no el número de ubicación.
- **g-colateral-2** (`test_r5_motor_freno_y_reclamo`): `_reemplazos` no vuelve a bloquear por nombre el stream de una
  ubicación que el juez frenó y levantó (su orden seguía viva solo porque otra la sostenía: `levantar_al_liberar`).
- **g-colateral-1** (`test_r5_motor_fundamento_reclamo`): el fundamento por defecto de `resolver_reclamo` nombra solo
  las órdenes que alcanzaban al reclamante; si se levantan más por refutar el dominio, agrega «; además se levantan N
  bloqueos sobre lo que la plataforma había inferido del mismo dominio X y nunca vio transmitir» (N cuenta solo los
  bloqueos por nombre). Los bloqueos por IP de otros servidores del pirata van aparte (h-motor-1,
  `test_r6_motor_fundamento_no_vio`): «; también se levanta el bloqueo por IP de <ips>, que alojaba nombres de ese
  dominio» y, si la acción reemplaza, «; lo que la plataforma vio transmitir ahí queda bloqueado por nombre».
- **g-despacho-2** (`test_r5_motor_reintento_de_reemplazo`): el reintento C13 de un reemplazo por reclamo (conserva
  `reclamo` y `entrada_sello`) publica la decisión del reclamo y su texto llano dice que reemplaza un bloqueo por IP.
- **NV7** (`test_r5_motor_traspaso_solo_heredados`): mientras el traspaso no está ratificado, `vista_traspaso` deja en
  `resumen.dinamicas` solo lo heredado (lo que espera ratificación y lo ya ratificado en ese traspaso); un seguimiento
  que el entrante firmó él mismo no se ofrece para ratificar. Lo guardado en el traspaso y la auditoría no cambian.
- **g-pruebas-1**: `test_r4_pruebas_reemplazo_cada_proveedor` (sin cambio de código).

De verificar, exportar y las pantallas (I y W):

- `verificar` rehace el colateral de un pedido recalculado (`recalculada`) a partir de la evidencia sellada y de las
  entradas `inferencia_refutada` (g-paquete-1). Como el motor, toma como hosts del pirata los de **todos** los
  expedientes (h-paquete-1), y si la ubicación ya estaba decidida antes de esa refutación exige el colateral sellado,
  diga lo que diga `recalculada` (h-paquete-2): el motor solo rehace pedidos que esperaban firma
  (`test_r5_paquete_colateral_lavado`).
- El acta separa las causas de una orden que no salió: el partido terminaba, el juez entrante no recibió el turno, o
  se envió y al cierre el proveedor no la tenía.
- `--simulador` exige `http://` o `https://`.
