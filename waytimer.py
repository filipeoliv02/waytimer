#!/usr/bin/env python3
"""
Simple activity timer with fuzzel menu integration and waybar support.
Tracks time spent on different activities.
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    import fcntl
except ImportError:  # e.g. platforms without POSIX file locking
    fcntl = None

DATA_DIR = Path.home() / ".local" / "share" / "waytimer"
DATA_FILE = DATA_DIR / "activities.json"


class ActivityTimer:
    """Manages activity timing and persistence."""

    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = Path(data_dir) if data_dir is not None else DATA_DIR
        self.data_file = self.data_dir / "activities.json"
        self._thread_lock = threading.RLock()
        self._lock_depth = 0
        self.ensure_data_dir()
        self.current_activity = self._load_current()
        self.activities = self._load_activities()

    def ensure_data_dir(self):
        """Create data directory if it doesn't exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def _backup_corrupt_json(self, path: Path):
        """Rename a corrupt JSON file without losing its contents."""
        if not path.exists():
            return
        timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        backup = path.with_name(f"{path.name}.corrupt-{timestamp}-{os.getpid()}.bak")
        path.replace(backup)

    def _load_json(self, path: Path, default):
        """Load JSON, backing up and replacing corrupt files."""
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            self._backup_corrupt_json(path)
            return default

    def _atomic_write(self, path: Path, data):
        """Atomically write JSON with fsync and a same-directory temp file."""
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as temp_file:
                json.dump(data, temp_file, indent=2)
                temp_file.flush()
                os.fsync(temp_file.fileno())
            os.replace(temp_name, path)
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except Exception:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise

    def _lock(self):
        """Return an advisory lock context manager for the data directory."""
        from contextlib import contextmanager

        @contextmanager
        def locked():
            with self._thread_lock:
                nested = self._lock_depth > 0
                lock_file = None
                if not nested:
                    lock_file = open(self.data_dir / ".waytimer.lock", "a+", encoding="utf-8")
                    if fcntl is not None:
                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                self._lock_depth += 1
                try:
                    yield
                finally:
                    self._lock_depth -= 1
                    if lock_file is not None:
                        if fcntl is not None:
                            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                        lock_file.close()

        return locked()

    def _load_current(self) -> Optional[dict]:
        """Load the currently running timer under the data lock."""
        with self._lock():
            return self._load_json(self.data_dir / "current.json", None)

    def _save_current(self, activity: Optional[dict]):
        """Save the currently running timer atomically under the data lock."""
        current_file = self.data_dir / "current.json"
        with self._lock():
            if activity is None:
                current_file.unlink(missing_ok=True)
            else:
                self._atomic_write(current_file, activity)

    def _load_activities(self) -> dict:
        """Load all activities under the data lock."""
        with self._lock():
            return self._load_json(self.data_file, {})

    def _save_activities(self):
        """Save all activities atomically under the data lock."""
        with self._lock():
            self._atomic_write(self.data_file, self.activities)

    def create_activity(self, name: str):
        """Create a new activity and start the timer."""
        with self._lock():
            self.activities = self._load_json(self.data_file, {})
            self.current_activity = self._load_json(self.data_dir / "current.json", None)
            return self._create_activity_locked(name)

    def _create_activity_locked(self, name: str):
        if name in self.activities:
            return False

        now_wall = time.time()
        now_mono = time.monotonic()
        self.current_activity = {
            "name": name,
            "started_at": now_wall,
            "started_monotonic": now_mono,
            "elapsed_before_pause": 0.0,
            "paused_at": None,
            "paused_monotonic": None,
        }
        self._save_current(self.current_activity)

        # Initialize activity in storage
        if name not in self.activities:
            self.activities[name] = {
                "name": name,
                "total_time": 0,
                "sessions": [],
            }
            self._save_activities()

        return True

    def pause_activity(self):
        """Pause the current activity."""
        with self._lock():
            self.current_activity = self._load_json(self.data_dir / "current.json", None)
            return self._pause_activity_locked()

    def _pause_activity_locked(self):
        if not self.current_activity:
            return False

        if self.current_activity.get("paused_at") is not None:
            # Resume: accumulate only active monotonic time.
            pause_mono = self.current_activity.get("paused_monotonic")
            started_mono = self.current_activity.get("started_monotonic")
            accumulated = self.current_activity.get("elapsed_before_pause", 0.0)
            if pause_mono is not None and started_mono is not None:
                accumulated += max(0.0, pause_mono - started_mono)
            self.current_activity["elapsed_before_pause"] = accumulated
            self.current_activity["started_monotonic"] = time.monotonic()
            self.current_activity["paused_at"] = None
            self.current_activity["paused_monotonic"] = None
        else:
            # Pause
            self.current_activity["paused_at"] = time.time()
            self.current_activity["paused_monotonic"] = time.monotonic()

        self._save_current(self.current_activity)
        return True

    def stop_activity(self):
        """Stop the current activity and save the time."""
        with self._lock():
            self.current_activity = self._load_json(self.data_dir / "current.json", None)
            self.activities = self._load_json(self.data_file, {})
            return self._stop_activity_locked()

    def _stop_activity_locked(self):
        if not self.current_activity:
            return False

        name = self.current_activity["name"]
        elapsed = self._get_elapsed_time(self.current_activity)

        if name not in self.activities:
            self.activities[name] = {"name": name, "total_time": 0, "sessions": []}

        session = {
            "started_at": self.current_activity["started_at"],
            "ended_at": time.time(),
            "duration": elapsed,
        }

        self.activities[name]["total_time"] += elapsed
        self.activities[name]["sessions"].append(session)
        self._save_activities()

        self.current_activity = None
        self._save_current(None)

        return True

    def _get_elapsed_time(self, activity: dict) -> float:
        """Calculate active elapsed time using monotonic time when available."""
        accumulated = activity.get("elapsed_before_pause", 0.0)
        started_mono = activity.get("started_monotonic")

        if started_mono is not None:
            if activity.get("paused_at") is not None:
                paused_mono = activity.get("paused_monotonic")
                end_mono = paused_mono if paused_mono is not None else time.monotonic()
            else:
                end_mono = time.monotonic()
            return max(0.0, accumulated + max(0.0, end_mono - started_mono))

        # Compatibility for state files created before monotonic tracking.
        start = activity["started_at"]
        end = activity.get("paused_at") or time.time()
        return max(0.0, end - start)

    def _format_time(self, seconds: float) -> str:
        """Format seconds to HH:MM:SS."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    def get_current_time_str(self) -> str:
        """Get formatted time for current activity (total + current session)."""
        if not self.current_activity:
            return "00:00:00"
        
        name = self.current_activity["name"]
        # Get total time from all previous sessions
        total_previous = 0
        if name in self.activities:
            total_previous = self.activities[name].get("total_time", 0)
        
        # Get elapsed time in current session
        current_elapsed = self._get_elapsed_time(self.current_activity)
        
        # Total = previous sessions + current session
        total_time = total_previous + current_elapsed
        return self._format_time(total_time)

    def get_current_activity_name(self) -> str:
        """Get name of current activity."""
        return self.current_activity["name"] if self.current_activity else ""

    def get_summary(self) -> str:
        """Get summary of all activities."""
        if not self.activities:
            return "No activities yet"

        lines = ["Activity Summary:"]
        for name, data in sorted(self.activities.items()):
            total = data["total_time"]
            lines.append(f"  {name}: {self._format_time(total)}")
        return "\n".join(lines)

    def list_activities(self) -> list:
        """List all activities for selection."""
        return sorted(self.activities.keys())

    def resume_activity(self, name: str) -> bool:
        """Resume a previously stopped activity."""
        with self._lock():
            self.activities = self._load_json(self.data_file, {})
            self.current_activity = self._load_json(self.data_dir / "current.json", None)
            return self._resume_activity_locked(name)

    def _resume_activity_locked(self, name: str) -> bool:
        if name not in self.activities:
            return False

        if self.current_activity:
            return False

        # Start a new session for this activity
        now_wall = time.time()
        now_mono = time.monotonic()
        self.current_activity = {
            "name": name,
            "started_at": now_wall,
            "started_monotonic": now_mono,
            "elapsed_before_pause": 0.0,
            "paused_at": None,
            "paused_monotonic": None,
        }
        self._save_current(self.current_activity)
        return True

    def delete_activity(self, name: str) -> bool:
        """Delete an activity and its history."""
        with self._lock():
            self.activities = self._load_json(self.data_file, {})
            return self._delete_activity_locked(name)

    def _delete_activity_locked(self, name: str) -> bool:
        if name not in self.activities:
            return False

        del self.activities[name]
        self._save_activities()
        return True


def show_fuzzel_menu(options: list, prompt: str = "Select:") -> Optional[str]:
    """Show a fuzzel menu and return the selected option."""
    try:
        result = subprocess.run(
            ["fuzzel", "-d", "-p", prompt],
            input="\n".join(options).encode(),
            capture_output=True,
            timeout=10,
        )
        if result.returncode == 0:
            selected = result.stdout.decode().strip()
            return selected if selected else None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return None


def main_menu():
    """Main menu for the timer app."""
    timer = ActivityTimer()

    options = []
    
    # Show active timer info if running
    if timer.current_activity:
        options.append("Pause / Resume")
        options.append("Stop and save")
    else:
        # No active timer - show all activities directly with times
        past_activities = timer.list_activities()
        if past_activities:
            # Build options with time values, favorites first with bullet
            def sort_key(name):
                return (0 if timer.activities[name].get("favorite") else 1, name)
            for activity_name in sorted(past_activities, key=sort_key):
                total_time = timer.activities[activity_name].get("total_time", 0)
                time_str = timer._format_time(total_time)
                prefix = "• " if timer.activities[activity_name].get("favorite") else ""
                options.append(f"{prefix}{activity_name} ({time_str})")

    prompt = "Create or select activity:"
    if timer.current_activity:
        prompt = f"{timer.get_current_activity_name()} ({timer.get_current_time_str()})"
    selected = show_fuzzel_menu(options, prompt)

    if not selected:
        return

    if selected.startswith("Active:"):
        # Show active timer info (no action)
        pass
    elif selected.startswith("Pause"):
        timer.pause_activity()
    elif selected.startswith("Stop"):
        timer.stop_activity()
    else:
        # Selected an activity - extract name from "• activity_name (HH:MM:SS)" or "activity_name (HH:MM:SS)" or new name
        activity_part = selected
        if activity_part.startswith("• "):
            activity_part = activity_part[2:]
        if "(" in activity_part:
            # Existing activity with time format
            activity_part = activity_part.rsplit(" (", 1)[0]
        
        # Check if it's an existing activity or a new one
        if activity_part in timer.activities:
            # Show submenu for existing activity
            options = ["Resume", "Delete", "Rename", "Toggle Favorite"]
            action = show_fuzzel_menu(options, f"Action for '{activity_part}'")
            if action == "Resume":
                timer.resume_activity(activity_part)
            elif action == "Delete":
                timer.delete_activity(activity_part)
            elif action == "Rename":
                new_name = show_fuzzel_menu([], f"New name for '{activity_part}':")
                if new_name and new_name != activity_part and new_name not in timer.activities:
                    timer.activities[new_name] = timer.activities[activity_part]
                    del timer.activities[activity_part]
                    timer._save_activities()
            elif action == "Toggle Favorite":
                if "favorite" not in timer.activities[activity_part]:
                    timer.activities[activity_part]["favorite"] = False
                timer.activities[activity_part]["favorite"] = not timer.activities[activity_part]["favorite"]
                timer._save_activities()
        else:
            timer.create_activity(activity_part)


def waybar_output():
    """Output status for waybar integration."""
    timer = ActivityTimer()

    if timer.current_activity:
        name = timer.get_current_activity_name()
        current_time = timer.get_current_time_str()
        is_paused = timer.current_activity.get("paused_at") is not None

        output = f"{name}: {current_time}"

        # JSON output for waybar
        print(
            json.dumps(
                {
                    "text": output,
                    "class": "paused" if is_paused else "running",
                    "tooltip": f"{output}\nClick: pause/resume\nMiddle click: stop",
                }
            )
        )
    else:
        print(json.dumps({"text": "", "class": "inactive"}))


def waybar_click_handler(button: int):
    """Handle waybar clicks."""
    timer = ActivityTimer()

    if button == 1:
        timer.pause_activity()
    elif button == 2:
        timer.stop_activity()


def main():
    if len(sys.argv) > 1:
        if sys.argv[1] == "waybar":
            waybar_output()
        elif sys.argv[1] == "waybar-click":
            button = int(sys.argv[2]) if len(sys.argv) > 2 else 1
            waybar_click_handler(button)
        elif sys.argv[1] == "summary":
            timer = ActivityTimer()
            print(timer.get_summary())
    else:
        main_menu()

if __name__ == "__main__":
    main()
