from __future__ import annotations

import uuid

import questionary
import typer
from langgraph.types import Command
from rich.console import Console

from envagent.agent.graph import build_graph
from envagent.agent.nodes import NotConfiguredError
from envagent.config.credentials import get_api_key, set_api_key
from envagent.config.settings import Settings, load_settings, save_settings
from envagent.providers.base import ProviderAuthError
from envagent.providers.registry import PROVIDERS

app = typer.Typer(add_completion=False)
console = Console()


@app.command()
def init() -> None:
    """Pick a provider, enter an API key, validate it, and store it."""
    provider_id = questionary.select(
        "Which LLM provider do you want to use?",
        choices=[
            questionary.Choice(title=p.display_name, value=p.id)
            for p in PROVIDERS.values()
        ],
    ).ask()
    if provider_id is None:
        raise typer.Exit(code=1)

    provider = PROVIDERS[provider_id]

    if get_api_key(provider.id):
        keep_existing = questionary.confirm(
            f"A key is already saved for {provider.display_name}. Keep using it?",
            default=True,
        ).ask()
        if keep_existing is None:
            raise typer.Exit(code=1)
        if keep_existing:
            save_settings(Settings(provider=provider.id, model=provider.default_model))
            console.print(f"[green]Keeping existing {provider.display_name} key.[/green]")
            return

    api_key = questionary.password(f"Enter your {provider.display_name} API key:").ask()
    if not api_key:
        console.print("[red]No API key entered.[/red]")
        raise typer.Exit(code=1)

    with console.status(f"Validating {provider.display_name} key..."):
        try:
            provider.validate_key(api_key)
        except ProviderAuthError as exc:
            console.print(f"[red]Key validation failed:[/red] {exc}")
            raise typer.Exit(code=1) from exc

    set_api_key(provider.id, api_key)
    save_settings(Settings(provider=provider.id, model=provider.default_model))
    console.print(f"[green]{provider.display_name} key validated and stored.[/green]")


@app.command()
def setup(
    goal: str = typer.Argument(
        ..., help="What to set up, e.g. 'set up flutter for android development'"
    ),
) -> None:
    """Plan and execute an environment setup, pausing for confirmation
    before any destructive step (Phase 1: freeform LLM planning, no
    recipes/doc-grounding yet)."""
    graph = build_graph()
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    console.print(f"[dim]Session: {thread_id}[/dim]")

    settings = load_settings()
    settings.extra["active_thread_id"] = thread_id
    save_settings(settings)

    try:
        result = graph.invoke({"goal": goal, "status": "planning"}, config)
    except NotConfiguredError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    result = _drive_to_completion(graph, config, result)
    _finish(result, settings)


@app.command()
def resume() -> None:
    """Resume the most recent setup session that's paused on a HITL
    interrupt — e.g. the terminal was closed or the process died while a
    confirmation prompt was pending."""
    settings = load_settings()
    thread_id = settings.extra.get("active_thread_id")
    if not thread_id:
        console.print("[yellow]No interrupted session to resume.[/yellow]")
        raise typer.Exit(code=1)

    graph = build_graph()
    config = {"configurable": {"thread_id": thread_id}}
    state = graph.get_state(config)
    if not state.next:
        console.print("[yellow]That session already finished — nothing to resume.[/yellow]")
        settings.extra.pop("active_thread_id", None)
        save_settings(settings)
        raise typer.Exit(code=1)

    console.print(f"[dim]Resuming session: {thread_id}[/dim]")
    payload = state.tasks[0].interrupts[0].value
    answer = _render_interrupt(payload)
    result = graph.invoke(Command(resume=answer), config)
    result = _drive_to_completion(graph, config, result)
    _finish(result, settings)


def _drive_to_completion(graph, config: dict, result: dict) -> dict:
    while "__interrupt__" in result:
        payload = result["__interrupt__"][0].value
        answer = _render_interrupt(payload)
        result = graph.invoke(Command(resume=answer), config)
    return result


def _finish(result: dict, settings: Settings) -> None:
    settings.extra.pop("active_thread_id", None)
    save_settings(settings)
    if result["status"] == "done":
        console.print("[green]Setup complete.[/green]")
    else:
        console.print("[red]Setup stopped (a step failed or was declined).[/red]")


def _render_interrupt(payload: dict):
    if payload["type"] == "confirm":
        return questionary.confirm(payload["message"], default=False).ask()
    if payload["type"] == "select":
        return questionary.select(payload["message"], choices=payload["options"]).ask()
    if payload["type"] == "checkbox":
        return questionary.checkbox(payload["message"], choices=payload["options"]).ask()
    raise ValueError(f"Unknown interrupt type: {payload['type']!r}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
