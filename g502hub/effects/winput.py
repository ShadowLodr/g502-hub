"""Windows stand-in for the uinput macro device: turns evdev events into SendInput calls."""

import ctypes
from ctypes import wintypes

EV_KEY, EV_REL = 0x01, 0x02
REL_X, REL_Y, REL_HWHEEL, REL_WHEEL = 0x00, 0x01, 0x06, 0x08

# evdev codes 1-88 are the PC set-1 scancodes; these are the extended (0xE0) ones
EXTENDED_SCAN = {96: 0x1C, 97: 0x1D, 98: 0x35, 99: 0x37, 100: 0x38, 102: 0x47, 103: 0x48,
                 104: 0x49, 105: 0x4B, 106: 0x4D, 107: 0x4F, 108: 0x50, 109: 0x51, 110: 0x52,
                 111: 0x53, 125: 0x5B, 126: 0x5C, 127: 0x5D}
# Keys without a plain scancode go by virtual-key code: pause, F13-F24 and the media keys
VK = {119: 0x13, 164: 0xB3, 163: 0xB0, 165: 0xB1, 166: 0xB2, 113: 0xAD, 115: 0xAF, 114: 0xAE,
      140: 0xB7, 144: 0xB6, 155: 0xB4, 172: 0xAC, 158: 0xA6, 159: 0xA7, 173: 0xA8, 217: 0xAA}
VK.update({170 + n: 0x7C + n - 13 for n in range(13, 25)})
# BTN_LEFT, RIGHT, MIDDLE, SIDE, EXTRA -> (down flag, up flag, mouseData)
BUTTONS = {0x110: (0x0002, 0x0004, 0), 0x111: (0x0008, 0x0010, 0), 0x112: (0x0020, 0x0040, 0),
           0x113: (0x0080, 0x0100, 1), 0x114: (0x0080, 0x0100, 2)}
MOUSEEVENTF_MOVE, MOUSEEVENTF_WHEEL, MOUSEEVENTF_HWHEEL = 0x0001, 0x0800, 0x1000
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_SCANCODE = 0x1, 0x2, 0x8
WHEEL_DELTA = 120


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _U(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("pad", ctypes.c_byte * 32)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def to_input(type_, code, value):
    """The INPUT for one evdev event, or None for events Windows has no equivalent for."""
    inp = INPUT()
    if type_ == EV_KEY and code in BUTTONS:
        down, up, data = BUTTONS[code]
        inp.type = 0
        inp.u.mi = MOUSEINPUT(0, 0, data, down if value else up, 0, 0)
    elif type_ == EV_KEY:
        up = 0 if value else KEYEVENTF_KEYUP
        inp.type = 1
        if code in VK:
            inp.u.ki = KEYBDINPUT(VK[code], 0, up, 0, 0)
        elif code in EXTENDED_SCAN:
            inp.u.ki = KEYBDINPUT(0, EXTENDED_SCAN[code], KEYEVENTF_SCANCODE | KEYEVENTF_EXTENDEDKEY | up, 0, 0)
        elif 1 <= code <= 88:
            inp.u.ki = KEYBDINPUT(0, code, KEYEVENTF_SCANCODE | up, 0, 0)
        else:
            return None  # brightness keys: Windows has no virtual key for them
    elif type_ == EV_REL:
        inp.type = 0
        if code == REL_X:
            inp.u.mi = MOUSEINPUT(value, 0, 0, MOUSEEVENTF_MOVE, 0, 0)
        elif code == REL_Y:
            inp.u.mi = MOUSEINPUT(0, value, 0, MOUSEEVENTF_MOVE, 0, 0)
        elif code in (REL_WHEEL, REL_HWHEEL):
            flag = MOUSEEVENTF_WHEEL if code == REL_WHEEL else MOUSEEVENTF_HWHEEL
            inp.u.mi = MOUSEINPUT(0, 0, (value * WHEEL_DELTA) & 0xFFFFFFFF, flag, 0, 0)
        else:
            return None
    else:
        return None
    return inp


class SendInputBackend:
    """Same interface as macroplayer._UInputBackend."""

    def __init__(self):
        self._send = ctypes.windll.user32.SendInput
        self._send.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)

    def write(self, type_, code, value):
        inp = to_input(type_, code, value)
        if inp is not None and not self._send(1, ctypes.byref(inp), ctypes.sizeof(INPUT)):
            raise OSError("SendInput was blocked (a window running as administrator has focus?)")

    def syn(self):
        pass

    def close(self):
        pass
