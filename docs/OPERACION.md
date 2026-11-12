# Operación — Marca Personal

Python 3.9 o más nuevo, sin dependencias. Todo se corre **desde la carpeta del proyecto**.
Las contraseñas de los usuarios y las claves de firma de demostración están solo en `config/jueces_demo.json`, que va al repo público. Para el partido final se usan contraseñas propias, fuera del repo: ver «Contraseñas del partido final».

## 1. Antes del partido

```sh
python3 -m marca chequear --simulador http://HOST:PUERTO --host 0.0.0.0 --config config/jueces_final.json [--salida salida]
```

Apenas la organización dé la dirección del simulador, correr `python3 -m marca chequear --simulador <dirección> --host 0.0.0.0 --config config/jueces_final.json`.

La dirección se escribe entera, con `http://` o `https://` adelante (por ejemplo `http://192.168.0.10:8791`). Sin eso, `chequear` y `servir` frenan al toque, sin tocar la carpeta ni el puerto: «--simulador 192.168.0.10:8791: la dirección tiene que empezar con http:// o https:// (por ejemplo http://192.168.0.10:8791)».

No manda órdenes. Revisa la conexión y la latencia, el reloj, el partido (marcas válidas y licenciatarios), los proveedores y sus capacidades, que cada juez de turno tenga usuario y clave de firma, que haya un usuario de fiscalía, que la carpeta de salida se pueda escribir y que estén las pantallas de `marca/web/`. Con `--host` (el mismo que se va a usar en `servir`) avisa con ✗ si la plataforma quedaría abierta a la red con contraseñas publicadas en el repo. Si algo sale con ✗, devuelve 1.

Si la dirección es https y este Python no reconoce su certificado, el ✗ de conexión viene con una línea más: «Este Python no confía en el certificado de esa dirección. Probá con /usr/bin/python3 (usa los certificados del sistema) o pedile a la organización una dirección http.» No hay ninguna opción para saltear la verificación del certificado. Lo mismo avisa `servir` al arrancar.

### Contraseñas del partido final

`config/jueces_demo.json` está en el repo público: quien lo leyó podría entrar como el juez y firmar en su nombre. Antes del partido final:

```sh
python3 -m marca claves --salida config/jueces_final.json
```

- Arma el archivo con los mismos usuarios, roles, jueces y claves de firma (tienen que ser las del simulador) y **contraseñas de ingreso nuevas, al azar**.
- Lo deja con permisos 600 y está en `.gitignore`: no va al repo.
- Imprime la ruta y los usuarios, **nunca las contraseñas**: se leen abriendo el archivo en esa computadora y se le dan a cada juez en persona.
- No pisa un archivo que ya existe; con `--reemplazar` genera contraseñas nuevas (las anteriores dejan de valer).
- `servir` con un `--host` que no sea de esta máquina (`0.0.0.0`, la IP de la red, un nombre) y un archivo de usuarios con alguna contraseña publicada en `config/jueces_demo.json` (también una copia en otra ruta) **no arranca**: sale con 6 y no toca nada. En `127.0.0.1` / `localhost` (ensayos) sigue andando con el de demostración.
- Cinco intentos fallidos traban ese usuario 30 s **desde esa máquina**, no desde las demás: alguien que prueba contraseñas no deja afuera al juez. Los ingresos fallidos van a la auditoría de a **una entrada por máquina cada 30 s**, con `intentos_sin_anotar` (los que no se anotaron desde la anterior): no inundan el panel de la sala.

## 2. Durante el partido

Comando del partido final (la primera vez):

```sh
python3 -m marca servir --simulador http://HOST:PUERTO --host 0.0.0.0 --puerto 8792 --salida salida --config config/jueces_final.json --nueva
```

Con `--host 0.0.0.0` el celular del juez entra por la red local: la plataforma imprime la dirección. Usar una red propia (hotspot con clave) si se puede: la galleta de sesión viaja por HTTP. Si se entra por un túnel, **siempre** con `--config config/jueces_final.json`: el túnel publica la plataforma aunque escuche en `127.0.0.1`, y con el archivo de demostración las contraseñas son públicas (`chequear` lo avisa). Para que una sola máquina de la red no deje sin servicio a las demás: cada IP de afuera puede tener a lo sumo 24 conexiones abiertas a la vez (un celular usa unas pocas) y cada pedido tiene 20 s para llegar entero desde su primer byte; lo que se pasa recibe «503 Plataforma ocupada: reintentar» o se corta. Las pantallas abiertas en esta misma computadora (la sala, el ensayo, un túnel) no tienen el tope por IP, solo el general de 128. Si la plataforma ya arrancó una vez en este partido, el comando es el mismo **sin `--nueva`** (y con la misma `--salida`).

| Opción | Qué hace |
|---|---|
| `--simulador` | URL del simulador (obligatoria), con `http://` o `https://` adelante: `http://192.168.0.10:8791`. |
| `--puerto` / `--host` | Dónde escucha la plataforma (por defecto `127.0.0.1:8700`). Con `--host 0.0.0.0` queda abierta a la red local e imprime la dirección para el celular del juez. |
| `--salida` | Carpeta de estado: `estado.json`, `auditoria.jsonl`, `capturas/`, `testigos/`, `plataforma.json`. |
| `--nueva` | Empieza de cero. **Nunca borra:** aparta **toda** la carpeta de `--salida` a `<salida>.anterior-<fecha>` (no guardar ahí el registro del simulador ni nada propio: queda en la apartada, no en la nueva). Si el simulador ya tiene órdenes, se niega (ver abajo). **Sin `--nueva` reanuda** lo que haya en `--salida`. |
| `--descartar-anteriores` | Solo junto con `--nueva`: empieza de cero aunque el simulador ya tenga órdenes. Esas órdenes no van a figurar en la auditoría nueva. Casi nunca es lo correcto. |
| `--config` | Usuarios y claves (por defecto `config/jueces_demo.json`). Abierta a la red, tiene que ser uno con contraseñas propias (`claves`); si no, sale con 6. |
| `--sin-dinamica` | Deshabilita el seguimiento (ampliaciones automáticas): cada servidor nuevo espera la firma del juez. |
| `--tick` | Cada cuánto lee detecciones, en segundos (0,25). |

Pantallas: `/` (inicio), `/juez`, `/sala`, `/transparencia`, `/orden/<orden_id>`.

Al llegar a `fin_min + 5` la plataforma verifica los vencimientos, guarda los testigos de los proveedores y exporta sola a `<salida>/entrega/`. Se para con Ctrl-C (o `SIGTERM`).

### La orden marco de cada turno

- En `/juez` el juez entrante ve primero los pedidos; la **orden marco** está más abajo y la firma en su turno. Es un texto corto con los límites del partido. Queda en la auditoría con su huella y su firma.
- La casilla «Autorizo el seguimiento de la misma filtración» viene **destildada**. Sin ella, cada servidor espera su firma.
- Se puede volver a firmar en el turno (por ejemplo, para prender o apagar el seguimiento). Vale la última.
- Con `--sin-dinamica` la orden marco se firma igual, pero sin la casilla.
- Al entrar de turno, si hay un pedido esperando, fírmelo primero («Firmar solo este servidor» no necesita la orden marco). Después firme su orden marco y ratifique lo heredado; mientras no lo haga, las órdenes que dejó el saliente siguen en espera y las mudanzas le llegan como pedidos. Para eso:
  - **Sin seguimientos heredados:** «Recibir el turno» (lo que estaba en espera sale a los proveedores) y después la orden marco.
  - **Con seguimientos heredados:** la orden marco **con la casilla tildada** y después la ratificación de lo heredado.
- Alrededor del cambio de turno hay un margen en el que nadie firma (`marca/turnos.py`). Es a propósito: evita una firma fuera de turno.
  - **Antes del fin del turno** (y del final del partido y del vencimiento de una orden): 2 s reales + 1,5 × la demora de la consulta a `/estado`, y nunca menos de 0,05 min de partido.
  - **Después del inicio del turno:** 0,5 s reales + la demora de esa consulta, y nunca menos de 0,02 min.
  - En minutos de partido, con la red local (demora ≈ 0): a **x6**, 0,2 min antes y 0,05 min después (0,25 min en total); a **x20**, 0,67 min antes y 0,17 min después (0,83 min en total). Con 0,5 s de demora: x6, 0,28 + 0,1; x20, 0,92 + 0,33. En el partido real (x1), 3 s antes y 1,2 s después.

### La pantalla del juez, prendida

- «Presente» = **la bandeja del juez (`/juez`) abierta**. La plataforma lo cuenta presente si la bandeja habló con ella en los últimos **90 segundos**: cualquier pedido a `/api/juez/…` o la espera de cambios que la bandeja hace sola. Las páginas públicas (`/transparencia`, `/orden/…`, la portada) no cuentan aunque estén abiertas con la sesión del juez.
- «Salir» (cerrar sesión) lo deja ausente en el acto, salvo que tenga otra sesión abierta.
- Después de un reinicio de la plataforma las sesiones se pierden: **cada juez vuelve a entrar**. Durante los primeros 90 segundos después de volver, una mudanza que el seguimiento podría ampliar espera a que el juez vuelva a entrar; si entra en ese lapso, se amplía sola; si no, queda como pedido para firmar en persona.
- Si el juez no está presente, no hay ampliación automática: la mudanza queda como pedido para firmar en persona, aunque el juez vuelva después.
- Si el juez de turno lleva más de 90 s sin actividad y hay pedidos esperando, la sala recibe un aviso. Se repite en cada ausencia nueva del turno (no una sola vez por turno), con la cantidad de pedidos al día; cuando el juez vuelve, queda atendido.
- Dejar `/juez` abierta y con la pantalla encendida: la pantalla lo pide con un cartel fijo.

### Cómo se ve el día

**Sin seguimiento** (orden marco sin la casilla, o `--sin-dinamica`): cada servidor nuevo es un pedido. El juez firma uno por uno («Firmar solo este servidor»). Todas las órdenes empiezan con `ord-`.

**Con seguimiento** (orden marco con la casilla): el juez firma la primera ubicación con «Firmar y seguir a esta filtración». Si la misma marca de agua aparece en otro servidor y el juez está de turno y presente, la plataforma amplía sola cuando se cumple esta condición: «La evidencia nueva está completa y sellada, y el bloqueo nuevo no alcanza a sitios ajenos: si el servidor nuevo comparte la IP con sitios ajenos, se bloquea solo el nombre del stream.» Esas órdenes empiezan con `amp-`, se avisan al juez en el momento y se pueden frenar («Frenar las próximas mudanzas») o frenar y levantar («Frenar y levantar las N ampliaciones»). Fuera de esas condiciones, el pedido vuelve al juez.

### Lista de cada proveedor

El equipo de cada proveedor puede leer solo lo que tiene que bloquear, sin entrar a la plataforma:

| Ruta | Qué tiene |
|---|---|
| `/proveedor/<id>/vigentes.json` | Órdenes vigentes y retiradas, con número, objetivo, vencimiento y si se firmó en persona o es ampliación. Arriba, `acelerar`: minutos de partido por minuto real (1 en el partido de verdad). |
| `/proveedor/<id>/dominios.txt` | Un nombre por línea. |
| `/proveedor/<id>/ips.txt` | Una IP por línea. |
| `/proveedor/<id>/unbound.conf` | Líneas `local-zone` para incluir dentro de `server:`. |
| `/proveedor/<id>/rpz.zone` | Zona RPZ para BIND. |

- Son públicas, de solo lectura y sin caché.
- `dominios.txt` e `ips.txt` empiezan con líneas de comentario (`#`): dos o tres, según el caso (la tercera avisa cuántos objetivos se descartaron por formato inválido). Un script que las lea tiene que saltear todas las líneas que empiezan con `#` (`grep -v '^#'`), no un número fijo. En `rpz.zone` los comentarios empiezan con `;`.
- Son datos, no comandos: el equipo del proveedor decide cómo aplicarlos.
- Cliente de referencia, para dejar corriendo en el proveedor:

```sh
python3 herramientas/cliente_proveedor.py --plataforma http://HOST:8792 --proveedor <id> --cada 5 --salida-unbound /etc/unbound/bloqueo.conf
```

Notas de uso del cliente (`python3 herramientas/cliente_proveedor.py --help` las resume):

- `--estado`: por defecto `.<nombre>.estado.json` al lado de la primera salida (`--salida-unbound` si está, si no `--salida-ips`). Un estado de otro proveedor no se usa ni se toca; uno ilegible o de otra versión se mueve a `<estado>.danado` y se avisa.
- `--al-cambiar` corre al arrancar, cada vez que cambia algún archivo y, si falla, en cada vuelta hasta que ande, también con la plataforma caída. Corre sin shell, con tope de 60 s y stdin cerrado. Si el programa no existe, solo avisa (y lo reintenta en cada vuelta; con `--una-vez` sale con 4).
- Códigos de salida con `--una-vez`: 0 quedó todo aplicado; 1 no hubo lista válida; 2 argumentos inválidos; 3 no se pudo escribir algún archivo; 4 falló la recarga (`--al-cambiar`) o su programa no existe.
- Ningún bloqueo dura más de 6 horas desde la última lista buena. Una lista con el minuto más bajo que el máximo recibido (con 0,5 de tolerancia) solo quita. Una orden levantada nunca vuelve. Un cuerpo idéntico durante más de 60 s no cuenta como lista nueva.
- Al arrancar, las líneas de los archivos que el estado no justifica se quitan, salvo que la plataforma las confirme. La cabecera de Unbound suma «# Cada línea corta el nombre y sus subdominios.» Las listas empiezan con renglones de comentario `#`.
- `unbound.conf` puede traer, además de las líneas que bloquean, líneas `local-zone: "<nombre>." transparent`: son excepciones para sitios ajenos que cuelgan de un nombre bloqueado (llegan por `vigentes[].no_cortar` cuando el motor lo informa) y se incluyen tal cual. El cliente y el kit aceptan nombres con «_».
- Límite conocido: el cliente es más estricto que la plataforma con algunas direcciones IPv6 de transición (6to4, Teredo, NAT64 y reservadas): no las bloquea y lo informa. En el simulador no aparecen.
- Un 3xx no se sigue; la plataforma solo puede ser http o https. Respuestas: tope total de 9 s y de 2 MiB. Los objetivos por IP no aceptan zona `%` ni direcciones privadas, CGNAT, loopback, link-local, multicast, reservadas, ULA ni IPv4 dentro de IPv6; las de documentación sí (las usa el simulador).

- Consulta pública «¿Tu sitio quedó bloqueado?»: formulario en `/transparencia` (`GET /api/publico/consulta?dominio=…`).

### Una sola plataforma por carpeta

`servir` toma un candado del sistema operativo en `<salida>.candado` (al lado de la carpeta, no adentro). Lo hace **antes** de leer o tocar nada. Si el proceso muere, el sistema suelta el candado solo. Funciona igual en macOS, Linux y Windows.

| Código | Qué pasó | Qué se tocó |
|---|---|---|
| 3 | Ya hay una plataforma sobre esa `--salida` (candado tomado, o `plataforma.json` con una plataforma que responde en `/api/salud`). | Nada. |
| 4 | El puerto está ocupado. | Nada. Probar otro `--puerto`. |
| 5 | `--nueva` se negó: el simulador ya tiene órdenes, o no se pudo consultar. También sin `--nueva` sobre una `--salida` sin `estado.json` si el simulador ya tiene órdenes: es una `--salida` equivocada, no el arranque del partido. | Nada. |
| 6 | Abierta a la red (`--host` que no es de esta máquina) con contraseñas publicadas en el repo. Ver «Contraseñas del partido final». | Nada (ni la carpeta ni el puerto). |

### `--nueva` y `--descartar-anteriores`

- `--nueva` primero le pregunta al simulador si los proveedores ya tienen órdenes.
- Si tienen, **se niega** y sale con 5. El mensaje dice que lo normal es reanudar: el mismo comando **sin `--nueva`**.
- Si no se puede consultar al simulador, también se niega. No adivina.
- Si no hay órdenes, mueve la carpeta vieja a `<salida>.anterior-<fecha>` y empieza de cero.
- `--nueva --descartar-anteriores` empieza de cero igual. Usar solo si las órdenes del simulador son de un ensayo y no importan.

### Si la plataforma se cae

Volver a correr el mismo comando **sin `--nueva`**, con la **misma `--salida`** (la que tiene `estado.json`). Si la carpeta no tiene estado y el simulador ya tiene órdenes, no arranca de cero: sale con 5 y explica. Después del reinicio cada juez vuelve a entrar. Al reanudar:

- descarta una última línea de auditoría a medio escribir (queda anotada en la entrada `reanudacion`) y verifica la cadena;
- si la cadena no verifica, aparta la cola dañada sin borrarla a `auditoria.danada-<fecha>.jsonl`, deja la entrada `auditoria_reparada` con su sha256, avisa en la sala y sigue;
- toda orden que pudo haber salido queda «incierta»: primero hace `GET` y solo la reenvía si el proveedor responde 404;
- concilia con las listas de los proveedores.

Si el segundo intento dice «Ya hay una plataforma corriendo», la anterior sigue viva (quizás en otra terminal). Buscarla y usarla, o pararla con Ctrl-C. No borrar el candado a mano.

### Si la organización reinicia el simulador

- La plataforma lo nota cuando el minuto retrocede dos lecturas seguidas. Avisa en la sala y **no firma nada** hasta que el reloj vuelva a ser coherente.
- Si es el mismo partido: pedir a la organización que lo vuelva al minuto en que estaba (`--inicio-min`). La plataforma sigue sola.
- Si la plataforma estaba parada y el simulador quedó en un minuto anterior, no reanuda: dice «parece reiniciado».
- Si de verdad es un partido nuevo: parar la plataforma y arrancar con `--nueva`. La carpeta vieja queda apartada, no se pierde.

## 3. Después del partido

**El partido final se deja correr hasta el minuto 110 o más antes de cortar y exportar** (simulador y plataforma prendidos). El verificador oficial evalúa «bloqueos activos después del partido (minuto 110)» solo si el registro del simulador llega a ese minuto (el simulador anota `ventana_cerrada` al pasar por `fin_min + 5`); si se corta antes, ese punto sale «No evaluable». La plataforma exporta sola a `<salida>/entrega/` al llegar a `fin_min + 5`. `herramientas/ensayo.py` ya lo hace así: no corta el simulador antes del minuto `fin_min + 5,5`, aunque la plataforma haya terminado sola, y el resumen dice hasta qué minuto llegó el registro oficial.

El residual por ubicación que muestra la sala (y la cobertura del acta) es una **estimación**: la plataforma solo ve detecciones. El número que vale es el del verificador oficial (en un ensayo con el navegador: 6,7 % en la sala contra 7,0 % del verificador).

Partido final:

```sh
python3 -m marca exportar --salida salida --destino entrega/partido-final
python3 -m marca verificar entrega/partido-final --config config/jueces_final.json --huella <huella publicada>
```

(En un ensayo se agrega `--registro-simulador <registro.jsonl>`.)

**Con el partido cerrado, la huella que vale es la del cierre.** Al llegar a `fin_min + 5` la plataforma toma la foto final de los testigos, exporta sola a `<salida>/entrega` y publica esa huella en `/transparencia` y la sala. Después, `exportar` **solo copia ese paquete tal cual**, con la plataforma viva o apagada y cuantas veces se corra, a cualquier destino: no pide testigos nuevos ni escribe la auditoría, e imprime la misma huella. Lo que la auditoría anote después del cierre (sesiones, consultas) no va en el paquete; el comando lo avisa.

Con el partido **en curso** (todavía no hay `<salida>/entrega`), `exportar` refresca los testigos antes de armar el paquete:

- **plataforma viva:** responde `GET /api/salud` en 2 s con la `instancia` de `<salida>/plataforma.json`. El comando deja el archivo `<salida>/pedir-testigos`, que la plataforma consume en su ciclo, espera hasta 10 s a que anote una nueva `testigos_guardados` y a que `estado.json` la refleje (así el estado y los testigos son de la misma foto). Con la plataforma viva el comando **nunca** escribe la auditoría.
- **plataforma caída pero con conexión al simulador:** los consulta y los anota el propio comando.
- **sin conexión:** usa lo último guardado.

Un paquete exportado en pleno partido se coteja con el registro del simulador de ese momento, no con el del partido completo (ver «el cruce» en `verificar`, más abajo). El que se entrega es el del cierre.

Al final escribe `MANIFIESTO.json` e imprime **`Huella del paquete: <sha256>`**. La huella es repetible: el manifiesto no lleva la hora, así que exportar dos veces la misma salida sin entradas nuevas en la auditoría da la misma huella.

**Publicar esta huella** en el README, en el video y en el chat con la organización, apenas se exporta. La cadena de auditoría prueba que nada se cambió en el medio; la huella publicada prueba que no se cortó el final. Quien reciba el paquete corre `verificar <carpeta> --huella <huella publicada>`.

`exportar` arma el paquete en una carpeta temporal al lado del destino y recién al final la pone en su lugar. Un corte a mitad de camino deja la exportación anterior entera. Si `--destino` existe, tiene archivos y no es una exportación (no tiene `MANIFIESTO.json`), se niega y no toca nada. Usar siempre `entrega/partido-final`.

El paquete trae también `orden-marco/OM-xx.json` y `.md` (una por firma), y el acta abre con la sección «Orden marco» y las ampliaciones hechas bajo cada una. El acta muestra, por ubicación, cuánto pasó desde la detección hasta la firma, hasta el primer proveedor y hasta todos los proveedores, con promedios separados para firmadas en persona y ampliaciones automáticas, y dice quién firmó (personas o el juez automático de ensayo). La columna «Filtración» lleva el número de expediente, no la sesión del abonado.

`verificar` no necesita conexión. Revisa lo siguiente:

- el paquete contra `MANIFIESTO.json`: un archivo cambiado, faltante o sobrante da ✗ con su nombre (`.DS_Store`, `Thumbs.db` y `desktop.ini` no cuentan);
- que cada JSON se pueda leer y no tenga claves repetidas: si uno está roto, da ✗ con su nombre y sigue con los demás;
- la cadena de auditoría: no puede estar vacía y tiene que empezar en `inicio`; si el resumen dice que el partido cerró, tiene que estar el cierre;
- la cola: `resumen.json` y el acta dicen en qué entrada termina la auditoría; con `--huella`, la huella del paquete tiene que ser la publicada;
- cada captura contra su sha256;
- huellas, antecedentes y decisiones;
- que cada `orden_id` termine en su sello recalculado;
- `orden_enviada` y `orden_levantada` en la auditoría;
- el cruce en los dos sentidos: todo expediente, ubicación y orden que nombra la auditoría (o el registro, o los testigos) está exportado, y todo lo exportado está en la auditoría. Lo que la auditoría anotó después de la foto de los proveedores puede no estar en los expedientes exportados con esa foto (`exportar` con la plataforma viva a mitad del partido): es nota, no ✗. Después de la entrada `exportacion` del cierre ya no hay tolerancia: la plataforma guarda el estado en la misma pasada. En un paquete exportado a mitad del partido, lo posterior a la foto lo anclan la huella publicada y el registro oficial. Ese paquete se coteja con el registro del simulador **tal como estaba cuando se exportó**: contra el registro completo del partido es esperable que marque ✗ las órdenes posteriores (el registro las tiene y el paquete no). No es una falla del paquete ni hay que aflojar nada: el paquete que se entrega y se coteja con el registro completo es el del cierre;
- que lo que se lee fuera del sello coincida con lo sellado y lo auditado: host e IP, la decisión, y tipo, objetivo, vencimiento y juez de cada orden;
- **lo derivado**: estado y minutos de cada orden (aplicada, vencida, levantada, fallida, perdida, rechazada), ventana, cobertura y tiempos de cada ubicación, los promedios y «quién firmó» del acta, cada orden marco (minuto, nombre, ampliaciones), el nombre del juez en cada decisión, descartes y reclamos se recalculan desde la auditoría con las mismas funciones del exportador. Un `.json` editado da ✗ aunque se rehagan los `.md` y el manifiesto. No se anclan: los datos de los proveedores y los sitios ajenos que el DNS pasivo vio en cada IP;
- con `--config`, las firmas: **toda** decisión, ampliación y levantamiento tiene que tener la suya; una que falta es ✗. Un `--config` sin claves de firma es un error;
- que cada ampliación automática la haya escrito el sistema, bajo una orden anterior del mismo expediente;
- cada orden marco: su huella desde el texto y, con `--config`, su firma; cada ampliación cita una orden marco anterior del juez que la respalda, con el seguimiento autorizado y no reemplazada;
- los números de orden: `amp-` solo en ampliaciones automáticas, y toda ampliación con `amp-` (en la auditoría, los expedientes, el registro oficial y los testigos);
- los `.md`: los vuelve a generar desde los `.json` y los compara; un `.md` editado da ✗ aunque se rehaga el manifiesto;
- que una ubicación «sin decidir» (el partido terminó antes de la firma) no tenga órdenes;
- con `--registro-simulador`, el cruce con el registro oficial: mismas órdenes, nada ajeno, ninguna fuera de turno, ninguna rechazada, y el minuto de aplicación, el vencimiento y el estado final de cada orden iguales a los del simulador (también los de la cola posterior al último sello);
- los **testigos**, explicados abajo.

Devuelve 0 si no hay ✗ y 1 si hay. Cada falla dice el archivo, la ubicación o la línea y el campo. Sin `--registro-simulador` no hay fuente externa y la salida no dice «todo verifica»; termina con:

> Sin el registro oficial del simulador, esto prueba que el paquete es coherente consigo mismo, no que sea verdadero: los testigos también los guarda la plataforma, y quien la maneja podría haberlo recalculado todo. Para descartar una falsificación: --registro-simulador <registro.jsonl> y --huella <huella publicada>.
>
> Resultado: coherente consigo mismo (sin cotejar con el registro oficial del simulador).

Después del partido final no se toca el código: un paquete se verifica con la misma versión que lo exportó.

Con el registro oficial y sin ✗, termina con «Resultado: todo verifica.».

### Testigos de los proveedores

`testigos/proveedores.json` es lo que respondió `GET /proveedores/<id>/ordenes` para cada proveedor, junto con el minuto y la hora en que se consultó. En la auditoría queda `testigos_guardados` con el sha256 de esos bytes. `verificar` comprueba cuatro cosas:

- el sha256 coincide con esa entrada;
- cada orden nuestra que salió figura en el proveedor con el mismo tipo, objetivo, vencimiento y juez. Dos excepciones, que salen como nota (·) y no como ✗: una orden **perdida** (desapareció de la lista del proveedor y se volvió a emitir; tampoco se le exige al registro oficial) y una orden **enviada después de la foto** de los proveedores (`corte_auditoria` de la última `testigos_guardados`): el partido siguió después de exportar;
- el proveedor no tiene órdenes que no estén en nuestra auditoría;
- el `orden_id` del proveedor termina en el sello recalculado.

Si la auditoría no registra `testigos_guardados`, informa «no disponible». Si la auditoría dice que se guardaron y el archivo no está, es ✗.

## 4. Ensayos contra el simulador oficial

El simulador y el verificador oficiales se corren **solo** con `python3 -I`, con rutas absolutas y desde esta carpeta (nunca con `cd` al repo del desafío). `herramientas/ensayo.py` lo hace así. Arranca el simulador en el puerto 8791 y la plataforma en el 8792, con los dos jueces automáticos. Al terminar corre el verificador oficial y `marca verificar` cruzado con el registro, y da un veredicto según la sección 15.

```sh
R="/ruta/absoluta/al/repo/desafio-futbol"
python3 herramientas/ensayo.py --repo-desafio "$R" --acelerar 20 --salida salida-ensayo/A                                   # A
python3 herramientas/ensayo.py --repo-desafio "$R" --acelerar 20 --sin-dinamica --salida salida-ensayo/B                    # B
python3 herramientas/ensayo.py --repo-desafio "$R" --acelerar 20 --inicio-min 44 --salida salida-ensayo/C                   # C
python3 herramientas/ensayo.py --repo-desafio "$R" --acelerar 20 --forzar-ip tv.verpartido-hd.test --salida salida-ensayo/D # D
python3 herramientas/ensayo.py --repo-desafio "$R" --acelerar 20 --reiniciar-en 30 --salida salida-ensayo/E                 # E
```

Otras opciones:

- `--latencia-ms N`: la plataforma habla con el simulador a través de `herramientas/proxy_latencia.py`, que demora N ms cada pedido (ida y vuelta);
- `--jitter-ms J`: suma a cada pedido entre -J y +J ms al azar (`--semilla` lo repite igual);
- `--falla-cada N`: el proxy responde 502 a uno de cada N pedidos, sin pasarlo al simulador;
- `--puerto-proxy`: por defecto, el del simulador + 2;
- `--demora-juez` (0,3 min);
- `--alcance filtracion|ubicacion`;
- `--puerto-simulador` / `--puerto`;
- `--escenario` / `--verdad`: por defecto, los de práctica del repo.

Cada carpeta de ensayo guarda:

- `registro.jsonl` (registro oficial);
- `verificador_oficial.json`;
- `verificacion_integridad.txt`;
- `plataforma.log` y `simulador.log`;
- `marca/` (estado y exportación).

Ensayo con la red del evento (por ejemplo, 400 ms de ida y vuelta, ± 150 ms, y un 502 cada 40 pedidos):

```sh
python3 herramientas/ensayo.py --repo-desafio "$R" --acelerar 20 --latencia-ms 400 --jitter-ms 150 --falla-cada 40 --salida salida-ensayo/L
```

Solo la plataforma pasa por el proxy. El ensayo y el verificador oficial leen el simulador directo. El resumen dice cuántos pedidos pasaron, la demora media y cuántas fallas se inyectaron. El detalle queda en `proxy.jsonl`.

El proxy también se usa solo, por ejemplo para ensayar a mano:

```sh
python3 herramientas/proxy_latencia.py --destino http://127.0.0.1:8791 --puerto 8793 --latencia-ms 400
python3 -m marca servir --simulador http://127.0.0.1:8793 --puerto 8792 --salida salida-ensayo/manual --nueva
```

El resumen del ensayo también dice cuántas órdenes salieron con `ord-` y con `amp-`, y los tres tiempos promedio (hasta la firma, hasta el primer proveedor y hasta todos), separados en firmadas en persona y ampliaciones. Con `--sin-dinamica` o `--alcance ubicacion`, el veredicto exige 0 órdenes `amp-`.

`herramientas/juez_automatico.py` es **solo para ensayos**. En el partido final firman personas.

### «Ni nosotros podemos falsificarlo»

```sh
python3 herramientas/falsificar.py entrega/partido-final /tmp/falsificada --config config/jueces_demo.json
python3 -m marca verificar /tmp/falsificada                                                  # coherente consigo mismo
python3 -m marca verificar /tmp/falsificada --registro-simulador salida-ensayo/A/registro.jsonl  # ✗
```

- Trabaja sobre una copia: nunca toca la exportación original, y el destino no puede existir.
- Cambia la IP de una ubicación y recalcula todo lo que controla la plataforma: huellas, cadena de auditoría, firmas (con `--config`), sellos, números de orden, testigos, textos y manifiesto.
- Sin nada de afuera, `verificar` no lo nota. Con el registro oficial, sí: el simulador tiene las órdenes verdaderas.
- Imprime la huella original y la falsificada: son distintas. Por eso la huella se publica al exportar.

## 5. Si algo falla

| Síntoma | Qué mirar |
|---|---|
| `chequear` no conecta | URL y puerto del simulador; que no haya proxy (el cliente no usa proxy). |
| `chequear`: «Este Python no confía en el certificado…» | El simulador es https y este Python no tiene sus certificados: correr con `/usr/bin/python3` o pedir una dirección http. |
| Un celular recibe «Plataforma ocupada: reintentar» (503) | Hay demasiadas conexiones abiertas, en total o desde una misma IP. Recargar en unos segundos; si sigue, buscar qué máquina de la red abre tantas. |
| «No se pudo abrir el puerto» (código 4) | Otro proceso en el puerto: `lsof -nP -iTCP:8792 -sTCP:LISTEN` (Windows: `netstat -ano`). |
| «Ya hay una plataforma corriendo sobre la salida» (código 3) | Hay otra plataforma viva sobre esa carpeta. Usar esa. No borrar `<salida>.candado`. |
| `--nueva` se niega (código 5) | El simulador ya tiene órdenes: reanudar con el mismo comando **sin `--nueva`**. |
| `exportar`: «no es una exportación» | El destino tiene otros archivos. Usar `entrega/partido-final`. |
| Aviso «La auditoría guardada estaba dañada…» | La plataforma apartó la cola dañada a `auditoria.danada-<fecha>.jsonl` y siguió. No borrar ese archivo: `exportar` lo copia a `auditoria-apartada/` del paquete. |
| Aviso «Detección … inválida» o «Reclamo … inválido» | El simulador mandó un dato mal formado. Quedó auditado y no se bloquea nada por él. El partido sigue. |
| Aviso «Error interno en la etapa …» | Mirar el traceback en la consola. Las demás etapas siguen funcionando. |
| La plataforma no arranca sin `--nueva` | Es de otro partido, o el simulador volvió a un minuto anterior: el mensaje lo dice. Ver «Si la organización reinicia el simulador». |
| Una orden queda «incierta» | Es normal tras un error de red: se resuelve sola con un `GET` al proveedor. |
| Una orden sale «rechazada» en la sala | Ver la alerta y `plataforma.log`; nunca reenviarla a mano con el mismo `orden_id`. |
| No firma nadie | Fuera de los márgenes de turno no se firma, por diseño (sección 6). El campo `turno` de `/api/juez/bandeja` dice si el juez está de turno y cuánto falta para el próximo. |
| `verificar` da ✗ | La línea dice qué archivo y qué campo no cierra. |
| `verificar`: «la entrada N ya no da el sello» | Alguien reescribió la auditoría y recalculó la cadena entera. El paquete no sirve: volver a exportar desde `salida/`. |
| La consola muestra signos raros en vez de ✓ y ✗ | En Windows, `chcp 65001` antes de correr. Los comandos no se caen por esto. |
| Testigos «no disponible» | No se llegó a `fin_min + 5` con la plataforma viva. Correr `exportar` con el simulador accesible. |
| `verificar`: «cambió después de exportar» o «sobra» | Alguien tocó el paquete después de exportar. Volver a exportar desde `salida/`, que no se toca. |
| No se sabe la IP para el celular | macOS: `ipconfig getifaddr en0`. Linux: `hostname -I`. Windows: `ipconfig`. |
