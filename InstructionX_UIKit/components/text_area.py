# -*- coding: utf-8 -*-
"""多行文本域组件（SPEC §5.1）。

``TextArea`` 基于 QTextEdit，提供自适应高度（按内容行数伸缩并受
min/max 行数约束）、最大长度限制与右下角字数统计。
"""

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QLabel, QTextEdit

from ..theme import set_property

__all__ = ["TextArea"]


class TextArea(QTextEdit):
    """多行文本域。

    用途:
        长文本录入；可选自适应高度、最大长度限制与字数统计角标。

    参数:
        placeholder: 占位提示。
        auto_height: 是否随内容自动伸缩高度。
        min_rows: 最小行数（auto_height 时生效）。
        max_rows: 最大行数（auto_height 时生效，超出后出现滚动条）。
        max_length: 最大字符数，超出截断；为 None 不限制。
        show_count: 是否在右下角显示字数统计。
        parent: 父控件。

    示例::

        bio = TextArea(placeholder="介绍一下自己", auto_height=True,
                       max_length=200, show_count=True)
        bio.setPlainText("你好")
        print(bio.count())
    """

    def __init__(self, placeholder: str = "", auto_height: bool = False,
                 min_rows: int = 3, max_rows: int = 8, max_length: int = None,
                 show_count: bool = False, parent=None):
        super().__init__(parent)
        self._auto_height = auto_height
        self._min_rows = max(1, min_rows)
        self._max_rows = max(self._min_rows, max_rows)
        self._max_length = max_length
        self._count_label = None
        if placeholder:
            self.setPlaceholderText(placeholder)
        if show_count:
            self._count_label = QLabel(self)
            set_property(self._count_label, "role", "hint")
            self._count_label.raise_()
        self.textChanged.connect(self._on_text_changed)
        # 文档布局尺寸变化（换行 / 折行）时同步重算，覆盖字体就绪前的过期值
        self.document().documentLayout().documentSizeChanged.connect(
            self._on_document_size_changed)
        self._on_text_changed()

    # ------------------------------------------------------------------
    # 字数统计 / 长度限制
    # ------------------------------------------------------------------

    def count(self) -> int:
        """当前字符数。"""
        return len(self.toPlainText())

    def set_max_length(self, max_length) -> None:
        """设置最大字符数（None 表示不限制）。"""
        self._max_length = max_length
        self._on_text_changed()

    def max_length(self):
        """最大字符数，None 表示不限制。"""
        return self._max_length

    def _on_text_changed(self) -> None:
        if self._max_length is not None:
            text = self.toPlainText()
            if len(text) > self._max_length:
                cursor = self.textCursor()
                pos = cursor.position()
                self.blockSignals(True)
                self.setPlainText(text[: self._max_length])
                cursor = self.textCursor()
                cursor.setPosition(min(pos, self._max_length))
                self.setTextCursor(cursor)
                self.blockSignals(False)
        if self._count_label is not None:
            if self._max_length is not None:
                self._count_label.setText(f"{self.count()} / {self._max_length}")
            else:
                self._count_label.setText(f"{self.count()} 字")
            self._count_label.adjustSize()
            self._place_count_label()
        if self._auto_height:
            self._adjust_height()

    def _place_count_label(self) -> None:
        if self._count_label is None:
            return
        margin = 8
        x = self.width() - self._count_label.width() - margin
        y = self.height() - self._count_label.height() - 4
        self._count_label.move(max(0, x), max(0, y))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_count_label()
        # 宽度变化可能改变折行，从而改变内容高度
        if (self._auto_height and event.oldSize().width() >= 0
                and event.size().width() != event.oldSize().width()):
            self._adjust_height()

    # ------------------------------------------------------------------
    # 自适应高度
    # ------------------------------------------------------------------

    def set_auto_height(self, on: bool, min_rows: int = None,
                        max_rows: int = None) -> None:
        """开关自适应高度，可同时调整行数约束。"""
        self._auto_height = bool(on)
        if min_rows is not None:
            self._min_rows = max(1, min_rows)
        if max_rows is not None:
            self._max_rows = max(self._min_rows, max_rows)
        if on:
            self._adjust_height()
        else:
            self.setMinimumHeight(0)
            self.setMaximumHeight(16777215)
            self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

    def _row_height(self) -> int:
        return self.fontMetrics().lineSpacing()

    def _frame_padding(self) -> int:
        """内容之外的纵向占位（边框 + QSS padding 已计入 contentsMargins）。"""
        margins = self.contentsMargins()
        return margins.top() + margins.bottom() + 2  # +2 防取整抖动

    def _content_height(self) -> float:
        """文档可视高度（含文档边距）。

        ``QTextDocument.size()`` 已包含 documentMargin；在字体 / 布局
        未就绪时可能拿到过期值，故用行数 * 行高 + 文档边距兜底。
        """
        doc = self.document()
        doc_h = doc.size().height()
        lines = max(1, doc.blockCount())
        fallback = lines * self._row_height() + 2 * doc.documentMargin()
        return max(doc_h, fallback)

    def _adjust_height(self) -> None:
        doc_h = self._content_height()
        pad = self._frame_padding()
        row = self._row_height()
        min_h = self._min_rows * row + 2 * self.document().documentMargin() + pad
        max_h = self._max_rows * row + 2 * self.document().documentMargin() + pad
        h = int(max(min_h, min(doc_h + pad, max_h)))
        self.setMinimumHeight(h)
        self.setMaximumHeight(h)
        # 达到最大行数后允许滚动
        policy = (Qt.ScrollBarAsNeeded if doc_h + pad > max_h + 1
                  else Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(policy)

    def _on_document_size_changed(self, *_args) -> None:
        if self._auto_height:
            self._adjust_height()

    # ------------------------------------------------------------------
    # 首次显示 / 字体就绪 / 宽度变化时重算（修复首显截断）
    # ------------------------------------------------------------------
    #
    # 根因：高度只在 textChanged 时计算，构造期 QSS 边距与字体尚未就绪，
    # 得到的过期值（常塌缩为最小行高）在 show 之后无人刷新，输入字符才跳变。

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._auto_height:
            self._adjust_height()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if self._auto_height and event.type() in (
                QEvent.FontChange, QEvent.StyleChange,
                QEvent.ApplicationFontChange, QEvent.Polish):
            self._adjust_height()
