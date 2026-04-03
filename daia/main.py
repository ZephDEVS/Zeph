"""CLI entry point for Zeph."""

from __future__ import annotations

import argparse
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from daia.agent import ZephAgent
from daia.webui import launch_gui


def build_banner(agent: ZephAgent) -> Panel:
    """Create the startup banner."""

    status = agent.startup_status()
    table = Table.grid(padding=(0, 2))
    table.add_row("Agent", status["agent_name"])
    table.add_row("OS", status["os"])
    table.add_row("Monitors", str(len(status["monitors"])))
    table.add_row("Memory DB", status["db_path"])
    table.add_row("Scheduled Tasks", str(status["scheduled_tasks"]))
    table.add_row("Recent Activity", status["recent_activity"])
    return Panel(table, title="Zeph Desktop AI Agent", border_style="cyan")


def repl(agent: ZephAgent) -> None:
    """Run the interactive REPL."""

    agent.announce("Interactive mode ready. Type 'exit' to quit.")
    while True:
        try:
            command = input("zeph> ").strip()
        except (EOFError, KeyboardInterrupt):
            agent.console.print()
            break
        if not command:
            continue
        if command.lower() in {"exit", "quit"}:
            break
        result = agent.execute(command)
        agent.console.print(Panel.fit(result, title="Result"))


def main(argv: list[str] | None = None) -> int:
    """Program entry point."""

    parser = argparse.ArgumentParser(description="Zeph Desktop AI Agent")
    parser.add_argument("command", nargs="*", help="Command to run")
    parser.add_argument("--gui", action="store_true", help="Run the desktop GUI")
    parser.add_argument("--terminal", action="store_true", help="Force terminal REPL mode")
    parser.add_argument("--voice", action="store_true", help="Run in voice mode")
    args = parser.parse_args(argv)

    if args.gui or (not args.command and not args.voice and not args.terminal):
        return launch_gui()

    console = Console()
    agent = ZephAgent(console=console)
    agent.first_run_setup()
    console.print(build_banner(agent))

    if args.voice:
        agent.run_voice_loop()
        return 0

    if args.command:
        result = agent.execute(" ".join(args.command))
        console.print(Panel.fit(result, title="Result"))
        return 0

    repl(agent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
