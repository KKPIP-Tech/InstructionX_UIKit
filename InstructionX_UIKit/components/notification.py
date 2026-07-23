# -*- coding: utf-8 -*-
"""通知提醒框 Notification（SPEC §5.3 notification.py）。

管理器 + 单条卡片：以 FramelessWindowHint + Tool 顶层 QWidget 实现，
相对父窗口右上角堆叠弹出，自动消失并淡出，底部带剩余时间进度条。
"""

from PySide6.QtCore import (
    QEasingCurve,
    QElapsedTimer,
    QPoint,
    QPropertyAnimation,
    QRect,
    Qt,
    QTimer,
)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from ..theme import T, ThemeManager
from .alert import _close_icon, _type_icon
from shiboken6 import isValid as _shiboken_is_valid


def _connect_theme(widget, slot) -> None:
    """连接主题切换信号；控件销毁后自动忽略回调。"""
    ThemeManager.instance().theme_changed.connect(
        lambda *_: slot() if _shiboken_is_valid(widget) else None)

__all__ = ["Notification"]

_WIDTH = 320
_PAD = 14
_GAP = 12
_MARGIN = 16
_PROGRESS_H = 3


class Notification(QWidget):
    """通知提醒框（右上角堆叠、自动消失、带进度条）。

    一般通过静态方法弹出，无需直接实例化。

    参数:
        anchor: 相对定位的父窗口控件。
        title: 标题。
        message: 正文（自动换行）。
        type: ``"info"`` / ``"success"`` / ``"warning"`` / ``"error"``。
        duration: 自动关闭时长（毫秒）。

    示例::

        Notification.notify(win, "构建完成", "产物已输出到 dist/", "success")
        Notification.error(win, "构建失败", "请查看日志")
        Notification.close_all()
    """

    #: 合法类型
    TYPES = ("info", "success", "warning", "error")
    #: 当前所有存活通知（管理器状态）
    _active = []

    def __init__(self, anchor: QWidget, title: str, message: str,
                 type: str = "info", duration: int = 4000):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool
                         | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAutoFillBackground(False)
        # 覆盖全局基座 QSS「QWidget { background: bg.base }」，避免通知
        # 窗口整个矩形被涂上不透明底色（暗色下呈黑色方框）；圆角卡体、
        # 内容与进度条只由 paintEvent 自绘，窗口其余区域保持真透明。
        self.setStyleSheet("background: transparent;")
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        if type not in self.TYPES:
            raise ValueError(
                f"未知通知类型: {type!r}，应为 {self.TYPES} 之一")
        self._anchor = anchor
        self._type = type
        self._title = title
        self._message = message
        self._duration = max(0, int(duration))
        self._closing = False
        self._close_hover = False
        self.setMouseTracking(True)

        title_font = QFont(self.font())
        title_font.setPixelSize(T("font.md"))
        title_font.setWeight(QFont.DemiBold)
        self._title_font = title_font
        msg_font = QFont(self.font())
        msg_font.setPixelSize(T("font.sm"))
        self._msg_font = msg_font

        text_w = _WIDTH - _PAD * 2 - 28
        title_h = QFontMetrics(title_font).height()
        msg_h = (QFontMetrics(msg_font).boundingRect(
            QRect(0, 0, text_w, 1000), Qt.TextWordWrap, message).height()
            if message else 0)
        height = _PAD + title_h + (6 + msg_h if msg_h else 0) + _PAD \
            + _PROGRESS_H
        self.setFixedSize(_WIDTH, height)

        self._elapsed = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._tick)

        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(T("duration.normal"))
        self._fade.finished.connect(self._on_fade_finished)
        self._slide = QPropertyAnimation(self, b"pos", self)
        self._slide.setDuration(T("duration.slow"))
        self._slide.setEasingCurve(QEasingCurve.OutCubic)

        _connect_theme(self, self.update)

    # -- 静态管理器 API ---------------------------------------------------
    @staticmethod
    def notify(anchor: QWidget, title: str, message: str,
               type: str = "info", duration: int = 4000) -> "Notification":
        """弹出一条通知并返回实例（非阻塞）。"""
        n = Notification(anchor, title, message, type, duration)
        Notification._active.append(n)
        n._move_to_stack(animate=False, entrance=True)
        n.show()
        n._elapsed.start()
        if n._duration > 0:
            n._timer.start()
        return n

    @staticmethod
    def info(anchor, title, message, duration: int = 4000) -> "Notification":
        """弹出 info 通知。"""
        return Notification.notify(anchor, title, message, "info", duration)

    @staticmethod
    def success(anchor, title, message, duration: int = 4000) -> "Notification":
        """弹出 success 通知。"""
        return Notification.notify(anchor, title, message, "success", duration)

    @staticmethod
    def warning(anchor, title, message, duration: int = 4000) -> "Notification":
        """弹出 warning 通知。"""
        return Notification.notify(anchor, title, message, "warning", duration)

    @staticmethod
    def error(anchor, title, message, duration: int = 4000) -> "Notification":
        """弹出 error 通知。"""
        return Notification.notify(anchor, title, message, "error", duration)

    @staticmethod
    def close_all() -> None:
        """立即关闭所有存活通知。"""
        for n in list(Notification._active):
            n._timer.stop()
            n.close()

    # -- 内部 -------------------------------------------------------------
    def _main_color(self) -> str:
        return {"info": T("color.primary"),
                "success": T("color.success"),
                "warning": T("color.warning"),
                "error": T("color.danger")}[self._type]

    def _siblings(self):
        return [n for n in Notification._active if n._anchor is self._anchor]

    def _target_pos(self) -> QPoint:
        base = self._anchor.mapToGlobal(QPoint(0, 0))
        y = base.y() + _MARGIN
        for n in self._siblings():
            if n is self:
                break
            y += n.height() + _GAP
        x = base.x() + self._anchor.width() - self.width() - _MARGIN
        return QPoint(x, y)

    def _move_to_stack(self, animate: bool, entrance: bool = False) -> None:
        target = self._target_pos()
        if entrance:
            self.move(target + QPoint(36, 0))
            self.setWindowOpacity(0.0)
            self._slide.stop()
            self._slide.setStartValue(self.pos())
            self._slide.setEndValue(target)
            self._slide.start()
            self._fade.stop()
            self._fade.finished.disconnect(self._on_fade_finished)
            self._fade.setStartValue(0.0)
            self._fade.setEndValue(1.0)
            self._fade.start()
            self._fade.finished.connect(self._on_fade_finished)
        elif animate:
            self._slide.stop()
            self._slide.setStartValue(self.pos())
            self._slide.setEndValue(target)
            self._slide.start()
        else:
            self.move(target)

    def _tick(self) -> None:
        if self._elapsed.elapsed() >= self._duration:
            self._timer.stop()
            self.dismiss()
        else:
            self.update()  # 刷新进度条

    def dismiss(self) -> None:
        """淡出并关闭。"""
        if self._closing:
            return
        self._closing = True
        self._timer.stop()
        self._fade.stop()
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)
        self._fade.start()

    def _on_fade_finished(self) -> None:
        if self._closing:
            self.close()

    def closeEvent(self, event) -> None:
        if self in Notification._active:
            Notification._active.remove(self)
        self._reflow()
        super().closeEvent(event)

    def _reflow(self) -> None:
        for n in self._siblings():
            n._move_to_stack(animate=True)

    def mouseMoveEvent(self, event) -> None:
        hover = self._close_rect().contains(event.position().toPoint())
        if hover != self._close_hover:
            self._close_hover = hover
            self.setCursor(Qt.PointingHandCursor if hover else Qt.ArrowCursor)
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton \
                and self._close_rect().contains(event.position().toPoint()):
            self.dismiss()
            return
        super().mouseReleaseEvent(event)

    def _close_rect(self) -> QRect:
        return QRect(self.width() - _PAD - 16, _PAD - 2, 16, 16)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        c = lambda k: T(f"color.{k}")  # noqa: E731
        card = QRect(0, 0, self.width() - 1,
                     self.height() - _PROGRESS_H - 1)
        radius = T("radius.lg")
        # 卡片
        path = QPainterPath()
        path.addRoundedRect(card.x(), card.y(), card.width(), card.height(),
                            radius, radius)
        painter.fillPath(path, QColor(c("bg.elevated")))
        pen = QPen(QColor(c("border")))
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.drawPath(path)
        # 图标
        pm = _type_icon(self._type, self._main_color())
        painter.drawPixmap(_PAD, _PAD + 1, pm)
        # 标题 / 正文
        text_x = _PAD + 28
        text_w = self.width() - text_x - _PAD - 18
        painter.setFont(self._title_font)
        painter.setPen(QColor(c("text.primary")))
        title_h = QFontMetrics(self._title_font).height()
        painter.drawText(QRect(text_x, _PAD, text_w, title_h),
                         Qt.AlignLeft | Qt.AlignVCenter, self._title)
        if self._message:
            painter.setFont(self._msg_font)
            painter.setPen(QColor(c("text.secondary")))
            painter.drawText(
                QRect(text_x, _PAD + title_h + 6, text_w,
                      self.height() - _PAD * 2 - title_h - 6 - _PROGRESS_H),
                Qt.TextWordWrap, self._message)
        # 关闭按钮
        icon = _close_icon().pixmap(12, 12)
        rect = self._close_rect()
        if self._close_hover:
            painter.setBrush(QColor(c("bg.muted")))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(rect.center(), 9, 9)
        painter.drawPixmap(rect.x() + 2, rect.y() + 2, icon)
        # 剩余时间进度条
        if self._duration > 0 and self._elapsed.isValid():
            ratio = max(0.0, 1.0 - self._elapsed.elapsed() / self._duration)
            if ratio > 0.0:
                bar_w = int(self.width() * ratio)
                bar = QRect(0, self.height() - _PROGRESS_H, bar_w,
                            _PROGRESS_H)
                clip = QPainterPath()
                clip.addRoundedRect(0, 0, self.width(), self.height(),
                                    radius, radius)
                painter.setClipPath(clip)
                painter.fillRect(bar, QColor(self._main_color()))
        painter.end()
