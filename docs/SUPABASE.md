# Conexión Supabase y ciclo de vida de los logs

## Configuración

El archivo `.env` local contiene las opciones del robot. No forma parte de Git ni del ZIP. Completar:

```dotenv
SUPABASE_URL=https://TU_PROYECTO.supabase.co
SUPABASE_SECRET_KEY=sb_secret_TU_CLAVE_PRIVADA
SUPABASE_ENABLED=true
LOG_SYNC_MAX_ATTEMPTS=3
LOG_SYNC_SECONDS=30
LOG_DOWNLOAD_DAYS=15
AUTO_CLEAN_LOGS=true
LOG_CLEANUP_INTERVAL_SECONDS=3600
```

Los valores anteriores ilustran el formato y no son credenciales válidas. La URL se obtiene en la configuración/API del proyecto y la clave debe ser una secret key de servidor. No pegar la clave en conversaciones ni agregarla a JavaScript. La configuración oculta este campo al representar Settings.

Ejecutar la migración `supabase/migrations/202611170001_rpa_logs.sql` en el SQL Editor del proyecto que se desea usar. Crea únicamente `public.rpa_logs` e índices; activa RLS, revoca acceso a anon/authenticated y concede select/insert/update al rol de servidor. La clave secreta tiene privilegios amplios en el proyecto: conservarla solo en el equipo de confianza; el panel local no la recibe. No se creó ni modificó ningún proyecto remoto sin conexión confirmada.

## Qué se guarda

Cada fila incluye instalación, ejecución, tipo de registro (resumen o paso), inicio/fin UTC, duración_ms, intento, reintentos, estado, nivel, código y origen. El resumen añade procesados, clasificados, fallidos y estado de envío. La duración del resumen es el tiempo activo de procesamiento acumulado, antes de sincronizar logs; la duración de cada paso se mide con reloj monotónico. Un fallo transitorio permanece visible aunque la ejecución termine COMPLETADO.

No se replican cuerpos, asuntos, direcciones, host, tokens, enlaces de continuación ni adjuntos. El estado operativo permanece en SQLite. La pérdida temporal de red no autoriza volver a leer o enviar un reporte: únicamente deja logs pendientes en la cola.

## Reintentos sin bucles

Cada registro tiene ID estable y payload identificado por hash. Se usa POST upsert (`on_conflict=id`) para que una respuesta incierta pueda reconciliarse repitiendo el mismo ID sin duplicar filas.

Antes de cada petición se persiste el intento y el estado IN_FLIGHT. Una llamada a logs-sync envía un máximo configurable de lotes (cinco por defecto) dentro de un presupuesto de 30 segundos. Ante un error, termina esa invocación y agenda otra fecha. 429 respeta Retry-After, red/5xx usan espera exponencial; no hay espera activa ni llamadas en bucle. Se permiten tres intentos totales por registro, incluso entre reinicios. Los errores permanentes quedan BLOCKED; los agotados quedan REVIEW. La descarga manual tiene máximo 20 páginas y no reintenta automáticamente.

La fecha pendiente se comprueba en la próxima llamada a logs-sync o al finalizar otra ejecución del robot; no se instala un temporizador de sincronización en segundo plano. El temporizador del panel se limita a la limpieza de archivos. Se configura un proyecto Supabase por runtime; para cambiar de proyecto conservando una trazabilidad independiente, usar otro RUNTIME_DIR.

Un resumen ya sincronizado puede recibir una nueva versión al reanudar una ejecución; sus eventos anteriores siguen siendo inmutables. Una modificación de un resumen pendiente/bloqueado no reinicia sus intentos. Los estados REVIEW/BLOCKED requieren diagnóstico y reparación explícita de la cola; logs-sync por sí solo no los desbloquea. Para conocer la causa, consultar `code`, `attempts` y `next_attempt` en log_outbox sin modificar la base durante una ejecución.

## Archivos y borrado

El robot guarda automáticamente una copia JSON Lines `.log` al cerrar cada ejecución. El panel y `logs-download` pueden crear otras copias desde SQLite o Supabase. Se escriben en `<RUNTIME_DIR>/logs/descargas/` con nombre generado, hash y vencimiento registrado. La descarga remota se limita a la instalación local; opcionalmente se filtra con `--execution-id UUID`.

Las copias vencen 15 días después de crearlas. La limpieza ocurre al cerrar el robot, iniciar el panel y cada hora con el panel abierto. `logs-clean` permite ejecutarla manualmente. Si no hay un proceso abierto, los archivos vencidos se eliminarán en la próxima ejecución; no se instaló un servicio ni una tarea programada.

Se borran solo archivos registrados y no modificados, o logs rotativos reconocidos de ejecuciones cerradas que superen su retención por nivel. Archivos personales, enlaces/junctions, logs activos o archivos cuyo hash cambió quedan fuera. El borrado deja un resumen en cleanups. SQLite, Supabase, mensajes, cursores, pendientes y envíos no se eliminan. La retención de la base remota es independiente y no se configura mediante LOG_DOWNLOAD_DAYS.

## Verificación

Conexión real verificada el 18 de noviembre de 2026: lectura de esquema HTTP 200, 9 registros locales coincidentes con los remotos, upsert repetido sin duplicados, segunda sincronización sin peticiones, descarga validada por contenido/hash y acceso sin clave rechazado con HTTP 401. Evidencia sanitizada: `docs/evidence/supabase_real_checks.json`. No se enviaron correos. El rechazo sin clave es una comprobación de acceso API y no una auditoría completa de las políticas RLS.

```powershell
.\scripts\run.ps1 logs-sync
.\scripts\run.ps1 logs-download --source SUPABASE --execution-id UUID
.\scripts\run.ps1 panel
.\.venv\Scripts\python.exe scripts/verify_supabase.py
```

Revisar estado SYNCED y las filas en Table Editor. Ejecutar de nuevo logs-sync: una fila sin cambios no se vuelve a insertar. No declarar conexión real hasta ver respuestas válidas del proyecto configurado.

Las pruebas `tests/test_cloud_logs.py` usan HTTP simulado para verificar contrato, idempotencia, 429, timeout ambiguo, límites persistentes, recuperación IN_FLIGHT, descarga y retención. El resultado de estas pruebas no acredita conectividad remota.

`verify_supabase.py` es una prueba real explícita: sincroniza los logs de la instalación, vuelve a escribir un ID existente para comprobar idempotencia y guarda una descarga. No elimina filas ni ejecuta el flujo de correo. La suite pytest permanece aislada de las credenciales del `.env`, incluido el lanzador probado desde otra carpeta.

Fuentes oficiales: [REST de Supabase](https://supabase.com/docs/guides/api), [API keys](https://supabase.com/docs/guides/getting-started/api-keys), [upsert](https://supabase.com/docs/reference/python/upsert). El adaptador utiliza la secret key en el header apikey, sin tratarla como JWT Bearer.
