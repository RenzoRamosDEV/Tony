import inspect

from tony.apps.cli.main import create_app
from tony.core.orchestrator.claude_engine import ClaudeEngine


def test_cli_runs_tasks_on_the_claude_engine_by_default():
    default = inspect.signature(create_app).parameters["engine_factory"].default

    assert default is ClaudeEngine
