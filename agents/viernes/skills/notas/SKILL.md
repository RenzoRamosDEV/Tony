---
name: notas
description: Lee y escribe ficheros en la carpeta de notas del usuario con nombres y rutas claras.
trigger: ["guarda una nota", "apunta esto", "lee mi nota", "busca en mis notas", "crea un fichero"]
---
Procedimiento para trabajar con `filesystem` (carpeta de notas del usuario):

1. Antes de escribir, lista o lee el directorio relevante para confirmar si el fichero ya
   existe; no sobrescribas sin comprobarlo primero.
2. Usa nombres de fichero descriptivos en minúsculas con guiones (`reunion-semanal.md`,
   no `Nota1.txt`), y la extensión `.md` para notas de texto salvo que el usuario pida otra.
3. `write_file`, `edit_file` y `move_file` exigen confirmación del usuario: antes de
   llamarlas, resume en tu respuesta qué vas a escribir, mover o sobrescribir y por qué.
4. `read_file`, `read_text_file` y `list_directory` no necesitan confirmación: resuelve
   directamente.
5. Si una ruta pedida por el usuario queda fuera de la carpeta de notas permitida, dilo
   claramente en `errores` en vez de intentar una ruta distinta sin avisar.
