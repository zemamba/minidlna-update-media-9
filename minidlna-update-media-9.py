#!/usr/bin/env python3
"""Maintain a MiniDLNA library: clean covers, generate thumbnails, restart server."""

from __future__ import annotations

import argparse
import http.client
import os
import random
import shutil
import subprocess
import sys
import time
from pathlib import Path

VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".mov"}
PROTECTED_IMAGES = {"folder.jpg", "cover.jpg", "albumart.jpg"}


def env_path(name: str) -> Path | None:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else None


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def parse_args() -> argparse.Namespace:
    home = Path.home()
    parser = argparse.ArgumentParser(description="MiniDLNA media maintenance helper.")
    parser.add_argument("--media-dir", type=Path, default=env_path("MINIDLNA_MEDIA_DIR"))
    parser.add_argument("--conf-file", type=Path, default=env_path("MINIDLNA_CONF_FILE") or (home / ".config/minidlna/minidlna.conf"))
    parser.add_argument("--pid-file", type=Path, default=env_path("MINIDLNA_PID_FILE") or (home / ".minidlna/minidlna.pid"))
    parser.add_argument("--log-dir", type=Path, default=env_path("MINIDLNA_LOG_DIR") or (home / ".minidlna/log"))
    parser.add_argument("--ffmpeg-bin", default=os.environ.get("FFMPEG_BIN") or shutil.which("ffmpeg") or "ffmpeg")
    parser.add_argument("--minidlna-bin", default=os.environ.get("MINIDLNA_BIN") or shutil.which("minidlnad") or "minidlnad")
    parser.add_argument("--http-port", type=int, default=env_int("MINIDLNA_HTTP_PORT", 8200))
    parser.add_argument("--protected-images", nargs="*", default=sorted(PROTECTED_IMAGES))
    parser.add_argument("--extensions", nargs="*", default=sorted(VIDEO_EXTENSIONS))
    parser.add_argument("--thumb-min-sec", type=int, default=env_int("THUMB_MIN_SEC", 180))
    parser.add_argument("--thumb-max-sec", type=int, default=env_int("THUMB_MAX_SEC", 600))
    parser.add_argument("--startup-delay", type=float, default=float(os.environ.get("MINIDLNA_STARTUP_DELAY", 3)))
    parser.add_argument("--stop-delay", type=float, default=float(os.environ.get("MINIDLNA_STOP_DELAY", 2)))
    parser.add_argument("--ready-timeout", type=float, default=float(os.environ.get("MINIDLNA_READY_TIMEOUT", 45)))
    parser.add_argument("--double-restart", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--rescan", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def detect_media_dir() -> Path:
    home = Path.home()
    candidates = [home / "Movies", home / "Videos", home / "Downloads", Path.cwd()]
    for path in candidates:
        if path.exists() and path.is_dir() and any(p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS for p in path.rglob("*")):
            return path
    for path in candidates:
        if path.exists() and path.is_dir():
            return path
    return Path.cwd()


def choose_media_dir(cli_value: Path | None) -> Path:
    if cli_value:
        return cli_value
    detected = detect_media_dir()
    if not sys.stdin.isatty():
        return detected
    answer = input(f"Use detected media directory '{detected}'? [Y/n] ").strip().lower()
    if answer in {"", "y", "yes"}:
        return detected
    custom = input("Enter media directory path: ").strip()
    return Path(custom).expanduser() if custom else detected


class App:
    def __init__(self, args: argparse.Namespace) -> None:
        self.media_dir = choose_media_dir(args.media_dir).expanduser().resolve()
        self.conf_file = args.conf_file.expanduser()
        self.pid_file = args.pid_file.expanduser()
        self.log_dir = args.log_dir.expanduser()
        self.log_file = self.log_dir / "update-media.log"
        self.ffmpeg_bin = args.ffmpeg_bin
        self.minidlna_bin = args.minidlna_bin
        self.http_port = max(1, args.http_port)
        self.extensions = {e.lower() if e.startswith(".") else f".{e.lower()}" for e in args.extensions}
        self.protected_images = {p.lower() for p in args.protected_images}
        self.thumb_min_sec = max(0, args.thumb_min_sec)
        self.thumb_max_sec = max(self.thumb_min_sec, args.thumb_max_sec)
        self.startup_delay = max(0, args.startup_delay)
        self.stop_delay = max(0, args.stop_delay)
        self.ready_timeout = max(1, args.ready_timeout)
        self.double_restart = args.double_restart
        self.rescan = args.rescan
        self.dry_run = args.dry_run
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def log(self, message: str) -> None:
        ts = time.strftime("%Y/%m/%d %H:%M:%S")
        line = f"{ts} {message}"
        print(line)
        with self.log_file.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def run(self, cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
        self.log(f"$ {' '.join(cmd)}")
        if self.dry_run:
            return subprocess.CompletedProcess(cmd, 0)
        return subprocess.run(cmd, **kwargs)

    def popen(self, cmd: list[str]) -> None:
        self.log(f"$ {' '.join(cmd)}")
        if not self.dry_run:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def validate(self) -> None:
        if not self.media_dir.exists():
            raise SystemExit(f"Media directory does not exist: {self.media_dir}")
        if not self.media_dir.is_dir():
            raise SystemExit(f"Media directory is not a directory: {self.media_dir}")
        if not shutil.which(self.ffmpeg_bin) and not Path(self.ffmpeg_bin).exists():
            raise SystemExit(f"ffmpeg not found: {self.ffmpeg_bin}")
        if not shutil.which(self.minidlna_bin) and not Path(self.minidlna_bin).exists():
            raise SystemExit(f"minidlnad not found: {self.minidlna_bin}")
        if not self.conf_file.exists():
            self.log(f"warning: config file not found yet: {self.conf_file}")

    def stop_minidlna(self) -> None:
        self.log("Stopping MiniDLNA processes...")
        self.run(["pkill", "-9", "-x", "minidlnad"], capture_output=True)
        time.sleep(self.stop_delay)
        if self.pid_file.exists():
            try:
                if not self.dry_run:
                    self.pid_file.unlink()
                self.log(f"Removed pid file: {self.pid_file}")
            except OSError as exc:
                self.log(f"warning: failed to remove pid file: {exc}")

    def start_minidlna(self, rescan: bool) -> None:
        cmd = [self.minidlna_bin, "-f", str(self.conf_file)]
        if rescan:
            cmd.insert(1, "-R")
        self.log(f"Starting MiniDLNA ({'rescan' if rescan else 'normal'} mode)...")
        self.popen(cmd)
        time.sleep(self.startup_delay)

    def cleanup_orphaned_covers(self) -> int:
        self.log("Cleaning orphaned cover images...")
        removed = 0
        for path in self.media_dir.rglob("*.jpg"):
            if path.name.lower() in self.protected_images:
                continue
            if any(path.with_suffix(ext).exists() for ext in self.extensions):
                continue
            self.log(f"remove {path}")
            if self.dry_run:
                removed += 1
                continue
            try:
                path.unlink()
                removed += 1
            except OSError as exc:
                self.log(f"warning: failed to remove {path}: {exc}")
        self.log(f"Removed orphaned covers: {removed}")
        return removed

    def generate_new_covers(self) -> int:
        self.log("Generating missing covers...")
        created = 0
        for video in self.iter_videos():
            cover = video.with_suffix(".jpg")
            if cover.exists():
                continue
            seek = time.strftime("%H:%M:%S", time.gmtime(random.randint(self.thumb_min_sec, self.thumb_max_sec)))
            cmd = [
                self.ffmpeg_bin, "-loglevel", "error", "-ss", seek, "-i", str(video),
                "-vframes", "1", "-q:v", "2", "-pix_fmt", "yuvj420p", "-y", str(cover),
            ]
            self.log(f"cover {video.name} at {seek}")
            if self.run(cmd).returncode == 0:
                created += 1
        self.log(f"Created covers: {created}")
        return created

    def iter_videos(self):
        for path in self.media_dir.rglob("*"):
            if path.is_file() and path.suffix.lower() in self.extensions:
                yield path

    def check_status(self) -> bool:
        if self.dry_run:
            self.log("Dry-run: skipping final process check.")
            return True
        return self.run(["pgrep", "-x", "minidlnad"], capture_output=True).returncode == 0

    def wait_until_ready(self) -> bool:
        if self.dry_run:
            self.log("Dry-run: skipping HTTP readiness check.")
            return True
        deadline = time.time() + self.ready_timeout
        while time.time() < deadline:
            if not self.check_status():
                time.sleep(1)
                continue
            try:
                conn = http.client.HTTPConnection("127.0.0.1", self.http_port, timeout=2)
                conn.request("GET", "/rootDesc.xml")
                resp = conn.getresponse()
                resp.read()
                conn.close()
                if resp.status == 200:
                    self.log("MiniDLNA HTTP endpoint is ready.")
                    return True
            except OSError:
                pass
            time.sleep(1)
        return False

    def main(self) -> int:
        self.validate()
        self.log("=== MiniDLNA maintenance started ===")
        self.cleanup_orphaned_covers()
        self.generate_new_covers()
        self.stop_minidlna()
        self.start_minidlna(self.rescan)
        ready = self.wait_until_ready()
        if not ready and self.double_restart:
            self.log("MiniDLNA was not ready in time, performing fallback restart...")
            self.stop_minidlna()
            time.sleep(1)
            self.start_minidlna(False)
            ready = self.wait_until_ready()
        if not ready:
            self.log(f"MiniDLNA failed HTTP readiness check. Check logs under: {self.log_dir}")
            return 1
        if self.check_status():
            self.log("MiniDLNA is running.")
        else:
            self.log(f"MiniDLNA failed to start. Check logs under: {self.log_dir}")
            return 1
        self.log("=== MiniDLNA maintenance finished ===")
        return 0


def main() -> int:
    return App(parse_args()).main()


if __name__ == "__main__":
    sys.exit(main())
