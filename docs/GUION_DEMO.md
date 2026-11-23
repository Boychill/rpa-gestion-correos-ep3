# Guion de presentación de 11 minutos

Preparación: abre `Abrir_Demo.cmd`, ten una simulación rápida disponible y conserva la evidencia de campañas reales anteriores. No muestres `.env`, tokens ni asuntos privados. El recorrido funciona sin internet; cualquier demostración de envío real debe acordarse y autorizarse aparte.

| Tiempo | Acción | Explicación sugerida |
| --- | --- | --- |
| 0:00–1:00 | Mostrar Inicio y el propósito | «El robot lee metadatos, clasifica asuntos, calcula plazos, genera Excel y conserva auditoría. La clasificación usa reglas, no tokens de IA». Diferenciar revisión local de conexión remota comprobada. |
| 1:00–2:00 | Mostrar arquitectura y las siete secciones | Explicar interfaces → acciones → lectura/clasificación → calendario → Excel → auditoría. SQLite conserva el estado operativo; Supabase replica logs sanitizados. |
| 2:00–3:00 | Aplicar preset Rápida | Mostrar 12 = 9 normales + 3 especiales. Cambiar temporalmente una cifra para mostrar el rechazo de una distribución inválida y volver a aplicar el preset explícitamente. Mostrar semilla y guardado de configuración. |
| 3:00–4:15 | Ejecutar simulación y activar PRESENTACIÓN | Mostrar etapa, barra y resultados. Explicar Otros como categoría válida; asuntos combinados prueban prioridad. Las simulaciones no tocan campañas ni credenciales reales. |
| 4:15–5:15 | Mostrar resultados esperado y obtenido | Abrir Recepción y su tabla. Comparar tipo, categoría esperada, obtenida y validación. En una configuración con fallos técnicos, un rechazo esperado es una prueba correcta, no un error inesperado del robot. |
| 5:15–6:30 | Abrir reporte y vista previa | Recorrer las cuatro hojas y el detalle de Resumen. En Reportes, comprobar el adjunto y mostrar destinatario, tamaño, hash y correo. No confirmar el envío. Explicar que la simulación utiliza calendario sintético. |
| 6:30–7:45 | Seleccionar una campaña anterior y abrir VISTA PREVIA | Mostrar identificador único, secuencia y categoría. Explicar intervalos y tandas. Leer el ejemplo «24 aceptados, 22 recibidos, 2 pendientes» como ejemplo, no como resultado de la campaña visible. Cancelar cualquier confirmación de envío durante este recorrido. |
| 7:45–8:45 | Explicar recuperación | Aceptado no prueba recepción. Los inciertos no se reenvían automáticamente. Solo analizar consulta recepción sin enviar; continuar usa el mismo lote. El contador local de 24 horas no es la cuota oficial de Gmail. |
| 8:45–9:45 | Mostrar Auditoría | Explicar inicio, fin, duración, intento, HTTP, resultado y recuperación. El fallo de Supabase conserva la cola. La limpieza de archivos no elimina mensajes, cursores o estados de envío. |
| 9:45–10:30 | Mostrar pruebas y evidencia | Mostrar 144 pruebas aprobadas y GitHub Actions. Separar los 300 reales completos de los 1.000 locales; la campaña histórica real de 1.000 quedó parcial. Explicar protección de cancelación y envíos inciertos. |
| 10:30–11:00 | Cierre y preguntas | «La mejora permite configurar pruebas, ver resultados esperados y obtenidos y continuar trabajo sin duplicar envíos». Explicar límites: sin planificador automático, cuota externa, Excel COM según instalación y reglas basadas en palabras. |

## Plan alternativo si no hay conexión

Usa Rápida o Carga local, el historial de simulaciones y las evidencias archivadas. No pulses autorizar, sincronizar ni analizar Gmail. Si una simulación tarda más de lo previsto, muestra un resultado anterior; indica claramente que pertenece a otra ejecución.

## Evidencia que conviene tener abierta

- [Cómo utilizar el programa, paso a paso](../COMO_UTILIZAR.md).
- [Revisión final: 144 pruebas, CI y límites](REVISION_FINAL.md).
- [Evidencia histórica de 300 correos reales](evidence/prueba_real_300_20261123.json).
- [Guía de operación](DEMO_PRESENTACION.md).
- [Explicación completa del proyecto](EXPLICACION_PROYECTO.md).
- `pruebas.json`, `pruebas.csv` y `reporte_pruebas.xlsx` de una simulación reciente.
- [Resultado real parcial de 1.000](evidence/prueba_1000_gmail.json).
- `docs/evidence/revision_final_pytest.xml`, generado con la suite actual. Los XML anteriores conservan sus resultados históricos.
