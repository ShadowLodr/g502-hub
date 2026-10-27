"""POWERPLAY page: the charging mat's logo light, which it keeps by itself."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QConicalGradient, QPainter, QRadialGradient
from PySide6.QtWidgets import QLabel, QWidget

from ...onboard import LedEffect
from .. import theme
from ..widgets import ChoiceList, ColorPicker, SliderRow, heading, muted
from . import Page
from .lighting import EFFECTS


class MatView(QWidget):
    """The mat from above, its logo lit like the real one."""

    def __init__(self):
        super().__init__()
        self.effect = None

    def set_effect(self, effect):
        self.effect = effect
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(self.width() * 0.7, self.height() * 0.8)
        mat = QRectF((self.width() - side) / 2, (self.height() - side * 0.85) / 2, side, side * 0.85)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#17191c"))
        p.drawRoundedRect(mat, 18, 18)
        center = QPointF(mat.right() - side * 0.12, mat.top() + side * 0.12)
        radius = side * 0.045
        eff = self.effect
        if eff is not None and eff.effect in (0x01, 0x0A):
            color = QColor(*eff.color)
            glow = QRadialGradient(center, radius * 4)
            glow.setColorAt(0, QColor(color.red(), color.green(), color.blue(), 120))
            glow.setColorAt(1, QColor(0, 0, 0, 0))
            p.setBrush(glow)
            p.drawEllipse(center, radius * 4, radius * 4)
            p.setBrush(color)
        elif eff is not None and eff.effect == 0x03:
            ring = QConicalGradient(center, 0)
            for i, hue in enumerate((0, 60, 120, 180, 240, 300, 0)):
                ring.setColorAt(i / 6, QColor.fromHsv(hue, 255, 255))
            p.setBrush(ring)
        else:
            p.setBrush(QColor("#2a2d31"))
        p.drawEllipse(center, radius, radius)
        p.setPen(QColor(theme.FAINT))
        p.setFont(theme.font(12))
        p.drawText(mat.adjusted(0, 0, 0, -16), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                   "POWERPLAY")


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
