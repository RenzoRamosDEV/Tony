import re

from tony.core.config.placeholders import SecretMasker
from tony.core.config.secrets import load_variables
from tony.core.config.settings import TonyConfig
from tony.core.events import core_events
from tony.core.events.core_events import MaskingPublisher, ReplyMode
from tony.core.events.messages import TaskRequest, TaskResult
from tony.core.guard.session import SessionGate
from tony.core.memory.history import HistoryStore, StoredMessage
from tony.core.memory.preferences import PreferencesFile
from tony.core.orchestrator.agents import AgentSlots
from tony.core.orchestrator.front_tools import WAITING_AFTER_S, FrontTools
from tony.core.orchestrator.ports import ChatEngine
from tony.core.orchestrator.runner import RunDeps, agent_tools, run_task

PREFERENCES_HEADING = "## Preferencias del usuario"
USER_LABEL = "usuario"
_MODE_PREFIX = re.compile(r"^/([vt])(?: |$)")
_PREFIX_MODES: dict[str, ReplyMode] = {"v": "voice", "t": "text"}


class Conversation:
    """One front-agent turn per user message: history, preferences, control tools, streaming."""

    def __init__(
        self,
        *,
        slots: AgentSlots,
        config: TonyConfig,
        deps: RunDeps,
        chat_engine: ChatEngine,
        gate: SessionGate,
        history: HistoryStore,
        conversation_id: str,
        waiting_after_s: float = WAITING_AFTER_S,
    ) -> None:
        self.front = slots.front
        self._worker = slots.worker.name
        self._config = config
        self._deps = deps
        self._chat_engine = chat_engine
        self._gate = gate
        self._history = history
        self._conversation_id = conversation_id
        masker = SecretMasker(load_variables(deps.root, deps.environ).env_file_values.values())
        self._masker = masker
        self._publish = MaskingPublisher(masker, deps.publish)
        self.preferences = PreferencesFile(deps.root, masker)
        self._front_tools = FrontTools(
            front_agent=self.front.name,
            preferences=self.preferences,
            gate=gate,
            run_worker=self._run_worker,
            publish=self._publish,
            waiting_after_s=waiting_after_s,
        )

    def reply_mode(self) -> ReplyMode:
        return self.preferences.reply_mode() or self._config.reply_mode

    async def handle(self, text: str) -> str | None:
        """Answer one user message; returns the reply, or None when the model failed."""
        relocked = self._gate.session.touch()
        if relocked is not None:
            self._publish(core_events.auth(*relocked))
        message, mode = self._split_mode(text)
        earlier = self._history.recent(self._conversation_id)
        self._history.add(self._conversation_id, "user", self.front.name, message)
        try:
            reply = await self._converse(message, earlier)
        except Exception as error:
            self._publish(core_events.error("front", str(error) or type(error).__name__))
            return None
        self._history.add(self._conversation_id, "assistant", self.front.name, reply)
        self._publish(core_events.turn_result(self.front.name, reply, mode))
        return reply

    async def _converse(self, message: str, earlier: list[StoredMessage]) -> str:
        model_id = self._config.resolve_model(self.front.spec.model)
        async with agent_tools(self.front, self._config, self._deps) as own_tools:
            outcome = await self._chat_engine.converse(
                self.front.spec,
                self._system_prompt(),
                self._prompt(message, earlier),
                [*self._front_tools.tools(), *own_tools],
                model_id,
                lambda chunk: self._publish(core_events.token(self.front.name, chunk)),
            )
        return outcome.text

    def _split_mode(self, text: str) -> tuple[str, ReplyMode]:
        match = _MODE_PREFIX.match(text)
        if match is None:
            return text, self.reply_mode()
        return text[match.end() :], _PREFIX_MODES[match.group(1)]

    def _system_prompt(self) -> str:
        preferences = self._masker.mask(self.preferences.read()).strip()
        body = self.front.spec.system_prompt
        return f"{body}\n\n{PREFERENCES_HEADING}\n{preferences}" if preferences else body

    def _prompt(self, message: str, earlier: list[StoredMessage]) -> str:
        current = f"<mensaje>\n{message}\n</mensaje>"
        if not earlier:
            return current
        lines = "\n".join(
            f"{USER_LABEL if item.role == 'user' else item.agent}: {item.content}"
            for item in earlier
        )
        return f"<historial>\n{lines}\n</historial>\n{current}"

    async def _run_worker(self, request: TaskRequest) -> TaskResult:
        return await run_task(self._worker, request, self._deps)
