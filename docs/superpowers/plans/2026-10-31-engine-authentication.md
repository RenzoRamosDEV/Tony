# Selección de motor y autenticación

## Resultado solicitado

Desde el selector de Tony se podrá elegir Claude con la cuenta local, Codex con la cuenta de ChatGPT o un proveedor mediante API key. La selección debe determinar la autenticación real; no basta con cambiar la etiqueta.

## Estado observado

- El selector y GET/PATCH /api/engines ya existen como cambios locales sin confirmar.
- config/tony.yaml no declara perfiles adicionales: por eso solo aparece Claude.
- Hay adaptadores claude_sdk, codex_cli y litellm.
- El cambio actual afecta únicamente al front. El worker conserva su motor y podría seguir consumiendo Claude.
- LiteLLM actualmente toma credenciales del entorno; no existe un formulario de credenciales.

## Enfoques

1. Añadir perfiles YAML: permite elegir motores, pero no introducir una clave desde la interfaz ni garantizar la fuente de facturación.
2. Ampliar el selector existente con autenticación explícita: reutiliza los tres adaptadores y añade configuración de credenciales y cambio coherente de front y worker. Propuesta recomendada para cumplir la petición.

## Diseño propuesto

- Opciones visibles: Claude · cuenta, Codex · cuenta ChatGPT, API · OpenAI y API · Anthropic.
- Las opciones de cuenta usan las sesiones autenticadas de los CLI locales. Si falta la sesión, se presenta una instrucción de inicio de sesión; no se cambia silenciosamente a una API key.
- Las opciones de API muestran proveedor, modelo y un campo de contraseña para introducir la clave.
- La clave se conserva exclusivamente en el servidor en un fichero local excluido de Git, con permisos de propietario. Nunca se devuelve por GET ni se guarda en localStorage, historial o logs. La interfaz solo muestra si está configurada y permite reemplazarla o eliminarla.
- Las credenciales se suministran por invocación, sin modificar globalmente el entorno del proceso ni mezclar cuenta y API.
- La selección se aplica al front y al worker, incluyendo sus tareas nuevas. Se bloquea el cambio mientras haya trabajo activo.
- Cambiar inicia una conversación nueva y conserva el historial anterior. Los fallos restauran la configuración anterior.
- Se conservan los perfiles personalizados y los cambios locales existentes.

## Plan de implementación

- [x] Añadir perfiles y configuración explícita de autenticación, manteniendo compatibilidad con perfiles existentes.
- [x] Añadir almacenamiento local de secretos y endpoints que solo expongan estado, nunca la clave.
- [x] Conectar credenciales a cada adaptador y exigir autenticación de cuenta en los perfiles de cuenta.
- [x] Extender el cambio de motor al worker con persistencia y recuperación ante fallos.
- [x] Añadir formulario de proveedor, modelo y API key al selector existente.
- [x] Probar rutas de cuenta/API, aislamiento de credenciales, ausencia de secretos en respuestas/logs, cambio durante tareas y recuperación ante fallo.
- [x] Ejecutar pruebas de backend/frontend, Ruff, TypeScript y build. Las pruebas automatizadas no consumirán saldo real.

## Límites de verificación

Una cuenta conectada no demuestra que tenga cuota disponible. Las pruebas con consumo real requieren las credenciales del usuario; no se considerarán verificadas sin una ejecución real. No se iniciarán sesiones de terceros ni se solicitará pegar claves en el chat.

## Decisiones de implementación tras aprobación

El usuario aprobó el diseño. Ejecución directa en esta sesión, conservando los
cambios locales previos. La selección se persiste en `config/engine-auth.json`
en lugar de editar los archivos de agentes: permite aplicar un mismo motor a
front, worker y subagentes sin que una recarga de agentes lo revierta. Las
opciones predefinidas se incorporan al iniciar el runtime; los perfiles YAML
personalizados se conservan.

Se reutiliza NativeToolSet para conectar las herramientas de delegación a los
adaptadores Codex y LiteLLM, que antes no las exponían. Se corrige además la
posición del argumento de sandbox para `codex exec resume`, verificada con la
ayuda del CLI instalado.

Referencias de autenticación: https://learn.chatgpt.com/docs/auth?surface=cli
(`forced_login_method`) y opciones locales del SDK/CLI de Claude
(`forceLoginMethod`, entorno por proceso, sin fuentes de configuración locales).

## Verificación final

- 117 pruebas focalizadas de backend pasaron; después se añadió y pasó la prueba HTTP de credenciales/origen/redacción (12 pruebas del archivo API en total).
- 25 pruebas existentes de opciones y conversación Claude pasaron.
- 30 pruebas de los adaptadores Codex y su CLI falso pasaron; la prueba adicional de delegación y posición de sandbox también pasó en el conjunto focalizado.
- Suite completa de frontend: 319 pruebas, 31 archivos. Tras ajustar la normalización del modelo se repitió el selector y el build.
- Ruff y git diff --check sin errores. TypeScript y compilación Vite correctos.
- Una ejecución amplia inicial de tests/runner se interrumpió tras un timeout de AnyIO; los módulos modificados se verificaron por separado. No se afirma que toda la suite de Python haya pasado.
- No se realizaron llamadas de modelo con credenciales reales. Autenticación, rutas de facturación y fallos se prueban con dobles offline; no se verifica disponibilidad de cuota real.
- Reiniciar el proceso de Tony y recargar la web carga el backend y frontend nuevos. No se detuvieron procesos existentes.
