## ADDED Requirements

### Requirement: Probe managers wait for recovery
A manager used only to probe servers (startup probe and config-reload probe) SHALL stay open after the initial attempts until every failed server has either recovered, exhausted its retries, or been superseded by a newer probe of the same agent and server, or until the app shuts down. It SHALL then close all its connections and tasks. A probe that has recovered SHALL publish the server as up exactly once.

#### Scenario: Probed server recovers
- **WHEN** a probed server fails its first attempt and succeeds on the first retry
- **THEN** the server is published down, then up, and the probe manager closes afterwards with no task left

#### Scenario: Probe superseded
- **WHEN** a config reload starts a new probe for a server whose earlier probe is still waiting to retry
- **THEN** the earlier probe is cancelled and only the new probe publishes statuses

### Requirement: Concurrent server startup
Declared stdio and HTTP servers SHALL be connected concurrently, at most 4 at a time, each connection opened and closed by the same task. Startup time with N unavailable servers SHALL approach the slowest batch, not the sum. The tool catalog SHALL list servers in declaration order regardless of which connected first. A failed server SHALL still not prevent the others from connecting.

#### Scenario: Four servers time out
- **WHEN** 4 declared servers each take the full 30 s connect timeout
- **THEN** startup completes in under 40 s and the catalog holds only the servers that connected

#### Scenario: Catalog order
- **WHEN** server `b` connects before server `a`, declared as `a` then `b`
- **THEN** the catalog lists the tools of `a` before those of `b`
