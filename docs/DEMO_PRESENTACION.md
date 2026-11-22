# Presentación sin escribir comandos

Haz doble clic en **Abrir_Demo.cmd** en la raíz del proyecto. La ventana se ejecuta
localmente con Python y conserva los estados entre aperturas.

## Recorrido de 2 minutos

1. Muestra el lote real de 500 ya procesado en el selector. El resumen indica recibidos,
   clasificación, faltantes y duplicados. **Abrir Excel** abre el consolidado existente.
2. Deja cantidad **6** y pulsa **Ejecutar simulación**. Clasifica datos sintéticos, genera
   Excel y logs; funciona sin internet y no usa Gmail ni Supabase.
3. Para demostrar correo real, pulsa **Preparar lote**, revisa los seis asuntos y el
   remitente/destinatario configurados. Este paso no envía nada.
4. Pulsa **Enviar y analizar** y confirma la cantidad y las direcciones. Se envían los
   pendientes una sola vez, se lee el lote, se clasifica, se consultan feriados y se
   prepara el consolidado. La barra muestra aceptación; recepción se confirma después.
5. Usa **Abrir Excel**, **Ver logs** y **Ver resultados** para mostrar la evidencia.

La cuenta remitente y receptora se toman de `.env`; las credenciales no aparecen en la
ventana. El generador real admite hasta 500 mensajes; la simulación hasta 1.000.
Para una presentación conviene usar seis, uno por categoría. El lote de 500 existente
se reutiliza para mostrar resultados sin volver a enviarlo.

**Detener nuevos envíos** deja los pendientes guardados y espera la llamada en curso.
Para continuar selecciona el mismo lote. No prepares otro lote para reanudar el anterior.
Un envío incierto requiere revisión; no se repite automáticamente. Si algunos mensajes
tardan en llegar, usa **Solo analizar / reanudar lectura** después, sin reenviar.

Si aparece AUTH_REQUIRED, usa **Autorizar remitente** o **Autorizar receptor** y elige
la cuenta indicada. La ejecución normal reutiliza y refresca tokens; solo esos botones
abren autorización. La app External en Testing puede requerir reautorizar a los siete días.

El análisis está limitado al identificador del lote y usa lectura `GMAIL_LABEL=ALL` para
incluir Spam; no mueve ni marca mensajes. Esto permitió confirmar los 500 de la prueba:
328 en Inbox y 172 en Spam. La clasificación de los 500 coincidió con las seis categorías
esperadas y no hubo duplicados.

La ventana no envía automáticamente el reporte consolidado como correo adicional. Ese
envío separado requiere un destinatario autorizado y el comando documentado en
GOOGLE_CLOUD_GMAIL.md. El Excel se genera con openpyxl; para abrirlo en escritorio debe
existir una aplicación asociada. Excel COM sigue pendiente en este equipo.

Si falta el entorno virtual, ejecuta primero `scripts/setup.ps1`. Después puedes iniciar
siempre con Abrir_Demo.cmd, incluso desde un acceso directo.

## Pruebas conjuntas por tamaño

Para comprobar el mismo flujo de simulación de la ventana con 100, 300, 500 y 1.000 registros:

```powershell
.\.venv\Scripts\python.exe scripts/probar_conjuntos.py
```

Comprueba clasificación, filas y estructura del Excel, categorías, hash del log y una
segunda ejecución sin cambios ni duplicados. Guarda los Excel en `output/presentacion/`
y los resultados en `docs/evidence/pruebas_conjuntos.json`. No envía correos ni consulta
Gmail o Supabase. Las conexiones reales se comprueban por separado con los diagnósticos
documentados, sin confundir resultados sintéticos con recepción real.
