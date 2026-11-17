# -*- coding: utf-8 -*-
"""多行文本域组件（SPEC §5.1）。

``TextArea`` 基于 QTextEdit，提供自适应高度（按内容行数伸缩并受
min/max 行数约束）、最大长度限制与右下角字数统计。

本轮修复（轨道 2）：

- **字数统计不再压字**：原实现把统计标签浮在文本之上，最后一行文字与
  ``26 / 120`` 叠在一起。改为在自适应高度里**预留一行**统计条高度
  （标签高 + ``space.1`` 间隙），文字区与统计区上下分区（契约 §4
  「用 spacing 分区」），文字与计数互不相交。
- **默认高度回归高密度**：非自适应模式下 QTextEdit 默认 192px 高，
  与整套 22 / 28 / 34 刻度完全不搭。缺省改为 ``min_rows`` 行高
  （默认 3 行 ≈ 60px），并提供 ``set_rows`` 在关闭自适应后改行数。
- 内边距、间隙全部改走 ``T("layout.*") / T("space.*")`` 令牌。
"""

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtWidgets import QLabel, QTextEdit

from ..theme import T, set_property
from ._mixin import QWIDGETSIZE_MAX

__all__ = ["TextArea"]

#: 高度换算的取整保护：QSS 边距 / 文档边距在浮点与整数间取整时会差
#: 不到 1px，统一补半档（2px）避免高度抖动 1px。
_ROUNDING_GUARD = int(T("space.05"))


class TextArea(QTextEdit):
    """多行文本域。

    用途:
        长文本录入；可选自适应高度、最大长度限制与字数统计角标。

    参数:
        placeholder: 占位提示。
        auto_height: 是否随内容自动伸缩高度。
        min_rows: 最小行数（auto_height 时生效；否则作为缺省高度）。
        max_rows: 最大行数（auto_height 时生效，超出后出现滚动条）。
        max_length: 最大字符数，超出截断；为 None 不限制。
        show_count: 是否在右下角显示字数统计。
        parent: 父控件。

    示例::

        bio = TextArea(placeholder="介绍一下自己", auto_height=True,
                       max_length=200, show_count=True)
        bio.setPlainText("你好")
        print(bio.count())

    备注:
        ``show_count=True`` 时，文本区底部会**预留**一行统计条高度
        （``字数统计`` 与正文不重叠），因此控件总高比同 ``min_rows``
        的无统计实例多一行。
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
        else:
            self._apply_fixed_height()

    def _place_count_label(self) -> None:
        """把统计标签放到右下角（内缩取 ``inset.pad_x`` / ``space.1``）。"""
        if self._count_label is None:
            return
        x = self.width() - self._count_label.width() - int(T("layout.inset.pad_x"))
        y = self.height() - self._count_label.height() - int(T("space.1"))
        self._count_label.move(max(0, x), max(0, y))

    def _count_reserve(self) -> int:
        """统计条预留高度（标签高 + ``space.1`` 间隙）；无统计标签时为 0。"""
        if self._count_label is None:
            return 0
        self._count_label.adjustSize()
        return self._count_label.height() + int(T("space.1"))

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
            self._apply_fixed_height()
            self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

    def set_rows(self, rows: int) -> None:
        """设置非自适应模式下的行数（关闭自适应时的缺省高度）。"""
        self._min_rows = max(1, int(rows))
        self._max_rows = max(self._min_rows, self._max_rows)
        if not self._auto_height:
            self._apply_fixed_height()

    def _row_height(self) -> int:
        return self.fontMetrics().lineSpacing()

    def _frame_padding(self) -> int:
        """内容之外的纵向占位（边框 + QSS padding 已计入 contentsMargins）。"""
        margins = self.contentsMargins()
        return margins.top() + margins.bottom() + _ROUNDING_GUARD

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

    def _preferred_height(self) -> int:
        """非自适应模式的缺省高度：``min_rows`` 行 + 统计条预留。"""
        row = self._row_height()
        doc_pad = 2 * self.document().documentMargin()
        return (self._min_rows * row + doc_pad + self._frame_padding()
                + self._count_reserve())

    def sizeHint(self) -> QSize:
        """把「期望高度」压到缺省行数，取代 QTextEdit 的 192px 默认值。

        只压**建议高度**不压最大高度：布局仍可把控件拉高（用户可拖大），
        但默认排布时不会一上来就占掉 192px，与整套 22 / 28 / 34 高密度
        刻度完全不搭（契约 §1 / §4）。
        """
        hint = super().sizeHint()
        if self._auto_height:
            return hint
        return QSize(hint.width(), min(hint.height(), self._preferred_height()))

    def _apply_fixed_height(self) -> None:
        """非自适应模式：按 ``min_rows`` 给一个高密度缺省高度。

        不设固定值——QTextEdit 的 192px 缺省高度与整套 22 / 28 / 34
        刻度完全不搭；这里只压「最小高度 + 建议高度」，用户 / 布局仍可
        自由拉高。
        """
        self.setMinimumHeight(self._preferred_height())
        self.setMaximumHeight(QWIDGETSIZE_MAX)
        self._place_count_label()

    def _adjust_height(self) -> None:
        doc_h = self._content_height()
        pad = self._frame_padding()
        reserve = self._count_reserve()   # 统计条与正文分区，不叠字
        row = self._row_height()
        min_h = self._min_rows * row + 2 * self.document().documentMargin() \
            + pad + reserve
        max_h = self._max_rows * row + 2 * self.document().documentMargin() \
            + pad + reserve
        h = int(max(min_h, min(doc_h + pad + reserve, max_h)))
        self.setMinimumHeight(h)
        self.setMaximumHeight(h)
        self._place_count_label()
        # 达到最大行数后允许滚动
        policy = (Qt.ScrollBarAsNeeded if doc_h + pad + reserve > max_h + 1
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
        else:
            self._apply_fixed_height()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() in (QEvent.FontChange, QEvent.StyleChange,
                            QEvent.ApplicationFontChange, QEvent.Polish):
            if self._auto_height:
                self._adjust_height()
            else:
                self._apply_fixed_height()
