# B6 | Contrato propuesto para vincular ventas y cerrar una distribución

Estado: propuesta de integración. No crea ventas, movimientos, cierres, cuentas por cobrar ni comprobantes.

## Reglas conservadas

- BE-RC acredita unidades físicamente recibidas. BE-RI prepara un retorno. Los dos documentos conservan su historia.
- Una diferencia o hallazgo de B5.4 es evidencia para revisión; no mueve libros ni acredita ventas.
- «Sin retorno registrado» no es «vendido». Una feria no se cierra por llegar a su fecha de término.
- Consignación mantiene separados unidades vendidas, saldo de libros, rendiciones, comprobantes y abonos.
- La ubicación física efectiva importa: no retornar automáticamente todos los sobrantes a Principal si quedaron en tienda.

## Integración mínima recomendada

1. **Origen verificable.** Ventas o un adaptador autorizado entrega registros confirmados, no correos, notas de conteo ni saldos calculados. Cada línea debe indicar sistema y referencia únicos, identidad de la operación de distribución, línea del lote de entrega, cantidad neta de unidades y estado; anulaciones/devoluciones deben estar vinculadas al evento original. Mantener producto, ubicación y documento/fecha de origen para validación y auditoría.
2. **Asignación explícita.** El lote debe corresponder a la distribución y al producto. Si un registro solo trae un SKU que aparece en varios lotes, exigir asignación verificable; no atribuirlo automáticamente por precio, por resto ni al primer lote.
3. **No duplicar stock.** Definir un solo dueño del movimiento de venta. La conciliación consume la evidencia comercial y su referencia de stock; no vuelve a descontar lo que ya descontó Ventas.
4. **Revisión por lote.** Mostrar entregado, vendido verificable, devuelto físicamente, custodia remanente documentada y diferencias aprobadas, por separado. Impedir sumar dos veces una misma unidad. Un hallazgo reduce lo aún investigado en su observación, pero no sustituye una devolución ni una aprobación.
5. **Cierre con revisión.** Fallar de forma segura cuando la fuente no esté disponible, falte un lote, se supere lo entregado o quede una diferencia sin resolver. Configurar los permisos de aprobación y el procedimiento posterior para correcciones antes de activar el cierre. Separar el cierre logístico de la liquidación financiera de consignación.

## Ejemplos para aprobación de negocio

| Escenario DEMO | Resultado esperado |
|---|---|
| 15 entregados, 5 devueltos, 10 sin retorno y sin fuente de ventas | 5 confirmados en BE-RC, venta desconocida, no cerrar. |
| 15 entregados, 5 devueltos, 8 ventas verificadas y 2 físicamente en tienda | Mostrar 2 en custodia real; no marcarlos vendidos ni moverlos a Principal. Confirmar cuándo permite cerrar cada modalidad. |
| Registro de venta duplicado o anulado | Reintentar el mismo registro no cambia totales; una anulación válida revierte el neto y se audita. |
| Diferencia de 2 y hallazgo de 1 | Queda 1 por revisar; no incrementa stock por sí mismo. |
| Cantidad compra/venta por ISBN, sin lote identificable | Dejar pendiente de vincular y bloquear cierre. |
| Usuario de almacén sin autorización de cierre | Puede consultar según sus permisos; no puede aprobar ni cerrar. |

Decisiones necesarias: sistema de origen para el primer lanzamiento (módulo Ventas o exportación verificable), datos disponibles para identificar feria/colegio y lote, rol que aprueba por modalidad y tratamiento de unidades que continúan en custodia. No implementar cierre definitivo ni reabrir etapas ya aprobadas hasta resolver estas decisiones.
