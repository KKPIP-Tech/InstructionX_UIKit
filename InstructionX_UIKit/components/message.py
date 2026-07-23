# -*- coding: utf-8 -*-
"""全局提示 Message（SPEC §5.3 message.py）。

顶部居中的轻提示：FramelessWindowHint + Tool 顶层 QWidget，
相对父窗口定位，自动淡出消失。
"""

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRect,
    QSize,
    Qt,
    QTimer,
)
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from ..theme import T, ThemeManager
from .alert import _type_icon
from shiboken6 import isValid as _shiboken_is_valid


def _connect_theme(widget, slot) -> None:
    """连接主题切换信号；控件销毁后自动忽略回调。"""
    ThemeManager.instance().theme_changed.connect(
        lambda *_: slot() if _shiboken_is_valid(widget) else None)

__all__ = ["Message"]

_HEIGHT = 36
_PAD_X = 14
_PAD_Y = 8
_ICON_W = 20
_ICON_GAP = 8
_GAP = 10
_TOP = 20
#: 气泡最大宽度（含内边距），文本超出后换行并增高
_MAX_WIDTH = 480


class Message(QWidget):
    """全局轻提示（顶部居中、自动消失）。

    一般通过静态方法弹出，无需直接实例化。

    参数:
        anchor: 相对定位的父窗口控件。
        text: 提示文本。
        type: ``"info"`` / ``"success"`` / ``"warning"`` / ``"error"``。
        duration: 自动关闭时长（毫秒）。

    示例::

        Message.success(win, "保存成功")
        Message.warning(win, "磁盘空间不足")
        Message.close_all()
    """

    #: 合法类型
    TYPES = ("info", "success", "warning", "error")
    #: 当前所有存活提示（管理器状态）
    _active = []

    def __init__(self, anchor: QWidget, text: str, type: str = "info",
                 duration: int = 2000):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool
                         | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAutoFillBackground(False)
        # 覆盖全局基座 QSS「QWidget { background: bg.base }」，避免提示
        # 窗口整个矩形被涂上不透明底色（暗色下呈黑色方框）；胶囊卡体
        # 与内容只由 paintEvent 自绘，窗口其余区域保持真透明。
        self.setStyleSheet("background: transparent;")
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        if type not in self.TYPES:
            raise ValueError(
                f"未知提示类型: {type!r}，应为 {self.TYPES} 之一")
        self._anchor = anchor
        self._type = type
        self._text = text
        self._closing = False

        # 依据 sizeHint() 自适应内容尺寸（宽随文本增长，超长换行增高）
        self.adjustSize()

        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(T("duration.slow"))
        self._fade.finished.connect(self._on_fade_finished)
        self._slide = QPropertyAnimation(self, b"pos", self)
        self._slide.setDuration(T("duration.normal"))
        self._slide.setEasingCurve(QEasingCurve.OutCubic)

        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.setInterval(max(0, int(duration)))
        self._dismiss_timer.timeout.connect(self.dismiss)
        self._dismiss_timer.start()
        _connect_theme(self, self.update)

    # -- 静态管理器 API ---------------------------------------------------
    @staticmethod
    def show(anchor: QWidget, text: str, type: str = "info",
             duration: int = 2000) -> "Message":
        """弹出一条轻提示并返回实例（非阻塞）。"""
        m = Message(anchor, text, type, duration)
        Message._active.append(m)
        m._place(entrance=True)
        QWidget.show(m)  # 静态 show 遮蔽了 QWidget.show，需显式调用
        return m

    @staticmethod
    def info(anchor, text, duration: int = 2000) -> "Message":
        """弹出 info 提示。"""
        return Message.show(anchor, text, "info", duration)

    @staticmethod
    def success(anchor, text, duration: int = 2000) -> "Message":
        """弹出 success 提示。"""
        return Message.show(anchor, text, "success", duration)

    @staticmethod
    def warning(anchor, text, duration: int = 2000) -> "Message":
        """弹出 warning 提示。"""
        return Message.show(anchor, text, "warning", duration)

    @staticmethod
    def error(anchor, text, duration: int = 2000) -> "Message":
        """弹出 error 提示。"""
        return Message.show(anchor, text, "error", duration)

    @staticmethod
    def close_all() -> None:
        """立即关闭所有存活提示。"""
        for m in list(Message._active):
            m.close()

    # -- 内部 -------------------------------------------------------------
    def _main_color(self) -> str:
        return {"info": T("color.primary"),
                "success": T("color.success"),
                "warning": T("color.warning"),
                "error": T("color.danger")}[self._type]

    def sizeHint(self) -> QSize:
        """按文本内容自适应尺寸。

        宽度 = 内边距 + 图标槽 + 间距 + 文本宽，上限 ``_MAX_WIDTH``；
        文本超出可用宽度时按 ``_MAX_WIDTH`` 换行，高度随行数增加，
        最小高度保持 ``_HEIGHT``。单行时必须用 ``horizontalAdvance``
        （含尾部空白的布局宽度）而非 ``boundingRect`` 的墨迹宽度，
        否则绘制端按同一可用宽度换行会与尺寸计算不一致。
        """
        fm = QFontMetrics(self.font())
        text_max_w = _MAX_WIDTH - 2 * _PAD_X - _ICON_W - _ICON_GAP
        advance = fm.horizontalAdvance(self._text)
        if advance <= text_max_w:
            text_w, text_h = advance, fm.height()
        else:
            br = fm.boundingRect(QRect(0, 0, text_max_w, 0),
                                 Qt.TextWordWrap, self._text)
            # 换行气泡占满上限宽度，保证绘制端换行结果与这里一致
            text_w, text_h = text_max_w, br.height()
        w = 2 * _PAD_X + _ICON_W + _ICON_GAP + max(1, text_w)
        h = max(_HEIGHT, text_h + 2 * _PAD_Y)
        return QSize(min(w, _MAX_WIDTH), h)

    def _siblings(self):
        return [m for m in Message._active if m._anchor is self._anchor]

    def _target_pos(self) -> QPoint:
        base = self._anchor.mapToGlobal(QPoint(0, 0))
        x = base.x() + (self._anchor.width() - self.width()) // 2
        y = base.y() + _TOP
        # 逐条累加前方气泡的实际高度（多行气泡可能高于 _HEIGHT）
        for m in self._siblings():
            if m is self:
                break
            y += m.height() + _GAP
        return QPoint(x, y)

    def _place(self, entrance: bool) -> None:
        target = self._target_pos()
        if entrance:
            self.move(target + QPoint(0, -10))
            self.setWindowOpacity(0.0)
            self._slide.setStartValue(self.pos())
            self._slide.setEndValue(target)
            self._slide.start()
            self._fade.finished.disconnect(self._on_fade_finished)
            self._fade.setStartValue(0.0)
            self._fade.setEndValue(1.0)
            self._fade.start()
            self._fade.finished.connect(self._on_fade_finished)
        else:
            self.move(target)

    def dismiss(self) -> None:
        """淡出并关闭。"""
        if self._closing:
            return
        self._closing = True
        self._fade.stop()
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)
        self._fade.start()

    def _on_fade_finished(self) -> None:
        if self._closing:
            self.close()

    def closeEvent(self, event) -> None:
        if self in Message._active:
            Message._active.remove(self)
        for m in self._siblings():
            m._place(entrance=False)
        super().closeEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        c = lambda k: T(f"color.{k}")  # noqa: E731
        rect = self.rect().adjusted(0, 0, -1, -1)
        # radius.pill(999) 语义为“半高胶囊”，但 addRoundedRect 不会把
        # 过大的半径钳制到半宽/半高，直接传入会生成自交路径，填充后呈
        # 椭圆/叶片状。这里显式取半宽半高，保证背景始终是圆角矩形胶囊。
        radius = min(float(T("radius.pill")),
                     rect.width() / 2.0, rect.height() / 2.0)
        path = QPainterPath()
        path.addRoundedRect(rect.x(), rect.y(), rect.width(), rect.height(),
                            radius, radius)
        painter.fillPath(path, QColor(c("bg.elevated")))
        pen = QPen(QColor(c("border")))
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.drawPath(path)
        pm = _type_icon(self._type, self._main_color())
        y = (self.height() - 18) // 2
        painter.drawPixmap(_PAD_X, y, pm)
        painter.setFont(self.font())
        painter.setPen(QColor(c("text.primary")))
        # 文本区基于完整控件矩形计算（不能用上面为边框内缩 1px 的 rect），
        # 保证可用宽度与 sizeHint() 的布局宽度一致，避免单行文本被
        # TextWordWrap 差 1px 而意外换行。
        text_rect = self.rect().adjusted(
            _PAD_X + _ICON_W + _ICON_GAP, 0, -_PAD_X, 0)
        painter.drawText(text_rect,
                         Qt.AlignVCenter | Qt.AlignLeft | Qt.TextWordWrap,
                         self._text)
        painter.end()
