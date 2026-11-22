# Prompt para Codex — Integrar Google Cloud y Gmail API en el robot EP3

Actúa como desarrollador senior de Python, automatización RPA, OAuth y Gmail API. Integra la configuración de Google Cloud ya preparada en mi proyecto de gestión de correos para la Evaluación Parcial 3 de ATY1102. Necesito archivos completos, instrucciones para Windows, pruebas reales documentadas y un flujo que pueda explicar.

Este documento actualiza la integración de correo de `PROMPT_CODEX_EP3_RPA_GESTION_CORREOS.md`: **Gmail API será el proveedor principal de lectura y envío**, en lugar de Microsoft Graph/Outlook. Conserva el resto del proyecto: clasificación con Regex, API pública de feriados, templates Excel/HTML, SQLite, auditoría temporal, recuperación, panel de logs, retención, rutas relativas y diagramas. No agregues TestFire. No implementes dos proveedores a la vez salvo que el repositorio ya tenga adaptadores útiles.

## 1. Estado conocido y qué debes comprobar

En Google Cloud se ha trabajado con lo siguiente:

| Elemento | Valor o estado |
| --- | --- |
| Nombre del proyecto | `RPA-Correos-EP3` |
| ID visible en la consola | `rpa-correos-ep3` |
| Servicio | Gmail API; el usuario indica que la habilitó. |
| Plataforma OAuth | Configuración inicial creada. |
| Público previsto | Externo, con usuarios de prueba para las cuentas que autoricen acceso. |
| Permisos indicados | `gmail.send` y `gmail.readonly`, agregados manualmente en Acceso a los datos. |
| Cliente OAuth | `RPA Correos Python`, de tipo Aplicación de escritorio; creación visible en consola. |
| Archivo de cliente | JSON descargado según confirmación del usuario. Ubicación local todavía por comprobar. |
| Cuentas autorizadas/token | Pendiente: no hay evidencia de que se haya ejecutado la autorización Python. |
| Envío real | Pendiente; no confundir creación del cliente con conexión o envío comprobado. |

No recrees el proyecto ni las credenciales por defecto. Inspecciona repositorio, instrucciones, entorno virtual y archivos sin imprimir secretos. Si existe `autenticar_gmail.py`, revísalo y reutilízalo. Ese archivo se entregó como punto de partida con sintaxis verificada; no se ha demostrado su ejecución con las cuentas reales.

Verifica que la API esté habilitada para el proyecto correcto y que cada cuenta que deba autorizar esté agregada a Usuarios de prueba. Si falta acceso a consola, guía al usuario de forma concreta y continúa con el código independiente. No pidas claves ni tokens en el chat.

## 2. Roles, OAuth y tokens separados

Implementa OAuth de aplicación de escritorio con las librerías oficiales:

```text
google-api-python-client
google-auth-httplib2
google-auth-oauthlib
```

Declara versiones compatibles verificadas en el proyecto e instala dentro del entorno virtual, sin romper dependencias actuales. Usa autorización en navegador con callback local y puerto disponible, acceso offline y selección explícita de cuenta durante la autorización inicial. Cada credencial permite actuar sobre la cuenta que autorizó, no sobre cualquier dirección incluida en `userId`.

| Rol | Permiso inicial | Archivo local |
| --- | --- | --- |
| Remitente de pruebas y reportes | `https://www.googleapis.com/auth/gmail.send` | `config/google/token_remitente.json` |
| Receptor cuya bandeja lee el robot | `https://www.googleapis.com/auth/gmail.readonly` | `config/google/token_receptor.json` |
| Cliente OAuth común | JSON de cliente tipo escritorio | `config/google/credentials.json` |

El mismo cliente puede usarse para obtener autorizaciones independientes de ambas cuentas. El receptor necesita autorizar porque el robot leerá su buzón; recibir mensajes sin lectura automatizada no exige ese paso.

Conserva la clasificación en SQLite y Excel. Con `gmail.readonly` no puedes marcar como leído, mover, etiquetar mensajes ni borrarlos. No agregues `gmail.modify` ni `https://mail.google.com/` por comodidad. Documenta cualquier permiso adicional necesario y justifícalo.

No uses API key, contraseña normal ni cuenta de servicio para sustituir OAuth en estas cuentas personales. No fijes direcciones reales en el código. Presenta claramente qué cuenta se debe elegir en cada autorización y cómo corregir una selección equivocada. No afirmes verificar la identidad mediante un método que exige permisos no concedidos: `users.getProfile` no está autorizado por `gmail.send` solo. Si se necesita verificación automática del remitente, diseña y documenta una comprobación con permisos adecuados; no los amplíes silenciosamente.

Carga tokens existentes y valida los permisos; refresca el access token cuando proceda. En operación normal no abras el navegador repetidamente. Si el refresh token falla de forma permanente, registra `AUTH_REQUIRED` y termina con instrucciones para reautorizar explícitamente. Evita que una tarea programada quede esperando un navegador. Distingue contraseña/token revocado, falta de permisos y fallo transitorio de red.

Documenta que una aplicación externa en modo Testing con permisos de Gmail puede requerir reautorizar a los siete días por caducidad del refresh token. No prometas acceso indefinido ni publiques la app para esquivar verificaciones.

## 3. Configuración y portabilidad

Resuelve rutas relativas desde una única `PROJECT_ROOT`, no desde el directorio actual de la terminal. El JSON descargado debe conservar su estructura original y colocarse en `config/google/credentials.json`; no reconstruyas su contenido con valores ficticios. Guarda tokens con permisos de acceso locales adecuados y escritura atómica. El ZIP académico y las descargas del panel nunca deben incluirlos.

Ejemplo de configuración sin secretos:

```dotenv
MAIL_PROVIDER=gmail
GMAIL_CREDENTIALS_PATH=config/google/credentials.json
GMAIL_SENDER_TOKEN_PATH=config/google/token_remitente.json
GMAIL_RECEIVER_TOKEN_PATH=config/google/token_receptor.json
GMAIL_SENDER_ADDRESS=REEMPLAZAR
GMAIL_RECEIVER_ADDRESS=REEMPLAZAR
REPORT_TO=REEMPLAZAR
MAIL_MODE=DRY_RUN
GMAIL_BATCH_SIZE=100
MAX_ATTEMPTS=3
HTTP_TIMEOUT_SECONDS=30
OAUTH_TIMEOUT_SECONDS=180
RUN_DEADLINE_SECONDS=1800
DISPLAY_TIMEZONE=America/Santiago
```

Las direcciones y el destinatario permitido deben configurarse localmente y validarse. Gmail `me` se resuelve con el token de cada rol. Agrega al `.gitignore` al menos:

```gitignore
.env
config/google/credentials.json
config/google/token*.json
```

Excluye también cualquier caché OAuth, export de secretos o archivo equivalente que detectes. No vuelques variables de entorno o errores completos del proveedor en la consola. Los IDs públicos de proyecto/cliente son distintos de secretos y tokens, pero no necesitas copiarlos a evidencias.

## 4. Separar generación de correos y procesamiento del robot

Hay dos flujos diferentes:

1. **Generador de insumos:** la cuenta remitente crea correos sintéticos dirigidos exclusivamente a la cuenta receptora autorizada. Debe ejecutarse por un comando aparte, con modo simulación por defecto, manifiesto persistente y número solicitado explícito. El usuario quiere preparar un lote de hasta **500 mensajes reales**; configura esa capacidad, pero no ejecutes 500 como efecto de instalar, autenticar, iniciar el robot o correr tests. Para una prueba real usa la cantidad y direcciones expresamente autorizadas en ese momento.
2. **Robot de gestión:** lee el buzón receptor, clasifica los insumos, consulta los feriados, genera un Excel y envía **un reporte consolidado** mediante el remitente a `REPORT_TO`. Procesar 500 mensajes no significa enviar 500 reportes.

Permite generar diferentes asuntos/categorías para probar Regex sin datos personales reales. Etiqueta cada mensaje de prueba con un identificador de dataset y un identificador individual, y el reporte con otro prefijo; evita que el reporte generado sea clasificado como nuevo insumo.

La aplicación debe poder procesar 100, 300, 500 y 1.000 registros en fixtures sin enviar esa cantidad por internet. Separa los comandos y resultados sintéticos de los resultados del proveedor.

## 5. Lectura eficiente con Gmail API

Adapta el lector existente a Gmail; no reutilices endpoints ni `@odata.nextLink`/`deltaLink` de Microsoft Graph.

- Usa `users.messages.list(userId="me", ...)` con el token receptor, búsqueda acotada al dataset y paginación por `nextPageToken`. El tamaño de lote interno y `maxResults` son configuraciones distintas; respeta el contrato actual.
- La lista devuelve principalmente IDs y thread IDs; usa `users.messages.get` para los campos requeridos. Para clasificación por asunto/remitente basta normalmente metadata; pide cuerpo solo si una regla lo necesita. Controla cuántas llamadas haces realmente y no descargues adjuntos indiscriminadamente.
- Persiste mensajes y avances para reanudar. Usa clave única por buzón e ID de mensaje. No dedupliques por asunto ni por thread ID, porque un hilo puede contener varios mensajes.
- El token de página no es un cursor incremental permanente. Para una primera versión admite búsqueda por fecha con solapamiento y deduplicación, o implementa `users.history.list` con `historyId` si aporta valor. Si el historial ya no está disponible y retorna 404, resincroniza dentro del alcance autorizado. No inventes un mecanismo delta de Graph.
- Avanza checkpoints solo cuando la página o conjunto correspondiente quedó almacenado de manera duradera. Reanuda pendientes tras interrupciones sin perder mensajes ni repetir efectos secundarios.
- Parseo de fechas con zona horaria y conversión a America/Santiago para presentación. Conserva el identificador y la fecha original cuando sea necesario; no guardes cuerpos en logs.
- Clasifica localmente: Solicitud, Consulta, Reclamo, Urgente, Información y Otros, con reglas versionadas y prioridad documentada.

## 6. Envío, límites y estados inciertos

Construye mensajes MIME con `EmailMessage`, HTML escapado desde template, alternativa de texto y adjunto cuando corresponda. Codifica para Gmail según contrato oficial y usa `users.messages.send` con el token remitente. Verifica destinatario permitido, origen, tamaño, hash y cierre del archivo antes de enviar.

**Google Cloud habilita la API, pero no elimina las restricciones de envío de Gmail.** Google documenta límites para cuentas personales alrededor de 500 mensajes diarios y posibles restricciones por velocidad de recepción. El consumo previo y otros controles afectan la prueba; no garantices que 500 mensajes se enviarán de una vez ni que llegarán sin problemas. Distingue límite del buzón, cuota de API y límite de concurrencia. Una API habilitada y un OAuth válido no garantizan entrega.

Haz persistente un `send_job_id` antes de llamar al proveedor y registra estados:

```text
PREPARADO → EN_ENVIO → ACEPTADO → RECEPCION_CONFIRMADA
                   ↘ ENVIO_INCIERTO
                   ↘ ERROR / PENDIENTE_CUOTA
```

El identificador devuelto por Gmail acredita la aceptación de la solicitud, no la entrega al receptor. Confirma recepción con la lectura autorizada de la otra cuenta, correlacionando un identificador único de prueba o cabecera RFC Message-ID cuando el proveedor la conserve. No compares directamente IDs internos entre dos buzones: no son una clave compartida.

La API de envío no ofrece una garantía propia de exactly-once por usar un UUID local. Si la conexión cae después de enviar y antes de registrar la respuesta, deja estado incierto y reconcilia antes de repetir. Con el alcance send-only no puedes buscar en Enviados del remitente; usa lectura del receptor cuando sea suficiente o deja revisión explícita. Un resultado de búsqueda vacío inmediato no prueba que el mensaje no fue aceptado. Evita reintentos automáticos ambiguos tanto en tu código como en la librería.

En el generador, guarda estado por mensaje. Si se alcanza una cuota, termina con los pendientes y permite continuar después sin duplicar los aceptados. No cambies de cuentas/proyectos ni intentes eludir límites para completar el lote.

## 7. Reintentos y auditoría temporal

Conserva los registros de SQLite, archivos descargables y sincronización Supabase si ya existe. Si Supabase no está configurado, no inventes proyecto, conexión ni migraciones aplicadas; documenta el pendiente y conserva la operación local.

Por cada llamada/intento registra ejecución, dataset o trabajo, paso, rol, equipo, fecha UTC de inicio y término, duración monotónica en ms, intento, estado, código HTTP, razón de error sanitizada y decisión de recuperación. Distingue tiempo de espera y tiempo activo. No guardes tokens, Authorization headers, contraseñas, cuerpos ni PII innecesaria.

- Inicialmente **3 intentos totales por operación**, con timeout y presupuesto temporal global.
- Reintenta solo errores transitorios que sea seguro repetir; aplica backoff exponencial limitado con jitter y respeta `Retry-After` si existe.
- Distingue razones de error HTTP 403: falta de permiso o API deshabilitada no se tratan como un 429; una cuota diaria agotada queda pendiente en lugar de generar un bucle.
- Un 401 puede requerir refrescar una vez; si la credencial sigue inválida, marca autenticación requerida. No lances OAuth de navegador dentro de cada reintento.
- Para enviar, la política de estado incierto prevalece sobre la regla genérica de reintentos.
- La reanudación no debe resetear indefinidamente los intentos persistidos. El scheduler y el botón Reintentar deben respetar los límites.
- Un segundo proceso del mismo perfil no debe iniciar el mismo trabajo a la vez. Conserva deduplicación y pendientes al limpiar logs.

Mantén el panel en localhost, exporta solo datos sanitizados, y exige selección y confirmación antes de borrar originales. No borres tokens mediante la limpieza de logs ni borres claves de recuperación/deduplicación.

## 8. Mantener los requisitos de EP3

Conserva la API pública de feriados de Chile para enriquecer plazos de atención y la hoja `Referencia_API`. Gmail es el canal de correo; no lo uses como sustituto de la referencia externa de negocio.

Conserva `templates/reporte_base.xlsx` y `templates/correo_reporte.html`, escritura de Excel por bloques, clasificación, auditoría, ética y sostenibilidad. Demuestra una interacción real con **Excel de escritorio**. Si el informe anterior describía Outlook, actualízalo para describir Gmail API, sin afirmar que se usó Outlook. Contrasta el cambio con las instrucciones del docente y señala cualquier requisito de herramienta que aún deba validarse.

Actualiza diagramas editables y exportados: arquitectura con Google OAuth/Gmail, flujo secuencial con subprocesos, secuencia de remitente/receptor y estados de envío/reanudación. Distingue configuración, autorización, lectura y envío; no presentes Google Cloud como servidor que aloja el robot local.

## 9. Archivos y comandos de entrega

Adapta la estructura existente; propuesta mínima:

```text
autenticar_gmail.py
modules/gmail_auth.py
modules/gmail_reader.py
modules/gmail_sender.py
scripts/generar_correos_prueba.py
config/google/                   # Credenciales y tokens locales excluidos
config/reglas.*
templates/reporte_base.xlsx
templates/correo_reporte.html
tests/
docs/GOOGLE_CLOUD_GMAIL.md
docs/PRUEBAS_GMAIL.md
docs/diagramas/
.env.example
.gitignore
requirements.txt
README.md
```

No impongas rutas nuevas si ya hay una organización coherente. Expón comandos claros para autorizar remitente/receptor, diagnosticar conexión, ejecutar dry run, probar lectura, generar insumos controlados y ejecutar el reporte. Conserva compatibilidad de `python autenticar_gmail.py remitente` y `python autenticar_gmail.py receptor` si ese helper ya existe. No generes tokens ficticios.

Documenta problemas frecuentes: API deshabilitada en el proyecto incorrecto, cuenta fuera de usuarios de prueba, permisos insuficientes, JSON de otro tipo, callback local bloqueado, autorización vencida, 401/403/429, Excel bloqueado y cuota diaria. Los diagnósticos deben ser útiles sin exponer secretos. Instalar librerías y revisar sintaxis no equivale a autenticar una cuenta.

## 10. Criterios de aceptación y cierre

- [ ] Proyecto/cliente existentes reutilizados; ubicación del JSON comprobada sin divulgar su contenido.
- [ ] Dos roles con tokens y permisos mínimos separados; refresh y reautorización explícita sin bucles.
- [ ] Lectura paginada real comprobada y clasificación local sin cambios no autorizados al buzón.
- [ ] Envío controlado con aceptación registrada y recepción confirmada cuando se pudo comprobar.
- [ ] Generador separado capaz de preparar un lote de hasta 500, con dry run y reanudación; ningún envío masivo se ejecuta por defecto.
- [ ] Fixtures de 100/300/500/1.000, duplicados, interrupciones, expiración de credenciales, cuota agotada y envío incierto cubiertos.
- [ ] Rutas relativas, secretos fuera de Git/ZIP/panel, logs en DB/archivos y tiempos por intento.
- [ ] Templates, API pública, Excel de escritorio, diagramas e informe EP3 actualizados.
- [ ] Se distingue IMPLEMENTADO, PROBADO_REAL, PROBADO_CON_FIXTURES, PENDIENTE y BLOQUEADO.

Empieza inspeccionando lo existente, presenta el plan breve y continúa con la integración autorizada. Prepara y prueba primero todo lo que no envía mensajes. Para un envío real requiere destinatario y cantidad explícitos ya autorizados, y no supongas que solicitar este prompt autoriza a ejecutarlo. Cierra con archivos completos, comandos exactos y pruebas reales realizadas; no prometas que desaparecerán los límites o las verificaciones de Google.

### Fuentes oficiales para verificar la implementación

- [Python y OAuth de escritorio](https://developers.google.com/workspace/gmail/api/quickstart/python)
- [Permisos de Gmail](https://developers.google.com/workspace/gmail/api/auth/scopes)
- [Usuarios de prueba y caducidad](https://support.google.com/cloud/answer/15549945)
- [Listado paginado](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list)
- [Sincronización](https://developers.google.com/workspace/gmail/api/guides/sync)
- [Envío](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/send)
- [Manejo de errores](https://developers.google.com/workspace/gmail/api/guides/handle-errors)
- [Límites de Gmail](https://support.google.com/mail/answer/22839)
