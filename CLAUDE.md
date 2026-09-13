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
   to the user → executes one step at a time, verifying after each step →
   interrupts for human input wherever needed (see HITL section) before any
   destructive/irreversible action or whenever a choice among valid options
   exists (e.g. which IDE to configure).
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
  commands.
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
│   │   ├── graph.py           # LangGraph graph: plan -> execute -> verify -> (loop|end)
│   │   ├── state.py           # graph state schema
│   │   ├── nodes.py           # plan / execute / verify node implementations
│   │   ├── checkpointer.py    # SqliteSaver setup (local persistence for resume)
│   │   └── prompts.py         # PLAN_SYSTEM_PROMPT
│   ├── system/
│   │   ├── os_detect.py       # OS/arch/package-manager detection (not built yet - Phase 2)
│   │   ├── permissions.py     # sudo/admin/UAC checks (not built yet - Phase 2)
│   │   └── executor.py        # subprocess execution + JSONL logging + undo_command per entry
│   ├── docs/
│   │   ├── fetcher.py         # fetch + clean official doc pages
│   │   └── cache.py
│   ├── recipes/
│   │   ├── registry.py        # loads vetted setup recipes
│   │   └── flutter.yaml       # example: steps, verify commands, doc links
│   └── hitl/
│       └── gate.py            # risk classification + typed interrupt payloads
│                               # ({type: confirm|select|checkbox, message, options?})
│                               # PlanStep also carries check_command (idempotency)
├── evals/
│   └── scenarios/              # eval dataset: request -> expected plan/tool-calls/HITL
├── tests/
└── scripts/install.sh         # curl-based bootstrap installer
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
- **Phase 6 — Stretch**: IDE/editor integration (e.g. VSCode settings and
  extension install), community-contributed recipes, plugin system.

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

**Three additions landed after Phase 1, pulled forward from Phase 2/later
because they were judged too important to defer:**

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

Not yet done: no git commits made yet (repo initialized, working tree
otherwise untracked); `.github/ISSUE_TEMPLATE/` and Discussions not set
up; `select`/`checkbox` interrupt types are implemented end-to-end in
`cli.py` but not yet exercised by any real plan content (nothing in
Phase 1's freeform planning asks for a choice — that arrives with the
Flutter recipe's IDE choice in Phase 2); LangSmith tracing needs no code
(documented in README — env vars only) but hasn't been turned on and
inspected yet; official doc grounding (fetch a recipe's real doc URL,
extract the OS-relevant section, inject as prompt context) is unbuilt —
requires `docs/fetcher.py` (httpx + beautifulsoup4/trafilatura),
`docs/cache.py`, and a recipe registry carrying doc URLs, all Phase 2.

Next concrete step: Phase 2 — full `os_detect.py`, the doc fetcher +
cache described above, and the first real (non-freeform, doc-grounded)
recipe: Flutter on macOS, end-to-end, including a `select` HITL for IDE
choice.
