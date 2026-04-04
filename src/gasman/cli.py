"""CLI entrypoint for gasman dashboard."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
from pathlib import Path

from .config import Config, find_tmux_socket


GASMAN_DIR = Path.home() / ".gasman"
PID_FILE = GASMAN_DIR / "gasman.pid"
LOG_FILE = GASMAN_DIR / "gasman.log"


def _ensure_gasman_dir():
    """Create ~/.gasman/ if it doesn't exist."""
    GASMAN_DIR.mkdir(parents=True, exist_ok=True)


def setup_logging(verbose: bool = False, to_file: bool = False):
    """Configure logging. If to_file, writes to ~/.gasman/gasman.log."""
    level = logging.DEBUG if verbose else logging.INFO
    handlers: list[logging.Handler] = []

    if to_file:
        _ensure_gasman_dir()
        handler = logging.FileHandler(str(LOG_FILE), mode="a")
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [gasman] %(levelname)s %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        handlers.append(handler)
    else:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [gasman] %(levelname)s %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        handlers.append(handler)

    logging.basicConfig(level=level, handlers=handlers)


def _daemonize():
    """Fork the process into a background daemon (double-fork)."""
    # First fork
    pid = os.fork()
    if pid > 0:
        # Parent exits — child continues
        sys.exit(0)

    # Decouple from parent environment
    os.setsid()

    # Second fork — prevent zombie and ensure no controlling terminal
    pid = os.fork()
    if pid > 0:
        sys.exit(0)

    # Redirect stdin/stdout/stderr to /dev/null
    devnull = os.open(os.devnull, os.O_RDWR)
    os.dup2(devnull, 0)
    os.dup2(devnull, 1)
    os.dup2(devnull, 2)
    os.close(devnull)


def cmd_start(args):
    """Start the gasman dashboard."""
    _ensure_gasman_dir()

    # Check if already running
    if PID_FILE.exists():
        try:
            existing_pid = int(PID_FILE.read_text().strip())
            os.kill(existing_pid, 0)
            print(f"gasman is already running (PID {existing_pid})")
            sys.exit(1)
        except (ProcessLookupError, ValueError):
            # Stale PID file — clean up
            PID_FILE.unlink(missing_ok=True)

    config = Config.load(Path(args.config) if args.config else None)

    # Override config with CLI args
    if args.poll:
        config.poll_interval = args.poll
    if args.font_size:
        config.font_size = args.font_size

    if not args.foreground:
        print(f"Starting gasman daemon... (log: {LOG_FILE})")
        _daemonize()

    # After daemonize (or in foreground mode), set up logging
    setup_logging(args.verbose, to_file=not args.foreground)
    log = logging.getLogger(__name__)

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
        run_dashboard(config)
    except KeyboardInterrupt:
        log.info("Shutting down.")
    except Exception:
        log.exception("Dashboard crashed")
    finally:
        PID_FILE.unlink(missing_ok=True)


def cmd_stop(args):
    """Stop a running gasman dashboard and clean up panes."""
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
    print(f"PID file: {PID_FILE}")
    print(f"Log file: {LOG_FILE}")
    print(f"Tmux socket: {socket or 'not found'}")

    if socket:
        from .tmux_watcher import list_tmux_sessions, is_session_active
        from .config import is_polecat_session

        all_sessions = list_tmux_sessions(socket)
        polecats = {s for s in all_sessions if is_polecat_session(s, config)}
        active = {s for s in polecats if is_session_active(socket, s)}
        stale = polecats - active
        infra = all_sessions - polecats

        print(f"Total sessions: {len(all_sessions)}")
        print(f"Active polecats: {len(active)}")
        if active:
            for name in sorted(active):
                print(f"  - {name}")
        if stale:
            print(f"Stale polecats (idle): {len(stale)}")
            for name in sorted(stale):
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
    start_p.add_argument(
        "--foreground", "-f", action="store_true",
        help="Run in foreground (don't daemonize)",
    )
    start_p.set_defaults(func=cmd_start)

    stop_p = sub.add_parser("stop", help="Stop the dashboard")
    stop_p.set_defaults(func=cmd_stop)

    status_p = sub.add_parser("status", help="Show dashboard status")
    status_p.set_defaults(func=cmd_status)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
