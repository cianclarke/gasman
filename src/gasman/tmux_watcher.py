"""Watch GT tmux socket for polecat session lifecycle events."""

from __future__ import annotations

import asyncio
import logging
import subprocess
from dataclasses import dataclass

from .config import Config, find_tmux_socket, is_polecat_session

log = logging.getLogger(__name__)


@dataclass
class SessionEvent:
    """A polecat session lifecycle event."""

    name: str
    event_type: str  # "spawn" or "exit"


def list_tmux_sessions(socket_name: str) -> set[str]:
    """List all current tmux sessions on the given socket."""
    try:
        result = subprocess.run(
            ["tmux", "-L", socket_name, "list-sessions", "-F", "#{session_name}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return set()
        return {line.strip() for line in result.stdout.splitlines() if line.strip()}
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return set()


class TmuxWatcher:
    """Polls the GT tmux socket for polecat session changes."""

    def __init__(self, config: Config):
        self.config = config
        self._known_sessions: set[str] = set()
        self._socket_name: str | None = None
        self._running = False

    def _find_socket(self) -> str | None:
        """Find and cache the tmux socket."""
        if self._socket_name is None:
            self._socket_name = find_tmux_socket(self.config.tmux_socket_glob)
        return self._socket_name

    def _get_polecat_sessions(self) -> set[str]:
        """Get the current set of polecat sessions."""
        socket = self._find_socket()
        if not socket:
            return set()
        all_sessions = list_tmux_sessions(socket)
        return {s for s in all_sessions if is_polecat_session(s, self.config)}

    async def watch(self, callback):
        """Watch for session changes, calling callback(SessionEvent) on each.

        Args:
            callback: async callable that receives SessionEvent objects.
        """
        self._running = True
        self._known_sessions = self._get_polecat_sessions()
        log.info("Initial polecat sessions: %s", self._known_sessions)

        while self._running:
            await asyncio.sleep(self.config.poll_interval)

            # Re-discover socket if not found yet
            if self._socket_name is None:
                self._socket_name = find_tmux_socket(self.config.tmux_socket_glob)
                if self._socket_name is None:
                    continue

            current = self._get_polecat_sessions()

            # Detect new sessions (spawns)
            spawned = current - self._known_sessions
            for name in sorted(spawned):
                log.info("Polecat spawned: %s", name)
                await callback(SessionEvent(name=name, event_type="spawn"))

            # Detect removed sessions (exits)
            exited = self._known_sessions - current
            for name in sorted(exited):
                log.info("Polecat exited: %s", name)
                await callback(SessionEvent(name=name, event_type="exit"))

            self._known_sessions = current

    def stop(self):
        """Signal the watcher to stop."""
        self._running = False

    @property
    def socket_name(self) -> str | None:
        return self._find_socket()
