# Fuentes y decisiones verificadas

Consulta técnica: 17 de noviembre de 2026. Las fuentes siguientes respaldan los contratos; la evidencia de ejecución está en `docs/evidence`, separada de la documentación.

Actualización Gmail: 18 de noviembre de 2026. Gmail es el proveedor principal; las referencias Microsoft documentan los adaptadores de compatibilidad conservados.

| Fuente Gmail oficial | Decisión aplicada |
|---|---|
| [OAuth de escritorio Python](https://developers.google.com/workspace/gmail/api/quickstart/python) | Cliente Desktop existente, navegador explícito y callback localhost. |
| [Scopes Gmail](https://developers.google.com/workspace/gmail/api/auth/scopes) | send-only para remitente y readonly para receptor, tokens separados. |
| [Usuarios de prueba](https://support.google.com/cloud/answer/15549945) | External/Testing y posible reautorización a los siete días. |
| [Listado paginado](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list) | Búsqueda por dataset/fecha y nextPageToken, seguida de metadata por ID. |
| [Historial incremental](https://developers.google.com/workspace/gmail/api/guides/sync) | historyId y resincronización acotada tras 404. |
| [Envío MIME](https://developers.google.com/workspace/gmail/api/guides/sending) | EmailMessage, base64url y aceptación separada de recepción. |
| [Errores Gmail](https://developers.google.com/workspace/gmail/api/guides/handle-errors) | Separar API deshabilitada, permiso, cuota y resultado incierto. |

| Fuente oficial | Decisión aplicada |
|---|---|
| [Graph message delta](https://learn.microsoft.com/en-us/graph/api/message-delta?view=graph-rest-1.0) | Lectura con Mail.ReadBasic delegado; select mínimo, filtro inferior recibido, límite superior local. No search ni expansión de cuerpos. |
| [Identificadores inmutables](https://learn.microsoft.com/en-us/graph/outlook-immutable-id) | Prefer IdType ImmutableId en todas las páginas, también al reanudar. |
| [Delta overview](https://learn.microsoft.com/en-us/graph/delta-query-overview) | Cursor opaco y resincronización ante 410. |
| [Graph sendMail](https://learn.microsoft.com/en-us/graph/api/user-sendmail?view=graph-rest-1.0) | Mail.Send únicamente para envío Graph; HTTP 202 significa aceptación, no entrega. |
| [MSAL Python](https://msal-python.readthedocs.io/en/latest/) | OAuth interactivo con timeout y login_hint, comprobación posterior de cuenta; tokens solo en memoria. |
| [Alternativas de automatización Outlook](https://learn.microsoft.com/en-us/microsoft-365-apps/outlook/get-started/vba-alternatives) | Outlook clásico COM sujeto a instalación/perfil; Graph como alternativa explícita. |
| [Nager.Date API](https://nagerholidays.com/API) | GET público CL por año; schema validado en código y pruebas reales de 2026/2027. |
| [Términos Nager.Date](https://nagerholidays.com/legal/termsofservice) | Permiten proyectos privados o sin fines de lucro; para fines comerciales requieren patrocinio activo. Prohíben operar un portal propio de feriados con estos datos. No garantizan disponibilidad ni exactitud. Demo académica sin fines de lucro. |
| [openpyxl](https://openpyxl.readthedocs.io/en/stable/) | Creación, edición y verificación XLSX; no sustituye Excel de escritorio. |
| [HTTPX timeouts](https://www.python-httpx.org/advanced/timeouts/) | Timeout explícito por petición, más presupuestos de operación/ejecución. |
| [FastAPI](https://fastapi.tiangolo.com/) | Panel local con rutas tipadas y descargas. |
| [Supabase REST](https://supabase.com/docs/guides/api) | Historial remoto por REST, claves estables y cola local durable. |
| [Supabase API keys](https://supabase.com/docs/guides/getting-started/api-keys) | Secret key en apikey, solo en Python; RLS y sin acceso de navegador a la tabla. |

El sitio documental de Nager.Date redirige actualmente a nagerholidays.com; el endpoint `https://date.nager.at/api/v3/PublicHolidays/{year}/CL` respondió directamente HTTP 200 en la prueba guardada. No se siguen redirecciones de API automáticamente. Los datos son referencia externa y no certificación legal. Dependencias efectivamente instaladas: `requirements-lock.txt`; no se fija una versión a partir de memoria.
