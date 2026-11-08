---
name: drive
description: Busca y lee archivos de Google Drive, incluyendo hojas de cálculo (editar celdas siempre con confirmación).
---
Procedimiento para trabajar con `gdrive`:

1. Para buscar o leer (`gdrive_search`, `gdrive_read_file`, `gsheets_read`) no hace falta
   confirmación: resuelve directamente.
2. Para modificar una hoja de cálculo (`gsheets_update_cell`), confirma siempre con el
   usuario el archivo, la celda y el valor exacto antes de ejecutarlo; es una tool que ya
   exige confirmación en la configuración, pero igualmente resume la acción propuesta en tu
   respuesta.
3. No asumas el contenido de un archivo que no hayas leído; si necesitas confirmar un dato
   antes de actuar, léelo primero con `gdrive_read_file` o `gsheets_read`.
4. Si Drive devuelve un error (token caducado, permisos, archivo no encontrado), dilo con
   claridad en `errores` en vez de inventar un resultado.
5. Al resumir resultados de búsqueda, prioriza nombre, tipo y fecha de modificación; no
   reproduzcas el contenido completo de un documento salvo que el usuario lo pida.
