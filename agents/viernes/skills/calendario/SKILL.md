---
name: calendario
description: Consulta y gestiona Google Calendar en una o varias cuentas, con fechas relativas y confirmación antes de escribir.
---
Procedimiento para trabajar con `google-calendar`:

1. Antes de interpretar fechas relativas ("hoy", "mañana", "el viernes", "en dos semanas"),
   usa la fecha de hoy que tienes en el contexto del turno; nunca la calcules a ojo ni la
   inventes.
2. Si el usuario no pide una cuenta concreta, consulta todas las cuentas conectadas y junta
   los resultados en una sola respuesta, indicando de qué cuenta viene cada evento si hay
   más de una con resultados.
3. Para leer (`list-events`, `search-events`, `get-event`, `list-calendars`, `free-busy`) no
   hace falta confirmación: resuelve directamente.
4. Para crear, modificar o borrar un evento (`create-event`, `update-event`, `delete-event`),
   confirma siempre con el usuario el título, la fecha/hora y la cuenta antes de ejecutarlo;
   son tools que ya exigen confirmación en la configuración, pero igualmente resume la
   acción propuesta en tu respuesta.
5. Si una cuenta devuelve error (API deshabilitada, token caducado, sin acceso), dilo con
   claridad en `errores` y sigue con las cuentas que sí respondieron; no des una cuenta
   por vacía si en realidad falló.
6. Devuelve las fechas y horas en el huso horario del calendario consultado, no en UTC, y
   usa formato natural en español (ej. "17 de diciembre a las 18:00").
