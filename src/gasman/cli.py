"""CLI entrypoint for gasman dashboard."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

from .config import Config, find_tmux_socket


PID_FILE = Path.home() / ".gasman.pid"


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [gasman] %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )


def cmd_start(args):
    """Start the gasman dashboard."""
    setup_logging(args.verbose)
    log = logging.getLogger(__name__)

    config = Config.load(Path(args.config) if args.config else None)

    # Override config with CLI args
    if args.poll:
        config.poll_interval = args.poll
    if args.font_size:
        config.font_size = args.font_size

    # Check for tmux socket
    socket = find_tmux_socket(config.tmux_socket_glob)
    if socket:
        log.info("Found GT tmux socket: %s", socket)
    else:
        log.warning(
            "No GT tmux socket found matching '%s'. Will keep looking...",
            config.tmux_socket_glob,
        )

    # Write PID file
    PID_FILE.write_text(str(os.getpid()))

    # Import here to defer iterm2 dependency check
    from .iterm_dashboard import run_dashboard

    try:
        asyncio.run(run_dashboard(config))
    except KeyboardInterrupt:
        log.info("Shutting down.")
    finally:
        PID_FILE.unlink(missing_ok=True)


def cmd_stop(args):
    """Stop a running gasman dashboard."""
    setup_logging(args.verbose)
    log = logging.getLogger(__name__)

    if not PID_FILE.exists():
        log.error("No gasman process found (no PID file at %s)", PID_FILE)
        sys.exit(1)

    pid = int(PID_FILE.read_text().strip())
    try:
        os.kill(pid, signal.SIGTERM)
        log.info("Sent SIGTERM to gasman (PID %d)", pid)
    except ProcessLookupError:
        log.warning("Process %d not found. Cleaning up stale PID file.", pid)
    PID_FILE.unlink(missing_ok=True)


def cmd_status(args):
    """Show current dashboard status."""
    setup_logging(args.verbose)

    config = Config.load(Path(args.config) if args.config else None)
    socket = find_tmux_socket(config.tmux_socket_glob)

    # Check if dashboard is running
    running = False
    pid = None
    if PID_FILE.exists():
        pid = int(PID_FILE.read_text().strip())
        try:
            os.kill(pid, 0)  # Check if process exists
            running = True
        except ProcessLookupError:
            pass

    print(f"Dashboard: {'running (PID {})'.format(pid) if running else 'stopped'}")
    print(f"Tmux socket: {socket or 'not found'}")

    if socket:
        from .tmux_watcher import list_tmux_sessions
        from .config import is_polecat_session

        all_sessions = list_tmux_sessions(socket)
        polecats = {s for s in all_sessions if is_polecat_session(s, config)}
        infra = all_sessions - polecats

        print(f"Total sessions: {len(all_sessions)}")
        print(f"Polecat sessions: {len(polecats)}")
        if polecats:
            for name in sorted(polecats):
                print(f"  - {name}")
        print(f"Infrastructure: {len(infra)}")
        if args.verbose and infra:
            for name in sorted(infra):
                print(f"  - {name}")


def main():
    parser = argparse.ArgumentParser(
        prog="gasman",
        description="iTerm2 polecat dashboard for Gas Town",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging"
    )
    parser.add_argument(
        "-c", "--config", help="Config file path (default: ~/.gasman.yaml)"
    )

    sub = parser.add_subparsers(dest="command", required=True)

    start_p = sub.add_parser("start", help="Start the dashboard")
    start_p.add_argument("--poll", type=float, help="Poll interval in seconds")
    start_p.add_argument("--font-size", type=int, help="Font size for polecat panes")
    start_p.set_defaults(func=cmd_start)

    stop_p = sub.add_parser("stop", help="Stop the dashboard")
    stop_p.set_defaults(func=cmd_stop)

    status_p = sub.add_parser("status", help="Show dashboard status")
    status_p.set_defaults(func=cmd_status)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
