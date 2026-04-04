"""Configuration loading for gasman dashboard."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None


DEFAULT_CONFIG_PATH = Path.home() / ".gasman.yaml"

# Session name patterns that are NOT polecats (infrastructure agents)
INFRA_SUFFIXES = {
    "witness", "refinery", "mayor", "boot", "deacon",
}
INFRA_PREFIXES = {
    "hq-", "gt-",
}


@dataclass
class Config:
    """Gasman dashboard configuration."""

    # Tmux socket name glob pattern (e.g., "gt-*")
    tmux_socket_glob: str = "gt-*"
    # Poll interval in seconds for tmux session changes
    poll_interval: float = 2.0
    # Polecat session filter patterns (regex). Empty = match all non-infra.
    polecat_patterns: list[str] = field(default_factory=list)
    # Rig prefixes to watch. Empty = watch all.
    rig_filter: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path | None = None) -> Config:
        """Load config from YAML file, falling back to defaults."""
        path = path or DEFAULT_CONFIG_PATH
        if not path.exists():
            return cls()
        if yaml is None:
            raise ImportError("pyyaml is required to load config files: pip install pyyaml")
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        return cls(
            tmux_socket_glob=data.get("tmux_socket_glob", cls.tmux_socket_glob),
            poll_interval=data.get("poll_interval", cls.poll_interval),
            polecat_patterns=data.get("polecat_patterns", []),
            rig_filter=data.get("rig_filter", []),
        )


def find_tmux_socket(glob_pattern: str = "gt-*") -> str | None:
    """Find the GT tmux socket path matching the glob pattern."""
    uid = os.getuid()
    tmux_dir = Path(f"/tmp/tmux-{uid}")
    if not tmux_dir.exists():
        return None
    for sock in tmux_dir.iterdir():
        if sock.is_socket():
            from fnmatch import fnmatch
            if fnmatch(sock.name, glob_pattern):
                return sock.name
    return None


def is_polecat_session(session_name: str, config: Config) -> bool:
    """Determine if a tmux session name represents a polecat (not infra)."""
    # Check infra prefixes
    for prefix in INFRA_PREFIXES:
        if session_name.startswith(prefix):
            return False

    # Check infra suffixes (e.g., "ga-witness", "ar-refinery")
    parts = session_name.split("-", 1)
    if len(parts) == 2 and parts[1] in INFRA_SUFFIXES:
        return False

    # Check for crew sessions (e.g., "ar-crew-arbycrew")
    if "-crew-" in session_name:
        return False

    # Check for dog sessions (e.g., "hq-dog-alpha")
    if "-dog-" in session_name:
        return False

    # Apply rig filter if configured
    if config.rig_filter:
        if not any(session_name.startswith(r) for r in config.rig_filter):
            return False

    # Apply custom patterns if configured
    if config.polecat_patterns:
        import re
        return any(re.search(p, session_name) for p in config.polecat_patterns)

    # Must have a rig prefix (XX-name format) to be a polecat
    return len(parts) == 2 and len(parts[0]) == 2
