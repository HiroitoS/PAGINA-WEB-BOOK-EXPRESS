# Book Express — Checklist de mantenibilidad antes de producción

Este documento registra deuda técnica y refactorizaciones obligatorias antes de promover la plataforma a producción estable o comercializarla como producto para terceros.

## Principio

No se refactoriza por cantidad de líneas solamente. La prioridad aumenta cuando un archivo:
- mezcla varias responsabilidades;
- concentra reglas de negocio y transporte HTTP;
- dificulta pruebas aisladas;
- obliga a modificar muchas secciones para cambios pequeños;
- aumenta el riesgo de regresión.

## Prioridad alta — backend

### crm/api/views.py
- Tamaño aproximado actual: 130 KB.
- Riesgo: concentra demasiados endpoints y dominios CRM.
- Acción: dividir por dominio manteniendo rutas/API públicas estables.

Propuesta:

```text
crm/api/
  views/
    schools.py
    contacts.py
    activities.py
    opportunities.py
    projections.py
    quotations.py
    adoptions.py
    reports.py
    dashboard.py
    teams.py
```

### crm/api/serializers.py
- Tamaño aproximado actual: 100 KB.
- Riesgo: mezcla serialización de varios dominios CRM.
- Acción: separar serializers por dominio sin renombrar campos ni romper contratos existentes.

### crm/services/quotations.py
- Tamaño aproximado actual: 59 KB.
- Riesgo: reglas comerciales sensibles de precios, descuentos, incentivos y estados en un solo módulo.
- Acción: separar cálculo, transición de estados, validaciones y snapshots manteniendo una fachada pública estable.

### workspaces/views.py
- Tamaño aproximado actual: 41 KB.
- Riesgo: ToDo/Workspace crecerá en el siguiente bloque.
- Acción: revisar antes de profesionalizar ToDo para evitar seguir agregando lógica a un único archivo.

## Prioridad media — backend

- crm/services/school_imports.py
- crm/services/reports.py
- crm/services/report_exports.py
- crm/services/history.py
- catalog/views.py
- workspaces/serializers.py

Estos módulos deben revisarse por cohesión y responsabilidades, pero no requieren división automática si conservan una única responsabilidad clara.

## Tests grandes

### crm/tests/test_api.py
- Tamaño aproximado actual: 115 KB.
- No es un riesgo de producción equivalente a un `views.py` grande.
- Acción: dividir por dominio para mejorar navegación y diagnóstico:
  - test_schools_api.py
  - test_activities_api.py
  - test_opportunities_api.py
  - test_reports_api.py
  - test_dashboard_api.py

Los tests deben mantenerse o aumentar; nunca reducirse solo para bajar líneas.

## Prioridad alta — frontend

### src/components/admin/crm/CRMOpportunityQuotationSection.jsx
- Tamaño aproximado actual: 116 KB.
- Riesgo alto: cotización es un flujo comercial crítico.
- Acción: dividir formulario, reglas visuales, resumen de cálculo, descuentos, tabla de productos y acciones.

### src/pages/admin/crm/CRMSchoolDetailPage.jsx
- Tamaño aproximado actual: 84 KB.
- Acción: extraer secciones de ficha comercial y mantener la página como orquestador.

### src/pages/admin/crm/CRMContactDetailPage.jsx
- Tamaño aproximado actual: 69 KB.
- Acción: separar historial, actividades, relaciones y acciones.

### src/components/admin/crm/CRMOpportunityProjectionSection.jsx
- Tamaño aproximado actual: 57 KB.
- Acción: dividir selector de grados, búsqueda de productos, cantidades y resumen.

### Workspace / ToDo
Archivos grandes detectados:
- WorkspaceCalendarPage.jsx
- WorkspaceTasksPage.jsx
- WorkspacePage.jsx
- WorkspaceRemindersPage.jsx

Acción: refactor obligatorio durante el bloque ToDo profesional, no después.

## Prioridad media — frontend

- CRMReportsPage.jsx
- CRMOpportunitiesPage.jsx
- SchoolEducationalServicesSection.jsx
- SchoolInstitutionalPopulationSection.jsx
- ProductsPage.jsx
- UsersPage.jsx
- ProvidersPage.jsx

Revisar por responsabilidad antes de producción.

## Dashboard CRM

El Dashboard Premium se refactoriza ahora porque es reciente. La página debe quedar como orquestador y las visualizaciones en componentes independientes.

Estructura objetivo:

```text
src/components/admin/crm/dashboard/
  DashboardMetricCard.jsx
  DashboardProgressMetric.jsx
  ActivityTrendChart.jsx
  DashboardActivityComposition.jsx
  DashboardCoverageCard.jsx
  PipelineProgressList.jsx
  DashboardClosingStatus.jsx
```

## Checklist antes de merge a main / producción

1. Ejecutar tests backend completos.
2. Ejecutar `python manage.py check`.
3. Ejecutar `python manage.py makemigrations --check`.
4. Ejecutar `npm run lint`.
5. Ejecutar `npm run build`.
6. Auditar permisos por rol y endpoints.
7. Revisar dependencias y `npm audit` sin aplicar fixes automáticos a ciegas.
8. Refactorizar hotspots de prioridad alta.
9. Repetir pruebas de regresión después del refactor.
10. Validar backups, logging, variables de entorno y despliegue.
11. Validar flujo completo Colegio → Actividad → Proyección → Cotización → Adopción → Reportes.
12. Solo después promover `crm/gestion-colegios` a `main`.
