# Acta del partido — Partido de práctica — Club Ficticio del Norte vs. Deportivo Ejemplo

- Partido: practica-01 · titular: Liga Profesional Ficticia · fin: minuto 105,0
- Plataforma Marca Personal 1.0.0 · simulador: http://127.0.0.1:8900
- Cabeza de la auditoría: entrada 229, hash `d2927dff0f9b849493d9bf9cc6881dbfb99e4d4e0ab931763e79631c774deef7`
- Firmaron: el juez automático de ensayo (solo pruebas).

## Orden marco

- OM-01: Dra. Laura Ficticia (Juzgado de Garantías N.º 3 (ficticio) — Distrito Judicial Centro), minuto 0,2 (18:00:09) · seguimiento: sí · huella `dc4b858e2bcee10a90073371a18a62b36fdefaa57bf2a37ef98549d97157fdb4` (entrada 3). Texto en orden-marco/OM-01.md.
  - Ampliaciones hechas bajo esta orden: EXP-2026-000001 U2 (minuto 37,6).
- OM-02: Dr. Martín Ejemplo (Juzgado de Garantías N.º 1 (ficticio) — Distrito Judicial Norte), minuto 50,2 (18:50:11) · seguimiento: sí · huella `f8535052acf78f69f65cf94af1de21d8d46ac3434ae4c53aacf07d37f519ff26` (entrada 113). Texto en orden-marco/OM-02.md.
  - Ampliaciones hechas bajo esta orden: EXP-2026-000001 U3 (minuto 71,0); EXP-2026-000004 U2 (minuto 82,0).

## Filtraciones

| Expediente | Sitio | Filtración | Ubicación | Host / IP | Decisión | Promoción | Primer bloqueo | Cobertura | Visibilidad residual |
|---|---|---|---|---|---|---|---|---|---|
| EXP-2026-000001 | pelotaya.test | EXP-2026-000001 | U1 | s1.pelotaya.test / 203.0.113.10 | firmada en persona | x: https://x.example/futbolya_ok/status/1001 | 0,8 min | 100,0 % | 3,5 % |
| EXP-2026-000001 | pelotaya.test | EXP-2026-000001 | U2 | s2.pelotaya.test / 203.0.113.11 | ampliación automática | x: https://x.example/futbolya_ok/status/1001 | 0,5 min | 100,0 % | 3,2 % |
| EXP-2026-000001 | pelotaya.test | EXP-2026-000001 | U3 | s3.pelotaya.test / 198.51.100.77 | ampliación automática | x: https://x.example/futbolya_ok/status/1001 | 0,4 min | 100,0 % | 2,6 % |
| EXP-2026-000002 | golazo-libre.test | EXP-2026-000002 | U1 | live.golazo-libre.test / 198.51.100.20 | firmada en persona | x: https://x.example/golazolibre/status/2207; discord: https://discord.example/invite/golazo-hoy | 1,1 min | 100,0 % | 1,6 % |
| EXP-2026-000003 | verpartido-hd.test | EXP-2026-000003 | U1 | tv.verpartido-hd.test / 192.0.2.50 | firmada en persona | telegram: https://t.example/verpartidohd | 1,0 min | 100,0 % | 1,5 % |
| EXP-2026-000004 | tribuna-pirata.test | EXP-2026-000004 | U1 | x9.tribuna-pirata.test / 203.0.113.40 | firmada en persona | discord: https://discord.example/invite/tribuna-vip; telegram: https://t.example/tribunapirata | 0,9 min | 100,0 % | 4,9 % |
| EXP-2026-000004 | tribuna-pirata.test | EXP-2026-000004 | U2 | x10.tribuna-pirata.test / 203.0.113.41 | ampliación automática | discord: https://discord.example/invite/tribuna-vip; telegram: https://t.example/tribunapirata | 0,6 min | 100,0 % | 5,3 % |

Visibilidad residual promedio: 3,2 %.

## Tiempos

Minutos de partido desde la primera detección de cada ubicación.

| Expediente | Ubicación | Firma | Hasta la firma | Hasta el primer proveedor | Hasta todos los proveedores | Pedido en la bandeja antes de firmar |
|---|---|---|---|---|---|---|
| EXP-2026-000001 | U1 | en persona | 0,3 | 0,8 | 5,9 | 0,3 |
| EXP-2026-000001 | U2 | ampliación automática | 0,1 | 0,5 | 8,0 | — |
| EXP-2026-000001 | U3 | ampliación automática | 0,0 | 0,4 | 6,4 | — |
| EXP-2026-000002 | U1 | en persona | 0,4 | 1,0 | 5,9 | 0,3 |
| EXP-2026-000003 | U1 | en persona | 0,4 | 1,0 | 8,2 | 0,3 |
| EXP-2026-000004 | U1 | en persona | 0,4 | 0,9 | 6,3 | 0,3 |
| EXP-2026-000004 | U2 | ampliación automática | 0,0 | 0,6 | 7,7 | — |

- Firmadas en persona (4): hasta la firma 0,4 min · hasta el primer proveedor 0,9 min · hasta todos los proveedores 6,6 min.
- Ampliaciones automáticas (3): hasta la firma 0,0 min · hasta el primer proveedor 0,5 min · hasta todos los proveedores 7,4 min.

## Órdenes

fallida: 3, vencida: 30
Firmadas en persona (ord-): 17. Ampliaciones automáticas (amp-): 16.

## Descartes (no se bloquean)

- envivo.canalnorte.test (licenciatario, 3 detecciones): Retransmisión autorizada: el servidor está dentro de los dominios autorizados de Canal Norte TV (ficticio). Nunca se bloquea.
- vod.resumenes-deportivos.test (otra señal, 2 detecciones): La marca de agua LP25-F03-OFI-S102934 no corresponde a ninguna señal de este partido: no es la señal que se protege y no se bloquea.

## Reclamos

- No hubo reclamos.

## Traspasos de turno

- Minuto 50,0: de Dra. Laura Ficticia a Dr. Martín Ejemplo; ratificado por Dr. Martín Ejemplo en el minuto 50,5.

Acta generada en el minuto 110,0 (19:50:02).
