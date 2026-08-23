# -*- coding: utf-8 -*-
"""流式对话布局预设（SPEC §6 chat_conversation）。

面向 AI 人机对话场景的页面骨架：居中的消息列（用户气泡右对齐
主色底、AI 消息左对齐整宽 `bg.subtle` 底色气泡），AI 消息内嵌
``MarkdownView`` 原生渲染 Markdown，
``append_to_message`` 支持逐 token 流式输出；底部可选输入区
（``TextArea`` + 发送按钮），提交时发射 ``messageSubmitted`` 信号，
布局本身不承载任何 AI 逻辑。

**API 驱动，无内置假数据**：消息列表由调用方以
``[{"role": "user" | "assistant", "content": "<markdown>"}, ...]``
传入；全部为空时显示优雅的空占位（「暂无对话」）。

滚动跟随：追加内容时若滚动条在底部则自动跟随，用户上翻后不打断。

示例::

    from InstructionX_UIKit.layouts.chat_conversation import create_chat_conversation
    win = create_chat_conversation(messages=[
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好！**有什么可以帮你？**"},
    ])
    win.messageSubmitted.connect(lambda text: win.add_message("user", text))
    win.show()
"""

from PySide6.QtCore import QCoreApplication, QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..components.button import Button
from ..components.markdown_view import MarkdownView
from ..components.text_area import TextArea
from ..theme import T, ThemeManager
from ..tokens import Breakpoint
from .helpers import empty_placeholder

__all__ = ["ChatConversation", "create_chat_conversation"]

#: 消息列最大宽度（与单列布局一致）
_MAX_CONTENT_WIDTH = 760

#: 气泡高度 = 文档高度 + 取整余量（像素）
_BUBBLE_HEIGHT_PAD = 4

#: user 气泡宽度上限的兜底下限（像素）
_MIN_USER_BUBBLE_CAP = 160

#: 滚动跟随判定余量（像素）
_SCROLL_MARGIN = 4

#: 合法消息角色
_ROLES = ("user", "assistant")


class _BubbleView(MarkdownView):
    """气泡内的 Markdown 视图：高度随内容伸缩，禁用自身滚动条。"""

    def __init__(self, markdown: str = "", parent=None):
        super().__init__(markdown, variant="plain", parent=parent)
        # 流式中的空气泡不显示「暂无内容」占位
        self.set_empty_text("")
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        # 直接用信号携带的最新尺寸；信号时刻 doc.size() 可能尚未更新
        self.document().documentLayout().documentSizeChanged.connect(
            self._on_doc_size)
        self._sync_height(self.document().size().height())

    def _on_doc_size(self, size) -> None:
        self._sync_height(size.height())
        # setFixedHeight 的 updateGeometry 不会可靠冒泡到父布局链，
        # 由气泡（父控件）直接同步自身固定高度，确定性裁剪防护
        parent = self.parentWidget()
        if hasattr(parent, "_sync_bubble_height"):
            parent._sync_bubble_height()

    def _sync_height(self, doc_height: float = None) -> None:
        if doc_height is None:
            doc_height = self.document().size().height()
        h = int(-(-doc_height // 1)) + _BUBBLE_HEIGHT_PAD  # ceil + 取整余量
        self.setFixedHeight(max(h, T("font.md") + 8))


class _Bubble(QFrame):
    """单条消息气泡：user 右对齐主色底，assistant 整宽 `bg.subtle` 底。"""

    def __init__(self, role: str, content: str, parent=None):
        super().__init__(parent)
        self.role = role
        # user 气泡水平贴合内容（宽度上限由外层按列宽 2/3 设置），
        # 垂直方向一律贴合内容高度
        horizontal = (QSizePolicy.Maximum if role == "user"
                      else QSizePolicy.Expanding)
        self.setSizePolicy(horizontal, QSizePolicy.Maximum)
        lay = QVBoxLayout(self)
        pad = T("space.2")
        lay.setContentsMargins(pad, pad, pad, pad)
        self.view = _BubbleView(content)
        lay.addWidget(self.view)
        ThemeManager.instance().theme_changed.connect(lambda *_: self.update())
        self._sync_bubble_height()

    def _sync_bubble_height(self) -> None:
        """气泡固定高度 = 视图高度 + 内边距（确定性，不依赖布局事件传播）。"""
        m = self.layout().contentsMargins()
        self.setFixedHeight(self.view.height() + m.top() + m.bottom())

    def paintEvent(self, event) -> None:  # noqa: N802
        color_key = ("color.primary.subtle" if self.role == "user"
                     else "color.bg.subtle")
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(T(color_key)))
        painter.drawRoundedRect(self.rect(), T("radius.lg"), T("radius.lg"))
        painter.end()
        super().paintEvent(event)


class ChatConversation(QWidget):
    """流式对话布局：消息列 + 可选底部输入区。

    参数:
        messages: 初始消息列表，每项 ``{"role": "user" | "assistant",
            "content": "<markdown 文本>"}``；为空显示空占位。
        show_input: 是否显示底部输入区（TextArea + 发送按钮）。
        parent: 父控件。

    信号:
        messageSubmitted(str): 输入区提交（点击发送）时发射文本，
            布局不会自动上屏，由调用方决定后续处理。
    """

    #: 输入区提交信号，参数为消息文本
    messageSubmitted = Signal(str)

    def __init__(self, messages=None, show_input: bool = True, parent=None):
        super().__init__(parent)
        self._messages = []
        self._bubbles = []
        self._rows = []            # 包裹气泡的行布局（clear 时逐行清理）
        self._placeholder = None
        self._follow = True        # 底部跟随状态（用户上翻后暂停）
        self._programmatic_scroll = False
        self._last_max = 0         # 上次滚动范围上限（识别 value 钳制用）
        self._last_value = 0       # 上次滚动位置（钳制判据的兜底基线）

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        root.addWidget(self._scroll, 1)

        host = QWidget()
        self._center = QHBoxLayout(host)
        self._center.addStretch(1)
        self._column = QFrame()
        self._column.setFrameShape(QFrame.NoFrame)
        self._column.setMaximumWidth(_MAX_CONTENT_WIDTH)
        self._list_lay = QVBoxLayout(self._column)
        self._list_lay.setContentsMargins(0, 0, 0, 0)
        self._list_lay.setSpacing(T("space.3"))
        # 列宽在 resizeEvent 中显式计算（QBoxLayout 的 stretch 会被两侧
        # spacer 吃光，无法可靠扩张，见 _sync_geometry）
        self._center.addWidget(self._column)
        self._center.addStretch(1)
        self._list_lay.addStretch(1)
        self._scroll.setWidget(host)
        # 视口尺寸（含滚动条出现 / 消失引起的收缩）直接驱动列宽
        self._scroll.viewport().installEventFilter(self)
        # 用户滚动状态 → 底部跟随开关
        self._scroll.verticalScrollBar().valueChanged.connect(
            self._on_scroll_value)

        # 底部输入区（可选）
        self.input_edit = None
        self.send_button = None
        if show_input:
            bar = QFrame()
            bar.setFrameShape(QFrame.NoFrame)
            bar_lay = QHBoxLayout(bar)
            margin = T("space.2")
            bar_lay.setContentsMargins(margin, margin, margin, margin)
            bar_lay.setSpacing(T("space.2"))
            self.input_edit = TextArea(
                placeholder="输入消息...", auto_height=True,
                min_rows=1, max_rows=4)
            self.send_button = Button("发送", variant="primary")
            self.send_button.clicked.connect(self._on_send)
            bar_lay.addWidget(self.input_edit, 1)
            bar_lay.addWidget(self.send_button, 0, Qt.AlignBottom)
            root.addWidget(bar)

        self._bp = ""
        self._sync("lg")
        if messages:
            self.set_messages(messages)
        else:
            self._show_placeholder()

    # ------------------------------------------------------------------ 消息
    def set_messages(self, messages) -> None:
        """整体设置消息列表（覆盖现有内容）。

        先整体校验再提交：任何一条非法都不会留下半提交状态。
        """
        normalized = []
        for i, msg in enumerate(messages):
            if not isinstance(msg, dict) or "role" not in msg:
                raise ValueError(
                    f"消息 {i} 应为含 role/content 的 dict，收到 {msg!r}")
            role = msg["role"]
            if role not in _ROLES:
                raise ValueError(f"未知消息角色: {role!r}，应为 {_ROLES} 之一")
            content = msg.get("content")
            if content is None:
                content = ""
            normalized.append((role, str(content)))
        self.clear_messages()
        for role, content in normalized:
            self.add_message(role, content)

    def add_message(self, role: str, content: str = "") -> int:
        """追加一条消息，返回消息索引（供 ``append_to_message`` 使用）。"""
        if role not in _ROLES:
            raise ValueError(f"未知消息角色: {role!r}，应为 {_ROLES} 之一")
        if content is None:
            content = ""
        self._hide_placeholder()
        bubble = _Bubble(role, str(content))
        self._insert_bubble(bubble)
        # 气泡文档尺寸变化（流式追加 / 公式图片就绪）后保持底部跟随
        bubble.view.document().documentLayout().documentSizeChanged.connect(
            self._follow_after_doc_change)
        self._messages.append({"role": role, "content": str(content)})
        self._bubbles.append(bubble)
        self._follow_scroll()
        return len(self._messages) - 1

    def append_to_message(self, index: int, chunk: str) -> None:
        """向指定消息流式追加 Markdown 片段（AI 逐 token 输出）。"""
        if not 0 <= index < len(self._messages):
            raise IndexError(f"消息索引越界: {index}，当前共 {len(self._messages)} 条")
        self._messages[index]["content"] += chunk
        self._bubbles[index].view.append_markdown(chunk)
        self._follow_scroll()

    def clear_messages(self) -> None:
        """清空全部消息，回到空占位。

        气泡由包裹行（QHBoxLayout）持有：removeWidget 对非直接子项
        是 no-op，必须逐行 takeAt 移除行内条目再从列表布局摘除行
        本身，否则行随消息数永久累积。
        """
        for row in self._rows:
            while row.count():
                item = row.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.hide()
                    w.deleteLater()
            self._list_lay.removeItem(row)
        self._rows.clear()
        self._bubbles.clear()
        self._messages.clear()
        # 清空即新会话：从头跟随底部；滚动范围归零，同步重置钳制判定基线
        self._follow = True
        self._last_max = 0
        self._last_value = 0
        self._show_placeholder()

    def messages(self) -> list:
        """当前消息列表的副本。"""
        return [dict(m) for m in self._messages]

    # ------------------------------------------------------------------ 内部
    def _insert_bubble(self, bubble: _Bubble) -> None:
        """user 右对齐限宽，assistant 整宽左对齐；插入到末尾 stretch 之前。"""
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        if bubble.role == "user":
            row.addStretch(1)
            row.addWidget(bubble)
        else:
            row.addWidget(bubble, 1)
        self._list_lay.insertLayout(self._list_lay.count() - 1, row)
        self._rows.append(row)
        self._sync_bubble_caps()

    def _show_placeholder(self) -> None:
        if self._placeholder is None:
            self._placeholder = empty_placeholder("暂无对话")
            self._list_lay.insertWidget(self._list_lay.count() - 1,
                                        self._placeholder, 1)

    def _hide_placeholder(self) -> None:
        if self._placeholder is not None:
            self._list_lay.removeWidget(self._placeholder)
            # removeWidget 不会自动隐藏，游离控件会残留在原位置绘制
            self._placeholder.hide()
            self._placeholder.deleteLater()
            self._placeholder = None

    def _sync_bubble_caps(self) -> None:
        """user 气泡宽度上限为消息列的 2/3（随列宽变化）。"""
        cap = max(_MIN_USER_BUBBLE_CAP, int(self._column.width() * 2 / 3))
        for bubble in self._bubbles:
            if bubble.role == "user":
                bubble.setMaximumWidth(cap)

    def _sync_geometry(self) -> None:
        """显式计算消息列宽度：min(视口宽 - 页边距, 760)。

        QBoxLayout 的多余空间全被 stretch 因子 > 0 的两侧 spacer 吸收，
        列不会因 stretch 因子扩张，必须按视口宽度直接 setFixedWidth。
        """
        m = self._center.contentsMargins()
        avail = self._scroll.viewport().width() - m.left() - m.right() - 2
        self._column.setFixedWidth(max(120, min(avail, _MAX_CONTENT_WIDTH)))
        self._sync_bubble_caps()
        if self._follow:
            # 视口变矮使滚动范围增大后 value 不变、视图悬停在旧位置：
            # 延迟一轮等布局落定后重新吸附底部
            QTimer.singleShot(0, self._follow_scroll)

    def _follow_scroll(self) -> None:
        """滚动条在底部时追加后自动跟随（用户上翻则暂停跟随）。"""
        if not self._follow:
            return
        bar = self._scroll.verticalScrollBar()
        self._programmatic_scroll = True
        try:
            bar.setValue(bar.maximum())
        finally:
            self._programmatic_scroll = False
        # 程序滚动不触发钳制判定，在此手动刷新基线防止过期
        self._last_max = bar.maximum()
        self._last_value = bar.value()

    def _on_scroll_value(self, value: int) -> None:
        """用户滚动：更新底部跟随状态（程序 setValue 除外）。"""
        if self._programmatic_scroll:
            return
        bar = self._scroll.verticalScrollBar()
        maximum = bar.maximum()
        # 范围收缩时 Qt 会把 value 钳到 maximum，这是布局变化而非用户
        # 回到底部（主题切换 / 全量重渲染的占位图瞬态收缩可触发）：
        # 保持原跟随状态，否则阅读位置会被随后的自动跟随强拉到底。
        # value 下降判据用于兜底「范围先无声增长（无 valueChanged，
        # _last_max 过期）再收缩」的场景。
        if value == maximum and (maximum < self._last_max
                                 or value < self._last_value):
            self._last_max = maximum
            self._last_value = value
            return
        self._last_max = maximum
        self._last_value = value
        self._follow = value >= maximum - _SCROLL_MARGIN

    def _follow_after_doc_change(self) -> None:
        """气泡文档尺寸变化（流式追加 / 公式图片就绪）后继续底部跟随。

        文档变高时滚动范围在事件循环中才更新：若跟随状态开启，先
        等布局落定（processEvents）再滚到底，修复「公式图片到达使
        气泡长高后视口不再跟随」的问题。
        """
        if not self._follow:
            return

        def _flush_and_follow():
            # 布局与滚动范围更新可能需要多轮事件处理才落定
            for _ in range(4):
                QCoreApplication.processEvents()
            self._follow_scroll()

        QTimer.singleShot(0, _flush_and_follow)

    def _on_send(self) -> None:
        text = self.input_edit.toPlainText().strip()
        if not text:
            return
        self.input_edit.clear()
        self.messageSubmitted.emit(text)

    # ------------------------------------------------------------------ 响应式
    def eventFilter(self, watched, event):  # noqa: N802
        """滚动视口尺寸变化时重算列宽（resizeEvent 时机早于视口定型）。"""
        if watched is self._scroll.viewport() and event.type() == QEvent.Resize:
            self._sync_geometry()
        return super().eventFilter(watched, event)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._sync(Breakpoint.from_width(self.width()))
        self._sync_geometry()

    def _sync(self, bp: str) -> None:
        """按断点调整外边距：宽屏 space.6，中屏 space.4，窄屏 space.2。"""
        if bp == self._bp:
            return
        self._bp = bp
        if bp in ("lg", "xl"):
            margin = T("space.6")
        elif bp == "md":
            margin = T("space.4")
        else:
            margin = T("space.2")
        self._center.setContentsMargins(margin, margin, margin, margin)


def create_chat_conversation(messages=None, show_input: bool = True,
                             parent=None) -> ChatConversation:
    """创建流式对话布局部件（消息全部由调用方传入）。"""
    return ChatConversation(messages=messages, show_input=show_input,
                            parent=parent)
