# -*- coding: utf-8 -*-
"""日历组件（SPEC §5.2 calendar）。

中文表头（周一为一周起点）、今日以主色高亮圆角标记；
选中态由全局调色板与 QSS 提供。
"""

from PySide6.QtCore import QDate, QLocale, Qt
from PySide6.QtGui import QColor, QPen
from PySide6.QtWidgets import QCalendarWidget

from InstructionX_UIKit.theme import T, ThemeManager

__all__ = ["Calendar"]


class Calendar(QCalendarWidget):
    """中文日历。

    参数:
        parent: 父控件。

    示例::

        cal = Calendar()
        cal.setSelectedDate(QDate.currentDate())
        cal.clicked.connect(lambda d: print(d.toString("yyyy-MM-dd")))
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setLocale(QLocale(QLocale.Chinese, QLocale.China))
        self.setFirstDayOfWeek(Qt.Monday)
        self.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
        self.setHorizontalHeaderFormat(QCalendarWidget.ShortDayNames)
        self.setGridVisible(False)
        ThemeManager.instance().theme_changed.connect(self.updateCells)

    def paintCell(self, painter, rect, date) -> None:
        """今日未被选中时绘制主色圆角高亮；其余交给默认绘制。"""
        today = QDate.currentDate()
        if date == today and date != self.selectedDate():
            painter.save()
            painter.setRenderHint(painter.RenderHint.Antialiasing)
            inner = rect.adjusted(3, 3, -3, -3)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(T("color.primary.subtle")))
            painter.drawRoundedRect(inner, T("radius.sm"), T("radius.sm"))
            pen = QPen(QColor(T("color.primary")))
            pen.setWidth(1)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(inner, T("radius.sm"), T("radius.sm"))
            font = painter.font()
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor(T("color.primary")))
            painter.drawText(rect, Qt.AlignCenter, str(date.day()))
            painter.restore()
            return
        super().paintCell(painter, rect, date)
