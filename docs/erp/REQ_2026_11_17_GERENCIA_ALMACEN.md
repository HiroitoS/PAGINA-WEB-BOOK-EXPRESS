# Acta funcional y técnica — Requerimiento de Gerencia 17/11/2026

**Fuente:** documento entregado por usuario «Requerimiento 17-11-2026.docx» (2 páginas). Esta acta registra implementación en rama de pruebas, no una aprobación de producción. No inventar correos ni direcciones.

## Decisión funcional

1. **Libros dañados, incorrectos y faltantes:** la recepción ya separaba lo físico conforme y observado. Se incorporan `ReceivingEvidence`, adjuntos privados JPG/PNG/WEBP/PDF con descripción, producto, tipo, responsable y fecha, gestionados en `ERP → Almacén → Recepción → Recepciones registradas → Incidencias, evidencias y comunicación`. Los adjuntos se almacenan fuera de la carpeta `media/` pública. Se autentica y autoriza la descarga. Informe a editorial generado desde la guía y diferencias, incluyendo referencias de evidencias.
2. **Separación de funciones:** `ALMACEN` consulta y registra/edita borradores; solicita aprobación; `JEFE_ALMACEN` consulta, devuelve con motivo o valida. Solo la validación crea las entradas de stock. El actor normal NO puede aprobar su propia recepción aunque posea ambos permisos. Superusuarios conservan una excepción para regularización de borradores históricos y tests existentes. Registrar `submitted` y `returned` en historial. Refrescar sesión tras modificar roles.
3. **Saldos pendientes:** botón «Generar seguimiento de saldos pendientes» para pedidos ya enviados/recibidos parcialmente, con cantidades solicitadas, validadas y pendientes. Esto NO llama «pérdida en transporte» a una entrega parcial; si el pedido aún no ha sido enviado, corresponde al área de Compras, no a una reclamación a la editorial.
4. **Avisos:** al solicitar aprobación se notifica a jefatura; al validar se avisa a usuarios con permisos en Almacén/Compras y al asesor responsable de adopciones relacionadas. Diferencias producen aviso destacado. En Inventario se presentan novedades de los últimos siete días y recepciones pendientes de aprobación. Notificaciones internas se guardan con clave deduplicada para no duplicar; correos automáticos **solo** si administrador configuró SMTP real y `ERP_WAREHOUSE_EMAIL_ALERTS_ENABLED=true`. Por defecto no se envían correos.
5. **Filtros desplegables:** consolidado permite combinar Editorial, Colegio de origen, búsqueda y agrupación por editorial/colegio/almacén. Opciones provienen de lotes ingresados y no de una página parcial. El colegio identifica procedencia, no tenencia exclusiva.

## Correo al proveedor

`GET /api/admin/erp/almacen/recepciones/{id}/reporte-editorial/`: vista previa de asunto, texto y adjuntos. Solo reporta diferencias de la recepción que se puedan verificar, no saldos comerciales de futuras entregas.

`POST /api/admin/erp/almacen/recepciones/{id}/reporte-editorial/`: **solo** jefe autorizado, recepción aprobada, destinatario escrito y confirmado por usuario, UUID de envío y evidencias disponibles. Si no está configurado `ERP_WAREHOUSE_SUPPLIER_EMAIL_ENABLED=true`, `EMAIL_HOST`, `DEFAULT_FROM_EMAIL`, no envía y lo comunica. Envío real por SMTP con archivos adjuntos y registro de responsable/fecha/destino; reintento con mismo UUID no duplica el envío registrado. Se requiere probar SMTP con una cuenta de pruebas antes de usar una editorial verdadera.

No se debe mostrar una pantalla afirmando «Enviado» si el SMTP está apagado, falló o solo se generó un borrador. No autoriza guía SUNAT.

## Endpoints y migraciones

- `POST recepciones/{id}/solicitar-aprobacion/`
- `POST recepciones/{id}/devolver/` (motivo)
- `POST recepciones/{id}/validar/` (separación de funciones)
- `GET/POST recepciones/{id}/evidencias/` (subida autenticada)
- `GET recepciones/{id}/evidencias/{evidence_id}/archivo/` (descarga privada)
- `GET/POST recepciones/{id}/reporte-editorial/`
- `GET inventario/avisos-recepcion/`
- `GET inventario/consolidado-filtros/`
- `GET inventario/consolidado/?grupo=colegio&editorial_id=X&colegio_id=Y`
- `0017_receipt_supervisor_approval`; `0018_receiving_evidence`. Ambas dependen de `0016` B3.

## Pruebas obligatorias antes de cierre

- Respaldar base PostgreSQL local. `python manage.py makemigrations --check --dry-run`; revisar `migrate --plan`; aplicar migraciones **solo en desarrollo**.
- Ejecutar `python manage.py sync_bookexpress_roles`; desde Seguridad y accesos asignar dos **usuarios diferentes**, uno ALMACEN y otro JEFE_ALMACEN. No dar permiso de validación a ALMACEN ni gestión de registro a jefe salvo justificación explícita. Salir/ingresar para refrescar claims.
- Almacenero crea borrador, adjunta foto de libro observado, envía a aprobación: inventario sin cambios. Jefe devuelve para corregir, almacenero corrige/solicita; jefe aprueba y se crea UNA entrada por línea conforme; terceros consultan avisos; al repetir validación no se duplica stock.
- Probar informe generado con nombre de guía y faltante frente a la guía, abrir evidencia vía descarga protegida; no inferir correo de proveedor. SMTP bloqueado por defecto. Probar con correo de laboratorio configurado; luego activar según procedimiento de administración de claves.
- Validar filtros Editorial/Colegio sobre >20 registros, combinación y resultado vacío. Confirmar saldos/global no cambian.
- Tests automatizados `python manage.py test warehouse.test_supervisor_receiving warehouse.test_distribution_preparation warehouse.tests`; `npm run lint && npm run build`; CI PostgreSQL.

## Pendientes explícitos

- Cuando exista requisito de adjuntar fotos **antes** de registrar un borrador, diseñar captura temporal asociada a pre-recepción; ahora se adjuntan a un borrador guardado.
- Aprobación por jefatura no incluye todavía firma digital avanzada ni doble conformidad de inventario.
- Configurar correo corporativo verificado, listas de destinatarios y política de conservación de evidencia/retención.
- Mejorar presentación, miniaturas seguras, extracción de fotos de proveedores y reportes PDF formalizados (primero trabajar con borrador revisable).
- Asegurar que órdenes **por enviar** se atiendan en Compras y definir un flujo de seguimiento independiente de despacho, sin imputar culpa al proveedor.
- B4 pendiente: documento SUNAT, despacho formal, conformidad de destino e integración de salidas, no confundir reporte a editorial con GRE.
