"""Desktop integration: start at login, on-screen popups, and the one-time permission setup."""

import os
import shlex
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, Signal

import g502hub

UDEV_RULE_PATH = "/etc/udev/rules.d/70-g502-hub.rules"
PACKAGED_RULE_PATH = "/usr/lib/udev/rules.d/70-g502-hub.rules"  # where distro packages put it
# Same as udev/70-g502-hub.rules in the repository (a test keeps them identical)
UDEV_RULE = """\
# Give the logged-in user access to the Logitech G502 HERO's HID++ channel,
# so g502-hub can configure the mouse without root.
KERNEL=="hidraw*", SUBSYSTEM=="hidraw", ATTRS{idVendor}=="046d", ATTRS{idProduct}=="c08b", TAG+="uaccess"
# Let it create the virtual keyboard that plays macros run by the app
# (the same rule Steam ships for its controllers).
KERNEL=="uinput", SUBSYSTEM=="misc", TAG+="uaccess", OPTIONS+="static_node=uinput"
"""

CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
AUTOSTART = CONFIG / "autostart" / "g502-hub.desktop"


def launch_command(*args):
    """The command that starts this app, whether installed or run from a checkout."""
    root = Path(g502hub.__file__).resolve().parent.parent
    if sys.platform == "win32":  # pythonw: no console window; no `env`, so put the checkout on sys.path
        exe = Path(sys.executable).with_name("pythonw.exe")
        boot = f"import sys; sys.path.insert(0, {str(root)!r}); from g502hub.gui.app import main; main()"
        return [str(exe if exe.exists() else sys.executable), "-c", boot, *args]
    cmd = [sys.executable, "-m", "g502hub.gui", *args]
    if (root / "pyproject.toml").exists():  # a source checkout, not an installed package
        cmd = ["env", f"PYTHONPATH={root}", *cmd]
    return cmd


# ------------------------------------------------------------ start at login

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def autostart_enabled():
    if sys.platform == "win32":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                winreg.QueryValueEx(key, "G502 Hub")
            return True
        except OSError:
            return False
    return AUTOSTART.exists()


def set_autostart(on):
    if sys.platform == "win32":
        import subprocess
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if on:
                winreg.SetValueEx(key, "G502 Hub", 0, winreg.REG_SZ, subprocess.list2cmdline(launch_command("--tray")))
            else:
                try:
                    winreg.DeleteValue(key, "G502 Hub")
                except FileNotFoundError:
                    pass
        return
    if not on:
        AUTOSTART.unlink(missing_ok=True)
        return
    AUTOSTART.parent.mkdir(parents=True, exist_ok=True)
    exec_line = " ".join(shlex.quote(a) for a in launch_command("--tray"))
    AUTOSTART.write_text(f"""[Desktop Entry]
Type=Application
Name=G502 Hub
Comment=Keeps live lighting and game rules running for the G502 HERO
Exec={exec_line}
Icon=input-mouse
Terminal=false
X-GNOME-Autostart-enabled=true
X-KDE-autostart-after=panel
""")


# ------------------------------------------------------------ on-screen popup

def show_osd(text, icon="input-mouse"):
    """Plasma's own volume-style popup; does nothing elsewhere."""
    if sys.platform == "win32":
        return False
    from PySide6.QtDBus import QDBusConnection, QDBusMessage
    bus = QDBusConnection.sessionBus()
    if not bus.isConnected():
        return False
    msg = QDBusMessage.createMethodCall("org.kde.plasmashell", "/org/kde/osdService",
                                        "org.kde.osdService", "showText")
    msg.setArguments([icon, text])
    return bus.send(msg)


# ------------------------------------------------------------ permissions

def udev_rule_status():
    """"current", "old" (a rule from an earlier version) or "missing"."""
    if sys.platform == "win32":
        return "current"  # Windows lets any user open the mouse; there is no rule to install
    status = "missing"
    for path in (UDEV_RULE_PATH, PACKAGED_RULE_PATH):
        try:
            if Path(path).read_text() == UDEV_RULE:
                return "current"
        except OSError:
            continue
        status = "old"
    return status


class PermissionFix(QObject):
    """Install the udev rule as root through pkexec (one password prompt)."""

    finished = Signal(bool, str)  # ok, message

    def __init__(self, parent=None):
        super().__init__(parent)
        self._proc = None

    def start(self):
        script = (f"cat > {UDEV_RULE_PATH} && chmod 644 {UDEV_RULE_PATH} && udevadm control --reload "
                  "&& udevadm trigger --action=change --subsystem-match=hidraw "
                  "&& udevadm trigger --action=change --sysname-match=uinput")
        self._proc = QProcess(self)
        self._proc.finished.connect(self._done)
        self._proc.errorOccurred.connect(lambda _: self.finished.emit(False, "pkexec isn't available"))
        self._proc.start("pkexec", ["sh", "-c", script])
        self._proc.write(UDEV_RULE.encode())
        self._proc.closeWriteChannel()

    def _done(self, code, _status):
        if code == 0:
            self.finished.emit(True, "Access granted. Replug the mouse if it isn't found in a few seconds.")
        elif code in (126, 127):
            self.finished.emit(False, "The password prompt was cancelled")
        else:
            err = bytes(self._proc.readAllStandardError()).decode(errors="replace").strip()
            self.finished.emit(False, err or f"Setup failed (exit code {code})")


def session_info():
    """Lines for bug reports."""
    from PySide6 import __version__ as pyside_version
    from PySide6.QtCore import qVersion
    try:
        kernel = os.uname().release
    except AttributeError:
        import platform
        kernel = platform.platform()
    return [
        f"G502 Hub {g502hub.__version__}",
        f"Python {sys.version.split()[0]}, Qt {qVersion()}, PySide6 {pyside_version}",
        f"Kernel {kernel}",
        f"Desktop {os.environ.get('XDG_CURRENT_DESKTOP', '?')} ({os.environ.get('XDG_SESSION_TYPE', '?')})",
    ]
