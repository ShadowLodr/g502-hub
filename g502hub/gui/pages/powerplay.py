"""POWERPLAY page: the charging mat's logo light, which it keeps by itself."""

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QLabel, QWidget

from ...onboard import LedEffect
from .. import mat_photo, theme
from ..mouse_view import effect_color
from ..photo import PhotoFetcher
from ..widgets import ChoiceList, ColorPicker, SliderRow, heading, muted
from . import Page
from .lighting import EFFECTS


class MatView(QWidget):
    """Logitech's photo of the mat, its logo lit like the real one."""

    def __init__(self):
        super().__init__()
        self.setMinimumSize(300, 300)
        self.effect = None
        self.message = ""
        image = mat_photo.load_image()
        self.skin = mat_photo.MatSkin(image) if image is not None else None
        self.fetcher = PhotoFetcher(self, mat_photo.download)
        self.fetcher.done.connect(self._fetched)
        self._t0 = time.monotonic()
        self._timer = QTimer(self, interval=33)
        self._timer.timeout.connect(self.update)

    def showEvent(self, e):
        # Only fetch once someone with a mat opens the page
        if self.skin is None and not self.fetcher.busy:
            self.fetch_photo()
        super().showEvent(e)

    def fetch_photo(self):
        self.message = "Getting the picture of the POWERPLAY from logitechg.com…"
        self.update()
        self.fetcher.start()

    def _fetched(self, error):
        image = None if error else mat_photo.load_image()
        if image is None:
            self.message = (f"Couldn't download the picture of the mat ({error or 'damaged file'}). "
                            "Click here to try again.")
        else:
            self.skin = mat_photo.MatSkin(image)
        self.update()

    def mousePressEvent(self, e):
        if self.skin is None and not self.fetcher.busy:
            self.fetch_photo()

    def set_effect(self, effect):
        self.effect = effect
        if effect is not None and effect.effect in (0x03, 0x0A):
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if self.skin is None:
            p.setPen(QColor(theme.MUTED))
            p.setFont(theme.font(15))
            p.drawText(self.rect().adjusted(40, 0, -40, 0),
                       Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.message)
            return
        w, h = mat_photo.PHOTO_SIZE
        scale = min(self.width() * 0.8 / w, self.height() * 0.85 / h)
        p.translate((self.width() - w * scale) / 2, (self.height() - h * scale) / 2)
        p.scale(scale, scale)
        self.skin.paint(p, effect_color(self.effect, time.monotonic() - self._t0))


class PowerplayPage(Page):
    title = "POWERPLAY"
    icon = "powerplay"

    def __init__(self, state, view, keylabels):
        super().__init__(state, view, keylabels)
        self.mat = MatView()
        self.center = self.mat
        title = QLabel("POWERPLAY")
        title.setObjectName("Title")
        self.layout.addWidget(title)
        self.layout.addWidget(muted("The light on the mat's logo. The mat keeps it by itself, so it "
                                    "works without this app and with the mouse off.", "Faint"))

        self.layout.addWidget(heading("Effect"))
        self.effects = ChoiceList(EFFECTS, columns=2)
        self.effects.changed.connect(lambda _: self._apply(final=True))
        self.layout.addWidget(self.effects)

        self.color_heading = heading("Color")
        self.layout.addWidget(self.color_heading)
        self.picker = ColorPicker()
        self.picker.changed.connect(lambda _, final: self._apply(final))
        self.layout.addWidget(self.picker)

        self.rate = SliderRow("Rate", 1000, 20000, "{:,} ms", step=100)
        self.rate.moved.connect(lambda _: self._apply(final=False))
        self.rate.committed.connect(lambda _: self._apply(final=True))
        self.layout.addWidget(self.rate)
        self.brightness = SliderRow("Brightness", 1, 100, "{} %")
        self.brightness.moved.connect(lambda _: self._apply(final=False))
        self.brightness.committed.connect(lambda _: self._apply(final=True))
        self.layout.addWidget(self.brightness)
        self.layout.addStretch()

    def _effect(self):
        effect = self.effects.value() if self.effects.value() is not None else 0x01
        c = self.picker.color()
        rgb = (c.red(), c.green(), c.blue())
        if effect == 0x01:
            return LedEffect.fixed(rgb)
        if effect == 0x0A:
            return LedEffect.breathing(rgb, self.rate.slider.value(), self.brightness.slider.value())
        if effect == 0x03:
            return LedEffect.cycle(self.rate.slider.value(), self.brightness.slider.value())
        return LedEffect.off()

    def _apply(self, final):
        if self.state.mat_led is None:
            return
        effect = self._effect()
        self._show_controls(effect.effect)
        self.mat.set_effect(effect)
        self.state.set_mat_led(effect, final)

    def _show_controls(self, effect):
        has_color = effect in (0x01, 0x0A)
        self.color_heading.setVisible(has_color)
        self.picker.setVisible(has_color)
        self.rate.setVisible(effect in (0x0A, 0x03))
        self.brightness.setVisible(effect in (0x0A, 0x03))

    def refresh(self):
        led = self.state.mat_led
        if led is None:
            return
        self.mat.set_effect(led)
        self.effects.set_value(led.effect if led.effect in dict(EFFECTS) else None)
        if led.effect in (0x01, 0x0A):
            self.picker.set_color(QColor(*led.color))
        if led.effect in (0x0A, 0x03):
            self.rate.set_value(led.period_ms)
            self.brightness.set_value(led.brightness)
        else:
            self.rate.set_value(8000)
            self.brightness.set_value(100)
        self._show_controls(led.effect)
