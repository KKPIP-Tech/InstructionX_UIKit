# -*- coding: utf-8 -*-
"""通知提醒框 Notification（SPEC §5.3 notification.py）。

管理器 + 单条卡片：以 FramelessWindowHint + Tool 顶层 QWidget 实现，
相对父窗口右上角堆叠弹出，自动消失并淡出，底部带剩余时间进度条。

度量引用 ``.alert`` 的提示族共享常量（``ICON_D`` / ``ICON_GAP``），
与 Alert / Message 的图标—文字基线关系保持一致。
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
from .alert import ICON_D, ICON_GAP, _close_icon, _type_icon
from shiboken6 import isValid as _shiboken_is_valid


def _connect_theme(widget, slot) -> None:
    """连接主题切换信号；组件销毁时断开连接（shiboken 守卫双保险）。"""
    manager = ThemeManager.instance()
    receiver = lambda *_: slot() if _shiboken_is_valid(widget) else None
    manager.theme_changed.connect(receiver)

    def _cleanup(_obj=None):
        try:
            manager.theme_changed.disconnect(receiver)
        except (RuntimeError, TypeError):
            pass

    widget.destroyed.connect(_cleanup)

__all__ = ["Notification"]

#: 卡片宽度（固定宽度 + 自行折行，契约 §7：不依赖 wordWrap 的压缩行为）
_WIDTH = 320
#: 卡片内边距（四边同值，内部文本上下对称）
_PAD = T("space.3")
#: 同屏多条通知的堆叠间距
_GAP = T("space.3")
#: 卡片距窗口右 / 上边缘的距离
_MARGIN = T("space.4")
#: 标题与正文之间的行间距
_TITLE_GAP = T("space.1")
#: 剩余时间进度条厚度（2px 基网格的半档，扁平细线）
_PROGRESS_H = T("space.05")
#: 关闭按钮边长
_CLOSE_D = T("space.3")
#: 正文右边界到关闭按钮的让位距离
_CLOSE_GUTTER = T("space.3")


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
        # 与 Popover 同理：只给 WA_TranslucentBackground 不够，Qt 仍会用
        # 窗口的系统背景刷子把整个窗口矩形填成不透明色（真机上表现为
        # 一圈矩形色块）。本组件只由 paintEvent 绘制，明确交回背景控制权。
        self.setAttribute(Qt.WA_NoSystemBackground)
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
        # 锚点销毁时同步清理：退出活动列表并关闭自身，避免后续
        # 对死包装器调用 mapToGlobal 抛 RuntimeError。
        anchor.destroyed.connect(self._on_anchor_destroyed)
        # 自身销毁时从活动列表移除（deleteLater 直删不走 closeEvent）
        self.destroyed.connect(self._on_destroyed)
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

        # 文本区几何在构造时一次算清并存下：paintEvent 直接复用，
        # 不再拿「剩余高度」反推，避免正文被压缩（契约 §7）
        self._text_x = _PAD + ICON_D + ICON_GAP
        self._text_w = _WIDTH - self._text_x - _PAD - _CLOSE_GUTTER
        self._title_h = QFontMetrics(title_font).height()
        self._title_y = _PAD
        self._msg_y = _PAD + self._title_h + _TITLE_GAP
        self._msg_h = (QFontMetrics(msg_font).boundingRect(
            QRect(0, 0, self._text_w, 1000),
            Qt.TextWordWrap, message).height() if message else 0)
        # 图标顶边与标题首行光学中心对齐（而非与卡片顶边齐平）
        self._icon_y = _PAD + (self._title_h - ICON_D) // 2
        body_h = _PAD + self._title_h + self._msg_h \
            + (_TITLE_GAP if self._msg_h else 0) + _PAD
        self.setFixedSize(_WIDTH, body_h + _PROGRESS_H)

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
    def info(anchor: QWidget, title: str, message: str,
             duration: int = 4000) -> "Notification":
        """弹出 info 通知。"""
        return Notification.notify(anchor, title, message, "info", duration)

    @staticmethod
    def success(anchor: QWidget, title: str, message: str,
                duration: int = 4000) -> "Notification":
        """弹出 success 通知。"""
        return Notification.notify(anchor, title, message, "success", duration)

    @staticmethod
    def warning(anchor: QWidget, title: str, message: str,
                duration: int = 4000) -> "Notification":
        """弹出 warning 通知。"""
        return Notification.notify(anchor, title, message, "warning", duration)

    @staticmethod
    def error(anchor: QWidget, title: str, message: str,
              duration: int = 4000) -> "Notification":
        """弹出 error 通知。"""
        return Notification.notify(anchor, title, message, "error", duration)

    @staticmethod
    def close_all() -> None:
        """立即关闭所有存活通知。"""
        # 先剔除死包装器（调用方可能已 deleteLater），再逐一关闭
        Notification._active = [n for n in Notification._active
                                if _shiboken_is_valid(n)]
        for n in list(Notification._active):
            n._timer.stop()
            n.close()

    # -- 内部 -------------------------------------------------------------
    def _on_anchor_destroyed(self, _obj=None) -> None:
        """锚点销毁：退出活动列表并销毁自身（定位已无意义）。"""
        if self in Notification._active:
            Notification._active.remove(self)
        self._timer.stop()
        self.deleteLater()

    def _on_destroyed(self, _obj=None) -> None:
        """自身销毁（deleteLater 等不走 closeEvent 的路径）：清理活动列表。"""
        Notification._active = [n for n in Notification._active
                                if n is not self and _shiboken_is_valid(n)]

    def _main_color(self) -> str:
        return {"info": T("color.primary"),
                "success": T("color.success"),
                "warning": T("color.warning"),
                "error": T("color.danger")}[self._type]

    def _siblings(self):
        return [n for n in Notification._active
                if _shiboken_is_valid(n) and n._anchor is self._anchor]

    def _target_pos(self) -> QPoint:
        # 锚点已销毁时返回占位坐标：正常流程下锚点销毁会连带关闭自身，
        # 此守卫兜底动画回调等边界路径，避免死包装器 mapToGlobal 崩溃。
        if not _shiboken_is_valid(self._anchor):
            return QPoint(0, 0)
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
            self.move(target + QPoint(_WIDTH // 4, 0))
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
        if not _shiboken_is_valid(self._anchor):
            return
        for n in self._siblings():
            n._move_to_stack(animate=True)

    def showEvent(self, event) -> None:
        # 倒计时定时器仅在可见时运行（隐藏/关闭期间不空转）
        super().showEvent(event)
        if self._duration > 0 and self._elapsed.isValid() and not self._closing:
            self._timer.start()

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

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
        """关闭按钮热区：与标题首行光学中心同线，不与卡片顶边齐平。"""
        return QRect(self.width() - _PAD - _CLOSE_D, self._icon_y, _CLOSE_D,
                     _CLOSE_D)

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
        # 图标：顶边与标题首行中心对齐（标题恒为单行，故不存在多行歧义）
        pm = _type_icon(self._type, self._main_color())
        painter.drawPixmap(_PAD, self._icon_y, pm)
        # 标题 / 正文
        painter.setFont(self._title_font)
        painter.setPen(QColor(c("text.primary")))
        painter.drawText(QRect(self._text_x, self._title_y, self._text_w,
                               self._title_h),
                         Qt.AlignLeft | Qt.AlignVCenter, self._title)
        if self._msg_h:
            painter.setFont(self._msg_font)
            painter.setPen(QColor(c("text.secondary")))
            painter.drawText(QRect(self._text_x, self._msg_y, self._text_w,
                                   self._msg_h),
                             Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap,
                             self._message)
        # 关闭按钮
        icon = _close_icon(int(T("space.2"))).pixmap(int(T("space.2")),
                                                     int(T("space.2")))
        rect = self._close_rect()
        if self._close_hover:
            painter.setBrush(QColor(c("bg.muted")))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(rect.center(), rect.width() / 2,
                                rect.height() / 2)
        painter.drawPixmap(rect.x() + (rect.width() - icon.width()) // 2,
                           rect.y() + (rect.height() - icon.height()) // 2,
                           icon)
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