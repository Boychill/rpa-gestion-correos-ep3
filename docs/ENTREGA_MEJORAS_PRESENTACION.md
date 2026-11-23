# Entrega de mejoras de presentación y escenarios

Fecha: 22 de noviembre de 2026. Rama de trabajo: `feat/escenarios-presentacion`, basada en `main`.

**Cierre de entrega:** [REVISION_FINAL.md](REVISION_FINAL.md) documenta el envío del Excel integrado en la ventana, las nuevas regresiones, GitHub Actions y la regeneración de entregables. Los resultados de 124/127 pruebas de este documento corresponden a revisiones anteriores; la suite vigente se registra en `evidence/revision_final_pytest.xml`.

Revalidación del 23/11/2026: **127 pruebas aprobadas**, incluidos los tres casos nuevos de disposición de controles. Se volvió a ejecutar la simulación desde Tkinter y los presets de 12, 300 y 1.000 casos; también se comprobaron conexiones de lectura sin enviar correos. Consulta [el informe actualizado](VALIDACION_2026-11-23.md) y la nueva [guía de uso](../COMO_UTILIZAR.md). Las cifras de 124 pruebas y 30 archivos protegidos indicadas más adelante corresponden a la entrega original del 22/11.

## Funcionalidades implementadas

La interfaz existente incorpora siete secciones, modo PRESENTACIÓN, contadores diferenciados, progreso mediante threading y queue, historial, vista previa y confirmación explícita antes de cada tanda Gmail. El tamaño se adapta a la pantalla y los controles principales permanecen visibles.

La configuración valida total = normales + especiales y exige una distribución exacta. Incluye presets 12/3, 24/6, 300/60 y 1.000/200, semilla opcional y guardado/carga de configuraciones. No corrige cantidades automáticamente. Se conservan los límites de 1.000 en simulación y 500 por campaña Gmail.

Se implementaron cinco tipos especiales de contenido y diez casos técnicos controlados. Los técnicos usan transportes simulados y bases locales aisladas. Los mensajes reales siguen identificándose por campaña y secuencia, conservan el hash del manifiesto y no pueden contener escenarios técnicos.

Los reportes separan preparados, aceptados, recibidos, clasificados, casos validados y pendientes. Las exportaciones CSV/JSON excluyen asuntos, direcciones y credenciales. La copia `reporte_pruebas.xlsx` conserva las cuatro hojas y agrega el resumen de escenarios sin alterar el adjunto original.

## Archivos modificados

| Archivos | Cambios |
| --- | --- |
| `demo_presentacion.py` | Secciones, configuración, presentación, historial, vista previa, controles de tanda y confirmación |
| `rpa/demo_actions.py` | Integración de escenarios, opciones de envío, estado local y consulta de auditoría |
| `rpa/scenarios.py` | Nuevo: validaciones, presets, generación reproducible y persistencia de configuraciones |
| `rpa/scenario_runner.py` | Nuevo: ejecución aislada y fallos técnicos con MockTransport |
| `rpa/scenario_reports.py` | Nuevo: resumen, CSV, JSON y copia Excel de pruebas |
| `rpa/gmail_campaign.py` | Metadatos opcionales compatibles con manifiestos anteriores, vista previa, intervalos, tandas, progreso y estimación local de uso |
| `rpa/gmail_auth.py` | Inspección del estado local sin refrescar ni escribir tokens |
| `rpa/store.py` | Validación de ID, fecha y metadatos antes de confirmar una página y su cursor |
| `rpa/mail_send.py`, `rpa/runtime.py` | Auditoría de preparación, intento y resultado efectivo, incluyendo retornos inciertos sin excepción |
| `rpa/orchestrator.py` | Resultado de auditoría coherente con el envío y rendimiento basado en tiempo acumulado |
| `rpa/cloud_logs.py` | El resumen remoto conserva el código del último evento fallido cuando la ejecución requiere revisión |
| `scripts/gmail_demo.py` | Opciones adicionales de configuración e intervalo, compatibles con comandos anteriores |
| `scripts/escenarios_demo.py` | Nuevo comando para simulación configurable sin red |
| `tests/test_scenarios.py` | Nuevas pruebas funcionales, de integración con mocks y de confirmación en Tkinter |
| `tests/test_demo_layout.py` | Regresión de botones visibles, desplazamiento y presentación en tres tamaños de ventana |
| `README.md`, `docs/DEMO_PRESENTACION.md`, `docs/EXPLICACION_PROYECTO.md`, `docs/GUION_DEMO.md` | Uso, arquitectura actualizada, límites y exposición |

No se añadieron migraciones destructivas ni se cambió el esquema SQLite. Los adaptadores existentes Gmail, Graph, Outlook y Excel siguen cubiertos por la suite previa.

## Problemas encontrados y corregidos

1. Un estado de error devuelto por `send_report()` podía quedar registrado como éxito. Ahora se registra el resultado efectivo, el HTTP cuando existe, el código sanitizado y la acción de recuperación.
2. La velocidad de una reanudación dividía el total procesado por el último tramo. Ahora utiliza el tiempo activo acumulado; el Excel y la vista previa reciben también la duración acumulada.
3. Las entradas incompletas podían fallar durante la persistencia sin un código específico. Ahora se valida la página antes de guardar sus datos y cursor.
4. Un envío detenido con mensajes aceptados podía impedir comprobarlos desde la acción conjunta. Ahora puede analizar lo aceptado sin repetir el mensaje incierto.
5. Una pantalla baja podía ocultar botones inferiores. La ventana adapta su tamaño y reserva espacio para los controles; la configuración dispone de desplazamiento.

## Pruebas y resultados

La suite completa terminó con **124 pruebas aprobadas**, incluidas las 90 originales. Existe un aviso de deprecación de Starlette/httpx que no produjo fallos. Después del ajuste final de disposición de la ventana se repitió la prueba de confirmación de Tkinter, también aprobada.

Evidencia: [presentacion_pytest.xml](evidence/presentacion_pytest.xml) y [presentation_validation.json](evidence/presentation_validation.json).

| Preset ejecutado sin red | Configurados | Clasificados | Especiales comprobados | Fallos técnicos simulados | Pruebas correctas |
| --- | --- | --- | --- | --- | --- |
| Rápida | 12 | 12 | 3 de 3 | 0 | 12 de 12 |
| Carga local | 300 | 260 | 60 de 60 | 40 | 300 de 300 |
| Estrés local | 1.000 | 870 | 200 de 200 | 130 | 1.000 de 1.000 |

Los casos técnicos no se cuentan como correos correctamente clasificados. Su validación comprueba el rechazo, la deduplicación o la conservación de estado que corresponde. Por eso las pruebas pueden estar todas correctas aunque el número clasificado sea menor que el total configurado.

La prueba visual ejecutó una simulación real desde los controles Tkinter, comprobó que la ventana siguiera respondiendo y revisó su configuración y modo PRESENTACIÓN mediante capturas de la propia aplicación. Se compararon hashes de **30 archivos protegidos** —configuración privada, credenciales y estado operativo/campañas— sin encontrar cambios.

**No se enviaron correos reales durante el desarrollo o las pruebas.** Los ensayos Gmail usaron mocks, y en las ejecuciones locales de validación se bloqueó el transporte HTTP real. La existencia de evidencia histórica Gmail en el repositorio no corresponde a nuevos envíos de esta mejora.

## Comandos de la nueva versión

```powershell
# Ventana de presentación
.\Abrir_Demo.cmd

# Simulaciones sin conexión
.\.venv\Scripts\python.exe scripts/escenarios_demo.py --preset quick
.\.venv\Scripts\python.exe scripts/escenarios_demo.py --preset load --seed 42
.\.venv\Scripts\python.exe scripts/escenarios_demo.py --preset stress

# Suite automatizada
.\.venv\Scripts\python.exe -m pytest
```

Los comandos anteriores del robot siguen disponibles. La [guía de demostración](DEMO_PRESENTACION.md) explica autorización, campañas, recepción, continuación, reportes y Supabase. El [guion de 11 minutos](GUION_DEMO.md) permite presentar la mejora sin envíos reales.

## Limitaciones restantes

- El contador local de 24 horas es una estimación de campañas gestionadas por el programa; no consulta cuota oficial, no incluye mensajes externos ni aplica una cuota global preventiva.
- No existe un planificador que continúe automáticamente las campañas al día siguiente.
- Los fallos técnicos y las esperas asociadas son simulados; no prueban la disponibilidad real del proveedor ni su latencia.
- El estado OAuth de Inicio es una inspección local. El servidor puede haber revocado un token y solo se comprueba al utilizar el servicio.
- Excel de escritorio sigue dependiendo de su instalación; el reporte se genera con openpyxl.
- La suite muestra un aviso de deprecación de una dependencia existente. No se actualizó el conjunto de dependencias dentro de este cambio.
- Los PDF/PPTX originales quedaron pendientes en esta primera entrega; la revisión final los regenera junto con el ZIP desde las fuentes actualizadas.
