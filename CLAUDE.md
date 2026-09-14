# cmd-line Agent — Project Context

## What this is

A cross-platform CLI agent (installable from GitHub) that automates developer
environment setup through natural language. Example: the user says "set up a
Flutter environment end to end," and the agent checks system requirements,
checks permissions, consults official documentation, and installs/configures
the environment — asking for human confirmation (HITL) before any risky or
irreversible step.

Two goals behind this project, in order:
1. Hands-on exposure to building real agentic AI systems (graph-based
   orchestration, tool-use loops, grounding, HITL interrupts, observability)
   using the same tooling that's standard in industry — this is a learning
   vehicle first.
2. If it turns out well, a genuinely useful tool other developers could
   install and use for their own environment setup.

## Core UX flow

1. User installs the CLI (via `uv tool install` or a curl bootstrap script).
2. `init` command: pick an LLM provider. If a key is already saved for
   that provider, ask whether to keep it (and just mark it active) or
   replace it. Otherwise, enter API key, validate against the provider,
   store in the OS keychain (never plaintext).
3. User gives a natural-language instruction, e.g. "set up Flutter for
   Android development."
4. Agent: detects OS/arch → checks required permissions (sudo/admin) →
   checks for an existing vetted "recipe" for this target; if none, fetches
   and reads official docs → produces a step-by-step plan → shows the plan
   to the user → executes one step at a time, printing every command (and
   its output) live as it runs — not just the ones needing confirmation —
   verifying after each step → interrupts for human input wherever needed
   (see HITL section) before any destructive/irreversible action or
   whenever a choice among valid options exists (e.g. which IDE to
   configure).
5. Every executed command is logged with enough detail to construct an
   undo/rollback script later.
6. If the process is interrupted (crash, terminal closed, Ctrl+C), it can
   be resumed from the last completed step via the graph's checkpointed
   state.

## Governing principles (read this before changing architecture)

- **Recipes-first, LLM-fallback.** A small library of vetted, hand-written
  setup recipes (YAML: steps + verification commands + doc links) is the
  trusted default path for common stacks. Freeform "LLM reads docs and
  invents commands" is a fallback for targets with no recipe yet — not the
  primary mechanism. This bounds the risk of hallucinated/destructive
  commands. **Scope reminder: Flutter (`recipes/flutter.yaml`) is the
  first example recipe used to build this pipeline, not the boundary of
  what the agent handles.** The user can ask for *any* dev environment
  setup — `match_recipe()`/`fetch_doc()`/`extract_os_section()` are
  fully generic; adding Node/Python/Docker/etc. later means a new
  `.yaml` file, no code changes. Any goal that matches no recipe still
  falls back to freeform planning today.
  - **Planned evolution of the fallback path itself, not yet built**: the
    freeform path currently has zero doc grounding — pure LLM training
    knowledge, for anything without a curated recipe. The plan is to
    integrate a web search API (Tavily, given DuckDuckGo has no real
    developer API — see prior discussion) so the fallback can find and
    ground itself in real official docs for arbitrary targets too, not
    only recipe-covered ones — reducing reliance on stale/hallucination-
    prone memory for the long tail of possible setup goals. This is
    additive to recipes, not a replacement: a recipe's `doc_url` is
    curated once and needs no search at all; search is specifically for
    the case where no recipe exists yet.
- **HITL is a hard gate, not a suggestion.** Every command the agent wants
  to run is risk-classified (read-only/check vs. destructive/irreversible).
  Destructive commands always require explicit user confirmation. Never
  pipe a fetched remote script straight into a shell without showing it to
  the user first. Concretely (`hitl/gate.py`): risk classification never
  trusts a plan-generating LLM's own self-reported `risk` field alone — a
  deterministic keyword safety net (`sudo`, `rm -rf`, `install`, `curl |
  sh`, `chmod`, etc.) can only escalate a step to destructive, never
  downgrade one, so a model that mislabels a dangerous command as "safe"
  still gets gated.
- **An exit code is not proof the goal was achieved — never report success
  on exit codes alone.** Many CLI tools (`flutter doctor`, `npm doctor`,
  `pip check`, etc.) exit 0 while their own output reports real, unresolved
  problems — a "doctor" command's job is to report status, not to fail the
  process. `verify_node` correctly treats exit code as *step* success (did
  the command crash) — that is a different question from *goal* success
  (was the thing actually achieved), which is `judge_node`'s job (see
  Current status). Do not collapse these back into one check. Corollary,
  learned the hard way (see Current status item 13): the same lying-exit-
  code problem applies to `check_command`/idempotency too, not just the
  final judge — a diagnostic/status-report step must never be given a
  `check_command` at all, since "it exited 0 before" says nothing about
  problems it would report *now*. `hitl/gate.py::is_diagnostic_step`
  enforces this deterministically; don't rely on the prompt alone for it.
- **LangGraph is the orchestration layer.** The agent loop (plan → HITL
  interrupt → execute → verify → loop/resume) is built as a LangGraph
  graph, not a hand-rolled loop. Chosen deliberately over hand-rolling
  despite added upfront complexity: LangGraph's native interrupt/resume and
  checkpointing primitives map directly onto this agent's real requirements
  (pausing for human input, resuming an interrupted setup), and it's the
  dominant orchestration tool in the industry, which matters for the
  learning goal above. Persistence uses `SqliteSaver` — local-only, no
  external database, consistent with the BYOK/no-backend principle below.
- **BYOK, local-only, no backend for end users.** The user supplies their
  own API key via OS keychain. No remote telemetry about end users, no
  server component, by default. This is a local CLI tool, not a hosted
  service. (See Observability section for the separate, opt-in,
  developer-side tracing story — that principle is about *end users' data*,
  not about the author's own dev-time visibility into the agent.)
- **No heavy chain/RAG framework beyond LangGraph.** LangGraph is an
  orchestration/state-machine layer, not a kitchen-sink framework — tool
  definitions, provider calls, and the executor are still written directly
  against official provider SDKs so behavior stays auditable.
- **Windows is a second-class citizen by design, temporarily.** UAC
  elevation, PATH/session-restart semantics, and lack of one canonical
  package manager make Windows substantially harder than macOS/Ubuntu.
  It is deliberately the last platform tackled, not built in parallel.
- **Core engine is decoupled from the CLI.** The LangGraph agent, tools,
  and HITL interrupt payloads must not assume a terminal. An interrupt is
  emitted as a typed, presentation-agnostic payload (see HITL section) so
  a future front-end (VS Code extension, TUI) can render the same graph
  without touching agent logic.
- **Single agent, not multi-agent — by design, not by omission.** The task
  is inherently sequential (one setup target, one plan, step by step), so
  there is no independent/parallelizable subtask that would justify
  separate LLM-driven agents. LangGraph nodes already provide the
  plan/execute/verify separation of concerns without that overhead.
  Do not introduce a supervisor/multi-agent pattern unless the actual
  shape of the work becomes genuinely parallel (e.g. setting up two
  unrelated stacks concurrently) — and even then, prefer parallel branches
  within one graph over separate agents first.
- **Feedback channel is GitHub itself.** No separate feedback service or
  form. Use GitHub Issues (bug report + feature request templates under
  `.github/ISSUE_TEMPLATE/`) and GitHub Discussions for open-ended
  feedback — zero extra infrastructure, consistent with the no-backend
  principle.

## HITL design

HITL interrupts are typed so the presentation layer can pick the right UI
without the agent logic knowing about terminals specifically:

| Type | Shape | CLI rendering (`questionary`) | Example |
|---|---|---|---|
| `confirm` | binary | `questionary.confirm` (y/n) | "About to run `sudo apt install android-sdk` — proceed?" |
| `select` | single choice from options | `questionary.select` (arrow keys + enter) | "Which IDE do you want configured? VS Code / Android Studio / Neither" |
| `checkbox` | multiple independent choices | `questionary.checkbox` (space to toggle, enter to confirm) | "Which components do you want installed? Android SDK / iOS toolchain / Web support" |

`confirm` is reserved for risk gates before destructive/irreversible
actions. `select`/`checkbox` are for legitimate choices among valid options,
not for safety gating. The interrupt payload (`{type, message, options?}`)
is produced by `hitl/gate.py` and only rendered by `cli.py` — keeping the
decision of *what* to ask separate from *how* it's asked.

## Evaluation

Correctness of the plans/tool-calls the agent produces is treated as a
first-class, ongoing concern, not something bolted on after the fact:
- A dataset of scenarios (natural-language request → expected recipe match
  / expected tool calls / expected HITL triggers, e.g. "any install
  requiring sudo must trigger a `confirm` interrupt") is run as a
  regression suite whenever a prompt, model, or recipe changes.
- **Decision made in Phase 1: plain `pytest`, not `promptfoo`.** Adding
  `promptfoo` would pull a separate Node.js toolchain into a pure-Python
  project for scenarios that (so far) test deterministic logic, not live
  model output — not worth it yet. Revisit if/when scenarios need to
  assert on actual LLM-generated plan content rather than the risk-gating
  logic. Scenario data lives in `evals/scenarios/*.json`; `tests/test_evals.py`
  loads and runs it. First scenario file: `hitl_risk_gating.json` (9 cases
  covering sudo/install/rm/curl-pipe-sh commands and a few safe read-only
  ones).

## Observability (developer-side, distinct from the no-telemetry principle above)

The "no remote telemetry" principle is about *end users'* data (their
machine details, commands run) never leaving their machine without
explicit consent. Separately, the author needs visibility into the agent's
own behavior during development — that's normal engineering practice, not
a privacy concern, as long as it's opt-in and clearly scoped:
- **LangSmith** for tracing during development — chosen over Langfuse for
  now because it auto-instruments LangGraph with near-zero setup (same
  vendor), and has a usable free tier for individual developers. Captures
  token usage/cost, per-node latency, and full run traces — useful for
  diagnosing a stuck/looping graph (LangGraph's `recursion_limit` is the
  hard stop; the trace shows *why* it looped).
- **Langfuse** remains the documented fallback if open-source/self-hosted
  becomes a priority later (e.g. before recommending others install the
  tool) — it is provider-agnostic and has overlapping dataset/eval
  features, so tracing and evaluation could share one tool if adopted.
- Tracing is on for the author's own dev/test runs and off by default for
  anyone who installs the published tool, unless they explicitly opt in.

## Tech stack

| Concern | Choice | Why |
|---|---|---|
| Language | Python 3.11+ | Author's existing fluency; official SDKs exist for all target providers |
| Packaging/env | `uv` | Single tool for venv + deps + `uv tool install` distribution; avoids pip/pipx fragmentation |
| CLI framework | `typer` | Type-hint driven, built on Click |
| Agent orchestration | `langgraph` + `SqliteSaver` | Native interrupt/resume + checkpointing for HITL and resumable setups; industry-standard tooling |
| Terminal UX | `rich` + `questionary` | Formatted output/panels/spinners; typed HITL prompts (confirm/select/checkbox) |
| LLM SDKs | `anthropic`, `openai`, `google-genai` | Official SDKs. Grok uses the `openai` SDK with `base_url` override (OpenAI-compatible API) |
| HTTP/doc fetching | `httpx` + `beautifulsoup4`/`trafilatura` | Fetch and extract main content from official doc pages. Headless-browser scraping (Playwright) deferred — heavy dependency, not needed for v1 doc sites |
| Credentials | `keyring` | Wraps OS keychain (Keychain/Credential Manager/libsecret) with no native compilation step |
| Config | `platformdirs` + TOML | Non-secret settings: chosen provider, model, recipe cache location |
| Command execution | stdlib `subprocess`, wrapped in a custom Executor | Logging + undo-log + risk classification live in this wrapper, not scattered at call sites |
| Plan parsing | stdlib `json` → `json5` → `json_repair` | Three free (zero token cost) fallback layers, each catching a different real crash seen in live testing: `json5` for single-quoted strings (a dialect difference), `json_repair` for structurally broken JSON like a missing comma (not a dialect difference — json5 can't fix this either) |
| Observability | `langsmith` (dev-time, opt-in) | Tracing, token usage, loop diagnosis. Langfuse documented as open-source fallback |
| Evaluation | `promptfoo` or `pytest`-based harness | Regression-test plan/tool-call correctness as prompts/models/recipes change |
| Testing | `pytest` + GitHub Actions matrix (mac/windows/ubuntu runners) | Real OS differences can't be caught by unit tests alone |

**Providers targeted at launch**: Anthropic, OpenAI, Gemini, Grok.
Practical note: only Gemini currently has a standing free tier suitable for
the author's own testing; OpenAI/Anthropic/Grok are BYOK-and-pay beyond
trial credits.

## Project structure

```
cmd-line-agent/
├── CLAUDE.md                  # this file — auto-loaded context for any agent session
├── pyproject.toml
├── README.md
├── src/envagent/
│   ├── cli.py                 # typer entrypoint: init, setup, doctor, config
│   │                          # also renders HITL interrupt payloads via questionary
│   ├── config/
│   │   ├── settings.py        # non-secret config (provider, model, cache)
│   │   └── credentials.py     # keyring wrapper for API keys
│   ├── providers/
│   │   ├── base.py            # abstract Provider interface (chat/stream/tool-calling)
│   │   ├── anthropic_provider.py
│   │   ├── openai_provider.py
│   │   ├── gemini_provider.py
│   │   └── grok_provider.py
│   ├── agent/
│   │   ├── graph.py           # LangGraph graph: plan -> execute -> verify -> (loop|judge->end)
│   │   ├── state.py           # graph state schema (incl. Assessment)
│   │   ├── nodes.py           # plan / execute / verify / judge node implementations
│   │   ├── checkpointer.py    # SqliteSaver setup (local persistence for resume)
│   │   └── prompts.py         # PLAN_SYSTEM_PROMPT, JUDGE_SYSTEM_PROMPT
│   ├── system/
│   │   ├── os_detect.py       # SystemInfo: os_key/arch/release/package_managers
│   │   ├── permissions.py     # is_elevated()/can_elevate() — sudo/admin/UAC checks
│   │   └── executor.py        # subprocess execution + JSONL logging + undo_command per entry
│   ├── docs/
│   │   ├── fetcher.py         # fetch_doc() (tries <url>.md first, else bs4 HTML extraction)
│   │   │                      # + extract_os_section() (splits on {: .steps .<os>-only} markers)
│   │   └── cache.py           # local cache keyed by URL, 7-day TTL
│   ├── recipes/
│   │   ├── registry.py        # match_recipe(goal) — deterministic alias keyword match
│   │   └── flutter.yaml       # name/aliases/doc_url/ide_choice
│   └── hitl/
│       └── gate.py            # risk classification + typed interrupt payloads
│                               # ({type: confirm|select|checkbox, message, options?})
│                               # PlanStep also carries check_command (idempotency)
│                               # and automatable/manual_instructions (non-CLI steps)
├── evals/
│   └── scenarios/              # eval dataset: request -> expected plan/tool-calls/HITL
├── tests/
└── scripts/install.sh         # curl-based bootstrap installer (built — see Current status)
```

## Roadmap

- **Phase 0 — Scaffolding**: `pyproject.toml`, provider abstraction,
  `init` command (API key entry + validation + keyring storage), base
  LangGraph graph skeleton with `SqliteSaver` checkpointing wired in from
  the start.
- **Phase 1 — Core agent loop**: plan/execute/verify nodes, typed HITL
  interrupts, Executor with command logging and undo-log, first eval
  scenarios and LangSmith tracing wired in.
- **Phase 2 — First vertical slice**: OS detection + doc fetcher + Flutter
  recipe, macOS only, end-to-end (including a `select` HITL for IDE choice),
  plus a full `os_detect.py` module (structured OS/arch/package-manager
  detection, not just the string interpolation described below — that
  landed early, see Current status).
- **Phase 3 — Expand**: Node/Python/Docker recipes, add Ubuntu support.
- **Phase 4 — Windows**: UAC, winget/choco, PATH/session-restart handling.
  Tackled last on purpose (see governing principles).
- **Phase 5 — Polish**: `doctor`/`undo` commands, `uv tool install`
  packaging, CI matrix across macOS/Windows/Ubuntu.
  - **`undo`/delete design**: deletion is *not* a fresh freeform plan by
    default. If the target was set up by this agent, the run log already
    has every step's real `undo_command` — `undo` replays those (still
    individually HITL-gated), scoped to exactly what was actually
    installed, so it never guesses whether "delete flutter environment"
    should also touch the IDE. If there's no log for the target (e.g. it
    was installed manually, outside this agent), fall back to freeform
    delete-planning, but surface discovered components via a `checkbox`
    interrupt so the user picks scope explicitly rather than the model
    deciding silently.
- **Phase 6 — Stretch**: IDE/editor integration (e.g. VSCode settings and
  extension install), community-contributed recipes, plugin system.
  - **Adoption/onboarding idea, deliberately deferred**: BYOK is real
    friction for anyone without an existing API key. Considered a
    server-side free tier (pooled key, metered tokens per registered
    user) to solve this — deliberately deferred: that requires real
    ongoing LLM spend per free user, accounts, abuse prevention, and a
    shared key to protect, none of which is worth building before there's
    evidence of real user demand. Cheaper near-term alternative, not yet
    built either: during `init`, if the user has no key, point them at a
    provider's own existing free tier (Gemini) instead — zero
    infrastructure, zero cost to the author, solves the same "let people
    try it for free" problem. Revisit the server-based version only if
    the cheap version proves insufficient once there are real users.

## Current status

**Phase 0 (Scaffolding) is complete and verified end-to-end** — `init` has
been run against a real provider by the user (arrow-key select, hidden
key entry, live validation, keychain storage, "keep existing key?" check
on re-run all confirmed working).

**Phase 1 (Core agent loop) is complete and verified against a real
model**:
- `providers/base.py` gained a `complete(api_key, system, user) -> str`
  method (single-turn completion), implemented for all four providers.
- `hitl/gate.py`: `PlanStep`/`Interrupt` types and `classify_step` —
  destructive-risk gating with the keyword safety net described above.
- `system/executor.py`: runs a step's command via `subprocess`, logs
  every execution (command, returncode, stdout/stderr, undo_command,
  timestamps) as JSONL under the user log dir.
- `agent/prompts.py`, `agent/nodes.py`: `plan_node` (calls the active
  provider directly from the goal — freeform, no recipes/doc-grounding
  yet), `execute_node` (raises a LangGraph `interrupt()` before a
  destructive step), `verify_node` (checks returncode, advances or ends).
- `agent/graph.py` rewired: `plan -> execute -> verify -> (loop back to
  execute | end)`, compiled with the `SqliteSaver` checkpointer.
- `cli.py` gained a `setup <goal>` command that drives the graph and
  renders whatever interrupt type comes back (`confirm`/`select`/
  `checkbox`) via the matching `questionary` prompt, resuming with
  `Command(resume=...)`.
- Tests: `tests/test_hitl_gate.py` (risk-gating unit tests, including the
  safety-net-overrides-a-mislabeled-step case), `tests/test_graph.py`
  (rewritten — full graph run against a fake provider, both approval and
  rejection paths, using real `echo` subprocess calls), `tests/test_evals.py`
  + `evals/scenarios/hitl_risk_gating.json` (9-case regression dataset).
  All pass (`uv run pytest -q`).
- **Manually verified against a real OpenAI call**: `envagent setup "set
  up flutter"` produced a correct 5-step plan (Homebrew install, PATH
  export, bash-completion, `flutter doctor`, Android licenses), correctly
  flagged 3 of 5 steps as destructive, paused on the first one with the
  right confirm payload, and the pause **persisted across a fresh
  `build_graph()`/`get_state()` call** (proving checkpointed resume really
  works). The rejection path was also verified live: declining stops the
  run with zero commands executed. The actual `brew install` was
  deliberately never approved during this test — that would have really
  installed Flutter on the dev machine.

**Thirteen additions/fixes landed after Phase 1** — items 1-3 pulled
forward from Phase 2/later because they were judged too important to
defer; items 4-13 are bugs/gaps found by testing or reasoning through a
real result (one by writing a test, seven by live-testing against a real
provider, nine of those raised by the user directly) and fixed
immediately rather than left open:

1. **OS-awareness stopgap**: `plan_node` interpolates the real detected
   OS/arch (`platform.system()`/`.machine()`/`.release()`, via
   `nodes._describe_os()`) directly into the planning prompt, so the model
   is told the actual OS rather than guessing. Minimal stopgap, not the
   real `os_detect.py` module (no package-manager detection, no
   structured output) — that's still Phase 2 scope.
2. **Idempotency / check-before-install**: `PlanStep` gained an optional
   `check_command` field; the planning prompt asks the model for one per
   step (e.g. `command -v node` for an "install node" step).
   `execute_node` runs it first via `executor.run_check()` — if it exits
   0, the step is marked `skipped_install` and neither the HITL interrupt
   nor the real command ever runs. `ExecutionResult` gained a
   `kind: "execute" | "check"` field so the run log distinguishes the two.
   Covered by `tests/test_graph.py::test_step_already_satisfied_is_skipped_without_hitl`.
3. **`envagent resume` command**: the active `thread_id` is stored in
   `settings.extra["active_thread_id"]` while a `setup` run is in
   progress, and cleared when it reaches a terminal state. `resume` reads
   it back, rebuilds the graph, confirms via `get_state().next` that a
   pause is genuinely still pending, re-renders that interrupt, and
   continues. Rationale: a HITL confirm pause isn't a rare crash
   scenario — it happens before every destructive step, so "terminal
   closed while a prompt was up" (meeting interruption, closed laptop,
   deliberately stepping away to think about a `sudo` step) is a
   plausible everyday case, not an edge case. `setup` and `resume` share
   a `_drive_to_completion` loop in `cli.py`. Covered by
   `tests/test_graph.py::test_resume_works_from_a_freshly_built_graph_instance`,
   which discards the graph instance that hit the interrupt entirely and
   resumes from a fresh one against the same checkpoint DB — the same
   thing a real process restart would do.
4. **Real-time per-step command visibility**: `cli.py`'s driving loop
   switched from `graph.invoke()` to `graph.stream(..., stream_mode=
   "updates")`, which yields one chunk per completed node. Previously,
   safe steps ran silently in a batch inside one opaque `invoke()` call —
   only destructive steps (shown in the confirm prompt) were ever visible.
   Now every step prints `$ <command>` plus its stdout live as it runs,
   matching normal shell UX, not just the gated ones. `_drive_to_completion`
   in `cli.py` was rewritten around this; `setup` and `resume` both use it.
   Covered by `tests/test_cli.py` (a real `CliRunner` invocation, with
   `questionary` stubbed out since it needs a TTY).
   - **Bug found and fixed by writing that test**: `save_settings` crashed
     (`TypeError: ... not TOML serializable`) whenever `provider`/`model`
     were still `None` — which happens if `setup`/`resume` ever run before
     `init` (they write `active_thread_id` into `settings.extra`
     regardless). Fixed in `config/settings.py`: `save_settings` now omits
     `None`-valued fields before writing, since TOML has no null type.
5. **Irrelevant-goal edge case, found by live-testing against a real
   provider**: `envagent setup "what is the capital of France?"` crashed
   with `IndexError: list index out of range`. The model actually did the
   sensible thing (returned an empty plan `[]`), but nothing handled an
   empty plan — `execute_node` blindly indexed `state["plan"][0]`. Fixed:
   `PLAN_SYSTEM_PROMPT` now explicitly contracts that a non-setup goal
   (general question, unrelated request, small talk) should produce `[]`;
   `plan_node` raises `NoStepsPlannedError` with a clear message when the
   plan comes back empty, caught in `cli.py`'s `setup` alongside
   `NotConfiguredError`. Re-verified against the real provider after the
   fix: clean error message, no crash. Covered by
   `tests/test_graph.py::test_irrelevant_goal_raises_a_clear_error_instead_of_crashing`.
6. **Real crash found by the user testing `envagent setup "install vs
   code"`**: `json.JSONDecodeError` in `_parse_plan`. Root cause (captured
   the exact raw model output to diagnose): the model needed a literal
   `"` inside a shell command (`bash -c "$(curl ...)"`) and, instead of
   escaping it, switched that one string to single quotes — invalid
   strict JSON, a known/common LLM JSON-generation quirk whenever string
   content needs embedded double quotes. Fixed two ways: (a)
   `PLAN_SYSTEM_PROMPT` now explicitly instructs double-quoted strings
   only, with inner double quotes escaped as `\"`; (b) `_parse_plan` now
   tries strict `json.loads` first, and on failure falls back to `json5`
   (new dependency — a lenient parser that accepts single-quoted strings,
   among other common near-JSON variants). Verified against the real
   captured failure text and re-verified live against the real goal that
   crashed — now completes cleanly (and, since Homebrew + VS Code were
   already on the test machine, demonstrated idempotency skipping both
   steps with zero prompts). Covered by `tests/test_plan_parsing.py`,
   which pins the exact single-quoted output that caused the crash as a
   regression fixture.
7. **Real-time transparency — reported directly by the user testing
   `envagent setup "setup flutter development environment"`**: after
   approving `brew install --cask flutter`, the CLI appeared to hang with
   no output for a long time. Root cause: the Executor used
   `subprocess.run(capture_output=True)`, which blocks and buffers all
   output until the command *fully exits* — a real, slow install (large
   SDK download) was actually running the whole time, just with zero
   visibility, indistinguishable from a hang. Also reported in the same
   session: no visibility into the detected OS, the full generated plan,
   or *why* an idempotency check counted as satisfied. Fixed together,
   confirmed to add zero LLM/token cost (verified before implementing,
   since the user explicitly asked) — all of it is either already-fetched
   local data or local subprocess I/O handling, nothing here calls a
   provider:
   - `system/executor.py`: `_run_command` switched from
     `subprocess.run(capture_output=True)` to `subprocess.Popen` with
     stdout+stderr merged, read and streamed line-by-line via an optional
     `on_line` callback, while still returning the full captured output
     for logging. (`stderr` on `ExecutionResult` is now always `""` since
     it's merged into `stdout` for live streaming — a real behavior
     change, not just cosmetic.)
   - `agent/nodes.py`: nodes now push real-time progress via LangGraph's
     `get_stream_writer()` (verified this is a safe no-op under plain
     `.invoke()`, so it doesn't break anything invoking the graph
     directly) — `plan_node` emits `system_info` (the detected OS string)
     and `plan_ready` (the full parsed plan) events; `execute_node` emits
     `check_start`/`check_satisfied` (with the step's `description`, not
     just the raw check command) and `command_start`, plus `output_line`
     for every line of live command output via the executor's `on_line`.
   - `cli.py`: `_drive_to_completion` now streams
     `stream_mode=["custom", "updates"]` — `custom` chunks are the new
     progress events above (rendered by `_print_progress_event`);
     `updates` chunks are only still used to detect interrupts and a
     failed verify. This fully replaces the old post-hoc
     `_print_progress`/`_print_step_result` (which only showed output
     *after* a step finished).
   - Known minor quirk, not fixed (low priority): if a step's
     `check_command` is *not* satisfied, LangGraph re-runs the node from
     the top on resume (standard behavior for any node with an
     `interrupt()` call) — so that check command's `check_start`/output
     events appear twice (once before the pause, once after resuming). No
     correctness impact since check commands are read-only by design.
8. **Judge node — reported directly by the user**: after the above
   transparency fix, the same `flutter development environment` run
   completed all 8 steps (including a real `flutter doctor`) and printed
   "Setup complete." — but `flutter doctor`'s own output clearly reported
   `Doctor found issues in 2 categories` (missing Android SDK, incomplete
   Xcode). `verify_node` only checks exit code, and diagnostic tools like
   `flutter doctor` exit 0 regardless of what they report — so "every
   command exited 0" silently got treated as "the goal was achieved."
   Fixed by adding a new terminal node, **only reached on the 'done'
   path** (a declined/failed run is already an honest signal on its own):
   - `agent/nodes.py::judge_node` — one LLM call (`JUDGE_SYSTEM_PROMPT` in
     `prompts.py`) given the goal plus every step's description/command/
     output (truncated to ~1500 chars each to bound cost), returning
     `{"achieved": bool, "summary": str}`. A malformed judge response
     doesn't crash the run — falls back to `achieved: false` with an
     honest "couldn't verify" message rather than silently claiming
     success.
   - `agent/state.py::Assessment` — new `NotRequired` field on
     `AgentState`, absent on a 'failed' run.
   - `agent/graph.py` — `_route_after_verify` now sends `'done'` to a new
     `judge` node (not straight to `END`); `'failed'` is unchanged.
   - `cli.py::_finish` — no longer prints an unconditional "Setup
     complete."; renders the judge's actual verdict (green "Goal
     achieved: ..." vs. yellow "Steps ran, but the goal may not be fully
     achieved: ...").
   - **Real cost, confirmed with the user before building** (unlike items
     1-7, which were all free): exactly one extra LLM call per `setup`
     run that reaches 'done', regardless of step count — not per-step.
   - **Verified end-to-end for real**, not just with a fake provider: ran
     the actual graph with a real `flutter doctor` execution on the dev
     machine (exit code 0, as always) and a real judge call against the
     real output. Verdict: `achieved: false`, `"The Flutter SDK itself is
     installed, but the Android toolchain is missing because the Android
     SDK is not found. Xcode is only partially installed and CocoaPods is
     not installed..."` — matches the real state of the machine exactly.
   - Covered by `tests/test_graph.py::test_judge_catches_a_flutter_doctor_style_false_success`
     and `::test_judge_confirms_a_genuine_success`; existing tests' fake
     providers updated to answer both the plan call and the judge call
     (dispatched on which system prompt they receive).
9. **Non-automatable steps — raised by the user reasoning through the
   Xcode finding above**: if the judge finds something like an incomplete
   Xcode install, the agent had no way to act on it *and no concept that
   some things categorically can't be automated at all* — Xcode
   specifically can only be installed through the App Store or
   apple.com with a real Apple ID login; no CLI automation can ever do
   this, regardless of what agent logic exists. Designed collaboratively
   before implementing (no added token cost — one more instruction in the
   existing planning prompt, not a new call):
   - `hitl/gate.py::PlanStep` gained `automatable: NotRequired[bool]`
     (default `true`) and `manual_instructions: NotRequired[str | None]`.
     `PLAN_SYSTEM_PROMPT` now asks the model to set `automatable: false`
     only for genuinely non-scriptable steps (GUI installer, App Store
     login, license click-through), with `command` contractually `""` in
     that case — **deliberately a separate field from `command`, not
     reusing it for instructions**, so a manual step's human-readable text
     can never accidentally reach `subprocess` even if some future code
     path forgets to check `automatable` first.
   - `agent/nodes.py::execute_node` ordering, refined during design
     review: `check_command` (if any) still runs **first**, regardless of
     `automatable` — idempotency wins over "needs manual action" (don't
     tell the user to do something they've already done). Only when
     unsatisfied/unverifiable *and* `automatable` is false does it get
     flagged as `needs_manual_action`, skipped without any HITL interrupt
     (nothing destructive is attempted) and without ever executing
     `command`. The entry's `returncode` is normalized to `0` — "not done
     yet" must not be treated as a hard failure by `verify_node`.
   - `_build_judge_transcript` marks these steps `NOT AUTOMATED` so the
     judge's assessment correctly accounts for them instead of being
     confused by an apparently-skipped step.
   - `cli.py`: the upfront plan listing tags these `(manual)`; a live
     `manual_action_needed` event prints the instructions as the step is
     reached; `_finish` prints a distinct "Manual steps still needed"
     list after the judge's verdict — separate from the judge's prose, so
     it's scannable rather than buried.
   - Covered by three new tests in `tests/test_graph.py`: flagged
     correctly with no check, still flagged (not treated as a hard
     failure) when a check exists but fails, and correctly treated as
     already-satisfied (not manual) when a check exists and passes.
10. **A second, different real JSON crash — reported directly by the
    user**, same goal as item 6 (`"setup flutter development
    environment"`), different generation: `json.JSONDecodeError`
    ("Expecting ',' delimiter") and, notably, `json5` *also* failed on
    the same text. Captured the raw output to check — a genuinely
    missing comma between two fields, not a dialect difference like the
    single-quote case, so `json5` could never have fixed this class of
    error. Confirmed the non-determinism directly too: re-running the
    exact same goal against the same real provider immediately after
    produced perfectly valid JSON on the very next call — so this isn't
    reproducible from one bad sample, it's inherent variance across
    generations. Fixed by adding a third, still-free fallback layer:
    `json_repair` (new dependency, purpose-built for repairing malformed
    LLM JSON — missing commas/brackets, unterminated strings). Verified
    it fixes both the missing-comma pattern and an unterminated-string
    pattern with synthetic tests before trusting it. Deliberately did
    NOT add a costly LLM-retry-on-parse-failure fallback: `json_repair`
    is designed to essentially never fail outright, so planning stays
    exactly one call; revisit only if this recurs even past all three
    layers. Covered by `tests/test_plan_parsing.py::test_parse_plan_falls_back_for_a_missing_comma_delimiter`.
11. **A real step failure with a diagnosable root cause, plus a bare
    error message — both reported directly by the user**: same goal
    again, this time parsing succeeded and execution ran real steps, but
    step 5 ("Add Flutter to PATH via Flutter-managed environment") failed
    with zero visible output before "Step failed." Diagnosed by running
    the suspicious part of the generated command directly: `brew --prefix
    flutter` failed with `Error: No available formula with the name
    "flutter"` — Flutter had been installed as a Homebrew **cask** (step
    4 used `brew install --cask flutter`), but this step's command used
    formula-only lookup syntax (`brew --prefix flutter`, no `--cask`) —
    an internal inconsistency in the model's own plan. The command also
    had `2>/dev/null` specifically on that `brew --prefix` call, which is
    exactly why nothing was visible — the one diagnostic that would have
    explained the failure was suppressed by the command itself before the
    agent ever had a chance to stream it.
    - This particular root cause is a **plan-quality issue from Phase 1's
      freeform planning**, not an execution/architecture bug — `verify_node`,
      the Executor, and streaming all behaved correctly (correctly detected
      the real failure and stopped rather than continuing past it). Exactly
      the class of mistake Phase 2's recipes (hand-vetted, not freeform) are
      meant to reduce.
    - What *was* a real, fixed gap: `cli.py`'s failure message was a bare
      `"Step failed."` with zero diagnostic — no command, no exit code —
      even though that information was already sitting in the `verify`
      node's own state update (since `verify_node` returns `{**state,
      "status": "failed"}`, a full-state spread, the 'updates' stream
      chunk already carries the failed step's real `results` entry). Fixed
      to print the actual command, its exit code, and its output (or an
      explicit note when output was empty, as here) — zero cost, purely a
      display change using data that was already available. Covered by
      `tests/test_cli.py::test_failed_step_shows_command_and_exit_code_not_just_a_bare_message`.
    - Also added, same live-testing round: a general "be internally
      consistent about how a tool was installed" instruction in
      `PLAN_SYSTEM_PROMPT` (not Homebrew-cask-specific — applies equally
      to apt/snap, pip/pipx, etc.), as a cheap mitigation for this class
      of mistake.
12. **Manual-step dependency gap — directly reported by the user testing
    `envagent setup "install xcode"`**: step 1 (installing Xcode) was
    correctly flagged manual and skipped without attempting it — but the
    agent then just moved on to steps 2-3 with no way of knowing whether
    the user had actually gone and done it. Step 3
    (`sudo xcodebuild -license accept`) genuinely requires full Xcode.app,
    which was never installed, so it failed with a real but confusing OS
    error (`active developer directory ... is a command line tools
    instance`) — correct behavior given the state, but the agent had no
    business attempting it at all without checking the prerequisite.
    Fixed in `agent/nodes.py::execute_node`: a non-automatable step now
    raises a `confirm` interrupt — "have you completed this yourself?" —
    instead of silently moving on.
    - Declining stops the run immediately (same pattern as declining a
      destructive step) — no results entry added, nothing attempted.
    - Confirming "yes" does **not** get taken at face value if a
      `check_command` exists: it's **re-run** to verify. Only if it now
      passes does the step get recorded as genuinely satisfied
      (`skipped_install`, not `needs_manual_action`); if it still fails,
      the run stops with a clear `manual_action_still_not_detected`
      message rather than proceeding into a step that likely depends on
      it. Only when there's no `check_command` at all (nothing to verify
      with) does a confirmation get trusted at face value.
    - Live-verified twice against the real machine/provider: (a) a
      synthetic counter-based check confirming the re-check genuinely
      re-runs (fails twice — once before the pause, once again on
      resume's node re-execution — then the explicit post-confirm
      recheck is what actually passes); (b) the exact real `"install
      xcode"` scenario, answering honestly that Xcode isn't installed —
      now stops cleanly at step 1 with zero results recorded, instead of
      cascading into the step-3 crash.
    - Covered by three rewritten/new tests in `tests/test_graph.py`:
      confirmation-then-still-failing stops the run,
      declining stops the run, and (unchanged from before) a check that
      already passes on the first try skips straight past the manual
      flag entirely — idempotency still wins over asking.
13. **Idempotency swallowing a diagnostic step's real output — reported
    directly by the user testing `envagent setup "install flutter sdk"`**:
    the generated plan gave its `flutter doctor -v` step a
    `check_command` of `flutter doctor -v >/dev/null 2>&1`. That exited 0
    (verified live — same machine, same known-incomplete Xcode/Android
    setup from item 8), so the step got skipped via the idempotency path
    entirely — the real diagnostic output never ran, never reached the
    judge, and the judge confidently reported "Goal achieved" based on
    nothing. This is the same exit-code-lies problem `judge_node` exists
    to catch, hitting a different part of the pipeline: the check
    intercepted the step *before* judge_node ever got a chance to see
    real output.
    - Root issue: a step whose purpose is to report *current* status
      (a "doctor"/diagnostic command) is not the kind of thing that
      should ever be treated as idempotent — "it exited 0 once before"
      says nothing about whether problems exist *now*.
    - Fixed two ways, same pattern as the destructive-risk safety net:
      (a) `PLAN_SYSTEM_PROMPT` now explicitly forbids giving a
      diagnostic-purpose step a `check_command`; (b) **deterministic
      override**, not relying on the prompt alone (model behavior on this
      was inconsistent across generations, same non-determinism seen
      throughout this session) — `hitl/gate.py::is_diagnostic_step`
      pattern-matches on `"doctor"`/`"diagnos"`/etc. in the step's own
      command+description, and `execute_node` ignores any
      `check_command` on a match, forcing the step to always run fresh
      regardless of what the plan gave it.
    - Verified against the exact real step shape from the bug report: the
      diagnostic step now genuinely executes (not skipped), its real
      output (including the real Android SDK/Xcode gaps) is captured, and
      a fresh judge call correctly reports `achieved: false` with the
      accurate reasons. (One retry during this verification hit a
      malformed judge JSON response and correctly fell back to the
      existing "couldn't parse, don't claim success" safety net from item
      6 — not a new bug, that fallback working as designed for the first
      time observed live.)
    - Covered by `tests/test_hitl_gate.py::test_flutter_doctor_style_step_is_recognized_as_diagnostic`
      (+ a negative case) and
      `tests/test_graph.py::test_diagnostic_step_ignores_its_own_check_command_and_always_runs`.

Repo is now on GitHub: https://github.com/adityapandey410/envagent
(private) — items 1-9 above are pushed to `main` (commit `f850ece`).
Items 10-13, and all of Phase 2 below, are new since that push and not
yet pushed.

**Phase 2 (doc-grounded Flutter recipe, macOS) is built and verified live
against the real Flutter docs and a real provider call** — not just unit
tests:
- `system/os_detect.py::detect_system()` replaces the Phase-1 string
  stopgap with a structured `SystemInfo`: `os_key` ('macos'/'linux'/
  'windows' — chosen specifically to match doc sites' own OS-selector
  class-naming convention, not an arbitrary internal label), arch,
  release, and which candidate package manager is actually on PATH
  (checked via `shutil.which`, e.g. `brew` on macOS).
- `docs/fetcher.py::fetch_doc()` — tries a page's markdown variant first
  (`<url>.md`), which needs no HTML parsing at all; falls back to
  `beautifulsoup4` extraction. **Verified against the real
  docs.flutter.dev before building on top of it**: found the site
  declares `<link rel="alternate" type="text/markdown">`, confirmed
  `/install/manual.md` returns clean pre-rendered markdown directly —
  `trafilatura` turned out unnecessary for this site.
  `docs/cache.py` — local cache keyed by URL hash, 7-day TTL.
- `docs/fetcher.py::extract_os_section()` — splits on the `{: .steps
  .<os>-only}` marker convention Flutter's docs use for OS-selector tabs
  (a Jekyll-style attribute-list convention: a marker immediately after a
  block retroactively labels that block). **A real bug was caught here
  during verification, not left to production**: the first implementation
  had the marker-to-block pairing backwards (attributed each marker's
  label to the block *after* it instead of *before* it) — it ran without
  error and silently extracted the *wrong* OS's content (macOS's
  extraction actually contained Linux's `apt-get` instructions). Caught
  by checking actual keyword presence (`"Xcode" in section`) against the
  real fetched page rather than trusting that "it ran without a
  traceback" meant it was correct. Fixed and pinned as a regression test
  using a synthetic doc mirroring the exact real structure
  (`tests/test_docs_fetcher.py`, 5 cases). Known accepted limitation:
  content before the *first* marker can't be cleanly separated from that
  first-listed OS's own steps (they're not textually distinguished in the
  source) — a minor cosmetic loss for other OSes, not a correctness
  issue.
- `recipes/registry.py::match_recipe()` — deterministic alias/keyword
  matching against `recipes/*.yaml`, no LLM call (keeps planning at
  exactly one call for recipe-covered goals too, same as freeform).
  `recipes/flutter.yaml` — the first recipe: aliases, `doc_url`
  (`docs.flutter.dev/install/manual`), and an `ide_choice` (message +
  options for VS Code / Android Studio / neither).
- `agent/nodes.py::plan_node` rewired: checks `match_recipe(goal)` before
  planning; on a match, raises a `select` interrupt for the recipe's
  `ide_choice` (**the first real exercise of that interrupt type** —
  previously wired end-to-end but never exercised by real plan content),
  persists the answer in state (`AgentState.ide_choice`, new field) so a
  resumed run doesn't ask again, fetches + OS-extracts the recipe's doc,
  and injects it into the *same single* planning call as grounding
  context (capped at ~6000 chars, same cost-bounding pattern as the
  judge's per-step truncation). No match falls back to Phase 1's
  freeform behavior unchanged. `PLAN_SYSTEM_PROMPT` now instructs the
  model to treat an included doc excerpt as authoritative over its own
  knowledge.
- **Verified live, end-to-end, with the real provider and real Flutter
  docs** (not mocked): `envagent setup "install flutter sdk"` correctly
  matched the flutter recipe, raised the real `select` interrupt with the
  real IDE options, and — after resuming with "VS Code" — produced a plan
  using the **manual zip-download method** (`~/develop`,
  `flutter_macos_..._stable.zip`, PATH setup, `flutter doctor`) matching
  the real `/install/manual` doc's actual structure exactly — a visibly
  different (and now doc-accurate) plan shape from earlier ungrounded
  runs, which had used a Homebrew-based approach instead.
- Also covered by 3 new tests in `tests/test_graph.py` (recipe match
  raises the select interrupt; the planning prompt actually contains the
  fetched doc content, checked via a capturing fake provider; `ide_choice`
  isn't asked again on resume) and 2 pre-existing judge tests whose goals
  needed to be changed to non-flutter strings, since "flutter" now
  legitimately matches the new recipe and those tests are about judge
  logic specifically, not recipe behavior.
- **`system/permissions.py` — the last piece of Phase 2's original
  scope, built after a status check surfaced it was missing**:
  `is_elevated()` (already running as root/Administrator?) and
  `can_elevate()` (best-effort — root already, or a member of an
  admin-capable group: `admin`/`sudo`/`wheel` on macOS/Linux via the
  `grp` module; `IsUserAnAdmin()` on Windows, which only reflects current
  elevation state, not group membership — deliberately not investing
  further in Windows precision since it's out of scope until Phase 4).
  Verified against this real machine's actual group membership (`admin`,
  confirmed via `groups`) before trusting it: `is_elevated() == False`,
  `can_elevate() == True`, both correct.
  - `plan_node` calls `can_elevate()` alongside OS detection; if false,
    emits a `cannot_elevate` warning event (rendered by `cli.py`) *and*
    folds a note into the same single planning call telling the model to
    avoid elevation-requiring steps where a non-privileged alternative
    exists, rather than silently discovering a permission failure
    several steps into a run.
  - Covered by `tests/test_permissions.py` (5 cases: elevated/not,
    admin-group/not, monkeypatched rather than relying on this specific
    machine's real state so the tests are portable) and
    `tests/test_graph.py::test_plan_prompt_warns_the_model_when_user_cannot_elevate`.

Not yet done: `.github/ISSUE_TEMPLATE/` and Discussions not set up;
`checkbox` interrupt type is still implemented end-to-end but not yet
exercised by any real plan content (only `select` has been, via the IDE
choice above); LangSmith tracing needs no code (documented in README —
env vars only) but hasn't been turned on and inspected yet; recipes exist
for Flutter only, macOS only — Node/Python/Docker and Ubuntu are Phase 3.

**Phase 2 is now fully complete** against its original scope (OS
detection, doc fetcher, Flutter recipe end-to-end, `select` HITL,
permissions checks).

**`scripts/install.sh` (Phase 5 item, pulled forward) is built and
verified**: a two-stage POSIX-sh bootstrap for a genuinely fresh
macOS/Linux machine (nothing preinstalled but `curl`) — installs `uv`
itself first if missing (a standalone binary download, needs no Python
preinstalled), then `uv tool install`s the repo, which also handles
getting the right Python version automatically. Verified live:
`uv tool install git+https://github.com/adityapandey410/envagent`
actually installs and produces a working `envagent` command.
**Important caveat surfaced by that verification**: it only worked
because the author's local `git` is authenticated to this **private**
repo (via `gh auth setup-git`) — it will not work for anyone else until
the repo is made public, or envagent is published to PyPI instead (which
needs no repo-level auth at all, since it's a public registry). Windows
isn't covered by this script — Phase 4 scope, same as everywhere else;
a Windows user would need uv's separate PowerShell installer.

Next concrete step: Phase 3 — expand recipes to Node/Python/Docker, add
Ubuntu support. (Making the repo public, or publishing to PyPI, is a
separate decision needed before `install.sh` is actually usable by
anyone else — not yet decided.)
