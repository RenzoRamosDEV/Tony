## 1. Schema (tests first)

- [x] 1.1 Add failing loader tests in `tests/core/loader/test_tool_spec.py`: stdio entry with `isolation.env_allow` loads; `{}` loads with empty allowlist; HTTP entry with `isolation` fails naming `mcpServers.<server>`; unknown key inside `isolation` fails naming `mcpServers.<server>.isolation`; names `1BAD` and `A=B` fail; entry without `isolation` loads with `isolation` None
- [x] 1.2 Add a failing writer test in `tests/core/loader/test_tool_json_writer.py`: `add_server` writes an entry with `isolation` and rejects an invalid one leaving the file untouched
- [x] 1.3 Implement `Isolation` model, `McpServer.isolation` and the `_STDIO_ONLY` addition in `tony/core/loader/tool_json.py`; make 1.1 and 1.2 pass; refactor

## 2. Environment composition (tests first)

- [x] 2.1 Add failing unit tests in `tests/core/mcp/test_isolation.py` for `isolated_environment`: allowlisted set variable copied; allowlisted unset skipped; base `PATH/HOME/LANG/LC_ALL` copied only when set; non-allowed host variable (`SECRET_X`, `USER`, `SHELL`) absent; declared `env` added and overriding a host value; empty `isolation` yields only the base set
- [x] 2.2 Implement `tony/core/mcp/isolation.py` (pure function, no `os` access); make 2.1 pass

## 3. Launcher and manager wiring (tests first)

- [x] 3.1 Add failing tests in `tests/core/mcp/test_isolated_exec.py` running the launcher via `subprocess` with a tiny inline Python child that prints `sorted(os.environ)`: only the composed variables appear; `TONY_ISOLATED_ENV` itself is absent; a missing command exits 127 with a stderr message
- [x] 3.2 Implement `tony/core/mcp/isolated_exec.py` (stdlib only, `os.execvpe`); make 3.1 pass
- [x] 3.3 Add failing smoke tests in `tests/core/mcp/test_manager_isolation.py` using `fake_fs_entry` and `fs.echo_env`: allowlisted variable and declared `env` visible; `SECRET_VAR`, `USER`, `SHELL`, `TERM`, `LOGNAME` empty; without `isolation` `USER` is still visible (unchanged behavior); isolated server tools are cataloged; a nonexistent command is marked down while another server stays up; no value of the isolated environment appears in the launcher args
- [x] 3.4 Add the optional `host_environ` argument to `McpManager` and branch in `_transport` (`tony/core/mcp/manager.py`) for isolated servers; make 3.3 pass; confirm existing `tests/core/mcp` still pass; refactor

## 4. Doctor warning (tests first)

- [x] 4.1 Add failing tests in `tests/core/diagnostics/test_checks.py`: one missing variable gives a `warn` row naming server and variable; two missing give one sorted row; all present gives no row; no `isolation` or empty `env_allow` gives no row; a warn-only report keeps `exit_code` 0 in `tests/core/diagnostics/test_report.py`
- [x] 4.2 Add the isolation check to `tony/core/diagnostics/checks.py` using the `environ` already passed to `run_checks`; make 4.1 pass; refactor

## 5. Verification

- [x] 5.1 Run the full suite; confirm no regression (including the uncommitted changes' tests) and flag any test over 10 s
- [x] 5.2 Run mutation testing on the diff only (`isolation.py`, `isolated_exec.py`, the manager branch, the doctor check), target above 95 percent; use targeted manual mutants if the full run exceeds 3 minutes and justify survivors
- [x] 5.3 Document `isolation` in the README tool.json section (POSIX-only, base variables, `env_allow` and declared `env` precedence)
