# -*- coding: utf-8 -*-
"""警告提示 Alert（SPEC §5.3 alert.py）。

四种类型 info / success / warning / error，支持标题、描述、
操作按钮与关闭按钮；图标为主题感知自绘像素图。

本模块同时是**提示类组件的度量基准**：``message`` / ``notification`` /
``popconfirm`` 都从这里取 ``ICON_D``（图标边长）与 ``_type_icon``，
四个组件的「图标 ↔ 文字」基线关系因此能保持一致。
"""

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..theme import T, ThemeManager, set_property
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

__all__ = ["Alert"]

# ---------------------------------------------------------------------------
# 提示族共享度量（alert / message / notification / popconfirm 一律引用此处）
# ---------------------------------------------------------------------------

#: 提示类组件共用的自绘图标边长。四者共用同一枚图标是「图标与文字基线
#: 对齐」能成立的前提——图标只要大一分 / 小一分，四条反馈的视觉重心就会
#: 互相错位。改动这里等于同时改动四个组件，请勿在单个组件里另立图标尺寸。
ICON_D = 18

#: 图标与文字的间距（``layout.icon.gap``，提示族统一值）
ICON_GAP = T("layout.icon.gap")
#: 提示条内容区左右内边距（``layout.card.pad_x``）
PAD_X = T("layout.card.pad_x")
#: 提示条内容区上下内边距，上下同值保持对称（契约 §3「内部文本上下对称」）
PAD_Y = T("space.2")


def _wrap_text(text: str, fm, width: int) -> list:
    """按可用宽度自行折行，返回行列表。

    为什么不用 ``QLabel.setWordWrap``（契约 §7）：``QLabel`` 开 wordWrap
    后 ``minimumSizeHint`` 高度几乎为 0，在布局里会被优先压缩；而且一旦对
    它调用过 ``setFixedHeight``，``heightForWidth()`` 就会退化成「返回这个
    固定高度」，控件因此再也缩不回去——窗口拉宽后描述下方会留出一大片
    空白。自行折行 + 显式锁高是确定性做法，缩放两个方向都成立。
    """
    if not text:
        return []
    width = max(1, int(width))
    lines, cur = [], ""
    for ch in text:
        if ch == "\n":
            lines.append(cur)
            cur = ""
            continue
        if fm.horizontalAdvance(cur + ch) > width and cur:
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    lines.append(cur)
    return lines


def _rgba(hex_color: str, alpha: float) -> str:
    """把 #RRGGBB 转为 QSS rgba() 字符串。"""
    qc = QColor(hex_color)
    return f"rgba({qc.red()},{qc.green()},{qc.blue()},{alpha})"


def _close_icon(d: int = 12) -> QIcon:
    """绘制主题感知的关闭 × 图标（``d`` 为图标边长）。"""
    pm = QPixmap(d, d)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(T("color.text.tertiary")))
    pen.setWidthF(1.5)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    # 以 12px 为设计基准按比例缩放，保证不同边长下线宽与留白一致
    k = d / 12.0
    lo, hi = 3.0 * k, 9.0 * k
    painter.drawLine(QPointF(lo, lo), QPointF(hi, hi))
    painter.drawLine(QPointF(hi, lo), QPointF(lo, hi))
    painter.end()
    return QIcon(pm)


def _type_icon(kind: str, color: str, d: int = ICON_D) -> QPixmap:
    """绘制 ``d`` × ``d`` 圆形类型图标（填充色 + 反白符号）。

    以 18px 为设计基准等比缩放：调用方只传边长，不传内部坐标。
    """
    pm = QPixmap(d, d)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    k = d / float(ICON_D)
    painter.setBrush(QColor(color))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(QPointF(d / 2.0, d / 2.0), (d / 2.0) - 1.0,
                        (d / 2.0) - 1.0)
    on = QColor(T("color.on.primary"))
    if kind == "success":
        pen = QPen(on)
        pen.setWidthF(1.8 * k)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.drawPolyline([
            QPointF(5.0 * k, 9.4 * k), QPointF(8.0 * k, 12.2 * k),
            QPointF(13.2 * k, 6.0 * k)])
    elif kind == "error":
        pen = QPen(on)
        pen.setWidthF(1.8 * k)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.drawLine(QPointF(6.2 * k, 6.2 * k),
                         QPointF(11.8 * k, 11.8 * k))
        painter.drawLine(QPointF(11.8 * k, 6.2 * k),
                         QPointF(6.2 * k, 11.8 * k))
    else:
        font = QFont()
        font.setPixelSize(max(1, int(T("font.md") * k)))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(on)
        painter.drawText(pm.rect(), Qt.AlignCenter,
                         "i" if kind == "info" else "!")
    painter.end()
    return pm


class Alert(QFrame):
    """警告提示条：页面内的醒目光反馈。

    参数:
        type: ``"info"`` / ``"success"`` / ``"warning"`` / ``"error"``。
        title: 标题文本（加粗）。
        description: 描述文本（可换行）。
        closable: 是否显示关闭按钮。
        parent: 父控件。

    示例::

        a = Alert("warning", "请注意", "配置尚未保存", closable=True)
        a.add_action("去保存", lambda: print("save"))
        layout.addWidget(a)
    """

    #: 关闭按钮点击后发射
    closed = Signal()

    #: 合法类型
    TYPES = ("info", "success", "warning", "error")

    def __init__(self, type: str = "info", title: str = "",
                 description: str = "", closable: bool = False,
                 parent: QWidget = None):
        super().__init__(parent)
        self._type = "info"
        self._multiline = None      # 图标对齐模式的当前值（None = 未定）
        self._locked_desc_h = None   # 描述被锁定的高度（None = 未锁定）
        self._layout = QHBoxLayout(self)
        # 上下同值（对称），左右取卡片内边距；间距取卡片 gap，比原先的
        # 10px 魔数更紧且落在 layout.* 令牌上
        self._layout.setContentsMargins(PAD_X, PAD_Y, PAD_X, PAD_Y)
        self._layout.setSpacing(T("layout.card.gap"))

        self._icon = QLabel(self)
        self._icon.setFixedSize(ICON_D, ICON_D)
        set_property(self._icon, "uikAl", "icon")
        self._layout.addWidget(self._icon, 0, Qt.AlignVCenter)

        col = QVBoxLayout()
        col.setSpacing(T("layout.card.title_gap"))
        self._title = QLabel(title, self)
        set_property(self._title, "uikAl", "title")
        self._title.setVisible(bool(title))
        self._desc_text = str(description)
        self._desc = QLabel(self)
        set_property(self._desc, "uikAl", "desc")
        # 关闭 wordWrap：换行由 _apply_desc_text() 自行折行 + 锁高完成，
        # 原因见 _wrap_text 的注释
        self._desc.setWordWrap(False)
        # 横向策略取 Ignored：QLabel 的 minimumSizeHint 宽度等于「折行后
        # 最长一行」的宽度，而那一行本来就是被可用宽度撑出来的——若让它参与
        # 最小宽度计算，Alert 的 minimumSizeHint 会锁死在首次布局的宽度上
        # （实测 resize 到更窄时控件根本不变窄，表现为「拉不窄」）。
        # Ignored = 宽度完全由布局分配，高度仍按锁定的行数走。
        self._desc.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self._desc.setVisible(bool(description))
        col.addWidget(self._title)
        col.addWidget(self._desc)
        self._layout.addLayout(col, 1)

        self._actions = QHBoxLayout()
        self._actions.setSpacing(T("layout.inline.gap"))
        self._layout.addLayout(self._actions)

        self._close = QToolButton(self)
        # 关闭按钮用 sm 档（22px），高度改由全局 QSS 的 [uiksize] 提供，
        # 本地 QSS 只描述颜色，不再写死高度，避免与尺寸令牌打架
        set_property(self._close, "uikAl", "close")
        set_property(self._close, "size", "sm")
        self._close.setCursor(Qt.PointingHandCursor)
        self._close.setVisible(closable)
        self._close.clicked.connect(self._on_close)
        self._layout.addWidget(self._close, 0, Qt.AlignVCenter)

        _connect_theme(self, self._reload_style)
        self.set_type(type)
        # 先按当前宽度铺一次文本：只依赖 resizeEvent 的话，一个从不被
        # resize 的实例（例如直接 addWidget 进未激活的布局）描述会是空的
        self._apply_desc_text()

    # -- 公开 API ---------------------------------------------------------
    def set_type(self, type: str) -> None:
        """设置提示类型。"""
        if type not in self.TYPES:
            raise ValueError(f"未知 Alert 类型: {type!r}，应为 {self.TYPES} 之一")
        self._type = type
        set_property(self, "type", type)
        self._reload_style()

    def type(self) -> str:
        return self._type

    def set_title(self, text: str) -> None:
        """设置标题（为空则隐藏）。"""
        self._title.setText(text)
        self._title.setVisible(bool(text))
        self._sync_align()

    def set_description(self, text: str) -> None:
        """设置描述（为空则隐藏）。"""
        self._desc_text = str(text)
        self._desc.setVisible(bool(text))
        self._apply_desc_text()
        self._sync_align()

    def add_action(self, text: str, callback=None) -> QPushButton:
        """追加一个操作链接按钮，点击时调用 ``callback()``。"""
        btn = QPushButton(text, self)
        set_property(btn, "uikAl", "action")
        set_property(btn, "size", "sm")
        btn.setCursor(Qt.PointingHandCursor)
        if callable(callback):
            btn.clicked.connect(lambda _=False: callback())
        self._actions.addWidget(btn)
        self._sync_align()
        return btn

    # -- 内部 -------------------------------------------------------------
    def _is_multiline(self) -> bool:
        """文本块是否占两行及以上。"""
        # 用 isHidden() 而非 isVisible()：构造期祖先尚未 show，isVisible()
        # 恒为 False，会把「有描述」误判成单行
        if self._desc.isHidden():
            return False
        if not self._title.isHidden():
            return True   # 标题 + 描述 = 至少两行
        # 只有描述：按当前可用宽度判断是否折行（宽度未定时视为单行）。
        # 比较的是**原始文本**而非已折行的 label.text()——后者含 '\n'，
        # horizontalAdvance 对多行串没有意义
        avail = self._desc.width() - 2
        if avail <= 1:
            return False
        return self._desc.fontMetrics().horizontalAdvance(
            self._desc_text.replace("\n", "")) > avail

    def _sync_align(self) -> None:
        """按文本块行数切换图标 / 关闭按钮的对齐方式。

        - 单行（只有标题，或只有一行描述）：图标与文字**垂直居中**，
          二者几何中心落在同一条水平线上（契约 §3「图标中心同线」）；
        - 多行（标题 + 描述，或描述折行）：改为**顶部对齐**——
          居中的图标会在多行文本块中间悬空，看上去比文字高一截。

        契约 §4 明确要求多行时图标顶部对齐而非垂直居中。
        """
        multiline = self._is_multiline()
        if multiline == self._multiline:
            return
        self._multiline = multiline
        align = Qt.AlignTop if multiline else Qt.AlignVCenter
        self._layout.setAlignment(self._icon, align)
        self._layout.setAlignment(self._close, align)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # 立刻按新宽度重排一次：resizeEvent 早于子布局激活，此时
        # self._desc.width() 还是旧值，直接折行会把「窄宽度下的断行结果」
        # 固化下来，控件变宽后底部留出一大片空白。activate() 是同步的。
        if self._layout is not None and not self._layout.isEmpty():
            self._layout.activate()
        self._apply_desc_text()
        self._sync_align()

    def _apply_desc_text(self) -> None:
        """按当前宽度重新折行并锁定描述高度（契约 §7）。"""
        if self._desc.isHidden():
            return
        fm = self._desc.fontMetrics()
        lines = _wrap_text(self._desc_text, fm, self._desc.width())
        wrapped = "\n".join(lines)
        if self._desc.text() != wrapped:
            self._desc.setText(wrapped)
        need = max(1, len(lines)) * fm.height()
        if self._locked_desc_h != need:
            self._locked_desc_h = need
            self._desc.setFixedHeight(need)
            self._sync_align()

    def _on_close(self) -> None:
        self.hide()
        self.closed.emit()

    def _main_color(self) -> str:
        return {"info": T("color.primary"),
                "success": T("color.success"),
                "warning": T("color.warning"),
                "error": T("color.danger")}[self._type]

    def _subtle_color(self) -> str:
        return {"info": T("color.primary.subtle"),
                "success": T("color.success.subtle"),
                "warning": T("color.warning.subtle"),
                "error": T("color.danger.subtle")}[self._type]

    def _reload_style(self) -> None:
        c = lambda k: T(f"color.{k}")  # noqa: E731
        main = self._main_color()
        self.setStyleSheet(f"""
Alert {{
    background-color: {self._subtle_color()};
    border: 1px solid {_rgba(main, 0.35)};
    border-radius: {T('radius.lg')}px;
}}
QLabel[uikAl="icon"] {{ background-color: transparent; }}
QLabel[uikAl="title"] {{
    color: {c('text.primary')};
    font-weight: {T('font.weight.semibold')};
    background-color: transparent;
}}
QLabel[uikAl="desc"] {{
    color: {c('text.secondary')};
    background-color: transparent;
}}
QPushButton[uikAl="action"] {{
    /* 1px 透明边框：让全局 [uiksize="sm"] 的内容盒 20px 凑成 22px 总高 */
    border: 1px solid transparent;
    background-color: transparent;
    color: {main};
    padding: 0 {T('layout.icon.gap')}px;
    font-size: {T('font.md')}px;
    font-weight: {T('font.weight.semibold')};
}}
QPushButton[uikAl="action"]:hover {{ color: {c('primary.hover')};
    background-color: {_rgba(main, 0.12)}; }}
QPushButton[uikAl="action"]:pressed {{ color: {c('primary.pressed')}; }}
QPushButton[uikAl="action"]:disabled {{ color: {c('text.disabled')}; }}
QToolButton[uikAl="close"] {{
    background-color: transparent;
    /* 保留 1px 透明边框：全局 [uiksize] 的 min/max-height 按「内容盒」
       给出（sm=20），加上这 1px 上下边框才是契约要求的 22px 总高；
       同时把基座 padding 4px 清零，否则总高会多出 8px 对不上刻度 */
    border: 1px solid transparent;
    padding: 0;
    border-radius: {T('radius.sm')}px;
}}
QToolButton[uikAl="close"]:hover {{
    background-color: {_rgba(main, 0.15)};
}}
QToolButton[uikAl="close"]:disabled {{ color: {c('text.disabled')}; }}
""")
        self._icon.setPixmap(_type_icon(self._type, main))
        self._close.setIcon(_close_icon())
        self._sync_align()