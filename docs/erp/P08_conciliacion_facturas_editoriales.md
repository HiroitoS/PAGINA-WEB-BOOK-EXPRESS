# P-08 — Facturas de editoriales y conciliación de compras (diseño, no implementado)

Estado: **requerimiento identificado para módulo Administrativo/Compras y Cuentas por Pagar**.
Este documento no crea facturas, asientos contables ni movimientos de stock.

## Decisión operativa

- **Almacén** registra recepción física, usando la guía de remisión u otro documento
  de traslado válido que acompaña la mercadería, incluyendo el caso de una entrega
  sustentada con factura. Cuenta físicamente, observa daños, registra faltantes y
  valida. Esta acción genera **una sola entrada física** por línea de recepción.
- **Administración/Compras** recibe y verifica factura electrónica de proveedor,
  registra fecha, serie-número, RUC, importes, IGV/afectación aplicable,
  vencimiento, moneda y archivos XML/PDF si existen y se dispone de ellos;
  vincula el comprobante a pedido(s) y recepción(es); NO incrementa stock.
- **Tesorería/Cuentas por pagar** programa pagos según facturas conformes y
  reglas de aprobación. Contabilidad controla Registro de Compras, CPE y notas
  de crédito conforme a SUNAT/SIRE. La cuenta por pagar no se deduce únicamente
  de lo recibido físicamente.

## Reconciliación de tres vías: pedido ↔ recepción ↔ factura

No hay correspondencia obligatoria 1:1.
Una factura puede cubrir varias guías o pedidos del mismo proveedor;
una guía puede estar vinculada a varias facturas parciales. La conciliación se
registra **por línea de producto, cantidad e importe**, nunca solo por cabecera.
Evitar relacionar solo por nombre comercial o monto aproximado; exigir identificador
de proveedor, documento, producto y cantidades, y permitir revisión manual.

Claves sugeridas:
- `SupplierInvoice` con `provider`, `supplier_ruc`, tipo comprobante,
  serie y número normalizados, fecha de emisión, moneda, bases/impuestos/totales,
  estado administrativo, vencimiento, archivo/huella e historial de auditoría.
  Unicidad por proveedor + tipo + serie + número (revisar requisitos fiscales).
- `SupplierInvoiceLine` con producto, unidad, cantidades facturadas,
  costo unitario, descuentos e impuestos (sin redondeos en frontend).
- `InvoiceReceiptAllocation` tabla de conciliación por línea de factura
  y línea de recepción; suma de asignaciones no puede exceder límites
  aprobados. Admitir una factura pendiente de entrega física y una
  recepción pendiente de factura.
- `CreditNote` o ajuste documental referenciado a factura para resolver
  diferencias con autorización, sin borrar factura original.

## Estados UX propuestos

- Recepción: «Recibido físicamente, sin factura», «Con factura vinculada»,
  «Con incidencias por atender».
- Factura: «Pendiente de asociar», «Conciliada», «Con diferencias»,
  «En revisión administrativa», «Aprobada para pago».
- Liquidación: alertar antes de aprobar pagos cuando hay faltantes,
  observados, devoluciones o reposiciones pendientes; el tratamiento contable
  de cada diferencia debe aprobarse por Administración/Contabilidad.

## Principios de integridad

1. Factura y guía jamás crean dos ingresos por la misma entrega.
2. Recepción validada y comprobante registrado conservan trazabilidad separada;
   una nota de crédito no reescribe un movimiento de mercadería.
3. Adicionales físicos a favor de Book Express no se incluyen automáticamente
   como deuda a la editorial. Evaluar tratamiento contable con responsable fiscal.
4. Permisos: almacén valida conteo; administración registra factura;
   contabilidad verifica su tratamiento; quien aprueba pagos debe tener autorización
   separada y evidencia.
5. Si la editorial entrega directamente con factura válida como soporte del
   movimiento, Almacén registra el conteo físico una vez, y Administración
   registra la obligación financiera vinculada al documento. No existe
   duplicación de stock.
6. Diseñar futuras integraciones con CPE/SIRE como validaciones y conciliación;
   no afirmar sincronización automática con SUNAT antes de implementarla.

## Casos QA previos a desarrollo

- Dos guías parciales vinculadas a una factura, sin doble stock.
- Una guía y dos facturas parciales, sin duplicar deuda.
- Factura de 100 unidades con entrega de 98 y faltante de 2.
- Daños con reposición posterior y devolución del dañado.
- Entrega solo con factura como documento acompañante.
- Diferencia de precio o descuento factura versus orden aprobada.
- Registro repetido de misma factura proveedor/tipo/serie/número.
- Abonos, notas de crédito y factura con pago parcial.

Implementación futura: después del MVP de salidas por cortesía y definición de
ubicaciones de almacén. No activar pagos ni contabilización solo con este diseño.
