# Lote Gmail verificado

Resultado real: **500 aceptados, 500 recibidos, 500 clasificados correctamente, 0 faltantes y 0 duplicados**.
La distribución es 84 Solicitud, 84 Consulta y 83 de cada categoría restante.
328 llegaron a Inbox y 172 a Spam. La lectura del dataset incluye ambas ubicaciones sin modificar el buzón.

- Uso de la ventana: [DEMO_PRESENTACION.md](DEMO_PRESENTACION.md).
- OAuth, configuración y comandos: [GOOGLE_CLOUD_GMAIL.md](GOOGLE_CLOUD_GMAIL.md).
- Pruebas y pendientes: [PRUEBAS_GMAIL.md](PRUEBAS_GMAIL.md).

El lote `4aa43f17-2bb2-420a-96cd-0f91bee700a9` mantiene su manifiesto y estados en runtime/campaigns.
No prepares otro lote para reanudarlo. Los comandos send/run simulan por defecto y requieren
cantidad explícita y --execute para enviar. La correlación usa el identificador único de prueba
y From, porque Gmail puede sustituir Message-ID. El Excel acumulado ya está preparado;
su envío por correo es una acción separada pendiente de destinatario autorizado.
