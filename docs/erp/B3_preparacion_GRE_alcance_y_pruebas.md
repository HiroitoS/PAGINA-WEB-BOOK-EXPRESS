# Book Express · ERP Almacén B3 y preparación documental GRE

**Fecha:** 16/11/2026 · **Estado:** implementación parcial B3 en rama de pruebas. **No autoriza ni emite traslados SUNAT.** No hacer merge a main ni desplegar a Tecnoweb hasta cerrar pruebas y regularizar documentación.

## 1. Dos documentos diferentes

- **Recepción de editorial:** se conserva el pedido de compra y el documento del proveedor con cantidades declaradas, físicas y conformes. Solo la recepción validada genera `StockEntry` y saldo por ubicación. La guía del proveedor **no** sustituye una guía que Book Express deba emitir para una salida posterior.
- **Salida de Book Express:** requiere una operación con motivo real, origen, destino, productos, cantidades, transporte y responsable. Según circunstancias puede exigir GRE remitente y, con transportista externo, GRE transportista. Debe distinguirse **guía fiscal aceptada** de **constancia/orden interna**.

## 2. Qué incorporamos ahora a B3

- `DistributionOperation.status`: `planned → reserved → prepared`, además de `cancelled`. Los estados adicionales **no** representan transporte ni salida de libros.
- `DistributionStockReservation` identifica operación, lote de ingreso, almacén de salida, cantidad, responsable de reserva y conteo físico. Es una separación de stock de acceso exclusivo: las existencias **totales** no cambian.
- `warehouse/distribution_preparation.py`: GET disponibilidad por producto y lote del **mismo colegio**, cálculo de saldos reales y reservas previas; reserva transaccional y FIFO entre lotes conformes por ID, con bloqueo de `StockEntry` (PostgreSQL) y rollback si falta un producto. Luego confirmación de conteo físico por cada reserva; las diferencias impiden pasar a `prepared`.
- Los traslados directos y las cortesías posteriores comprueban saldo físico **menos reservas activas**; no pueden consumir unidades ya comprometidas. La anulación de una entrega solo reservada libera las cantidades y registra evento. Una entrega ya marcada Preparada requiere reversión física supervisada (pendiente B4): se impide anularla directamente para no dejar cajas preparadas como stock libre.
- Estados `reserved` / `prepared` continúan consumiendo el presupuesto **comercial** de la adopción para evitar planificar nuevamente lo adoptado.
- La operación planificada B2 **no** reserva al guardarse. Solo la acción explícita «Reservar existencias» lo hace. El conteo se escribe físicamente, no se autocompleta.
- La fuente de lotes se limita por `order.school_id` y producto: **no sustituir libremente mercadería de otro colegio ni su guía**. Reglas para stock compartido/no asignado, packs y otros casos requerirán modelo separado.

## 3. Pre-captura de datos para SUNAT (sin envío)

El formulario «Datos del traslado» registra borrador `DistributionTransportDraft` ligado a la operación de distribución: RUC remitente, direcciones reales, destinatario/identificación, fecha de salida, motivo propuesto, transporte privado/público, vehículo/conductor o RUC de transportista, peso bruto y notas.

La API `GET/PUT .../operaciones-distribucion/{id}/documento-traslado/` guarda exclusivamente estos **datos preparatorios**. No genera series/números GRE, no invoca API SUNAT, no firma XML, no consulta tickets/CDR y **siempre informa `sunat_issued=false`, `sunat_accepted=false`**. La bandera `data_complete_for_review` significa **solo** que el conjunto mínimo de campos internos está presente, nunca conformidad tributaria. Los datos reales varían con modalidad, destinatario, punto geográfico, motivo y vehículo.

**No usar «Otro documento», un PDF interno o un registro en B3 para reemplazar la GRE exigible.** Para transporte real, evaluar documentalmente y emitir/vincular GRE conforme a las disposiciones vigentes con la SUNAT, conservando autorización/QR/CDR. En la futura B4 el despacho deberá bloquearse cuando el documento exigible no esté aceptado, salvo excepción legal verificada y registrada; **B4 no está activada**.

## 4. Verificación oficial consultada el 16/11/2026

- SUNAT / CPE: [Tipos de guía y supuestos](https://cpe.sunat.gob.pe/node/114), [Sistema de emisión y condición de CDR](https://cpe.sunat.gob.pe/node/116), [Motivos de traslado y Catálogo 20](https://cpe.sunat.gob.pe/node/171).
- SUNAT: [GRE remitente, transportista y por evento](https://cpe.sunat.gob.pe/landing/guia-de-remision-electronica-gre).
- SUNAT: [Actualización normativa 108-2026](https://cpe.sunat.gob.pe/node/117), vigente desde el 01/06/2026; verificar modificaciones y casos particulares antes de emitir.
- Documentación técnica futura: [Servicios GRE y autenticación](https://cpe.sunat.gob.pe/node/116). Las reglas de validación SUNAT se actualizan; revisar versión publicada **antes de integrar el API**.

Para la emisión desde los propios sistemas, normalmente se requiere acceso/autorización SUNAT, credenciales SOL/API, certificado digital, construcción XML/UBL conforme a versiones vigentes, token, envío, ticket, CDR y almacenamiento seguro. **No almacenar claves SOL o tokens en frontend ni en repositorio GitHub.**

## 5. Ejecución local antes de registrar más movimientos

En backend/frontend `git status` y `git pull --ff-only origin feature/erp-p08-traslados-por-guia`. Respaldar **solo base local** y verificar `python manage.py migrate --plan`; aplicar la migración **0016** en desarrollo. Luego:

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test warehouse.test_distribution_preparation warehouse.test_distribution warehouse.test_transfers
```

Frontend:

```bash
npm run lint
npm run build
```

En pantalla: `Movimientos → Entregas → Detalle → Preparación de esta entrega`. No tocar la operación del traslado histórico `BE-TI-000003`; crear **otra planificación de prueba** dentro de una adopción con saldo libre real, verificar lotes/escasez, pulsar Reservar, comprobar inventario global igual, probar que traslado/cortesía no pueda consumir más del libre, ingresar conteo y confirmar preparación. Verificar la documentación como **borrador no GRE**, motivos/direcciones reales solo si se trata de un traslado real y autorizado.

## 6. Pendientes necesarios antes de cerrar Almacén

- B3 ampliado: pruebas locales de la selección manual de lotes ya implementada; discrepancias de picking y correcciones auditadas, responsable de preparación, bultos y etiquetado; pack específico sin doble stock; reserva por custodia de feria y por operación real, no solo por colegio.
- B4: definición y aprobación de despacho, enlace uno-a-uno/por lote con reservas, documento tributario aceptado cuando corresponda, envío, tránsito, recepción en destino, diferencias y vínculo auditable a `StockTransfer`. Nunca volver a realizar manualmente el movimiento para una entrega que ya lo generó.
- Consolidación de solicitudes internas existentes para que no creen una segunda planificación; destinos concretos por feria/consignación; retornos y liquidación por colegio.
- Revisión contable/tributaria real por asesor, condiciones SUNAT y datos de Book Express antes de integrar un emisor definitivo.

**Política:** el traslado manual existente solo debe usarse para movimientos físicos ya consumados y documentados correctamente. Preparar o reservar nunca cambia ubicación ni acredita envío.

## 7. Avance B3.1 (17/11/2026): elección de lotes/guías para reservar

**Alcance en rama de pruebas:** el encargado puede mantener la reserva automática FIFO (comportamiento anterior) o elegir manualmente la guía de recepción y la cantidad de cada libro. El nuevo campo opcional de `POST /operaciones-distribucion/{id}/reservar/` es `lots: [{stock_entry_id, quantity}]`. Si no se envía `lots`, la reserva sigue siendo automática. No se cambian rutas, permisos ni estructura de base de datos.

**Validaciones del servidor, aun si se elude la interfaz:** los lotes deben pertenecer al **mismo colegio y producto de la entrega**, estar disponibles en el almacén de salida y tener saldo conforme libre tras restar traslados/cortesías/reservas activas. Se rechazan IDs duplicados, cantidades no positivas, sobreasignación, selección parcial del producto y lotes ajenos. La reserva ocurre dentro de una transacción con bloqueo; cualquier error revierte todos los cambios. Reintentar una operación ya reservada no duplica líneas de inventario ni reservas.

**Interfaz:** en «Preparación de esta entrega», seleccionar «Automáticamente, por orden de recepción» o «Elegir guía y cantidades». En modo manual aparece un campo numérico por lote disponible y el contador «Seleccionadas X de Y» por producto. El botón de reserva solo se habilita con sumas exactas. La confirmación del conteo físico continúa siendo obligatoria y separada.

**Prueba guiada sin modificar recepciones históricas:**
1. En rama `feature/erp-p08-traslados-por-guia` actualizar backend/frontend, respaldar BD local, revisar migraciones y pasar CI/local.
2. Crear una planificación **nueva de prueba** con adopción confirmada y unidades libres verificadas en inventario. Abrir «Preparación de esta entrega».
3. Alternar modo FIFO/manual; seleccionar guía(s) y cantidades que sumen exactamente lo planificado. Comprobar que cantidades insuficientes bloquean reserva en interfaz **y API**.
4. Reservar; verificar las guías en las líneas de reserva, que la cantidad disponible baja sin alterar saldo físico/global ni crear `StockTransfer`. Repetir la petición: sin duplicados.
5. Probar manualmente una reserva de otra entrega que compita por el mismo lote: debe impedir usar lo ya reservado. Verificar confirmación del conteo correcto, que no se genera GRE ni despacho ni venta.

**Pendiente:** una evidencia del usuario en entorno local para cerrar la prueba de la recepción Santillana N.° 6; registrar discrepancias reales de picking con corrección auditada y responsable, bultos/etiquetas, packs y despacho B4. No aplicar en producción ni considerar el flujo logístico cerrado por esta mejora.

## 8. Mejora B3.1b — stock menor que la planificación: separación en dos entregas (17/11/2026)

**Problema real de prueba:** ANDINO / LECTOPOLIS 4 tiene **20 planificados**, y el inventario por almacén confirma **15 conformes libres en Principal, 5 observados no vendibles**. La reserva original era íntegra: `can_reserve=false` si faltaba siquiera un libro. Era correcto no reservar 20 sin 20 disponibles, pero la UX era confusa al bloquear también la posibilidad de aprovechar los 15.

**Solución de negocio:** no crear stock ni forzar una reserva de 20. El usuario autorizado puede ejecutar **«Reservar 15 y dejar 5 pendientes»**, con confirmación de impacto. El backend bloquea la adopción, la planificación y los lotes; recalcula saldos reales; divide la entrega de 20 en **una entrega A de 15 (reservada, pendiente de conteo físico)** y **una entrega B de 5 (por preparar, sin fecha programada)**. Las cantidades comerciales por adopción siguen sumando 20. Se conserva el colegio, editorial, producto, origen/destino, trazabilidad de guía, responsable e historial de separación. **No hay movimiento de inventario, GRE emitida, venta ni despacho**. Las cinco observadas permanecen separadas.

**Reglas importantes:** la operación solo permite dividir si existe algún stock conforme disponible **y** un faltante real. Si no hay stock, se espera reposición; si está todo disponible, se usa la reserva normal. La reserva de A usa FIFO y queda protegida contra uso duplicado en otra entrega. Jefatura/Almacén debe realizar conteo real antes de declararla `prepared`. El resto puede planificarse al llegar mercadería nueva. Operación transaccional con `idempotency_key`: un reintento no crea múltiples pendientes. La interfaz explica que se crearán dos entregas antes de confirmar.

**Flujo ilustrado para jefatura:**
```
Adopción 20 libros → Recepción: 15 conformes + 5 observados
   → Planificación inicial: 20 a Feria
   → Reserva total bloqueada (no hay 20 conformes)
   → Separación aprobada por operador: Entrega A 15 + Entrega B 5 pendiente
   → Reserva A 15 (sigue en Principal) → Conteo A 15 → Preparación A
   → B4 futuro: documentación, despacho, tránsito y recepción real en Feria
   → B pendiente se atiende después de subsanar faltante y recibir stock conforme
```

**Pruebas:** `warehouse/test_distribution_preparation.py` cubre split por disponibilidad, conservación de cantidad total, cero movimientos nuevos, rechazo cuando no hay faltante o no hay stock, bloqueo de edición tras reserva, e idempotencia de reintentos. Falta verificación de CI y prueba local antes de considerarlo aprobado para demo. No hay nueva migración en esta mejora.

**Alcance que NO debe perderse:** B3.2 Feria con identidad física/subalmacén propio, B3.3 packs termosellados por colegio (sin SKU ni stock adicional), B4 GRE/despacho y B5 devoluciones diferenciadas. **No llevar a main ni Tecnoweb todavía.**
