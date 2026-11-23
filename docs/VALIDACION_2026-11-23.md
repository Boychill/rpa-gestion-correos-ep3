# Validación del proyecto · 23 de noviembre de 2026

Fecha local: 23/11/2026, America/Santiago. Entorno: Windows, Python 3.13.14. Se validaron código, dependencias, interfaz, escenarios, capacidad local y conexiones de lectura. No se enviaron correos reales ni se reanudaron campañas pendientes.

## Suite automatizada

**127 pruebas aprobadas, 0 fallos**, en 48,76 segundos. `pip check` no encontró dependencias incompatibles. Aparece un aviso de deprecación de Starlette/httpx en el cliente de pruebas; no causó fallos y no se cambiaron dependencias durante esta validación.

La suite cubre clasificación, plazos, persistencia, paginación y recuperación, envío con proveedores simulados, autenticación Gmail, límites de reintentos, estados inciertos, Supabase con mocks, descargas, retención, panel, acciones de demostración, escenarios y confirmación de envío. Las pruebas de interfaz comprueban botones accesibles con mensajes largos en ventanas de 680×550, 800×600 y 1160×678, desplazamiento y modo presentación.

Evidencia: [validacion_20261123_pytest.xml](evidence/validacion_20261123_pytest.xml).

## Escenarios y capacidad sin red

Se bloqueó el transporte HTTP real durante las simulaciones. Los casos técnicos usan mocks y no provocan errores en los servicios externos.

| Preset | Casos correctos | Clasificados | Especiales comprobados | Casos técnicos simulados | Errores inesperados |
| --- | --- | --- | --- | --- | --- |
| Rápida | 12/12 | 12 | 3/3 | 0 | 0 |
| Carga local | 300/300 | 260 | 60/60 | 40 | 0 |
| Estrés local | 1.000/1.000 | 870 | 200/200 | 130 | 0 |

Los rechazos técnicos esperados son pruebas correctas y no cuentan como correos clasificados. Los libros generados por estos escenarios se reabrieron con openpyxl y conservaron las hojas Resumen, Correos, Referencia_API y Ejecuciones. Se registraron hashes de los archivos generados.

También se ejecutó el flujo sintético base, sin escenarios técnicos, con estado separado para cada cantidad:

| Mensajes | Clasificados | Estado | Envío | Tiempo de pared |
| --- | --- | --- | --- | --- |
| 100 | 100 | COMPLETED | DRY_RUN | 0,781 s |
| 300 | 300 | COMPLETED | DRY_RUN | 0,985 s |
| 500 | 500 | COMPLETED | DRY_RUN | 1,141 s |
| 1.000 | 1.000 | COMPLETED | DRY_RUN | 1,664 s |

Estas mediciones corresponden a datos locales y a este equipo; no representan latencia ni capacidad de envío de Gmail. El benchmark anterior con tracemalloc permanece como evidencia histórica independiente.

Evidencia: [validacion_20261123_local.json](evidence/validacion_20261123_local.json).

## Aplicación de escritorio

Se ejecutó una simulación rápida desde los controles reales de Tkinter, con red bloqueada y carpetas aisladas. La ventana siguió respondiendo, produjo 12 casos correctos y permitió cambiar al modo PRESENTACIÓN. Se generaron capturas locales de la configuración y del resultado; las pruebas automatizadas adicionales verificaron el diseño con ventanas pequeñas.

Se comprobó la compilación de los módulos y la ayuda de los comandos principal, escenarios, campañas y mantenimiento. No se encontraron enlaces locales rotos en README, la guía de uso y los documentos Markdown de `docs/`. Los hashes de 32 archivos protegidos permanecieron sin cambios durante la validación de escenarios y conexiones: `.env`, archivos OAuth, estado SQLite y manifiestos de campañas. Evidencia: [validacion_20261123_operacion.json](evidence/validacion_20261123_operacion.json).

## Conexiones reales, sin envío

| Integración | Resultado y alcance |
| --- | --- |
| Gmail remitente | Renovación remota del token correcta; no se probó envío ni entrega |
| Gmail receptor | Renovación correcta, identidad comprobada y listado de una página limitado a un mensaje con HTTP 200; no se descargaron cuerpos |
| Supabase | Consulta de esquema `rpa_logs`, con selección de columnas y límite cero, HTTP 200; no se escribieron registros remotos |
| Feriados Chile 2026 | GET real HTTP 200; 17 entradas validadas |
| Feriados Chile 2027 | GET real HTTP 200; 19 entradas validadas |
| Excel COM | No disponible: `EXCEL_COM_UNAVAILABLE`, componente no registrado |
| Outlook COM | Componente no registrado; no se probó envío |
| Microsoft Graph | No se realizó una prueba con buzón real; adaptador cubierto con mocks |

Los tokens se renovaron solo en memoria para comprobar las conexiones; no se guardaron cambios en los archivos OAuth. Las evidencias contienen estados y códigos, sin claves, tokens, cuerpos ni direcciones de cuentas. La lectura satisfactoria de Supabase no reemplaza una prueba nueva de escritura o de políticas RLS. La evidencia histórica de escritura/idempotencia del 18/11 sigue separada.

Evidencia: [conexiones](evidence/validacion_20261123_conexiones.json), [Office y API pública](evidence/real_checks.json), [feriados 2026](evidence/api_CL_2026.json) y [feriados 2027](evidence/api_CL_2027.json).

## Uso de estos resultados

Para operar el programa consulta [COMO_UTILIZAR.md](../COMO_UTILIZAR.md). Las campañas históricas de Gmail mantienen sus propios resultados; las pruebas locales de 1.000 casos no significan que se hayan enviado o recibido 1.000 correos reales hoy. Los PDF/PPTX históricos de `dist/` no se regeneraron: la documentación actualizada se encuentra en los archivos Markdown del repositorio.

Para repetir la suite:

```powershell
.\.venv\Scripts\python.exe -m pytest --junitxml=docs/evidence/validacion_20261123_pytest.xml
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe scripts/escenarios_demo.py --preset quick
.\.venv\Scripts\python.exe scripts/escenarios_demo.py --preset load --seed 42
.\.venv\Scripts\python.exe scripts/escenarios_demo.py --preset stress --seed 42
```

Las comprobaciones de servicios reales corresponden al momento registrado en sus JSON. Su disponibilidad posterior depende de permisos, red y estado del proveedor.
