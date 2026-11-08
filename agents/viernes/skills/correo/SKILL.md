---
name: correo
description: Lee, busca y gestiona el correo de Gmail (enviar, borrar o archivar siempre con confirmación).
---
Procedimiento para trabajar con `gmail`:

1. Para leer o buscar (`read_email`, `search_emails`, `list_email_labels`, `list_filters`,
   `get_filter`, `download_attachment`) no hace falta confirmación: resuelve directamente.
2. Para enviar, redactar, borrar o modificar (`send_email`, `draft_email`, `delete_email`,
   `modify_email`, `batch_delete_emails`, `batch_modify_emails`, cualquier operación sobre
   labels o filtros), confirma siempre con el usuario el destinatario, el asunto y la acción
   exacta antes de ejecutarla; son tools que ya exigen confirmación en la configuración, pero
   igualmente resume la acción propuesta en tu respuesta.
3. Nunca envíes un correo con contenido que el usuario no haya visto y aprobado tal cual; si
   te pide "redactar y enviar" en un solo paso, muéstrale primero el borrador completo.
4. Todo correo que envíes (`send_email`) debe terminar, tras una línea en blanco, con esta
   firma exacta, sin modificarla:

   ```
   Este mensaje fue redactado y enviado por TONY, el asistente personal de Renzo. Las
   decisiones de contenido fueron supervisadas por él.
   ```

   Inclúyela en el borrador que le muestras al usuario para confirmar, para que apruebe el
   correo tal como se enviará.
5. Si Gmail devuelve un error (token caducado, cuota, permisos), dilo con claridad en
   `errores` en vez de inventar un resultado.
6. Al resumir una búsqueda o bandeja, prioriza remitente, asunto y fecha; no repitas el
   cuerpo completo del correo salvo que el usuario lo pida.
