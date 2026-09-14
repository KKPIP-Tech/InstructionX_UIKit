# -*- coding: utf-8 -*-
"""编辑器浮层面板（CE_SPEC §2.1）：查找替换栏、补全弹窗、悬停气泡。

三者均为 CodeEditor 的内嵌浮层：面板用 ``bg.elevated + border`` 自绘，
``setAutoFillBackground(False)`` + 实例级透明 / 自绘背景，防全局 QSS 污染。
"""

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..theme import T, ThemeManager

__all__ = ["FindReplaceBar", "CompletionPopup", "HoverBubble"]

#: 补全项 kind -> 色块颜色（令牌键或 hex）
_KIND_COLORS = {
    "keyword": "color.primary",
    "function": "color.success",
    "method": "color.success",
    "class": "color.warning",
    "type": "color.warning",
    "variable": "color.text.secondary",
    "snippet": "color.danger",
    "module": "color.primary",
    "property": "color.text.secondary",
    "text": "color.text.tertiary",
}


def _bind_theme(fn) -> None:
    """订阅主题切换；控件销毁后回调静默忽略（防悬挂连接）。"""

    def _cb(_mode):
        try:
            fn()
        except RuntimeError:
            pass

    ThemeManager.instance().theme_changed.connect(_cb)


def _panel_qss() -> str:
    """浮层面板 QSS（bg.elevated + border 自绘面板）。"""
    return (
        "QFrame#uikCePanel {"
        f"background: {T('color.bg.elevated')};"
        f"border: 1px solid {T('color.border')};"
        f"border-radius: {T('radius.md')}px;"
        "}"
    )


def _make_button(text: str, checkable=False, tooltip="") -> QToolButton:
    btn = QToolButton()
    btn.setText(text)
    btn.setCheckable(checkable)
    btn.setAutoRaise(True)
    btn.setFixedSize(24, 24)
    btn.setFocusPolicy(Qt.NoFocus)
    if tooltip:
        btn.setToolTip(tooltip)
    btn.setStyleSheet(
        "QToolButton { border: none; background: transparent;"
        f" color: {T('color.text.secondary')}; font-family: monospace;"
        f" border-radius: {T('radius.sm')}px; }}"
        f"QToolButton:hover {{ background: {T('color.bg.muted')}; }}"
        f"QToolButton:checked {{ background: {T('color.primary.subtle')};"
        f" color: {T('color.primary')}; }}"
    )
    return btn


# ---------------------------------------------------------------------------
# 查找替换栏
# ---------------------------------------------------------------------------

class FindReplaceBar(QFrame):
    """编辑器内嵌顶部右侧查找替换浮条。

    功能：匹配计数 ``n/m``、大小写 / 整词 / 正则切换、上一个 / 下一个、
    替换 / 全部替换、Esc 关闭。搜索逻辑委托给所属 ``CodeEditor``。
    """

    #: 请求关闭
    close_requested = Signal()

    def __init__(self, editor, parent=None):
        super().__init__(parent or editor)
        self._editor = editor
        self.setObjectName("uikCePanel")
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(_panel_qss())
        _bind_theme(lambda: self.setStyleSheet(_panel_qss()))

        # -- 查找行 --
        self.find_edit = QLineEdit()
        self.find_edit.setPlaceholderText("查找")
        self.find_edit.setFixedWidth(180)
        self.count_label = QLabel("0/0")
        self.count_label.setStyleSheet(
            f"color: {T('color.text.tertiary')}; border: none;")
        self.case_btn = _make_button("Aa", True, "区分大小写")
        self.word_btn = _make_button("ab", True, "全字匹配")
        self.regex_btn = _make_button(".*", True, "正则表达式")
        self.prev_btn = _make_button("↑", False, "上一个 (Shift+Enter)")
        self.next_btn = _make_button("↓", False, "下一个 (Enter)")
        self.close_btn = _make_button("×", False, "关闭 (Esc)")

        row1 = QHBoxLayout()
        row1.setContentsMargins(6, 4, 6, 2)
        row1.setSpacing(2)
        row1.addWidget(self.find_edit)
        row1.addWidget(self.count_label)
        row1.addWidget(self.case_btn)
        row1.addWidget(self.word_btn)
        row1.addWidget(self.regex_btn)
        row1.addWidget(self.prev_btn)
        row1.addWidget(self.next_btn)
        row1.addWidget(self.close_btn)

        # -- 替换行 --
        self.replace_edit = QLineEdit()
        self.replace_edit.setPlaceholderText("替换")
        self.replace_edit.setFixedWidth(180)
        self.replace_btn = _make_button("→", False, "替换当前")
        self.replace_all_btn = _make_button("⇉", False, "全部替换")
        self._replace_row = QWidget()
        row2 = QHBoxLayout(self._replace_row)
        row2.setContentsMargins(6, 0, 6, 4)
        row2.setSpacing(2)
        row2.addWidget(self.replace_edit)
        row2.addWidget(self.replace_btn)
        row2.addWidget(self.replace_all_btn)
        row2.addStretch(1)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addLayout(row1)
        lay.addWidget(self._replace_row)
        self._replace_row.setVisible(False)

        # -- 信号 --
        self.find_edit.textChanged.connect(lambda _t: self._editor.find_update())
        self.case_btn.toggled.connect(lambda _v: self._editor.find_update())
        self.word_btn.toggled.connect(lambda _v: self._editor.find_update())
        self.regex_btn.toggled.connect(lambda _v: self._editor.find_update())
        self.find_edit.returnPressed.connect(self._editor.find_next)
        self.replace_edit.returnPressed.connect(self._editor.replace_current)
        self.prev_btn.clicked.connect(self._editor.find_prev)
        self.next_btn.clicked.connect(self._editor.find_next)
        self.replace_btn.clicked.connect(self._editor.replace_current)
        self.replace_all_btn.clicked.connect(self._editor.replace_all)
        self.close_btn.clicked.connect(self.close_requested.emit)

    # -- 状态 --------------------------------------------------------------
    def open(self, replace: bool = False, seed: str = "") -> None:
        """显示浮条；``replace=True`` 展开替换行；``seed`` 预填查找词。"""
        self._replace_row.setVisible(replace)
        if seed:
            self.find_edit.setText(seed)
        self.show()
        self.raise_()
        self.adjustSize()
        self.find_edit.setFocus()
        self.find_edit.selectAll()
        self._editor.find_update()

    def options(self) -> dict:
        """当前查找选项。"""
        return {
            "case": self.case_btn.isChecked(),
            "word": self.word_btn.isChecked(),
            "regex": self.regex_btn.isChecked(),
        }

    def pattern(self) -> str:
        return self.find_edit.text()

    def replacement(self) -> str:
        return self.replace_edit.text()

    def set_count(self, current: int, total: int) -> None:
        """更新匹配计数 ``n/m``（无匹配时 ``0/0``）。"""
        if total <= 0:
            self.count_label.setText("0/0" if self.pattern() else "")
        else:
            self.count_label.setText(f"{current}/{total}")

    def keyPressEvent(self, event):  # noqa: N802 - Qt 命名
        if event.key() == Qt.Key_Escape:
            self.close_requested.emit()
            return
        if (event.key() == Qt.Key_Return
                and event.modifiers() & Qt.ShiftModifier):
            self._editor.find_prev()
            return
        super().keyPressEvent(event)


# ---------------------------------------------------------------------------
# 补全弹窗
# ---------------------------------------------------------------------------

class CompletionPopup(QFrame):
    """补全弹窗（provider 驱动）。

    列表项：kind 图标色块 + label + detail；↑↓ 选择、Enter/Tab 确认、
    Esc 取消（按键由 CodeEditor 转发）。

    窗口标志刻意使用 ``Qt.ToolTip``（而非 ``Qt.Popup``）：``Qt.Popup``
    在 ``show()`` 时会对键盘 / 鼠标做隐式抓取（grab），把后续击键全部
    重定向到弹窗，文本区收不到输入，表现为「一弹出就卡死」；
    ``Qt.ToolTip`` + ``WA_ShowWithoutActivating`` 不抢焦点、不抓取输入，
    击键始终留在文本区（与 ``HoverBubble`` 同一策略）。
    """

    #: 确认某补全项，参数为插入文本
    item_chosen = Signal(str)

    def __init__(self, editor, parent=None):
        super().__init__(parent or editor)
        self._editor = editor
        self.setObjectName("uikCePanel")
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(_panel_qss())
        _bind_theme(lambda: self.setStyleSheet(_panel_qss()))
        # 不用 Qt.Popup：Popup 在 show 时抓取键盘 / 鼠标（焦点抢夺），
        # 输入触发的补全会每击键重抓一次 → 编辑器看似卡死。
        self.setWindowFlags(Qt.ToolTip | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.NoFocus)

        self._list = QListWidget()
        self._list.setFocusPolicy(Qt.NoFocus)
        self._list.setStyleSheet(
            "QListWidget { border: none; background: transparent;"
            f" color: {T('color.text.primary')}; outline: 0; }}"
            f"QListWidget::item {{ padding: 3px 8px; }}"
            f"QListWidget::item:selected {{"
            f" background: {T('color.primary.subtle')}; }}"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.addWidget(self._list)
        self._list.itemActivated.connect(self._activate)
        self._list.itemClicked.connect(self._activate)
        self._items = []

    # -- 数据 --------------------------------------------------------------
    def set_items(self, items) -> None:
        """设置补全项列表。

        每项: ``{"label", "kind", "detail", "insert"}``。
        """
        self._items = list(items or [])
        self._list.clear()
        for it in self._items:
            label = str(it.get("label", ""))
            detail = str(it.get("detail", ""))
            text = label + (f"    {detail}" if detail else "")
            item = QListWidgetItem(text)
            kind = str(it.get("kind", "text")).lower()
            color_key = _KIND_COLORS.get(kind, "color.text.tertiary")
            color = QColor(T(color_key) if color_key.startswith("color.")
                           else color_key)
            pm = QPixmap(10, 10)
            pm.fill(Qt.transparent)
            p = QPainter(pm)
            p.setRenderHint(QPainter.Antialiasing)
            p.setPen(Qt.NoPen)
            p.setBrush(color)
            p.drawRoundedRect(QRect(1, 1, 8, 8), 2, 2)
            p.end()
            item.setIcon(QIcon(pm))
            self._list.addItem(item)
        if self._items:
            self._list.setCurrentRow(0)
        rows = min(8, max(1, len(self._items)))
        self._list.setFixedHeight(rows * 26 + 6)
        self.setFixedWidth(300)
        self.adjustSize()

    def count(self) -> int:
        return len(self._items)

    def current_insert_text(self):
        """当前选中项的插入文本（无选中返回 None）。"""
        row = self._list.currentRow()
        if 0 <= row < len(self._items):
            it = self._items[row]
            return str(it.get("insert", it.get("label", "")))
        return None

    # -- 按键转发（由 CodeEditor 调用） -------------------------------------
    def handle_key(self, key: int) -> bool:
        """处理导航按键；返回 True 表示已消费。"""
        row = self._list.currentRow()
        if key == Qt.Key_Down:
            self._list.setCurrentRow(min(row + 1, self._list.count() - 1))
            return True
        if key == Qt.Key_Up:
            self._list.setCurrentRow(max(row - 1, 0))
            return True
        if key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Tab):
            text = self.current_insert_text()
            if text is not None:
                self.item_chosen.emit(text)
            return True
        if key == Qt.Key_Escape:
            self.hide()
            return True
        return False

    def _activate(self, item):
        row = self._list.row(item)
        if 0 <= row < len(self._items):
            it = self._items[row]
            self.item_chosen.emit(str(it.get("insert", it.get("label", ""))))

    def popup_at(self, global_pos) -> None:
        """在给定全局坐标弹出（通常取光标矩形左下角）。

        已可见时仅移动位置，避免每击键重复 ``show()`` 带来的闪烁与
        窗口系统级重激活开销。
        """
        self.move(global_pos)
        if not self.isVisible():
            self.show()
        self.raise_()


# ---------------------------------------------------------------------------
# 悬停气泡
# ---------------------------------------------------------------------------

class HoverBubble(QFrame):
    """悬停气泡（provider 驱动，富文本）。"""

    def __init__(self, editor, parent=None):
        super().__init__(parent or editor)
        self.setObjectName("uikCePanel")
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(_panel_qss())
        _bind_theme(lambda: self.setStyleSheet(_panel_qss()))
        self.setWindowFlags(Qt.ToolTip | Qt.FramelessWindowHint)
        self.setFocusPolicy(Qt.NoFocus)
        self._label = QLabel()
        self._label.setTextFormat(Qt.RichText)
        self._label.setWordWrap(True)
        self._label.setStyleSheet(
            f"color: {T('color.text.primary')}; border: none;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.addWidget(self._label)
        self.setMaximumWidth(420)

    def show_at(self, global_pos, html: str) -> None:
        """在全局坐标显示富文本气泡。"""
        self._label.setText(html)
        self.adjustSize()
        self.move(global_pos)
        self.show()
        self.raise_()
