"""The example policy the spec requires agents/edith/policy.yaml to equal."""

import yaml

SHIPPED_POLICY_YAML = r"""
default: confirm
rules:
  - match: "filesystem.read_*"
    verdict: allow
  - match: "filesystem.list_*"
    verdict: allow
  - match: "filesystem.write_file"
    verdict: confirm
    when:
      path_outside: ["~/notas", "~/proyectos"]
  - match: "filesystem.write_file"
    verdict: allow
  - match: ["filesystem.delete*", "filesystem.move_file"]
    verdict: confirm
  - match: "shell.run"
    verdict: deny
    when:
      args_regex: "(rm -rf|sudo|mkfs|curl .*\\| *sh)"
  - match: "shell.run"
    verdict: confirm
  - match: "github.search_*"
    verdict: allow
  - match: "github.*"
    verdict: confirm
  - match: ["tony.read_skill", "tony.run_subagent"]
    verdict: allow
limits:
  tool_timeout_s: 20
  task_timeout_s: 300
  confirm_timeout_s: 60
  max_denied_retries: 3
  token_alert: 50000
  max_steps_per_agent: 30
auth: {pin_required: true, lock_after_min: 30}
"""

SHIPPED_POLICY_DATA = yaml.safe_load(SHIPPED_POLICY_YAML)
