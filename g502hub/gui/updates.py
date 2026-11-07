"""Checking the fork on GitHub for new commits, and pulling them into this copy.

This fork has no releases: what's new is whatever is on UPDATES_BRANCH of
UPDATES_REPO and not yet in the local checkout. Both the check and the update
go through git, against that URL directly, so they work whatever `origin` the
copy was cloned from (the install script's clone, a checkout of upstream...).
"""

import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal

import g502hub

from .. import about, settings

REPO_URL = f"https://github.com/{about.UPDATES_REPO}"
BRANCH = about.UPDATES_BRANCH
DAY = 24 * 3600
ROOT = Path(g502hub.__file__).resolve().parent.parent
# Where the install script keeps the app: a git clone
SCRIPT_APP = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "g502-hub" / "app"
# No console window flashing up for every git call on Windows
_NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}


@dataclass
class Release:
    """What's waiting on GitHub: the newest commit and how far ahead of this copy it is."""
    version: str  # short hash of the newest commit on the fork
    url: str      # GitHub's comparison of this copy with it
    count: int = 0  # commits this copy doesn't have yet


def _git(root, *args, timeout=60):
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True,
                          text=True, timeout=timeout, **_NO_WINDOW).stdout.strip()


def current_commit(root=ROOT):
    """Short hash of this copy, or None when it isn't a git checkout (or git is missing)."""
    try:
        return _git(root, "rev-parse", "--short", "HEAD", timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None


def fetch_latest(root=ROOT):
    """Fetch the fork's branch and say how far ahead of HEAD it is."""
    _git(root, "fetch", "--quiet", REPO_URL, BRANCH, timeout=120)
    head, newest = _git(root, "rev-parse", "HEAD", "FETCH_HEAD").split()
    count = int(_git(root, "rev-list", "--count", "HEAD..FETCH_HEAD"))
    return Release(newest[:7], f"{REPO_URL}/compare/{head[:12]}...{newest[:12]}", count)


def install_kind(root=ROOT):
    """How this copy got here, which decides how it's updated: "script" (the install script's
    clone), "source" (another checkout) or "package" (pacman, the AUR, pip)."""
    if not (root / "pyproject.toml").exists() or not (root / ".git").exists():
        return "package"
    if root == SCRIPT_APP.resolve():
        return "script"
    return "source"


def update_copy(root=ROOT, kind="source"):
    """Fast-forward this copy to the fork's branch. Refuses (and changes nothing) when the
    copy has commits or edits of its own that git can't fast-forward over."""
    _git(root, "pull", "--ff-only", "--quiet", REPO_URL, BRANCH, timeout=120)
    menu_entry = root / "tools" / "install-desktop.sh"
    if kind == "script" and sys.platform != "win32" and menu_entry.exists():
        subprocess.run(["sh", str(menu_entry)], check=True, capture_output=True, text=True, timeout=60)


def _reason(error):
    if isinstance(error, subprocess.CalledProcessError):
        lines = (error.stderr or "").strip().splitlines()
        return lines[-1] if lines else str(error)  # git's last line says why
    if isinstance(error, FileNotFoundError):
        return "git isn't installed"
    return str(error)


class Updates(QObject):
    """Checks the fork for new commits, and pulls them, on background threads.

    `changed` fires on the UI thread whenever there's something new to show;
    `updated(error)` once an update has finished (error is None if it went through).
    """

    changed = Signal()
    updated = Signal(object)
    _checked = Signal(object, object)
    _installed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.root = ROOT
        self.kind = install_kind()
        self.commit = current_commit() if self.kind != "package" else None
        self.latest = None  # the newest Release, once a check went through
        self.error = None  # why the last check failed
        self.update_error = None
        self.checking = self.updating = self.installed = False
        self._checked.connect(self._check_done, Qt.ConnectionType.QueuedConnection)
        self._installed.connect(self._install_done, Qt.ConnectionType.QueuedConnection)

    @property
    def can_update(self):
        return self.kind != "package"

    @property
    def available(self):
        return self.latest is not None and self.latest.count > 0

    def check_if_due(self):
        prefs = settings.load()
        if (self.can_update and prefs.get("update_check", True)
                and time.time() - prefs.get("update_checked_at", 0) >= DAY):
            self.check()

    def check(self):
        if self.checking or not self.can_update:
            return
        self.checking = True
        self.changed.emit()

        def run():
            try:
                self._checked.emit(fetch_latest(self.root), None)
            except Exception as e:  # offline, git missing, not a checkout
                self._checked.emit(None, e)
        threading.Thread(target=run, daemon=True).start()

    def _check_done(self, release, error):
        self.checking = False
        self.error = _reason(error) if error else None
        if release is not None:
            self.latest = release
            settings.update(update_checked_at=time.time())
        self.changed.emit()

    def install(self):
        if self.updating or not self.can_update:
            return
        self.updating, self.update_error = True, None
        self.changed.emit()

        def run():
            try:
                update_copy(self.root, self.kind)
                self._installed.emit(None)
            except (OSError, subprocess.SubprocessError) as e:
                self._installed.emit(e)
        threading.Thread(target=run, daemon=True).start()

    def _install_done(self, error):
        self.updating = False
        self.installed = error is None
        self.update_error = _reason(error) if error else None
        if self.installed:
            self.commit = current_commit(self.root)
        self.changed.emit()
        self.updated.emit(self.update_error)
