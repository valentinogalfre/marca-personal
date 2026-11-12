# Fuentes

De dónde sale cada dato de prensa, de derecho y técnico que usan los documentos de la entrega. Todas las páginas se abrieron entre el 11 y el 12 de noviembre de 2026; no se hicieron búsquedas nuevas para esta versión.

Abreviaturas de «Dónde se usa»: **D** `EL-DESAFIO.md` (D §2 es la sección 2: 1 el problema, 2 lo fijo y lo abierto, 3 la evaluación, 4 las trampas, 5 la respuesta, 6 lo que sigue en discusión), **P** propuesta normativa (P2 es el punto 2), **R** README; **G**, **Q** y **PL** son el guion, las preguntas y el plan del equipo, que quedan fuera del repo público.

Reglas: si un dato solo está en la consigna, el texto dice «según la consigna». Si una fuente es la única que lo dice, lo marcamos.

## Vocabulario y postura

Lo que usan igual los siete documentos.

- **Seguimiento** (la prensa habló de «bloqueo dinámico»): si el juez lo autoriza en su orden marco y lo elige al firmar, la plataforma sigue sola a la misma filtración cuando se muda de servidor. Cada orden que sale así es una **ampliación automática** (número `amp-`). El juez la **frena** cuando quiere. La opción de la línea de comandos conserva su nombre: `--sin-dinamica`.
- **Postura del equipo:** el seguimiento está apagado por defecto y lo decide quien firma; se les pregunta a los mentores el jueves 12; si no hay respuesta, el partido final se corre con la casilla destildada (cada orden firmada en persona) y el seguimiento se muestra medido sobre un partido de práctica.
- **Presente**: la bandeja del juez abierta, vista en los últimos 90 segundos reales. El registro público, una orden o la sala no cuentan; cerrar sesión la corta en el acto.
- **Visto e inferido**: visto es el nombre del stream (y el de su página, si es del mismo dominio); inferido, otro nombre de ese dominio en el mismo servidor. El reclamo fundado de un inferido corrige la inferencia y levanta todo lo que dependía de ella.
- **Texto de la orden marco**: renglón 4, «…mi firma, servidor por servidor, salvo que en esta orden autorice el seguimiento de la misma filtración»; condición 1, «…el bloqueo nuevo no alcanza a sitios ajenos: si el servidor nuevo comparte la IP con sitios ajenos, se bloquea solo el nombre del stream». Fuente: `ronda3/CONTRATO-R3B.md`, no el código (a las 04:00 el código todavía tenía el texto anterior).

**Citas que no se sostienen al pie de la letra.**

- Cómo lo llamó la prensa: las notas guardadas dicen «bloqueo dinámico» (Baires Para Todos, La Capital), «mecanismo de bloqueo dinámico» (Elonce), «mecanismos de bloqueo dinámico» (Infobae) y «carácter dinámico» (DPL News, 2/6/2025). Nosotros lo llamamos «seguimiento».
- La Recomendación (UE) 2023/1018 no dice «órdenes dinámicas»: dice «acciones de cesación dinámicas» (fila de abajo).
- Los tiempos de «una herramienta lenta que firmó desde el navegador a ×6» que traía la versión anterior (4,98 · 5,52 · 12,08 y 0,01 · 0,54 · 5,62 min) no tienen una carpeta de corrida que los respalde: se sacaron de todos los documentos.

## Argentina

| Dato | Fuente | Dónde se usa |
|---|---|---|
| El 31 de mayo y el 1 de junio de 2025 se hizo el primer bloqueo en vivo, en la final de la Champions y en la del Torneo Apertura. Lo pidió la UFEIC de San Isidro y lo ordenó el Juzgado de Garantías N.º 4 de San Isidro. | La Nación, 2/6/2025: https://www.lanacion.com.ar/seguridad/bloquearon-en-vivo-sitios-y-apps-que-transmitian-partidos-de-futbol-de-manera-ilegal-nid02062025/ · Baires Para Todos, 31/5/2025: https://bairesparatodos.com.ar/la-justicia-activa-un-operativo-contra-la-pirateria-de-futbol-las-transmisiones-ilegales-de-partidos-seran-bloqueadas-en-tiempo-real/ · DPL News, 2/6/2025: https://dplnews.com/?p=276615 | D §1, Q |
| Baires Para Todos lo llama «prueba piloto»: la fiscalía identificaba durante los partidos los sitios y las IP; los proveedores tenían que tener técnicos disponibles. | Baires Para Todos, 31/5/2025 (enlace arriba). Única fuente. | D §1 |
| El bloqueo por IP rigió solo durante los partidos; el de DNS quedó permanente. | Consigna, línea 14. Baires Para Todos lo anuncia antes de los partidos; no hay segunda fuente. Se cita «según la consigna». | D §1, P4, Q |
| La orden llegó a los proveedores por sus cámaras (CABASE y CAPPI) porque el ENACOM no tenía un registro actualizado. | Consigna, línea 15. Baires Para Todos, única fuente de prensa. **DPL News (2/6/2025) dice en cambio que la orden se libró al ENACOM**, y La Nación (2/6/2025) habla de la «participación activa» del ENACOM. No se pudo aclarar. | D §1 y §6, P5 |
| La orden de 2025 tenía «carácter dinámico» y autorizaba al fiscal a pedir bloqueos nuevos cuando los sitios migraban de dominio: lo dice solo DPL News. Baires Para Todos habla de «bloqueo dinámico». 442 Perfil (copia de Baires) dice que la fiscalía identificaba sitios e IP; La Nación, que la orden «habilitó a los operadores» y que hubo «participación activa» del ENACOM (estas dos no se volvieron a abrir en esta versión). | DPL News, 2/6/2025: https://dplnews.com/?p=276615 · 442 Perfil, 30/5/2025: https://442.perfil.com/noticias/futbol/la-justicia-activa-un-operativo-contra-la-pirateria-de-futbol-las-transmisiones-ilegales-de-partidos-seran-bloqueadas-en-tiempo-real.phtml · La Nación, 2/6/2025 (enlace arriba) · Baires Para Todos (enlace arriba) | D §1 y §6, P2 |
| Las objeciones eran consideraciones internas de CABASE, que todavía no tenía postura pública: no todos los proveedores pueden reaccionar en tiempo real; faltan reglas sobre costos, duración y gestión posterior. La de la IP compartida, la nota se la atribuye a «proveedores consultados». La consigna pone las tres como objeciones de CABASE. | Baires Para Todos, 31/5/2025 (enlace arriba) · Consigna, líneas 17 a 20 | D §1, G, P8, Q |
| El presidente de CABASE dijo que la Justicia no debería usar a las cámaras como intermediarias de las notificaciones. | DPL News, 2/6/2025: https://dplnews.com/?p=276615 | D §1, P5 |
| Casos de apuestas (no de fútbol): la orden llega al ENACOM, que la remite a CABASE, que informa a cada socio y deja la decisión a criterio de cada uno; al ENACOM le dan 72 horas para informar. | iProfesional, 2/5/2018: https://www.iprofesional.com/marketing/267580-no-va-mas-los-oficios-contra-el-juego-online-al-estilo-uber-revelan-vacios-legales-con-que-actua-la-justicia | D §1 |
| El ENACOM se describe como «intermediario entre la justicia y los prestadores de internet»; más de mil casos de apuestas en 2024. | DPL News, 3/9/2024: https://dplnews.com/?p=247922 | D §1, P |
| 2023: el Juzgado Civil y Comercial Federal N.º 2 (causa CCF 10595/2022), con una cautelar, ordenó a todos los proveedores registrados ante el ENACOM bloquear 30 sitios que transmitían partidos de fútbol. | Palabras del Derecho, 3/3/2023: https://www.palabrasdelderecho.com.ar/articulo/4140/Ordenaron-el-bloqueo-de-sitios-web-que-transmitian-partidos-de-futbol-en-infraccion-de-los-derechos-de-propiedad-intelectual | P |
| El 1 de noviembre de 2026, antes del Superclásico, a partir de una presentación de ALIANZA, la UFEIC de San Isidro le pidió al ENACOM bloquear 182 dominios, y el ENACOM se lo comunicó a los proveedores de todo el país. Infobae: «la justicia autorizó la aplicación de mecanismos de bloqueo dinámico». | Elonce: https://www.elonce.com/deportes/la-justicia-bloqueo-182-sitios-web-que-iban-a-transmitir-ilegalmente-el-superclasico.htm · La Capital: https://www.lacapital.com.ar/superclasico-bloquearon-argentina-mas-180-sitios-piratas-que-iban-retransmitir-boca-y-river-n10289906.html · Infobae, 1/11/2026: https://www.infobae.com/judiciales/2026/11/01/la-justicia-ordeno-el-bloqueo-de-mas-de-180-sitios-web-que-planeaban-transmitir-ilegalmente-el-superclasico/ · DPL News: https://dplnews.com/?p=335763 (reproduce la nota de Infobae; no es una fuente independiente) · Consigna, línea 16. Infobae habla de una «resolución judicial» y La Capital dice que el bloqueo dinámico «eliminó la posibilidad» de que esos sitios retransmitieran; ninguna publica la orden. | D §1, G |
| Las notas revisadas no nombran al juzgado ni al juez, ni dicen quién decide cada actualización, si el bloqueo es por DNS o por IP, ni cuánto dura. Vale para esas notas, no para toda la prensa. | Infobae, La Capital, Elonce y DPL News (enlaces arriba) · 3DJuegos: https://www.3djuegos.com/tecnologia/noticias/justicia-ordeno-bloqueo-180-sitios-web-que-planeaban-transmitir-ilegalmente-superclasico | D §1 y §6, G |
| Agosto de 2011: una orden para bloquear dos dominios terminó con proveedores bloqueando la IP 216.239.32.2, ligada a más de un millón de blogs. | EFF, 19/8/2011: https://www.eff.org/deeplinks/2011/08/argentina-isps-ip-overblocking | D §1, P4, Q |
| En 2024, el Juzgado de Garantías N.º 4 de San Isidro le pidió por oficio al ENACOM bloquear 69 sitios de Magis TV. | La Nación, 19/9/2024: https://www.lanacion.com.ar/seguridad/55-millones-de-visitas-ordenaron-bloquear-el-mayor-sitio-de-servicio-ilegal-de-tv-y-le-hicieron-un-nid19092024/ | Q |
| Ley 11.723, art. 79: los jueces pueden, previa fianza, decretar preventivamente medidas para proteger esos derechos. | Infoleg: https://servicios.infoleg.gob.ar/infolegInternet/anexos/40000-44999/42755/texact.htm | P |
| Ley 27.078, art. 57 inc. a: los prestadores no pueden bloquear «salvo orden judicial o expresa solicitud del usuario». El art. 56 es el de neutralidad de red. | Infoleg: https://servicios.infoleg.gob.ar/infolegInternet/anexos/235000-239999/239771/texact.htm | P, Q |
| Ley 26.032: Internet está dentro de la garantía de libertad de expresión. «Rodríguez c/ Google» (CSJN, 2014): toda restricción a la libertad de expresión es de interpretación restrictiva. | Infoleg: https://servicios.infoleg.gob.ar/infolegInternet/anexos/105000-109999/107145/norma.htm · Fallo: https://repositorio.mpd.gov.ar/documentos/Rodriguez,%20Maria%20Belen.pdf | Q |
| Provincia de Buenos Aires, CPP art. 23 bis (Ley 13.183): el juez de garantías de turno recibe presentaciones las 24 horas; con extrema urgencia, resuelve en no más de 6 horas. | https://intranet.hcdiputados-ba.gov.ar/refleg/sw11922.pdf · https://normas.gba.gob.ar/documentos/0Z8oGFEB.html | D §1, P |

## Otros países

| Dato | Fuente | Dónde se usa |
|---|---|---|
| Italia: Piracy Shield es del regulador (AGCOM), sin juez, por la Ley 93/2023; los proveedores bloquean en 30 minutos. | Ley 93/2023: https://www.sistemapenale.it/pdf_contenuti/1690929522_legge-14-luglio-2023-n-93-diritto-dautore.pdf · https://www.normattiva.it/uri-res/N2Ls?urn:nir:stato:legge:2023-07-14;93 · Consigna, línea 28 | D §1, P5, Q |
| Italia, 24/2/2024: Piracy Shield bloqueó una IP de Cloudflare y cayeron sitios legítimos. | TorrentFreak: https://torrentfreak.com/piracy-shield-cloudflare-disaster-blocks-countless-sites-fires-up-opposition-240226/ · Punto Informatico: https://www.punto-informatico.it/piracy-shield-blocca-ip-cloudflare-siti-legittimi/ | D §1, Q |
| Reino Unido: en FAPL v BT [2017] EWHC 480 (Ch), la High Court fijó criterios; los servidores los identifica el titular (FAPL y su contratista) y la lista se renueva cada semana de partidos. | https://caselaw.nationalarchives.gov.uk/ewhc/ch/2017/480 | D §1, P1 |
| Reino Unido: en Cartier v BT [2018] UKSC 28, la Corte Suprema dijo que, en principio, los titulares cubren los costos razonables de cumplir. Es un caso de marcas, no de fútbol. | https://caselaw.nationalarchives.gov.uk/uksc/2018/28 | P5, Q |
| Francia: la Ley 2026-725 (3/8/2026, JORF 4/8/2026), art. 31: si la orden judicial lo prevé, los servicios nuevos se bloquean sin demora durante la transmisión, a través del sistema bajo control de ARCOM. | https://www.associatheque.fr/fr/fichiers/actualite/loi-2026-725-NOR-SPOX2516508L.pdf | D §1 y §6, Q |
| España: entre el 1 de enero y el 1 de junio de 2026, los bloqueos por IP de LaLiga afectaron en algún momento a 554 507 dominios. | OONI, 30/6/2026: https://ooni.org/post/2026-laliga-collateral/ | P4, Q |
| Grecia: el regulador (EETT) bloquea sin demora las direcciones nuevas y después hay una decisión complementaria (Ley 2121/1993, art. 66E); 30 minutos para los proveedores de más de 20 000 abonados (Ley 5179/2025, art. 81). | https://library.opi.gr/wp-content/uploads/2121_1993_en.pdf · https://www.taxheaven.gr/law/5179/2025/arthro/81 | D §1, Q |
| Brasil: la Ancine bloquea por vía administrativa desde la Instrução Normativa 174 (abril de 2026). | https://www.gov.br/ancine/pt-br/acesso-a-informacao/legislacao/instrucoes-normativas/instrucao-normativa-174 | D §1 |
| Uruguay: la URSEC tiene un sistema en línea para comunicar órdenes de bloqueo a los proveedores, incluidas medidas por eventos deportivos en línea; el proveedor confirma y desbloquea al vencer el plazo. No se comprobó si interviene un juez. | https://www.gub.uy/unidad-reguladora-servicios-comunicaciones/institucional/preguntas-frecuentes/comunicacion-ursec-prestadores-servicios-internet-isp | D §1 |
| Unión Europea: la Recomendación 2023/1018, en su texto en castellano, habla de «acciones de cesación dinámicas» («Carácter dinámico de las acciones de cesación», punto 12), que se amplíen a servicios no identificados al pedirlas «cuando afecten al mismo acontecimiento deportivo» (punto 12); pide que las actualizaciones queden «bajo el control de una autoridad judicial» (punto 13) y que la medida rija solo durante la transmisión en vivo (punto 19). No es obligatoria. | https://eur-lex.europa.eu/legal-content/ES/TXT/HTML/?uri=CELEX:32023H1018 | D §1 y §6, P2, P4, R, Q |
| Unión Europea: el TJUE, en UPC Telekabel (C-314/12, 27/3/2014, apartado 57), exige que los usuarios puedan hacer valer sus derechos ante el juez. | https://eur-lex.europa.eu/legal-content/ES/TXT/HTML/?uri=CELEX:62012CJ0314 | P7 |

## Kit del proveedor (técnico)

Las líneas del kit se revisaron contra esta documentación. No se probaron en equipos reales.

| Dato | Fuente | Dónde se usa |
|---|---|---|
| MikroTik: una entrada de address-list con timeout es dinámica y se borra al reiniciar el equipo. | https://manual.mikrotik.com/docs/7.25/cli-reference/ip/firewall/address-list/ | R, kit |
| MikroTik: lo que pasa por FastTrack saltea el firewall; una regla agregada al final no corta las conexiones ya abiertas (por eso `place-before=0`). | https://help.mikrotik.com/docs/spaces/ROS/pages/328227/Packet+Flow+in+RouterOS · https://manual.mikrotik.com/docs/firewall-and-quality-of-service/firewall/filter/ | R, Q, kit |
| MikroTik: IPv6 va por una lista aparte. | https://manual.mikrotik.com/docs/7.25/cli-reference/ipv6/firewall/address-list | kit |
| MikroTik: el DNS estático (NXDOMAIN) no vence solo, solo alcanza a los equipos que usan el router como DNS y hay que vaciar la caché; un `scheduler` con `interval=0s` corre una sola vez. | https://manual.mikrotik.com/docs/7.25/cli-reference/ip/dns/static/ · https://manual.mikrotik.com/docs/7.25/network-management/dns/ · https://manual.mikrotik.com/docs/7.25/cli-reference/system/scheduler/ | D §6, R, Q, kit |
| MikroTik: `type=NXDOMAIN` existe desde RouterOS 6.47 (inferido del anuncio de la versión y de un ejemplo en el foro). | https://forum.mikrotik.com/t/v6-47-stable-is-released/140100 · https://forum.mikrotik.com/t/question-how-to-set-a-nxdomain-entry-in-routeros-dns-with-6-47-1/141740 | kit |
| nftables: los elementos de un conjunto pueden llevar timeout; el hook `forward` es el del tráfico que atraviesa el equipo; los flujos de una flowtable saltean el camino clásico. | https://wiki.nftables.org/wiki-nftables/index.php/Element_timeouts · https://wiki.nftables.org/wiki-nftables/index.php/Netfilter_hooks | R, kit |
| Unbound: `always_nxdomain` responde NXDOMAIN; lo cargado con `unbound-control` vive en memoria y no vence solo. | https://unbound.docs.nlnetlabs.nl/en/latest/manpages/unbound.conf.html · https://unbound.docs.nlnetlabs.nl/en/latest/manpages/unbound-control.html | R, Q, kit |
| BIND: una zona RPZ con `CNAME .` responde NXDOMAIN; las actualizaciones se aplican como mucho una vez cada `min-update-interval` (60 s por defecto); `nsupdate -l` funciona con `update-policy local`. | https://bind9.readthedocs.io/en/stable/reference.html | R, Q, kit |
| Firefox con DNS cifrado (modo 3) saltea el bloqueo por DNS del proveedor. | https://wiki.mozilla.org/Trusted_Recursive_Resolver | D §6, R, Q |

Nota: que `always_nxdomain` corte también los subdominios es una decisión nuestra para el kit; no lo citamos como dato de la documentación.

## La consigna oficial

`README.md` del repo `qualydata-org/desafio-futbol`. `EL-DESAFIO.md` cita su línea en cada dato; acá van las que usan varios documentos.

| Dato | Línea | Dónde se usa |
|---|---|---|
| Un partido dura dos horas; un sitio pirata cambia de servidor en minutos; la orden tiene que llegar a todos los proveedores. | 9 | D §1 |
| Mayo de 2025: UFEIC y Juzgado de Garantías N.º 4; IP solo durante los partidos, DNS permanente; la orden por las cámaras porque el ENACOM no tenía un registro actualizado. | 13 a 15 | D §1, P4, P5 |
| Superclásico: ALIANZA; la UFEIC pidió al ENACOM 182 dominios, «con un mecanismo dinámico que actualiza la restricción cuando los sitios cambian de dominio». | 16 | D §1 y §6, P, R, G, Q, PL |
| Objeciones de CABASE. | 17 a 20 | D §1 |
| «Depende de una sola fiscalía y un solo juzgado, sin un procedimiento formal ni un canal estándar». | 22 | D §1, P, Q |
| Tabla de países y «no encontramos ningún país donde cada pedido llegue en el momento a un juez de turno». Francia y Reino Unido: el juez interviene en la orden inicial. | 26 a 34 | D §1 y §6 |
| Qué tiene que hacer la plataforma, núcleo y extras (juez de turno y decisión firmada, l. 73). | 52 a 83 | D §1 y §2 |
| Quién pide el bloqueo: titular de derechos o fiscalía. | 89 | D §1 |
| No bloquear sitios legítimos ni al licenciatario (rúbrica). | 263 | D §1 y §3 |
| Verificar la marca contra `GET /partido` antes de pedir el bloqueo. | 173 | D §2 y §4 |
| Formato de la orden, firma de demostración y estados. | 175 a 209 | D §2 |
| «La plataforma firma con la clave de un juez solo después de que ese juez inició sesión y aprobó la orden. Nadie firma en su nombre». | 203 | D §2, §4 y §6, P, R, G, Q, PL |
| Situaciones del partido. | 213 a 221 | D §2 y §4 |
| Qué mide el verificador. | 225 a 234 | D §3 y §4 |
| Requisitos excluyentes, entregables y «lo que se evalúa es lo que está en el repo a la hora de cierre». | 236 a 253 | D §2, §3 y §6 |
| Propuesta normativa: orden marco, registro, plazos, colateral, reclamos, transparencia. | 250 | D §2 y §6, P, R, G, Q, PL |
| Rúbrica. | 257 a 265 | D §3 |
| Firma de demostración: un HMAC con la clave de demostración del juez; en la vida real sería una firma digital. | 195 a 201 | D §2, R, Q |
| El saliente ya no puede firmar. | 74 |
| «No encontramos ningún país donde cada pedido llegue en el momento a un juez de turno […]. Eso es lo que les proponemos construir.» | 34 | D §2 y §6 |
| La plataforma corre el circuito completo durante el partido final (requisito excluyente). | 241 | D §2 y §3 | D §2 y §4, G, Q |
| A ×6 el partido dura 17,5 minutos reales; el simulador reescribe su registro en cada corrida; se evalúa «cuando el partido termine (y pasen los 5 minutos de gracia)». | 120, 121 y 130 | D §2, R, G |
| El final usa los mismos jueces y turnos. | 205 | D §2, PL |
| Claves y usuarios de demostración permitidos en el repo. | 243 | Q, PL |
| El video puede grabarse sobre un partido de práctica y mostrar al final la salida de `evaluacion/verificar.py`. | 248 | G, PL |
| En `entrega/`, lo exportado del partido final. | 249 | D §3, PL |
| Al cierre se clona el repo y se anota el commit. | 253 | R, PL |
| Velocidad: «con cobertura de todos los proveedores». | 264 | D §2 y §3, R, G, Q |
| Una instancia del simulador por equipo en el final, posiblemente acelerada. | 275 | D §3, R |

## Otros archivos del repo oficial (leídos, no ejecutados)

| Dato | Archivo | Dónde se usa |
|---|---|---|
| Cuatro proveedores: Aurora (3 800 000 clientes, IP y dominio, demora 0,5), Andina (1 200 000, IP y dominio, 2,0), Valle (140 000, solo dominio, 6,0), Cumbre (60 000, IP y dominio, 3,0, falla el 35 %). Aurora es el 73 % de los clientes. | `datos/proveedores.json` | D §2, §3 y §4 |
| La demora real de cada orden es la declarada por un factor entre 0,7 y 1,3 (Valle: de 4,2 a 7,8 min; Cumbre avisa la falla entre 2,1 y 3,9 min). | `simulador/servidor.py`, l. 192 (demora) y 256 a 264 (la falla se anota en el minuto en que tocaba aplicar) | D §2, §3, §4 y §6 |
| La API no muestra demoras ni fallas de los proveedores. | `simulador/servidor.py`, l. 123 a 128 | D §2 |
| El simulador acepta una orden de un juez fuera de turno y solo lo anota. | `simulador/servidor.py`, l. 201 y 202 | D §2 y §4 |
| Rechazos: `orden_id` repetido (409), tipo que el proveedor no acepta (422), `vence_min` no entero o vencido, juez o firma inválidos. | `simulador/servidor.py`, l. 155 a 178 | D §4 |
| El reclamo trae el sitio y el proveedor, no la orden. `GET /reclamos` redondea `minuto_actual` a dos decimales. | `simulador/servidor.py`, l. 144 a 147 y 296 a 299 | D §2 y §4 |
| Turnos de la práctica: la primera jueza hasta el minuto 50, el segundo juez desde el 50. | `datos/juzgados.json` | D §2 y §4 |
| CDN con 11 sitios legítimos detrás de la IP; hosting compartido con 4. | `datos/escenario_practica.json` (`dns_pasivo`) | D §4 |
| Dos servidores pirata comparten la IP solo con su propio respaldo (`s1.pelotaya.test` con `s1-respaldo.pelotaya.test`; `s3.pelotaya.test` con `espejo.pelotaya.test`) y la verdad oficial recomienda IP para los dos. | `datos/escenario_practica.json` y `evaluacion/verdad_practica.json` | D §4 |
| El verificador mide primer bloqueo, clientes cubiertos y visibilidad residual por servidor, y lista también los bloqueos por dominio activos después del partido. | `evaluacion/verificar.py`, l. 76 a 133 |
| El primer bloqueo se cuenta desde que empieza cada fase y vale el de cualquier proveedor; «clientes cubiertos» suma a cada proveedor que bloqueó en algún momento; la residual pesa clientes por minutos bloqueados. | `evaluacion/verificar.py`, l. 89 a 99 |
| El daño colateral se cuenta por orden aplicada en cada proveedor. | `evaluacion/verificar.py`, l. 102 a 111 |
| Los bloqueos activos después del partido solo se evalúan si el registro llega al minuto 110 (fin + gracia); si no, «no evaluable». Los de dominio son «informativo». | `evaluacion/verificar.py`, l. 125 a 133, 211, 212 y 216 |
| El simulador anota el cierre de la ventana (fin + gracia) en el registro. | `simulador/servidor.py`, l. 250 a 254 | D §3 y §4 |

## Lo que medimos nosotros

No son fuentes externas. Salen de nuestras corridas contra el simulador oficial y el verificador oficial. Se midieron con el código congelado y cada número dice de qué ensayo sale: A (práctica a ×20, seguimiento autorizado), U (casilla destildada), H (juez simulado a ritmo humano), M (partido espejo), D (error forzado), y los demás que se nombran en el texto.

| Familia | Corrida | Quién firma |
|---|---|---|
| A | Práctica oficial ×20, seguimiento autorizado (`herramientas/ensayo.py`, `--alcance filtracion`, juez a los 0,3 min) | Juez automático de ensayo |
| U | Ídem con `--alcance ubicacion` (casilla destildada, todo firmado una por una) | Juez automático |
| B, C, D, E, A60, L | `--sin-dinamica`; `--inicio-min 44`; `--forzar-ip tv.verpartido-hd.test`; `--reiniciar-en 30`; `--acelerar 60`; `--latencia-ms 400 --jitter-ms 150 --falla-cada 40` | Juez automático |
| M | Partido espejo con trampas, semilla 11, ×20 | Juez automático |
| P1 a P4 | Práctica oficial con personas desde el celular: ×6 y ×20, con y sin seguimiento | Personas del equipo, que ya conocían el partido |
| V | Corrida del video, ×6 | Personas del equipo |
| F | Partido final | Quien firme ese día |

Lo que no lleva marcas porque no lo medimos: la demora de cada proveedor y la tasa de falla (de 4,2 a 7,8 min y 35 %) salen de `datos/proveedores.json` y `simulador/servidor.py`, l. 192.

Valores de rondas anteriores que **no** se usan: los de la herramienta lenta (arriba); visibilidad residual sin seguimiento 3,7 %; mudanzas con primer bloqueo en 0,53, 0,62 y 0,83 min; los cuatro proveedores entre 4,94 y 7,16 min; los minutos del reclamo forzado; el reinicio en el minuto 30 «antes del rediseño» (7 de 7, sin duplicadas), que ahora es 7 de 7 y 0.

## Datos confirmados que no usamos

Están verificados pero no entraron: Ley 11.723, art. 71; «Gimbutas c/ Google» (CSJN, 2017) y «Denegri c/ Google» (CSJN, 2022); Italia, bloqueo de Google Drive (19/10/2024) y Delibera 48/25/CONS (bloqueos de al menos seis meses); Francia, art. L.333-10 del Código del Deporte; el acuerdo comercial Estados Unidos–Argentina de 2026 (ARTI), que habla de «injunctions» contra la piratería en línea pero no de bloqueo; los antecedentes argentinos de 2024 a 2026 (Fútbol Libre, Magis TV, «Operación Tarjeta Roja»).
