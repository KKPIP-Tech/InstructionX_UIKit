# -*- coding: utf-8 -*-
"""统一对话框 Dialog（SPEC §5.3 dialog.py）。

无边框浮层，卡片分三段：**标题区**（标题 + 关闭按钮）、**正文区**、
**按钮区**。卡片圆角取 ``radius.lg``，投影取 ``shadow.lg`` 令牌——浮层是
本项目允许使用阴影的少数场景，且每个浮层只此一处（普通控件一律无投影）。
三段的内边距与段内间距全部引用 ``layout.*`` / ``space.*`` 令牌，无裸数字。

**为什么不用系统原生标题栏**：原生标题栏不跟随主题换肤（暗色下仍是浅色，
与暗色卡片割裂），也无法与卡片的圆角 / 投影协调；自绘标题区后亮暗两套
主题下都是同一套层级。窗口标题仍写入 ``setWindowTitle``，供任务栏与
无障碍使用。

**本模块同时是轨道6 浮层的私有原语库**：``close_icon``（关闭图标）、
``wrap_text``（折行助手）、``paint_soft_shadow``（柔和投影）、``overlay_color``
（遮罩色）由 ``drawer`` / ``tour`` 复用，避免同一套浮层装饰在三处各写一遍
而逐渐漂移。

``confirm()`` / ``info()`` 静态便捷方法以非阻塞方式弹出（show），结果通过
回调或 finished 信号返回，便于 offscreen 测试与异步交互。
"""

import unicodedata

from PySide6.QtCore import QEvent, QRect, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFontMetrics,
    QGuiApplication,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid as _shiboken_is_valid

from ..theme import T, ThemeManager, set_font, set_property
from ..tokens import TokenState

__all__ = ["Dialog"]

#: 跟踪非阻塞弹出的对话框，避免被 GC
_OPEN_DIALOGS = []

#: 卡片圆角档（浮层用 lg）
_CARD_RADIUS = "radius.lg"
#: 投影等级：对话框浮在最上层取最重一档；抽屉 / 引导气泡用 md
_SHADOW_LEVEL = "lg"
#: 对话框最小宽度 = 8 × space.12（384px）：13px 正文单行约容 26 个汉字，
#: 窄于此会频繁折行
_MIN_W = T("space.12") * 8
#: 关闭按钮边长（半径取其一半，即圆形图标按钮）
_CLOSE_SIDE = T("space.6")
#: 标题区 / 正文区 / 按钮区的左右统一内边距
_PAD_X = T("space.4")
#: 段内元素间距（标题↔关闭、正文多块之间）
_GAP = T("layout.card.gap")


# ---------------------------------------------------------------------------
# 浮层原语（供 drawer / tour 复用）
# ---------------------------------------------------------------------------

def _connect_theme(widget, slot) -> None:
    """连接主题 / 令牌变更信号；控件销毁时断开（shiboken 守卫双保险）。

    自绘组件不走 QSS，令牌被会话级 ``set_token`` 覆盖时只有重绘才会生效，
    因此 ``token_changed`` 与 ``theme_changed`` 同样要订阅。
    """
    manager = ThemeManager.instance()
    tokens = TokenState.instance()
    receiver = lambda *_: slot() if _shiboken_is_valid(widget) else None
    manager.theme_changed.connect(receiver)
    tokens.token_changed.connect(receiver)

    def _cleanup(_obj=None):
        for signal in (manager.theme_changed, tokens.token_changed):
            try:
                signal.disconnect(receiver)
            except (RuntimeError, TypeError):
                pass

    widget.destroyed.connect(_cleanup)


def shadow_margin(level: str) -> int:
    """某投影等级所需的画布留白（四边），由令牌本身推出而非写死。

    留白须不小于「模糊半径的一半 + 位移」，否则投影会被窗口边界裁掉。
    """
    spec = T(f"shadow.{level}")
    dx, dy = spec["offset"]
    return int(round(max(spec["blur"] / 2.0 + abs(dy),
                         spec["blur"] / 2.0 + abs(dx))))


def paint_soft_shadow(painter: QPainter, path: QPainterPath, rect: QRectF,
                      level: str = "md", layers: int = 12,
                      spread: float = 6.0, offset_y: float = 2.0) -> None:
    """在 ``path`` 外缘铺一层令牌驱动的柔和投影（**仅浮层可用**）。

    不用 ``QGraphicsDropShadowEffect``：无边框 + 半透明背景的窗口上它会把
    整窗涂成不透明色块（暗色即「黑方块」）。这里用多层等比外扩叠加，
    权重按 ``(1-t)^2`` 二次衰减近似高斯模糊；颜色 / 模糊 / 位移全部取自
    ``shadow.<level>`` 令牌。``path`` 含箭头时整条路径一起带阴影。
    """
    if rect.width() <= 0 or rect.height() <= 0:
        return
    r, g, b, a = T(f"shadow.{level}")["color"]
    weights = [(1.0 - (i + 0.5) / layers) ** 2 for i in range(layers)]
    total = sum(weights)
    cx, cy = rect.center().x(), rect.center().y()
    painter.setPen(Qt.NoPen)
    # 由外层画到内层：外层单层透明度低、内层高，叠加后边缘无分层感。
    # save/restore 必须**在循环体内**：translate+scale 是对当前变换的累乘，
    # 放外面会让 12 层的缩放连乘（1.04^12 ≈ 1.67），阴影糊满整个留白区。
    for i in range(layers - 1, -1, -1):
        t = (layers - i) / layers                     # 1 -> 1/layers
        grow = t * spread
        alpha = round(a * weights[i] / total)
        if alpha <= 0:
            continue
        painter.save()
        painter.translate(cx, cy + 0.5 + t * offset_y)
        painter.scale((rect.width() + 2 * grow) / rect.width(),
                      (rect.height() + 2 * grow) / rect.height())
        painter.translate(-cx, -cy)
        painter.setBrush(QColor(r, g, b, alpha))
        painter.drawPath(path)
        painter.restore()


def overlay_color(alpha: float = 1.0) -> QColor:
    """解析 overlay 令牌（``rgba(r,g,b,a)`` 字符串）为 QColor，可再乘透明度。"""
    token = str(T("color.overlay"))
    if token.startswith("rgba"):
        inner = token[token.index("(") + 1: token.rindex(")")]
        r, g, b, a = [p.strip() for p in inner.split(",")][:4]
        base = float(a)
        base = base if base <= 1.0 else base / 255.0
        return QColor(int(float(r)), int(float(g)), int(float(b)),
                      int(round(base * alpha * 255)))
    color = QColor(token)
    if alpha < 1.0:
        color.setAlpha(int(round(color.alpha() * alpha)))
    return color


def close_icon(side: int = 12, color_key: str = "color.text.tertiary",
               width: float = 1.5) -> QIcon:
    """关闭「×」图标（尺寸 / 颜色 / 线宽可配，默认三级文字色）。"""
    pm = QPixmap(side, side)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(T(color_key)))
    pen.setWidthF(width)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    inset = side / 4.0
    painter.drawLine(inset, inset, side - inset, side - inset)
    painter.drawLine(side - inset, inset, inset, side - inset)
    painter.end()
    return QIcon(pm)


#: 旧私有名别名（drawer 等模块历史上按 ``_close_icon`` 引用）
_close_icon = close_icon


def body_font():
    """正文折行用的度量字体（与 ``set_font(label, "md")`` 同源）。"""
    return TokenState.instance().font("md", "regular")


def _is_wide(ch: str) -> bool:
    """全角 / 宽字符（中日韩）：逐字可断行。"""
    return unicodedata.east_asian_width(ch) in ("W", "F")


def _tokens_of(text: str):
    """把文本切成「宽字符 / 单词 / 空白 / 换行」四类记号。"""
    out, buf = [], ""

    def _flush():
        nonlocal buf
        if buf:
            out.append(buf)
            buf = ""

    for ch in text:
        if ch == "\n":
            _flush()
            out.append("\n")
        elif ch.isspace():
            _flush()
            out.append(" ")
        elif _is_wide(ch):
            _flush()
            out.append(ch)
        else:
            buf += ch
    _flush()
    return out


def wrap_text(text: str, font, width: int) -> str:
    """按给定像素宽度折行（契约 §7：不要只靠 ``QLabel.setWordWrap``）。

    ``QLabel`` 开 wordWrap 后 ``minimumSizeHint`` 高度近乎 0，在
    ``QScrollArea`` / 居中行布局里会被优先压缩，出现「第二行被盖住」。
    这里自行折行并返回带 ``\\n`` 的文本，调用方据此锁定控件高度，视觉稳定。
    英文按单词换行（不拆散单词），中文与全角标点逐字换行。
    """
    if not text:
        return ""
    width = max(1, int(width))
    fm = QFontMetrics(font)
    lines: list[str] = []
    cur = ""
    for token in _tokens_of(text):
        if token == "\n":
            lines.append(cur.rstrip())
            cur = ""
            continue
        probe = token.rstrip() if not _is_wide(token[0]) else token
        if cur and fm.horizontalAdvance(cur + probe) > width:
            lines.append(cur.rstrip())
            cur = "" if token.isspace() else token
        else:
            cur += token
    lines.append(cur.rstrip())
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------

class Dialog(QDialog):
    """统一对话框：标题区 + 正文区 + 按钮区。

    参数:
        parent: 父控件。
        title: 标题文本。
        ok_text: 确认按钮文本。
        cancel_text: 取消按钮文本。
        show_cancel: 是否显示取消按钮。

    示例::

        dlg = Dialog(self, title="删除文件")
        dlg.set_text("确定删除该文件吗？")
        dlg.accepted.connect(lambda: print("已确认"))
    """

    def __init__(self, parent: QWidget = None, title: str = "",
                 ok_text: str = "确定", cancel_text: str = "取消",
                 show_cancel: bool = True):
        super().__init__(parent, Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        # 与 Popover 同理：只给 WA_TranslucentBackground 不够，Qt 仍会用
        # 窗口的系统背景刷子把整个窗口矩形填成不透明色（真机上表现为
        # 一圈矩形色块）。本组件只由 paintEvent 绘制，明确交回背景控制权。
        self.setAttribute(Qt.WA_NoSystemBackground)
        self._title_text = title
        self._raw_text = ""
        self.setWindowTitle(title or "对话框")
        self.setMinimumWidth(_MIN_W)
        self.setWindowModality(Qt.WindowModal if parent is not None
                               else Qt.ApplicationModal)
        self._drag_offset = None
        self._centered = False
        self._text_label = None

        # 阴影留白：整窗比卡片大出一圈，四边透明
        self._margin = shadow_margin(_SHADOW_LEVEL)
        root = QVBoxLayout(self)
        root.setContentsMargins(self._margin, self._margin,
                                self._margin, self._margin)
        root.setSpacing(0)

        self._card = QFrame(self)
        self._card.setObjectName("uikDialogCard")
        card = QVBoxLayout(self._card)
        card.setContentsMargins(0, 0, 0, 0)
        card.setSpacing(0)
        root.addWidget(self._card, 1)

        # -- 标题区（按住可拖拽窗口） --
        header = QWidget(self._card)
        header.setObjectName("uikDialogHeader")
        header.setAttribute(Qt.WA_StyledBackground, True)   # 让 QSS 边框生效
        header.installEventFilter(self)
        self._header = header
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(_PAD_X, _GAP, _GAP, _GAP)
        header_layout.setSpacing(_GAP)
        self._title = QLabel(title, header)
        self._title.setObjectName("uikDialogTitle")
        # 透明鼠标事件：点标题也能拖动窗口
        self._title.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        set_font(self._title, "title.sm", "semibold")
        header_layout.addWidget(self._title, 1)
        self._close = QToolButton(header)
        self._close.setIcon(close_icon())
        self._close.setFixedSize(_CLOSE_SIDE, _CLOSE_SIDE)
        self._close.setCursor(Qt.PointingHandCursor)
        self._close.setFocusPolicy(Qt.NoFocus)
        self._close.clicked.connect(self.reject)
        header_layout.addWidget(self._close, 0, Qt.AlignVCenter)
        card.addWidget(header)

        # -- 正文区 --
        self._body = QWidget(self._card)
        self._body.setObjectName("uikDialogBody")
        # 正文最小高度 ≈ 两行：只有一行时对话框会显得头重脚轻
        self._body.setMinimumHeight(T("space.6") * 2)
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(_PAD_X, _PAD_X, _PAD_X, _PAD_X)
        self._body_layout.setSpacing(_GAP)
        self._body_layout.addStretch(1)
        card.addWidget(self._body, 1)

        # -- 按钮区 --
        footer = QWidget(self._card)
        footer.setObjectName("uikDialogFooter")
        footer.setAttribute(Qt.WA_StyledBackground, True)
        footer_layout = QHBoxLayout(footer)
        # 底部比顶部多 2px：补偿 1px 分隔线，正文与按钮区视觉等距
        footer_layout.setContentsMargins(_PAD_X, _GAP, _PAD_X, _GAP + T("space.05"))
        footer_layout.setSpacing(T("layout.inline.gap"))
        footer_layout.addStretch(1)
        self._cancel = QPushButton(cancel_text, self)
        set_property(self._cancel, "variant", "default")
        set_property(self._cancel, "size", "md")
        self._cancel.clicked.connect(self.reject)
        self._ok = QPushButton(ok_text, self)
        set_property(self._ok, "variant", "primary")
        set_property(self._ok, "size", "md")
        self._ok.setDefault(True)
        self._ok.clicked.connect(self.accept)
        footer_layout.addWidget(self._cancel)
        footer_layout.addWidget(self._ok)
        self._cancel.setVisible(show_cancel)
        card.addWidget(footer)

        _connect_theme(self, self._reload_style)
        self._reload_style()

    # -- 公开 API ---------------------------------------------------------
    def set_title(self, text: str) -> None:
        """设置标题（卡片标题区 + 窗口标题）。"""
        self._title_text = text
        self._title.setText(text)
        self.setWindowTitle(text or "对话框")

    def title(self) -> str:
        return self._title_text

    def set_text(self, text: str) -> None:
        """以一段文本填充内容区（自行折行、宽度固定，不依赖 wordWrap）。"""
        self._raw_text = text
        measure = self._text_measure()
        label = QLabel(self._card)
        label.setObjectName("uikDialogText")
        label.setFixedWidth(measure)
        label.setText(wrap_text(text, body_font(), measure))
        set_font(label, "md", "regular")
        self.set_content(label)
        self._text_label = label

    def set_content(self, widget: QWidget) -> None:
        """设置内容区控件（替换原有内容，旧控件销毁）。"""
        while self._body_layout.count():
            item = self._body_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._text_label = None
        self._body_layout.insertWidget(0, widget)

    def ok_button(self) -> QPushButton:
        return self._ok

    def cancel_button(self) -> QPushButton:
        return self._cancel

    def close_button(self) -> QToolButton:
        """右上角关闭按钮（供需要自定义图标的调用方）。"""
        return self._close

    # -- 内部 -------------------------------------------------------------
    def _text_measure(self) -> int:
        """正文折行宽度 = 卡片宽 - 左右内边距（构造期卡片尚未布局，取最小宽）。"""
        return max(self._card.width(), _MIN_W) - _PAD_X * 2

    def eventFilter(self, watched, event):
        """标题区拖拽：只在标题区上生效。"""
        if watched is self._header:
            et = event.type()
            if et == QEvent.Type.MouseButtonPress and event.button() == Qt.LeftButton:
                self._drag_offset = (event.globalPosition().toPoint()
                                     - self.frameGeometry().topLeft())
                return True
            if et == QEvent.Type.MouseMove and self._drag_offset is not None:
                self.move(event.globalPosition().toPoint() - self._drag_offset)
                return True
            if et == QEvent.Type.MouseButtonRelease:
                self._drag_offset = None
                return True
        return super().eventFilter(watched, event)

    def resizeEvent(self, event) -> None:
        # 卡片宽度变化时同步正文折行宽度，避免窄化后被压扁
        super().resizeEvent(event)
        if self._text_label is None:
            return
        measure = self._card.width() - _PAD_X * 2
        if measure > 0 and self._text_label.width() != measure:
            self._text_label.setFixedWidth(measure)
            self._text_label.setText(
                wrap_text(self._raw_text, body_font(), measure))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._centered:
            self._centered = True
            self._center()

    def paintEvent(self, event) -> None:
        """只画投影：卡片本体由子 QFrame 的 QSS 负责（圆角 + 底色 + 边框）。"""
        m = self._margin
        card = QRectF(m, m, self.width() - 2 * m, self.height() - 2 * m)
        if card.width() <= 0 or card.height() <= 0:
            return
        radius = T(_CARD_RADIUS)
        path = QPainterPath()
        path.addRoundedRect(card, radius, radius)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        paint_soft_shadow(painter, path, card, _SHADOW_LEVEL)
        painter.end()

    def _center(self) -> None:
        """首次显示时在父窗口（无父窗口则屏幕）正中。"""
        area = None
        parent = self.parentWidget()
        if parent is not None:
            window = parent.window()
            if window is not None and window.isVisible():
                area = window.frameGeometry()
        if area is None or not area.isValid():
            screen = QGuiApplication.primaryScreen()
            area = screen.availableGeometry() if screen is not None else QRect()
        self.move(area.x() + (area.width() - self.width()) // 2,
                  area.y() + (area.height() - self.height()) // 2)

    def _reload_style(self) -> None:
        c = lambda k: T(f"color.{k}")  # noqa: E731
        # 暗色下 elevated 与 canvas 亮度接近，用 strong 描边拉开层次
        border = ("border.strong" if ThemeManager.instance().mode == "dark"
                  else "border")
        radius = T(_CARD_RADIUS)
        # 关闭按钮走实例级样式表：只影响自身，不会覆盖全局按钮变体规则
        self._close.setStyleSheet(
            f"QToolButton {{ background-color: transparent; border: none;"
            f" border-radius: {_CLOSE_SIDE // 2}px; }}"
            f"QToolButton:hover {{ background-color: {c('bg.muted')}; }}"
            f"QToolButton:pressed {{ background-color: {c('border')}; }}")
        self.setStyleSheet(f"""
QFrame#uikDialogCard {{
    background-color: {c('bg.elevated')};
    border: 1px solid {c(border)};
    border-radius: {radius}px;
}}
QWidget#uikDialogHeader {{
    background-color: transparent;
    border-bottom: 1px solid {c('border')};
    border-top-left-radius: {radius}px;
    border-top-right-radius: {radius}px;
}}
QWidget#uikDialogBody {{ background-color: transparent; }}
QWidget#uikDialogFooter {{
    background-color: transparent;
    border-top: 1px solid {c('border')};
    border-bottom-left-radius: {radius}px;
    border-bottom-right-radius: {radius}px;
}}
QLabel#uikDialogTitle {{
    color: {c('text.primary')};
    background-color: transparent;
}}
QLabel#uikDialogText {{
    color: {c('text.secondary')};
    background-color: transparent;
}}
""")
        self._close.setIcon(close_icon())

    # -- 静态便捷方法（非阻塞） ------------------------------------------
    @staticmethod
    def confirm(parent: QWidget, title: str, text: str, on_result=None,
                ok_text: str = "确定", cancel_text: str = "取消") -> "Dialog":
        """弹出确认对话框（非阻塞）。

        参数 ``on_result`` 为回调，签名为 ``on_result(ok: bool)``；
        返回 Dialog 实例，可继续连接 accepted / rejected 信号。
        """
        dlg = Dialog(parent, title, ok_text, cancel_text, show_cancel=True)
        dlg.set_text(text)
        if callable(on_result):
            dlg.finished.connect(
                lambda res: on_result(res == QDialog.DialogCode.Accepted))
        _track(dlg)
        dlg.show()
        return dlg

    @staticmethod
    def info(parent: QWidget, title: str, text: str, on_close=None,
             ok_text: str = "知道了") -> "Dialog":
        """弹出信息提示对话框（非阻塞，仅确认按钮）。"""
        dlg = Dialog(parent, title, ok_text, show_cancel=False)
        dlg.set_text(text)
        if callable(on_close):
            dlg.finished.connect(lambda _res: on_close())
        _track(dlg)
        dlg.show()
        return dlg


def _track(dlg: Dialog) -> None:
    """持有非阻塞对话框引用，finished / destroyed 后释放。

    仅 finished 会漏掉直接 deleteLater 的路径（死包装器残留），
    补连 destroyed 双保险。
    """
    _OPEN_DIALOGS.append(dlg)

    def _release(*_):
        if dlg in _OPEN_DIALOGS:
            _OPEN_DIALOGS.remove(dlg)

    dlg.finished.connect(_release)
    dlg.destroyed.connect(_release)
