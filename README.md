# minidlna-update-media-library

Portable MiniDLNA maintenance script for local media libraries.

This script removes orphaned cover images, generates missing thumbnails with `ffmpeg`, and restarts `minidlnad` in a controlled way to refresh the media index.

Unlike the earlier local-only variant, this version is safe to publish:

- no hardcoded personal paths
- no hardcoded usernames
- no host-specific binaries
- configuration comes from CLI flags and environment variables
- media directory can be auto-detected interactively

## Features

- recursive scan of a media directory
- orphaned `.jpg` cover cleanup
- missing cover generation for supported video files
- no-op when nothing changed
- graceful MiniDLNA reload first, restart only as fallback
- dry-run mode
- configurable paths through flags and env vars

## Supported Video Extensions

- `.mkv`
- `.mp4`
- `.avi`
- `.mov`

## Protected Cover Names

- `folder.jpg`
- `cover.jpg`
- `albumart.jpg`

## Requirements

- Python 3.9+
- `ffmpeg`
- `minidlnad`
- `pkill`
- `pgrep`

## Configuration

All paths can be set either with flags or environment variables.

### Environment Variables

- `MINIDLNA_MEDIA_DIR`
- `MINIDLNA_CONF_FILE`
- `MINIDLNA_PID_FILE`
- `MINIDLNA_LOG_DIR`
- `FFMPEG_BIN`
- `MINIDLNA_BIN`
- `THUMB_MIN_SEC`
- `THUMB_MAX_SEC`
- `MINIDLNA_STARTUP_DELAY`
- `MINIDLNA_STOP_DELAY`
- `MINIDLNA_READY_TIMEOUT`

### Defaults

- media dir: auto-detected from common local folders such as `~/Movies`, `~/Videos`, `~/Downloads`, then confirmed interactively when possible
- config: `~/.config/minidlna/minidlna.conf`
- pid file: `~/.minidlna/minidlna.pid`
- log dir: `~/.minidlna/log`
- binaries: resolved from `PATH`

## Usage

```bash
python3 minidlna-update-media-9.py --media-dir /path/to/media
```

If `--media-dir` is omitted and `MINIDLNA_MEDIA_DIR` is not set, the script will try to detect a likely media folder and ask for confirmation in interactive mode.

### Dry Run

```bash
python3 minidlna-update-media-9.py --media-dir /path/to/media --dry-run
```

### Example With Environment Variables

```bash
export MINIDLNA_MEDIA_DIR=/srv/media
export MINIDLNA_CONF_FILE=~/.config/minidlna/minidlna.conf
python3 minidlna-update-media-9.py
```

## What The Script Does

1. Validates paths and required binaries.
2. Removes `.jpg` files that no longer match any supported video file.
3. Generates a thumbnail for each video that does not already have a sibling `.jpg`.
4. If nothing changed and MiniDLNA is already running, it leaves the service untouched.
5. If changes were detected, it first tries a graceful `SIGHUP` reload.
6. If reload is not enough, it falls back to a full restart.
7. Waits until the local MiniDLNA HTTP endpoint becomes ready.
8. Optionally performs one extra fallback restart if requested.
9. Verifies that MiniDLNA is running.

## Notes

- This is a utility script for local MiniDLNA setups, not a general package manager.
- Thumbnail capture uses a random timestamp in a configurable range.
- In `--dry-run` mode, commands are logged but not executed.
- The default mode does not force a second restart anymore; fallback restart is optional.
- The default mode also avoids touching MiniDLNA at all when no media changes are detected.

## License

MIT
