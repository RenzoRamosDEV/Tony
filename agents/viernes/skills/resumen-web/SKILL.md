---
name: resumen-web
description: Resume una página web en 5 viñetas con fuente y fecha.
trigger: ["resume esta web", "resúmeme la página", "resume https"]
---
Procedimiento para resumir una página web:

1. Descarga la página con `fetch.fetch` (argumento `url`). Si la tool no está disponible,
   indícalo en `errores` y no inventes el contenido.
2. Extrae el contenido principal e ignora menús, cookies y publicidad.
3. Redacta exactamente 5 viñetas en español, cada una con una idea completa.
4. Cierra con una línea `Fuente: <url> (consultada el <fecha de hoy>)`.
5. Devuelve el resumen en `resumen` y las viñetas también en `datos` como lista.
