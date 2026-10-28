"""Windows screen sampler: GDI StretchBlt of the primary monitor down to a tiny RGB frame.

Same interface as screen.ScreenCapture, without the portal: Windows needs no permission prompt.
"""

import ctypes
import threading
from ctypes import wintypes

import numpy as np

SRCCOPY, HALFTONE, CAPTUREBLT = 0x00CC0020, 4, 0x40000000
SM_CXSCREEN, SM_CYSCREEN = 0, 1


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD),
                ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


def bgra_to_rgb(data, width, height):
    """A top-down BGRA buffer as an (h, w, 3) RGB array."""
    return np.frombuffer(data, dtype=np.uint8).reshape(height, width, 4)[:, :, 2::-1].copy()


class ScreenCapture:
    """A downscaled live view of the primary monitor. Safe to poll from any thread; never raises."""

    def __init__(self, restore_token=None, size=(64, 36), fps=30):
        self.restore_token = None  # nothing to restore: no portal on Windows
        self.size, self.fps = size, fps
        self.state = "idle"
        self.error = None
        self.source_size = None
        self._frame = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread is not None:
            return
        self.state, self.error = "starting", None
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="g502hub-screen")
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        if self.state in ("starting", "running"):
            self.state = "idle"

    def frame(self):
        with self._lock:
            return self._frame

    def _run(self):
        user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
        gdi32.SelectObject.restype = gdi32.CreateCompatibleBitmap.restype = wintypes.HANDLE
        gdi32.CreateCompatibleDC.restype = user32.GetDC.restype = wintypes.HANDLE
        gdi32.SelectObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        gdi32.DeleteObject.argtypes = gdi32.DeleteDC.argtypes = (wintypes.HANDLE,)
        gdi32.SetStretchBltMode.argtypes = (wintypes.HANDLE, ctypes.c_int)
        gdi32.CreateCompatibleBitmap.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_int)
        gdi32.CreateCompatibleDC.argtypes = (wintypes.HANDLE,)
        user32.ReleaseDC.argtypes = (wintypes.HWND, wintypes.HANDLE)
        gdi32.StretchBlt.argtypes = (wintypes.HANDLE,) + (ctypes.c_int,) * 4 + (wintypes.HANDLE,) + \
            (ctypes.c_int,) * 4 + (wintypes.DWORD,)
        gdi32.GetDIBits.argtypes = (wintypes.HANDLE, wintypes.HANDLE, wintypes.UINT, wintypes.UINT,
                                    ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT)
        w, h = self.size
        screen = user32.GetDC(None)
        mem = gdi32.CreateCompatibleDC(screen)
        bmp = gdi32.CreateCompatibleBitmap(screen, w, h)
        old = gdi32.SelectObject(mem, bmp)
        gdi32.SetStretchBltMode(mem, HALFTONE)
        info = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0)  # negative: top-down
        buf = ctypes.create_string_buffer(w * h * 4)
        try:
            while not self._stop.is_set():
                sw, sh = user32.GetSystemMetrics(SM_CXSCREEN), user32.GetSystemMetrics(SM_CYSCREEN)
                ok = gdi32.StretchBlt(mem, 0, 0, w, h, screen, 0, 0, sw, sh, SRCCOPY | CAPTUREBLT) and \
                    gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(info), 0) == h
                if ok:
                    with self._lock:
                        self._frame = bgra_to_rgb(buf.raw, w, h)
                    self.source_size = (sw, sh)
                    self.state = "running"
                # a failed grab (secure desktop, lock screen) just skips a frame
                self._stop.wait(1 / self.fps)
        except Exception as e:  # never let the thread die silently
            self.state, self.error = "error", str(e) or type(e).__name__
        finally:
            gdi32.SelectObject(mem, old)
            gdi32.DeleteObject(bmp)
            gdi32.DeleteDC(mem)
            user32.ReleaseDC(None, screen)
