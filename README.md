# envagent

A CLI agent that sets up developer environments from a natural-language
request, with human confirmation before any destructive step. See
[CLAUDE.md](CLAUDE.md) for the full project context, architecture, and
roadmap.

## Setup

```bash
uv sync
uv run envagent init    # pick a provider, enter an API key
uv run envagent setup "set up flutter for android development"
```

## Development-time tracing (optional)

Tracing is off by default. To trace your own runs in LangSmith while
developing, set these before running the CLI — no code changes needed,
LangGraph auto-instruments from the environment:

```bash
export LANGSMITH_TRACING=true
export LANGSMITH_API_KEY="..."
```

## Tests

```bash
uv run pytest
```
