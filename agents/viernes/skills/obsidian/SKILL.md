---
name: obsidian
description: Busca, lee y edita notas del vault de Obsidian de Renzo (crear, editar, mover o borrar siempre con confirmación).
---
Procedimiento para trabajar con `obsidian` (vault `notas`):

1. Para buscar o leer (`obsidian_list_vaults`, `obsidian_read_note`, `obsidian_search_vault`)
   no hace falta confirmación: resuelve directamente.
2. Para crear, editar, mover o borrar (`obsidian_create_note`, `obsidian_edit_note`,
   `obsidian_delete_note`, `obsidian_move_note`, `obsidian_create_directory`,
   `obsidian_add_tags`, `obsidian_remove_tags`, `obsidian_rename_tag`, `obsidian_manage_tags`),
   confirma siempre con el usuario la nota y el cambio exacto antes de ejecutarlo; son tools
   que ya exigen confirmación en la configuración, pero igualmente resume la acción propuesta
   en tu respuesta.
3. Un borrado no es irreversible por defecto: `obsidian_delete_note` mueve la nota a la
   papelera del propio vault salvo que se indique lo contrario; aun así, trátalo como una
   acción seria y confírmalo igual.
4. Respeta la estructura de carpetas y el formato (frontmatter, tags) que ya tenga el vault;
   no inventes convenciones nuevas sin que el usuario las pida.
5. Si Obsidian devuelve un error (ruta inválida, nota inexistente, vault no encontrado), dilo
   con claridad en `errores` en vez de inventar un resultado.
