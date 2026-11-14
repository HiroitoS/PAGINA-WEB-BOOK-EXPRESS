-- BOOK EXPRESS | Inspección de datos de prueba para CRM / ERP (campaña 2027)
-- SOLO CONSULTAS: compatible con pgAdmin Query Tool en base local bookexpress_db.
-- Evitar INSERT directo en CRM, pedidos, recepciones o inventario:
-- esas operaciones ejecutan validaciones, numeración, eventos y movimientos
-- transaccionales desde Django, que un INSERT manual no reproduce.
-- NO ejecutar en la base de producción.

-- 1. Comprueba primero a qué base estás conectado y el volumen de datos.
SELECT
    current_database() AS base_actual,
    (SELECT COUNT(*) FROM crm_school WHERE is_active = TRUE) AS colegios_activos,
    (SELECT COUNT(*) FROM catalog_product WHERE is_active = TRUE) AS productos_activos,
    (SELECT COUNT(DISTINCT product_id)
       FROM catalog_productprice
      WHERE year = 2027 AND is_active = TRUE AND price > 0) AS libros_con_precio_2027;

-- 2. Colegios reales importados que pueden servir de REFERENCIA para pruebas,
--    no para crear operaciones comerciales reales.
SELECT id AS colegio_id, name AS colegio, book_express_code AS codigo
FROM crm_school
WHERE is_active = TRUE
  AND name NOT LIKE '[PRUEBA ERP]%'
ORDER BY id
LIMIT 12;

-- 3. Libros con precio 2027, uno por editorial para variar las pruebas.
SELECT DISTINCT ON (p.provider_id)
    p.provider_id AS editorial_id,
    e.name AS editorial,
    p.id AS producto_id,
    p.name AS libro,
    pp.price AS pvp_2027
FROM catalog_product AS p
JOIN catalog_provider AS e ON e.id = p.provider_id
JOIN catalog_productprice AS pp ON pp.product_id = p.id
WHERE p.is_active = TRUE
  AND pp.is_active = TRUE
  AND pp.year = 2027
  AND pp.price > 0
  AND p.commercial_line = 'school_text'
ORDER BY p.provider_id, p.id
LIMIT 12;

-- 4. Estado de los borradores de DEMOSTRACIÓN que ya generamos con Django.
SELECT
    s.id AS colegio_demo_id,
    s.name AS colegio_demo,
    COUNT(o.id) AS oportunidades
FROM crm_school AS s
LEFT JOIN crm_opportunity AS o ON o.school_id = s.id
WHERE s.name LIKE '[PRUEBA ERP]%'
GROUP BY s.id, s.name
ORDER BY s.id DESC;

-- ESCRITURA RECOMENDADA (TERMINAL DEL BACKEND; NO EN QUERY TOOL):
-- Vista previa sin escribir:
-- python manage.py preparar_demo_erp_lote --year 2027 --cantidad 3 --unidades 20
--
-- Crear 3 escenarios de CRM en BORRADOR solo en PostgreSQL local con DEBUG=True:
-- python manage.py preparar_demo_erp_lote --year 2027 --cantidad 3 --unidades 20 --crear --local
--
-- El comando reutiliza colegios y productos existentes, pero CREA únicamente
-- colegios de prueba etiquetados, oportunidades, proyecciones y cotizaciones
-- EN BORRADOR. NO genera adopciones, pedidos, recepciones, stock ni ventas.
-- Si se ejecuta nuevamente, evita duplicar escenarios por colegio/año.
