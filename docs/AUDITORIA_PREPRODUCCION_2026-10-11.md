# Book Express — Auditoría preliminar para publicación (11-10-2026)

**Estado: NO APTO AÚN para promover a `main` o desplegar el CRM actualizado.**
Este documento registra comprobaciones de lectura hechas sobre GitHub, complementadas con evidencias de terminal y capturas aportadas por el equipo. No equivale a una ejecución de pruebas en un servidor de producción.

## Alcance y versión examinada

- Backend: `HiroitoS/PAGINA-WEB-BOOK-EXPRESS`, rama existente `crm/gestion-colegios`, commit examinado `6d6abd5f5c1f`.
- Frontend: `HiroitoS/PAGINA-WEB-BOOK-EXPRESS-FRONTEND`, misma rama, commit examinado `809c75b9e827`.
- La comparación con `main` arroja 508 commits adicionales en backend y 409 en frontend (consulta de 11-10-2026). Revisar de nuevo antes de cualquier merge.
- Repositorios públicos. La existencia de una versión anterior publicada no demuestra que la nueva versión esté lista para despliegue.
- No se crearon ramas, no se modificó producción, no se abrieron archivos con secretos ni datos de clientes, y no se ejecutaron migraciones sobre datos reales durante esta auditoría.

## Hallazgos verificados en el repositorio

### P0 — Revisión de exposición de archivos bajo seguimiento

La raíz del repositorio backend contiene archivos **versionados** llamados `.env` (288 bytes) y `db.sqlite3` (131072 bytes). También existen directorios `media/`, `staticfiles/` y archivos `__pycache__/*.pyc` versionados.

Los patrones de exclusión **ya aparecen** en `.gitignore`, pero `.gitignore` no elimina de Git los archivos incorporados anteriormente. Se debe tratar la posible exposición de credenciales como riesgo hasta verificar y rotar cualquier secreto que haya sido real. El contenido de esos archivos **no fue consultado**.

**Acciones seguras pendientes:**

1. Identificar, en un entorno autorizado y sin pegar valores en chats o tickets, qué credenciales pudieron quedar en el historial público; rotar tokens, claves de sesión y contraseñas comprometidas. Verificar usuarios y accesos de base de datos.
2. Determinar si `db.sqlite3` y archivos en `media/` contienen información personal o comercial; identificar titulares, obligaciones de notificación y política de acceso/retención si correspondiera.
3. Hacer copia de seguridad verificable del repositorio de trabajo y de los datos locales o del servidor **antes** de dejar de versionar archivos. Planificar `git rm --cached` y validación de los efectos de `git pull`, que podría retirar archivos previamente versionados del árbol de trabajo de otros clones.
4. No reescribir historial o forzar `push` sin coordinar y asegurar respaldos y restauración; sacar un secreto del último commit **no** lo elimina del historial.
5. Separar almacenamiento de evidencias y subidas de clientes del árbol Git, con controles de acceso y backups. No borrar bases ni medios de forma automática.

### P0 — Configuración real de seguridad del despliegue

La captura del comando local `python manage.py check --deploy` mostró advertencias `security.W004`, `W008`, `W009`, `W012`, `W016` y `W018`. En `config/settings.py` se leen variables de entorno para `DEBUG`, `SECRET_KEY`, HTTPS/cookies y acceso a PostgreSQL. El valor predeterminado de `DEBUG` en ausencia de configuración es verdadero; las cookies seguras se calculan como `not DEBUG`. No debe extrapolarse el diagnóstico local a la configuración efectiva del hosting.

**Antes de desplegar:** comprobar de manera independiente el entorno real de producción (sin exponer claves), `DEBUG=False`, `ALLOWED_HOSTS`, clave robusta y protegida, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, HTTPS de extremo a extremo, redirección HTTPS, cabeceras del proxy, CORS/CSRF y política HSTS. Habilitar HSTS **solo** tras confirmar HTTPS y dominio/subdominios.

### P1 — Puerta de calidad reproducible

No se encontró directorio `.github/workflows` en los repositorios examinados y el estado combinado de sus commits examinados no mostró comprobaciones registradas. Esto no invalida las pruebas manuales ni las pruebas locales previamente aportadas; indica que aún falta un control automático confirmado en GitHub.

Evidencias de capturas aportadas: pruebas Django de planificación (7 correctas), auditoría de tareas (3 correctas), tests JavaScript de ToDo/CRM (16 correctos), lint sin errores y build Vite exitoso, con advertencia de bundle mayor de 500 kB. **No se han vuelto a ejecutar aquí**, por lo que deben reproducirse sobre el mismo commit que vaya a desplegarse.

Comandos orientativos, desde un entorno de pruebas aislado, sin apuntar a datos de producción:

```bash
# Backend — usando PostgreSQL de pruebas y variables adecuadas
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate --plan
python manage.py test --noinput

# Frontend
npm ci
node --test tests/*.test.js
npm run lint
npm run build
npm audit --omit=dev
```

La validación `check --deploy` debe realizarse con los **ajustes de producción** cargados, no solo con el `.env` de desarrollo. No ejecutar `migrate` en producción antes de una copia recuperable, ensayo de migración y procedimiento de reversión.

### P1 — Validación funcional y permisos antes de merge

Realizar pruebas de regresión de cambios recientes: ToDo y listas personales/compartidas, asignación desde jefe al asesor, visibilidad entre equipos, denegación de acceso por URL directa, sincronización de próxima acción CRM → tarea → calendario, historial de planificación y gestión con usuario/fecha; actividades con evidencias; flujo colegio → actividad → proyección → cotización → aceptación → adopción → reportes/Excel/impresión. Probar con usuarios distintos y confirmar restricciones en API/backend, además de interfaz.

Si un escenario ya fue aceptado y su módulo no se modificó, no es necesario repetir todas sus variantes; priorizar cambios y puntos de integración.

### P2 — Mantenibilidad y rendimiento

El documento `docs/PREPRODUCTION_MAINTAINABILITY.md` ya registra áreas de refactorización de `crm/api/views.py`, `crm/api/serializers.py`, servicios de cotización, `workspaces/views.py` y grandes secciones JSX. Antes de dividirlas, identificar responsabilidades/riesgo de regresión y proteger contratos existentes mediante tests. No refactorizar solo por número de líneas.

En la última captura de `npm run build` el frontend compiló y reportó un bundle JavaScript principal cercano a 1,223 kB antes de gzip. Medir carga real y decidir code splitting de rutas si afecta experiencia; **no** ocultar advertencia elevando el umbral sin optimizar.

Hay mejoras visuales solicitadas para espacios excesivos en ToDo/CRM; corregir sin alterar funcionalidad ni rutas y validarlas después de los bloqueantes.

## Criterio GO / NO-GO

**NO-GO** mientras persista duda material sobre credenciales/datos en repositorio público, falte verificar seguridad real del servidor, no exista respaldo restaurable o fallen permisos/flujo comercial crítico.

**GO** únicamente tras: resolver P0, comprobar migraciones de forma segura y backups, ejecutar pruebas de backend/frontend sobre commits congelados, completar aceptación de roles y flujo comercial, confirmar configuración y destino del despliegue, y aprobar expresamente la promoción de rama. No hacer merge a `main` ni publicar automáticamente.

## Próximo paso recomendado

1. Revisar exposición y almacenamiento versionado con la persona responsable del servidor y repositorios, sin compartir secretos.
2. Documentar ajustes actuales de producción y estrategia de respaldo, verificando capacidad de restaurar.
3. Corregir cualquier bloqueo confirmado; volver a ejecutar pruebas focalizadas.
4. Solo entonces preparar procedimiento de despliegue y rollback con aprobación del responsable.
