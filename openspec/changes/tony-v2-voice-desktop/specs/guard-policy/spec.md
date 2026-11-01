# Spec Delta

## MODIFIED Requirements

### Requirement: Bundled Edith guard agent
The repository SHALL ship `agents/edith/` with `agent.md` (`role: guard`, `model: claude-haiku`, persona `language: es`, `tone: muy formal, neutral, literal, sin humor`, voice `kokoro/ef_dora,bf_emma`, a system prompt for wording confirmation questions) and `policy.yaml`, and no `tool/` folder.

#### Scenario: Bundled Edith validates
- **WHEN** `agents/edith/` is loaded with the default configuration
- **THEN** loading succeeds with role `guard`, model alias `claude-haiku`, voice `kokoro/ef_dora,bf_emma` and no tools

#### Scenario: Bundled policy validates
- **WHEN** `agents/edith/policy.yaml` is loaded
- **THEN** loading succeeds and its `default` is not `allow`
