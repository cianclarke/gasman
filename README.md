# gasman

iTerm2 polecat dashboard with auto-spawn panes for Gas Town.

When a polecat session starts in the GT tmux socket, gasman automatically
creates a read-only iTerm2 split pane showing the polecat's streaming output.
When the polecat completes, its pane closes automatically.

## Layout

```
+------------------+------------------+
|                  | polecat: ar-obs  |
|    Mayor /       +------------------+
|    User Term     | polecat: ga-obs  |
|    (left pane)   +------------------+
|                  | polecat: ha-nux  |
+------------------+------------------+
```

The user's terminal stays in the left pane. Polecats tile vertically on the
right. Supports 3-10+ concurrent polecats across all rigs.

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
# Start watching for polecat sessions
gasman start

# Start with custom poll interval
gasman start --poll 1.0

# Check current status (works without iTerm2)
gasman status

# Stop the dashboard
gasman stop
```

## Configuration

Create `~/.gasman.yaml` (all fields optional):

```yaml
# Tmux socket glob pattern (default: "gt-*")
tmux_socket_glob: "gt-*"

# How often to check for session changes (seconds)
poll_interval: 2.0

# Font size for polecat panes
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
3. Uses the iTerm2 Python API to create/destroy split panes
4. Polecat panes attach to tmux in read-only mode (`-r`) so you can't
   accidentally type into them

## Cross-rig support

Gasman watches all sessions on the GT tmux socket, which includes all rigs
(arby, harvesty, gastown, etc.). Use `rig_filter` in config to limit to
specific rigs.
