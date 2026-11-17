# -*- coding: utf-8 -*-
"""抽屉 Drawer（SPEC §5.3 drawer.py）。

从父窗口四边滑入的浮层：半透明遮罩、滑入滑出动画、宽度（或高度）可拖拽、
点击遮罩关闭。非阻塞 show 方式工作。

浮层三段结构与 Dialog 保持同一套语言：**标题区**（标题 + 关闭）、**正文区**、
（可选）底部操作区。面板圆角取 ``radius.lg``（只圆「离页面远」的两个角，
贴边那一侧保持直角），投影取 ``shadow.md`` 令牌——浮层是本项目允许使用
阴影的少数场景，且每个浮层只此一处。两段的内边距与间距全部引用
``layout.*`` / ``space.*`` 令牌。
"""

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPoint,
    QPropertyAnimation,
    QRect,
    QRectF,
    Qt,
    QVariantAnimation,
)
from PySide6.QtGui import QPainter, QPainterPath
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .._draw import arc_points
from ..theme import T, ThemeManager, set_font
from .dialog import (
    _connect_theme,
    close_icon,
    overlay_color,
    paint_soft_shadow,
)

__all__ = ["Drawer"]

#: 旧私有名别名（保持历史引用可用）
_overlay_color = overlay_color
_close_icon = close_icon

#: 面板最小尺寸（左右为宽、上下为高）
_MIN_SIZE = 200
#: 面板圆角：只圆远离页面的一侧
_PANEL_RADIUS = "radius.lg"
#: 投影等级（抽屉是大面积面板，取 md 而非 lg，避免整页被阴影压暗）
_SHADOW_LEVEL = "md"
#: 拖拽手柄宽度（面板内缘的隐形拖拽区）
_GRIP = T("space.2")
#: 关闭按钮边长（半径取其一半，即圆形图标按钮）
_CLOSE_SIDE = T("space.6")
#: 两段左右统一内边距（标题左缘与正文左缘严格一致）
_PAD_X = T("space.4")


class _Grip(QWidget):
    """抽屉内缘拖拽手柄，按住拖动调整面板尺寸。"""

    def __init__(self, drawer: "Drawer"):
        super().__init__(drawer._panel)
        self._drawer = drawer
        self._dragging = False
        self.setCursor(Qt.SizeHorCursor if drawer.position() in ("left", "right")
                       else Qt.SizeVerCursor)
        self._reposition()

    def _reposition(self) -> None:
        panel = self._drawer._panel
        pos = self._drawer.position()
        if pos == "right":
            self.setGeometry(0, 0, _GRIP, panel.height())
        elif pos == "left":
            self.setGeometry(panel.width() - _GRIP, 0, _GRIP, panel.height())
        elif pos == "top":
            self.setGeometry(0, panel.height() - _GRIP, panel.width(), _GRIP)
        else:
            self.setGeometry(0, 0, panel.width(), _GRIP)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._dragging = True
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if not self._dragging:
            return
        self._drawer._drag_to(event.globalPosition().toPoint())

    def mouseReleaseEvent(self, event) -> None:
        self._dragging = False


def _corner(path, rect, start_deg: float) -> None:
    """把一个 90° 圆角按点连线接进路径（不用 ``QPainterPath.arcTo``）。

    90° 实测本来是安全区间，但这里统一走折线：与其在代码里记「哪些跨度
    碰巧没事」，不如全包一个画法（见 ``_draw.py`` 的实测表）。
    """
    pts = arc_points(rect, start_deg, -90.0)
    for x, y in pts:
        path.lineTo(x, y)


def _rounded_corners_path(rect: QRectF, radius: float,
                          corners: tuple) -> QPainterPath:
    """逐角圆角矩形路径（``corners`` 为 (左上, 右上, 右下, 左下) 半径）。

    抽屉面板贴屏幕边的一侧必须是直角，否则会在窗口边界出现「半个圆角」
    的缺口——这正是 QSS 的逐角 ``border-*-radius`` 做不到而这里需要的。
    """
    tl, tr, br, bl = corners
    path = QPainterPath()
    path.moveTo(rect.left() + tl, rect.top())
    path.lineTo(rect.right() - tr, rect.top())
    if tr:
        _corner(path, QRectF(rect.right() - 2 * tr, rect.top(), 2 * tr, 2 * tr),
                90.0)
    path.lineTo(rect.right(), rect.bottom() - br)
    if br:
        _corner(path, QRectF(rect.right() - 2 * br, rect.bottom() - 2 * br,
                             2 * br, 2 * br), 0.0)
    path.lineTo(rect.left() + bl, rect.bottom())
    if bl:
        _corner(path, QRectF(rect.left(), rect.bottom() - 2 * bl, 2 * bl, 2 * bl),
                270.0)
    path.lineTo(rect.left(), rect.top() + tl)
    if tl:
        _corner(path, QRectF(rect.left(), rect.top(), 2 * tl, 2 * tl), 180.0)
    path.closeSubpath()
    return path


class Drawer(QDialog):
    """抽屉：从四边滑入，宽度可拖拽，点击遮罩关闭。

    参数:
        parent: 父窗口（抽屉几何跟随它）。
        position: 滑入方向 ``"right"`` / ``"left"`` / ``"top"`` / ``"bottom"``。
        size: 面板宽（左右方向）或高（上下方向）。
        title: 标题文本。
        resizable: 是否允许拖拽调整尺寸。

    示例::

        dr = Drawer(self, position="right", size=360, title="详情")
        dr.set_content(QLabel("内容"))
        dr.open()
    """

    #: 合法滑入方向
    POSITIONS = ("left", "right", "top", "bottom")

    def __init__(self, parent: QWidget = None, position: str = "right",
                 size: int = 360, title: str = "", resizable: bool = True):
        super().__init__(parent, Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        # 与 Popover 同理：只给 WA_TranslucentBackground 不够，Qt 仍会用
        # 窗口的系统背景刷子把整个窗口矩形填成不透明色（真机上表现为
        # 一圈矩形色块）。本组件只由 paintEvent 绘制，明确交回背景控制权。
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setModal(False)
        if position not in self.POSITIONS:
            raise ValueError(
                f"未知抽屉方向: {position!r}，应为 {self.POSITIONS} 之一")
        self._position = position
        self._size = max(_MIN_SIZE, int(size))
        self._overlay_alpha = 0.0
        self._opened = False
        self._closing = False

        self._panel = QFrame(self)
        self._panel.setObjectName("uikDrawerPanel")
        panel_layout = QVBoxLayout(self._panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)

        header = QWidget(self._panel)
        header.setObjectName("uikDrawerHeader")
        header.setAttribute(Qt.WA_StyledBackground, True)   # 让 QSS 分隔线生效
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(_PAD_X, T("space.3"), T("space.3"),
                                         T("space.2"))
        header_layout.setSpacing(T("layout.inline.gap"))
        self._title = QLabel(title, header)
        set_font(self._title, "title.sm", "semibold")
        header_layout.addWidget(self._title, 1)
        self._close_btn = QToolButton(header)
        self._close_btn.setIcon(close_icon())
        self._close_btn.setFixedSize(_CLOSE_SIDE, _CLOSE_SIDE)
        self._close_btn.setCursor(Qt.PointingHandCursor)
        self._close_btn.setFocusPolicy(Qt.NoFocus)
        self._close_btn.clicked.connect(self.close)
        header_layout.addWidget(self._close_btn, 0, Qt.AlignVCenter)
        panel_layout.addWidget(header)

        body = QWidget(self._panel)
        self._body_layout = QVBoxLayout(body)
        self._body_layout.setContentsMargins(_PAD_X, T("space.3"), _PAD_X,
                                             T("space.4"))
        self._body_layout.setSpacing(T("layout.card.gap"))
        panel_layout.addWidget(body, 1)

        self._grip = _Grip(self) if resizable else None
        self._panel.hide()

        self._anim = QPropertyAnimation(self._panel, b"pos", self)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.setDuration(T("duration.slow"))
        self._anim.finished.connect(self._on_anim_finished)
        self._fade = QVariantAnimation(self)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)
        self._fade.setDuration(T("duration.normal"))
        self._fade.valueChanged.connect(self._on_fade)

        if parent is not None:
            parent.installEventFilter(self)
        _connect_theme(self, self._reload_style)
        self._reload_style()

    # -- 公开 API ---------------------------------------------------------
    def position(self) -> str:
        """滑入方向。"""
        return self._position

    def set_title(self, text: str) -> None:
        """设置标题。"""
        self._title.setText(text)

    def title(self) -> str:
        return self._title.text()

    def set_content(self, widget: QWidget) -> None:
        """设置内容区控件（替换原有内容，旧控件销毁）。"""
        while self._body_layout.count():
            item = self._body_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._body_layout.addWidget(widget)

    def content_layout(self) -> QVBoxLayout:
        """返回内容区布局，便于自由添加多个控件。"""
        return self._body_layout

    def panel(self) -> QFrame:
        """返回抽屉面板控件。"""
        return self._panel

    def open(self) -> None:
        """打开抽屉（滑入动画，非阻塞）。"""
        self._sync_geometry()
        self._closing = False
        self.show()
        self.raise_()
        target, hidden = self._panel_positions()
        self._panel.resize(target.size())
        self._panel.move(hidden.topLeft())
        self._panel.show()
        if self._grip is not None:
            self._grip._reposition()
            self._grip.show()
        self._anim.stop()
        self._anim.setStartValue(hidden.topLeft())
        self._anim.setEndValue(target.topLeft())
        self._anim.start()
        self._start_fade(1.0)
        self._opened = True

    def close(self) -> None:  # noqa: A003 - 保持 QDialog 接口
        """关闭抽屉（滑出动画，结束后隐藏）。"""
        if not self.isVisible() or self._closing:
            return
        self._closing = True
        _target, hidden = self._panel_positions()
        self._anim.stop()
        self._anim.setStartValue(self._panel.pos())
        self._anim.setEndValue(hidden.topLeft())
        self._anim.start()
        self._start_fade(0.0)

    def reject(self) -> None:
        """Esc / 右上角关闭：走滑出动画。"""
        self.close()

    def panel_size(self) -> int:
        """面板宽（左右方向）或高（上下方向）。"""
        return self._size

    # -- 内部 -------------------------------------------------------------
    def _sync_geometry(self) -> None:
        if self.parent() is not None:
            top_left = self.parent().mapToGlobal(QPoint(0, 0))
            self.setGeometry(QRect(top_left, self.parent().size()))

    def _panel_positions(self):
        """返回 (目标矩形, 隐藏矩形)。"""
        w, h = self.width(), self.height()
        s = self._size
        if self._position == "right":
            return QRect(w - s, 0, s, h), QRect(w, 0, s, h)
        if self._position == "left":
            return QRect(0, 0, s, h), QRect(-s, 0, s, h)
        if self._position == "top":
            return QRect(0, 0, w, s), QRect(0, -s, w, s)
        return QRect(0, h - s, w, s), QRect(0, h, w, s)

    def _start_fade(self, end: float) -> None:
        self._fade.stop()
        self._fade.setStartValue(self._overlay_alpha)
        self._fade.setEndValue(end)
        self._fade.start()

    def _on_fade(self, value) -> None:
        self._overlay_alpha = float(value)
        self.update()

    def _on_anim_finished(self) -> None:
        if self._closing:
            self._closing = False
            self._opened = False
            self._panel.hide()
            self.hide()

    def _drag_to(self, global_pos: QPoint) -> None:
        geo = self.geometry()
        if self._position == "right":
            new = geo.x() + geo.width() - global_pos.x()
        elif self._position == "left":
            new = global_pos.x() - geo.x()
        elif self._position == "top":
            new = global_pos.y() - geo.y()
        else:
            new = geo.y() + geo.height() - global_pos.y()
        limit = int((self.width() if self._position in ("left", "right")
                     else self.height()) * 0.9)
        self._size = max(_MIN_SIZE, min(int(new), max(_MIN_SIZE, limit)))
        target, _hidden = self._panel_positions()
        self._panel.setGeometry(target)
        if self._grip is not None:
            self._grip._reposition()

    def eventFilter(self, watched, event) -> bool:
        if watched is self.parent() and event.type() in (
                QEvent.Resize, QEvent.Move) and self.isVisible():
            self._sync_geometry()
            if self._opened and not self._closing:
                target, _hidden = self._panel_positions()
                self._panel.setGeometry(target)
                if self._grip is not None:
                    self._grip._reposition()
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event) -> None:
        # 点击遮罩（面板之外）关闭
        if not self._panel.geometry().contains(event.position().toPoint()):
            self.close()
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        """遮罩 + 面板投影（面板本体由子 QFrame 的 QSS 负责）。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if self._overlay_alpha > 0.0:
            painter.fillRect(self.rect(), overlay_color(self._overlay_alpha))
        if self._panel.isVisible():
            rect = QRectF(self._panel.geometry())
            path = _rounded_corners_path(rect, T(_PANEL_RADIUS),
                                         self._panel_corners())
            paint_soft_shadow(painter, path, rect, _SHADOW_LEVEL)
        painter.end()

    def _panel_corners(self) -> tuple:
        """面板四角半径：贴屏幕边的两个角保持直角。"""
        r = T(_PANEL_RADIUS)
        return {
            "right": (r, 0.0, 0.0, r),
            "left": (0.0, r, r, 0.0),
            "top": (0.0, 0.0, r, r),
            "bottom": (r, r, 0.0, 0.0),
        }[self._position]

    def _reload_style(self) -> None:
        c = lambda k: T(f"color.{k}")  # noqa: E731
        radius = T(_PANEL_RADIUS)
        # 贴屏幕边的一侧不出圆角，否则窗口边界会缺一个角
        tl, tr, br, bl = self._panel_corners()
        corner_qss = "".join(
            f"border-{name}-radius: {value:g}px;"
            for name, value in (("top-left", tl), ("top-right", tr),
                                ("bottom-right", br), ("bottom-left", bl)))
        border = ("border.strong" if ThemeManager.instance().mode == "dark"
                  else "border")
        # 关闭按钮走实例级样式表：只影响自身，不污染全局按钮变体规则
        self._close_btn.setStyleSheet(
            f"QToolButton {{ background-color: transparent; border: none;"
            f" border-radius: {_CLOSE_SIDE // 2}px; }}"
            f"QToolButton:hover {{ background-color: {c('bg.muted')}; }}"
            f"QToolButton:pressed {{ background-color: {c('border')}; }}")
        self.setStyleSheet(f"""
QFrame#uikDrawerPanel {{
    background-color: {c('bg.elevated')};
    border: 1px solid {c(border)};
    {corner_qss}
}}
QWidget#uikDrawerHeader {{
    background-color: transparent;
    border-bottom: 1px solid {c('border')};
    border-top-left-radius: {tl:g}px;
    border-top-right-radius: {tr:g}px;
}}
""")
        self._close_btn.setIcon(close_icon())
