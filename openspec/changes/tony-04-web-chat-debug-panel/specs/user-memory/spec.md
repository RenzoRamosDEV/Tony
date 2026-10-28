# Spec Delta

## MODIFIED Requirements

### Requirement: Operaciones del historial
El almacén SHALL exponer `start_conversation(channel) -> id`, `add_message(conversation_id, role, content, reply_mode) -> message_id`, `record_task(...)` con estado, tokens, coste y JSON de petición y resultado, `recent_messages(conversation_id, limit=40)` en orden cronológico, `messages(conversation_id)` con todos los mensajes (con `id`) en orden cronológico, `list_conversations(limit=20)` de la más reciente a la más antigua con `id`, `channel` y `created_at`, `has_conversation(id) -> bool` y `last_conversation(channel) -> id | None`.

#### Scenario: Mensajes recientes en orden
- **GIVEN** una conversación con 45 mensajes
- **WHEN** se llama a `recent_messages(id)` con el límite por defecto
- **THEN** devuelve los 40 más recientes en orden cronológico ascendente

#### Scenario: Tarea registrada con coste
- **WHEN** se llama a `record_task` con `status = "done"`, `tokens_in = 120`, `tokens_out = 40`, `cost_usd = 0.003` y un `TaskResult`
- **THEN** la fila de `tasks` conserva esos valores, `request_json` y `result_json` son JSON válidos y `finished_at` no es nulo

#### Scenario: Última conversación del canal
- **GIVEN** dos conversaciones del canal `cli` y una del canal `web`
- **WHEN** se llama a `last_conversation("cli")`
- **THEN** devuelve el id de la conversación `cli` más reciente; `last_conversation("voice")` devuelve `None`

#### Scenario: Identificador del mensaje
- **WHEN** se llama a `add_message(id, "user", "hola", None)`
- **THEN** devuelve el `id` del mensaje y `messages(id)` contiene un mensaje con ese mismo `id`

#### Scenario: Listado de conversaciones
- **GIVEN** 25 conversaciones creadas en orden en los canales `cli` y `web`
- **WHEN** se llama a `list_conversations()`
- **THEN** devuelve 20 elementos, el primero es la conversación más reciente y cada uno tiene `id`, `channel` y `created_at`

#### Scenario: Existencia de una conversación
- **GIVEN** la conversación `c1`
- **WHEN** se llama a `has_conversation("c1")` y `has_conversation("nope")`
- **THEN** devuelve `True` y `False` respectivamente
