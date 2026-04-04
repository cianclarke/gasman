# gasman

iTerm2 polecat dashboard for Gas Town.

Runs in the foreground and watches for polecat tmux sessions. When a new polecat
spawns, gasman opens a new iTerm2 tab with a read-only view of the session.
When the polecat finishes, its tab closes automatically. Ctrl+C closes all
polecat tabs and exits.

## Layout

Each polecat gets its own iTerm2 tab, titled with the polecat session name.
The tab where gasman runs shows the watch log. Your mayor/user session lives
in a separate tab.

## Install

```bash
pip install .
```

Or in development mode:

```bash
pip install -e .
```

Requires iTerm2 with the Python API enabled (Preferences > General > Magic >
Enable Python API).

## Usage

```bash
# Start watching (foreground, Ctrl+C to quit)
gasman start

# Start with custom poll interval
gasman start --poll 1.0

# Check current status (works without iTerm2)
gasman status

# Stop a running gasman from another terminal
gasman stop
```

## Configuration

Create `~/.gasman.yaml` (all fields optional):

```yaml
# Tmux socket glob pattern (default: "gt-*")
tmux_socket_glob: "gt-*"

# How often to check for session changes (seconds)
poll_interval: 2.0

# Font size for polecat tabs
font_size: 11

# Only watch specific rigs (empty = all rigs)
rig_filter:
  - "ga-"
  - "ar-"

# Custom regex patterns for polecat detection
polecat_patterns: []
```

## How it works

1. Polls the GT tmux socket (`/tmp/tmux-$UID/gt-*`) for session changes
2. Identifies polecat sessions by excluding infrastructure agents (witness,
   refinery, mayor, etc.)
3. Uses the iTerm2 Python API to create/close tabs
4. Polecat tabs attach to tmux in read-only mode (`-r`)
5. On Ctrl+C, all polecat tabs are closed before exit

## Cross-rig support

Gasman watches all sessions on the GT tmux socket, which includes all rigs.
Use `rig_filter` in config to limit to specific rigs.
