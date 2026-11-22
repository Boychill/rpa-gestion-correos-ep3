# Informe técnico · Robot RPA de gestión de correos EP3

## 1. Problema y alcance

La clasificación manual de mensajes y la consolidación de resultados consumen tiempo y dificultan la trazabilidad. El robot implementado lee metadatos de una carpeta autorizada, asigna categorías mediante reglas explícitas, calcula un plazo interno con feriados de Chile y genera un reporte consolidado. El objetivo de demostración es procesar 1.000 mensajes, con mediciones intermedias de 100, 300 y 500.

La carpeta inicial contenía solo el prompt. No se recibió el texto original del proyecto, la pauta oficial EP3 ni un trabajo TestFire. No se agregó automatización bancaria. La orquestación usa Python; si el docente exige otra herramienta RPA, se deberá contrastar y adaptar antes de declarar cumplimiento. La matriz de indicadores es provisional.

## 2. Diseño implementado

`main.py` resuelve PROJECT_ROOT a partir de su ubicación y carga Settings. El orquestador obtiene locks de perfil y base, crea o recupera la ejecución y llama subprocesos de autenticación, lectura, clasificación, feriados, Excel, envío, auditoría y mantenimiento. Cada módulo declara su contrato en su docstring. No se comparten tokens o variables de negocio globales.

SQLite es la fuente principal del estado. executions registra el ciclo de vida; messages mantiene la identidad estable y fingerprint; run_messages conserva snapshots por ejecución; checkpoints guarda cursores por ámbito; operations limita intentos; events registra pasos; sends implementa outbox; cleanups registra exportaciones y borrados. La migración inicial crea restricciones e índices. Las relaciones de snapshots son lógicas respecto de messages y foráneas respecto de executions.

Gmail API es el proveedor principal. OAuth de escritorio usa tokens separados: gmail.send para el remitente y gmail.readonly para el receptor. El perfil receptor se verifica con getProfile; la identidad del remitente se contrasta con From en la recepción. Los tokens se protegen con DPAPI y ACL en Windows, fuera de Git, ZIP y panel. La ejecución normal no abre navegador. El alcance se limita al dataset y fechas; los mensajes no se modifican.

## 3. Incrementalidad y recuperación

Cada página y su avance se confirman dentro de una transacción corta. Si una caída ocurre antes del commit, se vuelve a leer la página. Después del commit, los mensajes pendientes ya están disponibles para clasificar. Gmail utiliza nextPageToken para paginar y historyId para incrementalidad. La búsqueda inicial se limita por fecha y dataset; no se usan cursores Graph en Gmail.

La clave es origen+buzón+ID, nunca asunto/fecha. Un fingerprint de metadatos diferencia duplicados de actualizaciones. Los tombstones retiran el mensaje del conjunto vigente de esa ejecución. El error 404 de historial Gmail provoca una resincronización acotada y deduplicación. Los resultados sintéticos se mantienen separados de los IDs reales.

Los intentos HTTP se persisten antes de consultar; la configuración inicial permite tres totales. Los 429 respetan Retry-After y los transitorios usan espera exponencial. Se comprueban timeout, presupuesto por operación y tiempo activo acumulado de ejecución. Permisos insuficientes y esquemas inválidos no se reintentan automáticamente. Los intentos de clasificación se conservan y una regla fallida puede terminar en REVIEW. No se eliminan cursores o claves al limpiar logs.

## 4. Clasificación y plazos

La prioridad es Urgente, Reclamo, Solicitud, Consulta, Información y Otros. Se normalizan tildes y mayúsculas y se usan fronteras de palabra. El JSON solo admite palabras literales confiables; no se ejecutan regex ingresadas por remitentes. Se registra categoría, regla ganadora y versión, sin cuerpos en auditoría. Otros indica ausencia de señal y no una interpretación semántica garantizada.

Nager.Date entrega JSON por país/año. La integración valida fecha, país, nombre, ámbito nacional y tipo. Registra proveedor, HTTP, consulta, origen y fechas; mantiene caché CL/año con vigencia. El calendario fixture es deliberadamente sintético y visible. Los datos reales de 2026 y 2027 se verificaron con GET; los archivos de evidencia contienen la respuesta pública.

El día de recepción no cuenta. La fecha de recepción se convierte a America/Santiago y se avanza por días hábiles, excluyendo sábados, domingos y feriados nacionales de tipo Public. Se consulta el nuevo año al cruzar diciembre. Feriados regionales o especiales fuera de esta cobertura no se incluyen. Si falta un año o la caché está vencida y no se obtiene una respuesta válida, el plazo queda nulo y se bloquea el envío. Es una regla operativa de demostración, no una obligación legal.

## 5. Reporte y acciones de escritorio

La plantilla XLSX tiene Resumen, Correos, Referencia_API y Ejecuciones; incluye estilos, fórmula total y gráfico. Se guarda una copia por UUID y se verifica su estructura, conteo, fórmula, gráfico y pertenencia a la ejecución. El texto susceptible de convertirse en fórmula se neutraliza. La evidencia académica oculta asuntos e identifica remitentes mediante seudónimos. La duración del libro corresponde al procesamiento disponible al construirlo; el resultado final permanece en SQLite/JSON.

El worker Excel COM abre una copia, deshabilita macros, modifica un rango, recalcula, guarda, cierra y reabre. En este equipo la prueba real volvió a devolver EXCEL_COM_UNAVAILABLE: openpyxl no acredita IL 3.2. Gmail reemplaza Outlook como canal principal; no se afirma haber usado Outlook.

## 6. Envío, efectos externos y auditoría

MAIL_MODE inicia en DRY_RUN. SEND requiere autorización, token remitente, feriados LIVE y destinatario permitido. REQUIRE_EXCEL obliga a comprobar Excel de escritorio cuando se configura; Gmail puede adjuntar un XLSX sin COM, sin acreditar por ello el requisito académico de escritorio. El reporte usa el prefijo [RPA-EP3], excluido de los insumos, HTML escapado y un único archivo consolidado.

Se verifica que el libro esté cerrado y se registra tamaño y SHA256 antes del envío. PREPARADO se persiste antes del efecto externo. Gmail HTTP 200 con identificador produce ACEPTADO; no significa entrega. Un error ambiguo o PREPARADO encontrado tras una caída se marca ENVIO_INCIERTO y no se reintenta. Reconciliar exige una operación separada y evidencia del operador. El estado del envío no altera el archivo que se adjuntó. Un fallo de mantenimiento posterior no puede autorizar un reenvío.

Cada evento registra ejecución, paso, host, inicio/fin UTC, duración monotónica, intento, nivel, resultado y código sanitizado. event_context añade rol, dataset, trabajo, HTTP, espera y decisión de recuperación. Se evita registrar excepciones completas, tokens, URLs de continuación y datos de mensajes. Hay logs rotativos por nivel y consultas SQLite. Los fallos transitorios permanecen visibles junto al éxito final del paso.

## 7. Panel, exportación y retención

FastAPI se inicia solo en 127.0.0.1. El panel ofrece ejecuciones, eventos, filtros, errores, almacenamiento y descargas log/csv/json/zip. Las exportaciones de auditoría limitan a 10.000 filas, explícitamente. Las mutaciones requieren token CSRF y verifican origen; los datos se insertan con textContent en el navegador.

La limpieza enumera únicamente logs vencidos de ejecuciones cerradas y reconoce nombres gestionados. No acepta rutas arbitrarias y rechaza enlaces/junctions, archivos modificados o activos. Genera y verifica un ZIP con manifiesto y hashes; luego solicita confirmación de copia guardada y frase de eliminación. No se interpreta HTTP 200 como prueba de descarga guardada. El resumen del borrado permanece en SQLite.

Retención inicial: DEBUG 7, INFO 15, ERROR 30, copias descargadas 15, exportaciones 7 y analítica 90 días. AUTO_CLEAN_LOGS elimina automáticamente archivos gestionados vencidos al terminar el robot, al iniciar el panel y cada hora mientras permanezca abierto. No hay tarea de Windows instalada: con el programa cerrado no hay limpieza en segundo plano. No se purgan automáticamente SQLite ni Supabase. La herramienta separada de mantenimiento permite respaldar SQLite con integrity_check y hash, previsualizar y purgar solo eventos técnicos informativos de ejecuciones sin envío real. Preserva errores en SQLite, pasos de envío, revisiones, ejecuciones, mensajes, deduplicación, cursores, outbox y limpieza. Los respaldos son privados y no entran al ZIP público.

## 8. Validación y límites de las mediciones

La suite cubre reglas, tildes, asunto vacío, prioridad, invalidación, transacciones antes/después del commit, recuperación, deduplicación, tombstones, cambio de año, cobertura ausente, neutralización de fórmulas, plantilla dañada, libro bloqueado en Windows, locks, 429, presupuesto, agotamiento persistente, HTTP 403, contratos de Gmail y compatibilidad Graph simulados, envío incierto, mantenimiento y limpieza segura. Los resultados de la última ejecución están en pytest.xml.

El benchmark crea estados aislados, genera páginas deterministas, ejecuta el flujo completo sin Office/envío y mide tiempo total, rendimiento, consultas, reintentos, duplicados y memoria de asignaciones Python con tracemalloc. No mide RSS del proceso ni memoria de Office. Las cifras dependen del equipo, almacenamiento, antivirus y cachés; no predicen rendimiento Gmail real. La tabla vigente se incorpora automáticamente al PDF desde benchmark.json.

Las pruebas reales incluyen feriados, Supabase, OAuth por rol y un lote Gmail de 500 mensajes: 500 recibidos y clasificados, sin faltantes ni duplicados. Se incorporaron 172 mensajes ubicados en Spam mediante lectura del dataset, sin moverlos. PRUEBAS_GMAIL.md y gmail_real_checks.json separan aceptación, recepción y clasificación. La interacción con Excel de escritorio sigue bloqueada.

## 9. Privacidad, impacto y sostenibilidad

La automatización reduce clasificación repetitiva y permite revisión mediante reglas visibles. También puede priorizar mal mensajes ambiguos, exponer datos si se comparte SQLite o duplicar correos si se ignora un resultado incierto. Las mitigaciones son ámbito de pruebas, mínimos campos/permisos, seudonimización de evidencia, escape de contenido, verificación de destinatario y una outbox conservadora. El asunto sigue siendo dato personal potencial en el estado privado; no se afirma anonimización total ni cifrado de SQLite.

El procesamiento incremental, la caché por año, lotes y guardados acotados reducen consultas, escrituras y trabajo repetido. La retención confirmada evita pérdida silenciosa y limita almacenamiento. La mejora creativa demostrable es combinar recuperación incremental con auditoría exportable, verificable y depurable sin perder deduplicación.

Supabase está implementado como historial compartido de ejecuciones y pasos sanitizados. La migración crea rpa_logs con RLS y sin acceso anon/authenticated. El proceso Python usa una secret key privada mediante REST. La cola SQLite conserva intentos y agenda Retry-After; un máximo de tres intentos por registro y revisión impide reintentos indefinidos. IDs estables y upsert evitan duplicados ante timeout ambiguo. Se pueden descargar registros a runtime/logs/descargas con hash y caducidad, y la limpieza nunca borra el estado operativo. No se envían cuerpos, asuntos, direcciones, host, tokens ni cursores. La conexión real se verificó el 18 de noviembre de 2026: esquema accesible, 9 registros coincidentes, escritura repetida sin duplicados, segunda sincronización sin peticiones y descarga con contenido/hash correcto. La evidencia está en supabase_real_checks.json; los fallos y límites de reintentos se prueban con transporte simulado para no forzar errores en el servicio real.

## 10. Pendientes para aceptación académica

Obtener la pauta oficial y confirmar la herramienta admitida por el docente. Demostrar Excel COM en un equipo con Excel instalado. El canal Gmail ya tiene envío, recepción y clasificación reales verificados; el envío adicional del consolidado está pendiente de REPORT_TO. No declarar acreditado el uso de Excel de escritorio mientras falte esa prueba.
