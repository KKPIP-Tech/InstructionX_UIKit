# -*- coding: utf-8 -*-
"""流式对话布局预设（SPEC §6 chat_conversation）。

面向 AI 人机对话场景的页面骨架：居中的消息列（用户气泡右对齐
主色底、AI 消息左对齐整宽 `bg.subtle` 底色气泡），AI 消息内嵌
``MarkdownView`` 原生渲染 Markdown，
``append_to_message`` 支持逐 token 流式输出；底部可选输入区
（``TextArea`` + 发送按钮），提交时发射 ``messageSubmitted`` 信号，
布局本身不承载任何 AI 逻辑。

每个气泡底部带操作条（悬停气泡显现，``set_actions_always_visible``
可常显）：左侧统计文案（token 估算，AI 消息附速度 / 用时），右侧
图标按钮——共有「复制 / 删除」，AI 消息加「重新生成 / 继续生成」，
用户消息加「编辑」（内联编辑态）。复制 / 删除 / 编辑由布局直接
执行，重新生成 / 继续生成仅发射 ``regenerateRequested`` /
``continueRequested`` 信号，AI 逻辑由调用方承载。

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

import time

from PySide6.QtCore import QCoreApplication, QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..components.button import Button
from ..components.icon_button import IconButton
from ..components.markdown_view import MarkdownView
from ..components.text_area import TextArea
from ..icons import get_icon
from ..theme import T, ThemeManager, set_property
from ..tokens import Breakpoint
from .helpers import apply_token_font, empty_placeholder

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

#: 操作条高度（像素，预留以避免悬停时布局跳动）
_ACTION_BAR_HEIGHT = 24

#: 操作条图标边长（像素，IconButton sm 档点击区 24px）
_ACTION_ICON_SIZE = 14

#: 复制成功反馈时长（毫秒）：图标短暂切换为对勾后复原
_COPY_FEEDBACK_MS = 1000

#: 各角色气泡的操作按钮：(操作名, 图标名, 提示文案)
_ACTIONS = {
    "user": (("copy", "copy", "复制"),
             ("edit", "edit", "编辑"),
             ("delete", "trash", "删除")),
    "assistant": (("copy", "copy", "复制"),
                  ("regenerate", "refresh", "重新生成"),
                  ("continue", "play", "继续生成"),
                  ("delete", "trash", "删除")),
}


def _is_cjk(ch: str) -> bool:
    """判断字符是否属于 CJK（中日韩）相关区块。"""
    code = ord(ch)
    return (0x3000 <= code <= 0x9FFF        # CJK 符号、假名、统一表意文字
            or 0xF900 <= code <= 0xFAFF     # 兼容表意文字
            or 0xFF00 <= code <= 0xFFEF     # 全角字符
            or 0x20000 <= code <= 0x2A6DF)  # 扩展 B 区


def _estimate_tokens(text: str) -> int:
    """启发式 token 估算：CJK 字符每字 1 token，其余按连续非空白片段
    （近似单词）计 1 token。

    仅用于操作条统计展示的估算值；真实 token 数可经
    ``ChatConversation.set_message_stats`` 传入覆盖。
    """
    tokens = 0
    run = 0  # 连续非 CJK 非空白片段长度
    for ch in text:
        if ch.isspace() or _is_cjk(ch):
            if run:
                tokens += 1
                run = 0
            if _is_cjk(ch):
                tokens += 1
        else:
            run += 1
    if run:
        tokens += 1
    return tokens


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
    """单条消息气泡：user 右对齐主色底，assistant 整宽 `bg.subtle` 底。

    底部带操作条（高度预留，内容默认隐藏，悬停气泡时显现；
    ``set_actions_always_visible`` 可常显）：左侧统计文案，右侧图标
    按钮按角色区分（见 ``_ACTIONS``）。按钮点击统一转发给外层
    ``ChatConversation._on_bubble_action``（``_controller`` 由其在
    ``add_message`` 时注入）。用户气泡支持内联编辑态：内容区换为
    ``TextArea`` + 确定 / 取消按钮，期间操作条隐藏。
    """

    def __init__(self, role: str, content: str, parent=None):
        super().__init__(parent)
        self.role = role
        self._controller = None      # ChatConversation（add_message 时注入）
        self._always_visible = False  # 操作条常显开关
        self._hover = False
        self._editing = False
        # user 气泡水平贴合内容（宽度上限由外层按列宽 2/3 设置），
        # 垂直方向一律贴合内容高度
        horizontal = (QSizePolicy.Maximum if role == "user"
                      else QSizePolicy.Expanding)
        self.setSizePolicy(horizontal, QSizePolicy.Maximum)
        lay = QVBoxLayout(self)
        pad = T("space.2")
        lay.setContentsMargins(pad, pad, pad, pad)
        lay.setSpacing(T("space.1"))
        self.view = _BubbleView(content)
        lay.addWidget(self.view)

        # 内联编辑区（默认隐藏）：原文本 + 确定 / 取消
        self._editor = TextArea(auto_height=True, min_rows=1, max_rows=8)
        self._editor.hide()
        # 编辑器高度随内容变化时同步气泡固定高度
        self._editor.document().documentLayout().documentSizeChanged.connect(
            self._on_editor_doc_size)
        lay.addWidget(self._editor)
        self._edit_bar = QWidget(self)
        edit_lay = QHBoxLayout(self._edit_bar)
        edit_lay.setContentsMargins(0, 0, 0, 0)
        edit_lay.setSpacing(T("space.2"))
        edit_lay.addStretch(1)
        ok_btn = Button("确定", variant="primary", size="sm")
        cancel_btn = Button("取消", size="sm")
        ok_btn.clicked.connect(self._on_edit_ok)
        cancel_btn.clicked.connect(self._on_edit_cancel)
        edit_lay.addWidget(ok_btn)
        edit_lay.addWidget(cancel_btn)
        self._edit_bar.hide()
        lay.addWidget(self._edit_bar)

        # 操作条：高度常驻预留（避免悬停时布局跳动），内容默认隐藏
        self._footer = QWidget(self)
        self._footer.setFixedHeight(_ACTION_BAR_HEIGHT)
        foot_lay = QHBoxLayout(self._footer)
        foot_lay.setContentsMargins(T("space.1"), 0, 0, 0)
        foot_lay.setSpacing(T("space.05"))
        self._stats_label = QLabel(self._footer)
        set_property(self._stats_label, "role", "hint")
        apply_token_font(self._stats_label, "font.xs")
        foot_lay.addWidget(self._stats_label, 1)
        self._action_icons = {}    # 操作名 -> 图标名（主题切换时重绘）
        self._action_buttons = {}  # 操作名 -> IconButton
        for action, icon_name, tip in _ACTIONS[role]:
            btn = IconButton(get_icon(icon_name, _ACTION_ICON_SIZE),
                             size="sm", parent=self._footer)
            btn.setToolTip(tip)
            btn.clicked.connect(
                lambda _checked=False, a=action: self._dispatch(a))
            self._action_icons[action] = icon_name
            self._action_buttons[action] = btn
            foot_lay.addWidget(btn)
        self._stats_label.hide()
        for btn in self._action_buttons.values():
            btn.hide()
        lay.addWidget(self._footer)

        ThemeManager.instance().theme_changed.connect(self._on_theme_changed)
        self._sync_bubble_height()

    # ------------------------------------------------------------------ 高度
    def _sync_bubble_height(self) -> None:
        """气泡固定高度 = 可见内容区高度 + 操作条 + 内边距（确定性，
        不依赖布局事件传播）。操作条高度常驻预留，不随显隐变化。"""
        lay = self.layout()
        m = lay.contentsMargins()
        if self._editing:
            content_h = (self._editor.height() + self._edit_bar.height()
                         + lay.spacing())
        else:
            content_h = self.view.height()
        h = (m.top() + m.bottom() + content_h + _ACTION_BAR_HEIGHT
             + lay.spacing() * 2)
        self.setFixedHeight(h)

    def _on_editor_doc_size(self, _size) -> None:
        if self._editing:
            self._sync_bubble_height()

    # ------------------------------------------------------------------ 操作条
    def set_stats_text(self, text: str) -> None:
        """更新操作条左侧统计文案（由 ChatConversation 计算后写入）。"""
        self._stats_label.setText(text)

    def set_actions_always_visible(self, visible: bool) -> None:
        """设置操作条是否常显（False 时仅在悬停气泡时显现）。"""
        self._always_visible = bool(visible)
        self._apply_actions_visibility()

    def _apply_actions_visibility(self) -> None:
        visible = (self._always_visible or self._hover) and not self._editing
        self._stats_label.setVisible(visible)
        for btn in self._action_buttons.values():
            btn.setVisible(visible)

    def _dispatch(self, action: str) -> None:
        if self._controller is not None:
            self._controller._on_bubble_action(self, action)

    def flash_copy_done(self) -> None:
        """复制成功反馈：图标短暂切换为对勾，约 1 秒后换回。

        定时器以气泡为父对象，气泡销毁时自动失效，无悬垂回调。
        """
        self._action_buttons["copy"].set_icon(
            get_icon("check", _ACTION_ICON_SIZE, T("color.success")))
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(self._restore_copy_icon)
        timer.start(_COPY_FEEDBACK_MS)

    def _restore_copy_icon(self) -> None:
        self._action_buttons["copy"].set_icon(
            get_icon("copy", _ACTION_ICON_SIZE))

    # ------------------------------------------------------------------ 编辑态
    def start_edit(self, text: str) -> None:
        """进入内联编辑态：内容区换为编辑器（填入原文本），操作条隐藏。"""
        if self._editing:
            return
        self._editing = True
        self.view.hide()
        self._editor.setPlainText(text)
        self._editor.show()
        self._edit_bar.show()
        self._apply_actions_visibility()
        self._editor.setFocus()
        self._sync_bubble_height()

    def cancel_edit(self) -> None:
        """退出内联编辑态（不改变消息内容），恢复内容区与操作条。"""
        if not self._editing:
            return
        self._editing = False
        self._editor.hide()
        self._edit_bar.hide()
        self.view.show()
        self._apply_actions_visibility()
        self._sync_bubble_height()

    def edit_text(self) -> str:
        """编辑器当前文本。"""
        return self._editor.toPlainText()

    def _on_edit_ok(self) -> None:
        self._dispatch("edit_ok")

    def _on_edit_cancel(self) -> None:
        self._dispatch("edit_cancel")

    # ------------------------------------------------------------------ 事件
    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self._apply_actions_visibility()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self._apply_actions_visibility()
        super().leaveEvent(event)

    def _on_theme_changed(self, *_args) -> None:
        """主题切换：重绘图标（令牌色）并刷新气泡底色。"""
        for action, btn in self._action_buttons.items():
            btn.set_icon(get_icon(self._action_icons[action],
                                  _ACTION_ICON_SIZE))
        self.update()

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
        messageDeleted(int): 气泡操作条「删除」后发射，参数为删除前
            的索引；删除后后续消息索引前移，调用方持有的索引需自行
            校正。
        messageEdited(int, str): 用户气泡内联编辑「确定」后发射，
            参数为消息索引与新文本。
        regenerateRequested(int): AI 气泡「重新生成」点击时发射索引，
            布局不承载 AI 逻辑，由调用方响应（可配合
            ``update_message`` 重置内容）。
        continueRequested(int): AI 气泡「继续生成」点击时发射索引，
            由调用方继续 ``append_to_message`` 追加内容。
    """

    #: 输入区提交信号，参数为消息文本
    messageSubmitted = Signal(str)
    #: 删除消息信号，参数为删除前的索引（删除后后续索引前移）
    messageDeleted = Signal(int)
    #: 编辑消息信号，参数为消息索引与新文本
    messageEdited = Signal(int, str)
    #: 请求重新生成信号，参数为消息索引
    regenerateRequested = Signal(int)
    #: 请求继续生成信号，参数为消息索引
    continueRequested = Signal(int)

    def __init__(self, messages=None, show_input: bool = True, parent=None):
        super().__init__(parent)
        self._messages = []
        self._bubbles = []
        self._rows = []            # 包裹气泡的行布局（clear 时逐行清理）
        self._stats = []           # 每条消息的统计 / 计时状态（按索引对齐）
        self._actions_always = False  # 操作条常显开关
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
        bubble._controller = self
        bubble.set_actions_always_visible(self._actions_always)
        self._insert_bubble(bubble)
        # 气泡文档尺寸变化（流式追加 / 公式图片就绪）后保持底部跟随
        bubble.view.document().documentLayout().documentSizeChanged.connect(
            self._follow_after_doc_change)
        self._messages.append({"role": role, "content": str(content)})
        self._bubbles.append(bubble)
        self._stats.append(self._fresh_stats())
        self._refresh_stats(len(self._messages) - 1)
        self._follow_scroll()
        return len(self._messages) - 1

    def append_to_message(self, index: int, chunk: str) -> None:
        """向指定消息流式追加 Markdown 片段（AI 逐 token 输出）。

        记录首个 / 最近 chunk 时间并刷新该气泡的统计标签（速度、
        用时实时滚动）；流式结束时调用 ``finish_message`` 冻结计时。
        """
        if not 0 <= index < len(self._messages):
            raise IndexError(f"消息索引越界: {index}，当前共 {len(self._messages)} 条")
        self._messages[index]["content"] += chunk
        st = self._stats[index]
        now = time.monotonic()
        if st["first"] is None:
            st["first"] = now
        st["last"] = now
        st["chunks"] += 1
        self._bubbles[index].view.append_markdown(chunk)
        self._refresh_stats(index)
        self._follow_scroll()

    def finish_message(self, index: int) -> None:
        """冻结消息计时（流式输出结束时调用）。

        冻结后「用时」不再随时间滚动；未调用时 AI 消息的统计实时滚动。
        """
        if not 0 <= index < len(self._messages):
            raise IndexError(f"消息索引越界: {index}，当前共 {len(self._messages)} 条")
        self._stats[index]["finished"] = time.monotonic()
        self._refresh_stats(index)

    def update_message(self, index: int, content: str) -> None:
        """整体替换消息内容（重新生成用），并重置该条计时为新一轮。

        该条消息的统计状态（含 ``set_message_stats`` 的覆盖值）全部
        重置；若正处于内联编辑态则先退出。
        """
        if not 0 <= index < len(self._messages):
            raise IndexError(f"消息索引越界: {index}，当前共 {len(self._messages)} 条")
        if content is None:
            content = ""
        bubble = self._bubbles[index]
        bubble.cancel_edit()
        self._messages[index]["content"] = str(content)
        bubble.view.set_markdown(str(content))
        self._stats[index] = self._fresh_stats()
        self._refresh_stats(index)
        self._follow_scroll()

    def set_message_stats(self, index: int, tokens: int = None,
                          elapsed: float = None, speed: float = None) -> None:
        """以真实值覆盖消息的统计展示（覆盖后不再按估算 / 计时更新）。

        参数:
            index: 消息索引。
            tokens: 真实 token 数；None 保持 ``_estimate_tokens`` 估算。
            elapsed: 真实整体用时（秒）；None 保持内部计时。
            speed: 真实速度（tok/s）；None 保持按 chunk 计时推算。
        """
        if not 0 <= index < len(self._messages):
            raise IndexError(f"消息索引越界: {index}，当前共 {len(self._messages)} 条")
        st = self._stats[index]
        if tokens is not None:
            tokens = int(tokens)
            if tokens < 0:
                raise ValueError(f"tokens 应 >= 0，收到 {tokens}")
            st["tokens"] = tokens
        if elapsed is not None:
            elapsed = float(elapsed)
            if elapsed < 0:
                raise ValueError(f"elapsed 应 >= 0，收到 {elapsed}")
            st["elapsed"] = elapsed
        if speed is not None:
            speed = float(speed)
            if speed < 0:
                raise ValueError(f"speed 应 >= 0，收到 {speed}")
            st["speed"] = speed
        self._refresh_stats(index)

    def set_actions_always_visible(self, visible: bool) -> None:
        """设置气泡操作条是否常显（默认 False，悬停气泡时显现）。"""
        self._actions_always = bool(visible)
        for bubble in self._bubbles:
            bubble.set_actions_always_visible(self._actions_always)

    def actions_always_visible(self) -> bool:
        """操作条是否常显。"""
        return self._actions_always

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
        self._stats.clear()
        # 清空即新会话：从头跟随底部；滚动范围归零，同步重置钳制判定基线
        self._follow = True
        self._last_max = 0
        self._last_value = 0
        self._show_placeholder()

    def messages(self) -> list:
        """当前消息列表的副本。"""
        return [dict(m) for m in self._messages]

    # ------------------------------------------------------------------ 统计
    @staticmethod
    def _fresh_stats() -> dict:
        """新建一条消息的统计 / 计时状态（计时用单调时钟，不受系统时间影响）。"""
        return {"created": time.monotonic(),  # 消息创建时间
                "first": None,   # 首个流式 chunk 时间
                "last": None,    # 最近流式 chunk 时间
                "chunks": 0,     # 流式 chunk 计数（速度至少需 2 个）
                "finished": None,  # finish_message 冻结时间
                "tokens": None,  # set_message_stats 覆盖：真实 token 数
                "elapsed": None,  # set_message_stats 覆盖：真实用时（秒）
                "speed": None}   # set_message_stats 覆盖：真实速度（tok/s）

    def _refresh_stats(self, index: int) -> None:
        """重算并写入指定气泡操作条的统计文案。"""
        self._bubbles[index].set_stats_text(self._stats_text(index))

    def _stats_text(self, index: int) -> str:
        """统计文案：共有「约 N tokens」；AI 消息在有数据时追加
        「· M tok/s · 用时 X.Xs」（无速度数据则不显示速度段；未经
        流式追加且未 finish 的静态 AI 消息不显示用时）。"""
        msg = self._messages[index]
        st = self._stats[index]
        tokens = st["tokens"]
        if tokens is None:
            tokens = _estimate_tokens(msg["content"])
        parts = [f"约 {tokens} tokens"]
        if msg["role"] == "assistant":
            speed = st["speed"]
            if speed is None and st["chunks"] >= 2 and st["first"] is not None:
                span = st["last"] - st["first"]
                if span > 0:
                    speed = tokens / span
            if speed is not None:
                parts.append(f"{speed:.1f} tok/s")
            elapsed = st["elapsed"]
            if elapsed is None and (st["finished"] is not None
                                    or st["first"] is not None):
                end = (st["finished"] if st["finished"] is not None
                       else time.monotonic())
                elapsed = end - st["created"]
            if elapsed is not None:
                parts.append(f"用时 {elapsed:.1f}s")
        return " · ".join(parts)

    # ------------------------------------------------------------------ 气泡操作
    def _on_bubble_action(self, bubble: _Bubble, action: str) -> None:
        """气泡操作条按钮分发（由 _Bubble 点击时回调）。"""
        try:
            index = self._bubbles.index(bubble)
        except ValueError:
            return
        if action == "copy":
            # 直接写系统剪贴板，图标短暂切换为对勾反馈
            QGuiApplication.clipboard().setText(self._messages[index]["content"])
            bubble.flash_copy_done()
        elif action == "delete":
            self._delete_message(index)
        elif action == "regenerate":
            self.regenerateRequested.emit(index)
        elif action == "continue":
            self.continueRequested.emit(index)
        elif action == "edit":
            bubble.start_edit(self._messages[index]["content"])
        elif action == "edit_ok":
            self._confirm_edit(index, bubble)
        elif action == "edit_cancel":
            bubble.cancel_edit()

    def _confirm_edit(self, index: int, bubble: _Bubble) -> None:
        """内联编辑「确定」：更新消息与视图，退出编辑态并发射信号。"""
        text = bubble.edit_text()
        bubble.cancel_edit()
        self._messages[index]["content"] = text
        bubble.view.set_markdown(text)
        self._refresh_stats(index)
        self.messageEdited.emit(index, text)

    def _delete_message(self, index: int) -> None:
        """移除指定消息（行布局逐条目清理，思路同 ``clear_messages``
        的单行版），随后发射 ``messageDeleted``（删除前索引）。

        删除流式中的消息不作特殊处理，计时随状态一并移除；调用方
        若持有进行中的流式任务需自行停止。
        """
        row = self._rows.pop(index)
        while row.count():
            item = row.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.deleteLater()
        self._list_lay.removeItem(row)
        self._bubbles.pop(index)
        self._messages.pop(index)
        self._stats.pop(index)
        if not self._messages:
            self._show_placeholder()
        self.messageDeleted.emit(index)

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
