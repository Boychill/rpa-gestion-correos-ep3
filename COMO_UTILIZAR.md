# Cómo utilizar el proyecto RPA de correos

Guía de operación actualizada el **23 de noviembre de 2026**. Para empezar, abre `Abrir_Demo.cmd` y realiza la simulación rápida descrita abajo. No necesitas Gmail ni Supabase para esa demostración.

## 1. Abrir el programa

1. Abre la carpeta del proyecto y ejecuta **[Abrir_Demo.cmd](Abrir_Demo.cmd)**.
2. Si indica que falta el entorno Python, abre PowerShell en esa carpeta y ejecuta:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
   .\Abrir_Demo.cmd
   ```

3. Si la ventana no aparece, ejecútala desde PowerShell para ver el error:

   ```powershell
   .\.venv\Scripts\python.exe demo_presentacion.py
   ```

Se requiere Windows con Python 3.12 o superior compatible. Se probó con Python 3.13.14. La instalación prepara dependencias y plantilla; no envía correos. Conserva el `.env` existente. En una instalación nueva, usa `.env.example` como referencia y consulta las guías de integración antes de configurar cuentas.

La ventana tiene siete pestañas. Los botones de Inicio están sobre los mensajes; los detalles y formularios tienen barras de desplazamiento. En ventanas pequeñas, los accesos inferiores se reparten en varias filas. Después de una actualización, cierra y vuelve a abrir el programa.

## 2. Hacer la primera demostración sin internet

1. Entra en **2 Simulación**.
2. Selecciona **Rápida: 12 / 3 especiales** y pulsa **Aplicar preset (reemplaza cantidades)**. Seleccionar el nombre por sí solo no aplica sus valores.
3. Comprueba modalidad `SIMULATION`, total **12**, normales **9** y especiales **3**. La suma de los tipos especiales debe ser **3**.
4. Pulsa **Validar cantidades** y después **Ejecutar simulación sin internet**.
5. Puedes activar **Modo PRESENTACIÓN** durante la ejecución. Vuelve a pulsarlo para recuperar las pestañas.
6. Al terminar, comprueba **12 casos correctos**, **0 fallidos** y **0 pendientes**. Son datos sintéticos: aceptados y recibidos de Gmail permanecen en cero.
7. Pulsa **Abrir Excel**. En **5 Recepción** puedes revisar la comparación entre resultado esperado y obtenido.

Esta operación genera datos, los clasifica, calcula plazos con un calendario sintético y crea reportes y logs aislados. No envía mensajes, no usa tokens de IA y no necesita autorizar Google.

## 3. Cambiar cantidades y escenarios

| Preset | Total | Normales | Especiales | Uso |
| --- | --- | --- | --- | --- |
| Rápida | 12 | 9 | 3 | Primera demostración local |
| Real | 24 | 18 | 6 | Preparación Gmail, sin envío automático |
| Carga local | 300 | 240 | 60 | Contenido y fallos simulados |
| Estrés local | 1.000 | 800 | 200 | Prueba local de mayor volumen |

La ventana comienza con el preset Real, **sin ejecutarlo**. Para una demostración sin red, aplica primero Rápida, Carga local o Estrés local.

Al personalizar, respeta `total = normales + especiales` y `suma de tipos especiales = especiales`. El límite es 1.000 casos locales o 500 por campaña Gmail. Los errores técnicos, como timeout, autenticación o Supabase no disponible, solo se permiten en `SIMULATION`.

La **semilla** reproduce la distribución y el orden con una misma configuración. **Guardar configuración** conserva un JSON en `runtime/test_configs/`; selecciona su nombre y pulsa **Cargar configuración** para recuperarlo. Usa las barras del formulario para llegar a los controles inferiores y a las columnas derechas.

Un fallo técnico esperado cuenta como prueba correcta si el programa lo detecta. En el preset de 1.000 hay 130 casos técnicos: el resultado esperado es **1.000 casos correctos y 870 clasificados**, no 1.000 correos clasificados.

## 4. Preparar Gmail

Este apartado usa cuentas reales. La configuración inicial del proyecto Google, API, cliente OAuth y usuarios de prueba está en [GOOGLE_CLOUD_GMAIL.md](docs/GOOGLE_CLOUD_GMAIL.md). Las credenciales se guardan en `config/google/`; la configuración del equipo está en `.env`.

1. En **1 Inicio**, revisa que remitente y receptor sean las cuentas que utilizarás.
2. Pulsa **Revisar estado local**. Esta consulta no comprueba Google por internet.
3. Si necesitas autorizar, pulsa **Autorizar remitente** y completa el navegador con la cuenta emisora. Después pulsa **Autorizar receptor** y completa el acceso con la cuenta receptora.
4. Espera el resultado de cada operación antes de iniciar la siguiente. No copies contraseñas ni códigos de autorización en los archivos del proyecto.

`REFRESH_REQUIRED` significa que el token necesita renovarse al usarlo; no demuestra que el permiso haya dejado de funcionar. Si aparece `AUTH_REQUIRED`, vuelve a autorizar el rol indicado. Si se cierra la ventana de Google o vence la espera, repite el botón de autorización.

## 5. Preparar, enviar y analizar una campaña

1. En **2 Simulación**, aplica **Real: 24 / 6 especiales** o configura un lote Gmail válido. Los tipos técnicos deben quedar en cero.
2. En **3 Campañas**, pulsa **Preparar campaña (sin enviar)**. Guarda el identificador mostrado y revisa **VISTA PREVIA**. Hasta aquí no se envía nada.
3. En **4 Envío**, configura el intervalo entre **1 y 60 segundos** y el máximo de mensajes a intentar en esta tanda. Para comprobar la conexión puedes comenzar con una tanda de 1.
4. Pulsa **Enviar tanda y analizar / continuar**. Revisa cuentas, campaña y cantidad en la confirmación. Solo confirma si deseas realizar esos envíos; **Cancelar** no envía.
5. Revisa los contadores y el resultado. **Detener nuevos envíos** actúa entre peticiones: no retira mensajes ya aceptados ni cancela una petición en curso.
6. Para volver a comprobar llegada sin enviar, selecciona la misma campaña y usa **5 Recepción → Solo analizar / reanudar lectura**.
7. Para enviar los pendientes, vuelve a **4 Envío** con la misma campaña. Los mensajes aceptados se omiten.

| Contador o estado | Cómo interpretarlo |
| --- | --- |
| Preparados | Mensajes definidos en el lote; aún pueden no haberse enviado |
| Aceptados | Gmail aceptó el envío; todavía no demuestra recepción |
| Recibidos | El análisis encontró el mensaje de esa campaña en el receptor |
| Clasificados | Mensajes procesados por las reglas de categorías |
| Pendientes | Falta envío, recepción o validación según la etapa |
| `UNCERTAIN` / envío incierto | Requiere revisión; no se reenvía automáticamente |

Si no llegan mensajes, comprueba la cuenta receptora, Spam y la campaña seleccionada. El análisis de campañas puede incluir Spam/Papelera con `GMAIL_LABEL=ALL` y filtro de campaña. El robot no mueve ni marca correos. Una consulta sin resultados no autoriza a repetir un envío incierto.

Preparar una campaña nueva crea otro lote; no continúa el anterior. No hay un planificador que complete los pendientes al día siguiente. El contador local de las últimas 24 horas tampoco equivale a la cuota oficial de Gmail. El envío del Excel es otra operación, descrita en la guía de Google; estos botones envían mensajes de prueba y analizan su recepción.

## 6. Consultar Excel y resultados anteriores

En **6 Reportes**, usa **Abrir Excel disponible** o selecciona una simulación y pulsa **Cargar resultado anterior**. **Abrir carpeta de CSV, JSON y Excel** permite localizar los archivos del resultado cargado.

| Archivo | Contenido |
| --- | --- |
| `reporte_pruebas.xlsx` | Resumen de pruebas y cuatro hojas: Resumen, Correos, Referencia_API y Ejecuciones |
| `pruebas.csv` y `pruebas.json` | Escenarios, resultados esperados/obtenidos y validación, sin asuntos ni credenciales |
| `resultado.json` | Estado y métricas de la ejecución |
| `reporte.xlsx` | Reporte base original, conservado aparte de la copia de pruebas |

Las simulaciones se guardan bajo `output/presentacion/` y su estado bajo `runtime/presentacion/`. Las campañas mantienen su manifiesto en `runtime/campaigns/<ID>/`; usa los botones o las rutas del resultado para encontrar sus reportes. No borres SQLite ni esas carpetas para resolver un bloqueo.

El XLSX se genera aunque no haya Excel de escritorio instalado. Para abrirlo necesitas un programa compatible. La automatización específica de Excel COM es una comprobación adicional y no está disponible en el equipo validado.

## 6.1. Preparar y enviar el Excel desde la ventana

El envío del reporte es independiente de los mensajes de prueba. En **6 Reportes**:

1. Para una campaña ya recibida y analizada, pulsa **Generar Excel de la campaña seleccionada**. También puedes elegir una ejecución ya disponible en la lista.
2. Escribe el destinatario del Excel. Debe estar autorizado en `ALLOWED_RECIPIENTS`; la aplicación no modifica esa lista.
3. Pulsa **Comprobar adjunto y ver correo**. Revisa archivo, tamaño, hash, destinatario, asunto y contenido de la vista previa.
4. Para dejarlo preparado, detente aquí. Para enviarlo, pulsa **Confirmar envío del Excel por Gmail** y revisa la confirmación. Cancelar no envía.
5. El estado **aceptado por Gmail** no confirma recepción. Los resultados inciertos no se repiten automáticamente; la entrega confirmada exige evidencia mediante la reconciliación existente.

Se adjunta el `reporte.xlsx` original validado, no la copia de escenarios. Los reportes locales pueden previsualizarse sin internet, pero no enviarse desde este flujo. Cambiar la selección o el destinatario invalida la vista previa. Generar un consolidado Gmail puede necesitar feriados reales o caché; no es necesario para la demostración local.

La [revisión final](docs/REVISION_FINAL.md) describe pruebas, CI, entrega y límites actuales.

## 7. Consultar logs, Supabase y limpieza

**Consultar logs** abre la carpeta correspondiente. **7 Auditoría** permite consultar el estado local o sincronizar con Supabase. **Estado de Supabase** muestra información local; el éxito de una sincronización o consulta remota es la comprobación de conexión.

Para guardar una copia descargable, abre PowerShell en el proyecto:

```powershell
# Copiar logs de la base local a la carpeta de descargas
.\.venv\Scripts\python.exe main.py logs-download --source LOCAL
# Consultar y descargar los registros remotos; requiere conexión
.\.venv\Scripts\python.exe main.py logs-download --source SUPABASE
# Abrir el panel de auditoría en http://127.0.0.1:8000
.\.venv\Scripts\python.exe main.py panel
```

Las descargas quedan en `runtime/logs/descargas/` con hash y vencimiento. Por defecto caducan a los 15 días. La limpieza se ejecuta en los puntos de mantenimiento del programa y con el panel abierto; con todo cerrado, espera a la siguiente ejecución. No es un servicio permanente. Los logs originales tienen retenciones por nivel de 7/15/30 días y las ejecuciones pendientes o en revisión se protegen.

Supabase registra inicio, fin, duración, estado e intentos. Si falla la conexión, SQLite conserva la cola. Cada registro tiene como máximo tres intentos persistentes; reiniciar no los pone a cero. La limpieza de archivos no borra mensajes, cursores ni estados de envío. Configuración y comandos adicionales: [SUPABASE.md](docs/SUPABASE.md).

## 8. Resolver problemas frecuentes

| Problema | Qué hacer |
| --- | --- |
| Un botón no se ve | Reabre la versión actualizada, amplía la ventana o usa las barras de desplazamiento de la pestaña |
| Total o distribución inválidos | Corrige las sumas o vuelve a aplicar un preset |
| `AUTHORIZATION_FAILED` | Repite la autorización, completa el navegador antes del timeout y consulta el mensaje de Google |
| `org_internal` | Usa el proyecto propio configurado para estas cuentas; sigue la guía Google Cloud |
| `PROFILE_BUSY` | Espera la operación de la otra ventana; evita abrir dos ejecuciones del mismo perfil |
| No llegan todos los correos | Analiza la misma campaña y revisa Spam; no confundas aceptados con recibidos |
| Campaña incierta, `REVIEW` o espera pendiente | Revisa logs y recepción; no borres el estado ni fuerces reintentos en bucle |
| Excel no se abre | Comprueba el archivo en Reportes y que exista un programa compatible; cierra libros bloqueados |
| Supabase no responde | Conserva la cola local y revisa la conexión; no repitas envíos de correo por este motivo |

## 9. Repetir las pruebas locales

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe scripts/escenarios_demo.py --preset quick
.\.venv\Scripts\python.exe scripts/escenarios_demo.py --preset load --seed 42
.\.venv\Scripts\python.exe scripts/escenarios_demo.py --preset stress --seed 42
```

Estos comandos no envían correos. El 23/11/2026 pasaron **127 pruebas automatizadas**, las tres simulaciones y las comprobaciones de interfaz. Consulta el [informe de validación](docs/VALIDACION_2026-11-23.md) para distinguir pruebas locales, conexiones reales y limitaciones.

Para exponer: [guion de 11 minutos](docs/GUION_DEMO.md). Para comprender arquitectura y reglas: [explicación del proyecto](docs/EXPLICACION_PROYECTO.md).
