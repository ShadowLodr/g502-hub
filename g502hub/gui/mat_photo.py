"""Logitech's product photo of the POWERPLAY mat, with its logo light on it.

Like the mouse photo (photo.py), it isn't part of G502 Hub: it is downloaded
once from logitechg.com, the first time the POWERPLAY page is shown.
"""

import os
from pathlib import Path

from PySide6.QtCore import QPointF, QRect

from . import photo

PHOTO_PATH = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "g502-hub" / "powerplay.png"
PHOTO_URL = ("https://resource.logitechg.com/f_png,q_auto/content/dam/gaming/en/non-braid/"
             "crush-powerplay/powerplay-gallery-2-nb.png")
# The mat from above inside Logitech's 1384x1038 picture, cable cut at the top
PHOTO_CROP = (234, 0, 921, 952)
PHOTO_SIZE = (921, 952)
# The lit G on the receiver module, in the cropped photo
LOGO = (QRect(150, 114, 48, 50), QPointF(172, 140), 70)


def download():
    return photo.fetch(PHOTO_URL, (1384, 1038), PHOTO_CROP, PHOTO_SIZE, PHOTO_PATH)


def load_image():
    return photo.load(PHOTO_PATH, PHOTO_SIZE)


class MatSkin:
    def __init__(self, image):
        self.base, masks = photo.split_lights(image, {0: LOGO})
        self.mask = masks[0]

    def paint(self, p, color):
        """The photo with its logo off, or lit in `color`."""
        p.drawImage(0, 0, self.base)
        if color is not None and color.value() > 6:
            photo.paint_light(p, LOGO, self.mask, color)
