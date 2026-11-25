# Book Express — B3/B4: subalmacenes, ferias y documentación de traslado

**Revisión:** 18/11/2026. **Estado:** B3.2 alta y consulta de feria específica implementadas en rama de desarrollo, pendientes de prueba local. **NO es emisión SUNAT ni autorización de despacho.**

## 1. Punto exacto del flujo

`Adopción → Pedido editorial → Recepción validada → Stock por lote y ubicación → Planificación (B2) → Reserva de existencias (B3) → Conteo/preparación (B3) → Despacho y GRE cuando corresponda (B4) → En tránsito → Recepción destino → Venta / liquidación / retorno`.

- En la prueba local, la entrega Feria del colegio `[PRUEBA ERP] ANDINO · 2027` pasó de 20 LECTOPOLIS 4 a **15 reservados y preparados** y **5 pendientes** mediante división auditada. La guía Santillana `T001-12358` conserva **15 conformes y 5 observados**. Preparación NO equivale a despacho: todavía no salió inventario de Principal. La planificación anterior con destino genérico `ALMACEN FERIA` sigue como dato histórico y no se convierte automáticamente al nuevo evento.
- La pestaña **1. Existencias, reserva y conteo** reserva unidades del stock por colegio/lote/ubicación y exige conteo físico antes de marcar preparada. La pestaña **2. Coordinación del traslado (opcional)** guarda datos conocidos, sin exigir vehículo ni transportista para preparar, y no altera inventario.
- La selección de lotes B3 permite FIFO automático o elección manual de guía y cantidades sin inventar stocks.

## 2. Ubicaciones y subalmacenes: separación arquitectónica

Un `WarehouseLocation` actual tiene nombre, tipo (principal/tienda/feria/consignación/otro), dirección opcional y estado. Es una **ubicación de custodia interna**. Su creación no incorpora libros y su descripción no prueba por sí misma el domicilio SUNAT.

**B3.2 implementado en rama (sin prueba visual local ni despliegue):** `WarehouseFairEvent` representa una feria concreta con nombre, recinto, dirección, fechas y custodio. Cada evento crea en una única transacción su `WarehouseLocation(kind=fair)` individual, identificada por código interno. La API `GET/POST /api/admin/erp/almacen/ferias/` usa permisos existentes, validación de fechas, token idempotente y protección contra alteraciones desde el formulario genérico. La interfaz en Ubicaciones permite registrar, consultar y elegir luego esa feria como destino al planificar. **No crea stock, no asigna lotes ni genera movimientos.**

**Modelo objetivo B3.3/B4 pendiente:**

- **Almacén principal:** centro físico de resguardo; ingreso de libros conformes cuando la recepción está validada.
- **Tienda/librería:** lugar fijo; su stock se origina solo en movimientos reales recibidos.
- **Subalmacén de feria:** **evento específico**, no un depósito genérico compartido. Una entidad `FeriaEvento` o equivalente debe representar nombre real, fechas, colegio(s) atendido(s), recinto/dirección de atención, responsable, estado de apertura/cierre y una relación de custodia a una ubicación de stock. Diferentes ferias simultáneas no pueden mezclar saldos; la misma feria puede recibir libros de varias adopciones con trazabilidad original por guía, colegio y lote.
- **Consignación:** custodia por colegio/consignatario y operación; no mezclar devoluciones de colegios ni tratarlas como ventas hasta la liquidación.
- **Sububicación física (pasillo/anaquel):** futura capa opcional dentro de una ubicación de custodia; por sí misma no altera el stock ni es punto de llegada de una GRE.
- **Valorización:** preservar costo histórico por `StockEntry`; movimientos internos origen -N / destino +N, global invariable; traslados en tránsito deben tener tratamiento explícito, nunca presumir recepción inmediata.

**Requisitos pendientes:** verificar visualmente la creación de evento y la planificación con destino nuevo; implementar apertura/cierre auditados, despacho y recepción por evento, saldo real por feria, arqueo y conciliación de ventas/retornos. No renombrar la ubicación histórica `ALMACEN FERIA` esperando que represente eventos distintos.

## 3. SUNAT: separación indispensable

- **Modalidad comercial** (Feria, Punto de venta o Consignación) no equivale necesariamente al **motivo de traslado de la GRE**. Para feria puede evaluarse «traslado por emisor itinerante» u otro motivo según el hecho real y criterio tributario; **nunca seleccionar automáticamente** «traslado entre establecimientos» por elegir Feria.
- **Ubicación interna** no es sinónimo de establecimiento anexo declarado a SUNAT. El punto de partida/llegada debe reflejar las direcciones físicas reales. Un recinto temporal de feria no se presume local propio inscrito.
- Separar transporte privado y público; capturar vehículo/conductor o transportista según corresponda. La futura emisión deberá contemplar GRE remitente y, en el caso aplicable, GRE transportista, además de documento, serie/número, autorización/estado, CDR, PDF/QR y auditable vínculo con el despacho.
- **El borrador actual no emite GRE ni invoca servicios SUNAT.** `data_complete_for_review` es solo un prechequeo de campos internos y no autoriza circulación. **No permitir despacho con documento exigible sin condición fiscal aceptada verificada** (con excepciones legales expresamente sustentadas por quien corresponda).
- No guardar SOL, certificados privados, credenciales ni tokens en frontend o código fuente.

**Fuentes oficiales revisadas 17/11/2026:**
- https://cpe.sunat.gob.pe/landing/guia-de-remision-electronica-gre
- https://cpe.sunat.gob.pe/node/114
- https://cpe.sunat.gob.pe/node/171
- https://cpe.sunat.gob.pe/node/116 (incluye reglas de validación publicadas 06/11/2026)
- https://orientacion.sunat.gob.pe/guia-de-remision-electronica-modelo-general

Antes de implementar integración: revisión conjunta con contabilidad/asesor tributario del traslado real de feria, del establecimiento y de las reglas vigentes.

## 4. Packs y devoluciones siguen pendientes (NO perder de vista)

**Packs:** Santillana puede entregar paquetes termosellados con etiqueta de colegio y facturación por los libros componentes. El futuro pack es una **unidad logística**, con componentes individuales ya registrados, trazabilidad por colegio/adopción, estado sellado/abierto, auditoría de manipulación, armado y devolución, **sin crear stock duplicado ni SKU de venta ficticio**.

**Retornos/devoluciones:**
1. Feria → inventario: conteo al cerrar feria, conciliar ventas y sobrantes, inspección de vendibles/observados y movimiento supervisado.
2. Consignación → almacén: conciliación por colegio de vendido, no vendido, cobrado y devuelto.
3. Cliente → almacén: validación documental/comercial, inspección y aceptación o rechazo.
4. Almacén → editorial: reclamo, autorización, devolución física documentada, y eventual nota de crédito/ajuste comercial mediante Administración.

Nunca usar nueva recepción de compra para reingresar mercancía retornada ni traslado directo como sustituto del despacho y recepción pendiente.

## 5. Hoja de ruta sin repetir pruebas ya concluidas

| Hito | Estado | Siguiente aceptación |
|---|---|---|
| B2 Edición Feria `[PRUEBA ERP] ANDINO` | Confirmada visualmente guardada en estado «Por preparar» | No modificar esta planificación durante pruebas documentales |
| B3.1 Guía/lotes, reserva y conteo | Implementado en rama, pruebas funcionales locales parciales | Ver stock real; si 20 planificados > libres, mantener botón bloqueado |
| B3.2 Feria específica/subalmacén | Alta/consulta implementadas en rama | Probar evento real o DEMO identificado, ver subalmacén independiente con saldo 0; sin despacho |
| B3.3 Packs/packing y discrepancias | Pendiente | Conteo, etiquetas y componentes sin doble stock |
| B4 GRE + despacho + tránsito + recepción | Pendiente | Documento tributario cuando corresponda; movimiento físico único, sin doble entrada |
| B5 Devoluciones y liquidaciones | Pendiente | Retorno por origen, inspección, aprobación y ajuste auditable |

**Norma de despliegue:** los cambios actuales son exclusivamente para `feature/erp-p08-traslados-por-guia`, sin merge a `main` ni publicación Tecnoweb hasta comprobación local, autorización y revisión fiscal.
