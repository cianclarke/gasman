from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gasman.config import Config
from gasman.tmux_watcher import TmuxWatcher


class TmuxWatcherTests(unittest.IsolatedAsyncioTestCase):
    async def test_watch_emits_existing_sessions_on_startup(self):
        watcher = TmuxWatcher(Config(poll_interval=0.01))
        events: list[tuple[str, str]] = []

        async def callback(event):
            events.append((event.event_type, event.name))
            watcher.stop()

        with patch.object(
            watcher,
            "_get_dashboard_sessions",
            side_effect=[{"hq-mayor", "ga-jasper"}],
        ):
            await watcher.watch(callback)

        self.assertEqual(
            events,
            [("spawn", "ga-jasper"), ("spawn", "hq-mayor")],
        )

    @patch("gasman.tmux_watcher.is_session_active")
    @patch("gasman.tmux_watcher.list_tmux_sessions")
    def test_dashboard_sessions_keep_mayor_but_filter_idle_polecats(
        self,
        list_tmux_sessions,
        is_session_active,
    ):
        watcher = TmuxWatcher(Config())
        watcher._socket_name = "gt-test"

        list_tmux_sessions.return_value = {"hq-mayor", "ga-jasper", "ga-idle"}
        is_session_active.side_effect = lambda socket, session: session == "ga-jasper"

        self.assertEqual(
            watcher._get_dashboard_sessions(),
            {"hq-mayor", "ga-jasper"},
        )


if __name__ == "__main__":
    unittest.main()
