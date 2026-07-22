# -*- coding: utf-8 -*-
"""二维码展示组件（SPEC §5.2 qrcode_view）。

基于 ``qrcode`` 库生成模块矩阵并自绘（白底黑块保证可扫描），
支持容错级别参数；卡片边框取主题令牌。
"""

import qrcode
from qrcode.constants import (
    ERROR_CORRECT_H,
    ERROR_CORRECT_L,
    ERROR_CORRECT_M,
    ERROR_CORRECT_Q,
)

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from InstructionX_UIKit.theme import T, ThemeManager

__all__ = ["QRCodeView"]

_LEVELS = {
    "L": ERROR_CORRECT_L,  # 约 7%
    "M": ERROR_CORRECT_M,  # 约 15%
    "Q": ERROR_CORRECT_Q,  # 约 25%
    "H": ERROR_CORRECT_H,  # 约 30%
}

_PADDING = 12  # 卡片内边距（px）


class QRCodeView(QWidget):
    """二维码卡片。

    参数:
        text: 编码内容（URL / 文本）。
        size: 二维码区域边长（px，不含内边距），默认 128。
        error_correction: 容错级别 ``"L"`` / ``"M"`` / ``"Q"`` / ``"H"``。
        parent: 父控件。

    示例::

        qr = QRCodeView("https://example.com", size=160)
        qr.set_error_correction("H")
        pm = qr.to_pixmap()           # 导出图片
    """

    def __init__(self, text: str = "", size: int = 128,
                 error_correction: str = "M", parent=None):
        super().__init__(parent)
        self._text = ""
        self._ec = "M"
        self._qr_size = 128
        self._matrix = None
        self.set_error_correction(error_correction)
        self.set_qr_size(size)
        self.set_text(text)
        ThemeManager.instance().theme_changed.connect(self.update)

    # ------------------------------------------------------------------ 配置
    def set_text(self, text: str) -> None:
        """设置编码内容并重新生成。"""
        self._text = text or ""
        self._regen()

    def text(self) -> str:
        return self._text

    def set_error_correction(self, level: str) -> None:
        """设置容错级别：L / M / Q / H。"""
        level = str(level).upper()
        if level not in _LEVELS:
            raise ValueError(f"未知容错级别: {level!r}，应为 L/M/Q/H 之一")
        self._ec = level
        if hasattr(self, "_matrix"):
            self._regen()

    def error_correction(self) -> str:
        return self._ec

    def set_qr_size(self, size: int) -> None:
        """设置二维码区域边长（px）。"""
        self._qr_size = max(48, int(size))
        side = self._qr_size + _PADDING * 2
        self.setFixedSize(side, side)
        self.update()

    def qr_size(self) -> int:
        return self._qr_size

    # ------------------------------------------------------------------ 生成
    def _regen(self) -> None:
        if not self._text:
            self._matrix = None
            self.update()
            return
        qr = qrcode.QRCode(
            version=None,
            error_correction=_LEVELS[self._ec],
            box_size=1,
            border=2,
        )
        qr.add_data(self._text)
        qr.make(fit=True)
        self._matrix = qr.get_matrix()
        self.update()

    def to_pixmap(self) -> QPixmap:
        """把当前二维码渲染为 QPixmap（便于保存 / 复制）。"""
        pm = QPixmap(self.size())
        pm.fill(Qt.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.Antialiasing)
        self._paint(painter)
        painter.end()
        return pm

    # ------------------------------------------------------------------ 绘制
    def _paint(self, painter: QPainter) -> None:
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        # 白底卡片（任何主题下保持可扫描对比度）
        painter.setPen(QPen(QColor(T("color.border"))))
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawRoundedRect(rect, T("radius.md"), T("radius.md"))

        if not self._matrix:
            painter.setPen(QColor(T("color.text.tertiary")))
            font = painter.font()
            font.setPixelSize(T("font.xs"))
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignCenter, "未设置内容")
            return

        n = len(self._matrix)
        area = self._qr_size
        cell = area / n
        ox = (self.width() - area) / 2
        oy = (self.height() - area) / 2
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#111111"))
        for r, row in enumerate(self._matrix):
            for c, filled in enumerate(row):
                if filled:
                    painter.drawRect(
                        QRectF(ox + c * cell, oy + r * cell, cell + 0.2, cell + 0.2)
                    )

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        self._paint(painter)
        painter.end()
