# P-07 — Arquitectura incremental de Almacén e Inventario (Book Express)

Estado: **diseño de la siguiente etapa, NO implementación ni aprobación para producción**.
Rama de trabajo: `crm/gestion-colegios`. No desplegar sin pruebas.

## 1. Contrato y límites actuales

- `purchasing`: pedido a editorial, cantidades solicitadas, costo contractual por línea, adopción y colegio.
- `warehouse/receiving.py`: recepción documental y física, faltantes, observados, adicionales, validación y eventos.
- `warehouse/inventory.py`: contabilización única por línea de recepción mediante `StockEntry.receipt_line` (OneToOne).
- `warehouse/api_views.py`: consultas de ingresos, existencias brutas y valor referencial.
- `catalog`: producto, editorial, clasificación y datos maestros. No duplicar su CRUD en almacén.

**Precisión:** `StockEntry.quantity_available` conserva el ingreso conforme histórico, no un saldo neto posterior a salidas; las vistas actuales aún no descuentan ventas, cortesías ni traslados. Los adicionales conformes están incluidos en el ingreso y valorización referencial, pero no crean deuda automática con la editorial.

## 2. Modelo objetivo de movimientos, sin reescribir recepción

### Movimientos inmutables (dominio warehouse)

Crear registros de salida/traslado vinculados a la **línea de ingreso `StockEntry`** (lote documental), al producto y al usuario. Mantener `StockEntry` como evidencia de entrada única y costos snapshot; no editar una recepción validada para contabilizar salidas.

Los movimientos de inventario deben registrar: tipo, origen/destino físico cuando proceda, cantidad positiva, condición (conforme/cuarentena), entrada origen, colegio de destino cuando aplique, operación/idempotencia, responsable, fecha, costo unitario histórico y referencia documental. Correcciones por movimientos inversos trazables, nunca borrados silenciosos.

Saldo neto por entrada = ingreso físico conforme − salidas conformes + devoluciones/reversiones aplicables; cuarentena separada. El backend, no React, decide el saldo.

No crear la tabla de movimientos con campos genéricos no validados antes de cerrar los casos de cortesía y traslado. En la primera migración de movimientos se debe mantener compatibilidad con los registros históricos.

### Cortesía a colegio

- Solo permite retirar unidades conformes realmente disponibles de un ingreso asociado al **mismo colegio** en el pedido/adopción origen; casos excepcionales requieren autorización y trazabilidad explícita.
- Registrar destinatario/función (director/a), motivo, producto, cantidad, lote/guía fuente, costo snapshot y actor. No asumir que es venta ni reemplazarla con una categoría o almacén ficticio llamado «Cortesías».
- El costo de reposición y acuerdos 50/50 con la editorial pertenecen a un flujo comercial/financiero posterior; no cambian el descuento físico del stock.
- Cada acción se confirma dentro de una transacción `transaction.atomic`, bloqueando filas disponibles con `select_for_update` y validando saldo no negativo e idempotencia.

### Ubicaciones y destinos futuros

Distinguir **almacenes físicos** (principal, tienda), **ubicaciones temporales** (ferias, consignaciones), **motivos de salida** (cortesía, devolución, venta) y **reservas por colegio**. No confundir una cortesía con un almacén físico. Los traslados mueven existencias entre ubicaciones sin alterar el total empresarial. Separar reservas del stock físico.

## 3. Secuencia sin grandes refactorizaciones

1. P-07.3: contrato y pruebas de salidas por cortesía; ledger de movimientos, permisos específicos, transacción y anti-duplicación. Sin modificar las URLs de recepción.
2. P-07.4: consulta de saldo neto real y movimientos históricos en un servicio de inventario. Mantener columnas de ingresos históricos y añadir «disponible real» solo cuando sea cierto.
3. P-07.5: ubicaciones, traspasos y reserva por colegio. Definir feria y consignación según entrega y devolución reales.
4. P-07.6: devoluciones, regularizaciones de no conformes, incidencias pendientes y alertas previas al cierre con editorial.
5. Pruebas integrales aisladas desde adopción hasta devolución/liquidación, roles y simultaneidad; desplegar únicamente después de aprobar QA.

## 4. Separación de responsabilidades al crecer

Mantener `purchasing` y `catalog` independientes. Dentro de `warehouse`, separar gradualmente `services/receiving.py`, `services/stock.py`, `services/courtesies.py`, `services/transfers.py` y `services/incidents.py` **solo cuando haya implementación y tests para cada responsabilidad**. Separar vistas, serializers y pruebas por dominio al intervenirlas; evitar directorios vacíos y cambios cosméticos masivos.

Frontend: Recepción sigue registrando y validando; Inventario consulta saldos reales y movimientos; Salidas se introducen como operación clara con confirmación React y sin formularios duplicados.

## 5. Criterios mínimos de aceptación antes de declarar P-07 cerrado

- Recibir 100, contar 102, documentar 2 adicionales, valorizar 102 como referencia y no generar deuda por los 2.
- Registrar 3 cortesías asociadas al mismo colegio y lote: saldo conforme baja de 102 a 99; otro colegio no puede usar ese lote sin autorización.
- Dos usuarios simultáneos no pueden extraer el mismo saldo por encima del disponible.
- La misma petición repetida no crea una salida duplicada; una reversión deja historial.
- Observados no salen como conformes; faltantes frente a guía generan incidencia sin ingreso de stock.
- Traslado no cambia el stock total empresarial; reposición sí ingresa nueva existencia documentada.
- Pruebas con base temporal, lint/build frontend, permisos por rol y escenarios de punta a punta.
- Acompañar las pruebas de una evaluación de rendimiento (consultas, índices, paginación) antes de declarar escalabilidad.

No es evidencia de pruebas ejecutadas ni autorización para modificar producción.
