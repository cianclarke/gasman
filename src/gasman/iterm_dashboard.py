"""iTerm2 Python API pane management for the polecat dashboard."""

from __future__ import annotations

import asyncio
import logging

import iterm2

from .config import Config
from .tmux_watcher import SessionEvent, TmuxWatcher

log = logging.getLogger(__name__)


class Dashboard:
    """Manages iTerm2 panes for polecat sessions.

    Layout: Mayor/user terminal stays in the left pane. Polecats tile
    vertically on the right side via horizontal splits.
    """

    def __init__(self, config: Config, connection: iterm2.Connection):
        self.config = config
        self.connection = connection
        self.watcher = TmuxWatcher(config)
        # Maps session name -> iTerm2 session ID
        self._pane_map: dict[str, str] = {}
        # The mayor's (original) iTerm2 session — always stays leftmost
        self._mayor_session_id: str | None = None

    async def start(self):
        """Start the dashboard: set up layout and begin watching."""
        app = await iterm2.async_get_app(self.connection)
        window = app.current_terminal_window
        if not window:
            log.error("No current iTerm2 window found")
            return

        self._window = window
        self._main_tab = window.current_tab
        # Pin the mayor's session (the current/leftmost pane at startup)
        self._mayor_session_id = self._main_tab.current_session.session_id

        socket = self.watcher.socket_name
        if not socket:
            log.warning("No GT tmux socket found matching '%s'", self.config.tmux_socket_glob)
            log.info("Waiting for tmux socket to appear...")

        # Do NOT scan for existing polecat sessions on startup.
        # Only react to NEW sessions appearing after gasman starts.
        # The watcher seeds _known_sessions so existing sessions are ignored.

        log.info(
            "Dashboard started. Watching for polecats (socket pattern: %s, poll: %.1fs)",
            self.config.tmux_socket_glob,
            self.config.poll_interval,
        )

        # Begin watching for lifecycle events
        await self.watcher.watch(self._handle_event)

    async def _handle_event(self, event: SessionEvent):
        """Handle a polecat spawn or exit event."""
        if event.event_type == "spawn":
            await self._spawn_pane(event.name)
        elif event.event_type == "exit":
            await self._close_pane(event.name)

    async def _spawn_pane(self, session_name: str):
        """Create a new iTerm2 pane for a polecat session."""
        if session_name in self._pane_map:
            log.debug("Pane already exists for %s", session_name)
            return

        socket = self.watcher.socket_name
        if not socket:
            log.warning("Cannot spawn pane for %s: no tmux socket", session_name)
            return

        try:
            app = await iterm2.async_get_app(self.connection)

            # Split horizontally (right side) for the first polecat,
            # vertically within the right column for subsequent ones
            if not self._pane_map:
                # First polecat: split the mayor's pane to the right
                mayor_session = app.get_session_by_id(self._mayor_session_id)
                if mayor_session is None:
                    mayor_session = self._main_tab.current_session
                new_session = await mayor_session.async_split_pane(
                    vertical=True,  # side-by-side (polecat goes right)
                )
            else:
                # Subsequent: split the last polecat pane vertically
                last_session_id = list(self._pane_map.values())[-1]
                target = app.get_session_by_id(last_session_id)
                if target is None:
                    # Fallback: split the mayor's pane
                    target = app.get_session_by_id(self._mayor_session_id)
                    if target is None:
                        target = self._main_tab.current_session
                new_session = await target.async_split_pane(
                    vertical=False,  # stack vertically in right column
                )

            # Attach to the polecat's tmux session in read-only mode
            attach_cmd = f"tmux -L {socket} attach-session -t {session_name} -r"
            await new_session.async_send_text(attach_cmd + "\n")

            # Set the pane title and prevent tmux from overriding it
            await new_session.async_set_name(session_name)
            profile = await new_session.async_get_profile()
            await profile.async_set_allow_title_setting(False)

            # Apply font size if configured
            if self.config.font_size:
                await profile.async_set_normal_font_size(self.config.font_size)

            self._pane_map[session_name] = new_session.session_id
            log.info("Spawned pane for %s (id: %s)", session_name, new_session.session_id)

        except Exception:
            log.exception("Failed to spawn pane for %s", session_name)

    async def _close_pane(self, session_name: str):
        """Close the iTerm2 pane for a completed polecat session."""
        session_id = self._pane_map.pop(session_name, None)
        if not session_id:
            log.debug("No pane to close for %s", session_name)
            return

        try:
            app = await iterm2.async_get_app(self.connection)
            session = app.get_session_by_id(session_id)
            if session:
                await session.async_close(force=True)
                log.info("Closed pane for %s", session_name)
            else:
                log.debug("Pane already gone for %s (id: %s)", session_name, session_id)
        except Exception:
            log.exception("Failed to close pane for %s", session_name)

    def stop(self):
        """Stop the dashboard."""
        self.watcher.stop()


def run_dashboard(config: Config):
    """Main entry point: connect to iTerm2 and run the dashboard."""
    log.info("Connecting to iTerm2...")

    async def _main(connection: iterm2.Connection):
        dashboard = Dashboard(config, connection)
        try:
            await dashboard.start()
        except asyncio.CancelledError:
            dashboard.stop()
            log.info("Dashboard stopped.")
        except KeyboardInterrupt:
            dashboard.stop()
            log.info("Dashboard stopped by user.")

    iterm2.run_until_complete(_main)
