# -*- coding: utf-8 -*-
"""Demo 演示页公共脚手架。

提供统一的「页头 + 卡片分区」页面骨架，以及代码块、色块、动画卡片等辅助件。

视觉规则（与 Kit 令牌保持一致）：

- 页面底色用 ``role="canvas"``，分区卡片用 ``role="card"``，
  卡片浮在画布上形成「画布 → 面」的层次，而不是所有元素同色铺平；
- 纯布局容器（:func:`row` / :func:`col`）标记 ``role="plain"`` 显式透明，
  避免在卡片内形成与卡片不同色的色块；
- 标题层级固定为「页头 title.lg → 卡片标题 title.sm → 正文 md → 提示 sm」，
  颜色依次为 text.primary / text.secondary / text.tertiary。

自绘元素通过 ``T()`` 取令牌并在 ``theme_changed`` 时刷新，
保证亮 / 暗主题切换后无需重启即可正确换肤。
"""

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from InstructionX_UIKit.theme import T, ThemeManager, set_font, set_property
from InstructionX_UIKit.tokens import MONO_FAMILY

__all__ = [
    "make_page",
    "Card",
    "Section",
    "row",
    "col",
    "ColorBlock",
    "DemoCard",
    "CodeBlock",
    "hint_label",
    "code_label",
    "usage_section",
]


# ---------------------------------------------------------------------------
# 基础标签
# ---------------------------------------------------------------------------

def _label(text: str, size_key: str, weight: str, role: str) -> QLabel:
    """按「字阶 + 字重 + 文字角色」构造 QLabel（三个维度分离，避免各处硬编码）。

    字号 / 字重走 ``set_font``（实例级 QSS）：全局 ``QWidget { font-size }``
    会覆盖 ``setFont``，直接用 setFont 会让所有层级塌缩成同一字号。
    """
    lab = QLabel(text)
    set_font(lab, size_key, weight)
    set_property(lab, "role", role)
    return lab


def _wrap_text(text: str, fm: QFontMetricsF, max_w: int) -> list:
    """按像素宽度把文本折成多行（逐字符断行，兼容中英混排）。

    为什么不用 ``QLabel.setWordWrap``：换行标签在 ``QScrollArea`` 的
    ``QVBoxLayout`` 里会被压扁——QLabel 的 ``minimumSizeHint`` 高度几乎为 0
    （「总能换行」），视口高度不足时布局优先压缩它，于是页面说明被压成一行、
    第二行被下一张卡片盖住（实测 ``height()=19`` 而 ``heightForWidth()=38``）。
    自行折行后高度 = 行数 × 行高，完全确定，不再依赖布局协商。
    """
    lines, cur = [], ""
    for ch in text:
        if ch == "\n":
            lines.append(cur)
            cur = ""
            continue
        if cur and fm.horizontalAdvance(cur + ch) > max_w:
            lines.append(cur.rstrip())
            cur = "" if ch == " " else ch
        else:
            cur += ch
    lines.append(cur.rstrip())
    return lines or [""]


def _multiline_label(text: str, max_w: int) -> QLabel:
    """按固定版心预折行的高度确定型标签（不启用 wordWrap）。"""
    lab = QLabel()
    set_property(lab, "role", "secondary")
    fm = QFontMetricsF(lab.font())
    lines = _wrap_text(text, fm, max_w)
    lab.setText("\n".join(lines))
    lab.setFixedHeight(len(lines) * fm.lineSpacing() + 3)
    return lab


def _title_label(text: str) -> QLabel:
    """页面主标题：title.lg + bold，页面唯一的最大字号。"""
    return _label(text, "font.title.lg", "bold", "primary")


def hint_label(text: str, role: str = "secondary", max_w: int = 0) -> QLabel:
    """说明 / 提示文字：次要或三级色。

    参数:
        text: 文本。
        role: ``secondary`` / ``tertiary`` / ``hint``。
        max_w: >0 时按该像素宽度**预折行**并锁定高度（版心固定、不会被布局压扁）；
            0 则启用 wordWrap 随容器自适应宽度（适合卡���内宽度不确定的说明）。
    """
    if max_w > 0:
        lab = _multiline_label(text, max_w)
        set_property(lab, "role", role)
        return lab
    lab = QLabel(text)
    lab.setWordWrap(True)
    set_property(lab, "role", role)
    return lab


#: 代码块版心（px）：等宽字体按此宽度折行，高度可确定，不受布局挤压影响
_CODE_MEASURE = 1000


def code_label(code: str) -> QLabel:
    """单行等宽代码标签（第三级文字色），用于 :class:`CodeBlock` 内部。

    超长代码行按等宽字符宽度**预先折行**并锁定高度——同样是为了避开
    ``QScrollArea`` 布局对换行标签的挤压（说明见 :func:`hint_label`）。
    """
    lab = QLabel()
    lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
    set_property(lab, "role", "tertiary")
    px = T("font.sm")
    fam = MONO_FAMILY.replace('"', "")
    qss = (f'font-family: {fam}; font-size: {px}px; '
           f'font-weight: {T("font.weight.regular")};')
    lab.setStyleSheet(qss)
    # 先应用样式再量字体，确保折行宽度与实际渲染一致
    fm = QFontMetricsF(lab.font())
    per_line = max(int(fm.horizontalAdvance("M")) or 1, 1)
    ncols = max(_CODE_MEASURE // per_line, 20)
    out = []
    for raw in code.split("\n"):
        while len(raw) > ncols:
            cut = raw.rfind(" ", 0, ncols)
            cut = cut if cut > ncols * 0.6 else ncols
            out.append(raw[:cut].rstrip())
            raw = raw[cut:].lstrip()
        out.append(raw)
    lab.setText("\n".join(out))
    lab.setFixedHeight(len(out) * fm.lineSpacing() + 2)
    return lab


# ---------------------------------------------------------------------------
# 卡片
# ---------------------------------------------------------------------------

class Card(QFrame):
    """分区卡片：细边框 + 圆角 + 悬浮标题（替代 QGroupBox 的「标题压边框」样式）。

    标题作为真实子控件而非 ``QGroupBox::title``，因此不依赖父级底色做
    「挖空」，放在任何背景上都不会出现横线穿字。

    参数:
        title: 卡片标题（None 表示无标题区）。
        description: 标题下方的补充说明（可选）。
        spacing: 内容区子项间距。
        dense: True 时收紧内边距（用于密集控件演示）。
    """

    def __init__(self, title: str | None = None, description: str = "",
                 spacing: int = 8, dense: bool = False, parent=None):
        super().__init__(parent)
        set_property(self, "role", "card")

        outer = QVBoxLayout(self)
        # 内边距 / 间距一律引用 layout.* 令牌，避免页面间对齐关系漂移
        outer.setContentsMargins(
            T("layout.card.pad_x"),
            T("layout.card.pad_top"),
            T("layout.card.pad_x"),
            T("layout.card.pad_bottom") if not dense else T("layout.inset.pad_y") * 2,
        )
        outer.setSpacing(T("layout.card.gap") if not dense else T("space.1"))

        if title is not None:
            outer.addWidget(self._build_header(title, description))
            outer.addSpacing(2 if description else 0)

        # 内容区：对外暴露的 layout() 就是它，Section() 的既有调用方式不变
        self._body = QVBoxLayout()
        self._body.setContentsMargins(0, 0, 0, 0)
        self._body.setSpacing(spacing or T("layout.card.gap"))
        outer.addLayout(self._body)

    def _build_header(self, title: str, description: str) -> QWidget:
        """卡片头：标题 + 可选说明（说明在标题下方，弱化为次要色）。"""
        host = QWidget()
        set_property(host, "role", "plain")
        lay = QVBoxLayout(host)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(T("layout.card.title_gap"))
        lay.addWidget(_label(title, "font.title.sm", "semibold", "primary"))
        if description:
            lab = hint_label(description, role="tertiary")
            lay.addWidget(lab)
        return host

    def layout(self):  # noqa: A003 - 刻意覆盖，兼容既有 Section(...).layout() 调用
        """返回卡片内容区布局。"""
        return self._body


def Section(title: str, spacing: int = 8, description: str = "") -> Card:
    """分区容器（现代卡片）。

    用法::

        box = Section("基础用法")
        box.layout().addWidget(some_widget)
    """
    return Card(title, description=description, spacing=spacing)


def CodeBlock(code: str, caption: str = "") -> QWidget:
    """代码块：等宽底色 + 圆角内边距，替代裸灰字代码行。

    参数:
        code: 代码文本（按 ``\\n`` 分行渲染）。
        caption: 可选的标题行（如语言名 / 说明）。
    """
    host = QWidget()
    set_property(host, "role", "code")
    lay = QVBoxLayout(host)
    pad = T("layout.code.pad")
    lay.setContentsMargins(pad, T("layout.inset.pad_y"), pad, T("layout.inset.pad_y"))
    lay.setSpacing(T("space.05"))

    if caption:
        cap = _label(caption, "font.xs", "medium", "tertiary")
        lay.addWidget(cap)

    for line in code.split("\n"):
        lab = code_label(line)
        lay.addWidget(lab)
    if not code.strip():
        lay.addWidget(code_label(" "))
    return host


def usage_section(code: str) -> QWidget:
    """「用法」分区：展示该演示对应的最小 Kit 调用代码。

    扁平化处理：**不做成卡片**。原实现是「卡片 + 代码块」双层嵌套，
    既多一圈边框又多一整块留白。改为纯透明容器 + 小号「用法」标签 +
    单层代码块底色，把纵向空间还给真正的组件演示（多数页面一屏能多放
    一整组演示）。

    用法::

        page = make_page(title, desc, [usage_section('Button("确定", variant="primary")')])
    """
    host = QWidget()
    set_property(host, "role", "plain")
    lay = QVBoxLayout(host)
    # 左右各缩进一个卡片内边距：使「用法」标签与卡片标题左缘对齐、
    # 代码块与卡片内容左右两缘都对齐（否则这两块会比卡片整体偏左 12px）
    _px = T("layout.card.pad_x")
    lay.setContentsMargins(_px, 0, _px, 0)
    lay.setSpacing(T("layout.card.title_gap") + T("space.1"))
    lay.addWidget(_label("用法", "font.sm", "semibold", "tertiary"))
    lay.addWidget(CodeBlock(code))
    return host


# ---------------------------------------------------------------------------
# 布局辅助
# ---------------------------------------------------------------------------

def row(*widgets, spacing: int = 0) -> QWidget:
    """水平一行（左对齐，末尾拉伸）。

    既接受 QWidget，也接受 QLayout；常用于把若干控件排成一行。
    """
    host = QWidget()
    set_property(host, "role", "plain")
    lay = QHBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(spacing or T("layout.inline.gap"))
    for w in widgets:
        if isinstance(w, QWidget):
            lay.addWidget(w)
        elif w is not None:
            lay.addLayout(w)
    lay.addStretch(1)
    return host


class _FlowLayout(QLayout):
    """按可用宽度自动换行的横向布局。

    工具条这类「控件多、单个都窄」的场景用 QHBoxLayout 会被整行控件的
    宽度之和顶死最小宽度：窗口一窄，不是控件被挤扁，就是整页被撑出一条
    横向滚动条。编辑器工具条（语言/字体/字号 + 一排开关）就是这样。

    关键点是 ``minimumSize().width()`` 只取**最宽的单个控件**，而不是
    所有控件之和 —— 这样容器才真的能收缩，行数由 ``heightForWidth`` 决定。
    """

    def __init__(self, parent=None, spacing: int = 6, row_spacing: int = 6):
        super().__init__(parent)
        self._items: list = []
        self._spacing = spacing
        self._row_spacing = row_spacing

    def addItem(self, item):  # noqa: N802 - Qt 回调
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):  # noqa: N802 - Qt 回调
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):  # noqa: N802 - Qt 回调
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):  # noqa: N802 - Qt 回调
        return Qt.Orientation(0)

    def hasHeightForWidth(self):  # noqa: N802 - Qt 回调
        return True

    def heightForWidth(self, width):  # noqa: N802 - Qt 回调
        return self._arrange(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect):  # noqa: N802 - Qt 回调
        super().setGeometry(rect)
        self._arrange(rect, apply=True)

    def sizeHint(self):  # noqa: N802 - Qt 回调
        return self._natural_size()

    def minimumSize(self):  # noqa: N802 - Qt 回调
        # 宽度只取最宽的单个控件，行数交给 heightForWidth，否则永远收不回来
        size = QSize(0, 0)
        for it in self._items:
            size = size.expandedTo(it.minimumSize())
        return size

    def _natural_size(self) -> QSize:
        """无约束时的自然尺寸：单行铺开。"""
        w = h = 0
        for it in self._items:
            hint = it.sizeHint()
            w += hint.width() + self._spacing
            h = max(h, hint.height())
        return QSize(max(0, w - self._spacing) if self._items else 0, h)

    def _arrange(self, rect: QRect, apply: bool) -> int:
        x, y, line_h = rect.x(), rect.y(), 0
        for it in self._items:
            hint = it.sizeHint()
            w, h = hint.width(), hint.height()
            if line_h > 0 and x + w > rect.x() + rect.width():
                x = rect.x()
                y += line_h + self._row_spacing
                line_h = 0
            if apply:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x += w + self._spacing
            line_h = max(line_h, h)
        return y + line_h - rect.y()


def flow_row(*widgets, spacing: int = 0, row_spacing: int = 0) -> QWidget:
    """水平一行，空间不够时自动折行（末尾不拉伸，占满整行宽度）。

    与 :func:`row` 的区别只在于会不会换行；控件参数完全一致。
    """
    host = QWidget()
    set_property(host, "role", "plain")
    lay = _FlowLayout(
        host,
        spacing or T("layout.inline.gap"),
        row_spacing or T("layout.card.gap"),
    )
    for w in widgets:
        if isinstance(w, QWidget):
            lay.addWidget(w)
        elif w is not None:
            lay.addLayout(w)
    return host


def col(*widgets, spacing: int = 0) -> QWidget:
    """垂直一列（顶部对齐，末尾拉伸）。"""
    host = QWidget()
    set_property(host, "role", "plain")
    lay = QVBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(spacing or T("layout.inline.gap"))
    for w in widgets:
        if isinstance(w, QWidget):
            lay.addWidget(w)
        elif w is not None:
            lay.addLayout(w)
    lay.addStretch(1)
    return host


def make_page(title: str, description: str, sections) -> QScrollArea:
    """组装一个完整演示页（滚动容器）。

    页面结构：画布底 → 页头（标题 + 说明）→ 卡片分区列表。
    分区之间留 16px 间距，卡片自身 1px 边框 + 12px 圆角。

    返回:
        QScrollArea；其 ``widget()`` 为内容根控件（供整页 grab() 截图）。
    """
    content = QWidget()
    set_property(content, "role", "canvas")
    lay = QVBoxLayout(content)
    pad = T("layout.page.pad")   # 四边同值：左右边距严格对称
    lay.setContentsMargins(pad, pad, pad, pad)
    lay.setSpacing(T("layout.gutter"))
    # 关键：页面装在 QScrollArea 里。若不加这条约束，视口高度不足时
    # QVBoxLayout 会优先压缩「可收缩」控件——QLabel 首当其冲，于是换行的
    # 页面说明会被压成一行、第二行被下一张卡片盖住（实测 label 高 19px 而
    # heightForWidth 需要 38px）。SetMinimumSize 让控件最小尺寸等于布局
    # 最小尺寸，内容装不下时改为滚动而不是挤压。
    lay.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)

    # 页头：标题 + 说明之间留 6px，页头与首张卡片之间由 spacing 统一
    head = QWidget()
    set_property(head, "role", "plain")
    head_lay = QVBoxLayout(head)
    head_lay.setContentsMargins(0, 0, 0, 0)
    head_lay.setSpacing(T("layout.header.gap"))
    head_lay.addWidget(_title_label(title))
    if description:
        # 版心固定 880px：既避免大屏上一行拉到 2000px，又让高度可确定
        head_lay.addWidget(hint_label(description, max_w=880))
    lay.addWidget(head)

    for sec in sections:
        if sec is not None:
            lay.addWidget(sec)
    lay.addStretch(1)

    scroll = QScrollArea()
    scroll.setWidget(content)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.viewport().setProperty("role", "canvas")
    return scroll


# ---------------------------------------------------------------------------
# 演示辅助件
# ---------------------------------------------------------------------------

class ColorBlock(QWidget):
    """主题感知色块：圆角矩形 + 居中文字，常用作布局 / 动画的演示目标。

    参数:
        text: 居中显示的文字。
        color_key: 令牌键（不含 ``color.`` 前缀），如 ``"primary"``。
        size: (宽, 高)。
        text_on: 文字色令牌键，默认 ``on.primary``（深色文字场景可改）。
    """

    def __init__(self, text: str = "", color_key: str = "primary",
                 size=(120, 72), text_on: str = "on.primary", parent=None):
        super().__init__(parent)
        self._text = text
        self._key = color_key
        self._on = text_on
        self.setMinimumSize(*size)
        ThemeManager.instance().theme_changed.connect(lambda *_: self.update())

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(T(f"color.{self._key}")))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1),
                                T("radius.lg"), T("radius.lg"))
        if self._text:
            font = QFont()
            font.setPixelSize(T("font.md"))
            font.setWeight(QFont.Weight(T("font.weight.medium")))
            painter.setFont(font)
            painter.setPen(QPen(QColor(T(f"color.{self._on}"))))
            painter.drawText(self.rect(), Qt.AlignCenter, self._text)
        painter.end()


class DemoCard(QFrame):
    """动画演示卡片：标题 + 演示区 + 「播放」按钮。

    参数:
        title: 卡片标题（动画名称）。
        demo: 演示元件控件。
        play: 点击「播放」时执行的可调用对象（重发动画）。
        hint: 动画的简短说明。
        demo_height: 演示区最小高度。
    """

    def __init__(self, title: str, demo: QWidget, play, hint: str = "",
                 demo_height: int = 130, parent=None):
        super().__init__(parent)
        set_property(self, "role", "card")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(
            T("layout.card.pad_x"), T("layout.card.pad_top"),
            T("layout.card.pad_x"), T("layout.card.pad_bottom"))
        lay.setSpacing(T("layout.card.gap"))

        lay.addWidget(_label(title, "font.title.sm", "semibold", "primary"))

        if hint:
            lay.addWidget(hint_label(hint, role="tertiary"))

        demo_wrap = QWidget()
        set_property(demo_wrap, "role", "plain")
        demo_lay = QVBoxLayout(demo_wrap)
        demo_lay.setContentsMargins(0, T("space.05"), 0, T("space.05"))
        demo_lay.addWidget(demo, 0, Qt.AlignCenter)
        demo_wrap.setMinimumHeight(demo_height)
        lay.addWidget(demo_wrap, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        play_btn = QPushButton("播放")
        set_property(play_btn, "size", "sm")
        play_btn.clicked.connect(self._safe_play)
        btn_row.addWidget(play_btn)
        lay.addLayout(btn_row)

        self._play = play
        self.play_button = play_btn

    def _safe_play(self):
        """执行播放回调（吞掉异常以免打断 Demo 交互）。"""
        try:
            self._play()
        except Exception:  # noqa: BLE001
            pass
