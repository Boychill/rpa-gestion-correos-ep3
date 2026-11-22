# Evidencia de integración Gmail EP3

Fecha: 18 de noviembre de 2026 (America/Santiago). Evidencia final: `docs/evidence/gmail_real_checks.json`.

| Criterio | Estado | Evidencia y límite |
|---|---|---|
| Cliente Desktop existente | IMPLEMENTADO / COMPROBADO_LOCAL | JSON original reutilizado en config/google/credentials.json, con ACL y exclusión de Git/ZIP. |
| OAuth remitente y receptor | PROBADO_REAL | Tokens separados send-only y readonly; carga y refresh sin navegador. Receptor validado con getProfile. |
| Identidad del remitente | PROBADO_REAL | From de los mensajes recibidos coincide con el remitente configurado; no se usó getProfile con send-only. |
| API habilitada | PROBADO_REAL | Tras corregir GMAIL_API_DISABLED, getProfile y list respondieron HTTP 200. No se enumeró administrativamente Test users. |
| Envío de 500 | PROBADO_REAL | 500 aceptados; primer mensaje verificado antes de continuar con los otros 499. Sin reintentos de envío. |
| Recepción y clasificación | PROBADO_REAL | 500 recibidos únicos, 500 clasificaciones correctas, 0 faltantes, 0 duplicados. |
| Spam | PROBADO_REAL | 328 mensajes en Inbox y 172 en Spam. Lectura del dataset en ALL, sin mover ni marcar mensajes. |
| Paginación e historial | PROBADO_REAL | Barrido final con 508 llamadas del lector; incorporó 172 registros y deduplicó los 328 ya almacenados. |
| Correlación | PROBADO_REAL | Gmail sustituyó Message-ID. Se verificó UUID del dataset, número individual y From; no IDs internos entre cuentas. |
| Excel consolidado de 500 | PROBADO_REAL | 500 filas, seis categorías, Referencia_API real y manifiesto SHA256. |
| Envío adicional del reporte | IMPLEMENTADO / PROBADO_CON_FIXTURES / PENDIENTE_REAL | MIME texto/HTML/Excel, destinatario permitido y promoción explícita de DRY_RUN. Falta configurar REPORT_TO; no se envió un correo adicional. |
| Interfaz de presentación | IMPLEMENTADO / PROBADO_LOCAL | Abrir_Demo.cmd; simulación desde el botón con seis registros, Excel generado y resumen real de 500 visible. |
| Recuperación, cuotas y fallo ambiguo | PROBADO_CON_FIXTURES | Máximo de intentos, pausa por cuota, ausencia de reenvío incierto, recepción incremental y detención de nuevos envíos. |
| Capacidad 100/300/500/1000 | PROBADO_CON_FIXTURES | benchmark.json; todos COMPLETED. No se extrapola a rendimiento Gmail. |
| Feriados Chile | PROBADO_REAL | GET 200 para 2026 y 2027, 17 registros cada año; real_checks.json. |
| Excel de escritorio | BLOQUEADO | EXCEL_COM_UNAVAILABLE; Excel.Application no registrado. openpyxl no acredita escritorio. |
| Supabase | PROBADO_REAL | 1.409 registros sincronizados y descargados; copias con retención de 15 días. |
| Secretos fuera de entrega | PROBADO_LOCAL | ZIP inspeccionado por nombres y por contenido de las claves y tokens locales, sin divulgarlos. |

Categorías verificadas: Solicitud 84, Consulta 84, Reclamo 83, Urgente 83, Información 83 y Otros 83.
El lote usa el UUID `4aa43f17-2bb2-420a-96cd-0f91bee700a9`. No debe recrearse para reanudar.
La espera de envío y los límites de Gmail permanecen; no se promete exactly-once del proveedor.

Para presentar, abrir **Abrir_Demo.cmd** y seguir **DEMO_PRESENTACION.md**. La simulación local
no necesita conexión ni autorización. La prueba Gmail utiliza los tokens locales y el estado
persistente. El consentimiento de una app External en Testing puede requerir reautorización.

Comprobaciones sin enviar nuevos mensajes:

```powershell
.\.venv\Scripts\python.exe scripts/diagnosticar_gmail.py
.\.venv\Scripts\python.exe scripts/gmail_demo.py status --campaign 4aa43f17-2bb2-420a-96cd-0f91bee700a9
.\.venv\Scripts\python.exe scripts/exportar_campana.py --campaign 4aa43f17-2bb2-420a-96cd-0f91bee700a9
```
