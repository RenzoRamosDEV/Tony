# Spec Delta

## Purpose

Defines how Tony converses by voice: transcripts as user messages, when a reply is spoken or written, how replies are streamed as speech sentence by sentence, what is never spoken, and how Edith's confirmations are asked and answered by voice.

## ADDED Requirements

### Requirement: Transcript as a user message
A transcript that is not a confirmation answer SHALL be published as a `transcript` event and sent to the front agent exactly as a typed message, with origin `voice`: the same mode prefixes, history, preferences and tools apply.

#### Scenario: Spoken question
- **WHEN** the user says «¿Qué hora es?» and no confirmation is pending
- **THEN** a `transcript` event with text `¿Qué hora es?` is published and the front agent receives `¿Qué hora es?` as the current message, stored in the history as a user message

### Requirement: Speak and write decision
For each turn, the applied reply mode (prefix or persisted) SHALL decide: `voice` speaks and does not write, `text` writes and does not speak, `both` speaks and writes, `auto` speaks and does not write when the origin is `voice`, and writes and does not speak otherwise. When voice is not `ready`, the turn SHALL write and not speak.

#### Scenario: Decision table
- **WHEN** the decision is computed for (mode, origin, voice ready): (`voice`, text, yes), (`text`, voice, yes), (`both`, text, yes), (`auto`, voice, yes), (`auto`, text, yes), (`voice`, voice, no)
- **THEN** (speaks, writes) is respectively (yes, no), (no, yes), (yes, yes), (yes, no), (no, yes), (no, yes)

#### Scenario: Full reply always in the chat
- **WHEN** a turn speaks and does not write
- **THEN** the reply is not shown token by token, and the full reply text is shown in the chat when the turn's `result` event arrives

### Requirement: Sentence-streamed speech
In a speaking turn, the reply SHALL be split into sentences while it streams and each sentence SHALL be synthesised and played as soon as it is complete, in order, before the full reply exists. A sentence ends at `.`, `!`, `?` or `…` followed by whitespace or the end of the reply, or at a line break.

#### Scenario: Playback starts early
- **WHEN** the reply streams as `Buenas tardes, señor.` then, 2 s later, ` Hace sol.`
- **THEN** `Buenas tardes, señor.` is played before ` Hace sol.` has arrived

#### Scenario: Decimal not split
- **WHEN** the reply is `Cuesta 3.5 euros.`
- **THEN** one sentence `Cuesta 3.5 euros.` is spoken

#### Scenario: Line break ends a sentence
- **WHEN** the reply is `Opciones:\nla primera`
- **THEN** the sentences `Opciones:` and `la primera` are spoken

### Requirement: Spoken voice per agent
Each spoken text SHALL use the voice of the agent that produced it: front-agent reply sentences and its `progress` messages use the front agent's voice, and confirmation questions use the guard agent's voice.

#### Scenario: Waiting phrase spoken
- **WHEN** a speaking turn delegates a task that emits the `progress` text `Un momento, señor; estoy en ello.`
- **THEN** that text is spoken with Jarvis' voice

### Requirement: Code and tables not spoken
Fenced code blocks and Markdown tables SHALL never be spoken; each SHALL be replaced in the spoken stream by «Te lo dejo en pantalla.», and two replacements with nothing spoken between them SHALL be spoken once. Markdown markup (emphasis, heading and list markers, inline code backticks, link targets) SHALL NOT be read aloud.

#### Scenario: Code block replaced
- **WHEN** the reply is the line `Aquí tiene:`, a fenced `python` code block containing `print(1)`, and the line `Listo.`
- **THEN** the spoken sentences are `Aquí tiene:`, `Te lo dejo en pantalla.` and `Listo.`

#### Scenario: Table replaced
- **WHEN** the reply contains the lines `| a | b |`, `|---|---|` and `| 1 | 2 |`
- **THEN** those lines are spoken as a single `Te lo dejo en pantalla.`

#### Scenario: Markup removed
- **WHEN** the reply is `Es **muy** importante: ver [la guía](https://x.test).`
- **THEN** the spoken sentence is `Es muy importante: ver la guía.`

### Requirement: Long replies spoken briefly
A reply longer than 600 characters SHALL be spoken as its first two spoken sentences followed by «Te lo dejo en pantalla.». Sentences after the second SHALL be held until the reply is known to be at most 600 characters (then spoken) or longer (then dropped).

#### Scenario: Long reply
- **WHEN** the reply has five sentences and 900 characters
- **THEN** exactly the first two sentences and `Te lo dejo en pantalla.` are spoken

#### Scenario: Reply of exactly 600 characters
- **WHEN** the reply has four sentences and 600 characters
- **THEN** all four sentences are spoken and the phrase is not added

### Requirement: Speech stops with the turn
A front-agent model error, `cancel` or a new listening session SHALL stop the speech of the current turn and discard its pending sentences.

#### Scenario: Cancel while speaking
- **WHEN** a reply is being spoken and the user sends `cancel`
- **THEN** playback stops and no further sentence of that reply is played

### Requirement: Confirmation asked by voice
When a confirmation is pending during a speaking turn, its question SHALL be spoken with the guard agent's voice, without the `Regla: <rule id>.` part, after the sentences already queued; then a listening session for the answer SHALL start, lasting until the request is answered or times out. The banner SHALL still be shown.

#### Scenario: Question spoken
- **WHEN** in reply mode `voice` the question `Acción: borrar el archivo /home/renzo/notas/viejo.md. Regla: filesystem.delete*/confirm. ¿Autoriza?` is pending
- **THEN** `Acción: borrar el archivo /home/renzo/notas/viejo.md. ¿Autoriza?` is spoken with Edith's voice and listening starts after it is played

#### Scenario: Text turn not spoken
- **WHEN** a confirmation is pending during a turn in reply mode `text`
- **THEN** nothing is spoken, the microphone is not opened and only the banner is shown

### Requirement: Spoken confirmation answer
While a spoken confirmation is pending, the next transcript SHALL answer it and SHALL NOT start a turn: after lowercasing, removing accents and punctuation and collapsing spaces, exactly `si edith` SHALL answer yes; any other transcript SHALL answer no. No transcript before `confirm_timeout_s` SHALL be a timeout. An answer from the banner SHALL end the listening.

#### Scenario: Yes by voice
- **WHEN** reply mode is `voice`, a confirmation for `filesystem.delete_file` is pending and the user says «Sí, Edith.»
- **THEN** the tool runs and the audit line has `user_decision: "allow"`

#### Scenario: Anything else is no
- **WHEN** a spoken confirmation is pending and the user says «vale»
- **THEN** the tool is not run, the task is cancelled and the audit line has `user_decision: "deny"`

#### Scenario: Normalisation
- **WHEN** the transcript is `¡SÍ, Edith!` or ` si   edith `
- **THEN** the answer is yes, and for `sí edith por favor` or `sí` it is no

#### Scenario: Silence times out
- **WHEN** a spoken confirmation is pending and nothing is said within `confirm_timeout_s`
- **THEN** the audit line has `user_decision: "timeout"` and the microphone is closed

#### Scenario: Banner answers first
- **WHEN** a spoken confirmation is pending and the user clicks «Permitir»
- **THEN** the tool runs, listening stops and a later transcript starts a normal turn

### Requirement: Latency benchmark
A `voice`-marked benchmark test SHALL measure the time to the first text token of a reply and, from the end of an utterance, the time to the first played audio of a reply without tools, and SHALL report the p50 of each without asserting the targets (1 s and 2 s).

#### Scenario: Benchmark does not gate
- **WHEN** `uv run pytest -m voice` runs the benchmark and the voice p50 is 9 s
- **THEN** both p50 values are reported and the test passes
