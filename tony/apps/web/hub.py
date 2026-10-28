"""One open chat session per server, one active socket per conversation (design.md D4)."""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from tony.apps.web.audio_ws import AUDIO_BACKPRESSURE, AudioSession
from tony.apps.web.confirmations import ConfirmationRouter, InvalidConfirmation, WebConfirmGate
from tony.apps.web.echo import is_echo
from tony.apps.web.playback_window import PlaybackWindow
from tony.apps.web.protocol import (
    AUDIO_END,
    AUDIO_FRAME_MAX_BYTES,
    AUDIO_START,
    CANCEL,
    CLOSE_GOING_AWAY,
    CLOSE_POLICY_VIOLATION,
    CONFIRM,
    ERROR,
    HELLO,
    HELLO_OK,
    PLAYBACK_STOPPED,
    SET_MODE,
    STT_FINAL,
    USER_TEXT,
    BinaryFrame,
    ClientMessage,
    ConversationStream,
    Envelope,
    OutboundQueue,
)
from tony.apps.web.tts_stream import SpeechStreamer
from tony.apps.web.voice import VoiceRuntime
from tony.apps.web.ws_channel import UsageTracker, WebChannel
from tony.core.channels.bootstrap import ChatRuntime
from tony.core.channels.ports import AssistantReply
from tony.core.config import TonySettings
from tony.core.loader import AgentSpec
from tony.core.orchestrator.clock import Clock
from tony.core.orchestrator.errors import OrchestratorError
from tony.core.runner.reply_mode import InputModality
from tony.core.voice.ports import Transcript

WEB_CHANNEL = "web"
TURN_CRASHED = "No pude completar el turno por un error interno: {error}"
HELLO_REQUIRED = "envía hello antes de cualquier otro mensaje"
UNKNOWN_CONVERSATION = "la conversación {} no existe"
SOCKET_BUSY = "la conversación ya tiene un socket activo"
CONVERSATION_BUSY = "hay otra conversación en curso"
TURN_CLOSE_BUDGET_S = 5.0
DRAIN_BUDGET_S = 1.0
AUDIO_IN_PROGRESS = "ya hay una intervención de audio abierta"
AUDIO_NOT_STARTED = "envía audio.start antes de los frames de audio"
FRAME_TOO_LARGE = "frame de audio de {size} bytes; el máximo es {limit}"
AUDIO_OVER_BUDGET = "demasiado audio pendiente de procesar; se descartó el frame"
NO_SPEECH = "no hay síntesis en curso para el mensaje {}"
NO_TARGET = "cancel necesita task_id o message_id"
BARGE_IN_EVENT = "barge_in"
ECHO_EVENT = "barge_in.echo"
INTERRUPTED_TURN_WAIT_S = 3.0
HelloDecision = Literal["open", "attach", "switch", "busy_same", "busy_other", "unknown"]


class SocketLike(Protocol):
    async def send_text(self, text: str) -> None: ...

    async def send_bytes(self, data: bytes) -> None: ...

    async def close(self, code: int = 1000) -> None: ...


@dataclass(frozen=True)
class HubState:
    conversation_id: str | None
    has_socket: bool
    busy: bool


def decide_hello(state: HubState, requested: str | None, exists: bool) -> HelloDecision:
    if requested is not None and not exists:
        return "unknown"
    if state.conversation_id is None:
        return "open"
    if requested == state.conversation_id:
        return "busy_same" if state.has_socket else "attach"
    if state.has_socket or state.busy:
        return "busy_other"
    return "switch"


def error_envelope(code: str, detail: str, conversation_id: str | None = None) -> Envelope:
    return Envelope(
        type=ERROR, seq=0, conversation_id=conversation_id, payload={"code": code, "detail": detail}
    )


class ConversationHub:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self.router: ConfirmationRouter | None = None
        self.gate: WebConfirmGate | None = None
        self.usage: UsageTracker | None = None
        self.stream: ConversationStream | None = None
        self.channel: WebChannel | None = None
        self.conversation_id: str | None = None
        self.socket: SocketLike | None = None
        self.turn: asyncio.Task[None] | None = None
        self.audio: AudioSession | None = None
        self.playback = PlaybackWindow(clock.monotonic)
        self._echo_reference = ""
        self._interrupted_turn: asyncio.Task[None] | None = None
        self._emitter: asyncio.Task[None] | None = None
        self._queue: OutboundQueue | None = None
        self._runtime: ChatRuntime | None = None
        self._voice: VoiceRuntime | None = None
        self._transition = asyncio.Lock()
        self._admission = asyncio.Lock()

    def gate_factory(self, settings: TonySettings, front: AgentSpec) -> WebConfirmGate:
        limits = settings.limits
        self.router = ConfirmationRouter(
            now=self._clock.monotonic, timeout_s=limits.confirm_timeout_s
        )
        self.usage = UsageTracker(limits.token_alert)
        self.gate = WebConfirmGate(self.router, None, limits.confirm_timeout_s, self._clock)
        return self.gate

    def bind(self, runtime: ChatRuntime, voice: VoiceRuntime | None = None) -> None:
        self._runtime = runtime
        self._voice = voice or VoiceRuntime.disabled(runtime.settings.voice)

    @property
    def runtime(self) -> ChatRuntime:
        assert self._runtime is not None, "bind() must run before serving"
        return self._runtime

    @property
    def voice(self) -> VoiceRuntime:
        assert self._voice is not None, "bind() must run before serving"
        return self._voice

    @property
    def turn_in_progress(self) -> bool:
        return self.turn is not None and not self.turn.done()

    def state_for(self, socket: SocketLike | None) -> HubState:
        """Hub state as seen by `socket`: its own attachment never counts as a competing one."""
        session = self.runtime.session
        busy = self.turn_in_progress or (session is not None and session.has_active_task)
        other_socket = self.socket is not None and self.socket is not socket
        return HubState(self.conversation_id, other_socket, busy)

    async def dispatch(self, socket: SocketLike, message: ClientMessage) -> None:
        payload = message.payload
        if message.type == HELLO:
            await self.hello(socket, payload.get("conversation_id"), payload.get("last_seq", 0))
        elif socket is not self.socket:
            await self._error(socket, "hello_required", HELLO_REQUIRED)
        elif message.type == USER_TEXT:
            await self.user_text(payload.get("text", ""), payload.get("client_id"))
        elif message.type == CONFIRM:
            await self.confirm(
                payload.get("confirmation_id", ""),
                payload.get("approved", False),
                payload.get("task_id"),
            )
        elif message.type == CANCEL:
            await self.cancel(payload.get("task_id"), payload.get("message_id"))
        elif message.type == SET_MODE:
            await self.set_mode(payload.get("reply_mode", ""))
        elif message.type == AUDIO_START:
            await self.audio_start()
        elif message.type == AUDIO_END:
            await self.audio_end()
        elif message.type == PLAYBACK_STOPPED:
            self.playback.stopped(payload["message_id"])

    async def hello(self, socket: SocketLike, requested: str | None, last_seq: int) -> None:
        async with self._transition:
            exists = requested is not None and self.runtime.memory.conversations.has_conversation(
                requested
            )
            decision = decide_hello(self.state_for(socket), requested, exists)
            if decision == "unknown":
                await self._error(
                    socket, "unknown_conversation", UNKNOWN_CONVERSATION.format(requested)
                )
            elif decision == "busy_same":
                await self._error(socket, "conversation_busy", SOCKET_BUSY)
                await socket.close(CLOSE_POLICY_VIOLATION)
            elif decision == "busy_other":
                await self._error(socket, "conversation_busy", CONVERSATION_BUSY)
            else:
                self.detach(socket)
                if decision == "switch":
                    await self._close_conversation()
                if decision in ("open", "switch"):
                    await self._open_conversation(requested)
                await self._attach(socket, last_seq)

    def detach(self, socket: SocketLike) -> None:
        if socket is not self.socket:
            return
        self.socket = None
        self._discard_audio()
        if self.stream is not None:
            self.stream.detach()
        self._queue = None
        emitter, self._emitter = self._emitter, None
        if emitter is not None and emitter is not asyncio.current_task():
            emitter.cancel()

    async def user_text(
        self,
        text: str,
        client_id: str | None = None,
        modality: InputModality = "text",
        message_id: str | None = None,
    ) -> None:
        assert self.socket is not None and self.channel is not None
        async with self._admission:
            if self.turn_in_progress:
                await self._error(
                    self.socket, "turn_in_progress", "espera a que termine la respuesta"
                )
                return
            if not text.strip():
                await self._error(self.socket, "empty_text", "el mensaje está vacío")
                return
            await self._cancel_speech()
            if self.channel is None:
                return
            self.channel.client_id = client_id
            self.turn = asyncio.create_task(self._run_turn(text, modality, message_id))

    # --- audio input ------------------------------------------------------------------------

    async def audio_start(self) -> None:
        assert self.socket is not None
        voice = self.voice
        if not voice.available or voice.registry is None:
            await self._error(self.socket, "voice_unavailable", voice.availability.reason or "")
            return
        if self.audio is not None and self.audio.capturing:
            await self._error(self.socket, "audio_in_progress", AUDIO_IN_PROGRESS)
            return
        await self._cancel_speech()
        if self.audio is not None:
            self.audio.open()
            return
        registry = voice.registry
        try:
            vad = await voice.executor.run(registry.get_vad)
        except Exception as exc:  # noqa: BLE001 - a broken engine is reported, not fatal
            detail = f"{exc.__class__.__name__}: {exc}"
            await self._error(self.socket, "voice_unavailable", detail)
            return
        if self.audio is not None or self.socket is None:
            return
        settings = self.runtime.settings.voice
        session = AudioSession(
            vad,
            lambda: registry.get_stt(registry.stt_alias),
            voice.executor,
            self.runtime.front.persona.language,
            lambda transcript, interrupting: self._on_transcript(session, transcript, interrupting),
            lambda code, detail: self._on_audio_error(session, code, detail),
            self.runtime,
            end_silence_ms=settings.end_silence_ms,
            barge_in=settings.barge_in,
            barge_in_threshold=settings.barge_in_threshold,
            barge_in_min_speech_ms=settings.barge_in_min_speech_ms,
            speaking=self.playback.speaking,
            on_barge_in=lambda speech_ms: self._on_barge_in(session, speech_ms),
        )
        self.audio = session
        session.open()

    async def audio_frame(self, socket: SocketLike, data: bytes) -> None:
        if socket is not self.socket:
            await self._error(socket, "hello_required", HELLO_REQUIRED)
            return
        if len(data) > AUDIO_FRAME_MAX_BYTES:
            detail = FRAME_TOO_LARGE.format(size=len(data), limit=AUDIO_FRAME_MAX_BYTES)
            await self._error(socket, "audio_frame_too_large", detail)
            return
        if self.audio is None or not self.audio.capturing:
            await self._error(socket, "audio_not_started", AUDIO_NOT_STARTED)
            return
        if not self.audio.feed(data):
            await self._error(socket, AUDIO_BACKPRESSURE, AUDIO_OVER_BUDGET)

    async def audio_end(self) -> None:
        assert self.socket is not None
        if self.audio is None or not self.audio.capturing:
            await self._error(self.socket, "audio_not_started", AUDIO_NOT_STARTED)
            return
        self.audio.end()

    async def _on_barge_in(self, session: AudioSession, speech_ms: int) -> None:
        """The user speaks over Tony: silence him now and, if the front is still composing
        (and not waiting for a delegated task, which interrupting would cancel), stop it."""
        speech = self.channel.speech if self.channel is not None else None
        if self.audio is not session or speech is None:
            return
        playing = list(dict.fromkeys([*self.playback.playing(), *speech.speaking]))
        self.runtime.emit(
            BARGE_IN_EVENT,
            {"message_id": playing[0] if playing else None, "speech_ms": speech_ms},
        )
        self._echo_reference = speech.spoken_text(playing)
        await speech.stop_playing(playing)
        chat = self.runtime.session
        if chat is not None and chat.turn_in_progress and not chat.has_active_task:
            self._interrupted_turn = self.turn
            await chat.interrupt_turn()

    async def _on_transcript(
        self, session: AudioSession, transcript: Transcript, interrupting: bool = False
    ) -> None:
        """A transcript only counts while its session is still the conversation's current one."""
        stream = self.stream
        if self.audio is not session or self.socket is None or stream is None:
            return
        if interrupting:
            spoken, self._echo_reference = self._echo_reference, ""
            if is_echo(transcript.text, spoken):
                self.runtime.emit(ECHO_EVENT, {"chars": len(transcript.text)})
                return
        message_id = uuid.uuid4().hex
        await stream.publish(
            STT_FINAL, {"text": transcript.text, "message_id": message_id}, message_id=message_id
        )
        await self._settle_interrupted_turn()
        if self.audio is session and self.socket is not None:
            await self.user_text(transcript.text, modality="audio", message_id=message_id)

    async def _settle_interrupted_turn(self) -> None:
        """Give a turn cut short by the user's voice a moment to close before the next one."""
        turn, self._interrupted_turn = self._interrupted_turn, None
        if turn is not None and not turn.done():
            await asyncio.wait({turn}, timeout=INTERRUPTED_TURN_WAIT_S)

    async def _on_audio_error(self, session: AudioSession, code: str, detail: str) -> None:
        if self.audio is session and self.socket is not None:
            await self._error(self.socket, code, detail)

    def _discard_audio(self) -> AudioSession | None:
        audio, self.audio = self.audio, None
        if audio is not None:
            audio.discard()
        return audio

    async def _cancel_speech(self) -> None:
        if self.channel is not None and self.channel.speech is not None:
            await self.channel.speech.cancel_all()

    async def confirm(
        self, confirmation_id: str, approved: bool, task_id: str | None = None
    ) -> None:
        assert self.router is not None
        try:
            await self.router.resolve(confirmation_id, approved, task_id)
        except InvalidConfirmation as exc:
            if self.socket is not None:
                await self._error(self.socket, exc.code, exc.detail)

    async def cancel(self, task_id: str | None, message_id: str | None = None) -> None:
        assert self.socket is not None
        if message_id is not None:
            speech = self.channel.speech if self.channel is not None else None
            if speech is None or not await speech.cancel(message_id):
                await self._error(self.socket, "unknown_task", NO_SPEECH.format(message_id))
            return
        if task_id is None:
            await self._error(self.socket, "unknown_task", NO_TARGET)
            return
        try:
            await self.cancel_task(task_id)
        except OrchestratorError as exc:
            await self._error(self.socket, exc.code, f"la tarea {task_id} no existe")

    async def cancel_task(self, task_id: str) -> None:
        session = self.runtime.session
        if session is not None and task_id in session.active_task_ids:
            await session.cancel_active()
            return
        await self.runtime.orchestrator.cancel(task_id)

    async def set_mode(self, reply_mode: str) -> None:
        try:
            self.runtime.memory.settings.set_reply_mode(reply_mode)
        except ValueError as exc:
            if self.socket is not None:
                await self._error(self.socket, "invalid_reply_mode", str(exc))

    def reply_mode(self) -> str:
        persisted = self.runtime.memory.settings.load().reply_mode
        return persisted or self.runtime.settings.reply_mode

    async def aclose(self) -> None:
        try:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._silence_outbound(), DRAIN_BUDGET_S)
            socket = self.socket
            if socket is not None:
                self.detach(socket)
                with contextlib.suppress(Exception):
                    await socket.close(CLOSE_GOING_AWAY)
            session = self.runtime.session
            if session is not None and self.turn_in_progress:
                await session.interrupt()
            await self._settle_turn()
        finally:
            try:
                await self._close_conversation()
            finally:
                self.voice.close()

    async def _silence_outbound(self) -> None:
        """Cancel the speech and let the pump deliver what is queued (its `tts.cancelled`)."""
        await self._cancel_speech()
        if self._queue is not None:
            await self._queue.drained()

    async def _settle_turn(self) -> None:
        turn = self.turn
        if turn is None or turn.done():
            return
        turn.cancel()
        budget = asyncio.ensure_future(self._clock.sleep(TURN_CLOSE_BUDGET_S))
        await asyncio.wait({turn, budget}, return_when=asyncio.FIRST_COMPLETED)
        budget.cancel()
        await asyncio.gather(budget, return_exceptions=True)

    async def _open_conversation(self, requested: str | None) -> None:
        runtime = self.runtime
        assert self.router is not None and self.usage is not None and self.gate is not None
        conversation_id = requested or runtime.memory.conversations.start_conversation(WEB_CHANNEL)
        self.stream = ConversationStream(conversation_id, secrets=runtime.secrets)
        self.gate.stream = self.stream
        self.playback = PlaybackWindow(self._clock.monotonic)
        self.channel = WebChannel(
            self.stream,
            self.router,
            runtime.orchestrator,
            self.usage,
            runtime.options.logs_dir,
            runtime.settings.limits.confirm_timeout_s,
            self._clock,
            speech=self._speech_streamer(self.stream, self.playback),
        )
        self.conversation_id = conversation_id
        await runtime.open_session(conversation_id, self.channel)

    def _speech_streamer(
        self, stream: ConversationStream, playback: PlaybackWindow
    ) -> SpeechStreamer | None:
        voice = self.voice
        if not voice.available or voice.registry is None:
            return None
        registry = voice.registry
        return SpeechStreamer(
            stream,
            lambda: registry.get_tts(registry.tts_alias),
            voice.executor,
            registry.tts_voice,
            self.runtime,
            playback,
        )

    async def _close_conversation(self) -> None:
        audio = self._discard_audio()
        if audio is not None:
            await audio.aclose()
        channel, self.channel = self.channel, None
        self.conversation_id = None
        self.stream = None
        try:
            await self.runtime.close_session()
        finally:
            if channel is not None:
                await channel.close()

    async def _attach(self, socket: SocketLike, last_seq: int) -> None:
        assert self.stream is not None
        replay = self.stream.replay(last_seq)
        queue = OutboundQueue()
        queue.prefill(replay or [])
        self.socket = socket
        self._queue = queue
        self.stream.attach(queue)
        greeting = self._hello_ok(replay is None).to_json()
        try:
            await socket.send_text(greeting)
        except Exception:  # noqa: BLE001 - a socket that cannot take hello.ok is not attached
            self.detach(socket)
            return
        self._emitter = asyncio.create_task(self._pump(socket, queue))

    def _hello_ok(self, resync: bool) -> Envelope:
        assert self.stream is not None and self.router is not None
        payload: dict[str, Any] = {
            "conversation_id": self.conversation_id,
            "stream_id": self.stream.stream_id,
            "reply_mode": self.reply_mode(),
            "last_seq": self.stream.last_seq,
            "state": self._state_payload(),
        }
        if resync:
            payload["resync"] = True
        return Envelope(
            type=HELLO_OK,
            seq=0,
            conversation_id=self.conversation_id,
            payload=self.stream.redact(payload),
        )

    def _state_payload(self) -> dict[str, Any]:
        assert self.router is not None
        session = self.runtime.session
        active = session.active_task_ids if session is not None else set()
        tasks = self.runtime.orchestrator.tasks
        pending = self.router.pending()
        return {
            "turn_in_progress": self.turn_in_progress,
            "active_tasks": [
                {"task_id": task.id, "parent_id": task.parent_id, "status": task.status.value}
                for task in tasks.values()
                if task.id in active
            ],
            "pending_confirmation": None
            if pending is None
            else {
                "confirmation_id": pending.confirmation_id,
                "task_id": pending.task_id,
                "tool": pending.tool,
                "args": pending.args,
                "expires_in_s": pending.expires_in_s,
            },
        }

    async def _run_turn(
        self, text: str, modality: InputModality = "text", message_id: str | None = None
    ) -> None:
        session, channel = self.runtime.session, self.channel
        assert session is not None and channel is not None
        try:
            await session.handle(text, modality, message_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - the socket must learn that the turn died
            detail = f"{exc.__class__.__name__}: {exc}"
            await channel.send(
                AssistantReply(TURN_CRASHED.format(error=detail), None, "text", error=detail)
            )

    async def _pump(self, socket: SocketLike, queue: OutboundQueue) -> None:
        try:
            while True:
                item = await queue.get()
                if isinstance(item, BinaryFrame):
                    await socket.send_bytes(item.data)
                else:
                    await socket.send_text(item.to_json())
                queue.done()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a dead socket just detaches; the turn goes on
            self.detach(socket)

    async def _error(self, socket: SocketLike, code: str, detail: str) -> None:
        with contextlib.suppress(Exception):
            await socket.send_text(error_envelope(code, detail, self.conversation_id).to_json())
