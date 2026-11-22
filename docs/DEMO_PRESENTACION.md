# Demostración configurable del robot de correos

La ventana se abre con **[Abrir_Demo.cmd](../Abrir_Demo.cmd)**. Las simulaciones funcionan sin conexión y utilizan carpetas aisladas. Una campaña Gmail conserva su historial y exige confirmar cada tanda antes de enviar mensajes reales.

## Instalación

En Windows, con Python 3.12 o superior, abre PowerShell en el proyecto:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup.ps1
.\Abrir_Demo.cmd
```

La política Bypass solo afecta ese proceso de instalación. También puedes usar el entorno existente y ejecutar `.\.venv\Scripts\python.exe demo_presentacion.py`. Las dependencias del archivo `requirements-lock.txt` incluyen las pruebas. Copia `.env.example` a `.env` únicamente si aún no existe; no reemplaces credenciales ya configuradas.

## Las siete secciones

Los botones de Inicio permanecen sobre el estado de las conexiones. Los mensajes y los detalles tienen desplazamiento independiente; las acciones inferiores se distribuyen en varias filas si falta ancho. En las pestañas, usa las barras vertical y horizontal para acceder al contenido que no cabe. Después de actualizar el programa, cierra y vuelve a abrir `Abrir_Demo.cmd` para cargar la nueva interfaz.

| Sección | Uso |
| --- | --- |
| Inicio | Cuentas configuradas, autorización local, estado de cola Supabase y estimación de envíos |
| Simulación | Presets, distribución exacta, semilla, guardado y simulación |
| Campañas | Crear campaña sin enviar, seleccionar campañas anteriores y vista previa |
| Envío | Intervalo, máximo de intentos por tanda, confirmación y continuación |
| Recepción | Leer sin enviar y comparar resultados esperados con obtenidos |
| Reportes | Abrir reporte, CSV/JSON y simulaciones anteriores |
| Auditoría | Consultar logs y sincronizarlos con Supabase mediante una acción explícita |

**Modo PRESENTACIÓN** oculta los controles de configuración y deja visibles los contadores, etapa, progreso, últimos eventos y accesos a reportes. Puede activarse mientras se procesa una simulación. El trabajo se ejecuta en un hilo secundario y la ventana recibe cambios mediante una cola.

## Cantidades y presets

El total debe coincidir exactamente con normales + especiales. La suma de la distribución debe coincidir con los especiales. El programa rechaza valores negativos o inconsistentes; no ajusta las cifras silenciosamente.

| Preset | Total | Normales | Especiales | Modalidad |
| --- | --- | --- | --- | --- |
| Rápida | 12 | 9 | 3 | Simulación |
| Real | 24 | 18 | 6 | Gmail |
| Carga local | 300 | 240 | 60 | Simulación |
| Estrés local | 1.000 | 800 | 200 | Simulación |

La ventana comienza con el preset real de 24, sin ejecutarlo. **Aplicar preset** reemplaza las cantidades por los valores indicados. En Personalizado puedes editar cada campo. Elegir otra modalidad no modifica automáticamente la distribución: los fallos técnicos deben quedar en cero para preparar Gmail.

El intervalo real admite entre 1 y 60 segundos. El máximo por tanda limita cuántos mensajes se intentan en esa invocación, no los intentos de cada mensaje a lo largo de su vida. Se conserva el máximo persistente de tres intentos por mensaje y el bloqueo de envíos inciertos.

La semilla opcional reproduce los tipos, orden y contenido cuando se usa la misma configuración. La campaña real recibe un UUID nuevo en cada preparación, por lo que sus asuntos mantienen identificadores diferentes aun usando la misma semilla.

**Guardar configuración** conserva un JSON en `runtime/test_configs/<nombre>.json`. Para reemplazar uno existente se pide confirmación. El nombre admite letras sin tildes, números, guion y guion bajo. **Cargar configuración** recupera exactamente las cantidades, modalidad, semilla y controles de envío.

## Escenarios disponibles

| Tipo | Entorno permitido | Qué se comprueba |
| --- | --- | --- |
| Normal | Local o Gmail | Una de las seis categorías |
| Sin palabras clave | Local o Gmail | Otros es un resultado correcto |
| Dos categorías | Local o Gmail | Reclamo tiene prioridad sobre Consulta |
| Tildes | Local o Gmail | Normalización de Información |
| Mayúsculas y minúsculas | Local o Gmail | Urgente se reconoce sin distinguir capitalización |
| Texto comercial repetido | Local o Gmail | El texto puede coincidir, pero ID y asunto de campaña siguen siendo únicos |
| Sin ID, fecha inválida, metadatos incompletos | Solo local | Rechazo antes de guardar una página o adelantar su cursor |
| ID duplicado | Solo local | Una segunda ingestión no crea otra fila |
| HTTP 429, HTTP 500, timeout | Solo local | Reintentos acotados y agotamiento controlado mediante mocks |
| Fallo de autenticación | Solo local | Error simulado sin abrir Google |
| Feriados no disponibles | Solo local | Plazo no calculado y error explícito |
| Supabase no disponible | Solo local | Cola local conservada ante respuesta HTTP simulada |

Los fallos técnicos utilizan transportes simulados de httpx y bases aisladas. Las esperas de esos mocks se contabilizan sin dormir realmente. No provocan agotamiento de cuota, rechazos ni modificaciones en un buzón real. Una prueba negativa es exitosa si el programa detecta el fallo esperado.

## Demostración sin internet

1. En la sección 2 elige Rápida, Carga local o Estrés local y pulsa **Aplicar preset**.
2. Revisa el total, normales, especiales y distribución. Usa **Validar cantidades**.
3. Pulsa **Ejecutar simulación sin internet** y activa PRESENTACIÓN si deseas mostrar el progreso.
4. Comprueba las pruebas correctas, fallidas y pendientes, sin confundir fallos simulados con errores inesperados.
5. Abre el Excel y los resultados de la sección 6. Puedes repetir la simulación: cada vez usa otro directorio.

Comandos equivalentes:

```powershell
.\.venv\Scripts\python.exe scripts/escenarios_demo.py --preset quick
.\.venv\Scripts\python.exe scripts/escenarios_demo.py --preset load --seed 42
.\.venv\Scripts\python.exe scripts/escenarios_demo.py --preset stress
.\.venv\Scripts\python.exe scripts/escenarios_demo.py --config runtime/test_configs/mi_prueba.json
```

El último comando exige una configuración en modalidad SIMULATION. La simulación no carga ni modifica tokens, no llama a Gmail y desactiva la sincronización real de Supabase. Los escenarios técnicos se prueban separadamente; un caso con metadatos inválidos no aparece como un correo clasificado en la hoja Correos.

## Preparar y enviar una campaña autorizada

Autoriza ambas cuentas desde Inicio o mediante:

```powershell
.\.venv\Scripts\python.exe autenticar_gmail.py remitente
.\.venv\Scripts\python.exe autenticar_gmail.py receptor
```

El remitente usa permiso de envío y el receptor de lectura. Consulta [Google Cloud y Gmail](GOOGLE_CLOUD_GMAIL.md) para configurar el proyecto y sus usuarios de prueba. La revisión de estado local no refresca tokens ni comprueba el servidor; una autorización aparentemente vigente puede haber sido revocada remotamente.

Selecciona el preset Real o una configuración Gmail válida, prepara la campaña y abre **VISTA PREVIA**. Cada asunto conserva el identificador de campaña y secuencia, incluso cuando su texto comercial se repite.

En Envío puedes reducir el máximo de intentos para una tanda pequeña. Antes de comenzar se muestran remitente, receptor, campaña, total preparado, aceptados previos, pendientes, cantidad a intentar e intervalo. **Cancelar no envía nada.** El botón para detener nuevos envíos actúa entre peticiones y conserva los pendientes; no cancela una petición ya iniciada.

La estimación de uso del remitente cuenta eventos de campañas locales en las últimas 24 horas. **No representa la cuota oficial restante, no incluye envíos externos ni garantiza disponibilidad.** La aplicación se detiene ante rechazos o respuestas inciertas y no programa automáticamente una continuación para otro día.

## Comprobar recepción y continuar

Selecciona la campaña anterior y pulsa **Solo analizar / reanudar lectura**. Esta operación no envía correos. Con `GMAIL_LABEL=ALL`, la consulta incluye Spam y Papelera y exige una etiqueta de campaña. El robot no mueve ni marca mensajes.

Un resultado puede indicar 24 preparados, 24 aceptados, 22 recibidos y dos pendientes. Los especiales recibidos se validan; los que faltan siguen pendientes, no se cuentan como pruebas fallidas. Una clasificación Otros esperada se cuenta como correcta.

Para enviar el resto de una campaña usa la misma campaña en Envío. Los mensajes aceptados se omiten. Un `UNCERTAIN` exige revisión: si el análisis encuentra evidencia positiva puede marcarlo recibido; la ausencia en una consulta no habilita su reenvío automático. Crear otro lote no es reanudar el anterior.

## Excel y exportaciones

El archivo original `reporte.xlsx` y su manifiesto se conservan. El nuevo `reporte_pruebas.xlsx` mantiene Resumen, Correos, Referencia_API y Ejecuciones y agrega métricas y detalle de escenarios dentro de Resumen. No modifica un adjunto ya preparado o enviado.

`pruebas.json` y `pruebas.csv` contienen ID de escenario, tipo, categoría y resultado esperados, resultado obtenido, validación y motivo de fallo. No incluyen asuntos, direcciones ni credenciales. Los contadores separan normales, especiales, especiales comprobados, fallos técnicos simulados, fallos reales de envío/proveedor, duplicados y reintentos.

En Gmail, el tiempo acumulado suma las ejecuciones de envío y análisis de esa campaña. En simulación incluye lectura y comprobación de casos. El promedio divide ese tiempo por los casos ya validados, sin incluir los pendientes en el denominador. No es una medición del tiempo de tránsito de cada correo en Gmail.

## Logs y Supabase

Abre los logs desde la ventana o utiliza:

```powershell
.\.venv\Scripts\python.exe main.py logs-sync
.\.venv\Scripts\python.exe main.py logs-download --source LOCAL
.\.venv\Scripts\python.exe main.py logs-download --source SUPABASE
.\.venv\Scripts\python.exe main.py panel
```

Las consultas y sincronizaciones remotas requieren configuración y conexión. La simulación guarda su propia auditoría bajo `runtime/presentacion/` y no altera la base operativa. Los eventos técnicos simulados se identifican con origen `SIMULATED_TEST`.

## Errores comunes

| Situación | Acción |
| --- | --- |
| Total o distribución no coinciden | Corrige los campos; no se cambian automáticamente |
| Fallos técnicos en GMAIL | Cambia a SIMULATION o deja esos escenarios en cero y ajusta el resto explícitamente |
| AUTH_REQUIRED | Autoriza el rol correspondiente desde Inicio |
| AUTH_TRANSIENT | Revisa la conexión; el mensaje no pide introducir contraseñas en la aplicación |
| Campaña incierta o bloqueada | Consulta recepción y logs; no prepares otra campaña para duplicar el envío |
| Aún no vence la espera | Conserva la campaña y vuelve después de la fecha permitida |
| PARTIAL o tiempo agotado | Reanuda con la misma configuración; si se agotó el presupuesto acumulado, requiere revisión técnica |
| Excel abierto o bloqueado | Cierra el archivo antes de volver a generarlo |
| Supabase pendiente | La cola sigue en SQLite; sincroniza después sin reenviar correos |

## Qué usa servicios reales

| Operación | Red real | Envíos reales |
| --- | --- | --- |
| Simulación y pruebas pytest | No; transportes simulados | No |
| Preparar campaña y vista previa | No | No |
| Revisar estado local | No | No |
| Autorizar Gmail | Google OAuth y comprobación del receptor | No |
| Enviar tanda confirmada | Gmail | Sí, mensajes de prueba |
| Analizar Gmail | Gmail y feriados LIVE/caché | No |
| Sincronizar o descargar Supabase | Supabase | No |
| Enviar reporte con el comando específico | Proveedor configurado | Sí, operación separada |

Las cuatro hojas y los comandos anteriores siguen disponibles. Excel COM continúa dependiendo de tener Excel de escritorio instalado; openpyxl genera el reporte sin él. El [guion de 11 minutos](GUION_DEMO.md) permite presentar todo el flujo sin realizar envíos durante la exposición.
