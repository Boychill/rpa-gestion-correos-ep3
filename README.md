# Robot RPA de gestión de correos · EP3

Proyecto Python para leer metadatos de correo, clasificar seis categorías, calcular plazos con feriados de Chile, producir un Excel y preparar un reporte consolidado. Incluye SQLite, recuperación, auditoría y panel local. **El modo inicial es sintético y DRY_RUN: no envía correos.**

**Para usarlo por primera vez:** [Cómo utilizar el programa](COMO_UTILIZAR.md), con el recorrido por la ventana, simulación, campañas Gmail, reportes, logs y solución de problemas.

**Revisión final: 144 pruebas aprobadas.** [Informe de entrega](docs/REVISION_FINAL.md). Incluye envío del Excel desde Reportes con vista previa y confirmación, contadores completos, progreso optimizado, auditoría ampliada opcional y GitHub Actions aprobadas en Windows/Python 3.12 y 3.13. La evidencia vigente de la suite está en `docs/evidence/revision_final_pytest.xml`. Esta fase no realiza nuevos envíos reales.

**Validación inicial del 23/11/2026 (histórica):** 127 pruebas aprobadas; escenarios locales de 12, 300 y 1.000 casos correctos; lectura real de Gmail y esquema Supabase comprobados. En esa fase no se enviaron correos. Excel/Outlook COM no están disponibles en este equipo. [Resultados y límites](docs/VALIDACION_2026-11-23.md).

**Prueba real posterior, autorizada el mismo día:** 3 correos enviados, recibidos en la bandeja de entrada y clasificados correctamente; reporte Excel verificado, análisis repetido sin duplicados y 32 registros de auditoría comprobados en Supabase. [Evidencia del envío real](docs/evidence/prueba_real_3_20261123.json).

**Prueba real de 300 correos:** 300 enviados, recibidos y clasificados correctamente; 248 en Recibidos y 52 en Spam. Los 60 escenarios especiales se validaron, sin duplicados ni reintentos; se verificaron el Excel y 634 registros en Supabase. [Evidencia del lote de 300](docs/evidence/prueba_real_300_20261123.json).

Para entender la estructura, reglas de negocio, flujo completo, estados y límites, consulta
[Funcionamiento y estructura del proyecto](docs/EXPLICACION_PROYECTO.md).

## Pruebas configurables y presentación

La ventana incluye siete secciones y modo PRESENTACIÓN. Permite definir normales,
especiales y distribución exacta, guardar configuraciones, usar una semilla y preparar
campañas Gmail con vista previa y confirmación por tanda. Presets: 12/3, 24/6,
300/60 y 1.000/200 (total/especiales). Los fallos técnicos solo se ejecutan localmente
con mocks; las campañas reales conservan el límite de 500 y sus estados históricos.

```powershell
.\Abrir_Demo.cmd
.\.venv\Scripts\python.exe scripts/escenarios_demo.py --preset quick
.\.venv\Scripts\python.exe scripts/escenarios_demo.py --preset stress --seed 42
```

Estas simulaciones no envían correos ni usan servicios reales. Generan CSV, JSON y
un Excel de pruebas con las cuatro hojas originales. La guía completa está en
[DEMO_PRESENTACION.md](docs/DEMO_PRESENTACION.md), con un
[guion de 11 minutos](docs/GUION_DEMO.md). El envío del reporte final sigue siendo
una operación separada de las campañas. La estimación local de envíos de las últimas
24 horas no representa la cuota oficial de Gmail.

Resumen de implementación, pruebas y límites:
[Entrega de mejoras de presentación](docs/ENTREGA_MEJORAS_PRESENTACION.md).

## Inicio en Windows

Para presentar el programa, abre **[Abrir_Demo.cmd](Abrir_Demo.cmd)**. Incluye simulación
sin envíos, preparación de lotes Gmail, envío con progreso, análisis y acceso al Excel.
Guía breve: [docs/DEMO_PRESENTACION.md](docs/DEMO_PRESENTACION.md).

Requiere Python 3.12 o superior compatible. Se verificó con Python 3.13.14 en Windows. Abra PowerShell en esta carpeta:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
.\scripts\run.ps1 run
.\scripts\run.ps1 panel
```

El panel escucha en `http://127.0.0.1:8000`. Cierre con Ctrl+C. `ExecutionPolicy Bypass` solo afecta el proceso del lanzador; no cambia la política del equipo. Si la organización lo prohíbe, use directamente Python:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe main.py init
.\.venv\Scripts\python.exe main.py run
```

`setup.ps1` no crea tareas, no abre un buzón y no habilita envíos. El lock contiene también herramientas para pruebas/PDF/PPTX. Para instalar solo ejecución, use `requirements.txt`.

Desde otra carpeta puede invocar `& 'C:\ruta con espacios\RPA\scripts\run.ps1' run`; todas las rutas se resuelven desde `main.py`. El archivo `.env` se busca allí, nunca en la carpeta actual. El entorno del proceso tiene precedencia. Copie `.env.example` a `.env` si desea personalizarlo.

## Qué está verificado

- Versión actual: [validación del 23/11/2026](docs/VALIDACION_2026-11-23.md), con suite completa, interfaz, escenarios, capacidad y conexiones de lectura. Las evidencias anteriores que siguen son históricas.
- Flujo sintético completo, pruebas de fallo y capacidad 100/300/500/1.000: `docs/evidence/pytest.xml` y `benchmark.json`.
- API real de feriados Chile 2026/2027: `docs/evidence/api_CL_*.json`.
- Excel COM no disponible en el equipo de implementación: `docs/evidence/real_checks.json`.
- Gmail real: 500 aceptados, recibidos y clasificados, sin duplicados; evidencia en docs/PRUEBAS_GMAIL.md.
- La pauta oficial EP3 y el texto base mencionados en el prompt no se entregaron. La matriz es provisional y no acredita cumplimiento de una pauta no revisada.

Consulte `docs/INFORME.md`, `docs/MATRIZ_EP3.md`, `docs/PRUEBAS_REALES.md` y `docs/FUENTES.md`. Los entregables generados están en `dist/`.

## Ejecución, resultados y recuperación

Cada ejecución devuelve un UUID. Los resultados del flujo base están en `output/<UUID>/`: `reporte.xlsx`, vista previa HTML, manifiesto del adjunto y `resultado.json`. Las simulaciones de presentación usan `output/presentacion/` y añaden `reporte_pruebas.xlsx`, CSV y JSON de escenarios. Las cuatro hojas se llaman Resumen, Correos, Referencia_API y Ejecuciones; los metadatos privados se redactan en el reporte. La plantilla original se conserva.

```powershell
.\scripts\run.ps1 run --count 1000
.\scripts\run.ps1 run --resume UUID
```

La segunda ejecución incremental sin novedades devuelve `NO_CHANGES` y no prepara otro reporte. Un resultado `PARTIAL` bloquea una nueva ejecución del perfil hasta reanudar la misma. Se conserva la configuración relevante mediante firma. Si cambió, restaure la configuración original antes de reanudar; no borre SQLite para desbloquearlo. El presupuesto activo acumulado y los intentos HTTP agotados no se reinician en una reanudación: al agotarse requieren intervención técnica, no un bucle. Conserve una copia de la base antes de una reparación manual.

El lock de perfil y el lock del estado SQLite evitan ejecuciones simultáneas en el mismo runtime. Una ejecución pendiente debe completarse antes de iniciar otro perfil en esa misma base; para perfiles independientes use directorios runtime separados. Cada página se confirma con su cursor; se deduplica por origen, buzón e ID. Los cambios reales de metadatos se diferencian mediante fingerprint. Un movimiento/eliminación de la carpeta actualiza el estado local. Se reanuda la clasificación de los snapshots de esa ejecución.

`PREPARADO` interrumpido se convierte en `ENVIO_INCIERTO`, incluso si el correo posiblemente no salió. Ninguno se reenvía automáticamente. `ACEPTADO` significa aceptación del proveedor (Gmail HTTP 200 con ID); no prueba entrega. La entrega requiere evidencia independiente:

```powershell
.\scripts\run.ps1 reconcile UUID --state ENTREGA_CONFIRMADA --evidence 'C:\evidencia\recepcion-redactada.txt'
```

La reconciliación es una declaración del operador respaldada por hash; el robot no interpreta el contenido como prueba ni modifica el XLSX adjuntado.

## Configuración de integraciones reales

Use [docs/GOOGLE_CLOUD_GMAIL.md](docs/GOOGLE_CLOUD_GMAIL.md) para autorizar remitente y receptor, diagnosticar y configurar el reporte Gmail. MAIL_MODE=DRY_RUN es el valor inicial. El envío requiere destinatario permitido y feriados LIVE. REQUIRE_EXCEL=true exige la comprobación de escritorio; su ausencia permanece visible como pendiente académico. Los adaptadores Microsoft existentes se conservan como compatibilidad.

Reglas en `config/reglas.json`: prioridad Urgente → Reclamo → Solicitud → Consulta → Información → Otros. Se normalizan tildes y mayúsculas y se comparan palabras completas. No se ejecutan expresiones regulares arbitrarias ni instrucciones de mensajes. Solo el asunto se usa para clasificar; casos sin señal van a Otros. La versión queda guardada. Cambiar reglas no reclasifica automáticamente el historial ya enviado.

El plazo interno excluye el día de recepción y avanza días de lunes a viernes, excluyendo feriados nacionales Public. Usa America/Santiago y carga cada año atravesado; los feriados regionales no están incluidos. Un año ausente o una caché vencida sin API válida deja plazo nulo y bloquea el envío. El fixture solo tiene cuatro feriados sintéticos por año: no es un calendario oficial.

## Auditoría, privacidad y mantenimiento

SQLite está en `runtime/state.sqlite3`. Su estado contiene metadatos privados (incluido asunto) necesarios para reanudar; no lo publique. Los remitentes se seudonimizan; los cuerpos y adjuntos recibidos no se persisten. Los tokens OAuth se almacenan cifrados por separado en config/google. Proteja `runtime/`, `.env` y `output/` con permisos de usuario Windows y cifrado de disco cuando corresponda. SQLite no está cifrado por esta aplicación. El ZIP de entrega excluye todo el estado privado.

El panel muestra eventos sanitizados, filtros, uso y exportaciones log/csv/json/zip, con límite visible de 10.000 eventos por descarga. Para limpiar: seleccionar logs vencidos → generar ZIP y verificar manifiesto → descargar y verificar copia → marcar confirmación y escribir `ELIMINAR <ID>`. El servidor no puede demostrar que el navegador guardó el archivo. Se rechazan archivos activos, rutas arbitrarias, enlaces/junctions y hashes alterados.

Retención inicial: DEBUG 7, INFO 15, ERROR 30 días. Las ejecuciones en revisión/pendientes permanecen protegidas. Las copias descargadas caducan a los 15 días. AUTO_CLEAN_LOGS aplica la limpieza al terminar el robot, al abrir el panel y cada hora mientras esté abierto. Con el programa cerrado, se ejecuta en la próxima apertura; también existe `main.py logs-clean`. Exportaciones ZIP temporales: 7 días; historial analítico: 90 días sugeridos, sin purga automática de bases. `scripts/maintenance.py` ofrece previsualización, respaldo verificable y purga separada de eventos no protegidos. Ninguna limpieza de logs toca claves de deduplicación, cursores, mensajes, outbox ni auditoría SQLite. No hay tarea programada instalada.

## Historial en Supabase

La integración guarda tiempo de inicio/fin, duración en milisegundos, estado COMPLETADO/FALLIDO/REVISION, intento y reintentos. Se separa un intento fallido recuperado del resultado final. SQLite conserva la recuperación y la cola si no hay conexión. El panel incorpora botones para sincronizar, guardar logs y descargarlos desde Supabase a `runtime/logs/descargas/`.

Conexión real comprobada el 18/11/2026: 9 registros, lectura/escritura, idempotencia y descarga verificada. Evidencia: `docs/evidence/supabase_real_checks.json`. Para repetir explícitamente esta comprobación: `.\.venv\Scripts\python.exe scripts/verify_supabase.py`. La suite pytest utiliza HTTP simulado y no toma tus credenciales reales para sincronizar.

El 23/11/2026 se volvió a comprobar la lectura del esquema con HTTP 200, sin escribir ni sincronizar la cola operativa. Esta consulta no vuelve a acreditar las pruebas históricas de escritura.

1. Completar `SUPABASE_URL` y `SUPABASE_SECRET_KEY` en `.env` (privado y excluido de Git/ZIP).
2. Ejecutar `supabase/migrations/202611170001_rpa_logs.sql` en el SQL Editor del proyecto elegido.
3. Establecer `SUPABASE_ENABLED=true` y ejecutar `scripts/run.ps1 logs-sync`.

La secret key comienza con `sb_secret_`; se usa solo en Python y nunca se muestra en el panel. No se incluyó una clave ficticia. Sin valores reales, la conexión permanece deshabilitada.

```powershell
.\scripts\run.ps1 logs-sync
.\scripts\run.ps1 logs-download --source LOCAL
.\scripts\run.ps1 logs-download --source SUPABASE
.\scripts\run.ps1 logs-clean
```

Máximo tres intentos persistentes por registro; cada invocación está acotada por lotes y tiempo. Un 429 agenda el siguiente intento respetando Retry-After. 401/403 bloquean el registro; al agotar intentos pasa a REVIEW. Reabrir el programa no reinicia el contador. Las descargas remotas no reintentan automáticamente y se limitan a 20 páginas; si exceden el límite, se debe filtrar por ejecución. Más detalles y límites en `docs/SUPABASE.md`.

## Gmail: lote de 500 mensajes y análisis

La integración Gmail usa OAuth de escritorio, lectura de metadatos e historial incremental.
`scripts/gmail_demo.py` prepara, envía y analiza lotes sintéticos con estado persistente por
mensaje; detiene los envíos inciertos para evitar duplicados. Instrucciones y resultados
en [docs/GMAIL_PRUEBAS.md](docs/GMAIL_PRUEBAS.md). Requiere autorizar el remitente y el receptor.

## Pruebas y entregables reproducibles

```powershell
.\.venv\Scripts\python.exe -m pytest --junitxml=docs/evidence/pytest.xml
.\.venv\Scripts\python.exe scripts/benchmark.py
.\.venv\Scripts\python.exe scripts/verify_real.py
powershell -ExecutionPolicy Bypass -File scripts/render_diagrams.ps1
.\.venv\Scripts\python.exe scripts/build_deliverables.py
```

`verify_real.py` solo consulta la API pública y prueba una copia sintética de la plantilla con Excel COM; no envía correo. El benchmark genera páginas deterministas de 100, 300, 500 y 1.000 mensajes y usa bases temporales. No compara su resultado con Gmail real. El ZIP usa selección explícita de fuentes, manifiesto SHA256 y fechas normalizadas; no empaqueta `.env`, tokens, logs privados, `.venv`, runtime ni output. Los documentos y sus cifras deben regenerarse después de nuevas pruebas.

La exportación de diagramas usa Node/npm, Mermaid CLI 12.2.0 y Edge instalado; `-BrowserPath` permite indicar Chrome. No descarga otro navegador. Las fuentes `.mmd` y las exportaciones SVG/PNG/PDF ya se incluyen en la entrega. El script de documentos requiere esas exportaciones y evidencia de pruebas vigente.

Mantenimiento separado (la primera orden solo previsualiza):

```powershell
.\.venv\Scripts\python.exe scripts/maintenance.py preview
.\.venv\Scripts\python.exe scripts/maintenance.py backup
# Solo después de revisar la selección y conservar el respaldo:
.\.venv\Scripts\python.exe scripts/maintenance.py purge-events --confirm PURGAR_EVENTOS_NO_PROTEGIDOS
.\.venv\Scripts\python.exe scripts/maintenance.py expire-exports --confirm ELIMINAR_EXPORTACIONES_VENCIDAS
```
