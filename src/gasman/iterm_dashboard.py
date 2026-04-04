"""iTerm2 split-pane dashboard for polecat sessions."""

from __future__ import annotations

import asyncio
import logging
import signal

import iterm2

from .config import Config
from .tmux_watcher import SessionEvent, TmuxWatcher

log = logging.getLogger(__name__)


class Dashboard:
    """Manages iTerm2 split panes for polecat sessions.

    Each polecat gets its own vertical split pane with a tmux attach.
    Ctrl+C closes all polecat panes and exits cleanly.
    """

    def __init__(self, config: Config, connection: iterm2.Connection):
        self.config = config
        self.connection = connection
        self.watcher = TmuxWatcher(config)
        # Maps attached session name -> iTerm2 session ID (pane)
        self._pane_map: dict[str, str] = {}
        self._split_base_session: iterm2.Session | None = None

    async def start(self):
        """Start the dashboard: begin watching for polecats."""
        app = await iterm2.async_get_app(self.connection)
        window = app.current_terminal_window
        if not window:
            log.error("No current iTerm2 window found")
            return

        self._window = window
        tab = window.current_tab
        if not tab:
            log.error("No current tab available")
            return

        self._split_base_session = tab.current_session
        if not self._split_base_session:
            log.error("No current session available")
            return

        await self._open_mayor_pane()

        socket = self.watcher.socket_name
        if not socket:
            log.info("Waiting for tmux socket...")

        log.info(
            "Watching for polecats (poll: %.1fs). Ctrl+C to quit.",
            self.config.poll_interval,
        )

        await self.watcher.watch(self._handle_event)

    async def _open_mayor_pane(self):
        """Create the initial Mayor pane in the dashboard layout."""
        if "hq-mayor" in self._pane_map:
            return

        await self._open_pane(
            "hq-mayor",
            command="GASTOWN_DISABLED=1 gt mayor attach",
        )

    async def _handle_event(self, event: SessionEvent):
        """Handle a polecat spawn or exit event."""
        if event.event_type == "spawn":
            await self._open_pane(event.name)
        elif event.event_type == "exit":
            await self._close_pane(event.name)

    async def _open_pane(self, session_name: str, command: str | None = None):
        """Create a new iTerm2 vertical split pane for a dashboard session."""
        if session_name in self._pane_map:
            return

        try:
            base_session = self._split_base_session
            if not base_session:
                log.error("No split base session available")
                return

            # Create a vertical split pane to the right.
            # GASTOWN_DISABLED=1 prevents the shell profile from triggering
            # GT hooks that would launch unwanted agent sessions.
            pane = await base_session.async_split_pane(vertical=True)

            attach_cmd = command or self._tmux_attach_command(session_name)
            await pane.async_send_text(attach_cmd + "\n")

            # Set pane title
            await pane.async_set_name(session_name)

            self._pane_map[session_name] = pane.session_id
            self._split_base_session = pane
            log.info("Attached pane: %s", session_name)

        except Exception:
            log.exception("Failed to open pane for %s", session_name)

    def _tmux_attach_command(self, session_name: str) -> str:
        """Build the tmux attach command for a session pane."""
        socket = self.watcher.socket_name
        if not socket:
            raise RuntimeError(f"Cannot open pane for {session_name}: no tmux socket")

        return (
            f"tmux -L {socket} set-option -t {session_name} "
            f"window-size largest 2>/dev/null; "
            f"GASTOWN_DISABLED=1 tmux -L {socket} "
            f"attach-session -t {session_name}"
        )

    async def _close_pane(self, session_name: str):
        """Close the iTerm2 pane for a finished polecat."""
        session_id = self._pane_map.pop(session_name, None)
        if not session_id:
            return

        try:
            app = await iterm2.async_get_app(self.connection)
            for window in app.terminal_windows:
                for tab in window.tabs:
                    for session in tab.sessions:
                        if session.session_id == session_id:
                            await session.async_close(force=True)
                            log.info("Closed pane: %s", session_name)
                            return
            log.debug("Pane already gone: %s", session_name)
        except Exception:
            log.exception("Failed to close pane for %s", session_name)

    async def close_all_panes(self):
        """Close ALL polecat panes (called on Ctrl+C / shutdown)."""
        if not self._pane_map:
            return

        names = list(self._pane_map.keys())
        log.info("Closing %d polecat pane(s)...", len(names))

        for name in names:
            await self._close_pane(name)

    def stop(self):
        """Signal the watcher to stop."""
        self.watcher.stop()


def run_dashboard(config: Config):
    """Connect to iTerm2 and run the dashboard. Blocks until Ctrl+C."""
    log.info("Connecting to iTerm2...")

    async def _main(connection: iterm2.Connection):
        dashboard = Dashboard(config, connection)

        # Wire up SIGINT to close all panes before exiting
        loop = asyncio.get_running_loop()

        def _on_sigint():
            dashboard.stop()
            # Schedule pane cleanup then stop the loop
            asyncio.ensure_future(_shutdown(dashboard, loop))

        loop.add_signal_handler(signal.SIGINT, _on_sigint)

        try:
            await dashboard.start()
        except asyncio.CancelledError:
            pass

    async def _shutdown(dashboard: Dashboard, loop: asyncio.AbstractEventLoop):
        """Clean up panes and stop the event loop."""
        try:
            await dashboard.close_all_panes()
        except Exception:
            log.exception("Error during pane cleanup")
        finally:
            loop.stop()

    iterm2.run_until_complete(_main)
