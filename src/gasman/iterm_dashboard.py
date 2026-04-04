"""iTerm2 tab management for the polecat dashboard."""

from __future__ import annotations

import asyncio
import logging
import signal

import iterm2

from .config import Config
from .tmux_watcher import SessionEvent, TmuxWatcher

log = logging.getLogger(__name__)


class Dashboard:
    """Manages iTerm2 tabs for polecat sessions.

    Each polecat gets its own tab with a read-only tmux attach.
    Ctrl+C closes all polecat tabs and exits cleanly.
    """

    def __init__(self, config: Config, connection: iterm2.Connection):
        self.config = config
        self.connection = connection
        self.watcher = TmuxWatcher(config)
        # Maps polecat session name -> iTerm2 tab ID
        self._tab_map: dict[str, str] = {}

    async def start(self):
        """Start the dashboard: begin watching for polecats."""
        app = await iterm2.async_get_app(self.connection)
        window = app.current_terminal_window
        if not window:
            log.error("No current iTerm2 window found")
            return

        self._window = window

        socket = self.watcher.socket_name
        if not socket:
            log.info("Waiting for tmux socket...")

        log.info(
            "Watching for polecats (poll: %.1fs). Ctrl+C to quit.",
            self.config.poll_interval,
        )

        await self.watcher.watch(self._handle_event)

    async def _handle_event(self, event: SessionEvent):
        """Handle a polecat spawn or exit event."""
        if event.event_type == "spawn":
            await self._open_tab(event.name)
        elif event.event_type == "exit":
            await self._close_tab(event.name)

    async def _open_tab(self, session_name: str):
        """Create a new iTerm2 tab for a polecat session."""
        if session_name in self._tab_map:
            return

        socket = self.watcher.socket_name
        if not socket:
            log.warning("Cannot open tab for %s: no tmux socket", session_name)
            return

        try:
            app = await iterm2.async_get_app(self.connection)
            window = app.current_terminal_window
            if not window:
                log.error("No iTerm2 window available")
                return

            tab = await window.async_create_tab()
            session = tab.current_session

            # Attach read-only to the polecat's tmux session
            attach_cmd = f"tmux -L {socket} attach-session -t {session_name} -r"
            await session.async_send_text(attach_cmd + "\n")

            # Set tab title and lock it
            await session.async_set_name(session_name)
            profile = await session.async_get_profile()
            await profile.async_set_allow_title_setting(False)

            if self.config.font_size:
                await profile.async_set_normal_font_size(self.config.font_size)

            self._tab_map[session_name] = tab.tab_id
            log.info("New polecat: %s", session_name)

        except Exception:
            log.exception("Failed to open tab for %s", session_name)

    async def _close_tab(self, session_name: str):
        """Close the iTerm2 tab for a finished polecat."""
        tab_id = self._tab_map.pop(session_name, None)
        if not tab_id:
            return

        try:
            app = await iterm2.async_get_app(self.connection)
            for window in app.terminal_windows:
                for tab in window.tabs:
                    if tab.tab_id == tab_id:
                        await tab.async_close(force=True)
                        log.info("Closed tab: %s", session_name)
                        return
            log.debug("Tab already gone: %s", session_name)
        except Exception:
            log.exception("Failed to close tab for %s", session_name)

    async def close_all_tabs(self):
        """Close ALL polecat tabs (called on Ctrl+C / shutdown)."""
        if not self._tab_map:
            return

        names = list(self._tab_map.keys())
        log.info("Closing %d polecat tab(s)...", len(names))

        for name in names:
            await self._close_tab(name)

    def stop(self):
        """Signal the watcher to stop."""
        self.watcher.stop()


def run_dashboard(config: Config):
    """Connect to iTerm2 and run the dashboard. Blocks until Ctrl+C."""
    log.info("Connecting to iTerm2...")

    async def _main(connection: iterm2.Connection):
        dashboard = Dashboard(config, connection)

        # Wire up SIGINT to close all tabs before exiting
        loop = asyncio.get_running_loop()

        def _on_sigint():
            dashboard.stop()
            # Schedule tab cleanup then stop the loop
            asyncio.ensure_future(_shutdown(dashboard, loop))

        loop.add_signal_handler(signal.SIGINT, _on_sigint)

        try:
            await dashboard.start()
        except asyncio.CancelledError:
            pass

    async def _shutdown(dashboard: Dashboard, loop: asyncio.AbstractEventLoop):
        """Clean up tabs and stop the event loop."""
        try:
            await dashboard.close_all_tabs()
        except Exception:
            log.exception("Error during tab cleanup")
        finally:
            loop.stop()

    iterm2.run_until_complete(_main)
