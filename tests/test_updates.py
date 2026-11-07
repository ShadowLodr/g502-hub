"""The update check: versions, how a copy updates, the checker and what Settings shows. No network."""

import subprocess
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication

from g502hub import settings
from g502hub.gui import updates
from g502hub.gui.app import MainWindow
from g502hub.gui.pages.settings import SettingsPage
from g502hub.gui.updates import Release, Updates

REAL_FETCH = updates.fetch_latest  # the tests replace it, so nothing reaches the network


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(settings, "PATH", tmp_path / "settings.json")
    monkeypatch.setattr(updates, "fetch_latest", MagicMock(side_effect=AssertionError("no network in tests")))


def wait_for(predicate):
    deadline = time.monotonic() + 2
    while not predicate() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.005)
    assert predicate()


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


def commit(repo, name):
    (repo / name).write_text(name)
    git(repo, "add", name)
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", name)


@pytest.fixture
def fork(tmp_path, monkeypatch):
    """A stand-in for the fork on GitHub, and a copy cloned from it."""
    upstream = tmp_path / "fork"
    upstream.mkdir()
    git(upstream, "init", "-q", "-b", "main")
    commit(upstream, "pyproject.toml")
    copy = tmp_path / "copy"
    git(tmp_path, "clone", "-q", str(upstream), str(copy))
    monkeypatch.setattr(updates, "REPO_URL", str(upstream))
    monkeypatch.setattr(updates, "BRANCH", "main")
    return upstream, copy


def test_fetch_latest_counts_new_commits_on_the_fork(fork):
    upstream, copy = fork
    assert REAL_FETCH(copy).count == 0
    commit(upstream, "a")
    commit(upstream, "b")
    latest = REAL_FETCH(copy)
    assert latest.count == 2
    assert latest.version == git(upstream, "rev-parse", "--short=7", "HEAD")
    assert latest.url.startswith(f"{updates.REPO_URL}/compare/")
    assert not (copy / "a").exists()  # checking never changes the copy


def test_update_copy_fast_forwards_to_the_fork(fork):
    upstream, copy = fork
    commit(upstream, "a")
    updates.update_copy(copy)
    assert (copy / "a").exists()
    assert git(copy, "rev-parse", "HEAD") == git(upstream, "rev-parse", "HEAD")
    assert REAL_FETCH(copy).count == 0


def test_update_copy_refuses_when_the_copy_went_its_own_way(fork):
    upstream, copy = fork
    commit(upstream, "a")
    commit(copy, "mine")
    with pytest.raises(subprocess.CalledProcessError) as e:
        updates.update_copy(copy)
    assert "fast-forward" in updates._reason(e.value)
    assert not (copy / "a").exists()


def test_a_script_copy_also_rewrites_the_menu_entry(monkeypatch, tmp_path):
    ran = []
    monkeypatch.setattr(updates, "_git", lambda root, *args, **kw: ran.append(["git", *args]))
    monkeypatch.setattr(updates.subprocess, "run", lambda cmd, **kw: ran.append(cmd))
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "install-desktop.sh").touch()
    updates.update_copy(tmp_path, "script")
    assert ran[0] == ["git", "pull", "--ff-only", "--quiet", updates.REPO_URL, updates.BRANCH]
    if updates.sys.platform != "win32":
        assert ran[1] == ["sh", str(tmp_path / "tools" / "install-desktop.sh")]


def test_install_kind(monkeypatch, tmp_path):
    script = tmp_path / "data" / "g502-hub" / "app"
    monkeypatch.setattr(updates, "SCRIPT_APP", script)
    package = tmp_path / "site-packages"
    package.mkdir()
    assert updates.install_kind(package) == "package"
    for root in (script, tmp_path / "checkout"):
        (root / ".git").mkdir(parents=True)
        (root / "pyproject.toml").touch()
    assert updates.install_kind(script) == "script"
    assert updates.install_kind(tmp_path / "checkout") == "source"


def test_missing_git_is_said_plainly():
    assert updates._reason(FileNotFoundError(2, "No such file", "git")) == "git isn't installed"


def test_check_finds_a_newer_release():
    updates.fetch_latest.side_effect = None
    updates.fetch_latest.return_value = Release("abc1234", "https://example.invalid/compare", 3)
    u = Updates()
    u.kind = "source"
    u.check()
    wait_for(lambda: not u.checking)
    assert u.available and u.latest.count == 3 and u.error is None
    assert time.time() - settings.load()["update_checked_at"] < 5


def test_check_reports_why_it_failed():
    updates.fetch_latest.side_effect = subprocess.CalledProcessError(
        128, "git", stderr="fatal: unable to access 'https://github.com/x/': Could not resolve host: github.com\n")
    u = Updates()
    u.kind = "source"
    u.check()
    wait_for(lambda: not u.checking)
    assert not u.available and "Could not resolve host" in u.error
    assert "update_checked_at" not in settings.load()  # try again next time


def test_daily_check_respects_the_setting_and_the_last_check():
    u = Updates()
    u.kind = "source"
    u.check = MagicMock()
    u.check_if_due()
    assert u.check.call_count == 1  # never checked
    settings.update(update_checked_at=time.time() - 3600)
    u.check_if_due()
    assert u.check.call_count == 1  # checked an hour ago
    settings.update(update_checked_at=time.time() - 2 * updates.DAY)
    u.check_if_due()
    assert u.check.call_count == 2
    settings.update(update_check=False)
    u.check_if_due()
    assert u.check.call_count == 2
    settings.update(update_check=True)
    u.kind = "package"  # can't update itself, so there's nothing to check for
    u.check_if_due()
    assert u.check.call_count == 2


def test_install_pulls_unless_installed_as_a_package(monkeypatch):
    copy = MagicMock()
    monkeypatch.setattr(updates, "update_copy", copy)
    monkeypatch.setattr(updates, "current_commit", lambda root=None: "def5678")
    u = Updates()
    u.kind = "package"
    u.install()
    assert not copy.called
    u.kind = "source"
    results = []
    u.updated.connect(results.append)
    u.install()
    wait_for(lambda: not u.updating)
    assert copy.called and u.installed and results == [None] and u.commit == "def5678"
    copy.side_effect = subprocess.CalledProcessError(1, "git", stderr="fatal: Not possible to fast-forward, aborting.\n")
    u.installed = False
    u.install()
    wait_for(lambda: not u.updating)
    assert not u.installed and results[-1] == "fatal: Not possible to fast-forward, aborting."


def page_with(kind, latest=None, installed=False):
    u = Updates()
    u.kind, u.latest, u.installed = kind, latest, installed
    page = SettingsPage(MagicMock(), MagicMock(), MagicMock(), u)
    page._show_updates()
    return page


def test_settings_shows_what_to_do():
    newer = Release("abc1234", "https://example.invalid/compare", 2)
    page = page_with("script")
    assert page.update_btn.text() == "Check now" and page.notes_btn.isHidden()
    page = page_with("source", newer)
    assert page.update_btn.text() == "Update now" and not page.notes_btn.isHidden()
    assert "2 new update(s)" in page.update_status.text()
    page = page_with("package", newer)
    assert not page.update_btn.isEnabled() and "can't update itself" in page.update_status.text()
    page = page_with("script", Release("abc1234", "https://example.invalid/compare", 0))
    assert "up to date" in page.update_status.text() and page.notes_btn.isHidden()
    page = page_with("script", newer, installed=True)
    assert page.update_btn.text() == "Restart now"


def test_a_new_version_is_announced_once():
    u = Updates()
    u.latest = Release("abc1234", "https://example.invalid/compare", 3)
    window = SimpleNamespace(updates=u, tray=MagicMock(), _status=MagicMock(), tr=lambda text: text)
    MainWindow._update_found(window)
    MainWindow._update_found(window)
    assert window.tray.showMessage.call_count == 1
    assert "3 new update(s)" in window._status.call_args.args[1]
