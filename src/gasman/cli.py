"""CLI entrypoint for gasman dashboard."""

from __future__ import annotations

import argparse
import logging
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from .config import Config, find_tmux_socket


GASMAN_DIR = Path.home() / ".gasman"
PID_FILE = GASMAN_DIR / "gasman.pid"
LOG_FILE = GASMAN_DIR / "gasman.log"


def _ensure_gasman_dir():
    """Create ~/.gasman/ if it doesn't exist."""
    GASMAN_DIR.mkdir(parents=True, exist_ok=True)


def setup_logging(verbose: bool = False):
    """Configure logging to stderr for foreground operation."""
    level = logging.DEBUG if verbose else logging.INFO
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [gasman] %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    logging.basicConfig(level=level, handlers=[handler])


def _find_gasman_script() -> str:
    """Find the gasman console script installed in the current environment."""
    # Prefer the script next to the running Python interpreter (same venv)
    venv_script = Path(sys.executable).parent / "gasman"
    if venv_script.is_file():
        return str(venv_script)
    # Fall back to PATH lookup
    found = shutil.which("gasman")
    if found:
        return found
    # Last resort: invoke via python -m (may fail without __main__.py)
    return f"{sys.executable} -m gasman"


def _build_foreground_cmd(args) -> str:
    """Build the 'gasman start --foreground' command string from current args."""
    gasman_bin = _find_gasman_script()
    parts = [gasman_bin, "start", "--foreground"]
    if args.verbose:
        parts.insert(1, "--verbose")
    if args.config:
        parts.insert(1, "--config")
        parts.insert(2, args.config)
    if args.poll:
        parts.extend(["--poll", str(args.poll)])
    if args.font_size:
        parts.extend(["--font-size", str(args.font_size)])
    return " ".join(shlex.quote(p) for p in parts)


def _open_iterm_tab(command: str) -> bool:
    """Open a new iTerm2 tab and run the given command in it.

    Uses AppleScript to create a new tab in the current iTerm2 window,
    then sends the command to execute. Returns True on success.
    """
    # Escape for AppleScript string literal (backslash and double-quote)
    escaped = command.replace("\\", "\\\\").replace('"', '\\"')
    applescript = f'''
    tell application "iTerm2"
        tell current window
            set newTab to (create tab with default profile)
            tell current session of newTab
                write text "{escaped}"
            end tell
        end tell
    end tell
    '''
    try:
        result = subprocess.run(
            ["osascript", "-e", applescript],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def cmd_start(args):
    """Start the gasman dashboard.

    Default: opens a new iTerm2 tab for the dashboard and returns immediately.
    With --foreground: runs the dashboard in the current terminal (Ctrl+C to quit).
    """
    _ensure_gasman_dir()

    # Check if already running
    if PID_FILE.exists():
        try:
            existing_pid = int(PID_FILE.read_text().strip())
            os.kill(existing_pid, 0)
            print(f"gasman is already running (PID {existing_pid})")
            sys.exit(1)
        except (ProcessLookupError, ValueError):
            PID_FILE.unlink(missing_ok=True)

    # Default mode: relocate to a new iTerm2 tab
    if not args.foreground:
        fg_cmd = _build_foreground_cmd(args)
        if _open_iterm_tab(fg_cmd):
            print("gasman started in new tab.")
            return
        else:
            print("Failed to open iTerm2 tab. Falling back to foreground mode.",
                  file=sys.stderr)

    # Foreground mode: run the dashboard directly
    config = Config.load(Path(args.config) if args.config else None)

    if args.poll:
        config.poll_interval = args.poll
    if args.font_size:
        config.font_size = args.font_size

    setup_logging(args.verbose)
    log = logging.getLogger(__name__)

    socket = find_tmux_socket(config.tmux_socket_glob)
    if socket:
        log.info("Found GT tmux socket: %s", socket)
    else:
        log.info("No tmux socket yet (pattern: %s). Waiting...", config.tmux_socket_glob)

    PID_FILE.write_text(str(os.getpid()))

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
    """Stop a running gasman dashboard."""
    import signal as _signal

    setup_logging(args.verbose)
    log = logging.getLogger(__name__)

    if not PID_FILE.exists():
        log.error("No gasman process found (no PID file at %s)", PID_FILE)
        sys.exit(1)

    pid = int(PID_FILE.read_text().strip())
    try:
        os.kill(pid, _signal.SIGINT)
        log.info("Sent SIGINT to gasman (PID %d) — tabs will be cleaned up", pid)
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

    start_p = sub.add_parser("start", help="Start the dashboard in a new iTerm2 tab")
    start_p.add_argument("--foreground", action="store_true",
                         help="Run in the current terminal instead of opening a new tab")
    start_p.add_argument("--poll", type=float, help="Poll interval in seconds")
    start_p.add_argument("--font-size", type=int, help="Font size for polecat tabs")
    start_p.set_defaults(func=cmd_start)

    stop_p = sub.add_parser("stop", help="Stop the dashboard")
    stop_p.set_defaults(func=cmd_stop)

    status_p = sub.add_parser("status", help="Show dashboard status")
    status_p.set_defaults(func=cmd_status)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
