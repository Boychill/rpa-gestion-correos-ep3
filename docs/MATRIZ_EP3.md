# Matriz provisional de trazabilidad EP3

La pauta oficial no fue proporcionada. Los IL se toman exclusivamente del prompt recibido; esta matriz no reemplaza la rúbrica del docente.

| Indicador / requisito | Implementación | Prueba / evidencia | Estado |
|---|---|---|---|
| IL 3.1 API útil en Excel | holidays.py + excel.py, plazo y Referencia_API | GET reales api_CL_2026/2027.json; test_year_boundary_and_timezone; reporte live de demostración | API real verificada; calendario nacional documentado |
| IL 3.2 escritorio | office_worker.py excel, rango/recalcular/guardar/reabrir | real_checks.json; test_windows_locked_workbook; PRUEBAS_REALES.md | Pendiente Excel instalado: COM ausente |
| IL 3.3 recepción y clasificación | gmail.py OAuth/historial; classify.py | test_gmail.py, test_gmail_auth.py y gmail_connection.json; reglas/prioridad | Sintético y contrato HTTP probados; falta buzón real |
| IL 3.3 envío | mail_send.py MIME Gmail + gmail_campaign.py | test_uncertain_send_never_repeated, destinatarios bloqueados, HTML dry-run | Gmail real: 500 mensajes aceptados y recibidos; reporte adicional pendiente de destinatario |
| IL 3.4 subprocesos anidados | main → run → etapas y adaptadores | flujo.mmd, secuencia.mmd; ejecución completa y recuperación | Implementado y probado localmente |
| IL 3.5 privacidad/impacto/sostenibilidad | metadatos mínimos, seudónimos, reglas, caché, retención | INFORME secciones 7 y 9; pruebas CSRF/hash/limpieza | Implementado con límites explícitos |
| Capacidad 1.000 | FixtureReader paginado, clasificación lote 100 | benchmark.json: 100/300/500/1.000 | Medida en fixtures; no extrapolar a Gmail |
| Reanudación sin pérdida | store.ingest transacción + checkpoint + snapshots | test_atomic_ingest_and_genuine_update; test_recover_interrupted_pagination | Probado |
| Reintentos acotados | ReaderHTTP + operations + Budget | 429, 403, agotamiento persistente y Retry-After | Probado |
| Sin efectos secundarios duplicados | sends UNIQUE execution_id, PREPARADO, incertidumbre | test_uncertain_send_never_repeated; test_maintenance_never_resends | Probado con adaptador simulado |
| Excel seguro | neutralización, hash, validación, locks | test_report_styles_formula_chart_and_hash, corrupt_template, windows_locked_workbook | openpyxl/Win32 probados; Office pendiente |
| Auditoría/exportación/limpieza | panel.py, retention.py, maintenance.py, log_files.py | test_retention_panel.py, test_maintenance.py, test_cloud_logs.py | Exportación manual con confirmación; política de retención automática de archivos configurable |
| Supabase y logs con caducidad | cloud_logs.py, log_files.py, migración Supabase | test_cloud_logs.py y supabase_real_checks.json | Conexión real verificada: 9 registros, upsert sin duplicados y descarga con hash; fallos/reintentos/retención probados localmente |
| Entregables | build_deliverables.py | PDF técnico, PPTX/PDF, guion, diagramas y ZIP con hashes | Generados a partir de fuentes y resultados locales |

Los nombres de prueba corresponden a `tests/`. El XML JUnit indica fecha, cantidad y resultado de la corrida final. Los archivos en `docs/evidence` no contienen tokens ni correos reales. La presentación debe mostrar las limitaciones junto a los resultados, no ocultarlas.
