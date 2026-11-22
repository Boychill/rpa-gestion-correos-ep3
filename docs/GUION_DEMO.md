# Guion de exposición · 11 minutos

## 0:00–1:00 · Problema, objetivo y honestidad de alcance

Explicar que se procesan correos entrantes para seis categorías y un reporte único. Mostrar el objetivo 1.000 y el modo DRY_RUN. Aclarar que la pauta oficial no estuvo disponible; separar pruebas sintéticas, API real y escritorio pendiente.

## 1:00–2:00 · Arquitectura y subprocesos

Mostrar arquitectura y flujo. Seguir main → autenticación → páginas → clasificación → feriados → Excel → envío → auditoría → mantenimiento. Explicar por qué SQLite conserva el avance y la auditoría.

## 2:00–3:15 · Lectura incremental y clasificación

Mostrar reglas JSON: prioridad, versión y normalización. Usar ejemplos “consulta y reclamo”, “URGÉNTE” y asunto vacío. Mostrar que no se leen cuerpos ni adjuntos. Explicar transacción de página con cursor e IDs estables. Mostrar una prueba de interrupción y recuperación de la suite.

## 3:15–4:30 · API y plazo de atención

Abrir evidencia GET real para Chile y Referencia_API del libro de demostración LIVE. Explicar que el día de recepción no cuenta y mostrar cruce de diciembre a enero. El calendario nacional no cubre feriados regionales. Un año faltante bloquea envío, no produce una fecha inventada.

## 4:30–5:45 · Excel y escritorio

Abrir reporte sintético: resumen/gráfico, correos redactados, API y ejecución. Mostrar plantilla intacta y manifiesto. En el equipo inicial, mostrar el estado COM no disponible y el adaptador; si la prueba de Office ya fue realizada en otro equipo, usar su evidencia real antes/después con fecha y versión. No presentar openpyxl como escritorio.

## 5:45–7:00 · Envío controlado y recuperación

Mostrar vista previa HTML, allowlist y estados PREPARADO → ACEPTADO / ENVIO_INCIERTO. Explicar que HTTP 202 no acredita entrega y que una reanudación nunca reenvía automáticamente. Solo si existe autorización previa y configuración completa, presentar evidencia de un único envío de pruebas; no habilitarlo improvisadamente durante la exposición.

## 7:00–8:15 · Panel y limpieza verificable

Abrir localhost, filtrar por ejecución y ERROR, descargar JSON/ZIP y revisar manifiesto. Mostrar selección de logs vencidos, frase requerida y confirmación de copia. No borrar evidencia necesaria para la evaluación. Explicar qué tablas y archivos están protegidos.

## 8:15–9:30 · Pruebas y capacidad

Mostrar la tabla generada de 100/300/500/1.000: tiempo, consultas, reintentos y memoria Python. Indicar que es una medición de fixtures, no Gmail real. Presentar la suite y destacar 429, commit interrumpido, archivo bloqueado, destinatario rechazado y resultado de envío incierto.

## 9:30–10:30 · Ética y sostenibilidad

Discutir errores de clasificación, datos personales en el estado privado y necesidad de revisión. Mostrar campos mínimos, seudonimización, ámbito de pruebas, retención y caché. Explicar mejora creativa: recuperación incremental más auditoría exportable sin perder deduplicación.

## 10:30–11:00 · Pendientes y preguntas

Mostrar matriz provisional. Enumerar pauta oficial, Excel instalado, buzón autorizado y entrega real pendiente según la evidencia vigente. Mostrar el historial Supabase, la cola con tres intentos máximos y la caducidad de copias; aclarar si la conexión real todavía no fue configurada. Cerrar con la demostración de lo medido y la ruta concreta de aceptación, sin prometer cumplimiento no comprobado.
