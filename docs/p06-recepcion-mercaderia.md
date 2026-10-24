# P-06 — Recepción de Mercadería (base de backend)

Estado: **55 pruebas de warehouse y purchasing aprobadas en el entorno local del usuario el 24/10/2026, antes de las ampliaciones de API/edición y frontend de esta sesión**. Las nuevas pruebas y rutas añadidas después requieren volver a ejecutarse. No desplegar ni migrar en producción.

## Fuentes y alcance
- Documento de proyecto: `01_Levantamiento_Funcional_ERP_Book_Express_v2_FINAL1.docx`, apartado 9.1 (Recepción e ingreso de mercadería), 9.2 (Almacenamiento) y 10.2 (Cuentas por pagar).
- El apartado 9.1 del DOCX está redactado como cuestionario, sin respuestas observadas. No asumir que las políticas de excepciones, documentos o autorizaciones ya están confirmadas.
- Se usan también reglas conversadas: Santillana puede entregar 80 de 100 unidades; otras editoriales también hacen entregas parciales. Todas las editoriales con las que trabaja Book Express aceptan devoluciones, pero el cálculo financiero dependerá de contratos, comprobantes y conciliación.

## Separación de responsabilidades
- CRM: adopción confirmada por colegio.
- Pedidos: cantidad solicitada, costo editorial histórico, aprobación, correo y constancia de envío. La ruta técnica `/api/admin/erp/compras/` se conserva por compatibilidad. La interfaz se denomina «ERP · Pedidos».
- Almacén / Recepción: documento del proveedor, fecha, cantidad llegada, aceptada y observada; saldo pendiente por cada línea original de pedido. Puede agrupar líneas de diferentes pedidos de una misma editorial en una guía.
- Inventario futuro: fuente única de movimientos de stock, física y operacional. **Validar recepción no crea automáticamente stock** mientras no exista el módulo de movimientos idempotentes.
- Finanzas: facturas, liquidaciones, notas de crédito, devoluciones y pagos de proveedores; no se infiere monto de obligación de recepción ni de pedido.

## Contrato backend inicial
Entidad `warehouse.GoodsReceipt`: editorial, documento, fecha, estado (borrador/validada), usuario creador y validador, eventos.
Entidad `warehouse.GoodsReceiptLine`: línea de pedido, cantidad llegada, aceptada y observada. Llegada = aceptada + observada; cantidad aceptada acumulada de recepciones validadas no excede cantidad solicitada.
Endpoints autenticados bajo `/api/admin/erp/almacen/recepciones/`:
- `GET /, GET /{id}/`: registros, sin datos financieros.
- `POST /crear/`: registrar borrador con una o varias líneas de pedidos enviados de una sola editorial.
- `POST /{id}/validar/`: validación transaccional y auditada.
- `GET /saldos/?pedido={id}`: solicitadas, aceptadas y pendientes para cada producto de un pedido.

Permisos funcionales: `warehouse.view_receiving`, `warehouse.manage_receiving`, `warehouse.validate_receiving`. ADMINISTRADOR habilitado según permisos existentes; asignar ALMACEN por rol solo después de contrastar MOF real. El frontend operativo aún está pendiente.

## Controles técnicos
- Validación bajo `transaction.atomic`; `select_for_update` para bloquear recepción y pedidos antes de conciliar acumulados.
- Impide segunda validación de una recepción; impide duplicar la misma guía de remisión por editorial.
- Restricción de base de datos: cantidad llegada = cantidad aceptada + cantidad observada; protege incluso escrituras que evadan la interfaz.
- No acepta líneas que no pertenezcan a la editorial ni pedidos sin constancia de envío.
- Admite entregas múltiples sin alterar el pedido original.
- El estado del pedido cambia a recepción parcial o completa según aceptación acumulada; no se actualiza stock.

## Validación local obligatoria
```bash
git pull --ff-only origin crm/gestion-colegios
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test warehouse purchasing
```
Si las pruebas pasan, para inspeccionar y aplicar migración únicamente en base de desarrollo:
```bash
python manage.py showmigrations warehouse
python manage.py migrate warehouse
```

## Nuevas capacidades incorporadas después de las 55 pruebas iniciales
- `GET /api/admin/erp/almacen/recepciones/pedidos-pendientes/`: listado paginado de órdenes enviadas con saldo por producto, sin costos de editorial.
- `POST /api/admin/erp/almacen/recepciones/{id}/actualizar/`: edición completa transaccional de un borrador, con historial.
- Interfaz React `/admin/erp/almacen/recepciones`: seleccionar editorial y pedidos, ingresar datos del documento y las cantidades llegadas, observadas y aceptadas, guardar/editar borradores y validarlos. Puede reunir varios colegios de la misma editorial bajo una recepción documental.
- En el menú, `ERP · Pedidos` y `Almacén · Recepción` separados. Rutas técnicas de pedidos intactas.
- En Pedidos, los estados de recepción parcial/completa siguen visibles tras validar entregas.
- Los usuarios con permiso `warehouse.view_receiving` pueden acceder al panel por su ruta; no hace falta permiso de `purchasing.view_purchasing` para ver saldos.

## Registro de facturas del proveedor — dominio futuro de Finanzas
- No confundir documento físico de entrega con registro contable.
- Futuro submódulo `Finanzas > Facturas de proveedores`: RUC del emisor, tipo, serie, correlativo, fechas emisión/vencimiento, moneda, importes e impuestos, referencias a proveedor, guías, órdenes y condiciones comerciales; vínculo con notas de crédito, devoluciones, conciliación y pagos.
- Validar la correspondencia documental y comercial por editorial; una factura puede relacionarse con múltiples guías/órdenes, y una orden con múltiples entregas/facturas.
- La opción `Factura (referencia física)` en P-06 NO registra cuentas por pagar, IGV, costos contables ni obligación tributaria.

## Pendientes antes de declarar P-06 terminado
1. Validar localmente las nuevas rutas y pantalla React mediante pruebas backend, `npm run lint`, `npm run build` y prueba manual de guía real o de prueba; completar prueba desde el navegador con recepción parcial y segunda entrega.
2. Definir con evidencia real qué guías y documentos acompañan cada entrega y cómo registrar diferencias, paquetes incompletos, material de muestra, donaciones y devoluciones.
3. Integrar Inventario con movimientos inmutables e idempotentes al validar recepción; no duplicar existencia por reintentos.
4. Pruebas negativas y de concurrencia en PostgreSQL real, y tests de permisos por ALMACEN, administrador y otros roles.
5. Pruebas integrales CRM → Pedidos → Recepción → Inventario → Ventas → Devoluciones → Liquidación, antes del paso a main y producción.
6. Revisión de paginación y límite silencioso de 200 adopciones en listado de Pedidos antes de campaña.
