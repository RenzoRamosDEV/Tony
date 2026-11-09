---
name: musica
description: Reproduce música en el PC del usuario (buscar y poner canciones, cola, pausa, volumen, qué suena).
---
Procedimiento para trabajar con `music`:

1. Poner una canción o artista («ponme Bohemian Rhapsody») requiere confirmación del usuario.
   Primero llama a `music_search` con la búsqueda en `consulta`: no reproduce nada y devuelve
   `Encontrada: <título>`.
2. Con ese título, llama a `music_play` (sustituye lo que suene) o, si pide añadirla a
   continuación («añade», «pon después», «a la cola»), a `music_queue`, y pasa como `consulta`
   exactamente el título devuelto por `music_search`. Edith le mostrará al usuario ese título
   para que diga sí o no; no reproduzcas por otra vía ni repitas la pregunta tú.
   Si el usuario rechaza (la tool devuelve `blocked_by_policy`) o no responde, no insistas:
   di en `resumen` que no se reprodujo y no reintentes.
3. Para pausar, reanudar, saltar a la siguiente o volver a la anterior usa directamente
   `music_pause`, `music_resume`, `music_next` y `music_previous`; para parar del todo y vaciar
   la cola, `music_stop`.
4. Para el volumen usa `music_volume` con `nivel` entre 0 y 100; si el usuario dice «más alto»
   o «más bajo» sin cifra, consulta antes `music_now_playing` y ajusta unos 10-20 puntos.
5. Para responder «qué suena» usa `music_now_playing` y resume título, si está en pausa y el
   volumen; no inventes lo que suena.
6. Pausa, reanudar, siguiente, anterior, volumen, qué suena y parar se ejecutan al momento, sin
   confirmación ni `music_search`.
7. Si una tool devuelve un texto que empieza por `Error:` (falta instalar mpv o yt-dlp, nada
   encontrado, nada sonando), cuéntalo con claridad en `errores` en vez de inventar un resultado
   y, si falta una herramienta, indica que hay que instalarla.
