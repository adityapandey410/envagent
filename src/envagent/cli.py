from __future__ import annotations

import uuid

import questionary
import typer
from langgraph.types import Command
from rich.console import Console

from envagent.agent.graph import build_graph
from envagent.agent.nodes import NoStepsPlannedError, NotConfiguredError
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
    """Plan and execute an environment setup, pausing for confirmation before any destructive step."""
    graph = build_graph()
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    console.print(f"[dim]Session: {thread_id}[/dim]")

    settings = load_settings()
    settings.extra["active_thread_id"] = thread_id
    save_settings(settings)

    try:
        final_state = _drive_to_completion(
            graph, config, {"goal": goal, "status": "planning"}
        )
    except (NotConfiguredError, NoStepsPlannedError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    _finish(final_state, settings)


@app.command()
def resume() -> None:
    """Resume the most recent setup session paused on a HITL interrupt."""
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
    final_state = _drive_to_completion(graph, config, Command(resume=answer))
    _finish(final_state, settings)


def _drive_to_completion(graph, config: dict, stream_input) -> dict:
    """Streams the graph, rendering progress and resolving interrupts until a terminal state."""
    while True:
        interrupted = False
        for mode, chunk in graph.stream(stream_input, config, stream_mode=["custom", "updates"]):
            if mode == "custom":
                _print_progress_event(chunk)
                continue
            if "__interrupt__" in chunk:
                payload = chunk["__interrupt__"][0].value
                answer = _render_interrupt(payload)
                stream_input = Command(resume=answer)
                interrupted = True
                break
            if chunk.get("verify", {}).get("status") == "failed":
                results = chunk["verify"].get("results") or []
                if results:
                    last = results[-1]
                    console.print(
                        f"[red]Step failed:[/red] `{last['command']}` "
                        f"exited with code {last['returncode']}"
                    )
                    if last.get("stdout", "").strip():
                        console.print(last["stdout"].rstrip())
                    else:
                        console.print("[dim](no output was produced — the failure may be in a redirected/suppressed part of the command)[/dim]")
                else:
                    console.print("[red]Step failed.[/red]")
        if not interrupted:
            break
    return graph.get_state(config).values


def _print_progress_event(event: dict) -> None:
    kind = event.get("type")
    if kind == "system_info":
        console.print(f"[dim]Detected system: {event['description']}[/dim]")
    elif kind == "cannot_elevate":
        console.print(
            "[yellow]Warning: this user can't run privileged (sudo/admin) commands "
            "on this machine — some steps may fail if elevation is required.[/yellow]"
        )
    elif kind == "recipe_matched":
        console.print(f"[dim]Using vetted recipe: {event['name']} (doc-grounded plan).[/dim]")
    elif kind == "recipe_unsupported_on_os":
        console.print(
            f"[yellow]No vetted {event['name']} recipe for {event['os_key']} yet — "
            "falling back to freeform (ungrounded) planning.[/yellow]"
        )
    elif kind == "plan_ready":
        plan = event["plan"]
        console.print(f"[dim]Plan generated: {len(plan)} step(s).[/dim]")
        for i, step in enumerate(plan, start=1):
            tag = "manual" if not step.get("automatable", True) else step["risk"]
            console.print(f"  {i}. {step['description']} [dim]({tag})[/dim]")
    elif kind == "check_start":
        console.print(f"[dim]$ {event['command']}[/dim]  [dim]({event['description']})[/dim]")
    elif kind == "check_satisfied":
        console.print(f"[dim]  -> already satisfied: {event['description']} — skipping.[/dim]")
    elif kind == "manual_action_needed":
        console.print(
            f"[yellow]  -> can't be automated: {event['description']}[/yellow]\n"
            f"     {event['instructions']}"
        )
    elif kind == "manual_action_still_not_detected":
        console.print(
            f"[red]  -> still not detected: {event['description']} — stopping here "
            "rather than continue past a step that likely depends on it.[/red]"
        )
    elif kind == "command_start":
        console.print(f"[bold]$ {event['command']}[/bold]  [dim]({event['description']})[/dim]")
    elif kind == "output_line":
        console.print(event["line"])
    elif kind == "judging_start":
        console.print("[dim]Reviewing whether the goal was actually achieved...[/dim]")


def _finish(result: dict, settings: Settings) -> None:
    settings.extra.pop("active_thread_id", None)
    save_settings(settings)
    if result["status"] != "done":
        console.print("[red]Setup stopped (a step failed or was declined).[/red]")
        return

    assessment = result.get("assessment")
    if assessment is None:
        console.print("[yellow]All steps ran, but the outcome wasn't verified.[/yellow]")
    elif assessment["achieved"]:
        console.print(f"[green]Goal achieved:[/green] {assessment['summary']}")
    else:
        console.print(
            f"[yellow]Steps ran, but the goal may not be fully achieved:[/yellow] "
            f"{assessment['summary']}"
        )

    manual_steps = [r for r in result.get("results", []) if r.get("needs_manual_action")]
    if manual_steps:
        console.print("\n[yellow]Manual steps still needed:[/yellow]")
        for entry in manual_steps:
            console.print(f"  - {entry['manual_instructions']}")


def _render_interrupt(payload: dict):
    if payload["type"] == "confirm":
        return questionary.confirm(payload["message"], default=False).ask()
    if payload["type"] == "select":
        return questionary.select(payload["message"], choices=payload["options"]).ask()
    if payload["type"] == "checkbox":
        return questionary.checkbox(payload["message"], choices=payload["options"]).ask()
    if payload["type"] == "text":
        return questionary.text(payload["message"]).ask()
    raise ValueError(f"Unknown interrupt type: {payload['type']!r}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
