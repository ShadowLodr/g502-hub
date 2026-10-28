import sys

import numpy as np
import pytest

from g502hub import hidpp, keys
from g502hub.effects import macroplayer

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")


def test_every_macro_key_has_a_windows_input():
    from g502hub.effects import winput
    skipped = {224, 225}  # brightness: no virtual key
    for code in macroplayer.device_keys():
        inp = winput.to_input(winput.EV_KEY, code, 1)
        assert (inp is None) == (code in skipped), code


def test_windows_input_values():
    from g502hub.effects import winput
    a = winput.to_input(winput.EV_KEY, keys.HID_TO_EVDEV[keys.KEYS["a"]], 1).u.ki
    assert (a.wScan, a.dwFlags) == (30, winput.KEYEVENTF_SCANCODE)
    up = winput.to_input(winput.EV_KEY, 103, 0).u.ki  # arrow up, released
    assert up.wScan == 0x48 and up.dwFlags & winput.KEYEVENTF_EXTENDEDKEY and up.dwFlags & winput.KEYEVENTF_KEYUP
    wheel = winput.to_input(winput.EV_REL, winput.REL_WHEEL, -1).u.mi
    assert wheel.mouseData == (-120) & 0xFFFFFFFF
    side = winput.to_input(winput.EV_KEY, 0x113, 1).u.mi
    assert (side.dwFlags, side.mouseData) == (0x0080, 1)


def test_bgra_to_rgb():
    from g502hub.effects.winscreen import bgra_to_rgb
    out = bgra_to_rgb(bytes([10, 20, 30, 255, 1, 2, 3, 255]), 2, 1)
    assert out.tolist() == [[[30, 20, 10], [3, 2, 1]]]


def test_screen_capture_runs():
    import time
    from g502hub.effects.winscreen import ScreenCapture
    cap = ScreenCapture(size=(16, 9))
    cap.start()
    try:
        deadline = time.monotonic() + 3
        while cap.frame() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert cap.state == "running" and cap.frame().shape == (9, 16, 3) and cap.frame().dtype == np.uint8
    finally:
        cap.stop()


def test_hidpp_request_always_long_on_windows():
    class Raw:
        sent = []

        def write(self, data):
            self.sent.append(data)
            self.reply = bytes([0x11, 0xFF, data[2], data[3]]) + b"\x05" + b"\0" * 15

        def read(self, timeout):
            reply, self.reply = getattr(self, "reply", None), None
            return reply

    h = hidpp.Hidpp.__new__(hidpp.Hidpp)
    h.index, h.raw, h.events, h._features = 0xFF, Raw(), [], {0: 0}
    assert h.request(3, 1, [1])[0] == 5
    assert h.raw.sent[0][0] == hidpp.LONG and len(h.raw.sent[0]) == 20


def test_foreground_window():
    from g502hub.context import foreground_window
    app, title, pid = foreground_window()
    assert isinstance(app, str) and isinstance(title, str)
