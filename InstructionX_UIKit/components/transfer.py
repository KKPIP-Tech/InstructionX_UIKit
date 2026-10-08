# -*- coding: utf-8 -*-
"""穿梭框组件（SPEC §5.1）。

``Transfer`` = 源列表 + 目标列表（双 ListWidget）+ 左右移动按钮，
支持多选移动、双击移动与标题定制。

对齐要点（本轨重点）：

- 两侧列表直接用 Kit 的 ``ListWidget``：行高 28px、文字左缘 8px（全局
  QSS 的 ``layout.inset.pad_x``）与页面上的表格 / 树 / 列表完全一致。此前
  这里用的是裸 ``QListWidget``，行高随默认样式漂、字号也降一级，两侧
  面板和同页其它数据视图并排时明显不齐。
- 列表标题左缘同样缩进一个 ``layout.inset.pad_x``，与列表内文字左缘对齐，
  形成一条贯穿面板的左缘基准线。
- 间距全部取 ``layout.*`` / ``space.*`` 令牌，不再有 8 / 4 这样的字面量。
"""

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..icons import get_icon
from ..theme import T, ThemeManager, set_font, set_property
from .list_view import ListWidget

__all__ = ["Transfer"]

#: 面板最小边长（px）= 2 × space.16 + space.8，两侧面板同尺寸
_PANEL_MIN = T("space.16") * 2 + T("space.8")
#: 移动按钮边长（px）= space.10
_BTN_W = T("space.10")
#: 按钮内图标边长（px）= space.5
_BTN_ICON = T("space.5")
#: 纯图标按钮的水平内边距（px）= space.2。按钮通体的 `padding: 0 12px` 是给
#: 带文字按钮定的；40px 宽的纯图标按钮扣掉 24px 横向内边距和 2px 边框后
#: 内容区只剩 14px，16px 的图标会被挤扁 —— 必须单独收窄。
_BTN_PAD_X = T("space.2")


class _IconButton(QPushButton):
    """纯图标按钮：把 enter / leave 转成信号。

    图标是调用时烘进 ``QIcon`` 的位图，QSS 的 ``:hover { color: primary }``
    作用不到它身上，必须在鼠标进出时按新颜色重烘一次，否则边框变主色而
    图标不变，按钮看起来少了一半反馈。``QPushButton`` 本身没有
    ``entered`` / ``exited`` 信号（只有 ``enterEvent`` / ``leaveEvent``
    受保护虚函数），所以在这里转一道。
    """

    hovered_changed = Signal(bool)

    def enterEvent(self, event):  # noqa: N802 - Qt 回调
        super().enterEvent(event)
        self.hovered_changed.emit(True)

    def leaveEvent(self, event):  # noqa: N802 - Qt 回调
        super().leaveEvent(event)
        self.hovered_changed.emit(False)


class Transfer(QWidget):
    """穿梭框。

    用途:
        在两个列表之间移动条目（如权限分配、字段挑选）。
        选中若干项后点击方向按钮移动，也可双击单项移动。

    参数:
        items: 初始全部条目（默认放入源列表）。
        source_title / target_title: 左右列表标题。
        parent: 父控件。

    示例::

        tr = Transfer(["苹果", "香蕉", "橙子", "葡萄"])
        tr.changed.connect(lambda target: print("已选:", target))
        print(tr.target_items())
    """

    #: 目标列表变化信号（参数为目标条目文案列表）
    changed = Signal(list)

    def __init__(self, items=(), source_title: str = "源列表",
                 target_title: str = "目标列表", parent=None):
        super().__init__(parent)
        set_property(self, "role", "plain")
        self._source_title = self._make_title(source_title)
        self._target_title = self._make_title(target_title)
        self._source = ListWidget(parent=self)
        self._target = ListWidget(parent=self)
        for lst in (self._source, self._target):
            lst.setSelectionMode(ListWidget.ExtendedSelection)
            lst.setMinimumHeight(_PANEL_MIN)
            lst.setMinimumWidth(_PANEL_MIN)
        self._btn_right = _IconButton(self)
        self._btn_left = _IconButton(self)
        for btn in (self._btn_right, self._btn_left):
            set_property(btn, "size", "md")
            btn.setFixedWidth(_BTN_W)
            btn.setStyleSheet(f"padding: 0 {_BTN_PAD_X}px;")
            # QPushButton 的 iconSize 默认取 style 的 PM_SmallIconSize（16px），
            # Qt 绘制时会按它把 QIcon 缩小——图标画成 20px 也会被压回 16px。
            btn.setIconSize(QSize(_BTN_ICON, _BTN_ICON))
            btn.hovered_changed.connect(lambda _h: self._apply_btn_icons())
        self._apply_btn_icons()
        ThemeManager.instance().theme_changed.connect(self._on_theme_changed)
        self._btn_right.setToolTip("移动选中项到目标列表")
        self._btn_left.setToolTip("移动选中项回源列表")
        self._btn_right.clicked.connect(lambda: self._move(self._source, self._target))
        self._btn_left.clicked.connect(lambda: self._move(self._target, self._source))
        self._source.itemDoubleClicked.connect(
            lambda _item: self._move(self._source, self._target))
        self._target.itemDoubleClicked.connect(
            lambda _item: self._move(self._target, self._source))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(T("layout.inline.gap"))
        left = QVBoxLayout()
        left.setSpacing(T("space.1"))
        left.addWidget(self._source_title)
        left.addWidget(self._source, 1)
        layout.addLayout(left, 1)
        mid = QVBoxLayout()
        mid.setSpacing(T("space.1"))
        mid.addStretch(1)
        mid.addWidget(self._btn_right, 0, Qt.AlignHCenter)
        mid.addWidget(self._btn_left, 0, Qt.AlignHCenter)
        mid.addStretch(1)
        layout.addLayout(mid)
        right = QVBoxLayout()
        right.setSpacing(T("space.1"))
        right.addWidget(self._target_title)
        right.addWidget(self._target, 1)
        layout.addLayout(right, 1)

        self._all = []
        if items:
            self.set_items(items, emit=False)

    @staticmethod
    def _make_title(text: str) -> QLabel:
        """面板标题：次要色 + 左缘缩进一个内边距单位，与列表文字对齐。"""
        label = QLabel(text)
        set_property(label, "role", "secondary")
        set_font(label, "sm", "medium")
        label.setStyleSheet(
            f"{label.styleSheet()}padding-left: {T('layout.inset.pad_x')}px;")
        return label

    # ------------------------------------------------------------------
    # 数据接口
    # ------------------------------------------------------------------

    def set_items(self, items, emit: bool = True) -> None:
        """设置全部条目（重置为：全部在源列表，目标列表清空）。

        参数:
            items: 新条目（重置后全部位于源列表）。
            emit: 是否发射 ``changed`` 信号。构造路径传 ``False``，
                此时静默重置——``changed`` 仅在构造完成后的变更时发射
                （构造期间连接监听的应用收不到初始事件是预期行为）。
        """
        self._all = [str(x) for x in items]
        self._source.clear()
        self._target.clear()
        for text in self._all:
            QListWidgetItem(text, self._source)
        if emit:
            self._emit_changed()

    def source_items(self) -> list:
        """源列表条目文案。"""
        return [self._source.item(i).text() for i in range(self._source.count())]

    def target_items(self) -> list:
        """目标列表条目文案。"""
        return [self._target.item(i).text() for i in range(self._target.count())]

    def set_target_items(self, items) -> None:
        """指定目标条目；其余（在全集中）留在源列表。"""
        targets = [str(x) for x in items]
        self._source.clear()
        self._target.clear()
        for text in self._all:
            if text in targets:
                QListWidgetItem(text, self._target)
            else:
                QListWidgetItem(text, self._source)
        # 允许目标包含全集之外的条目
        for text in targets:
            if text not in self._all:
                QListWidgetItem(text, self._target)
        self._emit_changed()

    def set_titles(self, source_title: str, target_title: str) -> None:
        """修改左右列表标题。"""
        self._source_title.setText(source_title)
        self._target_title.setText(target_title)

    # ------------------------------------------------------------------
    # 移动按钮图标
    # ------------------------------------------------------------------
    # 这里原先用文本字符 "→" / "←" 当图标，实际渲染出来几乎认不出：
    # 一是箭头字形依赖字体，运行环境没装 Segoe UI 时会回退到中文字体，
    #   画出来是一根发丝般的细线；二是 14px 的字符压在 28px 高的按钮里
    #   占比过小，斜向笔画的抗锯齿把它糊成一团。
    # 改为走 icons 的矢量图标（唯一适配入口），并跟随主题重绘 —— 图标是
    # 调用时烘进 QIcon 的位图，不重绘的话切到暗色会留下一枚亮色箭头。

    def _apply_btn_icons(self) -> None:
        # 图标是调用时烘进 QIcon 的位图，所以 hover / 切主题都要重烘一次；
        # 否则边框变主色而图标还是常规色，按钮看起来少了一半反馈。
        for btn, name in ((self._btn_right, "arrow_right"),
                          (self._btn_left, "arrow_left")):
            color = (T("color.primary") if btn.underMouse()
                     else T("color.text.primary"))
            btn.setIcon(get_icon(name, size=_BTN_ICON, color=color))

    def _on_theme_changed(self, _mode) -> None:
        self._apply_btn_icons()

    # ------------------------------------------------------------------
    # 移动逻辑
    # ------------------------------------------------------------------

    def _move(self, src: ListWidget, dst: ListWidget) -> None:
        rows = sorted((src.row(i) for i in src.selectedItems()), reverse=True)
        if not rows:
            return
        # 逆序取出避免行号位移，再按原相对顺序追加到目标列表
        taken = [src.takeItem(row) for row in rows]
        for item in reversed(taken):
            if item is not None:
                dst.addItem(item)
        dst.clearSelection()
        self._emit_changed()

    def _emit_changed(self) -> None:
        self.changed.emit(self.target_items())