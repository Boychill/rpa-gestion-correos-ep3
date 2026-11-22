# Google Cloud y Gmail API en EP3

Gmail es el proveedor principal del robot local. Google Cloud identifica la aplicación
OAuth y habilita la API; no aloja este proceso Python. Los adaptadores Microsoft ya
existentes se conservan como compatibilidad y no son necesarios para el flujo Gmail.

## Configuración local

Se reutilizó el JSON de escritorio encontrado en `config/credentials.json.json`,
copiado byte por byte a `config/google/credentials.json`. El JSON corresponde al proyecto
previsto. La existencia de ese archivo no demuestra autorización ni envío.
La confirmación de API habilitada requiere una consulta autenticada exitosa.
La lista de usuarios de prueba en consola no puede inspeccionarse con un token Gmail.

`.env` conserva Supabase y configura `MAIL_PROVIDER=gmail`, los dos roles y las rutas.
Los alias `GMAIL_CREDENTIALS_PATH`, `REPORT_TO`, `HTTP_TIMEOUT_SECONDS` y
`RUN_DEADLINE_SECONDS` se traducen al contrato existente de Settings. Las rutas parten
de PROJECT_ROOT, aunque la terminal esté en otro directorio. `SOURCE=FIXTURE` conserva
la demostración sin internet; los comandos de análisis del lote usan `SOURCE=GMAIL`.

| Rol | Permiso | Token |
|---|---|---|
| Remitente | gmail.send | config/google/token_remitente.json |
| Receptor | gmail.readonly | config/google/token_receptor.json |

Los archivos de token `.json` son contenedores cifrados DPAPI en Windows, con ACL para
el usuario actual y SYSTEM y escritura atómica. En otros sistemas se aplica modo 0600.
No son tokens ficticios. El JSON original del cliente mantiene su estructura. Todos los
archivos de credenciales, sus nombres duplicados y tokens quedan fuera de Git, ZIP y panel.
La limpieza de logs no accede a `config/google`.

## Autorizar y diagnosticar

```powershell
.\.venv\Scripts\python.exe autenticar_gmail.py remitente
.\.venv\Scripts\python.exe autenticar_gmail.py receptor
.\.venv\Scripts\python.exe scripts/diagnosticar_gmail.py
```

Selecciona la cuenta exacta indicada en cada ventana. La autorización pide selección de
cuenta y acceso offline con callback localhost en puerto libre. El receptor se verifica
con `users.getProfile`. **gmail.send no habilita getProfile**: el remitente queda como
cuenta declarada por el operador. Su identidad se contrasta con From en la recepción de
los mensajes; no se agregan scopes de identidad silenciosamente.

El diagnóstico del remitente comprueba la disponibilidad del token, no el funcionamiento
del envío. El receptor usa la librería oficial y una consulta acotada al lote, sin cuerpos.
Solo `autenticar_gmail.py` o `scripts/authorize_gmail.py` abren navegador. La ejecución
normal carga tokens existentes, valida cliente/rol/scopes y refresca cuando corresponde.
Un fallo permanente termina con AUTH_REQUIRED; un problema de red con AUTH_TRANSIENT.
La lectura admite un refresh tras 401, sin volver a abrir OAuth dentro del reintento.

Para cambiar una cuenta equivocada o reemplazar un token revocado:

```powershell
.\.venv\Scripts\python.exe autenticar_gmail.py remitente --force
.\.venv\Scripts\python.exe autenticar_gmail.py receptor --force
```

Una app External en Testing con scopes Gmail puede necesitar autorización nueva a los
siete días. No se publica la aplicación para evitar esa condición.

## Generador separado

`scripts/gmail_demo.py prepare --sender DIRECCION --recipient DIRECCION --count 500`
prepara un manifiesto persistente. `send` y `run` también requieren `--count`; **sin
`--execute` solo simulan**. Ambos correos deben coincidir con la configuración local.
El lote preparado antes de esta integración conserva su UUID y sus estados.

```powershell
# Simular el lote existente, sin OAuth ni envío:
.\.venv\Scripts\python.exe scripts/gmail_demo.py send --campaign 4aa43f17-2bb2-420a-96cd-0f91bee700a9 --sender javiermontupilca@gmail.com --recipient correopruebaslocasprogra@gmail.com --count 500
# Envío real autorizado: misma orden más --execute.
# Analizar/reconciliar únicamente, sin enviar:
.\.venv\Scripts\python.exe scripts/gmail_demo.py analyze --campaign 4aa43f17-2bb2-420a-96cd-0f91bee700a9
```

`run --execute` verifica antes el token del receptor, envía los pendientes y después lee.
Cada trabajo tiene clave `dataset:sequence`, persistida antes del POST. Estados internos
del generador: PENDING (preparado), IN_FLIGHT (en envío), ACCEPTED (aceptado), RECEIVED
(recepción confirmada), UNCERTAIN, BLOCKED y DEFERRED (cuota pendiente).
RECEIVED requiere el identificador único de prueba (Message-ID RFC cuando se conserva, o UUID y número individual del asunto) y hash de From coincidentes en el
buzón receptor; los IDs internos Gmail de cuentas diferentes nunca se comparan.

Los aceptados/recibidos se omiten al reanudar. Un 403 de cuota deja DEFERRED con próxima
fecha; se conserva el contador, máximo tres intentos. Un 429 de envío, timeout, 5xx o
caída sin persistir respuesta queda incierto y exige reconciliación: un resultado vacío
inmediato no autoriza a repetir. La lectura del receptor puede confirmar un incierto.
Los bloqueados por permiso/API/autenticación requieren revisión, no un bucle automático.
Se envía secuencialmente con pausa de un segundo y presupuesto de 30 minutos.

## Robot y reporte consolidado

El lector solicita `list` con búsqueda por fecha/dataset, `maxResults=GMAIL_BATCH_SIZE`
y `nextPageToken`; los lotes de clasificación usan `BATCH_SIZE`, que es independiente.
Consulta `get(format=metadata)` por mensaje y usa historyId para cambios posteriores.
Historial 404 provoca una resincronización acotada, con deduplicación buzón+ID y commit
atómico de página/checkpoint. No marca leídos, etiqueta, mueve ni elimina mensajes.
Los reportes `[RPA-EP3]` quedan excluidos de los insumos.

Para un robot Gmail configura SOURCE=GMAIL, HOLIDAY_MODE=LIVE y MAIL_MODE=DRY_RUN primero.
`main.py run` genera el Excel y el HTML. El consolidado se envía solo con MAIL_MODE=SEND,
SEND_AUTHORIZED=true, REPORT_TO válido y ese destinatario en ALLOWED_RECIPIENTS. No hay
destinatario de reporte inventado en `.env`. El token receptor nunca se usa para enviar.
El remitente construye MIME con alternativa texto/HTML escapado y Excel adjunto verificado
por tamaño, SHA256 y cierre. PREPARADO/EN_ENVIO se persisten; HTTP 200 con ID produce
ACEPTADO, nunca entrega confirmada. Los errores ambiguos no se reintentan.

La API de feriados nacionales de Chile y `Referencia_API` permanecen. Las fechas se
guardan UTC y los plazos se calculan en America/Santiago. Excel COM es una comprobación
separada; openpyxl no demuestra uso de Excel de escritorio. REQUIRE_EXCEL=true obliga
a esa validación. Gmail permite enviar un XLSX sin COM; eso no acredita el requisito
académico de automatización de Excel. Debe validarse con la pauta del docente.

## Logs, recuperación y límites

SQLite mantiene eventos y contexto por llamada (rol, dataset, trabajo, HTTP y recuperación).
Los archivos rotativos contienen el mismo contexto sanitizado. Las esperas se registran
separadas de la duración activa. Supabase conserva el contrato existente de resumen e
intentos; los `.log` descargables tienen retención y no contienen secretos. No se borra
deduplicación, outbox o tokens al limpiar logs.

GET tiene máximo tres intentos persistentes, backoff con jitter, Retry-After y presupuesto.
Los POST de envío no usan ese mecanismo. Instalar y autenticar no envía mensajes.
Gmail conserva los límites del buzón personal (alrededor de 500/día), de recepción y de
cuota API. Consumo previo y controles de Gmail pueden impedir completar el lote; no hay
garantía de entrega ni de exactly-once del proveedor.

| Código/situación | Acción |
|---|---|
| GMAIL_API_DISABLED | Habilitar Gmail API en el proyecto del cliente descargado. |
| org_internal / access_denied | Revisar External, Testing y ambas cuentas en Test users. |
| GMAIL_DESKTOP_CLIENT_INVALID | Usar el JSON original de cliente Desktop. |
| AUTHORIZATION_FAILED | Revisar ventana Google/callback localhost; repetir autorización explícita. |
| AUTH_REQUIRED / 401 | Reautorizar el rol con --force; no enviar en bucle. |
| AUTH_SCOPE_MISMATCH | Autorizar el rol con los scopes documentados. |
| GMAIL_ACCOUNT_MISMATCH | Seleccionar el receptor correcto con --force. |
| GMAIL_PERMISSION_DENIED / 403 | Revisar permisos; no tratar como cuota. |
| GMAIL_DAILY_QUOTA | Esperar la fecha registrada; no cambiar cuenta para eludir límites. |
| 429, timeout o 5xx al enviar | Reconciliar recepción; no repetir automáticamente. |
| WORKBOOK_LOCKED | Cerrar el libro y reanudar la misma ejecución. |

## Fuentes verificadas

- https://developers.google.com/workspace/gmail/api/quickstart/python
- https://developers.google.com/workspace/gmail/api/auth/scopes
- https://developers.google.com/workspace/gmail/api/reference/rest/v1/users/getProfile
- https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list
- https://developers.google.com/workspace/gmail/api/guides/sync
- https://developers.google.com/workspace/gmail/api/guides/sending
- https://developers.google.com/workspace/gmail/api/guides/handle-errors
- https://support.google.com/cloud/answer/15549945
- https://support.google.com/mail/answer/22839

## Consolidado acumulado y envío separado del reporte

Después de confirmar los 500 mensajes, `scripts/exportar_campana.py --campaign UUID`
genera un Excel acumulado de todo el lote, incluso si llegó en varias ejecuciones.
Repetirlo reutiliza el archivo validado. No regenera adjuntos de envíos inciertos o aceptados.
`--limit 1` en el generador permite comprobar el primer mensaje del lote sin crear otro dataset.

El comando `scripts/enviar_reporte.py --campaign UUID --recipient DIRECCION` solo prepara
una vista previa. Añadir `--execute` envía un único consolidado y requiere que la dirección
está en ALLOWED_RECIPIENTS. Promueve únicamente el estado DRY_RUN ya preparado y valida
que el hash/tamaño no hayan cambiado. Repetir el comando no reenvía un aceptado o incierto.
No es necesario cambiar MAIL_MODE global para este comando explícito.

En la prueba final se usó GMAIL_LABEL=ALL, siempre limitado al dataset, para incluir los 172 mensajes de Spam. El modo ALL exige GMAIL_CAMPAIGN_TAG y no modifica etiquetas. Para presentar sin comandos, ver DEMO_PRESENTACION.md.
