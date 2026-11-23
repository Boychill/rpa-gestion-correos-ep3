> Para la integración principal Gmail, consultar GOOGLE_CLOUD_GMAIL.md y PRUEBAS_GMAIL.md. Las instrucciones Microsoft de este documento conservan la compatibilidad histórica; no son un requisito para Gmail.

# Completar las pruebas reales en Windows

Estado al 23/11/2026: se comprobó renovación de tokens de ambos roles Gmail, identidad y lectura del receptor, consulta del esquema Supabase y API pública de feriados. No se enviaron correos ni se probó Graph con un buzón real. Excel y Outlook COM no están registrados en este equipo. Consulta [la validación actual y sus evidencias](VALIDACION_2026-11-23.md); las instrucciones siguientes permiten completar las comprobaciones de Microsoft en otro entorno habilitado.

## Preparación de una cuenta autorizada

1. Usar un buzón propio de pruebas y una carpeta limitada. Registrar autorización de la cuenta y del único destinatario antes de habilitar envío. No usar una bandeja productiva para la demo.
2. En Microsoft Entra ID, registrar una aplicación pública de escritorio de un tenant permitido. Configurar plataforma móvil/escritorio y URI `http://localhost` para OAuth interactivo de MSAL. No crear un secreto de cliente.
3. Permisos delegados Microsoft Graph: `Mail.ReadBasic`. Añadir `Mail.Send` solo si se usará envío Graph. Consentimiento según política del tenant. El proyecto no requiere Mail.ReadWrite, User.Read ni permisos de aplicación para este diseño.
4. Copiar `.env.example` a `.env`. Configurar `SOURCE=GRAPH`, `PROFILE=prueba`, `CLIENT_ID`, `TENANT_ID`, `MAILBOX`, `FOLDER_ID` y el período ISO UTC. Mantener `MAIL_MODE=DRY_RUN`. `FOLDER_ID=inbox` sirve para la bandeja de entrada de pruebas; un ID de carpeta específica limita mejor el alcance.
5. Usar un runtime separado, por ejemplo `RUNTIME_DIR=runtime/prueba-real`, y `HOLIDAY_MODE=LIVE`. Ejecutar `scripts/run.ps1 run`. Iniciar sesión con el buzón exacto configurado. Los alias que no coincidan con el claim de identidad se rechazan deliberadamente: utilizar el UPN devuelto por el tenant.
6. Verificar cantidad, categoría, regla y versión en SQLite local, y evidencia redactada en Excel. Introducir mensajes de prueba: solicitud, consulta, reclamo, urgencia, información, vacío/sin señal. No usar correos reales de terceros como fixtures.

## Excel de escritorio

Instalar y activar Excel de escritorio con automatización COM y abrirlo una vez bajo el usuario que ejecutará el bot. Cerrar el libro de destino. Establecer `REQUIRE_EXCEL=true` y ejecutar. El proceso aislado abre la copia absoluta, escribe `COM_VERIFICADO` en Ejecuciones F2, recalcula, guarda, cierra y reabre. Guarda versión, valor antes/después, total recalculado y verificación de reapertura en `excel_desktop.json`.

Tomar capturas redactadas del libro antes y después para la exposición; el JSON prueba las operaciones del adaptador, no es una captura de pantalla. Ejecutar `scripts/verify_real.py` para la prueba acotada sin correo. Si COM queda bloqueado por una ventana de licencia/perfil, el timeout detiene el worker y falla la ejecución; verificar manualmente la instancia de Excel antes de reanudar. No se fuerza el cierre de todas las aplicaciones Office del usuario.

## Outlook y envío de un reporte

El adaptador preferido requiere Outlook clásico con un perfil iniciado y una cuenta cuyo SMTP coincida con MAILBOX. Outlook nuevo no es un reemplazo transparente para este adaptador; elegir `MAIL_ADAPTER=GRAPH` si se autoriza esa alternativa y mantener la prueba de Excel independiente.

Configurar simultáneamente:

```dotenv
SOURCE=GRAPH
HOLIDAY_MODE=LIVE
REQUIRE_EXCEL=true
MAIL_MODE=SEND
MAIL_ADAPTER=OUTLOOK
SEND_AUTHORIZED=true
MAILBOX=cuenta-de-prueba@dominio.example
RECIPIENT=destinatario-de-prueba@dominio.example
ALLOWED_RECIPIENTS=destinatario-de-prueba@dominio.example
```

Los dominios de ejemplo no son cuentas utilizables. Antes de ejecutar, sustituirlos por valores expresamente autorizados. Usar una nueva prueba con mensajes nuevos y un perfil/runtime propio. Una ejecución completada como DRY_RUN no se transforma en envío al reanudarla. Para Graph, elegir explícitamente `MAIL_ADAPTER=GRAPH`; el cliente solicitará Mail.Send al autenticar.

El bot envía como máximo un consolidado por ejecución. Adjuntos mayores o iguales a 3.000.000 bytes se rechazan; no se implementaron sesiones de carga grandes. Guardar asunto con UUID, manifiesto y hash, evento ACEPTADO y captura redactada de recepción en el destinatario. Confirmar entrega con el comando reconcile y una evidencia local no vacía. Nunca deducir entrega a partir de HTTP 202, la carpeta Enviados o una vista previa.

## Fallos y cierre

Probar con la suite automatizada el libro bloqueado, API incompleta, paginación interrumpida, HTTP 429, destinatario inválido y envío incierto. Para una prueba manual, cerrar el proceso después de PREPARADO y revisar el estado en la reanudación: no debe producir un segundo envío. Reconciliar es separado de ejecutar.

Restaurar `MAIL_MODE=DRY_RUN` y `SEND_AUTHORIZED=false` al finalizar. No publicar la base, la configuración, direcciones o capturas sin redactar. Registrar fecha, versión de Office, cuenta seudonimizada, alcance y resultado en una nueva evidencia; no sobrescribir los resultados originales como si hubieran ocurrido en el equipo inicial.
